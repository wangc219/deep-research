#!/usr/bin/env python3
"""用真实本地图、mix 检索和项目通用 LLM 验证双向创新链路，不写入假设。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor
from platform_core.knowledge.graphs.lightrag_innovation_enhancement import (
    LightRAGInnovationEnhancer,
)
from platform_core.knowledge.graphs.lightrag_path_reranking import LightRAGPathReranker
from platform_core.knowledge.graphs.lightrag_query_enhancement import LightRAGQueryPlanner
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.services.knowledge_graph_innovation_service import KnowledgeGraphInnovationService
from platform_core.services.knowledge_graph_retrieval_adapter import retrieve_graph_mix_chunks
from platform_core.storage.postgres.manager import pg_manager


class ProjectModelJSONClient:
    """复用项目模型设置完成结构化创新调用，禁止重新启用本地 LLM。"""

    def __init__(self, *, model_spec: str, timeout_seconds: float, max_output_tokens: int):
        _reject_local_model(model_spec)
        self.model_spec = model_spec
        self.calls: list[dict[str, Any]] = []
        self.started_at = time.monotonic()
        self.active_calls = 0
        self.peak_inflight_calls = 0
        self.extractor = LLMGraphExtractor(
            {
                "model_spec": model_spec,
                "model_params": {
                    "temperature": 0,
                    "max_tokens": max_output_tokens,
                    "max_retries": 0,
                },
                "timeout_seconds": timeout_seconds,
                "concurrency_count": 1,
                "enable_thinking": False,
                "max_truncation_retries": 0,
            }
        )

    async def complete(self, prompt: str) -> dict[str, Any]:
        """调用项目模型并按不同创新阶段约束顶层 JSON 字段。"""
        started = time.monotonic()
        started_offset_ms = round((started - self.started_at) * 1000, 2)
        self.active_calls += 1
        self.peak_inflight_calls = max(self.peak_inflight_calls, self.active_calls)
        role = _prompt_role(prompt)
        required_keys = {
            "query_planner": ("low_level_keywords", "high_level_keywords"),
            "path_reranker": ("rankings",),
            "innovation_enhancer": ("hypotheses",),
        }.get(role, ("hypotheses", "rankings", "low_level_keywords"))
        try:
            parsed = await self.extractor.complete_json(
                prompt,
                required_keys=required_keys,
            )
        finally:
            self.active_calls -= 1
        ended = time.monotonic()
        self.calls.append(
            {
                "role": role,
                "started_offset_ms": started_offset_ms,
                "ended_offset_ms": round((ended - self.started_at) * 1000, 2),
                "duration_ms": round((ended - started) * 1000, 2),
                "response_shape": _response_shape(parsed),
            }
        )
        return parsed

    async def aclose(self) -> None:
        """关闭项目模型连接。"""
        await self.extractor.aclose()


async def smoke(args: argparse.Namespace) -> dict[str, Any]:
    """分别执行 top_down 与 bottom_up，只输出脱敏结构结果。"""
    pg_manager.initialize()
    model_spec = await _resolve_project_chat_model(args.api_base, args.model_spec)
    client = ProjectModelJSONClient(
        model_spec=model_spec,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
    )

    def planner_factory(options: dict[str, Any]) -> LightRAGQueryPlanner:
        return LightRAGQueryPlanner(options, completion=client.complete)

    def reranker_factory(options: dict[str, Any]) -> LightRAGPathReranker:
        return LightRAGPathReranker(options, completion=client.complete)

    def innovation_factory(options: dict[str, Any]) -> LightRAGInnovationEnhancer:
        return LightRAGInnovationEnhancer(options, completion=client.complete)

    graph_service = MilvusGraphService(
        query_planner_factory=planner_factory,
        path_reranker_factory=reranker_factory,
        chunk_retriever=retrieve_graph_mix_chunks,
    )
    service = KnowledgeGraphInnovationService(
        graph_service=graph_service,
        innovation_enhancer_factory=innovation_factory,
    )
    runs = []
    started = time.monotonic()
    try:
        for mode, query in (
            ("top_down", args.top_down_query),
            ("bottom_up", args.bottom_up_query),
        ):
            result = await service.discover(
                kb_id=args.kb_id,
                query=query,
                discovery_mode=mode,
                max_hops=args.max_hops,
                max_candidates=args.max_candidates,
                persist=False,
                retrieval_mode="mix",
                evidence_scope="any",
                query_enhancement={
                    "enabled": True,
                    "model_spec": model_spec,
                    "strict": False,
                    "max_output_tokens": args.max_output_tokens,
                    "timeout_seconds": args.timeout_seconds,
                },
                path_reranking={
                    "enabled": True,
                    "model_spec": model_spec,
                    "strict": False,
                    "max_output_tokens": args.max_output_tokens,
                    "timeout_seconds": args.timeout_seconds,
                },
                llm_enhancement={
                    "enabled": True,
                    "model_spec": model_spec,
                    "strict": False,
                    "max_output_tokens": args.max_output_tokens,
                    "timeout_seconds": args.timeout_seconds,
                },
            )
            runs.append(_sanitize_run(mode=mode, query=query, result=result))
    finally:
        await client.aclose()
        await pg_manager.close()

    report = {
        "contract": "defense-kg-lightrag-innovation-project-model-smoke-v4",
        "evaluation_scope": "read_only_real_local_pilot_mix_retrieval_and_project_model_llm",
        "quality_claim_allowed": False,
        "created_at_unix": int(time.time()),
        "knowledge_base_id": args.kb_id,
        "runtime": {
            "transport": "project_model_settings",
            "model_spec": model_spec,
            "local_llm_used": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "peak_inflight_llm_calls": client.peak_inflight_calls,
            "calls": client.calls,
        },
        "runs": runs,
        "code_sha256": {
            path.name: _sha256_file(path)
            for path in (
                Path(__file__).parents[1] / "package/platform_core/knowledge/graphs/innovation_discovery.py",
                Path(__file__).parents[1] / "package/platform_core/knowledge/graphs/lightrag_innovation_enhancement.py",
                Path(__file__).parents[1] / "package/platform_core/knowledge/graphs/lightrag_path_reranking.py",
                Path(__file__).parents[1] / "package/platform_core/knowledge/graphs/milvus_graph_service.py",
            )
        },
        "limitations": [
            "真实 Pilot 图规模较小；结果只证明双向调用、mix 检索、门禁与项目通用模型联动可运行。",
            "单一路径时路径重排器按设计不调用模型，不能据此证明多候选重排质量。",
            "当前数据不是独立人工 Gold，不能证明实体、关系、检索或创新准确率提升。",
            "所有创新结果固定为 pending Hypothesis，persist=false，未写入 PostgreSQL。",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _sanitize_run(*, mode: str, query: str, result: dict[str, Any]) -> dict[str, Any]:
    hypotheses = result.get("hypotheses") or []
    enhancement = result.get("innovation_enhancement") or {}
    path_reranking = result.get("path_reranking") or {}
    summary = result.get("retrieval_summary") or {}
    return {
        "mode": mode,
        "query_sha256": _sha256_text(query),
        "retrieval_mode": summary.get("retrieval_mode"),
        "requested_retrieval_mode": summary.get("requested_retrieval_mode"),
        "retrieval_degraded": summary.get("retrieval_degraded"),
        "retrieval_failure_types": [item.get("failure_type") for item in summary.get("retrieval_failures") or []],
        "entity_hit_count": int(summary.get("entity_hit_count") or 0),
        "triple_hit_count": int(summary.get("triple_hit_count") or 0),
        "chunk_hit_count": int(summary.get("chunk_hit_count") or 0),
        "returned_path_count": int(summary.get("returned_path_count") or 0),
        "review_scope": result.get("review_scope") or summary.get("review_scope"),
        "preview_mode": bool(result.get("preview_mode")),
        "pending_evidence": bool(result.get("pending_evidence")),
        "pending_evidence_path_count": int(summary.get("pending_evidence_path_count") or 0),
        "retrieval_quality": summary.get("quality") or {},
        "query_planner_status": summary.get("query_planner_status"),
        "path_reranking": {
            "status": path_reranking.get("status"),
            "llm_used": path_reranking.get("llm_used"),
            "ranked_count": int(path_reranking.get("ranked_count") or 0),
            "failure_type": path_reranking.get("failure_type"),
            "candidate_count": int(path_reranking.get("candidate_count") or 0),
            "prompt_candidate_count": int(path_reranking.get("prompt_candidate_count") or 0),
            "omitted_candidate_count": int(path_reranking.get("omitted_candidate_count") or 0),
            "context_limited": bool(path_reranking.get("context_limited")),
        },
        "innovation_enhancement": {
            "status": enhancement.get("status"),
            "applied_count": int(enhancement.get("applied_count") or 0),
            "rejected_count": int(enhancement.get("rejected_count") or 0),
            "llm_calls": int(enhancement.get("llm_calls") or 0),
            "batches": int(enhancement.get("batches") or 0),
            "requested_candidates": int(enhancement.get("requested_candidates") or 0),
            "applied_candidates": int(enhancement.get("applied_candidates") or 0),
            "max_hypotheses_per_call": int(enhancement.get("max_hypotheses_per_call") or 0),
            "output_budget": int(enhancement.get("output_budget") or 0),
            "degraded_batches": int(enhancement.get("degraded_batches") or 0),
            "truncated_batches": int(enhancement.get("truncated_batches") or 0),
            "failure_types": enhancement.get("failure_types") or {},
            "min_evidence_coverage": enhancement.get("min_evidence_coverage"),
            "requires_boundary_relations": enhancement.get("requires_boundary_relations"),
            "requires_validation_and_falsification": enhancement.get("requires_validation_and_falsification"),
            "rejection_reasons": enhancement.get("rejection_reasons") or {},
            "structure_repair_attempted": enhancement.get("structure_repair_attempted"),
        },
        "hypothesis_count": len(hypotheses),
        "claim_levels": sorted({str(item.get("claim_level") or "") for item in hypotheses}),
        "review_statuses": sorted({str(item.get("review_status") or "") for item in hypotheses}),
        "expert_review_required_count": sum(bool(item.get("expert_review_required")) for item in hypotheses),
        "llm_applied_count": sum(bool(item.get("llm_enhancement")) for item in hypotheses),
        "coverage_values": [
            (item.get("llm_enhancement") or {}).get("evidence_coverage")
            for item in hypotheses
            if item.get("llm_enhancement")
        ],
        "risk_penalty_values": [
            ((item.get("llm_enhancement") or {}).get("risk_penalties") or {}).get("total")
            for item in hypotheses
            if item.get("llm_enhancement")
        ],
        "validation_requirement_counts": [len(item.get("validation_requirements") or []) for item in hypotheses],
        "falsification_criteria_counts": [len(item.get("falsification_criteria") or []) for item in hypotheses],
        "hypothesis_summaries": [_hypothesis_summary(item) for item in hypotheses],
        "persisted": result.get("persisted"),
        "expert_review_required": bool(result.get("expert_review_required")),
        "contains_source_text": False,
    }


def _hypothesis_summary(item: dict[str, Any]) -> dict[str, Any]:
    """保留创新语义与证据结构，不复制来源文档原文。"""
    source = item.get("source") or {}
    target = item.get("target") or {}
    evidence_path = item.get("evidence_path") or {}
    enhancement = item.get("llm_enhancement") or {}
    return {
        "source": {"name": source.get("name"), "type": source.get("type")},
        "target": {"name": target.get("name"), "type": target.get("type")},
        "relation_type": item.get("relation_type"),
        "mechanism_hypothesis": item.get("mechanism_hypothesis"),
        "evidence_relation_count": len(evidence_path.get("relation_ids") or []),
        "document_count": int(evidence_path.get("document_count") or 0),
        "cross_document": bool(evidence_path.get("cross_document")),
        "support_level": evidence_path.get("support_level"),
        "evidence_coverage": enhancement.get("evidence_coverage"),
        "boundary_coverage_satisfied": enhancement.get("boundary_coverage_satisfied"),
        "risk_penalty_total": (enhancement.get("risk_penalties") or {}).get("total"),
        "validation_requirement_count": len(item.get("validation_requirements") or []),
        "falsification_criteria_count": len(item.get("falsification_criteria") or []),
        "claim_level": item.get("claim_level"),
        "review_status": item.get("review_status"),
    }


async def _resolve_project_chat_model(api_base: str, explicit_model_spec: str | None) -> str:
    """读取项目默认模型；显式覆盖仍必须是项目已配置的非本地提供方。"""

    from platform_core.knowledge.training.local_pilot_operator import local_operator_headers

    model_spec = str(explicit_model_spec or "").strip()
    if not model_spec:
        headers, _ = await local_operator_headers(api_base, expires_minutes=15)
        async with httpx.AsyncClient(base_url=api_base.rstrip("/"), timeout=30) as client:
            response = await client.get("/system/config", headers=headers)
            response.raise_for_status()
            model_spec = str(response.json().get("default_model") or "").strip()
    if not model_spec:
        raise ValueError("项目模型设置尚未配置 default_model")
    _reject_local_model(model_spec)
    return model_spec


def _reject_local_model(model_spec: str) -> None:
    normalized = str(model_spec or "").strip().casefold()
    provider_id, _, model_id = normalized.partition(":")
    if provider_id.startswith("local") or model_id.startswith(("artifacts/", "/")):
        raise ValueError("创新烟测禁止使用本地 LLM，必须使用项目模型设置中的通用模型")


def _prompt_role(prompt: str) -> str:
    if "low_level_keywords" in prompt and "high_level_keywords" in prompt:
        return "query_planner"
    if "多跳路径重排器" in prompt:
        return "path_reranker"
    if "创新假设分析器" in prompt:
        return "innovation_enhancer"
    return "unknown"


def _response_shape(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"top_level_keys": sorted(payload)}
    for key in ("hypotheses", "rankings"):
        values = payload.get(key)
        if isinstance(values, list) and values and isinstance(values[0], dict):
            result[f"{key}_item_keys"] = sorted(values[0])
            result[f"{key}_item_types"] = {field: type(value).__name__ for field, value in sorted(values[0].items())}
    return result


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050/api")
    parser.add_argument("--model-spec", help="可选覆盖；默认读取项目模型设置中的 default_model")
    parser.add_argument("--top-down-query", default="复杂电磁环境下提升目标感知与抗干扰能力")
    parser.add_argument("--bottom-up-query", default="宽带阵列信号处理技术的潜在装备应用")
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 2 <= args.max_hops <= 6:
        parser.error("--max-hops 必须在 2 到 6 之间")
    if not 1 <= args.max_candidates <= 10:
        parser.error("--max-candidates 必须在 1 到 10 之间")
    if not 1.0 <= args.timeout_seconds <= 600.0:
        parser.error("--timeout-seconds 必须在 1 到 600 之间")
    if not 256 <= args.max_output_tokens <= 32768:
        parser.error("--max-output-tokens 必须在 256 到 32768 之间")
    return args


def main() -> int:
    report = asyncio.run(smoke(parse_args()))
    print(
        json.dumps(
            {
                "contract": report["contract"],
                "quality_claim_allowed": report["quality_claim_allowed"],
                "runtime": report["runtime"],
                "runs": report["runs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
