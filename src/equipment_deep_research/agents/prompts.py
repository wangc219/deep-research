"""Role-local baseline prompts; no agent receives another agent's raw session."""

from __future__ import annotations

from typing import Any

from equipment_deep_research.agents.designs import AgentDesignRegistry
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.runtime_profiles import military_mission_lens


_AGENT_DESIGNS = AgentDesignRegistry.load_default()


class BaselinePromptBuilder:
    def build(
        self,
        *,
        agent: AgentDef,
        route: str,
        task: dict[str, Any],
        context: dict[str, Any],
        compact_runtime: bool = False,
    ) -> dict[str, Any]:
        contract = (
            agent.output_contract
            if isinstance(agent.output_contract, dict)
            else {"name": agent.output_contract}
        )
        visible_context = dict(context)
        if compact_runtime:
            # Role, tools, skill, policy and output schema are compiled once in
            # agent_runtime.  The assignment carries only task facts and
            # dependency deltas; repeating governance text distracts the model
            # from the military business judgment.
            visible_context = {
                key: value
                for key, value in visible_context.items()
                if key
                in {
                    "task",
                    "evidence_policy",
                    "recall_request",
                    "upstream_handoffs",
                    "discovery_blueprint",
                    "structured_query_brief",
                    "source_priorities",
                    "incremental_knowledge",
                }
                and value not in (None, "", [], {})
            }
        prompt = (
            {
                "role": agent.display_name,
                "objective": agent.description,
                "task": task,
                "context": visible_context,
                "output_rule": "只输出当前结构化契约需要的业务结论、证据、置信度、限制和下一步建议，不描述执行流程。",
                "military_value_rule": military_mission_lens(agent.agent_id),
                "safety": "公开来源、任务级能力研究；不输出坐标、攻击步骤或可直接执行参数。",
            }
            if compact_runtime
            else {
                "role": agent.display_name,
                "objective": agent.description,
                "route": route,
                "task": task,
                "visible_context": visible_context,
                "evidence_rule": "只引用已材料化 EvidenceCard；不能将模型口述 URL 作为正式证据。",
                "workflow_rule": "先形成检索问题树，再按主题分轨检索、交叉验证、识别反证与不确定性，最后输出可供下游消费的结构化交接。",
                "safety_boundary": "仅使用公开来源开展战略、能力与防御性需求研究；不输出实时目标定位、具体攻击步骤或可直接执行的伤害行动指令。",
            }
        )
        if not compact_runtime:
            prompt.update(
                {
                    "allowed_tools": list(agent.tools),
                    "skills": agent.skills,
                    "research_policy": agent.research_policy,
                    "handoff_policy": agent.handoff_policy,
                    "output_contract": contract,
                }
            )
        try:
            role_guidance = _AGENT_DESIGNS.get(agent.agent_id).prompt_guidance()
        except KeyError:
            role_guidance = {}
        if role_guidance:
            prompt["role_guidance"] = role_guidance
        if compact_runtime:
            prompt.pop("role_guidance", None)
        return prompt
