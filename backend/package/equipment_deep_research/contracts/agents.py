"""Stable protocols for agent metadata consumed by other layers.

The executable registry lives in ``agents.registry``.  Planning, routing and
tool authorization only need this small structural contract, so they should
not import the registry implementation and its prompt/provider dependencies.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class AgentSpec(Protocol):
    agent_id: str
    capability_tags: Sequence[str]
    tools: Sequence[str]
    object_read_scopes: Sequence[str]
    object_write_scopes: Sequence[str]
    enabled: bool
    system_agent: bool
    handoff_policy: dict[str, Any]


class AgentCatalog(Protocol):
    def get(self, agent_id: str) -> AgentSpec: ...

    def agents_for_capability(
        self,
        tag: str,
        selected: list[AgentSpec],
    ) -> list[AgentSpec]: ...


__all__ = ["AgentCatalog", "AgentSpec"]
