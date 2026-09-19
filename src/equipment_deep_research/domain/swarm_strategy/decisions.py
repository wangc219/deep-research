"""Adaptive swarm controller decisions.

The decision function is intentionally a pure, thresholded policy rather than
a model judgment.  That keeps Gap Analyzer recruitment testable, replayable
and safe to disable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from equipment_deep_research.domain.swarm_strategy.coverage import (
    CoverageSnapshot,
)
from equipment_deep_research.domain.swarm_strategy.composition import (
    recruit_archetype_for_gap,
)


SwarmAction = Literal["expand", "verify", "review", "stop"]


@dataclass(frozen=True)
class AdaptiveSwarmDecision:
    action: SwarmAction
    reason: str
    coverage_ratio: float
    duplicate_ratio: float
    contradiction_coverage: float
    marginal_novelty: float
    primary_gaps: tuple[str, ...]
    recruit_mission_node: str = ""
    recruit_archetype: str = ""
    recruit_gap: str = ""
    abandoned_gaps: tuple[str, ...] = ()

    def to_event(self) -> dict[str, object]:
        return {
            "decision_action": self.action,
            "decision_reason": self.reason,
            "coverage_ratio": self.coverage_ratio,
            "duplicate_ratio": self.duplicate_ratio,
            "contradiction_coverage": self.contradiction_coverage,
            "marginal_novelty": self.marginal_novelty,
            "primary_gaps": list(self.primary_gaps),
            "recruit_mission_node": self.recruit_mission_node,
            "recruit_archetype": self.recruit_archetype,
            "recruit_gap": self.recruit_gap,
            "abandoned_gaps": list(self.abandoned_gaps),
        }


def decide_adaptive_action(
    snapshot: CoverageSnapshot,
    *,
    remaining_instances: int,
    remaining_calls: int,
    remaining_tokens: float | None = None,
    remaining_time: float | None = None,
    coverage_threshold: float = 0.75,
    contradiction_threshold: float = 0.70,
    novelty_floor: float = 0.08,
    duplicate_ceiling: float = 0.45,
    already_used_archetypes: tuple[str, ...] = (),
    consecutive_low_novelty: int = 0,
) -> AdaptiveSwarmDecision:
    """Choose EXPAND / VERIFY / REVIEW / STOP from coverage and budget."""

    gaps = snapshot.primary_gaps
    # ``None`` means that the host does not expose a token or wall-clock
    # allowance for this lane.  It is different from zero: an unavailable
    # metric must not accidentally stop an otherwise bounded graph.
    budget_exhausted = (
        remaining_instances <= 0
        or remaining_calls <= 0
        or (remaining_tokens is not None and remaining_tokens <= 0)
        or (remaining_time is not None and remaining_time <= 0)
    )
    common = {
        "coverage_ratio": snapshot.coverage_ratio,
        "duplicate_ratio": snapshot.duplicate_ratio,
        "contradiction_coverage": snapshot.contradiction_coverage,
        "marginal_novelty": snapshot.marginal_novelty,
        "primary_gaps": gaps,
    }
    if budget_exhausted:
        return AdaptiveSwarmDecision(
            action="review" if snapshot.candidate_count else "stop",
            reason="budget_exhausted",
            abandoned_gaps=gaps,
            **common,
        )
    if snapshot.candidate_count == 0:
        node, archetype = recruit_archetype_for_gap(
            "mechanism",
            already_used=already_used_archetypes,
        )
        return AdaptiveSwarmDecision(
            action="expand",
            reason="empty_candidate_pool",
            recruit_mission_node=node,
            recruit_archetype=archetype,
            recruit_gap="mechanism",
            **common,
        )
    # Repeated low-yield observations are a deliberate stop signal.  Check it
    # before opening another coverage or verification lane; otherwise a stale
    # contradiction gap can keep consuming calls after the portfolio has
    # demonstrably stopped gaining new semantic clusters.
    if (
        consecutive_low_novelty >= 2
        and snapshot.marginal_novelty < novelty_floor
    ):
        return AdaptiveSwarmDecision(
            action="stop",
            reason="marginal_novelty_exhausted",
            abandoned_gaps=gaps,
            **common,
        )
    if snapshot.coverage_ratio < coverage_threshold and gaps:
        node, archetype = recruit_archetype_for_gap(
            gaps[0],
            already_used=already_used_archetypes,
        )
        return AdaptiveSwarmDecision(
            action="expand",
            reason="coverage_below_threshold",
            recruit_mission_node=node,
            recruit_archetype=archetype,
            recruit_gap=gaps[0],
            **common,
        )
    if snapshot.duplicate_ratio > duplicate_ceiling and gaps:
        node, archetype = recruit_archetype_for_gap(
            gaps[0] if gaps else "mechanism",
            already_used=already_used_archetypes,
        )
        return AdaptiveSwarmDecision(
            action="expand",
            reason="duplicate_ratio_above_ceiling",
            recruit_mission_node=node,
            recruit_archetype=archetype,
            recruit_gap=gaps[0] if gaps else "mechanism",
            **common,
        )
    if snapshot.contradiction_coverage < contradiction_threshold:
        node, archetype = recruit_archetype_for_gap(
            "counter_adaptation",
            already_used=already_used_archetypes,
        )
        return AdaptiveSwarmDecision(
            action="verify",
            reason="contradiction_coverage_below_threshold",
            recruit_mission_node=node,
            recruit_archetype=archetype,
            recruit_gap="counter_adaptation",
            **common,
        )
    return AdaptiveSwarmDecision(
        action="review",
        reason="coverage_and_contradiction_ready",
        **common,
    )


__all__ = [
    "AdaptiveSwarmDecision",
    "SwarmAction",
    "decide_adaptive_action",
]
