from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from equipment_deep_research.agents.contracts import (
    DEFAULT_MODEL_PROFILE,
    LEGACY_SYSTEM_AGENT_IDS,
    OBJECT_SCOPE_CATALOG,
    TOOL_CATALOG,
    VISIBLE_SECTION_CATALOG,
    default_output_contract,
    validate_model_profile,
    validate_named_contract,
)
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
    input_contract: str | dict[str, Any] = "research_task"
    output_contract: str | dict[str, Any] = "baseline_finding_packet"
    object_read_scopes: list[str] = field(default_factory=list)
    object_write_scopes: list[str] = field(default_factory=list)
    model_profile: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_PROFILE)
    )
    system_agent: bool = False

    def validate(self) -> None:
        validate_internal_identifier(self.agent_id, field_name="agent_id")
        capabilities = [tag for tag in self.capability_tags if str(tag).strip()]
        if not capabilities or len(capabilities) != len(self.capability_tags):
            raise ValueError(f"agent {self.agent_id} requires non-empty capability_tags")

        unknown_tools = sorted(set(self.tools) - TOOL_CATALOG)
        if unknown_tools:
            raise ValueError(
                f"agent {self.agent_id} declares unknown tools: {unknown_tools}"
            )

        validate_named_contract(self.input_contract, field_name="input_contract")
        validate_named_contract(self.output_contract, field_name="output_contract")

        visible_sections = self.context_policy.get("visible_sections", [])
        if not isinstance(visible_sections, list):
            raise ValueError("context_policy visible_sections must be a list")
        unknown_sections = sorted(set(visible_sections) - VISIBLE_SECTION_CATALOG)
        if unknown_sections:
            raise ValueError(
                f"agent {self.agent_id} declares unknown visible sections: "
                f"{unknown_sections}"
            )

        _validate_scopes(
            self.agent_id,
            self.object_read_scopes,
            scope_kind="read",
        )
        _validate_scopes(
            self.agent_id,
            self.object_write_scopes,
            scope_kind="write",
        )
        validate_model_profile(self.model_profile)


class AgentRegistry:
    def __init__(self, agents: dict[str, AgentDef], default_model: str) -> None:
        self._agents = dict(agents)
        self.default_model = default_model

    @classmethod
    def load(cls, path: str | Path) -> "AgentRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, Mapping):
            raise ValueError("agent registry configuration must be an object")
        rows = data.get("agents", [])
        if not isinstance(rows, list):
            raise ValueError("agents must be a list")
        agents: dict[str, AgentDef] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("each agent definition must be an object")
            agent_id = validate_internal_identifier(
                str(row["agent_id"]),
                field_name="agent_id",
            )
            if agent_id in agents:
                raise ValueError(f"duplicate agent_id: {agent_id}")
            input_contract = row.get("input_contract", "research_task")
            output_contract = row.get(
                "output_contract",
                default_output_contract(agent_id),
            )
            model_profile = row.get("model_profile", DEFAULT_MODEL_PROFILE)
            if not isinstance(model_profile, Mapping):
                raise ValueError("model_profile must be an object")
            agent = AgentDef(
                agent_id=agent_id,
                display_name=str(row.get("display_name", row["agent_id"])),
                description=str(row.get("description", "")),
                capability_tags=list(row.get("capability_tags", [])),
                tools=list(row.get("tools", [])),
                context_policy=dict(row.get("context_policy", {})),
                enabled=bool(row.get("enabled", True)),
                input_contract=_copy_contract(input_contract),
                output_contract=_copy_contract(output_contract),
                object_read_scopes=list(row.get("object_read_scopes", [])),
                object_write_scopes=list(row.get("object_write_scopes", [])),
                model_profile=dict(model_profile),
                system_agent=bool(
                    row.get(
                        "system_agent",
                        row.get("is_system", agent_id in LEGACY_SYSTEM_AGENT_IDS),
                    )
                ),
            )
            agent.validate()
            agents[agent.agent_id] = agent
        return cls(agents=agents, default_model=str(data.get("default_model", "gpt-5.5")))

    def get(self, agent_id: str) -> AgentDef:
        if agent_id not in self._agents:
            raise KeyError(f"unknown agent_id: {agent_id}")
        return self._agents[agent_id]

    def enabled_baseline_agents(self) -> list[AgentDef]:
        return [
            agent
            for agent in self._agents.values()
            if agent.enabled and not agent.system_agent
        ]

    def select_agents(self, requested_ids: list[str] | None = None) -> list[AgentDef]:
        if requested_ids:
            return [self.get(agent_id) for agent_id in requested_ids]
        return self.enabled_baseline_agents()

    def agents_for_capability(self, tag: str, selected: list[AgentDef]) -> list[AgentDef]:
        return [agent for agent in selected if tag in agent.capability_tags]

    def resolve_capability(
        self,
        tag: str,
        selected: list[AgentDef] | None = None,
    ) -> AgentDef:
        candidates = self.agents_for_capability(
            tag,
            self.select_agents() if selected is None else selected,
        )
        if not candidates:
            raise KeyError(f"no selected agent provides capability: {tag}")
        return candidates[0]

    def all_agent_ids(self) -> list[str]:
        return sorted(self._agents)


def _copy_contract(value: Any) -> str | dict[str, Any]:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("agent contracts must be a name or object")


def _validate_scopes(
    agent_id: str,
    scopes: list[str],
    *,
    scope_kind: str,
) -> None:
    unknown = sorted(set(scopes) - OBJECT_SCOPE_CATALOG)
    if unknown:
        raise ValueError(
            f"agent {agent_id} declares unknown object {scope_kind} scopes: {unknown}"
        )
