"""Configurable business routes and their research question chains."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class RoutePolicy:
    route_id: str
    question_chain: list[str]
    required_outputs: list[str]


class RouteRegistry:
    def __init__(self, routes: dict[str, RoutePolicy]) -> None:
        self._routes = routes

    @classmethod
    def load(cls, path: str | Path) -> "RouteRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rows = data.get("routes", {})
        return cls({route_id: RoutePolicy(route_id, list(value.get("question_chain", [])), list(value.get("required_outputs", []))) for route_id, value in rows.items()})

    def get(self, route_id: str) -> RoutePolicy:
        return self._routes[route_id]

    def questions_for(self, route_id: str, capability_tag: str) -> list[str]:
        return [f"{capability_tag}：{question}" for question in self.get(route_id).question_chain]
