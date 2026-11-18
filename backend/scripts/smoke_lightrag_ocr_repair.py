#!/usr/bin/env python3
"""使用本地 OpenAI-compatible 模型验证 OCR repaired-view 抽取，不在报告保存原文。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import json_repair
from sqlalchemy import select

from platform_core.knowledge.graphs.extractors.lightrag_enhancement import (
    LightRAGQualityEnhancer,
    detect_ocr_damage,
)
from platform_core.knowledge.graphs.lightrag_contract import LIGHTRAG_ENHANCEMENT_REVISION
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import KnowledgeChunk


class LocalOpenAIJSONClient:
    """仅供本地烟测使用的严格 JSON 客户端。"""

    def __init__(self, *, base_url: str, model_id: str, timeout_seconds: float, max_output_tokens: int):
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.calls: list[dict[str, Any]] = []
        self.client = httpx.AsyncClient(timeout=timeout_seconds, trust_env=False)

    def validate_options(self) -> None:
        _require_local_url(self.base_url)

    async def complete_json(
        self,
        prompt: str,
        *,
        chunk_metadata: dict[str, Any] | None = None,
        required_keys: tuple[str, ...] = ("relations", "entities"),
    ) -> dict[str, Any]:
        started = time.monotonic()
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": self.max_output_tokens,
                "stream": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else None) or ""
        parsed = json_repair.loads(content)
        if not isinstance(parsed, dict) or not any(key in parsed for key in required_keys):
            raise ValueError("本地模型未返回要求的 JSON 字段")
        usage = payload.get("usage") or {}
        self.calls.append(
            {
                "chunk_id_sha256": _sha256_text(str((chunk_metadata or {}).get("chunk_id") or "")),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "finish_reason": str(choices[0].get("finish_reason") or "") if choices else "",
            }
        )
        return parsed

    async def aclose(self) -> None:
        await self.client.aclose()


async def smoke(args: argparse.Namespace) -> dict[str, Any]:
    """读取一个真实受损 Block，运行本地模型增强并生成脱敏报告。"""
    _require_local_url(args.base_url)
    pg_manager.initialize()
    client = LocalOpenAIJSONClient(
        base_url=args.base_url,
        model_id=args.model_id,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    )
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": f"local-smoke:{args.model_id}",
            "max_gleanings": 0,
            "entity_review_mode": "off",
            "max_output_tokens": args.max_output_tokens,
            "timeout_seconds": args.timeout_seconds,
            "strict": True,
            "ocr_repair_extraction": {
                "enabled": True,
                "min_confidence": args.min_confidence,
                "max_proposals": args.max_proposals,
            },
        },
        llm=client,
    )
    try:
        chunk = await _load_damaged_chunk(args.kb_id)
        text = str(chunk.content or "")
        damage = detect_ocr_damage(text)
        result = await enhancer.enhance_initial(
            text,
            {"entities": [], "relations": [], "metadata": {}},
            chunk_metadata={
                "file_id": str(chunk.file_id),
                "chunk_id": str(chunk.chunk_id),
                "chunk_index": int(chunk.chunk_index),
                "page_number": chunk.page_number,
                "heading_path": list(chunk.heading_path or []),
            },
        )
        enhancement = (result.get("metadata") or {}).get("llm_enhancement") or {}
        repair = enhancement.get("ocr_repair_extraction") or {}
        report = {
            "contract": "defense-kg-lightrag-ocr-repair-smoke-v1",
            "evaluation_scope": "real_pilot_block_local_model_structural_smoke",
            "quality_claim_allowed": False,
            "created_at_unix": int(time.time()),
            "knowledge_base_id": args.kb_id,
            "input": {
                "document_id_sha256": _sha256_text(str(chunk.file_id)),
                "block_id_sha256": _sha256_text(str(chunk.chunk_id)),
                "text_sha256": _sha256_text(text),
                "source_char_count": len(text),
                "ocr_damage_count": len(damage),
                "contains_source_text": False,
            },
            "runtime": {
                "transport": "OpenAI-compatible loopback HTTP",
                "base_url_host": urlparse(args.base_url).hostname,
                "model_id": args.model_id,
                "external_data_transfer": False,
                "calls": client.calls,
            },
            "pipeline": {
                "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                "initial_status": enhancement.get("initial_status"),
                "ocr_repair_extraction": repair,
                "entity_count": len(result.get("entities") or []),
                "relation_count": len(result.get("relations") or []),
                "all_entity_spans_match_original": all(
                    text[item["start"] : item["end"]] == item["text"] for item in result.get("entities") or []
                ),
                "all_relation_spans_reference_original": all(
                    0 <= span["start"] < span["end"] <= len(text)
                    for relation in result.get("relations") or []
                    for span in relation.get("evidence_spans") or []
                ),
                "repair_dependent_authority_eligible": False,
            },
            "limitations": [
                "单 Block 本地模型烟测只证明 repaired-view 调用、Span 回切和隔离门禁可运行。",
                "缺少独立人工 Gold，不证明实体、关系 Precision/Recall/F1 提升。",
                "repair_dependent_candidate 不进入复核候选或 PostgreSQL 权威图谱。",
            ],
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        await enhancer.aclose()
        await pg_manager.close()


async def _load_damaged_chunk(kb_id: str) -> KnowledgeChunk:
    async with pg_manager.get_async_session_context() as session:
        chunks = list(
            await session.scalars(
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.kb_id == kb_id,
                    KnowledgeChunk.content.is_not(None),
                    KnowledgeChunk.content != "",
                    KnowledgeChunk.graph_excluded.is_(False),
                )
                .order_by(KnowledgeChunk.chunk_id)
            )
        )
    for chunk in chunks:
        if detect_ocr_damage(str(chunk.content or "")):
            return chunk
    raise ValueError(f"知识库 {kb_id} 没有可用于 OCR repaired-view 烟测的损伤 Block")


def _require_local_url(value: str) -> None:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("base_url 必须是合法 HTTP(S) URL")
    if host in {"localhost", "host.docker.internal"} or host.endswith(".localhost"):
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise PermissionError("OCR repaired-view 真实论文烟测只允许连接本机回环模型")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--max-proposals", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1.0 <= args.timeout_seconds <= 600.0:
        parser.error("--timeout-seconds 必须在 1 到 600 之间")
    if not 256 <= args.max_output_tokens <= 32768:
        parser.error("--max-output-tokens 必须在 256 到 32768 之间")
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("--min-confidence 必须在 0 到 1 之间")
    if not 1 <= args.max_proposals <= 64:
        parser.error("--max-proposals 必须在 1 到 64 之间")
    return args


def main() -> int:
    report = asyncio.run(smoke(parse_args()))
    print(
        json.dumps(
            {
                "contract": report["contract"],
                "quality_claim_allowed": report["quality_claim_allowed"],
                "input": report["input"],
                "pipeline": report["pipeline"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
