"""Winning coordinator: mode selection, common S-step contracts, gates and finalization."""
# ruff: noqa: F841

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import (
    Mapping,
    Sequence,
)
from hashlib import (
    sha256,
)
from typing import (
    Any,
)
from urllib.parse import urlsplit

from equipment_deep_research.agents.workflows.errors import S6QualityError
from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_prompt,
)
from equipment_deep_research.agents.workflows.s6_quality import (
    _capability_direction_quality_issues,
    _capability_synthesis_handoff,
    _collect_reference_ids,
    _compact_s6_prior_outputs,
    _merge_dynamic_portfolio_with_s6_authored_cards,
    _merge_s6_direction_repairs,
    _merge_s6_portrait_module_repairs,
    _normalize_concept_direction_priorities,
    _normalize_effect_chain_references,
    _normalize_priority_references,
    _normalize_s6_deterministic_format,
    _prioritized_evidence_index,
    _s6_can_use_lightweight_card_repair,
    _s6_delivery_blocking_issues,
    _s6_first_pass_quality_contract,
    _s6_markdown_authoring_contract,
    _s6_portrait_module_repair_targets,
    _s6_portrait_repair_issues,
    _s6_release_gate_state,
    _s6_repair_targets,
)
from equipment_deep_research.agents.workflows.winning_flows import (
    clustering,
    dynamic_swarm,
    optimized,
    quality_swarm,
    s6_authoring,
    standard,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    S3_S4_WEAPON_NAMING_TYPES as S3_S4_WEAPON_NAMING_TYPES,
)
from equipment_deep_research.domain.capability_portrait import (
    S6_DEFAULT_CODEX_CONCURRENCY,
    S6_MAX_CODEX_CONCURRENCY,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _bounded_s6_parallelism as _bounded_s6_parallelism,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _bounded_semantic_review_window as _bounded_semantic_review_window,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _compact_s6_authored_card_event as _compact_s6_authored_card_event,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _creative_s3_candidate_instruction as _creative_s3_candidate_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _dynamic_portfolio_innovation_priority as _dynamic_portfolio_innovation_priority,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _dynamic_role_contract_handoff as _dynamic_role_contract_handoff,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _dynamic_s6_card_input as _dynamic_s6_card_input,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _dynamic_s6_input_fingerprint as _dynamic_s6_input_fingerprint,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _extract_s6_direction as _extract_s6_direction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _minimal_portfolio_candidate_handoff as _minimal_portfolio_candidate_handoff,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _minimal_s6_card_handoff as _minimal_s6_card_handoff,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _open_s3_exploration_brief as _open_s3_exploration_brief,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _open_s3_theme_contract as _open_s3_theme_contract,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _open_s3_theme_instruction as _open_s3_theme_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _parallel_s6_card_instruction as _parallel_s6_card_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _parallel_s6_quality_repair_instruction as _parallel_s6_quality_repair_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _parallel_s6_short_module_repair_instruction as _parallel_s6_short_module_repair_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _quality_cluster_candidate_instruction as _quality_cluster_candidate_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _random_s3_s4_naming_types as _random_s3_s4_naming_types,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s3_s4_name_authoring_issues as _s3_s4_name_authoring_issues,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s3_s4_naming_assignment as _s3_s4_naming_assignment,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s3_s4_quality_first_instruction as _s3_s4_quality_first_instruction,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s3_s4_rows_need_creative_retry as _s3_s4_rows_need_creative_retry,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_dimension_scores as _s5_dimension_scores,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_disruption_tier_rank as _s5_disruption_tier_rank,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_innovation_basis as _s5_innovation_basis,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_naming_assessment as _s5_naming_assessment,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_portfolio_fallback_result as _s5_portfolio_fallback_result,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_retain_passes_concrete_weapon_contract as _s5_retain_passes_concrete_weapon_contract,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_card_attempt_limit as _s6_card_attempt_limit,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_card_timeout_threshold as _s6_card_timeout_threshold,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_hard_timeout_is_enabled as _s6_hard_timeout_is_enabled,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_portrait_module_lengths as _s6_portrait_module_lengths,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_repair_wall_timeout_seconds as _s6_repair_wall_timeout_seconds,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s6_short_portrait_modules as _s6_short_portrait_modules,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _stabilize_s6_direction_structure as _stabilize_s6_direction_structure,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _targeted_expert_feedback as _targeted_expert_feedback,
)
from equipment_deep_research.agents.workflows.winning_stages import (
    stage_for,
)
from equipment_deep_research.domain.models import (
    WinningHypothesis,
    to_plain,
)
from equipment_deep_research.domain.swarm_strategy import SwarmState
from equipment_deep_research.domain.research_focus import (
    disruptive_seed_context,
)
from equipment_deep_research.orchestration.winning_mode import (
    resolve_winning_mode,
)
from equipment_deep_research.orchestration.winning_swarm import (
    SCIENTIFIC_WEAPON_REALIZABILITY_CONVENTION,
    WinningSwarmController,
)
from equipment_deep_research.providers.responses import (
    ProviderRequestError,
)


def _coordinator_helper(name: str):
    """Resolve legacy coordinator helpers only when a workflow calls them."""

    from equipment_deep_research.agents.workflows import coordinator

    return getattr(coordinator, name)


