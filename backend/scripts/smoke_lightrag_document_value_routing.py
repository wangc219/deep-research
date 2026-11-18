"""用本地真实知识库预览 LightRAG 军事技术价值路由，不修改权威数据。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from platform_core.config.options import system_options
from platform_core.knowledge.graphs.document_knowledge_audit import triage_document
from platform_core.knowledge.graphs.lightrag_document_value_routing import LightRAGDocumentValueRouter
from platform_core.repositories.knowledge_graph_document_audit_repository import (
    KnowledgeGraphDocumentAuditRepository,
)
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import KnowledgeSourceDocument


async def run(*, kb_id: str, limit: int) -> dict[str, Any]:
    """对已解析真实论文执行只读价值判别，并保留可回切 Span。"""

    options = await system_options.get()
    model_spec = str(options.get("default_model") or "").strip()
    if not model_spec:
        raise ValueError("项目模型设置尚未配置 default_model")
    provider_id = model_spec.partition(":")[0].casefold()
    if provider_id.startswith("local"):
        raise ValueError("价值路由真实验证禁止使用本地 LLM")

    async with pg_manager.get_async_session_context() as session:
        document_ids = list(
            await session.scalars(
                select(KnowledgeSourceDocument.document_id)
                .where(KnowledgeSourceDocument.kb_id == kb_id)
                .order_by(KnowledgeSourceDocument.created_at.asc())
                .limit(limit)
            )
        )
    repository = KnowledgeGraphDocumentAuditRepository()
    documents = await repository.load_documents(
        kb_id=kb_id,
        document_ids=[str(item) for item in document_ids],
        include_graph=False,
    )
    router = LightRAGDocumentValueRouter(
        {
            "model_spec": model_spec,
            "max_chars": 12_000,
            "max_output_tokens": 1200,
            "min_confidence": 0.8,
            "enable_thinking": False,
            "max_truncation_retries": 0,
        }
    )
    results = []
    try:
        for document in documents:
            triage = triage_document(document)
            if not triage.get("deep_extraction_recommended"):
                assessment = {
                    "status": "skipped_prefilter",
                    "focused_reextraction_recommended": False,
                    "reason": "规则初筛未发现军事或前沿技术迁移信号",
                }
            else:
                assessment = await router.assess(document, triage)
            results.append(
                {
                    "document_id": document["document_id"],
                    "title": document["title"],
                    "triage_code": triage["military_value_code"],
                    "triage_input_hash": triage["input_hash"],
                    "assessment": assessment,
                }
            )
    finally:
        await router.aclose()

    report = {
        "contract": "lightrag-document-value-routing-real-preview-v1",
        "scope": "local_read_only_preview",
        "kb_id": kb_id,
        "project_model": model_spec,
        "local_llm_used": False,
        "document_count": len(results),
        "focused_reextraction_count": sum(
            1 for item in results if item["assessment"].get("focused_reextraction_recommended") is True
        ),
        "results": results,
        "production_changed": False,
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit 必须在 1 到 50 之间")
    return args


def main() -> int:
    args = parse_args()
    report = asyncio.run(run(kb_id=args.kb_id, limit=args.limit))
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
