"""Mode selection for the winning workflow.

This module contains no workflow state or provider calls.  Keeping profile
classification here prevents the legacy, optimized and swarm paths from
reimplementing (and gradually diverging) their mode predicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

WinningFlow = Literal["standard", "quality_swarm", "dynamic_swarm"]


@dataclass(frozen=True)
class WinningMode:
    profile_id: str
    dynamic_swarm: bool
    quality_swarm: bool
    optimized: bool

    @property
    def swarm(self) -> bool:
        return self.dynamic_swarm or self.quality_swarm

    @property
    def uses_quality_contract(self) -> bool:
        return self.swarm or self.optimized

    def initial_flow(self, *, swarm_enabled: bool, resuming: bool) -> WinningFlow:
        """Resume selected S steps without repeating either swarm's discovery."""
        if not swarm_enabled or resuming:
            return "standard"
        if self.dynamic_swarm:
            return "dynamic_swarm"
        if self.quality_swarm:
            return "quality_swarm"
        return "standard"


def resolve_winning_mode(profile_id: object) -> WinningMode:
    value = str(profile_id or "legacy_v1").strip()
    return WinningMode(
        profile_id=value,
        dynamic_swarm=value == "winning_swarm_dynamic_v2",
        quality_swarm=value == "swarm_quality_v1",
        optimized=value == "optimized_v2",
    )


__all__ = ["WinningMode", "resolve_winning_mode"]
