"""Declarative Harness v2 branch execution contracts.

The contracts deliberately describe *logical* work.  A physical provider call may
execute a cohort of logical S-agents, but every logical result is still persisted
and exposed independently by the runner/provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Literal, Mapping, Sequence


StepIntensity = Literal["skip", "light", "standard", "deep"]


@dataclass(frozen=True)
class BranchExecutionContract:
    contract_id: str
    branch: str
    logical_agent_dag: dict[str, tuple[str, ...]]
    step_intensity: dict[int, StepIntensity]
    physical_cohorts: tuple[tuple[int, ...], ...]
    branch_products: tuple[str, ...]
    backtrack_map: dict[str, tuple[int, ...]]
    stop_conditions: tuple[str, ...]
    background_count: int | None = None
    scenarios_per_background: tuple[int, int] | None = None
    maximum_rounds: int = 3
    maximum_model_calls: int = 10
    maximum_model_calls_with_residuals: int = 14
    maximum_searches: int = 12
    codex_concurrency: int = 5
    soft_deadline_seconds: int = 1050
    hard_deadline_seconds: int = 1500
    delivery_grace_seconds: int = 900
    absolute_deadline_seconds: int = 2400
    maximum_delivery_model_calls: int = 4
    deadline_downshift_window_seconds: int = 240
    critical_fast_finalize_seconds: int = 120
    delivery_retry_reserve_seconds: int = 45
    fast_finalize_output_token_cap: int = 4200
    schema_version: str = "2.0"

    def validate(self) -> None:
        if self.branch not in set("ABCDEFGH"):
            raise ValueError(f"unsupported branch: {self.branch}")
        if set(self.step_intensity) != set(range(1, 7)):
            raise ValueError("step_intensity must define S1-S6")
        if not 1 <= self.maximum_rounds <= 3:
            raise ValueError("Harness v2 allows one to three rounds")
        if not 0 < self.soft_deadline_seconds <= self.hard_deadline_seconds:
            raise ValueError("soft deadline must be positive and no later than hard deadline")
        if not 0 <= self.delivery_grace_seconds <= 900:
            raise ValueError("delivery grace must be between zero and fifteen minutes")
        if self.absolute_deadline_seconds > 2400:
            raise ValueError("absolute deadline may not exceed 40 minutes")
        if self.hard_deadline_seconds + self.delivery_grace_seconds > self.absolute_deadline_seconds:
            raise ValueError("hard deadline plus delivery grace exceeds absolute deadline")
        if not 1 <= self.maximum_delivery_model_calls <= 4:
            raise ValueError(
                "delivery lane allows an initial draft/repair and one fresh retry/repair"
            )
        if not 30 <= self.deadline_downshift_window_seconds <= 600:
            raise ValueError("deadline downshift window must be between 30 and 600 seconds")
        if not 0 <= self.critical_fast_finalize_seconds <= self.delivery_grace_seconds:
            raise ValueError(
                "critical fast finalize window must fit inside delivery grace"
            )
        if not 0 <= self.delivery_retry_reserve_seconds <= 120:
            raise ValueError("delivery retry reserve must be between zero and 120 seconds")
        if not 1200 <= self.fast_finalize_output_token_cap <= 6000:
            raise ValueError("fast finalize output token cap must be between 1200 and 6000")
        seen: set[int] = set()
        for cohort in self.physical_cohorts:
            if len(cohort) < 2:
                raise ValueError("physical cohorts must contain at least two steps")
            for step in cohort:
                if step not in range(1, 7) or step in seen:
                    raise ValueError("physical cohorts must contain unique S1-S6 steps")
                seen.add(step)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["step_intensity"] = {
            str(key): value for key, value in self.step_intensity.items()
        }
        return payload


@dataclass(frozen=True)
class ExecutionProfile:
    profile_id: str
    harness_version: Literal["legacy_v1", "optimized_v2"]
    agent_mode: str
    branch_contracts: dict[str, BranchExecutionContract]
    model_tiers: dict[str, str]
    prompt_versions: dict[str, str]
    budgets: dict[str, int | float]
    status: Literal["champion", "challenger", "archived"] = "challenger"
    approved: bool = False
    parent_profile_id: str = ""
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "harness_version": self.harness_version,
            "agent_mode": self.agent_mode,
            "branch_contracts": {
                key: value.to_dict() for key, value in self.branch_contracts.items()
            },
            "model_tiers": dict(self.model_tiers),
            "prompt_versions": dict(self.prompt_versions),
            "budgets": dict(self.budgets),
            "status": self.status,
            "approved": self.approved,
            "parent_profile_id": self.parent_profile_id,
            "schema_version": self.schema_version,
            "config_hash": self.config_hash(),
        }

    def config_hash(self) -> str:
        payload = {
            key: value
            for key, value in self.to_dict_without_hash().items()
            if key not in {"status", "approved"}
        }
        return sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def to_dict_without_hash(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "harness_version": self.harness_version,
            "agent_mode": self.agent_mode,
            "branch_contracts": {
                key: value.to_dict() for key, value in self.branch_contracts.items()
            },
            "model_tiers": dict(self.model_tiers),
            "prompt_versions": dict(self.prompt_versions),
            "budgets": dict(self.budgets),
            "status": self.status,
            "approved": self.approved,
            "parent_profile_id": self.parent_profile_id,
            "schema_version": self.schema_version,
        }


_COMMON_STOP_CONDITIONS = (
    "all_required_branch_products_present",
    "accepted_claims_traceable_to_public_sources",
    "no_repeated_residual_without_new_evidence",
    "estimated_quality_gain_below_0.03",
    "hard_deadline_enters_fast_finalize",
)


def _contract(
    branch: str,
    *,
    dag: Mapping[str, Sequence[str]],
    modes: Sequence[StepIntensity],
    cohorts: Sequence[Sequence[int]],
    products: Sequence[str],
    backtrack: Mapping[str, Sequence[int]],
    background_count: int | None = None,
    scenarios_per_background: tuple[int, int] | None = None,
) -> BranchExecutionContract:
    result = BranchExecutionContract(
        contract_id=f"branch-{branch.lower()}-optimized-v2",
        branch=branch,
        logical_agent_dag={
            str(key): tuple(str(item) for item in value) for key, value in dag.items()
        },
        step_intensity={index: value for index, value in enumerate(modes, start=1)},
        physical_cohorts=tuple(tuple(int(item) for item in row) for row in cohorts),
        branch_products=tuple(str(item) for item in products),
        backtrack_map={
            str(key): tuple(int(item) for item in value)
            for key, value in backtrack.items()
        },
        stop_conditions=_COMMON_STOP_CONDITIONS,
        background_count=background_count,
        scenarios_per_background=scenarios_per_background,
    )
    result.validate()
    return result


OPTIMIZED_V2_CONTRACTS: dict[str, BranchExecutionContract] = {
    "A": _contract(
        "A",
        dag={
            "international_situation": (),
            "combat_scenario": ("international_situation",),
            "S1": ("combat_scenario",),
            "S2": ("S1",),
            "tactic_validation": ("S2",),
            "S3": ("tactic_validation",),
            "S4": ("S3",),
            "S5": ("S4",),
            "S6": ("S4", "S5"),
            "reporter": ("S6",),
        },
        modes=("light", "deep", "deep", "standard", "light", "deep"),
        cohorts=((1, 2), (3, 4, 5)),
        products=(
            "three_backgrounds",
            "six_scenarios",
            "three_tactic_concepts",
            "three_tactic_validations",
            "five_tactic_combinations",
            "eight_capability_domains",
            "thirty_capability_indicators",
            "equipment_forms",
        ),
        backtrack={
            "tactic_distinctness": (2, 3, 4, 6),
            "electromagnetic_pressure": (3, 4, 6),
            "capability_mapping": (4, 5, 6),
            "equipment_baseline": (5, 6),
            "report_section": (),
        },
        background_count=3,
        scenarios_per_background=(2, 2),
    ),
    "B": _contract(
        "B",
        dag={
            "international_situation": (),
            "combat_scenario": ("international_situation",),
            "S1": ("combat_scenario",),
            "S2": ("S1",),
            "S3": ("S2",),
            "S4": ("S3",),
            "S5": ("S4",),
            "S6": ("S4", "S5"),
            "reporter": ("S6",),
        },
        modes=("standard", "standard", "standard", "deep", "deep", "deep"),
        cohorts=((1, 2, 3), (4, 5)),
        products=(
            "three_backgrounds",
            "six_to_nine_scenarios",
            "five_level_gap_assessment",
            "requirement_cards",
            "capability_panorama",
            "traceable_deep_report",
        ),
        backtrack={
            "scenario_coverage": (1, 2, 3, 4, 5, 6),
            "capability_mapping": (4, 5, 6),
            "equipment_baseline": (5, 6),
            "priority": (6,),
            "report_section": (),
        },
        background_count=3,
        scenarios_per_background=(2, 3),
    ),
    "C": _contract(
        "C",
        dag={
            "scenario_divergence": (),
            "case_research": ("scenario_divergence",),
            "S3": ("case_research",),
            "S4": ("S3",),
            "S5": ("S4",),
            "S6": ("S4", "S5"),
            "reporter": ("S6",),
        },
        modes=("skip", "skip", "deep", "deep", "standard", "deep"),
        # S3-S5 in one response repeatedly exceeded the reliable structured
        # output envelope in real runs. Keep S3-S4 together and execute S5
        # independently before S6.
        # S3→S4→S5 are a strictly ordered case-transfer chain and share the
        # same evidence packet.  Keeping them in one physical provider turn
        # removes two repeated context builds while preserving three logical
        # results and their independent gates.
        cohorts=((3, 4, 5),),
        products=(
            "case_research_packet",
            "six_case_patterns",
            "three_future_scenarios",
            "four_emerging_equipment_categories",
            "transfer_boundaries",
        ),
        backtrack={
            "case_fact": (3, 4, 5, 6),
            "transfer_boundary": (3, 4, 6),
            "capability_mapping": (4, 5, 6),
            "report_section": (),
        },
    ),
}


for _branch, _modes, _cohorts, _products in (
    ("D", ("skip", "skip", "deep", "deep", "light", "deep"), ((3, 4, 5),), ("technology_driver", "scenario_impact", "capability_need", "equipment_form", "validation_route", "risk_boundary")),
    ("E", ("deep", "skip", "deep", "deep", "standard", "deep"), ((3, 4, 5),), ("opponent_signal", "scenario_impact", "causal_mechanism", "capability_need", "equipment_form", "risk_boundary")),
    ("F", ("skip", "skip", "deep", "deep", "deep", "deep"), ((3, 4, 5),), ("system_driver", "cascade_failure", "replacement_chain", "capability_need", "equipment_form", "validation_route")),
    ("G", ("skip", "skip", "deep", "deep", "skip", "deep"), ((3, 4),), ("cross_domain_driver", "interface_gap", "causal_mechanism", "capability_need", "equipment_form", "validation_route")),
    ("H", ("deep", "skip", "deep", "deep", "skip", "deep"), ((3, 4),), ("security_driver", "scenario_impact", "capability_need", "equipment_form", "legal_ethical_boundary", "civil_military_boundary")),
):
    OPTIMIZED_V2_CONTRACTS[_branch] = _contract(
        _branch,
        dag={"driver_agent": (), "S3": ("driver_agent",), "S4": ("S3",), "S6": ("S4",), "reporter": ("S6",)},
        modes=_modes,
        cohorts=_cohorts,
        products=_products,
        backtrack={"driver": (3, 4, 6), "mapping": (4, 5, 6), "report_section": ()},
    )


def optimized_v2_profile() -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="optimized_v2",
        harness_version="optimized_v2",
        agent_mode="branch_contract_with_physical_cohorts",
        branch_contracts=dict(OPTIMIZED_V2_CONTRACTS),
        model_tiers={
            "business_required": "quality",
            "business_reference": "balanced",
            "S2-S6": "quality",
            "reporter": "quality",
        },
        prompt_versions={
            "chief": "branch-contract-v2",
            "winning": "winning-cohort-v2",
            "reporter": "branch-report-v2",
        },
        budgets={
            "normal_model_calls": 10,
            "residual_model_calls": 14,
            "searches": 12,
            "codex_concurrency": 5,
            "soft_deadline_seconds": 1050,
            "hard_deadline_seconds": 1500,
            "delivery_grace_seconds": 900,
            "absolute_deadline_seconds": 2400,
            "maximum_delivery_model_calls": 4,
            "deadline_downshift_window_seconds": 240,
            "critical_fast_finalize_seconds": 120,
            "delivery_retry_reserve_seconds": 45,
            "fast_finalize_output_token_cap": 4200,
            "max_rounds": 3,
        },
        status="challenger",
        approved=False,
        parent_profile_id="legacy_v1",
    )


def resolve_execution_profile(profile_id: str | None) -> ExecutionProfile | None:
    if not profile_id or profile_id == "legacy_v1":
        return None
    if profile_id == "optimized_v2":
        return optimized_v2_profile()
    raise ValueError(f"unknown execution profile: {profile_id}")


def apply_execution_profile_to_blueprint(
    blueprint: Mapping[str, Any],
    profile: ExecutionProfile | None,
) -> dict[str, Any]:
    result = dict(blueprint)
    if profile is None:
        result.setdefault("execution_profile_id", "legacy_v1")
        return result
    branch = str(result.get("primary_branch", "A"))
    contract = profile.branch_contracts[branch]
    result["execution_profile_id"] = profile.profile_id
    result["execution_profile_hash"] = profile.config_hash()
    result["execution_contract"] = contract.to_dict()
    result["baseline_execution_mode"] = "query_dominant_isolated_parallel"
    result["minimum_business_agents"] = 3
    result["maximum_business_agents"] = 4
    result["adaptive_winning_step_modes"] = {
        str(step): mode for step, mode in contract.step_intensity.items()
    }
    result["hard_dependencies"] = {
        node: list(dependencies)
        for node, dependencies in contract.logical_agent_dag.items()
        if not node.startswith("S") and node != "reporter"
    }
    result["loop_policy"] = {
        **dict(result.get("loop_policy", {})),
        "outer_max_rounds": contract.maximum_rounds,
        "residual_only_after_first_round": True,
        "minimum_expected_gain": 0.03,
    }
    result["runtime_budgets"] = {
        "maximum_model_calls": contract.maximum_model_calls,
        "maximum_model_calls_with_residuals": contract.maximum_model_calls_with_residuals,
        "maximum_searches": contract.maximum_searches,
        "codex_concurrency": contract.codex_concurrency,
        "soft_deadline_seconds": contract.soft_deadline_seconds,
        "hard_deadline_seconds": contract.hard_deadline_seconds,
        "delivery_grace_seconds": contract.delivery_grace_seconds,
        "absolute_deadline_seconds": contract.absolute_deadline_seconds,
        "maximum_delivery_model_calls": contract.maximum_delivery_model_calls,
        "deadline_downshift_window_seconds": contract.deadline_downshift_window_seconds,
        "critical_fast_finalize_seconds": contract.critical_fast_finalize_seconds,
        "delivery_retry_reserve_seconds": contract.delivery_retry_reserve_seconds,
        "fast_finalize_output_token_cap": contract.fast_finalize_output_token_cap,
    }
    return result


__all__ = [
    "BranchExecutionContract",
    "ExecutionProfile",
    "OPTIMIZED_V2_CONTRACTS",
    "optimized_v2_profile",
    "resolve_execution_profile",
    "apply_execution_profile_to_blueprint",
]
