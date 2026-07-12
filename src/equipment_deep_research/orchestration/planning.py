"""Capability-driven Map-Reduce-Refine research planning."""

from __future__ import annotations

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.domain.planning import ResearchPlanGraph, ResearchPlanNode
from equipment_deep_research.orchestration.coverage import PresetPolicy


class ResearchPlanner:
    def __init__(self, policy: PresetPolicy) -> None:
        self.policy = policy

    def build(self, problem: ResearchProblem, selected_agents: list[AgentDef]) -> ResearchPlanGraph:
        route = problem.resolved_route()
        selected = self._minimal_cover(route, selected_agents)
        map_nodes = [ResearchPlanNode(f"map:{agent.agent_id}", "baseline_map", [], "pending", agent.agent_id, list(agent.capability_tags)) for agent in selected]
        reduce_node = ResearchPlanNode("reduce:baseline", "baseline_reduce", [node.node_id for node in map_nodes], "pending", "winning_mechanism", [])
        winning = ResearchPlanNode("winning:L1-L3", "winning_mechanism", [reduce_node.node_id], "pending", "winning_mechanism", ["winning_mechanism"])
        audit = ResearchPlanNode("audit:five-criteria", "audit", [winning.node_id], "pending", "auditor", ["audit"])
        report = ResearchPlanNode("report:final", "report", [audit.node_id], "pending", "reporter", ["report"])
        return ResearchPlanGraph([*map_nodes, reduce_node, winning, audit, report])

    def _minimal_cover(self, route: str, agents: list[AgentDef]) -> list[AgentDef]:
        required = set(self.policy.required_capability_tags.get(route, []))
        remaining = set(required)
        candidates = list(agents)
        result: list[AgentDef] = []
        while candidates and remaining:
            candidate = max(candidates, key=lambda item: (len(set(item.capability_tags) & remaining), item.agent_id))
            if not set(candidate.capability_tags) & remaining:
                break
            result.append(candidate)
            remaining -= set(candidate.capability_tags)
            candidates.remove(candidate)
        # Preserve explicit selections that add differentiated capability even when
        # the preset currently has no matching required tag.
        return result or agents
