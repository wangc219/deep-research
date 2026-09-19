"""HTTP request schemas owned by the API boundary.

Keeping validation models here prevents the application service and route
composition module from becoming a single change hotspot.  ``app.py`` keeps
compatibility imports for clients that historically imported these names from
the application module.
"""

from __future__ import annotations

from typing import Any
import os

from pydantic import BaseModel, ConfigDict, Field

from equipment_deep_research.domain.conversation import DEFAULT_BRANCH_ID
from equipment_deep_research.deep_thinking import MAX_MESSAGE_CHARS as DEEP_THINKING_MAX_MESSAGE_CHARS


class CreateRunBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str = Field(default="", max_length=8000)
    research_route: str = "auto"
    selected_agent_ids: list[str] = Field(default_factory=list)
    max_rounds: int = Field(default=2, ge=1, le=5)
    execution: dict = Field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = Field(
        default_factory=lambda: os.environ.get(
            "EQUIPMENT_DR_EXECUTION_PROFILE_ID", "winning_swarm_dynamic_v2"
        ).strip()
        or "winning_swarm_dynamic_v2"
    )
    report_template_mode: str = "project_argument_v1"
    source_query_id: str = Field(default="", max_length=128)
    source_query_version: int | None = Field(default=None, ge=1)
    publish_source_query_on_create: bool = False
    model_profile_id: str = Field(default="", max_length=128)
    tenant_id: str = Field(default="", max_length=160)
    workspace_id: str = Field(default="", max_length=160)
    project_id: str = Field(default="", max_length=160)
    profile_id: str = Field(default="", max_length=160)
    stage_scope: list[str] = Field(default_factory=list, max_length=6)


class UpdateRunBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str | None = Field(default=None, max_length=8000)
    research_route: str
    selected_agent_ids: list[str]
    max_rounds: int = Field(ge=1, le=5)
    execution: dict = Field(default_factory=dict)
    analyst_confirmed: bool = False
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"
    execution_profile_id: str = ""
    report_template_mode: str = ""
    model_profile_id: str = Field(default="", max_length=128)
    tenant_id: str = Field(default="", max_length=160)
    workspace_id: str = Field(default="", max_length=160)
    project_id: str = Field(default="", max_length=160)
    profile_id: str = Field(default="", max_length=160)
    stage_scope: list[str] | None = Field(default=None, max_length=6)


class DeleteRunsBody(BaseModel):
    # Retention cleanup and the UI multi-select can legitimately span more
    # than one page. Keep a bounded request size while allowing one atomic
    # batch for normal local workspaces.
    run_ids: list[str] = Field(min_length=1, max_length=500)


class FavoriteCreateBody(BaseModel):
    """Input for creating a capability-card favorite."""

    run_id: str = Field(min_length=1, max_length=256)
    scope: str = Field(default="global", max_length=32)
    card_key: str = Field(default="", max_length=512)
    card_binding_id: str = Field(default="", max_length=256)
    card_id: str = Field(default="", max_length=256)
    capability_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)


class FavoriteUpdateBody(BaseModel):
    """Mutable presentation fields for an existing favorite."""

    model_config = ConfigDict(extra="ignore")

    display_name: str | None = Field(default=None, max_length=400)
    name: str | None = Field(default=None, max_length=400)
    title: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=4000)
    memo: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=20)


class UpdateRuntimeCapacityBody(BaseModel):
    capacity: int = Field(ge=1, le=8)


