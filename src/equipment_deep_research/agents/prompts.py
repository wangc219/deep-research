"""Role-local baseline prompts; no agent receives another agent's raw session."""

from __future__ import annotations

from typing import Any

from equipment_deep_research.agents.registry import AgentDef


class BaselinePromptBuilder:
    def build(self, *, agent: AgentDef, route: str, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        contract = agent.output_contract if isinstance(agent.output_contract, dict) else {"name": agent.output_contract}
        return {
            "role": agent.display_name,
            "objective": agent.description,
            "route": route,
            "task": task,
            "visible_context": context,
            "allowed_tools": list(agent.tools),
            "output_contract": contract,
            "evidence_rule": "只引用已材料化 EvidenceCard；不能将模型口述 URL 作为正式证据。",
        }
