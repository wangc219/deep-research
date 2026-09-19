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

from equipment_deep_research.orchestration.winning_swarm import (
    normalize_winning_swarm_policy,
)
from equipment_deep_research.domain.capability_portrait import (
    S6_DEFAULT_CODEX_CONCURRENCY,
)


StepIntensity = Literal["skip", "light", "standard", "deep"]
QUALITY_EXECUTION_PROFILE_IDS = frozenset(
    {"optimized_v2", "swarm_quality_v1", "winning_swarm_dynamic_v2"}
)


def is_quality_execution_profile_id(value: Any) -> bool:
    return str(value or "") in QUALITY_EXECUTION_PROFILE_IDS


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
    wall_clock_deadlines_enabled: bool = False
    soft_deadline_seconds: int = 0
    # Real completeness runs have no wall-clock soft, hard, or absolute stop.
    # Model-call budgets and bounded concurrency still prevent unbounded work.
    hard_deadline_seconds: int = 0
    delivery_grace_seconds: int = 0
    absolute_deadline_seconds: int = 0
    maximum_delivery_model_calls: int = 8
    maximum_swarm_model_calls: int = 20
    maximum_quality_judge_model_calls: int = 2
    deadline_downshift_window_seconds: int = 240
    critical_fast_finalize_seconds: int = 0
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
        if self.wall_clock_deadlines_enabled and not (
            0 < self.soft_deadline_seconds <= self.hard_deadline_seconds
        ):
            raise ValueError("soft deadline must be positive and no later than hard deadline")
        if not 0 <= self.delivery_grace_seconds <= 900:
            raise ValueError("delivery grace must be between zero and fifteen minutes")
        if self.wall_clock_deadlines_enabled and self.absolute_deadline_seconds > 2400:
            raise ValueError("absolute deadline may not exceed 40 minutes")
        if self.wall_clock_deadlines_enabled and (
            self.hard_deadline_seconds + self.delivery_grace_seconds
            > self.absolute_deadline_seconds
        ):
            raise ValueError("hard deadline plus delivery grace exceeds absolute deadline")
        if not 1 <= self.maximum_delivery_model_calls <= 8:
            raise ValueError(
                "delivery lane must cover the selected template's parallel sections"
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
            "codex_concurrency": 8,
            # Internal S6 card calls share this one run; they do not consume
            # additional research Worker slots.
            "s6_codex_concurrency": S6_DEFAULT_CODEX_CONCURRENCY,
            # Final report authoring is split by H3 column (12 project columns,
            # 9 three-layer columns).  This ceiling is activated only for the
            # Reporter wave and restored before returning to the shared gate.
            "reporter_codex_concurrency": 12,
            "wall_clock_deadlines_enabled": False,
            "soft_deadline_seconds": 0,
            "hard_deadline_seconds": 0,
            "delivery_grace_seconds": 0,
            "absolute_deadline_seconds": 0,
            "maximum_delivery_model_calls": 8,
            # Twelve single-column calls form the largest initial wave.  Keep
            # one targeted primary repair and one fallback slot per column;
            # completed columns are never replayed.
            "maximum_reporter_model_calls": 36,
            "deadline_downshift_window_seconds": 240,
            "critical_fast_finalize_seconds": 0,
            "delivery_retry_reserve_seconds": 45,
            "fast_finalize_output_token_cap": 4200,
            "max_rounds": 3,
        },
        status="challenger",
        approved=False,
        parent_profile_id="legacy_v1",
    )


def swarm_quality_v1_profile() -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="swarm_quality_v1",
        harness_version="optimized_v2",
        agent_mode="bounded_elastic_winning_swarm",
        branch_contracts=dict(OPTIMIZED_V2_CONTRACTS),
        model_tiers={
            "business_required": "quality",
            "business_reference": "balanced",
            "winning_swarm": "quality",
            "S1-S6": "quality",
            "independent_reviewer": "quality",
            "reporter": "quality",
        },
        prompt_versions={
            "chief": "branch-contract-v2",
            "winning": "winning-swarm-quality-v1",
            "reporter": "branch-report-v2",
        },
        budgets={
            **dict(optimized_v2_profile().budgets),
            "max_dynamic_instances": 12,
            "max_swarm_concurrency": 6,
            "max_swarm_waves": 3,
            "minimum_expected_gain": 0.03,
        },
        status="challenger",
        approved=False,
        parent_profile_id="legacy_v1",
    )


