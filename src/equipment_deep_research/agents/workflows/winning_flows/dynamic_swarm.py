"""Dynamic-v2 Mission Graph: S1/S2 seeds, S3/S4 creation and S5 portfolio selection."""
# ruff: noqa: F841

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from contextlib import nullcontext
from dataclasses import replace
from hashlib import (
    sha256,
)
from time import (
    monotonic,
)
from typing import (
    Any,
)

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
    load_dynamic_winning_prompt,
)
from equipment_deep_research.agents.workflows.coordinator import (
    _compact_equipment_portfolio_event,
    _compact_prompt_value,
    _compact_swarm_candidate_handoff,
    _compact_swarm_event_summary,
    _parse_json_object,
    _query_combat_equipment_divergence_brief,
    _query_domain_contract,
    _query_led_combat_equipment_theme_contract,
    _swarm_runtime_audit_contract,
    _swarm_session_ref,
)
from equipment_deep_research.agents.workflows.reporting_support import (
    _is_remote_precision_portfolio_direction,
    _winning_portfolio_title,
    _winning_primary_equipment_form,
)
from equipment_deep_research.agents.workflows.s6_quality import (
    _capability_text_similarity,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _dynamic_portfolio_innovation_priority,
    _dynamic_role_contract_handoff,
    _minimal_portfolio_candidate_handoff,
    _open_s3_exploration_brief,
    _open_s3_theme_contract,
    _s3_s4_name_authoring_issues,
    _s3_s4_dimension_catalog,
    _canonical_dimension_identity,
    _dimension_marker_text,
    _s3_s4_dimension_pack_for,
    _s3_s4_open_dimension_slots,
    _s3_s4_resolve_authored_dimension,
    _s5_diverse_portfolio_order,
    _s5_dimension_scores,
    _s5_disruption_tier_rank,
    _s5_innovation_basis,
    _s5_merge_target_is_valid,
    _s5_naming_assessment,
    _s5_portfolio_fallback_result,
    _s5_retain_passes_concrete_weapon_contract,
    _targeted_expert_feedback,
)
from equipment_deep_research.agents.workflows.winning_flows.naming import (
    NAMING_ASSIGNMENT_VERSION,
    build_s3_s4_naming_plan,
)
from equipment_deep_research.domain.models import (
    HypothesisLedgerVersion,
    MergeReceipt,
    PortfolioDecision,
    SpecialistTask,
    WinningAgentInstance,
    WinningContribution,
    WinningHypothesis,
    to_plain,
)
from equipment_deep_research.domain.swarm_strategy import (
    assign_scout_mission,
    build_coverage_snapshot,
    compact_coverage_for_review,
    decide_adaptive_action,
    gap_axis_from_residuals,
    resolve_dynamic_v2_instance_bounds,
    SwarmState,
)
from equipment_deep_research.orchestration.winning_swarm import (
    WinningSwarmController,
    winning_summary_language_issues,
)

from equipment_deep_research.contracts.runtime import SwarmRuntime


def _dynamic_output_schema(section: str) -> dict[str, Any]:
    """Load a model-visible output schema from the reviewed Markdown catalog."""

    value = load_dynamic_winning_json("common", section=section)
    if not isinstance(value, Mapping):
        raise ValueError(f"dynamic output schema must be an object: {section}")
    return dict(value)


def _s3_s4_structural_dimension_identities(value: Any) -> set[str]:
    """Extract distinct model-declared dimensions for the creative stop gate.

    This is intentionally a structural check only.  It does not judge whether
    a relation is militarily strong; S5 remains the semantic admission gate.
    Controller transport markers (``OPEN-*``/``AUTO``/slot ids) are ignored,
    while arbitrary model-authored ids and ``OTHER:<id>`` relations are kept.
    """

    def is_transport_marker(raw: Any) -> bool:
        token = _dimension_marker_text(raw)
        if not token:
            return False
        marker = token.casefold().replace(" ", "")
        if "::open-dimension::" in marker:
            return True
        return marker in {
            "open",
            "open_slot",
            "open-slot",
            "auto",
            "dynamic",
            "dynamic-open",
            "dynamic_open",
            "dynamicopen",
            "query开放制胜维度",
        } or bool(
            re.match(r"^query开放制胜(?:槽位|维度)\d*$", marker)
        ) or bool(
            re.match(
                r"^open(?:[_-]?slot)?[-_:][a-z0-9]{4,}(?:[-_:][a-z0-9]+)*$",
                marker,
            )
        )

    def identity(raw: Any) -> str:
        fallback_label = ""
        if isinstance(raw, Mapping):
            code = str(
                raw.get("dimension_code")
                or raw.get("code")
                or raw.get("winning_dimension_code")
                or ""
            ).strip()
            label = str(
                raw.get("combat_dimension")
                or raw.get("label")
                or raw.get("dimension")
                or ""
            ).strip()
            angle = str(
                raw.get("winning_angle_id")
                or raw.get("angle_id")
                or ""
            ).strip()
            if code and not is_transport_marker(code):
                raw, fallback_label = code, label
            elif label and not is_transport_marker(label):
                raw = label
            elif (
                angle
                and (
                    "::" in angle
                    or angle.casefold().startswith("self-proposed:")
                )
                and not is_transport_marker(angle)
            ):
                raw = angle.rsplit("::", 1)[-1]
            else:
                raw = ""
        token = _dimension_marker_text(raw)
        if not token or is_transport_marker(token):
            return ""
        pack = _s3_s4_dimension_pack_for(token)
        if pack is not None:
            return str(pack.get("code", "")).strip().casefold()
        return _canonical_dimension_identity(token, fallback=fallback_label).strip()

    values = value if isinstance(value, (list, tuple, set)) else [value]
    return {
        normalized
        for item in values
        if (normalized := identity(item))
    }