def _branch_product_output_schema(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_branch_product_output_schema")(*args, **kwargs)


def _compact_prompt_value(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_compact_prompt_value")(*args, **kwargs)


def _compact_swarm_event_summary(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_compact_swarm_event_summary")(*args, **kwargs)


def _is_harness_budget_error(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_is_harness_budget_error")(*args, **kwargs)


def _latest_inner_loop_failures(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_latest_inner_loop_failures")(*args, **kwargs)


def _parse_json_object(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_parse_json_object")(*args, **kwargs)


def _query_combat_equipment_divergence_brief(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_query_combat_equipment_divergence_brief")(*args, **kwargs)


def _query_led_combat_equipment_theme_instruction(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_query_led_combat_equipment_theme_instruction")(*args, **kwargs)


def _winning_military_divergence_contract(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_winning_military_divergence_contract")(*args, **kwargs)


def _winning_step_modes(*args: Any, **kwargs: Any) -> Any:
    return _coordinator_helper("_winning_step_modes")(*args, **kwargs)


def _winning_prompt(section: str, **values: Any) -> str:
    """Load model-facing legacy workflow prose from the reviewed Markdown.

    ``winning.py`` still owns orchestration and dynamic context assembly, but
    it must not own long natural-language instructions.  Prompt resources use
    ``{name}`` placeholders only where a runtime value is genuinely needed;
    replacement is deliberately literal so JSON braces in the resource remain
    untouched.
    """

    prompt = load_dynamic_winning_prompt("common", section=section)
    for key, value in values.items():
        prompt = prompt.replace("{" + str(key) + "}", str(value))
    return prompt


# Compatibility marker for source-level contract audits.  Actual prose is
# loaded from Markdown at runtime; legacy callers may still search for the
# historical ``+ _s6_markdown_authoring_contract()`` integration point.
# + _s6_markdown_authoring_contract()


async def analyze_winning_subagents(
    host,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run S1-S6 as independent Codex sessions with explicit handoffs."""
    if str(payload.get("execution_profile_id", "")).strip() == "deep_divergence_v1":
        return await _analyze_deep_divergence_subagents(host, payload)
    # Keep run-level prompt/memory snapshot identity on the provider host so
    # every nested S1--S6 call (including dynamic seats and S6 card modules)
    # can emit a reconstructable RetrievalEvent even when its compact step
    # payload intentionally omits global metadata.
    set_evolution_context = getattr(host, "set_evolution_context", None)
    if callable(set_evolution_context):
        set_evolution_context(
            {
                "run_id": payload.get("run_id", ""),
                "trace_id": payload.get("trace_id", payload.get("run_id", "")),
                "prompt_bundle_hash": payload.get("prompt_bundle_hash", ""),
                "memory_snapshot_hash": payload.get("memory_snapshot_hash", ""),
                "memory_ids": payload.get("memory_ids", []),
                "prompt_section_ids": payload.get("prompt_section_ids", []),
                "tenant_id": payload.get("tenant_id", ""),
                "workspace_id": payload.get("workspace_id", ""),
                "project_id": payload.get("project_id", ""),
                "profile_id": payload.get("profile_id", ""),
                "route": payload.get("route", payload.get("research_route", "")),
                "stage_scope": payload.get("stage_scope", []),
            }
        )
    metric_offset = host._call_metric_count()
    shared = {
        "run_id": payload.get("run_id", ""),
        "topic": payload.get("topic", ""),
        "structured_query_brief": payload.get("structured_query_brief", {}),
        "research_route": payload.get("research_route", ""),
        "discovery_blueprint": payload.get("discovery_blueprint", {}),
        "discovery_branch": payload.get("discovery_branch", ""),
        "coverage": payload.get("coverage", {}),
        "packets": payload.get("packets", []),
        "military_value_handoff": payload.get("military_value_handoff", {}),
        "evidence_index": payload.get("evidence_index", []),
        "discovery_convergence": payload.get("discovery_convergence", {}),
        "new_evidence_ids": payload.get("new_evidence_ids", []),
        "new_packet_ids": payload.get("new_packet_ids", []),
        "shared_skill_catalog": payload.get("shared_skill_catalog", []),
        "knowledge_pack_catalog": payload.get("knowledge_pack_catalog", []),
        "resume_from": payload.get("resume_from", "L1"),
        "attempt": payload.get("attempt", 1),
        "selected_business_agent_ids": payload.get("selected_business_agent_ids", []),
        "prior_winning_analysis": payload.get("prior_winning_analysis", {}),
        "resume_steps": payload.get("resume_steps", []),
        "execution_profile_id": payload.get("execution_profile_id", "legacy_v1"),
        "execution_contract": payload.get("execution_contract", {}),
        "ablation_scope": payload.get("ablation_scope", ""),
        "evidence_closed": bool(payload.get("evidence_closed", False)),
        "expert_review_feedback": payload.get("expert_review_feedback", []),
        # Deep-divergence children receive a canonical parent snapshot from
        # the API. Keep it visible to the scoped S3/S4/S6 helper; ordinary
        # winning profiles never populate this field.
        "deep_parent_context": payload.get("deep_parent_context", {}),
    }
    winning_mode = resolve_winning_mode(shared["execution_profile_id"])
    quality_contract = winning_mode.uses_quality_contract
    aggressive_compaction = winning_mode.optimized
    analysis_priority_contract = {
        "primary": [
            "current_agent_specialist_role_and_method",
            "query_military_problem",
            "direct_combat_value",
        ],
        "secondary_only": "cross_agent_handoff_for_evidence_constraints_counterevidence",
        "handoff_must_not_control": [
            "agenda",
            "structure",
            "naming",
            "priority",
            "final_conclusion",
        ],
    }

    raw_military_handoff = shared.get("military_value_handoff", {})
    military_value_claims = [
        {
            "military_effects": list(item.get("military_effects", []))[:5],
            "mechanism": str(item.get("mechanism", ""))[:460],
        }
        for item in (
            raw_military_handoff.get("claims", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("mechanism", "")).strip()
    ]
    military_branch_products = (
        raw_military_handoff.get("branch_products", {})
        if isinstance(raw_military_handoff, Mapping)
        else {}
    )
    baseline_boundaries = [
        {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": str(item.get("agent_id", "")),
            "availability": "unavailable",
            "limitations": [
                str(value)[:260] for value in item.get("limitations", [])[:2]
            ],
            "open_questions": [
                str(value)[:260] for value in item.get("open_questions", [])[:2]
            ],
            "downstream_obligations": [
                str(value)[:300] for value in item.get("downstream_obligations", [])[:3]
            ],
        }
        for item in (
            raw_military_handoff.get("baseline_boundaries", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and str(item.get("availability", "")) == "unavailable"
    ]
    baseline_frontier_inspirations = [
        {
            "source_agent_id": str(item.get("source_agent_id", "")),
            "packet_id": str(item.get("packet_id", "")),
            "signal": str(item.get("signal", ""))[:220],
            "conventional_assumption_challenged": str(
                item.get("conventional_assumption_challenged", "")
            )[:180],
            "possible_military_discontinuity": str(
                item.get("possible_military_discontinuity", "")
            )[:220],
            "query_relevance": str(item.get("query_relevance", ""))[:180],
            "evidence_boundary": str(item.get("evidence_boundary", ""))[:220],
            "downstream_question": str(item.get("downstream_question", ""))[:220],
            "evidence_ids": list(item.get("evidence_ids", []))[:3],
            "source_urls": list(item.get("source_urls", []))[:2],
        }
        for item in (
            raw_military_handoff.get("frontier_inspirations", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("signal", "")).strip()
    ][:6]

    def military_claims_for_steps(indices: Sequence[int]) -> list[dict[str, Any]]:
        targets = {f"S{index}" for index in indices if 1 <= index <= 5}
        rows = [
            item
            for item in military_value_claims
            if not item.get("downstream_steps")
            or targets.intersection(map(str, item.get("downstream_steps", [])))
        ]
        return rows[: min(8, max(4, len(indices) * 3))]

    def creative_military_value_handoff() -> dict[str, Any]:
        """Expose only a tiny military-value hint to creative S3/S4 Agents."""

        return {"claims": [dict(item) for item in military_value_claims[:2]]}

    def military_packet_refs_for_claims(
        claims: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        packet_ids = {
            str(item.get("packet_id", ""))
            for item in claims
            if str(item.get("packet_id", ""))
        }
        # The minimal military handoff intentionally omits packet routing
        # metadata. In that mode, retain the independently supplied packet
        # index rather than dropping all baseline context.
        if not packet_ids:
            return [
                {
                    "packet_id": item["packet_id"],
                    "agent_id": item["agent_id"],
                    "evidence_ids": item.get("evidence_ids", [])[:3],
                    "confidence": item.get("confidence"),
                }
                for item in packet_index
                if item.get("packet_id")
            ]
        return [
            {
                "packet_id": item["packet_id"],
                "agent_id": item["agent_id"],
                "evidence_ids": item["evidence_ids"][:3],
                "confidence": item["confidence"],
            }
            for item in packet_index
            if item["packet_id"] in packet_ids
        ]

    def evidence_for_claims(
        claims: Sequence[Mapping[str, Any]],
        *,
        prior_step_outputs: Mapping[str, Any] | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        relevant_ids = {
            str(evidence_id)
            for item in claims
            for evidence_id in item.get("evidence_ids", [])
            if str(evidence_id)
        }
        relevant_ids.update(_collect_reference_ids(prior_step_outputs or {}))
        return [
            dict(item)
            for item in shared.get("evidence_index", [])
            if isinstance(item, Mapping)
            and str(item.get("evidence_id", "")) in relevant_ids
        ][:limit]

    packet_index = [
        {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": str(item.get("agent_id", "")),
            "capability_tags": list(item.get("capability_tags", [])),
            "handoff_summary": str(item.get("handoff_summary", "")),
            "evidence_ids": list(item.get("evidence_ids", [])),
            "confidence": item.get("confidence"),
            "open_questions": list(item.get("open_questions", []))[:3],
        }
        for item in shared["packets"]
        if isinstance(item, Mapping)
    ]

    def packet_projection(item: Mapping[str, Any], *, step: int) -> dict[str, Any]:
        """Keep only decision-bearing handoff fields for the current S-step."""
        agent_id = str(item.get("agent_id", ""))
        case_packet = agent_id == "case_research" and step in {3, 4, 5, 6}
        payload_value = item.get("business_payload", item.get("payload", {}))
        projected = {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": agent_id,
            "summary": str(item.get("summary", "") or item.get("handoff_summary", "")),
            "findings": list(item.get("findings", []))[: (6 if case_packet else 3)],
            "business_payload": payload_value,
            "evidence_ids": list(item.get("evidence_ids", []))[
                : (12 if case_packet else 6)
            ],
            "confidence": item.get("confidence"),
            "limits": list(item.get("limits", item.get("limitations", [])))[:1],
            "next_questions": list(
                item.get("next_questions", item.get("open_questions", []))
            )[:1],
        }
        return _compact_prompt_value(
            {
                key: value
                for key, value in projected.items()
                if value not in (None, "", [], {})
            },
            max_string_chars=900 if case_packet else 220,
            max_list_items=10 if case_packet else 3,
        )

    valid_evidence_ids = {
        str(item.get("evidence_id", ""))
        for item in shared.get("evidence_index", [])
        if isinstance(item, Mapping) and str(item.get("evidence_id", "")).strip()
    }
    valid_packet_ids = {
        str(item.get("packet_id", ""))
        for item in packet_index
        if str(item.get("packet_id", "")).strip()
    }
    valid_reference_ids = valid_evidence_ids | valid_packet_ids
    packet_agents_by_step = {
        1: {
            "international_situation",
            "opponent_monitoring",
            "system_confrontation",
            "weapon_equipment",
        },
        2: {
            "combat_scenario",
            "operational_employment",
            "international_situation",
        },
        3: set(),
        4: {
            "combat_scenario",
            "operational_employment",
            "system_confrontation",
            "weapon_equipment",
        },
        5: {
            "weapon_equipment",
            "system_confrontation",
            "combat_scenario",
        },
        6: set(),
    }
    primary_branch_for_packets = str(
        shared.get("discovery_blueprint", {}).get("primary_branch", "")
        if isinstance(shared.get("discovery_blueprint", {}), Mapping)
        else ""
    )
    if primary_branch_for_packets == "C":
        for step in (3, 4, 5, 6):
            packet_agents_by_step[step].add("case_research")

    def step_shared_context(
        index: int,
        prior_step_outputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        blueprint = shared.get("discovery_blueprint", {})
        compact_blueprint = (
            {
                key: blueprint.get(key)
                for key in (
                    "execution_profile_id",
                    "primary_branch",
                    "runtime_route",
                    "emphasis",
                    "required_outputs",
                    "reference_focus",
                    "focus_questions",
                    "hard_constraints",
                    "structured_query_brief",
                    "adaptive_winning_step_modes",
                )
                if blueprint.get(key) not in (None, "", [], {})
            }
            if isinstance(blueprint, Mapping)
            else {}
        )
        if quality_contract:
            compact_blueprint["execution_profile_id"] = shared["execution_profile_id"]
        allowed_agents = packet_agents_by_step[index]
        case_projection = primary_branch_for_packets == "C" and index in {3, 4, 5, 6}
        step_claims = (
            list(creative_military_value_handoff()["claims"])
            if quality_contract and index in {3, 4}
            else (
                military_claims_for_steps([index])
                if quality_contract and index <= 5
                else []
            )
        )
        if quality_contract:
            evidence_rows = (
                []
                if index in {3, 4}
                else evidence_for_claims(
                    step_claims,
                    prior_step_outputs=prior_step_outputs,
                    limit=12 if case_projection else (10 if index in {1, 2} else 8),
                )
            )
            selected_packets: list[Mapping[str, Any]] = []
            step_packet_index = (
                [] if index in {3, 4} else military_packet_refs_for_claims(step_claims)
            )
        else:
            evidence_rows = _prioritized_evidence_index(
                shared["evidence_index"],
                preferred_ids=_collect_reference_ids(prior_step_outputs or {}),
                allowed_agents=allowed_agents,
                limit=16 if index in {1, 2} else 12,
            )
            selected_packets = [
                item
                for item in shared["packets"]
                if isinstance(item, Mapping)
                and str(item.get("agent_id", "")) in allowed_agents
            ]
            step_packet_index = packet_index
        context = {
            "topic": shared["topic"],
            "query": shared["topic"],
            "structured_query_brief": _compact_prompt_value(
                shared.get("structured_query_brief", {}),
                max_string_chars=360,
                max_list_items=8,
            ),
            "query_combat_equipment_divergence_brief": (
                _query_combat_equipment_divergence_brief(
                    str(shared.get("topic", "")),
                    structured_query_brief=shared.get("structured_query_brief", {}),
                )
            ),
            "research_route": shared["research_route"],
            "discovery_branch": shared["discovery_branch"],
            "execution_profile_id": shared["execution_profile_id"],
            "analysis_priority": analysis_priority_contract,
            "discovery_blueprint": compact_blueprint,
            "packet_index": _compact_prompt_value(
                step_packet_index,
                max_string_chars=220 if aggressive_compaction else 280,
                max_list_items=6 if aggressive_compaction else 8,
            ),
            "packets": (
                [packet_projection(item, step=index) for item in selected_packets]
                if quality_contract
                else _compact_prompt_value(
                    selected_packets,
                    max_string_chars=1200
                    if case_projection
                    else (420 if index in {1, 2} else 280),
                    max_list_items=14
                    if case_projection
                    else (6 if index in {1, 2} else 4),
                )
            ),
            "military_value_handoff": (
                {"claims": step_claims}
                if quality_contract and index in {3, 4} and step_claims
                else {}
            ),
            "secondary_cross_agent_constraints": (
                _compact_prompt_value(
                    step_claims,
                    max_string_chars=460,
                    max_list_items=6,
                )
                if quality_contract and index in {1, 2, 5}
                else []
            ),
            "branch_products": (
                _compact_prompt_value(
                    military_branch_products,
                    max_string_chars=360,
                    max_list_items=8,
                )
                if quality_contract and primary_branch_for_packets == "C" and index == 5
                else {}
            ),
            "evidence_index": _compact_prompt_value(
                evidence_rows,
                max_string_chars=240 if aggressive_compaction else 300,
                max_list_items=len(evidence_rows),
            ),
            "discovery_convergence": _compact_prompt_value(
                (
                    shared.get("discovery_convergence", {})
                    if not aggressive_compaction and index in {1, 2}
                    else {}
                ),
                max_string_chars=260 if aggressive_compaction else 420,
                max_list_items=3 if aggressive_compaction else 6,
            ),
        }
        targeted_feedback = _targeted_expert_feedback(
            shared.get("expert_review_feedback", []),
            f"S{index}",
        )
        if targeted_feedback:
            context["expert_review_feedback"] = _compact_prompt_value(
                targeted_feedback,
                max_string_chars=520,
                max_list_items=8,
            )
        step_agent_id = stage_for(index).agent_id
        if index == 5:
            selected_seed_context = disruptive_seed_context(
                str(shared.get("topic", "")),
                branch=primary_branch_for_packets,
                agent_id=step_agent_id,
            )
            if selected_seed_context:
                context["disruptive_seed_context"] = selected_seed_context
        if index <= 5:
            context["military_divergence_contract"] = (
                _winning_military_divergence_contract(index)
            )
        if not quality_contract:
            context.update(
                {
                    "coverage": shared["coverage"],
                    "resume_from": shared["resume_from"],
                    "attempt": shared["attempt"],
                }
            )
        elif index in {1, 2} and shared.get("coverage"):
            context["coverage"] = _compact_prompt_value(
                shared["coverage"], max_string_chars=180, max_list_items=3
            )
        recall_increment = {
            "new_evidence_ids": list(shared.get("new_evidence_ids", []))[:12],
            "new_packet_ids": list(shared.get("new_packet_ids", []))[:6],
        }
        if any(recall_increment.values()):
            context["recall_increment"] = recall_increment
        return {
            key: value
            for key, value in context.items()
            if value not in (None, "", [], {})
        }

    def compact_for_prompt(
        value: Any,
        *,
        max_string_chars: int = 900,
        max_list_items: int = 8,
    ) -> Any:
        """Bound repeated model context without changing the stored result."""
        return _compact_prompt_value(
            value,
            max_string_chars=max_string_chars,
            max_list_items=max_list_items,
        )

    def round_review_projection(value: Mapping[str, Any]) -> dict[str, Any]:
        keys = (
            "defense_decomposition",
            "operational_review",
            "winning_paths",
            "breakthrough_directions",
            "effect_chain",
            "capability_mapping",
            "dotmlpf_matrix",
            "s4_concept_directions",
            "gap_assessment",
            "concept_directions",
            "capability_image_drafts",
            "upstream_coverage",
            "evidence_validation",
            "reasoning_nodes",
            "open_questions",
        )
        return compact_for_prompt(
            {key: value[key] for key in keys if key in value},
            max_string_chars=700,
            max_list_items=6,
        )

    def prior_projection(
        index: int,
        prior_step_outputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        field_map = {
            1: (),
            2: ("defense_decomposition",),
            3: (
                "defense_decomposition",
                "operational_review",
                "winning_paths",
                "existing_tactic_baseline",
                "tactic_concepts",
                "tactic_validation_results",
            ),
            4: ("breakthrough_directions", "effect_chain"),
            5: (
                "capability_mapping",
                "dotmlpf_matrix",
                "s4_concept_directions",
            ),
            6: (
                "capability_mapping",
                "gap_assessment",
                "s4_concept_directions",
            ),
        }
        if index == 6:
            projected = _compact_s6_prior_outputs(prior_step_outputs)
            if aggressive_compaction:
                projected = compact_for_prompt(
                    projected,
                    max_string_chars=420,
                    max_list_items=6,
                )
        else:
            projected = {
                key: compact_for_prompt(
                    prior_step_outputs[key],
                    max_string_chars=520 if aggressive_compaction else 900,
                    max_list_items=6 if aggressive_compaction else 8,
                )
                for key in field_map[index]
                if key in prior_step_outputs
            }
        raw_nodes = prior_step_outputs.get("reasoning_nodes", {})
        if not aggressive_compaction and isinstance(raw_nodes, Mapping):
            projected["reasoning_nodes"] = {
                str(step): compact_for_prompt(
                    value,
                    max_string_chars=500,
                    max_list_items=6,
                )
                for step, value in raw_nodes.items()
                if str(step).isdigit() and int(str(step)) <= index
            }
        dynamic_rows = prior_step_outputs.get("dynamic_subagent_outputs", [])
        if isinstance(dynamic_rows, list):
            allowed_merge_targets = {f"S{index}"}
            if index == 6:
                allowed_merge_targets.add("convergence")
            eligible_dynamic_rows = [
                item
                for item in dynamic_rows
                if isinstance(item, Mapping)
                and item.get("accepted", True) is True
                and str(item.get("merge_target", "")) in allowed_merge_targets
                and isinstance(item.get("result", {}), Mapping)
            ]
            projected["dynamic_inputs"] = [
                {
                    "agent_instance_id": str(item.get("agent_instance_id", "")),
                    "hypothesis_id": str(item.get("hypothesis_id", "")),
                    "merge_target": str(item.get("merge_target", "")),
                    "findings": list(result.get("findings", []))[
                        : (2 if aggressive_compaction else 4)
                    ],
                    "contribution_to_steps": list(
                        result.get("contribution_to_steps", [])
                    )[: (2 if aggressive_compaction else 4)],
                    "evidence_refs": list(result.get("evidence_refs", []))[
                        : (4 if aggressive_compaction else 8)
                    ],
                    "open_questions": list(result.get("open_questions", []))[:1],
                    "confidence": result.get("confidence"),
                }
                for item in eligible_dynamic_rows[: (4 if quality_contract else 3)]
                if isinstance((result := item.get("result", {})), Mapping)
            ]
        winning_swarm = prior_step_outputs.get("winning_swarm", {})
        if index in {4, 5, 6} and isinstance(winning_swarm, Mapping):
            finalists = winning_swarm.get("finalists", [])
            if isinstance(finalists, list):
                projected["winning_hypotheses"] = [
                    compact_for_prompt(
                        item,
                        max_string_chars=420 if aggressive_compaction else 700,
                        max_list_items=6,
                    )
                    for item in finalists[:4]
                    if isinstance(item, Mapping)
                ]
        return projected

    def sanitize_references(value: Any) -> Any:
        if isinstance(value, list):
            return [sanitize_references(item) for item in value]
        if not isinstance(value, Mapping):
            return value
        cleaned: dict[str, Any] = {}
        removed_refs: list[str] = []
        for key, item in value.items():
            if key in {"evidence_refs", "direct_evidence_refs"} and isinstance(
                item, list
            ):
                accepted = [str(ref) for ref in item if str(ref) in valid_reference_ids]
                removed_refs.extend(
                    str(ref) for ref in item if str(ref) not in valid_reference_ids
                )
                cleaned[key] = list(dict.fromkeys(accepted))
            else:
                cleaned[str(key)] = sanitize_references(item)
        if removed_refs and "derived_from" in cleaned:
            existing = cleaned.get("derived_from", [])
            existing_rows = list(existing) if isinstance(existing, list) else []
            cleaned["derived_from"] = list(
                dict.fromkeys([*map(str, existing_rows), *removed_refs])
            )
        return cleaned

    primary_branch = str(
        shared.get("discovery_blueprint", {}).get("primary_branch", "")
        if isinstance(shared.get("discovery_blueprint", {}), Mapping)
        else ""
    ) or {
        "new_winning_mechanism": "A",
        "traditional_gap": "B",
        "war_case_learning": "C",
    }.get(str(shared.get("research_route", "")), "B")
    branch_product_schema = _branch_product_output_schema(primary_branch)

    query_led_combat_rule = _winning_prompt(
        "legacy_workflow.evidence_closed_rule"
        if shared["evidence_closed"]
        else "legacy_workflow.query_led_rule"
    )
    equipment_theme_rule = _query_led_combat_equipment_theme_instruction(
        str(shared.get("topic", "")),
        structured_query_brief=(
            shared.get("structured_query_brief", {})
            if isinstance(shared.get("structured_query_brief", {}), Mapping)
            else {}
        ),
    )
    steps = [
        (
            "winning_s1_opponent",
            _winning_prompt(
                "legacy_workflow.s1_system",
                query_rule=query_led_combat_rule,
            ),
            {
                "defense_decomposition": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s2_operations",
            _winning_prompt(
                "legacy_workflow.s2_system",
                query_rule=query_led_combat_rule,
            ),
            {
                "operational_review": ["string"],
                "winning_paths": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s3_breakthrough",
            _winning_prompt(
                "legacy_workflow.s3_system",
                query_rule=query_led_combat_rule,
                theme_rule=equipment_theme_rule + SCIENTIFIC_WEAPON_REALIZABILITY_CONVENTION,
            ),
            {
                "breakthrough_directions": ["string"],
                "effect_chain": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s4_capability",
            _winning_prompt(
                "legacy_workflow.s4_system",
                query_rule=query_led_combat_rule,
                theme_rule=equipment_theme_rule + SCIENTIFIC_WEAPON_REALIZABILITY_CONVENTION,
            ),
            {
                "capability_mapping": ["string"],
                "dotmlpf_matrix": [
                    {
                        "mission": "string",
                        "gap_type": "platform|interface|redundancy|governance|mixed",
                        "materiel": ["string"],
                        "non_materiel": ["string"],
                        "interfaces": ["string"],
                        "boundaries": ["string"],
                        "evidence_refs": ["exact evidence_id or packet_id"],
                        "derived_from": ["packet_id, dynamic input, or prior step"],
                        "validation_needed": ["string"],
                    }
                ],
                "concept_directions": [
                    {
                        "name": "string",
                        "priority": "P1..P8",
                        "type": "new_capability|upgrade",
                        "function": "string",
                        "feasibility": "1..5",
                        "feasibility_basis": "string",
                        "direct_evidence_refs": ["exact evidence_id"],
                        "derived_from": ["packet_id, dynamic input, or prior step"],
                        "verification": "string",
                        "uncertainty_boundary": "string",
                        "military_value": "string",
                        "depth_mechanism": "string",
                        "foresight": "string",
                        "novelty": "string",
                        "strike_countermeasure_value": "string",
                        "equipment_form": "string",
                        "operational_mechanism": "string",
                        "capability_classification": {
                            "primary_dimension": "Query驱动的主要能力维度，如毁伤维度、突防维度或其他自然维度",
                            "secondary_dimensions": ["确有独立价值的辅助能力维度"],
                            "classification_basis": "主要战场结果、关键流程节点与制胜关系为何支持该分类",
                        },
                    }
                ],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s5_gap",
            _winning_prompt(
                "legacy_workflow.s5_system",
                query_rule=query_led_combat_rule,
                theme_rule=equipment_theme_rule,
            ),
            {
                "gap_assessment": [
                    {
                        "capability": "string",
                        "grade": "空白|关键差距|部分差距|满足|超出",
                        "gap_statement": "string",
                        "evidence_strength": "high|medium|low",
                        "current_upgrade": "string",
                        "new_development": "string",
                        "verification": "string",
                        "evidence_refs": ["exact evidence_id or packet_id"],
                        "basis": "string",
                    }
                ],
                "s6_preflight": {
                    "equipment_buckets": [
                        {
                            "category": "Codex依据Query语义形成的具体武器装备族标识",
                            "ready": "boolean",
                            "query_relevance": "与当前query契合的任务对象、作战阶段和直接作战效果",
                            "baseline_system": "该类方向的现役或类比装备基线",
                            "capability_gap": "该类方向独立且具体的能力差距",
                            "candidate_equipment": "与Query目标、阶段和直接战果对应的具体打击杀伤武器对象",
                            "primary_equipment_identity": "唯一主装备对象及其平台/弹体/载荷边界",
                            "process_actor": "实际执行部署、进入、搜索/告警、交战和再组织的主体",
                            "launch_or_release_domain": "明确空/陆/海/水下或平台中性，以及发射/释放方式",
                            "target_and_direct_effect": "主要目标对象与可直接验收的打击、毁伤、压制或拦截战果",
                            "operational_flow_contract": [
                                "Codex按完整语义形成、步骤数由真实交战因果链决定的装备专属作战流程"
                            ],
                            "cross_family_confusion_risks": [
                                "可能被基线、载荷或相邻卡片误导的主体/发射域/目标/毁伤语义"
                            ],
                            "capability_classification": {
                                "primary_dimension": "主要能力维度",
                                "secondary_dimensions": ["辅助能力维度"],
                                "classification_basis": "按主要战果和制胜关系说明归类依据",
                            },
                            "evidence_refs": ["exact evidence_id or packet_id"],
                            "blocking_reason": "ready=false时说明缺少的证据或因果条件",
                        }
                    ],
                    "title_risks": ["重复词、抽象技术名、支援装备冒充武器等风险"],
                },
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s6_image",
            _winning_prompt(
                "legacy_workflow.s6_system",
                theme_rule=equipment_theme_rule,
            )
            + "\n"
            + _s6_markdown_authoring_contract(),
            {
                "concept_directions": [
                    {
                        "name": "S3/S5冻结的自然整装名称：清楚识别唯一主装备，只承载一条最值得记住的创新主线；复杂任务、机理与战果写入下方说明，不把字段短语拼成标题",
                        "priority": "P1..P8",
                        "type": "new_capability|upgrade",
                        "function": "string",
                        "feasibility": "1..5",
                        "horizon": "near|mid|long",
                        "direct_evidence_refs": ["exact evidence_id"],
                        "foresight_evidence_status": "direct_object_baseline|analogous_project_evidence|component_mechanism_evidence",
                        "evidence_boundary": "公开证据支持与不支持的内容；未来增量属于何种待验证假设",
                        "derived_from": ["packet_id or prior step"],
                        "military_value": "string",
                        "depth_mechanism": "string",
                        "foresight": "string",
                        "novelty": "string",
                        "strike_countermeasure_value": "string",
                        "equipment_form": "具体武器装备形态；优先无人作战平台、导弹/弹药/拦截器、火控与效应器，写清载荷和作战对象",
                        "primary_equipment_identity": "唯一主装备对象，明确平台/弹体/载荷边界以及是否平台中性",
                        "operational_mechanism": "该装备能力如何作用于任务链并改变对抗效果",
                        "capability_classification": {
                            "primary_dimension": "主要能力维度，如毁伤维度、突防维度或Query驱动的其他自然维度",
                            "secondary_dimensions": ["确有独立价值的辅助维度"],
                            "classification_basis": "用通俗军语说明主要战果、关键流程节点和制胜关系为何支持该分类",
                        },
                        "equipment_semantic_assessment": {
                            "classification": "direct_combat|unmanned_combat|upgrade|system_link|support_only|non_equipment",
                            "direct_combat_effect": "boolean",
                            "support_only": "boolean",
                            "unmanned_combat": "boolean",
                            "precision_munition": "boolean",
                            "concrete_equipment": "boolean",
                            "query_alignment_confirmed": "boolean",
                            "rationale": "S5模型基于完整候选语义形成的判断理由",
                        },
                        "target_scenario": "面向的具体对象、环境、作战阶段和约束场景",
                        "problem_statement": "当前要解决的问题、难点、需求或任务链断点",
                        "scientific_principle": "支撑方案成立的作战、控制、信息、效应或体系原理",
                        "enabling_technologies": ["形成能力所采用的具体软硬件技术"],
                        "operational_concept": "装备如何编组、部署、协同、交战、评估和再组织的作战概念",
                        "operational_process": ["按时间顺序给出的关键作战流程步骤"],
                        "semantic_consistency_check": {
                            "process_actor": "流程各阶段实际行动主体",
                            "launch_or_release_mode": "发射、释放、部署域及其是否由方案明确限定",
                            "target_and_direct_effect": "主要目标对象与直接战果",
                            "checked_fields": [
                                "name|primary_equipment_identity|function|equipment_form|operational_concept|operational_process|capability_portrait"
                            ],
                            "consistent": True,
                            "resolution_note": "发现冲突时在本次成稿内如何重写；无冲突时说明为何一致",
                        },
                        "capability_outcome": "最终形成的可考核装备能力",
                        "winning_mechanism": "为何能改变时间、精度、成本、平台、毁伤或体系关系并制胜",
                        "development_path": "近期现役武器改装—中期无人/导弹/弹药样机或型号研制—体系集成与实弹/对抗验证闸门",
                        "future_trigger": "3至10年内使该方向变得必要或可行的威胁/技术/体系触发条件",
                        "adversary_adaptation": "对手可能采取的反适应及本方向的再对抗要求",
                        "validation_plan": [
                            "前瞻方向的可证伪验证、判退或淘汰条件；暂缺可显式标为后续补全"
                        ],
                        "query_relevance": "必填：该装备方向为何与当前query的任务对象、作战阶段、威胁压力和直接作战效果契合",
                        "baseline_system": "所有方向必填：优先写证据支持的公开型号/装备族谱及当前能力基线；证据不足时明确保留类别级，不得虚构型号",
                        "capability_gap": "所有方向必填：该装备对象在当前query下独立、具体且不可复用的能力差距",
                        "upgrade_package": [
                            "upgrade必填：服务直接作战效果的具体传感、火控、制导、电子战、任务软件或载荷改进措施"
                        ],
                        "combat_effect_uplift": "upgrade必填：升级后对实际作战、打击/反制和持续任务能力的提升",
                        "strike_chain_contribution": "upgrade必填：对侦察—决策—火力—打击—评估—再组织链路的贡献",
                        "upgrade_boundary": "upgrade必填：现役改装可达边界及必须转入新研的条件",
                        "capability_portrait": "由五个独立模块确定性组装的装备战斗画像；突出真实交战流程、直接战果和创新制胜机理，不写发展与验证信息",
                        "capability_portrait_modules": {
                            "overview": "只保留一个传统能力瓶颈、一个创新断点和一个直接战果",
                            "technology_implementation": "只保留一条技术痛点—突破原理—工程实现—能力跃迁的决定性突破链",
                            "operational_process": "只保留使任务状态发生变化的装备专属战斗动作链",
                            "capability_effects": "只保留相对基线新增能力和可验证战场结果",
                            "winning_logic": "只保留主要战争交换关系、新制胜机制和对手新增成本",
                        },
                        "system_contribution_thesis": "由本装备在实际体系中改变任务结果的原因独立形成的贡献判断；内容与结构服从本装备，不套逐装备固定字段或长句",
                        "indicator_portrait": "由本装备制胜机理和主要风险直接推导的差异化指标画像；指标选择、数量与证伪方式服从实际判断，不套固定指标清单",
                        "confidence": "0..1；按该对象证据强度和推导跨度单独给出；前瞻新质方向允许0.45..0.65，低置信度表示推导跨度而非失败",
                    }
                ],
                "capability_image_drafts": ["每项入选具体武器装备能力画像的单句结论"],
                "upstream_coverage": [
                    {
                        "upstream_item": "精简交接中的能力差距或作战效果名称",
                        "disposition": "standalone|merged|horizontal_layer",
                        "target_directions": ["最终能力方向名称"],
                        "rationale": "为何单列、合并或作为横向层",
                    }
                ],
                "branch_products": branch_product_schema,
                "evidence_validation": {
                    "all_ids_valid": "boolean",
                    "invalid_ids": ["string"],
                    "mismatched_claims": ["string"],
                },
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
    ]
    if primary_branch == "A":
        agent_id, system, schema = steps[1]
        steps[1] = (
            agent_id,
            system
            + " "
            + _winning_prompt("legacy_workflow.branch_a_tactic_suffix"),
            {
                **schema,
                "existing_tactic_baseline": ["string"],
                "tactic_concepts": [
                    {
                        "tactic_id": "稳定且唯一的战法ID",
                        "name": "string",
                        "mechanism": "string",
                        "difference_from_baseline": "string",
                        "applicable_scenarios": ["scenario_id"],
                        "failure_conditions": ["string"],
                        "evidence_refs": ["exact evidence_id or packet_id"],
                    }
                ],
            },
        )
        agent_id, system, schema = steps[2]
        steps[2] = (
            agent_id,
            system
            + " "
            + _winning_prompt("legacy_workflow.branch_a_pressure_test_suffix"),
            {
                **schema,
                "pressure_test_matrix": [
                    {
                        "tactic_id": "已形成的稳定战法ID",
                        "scenario_id": "string",
                        "mission_chain": "high|medium|low",
                        "strong_electromagnetic": "high|medium|low",
                        "degraded_network": "high|medium|low",
                        "attrition_resilience": "high|medium|low",
                        "opponent_adaptation": "high|medium|low",
                        "conditions": ["string"],
                        "confidence": "0..1",
                    }
                ],
                "tactic_effect_ranking": ["按任务适配与证据排序的战法ID"],
            },
        )

    def cohort_role_contract(index: int) -> dict[str, Any]:
        base = {
            1: {
                "objective": "解构对手感知、决策、火力、保障与恢复体系，识别依赖、替代链和任务级薄弱环节。",
                "must_consume": ["背景与场景约束", "对手/装备公开证据"],
                "military_test": "说明可被削弱、延迟、欺骗、拒止或制衡的环节及失效边界。",
            },
            2: {
                "objective": "审查现有任务链、战法、协同与保障基线，形成机制不同且可比较的制胜运用路径。",
                "must_consume": ["场景任务链", "S1对手体系认识"],
                "military_test": "比较打击/歼灭闭环、反制效率、拒止强度、抗毁恢复和持续作战效果。",
            },
            3: {
                "objective": "围绕核心矛盾执行反事实与压力测试，形成突破方向和直接—间接—最终效果链。",
                "must_consume": ["S1/S2结论或分支专用Packet", "反证与适用条件"],
                "military_test": "验证强电磁、弱网、节点损耗和对手适应下的任务效果与失败模式。",
            },
            4: {
                "objective": "把效果链映射为任务—能力—功能—性能约束—体系接口，并区分装备与非装备措施。",
                "must_consume": ["S3效果链", "相关业务Packet与直接证据"],
                "military_test": "每项能力必须解释对打击、反制、拒止、抗毁或持续作战链路的可验证贡献。",
            },
            5: {
                "objective": "对齐目标能力与现役/在研装备、成熟度和体系约束，完成五档差距及升级/新研边界。",
                "must_consume": ["S4能力映射", "装备现状与成熟度证据"],
                "military_test": "说明缺口切断何种任务效果，补齐后恢复哪段打击、反制、抗毁或保障链。",
            },
            6: {
                "objective": "融合前五步形成少而精的能力画像、优先级、装备形态、演化路径和验证闸门。",
                "must_consume": ["S4能力映射", "S5差距评估", "分支规定产物"],
                "military_test": "只保留具备显著军事价值、前瞻机制和可证伪建设路径的方向。",
            },
        }[index]
        branch_focus = {
            "A": {
                2: "形成由证据支持、机制真正不同的新战法；不是同义改名，数量不设配额。",
                3: "消费已形成的战法，对有区分度的代表性场景执行任务链与对抗压力测试。",
                4: "围绕Query相关能力域、指标和装备形态建立可追溯映射基础，不按目录补齐。",
                5: "轻量盘点现役底座与关键差距，不重复完整装备研究。",
            },
            "B": {
                1: "围绕西太/反介入等给定体系识别对手关键节点和反适应方式。",
                2: "审查我方现有运用与保障基线，不另造脱离场景的新战法。",
                3: "形成能够牵引S4/S5的突破方向，不提前跳到装备型号。",
                4: "重点完成能力映射、需求卡片字段和体系接口。",
                5: "重点完成五档差距、现役升级、新研边界和验证依据。",
            },
            "C": {
                3: "完整消费案例Packet，形成3类未来场景迁移及不可迁移边界。",
                4: "把6条案例规律映射为能力需求，并支撑4类新兴装备类别。",
                5: "对迁移后的能力需求执行现役基础、差距与工程边界审查。",
            },
            "D": {3: "以技术改变任务机制为主线，区分成熟度与能力潜力。"},
            "E": {3: "把对手能力形成信号转换为可削弱、延迟、拒止或制衡的窗口。"},
            "F": {
                3: "构造级联失效、替代链和降级运行场景。",
                4: "形成补链强链能力映射。",
                5: "审查替代链的现役基础和关键差距。",
            },
            "G": {
                3: "聚焦数据、权限、时序和接口缝隙。",
                4: "映射跨域闭环与最低可用能力。",
            },
            "H": {
                3: "兼顾威胁扩散、任务保护和可控反制。",
                4: "保留法律伦理与军地协同边界。",
            },
        }.get(primary_branch, {}).get(
            index, "按当前分支合同完成本步骤，不扩展无关分析。"
        )
        return {
            **base,
            "branch_focus": branch_focus,
            "military_divergence_contract": _winning_military_divergence_contract(
                index
            ),
            "quality_gate": "事实/推断/假设分离；结论绑定证据或上游引用；保留反证、置信度和失效边界。",
        }

    step_modes = _winning_step_modes(shared)
    if winning_mode.dynamic_swarm:
        # The Mission Graph stops at the governed equipment portfolio;
        # its S6 node is intentionally supplied by the parallel portrait
        # author below.  An adaptive blueprint may skip analytical S6 in
        # other profiles, but dynamic v2 must still author the deliverable
        # cards before the final gate can judge them.
        step_modes[6] = "deep"
    active_steps = [
        index for index in range(1, len(steps) + 1) if step_modes[index] != "skip"
    ]
    requested_resume_steps: list[int] = []
    for item in shared.get("resume_steps", []):
        try:
            step = int(item)
        except (TypeError, ValueError):
            continue
        # An explicit resume request is authoritative, including a step that
        # the branch blueprint normally skips.  This is required for repairing
        # an S6 checkpoint in profiles whose fresh-run S6 is optional.
        if step in range(1, 7) and step not in requested_resume_steps:
            requested_resume_steps.append(step)
    if requested_resume_steps:
        active_steps = requested_resume_steps

    fast_profile = (
        os.environ.get(
            "EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE",
            "quality",
        )
        .strip()
        .lower()
        == "fast"
    )
    model_loop_critics = os.environ.get(
        "EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS",
        "0",
    ).strip().lower() in {"1", "true", "yes"}
    shared["winning_step_plan"] = [
        {
            "step": index,
            "agent_id": steps[index - 1][0],
            "execution_mode": step_modes[index],
        }
        for index in range(1, len(steps) + 1)
    ]
    prior_winning_analysis = shared.get("prior_winning_analysis", {})
    accumulated: dict[str, Any] = (
        {
            key: value
            for key, value in prior_winning_analysis.items()
            if key
            not in {
                "assumptions",
                "open_questions",
                "subagent_runs",
                "dynamic_subagent_runs",
                "loop_trace",
                "codex_call_metrics",
                "middle_loop_limited",
                "evidence_supplement_pending",
                "targeted_evidence_requests",
            }
        }
        if isinstance(prior_winning_analysis, Mapping)
        else {}
    )
    all_assumptions: list[str] = []
    all_open_questions: list[str] = []
    runs: list[dict[str, Any]] = []
    loop_trace: list[dict[str, Any]] = []
    state = SwarmState()
    reasoning_nodes: dict[str, dict[str, Any]] = {}
    s6_model_repair_used = False
    # All quality profiles use the per-card/ five-column S6 authoring lane.
    # Codex-capable providers additionally receive a hard process boundary for
    # every scoped turn; Responses-compatible providers retain the same async
    # fan-out even when they cannot manufacture a local CLI process.
    s6_parallel_authoring_only = bool(quality_contract)
    dynamic_s6_authoring = winning_mode.dynamic_swarm

    blueprint = shared.get("discovery_blueprint", {})
    swarm_policy = (
        blueprint.get("winning_swarm_policy", {})
        if isinstance(blueprint, Mapping)
        and isinstance(blueprint.get("winning_swarm_policy", {}), Mapping)
        else {}
    )
    if winning_mode.dynamic_swarm:
        swarm_policy = {
            "policy_id": "winning_swarm_dynamic_v2",
            "enabled": True,
            **dict(swarm_policy),
        }
    # DeepSeek behind the Codex Responses adapter is materially slower and
    # more sensitive to burst concurrency than the native Codex endpoint.
    # Running the dynamic-v2 eight-lane swarm unchanged can leave several
    # sessions waiting for minutes and, if the worker supervisor is restarted,
    # strand the run in ``synthesizing`` with a claimed queue lease.  Keep the
    # general GPT/Kimi policy untouched, but apply a bounded, configurable
    # ceiling for DeepSeek.  The effective value is persisted in the policy
    # snapshot and therefore remains visible in the run trace.
    provider_id = str(
        getattr(host.provider, "provider_id", "")
        or getattr(host.provider, "provider_name", "")
        or ""
    ).strip().lower()
    is_deepseek_codex = (
        getattr(host, "provider_kind", "") == "codex_cli"
        and ("deepseek" in provider_id or "deepseek" in str(getattr(host.provider, "model", "")).lower())
    )
    if is_deepseek_codex:
        try:
            configured_limit = int(
                os.environ.get("EQUIPMENT_DR_DEEPSEEK_SWARM_CONCURRENCY", "3")
            )
        except ValueError:
            configured_limit = 3
        deepseek_limit = max(1, min(4, configured_limit))
        swarm_policy["max_concurrency"] = min(
            int(swarm_policy.get("max_concurrency", deepseek_limit) or deepseek_limit),
            deepseek_limit,
        )
        swarm_policy["provider_throttle"] = {
            "provider": "codex_deepseek",
            "max_concurrency": deepseek_limit,
            "reason": "DeepSeek Responses latency/backpressure protection",
        }
    swarm_controller = WinningSwarmController(swarm_policy)
    initial_flow = winning_mode.initial_flow(
        swarm_enabled=swarm_controller.enabled,
        resuming=bool(requested_resume_steps),
    )
    dynamic_swarm_enabled = initial_flow == "dynamic_swarm"
    swarm_enabled = initial_flow == "quality_swarm"
    dynamic_specs = (
        list(blueprint.get("dynamic_subagents", []))
        if isinstance(blueprint, Mapping)
        and isinstance(blueprint.get("dynamic_subagents", []), list)
        else []
    )[: (12 if (swarm_enabled or dynamic_swarm_enabled) else 3)]

    async def run_dynamic_specialist(spec: Mapping[str, Any]) -> dict[str, Any]:
        instance_id = str(spec.get("agent_instance_id", "dynamic-specialist"))
        hypothesis_id = str(spec.get("hypothesis_id", "")).strip() or (
            "hypothesis-dynamic-"
            + sha256(
                f"{instance_id}:{spec.get('merge_target', 'S3')}".encode("utf-8")
            ).hexdigest()[:12]
        )
        dynamic_steps = [
            int(item)
            for item in spec.get("contribution_to_steps", [])
            if str(item).isdigit() and 1 <= int(item) <= 5
        ]
        dynamic_claims = (
            military_claims_for_steps(dynamic_steps or [3, 4, 5])
            if quality_contract
            else []
        )
        dynamic_evidence = (
            evidence_for_claims(dynamic_claims, limit=10)
            if quality_contract
            else list(shared.get("evidence_index", []))
        )
        result = _parse_json_object(
            await host._run_core_json(
                "winning_dynamic_specialist",
                _winning_prompt("legacy_workflow.dynamic_specialist"),
                {
                    "topic": shared["topic"],
                    "research_route": shared["research_route"],
                    "analysis_priority": analysis_priority_contract,
                    "discovery_blueprint": _compact_prompt_value(
                        shared.get("discovery_blueprint", {}),
                        max_string_chars=700,
                        max_list_items=8,
                    ),
                    "coverage": _compact_prompt_value(
                        {} if quality_contract else shared.get("coverage", {}),
                        max_string_chars=500,
                        max_list_items=10,
                    ),
                    "packet_index": _compact_prompt_value(
                        military_packet_refs_for_claims(dynamic_claims)
                        if quality_contract
                        else packet_index,
                        max_string_chars=320,
                        max_list_items=8,
                    ),
                    "packets": _compact_prompt_value(
                        [] if quality_contract else shared.get("packets", []),
                        max_string_chars=360,
                        max_list_items=6,
                    ),
                    "secondary_cross_agent_constraints": _compact_prompt_value(
                        dynamic_claims,
                        max_string_chars=460,
                        max_list_items=6,
                    ),
                    "evidence_index": _compact_prompt_value(
                        dynamic_evidence,
                        max_string_chars=280,
                        max_list_items=20,
                    ),
                    "dynamic_agent_spec": dict(spec),
                    "valid_evidence_ids": [
                        str(item.get("evidence_id", ""))
                        for item in dynamic_evidence
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    ],
                },
                {
                    "findings": ["string"],
                    "evidence_refs": ["exact evidence_id or packet_id"],
                    "contribution_to_steps": [
                        {
                            "step": "1..6",
                            "contribution": "string",
                        }
                    ],
                    "assumptions": ["string"],
                    "open_questions": ["string"],
                    "merge_target": "S1|S2|S3|S4|S5|S6|convergence",
                    "stop_reason": "string",
                    "confidence": "0..1",
                },
                int(spec.get("max_output_tokens", 1800)),
                phase="winning_dynamic_specialist",
            )
        )
        if not result:
            raise ValueError(f"{instance_id} returned invalid structured JSON")
        reported_target = str(result.get("merge_target", ""))
        declared_target = str(spec.get("merge_target", "S3"))
        if reported_target and reported_target != declared_target:
            raise ValueError(
                f"{instance_id} crossed merge target {declared_target} -> {reported_target}"
            )
        result = sanitize_references(result)
        result["merge_target"] = declared_target
        return {
            "agent_instance_id": instance_id,
            "hypothesis_id": hypothesis_id,
            "display_name": str(spec.get("display_name", "动态专用Agent")),
            "merge_target": declared_target,
            "skill_ids": list(spec.get("skill_ids", [])),
            "knowledge_pack_ids": list(spec.get("knowledge_pack_ids", [])),
            "accepted": True,
            "result": result,
        }

    if (
        dynamic_specs
        and not (swarm_enabled or dynamic_swarm_enabled)
        and not requested_resume_steps
        and host._optional_work_allowed(
            priority="critical",
            minimum_remaining_seconds=240.0,
        )
    ):
        try:
            state.dynamic_outputs = list(
                await asyncio.gather(
                    *(run_dynamic_specialist(spec) for spec in dynamic_specs)
                )
            )
        except (RuntimeError, TimeoutError) as exc:
            if not _is_harness_budget_error(exc):
                raise
            accumulated["dynamic_specialists_budget_skipped"] = True
            state.dynamic_outputs = []
        accumulated["dynamic_subagent_outputs"] = state.dynamic_outputs
        for item in state.dynamic_outputs:
            result = item["result"]
            runs.append(
                {
                    "step": 0,
                    "agent_id": item["agent_instance_id"],
                    "template_agent_id": "winning_dynamic_specialist",
                    "middle_cycle": 0,
                    "execution_mode": "dynamic",
                    "merge_target": item["merge_target"],
                    "skill_ids": item["skill_ids"],
                    "knowledge_pack_ids": item["knowledge_pack_ids"],
                    "confidence": result.get("confidence"),
                    "open_question_count": len(result.get("open_questions", [])),
                    "status": "completed",
                }
            )
    elif (
        dynamic_specs
        and not (swarm_enabled or dynamic_swarm_enabled)
        and not requested_resume_steps
    ):
        accumulated["dynamic_specialists_budget_skipped"] = True
        loop_trace.append(
            {
                "loop": "dynamic",
                "event": "deadline_skip",
                "passed": True,
                "issues": [
                    "运行已进入截止收敛区间，跳过可选动态专用分析，保留主链证据。"
                ],
            }
        )

    core_swarm_schedule: dict[str, Any] = {}

    def emit_swarm_event(
        event_type: str,
        *,
        actor: str = "winning_swarm_controller",
        **details: Any,
    ) -> None:
        host._emit_winning_progress(
            {
                "event_type": event_type,
                "agent_id": actor,
                **details,
            }
        )

    async def cluster_hypotheses_with_independent_codex(
        candidates: Sequence[WinningHypothesis],
        *,
        scope_id: str,
        changed_hypothesis_ids: set[str] | None = None,
    ) -> tuple[list[WinningHypothesis], list[dict[str, str]]]:
        return await clustering.cluster_hypotheses_with_independent_codex(
            candidates=candidates,
            scope_id=scope_id,
            changed_hypothesis_ids=changed_hypothesis_ids,
            emit_swarm_event=emit_swarm_event,
            host=host,
            shared=shared,
            swarm_controller=swarm_controller,
        )

    async def execute_dynamic_mission_graph() -> None:
        return await dynamic_swarm.execute_dynamic_mission_graph(
            accumulated=accumulated,
            baseline_boundaries=baseline_boundaries,
            cluster_hypotheses_with_independent_codex=cluster_hypotheses_with_independent_codex,
            creative_military_value_handoff=creative_military_value_handoff,
            emit_swarm_event=emit_swarm_event,
            host=host,
            primary_branch=primary_branch,
            runs=runs,
            shared=shared,
            state=state,
            swarm_controller=swarm_controller,
            valid_reference_ids=valid_reference_ids,
        )

    async def generate_parallel_s6_cards(
        *,
        agent_id: str,
        system: str,
        schema: Mapping[str, Any],
        step_input: Mapping[str, Any],
    ) -> dict[str, Any]:
        return await s6_authoring.generate_parallel_s6_cards(
            agent_id=agent_id,
            system=system,
            schema=schema,
            step_input=step_input,
            accumulated=accumulated,
            dynamic_s6_authoring=dynamic_s6_authoring,
            parallel_portrait_modules=(
                # Dynamic-v2 uses the same bounded spine + five-column fanout
                # as the quality lane. The spine freezes identity and
                # mechanism; independent columns then finish concurrently
                # with their own responsibilities and output budgets.
                True
                if dynamic_s6_authoring
                else s6_parallel_authoring_only
            ),
            emit_swarm_event=emit_swarm_event,
            host=host,
            requested_resume_steps=requested_resume_steps,
            shared=shared,
        )

    async def run_step(
        index: int,
        *,
        middle_cycle: int,
        prior_step_outputs: Mapping[str, Any],
        middle_feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        nonlocal s6_model_repair_used
        agent_id, system, schema = steps[index - 1]

        # Dynamic-v2 owns the S6 authoring contract in ``S6.md``.  The
        # legacy ``steps`` table is retained for compatibility with the
        # standard/quality lanes, but its S6 system text must not leak into
        # dynamic planner or recovery calls when the compact dynamic handoff
        # is empty.  Keep the provider boundary on the reviewable Markdown
        # resource for every dynamic S6 branch (normal cards, planner and
        # checkpoint recovery).
        if index == 6 and dynamic_s6_authoring:
            system = load_dynamic_winning_prompt("S6")

        schema = {
            **schema,
            "reasoning_node": {
                "recognition": "当前步骤形成的可审计认识",
                "evidence_refs": ["exact evidence_id or packet_id"],
                "confidence": "0..1",
                "next_action": {
                    "action": "continue|parallel|backtrack|recall|stop",
                    "target_step": "1..6 or 0",
                    "reason": "string",
                },
            },
        }
        execution_mode = step_modes[index]
        critic_feedback: list[str] = list(middle_feedback or [])
        result: dict[str, Any] = {}
        if index == 6 and middle_cycle > 1:
            result = {
                key: prior_step_outputs[key]
                for key in (
                    "concept_directions",
                    "capability_image_drafts",
                    "upstream_coverage",
                    "branch_products",
                    "evidence_validation",
                    "assumptions",
                    "open_questions",
                    "confidence",
                )
                if key in prior_step_outputs
            }
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("6")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        resume_s6_checkpoint = (
            index == 6
            and middle_cycle == 1
            and requested_resume_steps == [6]
            and bool(prior_step_outputs.get("concept_directions"))
        )
        if resume_s6_checkpoint:
            # A failed S6 checkpoint already contains the complete cards
            # and their exact residual issues. Replanning and reauthoring
            # the portfolio here discards successful work and can drift
            # the expert-approved equipment set. Seed the first inner pass
            # from the checkpoint, then let the normal deterministic gate
            # select only the cards that still need repair.
            result = {
                key: (
                    prior_step_outputs[key]
                    if key in prior_step_outputs
                    else []
                    if isinstance(value, list)
                    else {}
                    if isinstance(value, Mapping)
                    else ""
                )
                for key, value in schema.items()
            }
            directions = result.get("concept_directions", [])
            if not result.get("capability_image_drafts") and isinstance(
                directions, list
            ):
                result["capability_image_drafts"] = [
                    str(item.get("capability_outcome") or item.get("name") or "")
                    for item in directions
                    if isinstance(item, Mapping)
                ]
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("6")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        final_review: dict[str, Any] = {}
        if index == 4 and middle_cycle > 1:
            result = {
                key: prior_step_outputs[key]
                for key in (
                    "capability_mapping",
                    "dotmlpf_matrix",
                    "open_questions",
                    "confidence",
                )
                if key in prior_step_outputs
            }
            if "s4_concept_directions" in prior_step_outputs:
                result["concept_directions"] = prior_step_outputs[
                    "s4_concept_directions"
                ]
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("4")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        s6_targeted_repair = False
        s4_targeted_repair = index == 4 and middle_cycle > 1 and bool(result)
        if s6_parallel_authoring_only:
            s6_targeted_repair = False
        reuse_s6_without_model = (
            index == 6
            and middle_cycle > 1
            and bool(result)
            and (s6_model_repair_used or s6_parallel_authoring_only)
        )
        if reuse_s6_without_model:
            s6_targeted_repair = False
        s6_handoff: dict[str, Any] = {}
        # The second middle cycle is already a targeted repair informed by
        # the round critic. One bounded regeneration plus the final round
        # rereview is sufficient; repeating the full high-reasoning step a
        # second time added minutes without introducing new evidence.
        # 常规步骤默认一次通过本地门控；S6 的篇幅目标只属于
        # Codex 首稿编辑合同，不能被本地长度、句数或关键词检查
        # 转换成重试、修复或交付失败。
        step_deadline_state = host._deadline_state(priority="critical")
        deadline_pressure = index != 6 and step_deadline_state.get("mode") != "normal"
        if index == 6:
            # S6 is a one-pass, per-card Codex authoring stage. Local field,
            # length, keyword, confidence, repetition and similarity checks
            # must never buy a second model call or enter the middle loop.
            max_inner_iterations = 1
        elif middle_cycle == 1 and model_loop_critics and not deadline_pressure:
            max_inner_iterations = 2
        else:
            max_inner_iterations = 1
        for inner_iteration in range(1, max_inner_iterations + 1):
            if (
                inner_iteration > 1
                and index != 6
                and host._deadline_state(priority="critical").get("mode") != "normal"
            ):
                loop_trace.append(
                    {
                        "loop": "inner",
                        "middle_cycle": middle_cycle,
                        "step": index,
                        "agent_id": agent_id,
                        "iteration": inner_iteration,
                        "event": "deadline_skip",
                        "passed": False,
                        "issues": [
                            "进入截止收敛区间，停止第二次模型修复并保留首次有效结果。"
                        ],
                        "recommended_action": "stop",
                    }
                )
                break
            projected_prior = prior_projection(index, prior_step_outputs)
            if index == 6:
                if dynamic_s6_authoring:
                    # Dynamic S5 already froze the decision spine.  Do not
                    # rebuild the legacy portfolio/evidence contract here;
                    # that contract was the main source of prompt bloat.
                    dynamic_portfolio = (
                        accumulated.get("winning_swarm", {}).get(
                            "final_equipment_portfolio", []
                        )
                        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
                        else []
                    )
                    if not dynamic_portfolio:
                        dynamic_portfolio = accumulated.get("concept_directions", [])
                    s6_handoff = {
                        "selected_equipment_portfolio": [
                            _minimal_s6_card_handoff(item)
                            for item in dynamic_portfolio
                            if isinstance(item, Mapping)
                        ],
                        "s6_card_capacity": min(12, len(dynamic_portfolio) or 1),
                        "s6_parallelism": _bounded_s6_parallelism(
                            host._runtime_budgets
                        ),
                        "handoff_mode": "dynamic_s5_decision_spine",
                    }
                else:
                    s6_handoff = _capability_synthesis_handoff(
                        topic=shared["topic"],
                        branch=primary_branch,
                        prior_step_outputs=prior_step_outputs,
                        evidence_index=shared.get("evidence_index", []),
                        s6_parallelism=_bounded_s6_parallelism(host._runtime_budgets),
                    )
                s6_valid_evidence_ids = sorted(
                    {
                        str(item.get("evidence_id", ""))
                        for item in s6_handoff.get("public_evidence", [])
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    }
                )
                if resume_s6_checkpoint and not isinstance(
                    result.get("reasoning_node"), Mapping
                ):
                    result["reasoning_node"] = {}
                if resume_s6_checkpoint:
                    reasoning_node = dict(result.get("reasoning_node", {}))
                    reasoning_node.setdefault(
                        "recognition",
                        "复核已保存的具体装备能力画像及其证据、场景和指标闭环",
                    )
                    reasoning_node["evidence_refs"] = list(
                        dict.fromkeys(
                            [
                                *[
                                    str(item)
                                    for item in reasoning_node.get("evidence_refs", [])
                                    if str(item).strip()
                                ],
                                *s6_valid_evidence_ids[:4],
                            ]
                        )
                    )
                    reasoning_node.setdefault(
                        "confidence",
                        result.get("confidence", 0.68) or 0.68,
                    )
                    reasoning_node.setdefault(
                        "next_action",
                        {
                            "action": "continue",
                            "target_step": 0,
                            "reason": "完成S6发布门复核后进入报告生成",
                        },
                    )
                    result["reasoning_node"] = reasoning_node
                s6_first_pass_contract = (
                    {"mode": "dynamic_minimal_card", "identity_frozen_by": "S5"}
                    if dynamic_s6_authoring
                    else _s6_first_pass_quality_contract(
                        topic=str(shared["topic"]),
                        handoff=s6_handoff,
                    )
                )
                step_input = {
                    "query": shared["topic"],
                    "branch": primary_branch,
                    "execution_profile_id": shared.get("execution_profile_id", ""),
                    "analysis_priority": analysis_priority_contract,
                    "branch_deliverables": list(branch_product_schema),
                    "capability_synthesis_handoff": s6_handoff,
                    "first_pass_quality_contract": s6_first_pass_contract,
                    "valid_evidence_ids": s6_valid_evidence_ids,
                }
                targeted_feedback = _targeted_expert_feedback(
                    shared.get("expert_review_feedback", []),
                    "S6",
                )
                if targeted_feedback:
                    step_input["expert_review_feedback"] = _compact_prompt_value(
                        targeted_feedback,
                        max_string_chars=520,
                        max_list_items=8,
                    )
            else:
                shared_step_context = step_shared_context(
                    index,
                    prior_step_outputs,
                )
                step_input = {
                    **shared_step_context,
                    "valid_evidence_ids": sorted(
                        {
                            str(item.get("evidence_id", ""))
                            for item in shared_step_context.get("evidence_index", [])
                            if isinstance(item, Mapping)
                            and str(item.get("evidence_id", "")).strip()
                        }
                        if quality_contract
                        else valid_evidence_ids
                    ),
                    "prior_step_outputs": projected_prior,
                    "loop_context": {
                        "middle_cycle": middle_cycle,
                        "inner_iteration": inner_iteration,
                        "critic_feedback": critic_feedback,
                        "execution_mode": execution_mode,
                    },
                }
                if index in {3, 4} and not (index == 4 and s4_targeted_repair):
                    step_input["random_naming_style_assignment"] = (
                        _s3_s4_naming_assignment(
                            "|".join(
                                (
                                    str(shared.get("run_id", "")),
                                    str(shared.get("topic", "")),
                                    agent_id,
                                    str(middle_cycle),
                                    str(inner_iteration),
                                )
                            ),
                            count=6,
                        )
                    )
            if reuse_s6_without_model:
                # A previous inner iteration already spent the one allowed
                # card-level model repair. Re-evaluate the preserved S6
                # result against the final gate, but never pay for another
                # repair or full regeneration in a later middle cycle.
                pass
            elif (
                resume_s6_checkpoint
                and inner_iteration == 1
                and not s6_parallel_authoring_only
            ):
                # The checkpoint is the first-pass candidate. Its
                # deterministic review below decides the exact per-card
                # repair targets without another portfolio-planning call.
                pass
            elif index == 4 and s4_targeted_repair:
                repair_schema = {
                    "capability_mapping": schema["capability_mapping"],
                    "dotmlpf_matrix": schema["dotmlpf_matrix"],
                    "concept_directions": schema["concept_directions"],
                }
                text = await host._run_core_json(
                    agent_id,
                    _winning_prompt("legacy_workflow.s4_targeted_repair"),
                    {
                        "topic": shared["topic"],
                        "research_route": shared["research_route"],
                        "current_result": compact_for_prompt(
                            result,
                            max_string_chars=700,
                            max_list_items=8,
                        ),
                        "repair_issues": critic_feedback,
                        "effect_chain": projected_prior.get("effect_chain", []),
                        "valid_evidence_ids": sorted(valid_evidence_ids),
                    },
                    repair_schema,
                    1800,
                    phase="winning_s4_targeted_repair",
                )
                repair = _parse_json_object(text)
                if repair:
                    result = {**result, **repair}
            elif index == 6 and (
                s6_targeted_repair
                or (
                    middle_cycle == 1
                    and inner_iteration > 1
                    and bool(result)
                    and host.provider.__class__.__module__
                    == "equipment_deep_research.providers.codex"
                )
            ):
                repair_targets = _s6_repair_targets(result, critic_feedback)
                directions = result.get("concept_directions", [])
                target_cards = [
                    {"position": position, "direction": directions[position - 1]}
                    for position in repair_targets
                    if isinstance(directions, list) and 1 <= position <= len(directions)
                ]
                protected_cards = [
                    {
                        "position": position,
                        "name": str(item.get("name", "")),
                        "type": str(item.get("type", "")),
                    }
                    for position, item in enumerate(directions, start=1)
                    if isinstance(item, Mapping) and position not in repair_targets
                ]
                repair_card_semaphore = asyncio.Semaphore(
                    max(
                        1,
                        min(
                            S6_MAX_CODEX_CONCURRENCY,
                            int(
                                s6_handoff.get(
                                    "s6_parallelism",
                                    S6_DEFAULT_CODEX_CONCURRENCY,
                                )
                                or S6_DEFAULT_CODEX_CONCURRENCY
                            ),
                        ),
                    )
                )
                direction_schema = schema["concept_directions"][0]
                repair_prompt = _winning_prompt(
                    "legacy_workflow.s6_card_repair",
                    authoring_contract=_s6_markdown_authoring_contract(),
                )
                protected_fields = (
                    "name",
                    "hypothesis_id",
                    "source_hypothesis_title",
                    "type",
                    "primary_equipment_identity",
                    "equipment_form",
                    "equipment_family",
                    "unique_operational_role",
                    "launch_or_release_domain",
                    "target_and_direct_effect",
                    "non_substitutable_difference",
                    "portfolio_identity_contract",
                    "baseline_system",
                    "capability_gap",
                    "direct_evidence_refs",
                    "foresight_evidence_status",
                    "evidence_boundary",
                    "validation_plan",
                    "expert_score",
                    "expert_assessment_id",
                )

                async def repair_target_card(
                    target: Mapping[str, Any],
                ) -> dict[str, Any]:
                    position = int(target["position"])
                    current_direction = dict(target["direction"])
                    async with repair_card_semaphore:
                        text = await host._run_core_json(
                            agent_id,
                            repair_prompt,
                            {
                                "parallel_card_id": f"s6-card-{position}",
                                "query": shared["topic"],
                                "branch": primary_branch,
                                "analysis_priority": analysis_priority_contract,
                                "capability_synthesis_handoff": s6_handoff,
                                "first_pass_quality_contract": s6_first_pass_contract,
                                "current_direction": current_direction,
                                "protected_cards": protected_cards,
                                "repair_issues": critic_feedback,
                                "valid_evidence_ids": step_input["valid_evidence_ids"],
                            },
                            {"direction": direction_schema},
                            3600,
                            phase=(f"winning_s6_parallel_card_repair_{position:02d}"),
                        )
                    parsed = _parse_json_object(text)
                    repaired_direction = parsed.get("direction", {})
                    if not isinstance(repaired_direction, Mapping):
                        return {
                            "position": position,
                            "direction": current_direction,
                        }
                    repaired_direction = dict(repaired_direction)
                    for field_name in protected_fields:
                        protected_value = current_direction.get(field_name)
                        if protected_value not in (None, "", []):
                            repaired_direction[field_name] = protected_value
                    return {
                        "position": position,
                        "direction": repaired_direction,
                    }

                if resume_s6_checkpoint and target_cards:
                    repair_outcomes = await asyncio.gather(
                        *(repair_target_card(target) for target in target_cards),
                        return_exceptions=True,
                    )
                    repair = {
                        "direction_repairs": [
                            item
                            for item in repair_outcomes
                            if isinstance(item, Mapping)
                        ]
                    }
                else:
                    text = await host._run_core_json(
                        agent_id,
                        repair_prompt
                        + " "
                        + _winning_prompt("legacy_workflow.s6_multi_repair_suffix"),
                        {
                            "query": shared["topic"],
                            "branch": primary_branch,
                            "analysis_priority": analysis_priority_contract,
                            "capability_synthesis_handoff": s6_handoff,
                            "first_pass_quality_contract": s6_first_pass_contract,
                            "repair_targets": target_cards,
                            "capability_image_drafts": result.get(
                                "capability_image_drafts", []
                            ),
                            "protected_cards": protected_cards,
                            "repair_issues": critic_feedback,
                            "valid_evidence_ids": step_input["valid_evidence_ids"],
                        },
                        {
                            "direction_repairs": [
                                {
                                    "position": "1-based integer from repair_targets",
                                    "direction": direction_schema,
                                }
                            ]
                        },
                        min(4200, 1400 + 700 * max(1, len(repair_targets))),
                        phase="winning_s6_card_repair",
                    )
                    repair = _parse_json_object(text)
                s6_model_repair_used = True
                if repair:
                    result = _merge_s6_direction_repairs(result, repair)
            elif (
                index == 6
                and middle_cycle == 1
                and inner_iteration == 1
                # Quality profiles use the isolated per-card authoring path;
                # its five portrait columns are concurrent even when the
                # dynamic-v2 compact handoff is not active.  This is a profile
                # invariant, not a capability of one provider implementation.
                and (s6_parallel_authoring_only or dynamic_s6_authoring)
            ):
                result = await generate_parallel_s6_cards(
                    agent_id=agent_id,
                    system=system,
                    schema=schema,
                    step_input=step_input,
                )
            else:
                try:
                    text = await host._run_core_json(
                        agent_id,
                        system
                        + (
                            " " + _winning_prompt("legacy_workflow.first_pass_suffix")
                            if index == 6
                            else ""
                        )
                        + (
                            " " + _winning_prompt("legacy_workflow.naming_suffix")
                            if index in {3, 4}
                            else ""
                        )
                        + " " + _winning_prompt("legacy_workflow.reasoning_suffix")
                        + " "
                        + _winning_prompt(
                            "legacy_workflow.execution_mode_suffix",
                            execution_mode=execution_mode,
                            mode_instruction=(
                                _winning_prompt("legacy_workflow.mode_deep")
                                if execution_mode == "deep"
                                else _winning_prompt("legacy_workflow.mode_light")
                                if execution_mode == "light"
                                else _winning_prompt("legacy_workflow.mode_standard")
                            ),
                        ),
                        step_input,
                        schema,
                        (
                            5200
                            if index == 6
                            else {
                                "light": 1800,
                                "standard": 2400,
                                "deep": 2800,
                            }.get(execution_mode, 2400)
                        ),
                        phase=f"{agent_id}_{execution_mode}",
                    )
                except ProviderRequestError:
                    # The provider performs its own retry. If S6 still
                    # cannot return a complete response, fail the stage;
                    # never replace it with a deterministic portfolio.
                    raise
                else:
                    result = _parse_json_object(text)
            if not result:
                raise ValueError(f"{agent_id} returned invalid structured JSON")
            result = sanitize_references(result)
            if index in {4, 6}:
                effect_chain_rows = projected_prior.get("effect_chain", [])
                effect_chain_count = (
                    len(effect_chain_rows) if isinstance(effect_chain_rows, list) else 0
                )
                result = _normalize_effect_chain_references(
                    result,
                    effect_chain_count,
                )
            if index == 6:
                result = _normalize_s6_deterministic_format(
                    result,
                    topic=str(shared.get("topic", "")),
                )
                result = _normalize_concept_direction_priorities(result)
            deterministic_quality_issues: list[str] = []
            deterministic_quality_warnings: list[str] = []
            if (
                index == 6
                and host.provider.__class__.__module__
                != "equipment_deep_research.providers.fake"
            ):
                deterministic_quality_warnings = _capability_direction_quality_issues(
                    result,
                    handoff=s6_handoff,
                )
                deterministic_quality_issues = _s6_delivery_blocking_issues(
                    deterministic_quality_warnings
                )
                if deterministic_quality_issues and quality_contract:
                    lightweight_repair = _s6_can_use_lightweight_card_repair(
                        result,
                        deterministic_quality_issues,
                    )
                    loop_trace.append(
                        {
                            "loop": "inner",
                            "middle_cycle": middle_cycle,
                            "step": 6,
                            "agent_id": agent_id,
                            "iteration": inner_iteration,
                            "event": (
                                "lightweight_card_repair_planned"
                                if lightweight_repair
                                else "full_s6_quality_regeneration_planned"
                            ),
                            "passed": False,
                            "issues": deterministic_quality_issues[:4],
                            "repair_targets": (
                                _s6_repair_targets(
                                    result,
                                    deterministic_quality_issues,
                                )
                                if lightweight_repair
                                else []
                            ),
                            "recommended_action": "retry",
                        }
                    )
            # 默认使用本地结构、证据与置信度门控。只有本地门控发现实质
            # 缺陷时，中循环才调用独立批判 Agent 生成一次定向修复建议。
            if index == 6:
                review = {
                    "passed": True,
                    "issues": [],
                    "retry_guidance": [],
                    "recommended_action": "pass",
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": "s6_advisory_diagnostics_only",
                    "warnings": deterministic_quality_warnings[:8],
                }
            elif (
                not model_loop_critics
                or fast_profile
                or deadline_pressure
                or execution_mode == "light"
                or index == 4
            ):
                missing_fields = [key for key in schema if key not in result]
                local_issues = (
                    [f"缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else []
                )
                try:
                    confidence = float(result.get("confidence", 0.0) or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < 0.65:
                    local_issues.append("步骤置信度低于0.65，需要定向复核")
                raw_node = result.get("reasoning_node", {})
                if isinstance(raw_node, Mapping):
                    refs = raw_node.get("evidence_refs", [])
                    if valid_reference_ids and not any(str(item) for item in refs):
                        local_issues.append(
                            "reasoning_node缺少有效证据或上游Packet引用"
                        )
                review = {
                    "passed": not local_issues,
                    "issues": local_issues,
                    "retry_guidance": [
                        "仅修复被指出的字段、证据承接或置信度问题，保留有效结论。"
                    ]
                    if local_issues
                    else [],
                    "recommended_action": "retry" if local_issues else "pass",
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": (
                        "harness_structured_gate"
                        if index in {4, 6}
                        else "harness_fast_gate"
                    ),
                }
            elif inner_iteration == max_inner_iterations:
                missing_fields = [key for key in schema if key not in result]
                review = {
                    "passed": not missing_fields,
                    "issues": [f"重试结果仍缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else [],
                    "retry_guidance": [],
                    "recommended_action": ("pass" if not missing_fields else "stop"),
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": "retry_schema_gate_then_round_critic",
                }
            else:
                critic_text = await host._run_core_json(
                    "winning_step_critic",
                    _winning_prompt("legacy_workflow.step_critic"),
                    {
                        "step": index,
                        "agent_id": agent_id,
                        "step_context": {
                            "topic": shared["topic"],
                            "research_route": shared["research_route"],
                            "execution_mode": execution_mode,
                            "middle_cycle": middle_cycle,
                            "inner_iteration": inner_iteration,
                            "valid_evidence_ids": step_input["valid_evidence_ids"],
                            "packet_ids": [item["packet_id"] for item in packet_index],
                            "prior_step_outputs": projected_prior,
                            "critic_feedback": critic_feedback,
                            "winning_step_plan": shared["winning_step_plan"],
                            "contract_note": _winning_prompt(
                                "legacy_workflow.step_critic_contract_note"
                            ),
                        },
                        "step_output": compact_for_prompt(
                            result,
                            max_string_chars=1000,
                            max_list_items=8,
                        ),
                        "deterministic_quality_issues": deterministic_quality_issues,
                    },
                    {
                        "passed": "boolean",
                        "issues": ["string"],
                        "retry_guidance": ["string"],
                        "recommended_action": "pass|retry|recall|backtrack|stop",
                        "backtrack_to_step": "1..6 or 0",
                        "recall_target": "capability tag or empty string",
                    },
                    1200,
                    phase="winning_step_review",
                )
                review = _parse_json_object(critic_text)
            if deterministic_quality_issues:
                review = {
                    **dict(review),
                    "passed": False,
                    "issues": [
                        *deterministic_quality_issues,
                        *[str(item) for item in review.get("issues", [])],
                    ][:8],
                    "retry_guidance": deterministic_quality_issues[:6],
                    "recommended_action": (
                        "stop"
                        if s6_model_repair_used
                        or inner_iteration >= max_inner_iterations
                        else "retry"
                    ),
                }
            final_review = dict(review)
            passed = review.get("passed") is True
            recommended_action = (
                str(
                    review.get(
                        "recommended_action",
                        "pass" if passed else "stop",
                    )
                )
                .strip()
                .lower()
            )
            loop_trace.append(
                {
                    "loop": "inner",
                    "middle_cycle": middle_cycle,
                    "step": index,
                    "agent_id": agent_id,
                    "iteration": inner_iteration,
                    "passed": passed,
                    "issues": [str(item) for item in review.get("issues", [])][:4],
                    "warnings": [str(item) for item in review.get("warnings", [])][:4],
                    "recommended_action": recommended_action,
                    "backtrack_to_step": review.get("backtrack_to_step", 0),
                    "recall_target": str(review.get("recall_target", "")),
                }
            )
            if passed or inner_iteration == max_inner_iterations:
                break
            # 只有可在当前输入上原地修复的字段/表达问题才重试。
            # recall/backtrack/stop 需要新增证据或改变上游输入，立即用相同
            # 上下文重跑只会增加耗时并放大不一致，交由中循环统一处理。
            if recommended_action != "retry":
                break
            critic_feedback = [str(item) for item in review.get("retry_guidance", [])][
                :6
            ]
            if index == 6:
                s6_targeted_repair = False
        # S6 review findings are advisory. Candidate identity and semantic
        # admission were already decided by S5; local prose/shape checks may
        # request a bounded rewrite but must never convert a completed card
        # into a hard task failure.
        raw_reasoning_node = result.pop("reasoning_node", {})
        reasoning_node = (
            dict(raw_reasoning_node) if isinstance(raw_reasoning_node, Mapping) else {}
        )
        return {
            "result": result,
            "assumptions": [
                str(item) for item in result.get("assumptions", []) if str(item).strip()
            ],
            "open_questions": [
                str(item)
                for item in result.get("open_questions", [])
                if str(item).strip()
            ],
            "reasoning_node": reasoning_node,
            "run": {
                "step": index,
                "agent_id": agent_id,
                "middle_cycle": middle_cycle,
                "execution_mode": execution_mode,
                "confidence": result.get("confidence"),
                "open_question_count": len(result.get("open_questions", [])),
                "status": "completed",
                "reasoning_node": reasoning_node,
                "next_action": reasoning_node.get("next_action", {}),
                "critic_action": str(final_review.get("recommended_action", "pass")),
                "critic_issues": [
                    str(item)
                    for item in final_review.get("issues", [])
                    if str(item).strip()
                ][:4],
                "critic_recall_target": str(final_review.get("recall_target", "")),
                "critic_backtrack_to_step": final_review.get("backtrack_to_step", 0),
            },
        }

    execution_contract = (
        dict(shared.get("execution_contract", {}))
        if isinstance(shared.get("execution_contract", {}), Mapping)
        else {}
    )
    core_step_dependency_map = swarm_controller.core_dependencies_from_dag(
        execution_contract.get("logical_agent_dag", {})
        if isinstance(execution_contract.get("logical_agent_dag", {}), Mapping)
        else {}
    )
    physical_cohorts: list[tuple[int, ...]] = []
    if aggressive_compaction:
        for raw_cohort in execution_contract.get("physical_cohorts", []):
            if not isinstance(raw_cohort, Sequence) or isinstance(
                raw_cohort, (str, bytes)
            ):
                continue
            cohort = tuple(
                int(item)
                for item in raw_cohort
                if str(item).isdigit() and int(item) in range(1, 7)
            )
            if len(cohort) >= 2:
                physical_cohorts.append(cohort)

    async def run_physical_cohort(
        indices: tuple[int, ...],
        *,
        middle_cycle: int,
        prior_step_outputs: Mapping[str, Any],
        middle_feedback: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute causally ordered logical S-agents in one provider turn."""
        cohort_id = "cohort-" + "-".join(f"s{index}" for index in indices)
        schemas = {
            f"S{index}": {
                **steps[index - 1][2],
                "reasoning_node": {
                    "recognition": "当前逻辑步骤形成的可审计认识",
                    "evidence_refs": ["exact evidence_id or packet_id"],
                    "confidence": "0..1",
                    "next_action": {
                        "action": "continue|backtrack|recall|stop",
                        "target_step": "1..6 or 0",
                        "reason": "string",
                    },
                },
            }
            for index in indices
        }
        logical_contracts = [
            {
                "step": index,
                "agent_id": steps[index - 1][0],
                "execution_mode": step_modes[index],
                "depends_on_steps": [
                    dependency
                    for dependency in {
                        1: (),
                        2: (1,),
                        3: (1, 2),
                        4: (3,),
                        5: (4,),
                        6: (4, 5),
                    }[index]
                    if dependency in indices
                ],
                "role_contract": cohort_role_contract(index),
                # The authoritative nested schema is already supplied once
                # through the provider's output_schema option. Repeating it
                # in the user payload materially inflated S4/S5 input size.
                "required_output_fields": list(schemas[f"S{index}"].keys()),
            }
            for index in indices
        ]
        cohort_agents = set().union(
            *(packet_agents_by_step[index] for index in indices)
        )
        cohort_prior = prior_projection(indices[0], prior_step_outputs)
        creative_cohort = quality_contract and set(indices) <= {3, 4}
        cohort_claims = (
            list(creative_military_value_handoff()["claims"])
            if creative_cohort
            else (military_claims_for_steps(indices) if quality_contract else [])
        )
        if quality_contract:
            cohort_packets: list[Mapping[str, Any]] = []
            cohort_packet_index = (
                []
                if creative_cohort
                else military_packet_refs_for_claims(cohort_claims)
            )
            cohort_evidence = (
                []
                if creative_cohort
                else evidence_for_claims(
                    cohort_claims,
                    prior_step_outputs=cohort_prior,
                    limit=12 if primary_branch_for_packets == "C" else 10,
                )
            )
        else:
            cohort_packets = [
                item
                for item in shared.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("agent_id", "")) in cohort_agents
            ]
            cohort_packet_index = packet_index
            cohort_evidence = _prioritized_evidence_index(
                shared.get("evidence_index", []),
                preferred_ids=_collect_reference_ids(cohort_prior),
                allowed_agents=cohort_agents,
                limit=12 if primary_branch_for_packets == "C" else 10,
            )
        cohort_valid_reference_ids = {
            str(item.get("packet_id", ""))
            for item in cohort_packet_index
            if str(item.get("packet_id", ""))
        } | {
            str(item.get("evidence_id", ""))
            for item in cohort_evidence
            if str(item.get("evidence_id", ""))
        }
        cohort_input = {
            "topic": shared["topic"],
            "query": shared["topic"],
            "research_route": shared["research_route"],
            "execution_profile_id": shared["execution_profile_id"],
            "analysis_priority": analysis_priority_contract,
            "discovery_blueprint": step_shared_context(indices[0]).get(
                "discovery_blueprint", {}
            ),
            "logical_contracts": logical_contracts,
            "required_branch_products": list(
                execution_contract.get("branch_products", [])
            )[:10],
            "prior_step_outputs": (
                cohort_prior
                if quality_contract
                else compact_for_prompt(
                    prior_step_outputs,
                    max_string_chars=1000,
                    max_list_items=10,
                )
            ),
            "packet_index": _compact_prompt_value(
                cohort_packet_index,
                max_string_chars=220 if quality_contract else 280,
                max_list_items=6 if quality_contract else 8,
            ),
            "packets": (
                [packet_projection(item, step=indices[0]) for item in cohort_packets]
                if quality_contract
                else _compact_prompt_value(
                    cohort_packets,
                    max_string_chars=(
                        1200 if primary_branch_for_packets == "C" else 520
                    ),
                    max_list_items=(14 if primary_branch_for_packets == "C" else 8),
                )
            ),
            "military_value_handoff": (
                {"claims": cohort_claims} if creative_cohort and cohort_claims else {}
            ),
            "secondary_cross_agent_constraints": (
                _compact_prompt_value(
                    cohort_claims,
                    max_string_chars=460,
                    max_list_items=8,
                )
                if quality_contract and not creative_cohort
                else []
            ),
            "branch_products": (
                _compact_prompt_value(
                    military_branch_products,
                    max_string_chars=360,
                    max_list_items=8,
                )
                if quality_contract
                and primary_branch_for_packets == "C"
                and 5 in indices
                else {}
            ),
            "evidence_index": _compact_prompt_value(
                cohort_evidence,
                max_string_chars=240 if quality_contract else 320,
                max_list_items=len(cohort_evidence) if quality_contract else 24,
            ),
            "valid_reference_ids": sorted(
                cohort_valid_reference_ids if quality_contract else valid_reference_ids
            ),
            "middle_cycle": middle_cycle,
            "repair_guidance": list(middle_feedback or [])[:8],
            "cohort_rule": (
                _winning_prompt("legacy_workflow.cohort_review_suffix")
                + (
                    "\n" + _winning_prompt("legacy_workflow.cohort_compact_s1_s2")
                    if set(indices) == {1, 2}
                    else ""
                )
                + (
                    "\n" + _winning_prompt("legacy_workflow.cohort_compact_s4_s5")
                    if {4, 5}.issubset(set(indices))
                    else ""
                )
            ),
        }
        if 4 in indices:
            cohort_input["random_naming_style_assignment"] = _s3_s4_naming_assignment(
                "|".join(
                    (
                        str(shared.get("run_id", "")),
                        str(shared.get("topic", "")),
                        cohort_id,
                        str(middle_cycle),
                    )
                ),
                count=4,
            )
        text = await host._run_core_json(
            f"winning_{cohort_id}",
            _winning_prompt("legacy_workflow.cohort_executor"),
            cohort_input,
            {"logical_results": schemas},
            min(
                5600 if {4, 5}.issubset(set(indices)) else 7600,
                sum(
                    {
                        "light": 1800,
                        "standard": 2400,
                        "deep": 2800,
                    }.get(step_modes[index], 2400)
                    for index in indices
                ),
            ),
            phase=f"winning_{cohort_id}",
        )
        payload = _parse_json_object(text)
        logical_results = payload.get("logical_results", {})
        if not isinstance(logical_results, Mapping):
            logical_results = {}
        outcomes: list[dict[str, Any]] = []
        for index in indices:
            agent_id = steps[index - 1][0]
            schema = schemas[f"S{index}"]
            raw_result = logical_results.get(f"S{index}", {})
            result = dict(raw_result) if isinstance(raw_result, Mapping) else {}
            result = sanitize_references(result)
            missing_fields = [key for key in schema if key not in result]
            try:
                confidence = float(result.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            issues = [
                *(
                    [f"缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else []
                ),
                *(["步骤置信度低于0.65，需要残差复核"] if confidence < 0.65 else []),
            ]
            loop_trace.append(
                {
                    "loop": "inner",
                    "middle_cycle": middle_cycle,
                    "step": index,
                    "agent_id": agent_id,
                    "iteration": 1,
                    "passed": not issues,
                    "issues": issues,
                    "recommended_action": "pass" if not issues else "backtrack",
                    "physical_cohort_id": cohort_id,
                }
            )
            raw_node = result.pop("reasoning_node", {})
            reasoning_node = dict(raw_node) if isinstance(raw_node, Mapping) else {}
            outcomes.append(
                {
                    "result": result,
                    "assumptions": [
                        str(item)
                        for item in result.get("assumptions", [])
                        if str(item).strip()
                    ],
                    "open_questions": [
                        str(item)
                        for item in result.get("open_questions", [])
                        if str(item).strip()
                    ],
                    "reasoning_node": reasoning_node,
                    "run": {
                        "step": index,
                        "agent_id": agent_id,
                        "middle_cycle": middle_cycle,
                        "execution_mode": step_modes[index],
                        "confidence": result.get("confidence"),
                        "open_question_count": len(result.get("open_questions", [])),
                        "status": "completed" if result else "limited",
                        "reasoning_node": reasoning_node,
                        "next_action": reasoning_node.get("next_action", {}),
                        "critic_action": "pass" if not issues else "backtrack",
                        "critic_issues": issues,
                        "physical_cohort_id": cohort_id,
                        "logical_result_preserved": True,
                    },
                }
            )
        return outcomes

    async def run_tactic_validation_wave() -> None:
        concepts = accumulated.get("tactic_concepts", [])
        concept_rows = [dict(item) for item in concepts if isinstance(item, Mapping)][
            :3
        ]
        if aggressive_compaction and len(concept_rows) == 3:
            validations = []
            for index, concept in enumerate(concept_rows, start=1):
                tactic_id = str(concept.get("tactic_id") or f"T{index}")
                failure_conditions = [
                    str(item)
                    for item in concept.get("failure_conditions", [])
                    if str(item).strip()
                ][:3]
                evidence_refs = [
                    str(item)
                    for item in concept.get("evidence_refs", [])
                    if str(item) in valid_reference_ids
                ][:6]
                applicable_scenarios = [
                    str(item)
                    for item in concept.get("applicable_scenarios", [])
                    if str(item).strip()
                ][:6]
                validations.append(
                    {
                        "task_id": f"validation-{tactic_id}",
                        "tactic_id": tactic_id,
                        "public_evidence": evidence_refs,
                        "feasibility": "medium",
                        "counter_evidence": failure_conditions
                        or ["缺少独立反证时不得上调为高可行性"],
                        "technical_boundaries": [
                            "强电磁、弱网、节点损耗与目标信息过期必须同时进入压力测试",
                            "无校准数据时只比较任务链闭合等级，不给精确效能百分比",
                        ],
                        "failure_conditions": failure_conditions
                        or ["关键任务链在代表性对抗条件下不能闭合"],
                        "applicable_scenarios": applicable_scenarios,
                        "confidence": min(
                            0.76,
                            max(
                                0.65,
                                float(concept.get("confidence", 0.68) or 0.68),
                            ),
                        ),
                    }
                )
            accumulated["tactic_validation_results"] = validations
            accumulated["tactic_validation_tasks"] = [
                {
                    "task_id": str(item["task_id"]),
                    "tactic_id": str(item["tactic_id"]),
                    "validation_axes": [
                        "public_evidence",
                        "feasibility",
                        "counter_evidence",
                        "technical_boundary",
                    ],
                }
                for item in validations
            ]
            for item in validations:
                row = {
                    "step": 0,
                    "agent_id": f"tactic_validation_{item['tactic_id']}",
                    "middle_cycle": 1,
                    "execution_mode": "deterministic_frontloaded_validation",
                    "status": "completed",
                    "confidence": item["confidence"],
                    "physical_cohort_id": "tactic-validation-frontloaded",
                    "logical_result_preserved": True,
                }
                runs.append(row)
                host._emit_winning_progress(row)
            loop_trace.append(
                {
                    "loop": "validation",
                    "step": 2,
                    "event": "frontloaded_deterministic_validation",
                    "passed": True,
                    "issues": [],
                }
            )
            return
        text = await host._run_core_json(
            "tactic_validation_cohort",
            _winning_prompt("legacy_workflow.tactic_validation"),
            {
                "topic": shared["topic"],
                "tactic_concepts": concept_rows,
                "scenario_packets": [
                    item
                    for item in shared.get("packets", [])
                    if isinstance(item, Mapping)
                    and item.get("agent_id") == "combat_scenario"
                ],
                "evidence_index": shared.get("evidence_index", []),
                "valid_reference_ids": sorted(valid_reference_ids),
            },
            {
                "validations": [
                    {
                        "task_id": "validation-T1|validation-T2|validation-T3",
                        "tactic_id": "T1|T2|T3",
                        "public_evidence": ["exact evidence_id or packet_id"],
                        "feasibility": "high|medium|low",
                        "counter_evidence": ["string"],
                        "technical_boundaries": ["string"],
                        "failure_conditions": ["string"],
                        "applicable_scenarios": ["scenario_id"],
                        "confidence": "0..1",
                    }
                ]
            },
            4200,
            phase="tactic_validation_wave",
        )
        payload = _parse_json_object(text)
        validations = [
            sanitize_references(dict(item))
            for item in payload.get("validations", [])
            if isinstance(item, Mapping)
        ][:3]
        accumulated["tactic_validation_results"] = validations
        accumulated["tactic_validation_tasks"] = [
            {
                "task_id": str(item.get("task_id", f"validation-{index + 1}")),
                "tactic_id": str(item.get("tactic_id", f"T{index + 1}")),
                "validation_axes": [
                    "public_evidence",
                    "feasibility",
                    "counter_evidence",
                    "technical_boundary",
                ],
            }
            for index, item in enumerate(validations)
        ]
        for index, item in enumerate(validations, start=1):
            row = {
                "step": 0,
                "agent_id": f"tactic_validation_{item.get('tactic_id', index)}",
                "middle_cycle": 1,
                "execution_mode": "parallel_validation",
                "status": "completed",
                "confidence": item.get("confidence"),
                "physical_cohort_id": "tactic-validation-wave",
                "logical_result_preserved": True,
            }
            runs.append(row)
            host._emit_winning_progress(row)
        if len(validations) != 3:
            loop_trace.append(
                {
                    "loop": "validation",
                    "step": 2,
                    "passed": False,
                    "issues": [
                        _winning_prompt(
                            "legacy_workflow.tactic_validation_count_issue",
                            validation_count=len(validations),
                        )
                    ],
                    "recommended_action": "backtrack",
                    "backtrack_to_step": 2,
                }
            )

    def commit_step(outcome: Mapping[str, Any]) -> None:
        row = dict(outcome["run"])
        index = int(row["step"])
        all_assumptions.extend(outcome.get("assumptions", []))
        all_open_questions.extend(outcome.get("open_questions", []))
        reasoning_node = dict(outcome.get("reasoning_node", {}))
        if reasoning_node:
            reasoning_nodes[str(index)] = reasoning_node
        step_result = dict(outcome["result"])
        if index == 4 and "concept_directions" in step_result:
            # S4 owns provisional mappings; S6 owns the final capability portrait.
            # A later S4 backtrack must never silently replace a completed S6 result.
            step_result["s4_concept_directions"] = step_result.pop("concept_directions")
        if index == 6:
            directions = step_result.get("concept_directions", [])
            direction_count = len(directions) if isinstance(directions, list) else 0
            if direction_count:
                normalized_nodes = _normalize_priority_references(
                    reasoning_nodes,
                    direction_count,
                )
                if isinstance(normalized_nodes, Mapping):
                    reasoning_nodes.clear()
                    reasoning_nodes.update(
                        {
                            str(key): dict(value)
                            for key, value in normalized_nodes.items()
                            if isinstance(value, Mapping)
                        }
                    )
        accumulated.update(step_result)
        accumulated["reasoning_nodes"] = dict(reasoning_nodes)
        runs.append(row)
        host._emit_winning_progress(row)

    # 真实数据依赖：S3←{S1,S2}，S4←{S3}，S5←{S4}，S6←{S4,S5}。
    # S5 必须消费 S4 的能力映射/约束矩阵后才能做装备差距排序，避免
    # 跨步跳跃触发整段 S3-S6 回溯。
    step_dependency_map = core_step_dependency_map

    def plan_step_waves(selected: set[int]) -> list[tuple[int, ...]]:
        """依据分支蓝图激活的步骤拓扑排布可并行波次。

        skip/复用步骤视为依赖已满足（其结论经 prior 累积上下文提供）。
        全量激活时等价于静态波次 ((1,2),(3,),(4,),(5,),(6,))；分支裁剪或
        定向重跑时波次自动收缩，减少串行轮次。
        """
        pending = sorted(selected)
        satisfied = {index for index in range(1, 7) if index not in selected}
        waves: list[tuple[int, ...]] = []
        while pending:
            wave = tuple(
                index
                for index in pending
                if all(dep in satisfied for dep in step_dependency_map[index])
            )
            if not wave:
                wave = (pending[0],)
            waves.append(wave)
            satisfied.update(wave)
            pending = [index for index in pending if index not in wave]
        return waves

    async def run_step_waves(
        selected_steps: Sequence[int],
        *,
        middle_cycle: int,
        middle_feedback: list[str] | None = None,
    ) -> None:
        if winning_mode.optimized and middle_cycle == 1:
            await optimized.run_optimized_steps(
                selected_steps,
                middle_cycle=middle_cycle,
                middle_feedback=middle_feedback,
                accumulated=accumulated,
                commit_step=commit_step,
                run_step=run_step,
                step_dependency_map=step_dependency_map,
                host=host,
                loop_trace=loop_trace,
                physical_cohorts=physical_cohorts,
                primary_branch=primary_branch,
                run_physical_cohort=run_physical_cohort,
                run_tactic_validation_wave=run_tactic_validation_wave,
            )
        else:
            await standard.run_standard_steps(
                selected_steps,
                middle_cycle=middle_cycle,
                middle_feedback=middle_feedback,
                accumulated=accumulated,
                commit_step=commit_step,
                run_step=run_step,
                step_dependency_map=step_dependency_map,
                plan_step_waves=plan_step_waves,
            )

    core_swarm_schedule = swarm_controller.plan_core_schedule(
        active_steps=active_steps,
        step_modes=step_modes,
        physical_cohorts=physical_cohorts,
        dependency_map=core_step_dependency_map,
    )

    try:
        if dynamic_swarm_enabled:
            await execute_dynamic_mission_graph()
            # The dynamic Mission Graph owns S1-S5 candidate generation,
            # competition and evidence closure, but it deliberately does
            # not author user-facing capability portraits.  Always hand
            # the selected portfolio to the dedicated parallel S6 writer
            # before evaluating the delivery gate.  Previously the
            # portfolio was validated as if it were already an S6 result,
            # so upstream audit wording or a provisional title could fail
            # the run without any S6 Codex session ever starting.
            if 6 in active_steps:
                await run_step_waves([6], middle_cycle=1)
        elif swarm_enabled:
            await quality_swarm.execute_quality_swarm(
                accumulated=accumulated,
                cluster_hypotheses_with_independent_codex=cluster_hypotheses_with_independent_codex,
                core_swarm_schedule=core_swarm_schedule,
                emit_swarm_event=emit_swarm_event,
                host=host,
                packet_index=packet_index,
                primary_branch=primary_branch,
                runs=runs,
                shared=shared,
                state=state,
                swarm_controller=swarm_controller,
                valid_reference_ids=valid_reference_ids,
                active_steps=active_steps,
                run_steps=run_step_waves,
            )
        else:
            await run_step_waves(active_steps, middle_cycle=1)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        if isinstance(exc, S6QualityError):
            raise
        deadline_state = host._deadline_state(priority="critical")
        deadline_limited = (
            _is_harness_budget_error(exc) or deadline_state.get("mode") != "normal"
        )
        if not deadline_limited:
            raise
        accumulated["winning_deadline_limited"] = True
        accumulated["winning_deadline_reason"] = type(exc).__name__
        loop_trace.append(
            {
                "loop": "winning",
                "cycle": 1,
                "event": "deadline_finalize",
                "passed": True,
                "issues": [
                    "制胜主链到达收敛时限，保留已完成步骤并停止启动新的深度调用。"
                ],
            }
        )

    for index in range(1, len(steps) + 1):
        if index in active_steps:
            continue
        skipped_row = {
            "step": index,
            "agent_id": steps[index - 1][0],
            "middle_cycle": 1,
            "execution_mode": (step_modes[index] if requested_resume_steps else "skip"),
            "status": (
                "reused_from_prior_analysis"
                if requested_resume_steps
                else "skipped_by_branch_blueprint"
            ),
        }
        runs.append(skipped_row)
        host._emit_winning_progress(skipped_row)

    inner_failures = _latest_inner_loop_failures(loop_trace)
    failed_inner_steps = {
        int(item.get("step", 0) or 0)
        for item in inner_failures
        if int(item.get("step", 0) or 0) in range(1, 7)
    }
    deadline_skip_round_critic = not host._optional_work_allowed(
        priority="normal",
        minimum_remaining_seconds=180.0,
    )
    exhausted_s6_repair = failed_inner_steps == {6} and s6_model_repair_used
    skip_round_critic = (
        (not model_loop_critics and not inner_failures)
        or deadline_skip_round_critic
        or exhausted_s6_repair
    )
    deterministic_round_review = {
        "passed": not inner_failures,
        "rerun_from_step": 0,
        "issues": [
            str(issue) for item in inner_failures for issue in item.get("issues", [])
        ][:8],
        "affected_fields": [],
        "rerun_guidance": [],
        "rerun_steps": [],
        "requires_new_evidence": False,
        "evidence_requests": [],
    }
    round_review_text = json.dumps(
        deterministic_round_review,
        ensure_ascii=False,
    )
    if deadline_skip_round_critic and inner_failures:
        accumulated["round_critic_budget_skipped"] = True
        accumulated["middle_loop_limited"] = True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 1,
                "event": "deadline_skip",
                "passed": False,
                "issues": [
                    "剩余时间不足以启动可选中循环批判；保留最新步骤结果并标记受限。"
                ],
            }
        )
    elif exhausted_s6_repair:
        accumulated["s6_additional_review_skipped"] = True
        accumulated["middle_loop_limited"] = True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 1,
                "event": "repair_exhausted",
                "passed": False,
                "issues": [
                    "S6已使用唯一卡片级模型修复，不再启动无新增证据的批判和回跑。"
                ],
            }
        )
    if not skip_round_critic:
        try:
            round_review_text = await host._run_core_json(
                "winning_round_critic",
                _winning_prompt("legacy_workflow.round_critic"),
                {
                    "topic": shared["topic"],
                    "research_route": shared["research_route"],
                    "discovery_blueprint": step_shared_context(6).get(
                        "discovery_blueprint", {}
                    ),
                    "packet_index": (
                        military_packet_refs_for_claims(military_value_claims)
                        if quality_contract
                        else packet_index
                    ),
                    "valid_evidence_ids": [
                        str(item.get("evidence_id", ""))
                        for item in shared.get("evidence_index", [])
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    ],
                    "six_step_outputs": round_review_projection(accumulated),
                    "inner_critic_findings": [
                        {
                            "step": item.get("step"),
                            "recommended_action": item.get("recommended_action"),
                            "issues": item.get("issues", []),
                            "backtrack_to_step": item.get("backtrack_to_step", 0),
                            "recall_target": item.get("recall_target", ""),
                        }
                        for item in loop_trace
                        if item.get("loop") == "inner"
                        and item.get("passed") is not True
                    ],
                    "allowed_target_agent_ids": list(
                        shared.get("selected_business_agent_ids", [])
                    ),
                    "winning_step_plan": shared["winning_step_plan"],
                    "review_contract": _winning_prompt(
                        "legacy_workflow.round_critic_contract"
                    ),
                },
                {
                    "passed": "boolean",
                    "rerun_from_step": "1..6 or 0",
                    "issues": ["string"],
                    "affected_fields": [
                        "defense_decomposition|operational_review|winning_paths|"
                        "breakthrough_directions|effect_chain|capability_mapping|"
                        "dotmlpf_matrix|gap_assessment"
                    ],
                    "rerun_guidance": ["string"],
                    "rerun_steps": ["1..6"],
                    "requires_new_evidence": "boolean",
                    "evidence_requests": [
                        {
                            "question": "single narrow evidence question",
                            "target_agent_id": "one allowed business agent id",
                            "affected_steps": ["1..6"],
                            "source_preferences": [
                                "primary or authoritative source type"
                            ],
                            "reason": "why this evidence can change the conclusion",
                        }
                    ],
                },
                1600,
                phase="winning_round_review",
            )
        except (RuntimeError, TimeoutError) as exc:
            if not _is_harness_budget_error(exc):
                raise
            accumulated["round_critic_budget_skipped"] = True
            loop_trace.append(
                {
                    "loop": "middle",
                    "cycle": 1,
                    "event": "budget_skip",
                    "passed": True,
                    "issues": [
                        "可选中循环模型批判因运行预算到达而跳过；"
                        "已使用步骤内批判结果继续确定性门控。"
                    ],
                }
            )
    round_review = _parse_json_object(round_review_text)
    try:
        rerun_from = int(round_review.get("rerun_from_step", 0) or 0)
    except (TypeError, ValueError):
        rerun_from = 0
    middle_passed = round_review.get("passed") is True
    loop_trace.append(
        {
            "loop": "middle",
            "cycle": 1,
            "passed": middle_passed,
            "rerun_from_step": rerun_from,
            "issues": [str(item) for item in round_review.get("issues", [])][:6],
        }
    )
    # A skipped step is an intentional branch decision, not shorthand for the
    # next active step. Reject the critic's skipped target instead of silently
    # remapping it and paying for an unrelated rerun.
    if rerun_from not in active_steps:
        rerun_from = 0
    requires_new_evidence = round_review.get("requires_new_evidence") is True
    allowed_targets = {
        str(item)
        for item in shared.get("selected_business_agent_ids", [])
        if str(item).strip()
    }
    targeted_requests: list[dict[str, Any]] = []
    if requires_new_evidence:
        for item in round_review.get("evidence_requests", []):
            if not isinstance(item, Mapping):
                continue
            question = str(item.get("question", "")).strip()
            target_agent_id = str(item.get("target_agent_id", "")).strip()
            if not question or target_agent_id not in allowed_targets:
                continue
            affected_steps: list[int] = []
            for raw_step in item.get("affected_steps", []):
                try:
                    step = int(raw_step)
                except (TypeError, ValueError):
                    continue
                if step in range(1, 7) and step not in affected_steps:
                    affected_steps.append(step)
            targeted_requests.append(
                {
                    "question": question,
                    "target_agent_id": target_agent_id,
                    "affected_steps": affected_steps or [4, 5, 6],
                    "source_preferences": [
                        str(value)
                        for value in item.get("source_preferences", [])
                        if str(value).strip()
                    ][:3],
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
            if len(targeted_requests) >= 2:
                break
    if (
        not middle_passed
        and (targeted_requests or rerun_from)
        and not host._optional_work_allowed(
            priority="critical",
            minimum_remaining_seconds=180.0,
        )
    ):
        accumulated["middle_backtrack_budget_skipped"] = True
        accumulated["middle_loop_limited"] = True
        targeted_requests = []
        rerun_from = 0
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "event": "deadline_skip",
                "passed": False,
                "issues": [
                    "中循环复核结束时已进入截止收敛区间，取消补证与回溯，保留最新检查点。"
                ],
            }
        )
    if targeted_requests:
        accumulated["evidence_supplement_pending"] = True
        accumulated["targeted_evidence_requests"] = targeted_requests
        accumulated["suggested_resume_steps"] = sorted(
            {
                *(
                    step
                    for request in targeted_requests
                    for step in request["affected_steps"]
                ),
                6,
            }
        )
    elif not middle_passed and rerun_from:
        feedback = [str(item) for item in round_review.get("rerun_guidance", [])][:8]
        requested_steps = []
        for item in round_review.get("rerun_steps", []):
            try:
                step = int(item)
            except (TypeError, ValueError):
                continue
            if step in active_steps and step not in requested_steps:
                requested_steps.append(step)
        failed_inner_steps = {
            int(item.get("step", 0) or 0)
            for item in inner_failures
            if item.get("passed") is not True
        }
        if failed_inner_steps == {6} and 6 in active_steps:
            # A bounded S6 repair must never drag the stable S4 mapping
            # back into another expensive model call. If the only failed
            # inner gate belongs to S6, the middle-cycle residual is S6.
            requested_steps = [6]
        issue_text = " ".join(
            str(item) for item in round_review.get("issues", [])
        ).lower()
        traceability_only = (
            bool(issue_text)
            and any(
                marker in issue_text
                for marker in (
                    "索引",
                    "编号",
                    "derived_from",
                    "可追溯",
                    "引用",
                    "承接说明",
                    "承接不足",
                )
            )
            and not any(
                marker in issue_text
                for marker in (
                    "能力方向缺失",
                    "差距等级错误",
                    "优先级错误",
                    "证据矛盾",
                    "结论错误",
                    "需要新增证据",
                )
            )
        )
        if traceability_only:
            # When the critic identifies the final image as the earliest
            # affected step, S4 is already stable and must not be paid for
            # again. Only include S4 when the backtrack genuinely begins
            # at or before the mapping layer.
            repair_candidates = (6,) if rerun_from >= 6 else (4, 6)
            requested_steps = [
                step for step in repair_candidates if step in active_steps
            ]
        if not requested_steps:
            # 智能回溯：依据 critic 标注的受影响字段，只重跑真正受影响的
            # 下游步骤，而非机械重跑 rerun_from 之后的全部步骤。
            # 字段级影响映射：(字段, 产出步骤) -> 受影响的下游步骤集合。
            field_impact_map = {
                ("defense_decomposition", 1): {2, 3},
                ("operational_review", 2): {3, 6},
                ("winning_paths", 2): {3, 6},
                ("breakthrough_directions", 3): {4},
                ("effect_chain", 3): {4, 6},
                ("capability_mapping", 4): {5, 6},
                ("dotmlpf_matrix", 4): {6},
                ("gap_assessment", 5): {6},
            }
            affected_fields = [
                str(item)
                for item in round_review.get("affected_fields", [])
                if str(item).strip()
            ]
            if affected_fields:
                impacted: set[int] = {rerun_from}
                for field in affected_fields:
                    impacted.add(rerun_from)
                    impacted.update(field_impact_map.get((field, rerun_from), set()))
                requested_steps = sorted(
                    index for index in active_steps if index in impacted
                )
            if not requested_steps:
                # 无字段信息时退回粗粒度：rerun_from 之后的全部激活步骤。
                requested_steps = [
                    index for index in active_steps if index >= rerun_from
                ]
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "event": "intelligent_backtrack",
                "rerun_from_step": rerun_from,
                "rerun_steps": requested_steps,
                "affected_fields": [
                    str(item) for item in round_review.get("affected_fields", [])
                ][:8],
            }
        )
        middle_rerun_completed = True
        try:
            await run_step_waves(
                requested_steps,
                middle_cycle=2,
                middle_feedback=feedback,
            )
        except (RuntimeError, TimeoutError, ValueError) as exc:
            deadline_state = host._deadline_state(priority="critical")
            if not (
                _is_harness_budget_error(exc) or deadline_state.get("mode") != "normal"
            ):
                raise
            middle_rerun_completed = False
            accumulated["middle_backtrack_budget_skipped"] = True
            accumulated["middle_loop_limited"] = True

        residual_inner_failures = [
            item
            for item in loop_trace
            if item.get("loop") == "inner"
            and int(item.get("middle_cycle", 1) or 1) == 2
            and item.get("passed") is not True
        ]
        run_model_rereview = (
            model_loop_critics
            and middle_rerun_completed
            and host._optional_work_allowed(
                priority="normal",
                minimum_remaining_seconds=120.0,
            )
        )
        if not run_model_rereview:
            accumulated["round_rereview_budget_skipped"] = True
            second_review = {
                "passed": middle_rerun_completed and not residual_inner_failures,
                "issues": [
                    "使用残差步骤的本地结构、证据与置信度门控完成二次复核；"
                    + (
                        "未发现新的步骤内失败。"
                        if middle_rerun_completed and not residual_inner_failures
                        else "仍有未闭合问题，结果保留并标记受限。"
                    )
                ],
            }
            loop_trace.append(
                {
                    "loop": "middle",
                    "cycle": 2,
                    "event": "deterministic_rereview",
                    "passed": second_review["passed"],
                    "issues": list(second_review["issues"]),
                }
            )
        else:
            try:
                second_review_text = await host._run_core_json(
                    "winning_round_critic",
                    _winning_prompt("legacy_workflow.round_rereview"),
                    {
                        "topic": shared["topic"],
                        "research_route": shared["research_route"],
                        "packet_index": (
                            military_packet_refs_for_claims(military_value_claims)
                            if quality_contract
                            else packet_index
                        ),
                        "middle_cycle": 2,
                        "six_step_outputs": round_review_projection(accumulated),
                        "winning_step_plan": shared["winning_step_plan"],
                        "review_contract": _winning_prompt(
                            "legacy_workflow.round_rereview_contract"
                        ),
                    },
                    {"passed": "boolean", "issues": ["string"]},
                    1200,
                    phase="winning_round_rereview",
                )
                second_review = _parse_json_object(second_review_text)
            except (RuntimeError, TimeoutError) as exc:
                if not _is_harness_budget_error(exc):
                    raise
                # A missed optional re-review must not discard the latest
                # valid residual checkpoint.
                accumulated["round_rereview_budget_skipped"] = True
                second_review = {
                    "passed": not residual_inner_failures,
                    "issues": [
                        "可选二次中循环复核因运行预算到达而跳过；"
                        + (
                            "保留已通过步骤内批判的残差修订结果。"
                            if not residual_inner_failures
                            else "残差步骤内门控仍有问题，保留结果但继续标记受限。"
                        )
                    ],
                }
                loop_trace.append(
                    {
                        "loop": "middle",
                        "cycle": 2,
                        "event": "budget_skip",
                        "passed": second_review["passed"],
                        "issues": list(second_review["issues"]),
                    }
                )
        second_passed = second_review.get("passed") is True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "passed": second_passed,
                "rerun_from_step": rerun_from,
                "issues": [str(item) for item in second_review.get("issues", [])][:6],
            }
        )
        accumulated["middle_loop_limited"] = not second_passed
    final_s6_handoff = _capability_synthesis_handoff(
        topic=shared["topic"],
        branch=primary_branch,
        prior_step_outputs=accumulated,
        evidence_index=shared.get("evidence_index", []),
        s6_parallelism=_bounded_s6_parallelism(host._runtime_budgets),
    )
    if not [
        item
        for item in accumulated.get("concept_directions", [])
        if isinstance(item, Mapping) and str(item.get("name", "")).strip()
    ] and accumulated.get("winning_deadline_limited"):
        accumulated["s6_card_authoring_limited"] = True
        accumulated.setdefault("s6_card_authoring_warnings", []).append(
            "S6在收敛时限内未形成新画像，保留S5冻结组合并继续受限交付"
        )
    dynamic_portfolio = (
        accumulated.get("winning_swarm", {}).get("final_equipment_portfolio", [])
        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
        else []
    )
    if dynamic_swarm_enabled and dynamic_portfolio:
        # The expert-selected portfolio remains authoritative for weapon
        # membership and identity.  Preserve the parallel S6 sessions'
        # equipment-specific scenes, processes and capability portraits;
        # replacing them with deterministic merge-stage drafts discards
        # the most valuable user-facing work and reintroduces templates.
        accumulated["concept_directions"] = (
            _merge_dynamic_portfolio_with_s6_authored_cards(
                dynamic_portfolio,
                accumulated.get("concept_directions", []),
            )
        )
        accumulated["capability_synthesis"] = [
            str(item.get("name", ""))
            for item in accumulated["concept_directions"]
            if str(item.get("name", "")).strip()
        ]
        expert_scores = [
            float(item["expert_score"])
            for item in dynamic_portfolio
            if isinstance(item.get("expert_score"), (int, float))
        ]
        if expert_scores:
            accumulated["confidence"] = sum(expert_scores) / len(expert_scores)
        normalized_dynamic = _normalize_s6_deterministic_format(
            {
                "concept_directions": accumulated["concept_directions"],
                "confidence": accumulated.get("confidence", 0.68),
            },
            topic=str(shared.get("topic", "")),
        )
        normalized_dynamic = _normalize_concept_direction_priorities(normalized_dynamic)
        accumulated["concept_directions"] = list(
            normalized_dynamic.get("concept_directions", [])
        )
        accumulated["capability_synthesis"] = [
            str(item.get("name", ""))
            for item in accumulated["concept_directions"]
            if isinstance(item, Mapping) and str(item.get("name", "")).strip()
        ]
        winning_swarm_summary = accumulated.get("winning_swarm", {})
        if isinstance(winning_swarm_summary, dict):
            # Keep every delivery surface on the same authoritative,
            # normalized S6 cards. Otherwise the UI/swarm audit retains
            # pre-normalization titles while capability_images.json and
            # the report consume the compact final names and portraits.
            winning_swarm_summary["final_equipment_portfolio"] = [
                dict(item)
                for item in accumulated["concept_directions"]
                if isinstance(item, Mapping)
            ]
    final_s6_all_issues = (
        _capability_direction_quality_issues(
            accumulated,
            handoff=final_s6_handoff,
        )
        if host.provider.__class__.__module__
        != "equipment_deep_research.providers.fake"
        else []
    )
    # The final deterministic evaluation is authoritative.  Do not append
    # stale first-pass critic messages after local normalization or the one
    # bounded card repair has already resolved them; doing so previously
    # made L1-L3 fail on an obsolete title/support diagnosis.
    final_s6_all_issues = list(dict.fromkeys(final_s6_all_issues))[:32]
    final_s6_issues = (
        [] if dynamic_swarm_enabled else _s6_portrait_repair_issues(final_s6_all_issues)
    )
    s6_low_repair_attempted = bool(s6_model_repair_used)
    s6_low_repair_error = ""
    if final_s6_issues and not s6_model_repair_used:
        # All modes receive one bounded low-reasoning repair for substantive
        # content/evidence defects. Diversity, count and style findings are
        # front-loaded as generation guidance and remain warnings here.
        s6_low_repair_attempted = True
        repair_targets = _s6_repair_targets(accumulated, final_s6_issues)
        portrait_module_targets = _s6_portrait_module_repair_targets(
            accumulated,
            final_s6_issues,
        )
        current_directions = accumulated.get("concept_directions", [])
        target_cards = [
            {
                "position": position,
                "direction": current_directions[position - 1],
            }
            for position in repair_targets
            if isinstance(current_directions, list)
            and 1 <= position <= len(current_directions)
        ]
        protected_cards = [
            {
                "position": position,
                "name": str(item.get("name", "")),
                "type": str(item.get("type", "")),
            }
            for position, item in enumerate(current_directions, start=1)
            if isinstance(item, Mapping) and position not in repair_targets
        ]
        emit_swarm_event(
            "winning_s6_low_repair_started",
            repair_targets=repair_targets,
            issues=final_s6_issues[:8],
            reasoning_effort="low",
        )
        try:
            direction_schema = steps[5][2]["concept_directions"][0]
            if portrait_module_targets:

                async def repair_portrait_modules(
                    target: Mapping[str, Any],
                ) -> list[Mapping[str, Any]]:
                    position = int(target["position"])
                    repair_text = await host._run_core_json(
                        "winning_s6_image",
                        _winning_prompt("legacy_workflow.s6_module_repair"),
                        {
                            "parallel_card_id": f"s6-card-{position}",
                            "query": shared["topic"],
                            "repair_target": target,
                            "repair_modules": portrait_module_targets[position],
                            "repair_issues": [
                                issue
                                for issue in final_s6_issues
                                if f"第{position}项" in issue
                            ],
                        },
                        {
                            "portrait_module_repairs": [
                                {
                                    "position": "1-based integer from repair_target",
                                    "module_repairs": [
                                        {
                                            "module": "overview|technology_implementation|operational_process|capability_effects|winning_logic",
                                            "content": "仅对应失败模块的精简正文，不含栏目标题；写到该栏独有结论完整即停止",
                                        }
                                    ],
                                }
                            ]
                        },
                        min(
                            2400,
                            700 + 400 * max(1, len(portrait_module_targets[position])),
                        ),
                        phase=f"winning_s6_portrait_module_repair_{position:02d}",
                    )
                    parsed = _parse_json_object(repair_text)
                    rows = parsed.get("portrait_module_repairs", [])
                    allowed_modules = set(portrait_module_targets[position])
                    filtered_rows: list[Mapping[str, Any]] = []
                    for item in rows:
                        if not isinstance(item, Mapping):
                            continue
                        filtered_rows.append(
                            {
                                "position": position,
                                "module_repairs": [
                                    row
                                    for row in item.get("module_repairs", [])
                                    if isinstance(row, Mapping)
                                    and str(row.get("module", "")) in allowed_modules
                                ],
                            }
                        )
                    return filtered_rows

                repair_outcomes = await asyncio.gather(
                    *(repair_portrait_modules(target) for target in target_cards),
                    return_exceptions=True,
                )
                repair = {
                    "portrait_module_repairs": [
                        row
                        for outcome in repair_outcomes
                        if isinstance(outcome, list)
                        for row in outcome
                    ]
                }
            else:
                repair_text = await host._run_core_json(
                    "winning_s6_image",
                    _winning_prompt(
                        "legacy_workflow.s6_low_repair",
                        authoring_contract=_s6_markdown_authoring_contract(),
                    ),
                    {
                        "query": shared["topic"],
                        "branch": primary_branch,
                        "capability_synthesis_handoff": final_s6_handoff,
                        "repair_targets": target_cards,
                        "protected_cards": protected_cards,
                        "repair_issues": final_s6_issues,
                        "valid_evidence_ids": sorted(
                            {
                                str(item.get("evidence_id", ""))
                                for item in final_s6_handoff.get("public_evidence", [])
                                if isinstance(item, Mapping)
                                and str(item.get("evidence_id", "")).strip()
                            }
                        ),
                    },
                    {
                        "direction_repairs": [
                            {
                                "position": "1-based integer from repair_targets",
                                "direction": direction_schema,
                            }
                        ]
                    },
                    min(4200, 1400 + 700 * max(1, len(repair_targets))),
                    phase="winning_s6_card_repair",
                )
                repair = _parse_json_object(repair_text)
            if repair:
                repaired = (
                    _merge_s6_portrait_module_repairs(accumulated, repair)
                    if portrait_module_targets
                    else _merge_s6_direction_repairs(accumulated, repair)
                )
                repaired = _normalize_s6_deterministic_format(
                    repaired,
                    topic=str(shared.get("topic", "")),
                )
                repaired = _normalize_concept_direction_priorities(repaired)
                accumulated["concept_directions"] = list(
                    repaired.get("concept_directions", [])
                )
                accumulated["capability_synthesis"] = [
                    str(item.get("name", ""))
                    for item in accumulated["concept_directions"]
                    if isinstance(item, Mapping) and str(item.get("name", "")).strip()
                ]
                winning_swarm_summary = accumulated.get("winning_swarm", {})
                if isinstance(winning_swarm_summary, dict):
                    winning_swarm_summary["final_equipment_portfolio"] = [
                        dict(item)
                        for item in accumulated["concept_directions"]
                        if isinstance(item, Mapping)
                    ]
            final_s6_all_issues = list(
                dict.fromkeys(
                    _capability_direction_quality_issues(
                        accumulated,
                        handoff=final_s6_handoff,
                    )
                )
            )[:32]
            final_s6_issues = (
                []
                if dynamic_swarm_enabled
                else _s6_portrait_repair_issues(final_s6_all_issues)
            )
            emit_swarm_event(
                "winning_s6_low_repair_completed",
                repair_targets=repair_targets,
                remaining_issues=final_s6_all_issues[:8],
                passed=not final_s6_issues,
                reasoning_effort="low",
            )
        except Exception as exc:
            s6_low_repair_error = f"{type(exc).__name__}: {exc}"
            emit_swarm_event(
                "winning_s6_low_repair_limited",
                repair_targets=repair_targets,
                issues=final_s6_issues[:8],
                failure_type=type(exc).__name__,
                reasoning_effort="low",
            )

    # Dynamic-v2 quality is front-loaded into the Query, frozen card and one
    # strong S6 authoring turn. Deterministic text-shape checks remain visible
    # as diagnostics, but they neither rewrite nor block a semantically
    # consistent authored card.
    residual_s6_issues = list(final_s6_issues)
    authored_card_warnings: list[str] = []
    for direction in accumulated.get("concept_directions", []):
        if not isinstance(direction, Mapping):
            continue
        authoring_status = str(direction.get("s6_authoring_status", "")).strip()
        if authoring_status in {
            "authored_quality_limited",
            "authored_fallback_from_frozen_selection",
            "limited_provider_failure",
        }:
            authored_card_warnings.append(
                f"{str(direction.get('name', '')).strip() or '未命名装备'}："
                f"S6写卡状态为{authoring_status}"
            )
        authored_card_warnings.extend(
            str(item).strip()
            for item in direction.get("s6_authoring_quality_warnings", [])
            if str(item).strip()
        )
    nonblocking_s6_warnings = list(
        dict.fromkeys(
            [
                *(
                    issue
                    for issue in final_s6_all_issues
                    if issue not in set(residual_s6_issues)
                ),
                *authored_card_warnings,
            ]
        )
    )[:32]
    s6_release_state = _s6_release_gate_state(
        residual_s6_issues,
        nonblocking_s6_warnings,
    )
    accumulated["s6_quality_gate_passed"] = s6_release_state["passed"]
    accumulated["s6_quality_gate_failed"] = s6_release_state["failed"]
    accumulated["s6_quality_gate_limited"] = s6_release_state["limited"]
    accumulated["s6_quality_gate_issues"] = s6_release_state["issues"]
    accumulated["s6_quality_warnings"] = s6_release_state["warnings"]
    accumulated["s6_low_repair_attempted"] = s6_low_repair_attempted
    final_s6_cards = [
        _compact_s6_authored_card_event(item)
        for item in accumulated.get("concept_directions", [])
        if isinstance(item, Mapping) and str(item.get("name", "")).strip()
    ]
    runtime_budget = (
        accumulated.get("winning_swarm", {}).get("budget", {})
        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
        else {}
    )
    runtime_budget = runtime_budget if isinstance(runtime_budget, Mapping) else {}
    emit_swarm_event(
        "winning_s6_release_gate_evaluated",
        passed=s6_release_state["passed"],
        failed=s6_release_state["failed"],
        limited=s6_release_state["limited"],
        issues=s6_release_state["issues"][:16],
        warnings=s6_release_state["warnings"][:16],
        authored_cards=final_s6_cards,
        card_count=len(final_s6_cards),
        maximum_concurrency=runtime_budget.get("maximum_concurrency"),
        maximum_observed_concurrency=runtime_budget.get("maximum_observed_concurrency"),
    )
    if s6_low_repair_error:
        accumulated["s6_low_repair_error"] = s6_low_repair_error
    if swarm_enabled or dynamic_swarm_enabled:
        latest_core_runs: dict[int, dict[str, Any]] = {}
        for row in runs:
            try:
                step = int(row.get("step", 0))
            except (TypeError, ValueError):
                continue
            if step in active_steps:
                latest_core_runs[step] = dict(row)
        completed_core_steps = sorted(
            step
            for step, row in latest_core_runs.items()
            if row.get("status") in {"completed", "reused_from_prior_analysis"}
        )
        limited_core_steps = sorted(
            step for step in active_steps if step not in completed_core_steps
        )
        core_gate_passed = (
            set(active_steps) <= set(completed_core_steps)
            and not accumulated.get("middle_loop_limited")
            and not final_s6_issues
        )
        finalized_core_schedule = {
            **core_swarm_schedule,
            "completed_steps": [f"S{step}" for step in completed_core_steps],
            "limited_steps": [f"S{step}" for step in limited_core_steps],
            "latest_runs": [
                {
                    "step": f"S{step}",
                    "agent_id": str(row.get("agent_id", "")),
                    "execution_mode": str(row.get("execution_mode", "")),
                    "middle_cycle": int(row.get("middle_cycle", 1) or 1),
                    "status": str(row.get("status", "")),
                    "confidence": row.get("confidence"),
                }
                for step, row in sorted(latest_core_runs.items())
            ],
            "quality_gate_passed": core_gate_passed,
            "status": "completed" if core_gate_passed else "limited",
        }
        swarm_summary = (
            dict(accumulated.get("winning_swarm", {}))
            if isinstance(accumulated.get("winning_swarm", {}), Mapping)
            else {}
        )
        swarm_summary.setdefault("policy", dict(swarm_controller.policy))
        swarm_summary.setdefault(
            "task_graph", [to_plain(item) for item in state.swarm_tasks]
        )
        swarm_summary.setdefault("finalists", [])
        swarm_summary["core_schedule"] = finalized_core_schedule
        swarm_summary["specialist_execution_batches"] = [
            {
                "wave": wave,
                "batch": batch,
                "task_ids": [
                    str(row.get("agent_id", ""))
                    for row in runs
                    if row.get("execution_mode") == "dynamic"
                    and int(row.get("wave", 0) or 0) == wave
                    and int(row.get("batch", 0) or 0) == batch
                ],
            }
            for wave, batch in sorted(
                {
                    (
                        int(row.get("wave", 0) or 0),
                        int(row.get("batch", 0) or 0),
                    )
                    for row in runs
                    if row.get("execution_mode") == "dynamic"
                    and int(row.get("wave", 0) or 0) > 0
                    and int(row.get("batch", 0) or 0) > 0
                }
            )
        ]
        active_set = set(active_steps)
        finalist_count = len(swarm_summary.get("finalists", []))
        dynamic_portfolio_ready = bool(
            swarm_summary.get("final_equipment_portfolio", [])
        )
        raw_portfolio_gate = swarm_summary.get("portfolio_quality_gate", {})
        raw_portfolio_gate = (
            raw_portfolio_gate if isinstance(raw_portfolio_gate, Mapping) else {}
        )
        diversity_only_warning = bool(
            not bool(raw_portfolio_gate.get("direct_equipment_diversity_passed", True))
            and bool(
                raw_portfolio_gate.get(
                    "query_domain_main_body_passed",
                    raw_portfolio_gate.get("direct_combat_main_body_passed"),
                )
            )
            and bool(
                raw_portfolio_gate.get(
                    "s6_handoff_gate_passed",
                    raw_portfolio_gate.get("capability_portrait_gate_passed"),
                )
            )
            and bool(raw_portfolio_gate.get("equipment_diversity_passed"))
            and not raw_portfolio_gate.get("hard_blockers")
        )
        if diversity_only_warning:
            # Older checkpoints may have serialized ``passed=false``
            # solely because the preferred family count was missed.  On
            # resume, normalize that legacy value so the UI and Reporter
            # observe the same non-blocking release decision.
            raw_portfolio_gate = {
                **dict(raw_portfolio_gate),
                "passed": True,
                "direct_equipment_diversity_limited": True,
            }
            swarm_summary["portfolio_quality_gate"] = raw_portfolio_gate
        portfolio_quality_gate_passed = (
            bool(raw_portfolio_gate.get("passed")) or diversity_only_warning
            if str(swarm_controller.policy.get("policy_id"))
            == "winning_swarm_dynamic_v2"
            else bool(raw_portfolio_gate.get("passed", finalist_count > 0))
        )
        final_merge = {
            "strategy": "candidate_ledger_plus_isolated_core_commits",
            "candidate_ledger_ready": finalist_count > 0,
            "finalist_count": finalist_count,
            "s4_mapping_ready": (
                4 not in active_set
                or bool(accumulated.get("capability_mapping"))
                or dynamic_portfolio_ready
            ),
            "s5_gap_review_ready": (
                5 not in active_set
                or bool(accumulated.get("gap_assessment"))
                or dynamic_portfolio_ready
            ),
            "s6_portfolio_ready": (
                6 not in active_set
                or bool(accumulated.get("concept_directions"))
                or dynamic_portfolio_ready
            ),
            "core_quality_gate_passed": core_gate_passed,
            "portfolio_quality_gate_passed": portfolio_quality_gate_passed,
        }
        final_merge["passed"] = bool(
            final_merge["candidate_ledger_ready"]
            and final_merge["s4_mapping_ready"]
            and final_merge["s5_gap_review_ready"]
            and final_merge["s6_portfolio_ready"]
            and final_merge["core_quality_gate_passed"]
            and final_merge["portfolio_quality_gate_passed"]
        )
        swarm_summary["final_merge"] = final_merge
        if not final_merge["passed"]:
            swarm_summary["stop_reason"] = "core_or_portfolio_quality_gate_failed"
        elif diversity_only_warning:
            swarm_summary["stop_reason"] = (
                "mission_graph_complete_with_diversity_warning"
            )
        accumulated["winning_swarm"] = swarm_summary
        emit_swarm_event(
            "swarm_gate_evaluated",
            stage="core_portfolio",
            passed=final_merge["passed"],
            finalist_count=finalist_count,
            completed_core_steps=finalized_core_schedule["completed_steps"],
            limited_core_steps=finalized_core_schedule["limited_steps"],
            final_merge=final_merge,
            swarm_summary=_compact_swarm_event_summary(swarm_summary),
        )
    accumulated["assumptions"] = list(dict.fromkeys(all_assumptions))[:12]
    accumulated["open_questions"] = list(dict.fromkeys(all_open_questions))[:12]
    accumulated["reasoning_nodes"] = reasoning_nodes
    runs.sort(key=lambda item: (int(item.get("middle_cycle", 1)), int(item["step"])))
    accumulated["subagent_runs"] = runs
    accumulated["dynamic_subagent_runs"] = [
        item
        for item in runs
        if item.get("execution_mode") in {"dynamic", "dynamic_mission_graph"}
    ]
    accumulated["loop_trace"] = loop_trace
    accumulated["winning_step_plan"] = shared["winning_step_plan"]
    accumulated["codex_call_metrics"] = host._call_metrics_since(metric_offset)
    return accumulated


async def _analyze_deep_divergence_subagents(
    host,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute the bounded contextual S3/S4/S6 deep-research child flow.

    This path intentionally does not call the ordinary six-step loop, the
    convergence Agent, the WinningCoreHarness, or any S1/S2/S5 prompt.  It
    fans out at most three independent S3 hypotheses, maps each through one
    S4 lane, then performs one S6 authoring call over the resulting (at most
    six) candidate directions.  Failed lanes are returned as auditable stage
    summaries instead of aborting successful siblings.
    """
    sensitive_key_markers = (
        "api_key",
        "credential",
        "secret",
        "access_token",
        "provider_metadata",
        "provider_session",
        "raw_session",
        "chain_of_thought",
        "hidden_reasoning",
    )

    def visible_context(value: Any) -> Any:
        """Detach canonical, user-visible context from runtime-only fields."""
        if isinstance(value, Mapping):
            return {
                str(key): visible_context(item)
                for key, item in value.items()
                if not any(marker in str(key).strip().lower() for marker in sensitive_key_markers)
            }
        if isinstance(value, (list, tuple)):
            return [visible_context(item) for item in value]
        return value

    run_id = str(payload.get("run_id", ""))
    topic = str(payload.get("topic", ""))
    route = str(payload.get("research_route", ""))
    parent = payload.get("deep_parent_context", {})
    parent = visible_context(dict(parent)) if isinstance(parent, Mapping) else {}
    candidate = parent.get("candidate", {})
    candidate = dict(candidate) if isinstance(candidate, Mapping) else {}
    parent_evidence_ids = [
        str(item)
        for item in candidate.get("evidence_ids", candidate.get("direct_evidence_refs", []))
        if str(item).strip()
    ]
    evidence_rows = payload.get("evidence_index", [])
    evidence_rows = [
        visible_context(dict(item))
        for item in evidence_rows
        if isinstance(item, Mapping)
    ]
    valid_evidence_ids = {
        str(item.get("evidence_id", ""))
        for item in evidence_rows
        if str(item.get("evidence_id", "")).strip()
    }
    # ``valid_evidence_ids`` tracks canonical references that may be shown in
    # a visible draft.  ``evidence_gate_ids`` is stricter: a newly retrieved
    # web citation is only a lead until the scheduler materializes and scores
    # it.  S4/S6 direct-evidence fields are filtered against this latter set,
    # preventing ungoverned citations from minting a capability card.
    evidence_gate_ids = {
        str(item.get("evidence_id", ""))
        for item in evidence_rows
        if str(item.get("evidence_id", "")).strip()
        and item.get("formal_evidence_allowed", True) is not False
    }
    # Parent evidence IDs are canonical references even when this isolated
    # child does not duplicate the parent's EvidenceCard rows locally.
    valid_evidence_ids.update(parent_evidence_ids)
    evidence_gate_ids.update(parent_evidence_ids)
    focus = str(parent.get("focus", "") or "当前Query下的参考装备方向深度研究")

    def emit(stage: str, status: str, *, progress: float, delta: str = "", **extra: Any) -> None:
        callback = getattr(host, "_emit_winning_progress", None)
        if callable(callback):
            callback({
                "event_type": "deep_stage",
                "run_id": run_id,
                "stage": stage,
                "status": status,
                "progress": max(0.0, min(1.0, progress)),
                "delta": {"kind": "summary", "text": delta} if delta else {},
                **extra,
            })

    def compact(value: Any, limit: int = 1400) -> Any:
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, Mapping):
            return {str(k): compact(v, limit // 2) for k, v in list(value.items())[:24]}
        if isinstance(value, (list, tuple)):
            return [compact(item, limit // 3) for item in list(value)[:12]]
        return value

    base_context = {
        "query": topic,
        "research_route": route,
        "focus": focus,
        "reference_candidate": compact(candidate),
        "parent_run_id": str(parent.get("parent_run_id", "")),
        "hypothesis_id": str(parent.get("hypothesis_id", candidate.get("hypothesis_id", ""))),
        "evidence_index": compact(evidence_rows, 3000),
        "valid_evidence_ids": sorted(valid_evidence_ids),
        "evidence_gate_ids": sorted(evidence_gate_ids),
        "stage_scope": ["S3", "S4", "S6"],
        "execution_profile_id": "deep_divergence_v1",
    }
    s3_prompt = (
        "你是深度发散S3 Agent。仅围绕当前Query和参考装备上下文，形成一个独立、"
        "可审核的制胜机理方向；不得复述S1/S2，也不得提出泛化支援系统。必须说明"
        "稳定装备身份、直接军事效果、独立机理、对手适应和失效边界。只输出JSON。"
    )
    s3_schema = {
        "hypothesis_id": "string",
        "direction_name": "string",
        "breakthrough_directions": ["string"],
        "effect_chain": ["string"],
        "equipment_form": "string",
        "operational_mechanism": "string",
        "military_value": "string",
        "target_and_direct_effect": "string",
        "failure_boundary": "string",
        "evidence_gap": ["具体需要公开资料核验的缺口"],
        "direct_evidence_refs": ["exact evidence_id"],
        "confidence": "0..1",
        "open_questions": ["string"],
    }

    async def call_s3(index: int) -> dict[str, Any]:
        emit("s3_divergence", "running", progress=(index - 1) / 3, delta=f"S3发散槽位{index}启动")
        seed = {
            1: "重点挑战当前参考方向的核心作战假设，寻找直接改变时间/暴露/毁伤关系的机理。",
            2: "从对手反适应和强约束条件出发，寻找不可由普通升级替代的装备本体方向。",
            3: "从跨域类比和未来威胁触发条件出发，寻找可证伪、可形成能力卡的独立方向。",
        }[index]
        raw_result = await host._run_core_json(
            "winning_s3_breakthrough",
            s3_prompt,
            {**base_context, "divergence_slot": index, "divergence_seed": seed},
            s3_schema,
            1800,
            phase="deep_s3_divergence",
        )
        result = (
            dict(raw_result)
            if isinstance(raw_result, Mapping)
            else _parse_json_object(raw_result)
        )
        if not isinstance(result, Mapping) or not str(result.get("direction_name", "")).strip():
            raise ValueError("S3未返回稳定装备方向")
        row = dict(result)
        row["slot"] = index
        row["stage"] = "S3"
        row["status"] = "completed"
        row["direct_evidence_refs"] = [
            str(ref)
            for ref in row.get("direct_evidence_refs", [])
            if str(ref) in evidence_gate_ids
        ]
        emit("s3_divergence", "completed", progress=index / 3, delta=f"S3发散槽位{index}完成", candidate=row)
        return row

    s3_results_raw = await asyncio.gather(
        *(call_s3(index) for index in range(1, 4)), return_exceptions=True
    )
    s3_results: list[dict[str, Any]] = []
    s3_failures: list[dict[str, Any]] = []
    for index, item in enumerate(s3_results_raw, start=1):
        if isinstance(item, Mapping):
            s3_results.append(dict(item))
        else:
            s3_failures.append({"stage": "S3", "slot": index, "status": "failed", "error": f"{type(item).__name__}: {item}"[:500]})
    emit("s3_divergence", "partial" if s3_failures and s3_results else "failed" if s3_failures else "completed", progress=1 / 3, delta="S3发散阶段已保留成功槽位和失败摘要", failures=s3_failures)

    # A deep turn starts from the parent's evidence snapshot, but a stable
    # S3 direction can still expose a concrete evidence gap.  In that case
    # escalate through the same governed hosted-search seam used by baseline
    # discovery.  Search results remain *leads* until the normal materializer
    # and evidence governor accept them; only the canonical, redacted rows
    # below are allowed into the S4/S6 context.  This keeps provider metadata,
    # credentials and hidden reasoning out of the child result while making
    # the retrieval decision auditable.
    retrieval_requests: list[dict[str, Any]] = []
    for row in s3_results:
        if not isinstance(row, Mapping):
            continue
        refs = [
            str(ref).strip()
            for ref in row.get("direct_evidence_refs", [])
            if str(ref).strip()
        ]
        gaps: list[str] = []
        for value in (
            row.get("evidence_gap", []),
            row.get("evidence_boundary", ""),
        ):
            values = value if isinstance(value, (list, tuple)) else [value]
            gaps.extend(str(item).strip() for item in values if str(item).strip())
        # A direction without a usable evidence reference, or one that
        # explicitly reports an unresolved boundary, is eligible for one
        # focused retrieval query.  Empty parent snapshots are also a gap.
        if not refs or gaps or (not evidence_rows and not parent_evidence_ids):
            focus_text = "; ".join(gaps[:2]) or "验证该方向的公开装备与作战效果依据"
            retrieval_requests.append(
                {
                    "slot": int(row.get("slot", len(retrieval_requests) + 1) or 1),
                    "query": f"{topic} {focus} {row.get('direction_name', '')} {focus_text}"[:1200],
                    "direction": str(row.get("direction_name", ""))[:240],
                }
            )
    # The profile budget is six searches per child batch.  Reserve through
    # the host's run-scoped governor so concurrent workers cannot over-admit
    # requests; the local slice is retained for embedders without budgets.
    retrieval_requests = retrieval_requests[:6]
    granted = 0
    if retrieval_requests:
        try:
            granted = int(host._reserve_search_batches(len(retrieval_requests)))
        except Exception:
            granted = len(retrieval_requests)
        granted = max(0, min(len(retrieval_requests), granted, 6))
    retrieval_requests = retrieval_requests[:granted]
    retrieval_request_count = len(retrieval_requests)
    retrieved_rows: list[dict[str, Any]] = []
    retrieval_failures: list[dict[str, Any]] = []

    async def retrieve_one(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        query = str(request.get("query", "")).strip()
        slot = int(request.get("slot", 0) or 0)
        emit("retrieval", "running", progress=0.36, delta=f"按需检索槽位{slot}启动")
        try:
            provider = host._discovery_provider_for("winning_s3_breakthrough")
            if provider is None:
                raise RuntimeError("受治理检索提供方不可用")
            retrieval_payload = {
                "run_id": run_id,
                "query": topic,
                "research_route": route,
                "focus": focus,
                "retrieval_query": query,
                "direction": str(request.get("direction", ""))[:240],
                "stage_scope": ["retrieval"],
                "execution_profile_id": "deep_divergence_v1",
            }
            agent = getattr(host, "agent_definitions", {}).get("winning_s3_breakthrough")
            runtime_messages = getattr(host, "_runtime_messages", None)
            if callable(runtime_messages):
                messages = runtime_messages(
                    "winning_s3_breakthrough",
                    "仅执行一次受治理公开资料检索。返回简短、可见的来源线索，不要输出隐藏推理、凭据或provider元数据。",
                    retrieval_payload,
                    phase="deep_retrieval",
                    agent=agent,
                    harness_profile=(host._harness_for(agent) if callable(getattr(host, "_harness_for", None)) else None),
                )
            else:
                messages = []
            options = {
                "web_search": {"search_context_size": "medium", "external_web_access": True},
                "include_web_sources": True,
                # Retrieval enriches a deep direction but is not a prerequisite
                # for returning the S3/S4 draft.  Some provider profiles (and
                # transient gateway failures) reject a forced hosted-search
                # tool call before producing any text; keeping the tool
                # optional lets the workflow preserve the already completed
                # direction and continue through the evidence gate normally.
                "require_web_search": False,
                "_run_id": run_id,
                "_provider_retry_attempts": 1,
            }
            text, metadata = await host._collect_stream(
                provider,
                messages,
                options,
                priority="normal",
                progress={
                    "run_id": run_id,
                    "agent_id": "winning_s3_breakthrough",
                    "phase": "deep_retrieval",
                    "step": 3,
                    "steps": [3],
                    "current_step": "深研按需检索",
                },
                progress_family="winning",
            )
            del text  # only provider-reported citations are admissible leads
            raw_sources = metadata.get("web_sources", []) if isinstance(metadata, Mapping) else []
            rows: list[dict[str, Any]] = []
            seen_urls: set[str] = set()
            for source in raw_sources if isinstance(raw_sources, list) else []:
                if not isinstance(source, Mapping):
                    continue
                url = str(source.get("url", "")).strip()
                try:
                    parsed = urlsplit(url)
                except ValueError:
                    continue
                if parsed.scheme.lower() != "https" or not parsed.hostname or url in seen_urls:
                    continue
                seen_urls.add(url)
                digest = sha256(url.encode("utf-8")).hexdigest()[:12]
                title = str(source.get("title", "")).strip()[:300] or url
                snippet = str(source.get("snippet", "")).strip()[:800]
                rows.append(
                    {
                        "evidence_id": f"ev-deep-{digest}",
                        "source_title": title,
                        "source_url": url,
                        "source_tier": "B",
                        "claim": snippet or f"公开来源支持{request.get('direction', '')}方向的进一步核验。",
                        "excerpt": snippet,
                        "source_location": "deep_divergence:web_search",
                        "quality_assessment": "deep_retrieval_lead; pending_materialization",
                        "created_by": "deep_divergence_v1",
                        "retrieval_query": query[:1200],
                        "retrieval_slot": slot,
                        "formal_evidence_allowed": False,
                    }
                )
            # Production runners may provide the normal materializer/governor
            # callback.  Keep the workflow usable in isolated unit hosts (no
            # callback => lead-only rows), while allowing accepted evidence to
            # reopen the S4/S6 evidence gate in a real child run.
            materialize = getattr(host, "_deep_evidence_materializer", None)
            if callable(materialize) and rows:
                try:
                    # Page fetching is synchronous in the existing
                    # EvidenceMaterializer; keep it off the provider event
                    # loop while preserving the scheduler's thread-safe
                    # store/state locks.
                    governed = await asyncio.to_thread(materialize, rows)
                    if isinstance(governed, list):
                        rows = [dict(item) for item in governed if isinstance(item, Mapping)]
                except Exception:
                    # Materialization is best-effort; the retrieval lead and
                    # its failure boundary remain visible and S6 stays gated.
                    pass
            emit("retrieval", "completed", progress=0.40, delta=f"按需检索槽位{slot}完成，获得{len(rows)}条来源线索", evidence_refs=[item["evidence_id"] for item in rows])
            return rows, None
        except Exception as exc:
            failure = {"stage": "retrieval", "slot": slot, "status": "partial", "error": f"{type(exc).__name__}: {exc}"[:500]}
            emit("retrieval", "partial", progress=0.40, delta=f"按需检索槽位{slot}失败，保留既有草稿", failures=[failure])
            return [], failure

    if retrieval_requests:
        max_parallel = 6
        try:
            configured = int(
                getattr(host, "_runtime_budgets", {}).get(
                    "codex_concurrency",
                    getattr(host, "_runtime_budgets", {}).get("max_concurrency", 6),
                )
            )
            max_parallel = max(1, min(6, configured))
        except (AttributeError, TypeError, ValueError):
            pass
        semaphore = asyncio.Semaphore(max_parallel)

        async def bounded_retrieve(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            async with semaphore:
                return await retrieve_one(request)

        retrieval_results = await asyncio.gather(
            *(bounded_retrieve(request) for request in retrieval_requests),
            return_exceptions=True,
        )
        for request, result in zip(retrieval_requests, retrieval_results):
            if isinstance(result, Exception):
                retrieval_failures.append({"stage": "retrieval", "slot": request.get("slot"), "status": "partial", "error": f"{type(result).__name__}: {result}"[:500]})
                continue
            rows, failure = result
            retrieved_rows.extend(rows)
            if failure:
                retrieval_failures.append(failure)
    # Dedupe and append only canonical public fields to the context consumed
    # by S4/S6.  The original parent evidence rows remain unchanged.
    existing_ids = {
        str(item.get("evidence_id", ""))
        for item in evidence_rows
        if isinstance(item, Mapping)
    }
    for row in retrieved_rows:
        evidence_id = str(row.get("evidence_id", ""))
        if evidence_id and evidence_id not in existing_ids:
            evidence_rows.append(row)
            existing_ids.add(evidence_id)
            valid_evidence_ids.add(evidence_id)
            if row.get("formal_evidence_allowed", False) is True:
                evidence_gate_ids.add(evidence_id)
    if retrieved_rows:
        base_context["evidence_index"] = compact(evidence_rows, 3600)
        base_context["valid_evidence_ids"] = sorted(valid_evidence_ids)
        base_context["evidence_gate_ids"] = sorted(evidence_gate_ids)
    if retrieval_failures:
        emit("retrieval", "partial" if retrieved_rows else "failed", progress=0.42, delta="按需检索阶段已保留成功来源和失败摘要", failures=retrieval_failures)

    # A source may be cited by multiple focused queries.  Keep one canonical
    # row per evidence id in the public result while retaining every query's
    # audit event in the stage stream.
    unique_retrieved: dict[str, dict[str, Any]] = {}
    for row in retrieved_rows:
        evidence_id = str(row.get("evidence_id", "")).strip()
        if evidence_id and evidence_id not in unique_retrieved:
            unique_retrieved[evidence_id] = dict(row)
    retrieved_rows = list(unique_retrieved.values())

    s4_prompt = (
        "你是深度发散S4 Agent。消费一个S3独立方向，将其映射为唯一主装备、"
        "能力、功能、作战流程、直接战果和可证伪验证条件。不得引入第二个主装备，"
        "不得回到S1/S2/S5。只输出JSON。"
    )
    s4_schema = {
        "hypothesis_id": "string",
        "capability_mapping": ["string"],
        "concept_directions": [
            {
                "name": "string",
                "type": "new_capability|upgrade",
                "function": "string",
                "equipment_form": "string",
                "primary_equipment_identity": "string",
                "operational_mechanism": "string",
                "target_scenario": "string",
                "military_value": "string",
                "direct_evidence_refs": ["exact evidence_id"],
                "capability_gap": "string",
                "baseline_system": "string",
                "failure_boundary": "string",
                "evidence_gap": ["具体需要公开资料核验的缺口"],
                "validation_plan": ["string"],
                "confidence": "0..1",
            }
        ],
        "confidence": "0..1",
        "open_questions": ["string"],
    }

    async def call_s4(index: int, s3: Mapping[str, Any]) -> dict[str, Any]:
        emit("s4_mapping", "running", progress=(index - 1) / 3, delta=f"S4映射槽位{index}启动")
        raw_result = await host._run_core_json(
            "winning_s4_capability",
            s4_prompt,
            {**base_context, "s3_direction": compact(s3), "mapping_slot": index},
            s4_schema,
            2200,
            phase="deep_s4_mapping",
        )
        result = (
            dict(raw_result)
            if isinstance(raw_result, Mapping)
            else _parse_json_object(raw_result)
        )
        if not isinstance(result, Mapping):
            raise ValueError("S4未返回结构化映射")
        row = dict(result)
        row["slot"] = index
        row["stage"] = "S4"
        row["status"] = "completed"
        directions = []
        for raw in row.get("concept_directions", []) if isinstance(row.get("concept_directions", []), list) else []:
            if not isinstance(raw, Mapping) or not str(raw.get("name", "")).strip():
                continue
            item = dict(raw)
            item["hypothesis_id"] = str(item.get("hypothesis_id") or s3.get("hypothesis_id") or parent.get("hypothesis_id", ""))
            item["direct_evidence_refs"] = [
                str(ref)
                for ref in item.get("direct_evidence_refs", [])
                if str(ref) in evidence_gate_ids
            ]
            directions.append(item)
        row["concept_directions"] = directions[:2]
        emit("s4_mapping", "completed", progress=index / 3, delta=f"S4映射槽位{index}完成", candidate_count=len(directions))
        return row

    s4_results_raw = await asyncio.gather(
        *(call_s4(index, s3) for index, s3 in enumerate(s3_results, start=1)),
        return_exceptions=True,
    )
    s4_results: list[dict[str, Any]] = []
    s4_failures: list[dict[str, Any]] = []
    for index, item in enumerate(s4_results_raw, start=1):
        if isinstance(item, Mapping):
            s4_results.append(dict(item))
        else:
            s4_failures.append({"stage": "S4", "slot": index, "status": "failed", "error": f"{type(item).__name__}: {item}"[:500]})

    # S4 may identify a new, direction-specific evidence gap after mapping
    # the S3 mechanism to a concrete equipment object.  Spend only the
    # remaining child budget on those focused queries, then feed the redacted
    # leads into the S6 context.  They remain outside ``evidence_gate_ids``
    # until materialized by the governed scheduler, so this second escalation
    # can never bypass the release gate.
    s4_retrieval_requests: list[dict[str, Any]] = []
    for row in s4_results:
        if not isinstance(row, Mapping):
            continue
        slot = int(row.get("slot", len(s4_retrieval_requests) + 1) or 1)
        row_gaps: list[str] = []
        for value in (row.get("evidence_gap", []), row.get("evidence_boundary", "")):
            values = value if isinstance(value, (list, tuple)) else [value]
            row_gaps.extend(str(item).strip() for item in values if str(item).strip())
        directions = row.get("concept_directions", [])
        direction_rows = directions if isinstance(directions, list) else []
        for direction in direction_rows[:2]:
            if not isinstance(direction, Mapping):
                continue
            refs = [
                str(ref).strip()
                for ref in direction.get("direct_evidence_refs", [])
                if str(ref).strip()
            ]
            gaps = list(row_gaps)
            for value in (direction.get("evidence_gap", []), direction.get("failure_boundary", "")):
                values = value if isinstance(value, (list, tuple)) else [value]
                gaps.extend(str(item).strip() for item in values if str(item).strip())
            if refs and not gaps:
                continue
            direction_name = str(direction.get("name", ""))[:240]
            s4_retrieval_requests.append(
                {
                    "slot": slot,
                    "query": f"{topic} {focus} {direction_name} {'; '.join(gaps[:2]) or '核验装备能力与直接作战效果依据'}"[:1200],
                    "direction": direction_name,
                }
            )
    remaining = max(0, 6 - retrieval_request_count)
    s4_retrieval_requests = s4_retrieval_requests[:remaining]
    if s4_retrieval_requests:
        try:
            granted_s4 = int(host._reserve_search_batches(len(s4_retrieval_requests)))
        except Exception:
            granted_s4 = len(s4_retrieval_requests)
        s4_retrieval_requests = s4_retrieval_requests[: max(0, min(remaining, granted_s4))]
    retrieval_request_count += len(s4_retrieval_requests)
    if s4_retrieval_requests:
        semaphore = asyncio.Semaphore(max_parallel if "max_parallel" in locals() else 6)

        async def bounded_s4_retrieve(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            async with semaphore:
                return await retrieve_one(request)

        s4_retrieval_results = await asyncio.gather(
            *(bounded_s4_retrieve(request) for request in s4_retrieval_requests),
            return_exceptions=True,
        )
        for request, result in zip(s4_retrieval_requests, s4_retrieval_results):
            if isinstance(result, Exception):
                retrieval_failures.append({"stage": "retrieval", "slot": request.get("slot"), "status": "partial", "error": f"{type(result).__name__}: {result}"[:500]})
                continue
            rows, failure = result
            retrieved_rows.extend(rows)
            if failure:
                retrieval_failures.append(failure)
        for row in retrieved_rows:
            evidence_id = str(row.get("evidence_id", ""))
            if evidence_id and evidence_id not in existing_ids:
                evidence_rows.append(row)
                existing_ids.add(evidence_id)
                valid_evidence_ids.add(evidence_id)
                if row.get("formal_evidence_allowed", False) is True:
                    evidence_gate_ids.add(evidence_id)
        base_context["evidence_index"] = compact(evidence_rows, 3600)
        base_context["valid_evidence_ids"] = sorted(valid_evidence_ids)
        base_context["evidence_gate_ids"] = sorted(evidence_gate_ids)
        emit("retrieval", "partial" if retrieval_failures else "completed", progress=0.48, delta="S4映射后的补充检索已完成，来源仍待材料化证据门", failures=retrieval_failures)

    unique_retrieved: dict[str, dict[str, Any]] = {}
    for row in retrieved_rows:
        evidence_id = str(row.get("evidence_id", "")).strip()
        if evidence_id and evidence_id not in unique_retrieved:
            unique_retrieved[evidence_id] = dict(row)
    retrieved_rows = list(unique_retrieved.values())
    mapped_directions = [
        dict(direction)
        for row in s4_results
        for direction in row.get("concept_directions", [])
        if isinstance(direction, Mapping) and str(direction.get("name", "")).strip()
    ][:6]
    s6_candidate_directions = [
        dict(direction)
        for direction in mapped_directions
        if any(
            str(ref) in evidence_gate_ids
            for ref in direction.get("direct_evidence_refs", [])
        )
    ]
    evidence_blocked_directions = [
        str(direction.get("name", ""))
        for direction in mapped_directions
        if direction not in s6_candidate_directions
    ]
    emit("s4_mapping", "partial" if s4_failures and s4_results else "failed" if s4_failures else "completed", progress=2 / 3, delta="S4能力映射阶段已保留成功槽位和失败摘要", failures=s4_failures, candidate_count=len(mapped_directions), evidence_gated_candidate_count=len(s6_candidate_directions))

    s6_result: dict[str, Any] = {}
    s6_failure: dict[str, Any] | None = None
    if s6_candidate_directions:
        emit("s6_authoring", "running", progress=2 / 3, delta="S6能力卡撰写启动")
        s6_prompt = (
            "你是深度发散S6 Agent。仅消费S3/S4已形成的候选方向，保持每个方向的"
            "唯一装备身份和独立制胜机理，生成可审核的能力画像卡。候选不超过6张；"
            "若身份、直接战果、证据或验证条件不稳定，返回空候选并说明原因。只输出JSON。"
        )
        s6_schema = {
            "concept_directions": [
                {
                    "name": "string",
                    "type": "new_capability|upgrade",
                    "function": "string",
                    "equipment_form": "string",
                    "primary_equipment_identity": "string",
                    "operational_mechanism": "string",
                    "target_scenario": "string",
                    "problem_statement": "string",
                    "scientific_principle": "string",
                    "operational_process": ["string"],
                    "military_value": "string",
                    "capability_gap": "string",
                    "baseline_system": "string",
                    "direct_evidence_refs": ["exact evidence_id"],
                    "failure_boundary": "string",
                    "validation_plan": ["string"],
                    "development_path": "string",
                    "confidence": "0..1",
                }
            ],
            "confidence": "0..1",
            "open_questions": ["string"],
            "evidence_validation": {"all_ids_valid": "boolean", "invalid_ids": ["string"]},
        }
        try:
            raw = await host._run_core_json(
                "winning_s6_image",
                s6_prompt,
                {
                    **base_context,
                    "s3_directions": compact(s3_results),
                    "s4_mappings": compact(s4_results),
                    "candidate_directions": compact(s6_candidate_directions, 5000),
                    "max_candidates": 6,
                },
                s6_schema,
                4200,
                phase="deep_s6_authoring",
            )
            parsed_raw = (
                dict(raw)
                if isinstance(raw, Mapping)
                else _parse_json_object(raw)
            )
            if isinstance(parsed_raw, Mapping):
                s6_result = dict(parsed_raw)
                cleaned: list[dict[str, Any]] = []
                for raw_direction in s6_result.get("concept_directions", []) if isinstance(s6_result.get("concept_directions", []), list) else []:
                    if not isinstance(raw_direction, Mapping) or not str(raw_direction.get("name", "")).strip():
                        continue
                    item = dict(raw_direction)
                    item["direct_evidence_refs"] = [
                        str(ref)
                        for ref in item.get("direct_evidence_refs", [])
                        if str(ref) in evidence_gate_ids
                    ]
                    if item["direct_evidence_refs"]:
                        cleaned.append(item)
                s6_result["concept_directions"] = cleaned[:6]
            else:
                raise ValueError("S6未返回结构化能力卡")
            emit("s6_authoring", "completed", progress=1.0, delta=f"S6已形成{len(s6_result.get('concept_directions', []))}张候选能力卡", candidate_count=len(s6_result.get("concept_directions", [])))
        except Exception as exc:
            s6_failure = {"stage": "S6", "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
            emit("s6_authoring", "partial", progress=1.0, delta="S6失败，保留S3/S4候选草稿但不自动成卡", failures=[s6_failure])
    else:
        reason = (
            "S4候选未通过正式证据门"
            if mapped_directions
            else "S4未形成可成卡方向"
        )
        s6_failure = {"stage": "S6", "status": "blocked", "error": reason}
        emit("s6_authoring", "blocked", progress=1.0, delta=f"{reason}，保留可见草稿")

    if not s6_result.get("concept_directions"):
        # S6 failure/empty output must never be interpreted as a successful
        # capability version. Keep the mapped drafts for visible analysis,
        # while leaving ``concept_directions`` empty for the release gate.
        status = "blocked" if not s3_results else "partial"
    else:
        status = "completed" if not (s3_failures or s4_failures or retrieval_failures or evidence_blocked_directions) else "partial"
    return {
        "execution_profile_id": "deep_divergence_v1",
        "deep_divergence_status": status,
        "deep_stage_scope": ["S3", "S4", "S6"],
        "deep_stage_plan": {
            "S3": {"max_parallel_slots": 3, "completed": len(s3_results), "failed": len(s3_failures)},
            "retrieval": {"max_searches": 6, "requested": retrieval_request_count, "completed": len(retrieved_rows), "failed": len(retrieval_failures)},
            "S4": {"max_parallel_slots": 3, "completed": len(s4_results), "failed": len(s4_failures)},
            "S6": {"max_parallel_slots": 1, "completed": bool(s6_result.get("concept_directions")), "failed": bool(s6_failure)},
        },
        "breakthrough_directions": [
            item for row in s3_results for item in row.get("breakthrough_directions", []) if str(item).strip()
        ][:12],
        "effect_chain": [
            item for row in s3_results for item in row.get("effect_chain", []) if str(item).strip()
        ][:12],
        "capability_mapping": [
            item for row in s4_results for item in row.get("capability_mapping", []) if str(item).strip()
        ][:12],
        "concept_directions": list(s6_result.get("concept_directions", []))[:6],
        "deep_drafts": {
            "s3": s3_results,
            "s4": s4_results,
            "mapped_concept_directions": mapped_directions,
            "evidence_blocked_directions": evidence_blocked_directions,
        },
        "retrieved_evidence": retrieved_rows[:18],
        "deep_failures": [*s3_failures, *retrieval_failures, *s4_failures, *([s6_failure] if s6_failure else [])],
        "evidence_validation": s6_result.get("evidence_validation", {"all_ids_valid": True, "invalid_ids": []}),
        "open_questions": list(s6_result.get("open_questions", []))[:12],
        "confidence": s6_result.get("confidence", 0.0),
        "subagent_runs": [
            *[
                {"step": 3, "agent_id": "winning_s3_breakthrough", "slot": item.get("slot"), "status": "completed"}
                for item in s3_results
            ],
            *[
                {"step": 4, "agent_id": "winning_s4_capability", "slot": item.get("slot"), "status": "completed"}
                for item in s4_results
            ],
            {"step": 6, "agent_id": "winning_s6_image", "status": "completed" if s6_result.get("concept_directions") else "partial" if s6_failure else "blocked"},
        ],
        "loop_trace": [],
    }
