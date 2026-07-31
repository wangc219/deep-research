from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from equipment_deep_research.domain.proposals import TraceProposal, thaw_plain
from equipment_deep_research.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


DOMAIN_TOOL_OUTPUTS: dict[str, str] = {
    "register_event_timeline": "StrategicAssessment",
    "compare_actor_positions": "StrategicAssessment",
    "register_warning_indicator": "StrategicAssessment",
    "test_competing_hypothesis": "StrategicAssessment",
    "build_scenario_graph": "ScenarioModel",
    "branch_scenario": "ScenarioModel",
    "map_critical_window": "ScenarioModel",
    "map_environment_constraint": "ScenarioModel",
    "stress_test_scenario": "ScenarioModel",
    "extract_parameter_observation": "EquipmentObservation",
    "normalize_equipment_variant": "EquipmentObservation",
    "reconcile_parameter_conflict": "EquipmentObservation",
    "assess_technology_readiness": "EquipmentObservation",
    "compare_equipment_capability": "EquipmentObservation",
    "map_defensive_countermeasure": "EquipmentObservation",
    "formulate_equipment_requirement": "EquipmentObservation",
    "map_task_capability": "OperationalSynthesis",
    "build_coordination_dependency": "OperationalSynthesis",
    "compare_coa": "OperationalSynthesis",
    "assess_sustainment_resilience": "OperationalSynthesis",
    "transfer_case_lesson": "OperationalSynthesis",
    "prepare_winning_input": "WinningMechanismInput",
    "project_winning_resources": "WinningKnowledgeProjection",
    "write_reasoning_node": "WinningReasoningNode",
    "analyze_research_request": "WorkingCheckpoint",
    "classify_discovery_drivers": "WorkingCheckpoint",
    "build_discovery_blueprint": "WorkingCheckpoint",
    "plan_execution_waves": "WorkingCheckpoint",
    "evaluate_loop_transition": "WorkingCheckpoint",
    "reconstruct_case_timeline": "OperationalSynthesis",
    "build_causal_chain": "OperationalSynthesis",
    "compare_case_patterns": "OperationalSynthesis",
    "assess_technology_potential": "EquipmentObservation",
    "construct_disruptive_scenario": "ScenarioModel",
    "detect_baseline_change": "StrategicAssessment",
    "estimate_capability_formation": "StrategicAssessment",
    "build_system_model": "OperationalSynthesis",
    "identify_cascading_vulnerability": "OperationalSynthesis",
    "build_cross_domain_matrix": "OperationalSynthesis",
    "identify_interface_gap": "OperationalSynthesis",
    "scan_emerging_threat": "StrategicAssessment",
    "assess_legal_ethical_boundary": "OperationalSynthesis",
    "cluster_demand_signals": "WinningKnowledgeProjection",
    "rank_capability_priorities": "WinningKnowledgeProjection",
    "analyze_ooda_vulnerability": "WinningReasoningNode",
    "generate_counterfactual_option": "WinningReasoningNode",
    "apply_triz_contradiction": "WinningReasoningNode",
    "map_dotmlpf_requirement": "WinningReasoningNode",
    "evaluate_reasoning_step": "RecallRequest",
    "evaluate_reasoning_round": "RecallRequest",
    "evaluate_release_readiness": "AuditResult",
    "build_capability_demand_card": "ResearchReport",
}


