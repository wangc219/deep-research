"""Platform-native composition for one directed deep-research Agent.

A main Agent is a bounded combination of model, system prompt, tools,
Skills, MCP servers and specialized SubAgents.  Resource fields follow
Platform selection semantics:

* omitted or ``null`` uses every currently accessible resource;
* an explicit empty list disables that class of resource;
* a non-empty list keeps only still-accessible items, in the saved order.

Identity, S6 confirmation and durable commit remain host-owned.  A custom
system prompt is appended after the identity lock and cannot replace it.
SubAgents cannot spawn further children.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.deep_runtime.planner import ALLOWED_TOOLS

AGENT_SPEC_SCHEMA = "deep-agent-spec-v1"
_MAX_PROMPT_CHARS = 4000
_MAX_RESOURCE_ITEMS = 16
_MAX_SKILLS = 6
_ALWAYS_TOOLS = frozenset({"help", "inspect_memory"})
RESEARCH_TOOLS = tuple(name for name in ALLOWED_TOOLS if name not in _ALWAYS_TOOLS)


def _text(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def _string_list(value: Any, *, limit: int, item_limit: int = 140) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    items: list[str] = []
    for item in value:
        text = _text(item, item_limit)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def parse_resource_selection(raw: Any, *, limit: int = _MAX_RESOURCE_ITEMS) -> tuple[str, ...] | None:
    """Return ``None`` for all-accessible, otherwise an explicit ordered subset."""

    if raw is None:
        return None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    return tuple(_string_list(raw, limit=limit))


def resolve_resource_selection(
    selection: tuple[str, ...] | None,
    available: Sequence[str],
) -> tuple[str, ...]:
    """Intersect a saved selection with currently accessible identifiers."""

    accessible = tuple(item for item in (_text(value, 140) for value in available) if item)
    if selection is None:
        return accessible
    allowed = set(accessible)
    return tuple(item for item in selection if item in allowed)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One composed Agent snapshot used by the directed dialogue runtime."""

    model_profile_id: str = ""
    system_prompt: str = ""
    tools: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None
    preload_skills: tuple[str, ...] = ()
    mcps: tuple[str, ...] | None = None
    subagents: tuple[str, ...] | None = None
    enable_subagents: bool | None = None

    @classmethod
    def from_mapping(cls, raw: Any) -> "AgentSpec":
        source = raw if isinstance(raw, Mapping) else {}
        tools = parse_resource_selection(source.get("tools"), limit=len(ALLOWED_TOOLS))
        if tools is not None:
            tools = tuple(name for name in tools if name in ALLOWED_TOOLS)
        skills = parse_resource_selection(source.get("skills"), limit=_MAX_SKILLS)
        preload = tuple(
            item
            for item in _string_list(source.get("preload_skills"), limit=_MAX_SKILLS, item_limit=140)
            if skills is None or item in skills
        )
        enable_raw = source.get("enable_subagents", source.get("subagents_enabled"))
        enable_subagents = None if enable_raw is None else bool(enable_raw)
        subagents = parse_resource_selection(source.get("subagents"))
        if enable_subagents is False:
            subagents = ()
        mcps_raw = source.get("mcps") if "mcps" in source else source.get("mcp_servers")
        return cls(
            model_profile_id=_text(source.get("model_profile_id"), 128),
            system_prompt=_text(source.get("system_prompt"), _MAX_PROMPT_CHARS),
            tools=tools,
            skills=skills,
            preload_skills=preload,
            mcps=parse_resource_selection(mcps_raw),
            subagents=subagents,
            enable_subagents=enable_subagents,
        )

    @property
    def subagents_enabled(self) -> bool:
        if self.enable_subagents is False:
            return False
        if self.subagents == ():
            return False
        return True

    def resolved_tools(self, available: Sequence[str] = ALLOWED_TOOLS) -> tuple[str, ...]:
        selected = resolve_resource_selection(self.tools, available)
        return tuple(dict.fromkeys((*selected, *sorted(_ALWAYS_TOOLS & set(available)))))

    def resolved_skills(self, available: Sequence[str]) -> tuple[str, ...]:
        selected = resolve_resource_selection(self.skills, available)
        preload = tuple(item for item in self.preload_skills if item in selected)
        return tuple(dict.fromkeys((*preload, *selected)))[:_MAX_SKILLS]

    def resolved_mcps(self, available: Sequence[str]) -> tuple[str, ...]:
        return resolve_resource_selection(self.mcps, available)

    def resolved_subagents(self, available: Sequence[str]) -> tuple[str, ...]:
        if not self.subagents_enabled:
            return ()
        return resolve_resource_selection(self.subagents, available)

    def overlay_prompt(self, identity: str) -> str:
        """Append operator instructions after the host identity lock."""

        identity_text = str(identity or "").strip()
        overlay = self.system_prompt
        if not overlay:
            return identity_text
        if not identity_text:
            return overlay
        return f"{identity_text}\n\n[Operator system prompt]\n{overlay}"[: len(identity_text) + _MAX_PROMPT_CHARS + 40]

    def public_payload(self) -> dict[str, Any]:
        def encode(value: tuple[str, ...] | None) -> list[str] | None:
            return None if value is None else list(value)

        return {
            "schema_version": AGENT_SPEC_SCHEMA,
            "model_profile_id": self.model_profile_id,
            "system_prompt": self.system_prompt,
            "tools": encode(self.tools),
            "skills": encode(self.skills),
            "preload_skills": list(self.preload_skills),
            "mcps": encode(self.mcps),
            "subagents": encode(self.subagents),
            "enable_subagents": self.subagents_enabled,
            "resource_semantics": {
                "omitted_or_null": "all_accessible",
                "empty_list": "disabled",
                "explicit_list": "intersection_with_accessible",
            },
        }