class AgentSelectionPreviewBody(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    supplemental_information: str = Field(default="", max_length=8000)
    research_route: str = "auto"
    interaction_mode: str = "expert"
    discovery_branch: str = "auto"


class CapabilityFeedbackBody(BaseModel):
    capability_id: str = Field(default="", max_length=160)
    hypothesis_id: str = Field(default="", max_length=160)
    capability_name: str = Field(default="", max_length=300)
    comment: str = Field(default="", max_length=4000)
    important_information: str = Field(default="", max_length=2400)
    verdict: str = Field(default="needs_revision", max_length=32)
    rating: int | None = Field(default=None, ge=1, le=5)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    model_dimension_scores: dict[str, float] = Field(default_factory=dict)
    expert_dimension_scores: dict[str, float] = Field(default_factory=dict)
    target_agent_ids: list[str] = Field(default_factory=list, max_length=6)
    stage_scope: list[str] = Field(default_factory=list, max_length=6)
    reviewer_name: str = Field(default="", max_length=120)
    reviewer_role: str = Field(default="expert", max_length=80)


class DeepSessionCreateBody(BaseModel):
    kind: str = Field(default="deep-thinking", max_length=64)
    title: str = Field(default="深度思考会话", max_length=240)
    capability_id: str = Field(default="", max_length=256)
    card_binding_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)
    hypothesis_id: str = Field(default="", max_length=256)
    question: str = Field(default="", max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    focus: str = Field(default="", max_length=1600)
    context_refs: dict[str, Any] = Field(default_factory=dict)
    candidate: dict[str, Any] = Field(default_factory=dict)
    reference_weapon: dict[str, Any] = Field(default_factory=dict)
    active_skill_ids: list[str] = Field(default_factory=list, max_length=6)
    create_artifact: bool = False
    auto_merge: bool = False


class DeepSessionMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    create_artifact: bool = False
    focus: str = Field(default="", max_length=1600)
    branch_id: str = Field(default=DEFAULT_BRANCH_ID, max_length=128)
    parent_message_id: str = Field(default="", max_length=128)
    active_skill_ids: list[str] = Field(default_factory=list, max_length=6)
    channel: str | None = Field(default=None, pattern="^(web|cli|telegram|discord)$")


class DeepPluginStateBody(BaseModel):
    enabled: bool


class DeepWorkspaceResourceBody(BaseModel):
    content: str = Field(max_length=2 * 1024 * 1024)
    expected_sha256: str = Field(default="", max_length=64)


class DeepWorkspaceResourceRestoreBody(BaseModel):
    expected_sha256: str = Field(default="", max_length=64)


class DeepWorkspaceResourceMergeBody(BaseModel):
    base_version_id: str = Field(min_length=1, max_length=256)
    content: str = Field(max_length=2 * 1024 * 1024)


class DeepWorkspacePluginPackageMergeBody(BaseModel):
    base_versions: dict[str, str] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)


class DeepSteerBody(BaseModel):
    content: str = Field(min_length=1, max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    mode: str = Field(default="steer", max_length=32)
    client_steer_id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(default=DEFAULT_BRANCH_ID, max_length=128)
    parent_message_id: str = Field(default="", max_length=128)


class DeepBranchForkBody(BaseModel):
    from_message_id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(default="", max_length=128)
    title: str = Field(default="探索分支", max_length=240)


class DeepSessionManageBody(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    archived: bool | None = None


class DeepSessionMergeBody(BaseModel):
    artifact_id: str = Field(default="", max_length=256)
    mode: str = Field(default="append", max_length=32)


class ReferenceResearchBody(BaseModel):
    hypothesis_id: str = Field(default="", max_length=256)
    focus: str = Field(default="", max_length=1600)
    question: str = Field(default="", max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    candidate: dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="", max_length=256)
    retry: bool = False


class PromptEvolutionBody(BaseModel):
    feedback: str = Field(min_length=1, max_length=6000)
    stages: list[str] = Field(default_factory=lambda: ["S3", "S4", "S5", "S6"], max_length=6)
    context: dict[str, Any] = Field(default_factory=dict)


class PromptEvolutionReviewBody(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str = Field(default="", max_length=2000)
    review_password: str = Field(default="", min_length=1, max_length=128)


class EvolutionEffectBody(BaseModel):
    effect_status: str = Field(min_length=1, max_length=32)
    evaluator_id: str = Field(default="", max_length=160)
    evaluation_id: str = Field(default="", max_length=160)
    reason: str = Field(default="", max_length=2000)
    metrics: dict[str, Any] = Field(default_factory=dict)


class PromptReplayEvidenceBody(BaseModel):
    evaluation_id: str = Field(min_length=1, max_length=160)
    replay_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str = Field(default="", max_length=400)
    evaluator_id: str = Field(default="", max_length=160)
    require_pass: bool = True


__all__ = [name for name, value in globals().items() if isinstance(value, type) and issubclass(value, BaseModel)]
