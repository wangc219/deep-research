"""Stable request/result contracts for agent execution providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    agent: AgentDef
    topic: str
    research_route: str
    context: dict
    round_index: int = 1


@dataclass(frozen=True)
class AgentRunResult:
    packet: BaselineFindingPacket
    evidence: list[EvidenceCard]
    raw_message: str
    model_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentSelectionRequest:
    topic: str
    research_route: str
    required_capability_tags: list[str]
    candidates: list[dict[str, Any]]


@dataclass(frozen=True)
class AgentSelectionResult:
    selected_agent_ids: list[str]
    rationale: str
    task_analysis: list[str]
    dependency_notes: list[str]
    model_used: bool


class AgentProvider(Protocol):
    def select_agents(self, request: AgentSelectionRequest) -> AgentSelectionResult: ...

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult: ...


__all__ = [
    "AgentProvider",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentSelectionRequest",
    "AgentSelectionResult",
]