def spec_from_payload(payload: Mapping[str, Any] | None) -> AgentSpec:
    """Read a turn payload, preferring an explicit spec over flat aliases."""

    source = payload if isinstance(payload, Mapping) else {}
    parent = source.get("deep_parent_context")
    parent = parent if isinstance(parent, Mapping) else {}
    raw = source.get("agent_spec")
    if not isinstance(raw, Mapping):
        raw = parent.get("agent_spec")
    spec = AgentSpec.from_mapping(raw if isinstance(raw, Mapping) else {})
    aliases: dict[str, Any] = {}
    if spec.model_profile_id:
        aliases["model_profile_id"] = spec.model_profile_id
    elif _text(source.get("model_profile_id") or parent.get("model_profile_id"), 128):
        aliases["model_profile_id"] = _text(source.get("model_profile_id") or parent.get("model_profile_id"), 128)
    if spec.skills is None and "active_skill_ids" in source:
        aliases["skills"] = source.get("active_skill_ids")
    elif spec.skills is None and "active_skill_ids" in parent:
        aliases["skills"] = parent.get("active_skill_ids")
    if spec.mcps is None and "mcp_servers" in source:
        aliases["mcps"] = source.get("mcp_servers")
    if spec.enable_subagents is None and "enable_subagents" in source:
        aliases["enable_subagents"] = source.get("enable_subagents")
    if aliases:
        merged = {**spec.public_payload(), **aliases}
        spec = AgentSpec.from_mapping(merged)
    return spec


def composition_catalog(
    *,
    tools: Sequence[str] = ALLOWED_TOOLS,
    subagents: Sequence[Mapping[str, Any]] = (),
    mcp_servers: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Public catalog fragment describing how an Agent can be assembled."""

    return {
        "schema_version": AGENT_SPEC_SCHEMA,
        "resource_semantics": {
            "tools": "omitted=all; empty=none; list=intersection",
            "skills": "omitted=all; empty=none; list=intersection",
            "mcps": "omitted=all; empty=none; list=intersection",
            "subagents": "omitted=all; empty=none; list=intersection",
        },
        "identity_lock": "system_prompt_appends_after_identity",
        "subagent_nesting": False,
        "parallel_dispatch": "start_then_await",
        "tools": [
            {
                "tool_id": name,
                "required": name in _ALWAYS_TOOLS,
            }
            for name in tools
        ],
        "subagents": [dict(item) for item in list(subagents)[:16] if isinstance(item, Mapping)],
        "mcp_servers": [dict(item) for item in list(mcp_servers)[:16] if isinstance(item, Mapping)],
    }


__all__ = [
    "AGENT_SPEC_SCHEMA",
    "AgentSpec",
    "RESEARCH_TOOLS",
    "composition_catalog",
    "parse_resource_selection",
    "resolve_resource_selection",
    "spec_from_payload",
]
