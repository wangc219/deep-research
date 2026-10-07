"""Baseline-agent workflow planning independent from provider transport."""

from __future__ import annotations

from typing import Any

from equipment_deep_research.agents.designs import (
    AgentDesign,
    AgentDesignRegistry,
    AgentDesignSpec,
)
from equipment_deep_research.agents.registry import AgentDef


class BaselineAgentService:
    """Resolve role-local behavior while the provider owns model I/O."""

    def __init__(self, designs: AgentDesignRegistry) -> None:
        self.designs = designs

    def design_for(self, agent: AgentDef) -> AgentDesign:
        try:
            return self.designs.get(agent.agent_id)
        except KeyError:
            return AgentDesignSpec(agent.agent_id, agent.description)

    def output_schema(
        self,
        agent: AgentDef,
        base_schema: dict[str, Any],
    ) -> dict[str, Any]:
        schema = dict(base_schema)
        schema.update(self.design_for(agent).output_schema_extensions())
        return schema

    def discovery_system_prompt(self, agent: AgentDef) -> str:
        design = self.design_for(agent)
        return design.discovery_instruction() or (
            "你是公开资料检索Agent。发现可核验来源，优先政府、军方、国际组织、"
            "制造商和权威研究机构；只输出最小事实。"
        )

    def phase_options(self, agent: AgentDef, phase: str) -> dict[str, Any]:
        return dict(self.design_for(agent).phase_options(phase))
