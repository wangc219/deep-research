from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.identifiers import validate_internal_identifier


@dataclass(frozen=True)
class RouteWave:
    phase_id: str
    capability_tags: tuple[str, ...] = ()
    system_agent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutePolicy:
    route_id: str
    optional_pre_wave_tags: tuple[str, ...]
    waves: tuple[RouteWave, ...]


class RoutePolicyRegistry:
    def __init__(self, policies: Mapping[str, RoutePolicy]) -> None:
        self.policies = dict(policies)

    @classmethod
    def load(cls, path: str | Path) -> "RoutePolicyRegistry":
        source = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        routes = source.get("routes", {}) if isinstance(source, Mapping) else {}
        if not isinstance(routes, Mapping) or not routes:
            raise ValueError("routes configuration requires a routes object")
        policies: dict[str, RoutePolicy] = {}
        for route_id, raw in routes.items():
            validate_internal_identifier(str(route_id), field_name="route_id")
            if not isinstance(raw, Mapping):
                raise ValueError(f"route {route_id} must be an object")
            waves: list[RouteWave] = []
            seen_phases: set[str] = set()
            for row in raw.get("waves", []):
                if not isinstance(row, Mapping):
                    raise ValueError(f"route {route_id} wave must be an object")
                phase_id = validate_internal_identifier(
                    str(row["phase_id"]), field_name="phase_id"
                )
                if phase_id in seen_phases:
                    raise ValueError(f"route {route_id} has duplicate phase: {phase_id}")
                seen_phases.add(phase_id)
                tags = tuple(str(item) for item in row.get("capability_tags", []))
                system_ids = tuple(str(item) for item in row.get("system_agent_ids", []))
                if not tags and not system_ids:
                    raise ValueError(f"route {route_id} phase {phase_id} has no selectors")
                waves.append(RouteWave(phase_id, tags, system_ids))
            policies[str(route_id)] = RoutePolicy(
                route_id=str(route_id),
                optional_pre_wave_tags=tuple(
                    str(item) for item in raw.get("optional_pre_wave_tags", [])
                ),
                waves=tuple(waves),
            )
        return cls(policies)

    def execution_waves(
        self,
        route_id: str,
        selected: Sequence[AgentDef],
    ) -> list[list[AgentDef]]:
        if route_id not in self.policies:
            raise KeyError(f"unknown route policy: {route_id}")
        policy = self.policies[route_id]
        remaining = list(selected)
        result: list[list[AgentDef]] = []
        optional = [
            agent
            for agent in remaining
            if set(agent.capability_tags) & set(policy.optional_pre_wave_tags)
        ]
        if optional:
            result.append(optional)
            remaining = [agent for agent in remaining if agent not in optional]
        for wave in policy.waves:
            if wave.system_agent_ids:
                continue
            members = [
                agent
                for agent in remaining
                if set(agent.capability_tags) & set(wave.capability_tags)
            ]
            if members:
                result.append(members)
                remaining = [agent for agent in remaining if agent not in members]
        if remaining:
            result.append(remaining)
        return result


@dataclass(frozen=True)
class RouteDefinition:
    route_id: str
    question_chain: tuple[str, ...]
    required_outputs: tuple[str, ...]


class RouteRegistry:
    """Compatibility view for route question chains and required outputs."""

    def __init__(self, routes: Mapping[str, RouteDefinition]) -> None:
        self.routes = dict(routes)

    @classmethod
    def load(cls, path: str | Path) -> "RouteRegistry":
        source = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw_routes = source.get("routes", {}) if isinstance(source, Mapping) else {}
        routes = {
            str(route_id): RouteDefinition(
                route_id=str(route_id),
                question_chain=tuple(str(item) for item in raw.get("question_chain", [])),
                required_outputs=tuple(str(item) for item in raw.get("required_outputs", [])),
            )
            for route_id, raw in raw_routes.items()
            if isinstance(raw, Mapping)
        }
        return cls(routes)

    def get(self, route_id: str) -> RouteDefinition:
        if route_id not in self.routes:
            raise KeyError(f"unknown route: {route_id}")
        return self.routes[route_id]
