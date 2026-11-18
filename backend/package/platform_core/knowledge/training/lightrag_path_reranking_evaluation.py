"""评估确定性多跳排序与 LightRAG 受约束重排的成对质量。"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

PATH_RERANKING_EVALUATION_CONTRACT = "defense-kg-lightrag-path-reranking-evaluation-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PathRerankingJudgment(BaseModel):
    """真实人工路径相关性判断的审计来源。"""

    source: Literal["human"] = "human"
    reviewer_id: str = Field(min_length=1, max_length=128)
    reviewed_at: datetime
    guideline_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_timezone(self):
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at 必须包含时区")
        return self


class PathRerankingRuntime(BaseModel):
    """一次查询排序阶段的可复现资源记录。"""

    latency_ms: float = Field(ge=0)
    llm_calls: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)


class PathRerankingEvaluationCase(BaseModel):
    """同一封闭候选集在增强前后的成对排序结果。"""

    query_sha256: str
    candidate_path_ids: list[str] = Field(min_length=2, max_length=30)
    deterministic_ranking: list[str] = Field(min_length=2, max_length=30)
    enhanced_ranking: list[str] = Field(min_length=2, max_length=30)
    relevant_path_ids: list[str] = Field(default_factory=list, max_length=30)
    valid_path_ids: list[str] = Field(default_factory=list, max_length=30)
    deterministic_runtime: PathRerankingRuntime
    enhanced_runtime: PathRerankingRuntime
    judgment: PathRerankingJudgment

    @model_validator(mode="after")
    def validate_closed_pair(self):
        if not _SHA256.fullmatch(self.query_sha256.lower()):
            raise ValueError("query_sha256 必须是 SHA-256")
        for label, values in (
            ("candidate_path_ids", self.candidate_path_ids),
            ("deterministic_ranking", self.deterministic_ranking),
            ("enhanced_ranking", self.enhanced_ranking),
            ("relevant_path_ids", self.relevant_path_ids),
            ("valid_path_ids", self.valid_path_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} 不得包含重复路径")
        candidates = set(self.candidate_path_ids)
        if set(self.deterministic_ranking) != candidates or set(self.enhanced_ranking) != candidates:
            raise ValueError("确定性排序和增强排序必须是同一封闭候选集的完整排列")
        if not set(self.relevant_path_ids).issubset(candidates):
            raise ValueError("相关路径必须来自封闭候选集")
        if not set(self.valid_path_ids).issubset(candidates):
            raise ValueError("有效路径必须来自封闭候选集")
        return self


class PathRerankingEvaluationInput(BaseModel):
    """不含查询原文的路径重排质量输入。"""

    contract: Literal["defense-kg-lightrag-path-reranking-evaluation-v1"]
    pipeline_revision: str = Field(min_length=1, max_length=128)
    k: int = Field(default=10, ge=1, le=30)
    cases: list[PathRerankingEvaluationCase] = Field(min_length=1)
    minimum_ndcg_gain: float = Field(default=0.02, ge=0, le=1)
    max_latency_p95_ratio: float = Field(default=2.0, ge=1)
    max_llm_calls_per_query: float = Field(default=1.0, ge=0)
    max_estimated_cost: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_queries(self):
        hashes = [item.query_sha256.lower() for item in self.cases]
        if len(hashes) != len(set(hashes)):
            raise ValueError("路径重排评测查询不得重复")
        return self


def evaluate_path_reranking(value: PathRerankingEvaluationInput | dict[str, Any]) -> dict[str, Any]:
    """输出成对排序、人工有效性和成本门禁，不包含查询或证据原文。"""

    source = (
        value if isinstance(value, PathRerankingEvaluationInput) else PathRerankingEvaluationInput.model_validate(value)
    )
    route_metrics = {
        route: _aggregate(source.cases, route=route, k=source.k) for route in ("deterministic", "enhanced")
    }
    runtime = _runtime_metrics(source.cases)
    delta = {
        key: round(route_metrics["enhanced"][key] - route_metrics["deterministic"][key], 6)
        for key in ("recall_at_k", "mrr", "ndcg_at_k", "valid_path_rate_at_k")
    }
    gates = [
        _gate("human_judgments_complete", True, True, True),
        _gate("closed_candidate_set", True, True, True),
        _minimum("ndcg_material_gain", delta["ndcg_at_k"], source.minimum_ndcg_gain),
        _minimum("recall_non_degradation", delta["recall_at_k"], 0),
        _minimum("path_validity_non_degradation", delta["valid_path_rate_at_k"], 0),
        _maximum("latency_p95_ratio", runtime["latency_p95_ratio"], source.max_latency_p95_ratio),
        _maximum(
            "llm_calls_per_query",
            runtime["enhanced"]["llm_calls_per_query"],
            source.max_llm_calls_per_query,
        ),
        _maximum("estimated_cost", runtime["enhanced"]["estimated_cost"], source.max_estimated_cost),
    ]
    return {
        "report_contract": "defense-kg-lightrag-path-reranking-report-v1",
        "pipeline_revision": source.pipeline_revision,
        "evaluation_scope": "paired_closed_candidates_with_human_judgments",
        "contains_source_text": False,
        "k": source.k,
        "query_count": len(source.cases),
        "reviewer_ids": sorted({item.judgment.reviewer_id for item in source.cases}),
        "metrics": {**route_metrics, "delta": delta, "runtime": runtime},
        "gates": gates,
        "passed": all(item["passed"] for item in gates),
    }


def _aggregate(cases: list[PathRerankingEvaluationCase], *, route: str, k: int) -> dict[str, float]:
    values = []
    for case in cases:
        ranking = getattr(case, f"{route}_ranking")
        values.append(
            _ranking_metrics(
                ranking,
                relevant=set(case.relevant_path_ids),
                valid=set(case.valid_path_ids),
                k=k,
            )
        )
    return {key: _mean([item[key] for item in values]) for key in values[0]}


def _ranking_metrics(
    ranking: list[str],
    *,
    relevant: set[str],
    valid: set[str],
    k: int,
) -> dict[str, float]:
    ranked = ranking[:k]
    relevance = [1 if path_id in relevant else 0 for path_id in ranked]
    first_rank = next((index for index, hit in enumerate(relevance, start=1) if hit), None)
    ideal = [1] * min(len(relevant), k)
    return {
        "recall_at_k": _ratio(sum(relevance), len(relevant)),
        "mrr": 1 / first_rank if first_rank else 0.0,
        "ndcg_at_k": _ratio(_dcg(relevance), _dcg(ideal)),
        "valid_path_rate_at_k": _ratio(sum(path_id in valid for path_id in ranked), len(ranked)),
    }


def _runtime_metrics(cases: list[PathRerankingEvaluationCase]) -> dict[str, Any]:
    result = {}
    for route in ("deterministic", "enhanced"):
        values = [getattr(item, f"{route}_runtime") for item in cases]
        result[route] = {
            "latency_p95_ms": _percentile([item.latency_ms for item in values], 0.95),
            "llm_calls": sum(item.llm_calls for item in values),
            "llm_calls_per_query": _ratio(sum(item.llm_calls for item in values), len(values)),
            "estimated_cost": round(sum(item.estimated_cost for item in values), 6),
        }
    result["latency_p95_ratio"] = _ratio(
        result["enhanced"]["latency_p95_ms"],
        result["deterministic"]["latency_p95_ms"],
    )
    return result


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(math.ceil(len(ordered) * percentile) - 1, 0)
    return round(float(ordered[index]), 6)


def _dcg(values: list[int]) -> float:
    return sum(value / math.log2(index + 1) for index, value in enumerate(values, start=1))


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _minimum(identifier: str, actual: float, threshold: float) -> dict[str, Any]:
    return _gate(identifier, actual >= threshold, threshold, actual)


def _maximum(identifier: str, actual: float, threshold: float) -> dict[str, Any]:
    return _gate(identifier, actual <= threshold, threshold, actual)


def _gate(identifier: str, passed: bool, threshold: Any, actual: Any) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "actual": actual, "threshold": threshold}
