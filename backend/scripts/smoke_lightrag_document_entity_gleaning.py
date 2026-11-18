#!/usr/bin/env python3
"""在同一真实论文窗口上对照文档实体单轮与自适应 gleaning。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import json_repair

from defense_document_entity_contract import (
    DocumentEntityBlock,
    DocumentEntityOptions,
    DocumentEntityRequest,
    DocumentEntityType,
)
from platform_core.knowledge.graphs.defense_ontology import DEFENSE_ONTOLOGY_V1
from platform_core.knowledge.graphs.lightrag_document_entity_enhancement import (
    DOCUMENT_ENTITY_PROMPT_VERSION,
    LightRAGDocumentEntityEnhancer,
)
from platform_core.knowledge.parser.docling_pdf import DoclingPdfParser

DOMAIN_TERMS = ("MIMO", "雷达", "波形", "阵列", "射频", "测向")


class LocalOpenAIJSONClient:
    """只向回环 OpenAI-compatible 服务发送论文窗口。"""

    def __init__(self, *, base_url: str, model_id: str, timeout_seconds: float, max_output_tokens: int):
        _require_local_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.calls: list[dict[str, Any]] = []
        self.client = httpx.AsyncClient(timeout=timeout_seconds, trust_env=False)

    async def complete_json(self, prompt: str, **_: Any) -> dict[str, Any]:
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
        if not isinstance(parsed, dict) or "entities" not in parsed:
            raise ValueError("本地模型未返回 entities JSON 字段")
        usage = payload.get("usage") or {}
        self.calls.append(
            {
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
    """执行严格同源的单轮与自适应双轮对照并保存审计报告。"""
    source = Path(args.pdf).resolve()
    parser = DoclingPdfParser()
    parsed = parser.process_file_result(str(source))
    blocks = _select_blocks(
        parsed,
        page=args.page,
        max_blocks=args.max_blocks,
        max_chars=args.max_chars,
    )
    source_sha256 = _sha256_file(source)
    input_hash = hashlib.sha256(
        json.dumps(
            [item.model_dump(mode="json") for item in blocks],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    request = DocumentEntityRequest(
        request_id=f"{source.stem}-p{args.page}-document-entity-v4",
        stage_revision="document-entity-enhancement-v4",
        input_hash=input_hash,
        pipeline_revision="hybrid-v2-lightrag-experiment",
        model_version=args.model_id,
        ontology_version=DEFENSE_ONTOLOGY_V1.version,
        document_id=source_sha256,
        document_version=1,
        blocks=blocks,
        known_entities=[],
        entity_types=[
            DocumentEntityType(code=item.code, name_zh=item.name_zh, description=item.description)
            for item in DEFENSE_ONTOLOGY_V1.entity_types
        ],
        options=DocumentEntityOptions(
            max_blocks=args.max_blocks,
            max_chars=args.max_chars,
            max_candidates=args.max_candidates,
        ),
    )

    baseline, baseline_calls = await _run(request, args, max_gleanings=0)
    adaptive, adaptive_calls = await _run(request, args, max_gleanings=1)
    baseline_keys = {_candidate_key(item) for item in baseline.entities}
    adaptive_keys = {_candidate_key(item) for item in adaptive.entities}
    block_by_id = {block.block_id: block for block in blocks}
    report = {
        "contract": "defense-kg-lightrag-document-entity-gleaning-ablation-v1",
        "evaluation_scope": "real_local_pdf_model_assisted_same_source_ablation",
        "quality_claim_allowed": False,
        "human_gold": False,
        "created_at_unix": int(time.time()),
        "source": {
            "filename": source.name,
            "sha256": source_sha256,
            "page": args.page,
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
        },
        "input": {
            "input_hash": input_hash,
            "block_count": len(blocks),
            "source_char_count": sum(len(block.text) for block in blocks),
            "contains_source_text": False,
        },
        "prompt_version": DOCUMENT_ENTITY_PROMPT_VERSION,
        "runtime_audit": {
            "external_data_transfer": False,
            "llm_transport": "direct loopback HTTP with trust_env=False",
            "llm_host": urlparse(args.base_url).hostname,
        },
        "baseline": {
            "entities": [item.model_dump(mode="json") for item in baseline.entities],
            "normalization": baseline.normalization,
            "runtime": baseline.runtime.model_dump(mode="json"),
            "calls": baseline_calls,
        },
        "adaptive": {
            "entities": [item.model_dump(mode="json") for item in adaptive.entities],
            "normalization": adaptive.normalization,
            "runtime": adaptive.runtime.model_dump(mode="json"),
            "calls": adaptive_calls,
        },
        "delta": {
            "baseline_candidate_count": len(baseline.entities),
            "adaptive_candidate_count": len(adaptive.entities),
            "new_candidate_count": len(adaptive_keys - baseline_keys),
            "missing_baseline_candidate_count": len(baseline_keys - adaptive_keys),
            "new_candidates": [
                item.model_dump(mode="json") for item in adaptive.entities if _candidate_key(item) not in baseline_keys
            ],
        },
        "validation": {
            "baseline_spans_match_original": _spans_match(baseline.entities, block_by_id),
            "adaptive_spans_match_original": _spans_match(adaptive.entities, block_by_id),
            "all_candidates_pending": True,
            "postgres_written": False,
            "neo4j_written": False,
            "milvus_written": False,
            "stable_flow_changed": False,
        },
        "limitations": [
            "这是本地模型辅助同源对照，不是人工 Gold，不能证明 Precision、Recall 或 F1 提升。",
            "新增候选只表示召回代理增量，仍需 canonical 对齐与人工审核。",
            "自适应 gleaning 仅在 experiment 通道可启用，默认 LightRAG 主流程不变。",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


async def _run(
    request: DocumentEntityRequest,
    args: argparse.Namespace,
    *,
    max_gleanings: int,
) -> tuple[Any, list[dict[str, Any]]]:
    client = LocalOpenAIJSONClient(
        base_url=args.base_url,
        model_id=args.model_id,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    )
    enhancer = LightRAGDocumentEntityEnhancer(
        {
            "model_spec": args.model_id,
            "min_confidence": args.min_confidence,
            "max_output_tokens": args.max_output_tokens,
            "timeout_seconds": args.timeout_seconds,
            "max_gleanings": max_gleanings,
            "gleaning_min_source_chars": args.gleaning_min_source_chars,
            "gleaning_min_candidates": args.gleaning_min_candidates,
        },
        llm=client,
    )
    try:
        return await enhancer.enhance(request), client.calls
    finally:
        await enhancer.aclose()


def _select_blocks(parsed: Any, *, page: int, max_blocks: int, max_chars: int) -> list[DocumentEntityBlock]:
    """从目标页技术正文起点选取固定预算的非标点布局块。"""
    candidates = []
    started = False
    selected_chars = 0
    for index, item in enumerate(parsed.blocks):
        if item.source_metadata.get("position_kind") != "docling_pdf_layout_block" or item.page_number != page:
            continue
        text = parsed.markdown[item.start_char : item.end_char]
        if not started and any(term.casefold() in text.casefold() for term in DOMAIN_TERMS):
            started = True
        meaningful = "".join(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text))
        if not started or len(meaningful) < 2:
            continue
        if candidates and selected_chars + len(text) > max_chars:
            break
        candidates.append(
            DocumentEntityBlock(
                block_id=f"p{page}-b{index}",
                text=text,
                block_index=len(candidates),
                page=page,
                base_char_offset=item.start_char,
                heading_path=list(item.heading_path or []),
            )
        )
        selected_chars += len(text)
        if len(candidates) >= max_blocks:
            break
    if not candidates:
        raise ValueError("目标页没有可用军事技术正文 Block")
    return candidates


def _candidate_key(item: Any) -> tuple[str, int, int, str]:
    return item.block_id, item.start, item.end, item.type


def _spans_match(entities: list[Any], block_by_id: dict[str, DocumentEntityBlock]) -> bool:
    return all(block_by_id[item.block_id].text[item.start : item.end] == item.text for item in entities)


def _require_local_url(value: str) -> None:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("base_url 必须是有效 HTTP URL")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        if host != "localhost":
            raise ValueError("真实论文烟测只允许回环 LLM") from exc
    else:
        if not address.is_loopback:
            raise ValueError("真实论文烟测只允许回环 LLM")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--page", type=int, default=2)
    parser.add_argument("--max-blocks", type=int, default=48)
    parser.add_argument("--max-chars", type=int, default=12_000)
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--gleaning-min-source-chars", type=int, default=512)
    parser.add_argument("--gleaning-min-candidates", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


if __name__ == "__main__":
    result = asyncio.run(smoke(_parse_args()))
    print(json.dumps({"output": "written", "delta": result["delta"]}, ensure_ascii=False))
