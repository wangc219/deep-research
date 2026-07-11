from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from equipment_deep_research.agents.registry import AgentDef


KNOWN_TOOLS = {
    "search_sources",
    "fetch_page",
    "create_evidence_card",
    "write_stage_output",
    "create_recall_request",
    "create_capability_image",
    "write_audit",
    "write_report",
}


@dataclass(frozen=True)
class ToolScopeRequirement:
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_scopes", tuple(self.read_scopes))
        object.__setattr__(self, "write_scopes", tuple(self.write_scopes))


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


@dataclass(frozen=True)
class ToolPermissionRegistry:
    known_tools: set[str]

    @classmethod
    def default(cls) -> "ToolPermissionRegistry":
        return cls(known_tools=set(KNOWN_TOOLS))

    def validate_agent_tools(self, agent: AgentDef) -> None:
        unknown = sorted(set(agent.tools) - self.known_tools)
        if unknown:
            raise ValueError(f"agent {agent.agent_id} declares unknown tools: {unknown}")

    def enforce_active_tool(self, agent: AgentDef, tool_name: str) -> None:
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


def _coerce_requirement(
    value: ToolScopeRequirement | Mapping[str, Any],
) -> ToolScopeRequirement:
    if isinstance(value, ToolScopeRequirement):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("tool scope requirements must be objects")
    read = value.get("read_scopes", value.get("object_read_scopes", ()))
    write = value.get("write_scopes", value.get("object_write_scopes", ()))
    return ToolScopeRequirement(tuple(read), tuple(write))


__all__ = [
    "DEFAULT_TOOL_SCOPE_REQUIREMENTS",
    "KNOWN_TOOLS",
    "ToolAuthorizationPolicy",
    "ToolPermissionRegistry",
    "ToolScopeRequirement",
]
