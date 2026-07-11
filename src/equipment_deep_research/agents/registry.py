from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from equipment_deep_research.domain.identifiers import validate_internal_identifier


@dataclass(frozen=True)
class AgentDef:
    agent_id: str
    display_name: str
    description: str
    capability_tags: list[str]
    tools: list[str]
    context_policy: dict[str, Any]
    enabled: bool = True
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    object_read_scopes: list[str] = field(default_factory=list)
    object_write_scopes: list[str] = field(default_factory=list)


class AgentRegistry:
    def __init__(self, agents: dict[str, AgentDef], default_model: str) -> None:
        self._agents = dict(agents)
        self.default_model = default_model

    @classmethod
    def load(cls, path: str | Path) -> "AgentRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        agents: dict[str, AgentDef] = {}
        for row in data.get("agents", []):
            agent_id = validate_internal_identifier(
                str(row["agent_id"]),
                field_name="agent_id",
            )
            agent = AgentDef(
                agent_id=agent_id,
                display_name=str(row.get("display_name", row["agent_id"])),
                description=str(row.get("description", "")),
                capability_tags=list(row.get("capability_tags", [])),
                tools=list(row.get("tools", [])),
                context_policy=dict(row.get("context_policy", {})),
                enabled=bool(row.get("enabled", True)),
                input_contract=dict(row.get("input_contract", {})),
                output_contract=dict(row.get("output_contract", {})),
                object_read_scopes=list(row.get("object_read_scopes", [])),
                object_write_scopes=list(row.get("object_write_scopes", [])),
            )
            agents[agent.agent_id] = agent
        return cls(agents=agents, default_model=str(data.get("default_model", "gpt-5.5")))

    def get(self, agent_id: str) -> AgentDef:
        if agent_id not in self._agents:
            raise KeyError(f"unknown agent_id: {agent_id}")
        return self._agents[agent_id]

    def enabled_baseline_agents(self) -> list[AgentDef]:
        excluded = {"winning_mechanism", "auditor", "reporter"}
        return [
            agent
            for agent in self._agents.values()
            if agent.enabled and agent.agent_id not in excluded
        ]

    def select_agents(self, requested_ids: list[str] | None = None) -> list[AgentDef]:
        if requested_ids:
            return [self.get(agent_id) for agent_id in requested_ids]
        return self.enabled_baseline_agents()

    def agents_for_capability(self, tag: str, selected: list[AgentDef]) -> list[AgentDef]:
        return [agent for agent in selected if tag in agent.capability_tags]

    def all_agent_ids(self) -> list[str]:
        return sorted(self._agents)
