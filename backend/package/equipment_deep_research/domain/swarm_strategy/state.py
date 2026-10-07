"""Run-local state for the winning swarm strategy.

The state object contains only domain data and deliberately knows nothing
about providers, prompts, persistence, or workflow orchestration. Keeping it
next to the swarm policy makes the boundary explicit: execution services
update this object, while strategy code can inspect it without importing the
Agent implementation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.domain.models import (
    SpecialistContribution,
    SpecialistTask,
    SwarmPlan,
    WinningHypothesis,
)


@dataclass
class SwarmState:
    """Run-local swarm state; never stored on a provider or shared across runs."""

    dynamic_outputs: list[dict[str, Any]] = field(default_factory=list)
    swarm_plan: SwarmPlan | None = None
    swarm_tasks: list[SpecialistTask] = field(default_factory=list)
    swarm_hypotheses: dict[str, WinningHypothesis] = field(default_factory=dict)
    swarm_contributions: list[SpecialistContribution] = field(default_factory=list)
    swarm_gates: list[dict[str, Any]] = field(default_factory=list)
    swarm_merges: list[dict[str, str]] = field(default_factory=list)
    swarm_rejections: list[dict[str, Any]] = field(default_factory=list)
    swarm_completed_task_ids: set[str] = field(default_factory=set)
    swarm_failed_task_ids: set[str] = field(default_factory=set)


__all__ = ["SwarmState"]