def winning_swarm_dynamic_v2_profile() -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="winning_swarm_dynamic_v2",
        harness_version="optimized_v2",
        agent_mode="mission_graph_dynamic_winning_swarm",
        branch_contracts=dict(OPTIMIZED_V2_CONTRACTS),
        model_tiers={
            "business_required": "quality",
            "business_reference": "balanced",
            "winning_mission_graph": "quality",
            "S1-S6_seed_instances": "quality",
            "dynamic_specialists": "quality",
            "independent_reviewer": "quality",
            "reporter": "quality",
        },
        prompt_versions={
            "chief": "branch-contract-v2",
            "winning": "winning-mission-graph-v2",
            "reporter": "branch-report-v2",
        },
        budgets={
            **dict(optimized_v2_profile().budgets),
            # Four S1/S2 seeds and up to eight independent S3/S4 creators are
            # dependency-safe. Let the dynamic run use eight internal model
            # lanes without consuming additional research Worker slots.
            "codex_concurrency": 8,
            "s6_codex_concurrency": S6_DEFAULT_CODEX_CONCURRENCY,
            "max_dynamic_instances": 21,
            "min_mission_graph_instances": 8,
            "target_mission_graph_instances": 10,
            "max_swarm_concurrency": 8,
            "max_swarm_waves": 3,
            "minimum_expected_gain": 0.03,
        },
        status="challenger",
        approved=False,
        parent_profile_id="swarm_quality_v1",
        schema_version="2.0",
    )


def deep_divergence_v1_profile() -> ExecutionProfile:
    """Bounded S3/S4/S6-only workflow used by expert deep research.

    It intentionally skips S1/S2/S5 reruns and caps the open innovation
    lanes at three S3 and three S4 candidates.  The parent run supplies the
    canonical query/evidence snapshot and any retrieval escalation happens
    inside the deep job.
    """
    contracts = {
        branch: _contract(
            branch,
            dag={"S3": ("context",), "S4": ("S3",), "S6": ("S4",)},
            modes=("skip", "skip", "deep", "deep", "skip", "deep"),
            cohorts=((3, 4), (5, 6)),
            products=("DeepDivergenceCandidates", "DeepCapabilityVersion"),
            backtrack={"S3": (3,), "S4": (3, 4), "S6": (4, 6)},
        ) for branch in "ABCDEFGH"
    }
    return ExecutionProfile(
        profile_id="deep_divergence_v1",
        harness_version="optimized_v2",
        agent_mode="deep_divergence_contextual",
        branch_contracts=contracts,
        model_tiers={"S3": "quality", "S4": "quality", "S6": "quality"},
        prompt_versions={"deep": "deep-divergence-v1"},
        budgets={"max_s3_slots": 3, "max_s4_slots": 3, "max_candidates": 6, "max_searches": 6, "max_concurrency": 6},
        status="challenger", approved=False, parent_profile_id="winning_swarm_dynamic_v2", schema_version="1.0",
    )


