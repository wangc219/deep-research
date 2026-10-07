from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from equipment_deep_research.contracts.agents import AgentSpec


@dataclass(frozen=True)
class PresetPolicy:
    required_capability_tags: dict[str, list[str]]
    optional_capability_tags: dict[str, list[str]]
    gate_policy: dict[str, Any]


def load_preset_policy(path: str | Path, preset_id: str = "default") -> PresetPolicy:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    preset = (data.get("presets") or {}).get(preset_id)
    if not preset:
        raise ValueError(f"unknown workflow preset: {preset_id}")
    return PresetPolicy(
        required_capability_tags=dict(preset.get("required_capability_tags", {})),
        optional_capability_tags=dict(preset.get("optional_capability_tags", {})),
        gate_policy=dict(preset.get("gate_policy", {})),
    )


def coverage_for_route(
    *,
    route: str,
    selected_agents: list[AgentSpec],
    policy: PresetPolicy,
    additional_required_tags: list[str] | None = None,
    discovery_branch: str = "",
) -> dict[str, Any]:
    provided: set[str] = set()
    by_agent: dict[str, list[str]] = {}
    for agent in selected_agents:
        by_agent[agent.agent_id] = list(agent.capability_tags)
        provided.update(agent.capability_tags)
    required = set(policy.required_capability_tags.get(route, []))
    required.update(additional_required_tags or [])
    optional = set(policy.optional_capability_tags.get(route, []))
    missing_required = sorted(required - provided)
    return {
        "route": route,
        "discovery_branch": discovery_branch,
        "provided_tags": sorted(provided),
        "required_tags": sorted(required),
        "optional_tags": sorted(optional),
        "missing_required_tags": missing_required,
        "coverage_passed": not missing_required,
        "by_agent": by_agent,
    }
