#!/usr/bin/env python3
"""在本地真实知识库验证双向多跳检索与创新预测。"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.services.equipment_model_adapter import default_chat_model_spec
from platform_core.services.knowledge_graph_innovation_service import KnowledgeGraphInnovationService
from platform_core.services.knowledge_graph_multihop_service import KnowledgeGraphMultiHopService
from platform_core.services.knowledge_graph_retrieval_adapter import retrieve_graph_mix_chunks


def _options(model_spec: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    query_enhancement = {"enabled": True, "model_spec": model_spec, "strict": False}
    path_reranking = {"enabled": True, "model_spec": model_spec, "strict": False}
    narrative = {"enabled": True, "model_spec": model_spec, "strict": False}
    return query_enhancement, path_reranking, narrative


def _multihop_summary(result: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    paths = result.get("paths") or []
    narrative = result.get("narrative") or {}
    allowed_path_ids = {str(path.get("path_id") or "") for path in paths}
    cited_path_ids = {str(item) for item in narrative.get("cited_path_ids") or []}
    citation_closed = bool(cited_path_ids) and cited_path_ids <= allowed_path_ids
    return {
        "feature_kind": result.get("feature_kind"),
        "discovery_mode": result.get("discovery_mode"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "path_count": len(paths),
        "entity_hit_count": (result.get("summary") or {}).get("entity_hit_count"),
        "triple_hit_count": (result.get("summary") or {}).get("triple_hit_count"),
        "chunk_hit_count": (result.get("summary") or {}).get("chunk_hit_count"),
        "keyword_entity_hit_count": (result.get("summary") or {}).get("keyword_entity_hit_count"),
        "retrieval_mode": (result.get("summary") or {}).get("retrieval_mode"),
        "query_planner_status": (result.get("summary") or {}).get("query_planner_status"),
        "path_reranker_status": (result.get("summary") or {}).get("path_reranker_status"),
        "narrative_status": (result.get("narrative_provenance") or {}).get("status"),
        "citation_closed": citation_closed,
        "citation_count": narrative.get("citation_count", 0),
        "executive_conclusion": narrative.get("executive_conclusion"),
        "technology_routes": [item.get("statement") for item in narrative.get("technology_routes") or []],
        "capability_implications": [
            item.get("statement") for item in narrative.get("capability_implications") or []
        ],
        "application_directions": [
            item.get("statement") for item in narrative.get("application_directions") or []
        ],
        "evidence_boundaries": [item.get("statement") for item in narrative.get("evidence_boundaries") or []],
    }


def _innovation_summary(result: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    hypotheses = result.get("hypotheses") or []
    return {
        "feature_kind": result.get("feature_kind"),
        "discovery_mode": result.get("discovery_mode"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "hypothesis_count": len(hypotheses),
        "all_hypotheses": bool(hypotheses)
        and all(str(item.get("claim_level") or "") == "Hypothesis" for item in hypotheses),
        "persisted": result.get("persisted"),
        "preview_mode": result.get("preview_mode"),
        "expert_review_required": result.get("expert_review_required"),
        "enhancement_status": (result.get("innovation_enhancement") or {}).get("status"),
        "retrieval_mode": (result.get("retrieval_summary") or {}).get("retrieval_mode"),
        "triple_hit_count": (result.get("retrieval_summary") or {}).get("triple_hit_count"),
        "keyword_entity_hit_count": (result.get("retrieval_summary") or {}).get(
            "keyword_entity_hit_count"
        ),
        "candidates": [
            {
                "source": (item.get("source") or {}).get("name"),
                "relation_type": item.get("relation_type"),
                "target": (item.get("target") or {}).get("name"),
                "mechanism_hypothesis": item.get("mechanism_hypothesis"),
                "validation_requirements": item.get("validation_requirements") or [],
                "uncertainties": item.get("uncertainties") or [],
                "query_anchor_match": item.get("query_anchor_match", False),
                "anchor_context_only": (item.get("evidence_path") or {}).get(
                    "anchor_context_only",
                    False,
                ),
            }
            for item in hypotheses[:5]
        ],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-id", default="kb_ighd8by766")
    parser.add_argument("--max-paths", type=int, default=5)
    parser.add_argument(
        "--case",
        action="append",
        choices=("multihop-top-down", "multihop-bottom-up", "innovation-top-down", "innovation-bottom-up"),
        help="只运行指定真实用例；可重复传入，默认运行全部。",
    )
    args = parser.parse_args()

    model_spec = await default_chat_model_spec(None)
    if not model_spec:
        raise RuntimeError("项目默认模型未配置")
    if model_spec.partition(":")[0].casefold() in {"local-lightrag", "local-lightrag-eval"}:
        raise RuntimeError("验证禁止使用本地 7B/MLX 模型")

    graph_service = MilvusGraphService(
        kb_id=args.kb_id,
        chunk_retriever=retrieve_graph_mix_chunks,
    )
    multihop_service = KnowledgeGraphMultiHopService(graph_service=graph_service)
    innovation_service = KnowledgeGraphInnovationService(graph_service=graph_service)
    query_enhancement, path_reranking, narrative = _options(model_spec)

    multihop_cases = (
        ("top_down", "在复杂空战环境下提升有人/无人机协同探测、任务规划与指挥控制能力"),
        ("bottom_up", "分布式态势感知与开放式体系架构技术可扩展哪些能力和应用场景"),
    )
    innovation_cases = (
        ("top_down", "面向通信受限和高风险任务，探索提升协同作战与可靠自主能力的技术组合"),
        ("bottom_up", "分布式自适应规划控制与载荷即插即用技术可以形成哪些新能力或应用链路"),
    )

    report: dict[str, Any] = {
        "kb_id": args.kb_id,
        "model_provider": model_spec.partition(":")[0],
        "multihop": [],
        "innovation": [],
    }
    selected_cases = set(args.case or ())
    selected_multihop = [
        item
        for item in multihop_cases
        if not selected_cases or f"multihop-{item[0].replace('_', '-')}" in selected_cases
    ]
    selected_innovation = [
        item
        for item in innovation_cases
        if not selected_cases or f"innovation-{item[0].replace('_', '-')}" in selected_cases
    ]
    for discovery_mode, query in selected_multihop:
        started = time.perf_counter()
        result = await multihop_service.discover(
            kb_id=args.kb_id,
            query=query,
            discovery_mode=discovery_mode,
            max_hops=5,
            max_paths=args.max_paths,
            include_combinations=False,
            retrieval_mode="mix",
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
            narrative=narrative,
        )
        report["multihop"].append(
            {"query": query, **_multihop_summary(result, time.perf_counter() - started)}
        )

    for discovery_mode, query in selected_innovation:
        started = time.perf_counter()
        result = await innovation_service.discover(
            kb_id=args.kb_id,
            query=query,
            discovery_mode=discovery_mode,
            max_hops=5,
            max_candidates=args.max_paths,
            persist=False,
            retrieval_mode="mix",
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
            llm_enhancement={
                "enabled": True,
                "model_spec": model_spec,
                "strict": False,
                "concurrency_count": 2,
            },
            evidence_scope="any",
        )
        report["innovation"].append(
            {"query": query, **_innovation_summary(result, time.perf_counter() - started)}
        )

    report["passed"] = all(
        item["feature_kind"] == "multi_hop_retrieval"
        and item["path_count"] > 0
        and item["narrative_status"] == "completed"
        and item["citation_closed"]
        for item in report["multihop"]
    ) and all(
        item["feature_kind"] == "innovation_hypothesis_generation"
        and item["hypothesis_count"] > 0
        and item["all_hypotheses"]
        and item["preview_mode"] is True
        and item["persisted"] is False
        for item in report["innovation"]
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
