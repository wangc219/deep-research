"""Chunk 级缓存隔离、批量信息抽取与失败降级编排。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from platform_core.knowledge.graphs.acceptance_policy import apply_acceptance_policy
from platform_core.knowledge.graphs.extraction_cache import (
    attach_extraction_cache_metadata,
    build_extraction_cache_manifest,
    extraction_cache_key,
    extraction_result_matches_cache,
)
from platform_core.knowledge.graphs.extractors.base import (
    GraphExtractionInput,
    GraphExtractor,
    normalize_extraction_result,
    verify_extraction_evidence,
)
from platform_core.utils import logger


@dataclass(frozen=True, slots=True)
class _PendingChunkExtraction:
    """一个已完成缓存判定、等待模型推理的 Chunk。"""

    chunk: Any
    metadata: dict[str, Any]
    cache_manifest: dict[str, Any]


def is_retryable_extraction_error(error: Exception) -> bool:
    """仅重试网络中断、超时、限流和供应商暂时故障。"""
    import httpx
    from openai import APIConnectionError

    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError | ConnectionError | httpx.TransportError | APIConnectionError):
            return True
        status = getattr(current, "status_code", None) or getattr(
            getattr(current, "response", None), "status_code", None
        )
        if isinstance(status, int) and (status in {408, 429} or status >= 500):
            return True
        current = current.__cause__ or current.__context__
    return False


class ChunkExtractionBatchCoordinator:
    """在不共享 Chunk 状态的前提下聚合模型请求。"""

    def __init__(
        self,
        *,
        chunk_repo: Any,
        context_loader: Callable[[Any, GraphExtractor], Awaitable[list[dict[str, Any]]]],
        max_attempts: int,
        retry_delays_seconds: Sequence[float],
    ):
        self.chunk_repo = chunk_repo
        self.context_loader = context_loader
        self.max_attempts = max_attempts
        self.retry_delays_seconds = tuple(retry_delays_seconds)

    async def get_result(self, kb_id: str, chunk: Any, extractor: GraphExtractor) -> dict[str, Any]:
        """获取单个 Chunk 结果，保持既有调用方兼容。"""
        results = await self.get_results(kb_id, [chunk], extractor)
        result = results[0]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_results(
        self,
        kb_id: str,
        chunks: list[Any],
        extractor: GraphExtractor,
    ) -> list[dict[str, Any] | Exception]:
        """独立判定缓存，只批量发送未命中的 Chunk，并隔离单块失败。"""
        if not chunks:
            return []

        results: list[dict[str, Any] | Exception | None] = [None] * len(chunks)
        pending: list[tuple[int, _PendingChunkExtraction]] = []
        for index, chunk in enumerate(chunks):
            cached, pending_item = await self._prepare(kb_id, chunk, extractor)
            if cached is not None:
                results[index] = cached
            elif pending_item is not None:
                pending.append((index, pending_item))

        if pending:
            await self._extract_pending(kb_id, pending, extractor, results)

        unresolved = [index for index, result in enumerate(results) if result is None]
        if unresolved:
            raise RuntimeError(f"Chunk 图谱抽取结果缺失: {unresolved}")
        return [result for result in results if result is not None]

    async def _extract_pending(
        self,
        kb_id: str,
        pending: list[tuple[int, _PendingChunkExtraction]],
        extractor: GraphExtractor,
        results: list[dict[str, Any] | Exception | None],
    ) -> None:
        inputs = [
            GraphExtractionInput(
                text=item.chunk.content,
                chunk_metadata=item.metadata,
            )
            for _, item in pending
        ]
        if len(inputs) == 1:
            batch_outputs: list[dict[str, Any]] | None = None
        else:
            try:
                batch_outputs = await extractor.extract_batch(inputs)
                if len(batch_outputs) != len(inputs):
                    raise ValueError("批量图谱抽取返回数量与请求不一致")
            except Exception as exc:
                logger.warning(f"批量图谱抽取降级为逐 Chunk 重试 kb_id={kb_id} batch_count={len(inputs)}: {exc}")
                batch_outputs = None

        if batch_outputs is None:
            await self._fallback_pending(
                kb_id,
                pending,
                extractor,
                results,
                start_attempt=1 if len(inputs) == 1 else 2,
            )
            return

        retry_items: list[tuple[int, _PendingChunkExtraction]] = []
        for (result_index, item), output in zip(pending, batch_outputs, strict=True):
            try:
                results[result_index] = await self._persist(item, output, extractor, attempt=1)
            except Exception as exc:
                logger.warning(f"批量结果单块校验失败，降级重试 kb_id={kb_id} chunk_id={item.chunk.chunk_id}: {exc}")
                retry_items.append((result_index, item))
        await self._fallback_pending(kb_id, retry_items, extractor, results, start_attempt=2)

    async def _fallback_pending(
        self,
        kb_id: str,
        pending: list[tuple[int, _PendingChunkExtraction]],
        extractor: GraphExtractor,
        results: list[dict[str, Any] | Exception | None],
        *,
        start_attempt: int,
    ) -> None:
        for result_index, item in pending:
            try:
                results[result_index] = await self._extract_one(
                    kb_id,
                    item,
                    extractor,
                    start_attempt=start_attempt,
                )
            except Exception as exc:
                results[result_index] = exc

    async def _prepare(
        self,
        kb_id: str,
        chunk: Any,
        extractor: GraphExtractor,
    ) -> tuple[dict[str, Any] | None, _PendingChunkExtraction | None]:
        extractor_type = extractor.extractor_type
        extractor_options = getattr(extractor, "options", None)
        if (
            chunk.extraction_result
            and extractor_type == "llm"
            and not _has_extraction_cache_metadata(chunk.extraction_result)
        ):
            return self._govern(chunk, chunk.extraction_result, extractor), None

        context_chunks = await self.context_loader(chunk, extractor)
        cache_manifest = build_extraction_cache_manifest(
            chunk=chunk,
            extractor_type=extractor_type,
            extractor_options=extractor_options,
            context_chunks=context_chunks,
        )
        expected_cache_key = extraction_cache_key(cache_manifest)
        if chunk.extraction_result and extraction_result_matches_cache(chunk.extraction_result, expected_cache_key):
            return self._govern(chunk, chunk.extraction_result, extractor), None

        details = getattr(chunk, "graph_extraction_details", None) or {}
        if details.get("status") == "failed":
            await self.chunk_repo.mark_graph_extraction_pending(chunk.chunk_id)

        metadata = {
            "kb_id": kb_id,
            "chunk_id": chunk.chunk_id,
            "file_id": chunk.file_id,
            "chunk_index": chunk.chunk_index,
            "page": getattr(chunk, "page_number", None),
            "heading_path": getattr(chunk, "heading_path", None) or [],
            "bbox": getattr(chunk, "bbox", None),
            "parser_name": getattr(chunk, "parser_name", None),
            "parser_version": getattr(chunk, "parser_version", None),
            "block_type": getattr(chunk, "block_type", None),
            "document_version": int(getattr(chunk, "document_version", None) or 1),
            "start_char_pos": getattr(chunk, "start_char_pos", None),
            "context_chunks": context_chunks,
        }
        return None, _PendingChunkExtraction(chunk=chunk, metadata=metadata, cache_manifest=cache_manifest)

    async def _extract_one(
        self,
        kb_id: str,
        pending: _PendingChunkExtraction,
        extractor: GraphExtractor,
        *,
        start_attempt: int,
    ) -> dict[str, Any]:
        chunk = pending.chunk
        for attempt in range(start_attempt, self.max_attempts + 1):
            try:
                output = await extractor.extract(chunk.content, chunk_metadata=pending.metadata)
                return await self._persist(pending, output, extractor, attempt=attempt)
            except Exception as exc:
                if attempt >= self.max_attempts or not is_retryable_extraction_error(exc):
                    await self.chunk_repo.mark_graph_extraction_failed(chunk.chunk_id, attempt, str(exc))
                    raise
                delay = self.retry_delays_seconds[attempt - 1] * random.uniform(1, 1.25)
                logger.warning(
                    f"Chunk 图谱抽取重试 kb_id={kb_id} chunk_id={chunk.chunk_id} "
                    f"attempt={attempt}/{self.max_attempts} delay={delay:.1f}s: {exc}"
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"Chunk 图谱抽取未返回结果: {chunk.chunk_id}")

    async def _persist(
        self,
        pending: _PendingChunkExtraction,
        output: dict[str, Any],
        extractor: GraphExtractor,
        *,
        attempt: int,
    ) -> dict[str, Any]:
        normalized_result = self._govern(pending.chunk, output, extractor)
        attach_extraction_cache_metadata(normalized_result, pending.cache_manifest)
        await self.chunk_repo.update_extraction_result(
            pending.chunk.chunk_id,
            normalized_result,
            attempt,
        )
        return normalized_result

    @staticmethod
    def _govern(chunk: Any, output: dict[str, Any], extractor: GraphExtractor) -> dict[str, Any]:
        extractor_options = getattr(extractor, "options", None)
        normalized_result = normalize_extraction_result(
            output,
            extractor.extractor_type,
            extractor_options,
        )
        normalized_result = verify_extraction_evidence(normalized_result, chunk.content)
        return apply_acceptance_policy(normalized_result, chunk.content, extractor_options)


def _has_extraction_cache_metadata(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    metadata = result.get("metadata")
    return isinstance(metadata, dict) and "extraction_cache" in metadata
