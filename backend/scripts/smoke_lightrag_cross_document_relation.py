#!/usr/bin/env python3
"""用本地 LLM 与临时 PostgreSQL schema 验证跨文档多源关系增强。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import json_repair
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.knowledge.graphs.lightrag_cross_document_relation_enhancement import (
    CrossDocumentRelationOptions,
    LightRAGCrossDocumentRelationEnhancer,
    build_cross_document_relation_request,
)
from platform_core.repositories import knowledge_graph_document_enhancement_repository as document_repository_module
from platform_core.repositories import knowledge_graph_repository as graph_repository_module
from platform_core.repositories.knowledge_graph_document_enhancement_repository import (
    KnowledgeGraphDocumentEnhancementRepository,
)
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphTripleMention,
    KnowledgeSourceDocument,
)


class LocalOpenAIJSONClient:
    """只连接本机回环 OpenAI-compatible 服务的 JSON 客户端。"""

    def __init__(self, *, base_url: str, model_id: str, timeout_seconds: float, max_output_tokens: int):
        _require_local_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.calls: list[dict[str, Any]] = []
        self.last_parsed: dict[str, Any] | None = None
        self.client = httpx.AsyncClient(timeout=timeout_seconds, trust_env=False)

    async def complete_json(self, prompt: str, *, required_keys: tuple[str, ...]) -> dict[str, Any]:
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
        if not isinstance(parsed, dict) or not all(key in parsed for key in required_keys):
            raise ValueError("本地模型未返回要求的 JSON 字段")
        self.last_parsed = parsed
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
    """在临时 schema 中验证 accepted-only 读取、证据门禁和条件写入。"""
    _require_local_url(args.base_url)
    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("缺少 POSTGRES_URL")

    schema = f"smoke_cross_doc_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(postgres_url, pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        postgres_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
    manager._initialized = True
    original_document_manager = document_repository_module.pg_manager
    original_graph_manager = graph_repository_module.pg_manager
    document_repository_module.pg_manager = manager
    graph_repository_module.pg_manager = manager
    client = LocalOpenAIJSONClient(
        base_url=args.base_url,
        model_id=args.model_id,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer(
        {
            "model_spec": f"local-smoke:{args.model_id}",
            "max_output_tokens": args.max_output_tokens,
            "timeout_seconds": args.timeout_seconds,
        },
        llm=client,
    )
    report: dict[str, Any] | None = None
    schema_dropped = False
    try:
        await manager.create_knowledge_tables()
        await _seed_database(manager)
        repository = KnowledgeGraphDocumentEnhancementRepository()
        documents = await repository.load_documents(
            kb_id="smoke-kb",
            document_ids=["doc-a", "doc-b"],
            accepted_mentions_only=True,
        )
        request = build_cross_document_relation_request(
            request_id=uuid.uuid4().hex,
            kb_id="smoke-kb",
            documents=documents,
            pipeline_revision="hybrid-v2-cross-document-smoke",
            ontology_version="defense-kg-1.0",
            model_version=f"local-smoke:{args.model_id}",
            options=CrossDocumentRelationOptions(min_confidence=args.min_confidence),
        )
        if request is None:
            raise RuntimeError("合成语义数据未形成跨文档候选")
        response = await enhancer.enhance(request)
        relation_payloads = [item.model_dump(mode="json") for item in response.relations]
        persisted = 0
        if relation_payloads:
            persisted = await repository.persist_cross_document_relations(
                kb_id="smoke-kb",
                documents=documents,
                relations=relation_payloads,
                model_version=f"local-smoke:{args.model_id}",
                ontology_version="defense-kg-1.0",
                pipeline_revision="hybrid-v2-cross-document-smoke",
            )
        async with manager.get_async_session_context() as session:
            mention = await session.scalar(select(KnowledgeGraphTripleMention))
            outbox = await session.scalar(select(KnowledgeGraphProjectionOutbox))
            mention_count = int(
                await session.scalar(select(func.count()).select_from(KnowledgeGraphTripleMention)) or 0
            )
            outbox_count = int(
                await session.scalar(select(func.count()).select_from(KnowledgeGraphProjectionOutbox)) or 0
            )
        evidence_spans = list(mention.evidence_spans or []) if mention is not None else []
        metadata = ((outbox.payload or {}).get("graph_payload") or {}).get("metadata") if outbox else {}
        report = {
            "contract": "defense-kg-lightrag-cross-document-smoke-v2",
            "evaluation_scope": "synthetic_semantics_real_local_llm_and_postgres",
            "quality_claim_allowed": False,
            "created_at_unix": int(time.time()),
            "runtime": {
                "transport": "OpenAI-compatible loopback HTTP",
                "base_url_host": urlparse(args.base_url).hostname,
                "model_id": args.model_id,
                "external_data_transfer": False,
                "calls": client.calls,
            },
            "input": {
                "document_count": len(documents),
                "candidate_pair_count": len(request.candidate_pairs),
                "source_sha256": [_sha256_text(block.text) for block in request.blocks],
                "contains_source_text": False,
            },
            "result": {
                "raw_last_model_relation_count": len((client.last_parsed or {}).get("relations") or []),
                "model_relation_count": len(response.relations),
                "evidence_normalized_by_platform_count": sum(
                    1 for item in response.relations if item.evidence_normalized_by_platform
                ),
                "persisted_relation_count": persisted,
                "triple_mention_count": mention_count,
                "outbox_count": outbox_count,
                "claim_level": mention.claim_level if mention is not None else None,
                "review_status": mention.review_status if mention is not None else None,
                "expert_review_required": mention.expert_review_required if mention is not None else None,
                "evidence_document_count": len({item["document_id"] for item in evidence_spans}),
                "all_evidence_spans_grounded": _all_evidence_grounded(evidence_spans, documents),
                "support_level": (metadata or {}).get("support_level"),
                "source_document_count": (metadata or {}).get("source_document_count"),
                "incomplete_evidence_rejected": bool(
                    (client.last_parsed or {}).get("relations") and not response.relations
                ),
                "safety_gate_passed": bool(
                    response.relations
                    or (
                        (client.last_parsed or {}).get("relations")
                        and persisted == 0
                        and mention_count == 0
                        and outbox_count == 0
                    )
                ),
            },
            "temporary_postgres_schema": {
                "created": True,
                "dropped": False,
                "schema_name_sha256": _sha256_text(schema),
            },
            "limitations": [
                "非敏感合成语义只证明真实本地 LLM、Span 门禁、PostgreSQL 与 Outbox 链路可运行。",
                "模型若未在每篇来源分别覆盖两端，零写入是预期安全结果，不代表召回质量达标。",
                "缺少独立人工 Gold，不证明跨文档关系 Precision、Recall 或 F1 提升。",
                "输出固定为 pending Inference，不能作为人工确认事实或正式验收结论。",
            ],
        }
    finally:
        await enhancer.aclose()
        document_repository_module.pg_manager = original_document_manager
        graph_repository_module.pg_manager = original_graph_manager
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        schema_dropped = True
        await admin_engine.dispose()

    if report is None:
        raise RuntimeError("跨文档烟测未生成报告")
    report["temporary_postgres_schema"]["dropped"] = schema_dropped
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


async def _seed_database(manager: PostgresManager) -> None:
    """写入两篇明确陈述同一关系的 accepted 合成语义文档。"""
    async with manager.get_async_session_context() as session:
        session.add(KnowledgeBase(kb_id="smoke-kb", name="smoke-kb", kb_type="milvus"))
        await session.flush()
        session.add_all(
            [
                KnowledgeFile(file_id="file-a", kb_id="smoke-kb", filename="synthetic-a.pdf"),
                KnowledgeFile(file_id="file-b", kb_id="smoke-kb", filename="synthetic-b.pdf"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                KnowledgeSourceDocument(
                    document_id="doc-a",
                    kb_id="smoke-kb",
                    file_id="file-a",
                    source_type="paper",
                    language="zh",
                    current_version=1,
                ),
                KnowledgeSourceDocument(
                    document_id="doc-b",
                    kb_id="smoke-kb",
                    file_id="file-b",
                    source_type="paper",
                    language="zh",
                    current_version=1,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                KnowledgeDocumentVersion(
                    document_id="doc-a",
                    version=1,
                    content_hash="synthetic-content-a",
                    input_hash="synthetic-input-a",
                ),
                KnowledgeDocumentVersion(
                    document_id="doc-b",
                    version=1,
                    content_hash="synthetic-content-b",
                    input_hash="synthetic-input-b",
                ),
            ]
        )
        session.add_all(
            [
                KnowledgeChunk(
                    chunk_id="block-a",
                    file_id="file-a",
                    kb_id="smoke-kb",
                    chunk_index=0,
                    content="氮化镓组件形成宽带感知能力。",
                    document_version=1,
                    page_number=1,
                ),
                KnowledgeChunk(
                    chunk_id="block-b",
                    file_id="file-b",
                    kb_id="smoke-kb",
                    chunk_index=0,
                    content="试验确认氮化镓组件形成宽带感知能力。",
                    document_version=1,
                    page_number=2,
                ),
            ]
        )
        session.add_all(
            [
                KnowledgeGraphEntity(
                    entity_id="component",
                    kb_id="smoke-kb",
                    normalized_name="氮化镓组件",
                    label="Component",
                    name="氮化镓组件",
                ),
                KnowledgeGraphEntity(
                    entity_id="capability",
                    kb_id="smoke-kb",
                    normalized_name="宽带感知能力",
                    label="Capability",
                    name="宽带感知能力",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                KnowledgeGraphEntityMention(
                    entity_id="component",
                    kb_id="smoke-kb",
                    file_id="file-a",
                    chunk_id="block-a",
                    mention_text="氮化镓组件",
                    start_char=0,
                    end_char=5,
                    confidence=1.0,
                    review_status="accepted",
                ),
                KnowledgeGraphEntityMention(
                    entity_id="capability",
                    kb_id="smoke-kb",
                    file_id="file-a",
                    chunk_id="block-a",
                    mention_text="宽带感知能力",
                    start_char=7,
                    end_char=13,
                    confidence=1.0,
                    review_status="accepted",
                ),
                KnowledgeGraphEntityMention(
                    entity_id="component",
                    kb_id="smoke-kb",
                    file_id="file-b",
                    chunk_id="block-b",
                    mention_text="氮化镓组件",
                    start_char=4,
                    end_char=9,
                    confidence=1.0,
                    review_status="accepted",
                ),
                KnowledgeGraphEntityMention(
                    entity_id="capability",
                    kb_id="smoke-kb",
                    file_id="file-b",
                    chunk_id="block-b",
                    mention_text="宽带感知能力",
                    start_char=11,
                    end_char=17,
                    confidence=1.0,
                    review_status="accepted",
                ),
            ]
        )


def _all_evidence_grounded(spans: list[dict[str, Any]], documents: list[dict[str, Any]]) -> bool:
    block_by_key = {
        (str(document["document_id"]), str(block["block_id"])): str(block["text"])
        for document in documents
        for block in document["blocks"]
    }
    return bool(spans) and all(
        (text := block_by_key.get((str(span["document_id"]), str(span["block_id"])))) is not None
        and 0 <= int(span["start"]) < int(span["end"]) <= len(text)
        for span in spans
    )


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
    raise PermissionError("跨文档真实模型烟测只允许连接本机回环模型")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1.0 <= args.timeout_seconds <= 600.0:
        parser.error("--timeout-seconds 必须在 1 到 600 之间")
    if not 256 <= args.max_output_tokens <= 32768:
        parser.error("--max-output-tokens 必须在 256 到 32768 之间")
    if not 0.0 <= args.min_confidence <= 1.0:
        parser.error("--min-confidence 必须在 0 到 1 之间")
    return args


def main() -> int:
    report = asyncio.run(smoke(parse_args()))
    print(
        json.dumps(
            {
                "contract": report["contract"],
                "evaluation_scope": report["evaluation_scope"],
                "quality_claim_allowed": report["quality_claim_allowed"],
                "result": report["result"],
                "temporary_postgres_schema": report["temporary_postgres_schema"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
