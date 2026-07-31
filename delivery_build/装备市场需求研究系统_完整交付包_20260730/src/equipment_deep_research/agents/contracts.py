from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_MODEL_PROFILE: dict[str, str] = {
    "provider": "responses",
    "model": "gpt-5.5",
}

# Task 2 can attach handlers to these names without making agent configuration
# depend on executable registry objects.
TOOL_CATALOG = frozenset(
    {
        "search_sources",
        "fetch_page",
        "create_evidence_card",
        "write_stage_output",
        "create_recall_request",
        "create_capability_image",
        "write_audit",
        "write_report",
        "register_event_timeline",
        "compare_actor_positions",
        "register_warning_indicator",
        "test_competing_hypothesis",
        "build_scenario_graph",
        "branch_scenario",
        "map_critical_window",
        "map_environment_constraint",
        "stress_test_scenario",
        "extract_parameter_observation",
        "normalize_equipment_variant",
        "reconcile_parameter_conflict",
        "assess_technology_readiness",
        "compare_equipment_capability",
        "map_defensive_countermeasure",
        "formulate_equipment_requirement",
        "map_task_capability",
        "build_coordination_dependency",
        "compare_coa",
        "assess_sustainment_resilience",
        "transfer_case_lesson",
        "prepare_winning_input",
        "project_winning_resources",
        "write_reasoning_node",
        "analyze_research_request",
        "classify_discovery_drivers",
        "build_discovery_blueprint",
        "plan_execution_waves",
        "evaluate_loop_transition",
        "reconstruct_case_timeline",
        "build_causal_chain",
        "compare_case_patterns",
        "assess_technology_potential",
        "construct_disruptive_scenario",
        "detect_baseline_change",
        "estimate_capability_formation",
        "build_system_model",
        "identify_cascading_vulnerability",
        "build_cross_domain_matrix",
        "identify_interface_gap",
        "scan_emerging_threat",
        "assess_legal_ethical_boundary",
        "cluster_demand_signals",
        "rank_capability_priorities",
        "analyze_ooda_vulnerability",
        "generate_counterfactual_option",
        "apply_triz_contradiction",
        "map_dotmlpf_requirement",
        "evaluate_reasoning_step",
        "evaluate_reasoning_round",
        "evaluate_release_readiness",
        "build_capability_demand_card",
    }
)

CONTRACT_CATALOG = frozenset(
    {
        "AgentExecutionResult",
        "AuditResult",
        "BaselineFindingPacket",
        "ResearchReport",
        "TaskEnvelope",
        "WinningMechanismStageOutput",
        "research_task",
        "task_envelope",
        "agent_execution_result",
        "baseline_finding_packet",
        "winning_mechanism_stage_output",
        "audit_result",
        "research_report",
    }
)

VISIBLE_SECTION_CATALOG = frozenset(
    {
        "task",
        "evidence_policy",
        "own_checkpoint",
        "recall_request",
        "agent_harness",
        "incremental_knowledge",
        "upstream_handoffs",
        "baseline_summaries",
        "evidence_index",
        "coverage",
        "checkpoints",
        "stage_outputs",
        "capability_images",
        "trace_summary",
        "audit",
    }
)

OBJECT_SCOPE_CATALOG = frozenset(
    {
        "ResearchProblem",
        "EvidenceCard",
        "BaselineFindingPacket",
        "WorkingCheckpoint",
        "RecallRequest",
        "AgentRecommendation",
        "WinningMechanismStageOutput",
        "CapabilityImageItem",
        "AuditResult",
        "ResearchReport",
        "TraceEvent",
        "SearchLead",
        "SourceMaterial",
        "StrategicAssessment",
        "ScenarioModel",
        "EquipmentObservation",
        "OperationalSynthesis",
        "WinningReasoningNode",
        "WinningMechanismInput",
        "WinningKnowledgeProjection",
    }
)

LEGACY_SYSTEM_AGENT_IDS = frozenset({"winning_mechanism", "auditor", "reporter"})

_SYSTEM_OUTPUT_CONTRACTS = {
    "winning_mechanism": "winning_mechanism_stage_output",
    "auditor": "audit_result",
    "reporter": "research_report",
}

_SECRET_PROFILE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credentials",
        "headers",
        "secret",
        "token",
    }
)


def default_output_contract(agent_id: str) -> str:
    return _SYSTEM_OUTPUT_CONTRACTS.get(agent_id, "baseline_finding_packet")


def validate_named_contract(value: str | Mapping[str, Any], *, field_name: str) -> None:
    if isinstance(value, str):
        if value not in CONTRACT_CATALOG:
            raise ValueError(f"unknown {field_name}: {value}")
        return
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field_name} must name or define an existing contract")
    reference = next(
        (
            value[key]
            for key in ("name", "contract", "$ref")
            if key in value
        ),
        None,
    )
    if reference is not None and (
        not isinstance(reference, str) or reference not in CONTRACT_CATALOG
    ):
        raise ValueError(f"unknown {field_name}: {reference}")


def validate_model_profile(value: Mapping[str, Any]) -> None:
    provider = value.get("provider")
    model = value.get("model")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("model_profile provider must be a non-empty string")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model_profile model must be a non-empty string")

    forbidden = sorted(_find_secret_keys(value))
    if forbidden:
        raise ValueError(f"model_profile cannot contain secret fields: {forbidden}")


def validate_agent_extension(value: Any, *, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    if _find_secret_keys(value):
        raise ValueError(f"{field_name} cannot contain secret fields")


def _find_secret_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {
            str(key)
            for key in value
            if str(key).lower().replace("-", "_") in _SECRET_PROFILE_KEYS
        }
        for item in value.values():
            found.update(_find_secret_keys(item))
        return found
    if isinstance(value, (list, tuple)):
        found: set[str] = set()
        for item in value:
            found.update(_find_secret_keys(item))
        return found
    return set()


__all__ = [
    "CONTRACT_CATALOG",
    "DEFAULT_MODEL_PROFILE",
    "LEGACY_SYSTEM_AGENT_IDS",
    "OBJECT_SCOPE_CATALOG",
    "TOOL_CATALOG",
    "VISIBLE_SECTION_CATALOG",
    "default_output_contract",
    "validate_model_profile",
    "validate_agent_extension",
    "validate_named_contract",
]
