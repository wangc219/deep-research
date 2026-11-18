"""评测需求匹配、图路径、创新候选与证据约束生成质量。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

INNOVATION_QUALITY_METHODS = ("keyword", "vector", "llm_unconstrained", "graphrag")
INNOVATION_ACCEPTANCE_CRITERIA = frozenset(
    {
        "innovation_quality_complete",
        "requirement_entity_match",
        "path_validity",
        "multi_hop_relevance",
        "candidate_relation_rationality",
        "solution_evidence_consistency",
        "unsupported_claim_rate",
        "innovation_expert_acceptance",
        "hallucination_suppression_vs_llm_unconstrained",
        "innovation_expert_gain_vs_llm_unconstrained",
    }
)


class RetrievedPathAssessment(BaseModel):
    """记录独立人工标注的一条检索路径质量。"""

    path_id: str = Field(min_length=1, max_length=128)
    hop_count: int = Field(ge=1, le=20)
    valid: bool
    relevant: bool


class CandidateRelationAssessment(BaseModel):
    """记录专家对候选关系合理性的判断。"""

    candidate_id: str = Field(min_length=1, max_length=128)
    rational: bool


class SolutionClaimAssessment(BaseModel):
    """记录一条生成声明是否被所引证据实际支持。"""

    claim_id: str = Field(min_length=1, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_supported: bool


class InnovationQualityCase(BaseModel):
    """同一查询在一种检索/生成方案下的独立评测记录。"""

    query_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4000)
    method: Literal["keyword", "vector", "llm_unconstrained", "graphrag"]
    gold_requirement_entity_ids: list[str] = Field(min_length=1, max_length=100)
    predicted_requirement_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    retrieved_paths: list[RetrievedPathAssessment] = Field(default_factory=list, max_length=100)
    candidate_relations: list[CandidateRelationAssessment] = Field(default_factory=list, max_length=100)
    solution_claims: list[SolutionClaimAssessment] = Field(default_factory=list, max_length=200)
    expert_accepted: bool

    @model_validator(mode="after")
    def validate_unique_ids(self):
        """避免重复 ID 人为放大指标。"""
        for label, identifiers in (
            ("gold_requirement_entity_ids", self.gold_requirement_entity_ids),
            ("predicted_requirement_entity_ids", self.predicted_requirement_entity_ids),
            ("retrieved_paths", [item.path_id for item in self.retrieved_paths]),
            ("candidate_relations", [item.candidate_id for item in self.candidate_relations]),
            ("solution_claims", [item.claim_id for item in self.solution_claims]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} 不得包含重复 ID")
        return self


class InnovationQualityThresholds(BaseModel):
    """版本化 Pilot 创新质量门槛。"""

    requirement_entity_f1: float = Field(default=0.80, ge=0, le=1)
    path_validity: float = Field(default=0.80, ge=0, le=1)
    multi_hop_relevance: float = Field(default=0.70, ge=0, le=1)
    candidate_relation_rationality: float = Field(default=0.70, ge=0, le=1)
    solution_evidence_consistency: float = Field(default=0.90, ge=0, le=1)
    unsupported_claim_rate_max: float = Field(default=0.05, ge=0, le=1)
    expert_acceptance_rate: float = Field(default=0.70, ge=0, le=1)
    hallucination_reduction_vs_llm: float = Field(default=0.05, ge=0, le=1)
    expert_acceptance_gain_vs_llm: float = Field(default=0.05, ge=0, le=1)


def evaluate_innovation_quality(
    records: list[InnovationQualityCase | dict[str, Any]],
    *,
    required_methods: tuple[str, ...] = INNOVATION_QUALITY_METHODS,
) -> dict[str, Any]:
    """按方法聚合 DOCX 指定的创新发现和生成质量指标。"""
    cases = [
        item if isinstance(item, InnovationQualityCase) else InnovationQualityCase.model_validate(item)
        for item in records
    ]
    if not cases:
        raise ValueError("创新质量评测记录不能为空")

    by_query: dict[str, set[str]] = defaultdict(set)
    by_method: dict[str, list[InnovationQualityCase]] = defaultdict(list)
    query_contracts: dict[str, tuple[str, tuple[str, ...]]] = {}
    seen = set()
    for case in cases:
        key = (case.query_id, case.method)
        if key in seen:
            raise ValueError(f"查询 {case.query_id} 的方法 {case.method} 重复出现")
        seen.add(key)
        contract = (case.query, tuple(sorted(case.gold_requirement_entity_ids)))
        previous_contract = query_contracts.setdefault(case.query_id, contract)
        if previous_contract != contract:
            raise ValueError(f"查询 {case.query_id} 的四方案必须共享相同 query 和需求实体金标")
        by_query[case.query_id].add(case.method)
        by_method[case.method].append(case)

    missing = {
        query_id: sorted(set(required_methods) - methods)
        for query_id, methods in sorted(by_query.items())
        if set(required_methods) - methods
    }
    methods = {method: _aggregate_method(method_cases) for method, method_cases in sorted(by_method.items())}
    return {
        "quality_contract": "defense-kg-innovation-quality-v1",
        "case_count": len(cases),
        "query_count": len(by_query),
        "required_methods": list(required_methods),
        "complete": not missing,
        "missing_methods_by_query": missing,
        "methods": methods,
        "graphrag_deltas": _graphrag_deltas(methods),
    }


def innovation_quality_gate(
    report: dict[str, Any] | None,
    *,
    thresholds: InnovationQualityThresholds | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把 GraphRAG 创新质量报告转成 Pilot 不可跳过的验收项。"""
    policy = (
        thresholds
        if isinstance(thresholds, InnovationQualityThresholds)
        else InnovationQualityThresholds.model_validate(thresholds or {})
    )
    metrics = (report or {}).get("methods", {}).get("graphrag", {})
    llm_delta = (report or {}).get("graphrag_deltas", {}).get("llm_unconstrained", {})
    complete = bool(report and report.get("complete") is True)
    return [
        _gate("innovation_quality_complete", complete, "四方案创新质量评测完整", complete, True),
        _minimum_gate(
            "requirement_entity_match",
            metrics.get("requirement_entity_match", {}).get("f1"),
            policy.requirement_entity_f1,
        ),
        _minimum_gate("path_validity", metrics.get("path_validity"), policy.path_validity),
        _minimum_gate(
            "multi_hop_relevance",
            metrics.get("multi_hop_relevance"),
            policy.multi_hop_relevance,
        ),
        _minimum_gate(
            "candidate_relation_rationality",
            metrics.get("candidate_relation_rationality"),
            policy.candidate_relation_rationality,
        ),
        _minimum_gate(
            "solution_evidence_consistency",
            metrics.get("solution_evidence_consistency"),
            policy.solution_evidence_consistency,
        ),
        _maximum_gate(
            "unsupported_claim_rate",
            metrics.get("unsupported_claim_rate"),
            policy.unsupported_claim_rate_max,
        ),
        _minimum_gate(
            "innovation_expert_acceptance",
            metrics.get("expert_acceptance_rate"),
            policy.expert_acceptance_rate,
        ),
        _gate(
            "hallucination_suppression_vs_llm_unconstrained",
            _finite_number(llm_delta.get("solution_evidence_consistency"))
            and llm_delta["solution_evidence_consistency"] >= policy.hallucination_reduction_vs_llm
            and _finite_number(llm_delta.get("unsupported_claim_rate_reduction"))
            and llm_delta["unsupported_claim_rate_reduction"] >= policy.hallucination_reduction_vs_llm,
            "GraphRAG 相对无图约束 LLM 提升证据一致性并降低无依据声明率",
            {
                "solution_evidence_consistency": llm_delta.get("solution_evidence_consistency"),
                "unsupported_claim_rate_reduction": llm_delta.get("unsupported_claim_rate_reduction"),
            },
            policy.hallucination_reduction_vs_llm,
        ),
        _minimum_gate(
            "innovation_expert_gain_vs_llm_unconstrained",
            llm_delta.get("expert_acceptance_rate"),
            policy.expert_acceptance_gain_vs_llm,
        ),
    ]