def resolve_execution_profile(profile_id: str | None) -> ExecutionProfile | None:
    if not profile_id or profile_id == "legacy_v1":
        return None
    if profile_id == "optimized_v2":
        return optimized_v2_profile()
    if profile_id == "swarm_quality_v1":
        return swarm_quality_v1_profile()
    if profile_id == "winning_swarm_dynamic_v2":
        return winning_swarm_dynamic_v2_profile()
    if profile_id == "deep_divergence_v1":
        return deep_divergence_v1_profile()
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
    runtime_codex_concurrency = int(
        profile.budgets.get("codex_concurrency", contract.codex_concurrency)
    )
    result["execution_profile_id"] = profile.profile_id
    result["execution_profile_hash"] = profile.config_hash()
    result["execution_contract"] = contract.to_dict()
    result["execution_contract"]["codex_concurrency"] = runtime_codex_concurrency
    result["baseline_execution_mode"] = "query_dominant_isolated_parallel"
    if profile.profile_id == "winning_swarm_dynamic_v2":
        # Baseline Agents only establish public boundaries for the dynamic
        # S1-S6 swarm.  Two or three complementary lanes fit the common
        # provider pool without making a fourth/fifth evidence lane the
        # critical path before creative reasoning can start.
        result["minimum_business_agents"] = 2
        result["maximum_business_agents"] = 3
    else:
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
    swarm_policy = dict(result.get("winning_swarm_policy", {}))
    if profile.profile_id == "winning_swarm_dynamic_v2":
        swarm_policy.update(
            {
                "policy_id": "winning_swarm_dynamic_v2",
                "max_dynamic_instances": 21,
                "max_concurrency": 8,
                "mission_graph_min_instances": 8,
                # Heterogeneous first wave: complementary S1/S2, unique
                # creative scouts, and 2-3 cross-pool S5 reviewers. Remaining
                # capacity up to max_instances is for Gap Analyzer recruitment.
                "mission_graph_target_instances": 10,
                "mission_graph_max_instances": 21,
                "s3_winning_thesis_capacity": 4,
                "coverage_expand_max_recruits": 2,
                "breadth_hypothesis_maximum": 18,
                "s3_empty_reallocation_max": 2,
                "s3_s4_candidate_maximum_per_session": 3,
                "s3_s4_candidate_pool_maximum_per_session": 3,
                # S5 is an innovation-first cut. The historical six-card value
                # remains a dashboard preference only; admission has no floor,
                # and rejected ordinary upgrades are never resurrected merely
                # to fill the seven-card ceiling.
                "finalist_minimum": 6,
                "finalist_maximum": 7,
                "minimum_direct_combat_equipment": 2,
                "preferred_distinct_direct_equipment": 3,
                "expert_candidate_pool_maximum": 0,
                "expert_judge_enabled": False,
                "expert_judge_required": False,
                "foresight_first_enabled": True,
                "frontier_evidence_relaxation": True,
                "frontier_final_gate_minimum_score": 0.62,
                "frontier_expert_judge_minimum_score": 0.66,
                "frontier_critical_dimension_minimum": 0.50,
                "expert_judge_minimum_score": 0.68,
                "expert_judge_critical_dimension_minimum": 0.52,
                "pending_verification_backfill_enabled": False,
                "pending_verification_minimum_score": 0.54,
                "pending_verification_critical_dimension_minimum": 0.42,
                "expert_repair_enabled": False,
                "expert_repair_max_candidates": 0,
                "expert_repair_reserved_instances": 0,
                "expert_repair_minimum_score": 0.64,
            }
        )
    elif profile.profile_id == "swarm_quality_v1":
        # The bounded three-wave cluster uses the same substantive acceptance
        # standard as dynamic v2.  Its simpler scheduler is not permission to
        # skip independent judgement or to cap the portfolio at a historical
        # four-card quota.
        swarm_policy.update(
            {
                "policy_id": "swarm_quality_v1",
                "finalist_minimum": 5,
                "finalist_maximum": 7,
                "minimum_direct_combat_equipment": 3,
                "preferred_distinct_direct_equipment": 5,
                "expert_candidate_pool_maximum": 12,
                "expert_judge_enabled": True,
                "expert_judge_required": True,
                "foresight_first_enabled": True,
                "frontier_evidence_relaxation": True,
                "frontier_final_gate_minimum_score": 0.62,
                "frontier_expert_judge_minimum_score": 0.66,
                "frontier_critical_dimension_minimum": 0.50,
                "expert_judge_minimum_score": 0.68,
                "expert_judge_critical_dimension_minimum": 0.52,
                "pending_verification_backfill_enabled": True,
                "pending_verification_minimum_score": 0.54,
                "pending_verification_critical_dimension_minimum": 0.42,
                "expert_repair_enabled": True,
                "expert_repair_max_candidates": 4,
                "expert_repair_reserved_instances": 4,
                "expert_repair_minimum_score": 0.64,
            }
        )
    result["winning_swarm_policy"] = normalize_winning_swarm_policy(
        swarm_policy,
        enabled=profile.profile_id in {"swarm_quality_v1", "winning_swarm_dynamic_v2"},
    )
    result["runtime_budgets"] = {
        "maximum_model_calls": contract.maximum_model_calls,
        "maximum_model_calls_with_residuals": contract.maximum_model_calls_with_residuals,
        "maximum_searches": contract.maximum_searches,
        "codex_concurrency": runtime_codex_concurrency,
        "s6_codex_concurrency": int(
            profile.budgets.get(
                "s6_codex_concurrency",
                S6_DEFAULT_CODEX_CONCURRENCY,
            )
        ),
        "reporter_codex_concurrency": int(
            profile.budgets.get("reporter_codex_concurrency", 12)
        ),
        "wall_clock_deadlines_enabled": contract.wall_clock_deadlines_enabled,
        "soft_deadline_seconds": contract.soft_deadline_seconds,
        "hard_deadline_seconds": contract.hard_deadline_seconds,
        "delivery_grace_seconds": contract.delivery_grace_seconds,
        "absolute_deadline_seconds": contract.absolute_deadline_seconds,
        "maximum_delivery_model_calls": contract.maximum_delivery_model_calls,
        "maximum_reporter_model_calls": int(
            profile.budgets.get(
                "maximum_reporter_model_calls",
                max(contract.maximum_delivery_model_calls, 36),
            )
        ),
        "maximum_swarm_model_calls": contract.maximum_swarm_model_calls,
        "maximum_quality_judge_model_calls": contract.maximum_quality_judge_model_calls,
        "deadline_downshift_window_seconds": contract.deadline_downshift_window_seconds,
        "critical_fast_finalize_seconds": contract.critical_fast_finalize_seconds,
        "delivery_retry_reserve_seconds": contract.delivery_retry_reserve_seconds,
        "fast_finalize_output_token_cap": contract.fast_finalize_output_token_cap,
    }
    if profile.profile_id == "deep_divergence_v1":
        # The deep profile owns a smaller child budget than the ordinary
        # branch contract.  Persist its limits into the runtime budget so
        # search reservation and run-scoped call gates enforce the declared
        # six-query/six-slot envelope rather than inheriting legacy defaults.
        result["runtime_budgets"].update(
            {
                "maximum_searches": int(profile.budgets.get("max_searches", 6)),
                "codex_concurrency": int(profile.budgets.get("max_concurrency", 6)),
                "max_searches": int(profile.budgets.get("max_searches", 6)),
                "max_concurrency": int(profile.budgets.get("max_concurrency", 6)),
            }
        )
    if profile.profile_id == "winning_swarm_dynamic_v2":
        # Dynamic-v2 has no quality-judge call budget. S5 incremental portfolio
        # review is accounted within the ordinary swarm model-call ceiling.
        result["runtime_budgets"].update(
            {
                # Compact first wave plus one or two coverage recruits, a
                # selector, clustering and 2-3 cross-pool S5 reviewers.
                "maximum_swarm_model_calls": 40,
                # S6 owns a separate call ceiling so upstream recruitment
                # cannot starve the five-column authoring wave.
                "maximum_s6_model_calls": 80,
                "maximum_quality_judge_model_calls": 0,
            }
        )
    return result


__all__ = [
    "BranchExecutionContract",
    "ExecutionProfile",
    "OPTIMIZED_V2_CONTRACTS",
    "QUALITY_EXECUTION_PROFILE_IDS",
    "is_quality_execution_profile_id",
    "optimized_v2_profile",
    "swarm_quality_v1_profile",
    "winning_swarm_dynamic_v2_profile",
    "deep_divergence_v1_profile",
    "resolve_execution_profile",
    "apply_execution_profile_to_blueprint",
]