_TOOL_FIELDS: dict[str, tuple[str, ...]] = {
    "register_event_timeline": ("timeline_id", "events"),
    "compare_actor_positions": ("comparison_id", "actors"),
    "register_warning_indicator": ("indicator_id", "indicator", "observable"),
    "test_competing_hypothesis": ("test_id", "hypotheses", "evidence_refs"),
    "build_scenario_graph": ("scenario_id", "nodes", "edges"),
    "branch_scenario": ("scenario_id", "branch_id", "trigger", "outcomes"),
    "map_critical_window": ("scenario_id", "window_id", "start_condition", "end_condition"),
    "map_environment_constraint": ("scenario_id", "constraint_id", "constraint", "capability_pressure"),
    "stress_test_scenario": ("scenario_id", "stress_id", "assumptions", "result"),
    "extract_parameter_observation": ("observation_id", "model", "parameter", "value", "unit", "variant", "condition", "confidence"),
    "normalize_equipment_variant": ("observation_id", "model", "variant", "aliases"),
    "reconcile_parameter_conflict": ("observation_id", "parameter", "observations", "resolution"),
    "assess_technology_readiness": ("observation_id", "technology", "readiness", "basis"),
    "compare_equipment_capability": ("comparison_id", "models", "dimensions", "result"),
    "map_defensive_countermeasure": ("mapping_id", "foreign_capability", "dependency_or_constraint", "defensive_function", "options", "applicability", "evidence_refs"),
    "formulate_equipment_requirement": ("requirement_id", "mission_need", "capability_goal", "upgrade_or_new", "technology_options", "maturity", "verification", "evidence_refs"),
    "map_task_capability": ("synthesis_id", "task", "capabilities", "constraints"),
    "build_coordination_dependency": ("synthesis_id", "nodes", "dependencies"),
    "compare_coa": ("synthesis_id", "baseline", "distributed", "resource_constrained"),
    "assess_sustainment_resilience": ("synthesis_id", "supplies", "failure_modes", "recovery"),
    "transfer_case_lesson": ("synthesis_id", "case", "lesson", "applicability", "limits"),
    "prepare_winning_input": ("input_id", "packet_ids", "coverage", "open_questions"),
    "project_winning_resources": ("projection_id", "input_id", "theory", "cases", "frontier", "questions"),
    "write_reasoning_node": ("object_id", "step", "title", "summary", "input_refs", "evidence_ids", "confidence", "next_action"),
    "analyze_research_request": ("analysis_id", "interaction_mode", "objective", "deliverables", "constraints", "safety_boundaries", "granularity", "domains", "time_horizon", "assumptions", "unknowns", "decision_questions"),
    "classify_discovery_drivers": ("classification_id", "driver_scores", "primary_driver", "secondary_drivers", "unmatched_driver", "evidence_signals", "rationale", "confidence"),
    "build_discovery_blueprint": ("blueprint_id", "primary_branch", "secondary_branches", "runtime_route", "unmatched_driver", "available_agent_capabilities", "custom_blueprint", "emphasis_steps", "agent_ids", "required_outputs", "waves", "dependencies", "loop_policy", "stop_conditions", "fallback_policy"),
    "plan_execution_waves": ("plan_id", "waves", "dependencies", "handoffs", "parallelism", "critical_path", "coverage_matrix", "budget"),
    "evaluate_loop_transition": ("decision_id", "loop_level", "quality_state", "information_gain", "next_action", "return_node", "budget_state", "reason", "stop_reason"),
    "reconstruct_case_timeline": ("synthesis_id", "case_id", "events", "decision_points", "evidence_refs"),
    "build_causal_chain": ("synthesis_id", "case_id", "causes", "mechanisms", "effects", "counterfactuals", "evidence_refs"),
    "compare_case_patterns": ("synthesis_id", "case_ids", "common_patterns", "differences", "transfer_boundaries"),
    "assess_technology_potential": ("observation_id", "technology", "mission_effects", "enablers", "constraints", "time_horizon", "confidence"),
    "construct_disruptive_scenario": ("scenario_id", "technology", "baseline", "disruption", "triggers", "failure_modes"),
    "detect_baseline_change": ("assessment_id", "baseline", "observations", "changes", "significance", "evidence_refs"),
    "estimate_capability_formation": ("assessment_id", "capability", "milestones", "dependencies", "time_window", "uncertainty"),
    "build_system_model": ("synthesis_id", "system_boundary", "nodes", "dependencies", "mission_threads", "assumptions"),
    "identify_cascading_vulnerability": ("synthesis_id", "trigger", "dependency_path", "cascading_effects", "alternatives", "limits"),
    "build_cross_domain_matrix": ("synthesis_id", "domains", "missions", "interfaces", "dependencies"),
    "identify_interface_gap": ("synthesis_id", "interface", "data_gap", "command_gap", "timing_gap", "support_gap", "degraded_mode"),
    "scan_emerging_threat": ("assessment_id", "threat", "drivers", "triggers", "affected_missions", "warning_indicators"),
    "assess_legal_ethical_boundary": ("synthesis_id", "scenario", "stakeholders", "constraints", "civilian_impacts", "allowed_responses"),
    "cluster_demand_signals": ("projection_id", "packet_ids", "clusters", "conflicts", "open_questions"),
    "rank_capability_priorities": ("projection_id", "candidates", "criteria", "scores", "dependencies", "ranking"),
    "analyze_ooda_vulnerability": ("object_id", "step", "ooda_nodes", "dependencies", "vulnerabilities", "alternatives", "evidence_ids", "confidence"),
    "generate_counterfactual_option": ("object_id", "step", "assumption", "counterfactual", "expected_effects", "risks", "evidence_ids", "confidence"),
    "apply_triz_contradiction": ("object_id", "step", "contradiction", "principles", "options", "tradeoffs", "evidence_ids", "confidence"),
    "map_dotmlpf_requirement": ("object_id", "step", "mission_effect", "capability", "dotmlpf", "equipment_functions", "interfaces", "evidence_ids", "confidence"),
    "evaluate_reasoning_step": ("recall_id", "step", "issues", "missing_evidence", "retry_guidance", "return_node"),
    "evaluate_reasoning_round": ("recall_id", "issues", "broken_links", "rerun_from_step", "rerun_guidance"),
    "evaluate_release_readiness": ("audit_id", "criteria", "findings", "risks", "release_recommendation"),
    "build_capability_demand_card": (
        "report_id",
        "weapon_equipment",
        "equipment_configuration",
        "development_mode",
        "mission_effect",
        "key_indicators",
        "priority",
        "supporting_scenarios",
        "evidence_chain",
        "source_winning_logic",
        "capability_gap",
        "deep_capability_portrait",
        "baseline_system",
        "upgrade_package",
        "combat_effect_uplift",
        "strike_chain_contribution",
        "upgrade_boundary",
        "system_dependencies",
        "verification",
        "limitations",
    ),
}


