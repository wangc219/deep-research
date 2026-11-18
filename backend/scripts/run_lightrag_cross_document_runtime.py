#!/usr/bin/env python3
"""在现有本地知识库上执行一次可审计的 LightRAG 跨文档关系增强。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.graphs.lightrag_cross_document_relation_enhancement import (
    CrossDocumentRelationOptions,
    LightRAGCrossDocumentRelationEnhancer,
    build_cross_document_relation_request,
)
from platform_core.repositories.knowledge_graph_document_enhancement_repository import (
    KnowledgeGraphDocumentEnhancementRepository,
)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    """读取权威 Block/mention，调用项目模型并按待审口径写入候选。"""
    repository = KnowledgeGraphDocumentEnhancementRepository()
    documents = await repository.load_documents(
        kb_id=args.kb_id,
        document_ids=args.document_id,
        accepted_mentions_only=args.review_scope == "accepted_only",
    )
    options = CrossDocumentRelationOptions(
        min_document_support=args.min_document_support,
        max_pairs=args.max_pairs,
        max_documents_per_pair=args.max_documents_per_pair,
        max_blocks=args.max_blocks,
        max_chars=args.max_chars,
        max_relations=args.max_relations,
        min_confidence=args.min_confidence,
        max_entities_per_document=args.max_entities_per_document,
        max_pairs_per_document=args.max_pairs_per_document,
        min_entity_confidence=args.min_entity_confidence,
    )
    request = build_cross_document_relation_request(
        request_id=uuid.uuid4().hex,
        kb_id=args.kb_id,
        documents=documents,
        pipeline_revision=args.pipeline_revision,
        ontology_version=args.ontology_version,
        model_version=args.model_spec,
        options=options,
        ontology_definition=ontology_payload(),
    )
    started = time.monotonic()
    response = None
    persisted = 0
    if request is not None:
        enhancer = LightRAGCrossDocumentRelationEnhancer(
            {
                "model_spec": args.model_spec,
                "timeout_seconds": args.timeout_seconds,
                "max_output_tokens": args.max_output_tokens,
                "max_repair_attempts": args.max_repair_attempts,
                "enable_thinking": False,
                "max_truncation_retries": 0,
            }
        )
        try:
            response = await enhancer.enhance(request)
        finally:
            await enhancer.aclose()
        if args.persist and response.relations:
            persisted = await repository.persist_cross_document_relations(
                kb_id=args.kb_id,
                documents=documents,
                relations=[item.model_dump(mode="json") for item in response.relations],
                model_version=args.model_spec,
                ontology_version=args.ontology_version,
                pipeline_revision=args.pipeline_revision,
                review_scope=args.review_scope,
            )

    report = {
        "contract": "defense-lightrag-cross-document-runtime-v1",
        "scope": "local_development_only",
        "kb_id": args.kb_id,
        "document_ids": list(args.document_id),
        "document_count": len(documents),
        "model_spec": args.model_spec,
        "local_llm_used": False,
        "review_scope": args.review_scope,
        "pipeline_revision": args.pipeline_revision,
        "ontology_version": args.ontology_version,
        "candidate_pair_count": len(request.candidate_pairs) if request is not None else 0,
        "candidate_pairs": [item.model_dump(mode="json") for item in request.candidate_pairs]
        if request is not None
        else [],
        "source_block_sha256": [hashlib.sha256(block.text.encode("utf-8")).hexdigest() for block in request.blocks]
        if request is not None
        else [],
        "model_relation_count": len(response.relations) if response is not None else 0,
        "relations": [item.model_dump(mode="json") for item in response.relations] if response is not None else [],
        "persist_requested": bool(args.persist),
        "persisted_relation_count": persisted,
        "claim_level": "Inference",
        "review_status": "pending",
        "expert_review_required": True,
        "duration_seconds": round(time.monotonic() - started, 2),
        "quality_claim_allowed": False,
        "limitations": [
            "输入实体和关系来自 weak supervision，不能冒充人工 Gold。",
            "模型关系保持 pending Inference，只有人工复核后才能进入权威接受态。",
            "原文证据只保存 Block 字符 Span，报告不复制来源全文。",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--document-id", action="append", required=True)
    parser.add_argument("--model-spec", required=True)
    parser.add_argument("--pipeline-revision", required=True)
    parser.add_argument("--ontology-version", default="defense-kg-1.0")
    parser.add_argument(
        "--review-scope",
        choices=("accepted_only", "pending_candidates"),
        default="pending_candidates",
    )
    parser.add_argument("--min-document-support", type=int, default=2)
    parser.add_argument("--max-pairs", type=int, default=24)
    parser.add_argument("--max-documents-per-pair", type=int, default=3)
    parser.add_argument("--max-blocks", type=int, default=64)
    parser.add_argument("--max-chars", type=int, default=30_000)
    parser.add_argument("--max-relations", type=int, default=24)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--max-entities-per-document", type=int, default=96)
    parser.add_argument("--max-pairs-per-document", type=int, default=512)
    parser.add_argument("--min-entity-confidence", type=float, default=0.3)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--max-repair-attempts", type=int, default=1)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
