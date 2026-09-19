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
    model_profile_id: str = ""
    # Evolution retrieval scope.  These fields are optional for backwards
    # compatibility with existing CLI/in-process callers; API/worker paths
    # persist them so a queued run cannot accidentally inherit another
    # tenant's learning memory after a restart.
    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    profile_id: str = ""
    stage_scope: list[str] = field(default_factory=list)


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
    model_profile_id: str = ""
    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    profile_id: str = ""
    stage_scope: list[str] | None = None


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
    model_profile_id: str = ""
    tenant_id: str = ""
    workspace_id: str = ""
    project_id: str = ""
    profile_id: str = ""
    stage_scope: list[str] = field(default_factory=list)