def _graphrag_deltas(methods: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    graph = methods.get("graphrag")
    if graph is None:
        return {}
    result = {}
    for baseline_name in ("keyword", "vector", "llm_unconstrained"):
        baseline = methods.get(baseline_name)
        if baseline is None:
            continue
        result[baseline_name] = {
            "requirement_entity_f1": (
                graph["requirement_entity_match"]["f1"] - baseline["requirement_entity_match"]["f1"]
            ),
            "path_validity": graph["path_validity"] - baseline["path_validity"],
            "multi_hop_relevance": graph["multi_hop_relevance"] - baseline["multi_hop_relevance"],
            "candidate_relation_rationality": (
                graph["candidate_relation_rationality"] - baseline["candidate_relation_rationality"]
            ),
            "solution_evidence_consistency": (
                graph["solution_evidence_consistency"] - baseline["solution_evidence_consistency"]
            ),
            "unsupported_claim_rate_reduction": (baseline["unsupported_claim_rate"] - graph["unsupported_claim_rate"]),
            "expert_acceptance_rate": graph["expert_acceptance_rate"] - baseline["expert_acceptance_rate"],
        }
    return result


def _aggregate_method(cases: list[InnovationQualityCase]) -> dict[str, Any]:
    requirement_tp = requirement_fp = requirement_fn = 0
    paths = []
    candidate_relations = []
    claims = []
    for case in cases:
        gold = set(case.gold_requirement_entity_ids)
        predicted = set(case.predicted_requirement_entity_ids)
        requirement_tp += len(gold & predicted)
        requirement_fp += len(predicted - gold)
        requirement_fn += len(gold - predicted)
        paths.extend(case.retrieved_paths)
        candidate_relations.extend(case.candidate_relations)
        claims.extend(case.solution_claims)

    requirement_precision = _safe_divide(requirement_tp, requirement_tp + requirement_fp)
    requirement_recall = _safe_divide(requirement_tp, requirement_tp + requirement_fn)
    multi_hop_paths = [path for path in paths if path.hop_count >= 2]
    supported_claims = [claim for claim in claims if claim.evidence_ids and claim.evidence_supported]
    unsupported_claims = [claim for claim in claims if not claim.evidence_ids or not claim.evidence_supported]
    return {
        "query_count": len(cases),
        "requirement_entity_match": {
            "true_positive": requirement_tp,
            "false_positive": requirement_fp,
            "false_negative": requirement_fn,
            "precision": requirement_precision,
            "recall": requirement_recall,
            "f1": _safe_divide(
                2 * requirement_precision * requirement_recall,
                requirement_precision + requirement_recall,
            ),
        },
        "path_validity": _safe_divide(sum(path.valid for path in paths), len(paths)),
        "multi_hop_relevance": _safe_divide(
            sum(path.valid and path.relevant for path in multi_hop_paths),
            len(multi_hop_paths),
        ),
        "candidate_relation_rationality": _safe_divide(
            sum(item.rational for item in candidate_relations),
            len(candidate_relations),
        ),
        "solution_evidence_consistency": _safe_divide(len(supported_claims), len(claims)),
        "unsupported_claim_rate": _safe_divide(len(unsupported_claims), len(claims)),
        "expert_acceptance_rate": _safe_divide(sum(case.expert_accepted for case in cases), len(cases)),
        "counts": {
            "paths": len(paths),
            "multi_hop_paths": len(multi_hop_paths),
            "candidate_relations": len(candidate_relations),
            "solution_claims": len(claims),
            "supported_claims": len(supported_claims),
        },
    }


def _minimum_gate(identifier: str, actual: Any, minimum: float) -> dict[str, Any]:
    return _gate(
        identifier,
        _finite_number(actual) and actual >= minimum,
        f"{identifier} 不低于 {minimum:.2f}",
        actual,
        minimum,
    )


def _maximum_gate(identifier: str, actual: Any, maximum: float) -> dict[str, Any]:
    return _gate(
        identifier,
        _finite_number(actual) and actual <= maximum,
        f"{identifier} 不高于 {maximum:.2f}",
        actual,
        maximum,
    )


def _gate(identifier: str, passed: bool, description: str, actual: Any, threshold: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "passed": bool(passed),
        "description": description,
        "actual": actual,
        "threshold": threshold,
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
