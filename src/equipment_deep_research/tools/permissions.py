from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from equipment_deep_research.contracts.agents import AgentSpec
from equipment_deep_research.domain.proposals import TraceProposal, thaw_plain
from equipment_deep_research.tools.definitions import ToolResult
from equipment_deep_research.tools.domain_tools import DOMAIN_TOOL_OUTPUTS


KNOWN_TOOLS = {
    "search_sources",
    "fetch_page",
    "create_evidence_card",
    "write_stage_output",
    "create_recall_request",
    "create_capability_image",
    "write_audit",
    "write_report",
    "register_event_timeline", "compare_actor_positions", "register_warning_indicator", "test_competing_hypothesis",
    "build_scenario_graph", "branch_scenario", "map_critical_window", "map_environment_constraint", "stress_test_scenario",
    "extract_parameter_observation", "normalize_equipment_variant", "reconcile_parameter_conflict", "assess_technology_readiness", "compare_equipment_capability", "map_defensive_countermeasure", "formulate_equipment_requirement",
    "map_task_capability", "build_coordination_dependency", "compare_coa", "assess_sustainment_resilience", "transfer_case_lesson",
    "prepare_winning_input", "project_winning_resources", "write_reasoning_node",
    "analyze_research_request", "classify_discovery_drivers", "build_discovery_blueprint", "plan_execution_waves", "evaluate_loop_transition",
    "reconstruct_case_timeline", "build_causal_chain", "compare_case_patterns",
    "assess_technology_potential", "construct_disruptive_scenario", "detect_baseline_change", "estimate_capability_formation",
    "build_system_model", "identify_cascading_vulnerability", "build_cross_domain_matrix", "identify_interface_gap",
    "scan_emerging_threat", "assess_legal_ethical_boundary", "cluster_demand_signals", "rank_capability_priorities",
    "analyze_ooda_vulnerability", "generate_counterfactual_option", "apply_triz_contradiction", "map_dotmlpf_requirement",
    "evaluate_reasoning_step", "evaluate_reasoning_round", "evaluate_release_readiness", "build_capability_demand_card",
}


def effective_tool_names(
    *,
    agent_allowlist: Iterable[str],
    task_allowlist: Iterable[str],
    skill_allowlists: Iterable[Iterable[str]],
    phase_allowlist: Iterable[str],
) -> tuple[str, ...]:
    """Return Agent ∩ Task ∩ Active Skills ∩ Phase in agent declaration order."""
    agent = tuple(dict.fromkeys(str(item) for item in agent_allowlist))
    allowed = set(str(item) for item in task_allowlist) & set(
        str(item) for item in phase_allowlist
    )
    skills = [set(str(item) for item in values) for values in skill_allowlists]
    if skills:
        allowed &= set.union(*skills)
    return tuple(name for name in agent if name in allowed)


@dataclass(frozen=True)
class ToolScopeRequirement:
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    allowed_write_types: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_scopes", tuple(self.read_scopes))
        object.__setattr__(self, "write_scopes", tuple(self.write_scopes))
        allowed = self.write_scopes if self.allowed_write_types is None else self.allowed_write_types
        object.__setattr__(self, "allowed_write_types", tuple(allowed))


DEFAULT_TOOL_SCOPE_REQUIREMENTS: dict[str, ToolScopeRequirement] = {
    "search_sources": ToolScopeRequirement(),
    "fetch_page": ToolScopeRequirement(),
    "create_evidence_card": ToolScopeRequirement(write_scopes=("EvidenceCard",)),
    "write_stage_output": ToolScopeRequirement(
        write_scopes=("WinningMechanismStageOutput",)
    ),
    "create_recall_request": ToolScopeRequirement(write_scopes=("RecallRequest",)),
    "create_capability_image": ToolScopeRequirement(
        write_scopes=("CapabilityImageItem",)
    ),
    "write_audit": ToolScopeRequirement(write_scopes=("AuditResult",)),
    "write_report": ToolScopeRequirement(write_scopes=("ResearchReport",)),
}
DEFAULT_TOOL_SCOPE_REQUIREMENTS.update(
    {
        tool_name: ToolScopeRequirement(
            write_scopes=(object_type,),
            allowed_write_types=(object_type,),
        )
        for tool_name, object_type in DOMAIN_TOOL_OUTPUTS.items()
    }
)


