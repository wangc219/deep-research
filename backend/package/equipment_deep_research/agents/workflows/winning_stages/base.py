from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WinningStage:
    step: int
    agent_id: str
    responsibility: str
