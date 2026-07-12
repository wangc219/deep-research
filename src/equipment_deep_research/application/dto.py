from __future__ import annotations

from dataclasses import dataclass, field
from equipment_deep_research.domain.models import new_stable_id, now_iso


@dataclass(frozen=True)
class CreateRunCommand:
    topic: str
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int
    created_by: str


@dataclass(frozen=True)
class RunView:
    run_id: str
    topic: str
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int
    created_by: str
    status: str = "draft"
    updated_at: str = field(default_factory=now_iso)
