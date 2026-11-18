"""GraphRAG 与关键词、向量和无图约束 LLM 的可复现对比评测。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

REQUIRED_RETRIEVAL_METHODS = ("keyword", "vector", "llm_unconstrained", "graphrag")
RETRIEVAL_BASELINES = ("keyword", "vector", "llm_unconstrained")
RETRIEVAL_ACCEPTANCE_CRITERIA = frozenset(
    {
        "retrieval_comparison_complete",
        "graphrag_recall_at_10",
        "graphrag_mrr",
        "graphrag_evidence_coverage",
        "graphrag_non_degradation_vs_keyword",
        "graphrag_gain_vs_keyword",
        "graphrag_non_degradation_vs_vector",
        "graphrag_gain_vs_vector",
        "graphrag_non_degradation_vs_llm_unconstrained",
        "graphrag_gain_vs_llm_unconstrained",
    }
)


class RetrievalRun(BaseModel):
    method: str = Field(min_length=1, max_length=64)
    retrieved_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)


class RetrievalComparisonCase(BaseModel):
    query_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    gold_ids: list[str] = Field(min_length=1)
    runs: list[RetrievalRun] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case(self):
        if len(self.gold_ids) != len(set(self.gold_ids)):
            raise ValueError("gold_ids 不能重复")
        methods = [run.method for run in self.runs]
        if len(methods) != len(set(methods)):
            raise ValueError("同一 query 的 method 不能重复")
        return self


class RetrievalComparisonThresholds(BaseModel):
    """版本化 Pilot GraphRAG 检索质量门槛。"""

    evaluation_k: Literal[10] = 10
    recall_at_k: float = Field(default=0.80, ge=0, le=1)
    mrr: float = Field(default=0.70, ge=0, le=1)
    evidence_coverage: float = Field(default=0.90, ge=0, le=1)
    minimum_baseline_delta: float = Field(default=0.0, ge=-1, le=1)
    minimum_gain_over_each_baseline: float = Field(default=0.02, ge=0, le=1)


def compare_retrieval_methods(
    cases: list[RetrievalComparisonCase | dict[str, Any]],
    *,
    k_values: tuple[int, ...] = (1, 3, 5, 10),
    required_methods: tuple[str, ...] = REQUIRED_RETRIEVAL_METHODS,
) -> dict[str, Any]:
    """计算四种检索方案的宏平均命中、PRF、MRR、证据覆盖与 p95。"""
    normalized = [
        case if isinstance(case, RetrievalComparisonCase) else RetrievalComparisonCase.model_validate(case)
        for case in cases
    ]
    if not normalized:
        raise ValueError("检索对比测试集不能为空")
    if not k_values or any(k <= 0 for k in k_values):
        raise ValueError("k_values 必须是正整数")

    missing = {}
    metrics_by_method: dict[str, list[dict[str, float]]] = defaultdict(list)
    for case in normalized:
        run_by_method = {run.method: run for run in case.runs}
        absent = sorted(set(required_methods) - set(run_by_method))
        if absent:
            missing[case.query_id] = absent
        for method, run in run_by_method.items():
            metrics_by_method[method].append(_case_metrics(case.gold_ids, run, k_values))

    methods = {method: _aggregate_method_metrics(rows, k_values) for method, rows in sorted(metrics_by_method.items())}
    graph = methods.get("graphrag")
    baseline_deltas = {}
    if graph:
        for baseline in ("keyword", "vector", "llm_unconstrained"):
            baseline_metrics = methods.get(baseline)
            if baseline_metrics is None:
                continue
            baseline_deltas[baseline] = {
                f"recall@{k}": graph[f"recall@{k}"] - baseline_metrics[f"recall@{k}"] for k in k_values
            }
            baseline_deltas[baseline]["mrr"] = graph["mrr"] - baseline_metrics["mrr"]
            baseline_deltas[baseline]["evidence_coverage"] = (
                graph["evidence_coverage"] - baseline_metrics["evidence_coverage"]
            )

    return {
        "comparison_contract": "defense-kg-retrieval-comparison-v1",
        "query_count": len(normalized),
        "k_values": list(k_values),
        "required_methods": list(required_methods),
        "complete": not missing,
        "missing_methods_by_query": missing,
        "methods": methods,
        "graphrag_deltas": baseline_deltas,
    }


def retrieval_comparison_gate(
    report: dict[str, Any] | None,
    *,
    thresholds: RetrievalComparisonThresholds | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把四方案检索报告转为 Pilot 不可跳过的 GraphRAG 验收项。"""
    policy = (
        thresholds
        if isinstance(thresholds, RetrievalComparisonThresholds)
        else RetrievalComparisonThresholds.model_validate(thresholds or {})
    )
    graph = (report or {}).get("methods", {}).get("graphrag", {})
    recall_key = f"recall@{policy.evaluation_k}"
    criteria = [
        _gate(
            "retrieval_comparison_complete",
            bool(report and report.get("complete") is True),
            "关键词、向量、无图约束 LLM 与 GraphRAG 四方案检索记录完整",
            bool(report and report.get("complete") is True),
            True,
        ),
        _minimum_gate("graphrag_recall_at_10", graph.get(recall_key), policy.recall_at_k),
        _minimum_gate("graphrag_mrr", graph.get("mrr"), policy.mrr),
        _minimum_gate(
            "graphrag_evidence_coverage",
            graph.get("evidence_coverage"),
            policy.evidence_coverage,
        ),
    ]
    deltas = (report or {}).get("graphrag_deltas", {})
    quality_fields = (recall_key, "mrr", "evidence_coverage")
    for baseline in RETRIEVAL_BASELINES:
        baseline_deltas = deltas.get(baseline, {})
        actual = {field: baseline_deltas.get(field) for field in quality_fields}
        numeric_values = [value for value in actual.values() if _finite_number(value)]
        criteria.append(
            _gate(
                f"graphrag_non_degradation_vs_{baseline}",
                len(numeric_values) == len(quality_fields)
                and all(value >= policy.minimum_baseline_delta for value in numeric_values),
                f"GraphRAG 对 {baseline} 的召回、MRR 和证据覆盖均不退化",
                actual,
                policy.minimum_baseline_delta,
            )
        )
        criteria.append(
            _gate(
                f"graphrag_gain_vs_{baseline}",
                len(numeric_values) == len(quality_fields)
                and max(numeric_values) >= policy.minimum_gain_over_each_baseline,
                f"GraphRAG 对 {baseline} 至少一项核心质量指标有实质提升",
                max(numeric_values) if numeric_values else None,
                policy.minimum_gain_over_each_baseline,
            )
        )
    return criteria