def _s3_s4_first_pass_structurally_complete(
    parsed: Mapping[str, Any] | None,
    candidate_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[bool, set[str]]:
    """Return the structural early-stop result for one creative pass.

    ``True`` means at least one candidate has the compact required fields and
    the model declared/adopted three distinct dimensions.  This helper does
    not score quality or decide admission; those decisions remain in S5.
    """

    payload = parsed if isinstance(parsed, Mapping) else {}
    rows = list(candidate_rows or [])
    if not rows:
        raw_rows = payload.get("hypotheses", [])
        if isinstance(raw_rows, list):
            rows = [
                item
                for item in raw_rows
                if isinstance(item, Mapping)
                and str(item.get("name", "") or item.get("title", "")).strip()
                and str(item.get("concise_winning_summary", "")).strip()
            ]
    declarations: list[Any] = []
    considered = payload.get("considered_dimensions", [])
    if isinstance(considered, list):
        declarations.extend(considered)
    selections = payload.get("dimension_selections", [])
    if isinstance(selections, list):
        declarations.extend(selections)
    for row in rows:
        if any(
            str(row.get(key, "")).strip()
            for key in ("dimension_code", "combat_dimension", "winning_angle_id")
        ):
            declarations.append(row)
    identities = _s3_s4_structural_dimension_identities(declarations)
    return bool(rows) and len(identities) >= 3, identities


async def execute_dynamic_mission_graph(
    *,
    accumulated: dict[str, Any],
    baseline_boundaries: Sequence[str],
    cluster_hypotheses_with_independent_codex: Callable[..., Any],
    creative_military_value_handoff: Callable[..., Any],
    emit_swarm_event: Callable[..., Any],
    host: SwarmRuntime,
    primary_branch: str,
    runs: list[dict[str, Any]],
    shared: Mapping[str, Any],
    state: SwarmState,
    swarm_controller: WinningSwarmController,
    valid_reference_ids: set[str],
) -> None:
    """Execute the v2 S1-S6 role graph as isolated, dependency-ready turns.

    Unlike ``swarm_quality_v1`` this path does not run one fixed Codex
    turn for each S node.  Every graph instance is a governed role and
    every model turn receives only the immutable candidate-ledger
    snapshot available when it starts.  Commits are serialized locally;
    stale contributions are explicitly rebased before they can merge.
    """

    # Dynamic-v2 has no reserved legacy repair or quality-judge capacity.
    repair_reserve = 0
    bounds = resolve_dynamic_v2_instance_bounds(
        minimum_instances=swarm_controller.policy.get(
            "mission_graph_min_instances", 8
        ),
        target_instances=swarm_controller.policy.get(
            "mission_graph_target_instances", 10
        ),
        maximum_instances=swarm_controller.policy.get(
            "mission_graph_max_instances", 21
        ),
        hard_maximum_instances=swarm_controller.policy.get(
            "max_dynamic_instances", 21
        ),
        reserved_instances=repair_reserve,
    )
    target_instances = bounds.target_instances
    graph = swarm_controller.build_mission_graph(
        topic=str(shared["topic"]),
        execution_profile_id=str(shared["execution_profile_id"]),
        target_instances=target_instances,
        query_theses=(
            shared.get("structured_query_brief", {}).get(
                "equipment_project_hypotheses", []
            )
            if isinstance(shared.get("structured_query_brief", {}), Mapping)
            else []
        ),
    )
    query_domain = _query_domain_contract(
        str(shared.get("topic", "")),
        structured_query_brief=(
            shared.get("structured_query_brief", {})
            if isinstance(shared.get("structured_query_brief", {}), Mapping)
            else {}
        ),
    )
    contracts = {item.role_contract_id: item for item in graph.role_contracts}
    completed_instances: set[str] = set()
    failed_instances: set[str] = set()
    pending = {item.instance_id: item for item in graph.agent_instances}
    hypotheses: list[WinningHypothesis] = []
    ledger: HypothesisLedgerVersion | None = None
    merge_receipts: list[MergeReceipt] = []
    contribution_rows: list[WinningContribution] = []
    execution_batches: list[dict[str, Any]] = []
    maximum_observed_concurrency = 0
    instance_hypothesis_ids: dict[str, set[str]] = {}
    reasoning_seeds_by_instance: dict[str, list[dict[str, Any]]] = {}
    winning_angle_assignments: dict[str, dict[str, Any]] = {}
    # Auditable trace of the dimensions each creative seat was allowed to
    # compare.  The primary lane is retained for compatibility, while this
    # map proves that every seat received a genuinely multi-dimensional
    # exploration surface.
    seat_dimension_traces: dict[str, list[str]] = {}
    seat_realized_dimensions: dict[str, set[str]] = {}
    query_equipment_blueprint: dict[str, Any] = {}
    winning_angle_refresh_task: asyncio.Task[None] | None = None
    candidate_id_aliases: dict[str, str] = {}
    portfolio_rejected_ids: set[str] = set()
    reviewed_candidate_ids: set[str] = set()
    candidate_innovation_priorities: dict[str, float] = {}
    candidate_innovation_bases: dict[str, str] = {}
    candidate_dimension_scores: dict[str, dict[str, float]] = {}
    candidate_weighted_scores: dict[str, float] = {}
    candidate_naming_assessments: dict[str, dict[str, Any]] = {}
    candidate_disruption_tiers: dict[str, str] = {}
    candidate_displaced_modes: dict[str, str] = {}
    candidate_new_operational_modes: dict[str, str] = {}
    candidate_winning_relation_shifts: dict[str, str] = {}
    portfolio_order_hints: dict[str, int] = {}
    portfolio_order_sequence = 0
    pending_incremental_review_ids: set[str] = set()
    review_targets_by_instance: dict[str, set[str]] = {}
    semantic_clustered_ledger_version = -1
    # Close-out clustering is deliberately recorded separately from the
    # per-seat S5 decisions.  The latter decide innovation/portfolio
    # admission; this pass only removes cross-seat same-thesis variants.
    semantic_cluster_audit: dict[str, Any] = {
        "scope_id": "",
        "candidate_count_before": 0,
        "candidate_count_after": 0,
        "merged_count": 0,
        "merge_map": {},
        "representative_selection": (
            "最高S5加权综合分；同分时沿用候选账本分数、证据数和稳定ID"
        ),
        "status": "not_run",
    }
    s3_active_instances_materialized = False
    coverage_recruitment_used = 0
    previous_coverage_cluster_keys: tuple[str, ...] = ()
    # Adaptive recruitment is stateful across scheduler ticks.  Without a
    # signature guard, observing the same ledger repeatedly would look like
    # repeated low novelty and either stop too early or, worse, trigger a
    # duplicate recruit before the first S5 review starts.
    last_coverage_signature: tuple[tuple[str, str], ...] = ()
    consecutive_low_novelty = 0
    coverage_recruitment_cutoff = False
    # S4 is allowed to start as soon as one S3 branch has published (or
    # irrecoverably failed).  This keeps the read-only S3 boundary useful
    # without idling the remaining concurrency slots behind a full S3
    # barrier.  The final S5/semantic-cluster passes remain authoritative for
    # cross-seat duplicate removal.
    s4_incremental_boundary_opened = False
    initial_expert_review_scope: set[str] | None = None
    dynamic_instance_retry_counts: dict[str, int] = {}
    s5_fallback_activated = False
    s5_fallback_reason = ""
    running_instances: dict[
        asyncio.Task[tuple[WinningAgentInstance, dict[str, Any], int]],
        tuple[WinningAgentInstance, set[str], int],
    ] = {}
    running_started_at: dict[asyncio.Task[Any], float] = {}

    def _remaining_swarm_budget(
        graph_capacity: int,
    ) -> dict[str, int | float | None]:
        """Read the live host budget without making the strategy layer stateful.

        The mission graph bounds logical seats, while the provider runtime
        counts actual attempts (including retries).  Recruitment must honor
        the tighter of those two ceilings.  Test hosts and embedded callers
        may not expose a runtime budget; in that case the graph capacity is
        the only authoritative bound.
        """

        budgets = getattr(host, "_runtime_budgets", {})
        if not isinstance(budgets, Mapping):
            budgets = {}
        lock = getattr(host, "_budget_lock", None)
        lock_context = lock if lock is not None else nullcontext()
        with lock_context:
            try:
                used_calls = int(
                    getattr(host, "_budget_started_swarm_calls", 0) or 0
                )
            except (TypeError, ValueError):
                used_calls = 0
            try:
                used_tokens = int(
                    getattr(host, "_budget_consumed_swarm_tokens", 0) or 0
                )
            except (TypeError, ValueError):
                used_tokens = 0
            configured_calls = budgets.get("maximum_swarm_model_calls")
            token_limit = next(
                (
                    budgets.get(key)
                    for key in (
                        "maximum_swarm_tokens",
                        "max_swarm_tokens",
                        "swarm_token_budget",
                    )
                    if budgets.get(key) is not None
                ),
                None,
            )
        try:
            remaining_calls = (
                max(0, int(configured_calls) - used_calls)
                if configured_calls is not None
                else graph_capacity
            )
        except (TypeError, ValueError):
            remaining_calls = graph_capacity
        try:
            remaining_tokens = (
                max(0.0, float(token_limit) - used_tokens)
                if token_limit is not None
                else None
            )
        except (TypeError, ValueError):
            remaining_tokens = None

        remaining_time: float | None = None
        deadline_reader = getattr(host, "_deadline_state", None)
        if callable(deadline_reader):
            try:
                deadline = deadline_reader(priority="swarm")
            except Exception:
                deadline = None
            if isinstance(deadline, Mapping) and deadline.get("enabled"):
                raw_remaining = deadline.get("remaining_seconds")
                try:
                    remaining_time = max(0.0, float(raw_remaining))
                except (TypeError, ValueError):
                    remaining_time = None
        return {
            # Keep the provider-wide remainder separate from graph capacity;
            # the controller subtracts mandatory pending seats before deciding
            # whether one more creator can be recruited.
            "remaining_calls": remaining_calls,
            "graph_capacity": graph_capacity,
            "remaining_tokens": remaining_tokens,
            "remaining_time": remaining_time,
            "used_calls": used_calls,
            "used_tokens": used_tokens,
        }

    def creative_producer_instances() -> list[WinningAgentInstance]:
        """Interleave S3/S4 so either group can receive active dimensions."""

        by_node = {
            node: [
                item
                for item in graph.agent_instances
                if item.mission_node == node and not item.hypothesis_id
            ]
            for node in ("S3", "S4")
        }
        rows: list[WinningAgentInstance] = []
        for index in range(max((len(value) for value in by_node.values()), default=0)):
            for node in ("S3", "S4"):
                if index < len(by_node[node]):
                    rows.append(by_node[node][index])
        return rows

    def _naming_candidate_count() -> int:
        """Resolve the bounded per-seat naming slots from the dynamic policy."""

        try:
            configured = int(
                swarm_controller.policy.get(
                    "s3_s4_candidate_maximum_per_session", 3
                )
            )
        except (TypeError, ValueError):
            configured = 3
        # Dynamic-v2's public contract is one-to-three candidates per seat.
        return max(1, min(3, configured))

    def _naming_plan_seed() -> str:
        # Include only durable run/graph identity.  In particular, do not
        # include batch, retry or creative-iteration counters: those are
        # execution details and must not reshuffle a resumed seat.
        return "|".join(
            (
                "s3-s4-naming-plan-v1",
                str(shared.get("run_id", "")),
                str(shared.get("topic", "")),
                str(graph.graph_id),
            )
        )

    def _resume_naming_plan(
        producer_ids: Sequence[str],
        candidate_count: int,
        seed: str,
    ) -> dict[str, Any] | None:
        """Reuse a compatible persisted plan on a resumed dynamic run.

        A stale or partial checkpoint is ignored and rebuilt deterministically;
        no model output is trusted as a naming plan.
        """

        prior = accumulated.get("winning_swarm", {})
        if not isinstance(prior, Mapping):
            return None
        candidate = prior.get("naming_plan")
        if not isinstance(candidate, Mapping):
            return None
        if str(candidate.get("assignment_version", "")) != NAMING_ASSIGNMENT_VERSION:
            return None
        expected_digest = sha256(str(seed).encode("utf-8")).hexdigest()[:16]
        if str(candidate.get("seed_digest", "")) != expected_digest:
            return None
        if int(candidate.get("candidate_count_per_seat", 0) or 0) != candidate_count:
            return None
        assignments = candidate.get("assignments")
        if not isinstance(assignments, Mapping):
            return None
        if set(str(key) for key in assignments) != set(producer_ids):
            return None
        for producer_id in producer_ids:
            row = assignments.get(producer_id)
            if not isinstance(row, Mapping):
                return None
            order = row.get("candidate_order")
            if not isinstance(order, list) or len(order) != candidate_count:
                return None
        return {
            str(key): dict(value) if isinstance(value, Mapping) else value
            for key, value in candidate.items()
        }

    # Allocate the complete six-seat portfolio once, immediately after the
    # graph is known.  The same object is used by every creative iteration and
    # retry, so a transient failure cannot silently change a seat's naming
    # perspective.
    producer_ids = [item.instance_id for item in creative_producer_instances()]
    naming_candidate_count = _naming_candidate_count()
    naming_seed = _naming_plan_seed()
    naming_plan = _resume_naming_plan(
        producer_ids,
        naming_candidate_count,
        naming_seed,
    )
    naming_plan_reused = naming_plan is not None
    if naming_plan is None and producer_ids:
        naming_plan = build_s3_s4_naming_plan(
            naming_seed,
            producer_ids,
            candidates_per_seat=naming_candidate_count,
        )
    else:
        naming_plan = dict(naming_plan or {})
    emit_swarm_event(
        "winning_s3_s4_naming_plan_allocated",
        actor="winning_swarm_controller",
        graph_id=graph.graph_id,
        assignment_version=str(
            naming_plan.get("assignment_version", NAMING_ASSIGNMENT_VERSION)
        ),
        allocation_mode=str(
            naming_plan.get(
                "allocation_mode", "portfolio_deterministic_balanced"
            )
        ),
        seed_digest=str(naming_plan.get("seed_digest", "")),
        seat_count=len(producer_ids),
        candidate_count_per_seat=naming_candidate_count,
        reused_from_checkpoint=naming_plan_reused,
        portfolio_stats=dict(naming_plan.get("portfolio_stats", {})),
    )
    # Bind six seats to exactly three *open* dimension slots once per graph.
    # Slot identity is independent of naming style and survives retries, while
    # the winning dimension itself remains model-authored at runtime.  The
    # reviewed D1--D7 catalog is carried only as an advisory reference on one
    # deterministic slot; it is not a production taxonomy, a seat-to-dimension
    # assignment, or a requirement to produce a source-forward candidate.
    dimension_assignment_seed = f"{naming_seed}|winning-dimensions"
    dimension_portfolios = (
        _s3_s4_open_dimension_slots(
            dimension_assignment_seed,
            producer_ids,
            dimensions_per_seat=3,
        )
        if producer_ids
        else {}
    )
    # Compatibility alias for older diagnostics/callers that expect a primary
    # assignment mapping.  Unlike the legacy helper, these rows are open slot
    # envelopes rather than fixed D1--D7 packs.
    dimension_assignments = {
        seat: dict(portfolio.get("primary_dimension", {}))
        for seat, portfolio in dimension_portfolios.items()
    }

    async def _refresh_winning_angle_assignments_once() -> None:
        """Build non-authoritative diversity provocations for S3/S4 creators.

        The scout may suppress obviously duplicate capacity, but it does
        not own the equipment answer.  Every isolated creator first forms
        its own Query interpretation and may accept, reframe or replace
        the suggested lens.  Semantic clustering and S5 remain the first
        authoritative cross-candidate decisions.
        """

        nonlocal winning_angle_assignments
        nonlocal query_equipment_blueprint
        nonlocal dimension_assignments
        nonlocal dimension_portfolios
        if winning_angle_assignments:
            return
        producers = creative_producer_instances()
        structured_brief = shared.get("structured_query_brief", {})
        blueprint_theses = [
            dict(item)
            for item in (
                structured_brief.get("equipment_project_hypotheses", [])
                if isinstance(structured_brief, Mapping)
                else []
            )
            if isinstance(item, Mapping)
        ][: len(producers)]
        frontier_theses = [
            dict(item)
            for item in (
                structured_brief.get("frontier_technology_hypotheses", [])
                if isinstance(structured_brief, Mapping)
                else []
            )
            if isinstance(item, Mapping)
        ][: len(producers)]
        raw_seeds = [
            dict(seed)
            for instance_id in sorted(reasoning_seeds_by_instance)
            for seed in reasoning_seeds_by_instance[instance_id]
            if isinstance(seed, Mapping)
        ]
        distinct_seeds: list[dict[str, Any]] = []
        seen_spines: set[tuple[str, str, str]] = set()
        for seed in raw_seeds:
            # S1/S2 intentionally use a five-field lightweight schema.
            # Keep the pre-generation transport tolerant of both that
            # contract and the historical verbose seed names.
            seed_mechanism = str(
                seed.get("mechanism_thesis")
                or seed.get("breakpoint")
                or seed.get("combat_problem", "")
            ).strip()
            seed_variable = str(
                seed.get("changed_confrontation_variable")
                or seed.get("changed_variable")
                or seed.get("enemy_advantage", "")
            ).strip()
            seed_result = str(
                seed.get("direct_military_result") or seed.get("direct_effect", "")
            ).strip()
            # Normalize aliases once so all similarity/fallback logic sees
            # the same semantic spine regardless of which producer schema
            # emitted it.
            seed = {
                **seed,
                "mechanism_thesis": seed_mechanism,
                "changed_confrontation_variable": seed_variable,
                "direct_military_result": seed_result,
                "target_and_phase": str(
                    seed.get("target_and_phase") or seed.get("combat_problem", "")
                ).strip(),
            }
            spine = tuple(
                str(seed.get(key, "")).strip().casefold()
                for key in (
                    "changed_confrontation_variable",
                    "mechanism_thesis",
                    "direct_military_result",
                )
            )
            if not any(spine) or spine in seen_spines:
                continue
            seen_spines.add(spine)
            distinct_seeds.append(seed)

        def angle_semantic_text(value: Mapping[str, Any]) -> str:
            """Project one thesis/seed onto its pre-generation win logic.

            This is used only to allocate isolated S3 sessions.  It
            does not generate prose or infer an equipment family.  By
            comparing the changed confrontation variable, mechanism
            and direct result before candidate authoring, a fourth
            S1/S2-derived seed cannot be selected merely because it
            occupies the fourth list position while duplicating a
            blueprint thesis already assigned to another session.
            """

            return "；".join(
                str(value.get(key, "")).strip()
                for key in (
                    "query_causal_link",
                    "changed_confrontation_variable",
                    "project_function",
                    "mechanism_thesis",
                    "frontier_principle",
                    "technology_discontinuity",
                    "novelty_search_question",
                    "exclusion_boundary",
                    "direct_military_effect",
                    "direct_military_result",
                    "target_and_phase",
                )
                if str(value.get(key, "")).strip()
            )

        # Select the complete active + reserve thesis portfolio before
        # any S3 candidate is authored.  Earlier code trusted the
        # first blueprint theses and only reviewed leftovers, which
        # allowed an incremental mechanism to consume an S3 slot and
        # be rejected much later by the expert judge.  This isolated
        # review can also formulate a replacement thesis when S1/S2
        # supplied fewer than four genuinely disruptive relationships.
        angle_candidates: list[dict[str, Any]] = []
        for index, thesis in enumerate(blueprint_theses, start=1):
            angle_candidates.append(
                {
                    "angle_id": f"blueprint-angle-{index}",
                    "source": "query_blueprint_thesis",
                    # A blueprint title is only an internal planning label;
                    # it must not become an S3 naming seed.
                    "project_name": "",
                    "equipment_form_hypothesis": str(
                        thesis.get("equipment_form", "")
                    ).strip(),
                    "target_and_phase": str(thesis.get("target_and_phase", "")).strip(),
                    "mechanism_thesis": str(
                        thesis.get("project_function")
                        or thesis.get("query_causal_link", "")
                    ).strip(),
                    "changed_confrontation_variable": str(
                        thesis.get("query_causal_link", "")
                    ).strip(),
                    "direct_military_result": str(
                        thesis.get("direct_military_effect", "")
                    ).strip(),
                    "competing_explanation": str(
                        thesis.get("competing_explanation", "")
                    ).strip(),
                    "adversary_adaptation": str(
                        thesis.get("adversary_adaptation", "")
                    ).strip(),
                    "failure_boundary": str(thesis.get("failure_boundary", "")).strip(),
                }
            )
        for index, thesis in enumerate(frontier_theses, start=1):
            angle_candidates.append(
                {
                    "angle_id": f"frontier-angle-{index}",
                    "source": "query_frontier_technology_hypothesis",
                    "project_name": "",
                    "equipment_form_hypothesis": str(
                        thesis.get("equipment_implication", "")
                    ).strip(),
                    "target_and_phase": "",
                    "mechanism_thesis": str(
                        thesis.get("query_causal_link", "")
                    ).strip(),
                    "changed_confrontation_variable": str(
                        thesis.get("disruptive_delta")
                        or thesis.get("conventional_absorption_limit", "")
                    ).strip(),
                    "direct_military_result": str(
                        thesis.get("direct_military_effect", "")
                    ).strip(),
                    "frontier_principle": str(
                        thesis.get("enabling_principle", "")
                    ).strip(),
                    "technology_discontinuity": str(
                        thesis.get("disruptive_delta")
                        or thesis.get("conventional_absorption_limit", "")
                    ).strip(),
                    "technology_horizon": str(
                        thesis.get("technology_horizon", "")
                    ).strip(),
                    "engineering_bottleneck": str(
                        thesis.get("engineering_bottleneck", "")
                    ).strip(),
                    "competing_explanation": "",
                    "adversary_adaptation": "",
                    "failure_boundary": str(
                        thesis.get("disconfirming_condition", "")
                    ).strip(),
                }
            )
        for index, seed in enumerate(distinct_seeds, start=1):
            angle_candidates.append(
                {
                    "angle_id": f"reasoning-angle-{index}",
                    "source": "s1_s2_query_reasoning",
                    "project_name": "",
                    "equipment_form_hypothesis": "",
                    "target_and_phase": str(seed.get("target_and_phase", "")).strip(),
                    "mechanism_thesis": str(seed.get("mechanism_thesis", "")).strip(),
                    "changed_confrontation_variable": str(
                        seed.get("changed_confrontation_variable", "")
                    ).strip(),
                    "direct_military_result": str(
                        seed.get("direct_military_result", "")
                    ).strip(),
                    "competing_explanation": str(
                        seed.get("competing_explanation", "")
                    ).strip(),
                    "adversary_adaptation": str(
                        seed.get("adversary_adaptation", "")
                    ).strip(),
                    "failure_boundary": str(seed.get("failure_boundary", "")).strip(),
                }
            )
        angle_candidates = [
            item for item in angle_candidates if angle_semantic_text(item)
        ]
        reviewer_observations = [
            dict(item)
            for item in angle_candidates
            if item.get("source") == "s1_s2_query_reasoning"
        ]
        active_angle_ids: list[str] = []
        reserve_angle_ids: list[str] = []
        replacement_angles: list[dict[str, Any]] = []
        replacement_reserve_angles: list[dict[str, Any]] = []
        angle_selection_audit: dict[str, Any] = {}
        # The reviewed selector schema currently exposes ``open_hints`` only,
        # but newer providers may return per-seat dimension envelopes.  Keep
        # parsing permissive so adding that model capability does not require a
        # second execution path or a hard-coded D1--D7 taxonomy.
        selection: dict[str, Any] = {}
        # Dynamic-v2 has six fixed creative seats (three S3 + three S4).
        # Policy capacity may tune legacy thesis bookkeeping, but it must not
        # deactivate an open seat or reduce its three dimension slots.
        angle_capacity = len(producers)
        # Keep a small cross-dimension reserve when upstream offers extra
        # theses.  Do not hard-code zero: the old value silently discarded
        # valid alternatives and made selector output look like empty slots.
        try:
            configured_reserve = int(
                swarm_controller.policy.get("s3_s4_reserve_angle_target", 2)
            )
        except (TypeError, ValueError):
            configured_reserve = 2
        reserve_target = max(
            0,
            min(configured_reserve, max(0, len(producers) - angle_capacity), 2),
        )
        active_selection_succeeded = False
        # The selector only refines concrete upstream angle seeds.  When the
        # Query/brief supplies no usable seed, calling it would be a redundant
        # model turn whose empty ``open_hints`` result adds no information;
        # the six isolated creators can already diverge directly from Query.
        if angle_candidates and host.supports_agent_runtime:
            try:
                selector_seed_rows = list(angle_candidates[:8])
                # A short structured Query brief is normal.  Keep the shared
                # selector's input wide enough to exercise model divergence
                # by adding S1/S2 seeds that were not already represented by
                # the brief, then explicit open questions for any remaining
                # slots.  These rows are prompts, not asserted equipment
                # claims; the wording makes that boundary visible in replay.
                seen_selector_pairs = {
                    (
                        str(item.get("changed_confrontation_variable", "")).strip(),
                        str(item.get("direct_military_result", "")).strip(),
                    )
                    for item in selector_seed_rows
                }
                for seed in distinct_seeds:
                    pair = (
                        str(seed.get("changed_confrontation_variable", "")).strip(),
                        str(seed.get("direct_military_result", "")).strip(),
                    )
                    if pair in seen_selector_pairs or not any(pair):
                        continue
                    selector_seed_rows.append(
                        {
                            "changed_confrontation_variable": pair[0],
                            "direct_military_result": pair[1],
                        }
                    )
                    seen_selector_pairs.add(pair)
                    if len(selector_seed_rows) >= 8:
                        break
                open_seed_ordinal = 1
                while len(selector_seed_rows) < 8:
                    selector_seed_rows.append(
                        {
                            "changed_confrontation_variable": (
                                f"{shared.get('topic', '')}的未覆盖战场关系"
                                f"（开放问题{open_seed_ordinal}，待模型推演）"
                            ),
                            "direct_military_result": (
                                "请模型提出不同于现有候选的可证伪直接军事结果"
                            ),
                        }
                    )
                    open_seed_ordinal += 1
                selection_text = await host._run_core_json(
                    "winning_swarm_innovative_equipment_dimension_generator",
                    (
                        load_dynamic_winning_prompt(
                            "common",
                            section="refresh_winning_angle_assignments_once.selection_text.1",
                        )
                        + "\n\n"
                        + load_dynamic_winning_prompt(
                            "common",
                            section="angle_assignment.seat_contract",
                        )
                    ),
                    {
                        "query": shared.get("topic", ""),
                        "open_angle_seeds": [
                            {
                                "battlefield_relationship": str(
                                    item.get("changed_confrontation_variable", "")
                                ).strip(),
                                "desired_direct_result": str(
                                    item.get("direct_military_result", "")
                                ).strip(),
                            }
                            # The selector must see the complete upstream
                            # angle surface (Query theses, frontier signals,
                            # and S1/S2 seeds).  Restricting this payload to
                            # ``reviewer_observations`` silently dropped
                            # blueprint/frontier rows and could leave the
                            # one shared selector with an empty input even
                            # though valid seeds existed.
                            for item in selector_seed_rows[:8]
                        ],
                    },
                    _dynamic_output_schema("angle_assignment.output_schema"),
                    min(900, 420 + len(reviewer_observations) * 25),
                    phase="winning_pre_generation_active_angle_selection",
                )
                selection = _parse_json_object(selection_text)
                valid_ids = {str(item["angle_id"]) for item in angle_candidates}
                active_angle_ids = list(
                    dict.fromkeys(
                        str(item)
                        for item in selection.get("active_angle_ids", [])
                        if str(item) in valid_ids
                    )
                )[:angle_capacity]
                # New lightweight selector contract returns open_hints;
                # retain compatibility with the historical replacement
                # field while normalizing both to the same internal shape.
                lightweight_hints = selection.get("open_hints", [])
                if isinstance(lightweight_hints, list):
                    for index, item in enumerate(lightweight_hints, start=1):
                        if not isinstance(item, Mapping):
                            continue
                        relationship = str(
                            item.get("battlefield_relationship", "")
                        ).strip()
                        result = str(item.get("desired_direct_result", "")).strip()
                        if not relationship and not result:
                            continue
                        replacement_angles.append(
                            {
                                "angle_id": f"reviewer-hint-{index}",
                                "source": "pre_generation_reviewer_exploration_problem",
                                "project_name": "",
                                "equipment_form_hypothesis": "",
                                "activation": "active",
                                "target_and_phase": "",
                                "mechanism_thesis": relationship,
                                "changed_confrontation_variable": relationship,
                                "direct_military_result": result,
                                "novelty_search_question": "",
                                "exclusion_boundary": "",
                                "competing_explanation": "",
                                "adversary_adaptation": "",
                                "failure_boundary": "",
                            }
                        )
                    replacement_angles = replacement_angles[:angle_capacity]
                reserve_angle_ids = list(
                    dict.fromkeys(
                        str(item)
                        for item in selection.get("reserve_angle_ids", [])
                        if str(item) in valid_ids and str(item) not in active_angle_ids
                    )
                )[:reserve_target]
                normalized_replacements = [
                    {
                        "angle_id": f"reviewer-replacement-{index}",
                        "source": "pre_generation_reviewer_exploration_problem",
                        "project_name": "",
                        "equipment_form_hypothesis": "",
                        "activation": str(item.get("activation", "active"))
                        .strip()
                        .lower(),
                        **{
                            key: str(item.get(key, "")).strip()
                            for key in (
                                "combat_dimension",
                                "dimension_winning_logic",
                                "target_and_phase",
                                "mechanism_thesis",
                                "changed_confrontation_variable",
                                "direct_military_result",
                                "novelty_search_question",
                                "exclusion_boundary",
                                "competing_explanation",
                                "adversary_adaptation",
                                "failure_boundary",
                            )
                        },
                    }
                    for index, item in enumerate(
                        selection.get("replacement_angles", []),
                        start=1,
                    )
                    if isinstance(item, Mapping)
                    and str(item.get("mechanism_thesis", "")).strip()
                    and str(item.get("changed_confrontation_variable", "")).strip()
                    and str(item.get("direct_military_result", "")).strip()
                ]
                legacy_replacement_angles = [
                    item
                    for item in normalized_replacements
                    if item.get("activation") != "reserve"
                ][:angle_capacity]
                replacement_angles.extend(legacy_replacement_angles)
                replacement_angles = replacement_angles[:angle_capacity]
                replacement_reserve_angles = [
                    item
                    for item in normalized_replacements
                    if item.get("activation") == "reserve"
                ][:reserve_target]
                active_selection_succeeded = bool(
                    active_angle_ids or replacement_angles
                )
                if not active_selection_succeeded:
                    emit_swarm_event(
                        "winning_pre_generation_active_angle_selection_fallback",
                        actor="winning_swarm_controller",
                        graph_id=graph.graph_id,
                        failure_type="EmptySelectorResult",
                        error_message=(
                            "lightweight selector returned no usable open hints; "
                            "continuing from S1/S2 seeds"
                        ),
                        fallback_source=(
                            "s1_s2_reasoning_seeds"
                            if angle_candidates
                            else "query_only"
                        ),
                    )
                angle_selection_audit = {
                    "query_equipment_blueprint": query_equipment_blueprint,
                    "selection_reasons": selection.get("selection_reasons", []),
                    "rejected_angle_groups": selection.get("rejected_angle_groups", []),
                    "technology_discontinuity_audit": selection.get(
                        "technology_discontinuity_audit", {}
                    ),
                    "stop_reason": selection.get("stop_reason", ""),
                }
                emit_swarm_event(
                    "winning_query_equipment_blueprint_planned",
                    actor="winning_swarm_controller",
                    graph_id=graph.graph_id,
                    query_equipment_blueprint=query_equipment_blueprint,
                    activated_dimensions=[
                        str(item.get("combat_dimension", ""))
                        for item in replacement_angles
                        if str(item.get("combat_dimension", "")).strip()
                    ],
                    rule=load_dynamic_winning_prompt(
                        "common", section="s3_s4.angle_selection_audit_rule"
                    ),
                )
            except Exception as exc:
                emit_swarm_event(
                    "winning_pre_generation_active_angle_selection_fallback",
                    actor="winning_swarm_controller",
                    graph_id=graph.graph_id,
                    failure_type=type(exc).__name__,
                    error_message=str(exc)[:300],
                    fallback_source=(
                        "s1_s2_reasoning_seeds" if angle_candidates else "query_only"
                    ),
                )

        angle_by_id = {str(item["angle_id"]): item for item in angle_candidates}
        selected_active = [
            dict(angle_by_id[angle_id])
            for angle_id in active_angle_ids
            if angle_id in angle_by_id
        ]
        if replacement_angles:
            selected_active = []
        for replacement in replacement_angles:
            if len(selected_active) >= angle_capacity:
                break
            selected_active.append(dict(replacement))
        # The selector only supplies optional provocations. It never owns
        # S3/S4 capacity: fill remaining bounded slots from distinct upstream
        # Query seeds even when the selector succeeds.
        remaining_angles = [
            dict(item)
            for item in angle_candidates
            if str(item["angle_id"])
            not in {str(selected["angle_id"]) for selected in selected_active}
        ]
        while remaining_angles and len(selected_active) < angle_capacity:
            occupied_texts = [angle_semantic_text(item) for item in selected_active]
            selected = min(
                remaining_angles,
                key=lambda item: max(
                    (
                        _capability_text_similarity(angle_semantic_text(item), occupied)
                        for occupied in occupied_texts
                        if occupied
                    ),
                    default=0.0,
                ),
            )
            remaining_angles.remove(selected)
            selected_active.append(selected)
        # Every governed creative seat remains active even when the selector
        # returns no thesis.  Query-only rows are open prompts, not synthetic
        # equipment answers.
        while len(selected_active) < angle_capacity:
            ordinal = len(selected_active) + 1
            selected_active.append(
                {
                    "angle_id": f"query-only-angle-{ordinal}",
                    "source": "query_only_open_exploration",
                    "project_name": "",
                    "equipment_form_hypothesis": "",
                    "target_and_phase": "",
                    "mechanism_thesis": "",
                    "changed_confrontation_variable": "",
                    "direct_military_result": "",
                    "competing_explanation": "",
                    "adversary_adaptation": "",
                    "failure_boundary": "",
                }
            )

        def _dimension_hint_rows(value: Any) -> list[Any]:
            """Flatten selector dimension envelopes without prescribing codes."""

            if isinstance(value, Mapping):
                nested = value.get("dimensions") or value.get("dimension_slots") or value.get("slots")
                if isinstance(nested, list):
                    return list(nested)
                return [dict(value)]
            if isinstance(value, list):
                return list(value)
            return [value] if value not in (None, "") else []

        # Extract model-authored dimensions when a provider offers them.  The
        # current Markdown selector returns only open_hints, so those hints are
        # also promoted to semantic slot seeds; no D1--D7 label is invented in
        # this path.
        dimension_hints_by_seat: dict[str, list[Any]] = {}
        dimension_hints_global: list[Any] = []
        for key in (
            "seat_dimension_slots",
            "seat_dimensions",
            "seat_dimension_portfolios",
            "dimensions_by_seat",
        ):
            container = selection.get(key)
            if isinstance(container, Mapping):
                for seat_key, values in container.items():
                    token = str(seat_key).strip()
                    if token in {item.instance_id for item in producers}:
                        dimension_hints_by_seat.setdefault(token, []).extend(
                            _dimension_hint_rows(values)
                        )
                    elif token.isdigit():
                        position = int(token)
                        target = (
                            producers[position].instance_id
                            if 0 <= position < len(producers)
                            else producers[position - 1].instance_id
                            if 1 <= position <= len(producers)
                            else ""
                        )
                        if target:
                            dimension_hints_by_seat.setdefault(target, []).extend(
                                _dimension_hint_rows(values)
                            )
            elif isinstance(container, list):
                for row in container:
                    if not isinstance(row, Mapping):
                        dimension_hints_global.extend(_dimension_hint_rows(row))
                        continue
                    seat_key = (
                        row.get("seat_id")
                        or row.get("agent_instance_id")
                        or row.get("producer_id")
                        or row.get("seat_index")
                    )
                    nested = row.get("dimensions") or row.get("dimension_slots") or row.get("slots")
                    if seat_key is not None and nested is not None:
                        token = str(seat_key).strip()
                        target = token
                        if token.isdigit():
                            position = int(token)
                            target = (
                                producers[position].instance_id
                                if 0 <= position < len(producers)
                                else producers[position - 1].instance_id
                                if 1 <= position <= len(producers)
                                else ""
                            )
                        if target in {item.instance_id for item in producers}:
                            dimension_hints_by_seat.setdefault(target, []).extend(
                                _dimension_hint_rows(nested)
                            )
                        else:
                            dimension_hints_global.extend(_dimension_hint_rows(nested))
                    else:
                        dimension_hints_global.extend(_dimension_hint_rows(row))
        for key in ("dimensions", "dimension_slots"):
            dimension_hints_global.extend(_dimension_hint_rows(selection.get(key)))
        # Replacement angles and open hints are model-derived relationship
        # seeds.  They become open slot hints only when they contain semantic
        # content; their source identity is retained for audit.
        for row in [*replacement_angles, *angle_candidates]:
            if isinstance(row, Mapping) and any(
                str(row.get(field, "")).strip()
                for field in (
                    "dimension_code",
                    "combat_dimension",
                    "dimension_winning_logic",
                    "battlefield_relationship",
                    "changed_confrontation_variable",
                )
            ):
                dimension_hints_global.append(row)
        for index, row in enumerate(selection.get("open_hints", []), start=1):
            if isinstance(row, Mapping):
                dimension_hints_global.append(
                    {
                        **dict(row),
                        "source": "selector_open_hint",
                        "winning_logic": str(
                            row.get("winning_logic")
                            or row.get("battlefield_relationship", "")
                        ).strip(),
                    }
                )
        dimension_hint_payload: Mapping[str, Any] | Sequence[Any] | None = (
            dimension_hints_by_seat if dimension_hints_by_seat else dimension_hints_global
        )
        dimension_portfolios = _s3_s4_open_dimension_slots(
            dimension_assignment_seed,
            [item.instance_id for item in producers],
            dimension_hints=dimension_hint_payload,
            dimensions_per_seat=3,
        )
        dimension_assignments = {
            seat: dict(portfolio.get("primary_dimension", {}))
            for seat, portfolio in dimension_portfolios.items()
        }
        # Attach the three open slots to each selected Query angle.  The angle
        # itself remains model/upstream authored; only missing metadata is
        # filled from the advisory first slot.
        hydrated_active: list[dict[str, Any]] = []
        for index, angle in enumerate(selected_active[: len(producers)]):
            producer_id = producers[index].instance_id
            portfolio = dimension_portfolios.get(producer_id, {})
            primary = dict(portfolio.get("primary_dimension", {}))
            hydrated = dict(angle)
            hydrated["open"] = True
            hydrated["dimension_portfolio"] = [
                dict(item) for item in portfolio.get("dimension_portfolio", [])
            ]
            hydrated["alternate_dimensions"] = [
                dict(item) for item in portfolio.get("alternate_dimensions", [])
            ]
            hydrated["dimension_codes"] = list(portfolio.get("dimension_codes", []))
            hydrated["dimension_labels"] = list(portfolio.get("dimension_labels", []))
            hydrated["reference_dimension_codes"] = list(
                portfolio.get("reference_dimension_codes", [])
            )
            hydrated["reference_only_dimension_codes"] = list(
                portfolio.get("reference_dimension_codes", [])
            )
            hydrated["dimension_slot_count"] = int(
                portfolio.get("slot_count", 3) or 3
            )
            hydrated["dimension_selection_rule"] = str(
                portfolio.get("dimension_selection_rule", "")
            )
            # Keep model-authored dimensions if present; otherwise expose an
            # open first-slot label solely as an audit/dispatch hint.
            if not str(hydrated.get("combat_dimension", "")).strip():
                hydrated["combat_dimension"] = str(
                    primary.get("label")
                    or load_dynamic_winning_prompt(
                        "common", section="s3_s4.open_dimension_fallback"
                    )
                )
            if not str(hydrated.get("dimension_code", "")).strip():
                hydrated["dimension_code"] = str(primary.get("code", ""))
            if not str(hydrated.get("dimension_winning_logic", "")).strip():
                hydrated["dimension_winning_logic"] = str(
                    primary.get("winning_logic", "")
                )
            for key in (
                "task_chain_breakpoint",
                "battlefield_relationship",
                "engagement_geometry",
                "time_space_position",
                "desired_direct_result",
                "forward_winning_question",
                "exclusion_boundary",
            ):
                if not str(hydrated.get(key, "")).strip():
                    hydrated[key] = str(primary.get(key, "")).strip()
            hydrated_active.append(hydrated)
        selected_active = hydrated_active
        selected_active_ids = {str(item["angle_id"]) for item in selected_active}
        selected_reserves = [
            dict(angle_by_id[angle_id])
            for angle_id in reserve_angle_ids
            if angle_id in angle_by_id and angle_id not in selected_active_ids
        ]
        if replacement_angles:
            selected_reserves = [dict(item) for item in replacement_reserve_angles]
        # If the semantic reviewer was unavailable, retain a bounded
        # least-similar reserve set for intentional empty returns.
        if not selected_reserves and not active_selection_succeeded:
            reserve_remaining = [
                item
                for item in remaining_angles
                if str(item["angle_id"]) not in selected_active_ids
            ]
            while reserve_remaining and len(selected_reserves) < reserve_target:
                occupied = [
                    angle_semantic_text(item)
                    for item in [*selected_active, *selected_reserves]
                ]
                selected = min(
                    reserve_remaining,
                    key=lambda item: max(
                        (
                            _capability_text_similarity(angle_semantic_text(item), text)
                            for text in occupied
                            if text
                        ),
                        default=0.0,
                    ),
                )
                reserve_remaining.remove(selected)
                selected_reserves.append(dict(selected))

        # The Query controller is the only pre-generation semantic pass.
        # Legacy disruptive seed mapping is intentionally absent: it added
        # another model-authored solution frame before S3/S4 and correlated
        # otherwise independent creators.
        angle_selection_audit["legacy_seed_challenge_disabled"] = True

        # Reuse the established assignment transport below: active
        # angles behave as blueprint theses and pair with their own
        # semantic seed; only the preselected reserves remain unused.
        blueprint_theses = [dict(item) for item in selected_active]
        distinct_seeds = [
            *[dict(item) for item in selected_active],
            *[dict(item) for item in selected_reserves],
        ]

        unused_seed_indices = set(range(len(distinct_seeds)))

        def select_seed(
            thesis: Mapping[str, Any],
            occupied: Sequence[Mapping[str, Any]],
        ) -> dict[str, Any]:
            if not unused_seed_indices:
                return {}
            thesis_text = angle_semantic_text(thesis)
            occupied_texts = [
                angle_semantic_text(item)
                for item in occupied
                if angle_semantic_text(item)
            ]

            def rank(index: int) -> tuple[float, float, int]:
                seed_text = angle_semantic_text(distinct_seeds[index])
                similarity_to_thesis = (
                    _capability_text_similarity(seed_text, thesis_text)
                    if seed_text and thesis_text
                    else 0.0
                )
                maximum_occupied_similarity = max(
                    (
                        _capability_text_similarity(seed_text, item)
                        for item in occupied_texts
                    ),
                    default=0.0,
                )
                # A blueprint-backed session prefers the S1/S2 seed
                # that explains its thesis. An open session prefers the
                # least occupied winning relationship. Stable reverse
                # index ordering preserves deterministic selection.
                if thesis_text:
                    return (
                        similarity_to_thesis,
                        -maximum_occupied_similarity,
                        -index,
                    )
                return (
                    1.0 - maximum_occupied_similarity,
                    0.0,
                    -index,
                )

            selected_index = max(unused_seed_indices, key=rank)
            unused_seed_indices.remove(selected_index)
            return distinct_seeds[selected_index]

        reserved: list[dict[str, str]] = []
        for index, instance in enumerate(producers):
            if index >= len(blueprint_theses):
                open_portfolio = dimension_portfolios.get(instance.instance_id, {})
                winning_angle_assignments[instance.instance_id] = {
                    "assignment_id": f"query-winning-capacity-{index + 1}",
                    "source": "semantic_no_distinct_angle",
                    # A lack of upstream theses must not turn a fixed creative
                    # seat into a non-dimensional hole.  Keep all three open
                    # slots available; the creator can still reason directly
                    # from Query.
                    "active": True,
                    "open_dimension_slots": True,
                    "dimension_slot_count": int(
                        open_portfolio.get("slot_count", 3) or 3
                    ),
                    "dimension_portfolio": [
                        dict(item)
                        for item in open_portfolio.get("dimension_portfolio", [])
                        if isinstance(item, Mapping)
                    ],
                    "dimension_codes": list(
                        open_portfolio.get("dimension_codes", [])
                    ),
                    "reference_dimension_codes": list(
                        open_portfolio.get("reference_dimension_codes", [])
                    ),
                    "reference_only_dimension_codes": list(
                        open_portfolio.get("reference_dimension_codes", [])
                    ),
                    "primary_dimension": dict(
                        open_portfolio.get("primary_dimension", {})
                    ),
                    "primary_dimension_code": str(
                        open_portfolio.get("primary_dimension_code", "")
                    ),
                    "primary_dimension_label": str(
                        open_portfolio.get("primary_dimension_label", "")
                    ),
                    "project_name": "",
                    "equipment_form_hypothesis": "",
                    "target_and_phase": "",
                    "mechanism_thesis": "",
                    "changed_confrontation_variable": "",
                    "direct_military_result": "",
                    "competing_explanation": "",
                    "adversary_adaptation": "",
                    "failure_boundary": "",
                    "reserved_other_angles": [],
                    "rule": load_dynamic_winning_prompt(
                        "common", section="s3_s4.angle_assignment_inactive_rule"
                    ),
                }
                seat_dimension_traces[instance.instance_id] = [
                    str(item.get("code", ""))
                    for item in open_portfolio.get("dimension_portfolio", [])
                    if isinstance(item, Mapping)
                    and str(item.get("code", "")).strip()
                ][:3]
                continue
            thesis = blueprint_theses[index] if index < len(blueprint_theses) else {}
            seed = select_seed(thesis, reserved)
            assignment = {
                "assignment_id": f"query-winning-angle-{index + 1}",
                "active": True,
                "authority": "advisory_diversity_pool_only",
                "allowed_response_modes": ["accept", "reframe", "replace"],
                "self_proposed_id_pattern": "self-proposed:<short-id>",
                "source": "query_blueprint_thesis"
                if thesis.get("source") == "query_blueprint_thesis"
                else "query_frontier_technology_hypothesis"
                if thesis.get("source") == "query_frontier_technology_hypothesis"
                else "s1_s2_query_reasoning"
                if thesis.get("source") == "s1_s2_query_reasoning"
                else "pre_generation_reviewer_exploration_problem"
                if thesis.get("source") == "pre_generation_reviewer_exploration_problem"
                else "post_divergence_model_reframed_seed_angle"
                if thesis.get("source") == "post_divergence_model_reframed_seed_angle"
                else "s1_s2_query_reasoning"
                if seed or thesis
                else "open_other_angle",
                "project_name": "",
                "combat_dimension": str(thesis.get("combat_dimension", "")).strip(),
                "dimension_code": str(thesis.get("dimension_code", "")).strip(),
                "dimension_winning_logic": str(
                    thesis.get("dimension_winning_logic", "")
                ).strip(),
                "query_equipment_blueprint": dict(query_equipment_blueprint),
                "equipment_form_hypothesis": str(
                    thesis.get("equipment_form_hypothesis")
                    or thesis.get("equipment_form", "")
                ).strip(),
                "target_and_phase": str(thesis.get("target_and_phase", "")).strip(),
                "mechanism_thesis": str(
                    thesis.get("project_function")
                    or thesis.get("query_causal_link")
                    or thesis.get("mechanism_thesis")
                    or seed.get("mechanism_thesis", "")
                ).strip(),
                "changed_confrontation_variable": str(
                    thesis.get("query_causal_link")
                    or thesis.get("changed_confrontation_variable")
                    or seed.get("changed_confrontation_variable", "")
                ).strip(),
                "direct_military_result": str(
                    thesis.get("direct_military_effect")
                    or thesis.get("direct_military_result")
                    or seed.get("direct_military_result", "")
                ).strip(),
                "novelty_search_question": str(
                    thesis.get("novelty_search_question")
                    or seed.get("novelty_search_question", "")
                ).strip(),
                "exclusion_boundary": str(
                    thesis.get("exclusion_boundary")
                    or seed.get("exclusion_boundary", "")
                ).strip(),
                "post_divergence_seed_provocations": list(
                    thesis.get("post_divergence_seed_provocations", [])
                ),
                "post_divergence_frontier_provocations": list(
                    thesis.get("post_divergence_frontier_provocations", [])
                ),
                "frontier_principle": str(
                    thesis.get("frontier_principle")
                    or seed.get("frontier_principle", "")
                ).strip(),
                "technology_discontinuity": str(
                    thesis.get("technology_discontinuity")
                    or seed.get("technology_discontinuity", "")
                ).strip(),
                "technology_horizon": str(
                    thesis.get("technology_horizon")
                    or seed.get("technology_horizon", "")
                ).strip(),
                "engineering_bottleneck": str(
                    thesis.get("engineering_bottleneck")
                    or seed.get("engineering_bottleneck", "")
                ).strip(),
                "competing_explanation": str(
                    thesis.get("competing_explanation")
                    or seed.get("competing_explanation", "")
                ).strip(),
                "adversary_adaptation": str(
                    thesis.get("adversary_adaptation")
                    or seed.get("adversary_adaptation", "")
                ).strip(),
                "failure_boundary": str(
                    thesis.get("failure_boundary") or seed.get("failure_boundary", "")
                ).strip(),
                "reserved_other_angles": list(reserved),
                "rule": load_dynamic_winning_prompt(
                    "common", section="s3_s4.angle_assignment_shared_rule"
                ),
            }
            # Three open slots are the durable seat contract.  Their labels
            # and relationships come from selector/Query analysis; the first
            # slot is only an audit hint and never an exclusive production
            # lane.  Preserve any explicit model-authored dimension metadata.
            portfolio = dimension_portfolios.get(instance.instance_id, {})
            primary = dict(portfolio.get("primary_dimension", {}))
            if not str(assignment.get("combat_dimension", "")).strip():
                assignment["combat_dimension"] = str(
                    primary.get("label")
                    or load_dynamic_winning_prompt(
                        "common", section="s3_s4.open_dimension_fallback"
                    )
                ).strip()
            if not str(assignment.get("dimension_code", "")).strip():
                assignment["dimension_code"] = str(primary.get("code", "")).strip()
            if not str(assignment.get("dimension_winning_logic", "")).strip():
                assignment["dimension_winning_logic"] = str(
                    primary.get("winning_logic", "")
                ).strip()
            assignment["primary_dimension_code"] = str(
                primary.get("code", assignment.get("dimension_code", ""))
            ).strip()
            assignment["primary_dimension_label"] = str(
                primary.get("label", assignment.get("combat_dimension", ""))
            ).strip()
            assignment["primary_dimension"] = primary
            assignment["alternate_dimensions"] = [
                dict(item)
                for item in portfolio.get("alternate_dimensions", [])
                if isinstance(item, Mapping)
            ]
            assignment["dimension_portfolio"] = [
                dict(item)
                for item in portfolio.get("dimension_portfolio", [])
                if isinstance(item, Mapping)
            ]
            assignment["dimension_codes"] = list(
                portfolio.get(
                    "dimension_codes",
                    [assignment["primary_dimension_code"]],
                )
            )
            assignment["reference_dimension_codes"] = list(
                portfolio.get("reference_dimension_codes", [])
            )
            assignment["reference_only_dimension_codes"] = list(
                portfolio.get("reference_dimension_codes", [])
            )
            assignment["dimension_slot_count"] = int(
                portfolio.get("slot_count", 3) or 3
            )
            assignment["open_dimension_slots"] = True
            assignment["dimension_selection_rule"] = str(
                portfolio.get("dimension_selection_rule", "")
            ).strip()
            for package_key in (
                "task_chain_breakpoint",
                "battlefield_relationship",
                "engagement_geometry",
                "time_space_position",
                "desired_direct_result",
                "forward_winning_question",
                "exclusion_boundary",
            ):
                assignment[package_key] = str(
                    primary.get(package_key, assignment.get(package_key, ""))
                ).strip()
            # Keep the historical aliases populated for downstream handoffs.
            assignment["changed_confrontation_variable"] = str(
                assignment.get("changed_confrontation_variable")
                or assignment.get("battlefield_relationship", "")
            ).strip()
            assignment["direct_military_result"] = str(
                assignment.get("direct_military_result")
                or assignment.get("desired_direct_result", "")
            ).strip()
            winning_angle_assignments[instance.instance_id] = assignment
            seat_dimension_traces[instance.instance_id] = [
                str(item.get("code", ""))
                for item in assignment.get("dimension_portfolio", [])
                if str(item.get("code", "")).strip()
            ]
            reserved.append(
                {
                    "assignment_id": assignment["assignment_id"],
                    "changed_confrontation_variable": assignment[
                        "changed_confrontation_variable"
                    ],
                    "mechanism_thesis": assignment["mechanism_thesis"],
                    "direct_military_result": assignment["direct_military_result"],
                    "frontier_principle": assignment["frontier_principle"],
                    "technology_discontinuity": assignment["technology_discontinuity"],
                    "novelty_search_question": assignment["novelty_search_question"],
                    "exclusion_boundary": assignment["exclusion_boundary"],
                }
            )
        for instance_id, assignment in winning_angle_assignments.items():
            own_id = str(assignment.get("assignment_id", ""))
            assignment["reserved_other_angles"] = [
                dict(item)
                for item in reserved
                if str(item.get("assignment_id", "")) != own_id
            ]
        emit_swarm_event(
            "winning_pre_generation_angle_portfolio_planned",
            actor="winning_swarm_controller",
            graph_id=graph.graph_id,
            assigned_angle_count=sum(
                bool(item.get("active", True))
                for item in winning_angle_assignments.values()
            ),
            s3_capacity_slot_count=len(winning_angle_assignments),
            inactive_capacity_slot_count=sum(
                not bool(item.get("active", True))
                for item in winning_angle_assignments.values()
            ),
            reserve_angle_count=0,
            # D7 is carried as an optional source-forward reference prompt
            # only; no seat is forced to author a D7 candidate.  Consumers
            # should read ``reference_only_dimension_codes`` when they need to
            # audit this advisory check.
            reference_only_dimension_codes=["D7"],
            reference_dimension_role="advisory_reference_only_not_hard_topic",
            dimension_mode="model_derived_open_slots",
            dimensions_per_seat={
                instance_id: list(codes)
                for instance_id, codes in seat_dimension_traces.items()
            },
            reference_dimensions_per_seat={
                instance_id: list(
                    winning_angle_assignments.get(instance_id, {}).get(
                        "reference_dimension_codes", []
                    )
                )
                for instance_id in seat_dimension_traces
                if winning_angle_assignments.get(instance_id, {}).get(
                    "reference_dimension_codes", []
                )
            },
            dimension_catalog_size=len(
                _s3_s4_dimension_catalog(
                    next(iter(winning_angle_assignments.values()), {})
                )
            ),
            dimension_assignment_rule=load_dynamic_winning_prompt(
                "common", section="s3_s4.dimension_assignment_rule"
            ),
            assigned_angles=[
                {
                    "assignment_id": item.get("assignment_id", ""),
                    "dimension_code": item.get("dimension_code", ""),
                    "combat_dimension": item.get("combat_dimension", ""),
                    "dimension_winning_logic": item.get(
                        "dimension_winning_logic", ""
                    ),
                    "changed_confrontation_variable": item.get(
                        "changed_confrontation_variable", ""
                    ),
                    "mechanism_thesis": item.get("mechanism_thesis", ""),
                    "direct_military_result": item.get("direct_military_result", ""),
                }
                for item in winning_angle_assignments.values()
                if bool(item.get("active", True))
            ],
            reserve_angles=[],
            rule=load_dynamic_winning_prompt(
                "common", section="s3_s4.seat_dispatch_rule"
            ),
            selection_audit=angle_selection_audit,
        )

    async def refresh_winning_angle_assignments() -> None:
        """Share one pre-generation portfolio review across all S3 slots."""

        nonlocal winning_angle_refresh_task
        if winning_angle_assignments:
            return
        if winning_angle_refresh_task is None:
            # No await occurs between the guard and task assignment,
            # so all concurrently awakened S3 producers observe the
            # same task on the single asyncio event loop.
            winning_angle_refresh_task = asyncio.create_task(
                _refresh_winning_angle_assignments_once()
            )
        await asyncio.shield(winning_angle_refresh_task)

    async def materialize_active_s3_instances() -> None:
        """Activate the bounded creative pool without pre-pruning it.

        The pre-generation selector is advisory only.  It provides each
        Codex creator with a different starting question so the pool can
        avoid isomorphic ideas, but it must not decide which S3/S4 slots
        are allowed to create.  Keeping every governed slot active makes
        candidate volume depend on model creativity rather than the number
        of blueprint theses; S5 remains the sole semantic admission gate.
        """

        nonlocal graph, s3_active_instances_materialized
        if s3_active_instances_materialized:
            return
        await refresh_winning_angle_assignments()
        s3_active_instances_materialized = True
        seeds = {key: list(value) for key, value in graph.s_node_seeds.items()}
        emit_swarm_event(
            "winning_s3_active_agents_materialized",
            actor="winning_swarm_controller",
            graph_id=graph.graph_id,
            active_instance_ids=[
                *seeds.get("S3", []),
                *seeds.get("S4", []),
            ],
            active_instance_count=(len(seeds.get("S3", [])) + len(seeds.get("S4", []))),
            unused_capacity_count=0,
            rule=load_dynamic_winning_prompt(
                "common", section="s3_s4.materialized_rule"
            ),
        )

    def task_for_instance(instance: WinningAgentInstance) -> SpecialistTask:
        contract = contracts[instance.role_contract_id]
        display_name = instance.display_name
        purpose = contract.purpose
        if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
            producers = creative_producer_instances()
            try:
                position = producers.index(instance)
            except ValueError:
                position = 0
            label = chr(ord("A") + min(position, 25))
            assignment = dict(winning_angle_assignments.get(instance.instance_id, {}))
            dimension = str(assignment.get("combat_dimension", "")).strip()
            # Keep model-visible fallback prose in the reviewed Markdown
            # resources.  The executor only injects runtime values here;
            # changing these defaults must not require a code edit or worker
            # redeploy beyond the normal prompt-cache refresh.
            purpose_defaults = load_dynamic_winning_json(
                "common", section="s3_s4.task_purpose_defaults"
            )
            if not isinstance(purpose_defaults, Mapping):
                purpose_defaults = {}

            def purpose_default(key: str) -> str:
                return str(purpose_defaults.get(key, "") or "").strip()

            dimension_catalog = _s3_s4_dimension_catalog(assignment)
            dimension_catalog_text = "；".join(
                f"{item['code']} {item['label']}"
                for item in dimension_catalog
            )
            display_name = f"开放创新武器 Agent {label}"
            semantic_parts = [
                str(assignment.get("combat_dimension", "")).strip(),
                str(assignment.get("dimension_winning_logic", "")).strip(),
                str(assignment.get("task_chain_breakpoint", "")).strip(),
                str(assignment.get("battlefield_relationship", "")).strip(),
                str(assignment.get("engagement_geometry", "")).strip(),
                str(assignment.get("time_space_position", "")).strip(),
                str(assignment.get("desired_direct_result", "")).strip(),
                str(assignment.get("forward_winning_question", "")).strip(),
                str(assignment.get("exclusion_boundary", "")).strip(),
                str(assignment.get("target_and_phase", "")).strip(),
                str(assignment.get("changed_confrontation_variable", "")).strip(),
                str(assignment.get("mechanism_thesis", "")).strip(),
                str(assignment.get("direct_military_result", "")).strip(),
                str(assignment.get("failure_boundary", "")).strip(),
            ]
            if any(semantic_parts):
                # Keep the full dimension package available to the task
                # purpose.  The package now carries the dimension label and
                # winning logic in addition to the historical target,
                # changed-variable, mechanism, result and boundary fields.
                # Unpacking only five values caused every S3/S4 seat to fail
                # before reaching its provider boundary.
                (
                    target,
                    dimension_logic,
                    task_breakpoint,
                    battlefield_relationship,
                    engagement_geometry,
                    time_space_position,
                    desired_result,
                    forward_question,
                    exclusion_boundary,
                    phase,
                    changed_variable,
                    mechanism,
                    result,
                    boundary,
                ) = semantic_parts
                purpose = load_dynamic_winning_prompt(
                    "common", section="s3_s4.task_purpose"
                ).format(
                    target=target or purpose_default("target"),
                    dimension=dimension or purpose_default("dimension"),
                    dimension_logic=dimension_logic
                    or purpose_default("dimension_logic"),
                    dimension_catalog=dimension_catalog_text
                    or load_dynamic_winning_prompt(
                        "common", section="s3_s4.open_dimension_fallback"
                    ),
                    task_breakpoint=task_breakpoint
                    or purpose_default("task_breakpoint"),
                    battlefield_relationship=(
                        battlefield_relationship
                        or changed_variable
                        or purpose_default("battlefield_relationship")
                    ),
                    engagement_geometry=engagement_geometry
                    or purpose_default("engagement_geometry"),
                    time_space_position=time_space_position
                    or phase
                    or purpose_default("time_space_position"),
                    desired_result=desired_result
                    or result
                    or purpose_default("desired_result"),
                    forward_question=(
                        forward_question
                        or purpose_default("forward_question")
                    ),
                    exclusion_boundary=(
                        exclusion_boundary
                        or purpose_default("exclusion_boundary")
                    ),
                ) + load_dynamic_winning_prompt(
                    "common", section="task_for_instance.purpose.1"
                )
        elif instance.mission_node == "S5" and instance.archetype == "independent_portfolio_reviewer" and not instance.hypothesis_id:
            producers = creative_producer_instances()
            try:
                reviewer_position = producers.index(
                    next(
                        (
                            producer
                            for producer in producers
                            if producer.instance_id in instance.depends_on
                        ),
                        producers[0],
                    )
                )
            except ValueError:
                reviewer_position = 0
            display_name = f"S5创新评分 Agent {chr(ord('A') + min(reviewer_position, 25))}"
        output_budget = (
            2400
            if instance.archetype == "independent_portfolio_reviewer"
            else 3600
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id
            else 2200
        )
        return SpecialistTask(
            task_id=instance.instance_id,
            agent_instance_id=instance.instance_id,
            archetype=instance.archetype,
            display_name=display_name,
            wave=instance.wave,
            purpose=purpose,
            merge_target=instance.merge_target,
            hypothesis_id=instance.hypothesis_id,
            trigger_residuals=list(instance.trigger_residuals),
            depends_on=list(instance.depends_on),
            expected_quality_gain=instance.expected_quality_gain,
            max_output_tokens=output_budget,
            allow_child_spawn=False,
        )

    def canonical_candidate_id(hypothesis_id: str) -> str:
        current = str(hypothesis_id)
        seen: set[str] = set()
        while current in candidate_id_aliases and current not in seen:
            seen.add(current)
            current = candidate_id_aliases[current]
        return current

    async def call_instance(
        instance: WinningAgentInstance,
        *,
        ledger_snapshot: HypothesisLedgerVersion | None,
        batch_index: int,
        candidate_scope: set[str],
    ) -> tuple[WinningAgentInstance, dict[str, Any], int]:
        if instance.allow_child_spawn:
            raise ValueError("mission graph instances may not recruit child agents")
        # Defensive no-op for a paired dynamic reviewer whose creator emitted
        # no live candidate.  Normal scheduling filters this case before task
        # creation; keeping the guard here prevents a direct caller or a
        # resume race from issuing an unintended full-ledger S5 request.
        requested_scope = {
            canonical_candidate_id(value)
            for value in candidate_scope
            if value is not None and str(value).strip()
        }
        effective_requested_scope = (
            requested_scope & effective_scope_for_instance(instance, ledger_snapshot)
            if is_dynamic_paired_reviewer(instance)
            else requested_scope
        )
        if is_dynamic_paired_reviewer(instance) and not effective_requested_scope:
            emit_swarm_event(
                "winning_s5_empty_scope_skipped",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                mission_node="S5",
                candidate_scope=[],
                reason="paired_creator_published_no_live_candidates",
            )
            return (
                instance,
                {
                    "decisions": [],
                    "portfolio_order": [],
                    "portfolio_summary": "",
                    "stop_reason": "empty_creator_scope_no_s5_review",
                },
                ledger_snapshot.version if ledger_snapshot is not None else 0,
            )
        contract = contracts[instance.role_contract_id]
        if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
            await refresh_winning_angle_assignments()
            # The selector is advisory and may mark a slot as having no
            # distinct precomputed angle.  That does not make the slot
            # ineligible: the isolated creator still receives the open
            # Query and may discover an entirely different OTHER weapon
            # architecture.  S5 is the first authoritative admission
            # gate, so never short-circuit a creative call here.
        # S3 task identity is bound only after semantic selection.  A
        # reallocated reserve therefore receives a freshly derived
        # purpose instead of retaining its prior static role or a
        # blueprint equipment working name.
        task = task_for_instance(instance)
        runtime_agent_id = f"winning_swarm_{instance.archetype}"
        scoped_provider = host._provider_for(
            runtime_agent_id,
            isolation_id=instance.instance_id,
            payload={
                "mission_node": instance.mission_node,
                "specialist_task": {"archetype": instance.archetype},
            },
        )
        runtime_contract = _swarm_runtime_audit_contract(
            task,
            getattr(scoped_provider, "snapshot", lambda: {})(),
            runtime_agent_id=runtime_agent_id,
            session_ref=_swarm_session_ref(task),
        )
        emit_swarm_event(
            "winning_agent_instance_ready",
            actor=instance.instance_id,
            graph_id=graph.graph_id,
            role_contract_id=instance.role_contract_id,
            mission_node=instance.mission_node,
            depends_on=list(instance.depends_on),
            batch=batch_index,
            **runtime_contract,
        )
        # Fresh S1/S2 and S3/S4 creator turns are context-free: their final
        # payload is rebuilt below and deliberately omits the candidate ledger,
        # so constructing compact handoffs here would only allocate and
        # serialize data that is immediately discarded. A reassigned S3/S4
        # instance carries a hypothesis_id and follows the patch/repair path,
        # so it still needs its scoped ledger context. Keep the full snapshot
        # path for downstream reviewers, where the ledger is actual model input.
        context_free_node = (
            str(swarm_controller.policy.get("policy_id"))
            == "winning_swarm_dynamic_v2"
            and (
                instance.mission_node in {"S1", "S2"}
                or (
                    instance.mission_node in {"S3", "S4"}
                    and not instance.hypothesis_id
                )
            )
        )
        compact_evidence_index: list[Any] = []
        if context_free_node:
            ledger_candidates: list[WinningHypothesis] = []
            candidate_snapshot: list[dict[str, Any]] = []
            candidate_semantic_spine: dict[str, Any] = {}
        else:
            ledger_candidates = (
                list(ledger_snapshot.hypotheses)
                if ledger_snapshot is not None
                else list(hypotheses)
            )
            # Validation designers only need the candidate branches
            # produced by their declared dependencies.  The old S6
            # exception sent the complete ledger to every validation
            # designer and made a three-candidate task reread 30-40k chars.
            # Only the independent portfolio reviewer is intentionally
            # global.
            # Dynamic-v2 paired reviewers are never allowed to widen an empty or
            # stale creator slice into a full-ledger review.  The scheduler skips
            # empty slices below; this defensive filter also protects direct
            # invocations and races with a concurrent S5 disposition.
            if is_dynamic_paired_reviewer(instance):
                candidate_scope = effective_requested_scope
                ledger_candidates = [
                    item
                    for item in ledger_candidates
                    if canonical_candidate_id(item.hypothesis_id) in candidate_scope
                ]
            elif candidate_scope:
                ledger_candidates = [
                    item
                    for item in ledger_candidates
                    if item.hypothesis_id in candidate_scope
                ]
            if instance.archetype == "independent_portfolio_reviewer":
                # The portfolio reviewer consumes the minimal candidate card
                # plus a separate semantic spine.  Do not first build the
                # larger generic handoff only to overwrite it immediately.
                candidate_snapshot = [
                    _minimal_portfolio_candidate_handoff(item)
                    for item in ledger_candidates
                ]
                candidate_semantic_spine = {
                    str(item.hypothesis_id): {
                        key: value
                        for key, value in _minimal_portfolio_candidate_handoff(
                            item, rich=True
                        ).items()
                        if key
                        not in {"hypothesis_id", "name", "concise_winning_summary"}
                    }
                    for item in ledger_candidates
                }
            else:
                candidate_snapshot = [
                    _compact_swarm_candidate_handoff(item)
                    for item in ledger_candidates
                ]
                # Non-reviewer roles do not receive a semantic spine in the
                # generic envelope; avoid computing rich handoffs for them.
                candidate_semantic_spine = {}
        candidate_handoff_chars = len(
            json.dumps(candidate_snapshot, ensure_ascii=False)
        )
        evidence_handoff_chars = len(
            json.dumps(compact_evidence_index, ensure_ascii=False)
        )
        # Fresh S1/S2/S3/S4 branches replace this legacy all-purpose envelope
        # below, so defer its large prompt/contract construction.  A
        # reallocated S3/S4 instance may carry a hypothesis_id and takes the
        # generic repair/patch path later; keep the envelope for that case.
        query_domain = _query_domain_contract(
            str(shared.get("topic", "")),
            structured_query_brief=(
                shared.get("structured_query_brief", {})
                if isinstance(shared.get("structured_query_brief", {}), Mapping)
                else {}
            ),
        )
        common_input = (
            {
            # Carry durable identity into every isolated dynamic turn
            # so model progress is attributable to one S-node and
            # refreshes the Worker lease while the CLI is running.
            "run_id": shared.get("run_id", ""),
            "agent_instance_id": instance.instance_id,
            "batch": batch_index,
            "mission_node": instance.mission_node,
            "topic": shared["topic"],
            "research_route": shared["research_route"],
            "execution_profile_id": shared["execution_profile_id"],
            "discovery_branch": primary_branch,
            "query_led_combat_equipment_themes": (
                _open_s3_theme_contract()
                if instance.mission_node in {"S1", "S2", "S3", "S4"}
                else _query_led_combat_equipment_theme_contract()
            ),
            "query_combat_equipment_divergence_brief": (
                _open_s3_exploration_brief(
                    str(shared.get("topic", "")),
                    shared.get("structured_query_brief", {}),
                )
                if instance.mission_node in {"S1", "S2", "S3", "S4"}
                else _query_combat_equipment_divergence_brief(
                    str(shared.get("topic", "")),
                    structured_query_brief=shared.get("structured_query_brief", {}),
                )
            ),
            "query_domain_contract": query_domain,
            "mission_graph": {
                "graph_id": graph.graph_id,
                "mission_objective": graph.mission_objective,
            },
            "equipment_portfolio_contract": {
                "selection_rule": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.selection_rule.1"
                    )
                ),
                "minimum_direct_combat_equipment": (
                    1 if query_domain["requires_direct_combat_weapon"] else 0
                ),
                "minimum_query_equipment": 1,
                "direct_equipment_definition": (
                    query_domain["subject_label"]
                    + "；"
                    + query_domain["direct_effect_label"]
                    + "。"
                    + "不得把"
                    + "、".join(query_domain["forbidden_subjects"])
                    + "作为主体。"
                ),
                "priority_lanes": [
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.priority_lanes.1"
                    ),
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.priority_lanes.2"
                    ),
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.priority_lanes.3"
                    ),
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.priority_lanes.4"
                    ),
                ],
                "priority_lane_rule": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.priority_lane_rule.1"
                    )
                ),
                "disruptive_lenses": [
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.1"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.1"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.1"
                        ),
                    },
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.2"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.2"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.2"
                        ),
                    },
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.3"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.3"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.3"
                        ),
                    },
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.4"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.4"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.4"
                        ),
                    },
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.5"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.5"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.5"
                        ),
                    },
                    {
                        "logic": load_dynamic_winning_prompt(
                            "common", section="call_instance.logic.6"
                        ),
                        "shift": load_dynamic_winning_prompt(
                            "common", section="call_instance.shift.6"
                        ),
                        "essential_change": load_dynamic_winning_prompt(
                            "common", section="call_instance.essential_change.6"
                        ),
                    },
                ],
                "disruptive_lens_rule": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.disruptive_lens_rule.1"
                    )
                ),
            },
            "role_contract": _dynamic_role_contract_handoff(contract, task),
            "specialist_task": to_plain(task),
            "candidate_ledger": {
                "ledger_id": ledger_snapshot.ledger_id if ledger_snapshot else "",
                "version": ledger_snapshot.version if ledger_snapshot else 0,
                "hypotheses": candidate_snapshot,
                "semantic_spine": (
                    candidate_semantic_spine
                    if instance.archetype == "independent_portfolio_reviewer"
                    else {}
                ),
                "allowed_hypothesis_ids": sorted(candidate_scope),
                "handoff_schema": (
                    "portfolio_semantic_spine_v2"
                    if instance.archetype == "independent_portfolio_reviewer"
                    else "compact_decision_spine_v1"
                ),
            },
            "evidence_index": compact_evidence_index,
            "valid_reference_ids": sorted(valid_reference_ids),
            "isolation_contract": {
                "raw_other_agent_sessions_visible": False,
                "may_recruit_child_agent": False,
                "declared_merge_target": instance.merge_target,
            },
            "upstream_reasoning_seeds": [
                seed
                for dependency in instance.depends_on
                for seed in reasoning_seeds_by_instance.get(dependency, [])
            ][: 6 if instance.mission_node in {"S3", "S4"} else 12],
            }
            if not context_free_node
            and instance.archetype != "independent_portfolio_reviewer"
            else {}
        )
        targeted_feedback = _targeted_expert_feedback(
            shared.get("expert_review_feedback", []),
            instance.mission_node,
        )
        if targeted_feedback:
            common_input["expert_review_feedback"] = _compact_prompt_value(
                targeted_feedback,
                max_string_chars=520,
                max_list_items=8,
            )
        if instance.mission_node in {"S1", "S2", "S3", "S4"}:
            open_brief = _open_s3_exploration_brief(
                str(shared.get("topic", "")),
                shared.get("structured_query_brief", {}),
            )
            upstream_seeds = [
                {
                    key: seed.get(key, "")
                    for key in (
                        "combat_problem",
                        "enemy_advantage",
                        "breakpoint",
                        "changed_variable",
                        "direct_effect",
                    )
                    if seed.get(key) not in (None, "", [], {})
                }
                for dependency in instance.depends_on
                for seed in reasoning_seeds_by_instance.get(dependency, [])
                if isinstance(seed, Mapping)
            ][:4]
            common_input = {
                "run_id": shared.get("run_id", ""),
                "agent_instance_id": instance.instance_id,
                "mission_node": instance.mission_node,
                # run_core_json adds a governed input wrapper around this
                # payload.  Keep the dynamic profile marker in the same
                # business payload as specialist_task so the runtime
                # contract resolver can distinguish a reassigned S3/S4
                # node from a static catalog boundary crossing.
                "execution_profile_id": shared.get("execution_profile_id", ""),
                "specialist_task": to_plain(task),
                "role_contract": _dynamic_role_contract_handoff(contract, task),
                "query": str(shared.get("topic", "")),
                "battlefield_contradiction": {
                    key: open_brief.get(key, "")
                    for key in (
                        "combat_problem_frame",
                        "enemy_target_profile",
                        "battle_phase_and_constraints",
                        "required_direct_military_effects",
                    )
                },
                "upstream_reasoning_seeds": upstream_seeds,
                "open_challenge": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.open_challenge.1"
                    )
                ),
                **(
                    {
                        "expert_review_feedback": _compact_prompt_value(
                            targeted_feedback,
                            max_string_chars=520,
                            max_list_items=8,
                        )
                    }
                    if targeted_feedback
                    else {}
                ),
                "portfolio_creative_diversity_goal": (
                    load_dynamic_winning_prompt(
                        "common",
                        section="call_instance.portfolio_creative_diversity_goal.1",
                    )
                ),
                "isolation_contract": {
                    "raw_other_agent_sessions_visible": False,
                    "may_recruit_child_agent": False,
                },
            }
        elif instance.archetype == "independent_portfolio_reviewer":
            coverage_for_review = (
                compact_coverage_for_review(
                    build_coverage_snapshot(
                        ledger_snapshot.hypotheses,
                        topic=str(shared.get("topic", "")),
                    )
                )
                if ledger_snapshot is not None and ledger_snapshot.hypotheses
                else {}
            )
            common_input = {
                "candidate_ledger": {
                    "query_boundary": str(shared.get("topic", "")),
                    "hypotheses": candidate_snapshot,
                    "semantic_spine": candidate_semantic_spine,
                    "allowed_hypothesis_ids": sorted(candidate_scope),
                    "handoff_schema": "portfolio_semantic_spine_v2",
                },
                **(
                    {"coverage_matrix": coverage_for_review}
                    if coverage_for_review
                    else {}
                ),
                **(
                    {
                        "expert_review_feedback": _compact_prompt_value(
                            targeted_feedback,
                            max_string_chars=520,
                            max_list_items=8,
                        )
                    }
                    if targeted_feedback
                    else {}
                ),
            }
        if instance.mission_node in {"S3", "S4"}:
            # Creative S3/S4 never consume claim-bundle audit context.
            # This also covers reallocated/repair instances that carry a
            # hypothesis_id and therefore do not take the fresh-creator
            # overwrite path above.
            common_input.pop("evidence_index", None)
            common_input.pop("valid_reference_ids", None)
            common_input.pop("upstream_reasoning_seeds", None)
            creative_handoff = creative_military_value_handoff()
            if creative_handoff["claims"]:
                common_input["military_value_handoff"] = creative_handoff
            else:
                common_input.pop("military_value_handoff", None)
        if instance.mission_node in {"S1", "S2"}:
            common_input["equipment_portfolio_contract"] = {
                "selection_rule": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.selection_rule.2"
                    )
                ),
                "direct_equipment_definition": (
                    query_domain["subject_label"]
                    + "；"
                    + query_domain["direct_effect_label"]
                ),
                "query_domain_contract": query_domain,
                "free_divergence_first": True,
                "counterfactual_examples_available_after_divergence_only": True,
            }
        if instance.mission_node == "S6":
            common_input["s6_release_preflight"] = {
                "identity_and_scene": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.identity_and_scene.1"
                    )
                ),
                "evidence_boundary": (
                    load_dynamic_winning_prompt(
                        "common", section="call_instance.evidence_boundary.1"
                    )
                ),
                "quality_basis": load_dynamic_winning_prompt(
                    "common", section="call_instance.quality_basis.1"
                ),
            }
        if instance.mission_node == "S6" and baseline_boundaries:
            common_input["baseline_availability_boundaries"] = list(baseline_boundaries)
            common_input["baseline_boundary_rule"] = load_dynamic_winning_prompt(
                "common", section="call_instance.common_input.1"
            )
        if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
            await refresh_winning_angle_assignments()
            dimension_assignment = dict(
                winning_angle_assignments.get(instance.instance_id, {})
            )
            creative_handoff = creative_military_value_handoff()
            occupied_sibling_concepts: list[dict[str, Any]] = []
            live_coverage = None
            if ledger_snapshot is not None and ledger_snapshot.hypotheses:
                live_coverage = build_coverage_snapshot(
                    ledger_snapshot.hypotheses,
                    topic=str(shared.get("topic", "")),
                )
                for candidate in ledger_snapshot.hypotheses[:12]:
                    occupied_sibling_concepts.append(
                        {
                            "hypothesis_id": candidate.hypothesis_id,
                            "name": candidate.title,
                            "winning_angle_id": candidate.winning_angle_id,
                            "combat_dimension": candidate.combat_dimension,
                            "equipment_form": "；".join(
                                candidate.equipment_forms[:2]
                            )[:220],
                            "mechanism": "；".join(
                                candidate.mechanism_chain[:3]
                            )[:300],
                            "core_difference": (
                                candidate.core_disruptive_difference
                                or candidate.disruptive_shift
                                or candidate.changed_confrontation_variable
                            )[:240],
                            "direct_effect": "；".join(
                                candidate.direct_military_effects[:2]
                            )[:220],
                        }
                    )
            mission = assign_scout_mission(
                archetype=instance.archetype,
                topic=str(shared.get("topic", "")),
                occupied=live_coverage,
                forced_gap=gap_axis_from_residuals(instance.trigger_residuals),
                on_query_seat=(
                    instance.archetype == "disruptive_mechanism_generator"
                    and not gap_axis_from_residuals(instance.trigger_residuals)
                ),
            )
            # A coverage-gap recruit can be appended after the one-time
            # portfolio allocation. It intentionally has no persisted angle
            # row yet; still give that seat a non-empty, query-derived
            # starting question so the provider cannot receive an empty
            # diversity envelope (and so replay/audit can explain why it was
            # recruited). This is an open hint, not a forced equipment type.
            open_hint_battlefield = str(
                dimension_assignment.get("task_chain_breakpoint")
                or dimension_assignment.get("changed_confrontation_variable", "")
                or "、".join(mission.labels(mission.focus_values))
                or mission.axis_label
            ).strip()
            open_hint_result = str(
                dimension_assignment.get("desired_direct_result")
                or dimension_assignment.get("direct_military_result", "")
                or (
                    "、".join(mission.labels(mission.focus_values))
                    + "形成可证伪的直接军事结果"
                )
            ).strip()
            steer_instruction = load_dynamic_winning_prompt(
                "common", section="coverage_steer.instruction"
            ).format(
                axis_label=mission.axis_label,
                focus_labels="、".join(mission.labels(mission.focus_values))
                or "尚未覆盖的互补轴",
                avoid_labels="、".join(mission.labels(mission.avoid_values))
                or "无",
                occupied="；".join(mission.occupied_cluster_keys) or "无",
                salient="、".join(mission.labels(mission.query_salient_values))
                or "Query未显式锁定单轴",
            )
            common_input = {
                "execution_profile_id": shared.get("execution_profile_id", ""),
                "specialist_task": {
                    "archetype": task.archetype,
                    "merge_target": task.merge_target,
                    "mission_node": instance.mission_node,
                    "task_id": task.task_id,
                    "agent_instance_id": task.agent_instance_id,
                    # Keep the seat-specific brief in the structured handoff;
                    # the Markdown system prompt already carries the shared
                    # creative contract.  Repeating the long brief in the
                    # system string wastes context on every S3/S4 call.
                    "purpose": task.purpose,
                    "trigger_residuals": list(task.trigger_residuals),
                    "allow_child_spawn": False,
                    "military_expert_creative_contract": {
                        "role": (
                            load_dynamic_winning_prompt(
                                "common", section="call_instance.role.1"
                            )
                        ),
                        "diversity": (
                            load_dynamic_winning_prompt(
                                "common", section="call_instance.diversity.1"
                            )
                        ),
                        "naming_reference": (
                            load_dynamic_winning_prompt(
                                "common", section="call_instance.naming_reference.1"
                            )
                        ),
                    },
                },
                "query": str(shared.get("topic", "")),
                "open_exploration_hint": {
                    "battlefield_relationship": open_hint_battlefield,
                    "desired_direct_result": open_hint_result,
                },
                **(
                    {
                        # Both creative nodes receive the same structured
                        # three-slot envelope.  The compatibility ``code``
                        # is deliberately a neutral marker rather than a
                        # D1--D7 assignment; the actual dimensions remain
                        # the model's choice and are carried in the slots.
                        "winning_dimension_package": {
                            "code": load_dynamic_winning_prompt(
                                "common", section="s3_s4.open_dimension_package_code"
                            ),
                            "dimension": str(
                                dimension_assignment.get("combat_dimension")
                                or load_dynamic_winning_prompt(
                                    "common", section="s3_s4.open_dimension_package_label"
                                )
                            ),
                            "winning_logic": str(
                                dimension_assignment.get("dimension_winning_logic")
                                or load_dynamic_winning_prompt(
                                    "common", section="s3_s4.open_dimension_package_logic"
                                )
                            ),
                            "task_chain_breakpoint": str(
                                dimension_assignment.get("task_chain_breakpoint", "")
                            ),
                            "engagement_geometry": str(
                                dimension_assignment.get("engagement_geometry", "")
                            ),
                            "time_space_position": str(
                                dimension_assignment.get("time_space_position", "")
                            ),
                            "desired_direct_result": str(
                                dimension_assignment.get("desired_direct_result", "")
                            ),
                            "forward_winning_question": str(
                                dimension_assignment.get("forward_winning_question")
                                or load_dynamic_winning_prompt(
                                    "common", section="s3_s4.open_dimension_fallback"
                                )
                            ),
                            "exclusion_boundary": str(
                                dimension_assignment.get("exclusion_boundary", "")
                            ),
                            "primary_dimension": dict(
                                dimension_assignment.get("primary_dimension", {})
                            ),
                            "alternate_dimensions": [
                                dict(item)
                                for item in dimension_assignment.get(
                                    "alternate_dimensions", []
                                )
                                if isinstance(item, Mapping)
                            ],
                            "dimension_portfolio": [
                                dict(item)
                                for item in dimension_assignment.get(
                                    "dimension_portfolio", []
                                )
                                if isinstance(item, Mapping)
                            ],
                            # ``open_slot_items`` is the explicit list form;
                            # retain the historical boolean ``open_slots``
                            # for provider compatibility.
                            "open_slot_items": [
                                dict(item)
                                for item in dimension_assignment.get(
                                    "dimension_portfolio", []
                                )
                                if isinstance(item, Mapping)
                            ],
                            "dimensions_per_seat": list(
                                dimension_assignment.get("dimension_codes", [])
                            ),
                            "slot_count": 3,
                            "open_slots": True,
                            "open_slots_enabled": True,
                            "reference_dimension_codes": list(
                                dimension_assignment.get(
                                    "reference_dimension_codes", []
                                )
                            ),
                            "reference_only_dimension_codes": list(
                                dimension_assignment.get(
                                    "reference_dimension_codes", []
                                )
                            ),
                            "dimension_mode": "model_derived_open_slots",
                            "seat_rule": load_dynamic_winning_prompt(
                                "common", section="s3_s4.seat_rule"
                            ),
                        }
                    }
                ),
                "coverage_steer": mission.to_payload(steer_instruction),
                "occupied_sibling_concepts": occupied_sibling_concepts,
                "occupied_s3_core_concepts": occupied_sibling_concepts,
                "occupied_s3_boundary_rule": load_dynamic_winning_prompt(
                    "common", section="s3_s4.occupied_boundary_rule"
                ),
                **(
                    {"military_value_handoff": creative_handoff}
                    if creative_handoff["claims"]
                    else {}
                ),
                **(
                    {
                        "expert_review_feedback": _compact_prompt_value(
                            targeted_feedback,
                            max_string_chars=520,
                            max_list_items=8,
                        )
                    }
                    if targeted_feedback
                    else {}
                ),
            }
        if instance.mission_node in {"S1", "S2"} and not instance.hypothesis_id:
            output_schema = _dynamic_output_schema("s1_s2.output_schema")
            instruction = load_dynamic_winning_prompt(instance.mission_node)
            phase = "winning_swarm_dynamic_reasoning_seed"
        elif instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
            # Keep the compact name+summary card stable for existing
            # providers, while transporting the creator's actual dimension
            # choice in an auditable sidecar owned by common.md.
            output_schema = _dynamic_output_schema("s3_s4.output_schema")
            hypothesis_template = dict(
                (output_schema.get("hypotheses") or [{}])[0]
            )
            output_schema["hypotheses"] = [
                {
                    **hypothesis_template,
                    "name": load_dynamic_winning_prompt(
                        "common", section=f"call_instance.name.{index}"
                    ),
                    "concise_winning_summary": load_dynamic_winning_prompt(
                        "common",
                        section=f"call_instance.concise_winning_summary.{index}",
                    ),
                }
                for index in (1, 2, 3)
            ]
            instruction = load_dynamic_winning_prompt(instance.mission_node)
            phase = "winning_swarm_dynamic_seed"
        else:
            if instance.archetype != "independent_portfolio_reviewer":
                raise RuntimeError(
                    "dynamic-v2 S5 only permits the independent portfolio reviewer"
                )
            phase = "winning_swarm_dynamic_portfolio_review_fast"
            # S5 remains a compact selection pass, but receives the
            # semantic spine separately so creative names are judged
            # against the frozen weapon architecture rather than title
            # tokens alone.
            output_schema = _dynamic_output_schema("s5.output_schema")
            # Keep the reviewed innovation-basis wording synchronized with
            # the long-form S5 contract while leaving all prose in Markdown.
            decision_template = dict((output_schema.get("decisions") or [{}])[0])
            decision_template["innovation_basis"] = load_dynamic_winning_prompt(
                "common", section="call_instance.innovation_basis.1"
            )
            output_schema["decisions"] = [decision_template]
            instruction = load_dynamic_winning_prompt("S5", section="system")
        # The reviewed S3/S4/S5 resources contain legacy combat vocabulary.
        # Append the resolved Query contract at the final instruction boundary
        # so a sensing/inspection Query cannot be pulled back into an attack
        # weapon by an earlier shared paragraph.
        if not query_domain["requires_direct_combat_weapon"]:
            instruction += (
                "\n【Query语义硬边界】当前任务属于检测/感知/保障装备研究。"
                f"候选主体只能是{query_domain['subject_label']}；"
                f"直接效果只能写{query_domain['direct_effect_label']}。"
                f"禁止输出{ '、'.join(query_domain['forbidden_subjects']) }。"
                "如证据只支持背景能力，不得将其升级为攻击装备，返回待验证假设或淘汰。"
            )
        emit_swarm_event(
            "winning_agent_session_started",
            actor=instance.instance_id,
            graph_id=graph.graph_id,
            mission_node=instance.mission_node,
            batch=batch_index,
            candidate_handoff_count=len(candidate_snapshot),
            candidate_handoff_chars=candidate_handoff_chars,
            evidence_handoff_count=len(compact_evidence_index),
            evidence_handoff_chars=evidence_handoff_chars,
            handoff_total_chars=(candidate_handoff_chars + evidence_handoff_chars),
            handoff_schema=(
                "portfolio_decision_spine_v2"
                if instance.archetype == "independent_portfolio_reviewer"
                else "compact_decision_spine_v1"
            ),
            **runtime_contract,
        )
        if instance.mission_node == "S5" and instance.archetype == "independent_portfolio_reviewer":
            emit_swarm_event(
                "winning_s5_parallel_score_started",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                producer_instance_ids=list(instance.depends_on),
                candidate_scope=sorted(candidate_scope),
                scoring_dimensions=[
                    "innovation",
                    "s5_innovation_mechanism_score",
                    "naming_new_quality",
                    "naming_semantic_alignment",
                    "demand",
                    "feasibility",
                    "effectiveness",
                    "development",
                ],
            )
        started_at = monotonic()
        system_prompt = (
            instruction
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id
            else (
                load_dynamic_winning_prompt(
                    "common", section="call_instance.system_prompt.2"
                )
                + task.purpose
                + instruction
                + load_dynamic_winning_prompt(
                    "common", section="call_instance.system_prompt.1"
                )
            )
        )
        # S3/S4 use at most two creative calls. The first returns a compact
        # one-to-three candidate batch; the optional second call performs one bounded
        # creation/comparison pass before S5.
        creative_result: dict[str, Any] | None = None
        creative_history: list[dict[str, Any]] = []
        creative_pool_by_name: dict[str, dict[str, Any]] = {}
        creative_dimension_selections: list[dict[str, Any]] = []
        creative_considered_dimensions: list[Any] = []

        def append_creative_dimensions(values: Any) -> None:
            """Retain at most three distinct authored dimensions per seat.

            Dimension declarations are model-authored and may differ only by
            formatting (for example ``D1`` versus its reviewed label).  Use the
            same structural identity normalizer as the early-stop gate so those
            variants do not consume separate slots.  Controller transport markers
            are ignored rather than promoted into fake dimensions.
            """

            if not isinstance(values, list):
                return
            for value in values:
                if value in (None, "", {}, []):
                    continue
                identities = _s3_s4_structural_dimension_identities([value])
                if not identities:
                    continue
                existing = _s3_s4_structural_dimension_identities(
                    creative_considered_dimensions
                )
                if identities & existing:
                    continue
                creative_considered_dimensions.append(value)
                if len(creative_considered_dimensions) >= 3:
                    break
        try:
            configured_creative_passes = int(
                os.environ.get(
                    "EQUIPMENT_DR_S3_S4_CREATIVE_PASSES",
                    str(swarm_controller.policy.get("s3_s4_creative_passes", 1)),
                )
            )
        except (TypeError, ValueError):
            configured_creative_passes = 1
        creative_passes = (
            max(1, min(2, configured_creative_passes))
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id
            else 1
        )
        for creative_iteration in range(1, creative_passes + 1):
            iteration_input: dict[str, Any] = dict(common_input)
            iteration_system = system_prompt
            iteration_phase = phase
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                seat_assignment = dict(
                    naming_plan.get("assignments", {}).get(instance.instance_id, {})
                )
                # The portfolio plan is allocated once per graph. Reuse the
                # exact assignment across creative iterations and retries.
                iteration_input["random_naming_style_assignment"] = seat_assignment
                iteration_system += load_dynamic_winning_prompt(
                    "common", section="call_instance.iteration_system.1"
                )
            if (
                creative_history
                or creative_dimension_selections
                or creative_considered_dimensions
            ):
                if creative_history:
                    iteration_input["previous_creative_draft"] = creative_history[-1]
                # Keep the legacy single-row field above for provider
                # compatibility, while exposing the complete prior batch and
                # dimension trace so a bounded second pass can fill missing
                # dimensions instead of rediscovering only the last row.
                iteration_input["previous_creative_draft_batch"] = {
                    "hypotheses": [dict(row) for row in creative_history],
                    "dimension_selections": [
                        dict(row) for row in creative_dimension_selections
                    ],
                    "considered_dimensions": list(creative_considered_dimensions),
                }
                iteration_input["session_candidate_pool"] = [
                    {
                        "name": str(row.get("name", "") or row.get("title", "")),
                        "concise_winning_summary": str(
                            row.get("concise_winning_summary", "")
                        ),
                    }
                    for row in creative_pool_by_name.values()
                ][-3:]
                iteration_input["creative_iteration"] = creative_iteration
                iteration_system += load_dynamic_winning_prompt(
                    "common", section="call_instance.iteration_system.2"
                )
            try:
                iteration_text = await host._run_core_json(
                    runtime_agent_id,
                    iteration_system,
                    iteration_input,
                    output_schema,
                    task.max_output_tokens,
                    phase=iteration_phase,
                )
                parsed_iteration = _parse_json_object(iteration_text)
            except BaseException:
                # A capacity/transient failure in the optional critique
                # must not erase a valid first creative draft.  When the
                # first pass itself fails structurally, consume the reserved
                # second pass before surfacing the failure to the outer
                # instance retry path.
                if creative_result is not None:
                    emit_swarm_event(
                        "winning_s3_s4_creative_iteration_limited",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        iteration=creative_iteration,
                        retained_previous=True,
                    )
                    break
                if creative_iteration < creative_passes:
                    emit_swarm_event(
                        "winning_s3_s4_creative_iteration_retrying",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        iteration=creative_iteration,
                        reason="structural_failure",
                    )
                    creative_result = {"hypotheses": []}
                    creative_history = []
                    continue
                raise
            if not parsed_iteration:
                if creative_result is not None:
                    break
                if creative_iteration < creative_passes:
                    emit_swarm_event(
                        "winning_s3_s4_creative_iteration_retrying",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        iteration=creative_iteration,
                        reason="empty_or_invalid_structure",
                    )
                    continue
                raise ValueError(f"{instance.instance_id} returned invalid JSON")
            if instance.mission_node in {"S3", "S4"}:
                raw_dimension_selections = parsed_iteration.get(
                    "dimension_selections", []
                )
                if isinstance(raw_dimension_selections, list):
                    # Some providers place the only dimension declarations in
                    # the sidecar array. Preserve those declarations for the
                    # bounded second pass as well; the structural gate and
                    # S5 resolver already treat both locations equivalently.
                    parsed_dimension_selections = [
                        dict(item)
                        for item in raw_dimension_selections
                        if isinstance(item, Mapping)
                    ][:3]
                    if parsed_dimension_selections:
                        creative_dimension_selections = parsed_dimension_selections
                # Candidate-linked selections are the most specific signal.
                # Consume them before the free-form considered list so broad
                # labels cannot occupy all three structural slots and force a
                # redundant second pass before the model's concrete choices
                # are seen.
                append_creative_dimensions(raw_dimension_selections)
                raw_considered_dimensions = parsed_iteration.get(
                    "considered_dimensions", []
                )
                append_creative_dimensions(raw_considered_dimensions)
            if instance.mission_node in {"S3", "S4"}:
                emit_swarm_event(
                    "winning_s3_first_pass_self_admission_completed",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    mission_node=instance.mission_node,
                    creative_iteration=creative_iteration,
                    candidate_maximum_per_session=max(
                        1,
                        int(
                            swarm_controller.policy.get(
                                "s3_s4_candidate_maximum_per_session", 3
                            )
                        ),
                    ),
                    separate_precommit_model_call=False,
                    candidate_count=len(
                        parsed_iteration.get("hypotheses", [])
                        if isinstance(parsed_iteration.get("hypotheses", []), list)
                        else []
                    ),
                    rule=load_dynamic_winning_prompt(
                        "common", section="s3_s4.post_generation_rule"
                    ),
                    naming_assignment={
                        "assignment_version": naming_plan.get(
                            "assignment_version", NAMING_ASSIGNMENT_VERSION
                        ),
                        "codes": [
                            str(row.get("code", ""))
                            for row in naming_plan.get("assignments", {})
                            .get(instance.instance_id, {})
                            .get("candidate_order", [])
                        ],
                    },
                )
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                iteration_rows = parsed_iteration.get("hypotheses", [])
                if not isinstance(iteration_rows, list):
                    iteration_rows = []
                session_candidate_maximum = max(
                    1,
                    int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_maximum_per_session", 3
                        )
                    ),
                )
                usable_rows = [
                    dict(row)
                    for row in iteration_rows[:session_candidate_maximum]
                    if isinstance(row, Mapping)
                    and str(row.get("name", "") or row.get("title", "")).strip()
                    and str(row.get("concise_winning_summary", "")).strip()
                ]
                if usable_rows:
                    # Retain the bounded batch from this one creative call.
                    for row in usable_rows:
                        name_key = str(
                            row.get("name", "") or row.get("title", "")
                        ).strip()
                        if name_key:
                            creative_pool_by_name[name_key] = row
                    pool_cap = int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_pool_maximum_per_session", 3
                        )
                    )
                    pooled_rows = list(creative_pool_by_name.values())[-pool_cap:]
                    creative_result = {
                        **parsed_iteration,
                        "hypotheses": pooled_rows,
                        "dimension_selections": creative_dimension_selections,
                        "considered_dimensions": creative_considered_dimensions,
                    }
                    creative_history = usable_rows
                    # A complete first pass need not pay for a redundant
                    # second creative call.  This is deliberately a
                    # structural gate: field presence plus three distinct
                    # declared/adopted dimensions.  S5 still owns all
                    # semantic quality, independence and admission decisions.
                    first_pass_complete, dimension_identities = (
                        _s3_s4_first_pass_structurally_complete(
                            parsed_iteration,
                            usable_rows,
                        )
                    )
                    if creative_iteration == 1 and first_pass_complete:
                        emit_swarm_event(
                            "winning_s3_s4_creative_early_stopped",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node=instance.mission_node,
                            completed_iteration=creative_iteration,
                            candidate_count=len(usable_rows),
                            dimension_count=len(dimension_identities),
                            dimension_identities=sorted(dimension_identities),
                            rule=load_dynamic_winning_prompt(
                                "common", section="call_instance.early_stop_rule.1"
                            ),
                        )
                        break
                elif creative_result is None:
                    creative_result = {
                        **parsed_iteration,
                        "dimension_selections": creative_dimension_selections,
                        "considered_dimensions": creative_considered_dimensions,
                    }
                    creative_history = []
            else:
                creative_result = parsed_iteration
                break
        result = creative_result or {}
        if not result:
            raise ValueError(f"{instance.instance_id} returned invalid JSON")
        if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
            raw_hypotheses = result.get("hypotheses", [])
            if not isinstance(raw_hypotheses, list):
                raw_hypotheses = []
            raw_candidate_count = len(raw_hypotheses)
            candidate_maximum = max(
                1,
                int(
                    swarm_controller.policy.get(
                        "s3_s4_candidate_maximum_per_session", 3
                    )
                ),
            )
            candidate_pool_maximum = max(
                candidate_maximum,
                int(
                    swarm_controller.policy.get(
                        "s3_s4_candidate_pool_maximum_per_session",
                        candidate_maximum,
                    )
                ),
            )
            # Keep the model handoff itself compact so retries, language
            # repair and audit events all describe the same bounded pool.
            raw_hypotheses = raw_hypotheses[:candidate_pool_maximum]
            result = {**result, "hypotheses": raw_hypotheses}
            if raw_candidate_count > candidate_pool_maximum:
                emit_swarm_event(
                    "winning_s3_s4_candidate_output_bounded",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    mission_node=instance.mission_node,
                    requested_candidate_count=raw_candidate_count,
                    retained_candidate_count=len(raw_hypotheses),
                    candidate_maximum_per_session=candidate_maximum,
                    candidate_pool_maximum_per_session=candidate_pool_maximum,
                    reason=(
                        "质量优先：每个S3/S4创作会话只保留最强候选，避免把同构变体带入S5"
                    ),
                )
            language_failures = [
                {
                    "position": position,
                    "name": str(item.get("name", "")).strip(),
                    "summary": str(item.get("concise_winning_summary", "")).strip(),
                    "issues": winning_summary_language_issues(
                        item.get("concise_winning_summary", "")
                    ),
                }
                for position, item in enumerate(raw_hypotheses, start=1)
                if isinstance(item, Mapping)
                and winning_summary_language_issues(
                    item.get("concise_winning_summary", "")
                )
            ]
            name_failures = [
                {
                    "position": position,
                    "name": str(item.get("name", "") or item.get("title", "")).strip(),
                    "issues": _s3_s4_name_authoring_issues(
                        item.get("name", "") or item.get("title", "")
                    ),
                }
                for position, item in enumerate(raw_hypotheses, start=1)
                if isinstance(item, Mapping)
                and _s3_s4_name_authoring_issues(
                    item.get("name", "") or item.get("title", "")
                )
            ]
            if name_failures:
                emit_swarm_event(
                    "winning_s3_s4_name_authoring_diagnostic",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    mission_node=instance.mission_node,
                    failure_count=len(name_failures),
                    failures=name_failures[:4],
                    rule=load_dynamic_winning_prompt(
                        "common", section="s3_s4.name_diagnostic_rule"
                    ),
                )
            # Language/name diagnostics are recorded above but do not trigger
            # a second S3/S4 model call.  The seat is intentionally one-shot;
            # S5 owns downstream comparison and selection.
        emit_swarm_event(
            "winning_agent_session_completed",
            actor=instance.instance_id,
            graph_id=graph.graph_id,
            mission_node=instance.mission_node,
            batch=batch_index,
            elapsed_seconds=round(monotonic() - started_at, 3),
            **runtime_contract,
        )
        return (
            instance,
            result,
            (ledger_snapshot.version if ledger_snapshot is not None else 0),
        )

    def refresh_candidate_ledger() -> dict[str, str]:
        """Publish newly completed seed branches without a global barrier."""

        nonlocal ledger
        candidates_by_id = {
            item.hypothesis_id: item
            for item in hypotheses
            if item.hypothesis_id not in portfolio_rejected_ids
            and canonical_candidate_id(item.hypothesis_id) == item.hypothesis_id
        }
        if ledger is not None:
            # Preserve already merged S4-S6 fields when a slower S3
            # branch publishes an additional candidate.
            candidates_by_id.update(
                {item.hypothesis_id: item for item in ledger.hypotheses}
            )
        # Do not perform local lexical or score-based admission before S5.
        # Producer IDs are already unique; S5 owns semantic merge/reject
        # decisions against the complete portfolio.
        unique = list(candidates_by_id.values())
        semantic_merges: list[dict[str, Any]] = []
        # Keep all bounded seed branches while downstream work is in
        # flight.  Early score/id truncation invalidated already-issued
        # candidate scopes and produced unknown_hypothesis_id rejects.
        unique = list(unique)
        id_remap = {
            str(item["source_hypothesis_id"]): str(item["target_hypothesis_id"])
            for item in semantic_merges
        }
        for source_id, target_id in id_remap.items():
            candidate_id_aliases[source_id] = canonical_candidate_id(target_id)
        for source_id in list(candidate_id_aliases):
            candidate_id_aliases[source_id] = canonical_candidate_id(
                candidate_id_aliases[source_id]
            )
        for instance_id, scoped_ids in list(instance_hypothesis_ids.items()):
            instance_hypothesis_ids[instance_id] = {
                canonical_candidate_id(item) for item in scoped_ids
            }
        state.swarm_merges.extend(semantic_merges)
        state.swarm_hypotheses.update({item.hypothesis_id: item for item in unique})
        if ledger is None:
            ledger = swarm_controller.create_ledger(unique)
        elif {item.hypothesis_id for item in ledger.hypotheses} != {
            item.hypothesis_id for item in unique
        }:
            ledger = HypothesisLedgerVersion(
                ledger_id=ledger.ledger_id,
                version=ledger.version + 1,
                parent_version=ledger.version,
                hypotheses=unique,
                merge_receipts=list(ledger.merge_receipts),
                change_summary="candidate_branch_published",
                created_by="winning_swarm_controller",
            )
        emit_swarm_event(
            "winning_candidate_ledger_frozen",
            graph_id=graph.graph_id,
            ledger_id=ledger.ledger_id,
            ledger_version=ledger.version,
            candidate_count=len(unique),
            incremental=True,
        )
        return id_remap

    def compact_candidate_ledger_for_review() -> None:
        """Plan a bounded legacy review scope without deleting candidates.

        Dynamic-v2 bypasses this compatibility helper because incremental
        S5 scope is driven by newly completed candidate ids.
        """

        nonlocal initial_expert_review_scope
        if str(swarm_controller.policy.get("policy_id")) == "winning_swarm_dynamic_v2":
            # Dynamic S5 reviewers receive disjoint creator-scoped slices;
            # never pre-trim the durable ledger with a local quota.
            initial_expert_review_scope = None
            return
        pool_maximum = int(
            swarm_controller.policy.get("expert_candidate_pool_maximum", 8)
        )
        if ledger is None:
            return
        if len(ledger.hypotheses) <= pool_maximum:
            initial_expert_review_scope = None
            return
        retained = swarm_controller.retain_diverse_candidates(
            ledger.hypotheses,
            maximum=pool_maximum,
        )
        initial_expert_review_scope = {item.hypothesis_id for item in retained}
        emit_swarm_event(
            "winning_candidate_review_scope_planned",
            graph_id=graph.graph_id,
            ledger_id=ledger.ledger_id,
            ledger_version=ledger.version,
            complete_candidate_count=len(ledger.hypotheses),
            review_candidate_count=len(retained),
            review_candidate_ids=sorted(initial_expert_review_scope),
            rule=load_dynamic_winning_prompt(
                "common", section="s3_s4.review_capacity_rule"
            ),
        )

    async def semantic_cluster_candidate_ledger(
        *,
        scope_id: str,
        changed_hypothesis_ids: set[str] | None = None,
    ) -> dict[str, str]:
        """Publish the isolated Codex five-axis clustering decision."""

        nonlocal ledger, semantic_clustered_ledger_version
        if ledger is None or ledger.version == semantic_clustered_ledger_version:
            return {}
        source_ledger = ledger
        source_candidates = list(source_ledger.hypotheses)
        source_by_id = {item.hypothesis_id: item for item in source_candidates}

        # ``clustering.py`` intentionally uses the hypothesis ``score`` only
        # to choose a representative inside an equivalence group.  Give it a
        # score-shadow carrying the authoritative S5 weighted score, then
        # restore the original candidate objects immediately after the call.
        # This keeps semantic clustering independent while ensuring that a
        # high-scoring S5 candidate, rather than an earlier/luckier producer,
        # becomes the durable representative.
        scored_candidates: list[WinningHypothesis] = []
        for item in source_candidates:
            weighted = candidate_weighted_scores.get(item.hypothesis_id)
            if weighted is None:
                scored_candidates.append(item)
                continue
            try:
                shadow_score = max(0.0, min(1.0, float(weighted)))
            except (TypeError, ValueError):
                shadow_score = item.score
            scored_candidates.append(replace(item, score=shadow_score))
        (
            clustered,
            semantic_merges,
        ) = await cluster_hypotheses_with_independent_codex(
            scored_candidates,
            scope_id=scope_id,
            changed_hypothesis_ids=changed_hypothesis_ids,
        )

        # Never let a provider-side score shadow leak into the ledger.  A
        # defensive fallback also protects compatibility stubs that return a
        # freshly reconstructed candidate object with the same ID.
        clustered = [
            source_by_id.get(item.hypothesis_id, item)
            for item in clustered
            if getattr(item, "hypothesis_id", "")
        ]
        live_source_ids = set(source_by_id)
        valid_merges: list[dict[str, str]] = []
        for raw_merge in semantic_merges:
            if not isinstance(raw_merge, Mapping):
                continue
            source_id = str(raw_merge.get("source_hypothesis_id", "")).strip()
            target_id = str(raw_merge.get("target_hypothesis_id", "")).strip()
            if (
                not source_id
                or not target_id
                or source_id == target_id
                or source_id not in live_source_ids
                or target_id not in live_source_ids
            ):
                continue
            valid_merges.append(
                {
                    "source_hypothesis_id": source_id,
                    "target_hypothesis_id": target_id,
                    "reason": str(
                        raw_merge.get("reason")
                        or "independent_codex_five_axis_semantic_cluster"
                    )[:240],
                }
            )

        # Build equivalence groups from the independent pair judgements.  The
        # clustering service normally chooses a representative by the
        # hypothesis score, but S5's weighted score is the authoritative
        # portfolio signal.  Re-select the representative here so provider
        # fallbacks and test doubles obey the same contract.
        parent: dict[str, str] = {
            item.hypothesis_id: item.hypothesis_id for item in source_candidates
        }

        def find(value: str) -> str:
            root = value
            while parent.get(root, root) != root:
                root = parent[root]
            while parent.get(value, value) != value:
                next_value = parent[value]
                parent[value] = root
                value = next_value
            return root

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for row in valid_merges:
            union(row["source_hypothesis_id"], row["target_hypothesis_id"])
        grouped_ids: dict[str, set[str]] = {}
        for candidate_id in parent:
            grouped_ids.setdefault(find(candidate_id), set()).add(candidate_id)

        def representative_rank(
            candidate_id: str,
        ) -> tuple[float, float, int, float, int, str]:
            try:
                weighted = float(
                    candidate_weighted_scores.get(candidate_id, float("-inf"))
                )
            except (TypeError, ValueError):
                weighted = float("-inf")
            try:
                priority = float(
                    candidate_innovation_priorities.get(candidate_id, 0.0) or 0.0
                )
            except (TypeError, ValueError):
                priority = 0.0
            tier = _s5_disruption_tier_rank(
                candidate_disruption_tiers.get(candidate_id), priority
            )
            try:
                base_score = float(source_by_id[candidate_id].score or 0.0)
            except (KeyError, TypeError, ValueError):
                base_score = 0.0
            # Earlier portfolio order hints win only after the S5 score and
            # disruption signals, keeping tie-breaking deterministic.
            hint = -int(portfolio_order_hints.get(candidate_id, 10**9))
            return (weighted, priority, tier, base_score, hint, candidate_id)

        canonical_merge_map: dict[str, str] = {}
        for members in grouped_ids.values():
            if len(members) < 2:
                continue
            representative = max(members, key=representative_rank)
            for member in members:
                if member != representative:
                    canonical_merge_map[member] = representative

        # Publish aliases first, then collapse alias chains.  The same helper
        # is used for old S5 merge aliases and this close-out pass, so every
        # score/assessment map has one canonical key before final ordering.
        for source_id, target_id in canonical_merge_map.items():
            candidate_id_aliases[source_id] = target_id
        for source_id in list(candidate_id_aliases):
            candidate_id_aliases[source_id] = canonical_candidate_id(
                candidate_id_aliases[source_id]
            )

        # Merge all per-candidate S5 metadata into the canonical target.  A
        # target normally already is the highest S5-scoring row (because of
        # the score-shadow above), but this code remains defensive for old
        # checkpoints and provider fallbacks where maps are incomplete.
        def merge_candidate_metadata(source_id: str, target_id: str) -> None:
            if source_id == target_id:
                return
            try:
                source_score = float(candidate_weighted_scores[source_id])
            except (KeyError, TypeError, ValueError):
                source_score = None
            try:
                target_score = float(candidate_weighted_scores[target_id])
            except (KeyError, TypeError, ValueError):
                target_score = None
            source_is_better = source_score is not None and (
                target_score is None or source_score > target_score
            )
            if source_score is not None:
                candidate_weighted_scores[target_id] = max(
                    target_score if target_score is not None else source_score,
                    source_score,
                )
            if source_is_better:
                if source_id in candidate_dimension_scores:
                    candidate_dimension_scores[target_id] = dict(
                        candidate_dimension_scores[source_id]
                    )
                if source_id in candidate_innovation_bases:
                    candidate_innovation_bases[target_id] = (
                        candidate_innovation_bases[source_id]
                    )
                if source_id in candidate_naming_assessments:
                    candidate_naming_assessments[target_id] = dict(
                        candidate_naming_assessments[source_id]
                    )
            else:
                candidate_dimension_scores.setdefault(
                    target_id,
                    dict(candidate_dimension_scores.get(source_id, {})),
                )
                candidate_innovation_bases.setdefault(
                    target_id,
                    candidate_innovation_bases.get(source_id, ""),
                )
                if target_id not in candidate_naming_assessments and source_id in candidate_naming_assessments:
                    candidate_naming_assessments[target_id] = dict(
                        candidate_naming_assessments[source_id]
                    )
            if source_id in candidate_innovation_priorities:
                candidate_innovation_priorities[target_id] = max(
                    candidate_innovation_priorities.get(target_id, 0.0),
                    candidate_innovation_priorities[source_id],
                )
            if source_id in candidate_innovation_bases:
                candidate_innovation_bases.setdefault(
                    target_id, candidate_innovation_bases[source_id]
                )
            source_tier = _s5_disruption_tier_rank(
                candidate_disruption_tiers.get(source_id),
                candidate_innovation_priorities.get(source_id),
            )
            target_tier = _s5_disruption_tier_rank(
                candidate_disruption_tiers.get(target_id),
                candidate_innovation_priorities.get(target_id),
            )
            if source_tier > target_tier:
                if candidate_disruption_tiers.get(source_id):
                    candidate_disruption_tiers[target_id] = candidate_disruption_tiers[
                        source_id
                    ]
                for mapping, default in (
                    (candidate_displaced_modes, ""),
                    (candidate_new_operational_modes, ""),
                    (candidate_winning_relation_shifts, ""),
                ):
                    if source_id in mapping and mapping[source_id]:
                        mapping[target_id] = mapping[source_id]
            else:
                for mapping in (
                    candidate_displaced_modes,
                    candidate_new_operational_modes,
                    candidate_winning_relation_shifts,
                ):
                    if not mapping.get(target_id) and mapping.get(source_id):
                        mapping[target_id] = mapping[source_id]
            if source_id in portfolio_order_hints:
                current_hint = portfolio_order_hints.get(target_id, 10**9)
                portfolio_order_hints[target_id] = min(
                    current_hint, portfolio_order_hints[source_id]
                )
            for mapping in (
                candidate_innovation_priorities,
                candidate_innovation_bases,
                candidate_dimension_scores,
                candidate_weighted_scores,
                candidate_naming_assessments,
                candidate_disruption_tiers,
                candidate_displaced_modes,
                candidate_new_operational_modes,
                candidate_winning_relation_shifts,
                portfolio_order_hints,
            ):
                mapping.pop(source_id, None)

        for source_id, target_id in list(canonical_merge_map.items()):
            target_id = canonical_candidate_id(target_id)
            canonical_merge_map[source_id] = target_id
            merge_candidate_metadata(source_id, target_id)

        # Canonicalize all historical maps as well (not only this call's
        # merges), then normalize scopes and run-local state to the live ledger.
        for source_id in list(candidate_id_aliases):
            target_id = canonical_candidate_id(source_id)
            if source_id != target_id:
                merge_candidate_metadata(source_id, target_id)
        # Rebuild the returned candidate list from canonical source objects.
        # This both removes non-representative aliases and prevents a
        # score-shadow or provider-side reconstructed object from leaking into
        # the durable ledger. Any non-merged source omitted by a malformed
        # compatibility stub is conservatively restored.
        rebuilt_clustered: list[WinningHypothesis] = []
        seen_cluster_ids: set[str] = set()
        for item in clustered:
            source_id = getattr(item, "hypothesis_id", "")
            canonical_id = canonical_candidate_id(source_id)
            if not canonical_id or canonical_id in seen_cluster_ids:
                continue
            original = source_by_id.get(canonical_id) or source_by_id.get(source_id)
            if original is not None:
                rebuilt_clustered.append(original)
                seen_cluster_ids.add(canonical_id)
        for source_id, original in source_by_id.items():
            canonical_id = canonical_candidate_id(source_id)
            if source_id in canonical_merge_map or canonical_id in seen_cluster_ids:
                continue
            rebuilt_clustered.append(original)
            seen_cluster_ids.add(canonical_id)
        clustered = rebuilt_clustered
        live_ids = {item.hypothesis_id for item in clustered}
        for instance_id, scoped_ids in list(instance_hypothesis_ids.items()):
            instance_hypothesis_ids[instance_id] = {
                canonical_candidate_id(item)
                for item in scoped_ids
                if canonical_candidate_id(item) in live_ids
            }
        for instance_id, scoped_ids in list(review_targets_by_instance.items()):
            review_targets_by_instance[instance_id] = {
                canonical_candidate_id(item)
                for item in scoped_ids
                if canonical_candidate_id(item) in live_ids
            }
        reviewed_candidate_ids.intersection_update(live_source_ids | live_ids)
        reviewed_candidate_ids.update(
            canonical_candidate_id(item) for item in list(reviewed_candidate_ids)
        )
        pending_incremental_review_ids.intersection_update(live_source_ids | live_ids)
        pending_incremental_review_ids.update(
            canonical_candidate_id(item)
            for item in list(pending_incremental_review_ids)
        )
        # A semantic merge is not a rejection.  Remove only its source alias
        # from the rejection set; genuine S5 rejects remain auditable.
        portfolio_rejected_ids.difference_update(canonical_merge_map)
        state.swarm_hypotheses = {
            item.hypothesis_id: item for item in clustered
        }

        known_merge_keys = {
            (
                item.get("source_hypothesis_id", ""),
                item.get("target_hypothesis_id", ""),
                item.get("reason", ""),
            )
            for item in state.swarm_merges
        }
        normalized_merge_rows: list[dict[str, str]] = []
        for row in valid_merges:
            source_id = row["source_hypothesis_id"]
            target_id = canonical_merge_map.get(
                source_id,
                canonical_merge_map.get(row["target_hypothesis_id"], row["target_hypothesis_id"]),
            )
            if source_id == target_id:
                continue
            normalized_merge_rows.append(
                {
                    "source_hypothesis_id": source_id,
                    "target_hypothesis_id": target_id,
                    "reason": row.get("reason", "")[:240],
                }
            )
        for source_id, target_id in canonical_merge_map.items():
            if source_id == target_id:
                continue
            row = {
                "source_hypothesis_id": source_id,
                "target_hypothesis_id": target_id,
                "reason": "s5_weighted_representative_selection",
            }
            if row not in normalized_merge_rows:
                normalized_merge_rows.append(row)
        for item in normalized_merge_rows:
            merge_key = (
                item.get("source_hypothesis_id", ""),
                item.get("target_hypothesis_id", ""),
                item.get("reason", ""),
            )
            if merge_key not in known_merge_keys:
                state.swarm_merges.append(item)
                known_merge_keys.add(merge_key)
                emit_swarm_event("hypothesis_merged", **item)
        if {item.hypothesis_id for item in clustered} != {
            item.hypothesis_id for item in ledger.hypotheses
        }:
            ledger = HypothesisLedgerVersion(
                ledger_id=ledger.ledger_id,
                version=ledger.version + 1,
                parent_version=ledger.version,
                hypotheses=clustered,
                merge_receipts=list(ledger.merge_receipts),
                change_summary="independent_codex_five_axis_clustering",
                created_by="winning_semantic_clusterer",
            )
            emit_swarm_event(
                "winning_candidate_ledger_frozen",
                graph_id=graph.graph_id,
                ledger_id=ledger.ledger_id,
                ledger_version=ledger.version,
                candidate_count=len(clustered),
                incremental=False,
                compaction_reason="independent_codex_five_axis_clustering",
            )
        semantic_clustered_ledger_version = ledger.version
        semantic_cluster_audit.update(
            {
                "scope_id": scope_id,
                "candidate_count_before": len(source_candidates),
                "candidate_count_after": len(clustered),
                "merged_count": len(canonical_merge_map),
                "merge_map": dict(sorted(canonical_merge_map.items())),
                "status": "completed",
            }
        )
        return canonical_merge_map

    def scope_for_instance(
        item: WinningAgentInstance,
        ledger_snapshot: HypothesisLedgerVersion | None,
    ) -> set[str]:
        if item.instance_id in review_targets_by_instance:
            return {
                canonical_candidate_id(value)
                for value in review_targets_by_instance[item.instance_id]
            }
        if item.hypothesis_id:
            return {canonical_candidate_id(item.hypothesis_id)}
        if (
            item.archetype == "independent_portfolio_reviewer"
            and ledger_snapshot is not None
            and (
                str(swarm_controller.policy.get("policy_id"))
                != "winning_swarm_dynamic_v2"
                or not is_dynamic_paired_reviewer(item)
            )
        ):
            return {
                hypothesis.hypothesis_id for hypothesis in ledger_snapshot.hypotheses
            }
        return {
            canonical_candidate_id(hypothesis_id)
            for dependency in item.depends_on
            for hypothesis_id in instance_hypothesis_ids.get(dependency, set())
        }

    def is_dynamic_paired_reviewer(item: WinningAgentInstance) -> bool:
        """Return whether an S5 seat is still paired with exactly one creator.

        Dynamic-v2 first wave now uses cross-pool reviewers (multiple
        producer dependencies).  The one-producer predicate is retained so a
        compatibility graph can still skip an empty paired slice without
        expanding that reviewer onto the full ledger.
        """

        return (
            str(swarm_controller.policy.get("policy_id"))
            == "winning_swarm_dynamic_v2"
            and item.mission_node == "S5"
            and item.archetype == "independent_portfolio_reviewer"
            and len(item.depends_on) == 1
        )

    def effective_scope_for_instance(
        item: WinningAgentInstance,
        ledger_snapshot: HypothesisLedgerVersion | None,
    ) -> set[str]:
        """Resolve a reviewer scope against the live ledger snapshot.

        A paired reviewer with no live candidate must remain a no-op.  In
        particular, an empty scope must never be interpreted as permission to
        inspect the complete ledger (the legacy reviewer contract does that
        only outside dynamic-v2).
        """

        scope = scope_for_instance(item, ledger_snapshot)
        if not is_dynamic_paired_reviewer(item):
            return scope
        if ledger_snapshot is None:
            return set()
        live_ids = {
            canonical_candidate_id(hypothesis.hypothesis_id)
            for hypothesis in ledger_snapshot.hypotheses
        }
        return {candidate_id for candidate_id in scope if candidate_id in live_ids}

    def skip_empty_dynamic_reviewers() -> None:
        """Retire paired S5 seats whose creator produced no live candidates.

        Empty creator branches are a valid bounded outcome, not a reason to
        spend another model turn scoring unrelated candidates.  Marking the
        reviewer complete here also keeps the scheduler from stalling after
        all productive branches have drained.
        """

        if not pending:
            return
        for item in list(pending.values()):
            if not is_dynamic_paired_reviewer(item):
                continue
            if not all(dep in completed_instances for dep in item.depends_on):
                continue
            scope = effective_scope_for_instance(item, ledger)
            if scope:
                continue
            pending.pop(item.instance_id, None)
            completed_instances.add(item.instance_id)
            instance_hypothesis_ids[item.instance_id] = set()
            emit_swarm_event(
                "winning_agent_instance_cancelled",
                actor=item.instance_id,
                graph_id=graph.graph_id,
                mission_node=item.mission_node,
                archetype=item.archetype,
                reason="empty_creator_scope_no_s5_review",
            )

    def maybe_recruit_for_coverage() -> None:
        """Insert Gap Analyzer scouts as soon as two creators have published.

        Recruitment used to wait until the whole first wave drained.  That
        serialized 1-2 extra sessions onto the S5 critical path.  Overlapping
        with remaining first-wave seats keeps wall-clock closer to the slowest
        unique scout, while still forbidding recruitment after the first S5
        reviewer is dispatched.  The cutoff is durable across scheduler ticks
        so a completed reviewer cannot be followed by an unreviewed recruit.
        """

        nonlocal graph, coverage_recruitment_used
        nonlocal previous_coverage_cluster_keys, last_coverage_signature
        nonlocal consecutive_low_novelty
        nonlocal contracts, pending
        max_recruits = int(
            swarm_controller.policy.get("coverage_expand_max_recruits", 2)
        )
        if coverage_recruitment_cutoff or coverage_recruitment_used >= max_recruits:
            return
        # ``running_instances`` stores ``(instance, scope, batch)`` tuples so
        # the scheduler can retain the immutable candidate snapshot and
        # execution batch alongside the role.  Inspect the first tuple member
        # here instead of treating the value as a ``WinningAgentInstance``.
        if any(
            running_item.mission_node == "S5"
            for running_item, _scope, _batch in running_instances.values()
        ):
            return
        if ledger is None or not ledger.hypotheses:
            return
        completed_creators = [
            item
            for item in graph.agent_instances
            if item.mission_node in {"S3", "S4"}
            and item.instance_id in completed_instances
        ]
        pending_only_reviewers = pending and all(
            item.archetype == "independent_portfolio_reviewer"
            for item in pending.values()
        )
        if len(completed_creators) < 2 and not (
            pending_only_reviewers and not running_instances
        ):
            return
        snapshot = build_coverage_snapshot(
            ledger.hypotheses,
            topic=str(shared.get("topic", "")),
            previous_cluster_keys=previous_coverage_cluster_keys,
        )
        previous_coverage_cluster_keys = tuple(snapshot.cluster_counts)
        coverage_signature = tuple(
            sorted(
                (
                    str(item.candidate_id),
                    str(item.cluster_key),
                )
                for item in snapshot.candidates
            )
        )
        if coverage_signature != last_coverage_signature:
            if snapshot.marginal_novelty < 0.08:
                consecutive_low_novelty += 1
            else:
                consecutive_low_novelty = 0
            last_coverage_signature = coverage_signature
        used_archetypes = tuple(
            item.archetype
            for item in graph.agent_instances
            if item.mission_node in {"S3", "S4"}
        )
        remaining_instances = max(
            0, graph.maximum_instances - len(graph.agent_instances)
        )
        budget = _remaining_swarm_budget(remaining_instances)
        mandatory_pending_calls = len(pending)
        recruit_call_capacity = min(
            remaining_instances,
            max(
                0,
                int(budget["remaining_calls"] or 0)
                - mandatory_pending_calls,
            ),
        )
        decision = decide_adaptive_action(
            snapshot,
            remaining_instances=remaining_instances,
            remaining_calls=recruit_call_capacity,
            remaining_tokens=(
                float(budget["remaining_tokens"])
                if budget["remaining_tokens"] is not None
                else None
            ),
            remaining_time=(
                float(budget["remaining_time"])
                if budget["remaining_time"] is not None
                else None
            ),
            already_used_archetypes=used_archetypes,
            consecutive_low_novelty=consecutive_low_novelty,
        )
        emit_swarm_event(
            "winning_coverage_decision",
            actor="winning_swarm_controller",
            graph_id=graph.graph_id,
            **decision.to_event(),
            coverage_snapshot=snapshot.to_event(),
            budget_snapshot=dict(budget),
            mandatory_pending_calls=mandatory_pending_calls,
            recruit_call_capacity=recruit_call_capacity,
            recruitment_cutoff=coverage_recruitment_cutoff,
            consecutive_low_novelty=consecutive_low_novelty,
        )
        if decision.action not in {"expand", "verify"}:
            return
        if remaining_instances <= 0 or not decision.recruit_archetype:
            return
        previous_ids = {item.instance_id for item in graph.agent_instances}
        graph = swarm_controller.recruit_for_coverage_gap(
            graph,
            topic=str(shared.get("topic", "")),
            execution_profile_id=str(shared.get("execution_profile_id", "")),
            gap_axis=str(decision.recruit_gap or "mechanism"),
            already_used=used_archetypes,
            expected_quality_gain=0.05,
        )
        contracts.update(
            {item.role_contract_id: item for item in graph.role_contracts}
        )
        for item in graph.agent_instances:
            if item.instance_id in pending:
                pending[item.instance_id] = item
            elif (
                item.instance_id not in previous_ids
                and item.instance_id not in completed_instances
                and item.instance_id not in failed_instances
            ):
                pending[item.instance_id] = item
        coverage_recruitment_used += 1
        emit_swarm_event(
            "winning_coverage_recruitment_applied",
            actor="winning_swarm_controller",
            graph_id=graph.graph_id,
            recruit_archetype=decision.recruit_archetype,
            recruit_gap=decision.recruit_gap,
            recruit_action=decision.action,
            graph_instance_count=len(graph.agent_instances),
        )

    def merge_lock_keys(
        item: WinningAgentInstance,
        candidate_scope: set[str],
    ) -> set[tuple[str, str]]:
        # S1-S3 seed roles read inherited branches for context but
        # publish new hypotheses. Locking their read scope serialized
        # the quality-critical S3 equipment generators even though
        # they never write the same candidate ids.
        if item.mission_node in {"S1", "S2", "S3", "S4"} and not item.hypothesis_id:
            return set()
        if (
            item.mission_node == "S5"
            and item.archetype == "independent_portfolio_reviewer"
            and len(item.depends_on) != 1
        ):
            # Cross-pool reviewers share one candidate snapshot and must be
            # allowed to score concurrently.  Ledger merge remains serial.
            return set()
        return {(hypothesis_id, item.merge_target) for hypothesis_id in candidate_scope}

    emit_swarm_event(
        "winning_mission_graph_planned",
        graph=to_plain(graph),
        graph_id=graph.graph_id,
        task_count=len(graph.agent_instances),
        maximum_concurrency=graph.maximum_concurrency,
        minimum_instances=graph.minimum_instances,
        target_instances=target_instances,
        maximum_instances=graph.maximum_instances,
    )
    batch_index = 0
    while pending or running_instances:
        s1_s2_finished = all(
            item.instance_id in completed_instances | failed_instances
            for item in graph.agent_instances
            if item.mission_node in {"S1", "S2"} and not item.hypothesis_id
        )
        if (
            s1_s2_finished
            and not s3_active_instances_materialized
            and any(
                item.mission_node in {"S3", "S4"} and not item.hypothesis_id
                for item in pending.values()
            )
        ):
            await materialize_active_s3_instances()
        # A creator may legitimately return no candidate.  Retire only its
        # paired S5 seat immediately; never let an empty scope fall through to
        # the legacy full-ledger reviewer path or consume a model slot.
        skip_empty_dynamic_reviewers()
        maybe_recruit_for_coverage()
        # S3/S4 branches are published as they complete.  Cross-pool S5
        # reviewers wait for the live producer set, including any coverage
        # recruits, then compare the complete candidate pool.
        if (
            ledger is not None
            and not running_instances
            and pending
            and all(
                item.archetype == "independent_portfolio_reviewer"
                for item in pending.values()
            )
        ):
            # Do not pre-merge or pre-trim the dynamic candidate pool. Each
            # paired S5 call owns only its producer's candidate scope; the
            # final top-seven ordering is applied after all scores arrive.
            compact_candidate_ledger_for_review()
        s3_creator_ids = {
            item.instance_id
            for item in graph.agent_instances
            if item.mission_node == "S3" and not item.hypothesis_id
        }
        s3_terminal_ids = s3_creator_ids.intersection(
            completed_instances | failed_instances
        )
        s4_boundary_ready = not s3_creator_ids or bool(s3_terminal_ids)
        if (
            s4_boundary_ready
            and not s4_incremental_boundary_opened
            and any(
                item.mission_node == "S4"
                and not item.hypothesis_id
                and item.instance_id in pending
                for item in graph.agent_instances
            )
        ):
            s4_incremental_boundary_opened = True
            emit_swarm_event(
                "winning_s4_incremental_boundary_opened",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                completed_s3_instance_ids=sorted(s3_terminal_ids),
                remaining_s3_instance_ids=sorted(s3_creator_ids - s3_terminal_ids),
                rule=load_dynamic_winning_prompt(
                    "common", section="s3_s4.incremental_boundary_rule"
                ),
            )
        def _creative_dispatch_priority(item: WinningAgentInstance) -> int:
            """Prefer S4 once its incremental boundary has opened.

            At the normal eight-lane ceiling all six creative seats can be
            dispatched together, so this ordering is usually invisible.  It
            matters for a deliberately constrained provider (one or two
            lanes): after the first S3 branch publishes, keeping S3 ahead of
            S4 would serialize the remaining S3 tail and defeat the
            incremental boundary.  S4 still remains behind S3 before that
            boundary is opened.
            """

            if s4_incremental_boundary_opened:
                if item.mission_node == "S4" and not item.hypothesis_id:
                    return 0
                if item.mission_node == "S3" and not item.hypothesis_id:
                    return 1
            else:
                if item.mission_node == "S3" and not item.hypothesis_id:
                    return 0
                if item.mission_node == "S4" and not item.hypothesis_id:
                    return 1
            return 2

        def _ready_dispatch_key(
            item: WinningAgentInstance,
        ) -> tuple[int, int, int, float, str]:
            """Order ready work without letting a creative tail starve S5.

            Before the incremental boundary opens, retain the graph's normal
            wave ordering.  Once one S3 branch publishes, S4 creators remain
            first, then a paired S5 reviewer whose producer already has a
            live scope, and only then the remaining S3 tail.  The reviewer
            scope check is read-only and prevents an empty creator from
            consuming a model slot.  All non-creative work keeps its original
            wave/quality ordering.
            """

            if s4_incremental_boundary_opened and item.mission_node in {
                "S3",
                "S4",
                "S5",
            }:
                if item.mission_node == "S4" and not item.hypothesis_id:
                    creative_rank = 0
                elif (
                    is_dynamic_paired_reviewer(item)
                    and bool(effective_scope_for_instance(item, ledger))
                ):
                    creative_rank = 1
                elif item.mission_node == "S3" and not item.hypothesis_id:
                    creative_rank = 2
                else:
                    creative_rank = 3
                return (
                    0,
                    creative_rank,
                    item.wave,
                    -item.expected_quality_gain,
                    item.instance_id,
                )
            return (
                1,
                item.wave,
                _creative_dispatch_priority(item),
                -item.expected_quality_gain,
                item.instance_id,
            )

        ready = sorted(
            (
                item
                for item in pending.values()
                if all(dep in completed_instances for dep in item.depends_on)
                and (
                    item.mission_node != "S4"
                    or s4_boundary_ready
                )
                and (
                    item.mission_node not in {"S3", "S4"}
                    or all(
                        seed_instance.instance_id
                        in completed_instances | failed_instances
                        for seed_instance in graph.agent_instances
                        if seed_instance.mission_node in {"S1", "S2"}
                        and not seed_instance.hypothesis_id
                    )
                )
                and (
                    item.mission_node not in {"S5", "S6"}
                    or ledger is not None
                    and bool(ledger.hypotheses)
                )
                and (
                    item.archetype != "independent_portfolio_reviewer"
                    or ledger is not None
                    and bool(ledger.hypotheses)
                )
                and (
                    not is_dynamic_paired_reviewer(item)
                    or bool(effective_scope_for_instance(item, ledger))
                )
            ),
            key=_ready_dispatch_key,
        )
        available_slots = max(0, graph.maximum_concurrency - len(running_instances))
        if not ready and not running_instances:
            for item in pending.values():
                failed_instances.add(item.instance_id)
                emit_swarm_event(
                    "winning_agent_instance_cancelled",
                    actor=item.instance_id,
                    graph_id=graph.graph_id,
                    reason="unsatisfied_dependency",
                )
            break
        running_merge_keys = {
            merge_key
            for running_item, running_scope, _ in running_instances.values()
            for merge_key in merge_lock_keys(running_item, running_scope)
        }
        selected: list[WinningAgentInstance] = []
        selected_merge_keys: set[tuple[str, str]] = set()
        for item in ready:
            if len(selected) >= available_slots:
                break
            item_scope = effective_scope_for_instance(item, ledger)
            item_keys = merge_lock_keys(item, item_scope)
            if item_keys & (running_merge_keys | selected_merge_keys):
                continue
            selected.append(item)
            selected_merge_keys.update(item_keys)
        if selected:
            batch_index += 1
            # Once any S5 reviewer is dispatched, the candidate pool is
            # closed for adaptive recruitment.  New creators after this point
            # would otherwise bypass the review snapshot and could enter S6
            # without a portfolio decision.
            if any(item.mission_node == "S5" for item in selected):
                coverage_recruitment_cutoff = True
            snapshot = ledger
            execution_batches.append(
                {
                    "batch": batch_index,
                    "instance_ids": [item.instance_id for item in selected],
                    "mission_nodes": [item.mission_node for item in selected],
                    "base_ledger_version": snapshot.version if snapshot else 0,
                }
            )
            for item in selected:
                pending.pop(item.instance_id, None)
                inherited_scope = effective_scope_for_instance(item, snapshot)
                call = asyncio.create_task(
                    call_instance(
                        item,
                        ledger_snapshot=snapshot,
                        batch_index=batch_index,
                        candidate_scope=inherited_scope,
                    )
                )
                running_instances[call] = (item, inherited_scope, batch_index)
                running_started_at[call] = monotonic()
            maximum_observed_concurrency = max(
                maximum_observed_concurrency, len(running_instances)
            )
        if not running_instances:
            continue
        # Do not wait forever without a durable event.  This is an
        # observability interval, not a timeout: the task remains
        # alive and is never cancelled or failed because it exceeded
        # the interval.  Its model-progress callback continues to
        # refresh the Worker lease while Codex is thinking.
        done, _ = await asyncio.wait(
            set(running_instances),
            return_when=asyncio.FIRST_COMPLETED,
            timeout=max(
                10.0,
                float(
                    os.environ.get(
                        "EQUIPMENT_DR_SWARM_WAIT_HEARTBEAT_SECONDS",
                        "30",
                    )
                ),
            ),
        )
        if not done:
            now = monotonic()
            emit_swarm_event(
                "winning_agent_waiting",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                running_instances=[
                    {
                        "agent_instance_id": item.instance_id,
                        "mission_node": item.mission_node,
                        "archetype": item.archetype,
                        "batch": batch,
                        "elapsed_seconds": round(
                            now - running_started_at.get(task, now), 1
                        ),
                    }
                    for task, (item, _scope, batch) in running_instances.items()
                ],
                note="模型会话仍在执行；仅写入进度，不触发超时失败或取消",
            )
            continue
        for completed_call in done:
            instance, candidate_scope, instance_batch = running_instances.pop(
                completed_call
            )
            running_started_at.pop(completed_call, None)
            try:
                outcome: object = completed_call.result()
            except BaseException as exc:  # soft-isolate one role instance
                outcome = exc
            # A failed competing instance is a soft failure: downstream
            # roles may still use the surviving branches.
            completed_instances.add(instance.instance_id)
            instance_hypothesis_ids[instance.instance_id] = set(candidate_scope)
            if isinstance(outcome, BaseException):
                retry_count = dynamic_instance_retry_counts.get(instance.instance_id, 0)
                if retry_count < 1:
                    dynamic_instance_retry_counts[instance.instance_id] = (
                        retry_count + 1
                    )
                    completed_instances.discard(instance.instance_id)
                    pending[instance.instance_id] = instance
                    emit_swarm_event(
                        "winning_agent_instance_retry_scheduled",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        retry_number=retry_count + 1,
                        failure_type=type(outcome).__name__,
                        error_message=str(outcome)[:500],
                    )
                    continue
                if instance.mission_node == "S5" and ledger is not None:
                    # S5 is a judgement layer. If a paired scorer's isolated CLI is at
                    # capacity after one retry, preserve the already
                    # authored S3/S4 pool and make a transparent,
                    # bounded transport fallback rather than marking the
                    # whole core run limited.  No candidate or attribute
                    # is invented here.
                    s5_fallback_activated = True
                    s5_fallback_reason = f"{type(outcome).__name__}: {outcome}"
                    fallback_scope = (
                        set(candidate_scope)
                        if is_dynamic_paired_reviewer(instance)
                        else candidate_scope
                        or {item.hypothesis_id for item in ledger.hypotheses}
                    )
                    if not fallback_scope:
                        emit_swarm_event(
                            "winning_s5_empty_scope_skipped",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node="S5",
                            candidate_scope=[],
                            reason="provider_failure_with_empty_creator_scope",
                        )
                        continue
                    fallback_result = _s5_portfolio_fallback_result(
                        [
                            item
                            for item in ledger.hypotheses
                            if item.hypothesis_id in fallback_scope
                        ],
                        maximum=min(
                            7,
                            int(swarm_controller.policy.get("finalist_maximum", 7)),
                        ),
                    )
                    emit_swarm_event(
                        "winning_s5_portfolio_fallback_activated",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node="S5",
                        failure_type=type(outcome).__name__,
                        error_message=str(outcome)[:500],
                        retry_count=retry_count,
                        retained_candidate_count=sum(
                            str(row.get("decision", "")).lower() == "retain"
                            for row in fallback_result.get("decisions", [])
                            if isinstance(row, Mapping)
                        ),
                        reason=(
                            "S5仅负责创新颠覆判断；模型不可用时按S3/S4既有候选语义"
                            "保守排序，不补写武器属性。"
                        ),
                    )
                    outcome = (
                        instance,
                        fallback_result,
                        ledger.version,
                    )
                else:
                    failed_instances.add(instance.instance_id)
                    completed_instances.add(instance.instance_id)
                    emit_swarm_event(
                        "winning_agent_instance_failed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        failure_type=type(outcome).__name__,
                        error_message=str(outcome)[:500],
                        retry_count=retry_count,
                    )
                    continue
            _, result, base_version = outcome
            runs.append(
                {
                    "step": int(instance.mission_node[1:]),
                    "agent_id": instance.instance_id,
                    "template_agent_id": f"winning_swarm_{instance.archetype}",
                    "middle_cycle": 1,
                    "execution_mode": "dynamic_mission_graph",
                    "wave": instance.wave,
                    "batch": instance_batch,
                    "merge_target": instance.merge_target,
                    "status": "completed",
                }
            )
            if instance.mission_node in {"S1", "S2"} and not instance.hypothesis_id:
                raw_reasoning_seeds = result.get("reasoning_seeds", [])
                if not isinstance(raw_reasoning_seeds, list):
                    raw_reasoning_seeds = []
                reasoning_seeds_by_instance[instance.instance_id] = [
                    dict(item)
                    for item in raw_reasoning_seeds
                    if isinstance(item, Mapping)
                ][:8]
                instance_hypothesis_ids[instance.instance_id] = set()
                emit_swarm_event(
                    "winning_reasoning_seed_published",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    mission_node=instance.mission_node,
                    seed_count=len(reasoning_seeds_by_instance[instance.instance_id]),
                )
            elif instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                task = task_for_instance(instance)
                raw_rows = result.get("hypotheses", [])
                if not isinstance(raw_rows, list):
                    raw_rows = []
                raw_considered_dimensions = result.get("considered_dimensions", [])
                if not isinstance(raw_considered_dimensions, list):
                    raw_considered_dimensions = []
                assignment_for_trace = winning_angle_assignments.get(
                    instance.instance_id, {}
                )
                allowed_codes = {
                    str(item.get("code", "")).strip().upper()
                    for item in _s3_s4_dimension_catalog(assignment_for_trace)
                    if str(item.get("code", "")).strip()
                }
                # ``allowed_codes`` describes the three open containers sent
                # to this seat; it is *not* a taxonomy or whitelist.  A model
                # may (and should) replace a container with a Query-specific
                # relation such as ``OTHER:授权断裂`` or an opaque short id.
                # The old intersection with ``allowed_codes`` silently
                # deleted those dimensions from the audit trace.  Canonicalize
                # built-in packs and preserve every authored custom identity,
                # while ignoring only controller markers that are not actual
                # dimensions.
                def _is_controller_dimension_marker(value: Any) -> bool:
                    token = _dimension_marker_text(value)
                    if not token:
                        return False
                    marker = token.casefold().replace(" ", "")
                    if "::open-dimension::" in marker:
                        return True
                    return marker in {
                        "open",
                        "open_slot",
                        "open-slot",
                        "auto",
                        "dynamic",
                        "dynamic-open",
                        "dynamic_open",
                        "dynamicopen",
                        "query开放制胜维度",
                    } or bool(
                        re.match(r"^query开放制胜(?:槽位|维度)\d*$", marker)
                    ) or bool(
                        re.match(
                            r"^open(?:[_-]?slot)?[-_:][a-z0-9]{4,}(?:[-_:][a-z0-9]+)*$",
                            marker,
                        )
                    )

                def _trace_dimension_token(value: Any) -> str:
                    if isinstance(value, Mapping):
                        code = str(
                            value.get("dimension_code")
                            or value.get("code")
                            or value.get("winning_dimension_code")
                            or ""
                        ).strip()
                        label = str(
                            value.get("combat_dimension")
                            or value.get("label")
                            or value.get("dimension")
                            or ""
                        ).strip()
                        angle = str(
                            value.get("winning_angle_id")
                            or value.get("angle_id")
                            or ""
                        ).strip()
                        # A mapping with ``dimension_code=OTHER`` and a
                        # richer label is one authored relation, not the
                        # generic OTHER bucket.  Pass the label as the
                        # canonicalizer fallback so it becomes
                        # ``OTHER:<stable-label>``.
                        if code and not _is_controller_dimension_marker(code):
                            value = (code, label)
                        elif label:
                            value = label
                        elif (
                            angle
                            and (
                                "::" in angle
                                or angle.casefold().startswith("self-proposed:")
                            )
                            and not _is_controller_dimension_marker(angle)
                        ):
                            # Resolver-generated angle ids append the
                            # authored dimension after ``::``.  Recover only
                            # that suffix; the seat/slot prefix is transport
                            # metadata and must not become a fake dimension.
                            value = angle.rsplit("::", 1)[-1]
                        else:
                            value = ""
                    fallback_label = ""
                    if isinstance(value, tuple):
                        value, fallback_label = value
                    token = _dimension_marker_text(value)
                    if not token:
                        return ""
                    if _is_controller_dimension_marker(token):
                        return ""
                    pack = _s3_s4_dimension_pack_for(token)
                    if pack is not None:
                        return str(pack.get("code", "")).strip().upper()
                    canonical = _canonical_dimension_identity(
                        token,
                        fallback=fallback_label,
                    )
                    return canonical.strip().upper()

                realized_trace: set[str] = set()
                ignored_dimension_markers: list[str] = []
                raw_dimension_labels: list[str] = []
                raw_dimension_selections_for_trace = result.get(
                    "dimension_selections", []
                )
                if not isinstance(raw_dimension_selections_for_trace, list):
                    raw_dimension_selections_for_trace = []
                # Providers may put the declaration in considered_dimensions,
                # dimension_selections, or inline on a compact hypothesis.
                # Treat all three as declarations of the same trace and
                # canonicalize/deduplicate them below.
                trace_inputs: list[Any] = [
                    *raw_considered_dimensions,
                    *raw_dimension_selections_for_trace,
                ]
                for raw_row in raw_rows:
                    if isinstance(raw_row, Mapping) and any(
                        str(raw_row.get(key, "")).strip()
                        for key in (
                            "dimension_code",
                            "combat_dimension",
                            "winning_angle_id",
                        )
                    ):
                        trace_inputs.append(raw_row)
                for item in trace_inputs:
                    raw_label = (
                        str(
                            item.get("combat_dimension")
                            or item.get("label")
                            or item.get("dimension_code")
                            or item.get("dimension")
                            or ""
                        ).strip()
                        if isinstance(item, Mapping)
                        else str(item or "").strip()
                    )
                    if raw_label:
                        raw_dimension_labels.append(raw_label)
                    normalized = _trace_dimension_token(item)
                    if normalized:
                        realized_trace.add(normalized)
                    elif raw_label:
                        ignored_dimension_markers.append(raw_label)
                if not realized_trace:
                    # A missing declaration is retained as an incomplete
                    # trace rather than fabricated as a hard D-code.  A
                    # persisted legacy assignment can still provide a real
                    # authored fallback; generated OPEN-* ids are markers and
                    # are deliberately excluded.
                    fallback = _trace_dimension_token(
                        assignment_for_trace.get("primary_dimension_code", "")
                    )
                    if fallback:
                        realized_trace = {fallback}
                seat_realized_dimensions.setdefault(instance.instance_id, set()).update(
                    realized_trace
                )
                emit_swarm_event(
                    "winning_s3_s4_multidimensional_reasoning_recorded",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    mission_node=instance.mission_node,
                    declared_dimensions=sorted(realized_trace),
                    allowed_dimensions=sorted(allowed_codes),
                    custom_dimensions_allowed=True,
                    raw_declared_dimensions=raw_dimension_labels,
                    ignored_dimension_markers=ignored_dimension_markers,
                    primary_dimension=str(
                        assignment_for_trace.get("primary_dimension_code", "")
                    ),
                    minimum_dimension_comparison=3,
                    dimension_trace_complete=len(realized_trace) >= 3,
                )
                candidate_maximum = max(
                    1,
                    int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_maximum_per_session", 3
                        )
                    ),
                )
                candidate_pool_maximum = max(
                    candidate_maximum,
                    int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_pool_maximum_per_session",
                            candidate_maximum,
                        )
                    ),
                )
                raw_rows = raw_rows[:candidate_pool_maximum]
                if instance.archetype in {
                    "direct_combat_equipment_generator",
                    "remote_precision_munition_generator",
                    "mass_scalable_combat_family_generator",
                }:
                    # A weak/empty Codex result must remain visible and
                    # trigger another governed reasoning pass.  Do not
                    # synthesize familiar weapon cards locally from the
                    # evidence index: that was the main source of the
                    # repeated, mechanically assembled candidate board.
                    added_count = 0
                    emit_swarm_event(
                        "winning_specialized_seed_authored"
                        if raw_rows
                        else "winning_specialized_seed_empty",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        archetype=instance.archetype,
                        recovered_count=added_count,
                        candidate_count=len(raw_rows),
                        stop_reason=str(result.get("stop_reason", ""))[:300],
                        quality_residuals=[
                            str(item)[:240]
                            for item in result.get("quality_residuals", [])
                            if str(item).strip()
                        ][:4],
                    )
                produced_ids: set[str] = set()
                assignment = dict(
                    winning_angle_assignments.get(instance.instance_id, {})
                )
                raw_dimension_selections = result.get("dimension_selections", [])
                if not isinstance(raw_dimension_selections, list):
                    raw_dimension_selections = []
                dimension_sidecars_by_position: dict[int, Mapping[str, Any]] = {}
                dimension_sidecars_by_name: dict[str, Mapping[str, Any]] = {}
                for sidecar in raw_dimension_selections:
                    if not isinstance(sidecar, Mapping):
                        continue
                    try:
                        position = int(sidecar.get("candidate_position", 0) or 0)
                    except (TypeError, ValueError):
                        position = 0
                    if position > 0:
                        dimension_sidecars_by_position[position] = sidecar
                    sidecar_name = str(
                        sidecar.get("name") or sidecar.get("candidate_name") or ""
                    ).strip()
                    if sidecar_name:
                        dimension_sidecars_by_name[sidecar_name] = sidecar
                # Dynamic S3/S4 is intentionally quality-first: extra
                # model rows do not enter the ledger. S5 still owns the
                # authoritative semantic merge/reject decision over the
                # compact complete pool.
                for ordinal, raw in enumerate(
                    raw_rows[:candidate_pool_maximum], start=1
                ):
                    if not isinstance(raw, Mapping):
                        continue
                    summary = str(raw.get("concise_winning_summary", "")).strip()
                    summary_issues = winning_summary_language_issues(summary)
                    # Authoring issues are advisory at the creative
                    # boundary.  In particular, do not discard a complete
                    # candidate merely because a reasoning model wrote a
                    # verbose summary (>180 chars) or retained a domain
                    # abbreviation.  S5 remains authoritative for
                    # semantic admission; only a missing summary is
                    # omitted as structurally unusable.
                    if "winning_summary_missing" in summary_issues:
                        emit_swarm_event(
                            "winning_candidate_rejected_before_ledger",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node=instance.mission_node,
                            name=str(raw.get("name", ""))[:180],
                            residuals=summary_issues,
                            reason="winning_summary_language_gate_failed_after_revision",
                        )
                        continue
                    if summary_issues:
                        emit_swarm_event(
                            "winning_candidate_summary_quality_advisory",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node=instance.mission_node,
                            name=str(raw.get("name", ""))[:180],
                            residuals=summary_issues,
                            blocking=False,
                        )
                    candidate_name = str(
                        raw.get("name", "") or raw.get("title", "")
                    ).strip()
                    sidecar = dimension_sidecars_by_position.get(ordinal) or (
                        dimension_sidecars_by_name.get(candidate_name)
                    )
                    resolved_dimension = _s3_s4_resolve_authored_dimension(
                        raw,
                        sidecar=sidecar,
                        assignment=assignment,
                    )
                    candidate_input = dict(raw)
                    # Sidecar fields are promoted only after the compact
                    # creator card has been validated. This preserves the
                    # historical two-field hypothesis schema while allowing
                    # newer creators to declare their actual dimension.
                    for key in (
                        "winning_angle_id",
                        "combat_dimension",
                        "dimension_winning_logic",
                    ):
                        if not str(candidate_input.get(key, "") or "").strip():
                            candidate_input[key] = resolved_dimension.get(key, "")
                    candidate = swarm_controller.hypothesis_from_mapping(
                        candidate_input,
                        task=task,
                        valid_evidence_ids=set(valid_reference_ids),
                        ordinal=ordinal,
                    )
                    # The controller supplies the seat's primary lane only as
                    # a fallback. An explicit D1-D7/OTHER choice authored by
                    # the creator remains intact, so multiple candidates from
                    # one seat can enter different S5 competition lanes.
                    candidate = replace(
                        candidate,
                        winning_angle_id=(
                            candidate.winning_angle_id
                            or resolved_dimension["winning_angle_id"]
                        ),
                        combat_dimension=(
                            candidate.combat_dimension
                            or resolved_dimension["combat_dimension"]
                        ),
                        dimension_winning_logic=(
                            candidate.dimension_winning_logic
                            or resolved_dimension["dimension_winning_logic"]
                        ),
                        changed_confrontation_variable=(
                            candidate.changed_confrontation_variable
                            or str(
                                assignment.get("task_chain_breakpoint", "")
                            ).strip()
                        ),
                    )
                    resolved_code = str(
                        resolved_dimension.get("dimension_code", "")
                    ).strip()
                    if resolved_code:
                        seat_realized_dimensions.setdefault(
                            instance.instance_id, set()
                        ).add(resolved_code)
                    if resolved_code == "D7":
                        emit_swarm_event(
                            "winning_s3_s4_source_forward_candidate_realized",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node=instance.mission_node,
                            hypothesis_id=candidate.hypothesis_id,
                            dimension_code=resolved_code,
                            winning_angle_id=candidate.winning_angle_id,
                        )
                    admission = swarm_controller.evaluate_gate(
                        candidate, stage="targeted"
                    )
                    # Local gates are diagnostic only for creative S3/S4
                    # output. S5 owns semantic admission, merge and reject
                    # decisions using the complete Query and portfolio.
                    if admission.residuals:
                        emit_swarm_event(
                            "winning_candidate_pre_s5_residual_recorded",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            hypothesis_id=candidate.hypothesis_id,
                            mission_node=instance.mission_node,
                            residuals=admission.residuals,
                            blocking=False,
                        )
                    hypotheses.append(candidate)
                    produced_ids.add(candidate.hypothesis_id)
                    emit_swarm_event(
                        "winning_candidate_branch_created",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        hypothesis_id=candidate.hypothesis_id,
                        mission_node=instance.mission_node,
                        score=candidate.score,
                        title=candidate.title,
                        equipment_form=list(candidate.equipment_forms[:2]),
                        primary_equipment_identity=(
                            str(raw.get("primary_equipment_identity", "")).strip()
                            or str(raw.get("equipment_form", "")).strip()
                            or "；".join(candidate.equipment_forms[:2])
                        ),
                        naming_rationale=str(raw.get("naming_rationale", "")).strip(),
                        naming_style=str(raw.get("naming_style", "")).strip(),
                        core_disruptive_difference=str(
                            raw.get("core_disruptive_difference", "")
                        ).strip(),
                        concise_winning_summary=str(
                            raw.get("concise_winning_summary", "")
                        ).strip(),
                        naming_owner="s3_s4_codex",
                        naming_assignment=(
                            dict(
                                naming_plan.get("assignments", {})
                                .get(instance.instance_id, {})
                                .get("candidate_order", [])[ordinal - 1]
                            )
                            if ordinal - 1
                            < len(
                                naming_plan.get("assignments", {})
                                .get(instance.instance_id, {})
                                .get("candidate_order", [])
                            )
                            else {}
                        ),
                    )
                id_remap = refresh_candidate_ledger()
                resolved_ids = {
                    id_remap.get(hypothesis_id, hypothesis_id)
                    for hypothesis_id in produced_ids
                }
                known_ledger_ids = {item.hypothesis_id for item in ledger.hypotheses}
                instance_hypothesis_ids[instance.instance_id] = {
                    hypothesis_id
                    for hypothesis_id in resolved_ids
                    if hypothesis_id in known_ledger_ids
                } or set(candidate_scope)
                incremental_ids = set(instance_hypothesis_ids[instance.instance_id])
                if incremental_ids:
                    known_incremental_ids = {
                        item.hypothesis_id for item in ledger.hypotheses
                    }
                    incremental_ids &= known_incremental_ids
                    instance_hypothesis_ids[instance.instance_id] = set(incremental_ids)
                    # Retain bookkeeping for audit compatibility. The paired
                    # S5 reviewer is scheduled as soon as this creator scope
                    # is ready; the controller later merges all score slices
                    # for the global top-seven decision.
                    pending_incremental_review_ids.update(
                        incremental_ids - reviewed_candidate_ids
                    )
            else:
                if ledger is None:
                    continue
                if instance.archetype == "independent_portfolio_reviewer":
                    raw_decisions = result.get("decisions", [])
                    if not isinstance(raw_decisions, list):
                        raw_decisions = []
                    known_ids = {item.hypothesis_id for item in ledger.hypotheses}
                    required_ids = (
                        set(candidate_scope)
                        if str(swarm_controller.policy.get("policy_id"))
                        == "winning_swarm_dynamic_v2"
                        else set(candidate_scope) or set(known_ids)
                    )
                    if not raw_decisions and required_ids:
                        # DeepSeek/OpenLux can return a complete but empty S5
                        # decision envelope (``{"decisions": []}``) after hidden
                        # reasoning consumed the visible answer budget. That is a
                        # transport/contract failure, not an innovation verdict.
                        # Reuse the same conservative S3/S4-only fallback as a
                        # failed S5 provider so an otherwise authored candidate
                        # pool can still reach S6 card authoring.
                        fallback_scope = (
                            set(candidate_scope)
                            if is_dynamic_paired_reviewer(instance)
                            else candidate_scope
                            or {item.hypothesis_id for item in ledger.hypotheses}
                        )
                        if not fallback_scope:
                            emit_swarm_event(
                                "winning_s5_empty_scope_skipped",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                mission_node="S5",
                                candidate_scope=[],
                                reason="empty_decision_with_empty_creator_scope",
                            )
                            continue
                        fallback_result = _s5_portfolio_fallback_result(
                            [
                                item
                                for item in ledger.hypotheses
                                if item.hypothesis_id in fallback_scope
                            ],
                            maximum=min(
                                7,
                                int(
                                    swarm_controller.policy.get(
                                        "finalist_maximum", 7
                                    )
                                ),
                            ),
                        )
                        raw_decisions = fallback_result.get("decisions", [])
                        if not isinstance(raw_decisions, list):
                            raw_decisions = []
                        emit_swarm_event(
                            "winning_s5_portfolio_fallback_activated",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node="S5",
                            failure_type="empty_decision_envelope",
                            error_message=(
                                "S5 reviewer returned no decisions for a non-empty "
                                "candidate pool"
                            ),
                            retry_count=0,
                            retained_candidate_count=sum(
                                str(row.get("decision", "")).lower() == "retain"
                                for row in raw_decisions
                                if isinstance(row, Mapping)
                            ),
                            reason=(
                                "S5模型未返回任何决策；按S3/S4既有直接装备与语义脊柱"
                                "保守排序，不补写武器属性。"
                            ),
                        )
                    # Model responses can be truncated or contain a repeated
                    # row. Treat the reviewer output as an unordered patch:
                    # keep the last valid decision for each candidate and
                    # synthesize an explicit *reject/unjudged* row for
                    # omissions. Missing a judgement must never silently
                    # promote a candidate into the final portfolio; S5 is
                    # an innovation gate, not a quantity filler.
                    decisions_by_id: dict[str, Mapping[str, Any]] = {}
                    duplicate_ids: set[str] = set()
                    for raw in raw_decisions:
                        if not isinstance(raw, Mapping):
                            continue
                        candidate_id = canonical_candidate_id(
                            str(raw.get("hypothesis_id", ""))
                        )
                        if candidate_id not in required_ids:
                            continue
                        if candidate_id in decisions_by_id:
                            duplicate_ids.add(candidate_id)
                        decisions_by_id[candidate_id] = raw
                    missing_ids = required_ids - set(decisions_by_id)
                    if duplicate_ids or missing_ids:
                        for missing_id in sorted(missing_ids):
                            decisions_by_id[missing_id] = {
                                "hypothesis_id": missing_id,
                                "decision": "reject",
                                "reason": (
                                    "S5 reviewer omitted this candidate; it is not "
                                    "admitted without an explicit innovation judgement."
                                ),
                                "innovation_priority": 0.0,
                                "disruption_tier": "incremental_upgrade",
                            }
                        raw_decisions = [
                            decisions_by_id[item] for item in sorted(required_ids)
                        ]
                        emit_swarm_event(
                            "winning_full_pool_portfolio_review_repaired",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            repaired_missing_ids=sorted(missing_ids),
                            deduplicated_ids=sorted(duplicate_ids),
                        )
                    # Candidates outside this reviewer's declared slice stay
                    # in the ledger untouched; candidates inside the slice
                    # must earn retention through an explicit valid
                    # ``retain`` or ``merge`` decision.  Starting with the
                    # full set here would silently retain malformed,
                    # omitted, or invalid-merge rows.
                    required_known_ids = required_ids & known_ids
                    retained_ids = known_ids - required_known_ids
                    reviewed_now: set[str] = set()
                    review_rows_by_id: dict[str, Mapping[str, Any]] = {}
                    for raw in raw_decisions:
                        if not isinstance(raw, Mapping):
                            continue
                        source_id = canonical_candidate_id(
                            str(raw.get("hypothesis_id", ""))
                        )
                        if source_id not in known_ids or (
                            candidate_scope and source_id not in candidate_scope
                        ):
                            continue
                        review_rows_by_id[source_id] = raw
                        decision = str(raw.get("decision", "")).strip().lower()
                        target_id = canonical_candidate_id(
                            str(raw.get("merge_target_hypothesis_id", ""))
                        )
                        reviewed_now.add(source_id)
                        current_candidate = next(
                            (
                                item
                                for item in ledger.hypotheses
                                if item.hypothesis_id == source_id
                            ),
                            None,
                        )
                        reviewer_priority: float | None = None
                        if raw.get("innovation_priority") not in (None, ""):
                            try:
                                reviewer_priority = max(
                                    0.0,
                                    min(
                                        1.0,
                                        float(raw.get("innovation_priority")),
                                    ),
                                )
                            except (TypeError, ValueError):
                                reviewer_priority = None
                        if reviewer_priority is not None:
                            candidate_innovation_priorities[source_id] = (
                                reviewer_priority
                            )
                        naming_assessment = _s5_naming_assessment(raw)
                        candidate_naming_assessments[source_id] = {
                            "naming_assessment_status": naming_assessment.get(
                                "status", "unassessed"
                            ),
                            "s5_innovation_mechanism_score": naming_assessment.get(
                                "s5_innovation_mechanism_score"
                            ),
                            "naming_new_quality": naming_assessment.get(
                                "naming_new_quality"
                            ),
                            "naming_semantic_alignment": naming_assessment.get(
                                "naming_semantic_alignment"
                            ),
                            "naming_semantics_aligned": raw.get(
                                "naming_semantics_aligned"
                            ),
                            "effective_innovation": naming_assessment.get(
                                "effective_innovation"
                            ),
                            "naming_anchor": naming_assessment.get("naming_anchor", ""),
                            "naming_reason": naming_assessment.get("naming_reason", ""),
                        }
                        dimension_scores, weighted_score = _s5_dimension_scores(raw)
                        candidate_dimension_scores[source_id] = dimension_scores
                        candidate_weighted_scores[source_id] = weighted_score
                        innovation_priority = (
                            _dynamic_portfolio_innovation_priority(
                                current_candidate,
                                reviewer_priority,
                            )
                            if current_candidate is not None
                            else reviewer_priority or 0.0
                        )
                        disruption_tier = (
                            str(raw.get("disruption_tier", "") or "").strip().lower()
                        )
                        if disruption_tier:
                            candidate_disruption_tiers[source_id] = disruption_tier
                        displaced_mode = str(
                            raw.get("displaced_operational_mode", "") or ""
                        ).strip()[:500]
                        new_operational_mode = str(
                            raw.get("new_operational_mode", "") or ""
                        ).strip()[:500]
                        relation_shift = str(
                            raw.get("winning_relation_shift", "") or ""
                        ).strip()[:500]
                        if displaced_mode:
                            candidate_displaced_modes[source_id] = displaced_mode
                        if new_operational_mode:
                            candidate_new_operational_modes[source_id] = (
                                new_operational_mode
                            )
                        if relation_shift:
                            candidate_winning_relation_shifts[source_id] = (
                                relation_shift
                            )
                        candidate_innovation_bases[source_id] = _s5_innovation_basis(
                            raw,
                            dimension_scores=dimension_scores,
                            naming_assessment=naming_assessment,
                        )
                        reported_decision = decision
                        decision_reason = str(raw.get("reason", "")).strip()[:500]
                        rejection_stage = "full_pool_s5_portfolio_review"
                        rejection_recorded = False

                        # S5 is an explicit admission gate.  A malformed
                        # decision (or a merge without a valid in-scope
                        # target) must never inherit the initial
                        # ``retained_ids = known_ids`` default.  Previously
                        # such rows fell through to ``continue`` and the
                        # source candidate was silently retained, which was
                        # particularly dangerous for truncated provider
                        # responses and hallucinated merge targets.
                        if decision not in {"retain", "reject", "merge"}:
                            decision = "reject"
                            decision_reason = (
                                f"{decision_reason}；S5返回未知决策，按未通过准入处理"
                            ).strip("；")[:500]
                            rejection_stage = "full_pool_s5_invalid_decision"
                            portfolio_rejected_ids.add(source_id)
                            emit_swarm_event(
                                "winning_s5_invalid_decision_rejected",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                hypothesis_id=source_id,
                                reported_decision=reported_decision,
                                reason=decision_reason,
                            )

                        if decision == "merge" and not _s5_merge_target_is_valid(
                            source_id,
                            target_id,
                            known_ids,
                            candidate_scope,
                        ):
                            # A paired reviewer is allowed to merge only
                            # into a real candidate in its declared slice.
                            # Rejecting an invalid merge source is safer than
                            # retaining it by accident, and keeps the
                            # candidate-scope isolation contract intact.
                            decision = "reject"
                            decision_reason = (
                                f"{decision_reason}；S5合并目标无效或越过候选作用域"
                                f"（target={target_id or '空'}）"
                            ).strip("；")[:500]
                            rejection_stage = "full_pool_s5_invalid_merge_target"
                            portfolio_rejected_ids.add(source_id)
                            emit_swarm_event(
                                "winning_s5_invalid_merge_rejected",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                hypothesis_id=source_id,
                                merge_target_hypothesis_id=target_id,
                                reported_decision=reported_decision,
                                reason=decision_reason,
                            )

                        if decision in {"retain", "merge"} and not _s5_retain_passes_concrete_weapon_contract(
                            raw,
                            query_domain_mode=query_domain["mode"],
                        ):
                            decision = "reject"
                            rejection_stage = "full_pool_s5_portfolio_contract_gate"
                            portfolio_rejected_ids.add(source_id)
                            rejection_recorded = True
                            decision_reason = (
                                f"{decision_reason}；S5具体武器/科学闭合/命名语义准入未通过"
                            ).strip("；")[:500]
                            state.swarm_rejections.append(
                                {
                                    "hypothesis_id": source_id,
                                    "reason": decision_reason,
                                    "stage": rejection_stage,
                                }
                            )
                            emit_swarm_event(
                                "winning_s5_contract_gate_rejected",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                hypothesis_id=source_id,
                                reported_decision=reported_decision,
                                reason=decision_reason,
                                naming_assessment=naming_assessment,
                            )
                        if decision == "merge" and (
                            target_id in known_ids and target_id != source_id
                        ):
                            candidate_id_aliases[source_id] = target_id
                            candidate_innovation_priorities[target_id] = max(
                                candidate_innovation_priorities.get(target_id, 0.0),
                                innovation_priority,
                            )
                            target_naming_assessment = candidate_naming_assessments.get(
                                target_id, {}
                            )
                            if (
                                naming_assessment.get("status") == "assessed"
                                and target_naming_assessment.get(
                                    "naming_assessment_status"
                                )
                                != "assessed"
                            ):
                                candidate_naming_assessments[target_id] = (
                                    dict(candidate_naming_assessments[source_id])
                                )
                            if weighted_score > candidate_weighted_scores.get(
                                target_id, -1.0
                            ):
                                candidate_dimension_scores[target_id] = dimension_scores
                                candidate_weighted_scores[target_id] = weighted_score
                            source_tier_rank = _s5_disruption_tier_rank(
                                disruption_tier,
                                innovation_priority,
                            )
                            target_tier_rank = _s5_disruption_tier_rank(
                                candidate_disruption_tiers.get(target_id),
                                candidate_innovation_priorities.get(target_id),
                            )
                            if source_tier_rank > target_tier_rank:
                                if disruption_tier:
                                    candidate_disruption_tiers[target_id] = (
                                        disruption_tier
                                    )
                                if displaced_mode:
                                    candidate_displaced_modes[target_id] = (
                                        displaced_mode
                                    )
                                if new_operational_mode:
                                    candidate_new_operational_modes[target_id] = (
                                        new_operational_mode
                                    )
                                if relation_shift:
                                    candidate_winning_relation_shifts[target_id] = (
                                        relation_shift
                                    )
                            if candidate_innovation_bases[source_id]:
                                candidate_innovation_bases.setdefault(
                                    target_id,
                                    candidate_innovation_bases[source_id],
                                )
                            retained_ids.discard(source_id)
                            merge_row = {
                                "source_hypothesis_id": source_id,
                                "target_hypothesis_id": target_id,
                                "reason": "full_pool_s5_portfolio_merge",
                            }
                            state.swarm_merges.append(merge_row)
                            emit_swarm_event("hypothesis_merged", **merge_row)
                        elif decision == "reject":
                            retained_ids.discard(source_id)
                            portfolio_rejected_ids.add(source_id)
                            if not rejection_recorded:
                                state.swarm_rejections.append(
                                    {
                                        "hypothesis_id": source_id,
                                        "reason": decision_reason,
                                        "stage": rejection_stage,
                                    }
                                )
                        elif decision == "retain":
                            # S5 owns only innovation/disruption
                            # disposition.  Candidate identity and name
                            # are frozen by S3/S4 and must flow through
                            # unchanged.
                            retained_ids.add(source_id)
                        else:
                            continue
                        emit_swarm_event(
                            "winning_full_pool_portfolio_decision",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            hypothesis_id=source_id,
                            decision=decision,
                            merge_target_hypothesis_id=(
                                target_id if decision == "merge" else ""
                            ),
                            reason=decision_reason,
                            independent_axis=str(raw.get("independent_axis", ""))[:120],
                            direct_equipment=bool(raw.get("direct_equipment", False)),
                            reported_decision=reported_decision,
                            innovation_priority=innovation_priority,
                            innovation_basis=candidate_innovation_bases[source_id],
                            dimension_scores=candidate_dimension_scores.get(
                                source_id, {}
                            ),
                            weighted_score=candidate_weighted_scores.get(
                                source_id, 0.0
                            ),
                            disruption_tier=disruption_tier,
                            material_innovation_breakpoint_present=raw.get(
                                "material_innovation_breakpoint_present"
                            ),
                            ordinary_upgrade_or_function_packaging=raw.get(
                                "ordinary_upgrade_or_function_packaging"
                            ),
                            displaced_operational_mode=displaced_mode,
                            new_operational_mode=new_operational_mode,
                            winning_relation_shift=relation_shift,
                            naming_assessment=naming_assessment,
                        )
                    # A reviewer can legitimately conclude that many
                    # candidates are same-family duplicates, but an
                    # all-reject result for a non-empty pool is not a
                    # usable S5 handoff.  It usually indicates that the
                    # model applied a naming/independence heuristic too
                    # broadly (for example, treating every physical-form
                    # name as an unexplained codename).  Recover the
                    # strongest semantically valid candidates using the
                    # fields the reviewer already supplied, without
                    # inventing new directions or weakening hard safety
                    # checks.
                    if not retained_ids and review_rows_by_id:
                        rescue_rows = [
                            (candidate_id, row)
                            for candidate_id, row in review_rows_by_id.items()
                            if str(row.get("decision", "")).strip().lower() == "retain"
                            and _s5_retain_passes_concrete_weapon_contract(
                                row,
                                query_domain_mode=query_domain["mode"],
                            )
                        ]
                        rescue_rows.sort(
                            key=lambda item: (
                                _s5_disruption_tier_rank(
                                    item[1].get("disruption_tier"),
                                    item[1].get("innovation_priority"),
                                ),
                                float(item[1].get("innovation_priority") or 0.0),
                            ),
                            reverse=True,
                        )
                        rescue_ids = [
                            candidate_id for candidate_id, _ in rescue_rows[:7]
                        ]
                        if rescue_ids:
                            retained_ids.update(rescue_ids)
                            portfolio_rejected_ids.difference_update(rescue_ids)
                            emit_swarm_event(
                                "winning_full_pool_portfolio_review_rescued",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                rescued_hypothesis_ids=rescue_ids,
                                reason="all_rejected_nonempty_pool_recovered_from_explicit_weapon_contract",
                            )
                    # Do not refill the portfolio merely to satisfy a
                    # quantity target. S5's semantic innovation judgement
                    # is authoritative; ordinary upgrades rejected by the
                    # reviewer must not re-enter ahead of disruptive rows.
                    for ordered_id in result.get("portfolio_order", []):
                        canonical_id = canonical_candidate_id(str(ordered_id))
                        if canonical_id not in known_ids:
                            continue
                        if canonical_id not in portfolio_order_hints:
                            portfolio_order_sequence += 1
                            portfolio_order_hints[canonical_id] = (
                                portfolio_order_sequence
                            )
                    if retained_ids != known_ids:
                        updated_hypotheses: list[WinningHypothesis] = []
                        for item in ledger.hypotheses:
                            if item.hypothesis_id not in retained_ids:
                                continue
                            updated_hypotheses.append(item)
                        ledger = HypothesisLedgerVersion(
                            ledger_id=ledger.ledger_id,
                            version=ledger.version + 1,
                            parent_version=ledger.version,
                            hypotheses=updated_hypotheses,
                            merge_receipts=list(ledger.merge_receipts),
                            change_summary="full_pool_s5_innovation_disposition",
                            created_by=instance.instance_id,
                        )
                    # S5 changed only portfolio disposition. It does not
                    # perform semantic clustering; leave the clustering
                    # watermark untouched so the close-out pass compares
                    # the complete candidate set once producers drain.
                    reviewed_candidate_ids.update(reviewed_now)
                    pending_incremental_review_ids.difference_update(reviewed_now)
                    review_targets_by_instance.pop(instance.instance_id, None)
                    emit_swarm_event(
                        "winning_s5_parallel_score_completed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        reviewed_candidate_ids=sorted(reviewed_now),
                        remaining_candidate_ids=sorted(pending_incremental_review_ids),
                        portfolio_order=[
                            str(value)
                            for value in result.get("portfolio_order", [])
                            if str(value).strip()
                        ],
                        portfolio_summary=str(result.get("portfolio_summary", ""))[
                            :500
                        ],
                    )
                    emit_swarm_event(
                        "winning_full_pool_portfolio_review_completed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        reviewed_candidate_ids=sorted(reviewed_now),
                        remaining_candidate_ids=sorted(pending_incremental_review_ids),
                        portfolio_order=[
                            str(value)
                            for value in result.get("portfolio_order", [])
                            if str(value).strip()
                        ],
                        portfolio_summary=str(result.get("portfolio_summary", ""))[
                            :500
                        ],
                        compatibility_alias=True,
                    )
                    continue
                raw_contributions = result.get("contributions", [])
                if isinstance(raw_contributions, Mapping):
                    raw_contributions = [raw_contributions]
                if not isinstance(raw_contributions, list):
                    raw_contributions = []
                known_ids = {item.hypothesis_id for item in ledger.hypotheses}
                for ordinal, raw in enumerate(raw_contributions[:8], start=1):
                    if not isinstance(raw, Mapping):
                        continue
                    reported_hypothesis_id = str(raw.get("hypothesis_id", ""))
                    hypothesis_id = canonical_candidate_id(reported_hypothesis_id)
                    if hypothesis_id not in known_ids:
                        obsolete_candidate = next(
                            (
                                item
                                for item in hypotheses
                                if item.hypothesis_id == reported_hypothesis_id
                            ),
                            None,
                        )
                        if obsolete_candidate is not None:
                            semantic_target = (
                                swarm_controller.semantic_hypothesis_match(
                                    obsolete_candidate,
                                    ledger.hypotheses,
                                )
                            )
                            if semantic_target:
                                candidate_id_aliases[reported_hypothesis_id] = (
                                    semantic_target
                                )
                                hypothesis_id = semantic_target
                    if hypothesis_id != reported_hypothesis_id:
                        emit_swarm_event(
                            "winning_contribution_hypothesis_remapped",
                            actor=instance.instance_id,
                            reported_hypothesis_id=reported_hypothesis_id,
                            hypothesis_id=hypothesis_id,
                        )
                    if hypothesis_id not in known_ids:
                        emit_swarm_event(
                            "winning_contribution_rejected",
                            actor=instance.instance_id,
                            reason="unknown_hypothesis_id",
                            hypothesis_id=hypothesis_id,
                        )
                        continue
                    if (
                        instance.mission_node != "S6"
                        and candidate_scope
                        and hypothesis_id not in candidate_scope
                    ):
                        emit_swarm_event(
                            "winning_contribution_rejected",
                            actor=instance.instance_id,
                            reason="crossed_candidate_scope",
                            hypothesis_id=hypothesis_id,
                            allowed_hypothesis_ids=sorted(candidate_scope),
                        )
                        continue
                    reported_target = str(
                        raw.get("merge_target") or instance.merge_target
                    )
                    if reported_target != instance.merge_target:
                        emit_swarm_event(
                            "winning_contribution_rejected",
                            actor=instance.instance_id,
                            reason="crossed_merge_target",
                            hypothesis_id=hypothesis_id,
                        )
                        continue
                    try:
                        quality = max(
                            0.0,
                            min(1.0, float(raw.get("incremental_quality", 0.0))),
                        )
                    except (TypeError, ValueError):
                        quality = 0.0
                    recommendation = str(raw.get("recommendation", "retain"))[:80]
                    findings = [
                        str(item)
                        for item in raw.get("findings", [])
                        if str(item).strip()
                    ][:8]
                    evidence_ids = swarm_controller.sanitize_evidence_ids(
                        raw.get("evidence_ids", raw.get("evidence_refs", [])),
                        set(valid_reference_ids),
                    )
                    patch_fields = {
                        key: raw.get(key)
                        for key in (
                            "findings",
                            "mechanism_chain_updates",
                            "direct_military_effects",
                            "equipment_forms",
                            "project_function",
                            "system_interfaces",
                            "novelty_delta",
                            "evidence_boundary",
                            "counterevidence",
                            "adversary_adaptations",
                            "failure_boundaries",
                            "trl_constraints",
                            "cost_constraints",
                            "industrial_constraints",
                            "cross_scenario_results",
                            "validation_plan",
                            "implementation_path",
                        )
                        if raw.get(key) not in (None, "", [], {})
                    }
                    retention = swarm_controller.contribution_retention_assessment(
                        raw,
                        evidence_ids=evidence_ids,
                        reported_quality=quality,
                        mission_node=instance.mission_node,
                    )
                    effective_quality = float(retention["effective_quality"])
                    accepted = bool(retention["accepted"])
                    # S4 fan-out and integrated S5 patches are scheduled
                    # only after their full dependency barrier, and merge
                    # locks guarantee disjoint candidate/target writes.
                    # Sibling completions therefore commute; advance the
                    # local ledger base without replaying a Codex session.
                    merge_base_version = (
                        ledger.version
                        if instance.mission_node in {"S4", "S5"}
                        else base_version
                    )
                    contribution = WinningContribution(
                        contribution_id=(
                            "winning-contribution-"
                            + sha256(
                                f"{instance.instance_id}:{hypothesis_id}:{ordinal}".encode()
                            ).hexdigest()[:16]
                        ),
                        agent_instance_id=instance.instance_id,
                        role_contract_id=instance.role_contract_id,
                        hypothesis_id=hypothesis_id,
                        merge_target=instance.merge_target,
                        base_ledger_version=merge_base_version,
                        hypothesis_patch=patch_fields,
                        quality_dimensions={
                            "incremental_quality": effective_quality,
                            "reported_incremental_quality": quality,
                            "structured_weapon_delta": (
                                1.0 if retention["structured_weapon_delta"] else 0.0
                            ),
                        },
                        evidence_ids=evidence_ids,
                        residuals_resolved=[
                            str(item)
                            for item in raw.get("residuals_resolved", [])
                            if str(item).strip()
                        ][:8],
                        incremental_quality=effective_quality,
                        recommendation=recommendation,
                        accepted=accepted,
                    )
                    contribution_rows.append(contribution)
                    emit_swarm_event(
                        "winning_contribution_queued",
                        actor=instance.instance_id,
                        contribution_id=contribution.contribution_id,
                        hypothesis_id=hypothesis_id,
                        merge_target=instance.merge_target,
                        base_ledger_version=base_version,
                    )
                    ledger_after, receipt = swarm_controller.merge_contribution(
                        ledger, contribution
                    )
                    merge_receipts.append(receipt)
                    if receipt.rebase_required:
                        emit_swarm_event(
                            "winning_contribution_rebase_required",
                            actor=instance.instance_id,
                            contribution_id=contribution.contribution_id,
                            from_version=contribution.base_ledger_version,
                            to_version=ledger.version,
                        )
                        contribution = swarm_controller.rebase_contribution(
                            contribution, ledger
                        )
                        ledger_after, receipt = swarm_controller.merge_contribution(
                            ledger, contribution
                        )
                        merge_receipts.append(receipt)
                    ledger = ledger_after
                    emit_swarm_event(
                        "winning_contribution_merged",
                        actor=instance.instance_id,
                        contribution_id=contribution.contribution_id,
                        hypothesis_id=hypothesis_id,
                        merge_target=instance.merge_target,
                        status=receipt.status,
                        resulting_ledger_version=receipt.resulting_ledger_version,
                    )

    if ledger is None:
        ledger = swarm_controller.create_ledger([])
    else:
        compact_candidate_ledger_for_review()
        # Cross-pool S5 already compared the complete candidate pool.  A
        # second independent clustering session only added wall-clock after
        # the reviewers finished.  Local coverage cluster keys remain in the
        # close-out events for audit.
        cross_pool_reviewers = [
            item
            for item in graph.agent_instances
            if item.mission_node == "S5"
            and item.archetype == "independent_portfolio_reviewer"
            and len(item.depends_on) > 1
        ]
        if cross_pool_reviewers:
            emit_swarm_event(
                "winning_semantic_cluster_skipped",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                reason="cross_pool_s5_owns_comparison",
                reviewer_count=len(cross_pool_reviewers),
            )
        else:
            await semantic_cluster_candidate_ledger(
                scope_id="dynamic-v2-closeout",
                changed_hypothesis_ids=None,
            )
    # The dynamic portfolio is the direct result of six paired S5 scoring
    # passes over the S3/S4 outputs. There is no second expert score,
    # evidence/TRL audit, repair wave, or completeness ranker. The controller
    # merges the per-seat judgements, globally orders retained candidates by
    # the five-axis score, and sends at most seven finalists to concurrent S6
    # card authoring.
    maximum = min(
        7,
        max(1, int(swarm_controller.policy.get("finalist_maximum", 7))),
    )
    ordered_hypotheses, portfolio_diversity_audit = _s5_diverse_portfolio_order(
        ledger.hypotheses,
        weighted_scores=candidate_weighted_scores,
        innovation_priorities=candidate_innovation_priorities,
        disruption_tiers=candidate_disruption_tiers,
        portfolio_order_hints=portfolio_order_hints,
        maximum=maximum,
    )
    selected_ids_ordered = [item.hypothesis_id for item in ordered_hypotheses]
    selected_ids = set(selected_ids_ordered)
    # ``hypotheses`` retains every authored branch, including rows removed by
    # a paired S5 reject or a close-out semantic merge.  Count against that
    # durable universe so UI/audit consumers see a truthful rejected count;
    # the previous hard-coded zero hid both kinds of disposition.
    all_authored_ids = {
        item.hypothesis_id
        for item in hypotheses
        if getattr(item, "hypothesis_id", "")
    }
    all_authored_ids.update(candidate_id_aliases)
    all_authored_ids.update(portfolio_rejected_ids)
    rejected_ids_ordered = [
        item
        for item in sorted(all_authored_ids)
        if item not in selected_ids
    ]
    # Keep active-ledger ordering first for compatibility, then append merged
    # or pre-ledger rejects in stable ID order.
    active_rejected_ids = [
        item.hypothesis_id
        for item in ledger.hypotheses
        if item.hypothesis_id not in selected_ids
    ]
    rejected_ids_ordered = list(
        dict.fromkeys([*active_rejected_ids, *rejected_ids_ordered])
    )
    decision = PortfolioDecision(
        decision_id=(
            "portfolio-decision-"
            + sha256(
                f"{ledger.ledger_id}:{ledger.version}:{'|'.join(selected_ids_ordered)}".encode()
            ).hexdigest()[:16]
        ),
        ledger_id=ledger.ledger_id,
        ledger_version=ledger.version,
        pareto_front=list(selected_ids_ordered),
        selected_hypothesis_ids=list(selected_ids_ordered),
        rejected_hypothesis_ids=rejected_ids_ordered,
        objective_scores={
            item.hypothesis_id: {
                "disruption_tier_rank": float(
                    _s5_disruption_tier_rank(
                        candidate_disruption_tiers.get(item.hypothesis_id),
                        candidate_innovation_priorities.get(item.hypothesis_id),
                    )
                ),
                "weighted_comprehensive_score": candidate_weighted_scores.get(
                    item.hypothesis_id, 0.0
                ),
                **{
                    f"s5_{key}": value
                    for key, value in candidate_dimension_scores.get(
                        item.hypothesis_id, {}
                    ).items()
                },
                **{
                    (
                        "s5_innovation_mechanism_score"
                        if key == "s5_innovation_mechanism_score"
                        else f"s5_{key}"
                    ): value
                    for key, value in candidate_naming_assessments.get(
                        item.hypothesis_id, {}
                    ).items()
                    if key
                    in {
                        "s5_innovation_mechanism_score",
                        "naming_new_quality",
                        "naming_semantic_alignment",
                        "effective_innovation",
                    }
                    and value is not None
                },
                "innovation_new_quality": _dynamic_portfolio_innovation_priority(
                    item,
                    candidate_innovation_priorities.get(item.hypothesis_id),
                ),
            }
            for item in ordered_hypotheses
        },
        dominance_reasons={},
        expert_assessment_ids=[],
        # Compatibility field on the shared decision model. In dynamic-v2
        # this means only "S5 produced a non-empty portfolio"; no quality
        # judge exists or is invoked.
        quality_judge_passed=bool(selected_ids_ordered),
        status="accepted_by_full_pool_s5",
        requires_human_review=False,
    )
    emit_swarm_event(
        "winning_inner_loop_evaluated",
        actor="winning_swarm_independent_portfolio_reviewer",
        graph_id=graph.graph_id,
        loop="inner",
        cycle=1,
        passed=decision.quality_judge_passed,
        candidate_count=len(ledger.hypotheses),
        repaired_count=0,
        issues=[],
    )
    final_hypotheses = [
        item for item in ordered_hypotheses if item.hypothesis_id in selected_ids
    ]

    def capability_direction(
        item: WinningHypothesis,
        position: int,
    ) -> dict[str, Any]:
        query_domain = _query_domain_contract(
            str(shared.get("topic", "")),
            structured_query_brief=(
                shared.get("structured_query_brief", {})
                if isinstance(shared.get("structured_query_brief", {}), Mapping)
                else {}
            ),
        )
        equipment_form = _winning_primary_equipment_form(item)
        military_value = "；".join(item.direct_military_effects[:3])
        mechanism = "→".join(item.mechanism_chain[:5])
        project_function = item.project_function or military_value or item.novelty_delta
        # Dynamic S3/S4 creators intentionally return a compact candidate
        # (identity + winning sentence).  Preserve an explicit, evidence-
        # bounded comparison spine for S6 instead of leaving the audit-facing
        # fields empty.  The fallback is deliberately category-level: it does
        # not claim that the public sources validate this particular concept.
        baseline = item.nearest_public_baseline.strip() or load_dynamic_winning_prompt(
            "common", section="s6.dynamic_defaults.baseline"
        ).strip()
        evidence_boundary = item.evidence_boundary.strip() or load_dynamic_winning_prompt(
            "common", section="s6.dynamic_defaults.evidence_boundary"
        ).strip()
        validation_plan = list(item.validation_plan[:8]) or [
            load_dynamic_winning_prompt(
                "common", section="s6.dynamic_defaults.validation"
            ).strip()
        ]
        card = {
            "hypothesis_id": item.hypothesis_id,
            "name": _winning_portfolio_title(item),
            "source_hypothesis_title": _winning_portfolio_title(item),
            "priority": f"P{position}",
            "type": "new_capability",
            "equipment_form": equipment_form,
            "primary_equipment_identity": equipment_form,
            "unique_operational_role": project_function,
            "target_and_direct_effect": military_value,
            "non_substitutable_difference": item.changed_confrontation_variable,
            "query_relevance": (
                f"通过改变“{item.changed_confrontation_variable}”，"
                f"在当前任务链中形成{military_value}。"
            ),
            "concise_winning_summary": (
                item.reference_overview or item.disruptive_shift or mechanism
            ),
            "mechanism_chain": list(item.mechanism_chain[:5]),
            "frontier_principle": item.frontier_principle,
            "disruptive_shift": item.disruptive_shift,
            # Preserve the candidate-local evidence and foresight boundary
            # through S5.  S6 still receives the intentionally minimal
            # three-field authoring input, but deterministic confidence
            # calibration after authoring needs these per-card facts.
            "direct_evidence_refs": list(item.evidence_ids[:8]),
            "evidence_ids": list(item.evidence_ids[:8]),
            "baseline_system": baseline,
            "evidence_boundary": evidence_boundary,
            "validation_plan": validation_plan,
            "operational_mechanism": mechanism,
            "novelty": item.novelty_delta or item.core_disruptive_difference,
            "future_trigger": item.technology_horizon,
            "selection_quality_status": "accepted_by_full_pool_s5",
            "innovation_priority": _dynamic_portfolio_innovation_priority(
                item,
                candidate_innovation_priorities.get(item.hypothesis_id),
            ),
            "innovation_basis": candidate_innovation_bases.get(
                item.hypothesis_id,
                item.core_disruptive_difference
                or item.disruptive_shift
                or item.novelty_delta,
            ),
            "s5_dimension_scores": candidate_dimension_scores.get(
                item.hypothesis_id, {}
            ),
            "s5_weighted_score": candidate_weighted_scores.get(item.hypothesis_id, 0.0),
            **candidate_naming_assessments.get(item.hypothesis_id, {}),
            "disruption_tier": candidate_disruption_tiers.get(item.hypothesis_id, ""),
            "displaced_operational_mode": candidate_displaced_modes.get(
                item.hypothesis_id, ""
            ),
            "new_operational_mode": candidate_new_operational_modes.get(
                item.hypothesis_id, ""
            ),
            "winning_relation_shift": candidate_winning_relation_shifts.get(
                item.hypothesis_id, ""
            ),
            "direct_combat_equipment": bool(
                query_domain["requires_direct_combat_weapon"]
            ),
            "equipment_classification": (
                "direct_combat"
                if query_domain["requires_direct_combat_weapon"]
                else "mission_equipment"
            ),
            "query_domain_mode": query_domain["mode"],
        }
        return {
            key: value for key, value in card.items() if value not in (None, "", [], {})
        }

    raw_equipment_portfolio = [
        capability_direction(item, position)
        for position, item in enumerate(final_hypotheses, start=1)
    ]

    # S5 is a portfolio decision only. The previous per-card handoff
    # contract was a second heavy authoring pass that recreated evidence,
    # TRL, indicators and semantic classification. S6 receives the
    # already-frozen candidate spine directly.
    equipment_portfolio: list[dict[str, Any]] = [
        dict(card) for card in raw_equipment_portfolio
    ]
    # Keep the S5 disposition counters mutually intelligible: a semantic
    # merge is not a rejection, while a retained candidate that falls past
    # the seven-card portfolio cap is an overflow disposition.  The legacy
    # ``rejected_count`` field remains the sum of genuine S5 rejects and
    # overflow rows for downstream consumers that only understand that field.
    merged_source_ids = {
        source_id
        for source_id, target_id in candidate_id_aliases.items()
        if source_id and target_id and source_id != target_id
    }
    s5_rejected_ids = {
        candidate_id
        for candidate_id in portfolio_rejected_ids
        if candidate_id and candidate_id not in merged_source_ids
    }
    authored_ids = {
        item.hypothesis_id
        for item in hypotheses
        if getattr(item, "hypothesis_id", "")
    }
    authored_ids.update(candidate_id_aliases)
    authored_ids.update(portfolio_rejected_ids)
    overflow_ids = {
        candidate_id
        for candidate_id in authored_ids
        if candidate_id not in selected_ids
        and candidate_id not in s5_rejected_ids
        and candidate_id not in merged_source_ids
    }
    s5_rejected_count = len(s5_rejected_ids)
    merged_source_count = len(merged_source_ids)
    overflow_count = len(overflow_ids)
    emit_swarm_event(
        "winning_s5_portfolio_frozen",
        actor="winning_swarm_independent_portfolio_reviewer",
        graph_id=graph.graph_id,
        selected_count=len(equipment_portfolio),
        rejected_count=s5_rejected_count + overflow_count,
        s5_rejected_count=s5_rejected_count,
        merged_source_count=merged_source_count,
        overflow_count=overflow_count,
        status="completed",
        contract_owner="s5_full_pool_portfolio_reviewer",
        pre_freeze_naming_repair_allowed=False,
        post_freeze_naming_mutation_allowed=False,
    )
    query_domain_mode = str(query_domain.get("mode", "direct_combat"))
    direct_combat_count = sum(
        bool(item.get("direct_combat_equipment")) for item in equipment_portfolio
    )
    mission_equipment_count = sum(
        str(item.get("equipment_classification", "")).strip().lower()
        == "mission_equipment"
        for item in equipment_portfolio
    )
    direct_hypotheses = list(final_hypotheses)
    direct_equipment_family_counts = swarm_controller.equipment_family_counts(
        direct_hypotheses
    )
    distinct_direct_equipment_family_count = len(direct_equipment_family_counts)
    complete_handoff_count = sum(
        all(
            (
                str(item.get("name", "")).strip(),
                str(item.get("equipment_form", "")).strip(),
                str(item.get("target_and_direct_effect", "")).strip(),
                str(item.get("unique_operational_role", "")).strip(),
                item.get("mechanism_chain"),
            )
        )
        for item in equipment_portfolio
    )
    s6_handoff_gate_passed = complete_handoff_count == len(
        equipment_portfolio
    ) and bool(equipment_portfolio)
    equipment_family_counts = swarm_controller.equipment_family_counts(final_hypotheses)
    equipment_family_count = len(equipment_family_counts)
    maximum_same_family_count = max(
        equipment_family_counts.values(),
        default=0,
    )
    minimum_family_count = min(3, len(equipment_portfolio))
    maximum_allowed_same_family = max(
        2,
        len(equipment_portfolio) // 2,
    )
    # Five-axis independent Codex clustering has already merged
    # same-thesis and non-independent variants before expert selection.
    # Do not re-open that semantic decision with a local family-name
    # classifier or Chinese token-overlap threshold at the final gate.
    same_family_independence_conflicts: list[dict[str, Any]] = []
    equipment_diversity_passed = True
    preferred_distinct_direct_equipment = int(
        swarm_controller.policy.get(
            "preferred_distinct_direct_equipment",
            5,
        )
    )
    direct_equipment_diversity_passed = True
    domain_main_body_count = (
        mission_equipment_count
        if query_domain_mode == "mission_equipment"
        else direct_combat_count
    )
    domain_main_body_passed = domain_main_body_count >= max(
        1, (len(equipment_portfolio) + 1) // 2
    )
    # Keep the legacy field for consumers that still render it, but make it a
    # non-blocking diagnostic for mission-equipment Queries. The domain-neutral
    # field below is the authoritative portfolio check.
    direct_combat_main_body_passed = (
        True if query_domain_mode == "mission_equipment" else domain_main_body_passed
    )
    remote_precision_present = any(
        _is_remote_precision_portfolio_direction(item) for item in equipment_portfolio
    )
    # Ratios and completeness counters below are diagnostics. They must
    # not turn a model-selected, independently authored portfolio into a
    # failed run. Semantic admission belongs to the Codex review; this
    # layer only records whether there is something concrete to deliver.
    portfolio_quality_gate_passed = bool(equipment_portfolio)
    direct_equipment_diversity_limited = bool(
        not direct_equipment_diversity_passed
        and distinct_direct_equipment_family_count > 0
    )
    diversity_only_warning = bool(
        direct_equipment_diversity_limited
        and direct_combat_main_body_passed
        and s6_handoff_gate_passed
        and equipment_diversity_passed
        and bool(equipment_portfolio)
    )
    state.dynamic_outputs = [
        {
            "agent_instance_id": item.source_task_ids[-1]
            if item.source_task_ids
            else "winning_mission_graph",
            "hypothesis_id": item.hypothesis_id,
            "display_name": item.title,
            "merge_target": "convergence",
            "accepted": item.hypothesis_id in selected_ids,
            "result": {
                "findings": [item.title, *item.mechanism_chain[:2]],
                "evidence_refs": list(item.evidence_ids),
                "open_questions": list(item.residuals[:2]),
                "confidence": item.score,
            },
        }
        for item in ledger.hypotheses
    ]
    accumulated["dynamic_subagent_outputs"] = list(state.dynamic_outputs)

    # Make every S5 disposition explainable to the UI without inventing a
    # second expert judgement or evidence status.
    selected_by_id = {item.hypothesis_id: item for item in final_hypotheses}
    candidate_lineage: list[dict[str, Any]] = []
    for item in ledger.hypotheses:
        row = to_plain(item)
        if item.hypothesis_id in selected_by_id:
            row.update(
                selection_status="selected",
                selection_reason_code="retained_by_full_pool_s5",
                selection_reason=(
                    "通过完整Query制胜因果、直接战果与组合独立性评审；"
                    "按创新/新质能力优先排序并进入S6并行画像撰写。"
                ),
                innovation_priority=_dynamic_portfolio_innovation_priority(
                    item,
                    candidate_innovation_priorities.get(item.hypothesis_id),
                ),
                innovation_basis=candidate_innovation_bases.get(
                    item.hypothesis_id,
                    item.core_disruptive_difference
                    or item.disruptive_shift
                    or item.novelty_delta,
                ),
                **candidate_naming_assessments.get(item.hypothesis_id, {}),
                disruption_tier=candidate_disruption_tiers.get(item.hypothesis_id, ""),
                displaced_operational_mode=candidate_displaced_modes.get(
                    item.hypothesis_id, ""
                ),
                new_operational_mode=candidate_new_operational_modes.get(
                    item.hypothesis_id, ""
                ),
                winning_relation_shift=candidate_winning_relation_shifts.get(
                    item.hypothesis_id, ""
                ),
                s6_eligible=True,
            )
        else:
            row.update(
                # This lineage board is a research catalogue, not the
                # delivery gate itself. Non-selected candidates remain
                # inspectable without a fabricated expert assessment.
                selection_status="reference",
                selection_reason_code="not_retained_by_full_pool_s5",
                selection_reason=(
                    "未通过S5具体武器、科学闭合或创新断点准入，不进入S6画像撰写。"
                    if item.hypothesis_id in portfolio_rejected_ids
                    else "已通过S5全池校准，但按颠覆层级与创新优先排序后超出本轮S6并行写卡容量，保留为参考武器。"
                    if item.hypothesis_id in candidate_innovation_priorities
                    else "本轮未由S5保留为独立组合成员，不进入S6画像撰写。"
                ),
                innovation_priority=_dynamic_portfolio_innovation_priority(
                    item,
                    candidate_innovation_priorities.get(item.hypothesis_id),
                ),
                innovation_basis=candidate_innovation_bases.get(
                    item.hypothesis_id,
                    item.core_disruptive_difference
                    or item.disruptive_shift
                    or item.novelty_delta,
                ),
                **candidate_naming_assessments.get(item.hypothesis_id, {}),
                disruption_tier=candidate_disruption_tiers.get(item.hypothesis_id, ""),
                displaced_operational_mode=candidate_displaced_modes.get(
                    item.hypothesis_id, ""
                ),
                new_operational_mode=candidate_new_operational_modes.get(
                    item.hypothesis_id, ""
                ),
                winning_relation_shift=candidate_winning_relation_shifts.get(
                    item.hypothesis_id, ""
                ),
                s6_eligible=False,
            )
        candidate_lineage.append(row)
    accumulated["winning_swarm"] = {
        "policy": dict(swarm_controller.policy),
        "mission_graph": to_plain(graph),
        "task_graph": [to_plain(item) for item in graph.agent_instances],
        "role_contracts": [to_plain(item) for item in graph.role_contracts],
        "naming_plan": naming_plan,
        "seat_dimension_portfolios": {
            instance_id: {
                "open": bool(assignment.get("open_dimension_slots", True)),
                "slot_count": int(assignment.get("dimension_slot_count", 3) or 3),
                "primary_dimension_code": str(
                    assignment.get("primary_dimension_code", "")
                ),
                "primary_dimension_label": str(
                    assignment.get("primary_dimension_label", "")
                ),
                "dimension_codes": list(
                    assignment.get("dimension_codes", [])
                ),
                "reference_dimension_codes": list(
                    assignment.get("reference_dimension_codes", [])
                ),
                "reference_only_dimension_codes": list(
                    assignment.get("reference_dimension_codes", [])
                ),
                "dimension_portfolio": [
                    dict(item)
                    for item in assignment.get("dimension_portfolio", [])
                    if isinstance(item, Mapping)
                ],
            }
            for instance_id, assignment in winning_angle_assignments.items()
        },
        "seat_realized_dimensions": {
            instance_id: sorted(values)
            for instance_id, values in seat_realized_dimensions.items()
        },
        "dimension_mode": "multi_dimensional_per_seat",
        "dimension_catalog_size": len(
            _s3_s4_dimension_catalog(
                next(iter(winning_angle_assignments.values()), {})
            )
        ),
        "candidate_id_aliases": dict(sorted(candidate_id_aliases.items())),
        "candidate_lineage": candidate_lineage,
        "hypothesis_ledger": to_plain(ledger),
        "hypotheses": [to_plain(item) for item in ledger.hypotheses],
        "contributions": [to_plain(item) for item in contribution_rows],
        "merge_receipts": [to_plain(item) for item in merge_receipts],
        "portfolio_decision": to_plain(decision),
        "portfolio_diversity_audit": portfolio_diversity_audit,
        "semantic_cluster_audit": semantic_cluster_audit,
        "finalists": [to_plain(item) for item in final_hypotheses],
        "final_equipment_portfolio": equipment_portfolio,
        "portfolio_quality_gate": {
            "passed": portfolio_quality_gate_passed,
            "direction_count": len(equipment_portfolio),
            "direct_combat_equipment_count": direct_combat_count,
            "mission_equipment_count": mission_equipment_count,
            "query_domain_mode": query_domain_mode,
            "query_domain_main_body_count": domain_main_body_count,
            "query_domain_main_body_passed": domain_main_body_passed,
            "complete_s6_handoff_count": complete_handoff_count,
            "s6_handoff_gate_passed": s6_handoff_gate_passed,
            "equipment_diversity_passed": equipment_diversity_passed,
            "equipment_family_count": equipment_family_count,
            "equipment_family_counts": equipment_family_counts,
            "direct_equipment_family_counts": (direct_equipment_family_counts),
            "distinct_direct_equipment_family_count": (
                distinct_direct_equipment_family_count
            ),
            "preferred_distinct_direct_equipment": (
                preferred_distinct_direct_equipment
            ),
            "available_distinct_direct_equipment_family_count": (
                distinct_direct_equipment_family_count
            ),
            "direct_equipment_diversity_passed": (direct_equipment_diversity_passed),
            "direct_equipment_diversity_limited": (direct_equipment_diversity_limited),
            "direct_equipment_diversity_warning": (
                "当前保留"
                f"{distinct_direct_equipment_family_count}个互异直接装备族；"
                f"未达到优先目标{preferred_distinct_direct_equipment}个，"
                "仅作为待补强项，不因数量不足淘汰已通过候选"
                if direct_equipment_diversity_limited
                else ""
            ),
            "diversity_only_warning": diversity_only_warning,
            "direct_combat_main_body_passed": (direct_combat_main_body_passed),
            "minimum_equipment_family_count": minimum_family_count,
            "maximum_same_family_count": maximum_same_family_count,
            "maximum_allowed_same_family": maximum_allowed_same_family,
            "same_family_minimum_independent_axes": int(
                swarm_controller.policy.get(
                    "same_family_minimum_independent_axes",
                    2,
                )
            ),
            "same_family_independence_conflicts": (same_family_independence_conflicts),
            "remote_precision_required": False,
            "remote_precision_present": remote_precision_present,
            "selection_rule": (
                "多选制：增量五轴语义聚类与六个并发S5独立评分席位决定保留、合并和判退；"
                "先在同一制胜维度内竞优并压缩同构候选，再跨维度优先覆盖互异制胜关系；"
                "最多保留7项，随后由S6逐卡并发撰写能力画像"
            ),
            "s6_card_capacity": int(
                swarm_controller.policy.get("finalist_maximum", 7)
            ),
            "direct_combat_equipment_must_be_main_body": (
                query_domain_mode == "direct_combat"
            ),
        },
        "execution_batches": execution_batches,
        "events_version": "winning_swarm_dynamic_v2",
        "s5_fallback_activated": s5_fallback_activated,
        "s5_fallback_reason": s5_fallback_reason,
        "s5_decision_scope": "innovation_disruption_only",
        "s5_scoring_mode": "parallel_per_creative_agent",
        "s5_reviewer_count": sum(
            item.archetype == "independent_portfolio_reviewer"
            and item.mission_node == "S5"
            for item in graph.agent_instances
        ),
        "s6_selection_limit": maximum,
        "s6_authoring_mode": "parallel_per_selected_equipment",
        "budget": {
            "planned_instances": len(graph.agent_instances),
            "completed_instances": len(completed_instances - failed_instances),
            "failed_instances": len(failed_instances),
            "minimum_instances": graph.minimum_instances,
            "maximum_instances": graph.maximum_instances,
            "maximum_concurrency": graph.maximum_concurrency,
            "maximum_observed_concurrency": maximum_observed_concurrency,
        },
        "adaptive_coverage": {
            "recruitment_used": coverage_recruitment_used,
            "recruitment_cutoff": coverage_recruitment_cutoff,
            "consecutive_low_novelty": consecutive_low_novelty,
            "last_cluster_count": len(previous_coverage_cluster_keys),
        },
        "stop_reason": (
            "mission_graph_complete_with_diversity_warning"
            if portfolio_quality_gate_passed and direct_equipment_diversity_limited
            else (
                "mission_graph_complete"
                if portfolio_quality_gate_passed
                else "mission_graph_limited_no_deliverable_portfolio"
            )
        ),
    }
    emit_swarm_event(
        "winning_portfolio_merge_completed",
        graph_id=graph.graph_id,
        ledger_id=ledger.ledger_id,
        ledger_version=ledger.version,
        selected_hypothesis_ids=decision.selected_hypothesis_ids,
        rejected_hypothesis_ids=decision.rejected_hypothesis_ids,
        final_equipment_portfolio=_compact_equipment_portfolio_event(
            equipment_portfolio
        ),
        portfolio_quality_gate=accumulated["winning_swarm"]["portfolio_quality_gate"],
        swarm_summary=_compact_swarm_event_summary(accumulated["winning_swarm"]),
    )
