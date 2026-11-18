"""评估 LightRAG 风格双通道检索、多跳路径和跨文档证据质量。"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

RETRIEVAL_METHODS = (
    "keyword",
    "entity_vector",
    "triple_vector",
    "lightrag_hybrid",
    "lightrag_mix",
)
GRAPH_RETRIEVAL_QUALITY_CRITERIA = frozenset(
    {
        "retrieval_quality_complete",
        "retrieval_human_judgments_complete",
        "entity_recall_at_k",
        "triple_recall_at_k",
        "entity_mrr",
        "graph_retrieval_multi_hop_relevance",
        "cross_document_path_validity",
        "graph_retrieval_evidence_completeness",
        "lightrag_synergy_gain",
    }
)


class RetrievalJudgmentProvenance(BaseModel):
    """人工相关性判断的最小审计记录。"""

    source: Literal["human"] = "human"
    reviewer_id: str = Field(min_length=1, max_length=128)
    reviewed_at: datetime
    guideline_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_timezone(self):
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at 必须包含时区")
        return self


class RetrievedPathJudgment(BaseModel):
    """人工或密封开发集对单条返回路径的判断。"""

    path_id: str = Field(min_length=1, max_length=128)
    relation_ids: list[str] = Field(min_length=1, max_length=12)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    file_ids: list[str] = Field(default_factory=list, max_length=100)
    valid: bool
    relevant: bool

    @property
    def cross_document(self) -> bool:
        return len(set(self.file_ids)) >= 2


class GraphRetrievalQualityCase(BaseModel):
    """同一查询在一种检索方法下的排序结果和人工判断。"""

    query_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2000)
    method: Literal[
        "keyword",
        "entity_vector",
        "triple_vector",
        "lightrag_hybrid",
        "lightrag_mix",
    ]
    gold_entity_ids: list[str] = Field(default_factory=list, max_length=500)
    gold_triple_ids: list[str] = Field(default_factory=list, max_length=1000)
    retrieved_entity_ids: list[str] = Field(default_factory=list, max_length=1000)
    retrieved_triple_ids: list[str] = Field(default_factory=list, max_length=2000)
    retrieved_paths: list[RetrievedPathJudgment] = Field(default_factory=list, max_length=100)
    judgment: RetrievalJudgmentProvenance | None = None

    @model_validator(mode="after")
    def validate_unique_rankings(self):
        for label, values in (
            ("gold_entity_ids", self.gold_entity_ids),
            ("gold_triple_ids", self.gold_triple_ids),
            ("retrieved_entity_ids", self.retrieved_entity_ids),
            ("retrieved_triple_ids", self.retrieved_triple_ids),
            ("retrieved_paths", [item.path_id for item in self.retrieved_paths]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} 不得包含重复 ID")
        return self


class GraphRetrievalQualityThresholds(BaseModel):
    """本地 Pilot 检索质量门槛；正式验收可通过版本化配置覆盖。"""

    entity_recall_at_k: float = Field(default=0.75, ge=0, le=1)
    triple_recall_at_k: float = Field(default=0.65, ge=0, le=1)
    entity_mrr: float = Field(default=0.70, ge=0, le=1)
    multi_hop_relevance: float = Field(default=0.70, ge=0, le=1)
    cross_document_path_validity: float = Field(default=0.75, ge=0, le=1)
    evidence_completeness: float = Field(default=0.95, ge=0, le=1)
    synergy_gain: float = Field(default=0.02, ge=-1, le=1)


def evaluate_graph_retrieval_quality(
    records: list[GraphRetrievalQualityCase | dict[str, Any]],
    *,
    k: int = 10,
    required_methods: tuple[str, ...] = RETRIEVAL_METHODS,
) -> dict[str, Any]:
    """计算排序、多跳与跨文档指标，并量化双通道相对单通道的协同增益。"""
    if not 1 <= int(k) <= 100:
        raise ValueError("k 必须在 1 到 100 之间")
    cases = [
        item if isinstance(item, GraphRetrievalQualityCase) else GraphRetrievalQualityCase.model_validate(item)
        for item in records
    ]
    if not cases:
        raise ValueError("图检索质量评测记录不能为空")

    by_query: dict[str, set[str]] = defaultdict(set)
    by_method: dict[str, list[GraphRetrievalQualityCase]] = defaultdict(list)
    query_contracts: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
    for case in cases:
        if case.method in by_query[case.query_id]:
            raise ValueError(f"查询 {case.query_id} 的方法 {case.method} 重复出现")
        contract = (
            case.query,
            tuple(sorted(case.gold_entity_ids)),
            tuple(sorted(case.gold_triple_ids)),
        )
        if query_contracts.setdefault(case.query_id, contract) != contract:
            raise ValueError(f"查询 {case.query_id} 的各方法必须共享相同 query 与 Gold")
        by_query[case.query_id].add(case.method)
        by_method[case.method].append(case)

    missing = {
        query_id: sorted(set(required_methods) - methods)
        for query_id, methods in sorted(by_query.items())
        if set(required_methods) - methods
    }
    human_judgment_complete = all(case.judgment is not None for case in cases)
    reviewer_ids = sorted({case.judgment.reviewer_id for case in cases if case.judgment is not None})
    methods = {method: _aggregate_method(values, k=int(k)) for method, values in sorted(by_method.items())}
    return {
        "quality_contract": "defense-kg-retrieval-quality-v1",
        "evaluation_scope": "requires_human_relevance_judgments",
        "k": int(k),
        "query_count": len(by_query),
        "case_count": len(cases),
        "required_methods": list(required_methods),
        "complete": not missing,
        "human_judgment_complete": human_judgment_complete,
        "reviewer_ids": reviewer_ids,
        "missing_methods_by_query": missing,
        "methods": methods,
        "synergy": _synergy_metrics(methods),
    }


def graph_retrieval_quality_gate(
    report: dict[str, Any] | None,
    *,
    thresholds: GraphRetrievalQualityThresholds | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """将检索质量报告转换为不可用单元测试替代的准入门。"""
    policy = (
        thresholds
        if isinstance(thresholds, GraphRetrievalQualityThresholds)
        else GraphRetrievalQualityThresholds.model_validate(thresholds or {})
    )
    metrics = (report or {}).get("methods", {}).get("lightrag_hybrid", {})
    synergy = (report or {}).get("synergy", {}).get("lightrag_hybrid_vs_best_single", {})
    return [
        _gate(
            "retrieval_quality_complete",
            bool(report and report.get("complete")),
            True,
            bool(report and report.get("complete")),
        ),
        _gate(
            "retrieval_human_judgments_complete",
            bool(report and report.get("human_judgment_complete")),
            True,
            bool(report and report.get("human_judgment_complete")),
        ),
        _minimum("entity_recall_at_k", metrics.get("entity", {}).get("recall_at_k"), policy.entity_recall_at_k),
        _minimum("triple_recall_at_k", metrics.get("triple", {}).get("recall_at_k"), policy.triple_recall_at_k),
        _minimum("entity_mrr", metrics.get("entity", {}).get("mrr"), policy.entity_mrr),
        _minimum(
            "graph_retrieval_multi_hop_relevance",
            metrics.get("multi_hop_relevance"),
            policy.multi_hop_relevance,
        ),
        _minimum(
            "cross_document_path_validity",
            metrics.get("cross_document_path_validity"),
            policy.cross_document_path_validity,
        ),
        _minimum(
            "graph_retrieval_evidence_completeness",
            metrics.get("evidence_completeness"),
            policy.evidence_completeness,
        ),
        _minimum("lightrag_synergy_gain", synergy.get("composite_gain"), policy.synergy_gain),
    ]


def _aggregate_method(cases: list[GraphRetrievalQualityCase], *, k: int) -> dict[str, Any]:
    entity_metrics = [_ranking_metrics(case.gold_entity_ids, case.retrieved_entity_ids, k) for case in cases]
    triple_metrics = [_ranking_metrics(case.gold_triple_ids, case.retrieved_triple_ids, k) for case in cases]
    paths = [path for case in cases for path in case.retrieved_paths]
    multi_hop = [path for path in paths if len(path.relation_ids) >= 2]
    cross_document = [path for path in multi_hop if path.cross_document]
    complete_evidence = [path for path in paths if path.relation_ids and path.chunk_ids and path.file_ids]
    unique_path_signatures = {tuple(path.relation_ids) for path in paths}
    metrics = {
        "query_count": len(cases),
        "entity": _mean_ranking_metrics(entity_metrics),
        "triple": _mean_ranking_metrics(triple_metrics),
        "path_validity": _ratio(sum(path.valid for path in paths), len(paths)),
        "multi_hop_relevance": _ratio(sum(path.valid and path.relevant for path in multi_hop), len(multi_hop)),
        "cross_document_path_validity": _ratio(
            sum(path.valid and path.relevant for path in cross_document),
            len(cross_document),
        ),
        "evidence_completeness": _ratio(len(complete_evidence), len(paths)),
        "duplicate_path_rate": _ratio(len(paths) - len(unique_path_signatures), len(paths)),
        "counts": {
            "paths": len(paths),
            "multi_hop_paths": len(multi_hop),
            "cross_document_paths": len(cross_document),
        },
    }
    metrics["composite"] = _mean(
        [
            metrics["entity"]["recall_at_k"],
            metrics["triple"]["recall_at_k"],
            metrics["multi_hop_relevance"],
            metrics["evidence_completeness"],
        ]
    )
    return metrics


def _ranking_metrics(gold: list[str], retrieved: list[str], k: int) -> dict[str, float]:
    gold_set = set(gold)
    ranked = retrieved[:k]
    hits = [1 if item in gold_set else 0 for item in ranked]
    first_rank = next((index for index, hit in enumerate(hits, start=1) if hit), None)
    ideal_hits = [1] * min(len(gold_set), k)
    return {
        "recall_at_k": _ratio(sum(hits), len(gold_set)),
        "mrr": 1 / first_rank if first_rank else 0.0,
        "ndcg_at_k": _ratio(_dcg(hits), _dcg(ideal_hits)),
    }


def _mean_ranking_metrics(values: list[dict[str, float]]) -> dict[str, float]:
    return {key: _mean([item[key] for item in values]) for key in ("recall_at_k", "mrr", "ndcg_at_k")}


def _synergy_metrics(methods: dict[str, dict[str, Any]]) -> dict[str, Any]:
    singles = [methods.get("entity_vector"), methods.get("triple_vector")]
    available = [item for item in singles if item]
    if not available:
        return {}
    best_single = max(available, key=lambda item: item["composite"])
    result = {}
    for method in ("lightrag_hybrid", "lightrag_mix"):
        enhanced = methods.get(method)
        if enhanced is None:
            continue
        result[f"{method}_vs_best_single"] = {
            "enhanced_composite": enhanced["composite"],
            "best_single_composite": best_single["composite"],
            "composite_gain": enhanced["composite"] - best_single["composite"],
        }
    return result


def _dcg(hits: list[int]) -> float:
    return sum(hit / math.log2(index + 1) for index, hit in enumerate(hits, start=1))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _minimum(identifier: str, actual: Any, threshold: float) -> dict[str, Any]:
    passed = isinstance(actual, int | float) and not isinstance(actual, bool) and actual >= threshold
    return _gate(identifier, passed, threshold, actual)


def _gate(identifier: str, passed: bool, threshold: Any, actual: Any) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "actual": actual, "threshold": threshold}
