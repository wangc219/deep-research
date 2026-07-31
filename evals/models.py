from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
import json


PAIRWISE_V0_DIMENSIONS = frozenset(
    {
        "task_fulfillment",
        "facts_and_citations",
        "analysis_depth",
        "equipment_demand_value",
        "uncertainty",
    }
)

PAIRWISE_V0_LEGACY_DIMENSIONS = frozenset(
    {*PAIRWISE_V0_DIMENSIONS, "communication_efficiency"}
)

PAIRWISE_V1_DIMENSIONS = frozenset(
    {
        "route_task_fulfillment",
        "evidence_and_factuality",
        "causal_and_mechanism_depth",
        "military_operational_value",
        "capability_mapping_and_demand_quality",
        "novelty_and_foresight",
        "system_and_cross_scenario_robustness",
        "uncertainty_and_validation",
    }
)

PAIRWISE_V1_LEGACY_DIMENSIONS = frozenset(
    {*PAIRWISE_V1_DIMENSIONS, "communication_efficiency"}
)

DEPRECATED_PAIRWISE_DIMENSIONS = frozenset({"communication_efficiency"})


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    query: str
    region: str
    domain: str
    difficulty: Literal["easy", "medium", "hard"]
    split: Literal["pilot", "test"]

    def validate(self) -> None:
        if not self.query_id.startswith("Q-"):
            raise ValueError(f"invalid anonymous query id: {self.query_id}")
        if not self.query.strip():
            raise ValueError("query text is required")
        if not self.region.strip() or not self.domain.strip():
            raise ValueError("region and domain are required")
        if self.difficulty not in {"easy", "medium", "hard"}:
            raise ValueError(f"invalid difficulty: {self.difficulty}")
        if self.split not in {"pilot", "test"}:
            raise ValueError(f"invalid split: {self.split}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalQuery":
        result = cls(**payload)
        result.validate()
        return result


@dataclass
class EvalRunResult:
    eval_id: str
    query_id: str
    system_id: str
    status: Literal["completed", "failed", "skipped"]
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    evidence_context: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    model_snapshot: dict[str, Any] = field(default_factory=dict)
    estimated_cost: float = 0.0
    artifact_refs: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalRunResult":
        return cls(**payload)


@dataclass(frozen=True)
class PairwiseJudgment:
    pair_id: str
    judge_id: str
    winner: Literal["A", "B", "tie"]
    confidence: float
    dimensions: dict[str, Literal["A", "B", "tie"]]
    reason: str
    citation_issues: list[str] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)
    primary_route: str = ""
    secondary_routes: list[str] = field(default_factory=list)
    route_confidence: float = 0.0
    preference_strength: str = ""
    route_deliverable_check: dict[str, Any] = field(default_factory=dict)
    adjudication_required: bool = False
    adjudication_reasons: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.winner not in {"A", "B", "tie"}:
            raise ValueError(f"invalid winner: {self.winner}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        dimension_names = frozenset(self.dimensions)
        if dimension_names not in {
            PAIRWISE_V0_DIMENSIONS,
            PAIRWISE_V0_LEGACY_DIMENSIONS,
            PAIRWISE_V1_DIMENSIONS,
            PAIRWISE_V1_LEGACY_DIMENSIONS,
        }:
            raise ValueError("judgment dimensions do not match a supported rubric")
        if any(value not in {"A", "B", "tie"} for value in self.dimensions.values()):
            raise ValueError("dimension winner must be A, B, or tie")
        if self.primary_route and self.primary_route not in {
            "A",
            "B",
            "C",
            "D",
            "E",
            "F",
            "G",
            "H",
            "OTHER",
        }:
            raise ValueError(f"invalid primary route: {self.primary_route}")
        if not 0.0 <= float(self.route_confidence) <= 1.0:
            raise ValueError("route confidence must be between 0 and 1")
        if self.preference_strength not in {"", "slight", "moderate", "strong"}:
            raise ValueError("invalid preference strength")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryResidual:
    residual_id: str
    eval_id: str
    query_id: str
    execution_profile_id: str
    split: str
    nine_dimension_gaps: dict[str, float]
    missing_branch_products: list[str] = field(default_factory=list)
    citation_issues: list[str] = field(default_factory=list)
    gate_issues: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)
    exploratory_only: bool = False

    def validate_for_evolution(self) -> None:
        if self.split == "test":
            raise ValueError("formal Test residuals cannot train harness evolution")
        if self.exploratory_only:
            raise ValueError("exploratory residuals cannot train official evolution")
        unknown = (
            set(self.nine_dimension_gaps)
            - PAIRWISE_V1_DIMENSIONS
            - DEPRECATED_PAIRWISE_DIMENSIONS
        )
        if unknown:
            raise ValueError(f"unknown residual dimensions: {sorted(unknown)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentContributionObservation:
    observation_id: str
    eval_id: str
    query_id: str
    execution_profile_id: str
    agent_id: str
    produced_claim_ids: list[str]
    adopted_by_s_steps: dict[str, list[str]]
    adopted_by_capability_ids: list[str]
    adopted_by_report_sections: list[str]
    critical_path_seconds: float
    model_calls: int
    loao_quality_delta: float | None = None

    @property
    def contributed(self) -> bool:
        return bool(
            self.adopted_by_s_steps
            or self.adopted_by_capability_ids
            or self.adopted_by_report_sections
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessActionObservation:
    observation_id: str
    eval_id: str
    query_id: str
    execution_profile_id: str
    action: Literal["select", "defer", "recall", "backtrack", "rerun", "l4", "stop"]
    target: str
    before_quality: float
    after_quality: float
    elapsed_seconds: float
    new_evidence_count: int = 0
    repeated_residual: bool = False

    @property
    def quality_gain(self) -> float:
        return round(self.after_quality - self.before_quality, 6)

    def should_early_stop(self) -> bool:
        return self.repeated_residual or (
            self.new_evidence_count == 0 and self.quality_gain < 0.03
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "quality_gain": self.quality_gain}


@dataclass(frozen=True)
class TacticValidationTask:
    task_id: str
    query_id: str
    tactic_id: str
    tactic_name: str
    scenario_ids: list[str]
    validation_axes: list[str] = field(
        default_factory=lambda: [
            "public_evidence",
            "feasibility",
            "counter_evidence",
            "technical_boundary",
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResidualCard:
    residual_id: str
    query_id: str
    round_index: int
    target_type: Literal["evidence", "background", "scenario", "s_step", "report_section"]
    target_id: str
    issue: str
    expected_quality_gain: float
    required_new_evidence: bool
    fingerprint: str

    def should_execute(self, prior_fingerprints: set[str]) -> bool:
        return (
            self.round_index <= 3
            and self.fingerprint not in prior_fingerprints
            and self.expected_quality_gain >= 0.03
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpecialistPatch:
    patch_id: str
    execution_profile_id: str
    target: str
    hypothesis: str
    changes: dict[str, Any]
    allowed_change_types: list[str] = field(
        default_factory=lambda: ["routing", "dependency", "prompt", "model_tier", "budget"]
    )
    source_code_change: bool = False

    def validate(self) -> None:
        if self.source_code_change:
            raise ValueError("evolution candidates may not modify source code")
        unknown = set(self.changes) - set(self.allowed_change_types)
        if unknown:
            raise ValueError(f"unsupported challenger changes: {sorted(unknown)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