def build_domain_tool_definitions(names: Iterable[str]) -> tuple[ToolDefinition, ...]:
    return tuple(_definition(str(name)) for name in names)


def _definition(name: str) -> ToolDefinition:
    fields = _TOOL_FIELDS.get(name, ())
    properties = {field: _field_schema(field) for field in fields}

    async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        arguments = thaw_plain(call.arguments)
        return ToolResult(
            call_id=call.call_id,
            content=f"{name} recorded",
            details={
                "tool_name": name,
                "writes_object_type": DOMAIN_TOOL_OUTPUTS.get(name, ""),
            },
            trace_proposals=(
                TraceProposal(
                    proposal_id=f"trace-{call.call_id}",
                    event_type="domain_tool_invoked",
                    actor=context.agent_id,
                    payload={
                        "tool_name": name,
                        "writes_object_type": DOMAIN_TOOL_OUTPUTS.get(name, ""),
                        "arguments": arguments,
                    },
                ),
            ),
        )

    return ToolDefinition(
        name=name,
        description=(
            f"Structured domain operation; auditable target object: "
            f"{DOMAIN_TOOL_OUTPUTS.get(name, 'none')}."
        ),
        input_schema={
            "type": "object",
            "properties": properties,
            "required": list(fields),
            "additionalProperties": False,
        },
        handler=handler,
    )


def _field_schema(name: str) -> Mapping[str, Any]:
    if name in {"events", "actors", "hypotheses", "evidence_refs", "nodes", "edges", "outcomes", "assumptions", "unknowns", "decision_questions", "deliverables", "safety_boundaries", "observations", "aliases", "models", "dimensions", "capabilities", "constraints", "dependencies", "handoffs", "supplies", "failure_modes", "packet_ids", "open_questions", "theory", "cases", "frontier", "questions", "input_refs", "evidence_ids", "options", "technology_options", "domains", "candidate_branches", "secondary_branches", "secondary_drivers", "driver_scores", "evidence_signals", "emphasis_steps", "agent_ids", "required_outputs", "waves", "stop_conditions", "decision_points", "causes", "mechanisms", "effects", "counterfactuals", "case_ids", "common_patterns", "differences", "transfer_boundaries", "mission_effects", "enablers", "triggers", "changes", "milestones", "mission_threads", "dependency_path", "cascading_effects", "alternatives", "missions", "interfaces", "drivers", "affected_missions", "warning_indicators", "stakeholders", "civilian_impacts", "allowed_responses", "clusters", "conflicts", "candidates", "criteria", "scores", "ranking", "coverage_matrix", "ooda_nodes", "vulnerabilities", "expected_effects", "risks", "principles", "tradeoffs", "dotmlpf", "equipment_functions", "issues", "missing_evidence", "retry_guidance", "broken_links", "rerun_guidance", "findings", "limitations", "key_indicators", "supporting_scenarios", "evidence_chain", "system_dependencies", "verification"}:
        return {"type": "array"}
    if name in {"confidence", "information_gain"}:
        return {"type": "number", "minimum": 0, "maximum": 1}
    if name in {"step"}:
        return {"type": "integer", "minimum": 1}
    if name in {"coverage", "baseline", "distributed", "resource_constrained", "recovery", "result", "resolution", "loop_policy", "quality_state", "parallelism", "fallback_policy", "budget", "budget_state", "available_agent_capabilities", "custom_blueprint", "next_action"}:
        return {"type": "object"}
    return {"type": "string", "minLength": 1}


__all__ = ["DOMAIN_TOOL_OUTPUTS", "build_domain_tool_definitions"]