def _case_metrics(gold_ids: list[str], run: RetrievalRun, k_values: tuple[int, ...]) -> dict[str, float]:
    gold = set(gold_ids)
    deduplicated = list(dict.fromkeys(run.retrieved_ids))
    result: dict[str, float] = {"latency_ms": run.latency_ms}
    reciprocal_rank = 0.0
    for index, identifier in enumerate(deduplicated, start=1):
        if identifier in gold:
            reciprocal_rank = 1 / index
            break
    result["mrr"] = reciprocal_rank
    evidence = set(run.evidence_ids)
    result["evidence_coverage"] = len(gold & evidence) / len(gold)
    for k in k_values:
        retrieved = set(deduplicated[:k])
        true_positive = len(gold & retrieved)
        precision = true_positive / len(retrieved) if retrieved else 0.0
        recall = true_positive / len(gold)
        result[f"hit@{k}"] = float(true_positive > 0)
        result[f"precision@{k}"] = precision
        result[f"recall@{k}"] = recall
        result[f"f1@{k}"] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return result


def _aggregate_method_metrics(rows: list[dict[str, float]], k_values: tuple[int, ...]) -> dict[str, Any]:
    fields = ["mrr", "evidence_coverage"]
    for k in k_values:
        fields.extend((f"hit@{k}", f"precision@{k}", f"recall@{k}", f"f1@{k}"))
    result = {field: sum(row[field] for row in rows) / len(rows) for field in fields}
    latencies = sorted(row["latency_ms"] for row in rows)
    result["latency_p50_ms"] = _percentile(latencies, 0.50)
    result["latency_p95_ms"] = _percentile(latencies, 0.95)
    result["query_count"] = len(rows)
    return result


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _minimum_gate(identifier: str, actual: Any, minimum: float) -> dict[str, Any]:
    return _gate(
        identifier,
        _finite_number(actual) and actual >= minimum,
        f"{identifier} 不低于 {minimum:.2f}",
        actual,
        minimum,
    )


def _gate(identifier: str, passed: bool, description: str, actual: Any, threshold: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "passed": bool(passed),
        "description": description,
        "actual": actual,
        "threshold": threshold,
    }


def _finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
