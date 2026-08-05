from __future__ import annotations

from dataclasses import dataclass, field
from equipment_deep_research.domain.models import now_iso


@dataclass(frozen=True)
class CreateRunCommand:
    topic: str
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int
    created_by: str
    execution: dict = field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = ""
    report_template_mode: str = "three_layer_nine_item"
    supplemental_information: str = ""


@dataclass(frozen=True)
class UpdateRunCommand:
    topic: str
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int
    execution: dict = field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = ""
    report_template_mode: str = ""
    supplemental_information: str | None = None


@dataclass(frozen=True)
class RunView:
    run_id: str
    topic: str
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int
    created_by: str
    execution: dict = field(default_factory=dict)
    status: str = "draft"
    result: dict = field(default_factory=dict)
    error: str = ""
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = ""
    report_template_mode: str = "three_layer_nine_item"
    updated_at: str = field(default_factory=now_iso)
    supplemental_information: str = ""