@dataclass(frozen=True)
class ToolPermissionRegistry:
    known_tools: set[str]

    @classmethod
    def default(cls) -> "ToolPermissionRegistry":
        return cls(known_tools=set(KNOWN_TOOLS))

    def validate_agent_tools(self, agent: AgentSpec) -> None:
        unknown = sorted(set(agent.tools) - self.known_tools)
        if unknown:
            raise ValueError(f"agent {agent.agent_id} declares unknown tools: {unknown}")

    def enforce_active_tool(self, agent: AgentSpec, tool_name: str) -> None:
        if tool_name not in self.known_tools:
            raise ValueError(f"unknown tool: {tool_name}")
        if tool_name not in agent.tools:
            raise PermissionError(f"agent {agent.agent_id} cannot use tool {tool_name}")


class ToolAuthorizationPolicy:
    """Per-call authorization for active tools and domain object scopes."""

    def __init__(
        self,
        scope_requirements: Mapping[
            str, ToolScopeRequirement | Mapping[str, Any]
        ] | None = None,
    ) -> None:
        source: dict[str, ToolScopeRequirement | Mapping[str, Any]] = dict(
            DEFAULT_TOOL_SCOPE_REQUIREMENTS
        )
        if scope_requirements is not None:
            source.update(scope_requirements)
        self.scope_requirements = {
            str(name): _coerce_requirement(requirement)
            for name, requirement in source.items()
        }

    @classmethod
    def default(cls) -> "ToolAuthorizationPolicy":
        return cls()

    def authorize(
        self,
        tool_name: str,
        *,
        active_tool_names: Iterable[str],
        object_read_scopes: Iterable[str] = (),
        object_write_scopes: Iterable[str] = (),
    ) -> None:
        active = frozenset(active_tool_names)
        if tool_name not in active:
            raise PermissionError(
                f"tool {tool_name} is not in the active tool allowlist"
            )

        requirement = self.scope_requirements.get(tool_name, ToolScopeRequirement())
        readable = frozenset(object_read_scopes)
        writable = frozenset(object_write_scopes)
        missing_read = sorted(set(requirement.read_scopes) - readable)
        missing_write = sorted(set(requirement.write_scopes) - writable)
        if missing_read or missing_write:
            details: list[str] = []
            if missing_read:
                details.append(f"missing read scopes {missing_read}")
            if missing_write:
                details.append(f"missing write scopes {missing_write}")
            raise PermissionError(f"tool {tool_name} denied: {'; '.join(details)}")

    def authorize_result(
        self,
        tool_name: str,
        result: ToolResult,
        *,
        active_tool_names: Iterable[str],
        object_read_scopes: Iterable[str] = (),
        object_write_scopes: Iterable[str] = (),
        agent_id: str,
        call_id: str,
    ) -> ToolResult:
        self.authorize(
            tool_name,
            active_tool_names=active_tool_names,
            object_read_scopes=object_read_scopes,
            object_write_scopes=object_write_scopes,
        )
        requirement = self.scope_requirements.get(tool_name, ToolScopeRequirement())
        task_writable = frozenset(object_write_scopes)
        tool_writable = frozenset(requirement.allowed_write_types or ())
        denied = sorted(
            {
                proposal.object_type
                for proposal in result.domain_proposals
                if proposal.object_type not in task_writable
                or proposal.object_type not in tool_writable
            }
        )
        if denied:
            raise PermissionError(
                f"tool {tool_name} returned unauthorized object types: {denied}"
            )

        controlled_traces = tuple(
            TraceProposal(
                proposal_id=proposal.proposal_id,
                event_type=proposal.event_type,
                actor=agent_id,
                payload={
                    **thaw_plain(proposal.payload),
                    "tool_name": tool_name,
                    "tool_call_id": call_id,
                },
            )
            for proposal in result.trace_proposals
        )
        return ToolResult(
            call_id=result.call_id,
            content=result.content,
            details=result.details,
            domain_proposals=result.domain_proposals,
            trace_proposals=controlled_traces,
            is_error=result.is_error,
        )


def _coerce_requirement(
    value: ToolScopeRequirement | Mapping[str, Any],
) -> ToolScopeRequirement:
    if isinstance(value, ToolScopeRequirement):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("tool scope requirements must be objects")
    read = value.get("read_scopes", value.get("object_read_scopes", ()))
    write = value.get("write_scopes", value.get("object_write_scopes", ()))
    allowed = value.get("allowed_write_types")
    return ToolScopeRequirement(
        tuple(read),
        tuple(write),
        None if allowed is None else tuple(allowed),
    )


__all__ = [
    "DEFAULT_TOOL_SCOPE_REQUIREMENTS",
    "KNOWN_TOOLS",
    "ToolAuthorizationPolicy",
    "ToolPermissionRegistry",
    "ToolScopeRequirement",
    "effective_tool_names",
]
