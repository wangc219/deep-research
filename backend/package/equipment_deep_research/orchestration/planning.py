"""Capability-driven Map-Reduce-Refine research planning."""

from __future__ import annotations

from equipment_deep_research.contracts.agents import AgentSpec
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.domain.planning import ResearchPlanGraph, ResearchPlanNode
from equipment_deep_research.orchestration.coverage import PresetPolicy


_TOPIC_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "situation": (
        "国际形势", "战略格局", "联盟", "地缘", "对手动向", "态势",
        "国外", "外军", "西太", "亚太", "印太", "台海", "南海", "地区安全",
    ),
    "threat": ("威胁", "风险预警", "敌情"),
    "scenario": ("场景", "战场环境", "环境约束", "任务阶段", "时间窗口", "战区", "coa"),
    "equipment": ("装备", "型号", "参数", "平台", "载荷"),
    "technology_readiness": ("技术成熟度", "在研", "工程化", "试验验证"),
    "capability_gap": ("能力差距", "缺口", "空白", "升级"),
    "operation": ("作战", "作战运用", "战法", "任务链", "部署", "打击", "反制", "防御"),
    "coordination": ("协同", "联合", "体系组合", "有人无人"),
    "lessons": ("战例", "战争案例", "冲突复盘", "经验教训"),
}


class ResearchPlanner:
    def __init__(self, policy: PresetPolicy) -> None:
        self.policy = policy

    def build(self, problem: ResearchProblem, selected_agents: list[AgentSpec]) -> ResearchPlanGraph:
        # Agent selection is a preceding orchestration decision.  The graph must
        # faithfully represent that audited decision, including any model-chosen
        # specialist beyond the mandatory minimum.
        selected = list(selected_agents)
        map_nodes = [ResearchPlanNode(f"map:{agent.agent_id}", "baseline_map", [], "pending", agent.agent_id, list(agent.capability_tags)) for agent in selected]
        reduce_node = ResearchPlanNode("reduce:baseline", "baseline_reduce", [node.node_id for node in map_nodes], "pending", "winning_mechanism", [])
        winning = ResearchPlanNode("winning:L1-L3", "winning_mechanism", [reduce_node.node_id], "pending", "winning_mechanism", ["winning_mechanism"])
        audit = ResearchPlanNode("audit:five-criteria", "audit", [winning.node_id], "pending", "auditor", ["audit"])
        report = ResearchPlanNode("report:final", "report", [audit.node_id], "pending", "reporter", ["report"])
        return ResearchPlanGraph([*map_nodes, reduce_node, winning, audit, report])

    def select_for_problem(
        self,
        problem: ResearchProblem,
        candidates: list[AgentSpec],
        preferred_agent_ids: list[str] | None = None,
        additional_required_tags: set[str] | None = None,
    ) -> list[AgentSpec]:
        """Reconcile a model preference with mandatory capability coverage."""
        required = self.required_tags_for_problem(problem) | set(
            additional_required_tags or set()
        )
        by_id = {agent.agent_id: agent for agent in candidates}
        preferred = [
            by_id[agent_id]
            for agent_id in preferred_agent_ids or []
            if agent_id in by_id
        ]
        if preferred:
            # A model may recommend useful reference roles, but the baseline is
            # intentionally the minimum sufficient research set.  Retain only
            # preferred roles that contribute to mandatory or topic-explicit
            # capability coverage; L3/L4 can add reference roles on demand.
            selected = self._minimal_cover_tags(required, preferred)
            covered = {tag for agent in selected for tag in agent.capability_tags}
            missing = required - covered
            additions = self._minimal_cover_tags(missing, candidates) if missing else []
            for agent in additions:
                if agent.agent_id not in {item.agent_id for item in selected}:
                    selected.append(agent)
            return selected
        return self._minimal_cover_tags(required, candidates) if required else candidates

    def required_tags_for_problem(self, problem: ResearchProblem) -> set[str]:
        route = problem.resolved_route()
        required = set(self.policy.required_capability_tags.get(route, []))
        normalized_topic = problem.analysis_text().lower()
        for tag, hints in _TOPIC_CAPABILITY_HINTS.items():
            if any(hint.lower() in normalized_topic for hint in hints):
                required.add(tag)
        return required

    def _minimal_cover(self, route: str, agents: list[AgentSpec]) -> list[AgentSpec]:
        required = set(self.policy.required_capability_tags.get(route, []))
        return self._minimal_cover_tags(required, agents)

    @staticmethod
    def _minimal_cover_tags(required: set[str], agents: list[AgentSpec]) -> list[AgentSpec]:
        remaining = set(required)
        candidates = list(agents)
        result: list[AgentSpec] = []
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
