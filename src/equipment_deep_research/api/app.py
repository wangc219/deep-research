from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import math
import os
import re
import shutil
import time
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from threading import Event, Lock, Semaphore, Thread
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from starlette.middleware.gzip import GZipMiddleware

from equipment_deep_research.application.dto import CreateRunCommand, RunView, UpdateRunCommand
from equipment_deep_research.application.run_service import (
    InvalidRunTransition,
    PERMANENTLY_DELETABLE_STATUSES,
    ResearchApplicationService,
    RunNotFoundError,
)
from equipment_deep_research.application.factory import build_application_service
from equipment_deep_research.application.worker_pool_config import write_worker_capacity
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.agents.provider import ResponsesAgentProvider
from equipment_deep_research.execution_model import (
    configured_agent_models,
    configured_model,
    configured_provider,
)
from equipment_deep_research.orchestration.blueprints import (
    BRANCH_BLUEPRINTS,
    WINNING_STEP_DEFINITIONS,
    build_discovery_blueprint,
    winning_step_modes,
)
from equipment_deep_research.domain.models import ResearchProblem, new_stable_id, now_iso
from equipment_deep_research.orchestration.coverage import load_preset_policy
from equipment_deep_research.orchestration.reporting import _branch_report_title
from equipment_deep_research.providers.registry import ProviderRegistry
from equipment_deep_research.orchestration.capability_portrait import (
    assemble_capability_portrait_modules,
    CAPABILITY_PORTRAIT_MODULES,
    capability_portrait_module_lengths,
    complete_operational_process,
    normalize_capability_classification,
    normalize_capability_portrait_modules,
    normalize_capability_portrait_text,
    normalize_capability_problem,
    normalize_verification_plan,
    parse_capability_portrait_modules,
    primary_equipment_form_title,
    strip_schema_placeholders,
)
from equipment_deep_research.orchestration.capability_confidence import (
    calibrate_capability_confidence,
)
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload
from equipment_deep_research.runtime_process_registry import terminate_run_process_groups
from equipment_deep_research.query_library.api import create_router as create_query_library_router
from equipment_deep_research.query_library.factory import (
    build_service as build_query_library_service,
    default_seed_manifest,
)
from equipment_deep_research.query_library.models import (
    InvalidStatusTransition,
    QueryLibraryError,
    VersionConflictError,
)
from equipment_deep_research.query_library.service import QueryLibraryService
from equipment_deep_research.expert_feedback import (
    ALL_AGENT_IDS,
    _TRUSTED_FEEDBACK_STATUS_TOKEN,
    append_feedback,
    load_feedback_index,
    load_feedback_knowledge,
    load_run_feedback,
    normalize_feedback,
    update_feedback_effect_status,
)
from equipment_deep_research.prompt_evolution import (
    attach_replay_evidence,
    list_versions,
    list_proposals,
    propose_with_codex,
    proposal_scope_requires_global_publish,
    rollback_version,
    review_proposal,
    update_proposal_effect_status,
)
from equipment_deep_research.model_profiles import (
    activate_profile,
    activate_swarm_overrides,
    doctor_profile,
    get_profile,
    normalize_profile_id,
    profile_execution,
    public_profiles,
)
from equipment_deep_research.deep_thinking import (
    MAX_MESSAGE_CHARS as DEEP_THINKING_MAX_MESSAGE_CHARS,
    append_message as append_deep_message,
    build_reference_capability,
    create_session as create_deep_session,
    delete_run_sidecars,
    get_session as get_deep_session,
    list_reference_research,
    list_research_links,
    list_sessions as list_deep_sessions,
    merge_capability_into_snapshot,
    save_reference_research,
    save_research_link,
    synthesize_reply,
    update_session as update_deep_session,
)
from equipment_deep_research.api.auth import install_tenant_auth_middleware


_KEY_INTERACTION_EVENT_TYPES = frozenset(
    {
        "run_started",
        "run_failed",
        "run_recovered",
        "discovery_meta_loop_evaluated",
        "baseline_pipeline_started",
        "baseline_discovery_started",
        "baseline_discovery_lane_started",
        "baseline_discovery_lane_completed",
        "baseline_discovery_lane_limited",
        "baseline_discovery_completed",
        "baseline_provider_neutral_source_anchor_fallback",
        "baseline_model_queue_started",
        "baseline_model_call_started",
        "baseline_model_call_progress",
        "baseline_model_call_completed",
        "baseline_analysis_started",
        "baseline_analysis_completed",
        "baseline_materialization_progress",
        "baseline_wave_started",
        "baseline_wave_completed",
        "agent_task_delegated",
        "agent_harness_completed",
        "baseline_agent_completed",
        "baseline_agents_summarized",
        "discovery_convergence_completed",
        "discovery_convergence_reused",
        "winning_subagent_completed",
        "winning_model_queue_started",
        "winning_model_call_started",
        "winning_model_call_progress",
        "winning_model_call_completed",
        "winning_model_result_reused",
        "swarm_planned",
        "specialist_recruitment_planned",
        "specialist_spawned",
        "specialist_session_started",
        "specialist_session_completed",
        "specialist_completed",
        "specialist_pruned",
        "winning_mission_graph_planned",
        "winning_agent_instance_recruited",
        "winning_agent_instance_ready",
        "winning_agent_instance_retry_scheduled",
        "winning_agent_session_started",
        "winning_agent_waiting",
        "winning_agent_session_completed",
        "winning_agent_instance_failed",
        "winning_agent_instance_cancelled",
        "winning_pre_generation_angle_portfolio_planned",
        "winning_pre_generation_active_angle_selection_fallback",
        "winning_query_equipment_blueprint_planned",
        "winning_s3_s4_naming_plan_allocated",
        "winning_s3_active_agents_materialized",
        "winning_s3_first_pass_self_admission_completed",
        "winning_s3_s4_candidate_output_bounded",
        "winning_s3_s4_creative_iteration_limited",
        "winning_s3_s4_name_authoring_diagnostic",
        "winning_s3_empty_angle_reallocated",
        "winning_candidate_branch_created",
        "winning_candidate_pre_s5_residual_recorded",
        "winning_candidate_rejected_before_ledger",
        "winning_candidate_review_scope_planned",
        "winning_candidate_summary_quality_advisory",
        "winning_semantic_clustering_started",
        "winning_semantic_clustering_bounded",
        "winning_semantic_clustering_failed",
        "winning_semantic_clustering_completed",
        "winning_candidate_competition_converged",
        "winning_specialized_seed_recovered",
        "winning_specialized_seed_empty",
        "winning_specialized_seed_authored",
        "winning_reasoning_seed_published",
        "winning_candidate_ledger_frozen",
        "winning_contribution_queued",
        "winning_contribution_rejected",
        "winning_contribution_hypothesis_remapped",
        "winning_contribution_rebase_required",
        "winning_contribution_merged",
        "winning_s5_portfolio_frozen",
        "winning_s5_parallel_score_started",
        "winning_s5_parallel_score_completed",
        "winning_s5_empty_scope_skipped",
        "winning_s5_contract_gate_rejected",
        "winning_s5_invalid_decision_rejected",
        "winning_s5_invalid_merge_rejected",
        "winning_s5_portfolio_fallback_activated",
        "winning_full_pool_portfolio_decision",
        "winning_full_pool_portfolio_review_repaired",
        "winning_full_pool_portfolio_review_rescued",
        "winning_full_pool_portfolio_review_completed",
        "winning_portfolio_merge_completed",
        "winning_s5_handoff_quality_gate_completed",
        "winning_s6_card_authoring_started",
        "winning_s6_parallel_authoring_configured",
        "winning_s6_card_authoring_retry_started",
        "winning_s6_card_authoring_completed",
        "winning_s6_card_authoring_reused",
        "winning_s6_card_authoring_limited",
        "winning_s6_card_authoring_rescue_started",
        "winning_s6_card_authoring_rescued",
        "winning_s6_card_quality_advisory",
        "winning_s6_card_quality_enhancement_limited",
        "winning_s6_card_quality_enhancement_completed",
        "winning_s6_low_repair_started",
        "winning_s6_low_repair_completed",
        "winning_s6_low_repair_limited",
        "winning_s6_release_gate_evaluated",
        "winning_quality_judge_recruited",
        "winning_quality_judge_started",
        "winning_quality_judge_assessed",
        "winning_quality_judge_completed",
        "winning_quality_judge_failed",
        "winning_quality_repair_planned",
        "winning_quality_repair_completed",
        "winning_quality_repair_failed",
        "hypothesis_created",
        "hypothesis_merged",
        "hypothesis_rejected",
        "swarm_gate_evaluated",
        "promotion_candidate_created",
        "winning_inner_loop_evaluated",
        "winning_middle_loop_evaluated",
        "winning_outer_loop_evaluated",
        "winning_reasoning_step_completed",
        "winning_stage_completed",
        "recall_requested",
        "recall_task_completed",
        "coverage_recomputed_after_recall",
        "winning_stage_gate_reevaluated",
        "capability_image_created",
        "audit_completed",
        "audit_model_fallback",
        "audit_model_pending",
        "audit_model_unavailable",
        "audit_delivery_blocked",
        "report_completed",
        "report_model_queue_started",
        "report_model_call_started",
        "report_model_call_progress",
        "report_model_call_completed",
        "report_model_fallback",
        "report_model_failed",
        "report_quality_gate_limited",
        "report_delivery_resume_gate_evaluated",
        "run_result_saved",
        "expert_feedback_submitted",
        "expert_feedback_handoff_loaded",
        "deep_session_created",
        "deep_session_message",
        "deep_research_started",
        "deep_research_completed",
        "deep_research_blocked",
        "deep_research_failed",
        "deep_thinking_candidate_created",
        "deep_capability_merged",
    }
)


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
    # Evolution scope is persisted with the run.  In enterprise deployments
    # the authenticated gateway should populate the matching X-* headers;
    # body values remain a backwards-compatible local/integration interface.
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
    run_ids: list[str] = Field(min_length=1, max_length=100)


class FavoriteCreateBody(BaseModel):
    """Input for creating a capability-card favorite.

    The client identifies a card only; the server always reloads and
    normalizes the authoritative S6 artifact before persisting a snapshot.
    ``card_id`` is accepted as a compatibility alias used by early clients.
    """

    run_id: str = Field(min_length=1, max_length=256)
    scope: str = Field(default="global", max_length=32)
    card_key: str = Field(default="", max_length=512)
    card_binding_id: str = Field(default="", max_length=256)
    card_id: str = Field(default="", max_length=256)
    capability_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)


class FavoriteUpdateBody(BaseModel):
    """Mutable presentation fields for an existing favorite.

    The authoritative capability snapshot is intentionally not replaceable:
    editing a favorite changes how it is organized in the workbench, not the
    evidence-backed five-module portrait captured at creation time.
    """

    model_config = ConfigDict(extra="ignore")

    display_name: str | None = Field(default=None, max_length=400)
    # ``name``/``title`` are compatibility aliases for clients that call the
    # editable presentation label simply “name” or “title”.
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
    capability_name: str = Field(default="", max_length=300)
    comment: str = Field(default="", max_length=4000)
    important_information: str = Field(default="", max_length=2400)
    verdict: str = Field(default="needs_revision", max_length=32)
    rating: int | None = Field(default=None, ge=1, le=5)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    # Empty means automatic routing by the feedback-memory processor.  Older
    # clients may still send an explicit target list and remain compatible.
    target_agent_ids: list[str] = Field(default_factory=list, max_length=6)
    stage_scope: list[str] = Field(default_factory=list, max_length=6)
    reviewer_name: str = Field(default="", max_length=120)
    reviewer_role: str = Field(default="expert", max_length=80)


class DeepSessionCreateBody(BaseModel):
    """Create a bounded follow-up/deep-thinking session for one run."""

    kind: str = Field(default="deep-thinking", max_length=64)
    title: str = Field(default="深度思考会话", max_length=240)
    capability_id: str = Field(default="", max_length=256)
    card_binding_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)
    hypothesis_id: str = Field(default="", max_length=256)
    question: str = Field(default="", max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    focus: str = Field(default="", max_length=1600)
    context_refs: dict[str, Any] = Field(default_factory=dict)
    # ``candidate``/``reference_weapon`` are accepted as aliases so clients
    # can post the card object shown in the UI without first flattening it.
    candidate: dict[str, Any] = Field(default_factory=dict)
    reference_weapon: dict[str, Any] = Field(default_factory=dict)
    auto_merge: bool = False


class DeepSessionMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    create_artifact: bool = True
    focus: str = Field(default="", max_length=1600)


class DeepSessionMergeBody(BaseModel):
    artifact_id: str = Field(default="", max_length=256)
    mode: str = Field(default="append", max_length=32)


class ReferenceResearchBody(BaseModel):
    hypothesis_id: str = Field(default="", max_length=256)
    focus: str = Field(default="", max_length=1600)
    question: str = Field(default="", max_length=DEEP_THINKING_MAX_MESSAGE_CHARS)
    candidate: dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="", max_length=256)
    # An explicit retry reuses the canonical parent/hypothesis fingerprint
    # and requeues the existing partial job instead of creating a duplicate
    # child run.  Ordinary repeated requests remain idempotent replays.
    retry: bool = False


class _DeepJobCancelled(Exception):
    """Internal sentinel used to stop a queued deep-thinking turn."""


class _DeepLedgerUnavailable(RuntimeError):
    """Internal sentinel for an unavailable configured deep ledger.

    A modern deployment must not turn a transient SQLite/adapter outage into
    a successful empty projection (or a misleading 404).  Read helpers keep
    their historical compatibility behaviour by default, while HTTP routes
    that need an authoritative answer opt into ``strict=True`` and translate
    this sentinel into a bounded 503 response.
    """


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
    """Bounded replay evidence attached before a Prompt review.

    Replay artifacts are generated by the evaluation service, not by the API
    reviewer.  The API stores only a bounded summary and a relocatable
    artifact reference; production Prompt files are untouched until a later
    explicit review call passes the replay-first gate.
    """

    evaluation_id: str = Field(min_length=1, max_length=160)
    replay_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str = Field(default="", max_length=400)
    evaluator_id: str = Field(default="", max_length=160)
    require_pass: bool = True


_EVOLUTION_STAGE_IDS = frozenset({"S1", "S2", "S3", "S4", "S5", "S6"})

# Deep-thinking events have a deliberately narrow transport contract.  Keep
# these values module-level so the dedicated SSE route and the legacy
# run/history projections cannot drift apart when a worker writes an older or
# hand-edited row into SQLite.
_DEEP_EVENT_STAGES = frozenset(
    {
        "context",
        "s3_divergence",
        "s4_mapping",
        "retrieval",
        "s6_authoring",
        "validation",
        "publish",
        "queued",
    }
)
_DEEP_EVENT_STATUSES = frozenset(
    {"queued", "running", "completed", "partial", "failed", "blocked", "cancelled"}
)
_DEEP_EVENT_KINDS = frozenset({"summary", "answer", "candidate"})
_DEEP_EVENT_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _deep_public_event_type(value: object) -> str:
    """Return an SSE-safe event name without control/newline injection."""

    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return "deep_stage"
    candidate = str(value or "deep_stage").strip()
    if _DEEP_EVENT_TYPE_PATTERN.fullmatch(candidate):
        return candidate
    # Event names are not user-facing prose.  Preserve useful ASCII portions
    # while replacing separators/control characters so a malformed row cannot
    # inject a second SSE frame via ``event:``.
    candidate = re.sub(r"[^A-Za-z0-9_.:-]+", "_", candidate)
    candidate = candidate.strip("_")[:64]
    return candidate or "deep_stage"


def _runtime_public_event_type(value: object) -> str:
    """Make a generic runtime SSE event name frame-safe without relabeling it."""

    candidate = str(value or "runtime_event").strip()
    if not candidate:
        return "runtime_event"
    # Generic S1-S6 event names are server-owned and may use Unicode labels.
    # Preserve those labels for history/UI compatibility while removing only
    # control characters that could terminate an SSE ``event:`` line.
    candidate = re.sub(r"[\x00-\x1f\x7f]", "_", candidate)
    return candidate[:128] or "runtime_event"


def _deep_public_progress(value: object) -> float:
    """Normalize public progress to a finite [0, 1] fraction."""

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _deep_public_refs(value: object, *, limit: int = 32) -> list[str]:
    """Project evidence/artifact/version refs to bounded opaque IDs only."""

    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    result: list[str] = []
    for item in list(value)[:limit]:
        # Reference arrays are identifiers, not arbitrary metadata objects.
        # Dropping mappings here is safer than recursively exposing a legacy
        # provider payload under an innocuous-looking reference key.
        if isinstance(item, Mapping):
            continue
        text = str(item or "").strip()
        if text:
            safe = sanitize_runtime_payload(text, max_string_length=256)
            result.append(str(safe)[:256])
    return result


def _deep_public_identifier(value: object, *, limit: int = 128) -> str:
    """Bound and redact an opaque identifier used in a public event."""

    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return ""
    safe = sanitize_runtime_payload(str(value or ""), max_string_length=limit)
    # Identifiers are rendered in DOM attributes and SSE metadata.  Strip
    # control characters even though JSON escaping would technically make the
    # payload valid; this prevents log/UI newline injection and keeps cursors
    # deterministic across transports.
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(safe)).strip()[:limit]


def _deep_public_text(value: object, *, limit: int) -> str:
    """Return a bounded visible text value, never a stringified object."""

    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return ""
    safe = sanitize_runtime_payload(str(value or ""), max_string_length=limit)
    return str(safe)[:limit]


def _is_deep_runtime_event(event_type: object, payload: object) -> bool:
    """Identify deep events stored in the generic runtime event ledger."""

    if isinstance(payload, Mapping) and str(payload.get("schema_version", "")) == "deep-events-v1":
        return True
    return str(event_type or "").startswith("deep_") or str(event_type or "") in {
        "capability_version_verified",
    }


def _deep_public_event_payload(
    payload: Mapping[str, Any] | None,
    *,
    run_id: str = "",
    sequence: object = 0,
    event_type: object | None = None,
) -> dict[str, Any]:
    """Build the fixed public deep-event shape for any transport boundary."""

    source = payload if isinstance(payload, Mapping) else {}
    raw_delta = source.get("delta")
    if not isinstance(raw_delta, Mapping):
        raw_delta = {}
    kind = str(raw_delta.get("kind", source.get("kind", "summary")) or "summary")
    if kind not in _DEEP_EVENT_KINDS:
        kind = "summary"
    text = _deep_public_text(
        raw_delta.get("text", source.get("text", source.get("summary", ""))),
        limit=2000,
    )
    try:
        public_sequence = int(sequence or 0)
    except (TypeError, ValueError, OverflowError):
        public_sequence = 0
    public_sequence = max(0, public_sequence)
    status = str(source.get("status", "running") or "running").strip().lower()
    if status not in _DEEP_EVENT_STATUSES:
        status = "partial"
    stage = str(source.get("stage", "context") or "context").strip().lower()
    if stage not in _DEEP_EVENT_STAGES:
        stage = "context"
    return {
        "schema_version": "deep-events-v1",
        "event_id": _deep_public_identifier(source.get("event_id", "")),
        "sequence": public_sequence,
        # The outer ledger/event column is authoritative.  Payload copies are
        # advisory and may be stale or browser-supplied; using ``event_type``
        # here prevents a nested spoof from changing the SSE event name.
        "event_type": _deep_public_event_type(
            source.get("event_type", "deep_stage")
            if event_type is None
            else event_type
        ),
        "session_id": _deep_public_identifier(source.get("session_id", "")),
        "job_id": _deep_public_identifier(source.get("job_id", "")),
        "parent_run_id": _deep_public_identifier(source.get("parent_run_id", run_id) or run_id),
        "child_run_id": _deep_public_identifier(source.get("child_run_id", "")),
        "stage": stage,
        "status": status,
        "progress": _deep_public_progress(source.get("progress", 0)),
        "delta": {
            "kind": kind,
            "text": text,
        },
        "evidence_refs": _deep_public_refs(source.get("evidence_refs", source.get("evidence_ids", []))),
        "artifact_refs": _deep_public_refs(source.get("artifact_refs", [])),
        "version_refs": _deep_public_refs(source.get("version_refs", [])),
        "error": _deep_public_text(source.get("error", ""), limit=1000) or None,
        "created_at": _deep_public_identifier(source.get("created_at", ""), limit=64),
    }


def _bounded_scope_id(value: object, *, limit: int = 160) -> str:
    """Normalize a scope identifier before persisting or comparing it."""

    return " ".join(str(value or "").split()).strip()[:limit]


def _normalized_stage_scope(value: object) -> list[str]:
    values = value
    if isinstance(value, str):
        values = re.split(r"[,;\s]+", value)
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    result: list[str] = []
    for raw in values:
        stage = _bounded_scope_id(raw, limit=16).upper()
        if stage in _EVOLUTION_STAGE_IDS and stage not in result:
            result.append(stage)
    return result


def _effective_evolution_scope(
    *,
    body: Mapping[str, Any] | None = None,
    tenant_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
    profile_id: str = "",
    stage_scope: object = None,
) -> dict[str, Any]:
    """Resolve request scope with trusted gateway headers taking precedence."""

    values = body if isinstance(body, Mapping) else {}

    def pick(header_value: object, body_key: str) -> str:
        # Non-empty headers are authoritative.  Empty headers preserve body
        # compatibility for local callers that do not have an identity proxy.
        return _bounded_scope_id(
            header_value if str(header_value or "").strip() else values.get(body_key, "")
        )

    header_stages = stage_scope
    body_stages = values.get("stage_scope")
    return {
        "tenant_id": pick(tenant_id, "tenant_id"),
        "workspace_id": pick(workspace_id, "workspace_id"),
        "project_id": pick(project_id, "project_id"),
        "profile_id": pick(profile_id, "profile_id"),
        "stage_scope": _normalized_stage_scope(
            header_stages if str(header_stages or "").strip() else body_stages
        ),
    }


_EVOLUTION_SCOPE_SCALAR_KEYS = ("tenant_id", "workspace_id", "project_id", "profile_id")


def _record_evolution_scope(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract a normalized scope from feedback/proposal/legacy records.

    Feedback rows historically stored scope fields at the top level while
    Prompt proposals use a nested ``scope`` object.  Keeping this adapter at
    the API boundary makes authorization fail closed regardless of which
    ledger schema produced a row.
    """

    source = record if isinstance(record, Mapping) else {}
    nested = source.get("scope")
    nested = nested if isinstance(nested, Mapping) else {}
    values: dict[str, Any] = {}
    for key in _EVOLUTION_SCOPE_SCALAR_KEYS:
        values[key] = _bounded_scope_id(
            source.get(key) or nested.get(key, "")
        )
    values["stage_scope"] = _normalized_stage_scope(
        source.get("stage_scope") or nested.get("stage_scope", [])
    )
    values["route"] = _bounded_scope_id(
        source.get("route") or nested.get("route", ""), limit=120
    )
    return values


def _scope_is_supplied(scope: Mapping[str, Any] | None) -> bool:
    value = scope if isinstance(scope, Mapping) else {}
    return bool(
        any(str(value.get(key, "")).strip() for key in _EVOLUTION_SCOPE_SCALAR_KEYS)
        or str(value.get("route", "")).strip()
        or _normalized_stage_scope(value.get("stage_scope"))
    )


def _evolution_scope_access(
    record: Mapping[str, Any] | None,
    request_scope: Mapping[str, Any] | None,
    *,
    role: str,
    cross_scope: bool = False,
    write: bool = False,
) -> bool:
    """Authorize a request against a persisted evolution record.

    Scope-less records are treated as legacy/global data.  A non-admin request
    without an authenticated scope can see only those records; it can never
    become a wildcard over another tenant.  A tenant header narrows the view
    to that tenant, while optional workspace/project/profile headers narrow it
    further.  Stage scope is an overlap relation.  Admins may intentionally
    request an unrestricted view with ``cross_scope``.
    """

    role_key = str(role or "").strip().lower()
    target = _record_evolution_scope(record)
    requested = _record_evolution_scope(request_scope)
    if role_key == "admin" and cross_scope:
        return True
    supplied = _scope_is_supplied(requested)
    target_scalar_present = any(target.get(key) for key in _EVOLUTION_SCOPE_SCALAR_KEYS)
    target_stage_present = bool(target.get("stage_scope"))
    if not supplied:
        # Scope-less requests can consume only explicitly global legacy rows.
        # Admin cross-scope access is deliberately opt-in via ``cross_scope``
        # and therefore cannot be triggered merely by omitting headers.
        return not target_scalar_present and not target_stage_present

    # A request carrying a child scope without a tenant is accepted for local
    # compatibility only when the persisted record has no tenant boundary.
    # This avoids accidental cross-tenant matches from a reused workspace id.
    if not requested.get("tenant_id") and target.get("tenant_id"):
        return False
    for key in _EVOLUTION_SCOPE_SCALAR_KEYS:
        expected = str(requested.get(key, "")).strip()
        actual = str(target.get(key, "")).strip()
        if expected and actual != expected:
            return False
        if write and actual and not expected:
            return False
    expected_route = str(requested.get("route", "")).strip()
    actual_route = str(target.get("route", "")).strip()
    if expected_route and actual_route != expected_route:
        return False
    expected_stages = set(_normalized_stage_scope(requested.get("stage_scope")))
    actual_stages = set(_normalized_stage_scope(target.get("stage_scope")))
    if expected_stages:
        # Unknown stage ownership must not cross an explicitly stage-scoped
        # request.  This is stricter than read-time scalar matching because a
        # stage patch/effect can alter future production behavior.
        if not actual_stages or not expected_stages.intersection(actual_stages):
            return False
    elif write and actual_stages:
        return False
    return True


def _cross_scope_requested(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "all"}


def _scope_request(
    *,
    tenant_id: object = "",
    workspace_id: object = "",
    project_id: object = "",
    profile_id: object = "",
    route: object = "",
    stage_scope: object = None,
) -> dict[str, Any]:
    """Normalize gateway scope headers for evolution endpoints."""

    result = _effective_evolution_scope(
        tenant_id=str(tenant_id or ""),
        workspace_id=str(workspace_id or ""),
        project_id=str(project_id or ""),
        profile_id=str(profile_id or ""),
        stage_scope=stage_scope,
    )
    result["route"] = _bounded_scope_id(route, limit=120)
    return result


def _prompt_replay_required() -> bool:
    """Whether API approval must have a passing fixed-query replay.

    Replay-first is the safe default.  An explicit false value is retained as
    a migration escape hatch for local development and old integrations; a
    production deployment can simply omit the variable and therefore remains
    fail-closed.
    """

    raw = os.environ.get("EQUIPMENT_DR_PROMPT_EVOLUTION_REQUIRE_REPLAY", "1")
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _proposal_for_id(output_root: Path, proposal_id: str) -> dict[str, Any]:
    target = next(
        (
            item
            for item in list_proposals(output_root)
            if str(item.get("proposal_id", "")) == str(proposal_id)
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return target


def _version_record_scope(
    row: Mapping[str, Any] | None,
    proposals: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Resolve scope for a version row, including legacy source linkage."""

    record = row if isinstance(row, Mapping) else {}
    direct = _record_evolution_scope(record)
    if _scope_is_supplied(direct):
        return direct
    source = str(record.get("source", "")).strip()
    if source:
        proposal = next(
            (
                item for item in proposals
                if str(item.get("proposal_id", "")) == source
            ),
            None,
        )
        if proposal is not None:
            return _record_evolution_scope(proposal)
    return direct


def create_app(
    service: ResearchApplicationService | None = None,
    event_repository: object | None = None,
    *,
    agent_config_path: str | Path | None = None,
    preset_config_path: str | Path | None = None,
    query_library_service: QueryLibraryService | None = None,
    provider_config_path: str | Path | None = None,
    strict_auth: bool | None = None,
) -> FastAPI:
    service = service or build_application_service()
    if event_repository is None:
        event_repository = getattr(service, "repository", None)
    app = FastAPI(title="Equipment Deep Research API", version="0.1.0")
    # Peanut Shell adds latency to every round trip. Compress JSON responses
    # at the API boundary so task lists and artifact summaries cross the tunnel
    # with fewer bytes. Streaming event responses remain usable because the
    # middleware handles them as a streaming response.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # Deep-thinking requests are deliberately detached from the HTTP worker.
    # A bounded daemon dispatcher keeps the API responsive while preserving a
    # durable job row that can be polled/replayed after a client disconnect.
    # The normal S1-S6 worker remains the execution authority for reference
    # child runs; these threads only advance the conversation ledger and
    # reconcile child-run state.
    try:
        _deep_worker_capacity = max(
            1, min(8, int(os.environ.get("EQUIPMENT_DR_DEEP_JOB_WORKERS", "4")))
        )
    except (TypeError, ValueError):
        _deep_worker_capacity = 4
    deep_worker_slots = Semaphore(_deep_worker_capacity)
    deep_worker_lock = Lock()
    deep_worker_threads: dict[str, Thread] = {}
    deep_worker_cancel: dict[str, Event] = {}
    deep_memory_jobs: dict[str, dict[str, Any]] = {}
    create_run_idempotency: dict[str, tuple[str, object]] = {}
    create_run_idempotency_lock = Lock()
    favorite_memory: dict[str, dict[str, Any]] = {}
    favorite_memory_lock = Lock()
    favorite_repository = getattr(service, "repository", None)
    if not callable(getattr(favorite_repository, "save_favorite", None)):
        candidate_repository = event_repository
        favorite_repository = (
            candidate_repository
            if callable(getattr(candidate_repository, "save_favorite", None))
            else None
        )

    def find_favorite_record(
        *, scope: str, owner_id: str, run_id: str, card_key: str
    ) -> dict[str, Any] | None:
        find = getattr(favorite_repository, "find_favorite", None)
        if callable(find):
            return find(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                card_key=card_key,
            )
        with favorite_memory_lock:
            return next(
                (
                    dict(item)
                    for item in favorite_memory.values()
                    if item.get("scope") == scope
                    and item.get("owner_id") == owner_id
                    and item.get("run_id") == run_id
                    and item.get("card_key") == card_key
                ),
                None,
            )

    def save_favorite_record(**values: Any) -> tuple[dict[str, Any], bool]:
        existing = find_favorite_record(
            scope=str(values["scope"]),
            owner_id=str(values["owner_id"]),
            run_id=str(values["run_id"]),
            card_key=str(values["card_key"]),
        )
        if existing is not None:
            return existing, False
        save = getattr(favorite_repository, "save_favorite", None)
        if callable(save):
            # Give the repository a request-local ID.  Its unique constraint
            # may return another request's canonical row when two API workers
            # race; comparing IDs lets the loser correctly return 200 rather
            # than claiming it created a second record.
            candidate_favorite_id = new_stable_id("favorite")
            parameters: Mapping[str, inspect.Parameter] = {}
            try:
                parameters = inspect.signature(save).parameters
                # A named parameter is the usual indication that a repository
                # persists the caller-supplied ID.  A wrapper may expose only
                # ``**kwargs`` (for example, a test repository that gates the
                # call before delegating to SqlRunRepository); inspect its
                # inherited implementations before deciding to pass the
                # candidate.  This keeps older, unrelated ``**kwargs``
                # repository doubles compatible while still preserving the
                # cross-process winner signal for delegating wrappers.
                accepts_favorite_id = "favorite_id" in parameters
                if not accepts_favorite_id and any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                ):
                    repository_instance = getattr(save, "__self__", None)
                    repository_type = getattr(repository_instance, "__class__", None)
                    for base_type in getattr(repository_type, "__mro__", ())[1:]:
                        inherited_save = getattr(base_type, "save_favorite", None)
                        if inherited_save is None:
                            continue
                        try:
                            inherited_parameters = inspect.signature(
                                inherited_save
                            ).parameters
                        except (TypeError, ValueError):
                            continue
                        if "favorite_id" in inherited_parameters:
                            accepts_favorite_id = True
                            break
            except (TypeError, ValueError):
                accepts_favorite_id = False
            accepts_var_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            call_values = dict(values)
            if not accepts_var_kwargs:
                call_values = {
                    key: value for key, value in call_values.items() if key in parameters
                }
            if accepts_favorite_id:
                saved = save(favorite_id=candidate_favorite_id, **call_values)
                if isinstance(saved, Mapping):
                    returned_id = str(saved.get("favorite_id", "") or "").strip()
                    if returned_id:
                        return saved, returned_id == candidate_favorite_id
                return saved, True
            # Lightweight repository doubles from older integrations keep
            # their original signature; do not pass a keyword they cannot
            # persist, and preserve their historical created semantics.  With
            # no request-local ID there is no reliable cross-process winner
            # signal, so the pre-check result remains the compatibility truth.
            saved = save(**call_values)
            return saved, True
        created_at = now_iso()
        favorite_id = new_stable_id("favorite")
        record = {
            **dict(values.get("snapshot") or {}),
            "favorite_id": favorite_id,
            "scope": str(values["scope"]),
            "owner_id": str(values["owner_id"]),
            "run_id": str(values["run_id"]),
            "card_key": str(values["card_key"]),
            "card_binding_id": str(values.get("card_binding_id") or ""),
            "capability_id": str(values.get("capability_id") or ""),
            "display_name": str(values.get("display_name") or "").strip()[:400],
            "note": str(values.get("note") or "").strip()[:4000],
            "tags": _normalize_favorite_tags(values.get("tags")),
            "source_topic": str(values.get("source_topic") or ""),
            "source_status": str(values.get("source_status") or ""),
            "source_deleted": bool(values.get("source_deleted", False)),
            "created_at": created_at,
            "updated_at": created_at,
        }
        # Keep the same dual representation as the SQL repository.  The
        # flattened snapshot fields are convenient for existing consumers,
        # while ``snapshot``/``snapshot_json`` make the immutable payload
        # explicit for clients that persist or inspect a favorite record.
        snapshot_payload = dict(values.get("snapshot") or {})
        record["snapshot"] = snapshot_payload
        record["snapshot_json"] = json.dumps(
            snapshot_payload, ensure_ascii=False, sort_keys=True
        )
        record["favorited"] = True
        with favorite_memory_lock:
            # Recheck under the write lock so the in-memory compatibility path
            # has the same idempotency semantics as the SQL unique constraint.
            duplicate = next(
                (
                    dict(item)
                    for item in favorite_memory.values()
                    if item.get("scope") == record["scope"]
                    and item.get("owner_id") == record["owner_id"]
                    and item.get("run_id") == record["run_id"]
                    and item.get("card_key") == record["card_key"]
                ),
                None,
            )
            if duplicate is not None:
                return duplicate, False
            favorite_memory[favorite_id] = record
        return dict(record), True

    def get_favorite_record(favorite_id: str) -> dict[str, Any] | None:
        load = getattr(favorite_repository, "get_favorite", None)
        if callable(load):
            return load(favorite_id)
        with favorite_memory_lock:
            record = favorite_memory.get(favorite_id)
            return dict(record) if record is not None else None

    def update_favorite_record(
        favorite_id: str,
        *,
        display_name: str | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Update mutable favorite metadata across SQL and memory stores."""

        update = getattr(favorite_repository, "update_favorite", None)
        if callable(update):
            # Keep lightweight/older repository doubles compatible while the
            # SQL repository exposes the full metadata surface.  Filter only
            # unsupported keywords discovered from the callable signature;
            # wrappers with ``**kwargs`` continue to receive all fields.
            call_values = {
                "display_name": display_name,
                "note": note,
                "tags": tags,
            }
            try:
                parameters = inspect.signature(update).parameters
            except (TypeError, ValueError):
                parameters = {}
            accepts_var_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if not accepts_var_kwargs and parameters:
                call_values = {
                    key: value
                    for key, value in call_values.items()
                    if key in parameters
                }
            return update(favorite_id, **call_values)
        with favorite_memory_lock:
            record = favorite_memory.get(favorite_id)
            if record is None:
                return None
            updated = dict(record)
            if display_name is not None:
                updated["display_name"] = str(display_name).strip()[:400]
            if note is not None:
                updated["note"] = str(note).strip()[:4000]
            if tags is not None:
                updated["tags"] = _normalize_favorite_tags(tags)
            updated["updated_at"] = now_iso()
            favorite_memory[favorite_id] = updated
            return dict(updated)

    def list_favorite_records(
        *,
        scope: str,
        owner_id: str,
        run_id: str = "",
        offset: int,
        limit: int,
        search: str,
        capability_type: str,
    ) -> dict[str, Any]:
        listing = getattr(favorite_repository, "list_favorites", None)
        if callable(listing):
            legacy_listing = False
            try:
                result = listing(
                    scope=scope,
                    owner_id=owner_id,
                    run_id=run_id,
                    offset=offset,
                    limit=limit,
                    search=search,
                    capability_type=capability_type,
                )
            except TypeError:
                # Keep compatibility with lightweight repository doubles used
                # by older integrations that do not yet accept run_id.
                legacy_listing = True
                result = listing(
                    scope=scope,
                    owner_id=owner_id,
                    offset=offset,
                    limit=limit,
                    search=search,
                    capability_type=capability_type,
                )
            if isinstance(result, list):
                result = {
                    "items": result,
                    "total": len(result),
                    "offset": offset,
                    "limit": limit,
                    "has_more": False,
                    "scope": scope,
                    "owner_id": owner_id,
                }
            if not isinstance(result, Mapping):
                return {
                    "items": [],
                    "total": 0,
                    "offset": offset,
                    "limit": limit,
                    "has_more": False,
                    "scope": scope,
                    "owner_id": owner_id,
                }
            result = dict(result)
            # An old repository double may ignore the run_id keyword (or not
            # accept it at all). Enforce the scope locally so capability star
            # state can never leak a favorite from another task.
            if run_id and (legacy_listing or str(result.get("run_id", "")).strip() != run_id):
                items = result.get("items", [])
                if isinstance(items, list):
                    filtered = [
                        item
                        for item in items
                        if isinstance(item, Mapping)
                        and str(item.get("run_id", "")).strip() == str(run_id).strip()
                    ]
                    result["items"] = filtered
                    result["total"] = len(filtered)
                    result["has_more"] = False
            return result
        with favorite_memory_lock:
            rows = [
                dict(item)
                for item in favorite_memory.values()
                if item.get("scope") == scope
                and item.get("owner_id") == owner_id
                and (not str(run_id or "").strip() or item.get("run_id") == str(run_id).strip())
            ]
        query = search.strip().casefold()
        if query:
            rows = [
                item
                for item in rows
                if query
                in " ".join(
                    str(item.get(key, ""))
                    for key in (
                        "name",
                        "display_name",
                        "note",
                        "tags",
                        "source_topic",
                        "card_key",
                        "capability_id",
                        "card_binding_id",
                    )
                ).casefold()
            ]
        if capability_type:
            rows = [
                item
                for item in rows
                if str(item.get("capability_type", "")) == capability_type
            ]
        rows.sort(
            key=lambda item: (
                str(item.get("created_at", "")),
                str(item.get("favorite_id", "")),
            ),
            reverse=True,
        )
        total = len(rows)
        page = rows[offset : offset + limit]
        return {
            "items": page,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
            "scope": scope,
            "owner_id": owner_id,
        }

    def delete_favorite_record(favorite_id: str) -> dict[str, Any] | None:
        remove = getattr(favorite_repository, "delete_favorite", None)
        if callable(remove):
            return remove(favorite_id)
        with favorite_memory_lock:
            record = favorite_memory.pop(favorite_id, None)
        return dict(record) if record is not None else None

    def update_favorite_sources(
        run_id: str, *, source_status: str, source_deleted: bool
    ) -> int:
        method_name = (
            "mark_favorites_source_deleted"
            if source_deleted
            else "update_favorites_source_status"
        )
        update_source = getattr(favorite_repository, method_name, None)
        if callable(update_source):
            if source_deleted:
                return int(
                    update_source(run_id, source_status=source_status) or 0
                )
            return int(
                update_source(
                    run_id,
                    source_status=source_status,
                    source_deleted=False,
                )
                or 0
            )
        updated = 0
        with favorite_memory_lock:
            for favorite_id, item in list(favorite_memory.items()):
                if item.get("run_id") != run_id:
                    continue
                favorite_memory[favorite_id] = {
                    **item,
                    "source_status": source_status,
                    "source_deleted": source_deleted,
                    "updated_at": now_iso(),
                }
                updated += 1
        return updated

    @app.exception_handler(RunNotFoundError)
    async def run_not_found_handler(
        _request: Request,
        _exc: RunNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "run not found"})

    if query_library_service is None:
        query_library_service = build_query_library_service()
        query_library_service.import_seed_manifest(default_seed_manifest())
    app.include_router(create_query_library_router(query_library_service))
    project_root = Path(os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", Path(__file__).resolve().parents[3]))
    output_root = Path(os.environ.get("EQUIPMENT_DR_OUTPUT_ROOT", project_root / "outputs/runs"))
    if not output_root.is_absolute():
        output_root = (project_root / output_root).resolve()
    # Workers persist provider process-group ownership outside individual run
    # directories.  The API must point at the same registry so Stop/Resume
    # can terminate children left behind by an interrupted Worker process.
    os.environ.setdefault(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(output_root.parent / "runtime" / "run-process-groups"),
    )
    agent_path = Path(agent_config_path or project_root / "configs/equipment_deep_research/agents.yaml")
    preset_path = Path(preset_config_path or project_root / "configs/equipment_deep_research/presets.yaml")
    provider_path = Path(provider_config_path or project_root / "configs/equipment_deep_research/providers.yaml")
    catalog_payload = _catalog_payload(agent_path, preset_path)
    agent_registry = AgentRegistry.load(agent_path)
    interaction_agents = _interaction_agents(agent_path)

    def read_view(run_id: str) -> RunView:
        """Read a DB run, or a completed artifact-only historical run.

        Real dynamic-swarm launches can be executed directly by the research
        runner and therefore have a durable output directory without a row in
        the application DB.  Treat those directories as immutable historical
        RunViews so the existing frontend task navigator can load them without
        fabricating lifecycle state or copying large artifacts into SQLite.
        """

        # Validate the identifier before touching either the database or the
        # filesystem. Apart from making path handling deterministic, this keeps
        # malformed IDs from being converted into a misleading 404 by the
        # historical-artifact fallback.
        if not _is_safe_run_id(run_id):
            raise HTTPException(status_code=400, detail="invalid run id")

        try:
            return service.get_run(run_id)
        except (KeyError, NoResultFound, RunNotFoundError) as exc:
            historical = _artifact_run_view(output_root, run_id)
            if historical is None:
                # Normalize repository-specific missing-row exceptions. A
                # custom service or an older SQLAlchemy adapter may raise a
                # plain KeyError/NoResultFound; exposing those directly would
                # turn a normal missing task into an internal server error.
                raise RunNotFoundError(run_id) from exc
            return historical

    def list_views() -> list[RunView]:
        stored = service.list_runs()
        known = {item.run_id for item in stored}
        historical = [
            item for item in _discover_artifact_runs(output_root)
            if item.run_id not in known
        ]
        return sorted(
            [*stored, *historical],
            key=lambda item: item.updated_at,
            reverse=True,
        )

    # Install one boundary check for every run sub-route, including SSE and
    # artifact downloads.  Existing handlers still own role checks and their
    # historical compatibility behavior; the middleware only rejects a
    # supplied namespace that does not match the persisted run.
    install_tenant_auth_middleware(
        app,
        strict=strict_auth,
        run_loader=lambda run_id: read_view(run_id),
    )

    def _require_prompt_evolution_password(password: str) -> None:
        expected = os.environ.get("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", "").strip()
        if not expected:
            # Never ship a universal reviewer credential.  The only supported
            # exception is an explicitly opted-in local/test compatibility
            # mode, which must be enabled by deployment configuration rather
            # than inferred from a missing secret.
            allow_dev_default = _cross_scope_requested(
                os.environ.get("EQUIPMENT_DR_ALLOW_DEFAULT_REVIEW_PASSWORD", "")
            )
            runtime_mode = str(
                os.environ.get("EQUIPMENT_DR_ENV", os.environ.get("ENVIRONMENT", ""))
            ).strip().lower()
            if allow_dev_default and runtime_mode in {"dev", "development", "local", "test", "testing"}:
                expected = "Hitsz123456"
            else:
                raise HTTPException(
                    status_code=503,
                    detail="prompt evolution review password is not configured",
                )
        if not str(password).strip() or not hmac.compare_digest(str(password), expected):
            raise HTTPException(status_code=403, detail="invalid prompt evolution review password")

    @app.get("/api/v1/prompt-evolution/proposals")
    def get_prompt_evolution_proposals(
        status: str = "",
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict:
        _require_role(x_role, {"developer", "reviewer", "auditor", "admin"})
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        cross_scope = x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope)
        rows = [
            row for row in list_proposals(output_root, status=status)
            if _evolution_scope_access(row, scope, role=x_role, cross_scope=cross_scope)
        ]
        payload = {"items": rows, "count": len(rows)}
        if _scope_is_supplied(scope) or cross_scope:
            payload.update({"scope": scope, "cross_scope": cross_scope})
        return payload

    @app.get("/api/v1/prompt-evolution/versions")
    def get_prompt_evolution_versions(
        stage: str = "",
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict:
        _require_role(x_role, {"developer", "reviewer", "auditor", "admin"})
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        cross_scope = x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope)
        proposals = list_proposals(output_root)
        rows = [
            row for row in list_versions(output_root, stage)
            if _evolution_scope_access(
                _version_record_scope(row, proposals),
                scope,
                role=x_role,
                cross_scope=cross_scope,
            )
        ]
        payload = {"items": rows, "count": len(rows)}
        if _scope_is_supplied(scope) or cross_scope:
            payload.update({"scope": scope, "cross_scope": cross_scope})
        return payload

    @app.post("/api/v1/prompt-evolution/versions/{stage}/{version}/rollback")
    def rollback_prompt_evolution_version(
        stage: str,
        version: str,
        body: PromptEvolutionReviewBody,
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict:
        _require_role(x_role, {"developer", "admin"})
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        proposals = list_proposals(output_root)
        target_version = next(
            (
                item for item in list_versions(output_root, stage)
                if str(item.get("version", "")).lower() == str(version).lower()
            ),
            None,
        )
        if target_version is None:
            raise HTTPException(status_code=404, detail="version not found")
        cross_scope = x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope)
        if not _evolution_scope_access(
            _version_record_scope(target_version, proposals),
            scope,
            role=x_role,
            cross_scope=cross_scope,
            write=True,
        ):
            raise HTTPException(status_code=403, detail="evolution scope mismatch")
        if proposal_scope_requires_global_publish(
            _version_record_scope(target_version, proposals)
        ) and not cross_scope:
            raise HTTPException(
                status_code=403,
                detail=(
                    "scoped prompt version cannot publish shared active prompt; "
                    "global admin with X-Evolution-Cross-Scope=true is required"
                ),
            )
        _require_prompt_evolution_password(body.review_password)
        if body.decision != "approved":
            raise HTTPException(status_code=422, detail="rollback requires decision=approved")
        try:
            record = rollback_version(
                output_root=output_root,
                stage=stage,
                version=version,
                reviewer=x_role,
                comment=body.comment,
                allow_scoped_publish=cross_scope,
            )
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"version": record}

    @app.post("/api/v1/prompt-evolution/proposals", status_code=201)
    async def create_prompt_evolution_proposal(
        body: PromptEvolutionBody,
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
    ) -> dict:
        _require_role(x_role, {"developer", "reviewer", "admin"})
        registry = ProviderRegistry.load(provider_path)
        provider = registry.create("codex", workspace_path=project_root, isolation_key="prompt-evolution")
        feedback_context = dict(body.context)
        # Resolve each scope field independently.  A gateway commonly sends
        # only a stage header (for example ``S6``) while the local request
        # carries tenant/workspace/project context in ``body.context``.  The
        # previous all-or-nothing merge treated the presence of *any* header
        # as authority for every field and silently erased those body values,
        # turning a tenant-scoped proposal into an apparently global one.
        scope = _effective_evolution_scope(
            body=feedback_context,
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
        )
        scope["route"] = _bounded_scope_id(
            x_research_route
            if str(x_research_route or "").strip()
            else feedback_context.get("route", ""),
            limit=120,
        )
        # Header values are authoritative when supplied; otherwise retain
        # body context for local integrations that predate gateway headers.
        for key in (*_EVOLUTION_SCOPE_SCALAR_KEYS, "route", "stage_scope"):
            feedback_context[key] = scope.get(key, "")
        feedback_context["comment"] = body.feedback
        try:
            proposal = await propose_with_codex(
                project_root=project_root,
                output_root=output_root,
                feedback=feedback_context,
                stages=body.stages,
                provider=provider,
            )
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        return {"proposal": proposal}

    @app.post("/api/v1/prompt-evolution/proposals/{proposal_id}/review")
    def review_prompt_evolution_proposal(
        proposal_id: str,
        body: PromptEvolutionReviewBody,
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict:
        _require_role(x_role, {"developer", "admin"})
        target = _proposal_for_id(output_root, proposal_id)
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        cross_scope = x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope)
        if not _evolution_scope_access(
            target,
            scope,
            role=x_role,
            cross_scope=cross_scope,
            write=True,
        ):
            raise HTTPException(status_code=403, detail="evolution scope mismatch")
        _require_prompt_evolution_password(body.review_password)
        try:
            proposal = review_proposal(
                output_root=output_root,
                proposal_id=proposal_id,
                decision=body.decision,
                reviewer=x_role,
                comment=body.comment,
                require_replay=_prompt_replay_required(),
                allow_scoped_publish=cross_scope,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"proposal": proposal}

    @app.post("/api/v1/prompt-evolution/proposals/{proposal_id}/replay")
    def attach_prompt_evolution_replay(
        proposal_id: str,
        body: PromptReplayEvidenceBody,
        x_role: str = Header(default="reviewer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
    ) -> dict:
        """Attach fixed-query replay evidence before Prompt approval."""

        _require_role(x_role, {"developer", "reviewer", "auditor", "admin"})
        target = _proposal_for_id(output_root, proposal_id)
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        if not _evolution_scope_access(target, scope, role=x_role, write=True):
            raise HTTPException(status_code=403, detail="evolution scope mismatch")
        try:
            proposal = attach_replay_evidence(
                output_root=output_root,
                proposal_id=proposal_id,
                evaluation_id=body.evaluation_id,
                replay_summary=body.replay_summary,
                artifact_path=body.artifact_path,
                evaluator_id=body.evaluator_id or x_role,
                require_pass=body.require_pass,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"proposal": proposal}

    @app.post("/api/v1/prompt-evolution/proposals/{proposal_id}/effect")
    def evaluate_prompt_evolution_proposal(
        proposal_id: str,
        body: EvolutionEffectBody,
        x_role: str = Header(default="developer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(
            default="", alias="X-Evolution-Stage-Scope"
        ),
    ) -> dict:
        """Record replay evidence after a separately approved proposal."""
        _require_role(x_role, {"developer", "reviewer", "auditor", "admin"})
        try:
            target = _proposal_for_id(output_root, proposal_id)
            scope = _scope_request(
                tenant_id=x_tenant_id,
                workspace_id=x_workspace_id,
                project_id=x_project_id,
                profile_id=x_profile_id,
                route=x_research_route,
                stage_scope=x_evolution_stage_scope,
            )
            if not _evolution_scope_access(target, scope, role=x_role, write=True):
                raise HTTPException(status_code=403, detail="evolution scope mismatch")
            proposal = update_proposal_effect_status(
                output_root=output_root,
                proposal_id=proposal_id,
                effect_status=body.effect_status,
                # Do not infer evaluator identity from the request role.  A
                # role authorizes the operation; the body must name the
                # evaluator that produced the evidence for auditability.
                evaluator_id=body.evaluator_id,
                evaluation_id=body.evaluation_id,
                reason=body.reason,
                metrics=body.metrics,
            )
        except HTTPException:
            raise
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"proposal": proposal}

    def benchmark_research_runs() -> list[dict]:
        rows: list[dict] = []
        for view in list_views():
            if view.status != "completed":
                continue
            run_dir = _resolve_run_root(output_root, view.run_id, view.result)
            if run_dir is None:
                continue
            report_path = _preferred_report_path(run_dir.resolve())
            if report_path is None:
                continue
            rows.append(
                {
                    "run_id": view.run_id,
                    "topic": view.topic,
                    "research_route": view.research_route,
                    "discovery_branch": view.discovery_branch,
                    "execution_profile_id": getattr(view, "execution_profile_id", "") or "legacy_v1",
                    "updated_at": view.updated_at,
                    "report_available": True,
                }
            )
        return rows

    def benchmark_research_report(run_id: str) -> dict:
        view = read_view(run_id)
        if view.status != "completed":
            raise ValueError("研究任务尚未完成")
        run_dir = _resolve_run_root(output_root, run_id, view.result)
        if run_dir is None:
            raise FileNotFoundError("研究任务输出目录不存在")
        report_path = _preferred_report_path(run_dir)
        if report_path is None:
            raise FileNotFoundError("研究报告不存在")
        citations: list[str] = []
        sources: list[str] = []
        evidence_context: list[dict] = []
        domain_path = run_dir / "domain.jsonl"
        if domain_path.is_file():
            for row in _jsonl_path(domain_path):
                if row.get("type") != "EvidenceCard":
                    continue
                payload = row.get("payload", {})
                url = str(payload.get("source_url", "")).strip()
                if url and url not in citations:
                    citations.append(url)
                title = str(payload.get("source_title", "")).strip()
                if title and title not in sources:
                    sources.append(title)
                evidence_context.append(
                    {
                        "evidence_id": str(payload.get("evidence_id", "")),
                        "source_title": title,
                        "source_url": url,
                        "source_tier": str(payload.get("source_tier", "")),
                        "quality_assessment": str(
                            payload.get("quality_assessment", "")
                        ),
                        "claim": str(
                            payload.get("claim")
                            or payload.get("evidence_summary")
                            or ""
                        ),
                    }
                )
        summary: dict = {}
        summary_path = run_dir / "round_summary.json"
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        answer = report_path.read_text(encoding="utf-8")
        answer = _normalize_report_title_for_display(answer, view.topic)
        return {
            "run_id": view.run_id,
            "topic": view.topic,
            "answer": answer,
            "citations": citations,
            "sources": sources,
            "evidence_context": evidence_context,
            "duration_seconds": float(
                summary.get("performance_summary", {}).get("wall_time_seconds", 0.0)
                or 0.0
            ),
            "usage": summary.get("usage", {}),
            "model_snapshot": {
                **dict(summary.get("provider", {})),
                "execution_profile_id": getattr(view, "execution_profile_id", "")
                or "legacy_v1",
            },
            "artifact_refs": [
                f"/api/v1/runs/{run_id}/report",
                f"/api/v1/runs/{run_id}/summary",
            ],
        }
    try:
        from evals.web_api import create_benchmark_router

        app.include_router(
            create_benchmark_router(
                project_root,
                list_research_runs=benchmark_research_runs,
                load_research_report=benchmark_research_report,
            )
        )
    except ImportError:
        # Production research APIs remain available when the optional sidecar
        # benchmark package is not included in a deployment image.
        pass
    if os.environ.get("EQUIPMENT_DR_ENABLE_ABLATION", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        try:
            from evals.ablation import create_ablation_router

            app.include_router(
                create_ablation_router(
                    project_root,
                    list_research_runs=benchmark_research_runs,
                    load_research_report=benchmark_research_report,
                )
            )
        except ImportError:
            # The extension is intentionally removable; core APIs stay intact.
            pass

    def permanently_remove(run_id: str) -> None:
        current = service.get_run(run_id)
        # Deletion is destructive by design: stop the run and terminate every
        # process group registered under it before removing its records/files.
        # This also handles a Worker that has already claimed the queue item.
        if current.status not in PERMANENTLY_DELETABLE_STATUSES:
            try:
                service.cancel_run(
                    run_id,
                    actor="api-user",
                    idempotency_key=f"delete:{run_id}",
                )
            except InvalidRunTransition:
                pass
            terminate_run_process_groups(run_id)
            current = service.get_run(run_id)
        _delete_run_output(output_root, run_id)
        # Remove legacy JSON compatibility sidecars after the SQL ledger and
        # run artifacts are deleted.  Verified favorites remain as immutable
        # snapshots and are marked source-deleted above.
        try:
            delete_run_sidecars(output_root, run_id)
        except Exception:
            pass
        # Favorites are immutable snapshots.  Mark them only after the source
        # artifact directory is gone; a failed filesystem deletion must not
        # falsely label a still-readable source as deleted.
        update_favorite_sources(
            run_id,
            source_status="deleted",
            source_deleted=True,
        )
        service.delete_run(
            run_id,
            allow_active=True,
        )
        _verify_run_deleted(service, output_root, run_id)

    def interaction_rows(run_id: str, view: object) -> list[dict]:
        rows: list[dict] = []
        rows_by_key: dict[str, dict] = {}

        def append_row(row: dict, *, runtime_sequence: int = 0) -> None:
            event_id = str(row.get("event_id", "")).strip()
            key = event_id or "|".join(
                str(row.get(field, ""))
                for field in ("event_type", "actor", "created_at", "summary")
            )
            existing = rows_by_key.get(key)
            if existing is not None:
                # File-backed trace rows are loaded first, while the runtime
                # repository carries the authoritative monotonic sequence.
                # Preserve the richer row but attach its runtime order when
                # the duplicate repository event is encountered.
                if runtime_sequence and not existing.get("_runtime_sequence"):
                    existing["_runtime_sequence"] = runtime_sequence
                return
            row["_runtime_sequence"] = runtime_sequence
            rows_by_key[key] = row
            rows.append(row)

        result = getattr(view, "result", {})
        result = result if isinstance(result, dict) else {}
        root = _resolve_run_root(output_root, run_id, result)
        if root is not None:
            trace_path = root / "trace.jsonl"
            if trace_path.is_file():
                for row in _jsonl_path(trace_path):
                    if row.get("type") != "TraceEvent":
                        continue
                    append_row(_public_trace_interaction(row.get("payload", {})))
            sessions_dir = root / "agent_sessions"
            if sessions_dir.is_dir() and not sessions_dir.is_symlink():
                for path in sorted(sessions_dir.glob("*.jsonl")):
                    if path.is_file() and not path.is_symlink():
                        for event in _jsonl_path(path):
                            public = _public_session_interaction(event)
                            if public is not None:
                                append_row(public)
        if event_repository is not None:
            for runtime_event in event_repository.events_after(run_id, 0):
                payload = runtime_event.get("payload", {})
                source = payload.get("source") if isinstance(payload, dict) else None
                event = payload.get("event", {}) if isinstance(payload, dict) else {}
                public = (
                    _public_trace_interaction(event)
                    if source == "trace"
                    else _public_session_interaction(event)
                    if source == "session_projection"
                    else None
                )
                if public is not None:
                    append_row(public, runtime_sequence=int(runtime_event["sequence"]))
                    continue
                # Runtime terminal events are not represented by TraceEvent files.
                # Keep them in the replay so a failed run cannot appear as merely stalled.
                if runtime_event.get("event_type") in {"run_failed", "run_recovered"}:
                    details = payload if isinstance(payload, dict) else {}
                    append_row(
                        {
                            "event_id": f"runtime-{runtime_event['sequence']}",
                            "event_type": str(runtime_event["event_type"]),
                            "actor": "orchestrator",
                            "title": "任务失败" if runtime_event["event_type"] == "run_failed" else "任务恢复",
                            "summary": str(details.get("error") or details.get("reason") or runtime_event["event_type"]),
                            "created_at": str(getattr(view, "updated_at", "")),
                            "input_refs": [],
                            "output_refs": [],
                            "details": details,
                        },
                        runtime_sequence=int(runtime_event["sequence"]),
                    )
        if event_repository is not None:
            # Repository-backed events are the live, authoritative timeline.
            # File-only session details remain available, but cannot push an
            # older terminal event behind a newer recovery/progress event.
            rows.sort(
                key=lambda item: (
                    0 if not item.get("_runtime_sequence", 0) else 1,
                    item.get("_runtime_sequence", 0),
                    item.get("created_at", ""),
                    item.get("event_id", ""),
                )
            )
        else:
            rows.sort(
                key=lambda item: (
                    item.get("created_at", ""),
                    item.get("event_id", ""),
                )
            )
        for row in rows:
            row.pop("_runtime_sequence", None)
        for sequence, row in enumerate(rows, start=1):
            row.setdefault("sequence", sequence)
        return rows

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/runtime-health")
    def runtime_health(x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        return service.runtime_health()

    @app.put("/api/v1/runtime-capacity")
    def update_runtime_capacity(
        body: UpdateRuntimeCapacityBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        config = write_worker_capacity(body.capacity, updated_by=x_role)
        return {
            "desired_capacity": config["desired_capacity"],
            "runtime": service.runtime_health(),
        }

    @app.get("/api/v1/runs")
    def list_runs(
        limit: int | None = Query(default=None, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        compact: bool = False,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> list[dict] | dict[str, object]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        all_views = list_views()
        # A supplied namespace is an explicit tenant/workspace view.  Keep
        # the historical no-header response intact for local integrations,
        # while ensuring list pagination and status counts cannot leak rows
        # from another tenant once a gateway context is present.
        requested_scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        cross_scope = x_role == "admin" and _cross_scope_requested(
            x_evolution_cross_scope
        )
        if _scope_is_supplied(requested_scope) or cross_scope:
            all_views = [
                item
                for item in all_views
                if _evolution_scope_access(
                    item.__dict__,
                    requested_scope,
                    role=x_role,
                    cross_scope=cross_scope,
                )
            ]
        views = all_views[offset : offset + limit] if limit is not None else all_views
        actual_by_run: dict[str, list[str]] = {}
        batch_loader = getattr(
            event_repository,
            "actual_baseline_agent_ids_by_run",
            None,
        )
        if callable(batch_loader):
            actual_by_run = batch_loader([item.run_id for item in views])
        elif event_repository is not None:
            actual_by_run = {
                item.run_id: _actual_baseline_agent_ids(
                    event_repository.events_after(item.run_id, 0)
                )
                for item in views
            }
        payload = [
            {
                **_public_run_view(item, output_root, compact=compact),
                "actual_agent_ids": actual_by_run.get(item.run_id, []),
                "actual_agent_count": len(actual_by_run.get(item.run_id, [])),
            }
            for item in views
        ]
        # Keep the historical no-parameter response as a plain list for API
        # compatibility. The paged form gives the remote UI enough metadata
        # to load older tasks only when the user scrolls.
        if limit is None:
            return payload
        status_counts: dict[str, int] = {}
        for item in all_views:
            status = str(getattr(item, "status", "") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "items": payload,
            "total": len(all_views),
            "status_counts": status_counts,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(views) < len(all_views),
        }

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        try:
            return _public_run_view(read_view(run_id), output_root)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/v1/catalog")
    def catalog() -> dict:
        return catalog_payload

    @app.get("/api/v1/model-profiles")
    def model_profiles(x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        return public_profiles()

    @app.get("/api/v1/model-profiles/{profile_id}")
    def model_profile(profile_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        try:
            selected, _ = get_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return next(item for item in public_profiles()["profiles"] if item["id"] == selected)

    @app.post("/api/v1/model-profiles/activate")
    def activate_model_profile(body: dict, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        profile_id = normalize_profile_id(str(body.get("profile_id", "")).strip())
        if not profile_id:
            raise HTTPException(status_code=422, detail="profile_id is required")
        try:
            result = activate_profile(profile_id)
            swarm_overrides = body.get("swarm_overrides")
            if isinstance(swarm_overrides, dict):
                result.update(activate_swarm_overrides(swarm_overrides))
        except (KeyError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**result, "active_profile": profile_id}

    @app.post("/api/v1/model-profiles/{profile_id}/doctor")
    def doctor_model_profile(profile_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            return doctor_profile(profile_id)
        except (KeyError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/agent-selection-preview")
    def agent_selection_preview(body: AgentSelectionPreviewBody) -> dict:
        problem = ResearchProblem(
            topic=body.topic.strip(),
            supplemental_information=body.supplemental_information.strip(),
            research_route=body.research_route,
            interaction_mode=body.interaction_mode,
            discovery_branch=body.discovery_branch,
        )
        available = {
            agent.agent_id: agent.capability_tags
            for agent in agent_registry.enabled_baseline_agents()
        }
        blueprint = build_discovery_blueprint(
            problem,
            available_agent_capabilities=available,
        )
        names = {
            agent.agent_id: agent.display_name
            for agent in agent_registry.enabled_baseline_agents()
        }
        active_plan = [
            {**item, "display_name": names.get(item["agent_id"], item["agent_id"])}
            for item in blueprint["baseline_agent_plan"]
            if item["mode"] in {"required", "reference"}
        ]
        return {
            "primary_branch": blueprint["primary_branch"],
            "branch_name": blueprint["branch_name"],
            "runtime_route": blueprint["runtime_route"],
            "selected_agent_ids": [item["agent_id"] for item in active_plan],
            "plan": active_plan,
            "callback_agent_ids": blueprint["callback_agent_ids"],
            "semantic_signals": blueprint["semantic_agent_signals"],
            "structured_query_brief": blueprint["structured_query_brief"],
            "policy": "Query主导军事作战发散 + A–H分支 + 能力覆盖；optimized_v2首轮3–4个独立Agent并行",
        }

    @app.post("/api/v1/runs", status_code=201)
    def create_run(
        body: CreateRunBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(
            default="", alias="X-Evolution-Stage-Scope"
        ),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        valid_routes = {item["id"] for item in catalog_payload["routes"]} | {"auto"}
        valid_agents = {item["agent_id"] for item in catalog_payload["agents"]}
        unknown_agents = sorted(set(body.selected_agent_ids) - valid_agents)
        if body.research_route not in valid_routes:
            raise HTTPException(status_code=422, detail="unknown research route")
        if body.interaction_mode not in {"expert", "autonomous"}:
            raise HTTPException(status_code=422, detail="unknown interaction mode")
        if body.discovery_branch not in {"auto", "A", "B", "C", "D", "E", "F", "G", "H"}:
            raise HTTPException(status_code=422, detail="unknown discovery branch")
        if body.execution_profile_id not in {
            "",
            "legacy_v1",
            "optimized_v2",
            "swarm_quality_v1",
            "winning_swarm_dynamic_v2",
            "deep_divergence_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown execution profile")
        if body.report_template_mode not in {
            "three_layer_nine_item",
            "project_argument_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown report template mode")
        valid_model_profiles = {
            str(item["id"])
            for item in catalog_payload["model_profiles"].get("profiles", [])
            if isinstance(item, dict) and item.get("id")
        }
        model_profile_id = normalize_profile_id(body.model_profile_id)
        if model_profile_id and model_profile_id not in valid_model_profiles:
            raise HTTPException(status_code=422, detail="unknown model profile")
        if unknown_agents:
            raise HTTPException(status_code=422, detail=f"unknown agent ids: {unknown_agents}")
        evolution_scope = _effective_evolution_scope(
            body=body.model_dump(mode="json"),
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
        )
        execution_input = dict(body.execution)
        if model_profile_id:
            execution_input["model_profile_id"] = model_profile_id
        try:
            execution = _validated_execution(execution_input, catalog_payload["provider"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not model_profile_id and execution.get("model_profile_id"):
            model_profile_id = normalize_profile_id(
                str(execution["model_profile_id"])
            )
        if body.source_query_id:
            try:
                source_query = query_library_service.get_query(
                    body.source_query_id, include_revisions=False
                )
                if (
                    source_query["status"] == "draft"
                    and body.publish_source_query_on_create
                ):
                    source_query = query_library_service.set_status(
                        body.source_query_id,
                        status="published",
                        expected_version=body.source_query_version,
                    ).to_dict()
            except QueryLibraryError as exc:
                status_code = 409 if isinstance(
                    exc, (VersionConflictError, InvalidStatusTransition)
                ) else 422
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc
            if source_query["status"] != "published":
                raise HTTPException(
                    status_code=409,
                    detail="source Query must be published before creating a research task",
                )
            if (
                body.source_query_version is not None
                and source_query["version"] != body.source_query_version
                and not (
                    body.publish_source_query_on_create
                    and source_query["status"] == "published"
                    and source_query["version"] == body.source_query_version + 1
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "source Query version changed; review the latest revision before "
                        "creating a research task"
                    ),
                )
            execution["query_library"] = {
                "query_id": source_query["query_id"],
                "version": source_query["version"],
                "source_type": source_query["source_type"],
            }
        command = CreateRunCommand(
            topic=body.topic.strip(),
            research_route=body.research_route,
            selected_agent_ids=body.selected_agent_ids,
            max_rounds=body.max_rounds,
            created_by="api-user",
            execution=execution,
            analyst_confirmed=body.analyst_confirmed,
            interaction_mode=body.interaction_mode,
            discovery_branch=body.discovery_branch,
            execution_profile_id=body.execution_profile_id,
            report_template_mode=body.report_template_mode,
            supplemental_information=body.supplemental_information.strip(),
            model_profile_id=model_profile_id,
            tenant_id=evolution_scope["tenant_id"],
            workspace_id=evolution_scope["workspace_id"],
            project_id=evolution_scope["project_id"],
            profile_id=(
                evolution_scope["profile_id"]
                or body.execution_profile_id
            ),
            stage_scope=evolution_scope["stage_scope"],
        )
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            return service.create_run(command).__dict__
        request_fingerprint = json.dumps(
            {
                **body.model_dump(mode="json"),
                "evolution_scope": evolution_scope,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with create_run_idempotency_lock:
            existing = create_run_idempotency.get(normalized_key)
            if existing is not None:
                existing_fingerprint, existing_run = existing
                if existing_fingerprint != request_fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="idempotency key was already used with a different request",
                    )
                return existing_run.__dict__
            created_run = service.create_run(command)
            create_run_idempotency[normalized_key] = (
                request_fingerprint,
                created_run,
            )
            return created_run.__dict__

    @app.post("/api/v1/runs/{run_id}/start")
    def start_run(run_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            run = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        missing_credentials = _missing_execution_credentials(run.execution)
        if missing_credentials:
            raise HTTPException(
                status_code=422,
                detail=(
                    "missing configured provider credentials: "
                    + ", ".join(missing_credentials)
                ),
            )
        try:
            return service.start_run(run_id, actor="api-user", idempotency_key=idempotency_key).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/resume")
    def resume_run(
        run_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        x_role: str = Header(default="analyst", alias="X-Role"),
        model_profile_id: str = "",
    ) -> dict:
        """Resume a paused run or retry a failed run from its checkpoint."""

        _require_role(x_role, {"analyst", "admin"})
        try:
            run = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        resume_execution = dict(run.execution)
        if resume_execution.get("mode") == "real":
            try:
                resume_input: dict[str, object] = {"mode": "real"}
                # An explicit profile is required when a completed limited
                # task is being reopened for S6-only rewriting.  Otherwise
                # preserve the task-pinned profile for ordinary resumes.
                pinned_profile_id = normalize_profile_id(
                    str(model_profile_id or resume_execution.get("model_profile_id", "") or "").strip()
                )
                if pinned_profile_id:
                    # A task-pinned model must stay stable across resume.
                    # Re-resolve its safe execution tuple instead of inheriting
                    # whichever deployment-wide profile is currently active.
                    try:
                        resume_input.update(profile_execution(pinned_profile_id))
                    except (KeyError, OSError, ValueError):
                        pinned_profile_id = ""
                if not pinned_profile_id:
                    current_provider = configured_provider(fallback="")
                    if current_provider:
                        # The server environment is authoritative for resumed
                        # runs that do not pin a task-level profile.
                        resume_input["provider"] = current_provider
                    else:
                        resume_input["provider"] = (
                            resume_execution.get("provider")
                            or catalog_payload["provider"].get(
                                "default_provider", "codex"
                            )
                        )
                if pinned_profile_id:
                    resume_input["model_profile_id"] = pinned_profile_id
                resume_execution = _validated_execution(
                    resume_input,
                    catalog_payload["provider"],
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        missing_credentials = _missing_execution_credentials(resume_execution)
        if missing_credentials:
            raise HTTPException(
                status_code=422,
                detail=(
                    "missing configured provider credentials: "
                    + ", ".join(missing_credentials)
                ),
            )
        try:
            return service.resume_run(
                run_id,
                actor="api-user",
                idempotency_key=idempotency_key,
                execution=resume_execution,
            ).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/stop")
    def stop_run(
        run_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        """Stop a queued or running task and terminate all of its child processes."""

        _require_role(x_role, {"analyst", "admin"})
        try:
            current = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if current.status in {"cancelled", "completed", "failed", "archived"}:
            cleanup = terminate_run_process_groups(run_id)
            return {
                **current.__dict__,
                "process_cleanup": cleanup.__dict__,
            }
        try:
            stopped = service.cancel_run(
                run_id,
                actor="api-user",
                idempotency_key=idempotency_key,
            )
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        cleanup = terminate_run_process_groups(run_id)
        stopped = service.set_status(run_id, "cancelled")
        service.publish_runtime_event(
            run_id,
            "run_processes_terminated",
            {
                "reason": "user_stop",
                "registered_process_groups": cleanup.registered_count,
                "orphan_process_groups": cleanup.orphan_count,
                "terminated_process_groups": cleanup.terminated_count,
                "forced_process_groups": cleanup.forced_count,
            },
        )
        return {
            **stopped.__dict__,
            "process_cleanup": cleanup.__dict__,
        }

    @app.patch("/api/v1/runs/{run_id}")
    def update_run(
        run_id: str,
        body: UpdateRunBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(
            default="", alias="X-Evolution-Stage-Scope"
        ),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            current = service.get_run(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        valid_routes = {item["id"] for item in catalog_payload["routes"]} | {"auto"}
        valid_agents = {item["agent_id"] for item in catalog_payload["agents"]}
        unknown_agents = sorted(set(body.selected_agent_ids) - valid_agents)
        if body.research_route not in valid_routes:
            raise HTTPException(status_code=422, detail="unknown research route")
        if body.interaction_mode not in {"expert", "autonomous"}:
            raise HTTPException(status_code=422, detail="unknown interaction mode")
        if body.discovery_branch not in {"auto", "A", "B", "C", "D", "E", "F", "G", "H"}:
            raise HTTPException(status_code=422, detail="unknown discovery branch")
        if body.execution_profile_id not in {
            "",
            "legacy_v1",
            "optimized_v2",
            "swarm_quality_v1",
            "winning_swarm_dynamic_v2",
            "deep_divergence_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown execution profile")
        if body.report_template_mode not in {
            "",
            "three_layer_nine_item",
            "project_argument_v1",
        }:
            raise HTTPException(status_code=422, detail="unknown report template mode")
        valid_model_profiles = {
            str(item["id"])
            for item in catalog_payload["model_profiles"].get("profiles", [])
            if isinstance(item, dict) and item.get("id")
        }
        model_profile_id = normalize_profile_id(body.model_profile_id)
        if model_profile_id and model_profile_id not in valid_model_profiles:
            raise HTTPException(status_code=422, detail="unknown model profile")
        if unknown_agents:
            raise HTTPException(status_code=422, detail=f"unknown agent ids: {unknown_agents}")
        evolution_scope = _effective_evolution_scope(
            body=body.model_dump(mode="json"),
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
        )
        # A run's tenant/workspace/project/profile namespace is immutable once
        # created. Gateway headers/body values may only agree with it (or be
        # omitted); silently relabelling a draft would allow cross-tenant
        # memory retrieval after queueing.
        for key in ("tenant_id", "workspace_id", "project_id", "profile_id"):
            current_value = _bounded_scope_id(getattr(current, key, ""))
            requested_value = str(evolution_scope.get(key, ""))
            if current_value and requested_value and current_value != requested_value:
                raise HTTPException(status_code=403, detail=f"{key} scope mismatch")
            if current_value and not requested_value:
                evolution_scope[key] = current_value
        current_stages = _normalized_stage_scope(getattr(current, "stage_scope", []))
        if current_stages:
            requested_stages = evolution_scope["stage_scope"]
            if requested_stages:
                if not set(requested_stages).issubset(set(current_stages)):
                    raise HTTPException(status_code=403, detail="stage_scope mismatch")
            else:
                evolution_scope["stage_scope"] = current_stages
        current_model_profile_id = normalize_profile_id(
            str(
                current.model_profile_id
                or current.execution.get("model_profile_id", "")
            )
        )
        effective_model_profile_id = model_profile_id or current_model_profile_id
        execution_input = dict(body.execution)
        if model_profile_id:
            execution_input["model_profile_id"] = model_profile_id
        elif current_model_profile_id:
            execution_input["model_profile_id"] = current_model_profile_id
        try:
            execution = _validated_execution(execution_input, catalog_payload["provider"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            query_reference = current.execution.get("query_library")
            if isinstance(query_reference, dict):
                execution["query_library"] = dict(query_reference)
            return service.update_run(
                run_id,
                UpdateRunCommand(
                    topic=body.topic,
                    research_route=body.research_route,
                    selected_agent_ids=body.selected_agent_ids,
                    max_rounds=body.max_rounds,
                    execution=execution,
                    analyst_confirmed=body.analyst_confirmed,
                    interaction_mode=body.interaction_mode,
                    discovery_branch=body.discovery_branch,
                    execution_profile_id=body.execution_profile_id,
                    report_template_mode=body.report_template_mode,
                    supplemental_information=(
                        None
                        if body.supplemental_information is None
                        else body.supplemental_information.strip()
                    ),
                    model_profile_id=effective_model_profile_id,
                    tenant_id=evolution_scope["tenant_id"],
                    workspace_id=evolution_scope["workspace_id"],
                    project_id=evolution_scope["project_id"],
                    profile_id=evolution_scope["profile_id"],
                    stage_scope=(
                        evolution_scope["stage_scope"]
                        if evolution_scope["stage_scope"]
                        else None
                    ),
                ),
                actor="api-user",
            ).__dict__
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.delete("/api/v1/runs/{run_id}")
    def archive_run(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            archived = service.archive_run(run_id, actor="api-user")
            update_favorite_sources(
                run_id,
                source_status="archived",
                source_deleted=False,
            )
            return archived.__dict__
        except (KeyError, NoResultFound, InvalidRunTransition) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/v1/runs/{run_id}/permanent")
    def permanently_delete_run(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            permanently_remove(run_id)
            return {"run_id": run_id, "deleted": True}
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except InvalidRunTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/v1/runs/permanent-delete")
    def permanently_delete_runs(
        body: DeleteRunsBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        deleted = []
        rejected = []
        for run_id in dict.fromkeys(body.run_ids):
            try:
                permanently_remove(run_id)
                deleted.append(run_id)
            except (KeyError, NoResultFound):
                rejected.append({"run_id": run_id, "reason": "run not found"})
            except InvalidRunTransition as exc:
                rejected.append({"run_id": run_id, "reason": str(exc)})
            except RuntimeError as exc:
                rejected.append({"run_id": run_id, "reason": str(exc)})
        return {"deleted": deleted, "rejected": rejected}

    @app.get("/api/v1/runs/{run_id}/history")
    def get_run_history(
        run_id: str,
        compact: bool = False,
        limit: int = Query(default=120, ge=1, le=500),
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        try:
            view = read_view(run_id)
        except (KeyError, NoResultFound) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        rows = [] if event_repository is None else event_repository.events_after(run_id, 0)
        if not rows:
            payload = [
                {
                    "sequence": int(row.get("sequence", index)),
                    "event_type": str(row.get("event_type", "trace_event")),
                    "payload": sanitize_runtime_payload(row),
                }
                for index, row in enumerate(interaction_rows(run_id, view), start=1)
            ]
            if not compact or len(payload) <= limit:
                return payload
            head_count = min(12, max(1, limit // 4))
            return [*payload[:head_count], *payload[-(limit - head_count):]]
        payload = []
        for row in rows:
            sequence = int(row.get("sequence", 0) or 0)
            row_event_type = row.get("event_type", "trace_event")
            row_payload = row.get("payload", {})
            if _is_deep_runtime_event(row_event_type, row_payload):
                deep_payload = dict(row_payload) if isinstance(row_payload, Mapping) else {}
                deep_payload.setdefault("event_id", f"runtime-{sequence}")
                public_payload = _deep_public_event_payload(
                    deep_payload,
                    run_id=run_id,
                    sequence=sequence,
                    event_type=row_event_type,
                )
                payload.append(
                    {
                        "sequence": sequence,
                        "event_type": public_payload["event_type"],
                        "payload": public_payload,
                    }
                )
            else:
                payload.append(
                    {
                        "sequence": sequence,
                        "event_type": str(row_event_type),
                        "payload": sanitize_runtime_payload(row_payload),
                    }
                )
        if not compact or len(payload) <= limit:
            return payload
        # The drawer only needs enough history to show the current stage and
        # the latest transitions. Keep a small head for early-stage context
        # and the tail for the current state.
        head_count = min(12, max(1, limit // 4))
        return [*payload[:head_count], *payload[-(limit - head_count):]]

    @app.get("/api/v1/runs/{run_id}/events")
    async def replay_events(run_id: str, last_event_id: str = Header(default="0", alias="Last-Event-ID"), x_role: str = Header(default="analyst", alias="X-Role")) -> StreamingResponse:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        async def stream():
            raw_cursor = str(last_event_id or "0").strip()
            try:
                cursor = max(0, int(raw_cursor))
            except (TypeError, ValueError):
                # Deep events also expose an opaque event_id for clients that
                # persisted that value instead of the numeric SSE id.  Resolve
                # it from the generic runtime payload before starting replay;
                # unknown cursors deliberately fall back to a full replay.
                cursor = 0
                if event_repository is not None:
                    try:
                        for candidate in event_repository.events_after(run_id, 0):
                            payload = candidate.get("payload", {})
                            if isinstance(payload, Mapping) and str(payload.get("event_id", "")) == raw_cursor:
                                cursor = max(0, int(candidate.get("sequence", 0) or 0))
                                break
                    except Exception:
                        cursor = 0
            idle_cycles = 0
            while True:
                rows = [] if event_repository is None else event_repository.events_after(run_id, cursor)
                for row in rows:
                    cursor = int(row["sequence"])
                    # Runtime repositories may contain provider/tool metadata
                    # written by older workers.  Keep the SSE boundary on the
                    # same redaction contract as /history; otherwise a live
                    # stream could leak credentials that a replayed history
                    # correctly hides.
                    row_event_type = row.get("event_type", "trace_event")
                    row_payload = row.get("payload", {})
                    if _is_deep_runtime_event(row_event_type, row_payload):
                        deep_payload = dict(row_payload) if isinstance(row_payload, Mapping) else {}
                        deep_payload.setdefault("event_id", f"runtime-{cursor}")
                        safe_payload = _deep_public_event_payload(
                            deep_payload,
                            run_id=run_id,
                            sequence=cursor,
                            event_type=row_event_type,
                        )
                        event_name = safe_payload["event_type"]
                    else:
                        safe_payload = sanitize_runtime_payload(row_payload)
                        event_name = _runtime_public_event_type(row_event_type)
                    yield f"id: {cursor}\nevent: {event_name}\ndata: {json.dumps(safe_payload, ensure_ascii=False)}\n\n"
                idle_cycles = 0 if rows else idle_cycles + 1
                try:
                    status = read_view(run_id).status
                except (KeyError, NoResultFound):
                    break
                if status in {"completed", "failed", "cancelled"} and not rows:
                    break
                if idle_cycles >= 20:
                    idle_cycles = 0
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)
        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/runs/{run_id}/summary")
    def get_summary(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        if _is_historical_snapshot(view):
            return {
                "run_id": run_id,
                "topic": view.topic,
                "historical_snapshot": True,
                "message": "原始任务产物未随恢复快照保存，未伪造摘要。",
            }
        return _read_json(service, output_root, run_id, "round_summary.json")

    @app.get("/api/v1/runs/{run_id}/capabilities")
    def get_capabilities(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        if _is_historical_snapshot(view):
            return []
        # While a run is active, expose only cards actually authored by S6.
        # The earlier frozen portfolio is an S5 selection decision and must
        # never be presented as an original S6 capability portrait. Once
        # delivery completes, capability_images.json is authoritative because
        # it contains the accepted parallel S6 prose and any identity restored
        # from the pre-S6 hypothesis ledger. Returning the earlier portfolio
        # event after completion would surface stale titles and omit portraits.
        root = _resolve_run_root(output_root, run_id, getattr(view, "result", {}))
        feedback_rows = load_run_feedback(root)
        global_favorites = list_favorite_records(
            scope="global",
            owner_id="workspace",
            # Star state is scoped to the current run.  Filtering at the
            # repository avoids silently dropping a card when the workspace
            # has more than the page-size cap of older favorites.
            run_id=run_id,
            offset=0,
            limit=200,
            search="",
            capability_type="",
        ).get("items", [])
        favorite_by_alias: dict[str, dict[str, Any]] = {}
        for favorite in global_favorites:
            if not isinstance(favorite, Mapping):
                continue
            # A favorite row stores the canonical key, while older clients may
            # navigate by capability_id or card_binding_id.  Index all aliases
            # to keep the star state stable across artifact versions.
            for alias in _favorite_identity_aliases(favorite):
                favorite_by_alias.setdefault(alias, dict(favorite))

        def project(rows: list[dict]) -> list[dict]:
            projected = []
            for row in rows:
                item = _capability_api_view(row)
                # The five structured modules are authoritative for the UI.
                # Reassemble once more after all legacy-field normalization so
                # an old ``capability_image`` blob cannot overwrite the
                # repaired 360–400-character columns.
                final_modules = item.get("capability_portrait_modules")
                if isinstance(final_modules, dict):
                    final_portrait = assemble_capability_portrait_modules(
                        {
                            **final_modules,
                            "capability_classification": item.get(
                                "capability_classification", {}
                            ),
                        }
                    )
                    if final_portrait:
                        item["capability_image"] = final_portrait
                        item["deep_capability_portrait"] = final_portrait
                capability_id = str(item.get("capability_id", "")).strip()
                capability_name = str(item.get("name", "")).strip()
                card_binding_id = str(item.get("card_binding_id", "")).strip()
                card_id = card_binding_id or capability_id
                card_key = _favorite_card_key(item)
                favorite = next(
                    (
                        favorite_by_alias.get(alias)
                        for alias in _favorite_identity_aliases(item)
                        if favorite_by_alias.get(alias) is not None
                    ),
                    None,
                )
                item["card_binding_id"] = card_binding_id
                item["card_id"] = card_id
                item["card_key"] = card_key
                item["favorited"] = favorite is not None
                item["favorite_id"] = (
                    str(favorite.get("favorite_id", "")).strip()
                    if isinstance(favorite, Mapping)
                    else ""
                )
                item["expert_feedback"] = [
                    feedback
                    for feedback in feedback_rows
                    if (
                        capability_id
                        and str(feedback.get("capability_id", "")).strip() == capability_id
                    )
                    or (
                        capability_name
                        and str(feedback.get("capability_name", "")).strip() == capability_name
                    )
                ]
                item["expert_feedback_count"] = len(item["expert_feedback"])
                projected.append(item)
            return projected

        def with_deep_research(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
            """Project capability versions without mutating the formal artifact.

            ``capability_versions`` is the authoritative deep-research ledger.
            A JSON sidecar is consulted only when the run has no durable
            version rows (the migration fallback for pre-ledger runs).  This
            distinction is important: merging both stores can resurrect
            rejected drafts, duplicate formal v1, and make a stale sidecar
            override a reviewer decision.  Projection is read-only; all
            writes remain owned by the explicit deep-research commands.
            """

            raw_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
            combined = list(raw_rows)

            def _identity_values(value: Mapping[str, Any]) -> set[str]:
                # IDs are the only safe cross-version identity.  Names are
                # intentionally a last-resort match for legacy artifacts that
                # predate hypothesis/binding persistence.
                values = {
                    str(value.get(field, "") or "").strip()
                    for field in ("card_binding_id", "hypothesis_id", "capability_id")
                }
                values = {item for item in values if item}
                if not values:
                    name = str(value.get("name") or value.get("title") or "").strip()
                    if name:
                        values.add(f"name:{name.casefold()}")
                return values

            def _same_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
                left_ids = {
                    str(left.get(field, "") or "").strip()
                    for field in ("card_binding_id", "hypothesis_id", "capability_id")
                    if str(left.get(field, "") or "").strip()
                }
                right_ids = {
                    str(right.get(field, "") or "").strip()
                    for field in ("card_binding_id", "hypothesis_id", "capability_id")
                    if str(right.get(field, "") or "").strip()
                }
                if left_ids and right_ids:
                    return bool(left_ids.intersection(right_ids))
                # Name matching is only a compatibility bridge when at least
                # one side predates stable IDs.  Never collapse two distinct
                # ID-bearing cards that happen to share a display name.
                left_name = str(left.get("name") or left.get("title") or "").strip().casefold()
                right_name = str(right.get("name") or right.get("title") or "").strip().casefold()
                return bool(left_name and right_name and left_name == right_name)

            def _status(value: Mapping[str, Any]) -> str:
                raw = value.get("status") or value.get("version_status") or value.get("verification_status") or "pending_verification"
                normalized = str(raw).strip().lower().replace("-", "_")
                aliases = {
                    "approved": "verified",
                    "accepted": "verified",
                    "pending": "pending_verification",
                    "unverified": "pending_verification",
                    "rolledback": "rolled_back",
                }
                return aliases.get(normalized, normalized)

            def _version_no(value: Mapping[str, Any]) -> int:
                try:
                    return max(1, int(value.get("version_no", value.get("research_version", 1)) or 1))
                except (TypeError, ValueError):
                    return 1

            def _row_version_no(value: Mapping[str, Any]) -> int:
                try:
                    return max(0, int(value.get("version_no", value.get("research_version", 0)) or 0))
                except (TypeError, ValueError):
                    return 0

            def _project_version(version: Mapping[str, Any]) -> dict[str, Any] | None:
                snapshot = version.get("snapshot")
                if not isinstance(snapshot, Mapping):
                    return None
                status = _status(version)
                # Rejected/rolled-back history remains available through the
                # version endpoint, but must never enter the default portrait
                # projection or become eligible for collection.
                if status in {
                    "rejected",
                    "rolled_back",
                    "cancelled",
                    "failed",
                    "blocked",
                    "partial",
                } or status not in {"formal", "pending_verification", "verified"}:
                    return None
                item = dict(snapshot)
                number = _version_no(version)
                item["version_id"] = str(version.get("version_id", item.get("version_id", "")) or "")
                item["research_version"] = number
                item["version_no"] = number
                item["version_status"] = status
                item["capability_version_status"] = status
                item["is_deep_research"] = status != "formal"
                # Keep the public verification vocabulary stable even when a
                # legacy snapshot used ``version_status`` only.
                if status == "formal":
                    item["verification_status"] = "formal"
                    item["confidence_limited"] = bool(item.get("confidence_limited", False))
                elif status == "verified":
                    item["verification_status"] = "verified"
                    # A reviewed version is a formal collectible projection;
                    # stale deep-draft flags in its snapshot must not block
                    # the favorites eligibility check.
                    item["confidence_limited"] = False
                else:
                    item["verification_status"] = "pending"
                    item["confidence_limited"] = True
                item.setdefault("source", str(version.get("source", "deep-thinking") or "deep-thinking"))
                return item

            repo = _deep_repository()
            durable_versions: list[Mapping[str, Any]] = []
            # Distinguish a successful empty SQLite query from an unavailable
            # or legacy adapter.  Once a deep-capability ledger is present,
            # its empty result is authoritative: falling back to a stale JSON
            # sidecar here can resurrect drafts that were rejected/deleted.
            durable_query_succeeded = False
            durable_method_available = False
            durable_read_error = False
            if repo is not None:
                list_versions = getattr(repo, "list_capability_versions", None)
                if callable(list_versions):
                    durable_method_available = True
                    try:
                        loaded = list_versions(run_id)
                        if isinstance(loaded, Sequence) and not isinstance(loaded, (str, bytes)):
                            durable_versions = [item for item in loaded if isinstance(item, Mapping)]
                            durable_query_succeeded = True
                    except Exception:
                        # A temporarily unavailable ledger is *not* a
                        # migration fallback.  Returning the formal artifact
                        # alone is safer than merging a possibly stale sidecar
                        # while the source of truth cannot be read.
                        durable_versions = []
                        durable_read_error = True

            def _looks_deep(value: Mapping[str, Any]) -> bool:
                source = str(value.get("source", "") or "").strip().lower()
                explicit_status = str(
                    value.get("version_status")
                    or value.get("capability_version_status")
                    or ""
                ).strip().lower().replace("-", "_")
                if explicit_status == "formal" and not value.get("is_deep_research") and source not in {
                    "deep-thinking",
                    "reference_weapon_deep_research",
                    "reference_weapon",
                }:
                    return False
                return bool(
                    value.get("is_deep_research")
                    or source in {"deep-thinking", "reference_weapon_deep_research", "reference_weapon"}
                    or value.get("version_id")
                    or value.get("version_status")
                    or value.get("research_version")
                )

            if durable_query_succeeded:
                # The artifact may have been explicitly merged before the SQL
                # write completed.  Treat those rows as a compatibility
                # projection and rebuild them from the durable versions below;
                # only original formal S6 rows remain from the JSON artifact.
                combined = [row for row in raw_rows if not _looks_deep(row)]
                # Formal v1 is already represented by the delivered S6 row in
                # normal runs.  Annotate that row rather than appending a
                # duplicate; if the artifact is missing, materialize the
                # immutable baseline from SQLite so the formal card remains
                # visible.
                for version in durable_versions:
                    projected = _project_version(version)
                    if projected is None:
                        continue
                    status = _status(version)
                    matching = next((item for item in combined if _same_identity(item, projected)), None)
                    if status == "formal" and matching is not None:
                        matching["version_id"] = projected.get("version_id", "")
                        matching["research_version"] = projected.get("research_version", 1)
                        matching["version_no"] = projected.get("version_no", 1)
                        matching["version_status"] = "formal"
                        matching["capability_version_status"] = "formal"
                        matching["is_deep_research"] = False
                        matching["verification_status"] = "formal"
                        continue
                    # Avoid duplicate rows when a merge operation has already
                    # appended the same version to the legacy artifact.
                    version_id = str(projected.get("version_id", "")).strip()
                    number = _version_no(version)
                    duplicate = any(
                        _same_identity(item, projected)
                        and (
                            (
                                version_id
                                and str(item.get("version_id", "")).strip() == version_id
                            )
                            or (
                                _row_version_no(item) == number
                                and str(item.get("version_status", "")).strip().lower() == _status(version)
                            )
                        )
                        for item in combined
                    )
                    if not duplicate:
                        combined.append(projected)
                return combined

            if durable_read_error:
                # Preserve the immutable S6 artifact for read continuity, but
                # do not surface deep drafts whose verification status cannot
                # be checked against SQLite.
                return raw_rows

            # Compatibility path for runs created before capability_versions.
            # A repository that exposes the version method but returned an
            # empty result has already taken the authoritative branch above;
            # this fallback is only for adapters that predate the ledger API.
            if durable_method_available:
                return raw_rows
            combined = [
                row
                for row in raw_rows
                if not (
                    _looks_deep(row)
                    and _status(row) in {"rejected", "rolled_back", "cancelled", "failed", "blocked", "partial"}
                )
            ]
            for extra in list_reference_research(output_root, run_id=run_id):
                if not isinstance(extra, Mapping):
                    continue
                item = dict(extra)
                status = _status(item)
                if status in {"rejected", "rolled_back", "cancelled", "failed", "blocked", "partial"}:
                    continue
                item.setdefault("is_deep_research", True)
                item.setdefault("research_version", _version_no(item))
                item.setdefault("version_no", item.get("research_version", 1))
                item.setdefault("version_status", status)
                item["verification_status"] = "verified" if status == "verified" else "pending"
                item["confidence_limited"] = False if status == "verified" else True
                if not any(
                    _same_identity(existing, item)
                    and _row_version_no(existing)
                    == int(item.get("research_version", item.get("version_no", 1)) or 1)
                    for existing in combined
                ):
                    combined.append(item)
            return combined

        # The completed capability snapshot is the authoritative page data.
        # Read it before rebuilding the much larger interaction workflow so a
        # capability click stays fast even when the trace contains thousands
        # of events and session records.
        if view.status == "completed":
            try:
                payload = _read_json(service, output_root, run_id, "capability_images.json")
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            else:
                rows = payload if isinstance(payload, list) else payload.get("capability_images", [])
                if isinstance(rows, list) and rows:
                    return project(_suppress_cross_card_capability_contamination(
                        with_deep_research([row for row in rows if isinstance(row, dict)])
                    ))

        workflow = _interaction_workflow_summary(interaction_rows(run_id, view), view)
        s6_cards = workflow.get("swarm_cluster", {}).get("s6_authored_cards", [])
        provisional_rows = _provisional_s6_capability_rows(s6_cards)

        if view.status != "completed":
            # S6 capability images are persisted before deferred Reporter
            # delivery begins. Prefer that durable artifact during reporting;
            # fall back to live S6 cards for the short window before the
            # snapshot is written. Never expose the earlier S5 portfolio as a
            # finished capability image.
            try:
                early_payload = _read_json(service, output_root, run_id, "capability_images.json")
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                return project(_suppress_cross_card_capability_contamination(with_deep_research(provisional_rows)))
            early_rows = early_payload if isinstance(early_payload, list) else early_payload.get("capability_images", [])
            if early_rows:
                return project(_suppress_cross_card_capability_contamination(with_deep_research([row for row in early_rows if isinstance(row, dict)])))
            return project(_suppress_cross_card_capability_contamination(with_deep_research(provisional_rows)))
        try:
            payload = _read_json(service, output_root, run_id, "capability_images.json")
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if provisional_rows:
                return project(_suppress_cross_card_capability_contamination(provisional_rows))
            raise
        else:
            rows = payload if isinstance(payload, list) else payload.get("capability_images", [])
            # A resumed S6-only run can finish its report with the durable
            # capability-image snapshot temporarily empty even though the
            # accepted parallel S6 cards are present in the interaction
            # trace. Keep the completed view useful and truthful by using
            # those authored cards until the snapshot writer catches up.
            if not rows and provisional_rows:
                rows = provisional_rows
        safe_rows = _suppress_cross_card_capability_contamination(
            with_deep_research([row for row in rows if isinstance(row, dict)])
        )
        return project(safe_rows)

    # ------------------------------------------------------------------
    # Bounded expert follow-up / deep-thinking sessions
    # ------------------------------------------------------------------
    def _deep_run_scope(view: object) -> dict[str, Any]:
        return {
            "tenant_id": str(getattr(view, "tenant_id", "") or ""),
            "workspace_id": str(getattr(view, "workspace_id", "") or ""),
            "project_id": str(getattr(view, "project_id", "") or ""),
            "profile_id": str(getattr(view, "profile_id", "") or ""),
            "stage_scope": list(getattr(view, "stage_scope", []) or []),
        }

    def _assert_deep_scope(
        view: object,
        *,
        role: str,
        tenant_id: str = "",
        workspace_id: str = "",
        project_id: str = "",
        profile_id: str = "",
        stage_scope: str = "",
        cross_scope: bool = False,
        mutation: bool = False,
    ) -> dict[str, Any]:
        target = _deep_run_scope(view)
        requested = _scope_request(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            profile_id=profile_id,
            stage_scope=stage_scope,
        )
        # Cross-tenant access is an explicit, opt-in operation for a trusted
        # admin.  The ASGI auth middleware has already validated the trusted
        # role/header combination; keep the same gate at the deep-research
        # route boundary so admin cross-scope requests are not rejected by
        # the ordinary parent-run comparison while lower roles cannot use the
        # flag as a wildcard.
        if cross_scope:
            if str(role or "").strip().lower() != "admin":
                raise HTTPException(status_code=403, detail="cross-scope access requires admin")
            if mutation:
                parent_status = str(getattr(view, "status", "") or "").strip().lower()
                if parent_status in {"cancelled", "cancel_requested"}:
                    raise HTTPException(
                        status_code=409,
                        detail="deep research is unavailable for a cancelled parent run",
                    )
                if parent_status in {"archived", "deleted"}:
                    raise HTTPException(
                        status_code=410,
                        detail="deep research source run is no longer mutable",
                    )
            effective = dict(target)
            effective["route"] = requested.get("route", "")
            return effective
        # A session is subordinate to its parent run.  A supplied namespace
        # may narrow access but can never relabel the run.
        for key in ("tenant_id", "workspace_id", "project_id", "profile_id"):
            actual = str(target.get(key, ""))
            supplied = str(requested.get(key, ""))
            if actual and supplied and actual != supplied:
                raise HTTPException(status_code=403, detail=f"{key} scope mismatch")
            if actual and not supplied:
                requested[key] = actual
        actual_stages = set(_normalized_stage_scope(target.get("stage_scope")))
        wanted_stages = set(_normalized_stage_scope(requested.get("stage_scope")))
        if actual_stages and wanted_stages and not actual_stages.intersection(wanted_stages):
            raise HTTPException(status_code=403, detail="stage_scope mismatch")
        if actual_stages and not wanted_stages:
            requested["stage_scope"] = sorted(actual_stages)
        if mutation:
            # Historical artifacts remain readable after a parent run is
            # archived/cancelled, but no new deep session, message, merge or
            # child research may be created against that immutable source.
            # Keep this check after namespace authorization so it cannot be
            # used to probe the state of another tenant/workspace.
            parent_status = str(getattr(view, "status", "") or "").strip().lower()
            if parent_status in {"cancelled", "cancel_requested"}:
                raise HTTPException(
                    status_code=409,
                    detail="deep research is unavailable for a cancelled parent run",
                )
            if parent_status in {"archived", "deleted"}:
                raise HTTPException(
                    status_code=410,
                    detail="deep research source run is no longer mutable",
                )
        return requested

    def _deep_query(view: object) -> str:
        topic = str(getattr(view, "topic", "") or "").strip()
        supplement = str(getattr(view, "supplemental_information", "") or "").strip()
        return topic if not supplement else f"{topic}\n{supplement}"

    def _deep_version_id(kind: str, job_id: str, artifact: Mapping[str, Any]) -> str:
        """Return a retry-stable capability-version identifier.

        Deep workers may be restarted after the artifact has already been
        authored.  Timestamps in the artifact are intentionally excluded from
        the fallback digest; when a durable job id is available it is the
        strongest idempotency boundary and therefore becomes the version id
        directly.  This prevents a recovery/retry from appending v3 for the
        same logical turn merely because ``updated_at`` changed.
        """

        normalized_kind = re.sub(r"[^a-z0-9_-]+", "-", str(kind or "deep").strip().lower())[:40] or "deep"
        normalized_job = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(job_id or "").strip())[:180]
        if normalized_job:
            return f"version-{normalized_kind}-{normalized_job}"
        stable_payload = {
            str(key): value
            for key, value in dict(artifact or {}).items()
            if str(key) not in {"created_at", "updated_at", "merged_at"}
        }
        digest = hashlib.sha256(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]
        return f"version-{normalized_kind}-{digest}"

    def _deep_repository() -> object | None:
        # ``service.repository`` is normally the same object as
        # ``event_repository``, but lightweight embedders/tests sometimes
        # provide a run repository without the deep-ledger methods and pass a
        # separate event repository.  Do not let the first (unsupported)
        # object shadow a valid deep repository behind it.
        seen: set[int] = set()
        for candidate in (
            getattr(service, "repository", None),
            event_repository,
        ):
            if candidate is None or id(candidate) in seen:
                continue
            seen.add(id(candidate))
            if callable(getattr(candidate, "create_deep_session", None)):
                return candidate
        return None

    def _deep_research_rows(
        run_id: str,
        *,
        include_history: bool = True,
        include_partial: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """Read deep-research artifacts from SQLite, with legacy fallback.

        The JSON reference-research ledger predates ``capability_versions``.
        Once any durable version exists for a run it is the sole source for
        this projection; otherwise the sidecar is read for backward
        compatibility.  This helper is intentionally read-only so GET
        endpoints cannot create/merge versions as a polling side effect.
        """

        repo = _deep_repository()
        if repo is not None:
            list_versions = getattr(repo, "list_capability_versions", None)
            if callable(list_versions):
                try:
                    versions = list_versions(run_id)
                except Exception as exc:
                    # A configured durable ledger is authoritative.  Do not
                    # silently merge a stale sidecar when it is unavailable.
                    if strict:
                        raise _DeepLedgerUnavailable(
                            "deep capability version ledger unavailable"
                        ) from exc
                    return []
                # A successful SQL query is authoritative even when it is
                # empty.  Falling back on ``if versions`` used to resurrect
                # deleted/rejected sidecar artifacts after a restart.
                rows: list[dict[str, Any]] = []
                if not isinstance(versions, Sequence) or isinstance(versions, (str, bytes)):
                    return rows
                for version in versions:
                    if not isinstance(version, Mapping) or not isinstance(version.get("snapshot"), Mapping):
                        continue
                    status = str(version.get("status", "pending_verification") or "pending_verification").strip().lower().replace("-", "_")
                    # ``partial`` rows are recoverable drafts, but should not
                    # be treated as publishable capability cards by ordinary
                    # projections.  Callers performing an explicit retry or
                    # merge may opt in with ``include_partial=True``.
                    hidden_statuses = {"rejected", "rolled_back", "cancelled", "failed", "blocked"}
                    if not include_partial:
                        hidden_statuses.add("partial")
                    if not include_history and status in hidden_statuses:
                        continue
                    # Version snapshots can outlive an older worker that did
                    # not apply the deep-event sanitizer.  Treat the ledger
                    # as untrusted input at this projection boundary so
                    # capability views cannot leak provider credentials or
                    # raw metadata after an upgrade.
                    snapshot = sanitize_runtime_payload(
                        dict(version["snapshot"]), max_string_length=12000
                    )
                    if not isinstance(snapshot, dict):
                        continue
                    snapshot.update(
                        {
                            "version_id": str(version.get("version_id", snapshot.get("version_id", "")) or ""),
                            "version_no": version.get("version_no", snapshot.get("version_no", 1)),
                            "research_version": version.get("version_no", snapshot.get("research_version", 1)),
                            "version_status": status,
                            "capability_version_status": status,
                            "is_deep_research": status != "formal",
                            "source": str(version.get("source", snapshot.get("source", "deep-thinking")) or "deep-thinking"),
                        }
                    )
                    rows.append(snapshot)
                return rows
            # An old adapter without the capability-version method cannot
            # answer this projection; retain sidecar compatibility only for
            # that explicitly legacy case.
        # No SQL rows means a pre-ledger run; this is the only case in which
        # the compatibility sidecar is authoritative.
        return list_reference_research(output_root, run_id=run_id)

    def _deep_canonical_fingerprint(
        *,
        parent_run_id: str,
        hypothesis_id: str,
        query: str,
        focus: str,
    ) -> tuple[str, str, str]:
        """Build the server-owned reference-research de-duplication key.

        The browser may submit a card/focus repeatedly (or with a different
        ``Idempotency-Key`` after a timeout).  De-duplication therefore uses
        canonical server context, not the request key.  Return the component
        hashes as well so they can be persisted/audited with the job payload.
        """

        query_payload = {"query": " ".join(str(query or "").split())[:4000]}
        query_snapshot_hash = hashlib.sha256(
            json.dumps(query_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        normalized_focus = " ".join(str(focus or "").split()).strip()[:1600]
        focus_hash = hashlib.sha256(normalized_focus.encode("utf-8")).hexdigest()
        fingerprint = hashlib.sha256(
            f"{parent_run_id}:{hypothesis_id}:{query_snapshot_hash}:{focus_hash}".encode("utf-8")
        ).hexdigest()
        return fingerprint, query_snapshot_hash, focus_hash

    def _deep_job_get(job_id: str) -> dict[str, Any] | None:
        """Read a deep job from the authoritative ledger.

        An API process can retain an in-memory compatibility row after a
        database outage.  Once a repository exposes ``get_deep_job`` that row
        must not be used as a successful read: doing so can resurrect a stale
        job (or expose a job deleted by another worker).  The in-memory map is
        reserved for pre-ledger adapters that do not implement the durable
        lookup at all.
        """

        repo = _deep_repository()
        getter = getattr(repo, "get_deep_job", None) if repo is not None else None
        if callable(getter):
            try:
                row = getter(str(job_id))
            except Exception:
                # Fail closed on a configured ledger.  Callers may surface a
                # bounded partial/503 state, but must not silently fall back
                # to a potentially stale process-local projection.
                return None
            return dict(row) if isinstance(row, Mapping) else None
        with deep_worker_lock:
            row = deep_memory_jobs.get(str(job_id))
            return dict(row) if row is not None else None

    def _deep_job_public(job: Mapping[str, Any] | None) -> dict[str, Any]:
        """Project a deep-job row onto the browser-safe public contract.

        ``deep_jobs.payload`` is an internal hand-off and may contain the
        canonical candidate, query text, idempotency material, or legacy
        provider fields.  Returning a repository row verbatim from polling
        endpoints would expose that internal envelope (and made an old
        hand-edited sidecar a data-leak path).  Keep only fields needed by the
        UI; the full query/evidence context is served through the session and
        version endpoints, which already apply their own redaction.
        """

        if not isinstance(job, Mapping):
            return {}
        payload = job.get("payload", {})
        payload = payload if isinstance(payload, Mapping) else {}
        candidate = job.get("candidate", payload.get("candidate", {}))
        candidate = candidate if isinstance(candidate, Mapping) else {}
        candidate_keys = (
            "hypothesis_id",
            "card_binding_id",
            "capability_id",
            "title",
            "name",
            "equipment_form",
            "equipment_category",
            "reference_overview",
            "mechanism_chain",
            "evidence_ids",
            "selection_status",
            "provenance_status",
            "s6_eligible",
            "score",
            "confidence",
            "mission_node",
            "related_scenario",
            "capability_gap",
        )
        candidate_public = {
            key: candidate.get(key)
            for key in candidate_keys
            if key in candidate
        }
        if isinstance(candidate_public.get("evidence_ids"), (list, tuple, set, frozenset)):
            candidate_public["evidence_ids"] = list(candidate_public["evidence_ids"])[:32]
        payload_public = {
            key: payload.get(key)
            for key in ("session_id", "hypothesis_id", "query_snapshot_hash", "focus_hash")
            if key in payload
        }
        if candidate_public:
            payload_public["candidate"] = candidate_public
        public_keys = (
            "job_id",
            "parent_run_id",
            "session_id",
            "child_run_id",
            "parent_job_id",
            "kind",
            "stage",
            "status",
            "error",
            "created_at",
            "updated_at",
            "hypothesis_id",
            "capability_name",
            "query_snapshot_hash",
            "focus_hash",
            "child_status",
            "child_updated_at",
            "merged",
            "merged_at",
            "merge_status",
            "retryable",
            "start_error",
            "relation",
        )
        result = {
            key: job.get(key)
            for key in public_keys
            if key in job
        }
        # The browser uses these normalized aliases when rendering reference
        # cards.  They are derived from canonical server data, never copied
        # from an arbitrary request body.
        result.setdefault(
            "hypothesis_id",
            str(candidate_public.get("hypothesis_id") or payload_public.get("hypothesis_id") or ""),
        )
        result.setdefault(
            "capability_name",
            str(candidate_public.get("title") or candidate_public.get("name") or candidate_public.get("equipment_form") or ""),
        )
        if payload_public:
            result["payload"] = payload_public
        if candidate_public:
            result["candidate"] = candidate_public
        # Partial/failed/blocked jobs remain explicitly retryable.  A
        # cancelled child can also be retried when the parent run is still
        # readable (the retry endpoint applies the same parent-scoped fence),
        # so keep the public hint aligned with that contract.
        status = str(result.get("status", "") or "").strip().lower()
        if "retryable" not in result:
            result["retryable"] = status in {"partial", "failed", "blocked", "cancelled"}
        # Preserve only a bounded, visible local artifact summary.  Do not
        # expose arbitrary sidecar/provider metadata through this field.
        local_result = job.get("local_result")
        if isinstance(local_result, Mapping):
            result["local_result"] = {
                key: local_result.get(key)
                for key in (
                    "capability_id",
                    "card_binding_id",
                    "hypothesis_id",
                    "name",
                    "title",
                    "verification_status",
                    "draft_status",
                    "merge_status",
                    "evidence_ids",
                    "source",
                    "source_session_id",
                )
                if key in local_result
            }
        return sanitize_runtime_payload(result, max_string_length=12000)

    def _deep_version_public(version: Mapping[str, Any] | None) -> dict[str, Any]:
        """Project a capability-version row onto the public API contract.

        ``capability_versions`` intentionally stores the complete immutable
        snapshot/diff used for audit.  Those JSON blobs may have been written
        by an older worker and can therefore contain provider metadata, raw
        sessions, credentials, or hidden-reasoning fields.  Never return the
        SQL row verbatim from list/verify endpoints; recursively redact and
        drop runtime-only keys while retaining the lineage and visible card
        content needed by the UI.
        """

        if not isinstance(version, Mapping):
            return {}

        blocked_keys = {
            "apikey",
            "authorization",
            "accesstoken",
            "refreshtoken",
            "password",
            "secret",
            "token",
            "cookie",
            "credential",
            "credentials",
            "privatekey",
            "rawsession",
            "rawsessions",
            "rawmessage",
            "rawmessages",
            "providerheaders",
            "providermetadata",
            "rawmetadata",
            "hiddenreasoning",
            "reasoningtrace",
            "chainofthought",
            "internalprompt",
            "providersession",
            "providerresponse",
            "requestmetadata",
            "runtimeoptions",
        }

        def safe(value: Any, *, depth: int = 0) -> Any:
            if depth > 12:
                return "<truncated>"
            if isinstance(value, Mapping):
                output: dict[str, Any] = {}
                for raw_key, raw_value in value.items():
                    key = str(raw_key)
                    normalized = "".join(ch for ch in key.casefold() if ch.isalnum())
                    if normalized in blocked_keys or any(
                        marker in normalized
                        for marker in (
                            "chainofthought",
                            "hiddenreasoning",
                            "providersession",
                            "providermetadata",
                            "rawmetadata",
                            "rawsession",
                            "credential",
                        )
                    ):
                        continue
                    output[key] = safe(raw_value, depth=depth + 1)
                return output
            if isinstance(value, (list, tuple, set, frozenset)):
                return [safe(item, depth=depth + 1) for item in list(value)[:128]]
            return sanitize_runtime_payload(value, max_string_length=12000)

        public_keys = (
            "version_id",
            "parent_run_id",
            "card_binding_id",
            "hypothesis_id",
            "version_no",
            "parent_version_id",
            "base_version_id",
            "base_snapshot_hash",
            "source",
            "evidence_refs",
            "snapshot",
            "diff",
            "status",
            "source_deleted",
            "source_status",
            "created_at",
            "updated_at",
        )
        result = {
            key: safe(version.get(key))
            for key in public_keys
            if key in version
        }
        # Keep the status aliases consumed by older clients, but derive them
        # from the durable status rather than trusting arbitrary snapshot
        # fields.
        status = str(version.get("status", "pending_verification") or "pending_verification").strip().lower().replace("-", "_")
        result["status"] = status
        result["version_status"] = status
        result["capability_version_status"] = status
        result["verification_status"] = (
            "formal" if status == "formal" else "verified" if status == "verified" else "pending"
        )
        return safe(result)

    def _deep_job_update(
        job_id: str,
        *,
        run_id: str,
        session_id: str = "",
        stage: str | None = None,
        status: str | None = None,
        progress: float | None = None,
        text: str = "",
        kind: str = "summary",
        error: str = "",
        evidence_refs: Sequence[str] = (),
        artifact_refs: Sequence[str] = (),
        version_refs: Sequence[str] = (),
        child_run_id: str = "",
    ) -> dict[str, Any] | None:
        """Advance a deep job and emit one public stage event atomically-ish.

        SQLite remains the source of truth when available.  The in-memory map
        is only a compatibility path for lightweight test/embed callers that
        construct a service without a repository.
        """

        normalized_stage = str(stage or "").strip().lower() or None
        normalized_status = str(status or "").strip().lower() or None
        repo = _deep_repository()
        updated: dict[str, Any] | None = None
        persistence_error = ""
        if repo is not None:
            try:
                try:
                    updated_raw = repo.update_deep_job(
                        str(job_id),
                        stage=normalized_stage,
                        status=normalized_status,
                        error=error if error else None,
                        child_run_id=child_run_id if child_run_id else None,
                        session_id=session_id if session_id else None,
                    )
                except TypeError:
                    # Compatibility with repositories from before the
                    # session-binding column was introduced.
                    updated_raw = repo.update_deep_job(
                        str(job_id),
                        stage=normalized_stage,
                        status=normalized_status,
                        error=error if error else None,
                        child_run_id=child_run_id if child_run_id else None,
                    )
                if updated_raw is not None:
                    updated = dict(updated_raw)
                else:
                    persistence_error = "deep job row was not found during update"
            except Exception as exc:
                # SQLite is the authoritative ledger whenever it is
                # configured.  Falling through as if the write succeeded
                # used to make a completed/failed event hide a lost job row.
                # Keep a bounded in-process recovery projection, but mark it
                # explicitly and downgrade successful transitions to
                # ``partial`` so callers can see that persistence needs
                # reconciliation after the database recovers.
                persistence_error = str(exc).strip()[:1000] or type(exc).__name__
        if updated is None:
            with deep_worker_lock:
                current = dict(deep_memory_jobs.get(str(job_id), {}))
                if normalized_stage:
                    current["stage"] = normalized_stage
                if normalized_status:
                    current["status"] = normalized_status
                if error:
                    current["error"] = str(error)[:4000]
                if persistence_error:
                    current["persistence_error"] = persistence_error
                    current["error"] = persistence_error
                    if normalized_status in {"completed", "running"}:
                        current["status"] = "partial"
                if child_run_id:
                    current["child_run_id"] = str(child_run_id)
                current["updated_at"] = now_iso()
                if current:
                    deep_memory_jobs[str(job_id)] = current
                    updated = dict(current)
        authoritative_status = str((updated or {}).get("status", "")).strip().lower()
        authoritative_stage = str((updated or {}).get("stage", "")).strip().lower()
        # The repository may reject a late transition after cancellation or
        # another terminal boundary.  Publish that durable status instead of
        # echoing the stale caller request (which would make SSE resurrect a
        # cancelled job in the UI).
        event_status = (
            authoritative_status
            if (
                authoritative_status == "cancelled"
                or (
                    authoritative_stage == "publish"
                    and authoritative_status in {"completed", "failed", "blocked"}
                )
            )
            and authoritative_status != normalized_status
            else normalized_status or authoritative_status or "running"
        )
        if persistence_error and event_status in {"completed", "running"}:
            event_status = "partial"
        # A stale worker may attempt to report an earlier stage after another
        # process has already crossed a terminal publish boundary.  Use the
        # durable stage in that case as well as the durable status; otherwise
        # SSE consumers can visually regress from ``publish/completed`` back
        # to ``validation/completed`` even though the ledger is monotonic.
        stage_was_rejected = bool(
            authoritative_status in {"completed", "failed", "blocked", "cancelled"}
            and normalized_stage
            and authoritative_stage
            and normalized_stage != authoritative_stage
        )
        event_stage = (
            authoritative_stage
            if stage_was_rejected
            else normalized_stage or authoritative_stage or "context"
        )
        details: dict[str, Any] = {
            "job_id": str(job_id),
            "session_id": str(session_id or ""),
            "stage": event_stage,
            "status": event_status,
            "progress": float(progress or 0),
            "kind": kind,
            "text": str(text or "")[:2000],
            "error": str(error or persistence_error or "")[:1000],
            "evidence_refs": list(evidence_refs or [])[:32],
            "artifact_refs": list(artifact_refs or [])[:32],
            "version_refs": list(version_refs or [])[:32],
            "child_run_id": str(child_run_id or (updated or {}).get("child_run_id", "")),
        }
        _publish_deep_event(run_id, "deep_stage", details)
        if persistence_error:
            _publish_deep_event(
                run_id,
                "deep_job_persistence_warning",
                {
                    "job_id": str(job_id),
                    "session_id": str(session_id or ""),
                    "stage": details["stage"],
                    "status": "partial",
                    "error": persistence_error,
                },
            )
        return updated

    def _deep_update_session(
        run_id: str,
        session_id: str,
        *,
        status: str | None = None,
        artifacts: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Keep sidecar and SQLite session projections in sync.

        The SQLite row is the durable authority.  The JSON transcript is only
        a user-visible compatibility projection for pre-ledger consumers, so
        a missing or read-only sidecar must never roll back (or downgrade) an
        otherwise successful SQL transition.  Internal ``_deep_*`` markers
        carry a best-effort projection warning and are intentionally stripped
        by :func:`_deep_session_public`; they never leave the API response.
        """

        # Prefer the SQL ledger as the authoritative state transition.  A
        # configured durable adapter that fails (or reports a missing row)
        # must not fall through to the JSON sidecar: doing so can resurrect a
        # deleted/cancelled session after a restart.  Sidecar writes are a
        # best-effort compatibility projection only after SQL succeeds.
        repo = _deep_repository()
        updater = getattr(repo, "update_deep_session", None) if repo is not None else None
        if callable(updater):
            try:
                durable = updater(session_id, status=status)
            except Exception as exc:
                # A configured durable ledger must fail closed.  Returning a
                # structured diagnostic (rather than ``None``) lets mutation
                # callers return a bounded ``partial`` result and makes an
                # explicit retry possible once SQLite recovers.
                return {
                    "session_id": str(session_id),
                    "run_id": str(run_id),
                    "status": "partial",
                    "_deep_update_ok": False,
                    "_deep_projection_ok": False,
                    "_deep_update_error": str(exc).strip()[:1000]
                    or type(exc).__name__,
                }
            if not isinstance(durable, Mapping):
                return {
                    "session_id": str(session_id),
                    "run_id": str(run_id),
                    "status": "partial",
                    "_deep_update_ok": False,
                    "_deep_projection_ok": False,
                    "_deep_update_error": "deep session row was not found during update",
                }
            result = dict(durable)
            durable_cancelled = str(result.get("status", "")).strip().lower() == "cancelled"
            requested_status = str(status or "").strip().lower()
            projection_error = ""
            transition_rejected = bool(
                durable_cancelled
                and requested_status
                and requested_status != "cancelled"
            )
            if not (durable_cancelled and requested_status and requested_status != "cancelled"):
                try:
                    projected = update_deep_session(
                        output_root,
                        run_id=run_id,
                        session_id=session_id,
                        status=status,
                        artifacts=artifacts,
                    )
                    if not isinstance(projected, Mapping):
                        projection_error = "deep session sidecar projection returned no row"
                except Exception as exc:
                    projection_error = str(exc).strip()[:1000] or type(exc).__name__

            result["_deep_update_ok"] = True
            result["_deep_projection_ok"] = not bool(projection_error)
            result["_deep_transition_rejected"] = transition_rejected
            if transition_rejected:
                result["_deep_update_error"] = (
                    "deep session transition fenced by cancellation"
                )
            if projection_error:
                # The SQL transition already committed.  Preserve the
                # requested durable status and expose only a private warning;
                # callers may log/retry the compatibility projection, but it
                # must not turn a completed deep job into ``partial``.
                result["_deep_projection_ok"] = False
                result["_deep_projection_warning"] = projection_error
            return result

        # Explicitly legacy adapters (no SQL update method) retain the old
        # sidecar-only behavior.  This branch is not used by SqlRunRepository.
        try:
            return update_deep_session(
                output_root,
                run_id=run_id,
                session_id=session_id,
                status=status,
                artifacts=artifacts,
            )
        except Exception as exc:
            return {
                "session_id": str(session_id),
                "run_id": str(run_id),
                "status": "partial",
                "_deep_update_ok": False,
                "_deep_projection_ok": False,
                "_deep_update_error": str(exc).strip()[:1000]
                or type(exc).__name__,
            }

    def _deep_session_update_error(update: Mapping[str, Any] | None) -> str:
        """Return only durable session-update failures.

        A modern SQL ledger can succeed while its optional JSON compatibility
        projection is unavailable.  Callers must not interpret that warning
        as a failed deep turn or merge.  Legacy sidecar-only adapters do not
        set ``_deep_update_ok`` and therefore retain their historical failure
        semantics.
        """

        if not isinstance(update, Mapping):
            return "deep session update returned no durable row"
        # Pre-ledger adapters return the sidecar projection directly and do
        # not carry the private SQL marker.  A normal sidecar row is a
        # successful compatibility update, even when its requested public
        # status happens to be ``partial`` or ``blocked``.
        if "_deep_update_ok" not in update:
            return ""
        if update.get("_deep_update_ok") is True:
            if bool(update.get("_deep_transition_rejected")):
                return str(update.get("_deep_update_error", "") or "").strip()[:1000]
            return ""
        return str(
            update.get("_deep_update_error")
            or update.get("_deep_projection_error")
            or "deep session update failed"
        ).strip()[:1000]

    def _deep_store_job(
        *,
        job_id: str,
        parent_run_id: str,
        session_id: str = "",
        kind: str = "deep_divergence_v1",
        idempotency_key: str = "",
        fingerprint: str = "",
        payload: Mapping[str, Any] | None = None,
        child_run_id: str = "",
        parent_job_id: str = "",
    ) -> dict[str, Any]:
        repo = _deep_repository()
        if repo is not None:
            row = repo.create_or_get_deep_job(
                job_id=str(job_id),
                parent_run_id=str(parent_run_id),
                session_id=str(session_id or ""),
                kind=str(kind),
                idempotency_key=str(idempotency_key or ""),
                fingerprint=str(fingerprint or ""),
                payload=dict(payload or {}),
                child_run_id=str(child_run_id or ""),
                parent_job_id=str(parent_job_id or ""),
            )
            return dict(row)
        now = now_iso()
        with deep_worker_lock:
            existing = next(
                (
                    dict(item)
                    for item in deep_memory_jobs.values()
                    if str(item.get("parent_run_id")) == str(parent_run_id)
                    and (
                        (idempotency_key and str(item.get("idempotency_key")) == str(idempotency_key))
                        or (fingerprint and str(item.get("fingerprint")) == str(fingerprint))
                    )
                ),
                None,
            )
            if existing is not None:
                return existing
            row = {
                "job_id": str(job_id),
                "parent_run_id": str(parent_run_id),
                "session_id": str(session_id or ""),
                "child_run_id": str(child_run_id or ""),
                "parent_job_id": str(parent_job_id or ""),
                "kind": str(kind),
                "stage": "queued",
                "status": "queued",
                "idempotency_key": str(idempotency_key or ""),
                "fingerprint": str(fingerprint or ""),
                "payload": dict(payload or {}),
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
            deep_memory_jobs[str(job_id)] = row
            return dict(row)

    def _deep_submit(job_id: str, target: Any, *, recover: bool = False) -> None:
        """Run a bounded deep job in a daemon thread with cancellation.

        A dispatcher is process-local, but the job row is shared by all API
        workers.  Claim the durable row inside the thread before invoking the
        target so duplicate startup recovery (or two API workers racing a
        request) can execute at most one copy.  Lightweight test services do
        not expose ``claim_deep_job`` and retain the historical in-memory
        behaviour.
        """

        cancel_event = Event()

        def runner() -> None:
            deep_worker_slots.acquire()
            try:
                repository = _deep_repository()
                claim = getattr(repository, "claim_deep_job", None)
                if callable(claim):
                    try:
                        stale_seconds = float(
                            os.environ.get("EQUIPMENT_DR_DEEP_JOB_STALE_SECONDS", "90")
                        )
                    except (TypeError, ValueError):
                        stale_seconds = 90.0
                    try:
                        claimed = claim(
                            str(job_id),
                            recover=bool(recover),
                            stale_after_seconds=stale_seconds,
                        )
                    except TypeError:
                        # Compatibility with a repository adapter that only
                        # implements the initial queued->running claim.
                        claimed = claim(str(job_id))
                    if claimed is None:
                        # A different API process owns the row, or the job is
                        # already terminal/cancelled.  Do not emit a failure
                        # event and, importantly, do not run the target.
                        return
                target(cancel_event)
            except _DeepJobCancelled:
                job = _deep_job_get(job_id) or {}
                _deep_job_update(
                    job_id,
                    run_id=str(job.get("parent_run_id", "")),
                    session_id=str(job.get("session_id", "")),
                    stage="publish",
                    status="cancelled",
                    progress=1.0,
                    text="深度研究任务已取消，已保留此前阶段摘要。",
                )
            except Exception as exc:  # pragma: no cover - defensive worker fence
                job = _deep_job_get(job_id) or {}
                run = str(job.get("parent_run_id", ""))
                sid = str(job.get("session_id", ""))
                message = str(exc)[:1000]
                _deep_job_update(
                    job_id,
                    run_id=run,
                    session_id=sid,
                    stage=str(job.get("stage", "validation")),
                    status="failed",
                    error=message,
                    progress=1.0,
                    text="深度研究任务失败，已保留可见阶段摘要。",
                )
                if run and sid:
                    _deep_update_session(run, sid, status="failed")
                if run:
                    _publish_deep_event(
                        run,
                        "deep_research_failed",
                        {
                            "job_id": job_id,
                            "session_id": sid,
                            "stage": "validation",
                            "status": "failed",
                            "error": message,
                        },
                    )
            finally:
                deep_worker_slots.release()
                with deep_worker_lock:
                    deep_worker_threads.pop(str(job_id), None)
                    deep_worker_cancel.pop(str(job_id), None)

        thread = Thread(target=runner, name=f"deep-job-{job_id}", daemon=True)
        with deep_worker_lock:
            prior = deep_worker_threads.get(str(job_id))
            if prior is not None and prior.is_alive():
                return
            deep_worker_threads[str(job_id)] = thread
            deep_worker_cancel[str(job_id)] = cancel_event
        thread.start()

    def _deep_cancel_signal(job_id: str) -> bool:
        with deep_worker_lock:
            event = deep_worker_cancel.get(str(job_id))
        if event is None:
            return False
        event.set()
        return True

    def _materialize_reference_artifact(
        *,
        job_id: str,
        run_id: str,
        session_id: str,
        child_run_id: str,
        candidate: Mapping[str, Any],
        query: str,
        focus: str,
        cancel_event: Event,
    ) -> dict[str, Any]:
        """Author and persist the provisional card inside the deep worker.

        The reference-research HTTP endpoint only commits identities and
        queues work.  Card construction and version writes belong here so a
        slow disk/database never turns a ``202 Accepted`` request into a
        synchronous research call or publishes half of a candidate before a
        durable job exists.
        """

        if cancel_event.is_set():
            raise _DeepJobCancelled()
        _deep_job_update(
            job_id,
            run_id=run_id,
            session_id=session_id,
            stage="s3_divergence",
            status="running",
            progress=0.22,
            text="已锁定 canonical 参考武器，开始多维 S3 发散。",
            child_run_id=child_run_id,
        )
        local_artifact = build_reference_capability(
            run_id=run_id,
            query=query,
            candidate=candidate,
            focus=focus,
            source_session_id=session_id,
        )
        local_artifact.update(
            {
                "is_deep_research": True,
                "merge_status": "available_for_parent",
                "verification_status": "pending",
                "confidence_limited": True,
                "child_run_id": child_run_id,
            }
        )
        if cancel_event.is_set():
            raise _DeepJobCancelled()
        _deep_job_update(
            job_id,
            run_id=run_id,
            session_id=session_id,
            stage="s3_divergence",
            status="completed",
            progress=0.34,
            text="参考武器多维 S3 发散完成。",
            child_run_id=child_run_id,
        )
        _deep_job_update(
            job_id,
            run_id=run_id,
            session_id=session_id,
            stage="s4_mapping",
            status="completed",
            progress=0.52,
            text="已映射能力缺口、任务节点和直接军事效果。",
            child_run_id=child_run_id,
        )
        _deep_job_update(
            job_id,
            run_id=run_id,
            session_id=session_id,
            stage="s6_authoring",
            status="partial",
            progress=0.60,
            kind="candidate",
            text="已形成待核验候选卡，等待子运行补充受治理证据。",
            artifact_refs=[str(local_artifact.get("capability_id", ""))],
            evidence_refs=list(local_artifact.get("evidence_ids", [])),
            child_run_id=child_run_id,
        )
        return local_artifact

    def _monitor_reference_child(
        *,
        job_id: str,
        run_id: str,
        session_id: str,
        child_run_id: str,
        local_artifact: Mapping[str, Any] | None = None,
        cancel_event: Event | None = None,
        submit: bool = True,
    ) -> None:
        """Reconcile a reference child run without mutating the parent card."""

        def cancellation_requested(event: Event) -> bool:
            if event.is_set():
                return True
            # Parent cancellation may be issued by a different API worker;
            # the local Event is then unavailable.  Consult the durable job
            # status at every stage boundary and poll iteration.
            try:
                current = _deep_job_get(job_id) or {}
                return str(current.get("status", "")).strip().lower() == "cancelled"
            except Exception:
                return False

        def execute(worker_cancel_event: Event) -> None:
            active_cancel_event = cancel_event or worker_cancel_event
            artifact = dict(local_artifact or {})
            # The initial request path materializes a provisional artifact
            # before handing control to the child-run monitor.  In that
            # normal path ``local_artifact`` is already populated, so the
            # recovery-only branch below is skipped.  Keep a canonical
            # candidate in scope for the later evidence gate regardless of
            # which path supplied the artifact; otherwise a completed child
            # would raise ``UnboundLocalError`` while constructing
            # ``review_candidate`` and be reported as a spurious failure.
            candidate: dict[str, Any] = {}
            try:
                job_row = _deep_job_get(job_id) or {}
                durable_payload = job_row.get("payload", {})
                if isinstance(durable_payload, Mapping) and isinstance(
                    durable_payload.get("candidate"), Mapping
                ):
                    candidate = dict(durable_payload["candidate"])
            except Exception:
                candidate = {}
            if artifact:
                # The artifact is server-authored from the canonical
                # candidate.  Merge only its stable/visible fields as a
                # fallback for legacy jobs whose payload predates the
                # candidate hand-off.
                candidate = {
                    **candidate,
                    **{
                        key: artifact.get(key)
                        for key in (
                            "hypothesis_id",
                            "card_binding_id",
                            "capability_id",
                            "name",
                            "title",
                            "equipment_form",
                            "mechanism_chain",
                            "reference_overview",
                            "evidence_ids",
                            "direct_military_effects",
                            "military_effects",
                            "validation_plan",
                        )
                        if artifact.get(key) is not None
                    },
                }
            # Build the provisional candidate only after the HTTP request has
            # returned.  The job payload is the server-owned handoff and is
            # intentionally the only source used to reconstruct this context
            # after a worker restart.
            if not artifact:
                job_row = _deep_job_get(job_id) or {}
                payload = job_row.get("payload", {})
                payload = payload if isinstance(payload, Mapping) else {}
                candidate = payload.get("candidate", {})
                candidate = dict(candidate) if isinstance(candidate, Mapping) else {}
                query = str(payload.get("query", "")).strip()
                if not query:
                    try:
                        query = _deep_query(service.get_run(run_id))
                    except Exception:
                        query = ""
                focus = str(payload.get("focus", "")).strip()
                artifact = _materialize_reference_artifact(
                    job_id=job_id,
                    run_id=run_id,
                    session_id=session_id,
                    child_run_id=child_run_id,
                    candidate=candidate,
                    query=query,
                    focus=focus,
                    cancel_event=active_cancel_event,
                )
            _deep_job_update(
                job_id,
                run_id=run_id,
                session_id=session_id,
                stage="retrieval",
                status="running",
                progress=0.62,
                text="等待受治理检索与子运行证据返回。",
                child_run_id=child_run_id,
            )
            try:
                max_polls = max(4, min(600, int(os.environ.get("EQUIPMENT_DR_DEEP_CHILD_MAX_POLLS", "240"))))
            except (TypeError, ValueError):
                max_polls = 240
            terminal = {"completed", "failed", "cancelled", "archived"}
            child_status = "queued"
            for poll_index in range(max_polls):
                if cancellation_requested(active_cancel_event):
                    raise _DeepJobCancelled()
                if poll_index % 4 == 0:
                    repository = _deep_repository()
                    touch = getattr(repository, "touch_deep_job", None) if repository is not None else None
                    if callable(touch):
                        try:
                            touch(job_id)
                        except Exception:
                            # A heartbeat failure is observable through the
                            # next stage update; do not discard child results
                            # solely because a transient write was busy.
                            pass
                try:
                    child = service.get_run(child_run_id)
                    child_status = str(getattr(child, "status", "queued") or "queued").lower()
                except Exception:
                    child_status = "unknown"
                if child_status in terminal:
                    break
                time.sleep(0.25)
            if cancellation_requested(active_cancel_event):
                raise _DeepJobCancelled()
            if child_status == "completed":
                # Child capabilities are read for the audit/result summary;
                # the parent card remains immutable and only a pending
                # version is appended below.
                child_results: list[Any] = []
                try:
                    child_results = get_capabilities(child_run_id, x_role="analyst")
                except Exception:
                    child_results = []
                child_evidence: list[str] = []
                for child_row in child_results if isinstance(child_results, list) else []:
                    if not isinstance(child_row, Mapping):
                        continue
                    values = child_row.get("evidence_ids", child_row.get("evidence_refs", []))
                    if not isinstance(values, (list, tuple, set)):
                        values = [values] if values else []
                    child_evidence.extend(str(value)[:180] for value in values if str(value).strip())
                artifact = {
                    **artifact,
                    "child_run_id": child_run_id,
                    "child_result_count": len(child_results),
                    "evidence_ids": list(dict.fromkeys([
                        *(
                            list(artifact.get("evidence_ids", []))
                            if isinstance(artifact.get("evidence_ids", []), list)
                            else []
                        ),
                        *child_evidence,
                    ]))[:32],
                    "verification_status": "pending",
                }
                # The child run may complete successfully while still
                # lacking an independently supported mechanism/effect.  Keep
                # that analysis visible as a blocked draft, but do not write a
                # capability_versions row (or expose it in the default
                # capability projection) until the evidence gate passes.
                review_context = {
                    "kind": "reference-research",
                    "session_id": session_id,
                    "hypothesis_id": artifact.get("hypothesis_id", ""),
                    "card_binding_id": artifact.get("card_binding_id", ""),
                }
                review_candidate = {**dict(candidate if isinstance(candidate, Mapping) else {}), **artifact}
                reviewable = _deep_candidate_reviewable(review_candidate, review_context)
                _deep_job_update(
                    job_id,
                    run_id=run_id,
                    session_id=session_id,
                    stage="validation",
                    status="running",
                    progress=0.86,
                    text=("子运行完成，正在校验候选与证据引用。" if reviewable else "子运行完成，但证据门未通过，保留为可见阻塞草稿。"),
                    child_run_id=child_run_id,
                )
                if not reviewable:
                    blocked_artifact = {
                        **artifact,
                        "verification_status": "blocked",
                        "draft_status": "blocked",
                        "candidate_reviewable": False,
                        "evidence_gate": "blocked",
                    }
                    try:
                        save_reference_research(
                            output_root,
                            run_id=run_id,
                            capability=blocked_artifact,
                            status="blocked",
                        )
                    except Exception:
                        pass
                    _deep_update_session(
                        run_id,
                        session_id,
                        status="blocked",
                        artifacts=[
                            {
                                **blocked_artifact,
                                "artifact_id": artifact.get("capability_id", ""),
                                "status": "blocked",
                            }
                        ],
                    )
                    _deep_job_update(
                        job_id,
                        run_id=run_id,
                        session_id=session_id,
                        stage="validation",
                        status="blocked",
                        progress=1.0,
                        text="参考武器研究完成，但未达到稳定身份、独立机理、直接军事效果和可审核证据门；仅保留可见分析草稿。",
                        child_run_id=child_run_id,
                    )
                    _publish_deep_event(
                        run_id,
                        "deep_research_blocked",
                        {
                            "job_id": job_id,
                            "session_id": session_id,
                            "child_run_id": child_run_id,
                            "stage": "validation",
                            "status": "blocked",
                            "artifact_refs": [str(artifact.get("capability_id", ""))],
                            "evidence_refs": list(artifact.get("evidence_ids", [])),
                        },
                    )
                    return
                persistence_error = ""
                version_record: dict[str, Any] | None = None
                sidecar_attempted = False
                try:
                    if cancellation_requested(active_cancel_event):
                        raise _DeepJobCancelled()

                    # The capability-version ledger is authoritative whenever
                    # a current durable repository is configured.  Commit it
                    # before touching the JSON capability projection so a
                    # successful sidecar write can never claim a completed
                    # deep-research result whose immutable version was lost.
                    # A repository that is explicitly missing the version API
                    # is treated as a pre-ledger adapter and may use the
                    # compatibility sidecar path below.
                    repo = _deep_repository()
                    save_version = (
                        getattr(repo, "save_capability_version", None)
                        if repo is not None
                        else None
                    )
                    durable_version_surface = bool(
                        repo is not None
                        and any(
                            callable(getattr(repo, name, None))
                            for name in (
                                "list_capability_versions",
                                "get_capability_version",
                                "ensure_capability_baseline",
                                "create_or_get_deep_job",
                            )
                        )
                    )
                    if durable_version_surface and not callable(save_version):
                        # A configured modern deep ledger without its version
                        # writer is unavailable.  Do not silently fall back
                        # to a sidecar-only success.
                        raise RuntimeError("deep capability version repository unavailable")
                    if callable(save_version):
                        job_payload = (_deep_job_get(job_id) or {}).get("payload", {})
                        job_payload = job_payload if isinstance(job_payload, Mapping) else {}
                        version_record = save_version(
                            version_id=_deep_version_id("reference", job_id, artifact),
                            parent_run_id=run_id,
                            card_binding_id=str(artifact.get("card_binding_id", "")),
                            hypothesis_id=str(artifact.get("hypothesis_id", "")),
                            snapshot=dict(artifact),
                            diff={
                                "source": "reference_weapon",
                                "focus": str(job_payload.get("focus", ""))[:1600],
                            },
                            base_snapshot_hash=hashlib.sha256(
                                str(job_payload.get("query", "")).encode("utf-8")
                            ).hexdigest(),
                            source="reference_weapon_deep_research",
                            evidence_refs=list(artifact.get("evidence_ids", [])),
                            status="pending_verification",
                        )
                        if isinstance(version_record, Mapping):
                            version_record = dict(version_record)

                    if isinstance(version_record, Mapping):
                        artifact = {
                            **artifact,
                            "version_id": str(version_record.get("version_id", "")),
                            "version_no": version_record.get("version_no", artifact.get("version_no", 1)),
                            "version_status": str(version_record.get("status", "pending_verification")),
                        }
                    elif persistence_error:
                        artifact = {
                            **artifact,
                            "version_status": "partial",
                            "draft_status": "partial",
                        }

                    # Only project after the authoritative version write has
                    # succeeded.  If this projection fails, the pending SQL
                    # version remains available for an explicit retry and the
                    # job is marked partial below.
                    save_reference_research(
                        output_root,
                        run_id=run_id,
                        capability=artifact,
                        status="partial" if persistence_error else "completed",
                    )
                    sidecar_attempted = True
                except _DeepJobCancelled:
                    raise
                except Exception as exc:
                    persistence_error = str(exc).strip()[:1000] or type(exc).__name__
                if isinstance(version_record, Mapping):
                    artifact = {
                        **artifact,
                        "version_id": str(version_record.get("version_id", "")),
                        "version_no": version_record.get("version_no", artifact.get("version_no", 1)),
                        "version_status": str(version_record.get("status", "pending_verification")),
                    }
                elif persistence_error:
                    artifact = {
                        **artifact,
                        "version_status": "partial",
                        "draft_status": "partial",
                    }
                if persistence_error and not sidecar_attempted:
                    try:
                        save_reference_research(
                            output_root,
                            run_id=run_id,
                            capability=artifact,
                            status="partial",
                        )
                        sidecar_attempted = True
                    except Exception as exc:
                        projection_error = str(exc).strip()[:1000] or type(exc).__name__
                        persistence_error = f"{persistence_error}; projection: {projection_error}"[:1000]
                session_update = _deep_update_session(
                    # Keep the SQL session projection in sync with the
                    # durable version before reporting publish completion.
                    # A successful version/sidecar write is not enough when
                    # this transition itself cannot be persisted; the job is
                    # then explicitly retryable below.
                    run_id,
                    session_id,
                    status="partial" if persistence_error else "active",
                    artifacts=[
                        {
                            **artifact,
                            "artifact_id": artifact.get("capability_id", ""),
                            "status": "draft" if persistence_error else "available_for_parent",
                            **(
                                {
                                    "version_id": version_record.get("version_id", ""),
                                    "version_no": version_record.get("version_no", 1),
                                    "version_status": version_record.get(
                                        "status", "pending_verification"
                                    ),
                                }
                                if isinstance(version_record, Mapping)
                                else {}
                            ),
                        }
                    ],
                )
                session_update_error = _deep_session_update_error(session_update)
                if session_update_error and not persistence_error:
                    # The capability version may already be durable, but the
                    # authoritative session transition itself failed.  Keep
                    # this task partial so an explicit retry can reconcile
                    # the SQL ledger instead of publishing success.
                    persistence_error = f"session projection: {session_update_error}"[:1000]
                if persistence_error:
                    _deep_job_update(
                        job_id,
                        run_id=run_id,
                        session_id=session_id,
                        stage="validation",
                        status="partial",
                        progress=1.0,
                        text="子运行已完成，但深研结果账本写入受限，已保留阶段草稿。",
                        error=persistence_error,
                        child_run_id=child_run_id,
                    )
                    return
                _deep_job_update(
                    job_id,
                    run_id=run_id,
                    session_id=session_id,
                    stage="publish",
                    status="completed",
                    progress=1.0,
                    text="参考武器深度研究完成，结果以待核验版本并入能力画像投影。",
                    artifact_refs=[str(artifact.get("capability_id", ""))],
                    evidence_refs=list(artifact.get("evidence_ids", [])),
                    child_run_id=child_run_id,
                )
                _publish_deep_event(
                    run_id,
                    "deep_research_completed",
                    {
                        "job_id": job_id,
                        "session_id": session_id,
                        "child_run_id": child_run_id,
                        "stage": "publish",
                        "status": "completed",
                        "result_count": 1,
                    },
                )
                save_research_link(
                    output_root,
                    {
                        "job_id": job_id,
                        "parent_run_id": run_id,
                        "child_run_id": child_run_id,
                        "session_id": session_id,
                        "hypothesis_id": str(artifact.get("hypothesis_id", "")),
                        "capability_name": str(artifact.get("name", "")),
                        "status": "completed",
                        "merge_status": "available_for_parent",
                        "merged": False,
                        "local_result": dict(artifact),
                        "updated_at": now_iso(),
                    },
                )
                return
            if child_status == "cancelled":
                raise _DeepJobCancelled()
            reason = "参考武器子运行失败" if child_status == "failed" else "参考武器子运行在限定时间内未完成"
            final_status = "failed" if child_status == "failed" else "partial"
            if artifact:
                # Keep a visible draft for failed/blocked runs, but do not
                # append a pending capability version until the evidence gate
                # has a completed child result.
                try:
                    save_reference_research(
                        output_root,
                        run_id=run_id,
                        capability={
                            **artifact,
                            "child_run_id": child_run_id,
                            "verification_status": "blocked" if final_status == "partial" else "failed",
                            "draft_status": final_status,
                        },
                        status=final_status,
                    )
                    _deep_update_session(
                        run_id,
                        session_id,
                        status=final_status,
                        artifacts=[
                            {
                                **artifact,
                                "artifact_id": artifact.get("capability_id", ""),
                                "status": final_status,
                            }
                        ],
                    )
                except Exception:
                    pass
            _deep_job_update(
                job_id,
                run_id=run_id,
                session_id=session_id,
                stage="validation",
                status=final_status,
                progress=1.0,
                text=f"{reason}，已保留本地候选和阶段摘要。",
                error=reason,
                child_run_id=child_run_id,
            )
            # A timeout is a durable partial outcome, not a live session.
            # Keep the visible draft and stage summary available for retry,
            # but never reopen the conversation as ``running`` after the
            # child has stopped responding.
            _deep_update_session(run_id, session_id, status=final_status)

        if submit:
            _deep_submit(job_id, execute)
        else:
            execute(cancel_event or Event())

    def _mark_deep_recovery_failure(
        job: Mapping[str, Any],
        *,
        message: str,
        status: str = "partial",
    ) -> None:
        """Persist a bounded recovery diagnostic without raising from startup."""

        job_id = str(job.get("job_id", ""))
        parent_id = str(job.get("parent_run_id", ""))
        session_id = str(job.get("session_id", ""))
        if not job_id or not parent_id:
            return
        try:
            _deep_job_update(
                job_id,
                run_id=parent_id,
                session_id=session_id,
                stage="validation",
                status=status,
                progress=1.0,
                text="深研任务在 API 重启恢复时缺少必要上下文，已保留阶段摘要。",
                error=str(message)[:1000],
            )
        except Exception:
            pass
        if session_id:
            try:
                _deep_update_session(parent_id, session_id, status=status)
            except Exception:
                pass
        try:
            _publish_deep_event(
                parent_id,
                "deep_recovery_partial",
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "stage": "validation",
                    "status": status,
                    "error": str(message)[:1000],
                },
            )
        except Exception:
            pass

    def _execute_deep_dialogue_job(
        job: Mapping[str, Any],
        cancel_event: Event,
        *,
        recovery: bool = False,
    ) -> None:
        """Execute one durable, single-equipment dialogue turn.

        Both ordinary deep-thinking messages and reference-weapon research
        use this adapter.  Keeping the finalization logic in one place is
        important: a restart/retry must not append a second version or emit a
        different terminal state merely because the original API worker
        disappeared.
        """

        row = dict(job)
        job_id = str(row.get("job_id", "") or "")
        parent_id = str(row.get("parent_run_id", "") or "")
        payload = row.get("payload", {})
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        session_id = str(row.get("session_id") or payload.get("session_id") or "")
        if not session_id:
            # The reservation/session update is intentionally two durable
            # writes.  If the process dies between them, recover the unique
            # session by the canonical hypothesis rather than creating a new
            # session or falling back to a client-supplied identity.
            candidate_payload = payload.get("candidate", {})
            candidate_payload = candidate_payload if isinstance(candidate_payload, Mapping) else {}
            hypothesis = str(
                candidate_payload.get("hypothesis_id")
                or payload.get("hypothesis_id")
                or ""
            ).strip()
            if hypothesis:
                try:
                    matching = [
                        item
                        for item in _deep_sessions_read(parent_id)
                        if str(item.get("hypothesis_id", "")).strip() == hypothesis
                    ]
                    if len(matching) == 1:
                        session_id = str(matching[0].get("session_id", ""))
                except Exception:
                    pass
        question = str(
            payload.get("question")
            or payload.get("content")
            or ""
        ).strip()[:DEEP_THINKING_MAX_MESSAGE_CHARS]
        focus = str(payload.get("focus", "") or "").strip()[:1600]
        if not job_id or not parent_id or not session_id or not question:
            _mark_deep_recovery_failure(
                row,
                message="durable deep-dialogue payload is incomplete",
                status="partial",
            )
            return
        try:
            parent = service.get_run(parent_id)
        except Exception as exc:
            _mark_deep_recovery_failure(row, message=f"parent run unavailable: {exc}")
            return
        session = _deep_session_read(parent_id, session_id)
        if session is None:
            _mark_deep_recovery_failure(row, message="deep-thinking session not found")
            return
        if cancel_event.is_set():
            raise _DeepJobCancelled()

        # The initial HTTP path writes the user message before queueing.  A
        # crash can occur in the tiny window before that write, so recover it
        # once by content rather than blindly appending a duplicate transcript
        # row.
        messages = session.get("messages", []) if isinstance(session, Mapping) else []
        has_user = any(
            isinstance(item, Mapping)
            and str(item.get("role", "")).strip().lower() == "user"
            and str(item.get("content", "")).strip() == question
            for item in messages
        ) if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)) else False
        if not has_user:
            user_message = _append_visible_deep_message(
                run_id=parent_id,
                session_id=session_id,
                role="user",
                content=question,
                status="completed",
            )
            _persist_deep_message(session_id, user_message)
            _publish_deep_event(
                parent_id,
                "deep_session_message",
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "role": "user",
                    "message_id": user_message.get("message_id", ""),
                },
            )

        result = _answer_deep_turn(
            parent_id,
            parent,
            session,
            question,
            focus,
            bool(payload.get("create_artifact", True)),
            job_id=job_id,
            append_user=False,
            cancel_event=cancel_event,
        )
        if cancel_event.is_set():
            raise _DeepJobCancelled()
        artifact = result.get("artifact") if isinstance(result, Mapping) else None
        result_status = str(
            result.get("job_status", "") if isinstance(result, Mapping) else ""
        ).strip().lower()
        workflow_status = str(
            result.get("deep_divergence_status", "")
            if isinstance(result, Mapping)
            else ""
        ).strip().lower().replace("-", "_")
        final_status = (
            result_status
            if result_status in {"partial", "failed", "blocked", "cancelled"}
            else workflow_status
            if workflow_status in {"partial", "failed", "blocked", "cancelled"}
            else "completed"
        )
        updated_job = _deep_job_update(
            job_id,
            run_id=parent_id,
            session_id=session_id,
            stage=(
                "validation"
                if final_status in {"partial", "failed", "blocked", "cancelled"}
                else "publish"
            ),
            status=final_status,
            progress=1.0,
            text=(
                "深度思考恢复部分完成，已保留可见分析和阶段草稿，可重试未完成步骤。"
                if final_status == "partial"
                else "深度思考恢复失败，已保留可见阶段摘要。"
                if final_status == "failed"
                else "深度思考恢复被证据门阻塞，已保留阶段摘要。"
                if final_status == "blocked"
                else "深度思考任务已取消，已保留此前阶段摘要。"
                if final_status == "cancelled"
                else "深度思考完成，结果以待核验版本保留。"
                if artifact
                else "深度思考完成，本轮仅返回可见分析。"
            ),
            error=str(result.get("job_error", "") or "")[:1000]
            if isinstance(result, Mapping)
            else "",
            artifact_refs=[str(artifact.get("capability_id", ""))]
            if isinstance(artifact, Mapping)
            else [],
            evidence_refs=list(artifact.get("evidence_ids", []))
            if isinstance(artifact, Mapping)
            and isinstance(artifact.get("evidence_ids", []), list)
            else [],
        )
        durable_status = str(
            updated_job.get("status", "") if isinstance(updated_job, Mapping) else ""
        ).strip().lower()
        if durable_status in {"partial", "failed", "blocked", "cancelled"}:
            final_status = durable_status
        event_type = (
            "deep_research_completed"
            if final_status == "completed"
            else "deep_research_blocked"
            if final_status == "blocked"
            else "deep_job_cancelled"
            if final_status == "cancelled"
            else "deep_research_failed"
        )
        _publish_deep_event(
            parent_id,
            event_type,
            {
                "job_id": job_id,
                "session_id": session_id,
                "stage": (
                    "validation"
                    if final_status in {"partial", "failed", "blocked", "cancelled"}
                    else "publish"
                ),
                "status": final_status,
                "result_count": 1 if artifact else 0,
                "error": str(result.get("job_error", "") or "")[:1000]
                if isinstance(result, Mapping)
                else "",
            },
        )

    def _resume_deep_dialogue_job(job: Mapping[str, Any], cancel_event: Event) -> None:
        """Recover a queued/partial single-equipment dialogue job."""

        _execute_deep_dialogue_job(job, cancel_event, recovery=True)

    def _resume_reference_job(job: Mapping[str, Any], cancel_event: Event) -> None:
        """Resume a reference-weapon job from its SQLite handoff.

        The original request thread may disappear between creating the job and
        linking its child run.  Reconstruct all inputs from the durable job
        payload/session and reuse an existing ``deep_run_links`` row when one
        is present.  No browser payload is consulted during recovery.
        """

        row = dict(job)
        payload_hint = row.get("payload", {})
        payload_hint = payload_hint if isinstance(payload_hint, Mapping) else {}
        if (
            str(payload_hint.get("dialogue_mode", "")).strip()
            == "single_equipment_contextual_divergence"
            and not str(row.get("child_run_id", "") or "").strip()
        ):
            _execute_deep_dialogue_job(row, cancel_event, recovery=True)
            return
        job_id = str(row.get("job_id", ""))
        parent_id = str(row.get("parent_run_id", ""))
        payload = row.get("payload", {})
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        session_id = str(row.get("session_id") or payload.get("session_id") or "")
        candidate = payload.get("candidate", {})
        candidate = dict(candidate) if isinstance(candidate, Mapping) else {}
        query = str(payload.get("query", "") or "").strip()
        focus = str(payload.get("focus", "") or "").strip()
        if not parent_id or not candidate:
            _mark_deep_recovery_failure(
                row,
                message="durable reference-research payload is incomplete",
                status="partial",
            )
            return
        try:
            parent = service.get_run(parent_id)
        except Exception as exc:
            _mark_deep_recovery_failure(row, message=f"parent run unavailable: {exc}")
            return
        if not query:
            query = _deep_query(parent)
        if not session_id:
            # A crash can occur after the job reservation but before the
            # session id is copied into the job row.  Resolve by the canonical
            # hypothesis, never by an arbitrary sidecar filename.
            hypothesis = str(candidate.get("hypothesis_id", ""))
            try:
                sessions = _deep_sessions_read(parent_id)
                matching = [
                    item for item in sessions
                    if hypothesis and str(item.get("hypothesis_id", "")) == hypothesis
                ]
                if len(matching) == 1:
                    session_id = str(matching[0].get("session_id", ""))
            except Exception:
                pass
        if not session_id:
            _mark_deep_recovery_failure(row, message="reference-research session binding is missing")
            return

        # Recover a child link written just before the original API process
        # exited.  This closes the crash window between create_run/start_run
        # and the deep_jobs.child_run_id update.
        child_run_id = str(row.get("child_run_id", "") or "")
        repo = _deep_repository()
        if not child_run_id and repo is not None:
            try:
                links = repo.list_deep_run_links(parent_id)
                linked = next(
                    (
                        item
                        for item in links
                        if str(item.get("job_id", "")) == job_id
                    ),
                    None,
                )
                if linked:
                    child_run_id = str(linked.get("child_run_id", "") or "")
                    if child_run_id:
                        _deep_job_update(
                            job_id,
                            run_id=parent_id,
                            session_id=session_id,
                            stage="queued",
                            status="running",
                            child_run_id=child_run_id,
                        )
            except Exception:
                pass

        if cancel_event.is_set():
            raise _DeepJobCancelled()
        if child_run_id:
            _monitor_reference_child(
                job_id=job_id,
                run_id=parent_id,
                session_id=session_id,
                child_run_id=child_run_id,
                local_artifact=None,
                cancel_event=cancel_event,
                submit=False,
            )
            return

        # No child exists yet.  Recreate the same server-owned child command
        # as the initial endpoint path.  The parent run's execution and scope
        # are copied; the browser cannot alter them during recovery.
        name = str(
            candidate.get("title")
            or candidate.get("name")
            or candidate.get("equipment_form")
            or "参考装备方向"
        ).strip()
        if not focus:
            focus = "针对该参考装备方向补齐当前 Query 的能力画像"
        execution = dict(getattr(parent, "execution", {}) or {})
        execution.update(
            {
                "parent_run_id": parent_id,
                "deep_job_id": job_id,
                "deep_research_kind": "reference_weapon",
                "parent_capability_id": str(candidate.get("capability_id", "")),
                "parent_hypothesis_id": str(candidate.get("hypothesis_id", "")),
                "reference_weapon": {
                    key: candidate.get(key)
                    for key in (
                        "title",
                        "name",
                        "equipment_form",
                        "reference_overview",
                        "mechanism_chain",
                        "evidence_ids",
                    )
                    if candidate.get(key) is not None
                },
                "merge_policy": "append_capability_cards",
                "deep_research_session_id": session_id,
            }
        )
        supplement = json.dumps(
            {
                "parent_run_id": parent_id,
                "hypothesis_id": candidate.get("hypothesis_id", ""),
                "candidate": candidate,
                "focus": focus,
            },
            ensure_ascii=False,
        )[:7800]
        command = CreateRunCommand(
            topic=f"{query}\n\n定向深度研究：{name}。{focus}"[:4000],
            research_route=str(getattr(parent, "research_route", "auto") or "auto"),
            selected_agent_ids=list(getattr(parent, "selected_agent_ids", []) or []),
            max_rounds=min(3, max(1, int(getattr(parent, "max_rounds", 2) or 2))),
            created_by="deep-thinking-agent",
            execution=execution,
            analyst_confirmed=True,
            interaction_mode=str(getattr(parent, "interaction_mode", "expert") or "expert"),
            discovery_branch=str(getattr(parent, "discovery_branch", "auto") or "auto"),
            execution_profile_id="deep_divergence_v1",
            report_template_mode=str(getattr(parent, "report_template_mode", "project_argument_v1") or "project_argument_v1"),
            supplemental_information=supplement,
            model_profile_id=str(getattr(parent, "model_profile_id", "") or ""),
            tenant_id=str(getattr(parent, "tenant_id", "") or ""),
            workspace_id=str(getattr(parent, "workspace_id", "") or ""),
            project_id=str(getattr(parent, "project_id", "") or ""),
            profile_id=str(getattr(parent, "profile_id", "") or ""),
            stage_scope=list(getattr(parent, "stage_scope", []) or []),
        )
        try:
            child = service.create_run(command)
            child_run_id = child.run_id
            try:
                child = service.start_run(
                    child_run_id,
                    actor="deep-thinking-agent",
                    idempotency_key=f"deep-recovery:{job_id}",
                )
            except Exception as exc:
                _mark_deep_recovery_failure(row, message=f"child run queue failed: {exc}", status="failed")
                return
        except Exception as exc:
            _mark_deep_recovery_failure(row, message=f"child run creation failed: {exc}", status="failed")
            return
        _deep_job_update(
            job_id,
            run_id=parent_id,
            session_id=session_id,
            stage="queued",
            status="running",
            progress=0.02,
            text="API 重启后已恢复参考武器子运行。",
            child_run_id=child_run_id,
        )
        if repo is not None:
            try:
                repo.save_deep_run_link(
                    parent_run_id=parent_id,
                    child_run_id=child_run_id,
                    job_id=job_id,
                )
            except Exception:
                # The child id remains in deep_jobs, so a later recovery can
                # still monitor it even if the auxiliary link write is busy.
                pass
        _publish_deep_event(
            parent_id,
            "deep_research_recovered",
            {
                "job_id": job_id,
                "session_id": session_id,
                "child_run_id": child_run_id,
                "stage": "context",
                "status": "running",
            },
        )
        artifact = _materialize_reference_artifact(
            job_id=job_id,
            run_id=parent_id,
            session_id=session_id,
            child_run_id=child_run_id,
            candidate=candidate,
            query=query,
            focus=focus,
            cancel_event=cancel_event,
        )
        _monitor_reference_child(
            job_id=job_id,
            run_id=parent_id,
            session_id=session_id,
            child_run_id=child_run_id,
            local_artifact=artifact,
            cancel_event=cancel_event,
            submit=False,
        )

    def _recover_deep_jobs() -> dict[str, Any]:
        """Reattach durable deep jobs after an API process restart.

        Recovery is deliberately one-shot per app instance.  A queued row is
        claimed by ``_deep_submit`` using a conditional SQLite update; stale
        running/partial rows are reclaimable, while a live worker's fresh row
        is left untouched.  Terminal jobs are never re-enqueued.
        """

        repo = _deep_repository()
        if repo is None:
            return {"status": "unavailable", "scheduled": 0, "skipped": 0}
        listing = getattr(repo, "list_recoverable_deep_jobs", None)
        if not callable(listing):
            return {"status": "unsupported", "scheduled": 0, "skipped": 0}
        try:
            rows = listing()
        except Exception as exc:
            return {"status": "partial", "scheduled": 0, "skipped": 0, "error": str(exc)[:500]}
        scheduled = 0
        skipped = 0
        for raw in rows if isinstance(rows, Sequence) else []:
            if not isinstance(raw, Mapping):
                continue
            job = dict(raw)
            job_id = str(job.get("job_id", ""))
            parent_id = str(job.get("parent_run_id", ""))
            if not job_id or not parent_id:
                skipped += 1
                continue
            # ``partial`` is also used for a completed-but-not-persisted
            # result.  Re-running a validation/publish-stage row would append
            # duplicate assistant messages or capability versions after a
            # restart.  Only reclaim partial work that was interrupted before
            # the terminal validation boundary; later rows remain visible for
            # an explicit analyst retry.
            if (
                str(job.get("status", "")).strip().lower() == "partial"
                and str(job.get("stage", "")).strip().lower()
                in {"validation", "publish"}
            ):
                skipped += 1
                continue
            payload = job.get("payload", {})
            payload = payload if isinstance(payload, Mapping) else {}
            job_kind = str(job.get("kind", "") or "").strip().lower().replace("_", "-")
            # New reference research is a normal single-equipment dialogue
            # job even though its payload contains a canonical candidate.  A
            # legacy row is identifiable by its child hand-off (or by the old
            # kind without the dialogue marker) and remains on the historical
            # monitor for backwards compatibility.
            is_reference = bool(job.get("child_run_id")) or (
                job_kind in {"reference-research", "reference-weapon"}
                and str(payload.get("dialogue_mode", ""))
                != "single_equipment_contextual_divergence"
            )
            is_dialogue = (
                str(payload.get("dialogue_mode", "")).strip()
                == "single_equipment_contextual_divergence"
                or job_kind == "deep-dialogue-v1"
            )
            session_id = str(job.get("session_id") or payload.get("session_id") or "")
            if is_reference:
                target = lambda event, item=job: _resume_reference_job(item, event)
            elif is_dialogue:
                target = lambda event, item=job: _resume_deep_dialogue_job(item, event)
            else:
                question = str(payload.get("question", "") or "").strip()
                if not question or not session_id:
                    _mark_deep_recovery_failure(job, message="deep-thinking question/session is missing")
                    skipped += 1
                    continue

                def target(event: Event, item=job, sid=session_id, prompt=question) -> None:
                    try:
                        parent = service.get_run(str(item.get("parent_run_id", "")))
                        session = _deep_session_read(str(item.get("parent_run_id", "")), sid)
                        if session is None:
                            _mark_deep_recovery_failure(item, message="deep-thinking session not found")
                            return
                        focus = str((item.get("payload", {}) or {}).get("focus", "") or "")
                        create_artifact = bool((item.get("payload", {}) or {}).get("create_artifact", True))
                        result = _answer_deep_turn(
                            str(item.get("parent_run_id", "")),
                            parent,
                            session,
                            prompt,
                            focus,
                            create_artifact,
                            job_id=str(item.get("job_id", "")),
                            append_user=False,
                            cancel_event=event,
                        )
                        if event.is_set():
                            raise _DeepJobCancelled()
                        artifact = result.get("artifact") if isinstance(result, Mapping) else None
                        result_status = str(
                            result.get("job_status", "") if isinstance(result, Mapping) else ""
                        ).strip().lower()
                        workflow_status = str(
                            (
                                result.get("deep_divergence_status", "")
                                if isinstance(result, Mapping)
                                else ""
                            )
                            or (
                                (result.get("answer", {}) or {}).get("deep_divergence_status", "")
                                if isinstance(result, Mapping)
                                and isinstance(result.get("answer", {}), Mapping)
                                else ""
                            )
                        ).strip().lower().replace("-", "_")
                        final_status = (
                            result_status
                            if result_status in {"partial", "failed", "blocked", "cancelled"}
                            else workflow_status
                            if workflow_status in {"partial", "failed", "blocked", "cancelled"}
                            else "completed"
                        )
                        updated_job = _deep_job_update(
                            str(item.get("job_id", "")),
                            run_id=str(item.get("parent_run_id", "")),
                            session_id=sid,
                            stage="validation" if final_status in {"partial", "failed", "blocked", "cancelled"} else "publish",
                            status=final_status,
                            progress=1.0,
                            text=(
                                "深度思考恢复部分完成，已保留可见分析和阶段草稿，可重试未完成步骤。"
                                if final_status == "partial"
                                else "深度思考恢复失败，已保留可见阶段摘要。"
                                if final_status == "failed"
                                else "深度思考恢复被证据门阻塞，已保留阶段摘要。"
                                if final_status == "blocked"
                                else "深度思考恢复完成，结果已保留。"
                                if artifact
                                else "深度思考恢复完成，本轮仅返回可见分析。"
                            ),
                            error=str(result.get("job_error", "") or "")[:1000]
                            if isinstance(result, Mapping)
                            else "",
                            artifact_refs=[str(artifact.get("capability_id", ""))] if isinstance(artifact, Mapping) else [],
                            evidence_refs=list(artifact.get("evidence_ids", [])) if isinstance(artifact, Mapping) and isinstance(artifact.get("evidence_ids", []), list) else [],
                        )
                        durable_status = str(
                            updated_job.get("status", "")
                            if isinstance(updated_job, Mapping)
                            else ""
                        ).strip().lower()
                        if durable_status in {"partial", "failed", "blocked", "cancelled"}:
                            final_status = durable_status
                        event_type = (
                            "deep_research_completed"
                            if final_status == "completed"
                            else "deep_research_blocked"
                            if final_status == "blocked"
                            else "deep_job_cancelled"
                            if final_status == "cancelled"
                            else "deep_research_failed"
                        )
                        _publish_deep_event(
                            str(item.get("parent_run_id", "")),
                            event_type,
                            {
                                "job_id": str(item.get("job_id", "")),
                                "session_id": sid,
                                "stage": "validation" if final_status in {"partial", "failed", "blocked", "cancelled"} else "publish",
                                "status": final_status,
                                "result_count": 1 if artifact else 0,
                                "error": str(result.get("job_error", "") or "")[:1000]
                                if isinstance(result, Mapping)
                                else "",
                            },
                        )
                    except _DeepJobCancelled:
                        raise
                    except Exception as exc:
                        _mark_deep_recovery_failure(item, message=str(exc), status="failed")
                        raise

            _deep_submit(job_id, target, recover=True)
            scheduled += 1
        return {"status": "ok", "scheduled": scheduled, "skipped": skipped}

    def _schedule_reference_retry(
        job: Mapping[str, Any],
        *,
        run_id: str,
        scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Reconcile a partial reference-research job without duplicating it.

        A child run can finish and its immutable ``capability_versions`` row
        can commit while the legacy JSON projection is temporarily
        unavailable.  Retrying the original POST used to return the same
        partial row forever because the fingerprint fence correctly refused
        to create a second child.  Explicit retry now requeues that row and
        either reprojects its durable version or resumes the existing child
        handoff when no version was committed yet.
        """

        repo = _deep_repository()
        job_id = str(job.get("job_id", "") or "").strip()
        if not job_id or repo is None:
            raise HTTPException(status_code=503, detail="deep job repository unavailable")
        requeue = getattr(repo, "requeue_deep_job", None)
        try:
            queued = (
                requeue(
                    job_id,
                    parent_run_id=run_id,
                    # Keep this set aligned with the public retry contract:
                    # cancelled jobs are recoverable as long as the parent
                    # run and its durable result remain readable.  The
                    # repository still applies its conditional status fence
                    # so terminal completed jobs cannot be resurrected.
                    allowed_statuses=("partial", "failed", "blocked", "cancelled"),
                )
                if callable(requeue)
                else None
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="deep job ledger unavailable") from exc
        if queued is None:
            # Another retry may have won the conditional transition.  Return
            # the current durable row rather than launching a duplicate.
            current = _deep_job_get(job_id)
            if isinstance(current, Mapping):
                return {"job": _deep_job_public(current), "scope": scope, "idempotent_replay": True}
            raise HTTPException(status_code=404, detail="deep job not found")

        row = dict(queued)

        def execute_retry(cancel_event: Event) -> None:
            sid = str(row.get("session_id", "") or row.get("payload", {}).get("session_id", "") or "")
            payload = row.get("payload", {})
            payload = dict(payload) if isinstance(payload, Mapping) else {}
            candidate_payload = payload.get("candidate", {})
            candidate_payload = dict(candidate_payload) if isinstance(candidate_payload, Mapping) else {}
            query = str(payload.get("query", "") or "").strip()
            focus = str(payload.get("focus", "") or "").strip()
            hypothesis = str(
                candidate_payload.get("hypothesis_id")
                or payload.get("hypothesis_id")
                or ""
            ).strip()
            try:
                if cancel_event.is_set():
                    raise _DeepJobCancelled()
                artifact: dict[str, Any] | None = None
                # Prefer the durable pending/verified version.  This is the
                # exact artifact that was committed before the projection
                # failed, so retrying cannot mint a second version number.
                list_versions = getattr(repo, "list_capability_versions", None)
                if callable(list_versions):
                    versions = list_versions(run_id)
                    matches = [
                        item
                        for item in (versions or [])
                        if isinstance(item, Mapping)
                        and str(item.get("hypothesis_id", "") or "").strip() == hypothesis
                        and str(item.get("status", "") or "").strip().lower()
                        in {"pending_verification", "verified"}
                        and isinstance(item.get("snapshot"), Mapping)
                    ]
                    if matches:
                        selected = max(
                            matches,
                            key=lambda item: int(item.get("version_no", 0) or 0),
                        )
                        artifact = dict(selected.get("snapshot", {}))
                        artifact.update(
                            {
                                "version_id": selected.get("version_id", ""),
                                "version_no": selected.get("version_no", 1),
                                "version_status": selected.get("status", "pending_verification"),
                                "is_deep_research": True,
                                "source_session_id": sid or artifact.get("source_session_id", ""),
                                "merge_status": "available_for_parent",
                                "verification_status": "pending",
                            }
                        )
                if artifact is None:
                    # New reference research is a single-equipment dialogue
                    # job.  Resume that same turn (and its stable job id)
                    # rather than creating a child S1--S6 run.  Legacy rows
                    # that already carry a child id retain the historical
                    # monitor for backwards compatibility.
                    row_payload = row.get("payload", {})
                    row_payload = row_payload if isinstance(row_payload, Mapping) else {}
                    dialogue_mode = str(row_payload.get("dialogue_mode", "")).strip()
                    if dialogue_mode == "single_equipment_contextual_divergence" or not str(row.get("child_run_id", "") or "").strip():
                        _execute_deep_dialogue_job(row, cancel_event, recovery=True)
                    else:
                        _resume_reference_job(row, cancel_event)
                    return

                _deep_job_update(
                    job_id,
                    run_id=run_id,
                    session_id=sid,
                    stage="publish",
                    status="running",
                    progress=0.84,
                    text="正在重试深研结果投影。",
                )
                save_reference_research(
                    output_root,
                    run_id=run_id,
                    capability=artifact,
                )
                session_update = _deep_update_session(
                    run_id,
                    sid,
                    status="active",
                    artifacts=[
                        {
                            **artifact,
                            "artifact_id": artifact.get("capability_id", ""),
                            "status": "available_for_parent",
                        }
                    ],
                ) if sid else None
                session_error = (
                    _deep_session_update_error(session_update) if sid else ""
                )
                if session_error:
                    _deep_job_update(
                        job_id,
                        run_id=run_id,
                        session_id=sid,
                        stage="validation",
                        status="partial",
                        progress=1.0,
                        text="重试已写入能力版本，但会话账本更新仍受限。",
                        error=session_error,
                    )
                    return
                _deep_job_update(
                    job_id,
                    run_id=run_id,
                    session_id=sid,
                    stage="publish",
                    status="completed",
                    progress=1.0,
                    text="深研结果投影重试完成，已恢复为待核验版本。",
                    artifact_refs=[str(artifact.get("capability_id", ""))],
                    evidence_refs=list(artifact.get("evidence_ids", []))
                    if isinstance(artifact.get("evidence_ids", []), list)
                    else [],
                )
                _publish_deep_event(
                    run_id,
                    "deep_research_completed",
                    {
                        "job_id": job_id,
                        "session_id": sid,
                        "stage": "publish",
                        "status": "completed",
                        "result_count": 1,
                        "retry": True,
                    },
                )
            except _DeepJobCancelled:
                raise
            except Exception as exc:
                _deep_job_update(
                    job_id,
                    run_id=run_id,
                    session_id=sid,
                    stage="validation",
                    status="partial",
                    progress=1.0,
                    text="深研结果投影重试失败，已保留可见草稿。",
                    error=str(exc).strip()[:1000] or type(exc).__name__,
                )

        _deep_submit(job_id, execute_retry)
        latest = _deep_job_get(job_id) or row
        return {"job": _deep_job_public(latest), "scope": scope, "retry_scheduled": True}

    def _deep_idempotency(key: str, *, operation: str, payload: Mapping[str, Any] | None = None) -> str:
        value = str(key or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        raw = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True, default=str)
        return f"{operation}:{value}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"

    def _claim_deep_idempotency(*, run_id: str, operation: str, key: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if not str(key or "").strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        repo = _deep_repository()
        if repo is None:
            return None
        # A legacy adapter may expose the deep-session API but predate the
        # durable idempotency ledger.  Keep that explicitly supported
        # compatibility path; once the method exists, every database error
        # must fail closed instead of silently allowing duplicate mutations.
        claimer = getattr(repo, "claim_deep_idempotency", None)
        if not callable(claimer):
            return None
        raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
        try:
            return claimer(scope_key=str(run_id), operation=operation, idempotency_key=str(key), request_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="deep idempotency ledger unavailable") from exc

    def _complete_deep_idempotency(*, run_id: str, operation: str, key: str, resource_id: str, response: Mapping[str, Any]) -> None:
        repo = _deep_repository()
        if repo is None:
            return
        # Keep the pre-ledger compatibility path only when the adapter does
        # not implement completion at all.  A configured durable method that
        # fails must be visible to the caller; swallowing it would acknowledge
        # a mutation whose replay fence was never persisted.
        completer = getattr(repo, "complete_deep_idempotency", None)
        if not callable(completer):
            return
        try: repo.complete_deep_idempotency(scope_key=str(run_id), operation=operation, idempotency_key=str(key), resource_id=resource_id, response=dict(response))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="deep idempotency ledger unavailable") from exc

    def _replay_or_raise_in_progress(claimed: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """Replay a completed idempotent request or fence an in-flight one.

        A database claim is written before the potentially expensive work.  A
        concurrent retry therefore sees a valid claim whose response is still
        empty; treating that as a fresh request would create duplicate
        sessions, child runs or capability versions.
        """
        if claimed is None:
            return None
        response = claimed.get("response") if isinstance(claimed, Mapping) else None
        if isinstance(response, Mapping) and response:
            return dict(response)
        raise HTTPException(status_code=409, detail="request with this Idempotency-Key is already in progress")

    def _deep_stream_id(run_id: str, session_id: str) -> str:
        return f"deep-session:{run_id}:{session_id}"

    def _persist_deep_session(
        session: Mapping[str, Any], *, view: object, scope: Mapping[str, Any]
    ) -> bool | None:
        """Persist a session in the durable ledger when one is configured.

        ``True`` means the SQL adapter accepted (or idempotently recovered)
        the row, ``None`` means the explicit pre-ledger path, and ``False``
        means a configured durable adapter failed.  A configured adapter that
        raises is not downgraded to a sidecar-only success; callers can
        surface a partial or 503 result instead.
        """

        repo = _deep_repository()
        if repo is None:
            return None
        creator = getattr(repo, "create_deep_session", None)
        if not callable(creator):
            return False
        context = (
            session.get("context_refs", {})
            if isinstance(session.get("context_refs"), Mapping)
            else {}
        )
        try:
            persisted = creator(
                session_id=str(session.get("session_id", "")),
                parent_run_id=str(session.get("run_id", "")),
                kind=str(session.get("kind", "deep-thinking")),
                title=str(session.get("title", "")),
                card_binding_id=str(session.get("card_binding_id", "")),
                hypothesis_id=str(session.get("hypothesis_id", "")),
                scope=dict(scope),
                query_snapshot={"query": _deep_query(view), "context": context},
                result_snapshot_hash=hashlib.sha256(
                    json.dumps(
                        context,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest(),
                created_by=str(session.get("created_by", "analyst")),
                idempotency_key=str(session.get("idempotency_key", "")),
            )
        except Exception:
            # Do not let a stale JSON session masquerade as a durable session.
            return False
        # A few legacy adapters return ``None`` after a successful INSERT.  If
        # they expose a durable read method, verify the row before reporting
        # success; this prevents a no-op test/dummy adapter from making the
        # caller acknowledge a sidecar-only session.
        getter = getattr(repo, "get_deep_session", None)
        if callable(getter):
            try:
                row = getter(str(session.get("session_id", "")))
            except Exception:
                return False
            if not isinstance(row, Mapping) or str(row.get("parent_run_id", "")) != str(session.get("run_id", "")):
                return False
        return True

    def _persist_deep_message(session_id: str, message: Mapping[str, Any]) -> None:
        if bool(message.get("_durable_persisted")):
            # ``_append_visible_deep_message`` already wrote the fallback
            # message to SQLite when the legacy sidecar was unavailable.
            # Avoid appending it a second time during restart recovery.
            return
        repo = _deep_repository()
        if repo is None:
            return
        try:
            repo.append_deep_message(
                session_id=session_id,
                role=str(message.get("role", "assistant")),
                content=str(message.get("content", "")),
                status=str(message.get("status", "completed")),
                artifact_refs=list(message.get("artifact_refs", [])) if isinstance(message.get("artifact_refs", []), list) else [],
                version_refs=list(message.get("version_refs", [])) if isinstance(message.get("version_refs", []), list) else [],
            )
        except Exception:
            pass

    def _append_visible_deep_message(
        *,
        run_id: str,
        session_id: str,
        role: str,
        content: str,
        status: str = "completed",
        artifact_refs: Sequence[str] = (),
        version_refs: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Append a visible message using SQL-first authority.

        For a durable adapter, a successful SQL append is the canonical write;
        the JSON sidecar is updated only as a best-effort compatibility
        projection.  SQL failures are propagated so a worker cannot report a
        visible turn that is absent from the authoritative transcript.  The
        sidecar-only branch is retained solely for pre-ledger adapters.
        """

        repo = _deep_repository()
        append = getattr(repo, "append_deep_message", None) if repo is not None else None
        if callable(append):
            # Write the authoritative transcript first.  Do not fall back to
            # a sidecar if this raises; doing so creates divergent histories.
            accepts_version_refs = True
            try:
                parameters = inspect.signature(append).parameters
                accepts_version_refs = (
                    "version_refs" in parameters
                    or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                )
            except (TypeError, ValueError):
                # Builtin/proxy callables may not expose a signature.  Passing
                # the current keyword keeps the modern contract; a genuine
                # operational TypeError must not be mistaken for an old
                # adapter mismatch.
                accepts_version_refs = True
            if accepts_version_refs:
                message = append(
                    session_id=session_id,
                    role=role,
                    content=content,
                    status=status,
                    artifact_refs=list(artifact_refs),
                    version_refs=list(version_refs),
                )
            else:
                # Adapters from the first ledger revision did not yet expose
                # ``version_refs``.  Preserve compatibility only for this
                # inspected signature mismatch.
                message = append(
                    session_id=session_id,
                    role=role,
                    content=content,
                    status=status,
                    artifact_refs=list(artifact_refs),
                )
            result = dict(message) if isinstance(message, Mapping) else {
                "session_id": session_id,
                "role": role,
                "content": content,
                "status": status,
                "artifact_refs": list(artifact_refs),
                "version_refs": list(version_refs),
            }
            result["_durable_persisted"] = True
            # Keep old JSON readers useful, but never make this projection a
            # prerequisite for a successful durable append (SQL-only restart
            # deployments intentionally have no sidecar directory).
            try:
                append_deep_message(
                    output_root,
                    run_id=run_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    artifact_refs=artifact_refs,
                    status=status,
                )
            except Exception:
                pass
            return result

        # Explicit pre-ledger compatibility path.  A repository object may be
        # present for run/events but lack the deep-message API; in that case
        # the sidecar remains the only supported transcript.
        message = append_deep_message(
            output_root,
            run_id=run_id,
            session_id=session_id,
            role=role,
            content=content,
            artifact_refs=artifact_refs,
            status=status,
        )
        result = dict(message)
        if version_refs:
            result["version_refs"] = list(version_refs)
        return result

    def _deep_session_read(
        run_id: str,
        session_id: str,
        *,
        strict: bool = False,
    ) -> dict[str, Any] | None:
        repo = _deep_repository()
        getter = getattr(repo, "get_deep_session", None) if repo is not None else None
        if not callable(getter):
            # Explicit pre-ledger compatibility path.  Once an adapter exposes
            # the durable lookup, a missing/error row must not be resurrected
            # from JSON.
            return get_deep_session(
                output_root, run_id=run_id, session_id=session_id
            )
        try:
            durable = getter(session_id)
        except Exception as exc:
            if strict:
                raise _DeepLedgerUnavailable(
                    "deep session ledger unavailable"
                ) from exc
            return None
        if not isinstance(durable, Mapping):
            return None
        if str(durable.get("parent_run_id")) != str(run_id):
            return None

        # SQLite is the authoritative session and transcript ledger.  If the
        # message query is temporarily unavailable, expose an empty transcript
        # rather than falling back to stale/provider-contaminated sidecar data.
        messages: list[dict[str, Any]] = []
        list_messages = getattr(repo, "list_deep_messages", None)
        if callable(list_messages):
            try:
                raw_messages = list_messages(session_id)
                if isinstance(raw_messages, Sequence) and not isinstance(
                    raw_messages, (str, bytes)
                ):
                    messages = [
                        dict(item) for item in raw_messages if isinstance(item, Mapping)
                    ]
            except Exception as exc:
                if strict:
                    raise _DeepLedgerUnavailable(
                        "deep message ledger unavailable"
                    ) from exc
                messages = []
        if durable is not None:
            stored_snapshot = durable.get("query_snapshot", {})
            if isinstance(stored_snapshot, Mapping) and isinstance(
                stored_snapshot.get("context"), Mapping
            ):
                # ``_persist_deep_session`` stores a small query envelope so
                # the hash is stable across deployments.  Expose the actual
                # context to the runner/UI; leaving the envelope wrapped made
                # restart recovery miss ``candidate`` and ``client_context``.
                context_refs = dict(stored_snapshot.get("context", {}))
                if stored_snapshot.get("query") and "query" not in context_refs:
                    context_refs["query"] = stored_snapshot.get("query")
            elif isinstance(stored_snapshot, Mapping):
                context_refs = dict(stored_snapshot)
            else:
                context_refs = {}
            context_candidate = context_refs.get("candidate", {})
            context_candidate = (
                context_candidate if isinstance(context_candidate, Mapping) else {}
            )
            result = {
                "schema_version": "deep-thinking-v1", "session_id": session_id, "run_id": run_id,
                "kind": durable.get("kind", "deep-thinking"), "title": durable.get("title", ""),
                "capability_id": context_candidate.get("capability_id", ""), "card_binding_id": durable.get("card_binding_id", ""),
                "capability_name": context_candidate.get("name") or context_candidate.get("title", ""), "hypothesis_id": durable.get("hypothesis_id", ""),
                "context_refs": context_refs, "messages": messages, "artifacts": [],
                "status": durable.get("status", "active"), "created_by": durable.get("created_by", "analyst"),
                "created_at": durable.get("created_at", ""), "updated_at": durable.get("updated_at", ""),
            }
            # Artifacts are materialized in capability_versions; include the
            # corresponding snapshots so a SQL-only deployment can resume a
            # session without depending on a sidecar file.
            if repo is not None:
                list_versions = getattr(repo, "list_capability_versions", None)
                version_method_available = callable(list_versions)
                try:
                    # Never query an empty binding as a wildcard for every
                    # card in the run.  Load the run's ledger once, then
                    # narrow it to this session's server-bound binding and
                    # hypothesis.  This prevents a global deep-thinking
                    # session from exposing another card's artifacts.
                    all_versions = list_versions(run_id) if callable(list_versions) else []
                    wanted_binding = str(durable.get("card_binding_id", "") or "").strip()
                    wanted_hypothesis = str(durable.get("hypothesis_id", "") or "").strip()
                    versions = (
                        [
                            item
                            for item in (all_versions if isinstance(all_versions, Sequence) else [])
                            if isinstance(item, Mapping)
                            and (not wanted_binding or str(item.get("card_binding_id", "") or "").strip() == wanted_binding)
                            and (not wanted_hypothesis or str(item.get("hypothesis_id", "") or "").strip() == wanted_hypothesis)
                        ]
                        if (wanted_binding or wanted_hypothesis)
                        else []
                    )
                    # Recover stable identity from the server-owned formal
                    # baseline as well as deep versions.  Formal v1 remains
                    # immutable and is never exposed as a deep artifact.
                    baseline_row = next(
                        (
                            item
                            for item in versions
                            if isinstance(item, Mapping)
                            and str(item.get("status", "")).strip().lower() == "formal"
                            and isinstance(item.get("snapshot"), Mapping)
                        ),
                        None,
                    )
                    if isinstance(baseline_row, Mapping):
                        baseline = baseline_row.get("snapshot", {})
                        # A formal v1 is an immutable identity anchor, not a
                        # deep artifact.  Restore its canonical identifiers
                        # into the session only when the durable session row
                        # predates those fields (older deployments often
                        # stored an empty candidate context).
                        identity_map = {
                            "capability_id": "capability_id",
                            "card_binding_id": "card_binding_id",
                            "hypothesis_id": "hypothesis_id",
                            "name": "capability_name",
                            "title": "capability_name",
                        }
                        for source_key, target_key in identity_map.items():
                            value = baseline.get(source_key) or baseline_row.get(source_key)
                            if not result.get(target_key) and value:
                                result[target_key] = value
                        canonical_candidate = {
                            key: baseline.get(key)
                            for key in (
                                "capability_id",
                                "card_binding_id",
                                "hypothesis_id",
                                "name",
                                "title",
                                "equipment_form",
                                "evidence_ids",
                            )
                            if baseline.get(key) not in (None, "", [], {})
                        }
                        if canonical_candidate:
                            context_refs["candidate"] = {
                                **dict(context_candidate),
                                **canonical_candidate,
                            }
                            result["context_refs"] = context_refs
                    result["artifacts"] = [
                        {**dict(item.get("snapshot", {})), "artifact_id": item.get("snapshot", {}).get("capability_id", ""), "version_id": item.get("version_id", ""), "version_status": item.get("status", "pending_verification")}
                        for item in versions
                        if isinstance(item.get("snapshot"), Mapping)
                        and str(item.get("status", "pending_verification") or "pending_verification").strip().lower() != "formal"
                    ]
                except Exception as exc:
                    # A configured version ledger is authoritative too.  Keep
                    # the session readable but omit artifacts until it recovers.
                    if strict:
                        raise _DeepLedgerUnavailable(
                            "deep capability version ledger unavailable"
                        ) from exc
                    result["artifacts"] = []
            return result
        return None

    def _deep_session_public(session: Mapping[str, Any] | None) -> dict[str, Any]:
        """Return the stable, redacted session contract exposed to clients.

        SQL rows contain storage bookkeeping (scope JSON, hashes and
        idempotency claims) and may have been written by an older worker that
        did not apply the sidecar sanitizer.  Never pass those rows through
        the API verbatim.  Keep only user-visible context/messages/artifacts,
        redact credential-like fields recursively, and include version refs so
        the UI can render the pending-verification lineage.
        """

        if not isinstance(session, Mapping):
            return {}
        allowed = {
            "schema_version",
            "session_id",
            "run_id",
            "kind",
            "title",
            "capability_id",
            "card_binding_id",
            "capability_name",
            "hypothesis_id",
            "context_refs",
            "messages",
            "artifacts",
            "status",
            "turn_count",
            "created_by",
            "created_at",
            "updated_at",
            "scope",
        }
        public = {
            key: sanitize_runtime_payload(session.get(key), max_string_length=2000)
            for key in allowed
            if key in session
        }
        messages = session.get("messages", [])
        if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
            visible_messages: list[dict[str, Any]] = []
            for item in list(messages)[-80:]:
                if not isinstance(item, Mapping):
                    continue
                visible_messages.append(
                    {
                        "message_id": str(item.get("message_id", ""))[:128],
                        "role": str(item.get("role", "user"))[:24],
                        "content": sanitize_runtime_payload(
                            str(item.get("content", ""))[:8000],
                            max_string_length=8000,
                        ),
                        "status": str(item.get("status", "completed"))[:32],
                        "created_at": str(item.get("created_at", ""))[:64],
                        "artifact_refs": sanitize_runtime_payload(
                            list(item.get("artifact_refs", []))[:16]
                            if isinstance(item.get("artifact_refs", []), (list, tuple, set))
                            else []
                        ),
                        "version_refs": sanitize_runtime_payload(
                            list(item.get("version_refs", []))[:16]
                            if isinstance(item.get("version_refs", []), (list, tuple, set))
                            else []
                        ),
                    }
                )
            public["messages"] = visible_messages
        artifacts = session.get("artifacts", [])
        if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)):
            public["artifacts"] = [
                sanitize_runtime_payload(dict(item), max_string_length=12000)
                for item in list(artifacts)[-24:]
                if isinstance(item, Mapping)
            ]
        return public

    def _deep_sessions_read(
        run_id: str,
        *,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        repo = _deep_repository()
        if repo is not None and callable(getattr(repo, "list_deep_sessions", None)):
            try:
                # Once a durable session repository is configured, a
                # successful (including empty) query is the complete view.
                # Mixing in JSON here can resurrect sessions deleted from
                # SQLite or expose stale context after a restart.
                rows = list(repo.list_deep_sessions(run_id))
            except Exception as exc:
                # Fail closed for a configured ledger.  The caller can still
                # show the parent run and a bounded storage diagnostic, but
                # must not silently fall back to an untrusted sidecar.
                if strict:
                    raise _DeepLedgerUnavailable(
                        "deep session ledger unavailable"
                    ) from exc
                return []
        else:
            # Only adapters from the pre-ledger deployment are allowed to use
            # the legacy JSON session projection.
            rows = list(list_deep_sessions(output_root, run_id=run_id))
        rows.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return rows

    def _deep_links_read(
        run_id: str,
        *,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """Read parent/child deep links with SQLite-first semantics."""

        repo = _deep_repository()
        listing = getattr(repo, "list_deep_run_links", None) if repo is not None else None
        if callable(listing):
            try:
                rows = listing(run_id)
            except Exception as exc:
                # A configured durable ledger is authoritative.  Returning an
                # empty projection is safer than resurrecting stale sidecar
                # links while the database is unavailable.
                if strict:
                    raise _DeepLedgerUnavailable(
                        "deep run-link ledger unavailable"
                    ) from exc
                return []
            return [dict(item) for item in rows if isinstance(item, Mapping)] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
        return [
            dict(item)
            for item in list_research_links(output_root, parent_run_id=run_id)
            if isinstance(item, Mapping)
        ]

    def _deep_context_for_run(run_id: str, view: object, body_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {
            "run_id": run_id,
            "query": _deep_query(view),
            "research_route": str(getattr(view, "research_route", "") or ""),
            "discovery_branch": str(getattr(view, "discovery_branch", "") or ""),
        }
        try:
            rows = get_capabilities(run_id, x_role="analyst")
        except Exception:
            rows = []
        if isinstance(rows, list):
            context["capability_ids"] = [str(row.get("capability_id", "")) for row in rows[:24] if isinstance(row, Mapping)]
            context["capability_names"] = [str(row.get("name", "")) for row in rows[:24] if isinstance(row, Mapping)]
        try:
            workflow = _interaction_workflow_summary(interaction_rows(run_id, view), view)
            swarm = workflow.get("swarm_cluster", {}) if isinstance(workflow, Mapping) else {}
            candidates = swarm.get("candidate_lineage", []) if isinstance(swarm, Mapping) else []
            context["candidate_count"] = len(candidates) if isinstance(candidates, list) else 0
        except Exception:
            pass
        if isinstance(body_context, Mapping):
            # Client context is advisory only and is bounded before storage;
            # server-derived query/run identifiers remain authoritative.
            context["client_context"] = dict(body_context)
        return context

    def _candidate_from_run(run_id: str, view: object, body: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve a client card to the canonical candidate-lineage row.

        Candidate objects are rendered by the browser and therefore cannot be
        treated as authoritative input.  Only a matching ``hypothesis_id`` or
        an unambiguous equipment identity from this run's server-side lineage
        is accepted.  Returning the canonical row also prevents callers from
        smuggling arbitrary evidence, scores, or provenance into a research
        artifact.
        """
        supplied: dict[str, Any] = {}
        for key in ("candidate", "reference_weapon"):
            value = body.get(key)
            if isinstance(value, Mapping):
                supplied.update(dict(value))
        current = body.get("context_refs")
        if isinstance(current, Mapping):
            nested = current.get("current_result_context")
            if isinstance(nested, Mapping):
                selected = nested.get("selected") or nested.get("candidate") or nested.get("reference_weapon")
                if isinstance(selected, Mapping):
                    supplied = {**dict(selected), **supplied}
        requested_hypothesis = str(
            body.get("hypothesis_id")
            or supplied.get("hypothesis_id")
            or supplied.get("candidate_id")
            or ""
        ).strip()
        requested_binding = str(
            body.get("card_binding_id")
            or supplied.get("card_binding_id")
            or supplied.get("capability_binding_id")
            or ""
        ).strip()
        requested_capability = str(
            body.get("capability_id")
            or supplied.get("capability_id")
            or supplied.get("card_id")
            or ""
        ).strip()
        supplied_name = str(
            supplied.get("title")
            or supplied.get("name")
            or supplied.get("primary_equipment_identity")
            or supplied.get("equipment_form")
            or ""
        ).strip()
        try:
            workflow = _interaction_workflow_summary(interaction_rows(run_id, view), view)
            swarm = workflow.get("swarm_cluster", {}) if isinstance(workflow, Mapping) else {}
            lineage = swarm.get("candidate_lineage", []) if isinstance(swarm, Mapping) else []
        except Exception:
            lineage = []
        rows = [dict(item) for item in lineage if isinstance(item, Mapping)] if isinstance(lineage, list) else []
        # Artifact-only/historical runs may not have a surviving interaction
        # trace.  Resolve against the server's immutable capability artifact
        # before considering any browser-supplied object.  This keeps the
        # canonical-candidate guarantee across both current and legacy runs.
        if not rows:
            try:
                canonical_cards = get_capabilities(run_id, x_role="analyst")
            except Exception:
                canonical_cards = []
            if isinstance(canonical_cards, list):
                rows = [
                    dict(item)
                    for item in canonical_cards
                    if isinstance(item, Mapping)
                    and not bool(item.get("is_deep_research"))
                    and str(
                        item.get("version_status")
                        or item.get("capability_version_status")
                        or "formal"
                    ).strip().lower().replace("-", "_")
                    not in {"rejected", "rolled_back", "pending_verification", "blocked", "partial"}
                ]
        if requested_hypothesis or requested_binding or requested_capability:
            matches = [
                item for item in rows
                if (
                    requested_hypothesis
                    and str(item.get("hypothesis_id", "")).strip() == requested_hypothesis
                )
                or (
                    requested_binding
                    and str(item.get("card_binding_id", "")).strip() == requested_binding
                )
                or (
                    requested_capability
                    and str(item.get("capability_id", "")).strip() == requested_capability
                )
            ]
            if len(matches) == 1:
                return matches[0]
            # An explicit identity must never fall back to client-supplied
            # fields when the run cannot prove ownership of that identity.
            if rows or not supplied_name:
                return {}
        if supplied_name:
            normalized = re.sub(r"\s+", " ", supplied_name).strip().casefold()

            def identity_values(item: Mapping[str, Any]) -> set[str]:
                values = {
                    str(item.get("title", "")),
                    str(item.get("name", "")),
                    str(item.get("primary_equipment_identity", "")),
                }
                forms = item.get("equipment_forms") or item.get("equipment_form")
                if isinstance(forms, (list, tuple, set)):
                    values.update(str(value) for value in forms)
                elif forms:
                    values.add(str(forms))
                return {
                    re.sub(r"\s+", " ", value).strip().casefold()
                    for value in values
                    if str(value).strip()
                }

            matches = [item for item in rows if normalized in identity_values(item)]
            if len(matches) == 1:
                return matches[0]
        # A client-only card is never a canonical reference candidate.  The
        # previous compatibility path accepted arbitrary names/evidence for
        # artifact-only runs, allowing a browser to mint a new hypothesis
        # without a server-owned lineage row.  Callers can still open a global
        # conversation and receive visible analysis; card authoring requires
        # an identity resolved above.
        return {}

    def _publish_deep_event(run_id: str, event_type: str, details: Mapping[str, Any]) -> None:
        # Independent, whitelisted event stream for conversation SSE.  Never
        # persist prompts, provider metadata or hidden reasoning fields.
        session_id = str(details.get("session_id", ""))
        job_id = str(details.get("job_id", ""))
        # Build one canonical projection for both the SQLite deep-event ledger
        # and the generic runtime event stream.  Keeping this in one helper is
        # important: a legacy worker can provide malformed stage/status,
        # NaN/Infinity progress, mapping-valued refs, or an event name with a
        # newline, and neither transport may echo those values unchecked.
        default_stage = "publish" if "merged" in str(event_type) else "context"
        default_status = "completed" if str(event_type).endswith("completed") else "running"
        public_details = {
            **dict(details),
            "event_type": event_type,
            "stage": details.get("stage") or default_stage,
            "status": details.get("status") or default_status,
        }
        # Runtime events do not have dedicated event_id/created_at columns.
        # Generate them before publishing so the payload remains a stable,
        # replayable public record even when the dedicated deep ledger is
        # temporarily unavailable.
        if not str(public_details.get("event_id", "") or "").strip():
            public_details["event_id"] = new_stable_id("deep-event")
        if not str(public_details.get("created_at", "") or "").strip():
            public_details["created_at"] = now_iso()
        public = _deep_public_event_payload(
            public_details,
            run_id=run_id,
            event_type=event_type,
        )
        stage = public["stage"]
        status = public["status"]
        delta = public["delta"]
        evidence_refs = public["evidence_refs"]
        artifact_refs = public["artifact_refs"]
        version_refs = public["version_refs"]
        repo = _deep_repository()
        if repo is not None:
            try:
                stream_id = _deep_stream_id(run_id, session_id) if session_id else f"deep-job:{run_id}:{job_id}" if job_id else f"deep-run:{run_id}"
                repo.append_deep_event(
                    stream_id=stream_id,
                    parent_run_id=run_id,
                    event_type=public["event_type"],
                    session_id=session_id,
                    job_id=job_id,
                    child_run_id=str(details.get("child_run_id", "")),
                    stage=stage,
                    status=status,
                    progress=public["progress"],
                    delta=delta,
                    evidence_refs=evidence_refs,
                    artifact_refs=artifact_refs,
                    version_refs=version_refs,
                    error=public["error"] or "",
                )
            except Exception:
                pass
        try:
            # Runtime events are also consumed by the generic run SSE/history
            # endpoints.  Apply the same public redaction contract here so a
            # future caller cannot accidentally bypass the deep-event
            # whitelist by attaching provider metadata to ``details``.
            # Keep the generic run event stream on the exact same public
            # contract as the dedicated deep SSE stream.  Passing ``details``
            # through wholesale would leak newly-added/internal keys (for
            # example merge receipts, provider session handles, or raw
            # metadata) to clients that subscribe to the legacy stream.
            runtime_public = {
                **public,
                # Runtime rows have their own outer event_type column.  Keep
                # the payload self-describing as well for /history consumers.
                "event_type": public["event_type"],
            }
            service.publish_runtime_event(
                run_id,
                public["event_type"],
                runtime_public,
            )
        except Exception:
            # Sidecar session files are authoritative; telemetry failure must
            # not make an already saved expert turn appear lost.
            pass

    @app.get("/api/v1/runs/{run_id}/deep-thinking/sessions")
    @app.get("/api/v1/runs/{run_id}/deep-sessions")
    def get_deep_sessions(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        scope = _assert_deep_scope(
            view,
            role=x_role,
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
            cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope),
        )
        try:
            sessions = _deep_sessions_read(run_id, strict=True)
            research = _deep_research_rows(run_id, strict=True)
            links = _deep_links_read(run_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep ledger unavailable",
            ) from exc
        return {
            "run_id": run_id,
            "items": [_deep_session_public(item) for item in sessions],
            "research": research,
            "links": links,
            "scope": scope,
        }

    @app.post("/api/v1/runs/{run_id}/deep-thinking/sessions", status_code=201)
    @app.post("/api/v1/runs/{run_id}/deep-sessions", status_code=201)
    def create_deep_thinking_session(
        run_id: str,
        body: DeepSessionCreateBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "admin"})
        view = read_view(run_id)
        scope = _assert_deep_scope(
            view,
            role=x_role,
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
            cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope),
            mutation=True,
        )
        idem = _deep_idempotency(idempotency_key, operation="session", payload=body.model_dump(mode="json"))
        claimed = _claim_deep_idempotency(run_id=run_id, operation="session", key=idempotency_key, payload=body.model_dump(mode="json"))
        replay = _replay_or_raise_in_progress(claimed)
        if replay is not None:
            return replay
        repo = _deep_repository()
        if repo is not None:
            try:
                existing = [item for item in repo.list_deep_sessions(run_id) if str(item.get("idempotency_key", "")) == idem]
                if existing:
                    response = {
                        "session": _deep_session_public(existing[0]),
                        "scope": scope,
                        "idempotent_replay": True,
                    }
                    # The request may have reached the durable session table
                    # before the idempotency response was committed (for
                    # example after a worker timeout).  Finish the claim now
                    # so subsequent retries replay the same response instead
                    # of being fenced forever as "in progress".
                    _complete_deep_idempotency(
                        run_id=run_id,
                        operation="session",
                        key=idempotency_key,
                        resource_id=str(existing[0].get("session_id", "")),
                        response=response,
                    )
                    return response
            except HTTPException:
                raise
            except Exception as exc:
                # A configured durable ledger is authoritative.  A listing
                # outage must not degrade into a sidecar-only duplicate.
                raise HTTPException(
                    status_code=503,
                    detail="deep session ledger unavailable",
                ) from exc
        candidate = _candidate_from_run(run_id, view, body.model_dump(mode="json"))
        context = _deep_context_for_run(run_id, view, body.context_refs)
        if candidate:
            context["candidate"] = candidate
        try:
            session = create_deep_session(
                output_root,
                run_id=run_id,
                kind=body.kind,
                title=body.title,
                capability_id=body.capability_id,
                capability_name=body.capability_name,
                card_binding_id=body.card_binding_id or str(candidate.get("card_binding_id", "")),
                hypothesis_id=body.hypothesis_id or str(candidate.get("hypothesis_id", "")),
                context_refs=context,
                created_by=x_role,
            )
            session = {**session, "idempotency_key": idem, "scope": scope}
            persisted = _persist_deep_session(session, view=view, scope=scope)
            if persisted is False:
                # Keep the sidecar draft for a possible operator retry, but do
                # not acknowledge a successful session creation when the
                # configured authoritative ledger rejected the write.
                try:
                    update_deep_session(
                        output_root,
                        run_id=run_id,
                        session_id=str(session.get("session_id", "")),
                        status="partial",
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=503,
                    detail="deep session ledger unavailable; session kept as partial draft",
                )
            _publish_deep_event(run_id, "deep_session_created", {"session_id": session["session_id"], "kind": session["kind"], "capability_id": session.get("capability_id", "")})
            response: dict[str, Any] = {"session": session, "scope": scope}
            if body.question.strip():
                # The initial prompt follows the same durable asynchronous
                # lifecycle as later messages.  The HTTP request returns once
                # the visible user message and queued job are committed.
                response.update(
                    _enqueue_deep_turn_job(
                        run_id=run_id,
                        view=view,
                        session=session,
                        content=body.question,
                        focus=body.focus,
                        create_artifact=True,
                        idempotency_key=idem,
                    )
                )
            _complete_deep_idempotency(run_id=run_id, operation="session", key=idempotency_key, resource_id=str(session.get("session_id", "")), response=response)
            return response
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _answer_deep_turn(
        run_id: str,
        view: object,
        session: Mapping[str, Any],
        content: str,
        focus: str = "",
        create_artifact: bool = True,
        *,
        job_id: str = "",
        append_user: bool = True,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        session_id = str(session.get("session_id", ""))
        context = session.get("context_refs", {}) if isinstance(session.get("context_refs"), Mapping) else {}
        def check_cancel() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise _DeepJobCancelled()
            current_job = _deep_job_get(job_id) if job_id else None
            if current_job is not None and str(current_job.get("status", "")).lower() == "cancelled":
                raise _DeepJobCancelled()

        check_cancel()
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "context", "status": "running", "progress": 0.05, "kind": "summary", "text": "已组装当前 Query、目标卡、可见证据和会话历史。"})
        user_message: dict[str, Any] = {}
        if append_user:
            user_message = _append_visible_deep_message(
                run_id=run_id,
                session_id=session_id,
                role="user",
                content=content,
                status="completed",
            )
            _persist_deep_message(session_id, user_message)
            _publish_deep_event(run_id, "deep_session_message", {"job_id": job_id, "session_id": session_id, "role": "user", "message_id": user_message.get("message_id", "")})
        check_cancel()
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "context", "status": "completed", "progress": 0.15, "kind": "summary", "text": "上下文快照已固定，进入多维发散。"})
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s3_divergence", "status": "running", "progress": 0.25, "kind": "summary", "text": "基于已有结果开展多维武器/装备发散，暂不重复检索。"})
        provider_status = "deterministic_fallback"
        provider_error = ""
        provider_workflow_status = "completed"

        def _provider_deep_answer() -> dict[str, Any] | None:
            """Run one provider-backed contextual turn when the parent is real.

            Deep-thinking previously always called ``synthesize_reply``. That
            deterministic helper remains a safe offline fallback, but a real
            parent run must not report a fabricated ``completed`` Agent turn
            when credentials/provider transport are unavailable.  Keep this
            adapter deliberately narrow: it asks the dedicated contextual
            dialogue entrypoint for bounded divergence material and exposes only a
            redacted visible summary; hidden/provider metadata never reaches
            the session ledger.
            """
            execution = getattr(view, "execution", {}) or {}
            if not isinstance(execution, Mapping):
                return None
            mode = str(execution.get("mode", "fake") or "fake").strip().lower()
            if mode != "real":
                return None
            provider_name = str(execution.get("provider", "") or "").strip()
            provider_model = str(execution.get("model", "") or "").strip()
            provider_base_url = str(execution.get("base_url", "") or "").strip()
            provider_api_key_env = str(execution.get("api_key_env", "") or "").strip()
            try:
                registry = ProviderRegistry.load(provider_path)
                provider = registry.create(
                    provider_name or None,
                    model=provider_model or None,
                    base_url=provider_base_url or None,
                    api_key_env=provider_api_key_env or None,
                    workspace_path=project_root,
                    isolation_key=f"deep-thinking-{run_id}:orchestrator",
                )
                # ProviderRegistry returns a wire-level ModelProvider.  Deep
                # thinking is a single-equipment conversation primitive, not
                # a child S1-S6/deep-divergence workflow.  Prefer the dedicated
                # contextual dialogue entrypoint so each user turn is one
                # governed model call over the canonical snapshot.
                advisor = getattr(provider, "deep_contextual_dialogue", None)
                if not callable(advisor):
                    definitions = {
                        agent_id: agent_registry.get(agent_id)
                        for agent_id in agent_registry.all_agent_ids()
                    }
                    host = ResponsesAgentProvider(
                        provider,
                        agent_definitions=definitions,
                        harness_profiles=agent_registry.harness_catalog.profiles,
                        provider_factory=lambda name, isolation_id: registry.create(
                            name,
                            workspace_path=project_root,
                            isolation_key=f"deep-thinking-{run_id}:{isolation_id}",
                        ),
                    )
                    advisor = host.deep_contextual_dialogue
                payload = {
                    "run_id": run_id,
                    "topic": _deep_query(view),
                    "question": str(content)[:DEEP_THINKING_MAX_MESSAGE_CHARS],
                    "focus": str(focus or "")[:1600],
                    # This is a dialogue contract, not the legacy
                    # deep-divergence execution profile.  The latter remains
                    # available only for historical child-run recovery.
                    "execution_profile_id": "deep_dialogue_v1",
                    "stage_scope": ["context", "divergence", "mapping", "authoring"],
                    "dialogue_mode": "single_equipment_contextual_divergence",
                    "workflow_dispatch": "none",
                    "deep_parent_context": sanitize_runtime_payload(
                        dict(context), max_string_length=8000
                    ),
                    "evidence_index": sanitize_runtime_payload(
                        context.get("evidence_index", [])
                        if isinstance(context, Mapping)
                        else [],
                        max_string_length=6000,
                    ),
                    "conversation_history": [
                        {
                            "role": str(item.get("role", ""))[:24],
                            "content": str(item.get("content", ""))[:4000],
                        }
                        for item in list(session.get("messages", []))[-12:]
                        if isinstance(item, Mapping)
                    ],
                }
                result = advisor(payload)
                if not isinstance(result, Mapping):
                    return None
                nonlocal provider_workflow_status
                raw_workflow_status = str(
                    result.get("deep_divergence_status", "completed")
                    or "completed"
                ).strip().lower().replace("-", "_")
                if raw_workflow_status not in {"completed", "partial", "blocked"}:
                    raw_workflow_status = "partial"
                provider_workflow_status = raw_workflow_status
                # Only project user-visible, decision-bearing fields.  Do not
                # persist the complete provider result or nested session data.
                directions = result.get("concept_directions", [])
                directions = directions if isinstance(directions, list) else []
                directions = [
                    {
                        "name": str(item.get("name", ""))[:240],
                        "hypothesis_id": str(item.get("hypothesis_id", ""))[:180],
                        "function": str(item.get("function", ""))[:500],
                        "equipment_form": str(item.get("equipment_form", ""))[:320],
                        "operational_mechanism": str(item.get("operational_mechanism", ""))[:600],
                        "military_value": str(item.get("military_value", ""))[:600],
                        "direct_military_effects": str(item.get("direct_military_effects", ""))[:600],
                        "related_scenario": str(item.get("related_scenario", ""))[:500],
                        "capability_gap": str(item.get("capability_gap", ""))[:500],
                        "failure_boundary": str(item.get("failure_boundary", ""))[:500],
                        "validation_plan": str(item.get("validation_plan", ""))[:500],
                        "stable": bool(item.get("stable", False)),
                        "direct_evidence_refs": [str(ref)[:180] for ref in item.get("direct_evidence_refs", [])[:8]],
                    }
                    for item in directions[:3]
                    if isinstance(item, Mapping) and str(item.get("name", "")).strip()
                ]
                dialogue_steps = result.get("divergence_steps", [])
                dialogue_steps = dialogue_steps if isinstance(dialogue_steps, list) else []
                dialogue_steps = [
                    {
                        "title": str(item.get("title", "深度推演"))[:160],
                        "text": str(item.get("text", ""))[:1200],
                        "stage": str(item.get("stage", "divergence"))[:32],
                    }
                    for item in dialogue_steps[:8]
                    if isinstance(item, Mapping) and str(item.get("text", "")).strip()
                ]
                visible_summary = result.get("visible_summary", [])
                visible_summary = visible_summary if isinstance(visible_summary, list) else []
                visible_summary = [str(item)[:1200] for item in visible_summary[:6] if str(item).strip()]
                visible = {
                    "sections": [
                        {
                            "title": "基于已有成果的可见推演",
                            "text": "；".join(visible_summary)[:2600]
                            or "已基于当前 Query 和该装备成果快照形成受限推演。",
                        },
                        {
                            "title": "发散过程",
                            "text": "\n".join(
                                f"{item['title']}：{item['text']}"
                                for item in dialogue_steps
                            )[:4200]
                            or "正在围绕单个装备形成可见发散方向。",
                        },
                        {
                            "title": "候选方向",
                            "text": "\n".join(
                                f"{item['name']}：{item['function'] or item['military_value']}"
                                for item in directions
                            )[:4200]
                            or "本轮未形成稳定候选能力卡。",
                        },
                        {
                            "title": "证据与边界",
                            "text": "；".join(
                                str(item)
                                for item in (
                                    result.get("evidence_gaps", []),
                                    result.get("open_questions", []),
                                )
                                if item
                            )[:2200]
                            or "证据边界沿用父任务快照，新增结论仍需验证。",
                        },
                    ],
                    "provider_backed": True,
                    "deep_divergence_status": provider_workflow_status,
                    "dialogue_mode": "single_equipment_contextual_divergence",
                    "workflow_dispatch": "none",
                    "divergence_steps": dialogue_steps,
                    "concept_directions": directions,
                }
                return visible
            except Exception as exc:
                # The caller converts this into a partial, auditable turn. Do
                # not expose provider names, URLs, credentials or raw errors.
                nonlocal provider_error
                provider_error = type(exc).__name__
                return None

        provider_answer = _provider_deep_answer()
        if provider_answer is not None:
            answer = provider_answer
            provider_status = "provider_backed"
        else:
            answer = synthesize_reply(
                query=_deep_query(view),
                question=content,
                context_refs=context,
                capability_name=str(session.get("capability_name", "")),
            )
            if str(getattr(view, "execution", {}).get("mode", "fake") or "fake").lower() == "real":
                provider_status = "provider_unavailable"
        check_cancel()
        workflow_stage_status = (
            provider_workflow_status
            if provider_workflow_status in {"partial", "blocked"}
            else "completed"
        )
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s3_divergence", "status": workflow_stage_status, "progress": 0.35, "kind": "summary", "text": "已形成可见发散方向，进入能力映射。" if workflow_stage_status == "completed" else "发散流程部分受限，保留可见阶段草稿。"})
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s4_mapping", "status": "running", "progress": 0.45, "kind": "summary", "text": "将发散方向映射到直接军事效果、任务节点和装备构型。"})
        visible_answer = "\n\n".join(f"### {item['title']}\n{item['text']}" for item in answer.get("sections", []) if isinstance(item, Mapping))
        # Surface the model's bounded, user-visible reasoning as incremental
        # deltas.  These are summaries only; hidden chain-of-thought and raw
        # provider output never enter the event stream or ledger.
        if provider_status == "provider_backed":
            for step in (answer.get("divergence_steps", []) if isinstance(answer, Mapping) else []):
                if not isinstance(step, Mapping) or not str(step.get("text", "")).strip():
                    continue
                stage = str(step.get("stage", "divergence")).strip().lower()
                stage = {"context": "context", "divergence": "s3_divergence", "mapping": "s4_mapping", "authoring": "s6_authoring"}.get(stage, "s3_divergence")
                _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": stage, "status": "running", "progress": 0.30, "delta": {"kind": "answer", "text": str(step.get("text", ""))[:1200]}})
        provider_directions = answer.get("concept_directions", []) if isinstance(answer, Mapping) else []
        provider_directions = [
            dict(item)
            for item in provider_directions
            if isinstance(item, Mapping) and str(item.get("name", "") or item.get("title", "")).strip()
        ][:3]
        artifact: dict[str, Any] | None = None
        refs: list[str] = []
        if provider_status == "provider_unavailable" or provider_workflow_status in {"partial", "blocked"}:
            # A real-mode deep turn that could not reach its configured
            # provider may still return the deterministic context summary for
            # the analyst, but it is not allowed to mint a completed
            # capability/version artifact.
            create_artifact = False
        if create_artifact:
            check_cancel()
            candidate = context.get("candidate", {}) if isinstance(context, Mapping) else {}
            if not isinstance(candidate, Mapping):
                candidate = {}
            candidate = dict(candidate)
            direction_stable = False
            session_kind = str(session.get("kind", "") or "").strip().lower().replace("_", "-")
            lineage_locked = session_kind in {
                "capability-followup",
                "capability",
                "follow-up",
                "reference-research",
                "reference-weapon",
            }
            # A formal-card follow-up and a reference-weapon session both
            # target one server-resolved equipment identity.  Capture that
            # identity before applying any model-proposed direction fields;
            # the model may enrich the mechanism/effects, but it cannot
            # relabel the equipment or move the turn to another hypothesis.
            locked_identity_keys = {
                "hypothesis_id",
                "card_binding_id",
                "capability_id",
                "name",
                "title",
                "primary_equipment_identity",
                "equipment_form",
                "equipment_forms",
            }
            locked_identity = {
                key: candidate.get(key)
                for key in locked_identity_keys
                if candidate.get(key) not in (None, "", [], {})
            }
            for key, value in {
                "hypothesis_id": session.get("hypothesis_id"),
                "card_binding_id": session.get("card_binding_id"),
                "capability_id": session.get("capability_id"),
                "name": session.get("capability_name"),
                "title": session.get("capability_name"),
            }.items():
                if key not in locked_identity and value not in (None, "", [], {}):
                    locked_identity[key] = value
            # A provider-backed deep turn may discover a genuinely new
            # direction.  Feed the first stable, visible direction into S6
            # authoring instead of rebuilding a card from the stale parent
            # candidate alone.  For formal-card follow-ups the session-bound
            # lineage remains authoritative; global/reference sessions may
            # adopt the provider's new hypothesis identity.
            if provider_directions:
                direction = provider_directions[0]
                direction_stable = bool(direction.get("stable", False))
                direction_map = {
                    "name": ("name", "title", "primary_equipment_identity", "equipment_form"),
                    "title": ("title", "name"),
                    "equipment_form": ("equipment_form", "equipment_forms", "primary_equipment_identity"),
                    "operational_mechanism": ("operational_mechanism", "depth_mechanism", "mechanism_chain", "winning_mechanism"),
                    "mechanism_chain": ("mechanism_chain", "operational_mechanism", "depth_mechanism", "winning_mechanism"),
                    "military_value": ("military_value", "direct_military_effects", "mission_effect"),
                    "direct_military_effects": ("direct_military_effects", "military_value", "mission_effect"),
                    "project_function": ("project_function", "function", "military_value"),
                    "related_scenario": ("related_scenario", "target_scenario", "scenario"),
                    "capability_gap": ("capability_gap", "failure_boundary", "evidence_gap"),
                    "validation_plan": ("validation_plan", "verification_plan"),
                    "evidence_ids": ("evidence_ids", "direct_evidence_refs", "evidence_refs"),
                    "hypothesis_id": ("hypothesis_id",),
                }
                for target, source_keys in direction_map.items():
                    if lineage_locked and target in locked_identity_keys:
                        continue
                    for source_key in source_keys:
                        value = direction.get(source_key)
                        if value not in (None, "", [], {}):
                            candidate[target] = value
                            break
                # A formal-card follow-up is explicitly bound to the original
                # card/hypothesis.  Global/reference sessions, however, may
                # discover a genuinely new direction; when the provider does
                # not supply a hypothesis id, derive one from the visible
                # direction rather than silently appending it to the parent
                # hypothesis.  The derived identity is deterministic across
                # retries and contains no provider metadata.
                if not lineage_locked:
                    supplied_hypothesis = str(
                        direction.get("hypothesis_id", "") or ""
                    ).strip()
                    if supplied_hypothesis:
                        candidate["hypothesis_id"] = supplied_hypothesis
                    else:
                        identity_seed = "\x1f".join(
                            str(direction.get(key, "") or "").strip()
                            for key in (
                                "name",
                                "title",
                                "equipment_form",
                                "primary_equipment_identity",
                                "operational_mechanism",
                                "mechanism_chain",
                                "military_value",
                            )
                            if str(direction.get(key, "") or "").strip()
                        )
                        identity_seed = identity_seed or json.dumps(
                            direction, ensure_ascii=False, sort_keys=True, default=str
                        )[:2000]
                        derived_hypothesis = (
                            "hypothesis-deep-"
                            + hashlib.sha256(
                                f"{run_id}\x1f{session_id}\x1f{identity_seed}".encode("utf-8")
                            ).hexdigest()[:24]
                        )
                        candidate["hypothesis_id"] = derived_hypothesis
                    # Do not carry the source card's binding into an
                    # independently hypothesized direction unless the model
                    # explicitly returned the same lineage.  The capability
                    # builder will derive a stable binding from this new id.
                    if str(candidate.get("hypothesis_id", "")) != str(
                        session.get("hypothesis_id", "") or ""
                    ):
                        candidate.pop("card_binding_id", None)
                # Evidence references are accepted only when they already
                # belong to the canonical parent/session context.  A model
                # citation is a lead, not an auditable source by itself.
                canonical_evidence = {
                    str(item).strip()
                    for item in (
                        candidate.get("evidence_ids", []),
                        candidate.get("evidence_refs", []),
                        context.get("evidence_ids", []) if isinstance(context, Mapping) else [],
                    )
                    if isinstance(item, (list, tuple, set, frozenset))
                    for item in item
                    if str(item).strip()
                }
                direction_refs = direction.get("direct_evidence_refs", direction.get("evidence_ids", []))
                if not isinstance(direction_refs, (list, tuple, set, frozenset)):
                    direction_refs = [direction_refs] if direction_refs else []
                candidate["evidence_ids"] = [
                    str(ref).strip() for ref in direction_refs
                    if str(ref).strip() in canonical_evidence
                ] or [
                    str(ref).strip() for ref in candidate.get("evidence_ids", [])
                    if str(ref).strip()
                ][:32]
            # A formal-card launcher may carry only the stable binding and
            # hypothesis.  Recover the server-owned baseline snapshot so the
            # evidence gate and version chain operate on canonical content,
            # never on a browser-authored replacement.
            repo_for_context = _deep_repository()
            if repo_for_context is not None and session.get("card_binding_id"):
                try:
                    versions = repo_for_context.list_capability_versions(
                        run_id, str(session.get("card_binding_id"))
                    )
                    baseline = next(
                        (
                            item.get("snapshot")
                            for item in versions
                            if isinstance(item, Mapping)
                            and item.get("status") == "formal"
                            and isinstance(item.get("snapshot"), Mapping)
                        ),
                        None,
                    )
                    if isinstance(baseline, Mapping):
                        candidate = {**dict(baseline), **candidate}
                except Exception:
                    pass
            # Older runs may not yet have a SQL baseline row.  Resolve the
            # canonical S6 projection once, then register it as immutable v1
            # before this turn appends the pending deep version.
            canonical_rows: list[Mapping[str, Any]] = []
            if session.get("card_binding_id") and not any(
                str(candidate.get(key, "")).strip()
                for key in ("mechanism_chain", "winning_mechanism", "source_winning_logic")
            ):
                try:
                    canonical_rows = get_capabilities(run_id, x_role="analyst")
                except Exception:
                    canonical_rows = []
            if isinstance(canonical_rows, list):
                wanted_binding = str(session.get("card_binding_id", "")).strip()
                wanted_hypothesis = str(session.get("hypothesis_id", "")).strip()
                matched = next(
                    (
                        row
                        for row in canonical_rows
                        if isinstance(row, Mapping)
                        and (
                            (wanted_binding and str(row.get("card_binding_id", "")).strip() == wanted_binding)
                            or (wanted_hypothesis and str(row.get("hypothesis_id", "")).strip() == wanted_hypothesis)
                            or (str(session.get("capability_id", "")).strip() and str(row.get("capability_id", "")).strip() == str(session.get("capability_id", "")).strip())
                        )
                    ),
                    None,
                )
                if isinstance(matched, Mapping):
                    candidate = {**dict(matched), **candidate}
            # Re-apply the server-owned identity after baseline enrichment as
            # well.  This second fence covers both model directions and the
            # legacy baseline merge above, so a reference session can never
            # drift to a different equipment/hypothesis during authoring.
            if lineage_locked:
                for key, value in locked_identity.items():
                    if value not in (None, "", [], {}):
                        candidate[key] = value
            candidate.setdefault("title", session.get("capability_name", ""))
            # A formal-card follow-up may intentionally omit a lineage
            # candidate from the browser payload.  Preserve the server-bound
            # card/hypothesis identity carried by the session so this turn
            # appends a new version to the same chain instead of inventing a
            # new card.
            if lineage_locked and session.get("hypothesis_id"):
                candidate["hypothesis_id"] = session.get("hypothesis_id")
            if lineage_locked and session.get("card_binding_id"):
                candidate["card_binding_id"] = session.get("card_binding_id")
            if session.get("capability_name"):
                candidate.setdefault("name", session.get("capability_name"))
            if provider_status == "provider_backed" and not direction_stable:
                # The dialogue may expose useful visible exploration without
                # freezing an unstable idea into the capability/version ledger.
                create_artifact = False
            elif not _deep_candidate_reviewable(candidate, session):
                # Keep the visible synthesis, but do not turn an exploratory
                # answer into a card until the identity/mechanism/effect and
                # auditable-input gates are all satisfied.
                create_artifact = False
            else:
                artifact = build_reference_capability(run_id=run_id, query=_deep_query(view), candidate=candidate, focus=focus or content, source_session_id=session_id)
            # Deep-thinking cards remain explicitly provisional until an
            # analyst chooses to promote/merge them.  Do not write the JSON
            # compatibility projection before the authoritative SQLite
            # version: a sidecar-only success is not a published result.
            if artifact is not None:
                refs = [str(artifact.get("capability_id", ""))]
                _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s4_mapping", "status": "completed", "progress": 0.60, "kind": "summary", "text": "已完成能力缺口与直接军事效果映射。"})
                _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s6_authoring", "status": "completed", "progress": 0.78, "kind": "candidate", "text": "已形成待核验能力卡候选。", "artifact_refs": [str(artifact.get("capability_id", ""))], "evidence_refs": list(artifact.get("evidence_ids", []))})
        else:
            _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "s4_mapping", "status": "completed", "progress": 0.60, "kind": "summary", "text": "已完成可见能力映射，本轮不生成候选卡。"})
        check_cancel()
        version_record: dict[str, Any] | None = None
        version_error = ""
        projection_error = ""
        if artifact:
            repo = _deep_repository()
            save_version = getattr(repo, "save_capability_version", None) if repo is not None else None
            durable_version_surface = bool(
                repo is not None
                and any(
                    callable(getattr(repo, name, None))
                    for name in (
                        "list_capability_versions",
                        "get_capability_version",
                        "ensure_capability_baseline",
                        "create_or_get_deep_job",
                    )
                )
            )
            if durable_version_surface and not callable(save_version):
                # Once a repository advertises the durable deep-session API,
                # a missing version writer is a broken modern ledger, not a
                # reason to claim a successful sidecar-only result.
                version_error = "deep capability version repository unavailable"
            elif callable(save_version):
                try:
                    # Only a follow-up explicitly launched from an existing
                    # formal S6 card may materialize the immutable v1 anchor.
                    # Global deep-thinking and reference-research sessions
                    # create genuinely new hypotheses and must start with a
                    # pending v1 row; manufacturing a ``formal`` baseline
                    # for them would make an unreviewed direction collectible.
                    session_kind = str(session.get("kind", "")).strip().lower().replace("_", "-")
                    formal_followup = session_kind in {
                        "capability-followup",
                        "capability",
                        "follow-up",
                    }
                    _ensure_deep_baseline(
                        repo,
                        run_id=run_id,
                        candidate=candidate,
                        card_binding_id=str(artifact.get("card_binding_id", "")),
                        hypothesis_id=str(artifact.get("hypothesis_id", "")),
                        allow_formal_baseline=formal_followup,
                    )
                    version_record = save_version(
                        version_id=_deep_version_id("deep", job_id, artifact),
                        parent_run_id=run_id,
                        card_binding_id=str(artifact.get("card_binding_id", "")),
                        hypothesis_id=str(artifact.get("hypothesis_id", "")),
                        snapshot=dict(artifact),
                        diff={"source": "deep-thinking", "focus": artifact.get("research_focus", "")},
                        base_snapshot_hash=hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(),
                        source="deep-thinking",
                        evidence_refs=list(artifact.get("evidence_ids", [])) if isinstance(artifact.get("evidence_ids", []), list) else [],
                        status="pending_verification",
                    )
                except Exception as exc:
                    version_error = str(exc).strip()[:1000] or type(exc).__name__

            if isinstance(version_record, Mapping):
                artifact = {
                    **artifact,
                    "version_id": str(version_record.get("version_id", "")),
                    "version_no": version_record.get("version_no", artifact.get("version_no", 1)),
                    "version_status": str(version_record.get("status", "pending_verification")),
                }
            elif version_error:
                artifact = {
                    **artifact,
                    "version_status": "partial",
                    "draft_status": "partial",
                }
            # The sidecar is a compatibility/report projection only.  It is
            # still useful as a visible draft when the SQL write failed, but
            # its status must make that partial state explicit.
            try:
                persisted_artifact = save_reference_research(
                    output_root,
                    run_id=run_id,
                    capability=artifact,
                    status="partial" if version_error else "completed",
                )
                if isinstance(persisted_artifact, Mapping):
                    artifact = {**artifact, **dict(persisted_artifact)}
            except Exception as exc:
                projection_error = str(exc).strip()[:1000] or type(exc).__name__

        persistence_error = version_error or projection_error
        if version_record is not None:
            refs = [str(artifact.get("capability_id", ""))] if artifact else []
        assistant_message = _append_visible_deep_message(
            run_id=run_id,
            session_id=session_id,
            role="assistant",
            content=visible_answer,
            artifact_refs=refs,
            version_refs=[str(version_record.get("version_id", ""))]
            if version_record is not None
            else (),
            status="completed",
        )
        _persist_deep_message(session_id, assistant_message)
        turn_status = (
            "blocked"
            if provider_workflow_status == "blocked"
            else "partial"
            if persistence_error
            or provider_status == "provider_unavailable"
            or provider_workflow_status == "partial"
            else "completed"
        )
        session_status = "blocked" if turn_status == "blocked" else "partial" if turn_status == "partial" else "active"
        session_update = _deep_update_session(
            run_id,
            session_id,
            status=session_status,
            artifacts=[artifact] if artifact else [],
        )
        updated = session_update if isinstance(session_update, Mapping) else None
        # A durable SQL transition is authoritative.  Compatibility sidecar
        # warnings are intentionally non-fatal; only a failed/missing SQL row
        # can downgrade this turn to a partial result.
        session_projection_error = _deep_session_update_error(session_update)
        if session_projection_error:
            if version_error:
                version_error = f"{version_error}; session ledger: {session_projection_error}"[:1000]
            else:
                version_error = f"session ledger: {session_projection_error}"[:1000]
            session_status = "partial"
            turn_status = "partial" if turn_status == "completed" else turn_status
        validation_status = "blocked" if turn_status == "blocked" else "partial" if turn_status == "partial" else "completed"
        _publish_deep_event(run_id, "deep_stage", {"job_id": job_id, "session_id": session_id, "stage": "validation", "status": validation_status, "progress": 0.92, "kind": "summary", "text": ("模型提供方不可用；已返回可见上下文分析，但未生成候选卡。" if provider_status == "provider_unavailable" else ("候选已形成，但版本账本写入受限，保留为部分结果。" if version_error else ("候选已通过结构完整性校验，状态保持 pending_verification。" if artifact else "本轮仅返回可见分析，尚未形成稳定候选卡。"))), "error": version_error or provider_error})
        if artifact:
            _publish_deep_event(run_id, "deep_thinking_candidate_created", {"job_id": job_id, "session_id": session_id, "capability_id": artifact.get("capability_id", ""), "hypothesis_id": artifact.get("hypothesis_id", ""), "provisional": True})
        _publish_deep_event(run_id, "deep_session_message", {"job_id": job_id, "session_id": session_id, "role": "assistant", "message_id": assistant_message.get("message_id", ""), "artifact_refs": refs})
        return {"session": updated, "user_message": user_message, "assistant_message": assistant_message, "answer": answer, "artifact": artifact, "job_status": turn_status, "job_error": version_error or projection_error or provider_error, "provider_status": provider_status, "deep_divergence_status": provider_workflow_status}

    def _enqueue_deep_turn_job(
        *,
        run_id: str,
        view: object,
        session: Mapping[str, Any],
        content: str,
        focus: str = "",
        create_artifact: bool = True,
        user_message: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
        fingerprint: str = "",
        job_id: str = "",
        job_kind: str = "deep-dialogue-v1",
        pre_reserved: bool = False,
    ) -> dict[str, Any]:
        """Persist and asynchronously execute one visible deep-thinking turn.

        ``job_id`` is accepted for the reference-research hand-off.  That
        endpoint reserves the canonical fingerprint before creating the
        session, then hands the very same durable row to this helper.  Keeping
        the reservation and execution on one row closes the race between two
        API workers without creating a child S1--S6 run.
        """

        session_id = str(session.get("session_id", ""))
        if not session_id:
            raise ValueError("deep-thinking session id is required")
        if user_message is None:
            user_message = _append_visible_deep_message(
                run_id=run_id,
                session_id=session_id,
                role="user",
                content=content,
                status="completed",
            )
            _persist_deep_message(session_id, user_message)
            _publish_deep_event(
                run_id,
                "deep_session_message",
                {
                    "session_id": session_id,
                    "role": "user",
                    "message_id": user_message.get("message_id", ""),
                },
            )
        supplied_job_id = str(job_id or "").strip()
        generated_job_id = supplied_job_id or new_stable_id("deep-thinking")
        if not fingerprint:
            fingerprint = hashlib.sha256(
                f"{run_id}:{session_id}:{content}:{focus}:{bool(create_artifact)}".encode("utf-8")
            ).hexdigest()
        row = _deep_store_job(
            job_id=generated_job_id,
            parent_run_id=run_id,
            session_id=session_id,
            kind=str(job_kind or "deep_dialogue_v1"),
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            payload={
                "session_id": session_id,
                "question": str(content)[:DEEP_THINKING_MAX_MESSAGE_CHARS],
                "focus": str(focus or "")[:1600],
                "create_artifact": bool(create_artifact),
                "dialogue_mode": "single_equipment_contextual_divergence",
            },
        )
        job_id = str(row.get("job_id") or generated_job_id)
        # When a caller supplies a reserved id, the row is intentionally
        # existing but still needs to be scheduled once.  A normal generated
        # id is scheduled only when the durable insert won the fingerprint
        # fence.  Terminal rows are never resurrected by a duplicate request.
        row_status = str(row.get("status", "queued") or "queued").strip().lower()
        is_new = (
            (not supplied_job_id and job_id == generated_job_id)
            or (pre_reserved and supplied_job_id and row_status == "queued")
        )
        if is_new:
            _deep_job_update(
                job_id,
                run_id=run_id,
                session_id=session_id,
                stage="queued",
                status="queued",
                progress=0.0,
                text="深度思考任务已排队，等待执行槽位。",
            )

            def execute(cancel_event: Event) -> None:
                current = _deep_job_get(job_id) or row
                if str(current.get("status", "")).lower() == "cancelled":
                    raise _DeepJobCancelled()
                _execute_deep_dialogue_job(
                    {
                        **dict(row),
                        "job_id": job_id,
                        "parent_run_id": run_id,
                        "session_id": session_id,
                        "payload": {
                            **(
                                dict(row.get("payload", {}))
                                if isinstance(row.get("payload", {}), Mapping)
                                else {}
                            ),
                            "session_id": session_id,
                            "question": content,
                            "focus": focus,
                            "create_artifact": bool(create_artifact),
                        },
                    },
                    cancel_event,
                )

            _deep_submit(job_id, execute)
        response_session = _deep_session_public(
            _deep_session_read(run_id, session_id) or dict(session)
        )
        return {
            "job": _deep_job_public(_deep_job_get(job_id) or row),
            "session": response_session,
            "user_message": dict(user_message),
        }

    def _deep_candidate_reviewable(
        candidate: Mapping[str, Any],
        session: Mapping[str, Any],
    ) -> bool:
        """Apply the visible evidence gate before authoring a candidate card.

        A generic deep-thinking answer is useful without becoming a capability
        card.  Card authoring is reserved for turns that carry a stable
        identity, an independent mechanism, a direct military effect, and at
        least one auditable input (evidence/validation or an existing formal
        binding).  This keeps speculative conversation visible while
        preventing accidental publication of a generic template card.
        """

        if not isinstance(candidate, Mapping):
            return False

        # Model/template fallbacks are useful for visible conversation, but
        # they are not auditable inputs.  Keep this list deliberately narrow:
        # a card containing one of these phrases must acquire an actual
        # source/ref or a concrete validation record before authoring.
        placeholder_markers = (
            "待核验",
            "待验证",
            "待补证",
            "待审核",
            "待确认",
            "当前 query",
            "当前query",
            "参考方向对应",
            "参考装备能力方向",
            "潜在制胜机理假设",
            "需要进一步确认",
            "独立证据核验",
            "通过改变任务链中的感知、决策、打击或保障连接",
        )

        def text_values(value: object) -> list[str]:
            if isinstance(value, Mapping):
                return [text for child in value.values() for text in text_values(child)]
            if isinstance(value, (list, tuple, set, frozenset)):
                return [text for child in value for text in text_values(child)]
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            return [text] if text else []

        def substantive(value: object, *, minimum: int = 6) -> bool:
            values = text_values(value)
            for text in values:
                compact = re.sub(r"[\s，。；：:、,.;!?！？()（）\[\]{}]", "", text)
                if len(compact) < minimum:
                    continue
                lowered = text.casefold()
                if any(marker.casefold() in lowered for marker in placeholder_markers):
                    continue
                return True
            return False

        # Stable identity must be server-bound.  A display name alone is not
        # enough because two reference cards may share a title.  Formal
        # follow-ups inherit their binding/hypothesis from the session.
        identity = any(
            substantive(candidate.get(key), minimum=3)
            for key in ("hypothesis_id", "card_binding_id", "capability_id")
        ) or any(
            substantive(session.get(key), minimum=3)
            for key in ("hypothesis_id", "card_binding_id", "capability_id")
        )
        if not identity:
            return False

        mechanism_fields = (
            "mechanism_chain",
            "winning_mechanism",
            "core_disruptive_difference",
            "independent_winning_mechanism",
            "source_winning_logic",
            "operational_mechanism",
            "depth_mechanism",
        )
        mechanism_markers = (
            "通过", "从而", "使", "导致", "压制", "破坏", "改变", "重构",
            "阻断", "欺骗", "诱导", "分散", "缩短", "扩大", "维持", "切断",
            "锁定", "复核", "续接", "扰乱", "夺取", "隔离", "穿透",
        )
        mechanism = any(
            substantive(candidate.get(key), minimum=8)
            # Explicit mechanism fields are already semantic evidence.  The
            # causal-marker check is advisory (rather than mandatory) so
            # concise expert labels such as ``独立机理：末段复核`` remain
            # reviewable while placeholder prose is still rejected above.
            and (
                any(
                    marker in text
                    for text in text_values(candidate.get(key))
                    for marker in mechanism_markers
                )
                or key in {"mechanism_chain", "winning_mechanism", "independent_winning_mechanism"}
            )
            for key in mechanism_fields
        )
        if not mechanism:
            return False

        # A scenario/mission node describes where the card is used, not what
        # direct military effect it produces.  Require an explicit effect
        # field so a generic scenario cannot create a candidate card.
        effect_fields = (
            "direct_military_effects",
            "military_effects",
            "capability_effects",
            "direct_effect",
            "military_value",
            "mission_effect",
            "strike_countermeasure_value",
            "target_and_direct_effect",
            "project_function",
        )
        effect_markers = (
            "摧毁", "毁伤", "压制", "阻断", "迟滞", "迫使", "缩短", "扩大",
            "夺取", "维持", "打乱", "干扰", "切断", "打开", "保障", "穿透",
            "击沉", "歼灭", "封锁", "削弱", "分散", "破坏", "杀伤",
        )
        direct_effect = any(
            substantive(candidate.get(key), minimum=6)
            # A value in an explicitly named direct-effect field is
            # reviewable even when it is a terse expert label.  Reject only
            # generic scenario prose by requiring either a concrete effect
            # marker or an explicitly effect-oriented field.
            and (
                any(
                    marker in text
                    for text in text_values(candidate.get(key))
                    for marker in effect_markers
                )
                or key in {
                    "direct_military_effects",
                    "military_effects",
                    "capability_effects",
                    "direct_effect",
                    "target_and_direct_effect",
                }
            )
            for key in effect_fields
        )
        if not direct_effect:
            return False

        # Evidence may be a list of canonical IDs, an evidence object, or a
        # concrete audit/validation input.  Generic failure-boundary prose is
        # not evidence by itself; it becomes acceptable only when accompanied
        # by an explicit test/source reference.
        evidence_fields = (
            "evidence_ids",
            "evidence_refs",
            "direct_evidence_refs",
            "source_evidence_refs",
            "evidence_cards",
            "evidence",
        )

        def real_evidence_ref(value: object) -> bool:
            """Recognize a canonical reference rather than arbitrary prose."""

            if isinstance(value, Mapping):
                for key in (
                    "evidence_id",
                    "evidence_ref",
                    "evidence_id_ref",
                    "source_id",
                    "source_ref",
                    "packet_id",
                    "id",
                    "ref",
                    "url",
                ):
                    if real_evidence_ref(value.get(key)):
                        return True
                return False
            if isinstance(value, (list, tuple, set, frozenset)):
                return any(real_evidence_ref(item) for item in value)
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if not text or len(text) > 500:
                return False
            lowered = text.casefold()
            if any(marker.casefold() in lowered for marker in placeholder_markers):
                return False
            if lowered in {
                "none",
                "null",
                "n/a",
                "na",
                "unknown",
                "tbd",
                "todo",
                "placeholder",
                "sample",
                "test",
                "invented",
                "invented-id",
            }:
                return False
            if re.match(r"^(?:https?://|doi:\s*10\.|urn:|arxiv:)", lowered):
                return True
            # Current ledgers use ev-*/evidence-*/packet-* identifiers. Keep
            # support for the short ``ev`` compatibility token as well.
            return bool(
                re.match(
                    r"^(?:e(?:v(?:idence)?)?|packet|source|src|ref(?:erence)?)[-_:.]?[a-z0-9][a-z0-9_.:@/+\-]*$",
                    lowered,
                )
            )

        evidence_present = any(real_evidence_ref(candidate.get(key)) for key in evidence_fields)
        audit_fields = (
            "validation_plan",
            "verification_plan",
            "verification",
            "audit_inputs",
            "auditability",
            "source_url",
            "source_urls",
            "evidence_basis",
        )
        auditable_input = any(
            substantive(candidate.get(key), minimum=12)
            and not any(
                marker.casefold() in text.casefold()
                for text in text_values(candidate.get(key))
                for marker in placeholder_markers
            )
            for key in audit_fields
        )

        # An existing formal binding is an auditable input only when the
        # session is explicitly a capability follow-up.  Reference research
        # must still carry evidence from the canonical candidate/child run.
        kind = str(session.get("kind", "")).strip().lower().replace("_", "-")
        formal_binding = bool(
            kind in {"capability-followup", "capability", "follow-up"}
            and substantive(session.get("card_binding_id"), minimum=3)
            and str(candidate.get("candidate_provenance", "")).strip()
            != "explicit_client_context"
        )
        return bool(evidence_present or auditable_input or formal_binding)

    def _ensure_deep_baseline(
        repo: object,
        *,
        run_id: str,
        candidate: Mapping[str, Any],
        card_binding_id: str,
        hypothesis_id: str,
        allow_formal_baseline: bool = False,
    ) -> None:
        """Register formal S6 v1 before appending a follow-up version."""

        ensure = getattr(repo, "ensure_capability_baseline", None)
        list_versions = getattr(repo, "list_capability_versions", None)
        # A new hypothesis (including every reference-weapon research task)
        # is intentionally independent of the formal card chain.  It must not
        # acquire a formal baseline merely because the artifact builder
        # derived a deterministic card binding.
        if (
            not allow_formal_baseline
            or not callable(ensure)
            or not callable(list_versions)
            or not card_binding_id
        ):
            return
        try:
            existing_rows = list_versions(run_id, card_binding_id)
            existing_rows = [
                row for row in (existing_rows or []) if isinstance(row, Mapping)
            ]
            exact_hypothesis = str(hypothesis_id or "").strip()
            exact_rows = [
                row
                for row in existing_rows
                if str(row.get("hypothesis_id", "") or "").strip()
                == exact_hypothesis
            ]
            # An existing exact-lineage row is authoritative.  In
            # particular, do not create a formal v1 for a new hypothesis
            # that happens to reuse a card binding owned by another chain.
            if exact_rows:
                return
            if existing_rows:
                return
            # Legacy runs may have no SQL baseline yet.  The candidate used
            # for a capability follow-up must still look like a server-owned
            # formal S6 card; reject deep/reference/provisional snapshots so
            # a malformed caller cannot promote them to v1 by omission.
            source = str(
                candidate.get("source")
                or candidate.get("analysis_provenance_status")
                or candidate.get("provenance_status")
                or ""
            ).strip().lower()
            version_status = str(
                candidate.get("version_status")
                or candidate.get("capability_version_status")
                or candidate.get("verification_status")
                or ""
            ).strip().lower().replace("-", "_")
            if (
                bool(candidate.get("is_deep_research"))
                or source in {
                    "deep-thinking",
                    "reference_weapon_deep_research",
                    "reference_weapon",
                    "deep_research_reference",
                }
                or version_status in {
                    "pending",
                    "pending_verification",
                    "rejected",
                    "rolled_back",
                    "blocked",
                    "partial",
                }
            ):
                raise RuntimeError("formal capability baseline unavailable")
            baseline = dict(candidate)
            # Keep the baseline visibly formal and immutable while retaining
            # the exact server-bound card snapshot used for this turn.
            baseline.setdefault("card_binding_id", card_binding_id)
            if hypothesis_id:
                baseline.setdefault("hypothesis_id", hypothesis_id)
            ensure(
                parent_run_id=run_id,
                card_binding_id=card_binding_id,
                hypothesis_id=hypothesis_id,
                snapshot=baseline,
                evidence_refs=list(baseline.get("evidence_ids", baseline.get("evidence_refs", [])) or [])[:32],
            )
        except Exception as exc:
            # A follow-up version must never silently become v1 when the
            # immutable formal baseline could not be registered.  Propagate a
            # bounded error so ``_answer_deep_turn`` records a partial result
            # and leaves the original card untouched; an explicit retry can
            # reconcile the baseline later.
            raise RuntimeError("formal capability baseline unavailable") from exc

    @app.get("/api/v1/runs/{run_id}/deep-thinking/sessions/{session_id}")
    @app.get("/api/v1/runs/{run_id}/deep-sessions/{session_id}")
    def get_deep_thinking_session(
        run_id: str,
        session_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        try:
            session = _deep_session_read(run_id, session_id, strict=True)
            research = _deep_research_rows(run_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep ledger unavailable",
            ) from exc
        if session is None:
            raise HTTPException(status_code=404, detail="deep-thinking session not found")
        return {
            "session": _deep_session_public(session),
            "research": research,
        }

    @app.get("/api/v1/runs/{run_id}/deep-thinking/sessions/{session_id}/events")
    @app.get("/api/v1/runs/{run_id}/deep-sessions/{session_id}/events")
    async def replay_deep_thinking_events(
        run_id: str,
        session_id: str,
        # The SSE ``id`` field is a numeric per-stream sequence in the current
        # transport, but clients from an earlier preview persisted the opaque
        # ``event_id`` instead.  Accept both forms and resolve opaque IDs via
        # the durable ledger below; rejecting them at FastAPI validation time
        # would make a reconnect lose the already-rendered prefix.
        last_event_id: str = Header(default="0", alias="Last-Event-ID"),
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> StreamingResponse:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        try:
            session = _deep_session_read(run_id, session_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep ledger unavailable",
            ) from exc
        if session is None:
            raise HTTPException(status_code=404, detail="deep-thinking session not found")

        async def stream():
            raw_cursor = str(last_event_id or "0").strip()
            try:
                sequence = max(0, int(raw_cursor))
            except (TypeError, ValueError):
                sequence = 0
                repo_for_cursor = _deep_repository()
                if repo_for_cursor is not None:
                    try:
                        resolved = repo_for_cursor.deep_event_sequence_for_id(
                            _deep_stream_id(run_id, session_id), raw_cursor
                        )
                        sequence = max(0, int(resolved or 0))
                    except Exception:
                        # An unknown opaque cursor is equivalent to a fresh
                        # stream.  Do not turn a reconnect into a 500 merely
                        # because an old event was compacted or deleted.
                        sequence = 0
            repo = _deep_repository()
            idle = 0
            while True:
                try:
                    rows = (
                        repo.deep_events_after(
                            _deep_stream_id(run_id, session_id), sequence
                        )
                        if repo is not None
                        else []
                    )
                except Exception as exc:
                    # Keep the stream contract stable during a transient
                    # ledger outage.  The error is visible and bounded; the
                    # client can reconnect with the last successful cursor.
                    safe_error = sanitize_runtime_payload(str(exc)[:300])
                    yield (
                        f"id: {sequence}\n"
                        "event: deep_stage\n"
                        "data: "
                        + json.dumps(
                            {
                                "schema_version": "deep-events-v1",
                                "event_id": "",
                                "sequence": sequence,
                                "event_type": "deep_stage",
                                "session_id": session_id,
                                "job_id": "",
                                "parent_run_id": run_id,
                                "child_run_id": "",
                                "stage": "validation",
                                "status": "partial",
                                "progress": 0.0,
                                "delta": {
                                    "kind": "summary",
                                    "text": "深研事件账本暂时不可用，请稍后重连。",
                                },
                                "evidence_refs": [],
                                "artifact_refs": [],
                                "version_refs": [],
                                "error": safe_error,
                                "created_at": now_iso(),
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                    break
                if rows:
                    for row in rows:
                        sequence = int(row.get("sequence", sequence))
                        # Deep events are persisted directly by the ledger,
                        # not always through EventBus.  Apply the same fixed
                        # projection and recursive sensitive-field filtering
                        # at this final transport boundary.
                        safe_public = _deep_public_event_payload(
                            {
                                **dict(row),
                                "event_type": row.get("event_type", "deep_stage"),
                                "session_id": session_id,
                                "parent_run_id": run_id,
                            },
                            run_id=run_id,
                            sequence=sequence,
                            event_type=row.get("event_type", "deep_stage"),
                        )
                        yield f"id: {sequence}\nevent: {safe_public['event_type']}\ndata: {json.dumps(safe_public, ensure_ascii=False)}\n\n"
                    idle = 0
                else:
                    idle += 1
                # Emit a heartbeat before the bounded replay window closes so
                # proxies and browsers can keep the connection alive.  A
                # reconnect remains safe because the cursor is monotonic.
                if idle and idle % 4 == 0:
                    yield ": heartbeat\n\n"
                # Use the SQLite-first projection for stream termination; a
                # stale sidecar status must not keep a cancelled/failed
                # stream alive after a worker restart.
                latest = _deep_session_read(run_id, session_id) or session
                if latest.get("status") in {"failed", "cancelled"} and not rows:
                    break
                # A request should never hold a worker thread forever.  The
                # client reconnects with Last-Event-ID when more stages arrive;
                # after a short quiet window close this bounded replay stream.
                if idle >= 20:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/runs/{run_id}/deep-thinking/sessions/{session_id}/messages", status_code=202)
    @app.post("/api/v1/runs/{run_id}/deep-sessions/{session_id}/messages", status_code=202)
    def append_deep_thinking_message(
        run_id: str,
        session_id: str,
        body: DeepSessionMessageBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope), mutation=True)
        # A configured SQLite ledger is authoritative for mutation ownership.
        # Do not turn a transient session-read outage into a misleading 404
        # (or let a stale sidecar transcript receive a new message).  Strict
        # mode raises ``_DeepLedgerUnavailable`` so the route can surface a
        # bounded 503 while preserving the caller's idempotency key for a
        # later retry.
        try:
            session = _deep_session_read(run_id, session_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep session ledger unavailable",
            ) from exc
        if session is None:
            raise HTTPException(status_code=404, detail="deep-thinking session not found")
        claimed = _claim_deep_idempotency(run_id=session_id, operation="message", key=idempotency_key, payload=body.model_dump(mode="json"))
        replay = _replay_or_raise_in_progress(claimed)
        if replay is not None:
            return replay
        try:
            response = _enqueue_deep_turn_job(
                run_id=run_id,
                view=view,
                session=session,
                content=body.content,
                focus=body.focus,
                create_artifact=body.create_artifact,
                idempotency_key=_deep_idempotency(
                    idempotency_key,
                    operation="message",
                    payload=body.model_dump(mode="json"),
                ),
            )
            # Complete the idempotency claim with the durable job reference,
            # not with a provider answer that may still be running.  Retries
            # after a timeout therefore replay the same task safely.
            _complete_deep_idempotency(
                run_id=session_id,
                operation="message",
                key=idempotency_key,
                resource_id=str(response.get("job", {}).get("job_id", "")),
                response=response,
            )
            return response
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/deep-thinking/sessions/{session_id}/merge")
    @app.post("/api/v1/runs/{run_id}/deep-sessions/{session_id}/merge")
    def merge_deep_thinking_capability(
        run_id: str,
        session_id: str,
        body: DeepSessionMergeBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        """Promote a provisional card into the parent capability snapshot.

        Merge is explicit and auditable.  The source session remains intact;
        the card carries ``deep_research_reference`` provenance and pending
        verification until a later quality review accepts it.
        """

        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope), mutation=True)
        # Validate the required key before looking up the target session, but
        # defer creating the durable claim until the session/artifact has
        # passed ownership checks.  A malformed or missing target must not
        # leave a permanently "in progress" idempotency row that blocks a
        # later retry with the same key.
        merge_payload = body.model_dump(mode="json")
        _deep_idempotency(
            idempotency_key,
            operation="merge",
            payload=merge_payload,
        )
        # Merge is a durable mutation as well.  Resolve the server-owned
        # session through the strict ledger path before inspecting artifacts;
        # otherwise a database outage can look like a normal 404 and leave a
        # retry key in an ambiguous state.
        try:
            session = _deep_session_read(run_id, session_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep session ledger unavailable",
            ) from exc
        if session is None:
            raise HTTPException(status_code=404, detail="deep-thinking session not found")
        session_binding = str(session.get("card_binding_id", "") or "").strip()
        session_hypothesis = str(session.get("hypothesis_id", "") or "").strip()
        artifacts = session.get("artifacts", []) if isinstance(session, Mapping) else []
        artifact = None
        wanted = str(body.artifact_id or "").strip()
        for item in artifacts if isinstance(artifacts, list) else []:
            if not isinstance(item, Mapping):
                continue
            artifact_status = str(
                item.get("version_status")
                or item.get("capability_version_status")
                or item.get("status")
                or ""
            ).strip().lower().replace("-", "_")
            if artifact_status in {"rejected", "rolled_back", "cancelled", "failed", "blocked"}:
                continue
            if artifact_status == "partial" and not any(
                str(item.get(key, "") or "").strip()
                for key in ("artifact_id", "capability_id", "version_id")
            ):
                # A partial row without any stable identity cannot be safely
                # retried or merged; do not let it become a wildcard.
                continue
            item_binding = str(item.get("card_binding_id", "") or "").strip()
            item_hypothesis = str(item.get("hypothesis_id", "") or "").strip()
            item_source_session = str(item.get("source_session_id", "") or "").strip()
            # An unbound/global session cannot select the first artifact in a
            # shared list.  Require an explicit artifact id or a server-owned
            # source-session marker before considering that artifact.
            if not session_binding and not session_hypothesis:
                if item_source_session != session_id:
                    continue
            if session_binding and item_binding != session_binding:
                continue
            if session_hypothesis and item_hypothesis != session_hypothesis:
                continue
            item_ids = {
                str(item.get(key, "") or "").strip()
                for key in ("artifact_id", "capability_id", "version_id", "hypothesis_id")
                if str(item.get(key, "") or "").strip()
            }
            if not wanted or wanted in item_ids:
                artifact = dict(item.get("payload", item)) if isinstance(item.get("payload", item), Mapping) else None
                if artifact is not None:
                    break
        if artifact is None:
            # Reference-research jobs persist their card in the durable ledger
            # even when the session response was lost during a reconnect.
            # Restrict the fallback to this session's exact lineage; selecting
            # the first pending row for an empty artifact id could otherwise
            # merge another card's draft into the current conversation.
            # Explicit merge/retry is allowed to recover a partial draft from
            # the same durable lineage.  Ordinary capability projections keep
            # partial versions hidden until they are reconciled.
            candidates = _deep_research_rows(
                run_id,
                include_history=False,
                include_partial=True,
            )
            scoped_candidates = []
            for item in candidates:
                if not isinstance(item, Mapping):
                    continue
                item_binding = str(item.get("card_binding_id", "") or "").strip()
                item_hypothesis = str(item.get("hypothesis_id", "") or "").strip()
                source_session = str(item.get("source_session_id", "") or "").strip()
                # A global session has no card identity and therefore must
                # never use the run-wide version list as a wildcard.  The
                # only safe fallback for such a session is an artifact that
                # explicitly records this exact source session.  For a
                # card-bound session, every server-owned identity carried by
                # the session must match (an empty item identity is not an
                # implicit match).
                if not session_binding and not session_hypothesis:
                    if not source_session or source_session != session_id:
                        continue
                if session_binding and item_binding != session_binding:
                    continue
                if session_hypothesis and item_hypothesis != session_hypothesis:
                    continue
                if source_session and source_session != session_id:
                    continue
                item_ids = {
                    str(item.get(key, "") or "").strip()
                    for key in ("artifact_id", "capability_id", "version_id", "hypothesis_id")
                    if str(item.get(key, "") or "").strip()
                }
                if wanted and wanted not in item_ids:
                    continue
                scoped_candidates.append(dict(item))
            # Without an explicit artifact id, only a unique scoped candidate
            # is safe to promote.  Ambiguous rows require the caller to pick
            # one explicitly instead of silently merging an arbitrary card.
            if len(scoped_candidates) == 1:
                artifact = scoped_candidates[0]
            elif len(scoped_candidates) > 1 and wanted:
                artifact = scoped_candidates[0]
        if artifact is None:
            raise HTTPException(status_code=404, detail="deep-thinking artifact not found")
        artifact["is_deep_research"] = True
        artifact["merged_from_session_id"] = session_id
        artifact["merge_status"] = "merged_pending_verification"
        artifact["updated_at"] = now_iso()
        repo = _deep_repository()
        binding_id = str(artifact.get("card_binding_id", "") or "").strip()
        hypothesis_id = str(artifact.get("hypothesis_id", "") or "").strip()
        if not binding_id or not hypothesis_id:
            raise HTTPException(status_code=422, detail="deep-thinking artifact has no stable capability lineage")

        # Claim only after the server has proven the session/artifact lineage.
        # This preserves replay protection for the mutation itself while
        # avoiding poisoned claims for 404/422 validation failures.
        claimed = _claim_deep_idempotency(
            run_id=session_id,
            operation="merge",
            key=idempotency_key,
            payload=merge_payload,
        )
        replay = _replay_or_raise_in_progress(claimed)
        if replay is not None:
            return replay

        # SQLite is the authoritative version ledger.  Commit/recover the
        # pending version before touching ``capability_images.json`` (which is
        # only a projection for reports and legacy readers).  This ordering
        # prevents a sidecar write from claiming success when the immutable
        # version record was lost, and lets a retry reconcile a projection
        # after a transient filesystem failure.
        version: dict[str, Any] | None = None
        ledger_error = ""
        if repo is None or not callable(getattr(repo, "save_capability_version", None)):
            ledger_error = "deep capability version repository unavailable"
        else:
            try:
                list_versions = getattr(repo, "list_capability_versions", None)
                prior_versions = list_versions(run_id, binding_id) if callable(list_versions) else []
                exact_versions = [
                    item for item in (prior_versions or [])
                    if isinstance(item, Mapping)
                    and str(item.get("hypothesis_id", "") or "").strip() == hypothesis_id
                ]
                existing_pending = next(
                    (
                        item for item in reversed(exact_versions)
                        if str(item.get("status", "") or "").strip().lower()
                        in {"pending_verification", "verified"}
                        and (
                            str((item.get("snapshot") or {}).get("capability_id", "") or "").strip()
                            == str(artifact.get("capability_id", "") or "").strip()
                            or str((item.get("snapshot") or {}).get("source_session_id", "") or "").strip()
                            == session_id
                        )
                    ),
                    None,
                )
                if isinstance(existing_pending, Mapping):
                    version = dict(existing_pending)
                else:
                    session_kind = str(session.get("kind", "") or "").strip().lower().replace("_", "-")
                    _ensure_deep_baseline(
                        repo,
                        run_id=run_id,
                        candidate=artifact,
                        card_binding_id=binding_id,
                        hypothesis_id=hypothesis_id,
                        allow_formal_baseline=session_kind in {"capability-followup", "capability", "follow-up"},
                    )
                    version_id = (
                        f"version-{artifact.get('capability_id', '')}-"
                        f"{hashlib.sha256(json.dumps(artifact, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]}"
                    )
                    version = repo.save_capability_version(
                        version_id=version_id,
                        parent_run_id=run_id,
                        card_binding_id=binding_id,
                        hypothesis_id=hypothesis_id,
                        snapshot=dict(artifact),
                        diff={"merge": "explicit_projection"},
                        base_snapshot_hash=hashlib.sha256(
                            json.dumps(artifact, ensure_ascii=False, sort_keys=True, default=str).encode()
                        ).hexdigest(),
                        source=str(artifact.get("source", "deep-thinking") or "deep-thinking"),
                        evidence_refs=list(artifact.get("evidence_ids", []))
                        if isinstance(artifact.get("evidence_ids", []), list)
                        else [],
                        status="pending_verification",
                    )
            except Exception as exc:
                ledger_error = str(exc).strip()[:1000] or type(exc).__name__

        if ledger_error:
            # Preserve the visible artifact/session for an explicit retry, but
            # never report a successful merge when the authoritative ledger
            # could not be written.
            partial_artifact = {
                **artifact,
                "merged": False,
                "merge_status": "partial",
                "status": "partial",
                "merge_error": ledger_error,
            }
            partial = {
                "merged": False,
                "status": "partial",
                "capability": partial_artifact,
                "version": None,
                "error": "capability version ledger unavailable",
                "retryable": True,
            }
            _deep_update_session(
                run_id,
                session_id,
                status="partial",
                artifacts=[{**partial_artifact, "artifact_id": wanted or artifact.get("capability_id", "")}],
            )
            _publish_deep_event(
                run_id,
                "deep_stage",
                {
                    "session_id": session_id,
                    "stage": "validation",
                    "status": "partial",
                    "kind": "summary",
                    "text": "合并未完成：能力版本账本写入受限，已保留草稿并等待重试。",
                    "error": ledger_error,
                },
            )
            _complete_deep_idempotency(
                run_id=session_id,
                operation="merge",
                key=idempotency_key,
                resource_id="",
                response=partial,
            )
            return partial

        if version is not None:
            artifact.update(
                {
                    "version_id": version.get("version_id", ""),
                    "version_no": version.get("version_no", artifact.get("version_no", 1)),
                    "version_status": version.get("status", "pending_verification"),
                }
            )

        root = _resolve_run_root(output_root, run_id, getattr(view, "result", {}))
        receipt: dict[str, Any] | None = None
        projection_error = ""
        if root is None:
            projection_error = "parent capability artifact is not ready"
        else:
            capability_path = root / "capability_images.json"
            try:
                receipt = merge_capability_into_snapshot(capability_path, artifact, mode=body.mode)
            except FileNotFoundError:
                projection_error = "parent capability artifact is not ready"
            except ValueError as exc:
                projection_error = str(exc)[:1000]
            except OSError:
                projection_error = "parent capability artifact projection is unavailable"

        if projection_error:
            partial_artifact = {
                **artifact,
                "merged": False,
                "merge_status": "partial",
                "status": "partial",
                "merge_error": projection_error,
            }
            partial = {
                "merged": False,
                "status": "partial",
                "capability": partial_artifact,
                "version": version,
                "error": projection_error,
                "retryable": True,
            }
            _deep_update_session(
                run_id,
                session_id,
                status="partial",
                artifacts=[{**partial_artifact, "artifact_id": wanted or artifact.get("capability_id", "")}],
            )
            _publish_deep_event(
                run_id,
                "deep_stage",
                {
                    "session_id": session_id,
                    "version_refs": [str(version.get("version_id", ""))] if version else [],
                    "stage": "publish",
                    "status": "partial",
                    "kind": "summary",
                    "text": "版本已保留，但能力画像投影尚未完成；可使用新的幂等键重试。",
                    "error": projection_error,
                },
            )
            _complete_deep_idempotency(
                run_id=session_id,
                operation="merge",
                key=idempotency_key,
                resource_id=str((version or {}).get("version_id", "")),
                response=partial,
            )
            return partial

        session_update = _deep_update_session(
            run_id,
            session_id,
            status="completed",
            artifacts=[{**artifact, "artifact_id": wanted or artifact.get("capability_id", ""), "status": "merged_pending_verification"}],
        )
        session_update_error = _deep_session_update_error(session_update)
        if session_update_error:
            # The immutable capability version and parent snapshot projection
            # may already exist, but the source session's durable state is not
            # coherent.  Never claim ``merged=true`` in that case: preserve a
            # retryable partial response and leave the pending version intact.
            partial_artifact = {
                **artifact,
                "merged": False,
                "merge_status": "partial",
                "status": "partial",
                "merge_error": session_update_error,
            }
            try:
                _deep_update_session(
                    run_id,
                    session_id,
                    status="partial",
                    artifacts=[
                        {
                            **partial_artifact,
                            "artifact_id": wanted or artifact.get("capability_id", ""),
                        }
                    ],
                )
            except Exception:
                pass
            partial = {
                "merged": False,
                "status": "partial",
                "capability": partial_artifact,
                "version": version,
                "receipt": receipt or {},
                "error": f"deep session projection unavailable: {session_update_error}"[:1000],
                "retryable": True,
            }
            _publish_deep_event(
                run_id,
                "deep_stage",
                {
                    "session_id": session_id,
                    "version_refs": [str(version.get("version_id", ""))] if version else [],
                    "stage": "publish",
                    "status": "partial",
                    "kind": "summary",
                    "text": "能力版本已保留，但会话状态投影尚未完成；请使用新的幂等键重试。",
                    "error": session_update_error,
                },
            )
            _complete_deep_idempotency(
                run_id=session_id,
                operation="merge",
                key=idempotency_key,
                resource_id=str((version or {}).get("version_id", "")),
                response=partial,
            )
            return partial
        _publish_deep_event(
            run_id,
            "deep_capability_merged",
            {
                "session_id": session_id,
                "capability_id": artifact.get("capability_id", ""),
                "hypothesis_id": hypothesis_id,
                "version_refs": [str(version.get("version_id", ""))] if version else [],
                "receipt": receipt or {},
                "status": "merged_pending_verification",
            },
        )
        response = {
            "merged": True,
            "status": "merged_pending_verification",
            "capability": artifact,
            "receipt": receipt or {},
            "version": version,
        }
        _complete_deep_idempotency(
            run_id=session_id,
            operation="merge",
            key=idempotency_key,
            resource_id=str((version or {}).get("version_id", artifact.get("capability_id", ""))),
            response=response,
        )
        return response

    @app.post("/api/v1/runs/{run_id}/deep-thinking/reference-research", status_code=202)
    @app.post("/api/v1/runs/{run_id}/deep-research", status_code=202)
    def start_reference_deep_research(
        run_id: str,
        body: ReferenceResearchBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        """Queue a single-equipment contextual dialogue for a reference weapon.

        New requests stay on the parent run and reuse its canonical Query,
        evidence and candidate snapshot.  Historical rows that already carry
        a child run are still readable/recoverable by the compatibility path,
        but this endpoint never creates a fresh S1--S6 child workflow.
        """

        _require_role(x_role, {"analyst", "admin"})
        parent = read_view(run_id)
        scope = _assert_deep_scope(parent, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope), mutation=True)
        candidate = _candidate_from_run(run_id, parent, body.model_dump(mode="json"))
        if not candidate:
            raise HTTPException(status_code=422, detail="reference weapon context is required")
        candidate.setdefault("hypothesis_id", body.hypothesis_id)
        candidate_hypothesis = str(candidate.get("hypothesis_id", "")).strip()
        if not candidate_hypothesis:
            # Historical/artifact-only candidates may not carry the winning
            # ledger's hypothesis id.  Derive a deterministic identity from
            # the server-resolved candidate instead of generating a random id
            # per click; otherwise repeated reference-research requests would
            # bypass the required canonical fingerprint de-duplication.
            identity_parts = [
                str(candidate.get(key, "")).strip()
                for key in (
                    "card_binding_id",
                    "capability_id",
                    "candidate_id",
                    "title",
                    "name",
                    "primary_equipment_identity",
                    "equipment_form",
                )
                if str(candidate.get(key, "")).strip()
            ]
            identity_seed = "\x1f".join(identity_parts) or json.dumps(
                candidate, ensure_ascii=False, sort_keys=True, default=str
            )[:2000]
            candidate_hypothesis = (
                "hypothesis-reference-"
                + hashlib.sha256(
                    f"{run_id}\x1f{identity_seed}".encode("utf-8")
                ).hexdigest()[:24]
            )
            candidate["hypothesis_id"] = candidate_hypothesis
        name = str(candidate.get("title") or candidate.get("name") or candidate.get("equipment_form") or "参考装备方向").strip()
        # Resolve the default prompt before reserving the durable job.  The
        # reservation is the recovery source of truth; storing an empty
        # question there would make a process restart lose the only user
        # visible turn and incorrectly mark the job partial.
        question = str(body.question or "").strip() or (
            f"请围绕“{name}”在当前 Query 下继续发散，比较竞争方向并判断是否达到固定成卡条件。"
        )
        question = question[:DEEP_THINKING_MAX_MESSAGE_CHARS]
        focus = str(body.focus or question or "针对该参考装备方向补齐当前 Query 的能力画像").strip()[:1600]
        query = _deep_query(parent)
        fingerprint, query_snapshot_hash, focus_hash = _deep_canonical_fingerprint(
            parent_run_id=run_id,
            hypothesis_id=candidate_hypothesis,
            query=query,
            focus=focus,
        )
        idem = _deep_idempotency(idempotency_key, operation="reference-research", payload={"hypothesis_id": candidate_hypothesis, "focus": focus, "question": question, "fingerprint": fingerprint})
        repo = _deep_repository()
        reference_idempotency_payload = {
            "hypothesis_id": candidate_hypothesis,
            "focus": focus,
            "question": question,
            "fingerprint": fingerprint,
        }
        if repo is not None:
            fingerprint_lookup = getattr(repo, "get_deep_job_by_fingerprint", None)
            if callable(fingerprint_lookup):
                # Once the durable fingerprint API exists, an operational
                # failure is a ledger outage, not a cache miss.  Falling
                # through would permit a second child run and violate the
                # canonical de-duplication fence.
                try:
                    canonical = fingerprint_lookup(run_id, fingerprint)
                except Exception as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="deep job ledger unavailable",
                    ) from exc
                if canonical is not None:
                    # The repository method is parent/fingerprint scoped, so
                    # a non-mapping row or a mismatched identity indicates a
                    # corrupt adapter response rather than a cache miss.  Do
                    # not expose a cross-run job or create a second child.
                    if not isinstance(canonical, Mapping):
                        raise HTTPException(
                            status_code=503,
                            detail="deep job ledger unavailable",
                        )
                    canonical_parent = str(canonical.get("parent_run_id", "") or "")
                    canonical_fingerprint = str(canonical.get("fingerprint", "") or "")
                    # Older durable adapters may project only ``job_id`` and
                    # omit the indexed columns.  Accept those minimal rows
                    # for compatibility, while rejecting an explicit
                    # cross-parent/fingerprint mismatch from a broken or
                    # untrusted adapter.
                    if (
                        (canonical_parent and canonical_parent != str(run_id))
                        or (canonical_fingerprint and canonical_fingerprint != str(fingerprint))
                    ):
                        raise HTTPException(
                            status_code=503,
                            detail="deep job ledger unavailable",
                        )
                    canonical_status = str(canonical.get("status", "") or "").strip().lower()
                    if body.retry and canonical_status in {"partial", "failed", "blocked", "cancelled"}:
                        retry_claim = _claim_deep_idempotency(
                            run_id=run_id,
                            operation="reference-research-retry",
                            key=idempotency_key,
                            payload=reference_idempotency_payload,
                        )
                        retry_replay = _replay_or_raise_in_progress(retry_claim)
                        if retry_replay is not None:
                            return retry_replay
                        response = _schedule_reference_retry(
                            canonical,
                            run_id=run_id,
                            scope=scope,
                        )
                        _complete_deep_idempotency(
                            run_id=run_id,
                            operation="reference-research-retry",
                            key=idempotency_key,
                            resource_id=str(canonical.get("job_id", "")),
                            response=response,
                        )
                        return response
                    # Even a fingerprint replay must pass through the
                    # request-key ledger.  Otherwise a caller could reuse an
                    # existing key with a different question/focus and
                    # bypass the request-hash conflict fence.
                    replay_claim = _claim_deep_idempotency(
                        run_id=run_id,
                        operation="reference-research",
                        key=idempotency_key,
                        payload=reference_idempotency_payload,
                    )
                    replay_response = _replay_or_raise_in_progress(replay_claim)
                    if replay_response is not None:
                        return replay_response
                    response = {"job": _deep_job_public(canonical), "scope": scope, "idempotent_replay": True}
                    _complete_deep_idempotency(run_id=run_id, operation="reference-research", key=idempotency_key, resource_id=str(canonical.get("job_id", "")), response=response)
                    return response
                # The fingerprint query is authoritative.  A separate
                # idempotency-key lookup is still useful for retries from an
                # older client, but it must also fail closed when available.
                list_jobs = getattr(repo, "list_deep_jobs", None)
                if callable(list_jobs):
                    try:
                        existing = [
                            job
                            for job in list_jobs(run_id)
                            if isinstance(job, Mapping)
                            and str(job.get("idempotency_key", "")) == idem
                        ]
                    except Exception as exc:
                        raise HTTPException(
                            status_code=503,
                            detail="deep job ledger unavailable",
                        ) from exc
                    if existing:
                        replay_claim = _claim_deep_idempotency(
                            run_id=run_id,
                            operation="reference-research",
                            key=idempotency_key,
                            payload=reference_idempotency_payload,
                        )
                        replay_response = _replay_or_raise_in_progress(replay_claim)
                        if replay_response is not None:
                            return replay_response
                        response = {"job": _deep_job_public(existing[0]), "scope": scope, "idempotent_replay": True}
                        _complete_deep_idempotency(run_id=run_id, operation="reference-research", key=idempotency_key, resource_id=str(existing[0].get("job_id", "")), response=response)
                        return response
            else:
                # Explicit compatibility path for adapters created before
                # ``get_deep_job_by_fingerprint``.  These adapters do not
                # provide the canonical durable fingerprint fence, so retain
                # the historical idempotency-key lookup when available.
                list_jobs = getattr(repo, "list_deep_jobs", None)
                if callable(list_jobs):
                    try:
                        existing = [
                            job
                            for job in list_jobs(run_id)
                            if isinstance(job, Mapping)
                            and str(job.get("idempotency_key", "")) == idem
                        ]
                    except Exception as exc:
                        raise HTTPException(
                            status_code=503,
                            detail="deep job ledger unavailable",
                        ) from exc
                    if existing:
                        replay_claim = _claim_deep_idempotency(
                            run_id=run_id,
                            operation="reference-research",
                            key=idempotency_key,
                            payload=reference_idempotency_payload,
                        )
                        replay_response = _replay_or_raise_in_progress(replay_claim)
                        if replay_response is not None:
                            return replay_response
                        response = {"job": _deep_job_public(existing[0]), "scope": scope, "idempotent_replay": True}
                        _complete_deep_idempotency(run_id=run_id, operation="reference-research", key=idempotency_key, resource_id=str(existing[0].get("job_id", "")), response=response)
                        return response
        else:
            with deep_worker_lock:
                canonical = next(
                    (
                        dict(item)
                        for item in deep_memory_jobs.values()
                        if str(item.get("parent_run_id")) == str(run_id)
                        and str(item.get("fingerprint")) == fingerprint
                    ),
                    None,
                )
            if canonical is not None:
                replay_claim = _claim_deep_idempotency(
                    run_id=run_id,
                    operation="reference-research",
                    key=idempotency_key,
                    payload=reference_idempotency_payload,
                )
                replay_response = _replay_or_raise_in_progress(replay_claim)
                if replay_response is not None:
                    return replay_response
                response = {"job": _deep_job_public(canonical), "scope": scope, "idempotent_replay": True}
                _complete_deep_idempotency(run_id=run_id, operation="reference-research", key=idempotency_key, resource_id=str(canonical.get("job_id", "")), response=response)
                return response
        # A reference-research action is intended for candidates that did not
        # pass the S6 selection gate.  Never launch a duplicate child task for
        # an already accepted formal capability card.
        selection_status = str(
            candidate.get("selection_status")
            or candidate.get("status")
            or candidate.get("provenance_status")
            or ""
        ).strip().lower().replace("-", "_")
        # Formal/verified capability projections may not carry the older
        # ``selection_status`` field.  Treat their server-derived version
        # state as an equivalent S6 admission fence so a direct API caller
        # cannot relabel an already accepted card as a reference weapon.
        version_status = str(
            candidate.get("version_status")
            or candidate.get("capability_version_status")
            or candidate.get("verification_status")
            or ""
        ).strip().lower().replace("-", "_")
        if candidate.get("s6_eligible") is True or selection_status in {
            "selected",
            "selected_limited",
            "accepted",
            "formal_s6",
            "s6",
            "s6_eligible",
        } or version_status in {"formal", "verified", "approved", "accepted"}:
            raise HTTPException(
                status_code=409,
                detail="reference candidate already passed the S6 selection gate",
            )
        # Claim only after canonical candidate and selection validation.  A
        # rejected/invalid reference card must not poison the caller's key as
        # an in-flight request and prevent a corrected retry.
        claim = _claim_deep_idempotency(
            run_id=run_id,
            operation="reference-research",
            key=idempotency_key,
            payload=reference_idempotency_payload,
        )
        if claim and claim.get("response"):
            return dict(claim["response"])
        # Reserve the canonical job before creating the session.  The job is
        # then handed to the single-equipment dialogue worker below.  Keeping
        # the reservation separate from execution closes the race where two
        # clicks with different request keys would otherwise create two
        # sessions or two capability versions.
        generated_job_id = new_stable_id("deep-research")
        reserved_job = _deep_store_job(
            job_id=generated_job_id,
            parent_run_id=run_id,
            session_id="",
            kind="reference-research",
            idempotency_key=idem,
            fingerprint=fingerprint,
            payload={
                "hypothesis_id": candidate_hypothesis,
                "query_snapshot_hash": query_snapshot_hash,
                "focus_hash": focus_hash,
                "query": query[:4000],
                "focus": focus[:1600],
                "question": question,
                "dialogue_mode": "single_equipment_contextual_divergence",
                "create_artifact": True,
                "candidate": candidate,
            },
        )
        job_id = str(reserved_job.get("job_id") or generated_job_id)
        if job_id != generated_job_id:
            response = {"job": _deep_job_public(reserved_job), "scope": scope, "idempotent_replay": True}
            _complete_deep_idempotency(
                run_id=run_id,
                operation="reference-research",
                key=idempotency_key,
                resource_id=job_id,
                response=response,
            )
            return response
        # The selected candidate is the only equipment identity this session
        # may author.  Keep the broader run snapshot for evidence/history, but
        # make the target explicit so a model cannot merge multiple cards.
        context = _deep_context_for_run(run_id, parent, {})
        context.update(
            {
                "candidate": candidate,
                "reference_weapon": candidate,
                "query": query,
                "focus": focus,
                "deep_research_mode": "single_equipment_contextual_divergence",
                "canonical_hypothesis_id": candidate_hypothesis,
            }
        )
        session = create_deep_session(
            output_root,
            run_id=run_id,
            kind="reference-research",
            title=f"参考武器深度研究 · {name}",
            capability_name=name,
            card_binding_id=str(candidate.get("card_binding_id", "")),
            hypothesis_id=candidate_hypothesis,
            context_refs=context,
            created_by=x_role,
        )
        session = {**session, "idempotency_key": idem, "scope": scope}
        # Persist the parent-bound session before scheduling the dialogue.  The
        # sidecar remains a compatibility projection, but a worker restart
        # must be able to recover the session/job relation from SQLite alone.
        persisted = _persist_deep_session(session, view=parent, scope=scope)
        if persisted is False:
            try:
                update_deep_session(
                    output_root,
                    run_id=run_id,
                    session_id=str(session.get("session_id", "")),
                    status="partial",
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail="deep session ledger unavailable; research kept as partial draft",
            )
        _deep_job_update(
            job_id,
            run_id=run_id,
            session_id=str(session.get("session_id", "")),
            stage="queued",
            status="queued",
            progress=0.0,
            text="参考武器深度对话已排队，等待单装备发散 Worker。",
        )
        # Reference research now follows exactly the same visible dialogue
        # lifecycle as a card follow-up.  It is a single bounded model turn,
        # not a newly created Run and not a re-entry into S1--S6.
        _publish_deep_event(
            run_id,
            "deep_research_started",
            {
                "job_id": job_id,
                "session_id": session["session_id"],
                "hypothesis_id": candidate_hypothesis,
                "child_run_id": "",
                "stage": "context",
                "status": "queued",
                "progress": 0.0,
                "text": "参考武器已锁定为单装备目标，进入对话式深度发散。",
            },
        )
        response_turn = _enqueue_deep_turn_job(
            run_id=run_id,
            view=parent,
            session=session,
            content=question,
            focus=focus,
            create_artifact=True,
            idempotency_key=idem,
            fingerprint=fingerprint,
            job_id=job_id,
            job_kind="reference-research",
            pre_reserved=True,
        )
        response_job = _deep_job_get(job_id) or {"job_id": job_id, "status": "queued", "stage": "queued", "fingerprint": fingerprint}
        response = {
            "job": _deep_job_public(response_turn.get("job") or response_job),
            "child_run": None,
            "session": _deep_session_public(
                _deep_session_read(run_id, session["session_id"]) or session
            ),
            "artifact": None,
            "scope": scope,
        }
        _complete_deep_idempotency(run_id=run_id, operation="reference-research", key=idempotency_key, resource_id=job_id, response=response)
        return response
    @app.get("/api/v1/runs/{run_id}/deep-thinking/reference-research")
    @app.get("/api/v1/runs/{run_id}/deep-research")
    def get_reference_deep_research(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        parent = read_view(run_id)
        _assert_deep_scope(parent, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        # SQLite deep_jobs/deep_run_links are authoritative.  Sidecar links
        # are retained only for an explicitly pre-ledger adapter that exposes
        # neither durable listing method.
        repo = _deep_repository()
        list_jobs = getattr(repo, "list_deep_jobs", None) if repo is not None else None
        list_links = getattr(repo, "list_deep_run_links", None) if repo is not None else None
        durable_listing = callable(list_jobs) or callable(list_links)
        if durable_listing:
            try:
                durable_jobs = [
                    dict(item)
                    for item in (list_jobs(run_id) if callable(list_jobs) else [])
                    if isinstance(item, Mapping)
                    and str(item.get("kind", ""))
                    in {"deep_divergence_v1", "reference-research", "reference_weapon"}
                ]
                durable_links = {
                    str(item.get("job_id", "")): dict(item)
                    for item in (list_links(run_id) if callable(list_links) else [])
                    if isinstance(item, Mapping) and str(item.get("job_id", ""))
                }
                merged: list[dict[str, Any]] = []
                seen_jobs: set[str] = set()
                for job in durable_jobs:
                    jid = str(job.get("job_id", ""))
                    if not jid:
                        continue
                    payload = job.get("payload", {})
                    payload = payload if isinstance(payload, Mapping) else {}
                    candidate_payload = payload.get("candidate", {})
                    candidate_payload = dict(candidate_payload) if isinstance(candidate_payload, Mapping) else {}
                    link = durable_links.get(jid, {})
                    item = {
                        **link,
                        **job,
                        "job_id": jid,
                        "child_run_id": str(job.get("child_run_id") or link.get("child_run_id", "")),
                        "session_id": str(job.get("session_id") or link.get("session_id", "")),
                        "hypothesis_id": str(candidate_payload.get("hypothesis_id") or payload.get("hypothesis_id") or link.get("hypothesis_id", "")),
                        "capability_name": str(candidate_payload.get("title") or candidate_payload.get("name") or link.get("capability_name", "")),
                    }
                    merged.append(item)
                    seen_jobs.add(jid)
                links = merged
            except Exception as exc:
                # A configured durable ledger is fail-closed.  In particular,
                # do not append stale sidecar links after a database outage.
                raise HTTPException(
                    status_code=503,
                    detail="deep job ledger unavailable",
                ) from exc
        else:
            links = _deep_links_read(run_id)
        jobs: list[dict[str, Any]] = []
        for link in links:
            item = dict(link)
            child_id = str(item.get("child_run_id", ""))
            if child_id:
                try:
                    child = read_view(child_id)
                    # ``deep_jobs.status`` is the authoritative research state;
                    # expose the child run state separately instead of allowing a
                    # polling GET to overwrite a completed/partial deep job with
                    # the child's intermediate status.
                    item["child_status"] = child.status
                    item["child_updated_at"] = child.updated_at
                    if not item.get("status"):
                        item["status"] = child.status
                    if child.status == "completed":
                        item["results"] = get_capabilities(child_id, x_role="analyst")
                        # GET is strictly read-only.  A worker or explicit
                        # reviewer action owns publication/merge; polling must
                        # never mutate the parent snapshot or emit duplicate
                        # completion events.
                        item["merged"] = bool(item.get("merged") or item.get("merged_at"))
                        item["merge_status"] = str(item.get("merge_status") or ("merged_pending_verification" if item.get("merged") else "available_for_parent"))
                except Exception as exc:
                    item["status"] = item.get("status") or "unknown"
                    item["error"] = str(exc)
            else:
                # Contextual dialogue reference jobs intentionally have no
                # child run.  Resolve their visible draft/version through the
                # bound session and keep the durable deep-job status intact;
                # never call ``read_view("")`` or manufacture a child error.
                session_id = str(item.get("session_id", "") or "")
                if session_id:
                    try:
                        session = _deep_session_read(run_id, session_id)
                        if isinstance(session, Mapping):
                            item["session_status"] = session.get("status", "")
                            artifacts = session.get("artifacts", [])
                            if isinstance(artifacts, list):
                                item["results"] = [
                                    sanitize_runtime_payload(dict(row), max_string_length=12000)
                                    for row in artifacts[:24]
                                    if isinstance(row, Mapping)
                                ]
                                item["merged"] = bool(item.get("merged") or item.get("merged_at"))
                                item["merge_status"] = str(
                                    item.get("merge_status")
                                    or ("merged_pending_verification" if item.get("merged") else "available_for_parent")
                                )
                    except Exception as exc:
                        item["error"] = str(exc)[:1000]
            # Keep polling responses on the same browser-safe contract as the
            # single-job endpoint.  In particular, do not expose the durable
            # payload envelope (which contains canonical query/candidate
            # hand-off data) or arbitrary legacy ``local_result`` fields.
            public_item = _deep_job_public(item)
            if isinstance(item.get("results"), list):
                public_item["results"] = [
                    sanitize_runtime_payload(dict(row), max_string_length=12000)
                    for row in item["results"][:24]
                    if isinstance(row, Mapping)
                ]
            jobs.append(public_item)
        try:
            research = _deep_research_rows(run_id, strict=True)
        except _DeepLedgerUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc) or "deep ledger unavailable",
            ) from exc
        return {"run_id": run_id, "jobs": jobs, "research": research}

    @app.get("/api/v1/runs/{run_id}/deep-research/{job_id}")
    def get_reference_deep_research_job(
        run_id: str,
        job_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        parent = read_view(run_id)
        _assert_deep_scope(parent, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        repo = _deep_repository()
        item = None
        durable_getter = getattr(repo, "get_deep_job", None) if repo is not None else None
        if callable(durable_getter):
            try:
                durable = durable_getter(job_id)
                if durable is not None and str(durable.get("parent_run_id")) == str(run_id):
                    payload = durable.get("payload", {})
                    payload = payload if isinstance(payload, Mapping) else {}
                    candidate_payload = payload.get("candidate", {})
                    candidate_payload = candidate_payload if isinstance(candidate_payload, Mapping) else {}
                    item = {
                        **dict(durable),
                        "hypothesis_id": str(candidate_payload.get("hypothesis_id") or payload.get("hypothesis_id", "")),
                        "capability_name": str(candidate_payload.get("title") or candidate_payload.get("name", "")),
                    }
                    list_links = getattr(repo, "list_deep_run_links", None)
                    if callable(list_links):
                        try:
                            links = list_links(run_id)
                            link = next(
                                (
                                    row
                                    for row in links
                                    if isinstance(row, Mapping)
                                    and str(row.get("job_id", "")) == str(job_id)
                                ),
                                None,
                            )
                            if link:
                                item = {**link, **item}
                        except Exception:
                            # The job row is still authoritative; an optional
                            # link projection being unavailable must not revive
                            # a sidecar row.
                            pass
            except Exception:
                # A configured durable lookup failure is fail-closed.
                raise HTTPException(status_code=503, detail="deep job ledger unavailable")
            if item is None:
                # A successful durable lookup returning no matching parent is
                # an authoritative miss; never search the legacy sidecar.
                raise HTTPException(status_code=404, detail="deep research job not found")
        else:
            item = next((row for row in list_research_links(output_root, parent_run_id=run_id) if str(row.get("job_id", "")) == str(job_id)), None)
        if item is None:
            raise HTTPException(status_code=404, detail="deep research job not found")
        child_id = str(item.get("child_run_id", ""))
        if child_id:
            try:
                child = read_view(child_id)
                item["child_status"] = child.status
                item["child_updated_at"] = child.updated_at
                if child.status == "completed":
                    item["results"] = get_capabilities(child_id, x_role="analyst")
            except Exception as exc:
                item["error"] = str(exc)
        else:
            # New single-equipment contextual dialogue jobs have no child run;
            # expose their session-bound draft/version without attempting an
            # empty run lookup.
            session_id = str(item.get("session_id", "") or "")
            if session_id:
                try:
                    session = _deep_session_read(run_id, session_id)
                    if isinstance(session, Mapping):
                        item["session_status"] = session.get("status", "")
                        artifacts = session.get("artifacts", [])
                        if isinstance(artifacts, list):
                            item["results"] = [
                                sanitize_runtime_payload(dict(row), max_string_length=12000)
                                for row in artifacts[:24]
                                if isinstance(row, Mapping)
                            ]
                except Exception as exc:
                    item["error"] = str(exc)[:1000]
        return {"job": _deep_job_public(item)}

    @app.get("/api/v1/runs/{run_id}/deep-thinking/jobs/{job_id}")
    def get_deep_job(run_id: str, job_id: str, x_role: str = Header(default="analyst", alias="X-Role"), x_tenant_id: str = Header(default="", alias="X-Tenant-ID"), x_workspace_id: str = Header(default="", alias="X-Workspace-ID"), x_project_id: str = Header(default="", alias="X-Project-ID"), x_profile_id: str = Header(default="", alias="X-Profile-ID"), x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"), x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope")) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        repo = _deep_repository()
        getter = getattr(repo, "get_deep_job", None) if repo is not None else None
        if callable(getter):
            try:
                job = getter(job_id)
            except Exception:
                raise HTTPException(status_code=503, detail="deep job ledger unavailable")
            if not isinstance(job, Mapping) or str(job.get("parent_run_id")) != str(run_id):
                # A durable miss is authoritative; do not fall back to a stale
                # compatibility link with the same opaque job id.
                job = None
        else:
            # Compatibility with the legacy link ledger is limited to
            # adapters that do not implement the durable lookup at all.
            job = next(
                (
                    row
                    for row in list_research_links(output_root, parent_run_id=run_id)
                    if isinstance(row, Mapping)
                    and str(row.get("job_id")) == str(job_id)
                ),
                None,
            )
        if job is None:
            raise HTTPException(status_code=404, detail="deep job not found")
        return {"job": _deep_job_public(job)}

    @app.post("/api/v1/runs/{run_id}/deep-thinking/jobs/{job_id}/cancel")
    def cancel_deep_job(
        run_id: str,
        job_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "admin"})
        parent = read_view(run_id)
        scope = _assert_deep_scope(
            parent,
            role=x_role,
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
            cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope),
        )
        cancel_payload = {"job_id": job_id}
        _deep_idempotency(
            idempotency_key,
            operation="cancel-job",
            payload=cancel_payload,
        )
        repo = _deep_repository()
        if repo is None:
            raise HTTPException(status_code=503, detail="deep job repository unavailable")
        # The durable job row is authoritative for cancellation.  A transient
        # SQLite/adapter failure must be visible as an outage, not leak as a
        # generic 500 or accidentally proceed against an in-memory/sidecar
        # projection.
        try:
            job = repo.get_deep_job(job_id)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="deep job ledger unavailable",
            ) from exc
        if job is None or str(job.get("parent_run_id")) != str(run_id):
            raise HTTPException(status_code=404, detail="deep job not found")
        # Claim only after the parent-scoped job lookup succeeds, avoiding a
        # permanently in-progress key for a typoed/non-owned job id.
        claimed = _claim_deep_idempotency(
            run_id=run_id,
            operation="cancel-job",
            key=idempotency_key,
            payload=cancel_payload,
        )
        replay = _replay_or_raise_in_progress(claimed)
        if replay is not None:
            return replay
        # Signal the in-process dispatcher first so a queued turn exits at its
        # next visible stage boundary.  The durable status update is still the
        # source of truth for API workers that do not share this process.
        _deep_cancel_signal(job_id)
        child_run_id = str(job.get("child_run_id", "") or "")
        child_cleanup: dict[str, Any] = {}
        if child_run_id:
            try:
                child = service.get_run(child_run_id)
                if child.status not in {"completed", "failed", "cancelled", "archived"}:
                    try:
                        service.cancel_run(
                            child_run_id,
                            actor="deep-thinking-agent",
                            idempotency_key=f"deep-cancel:{job_id}",
                        )
                    except Exception:
                        pass
                    try:
                        service.set_status(child_run_id, "cancelled")
                    except Exception:
                        pass
                cleanup = terminate_run_process_groups(child_run_id)
                child_cleanup = cleanup.__dict__
            except Exception as exc:
                child_cleanup = {"error": str(exc)[:1000]}
        try:
            updated = repo.update_deep_job(
                job_id,
                stage="publish",
                status="cancelled",
                child_run_id=child_run_id or None,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="deep job ledger unavailable",
            ) from exc
        if updated is None:
            # The row existed during the ownership check but disappeared (or
            # became unreadable) before the conditional transition.  Do not
            # acknowledge cancellation without a durable terminal row.
            raise HTTPException(status_code=404, detail="deep job not found")
        sid = str(job.get("session_id", ""))
        if sid:
            try: _deep_update_session(run_id, sid, status="cancelled")
            except Exception: pass
        _publish_deep_event(run_id, "deep_job_cancelled", {"job_id": job_id, "session_id": sid, "child_run_id": child_run_id, "stage": "publish", "status": "cancelled", "progress": 1.0})
        response = {"job": _deep_job_public(updated or job), "status": "cancelled", "child_cleanup": child_cleanup, "scope": scope}
        _complete_deep_idempotency(run_id=run_id, operation="cancel-job", key=idempotency_key, resource_id=job_id, response=response)
        return response

    @app.get("/api/v1/runs/{run_id}/capability-versions")
    def get_capability_versions(
        run_id: str,
        card_binding_id: str = "",
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"), x_workspace_id: str = Header(default="", alias="X-Workspace-ID"), x_project_id: str = Header(default="", alias="X-Project-ID"), x_profile_id: str = Header(default="", alias="X-Profile-ID"), x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"), x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        repo = _deep_repository()
        rows: Any = []
        list_versions = getattr(repo, "list_capability_versions", None) if repo is not None else None
        if callable(list_versions):
            # A configured durable ledger is authoritative.  Treat read
            # failures as an explicit service outage rather than returning a
            # misleading empty portrait (or reviving legacy sidecar data).
            try:
                rows = list_versions(run_id, card_binding_id)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail="deep version repository unavailable",
                ) from exc
        # An adapter with no capability-version method is an explicitly
        # supported pre-ledger deployment; preserve the historical empty
        # response in that narrow compatibility case.
        rows = [
            _deep_version_public(item)
            for item in (rows if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else [])
            if isinstance(item, Mapping)
        ]
        return {"run_id": run_id, "versions": rows}

    @app.post("/api/v1/runs/{run_id}/capability-versions/{version_id}/verify")
    def verify_capability_version(
        run_id: str,
        version_id: str,
        body: dict[str, Any],
        x_role: str = Header(default="analyst", alias="X-Role"),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"), x_workspace_id: str = Header(default="", alias="X-Workspace-ID"), x_project_id: str = Header(default="", alias="X-Project-ID"), x_profile_id: str = Header(default="", alias="X-Profile-ID"), x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"), x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        view = read_view(run_id)
        _assert_deep_scope(view, role=x_role, tenant_id=x_tenant_id, workspace_id=x_workspace_id, project_id=x_project_id, profile_id=x_profile_id, stage_scope=x_evolution_stage_scope, cross_scope=x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope))
        # Require the key before validating the target, but do not claim an
        # idempotency row until the version/decision are known to be valid.
        # Otherwise a typoed version id would poison the key as permanently
        # in-progress and make a corrected retry impossible.
        _deep_idempotency(
            idempotency_key,
            operation="verify-version",
            payload=body,
        )
        status = str(body.get("status", body.get("decision", ""))).strip().lower()
        status = {"approved": "verified", "accept": "verified", "rejected": "rejected", "rollback": "rolled_back"}.get(status, status)
        if status not in {"verified", "rejected", "rolled_back", "pending_verification"}:
            raise HTTPException(status_code=422, detail="invalid verification status")
        repo = _deep_repository()
        if repo is None:
            raise HTTPException(status_code=503, detail="deep version repository unavailable")
        # Read the exact parent-scoped version before claiming.  This is a
        # read-only ownership check; the repository's subsequent UPDATE still
        # carries the parent predicate as the atomic mutation fence.
        getter = getattr(repo, "get_capability_version", None)
        if not callable(getter):
            raise HTTPException(status_code=503, detail="deep version repository unavailable")
        try:
            existing_version = getter(version_id, parent_run_id=run_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="deep version repository unavailable") from exc
        if existing_version is None:
            raise HTTPException(status_code=404, detail="capability version not found")
        if str(existing_version.get("status", "") or "").strip().lower() == "formal":
            raise HTTPException(status_code=422, detail="formal capability version is immutable")
        claimed = _claim_deep_idempotency(
            run_id=run_id,
            operation="verify-version",
            key=idempotency_key,
            payload=body,
        )
        replay = _replay_or_raise_in_progress(claimed)
        if replay is not None:
            return replay
        try:
            version = repo.verify_capability_version(
                version_id,
                status=status,
                parent_run_id=run_id,
            )
        except ValueError as exc:
            # Invalid decisions and attempts to mutate the immutable formal
            # v1 baseline are client errors, never uncaught worker failures.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if version is None:
            raise HTTPException(status_code=404, detail="capability version not found")
        _publish_deep_event(run_id, "capability_version_verified", {"version_refs": [version_id], "status": status, "stage": "publish"})
        response = {"version": _deep_version_public(version)}
        _complete_deep_idempotency(run_id=run_id, operation="verify-version", key=idempotency_key, resource_id=version_id, response=response)
        return response

    def _favorite_owner(scope: str, user_id: str) -> str:
        """Resolve the storage owner without trusting a client body field."""

        if scope == "global":
            return "workspace"
        normalized_user = str(user_id or "").strip()
        if not normalized_user:
            raise HTTPException(
                status_code=403,
                detail="private favorites require authentication",
            )
        return normalized_user[:128]

    def _find_favorite_for_retry(
        *,
        scope: str,
        owner_id: str,
        run_id: str,
        body: FavoriteCreateBody,
    ) -> dict[str, Any] | None:
        """Find an immutable favorite before loading its source run.

        A retry can arrive after the source run was permanently removed.  In
        that case ``read_view`` cannot resolve the run, but the favorite row
        still contains the authoritative snapshot and must remain idempotent.
        Prefer explicit card identities; only use a single-row fallback when
        the request carries no identity at all.  Every lookup remains scoped
        to the caller's workspace/owner and source run.
        """

        strong_fields = ("card_key", "card_binding_id", "card_id", "capability_id")
        requested_aliases = {
            _normalize_favorite_fragment(getattr(body, field, ""))
            for field in strong_fields
            if _normalize_favorite_fragment(getattr(body, field, ""))
        }

        # A strong request identifier commonly equals the persisted canonical
        # card key.  Try each one through the indexed lookup before decoding
        # snapshot rows (``capability_id`` remains a useful fallback for older
        # records whose canonical key is the S6 binding ID).
        direct_matches: dict[str, dict[str, Any]] = {}
        for requested_key in requested_aliases:
            existing = find_favorite_record(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                card_key=requested_key,
            )
            if existing is not None:
                identity = str(existing.get("favorite_id", "") or requested_key)
                direct_matches[identity] = existing
        if len(direct_matches) == 1:
            return next(iter(direct_matches.values()))
        if len(direct_matches) > 1:
            return None

        # Older clients may retry with ``card_id``/``capability_id`` while the
        # persisted uniqueness key is a binding ID (or vice versa).  Compare
        # only explicit identity aliases so two cards with the same display
        # name cannot be collapsed accidentally.
        listing = list_favorite_records(
            scope=scope,
            owner_id=owner_id,
            run_id=run_id,
            offset=0,
            limit=200,
            search="",
            capability_type="",
        )
        items = listing.get("items", []) if isinstance(listing, Mapping) else []
        if requested_aliases:
            alias_matches: dict[str, dict[str, Any]] = {}
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, Mapping):
                    continue
                if requested_aliases.intersection(_favorite_identity_aliases(item)):
                    candidate = dict(item)
                    identity = str(
                        candidate.get("favorite_id", "")
                        or candidate.get("card_key", "")
                    )
                    alias_matches[identity] = candidate
            if len(alias_matches) == 1:
                return next(iter(alias_matches.values()))
            return None

        # Do not infer a retry target from a single row or a display name.  A
        # source run may contain same-named cards, and once it is detached the
        # server cannot prove which snapshot a weak request referred to.
        return None

    @app.post("/api/v1/favorites")
    def create_favorite(
        body: FavoriteCreateBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_user_id: str = Header(default="", alias="X-User-ID"),
    ) -> JSONResponse:
        """Create an idempotent immutable snapshot of an authored S6 card."""

        _require_role(x_role, {"analyst", "reviewer", "admin"})
        scope = str(body.scope or "global").strip().lower()
        if scope not in {"global", "private"}:
            raise HTTPException(status_code=422, detail="scope must be global or private")
        # Personal favorites are deliberately reserved until account
        # authentication is wired into the workbench.  Do not accept an
        # arbitrary owner_id from the browser as an impersonation shortcut.
        owner_id = _favorite_owner(scope, x_user_id)
        if scope == "private":
            raise HTTPException(
                status_code=403,
                detail="private favorites are reserved for authenticated accounts",
            )
        run_id = str(body.run_id or "").strip()

        # Resolve an idempotent retry before reading the source run.  Favorite
        # snapshots intentionally survive permanent run deletion, so a retry
        # after a network timeout must return the existing row rather than a
        # misleading 404 for the now-detached source.
        retry_existing = (
            _find_favorite_for_retry(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                body=body,
            )
            if _is_safe_run_id(run_id)
            else None
        )
        if retry_existing is not None:
            payload = {
                "favorite": retry_existing,
                **retry_existing,
                "created": False,
                "idempotent": True,
            }
            return JSONResponse(status_code=200, content=payload)

        try:
            view = read_view(run_id)
        except (KeyError, NoResultFound, RunNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        try:
            rows = get_capabilities(run_id, x_role="analyst")
        except HTTPException:
            raise
        if not isinstance(rows, list):
            rows = []
        requested = {
            _normalize_favorite_fragment(value)
            for value in (
                body.card_key,
                body.card_binding_id,
                body.card_id,
                body.capability_id,
                body.capability_name,
            )
            if _normalize_favorite_fragment(value)
        }
        candidates = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and (
                not requested
                or requested.intersection(_favorite_card_aliases(row))
            )
        ]
        if not requested and len(rows) == 1:
            candidates = [rows[0]]
        if not candidates:
            raise HTTPException(
                status_code=404,
                detail="capability card not found in the source run",
            )
        if len(candidates) > 1:
            raise HTTPException(
                status_code=422,
                detail="card identifier is ambiguous; provide card_binding_id or capability_id",
            )
        card = dict(candidates[0])
        eligible, reason = _favorite_portrait_eligibility(card)
        if not eligible:
            raise HTTPException(status_code=422, detail=reason)
        # Older artifacts may carry a complete labeled portrait string but no
        # structured ``capability_portrait_modules`` map.  Materialize the
        # five governed columns in the stored snapshot so every favorite is
        # independently renderable after its source run disappears.
        required_module_keys = [key for key, _ in CAPABILITY_PORTRAIT_MODULES]
        raw_modules = card.get("capability_portrait_modules")
        parsed_modules = parse_capability_portrait_modules(
            card.get("deep_capability_portrait") or card.get("capability_image")
        )
        if isinstance(raw_modules, Mapping):
            merged_modules = {
                **parsed_modules,
                **{
                    str(key): value
                    for key, value in raw_modules.items()
                    if str(value or "").strip()
                },
            }
        else:
            merged_modules = parsed_modules
        if all(str(merged_modules.get(key, "") or "").strip() for key in required_module_keys):
            normalized_modules = normalize_capability_portrait_modules(
                merged_modules,
                allow_structured_salvage=True,
            )
            card["capability_portrait_modules"] = normalized_modules
            card["portrait_module_character_counts"] = capability_portrait_module_lengths(
                normalized_modules
            )
            assembled = assemble_capability_portrait_modules(
                {
                    **normalized_modules,
                    "capability_classification": card.get(
                        "capability_classification", {}
                    ),
                }
            )
            if assembled:
                card["deep_capability_portrait"] = assembled
                card["capability_image"] = assembled
        card_key = _favorite_card_key(card)
        if not card_key:
            raise HTTPException(status_code=422, detail="capability card has no stable identity")
        card_binding_id = str(card.get("card_binding_id", "")).strip()
        capability_id = str(
            card.get("capability_id") or card.get("card_id") or ""
        ).strip()
        # The source row is already normalized by get_capabilities, so storing
        # it verbatim gives the favorites page a complete, source-independent
        # five-module snapshot.  Add only non-authoritative bookkeeping keys.
        snapshot = dict(card)
        snapshot["favorite_card_key"] = card_key
        snapshot["favorite_snapshot_version"] = "1"
        existing = find_favorite_record(
            scope=scope,
            owner_id=owner_id,
            run_id=run_id,
            card_key=card_key,
        )
        if existing is None:
            # A legacy client may have posted capability_id before the S6
            # binding id was materialized. Treat a matching alias in the same
            # run as the same favorite rather than creating a second row when
            # the artifact later gains its canonical binding.
            all_existing = list_favorite_records(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                offset=0,
                limit=200,
                search="",
                capability_type="",
            ).get("items", [])
            aliases = _favorite_identity_aliases(card)
            existing = next(
                (
                    dict(item)
                    for item in all_existing
                    if isinstance(item, Mapping)
                    and str(item.get("run_id", "")) == run_id
                    and aliases.intersection(_favorite_identity_aliases(item))
                ),
                None,
            )
        if existing is not None:
            payload = {
                "favorite": existing,
                **existing,
                "created": False,
                "idempotent": True,
            }
            return JSONResponse(status_code=200, content=payload)
        try:
            saved, created = save_favorite_record(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                card_key=card_key,
                card_binding_id=card_binding_id,
                capability_id=capability_id,
                snapshot=snapshot,
                display_name="",
                note="",
                tags=[],
                source_topic=str(view.topic or ""),
                source_status=str(view.status or ""),
                source_deleted=False,
            )
        except (IntegrityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload = {
            "favorite": saved,
            **saved,
            "created": bool(created),
            "idempotent": not created,
        }
        return JSONResponse(status_code=201 if created else 200, content=payload)

    @app.get("/api/v1/favorites")
    def list_favorites(
        scope: str = Query(default="global"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=24, ge=1, le=200),
        search: str = Query(default=""),
        q: str = Query(default=""),
        name: str = Query(default=""),
        capability_type: str = Query(default=""),
        card_type: str = Query(default=""),
        type: str = Query(default=""),
        page: int = Query(default=0, ge=0),
        page_size: int | None = Query(default=None, ge=1, le=200),
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_user_id: str = Header(default="", alias="X-User-ID"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        scope = str(scope or "global").strip().lower()
        if scope not in {"global", "private"}:
            raise HTTPException(status_code=422, detail="scope must be global or private")
        owner_id = _favorite_owner(scope, x_user_id)
        if scope == "private":
            raise HTTPException(
                status_code=403,
                detail="private favorites are reserved for authenticated accounts",
            )
        if page_size is not None:
            limit = page_size
            # ``page`` is zero-based for consistency with offset; when callers
            # provide an explicit offset it remains authoritative.
            if offset == 0 and page:
                offset = page * page_size
        query = str(search or q or name or "").strip()
        type_filter = str(capability_type or card_type or type or "").strip()
        result = list_favorite_records(
            scope=scope,
            owner_id=owner_id,
            offset=offset,
            limit=limit,
            search=query,
            capability_type=type_filter,
        )
        # ``favorites`` is a compatibility alias for clients that predate the
        # paged ``items`` envelope; both contain the same complete snapshots.
        result["favorites"] = result.get("items", [])
        result["scope"] = scope
        return result

    def _check_favorite_mutation_access(
        existing: Mapping[str, Any],
        *,
        x_role: str,
        x_user_id: str,
        require_admin: bool = False,
    ) -> None:
        scope = str(existing.get("scope", "global")).strip().lower()
        if scope == "global" and require_admin and x_role != "admin":
            raise HTTPException(
                status_code=403,
                detail="only admin can delete public favorites",
            )
        if scope == "private":
            owner_id = str(x_user_id or "").strip()
            if not owner_id or owner_id != str(existing.get("owner_id", "")):
                raise HTTPException(status_code=403, detail="favorite owner mismatch")

    @app.get("/api/v1/favorites/{favorite_id}")
    def get_favorite(
        favorite_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_user_id: str = Header(default="", alias="X-User-ID"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        existing = get_favorite_record(favorite_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="favorite not found")
        scope = str(existing.get("scope", "global")).strip().lower()
        if scope == "private":
            owner_id = str(x_user_id or "").strip()
            if not owner_id or owner_id != str(existing.get("owner_id", "")):
                raise HTTPException(status_code=403, detail="favorite owner mismatch")
        return {"favorite": existing, **existing}

    @app.patch("/api/v1/favorites/{favorite_id}")
    @app.put("/api/v1/favorites/{favorite_id}")
    def update_favorite(
        favorite_id: str,
        body: FavoriteUpdateBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_user_id: str = Header(default="", alias="X-User-ID"),
    ) -> dict[str, Any]:
        """Edit presentation metadata without mutating the capability snapshot."""

        _require_role(x_role, {"analyst", "reviewer", "admin"})
        existing = get_favorite_record(favorite_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="favorite not found")
        _check_favorite_mutation_access(
            existing,
            x_role=x_role,
            x_user_id=x_user_id,
        )
        fields_set = set(getattr(body, "model_fields_set", set()))
        if not fields_set:
            raise HTTPException(
                status_code=422,
                detail="at least one editable favorite field is required",
            )
        display_name = (
            body.display_name
            if "display_name" in fields_set
            else body.name
            if "name" in fields_set
            else body.title
            if "title" in fields_set
            else None
        )
        note = (
            body.note
            if "note" in fields_set
            else body.memo
            if "memo" in fields_set
            else None
        )
        tags = body.tags if "tags" in fields_set else None
        display_name_present = bool({"display_name", "name", "title"} & fields_set)
        note_present = bool({"note", "memo"} & fields_set)
        updated = update_favorite_record(
            favorite_id,
            display_name=(
                None
                if not display_name_present
                else ""
                if display_name is None
                else " ".join(str(display_name).split()).strip()[:400]
            ),
            note=(
                None
                if not note_present
                else ""
                if note is None
                else str(note).strip()[:4000]
            ),
            tags=(
                None
                if "tags" not in fields_set
                else _normalize_favorite_tags(tags)
            ),
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="favorite not found")
        return {
            "favorite": updated,
            **updated,
            "updated": True,
        }

    @app.delete("/api/v1/favorites/{favorite_id}")
    def delete_favorite(
        favorite_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_user_id: str = Header(default="", alias="X-User-ID"),
    ) -> dict[str, Any]:
        _require_role(x_role, {"analyst", "reviewer", "admin"})
        existing = get_favorite_record(favorite_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="favorite not found")
        _check_favorite_mutation_access(
            existing,
            x_role=x_role,
            x_user_id=x_user_id,
            require_admin=True,
        )
        removed = delete_favorite_record(favorite_id)
        if removed is None:
            raise HTTPException(status_code=404, detail="favorite not found")
        return {
            "deleted": True,
            "favorite_id": str(favorite_id),
            "favorite": removed,
        }

    @app.get("/api/v1/runs/{run_id}/expert-feedback")
    def get_expert_feedback(
        run_id: str,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
    ) -> dict:
        """Return task-scoped expert feedback and the downstream learning summary."""

        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        root = _resolve_run_root(output_root, run_id, getattr(view, "result", {}))
        items = load_run_feedback(root)
        scope = _effective_evolution_scope(
            body={
                "tenant_id": getattr(view, "tenant_id", ""),
                "workspace_id": getattr(view, "workspace_id", ""),
                "project_id": getattr(view, "project_id", ""),
                "profile_id": getattr(view, "profile_id", ""),
                "stage_scope": getattr(view, "stage_scope", []),
            }
        )
        run_route = str(
            (getattr(view, "result", {}) or {}).get("route", "")
            if isinstance(getattr(view, "result", {}), Mapping)
            else ""
        ).strip() or str(getattr(view, "research_route", "") or "").strip()
        request_scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        # The run itself is the authorization boundary.  A caller may read a
        # scoped run only from the same scope; legacy unscoped artifacts stay
        # readable by legacy clients that provide no scope headers.
        if not _evolution_scope_access(
            {
                "tenant_id": scope["tenant_id"],
                "workspace_id": scope["workspace_id"],
                "project_id": scope["project_id"],
                "profile_id": scope["profile_id"],
                "route": run_route,
                "stage_scope": scope["stage_scope"],
            },
            request_scope,
            role=x_role,
        ):
            raise HTTPException(status_code=403, detail="evolution scope mismatch")
        routed_agents = sorted(
            {
                str(agent_id).upper().strip()
                for item in items
                if isinstance(item, Mapping)
                for agent_id in (
                    item.get("target_agent_ids", [])
                    if isinstance(item.get("target_agent_ids", []), (list, tuple))
                    else []
                )
                if str(agent_id).strip()
            }
        )
        return {
            "run_id": run_id,
            "items": items,
            "learning_summary": {
                "target_agents": routed_agents,
                "available_target_agents": list(ALL_AGENT_IDS),
                "routing": "expert_feedback_memory",
                "routing_mode": "selective_memory",
                "future_task_memory_count": len(
                    load_feedback_knowledge(
                        output_root,
                        view.topic,
                        profile_id=scope["profile_id"] or None,
                        tenant_id=scope["tenant_id"] or None,
                        workspace_id=scope["workspace_id"] or None,
                        project_id=scope["project_id"] or None,
                        route=run_route or None,
                        stage_scope=scope["stage_scope"] or None,
                    )
                ),
                "scope": scope,
                "status": "available",
            },
        }

    @app.get("/api/v1/expert-feedback")
    def get_expert_feedback_index(
        limit: int = 100,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(default="", alias="X-Evolution-Stage-Scope"),
        x_evolution_cross_scope: str = Header(default="", alias="X-Evolution-Cross-Scope"),
    ) -> dict:
        """Developer/auditor view of the cross-task review memory index."""

        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        scope = _scope_request(
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            route=x_research_route,
            stage_scope=x_evolution_stage_scope,
        )
        cross_scope = x_role == "admin" and _cross_scope_requested(x_evolution_cross_scope)
        rows = [
            row for row in load_feedback_index(output_root)
            if _evolution_scope_access(row, scope, role=x_role, cross_scope=cross_scope)
        ]
        bounded_limit = max(1, min(int(limit), 500))
        payload = {
            "items": rows[-bounded_limit:],
            "count": len(rows),
        }
        if _scope_is_supplied(scope) or cross_scope:
            payload.update({"scope": scope, "cross_scope": cross_scope})
        return payload

    @app.post("/api/v1/runs/{run_id}/expert-feedback", status_code=201)
    def create_expert_feedback(
        run_id: str,
        body: CapabilityFeedbackBody,
        x_role: str = Header(default="analyst", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(
            default="", alias="X-Evolution-Stage-Scope"
        ),
    ) -> dict:
        """Store a human review and publish a bounded learning signal."""

        _require_role(x_role, {"analyst", "reviewer", "admin"})
        # Feedback must remain available for completed artifact-only runs.
        # Those runs are intentionally discoverable through ``read_view`` even
        # when their lifecycle row is no longer present in the application DB.
        try:
            view = read_view(run_id)
        except (KeyError, NoResultFound, RunNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        root = _resolve_run_root(output_root, run_id, getattr(view, "result", {}))
        if root is None or not root.is_dir() or root.is_symlink():
            raise HTTPException(status_code=404, detail="run output not found")
        run_scope = _effective_evolution_scope(
            body={
                "tenant_id": getattr(view, "tenant_id", ""),
                "workspace_id": getattr(view, "workspace_id", ""),
                "project_id": getattr(view, "project_id", ""),
                "profile_id": getattr(view, "profile_id", ""),
                "stage_scope": getattr(view, "stage_scope", []),
            }
        )
        run_route = str(
            (getattr(view, "result", {}) or {}).get("route", "")
            if isinstance(getattr(view, "result", {}), Mapping)
            else ""
        ).strip() or str(getattr(view, "research_route", "") or "").strip()
        if x_research_route and run_route and _bounded_scope_id(x_research_route, limit=120) != _bounded_scope_id(run_route, limit=120):
            raise HTTPException(status_code=403, detail="route scope mismatch")
        requested_scope = _effective_evolution_scope(
            body=body.model_dump(mode="json"),
            tenant_id=x_tenant_id,
            workspace_id=x_workspace_id,
            project_id=x_project_id,
            profile_id=x_profile_id,
            stage_scope=x_evolution_stage_scope,
        )
        # A feedback submission is attached to its run's immutable scope.  A
        # non-empty request header/body may only narrow stage scope; it may
        # not relabel a run as belonging to another tenant/workspace/project.
        for key in ("tenant_id", "workspace_id", "project_id", "profile_id"):
            run_value = str(run_scope.get(key, ""))
            requested_value = str(requested_scope.get(key, ""))
            if run_value and requested_value and run_value != requested_value:
                raise HTTPException(status_code=403, detail=f"{key} scope mismatch")
            if run_value and not requested_value:
                requested_scope[key] = run_value
        if run_scope["stage_scope"]:
            if requested_scope["stage_scope"]:
                requested_scope["stage_scope"] = [
                    stage
                    for stage in requested_scope["stage_scope"]
                    if stage in run_scope["stage_scope"]
                ]
                if not requested_scope["stage_scope"]:
                    raise HTTPException(status_code=403, detail="stage_scope mismatch")
            else:
                requested_scope["stage_scope"] = list(run_scope["stage_scope"])
        try:
            feedback = normalize_feedback(
                run_id=run_id,
                capability_id=body.capability_id,
                capability_name=body.capability_name,
                comment=body.comment,
                important_information=body.important_information,
                verdict=body.verdict,
                rating=body.rating,
                dimensions=body.dimensions,
                target_agent_ids=body.target_agent_ids,
                stage_scope=requested_scope["stage_scope"],
                reviewer_name=body.reviewer_name,
                reviewer_role=body.reviewer_role,
                profile_id=requested_scope["profile_id"],
                tenant_id=requested_scope["tenant_id"],
                workspace_id=requested_scope["workspace_id"],
                project_id=requested_scope["project_id"],
                route=run_route,
            )
            saved = append_feedback(run_root=root, output_root=output_root, feedback=feedback)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            service.publish_runtime_event(
                run_id,
                "expert_feedback_submitted",
                {
                    "feedback_id": saved["feedback_id"],
                    "capability_id": saved["capability_id"],
                    "capability_name": saved["capability_name"],
                    "verdict": saved["verdict"],
                    "rating": saved["rating"],
                    "target_agent_ids": saved["target_agent_ids"],
                    "important_information_present": bool(saved["important_information"]),
                    "reviewer_role": saved["reviewer_role"],
                },
            )
        except Exception:
            # The feedback file and cross-task memory index are the source of
            # truth. A telemetry backend can be unavailable (for example when
            # an artifact-only historical task has no DB row); that must not
            # make an already persisted reviewer submission look failed.
            pass
        return {
            "feedback": saved,
            "learning_summary": {
                "target_agents": saved["target_agent_ids"],
                "routing": saved.get("memory_processor", "expert_feedback_memory"),
                "learning_signal": saved.get("learning_signal", ""),
                "future_task_memory_count": len(
                    load_feedback_knowledge(
                        output_root,
                        view.topic,
                        profile_id=requested_scope["profile_id"] or None,
                        tenant_id=requested_scope["tenant_id"] or None,
                        workspace_id=requested_scope["workspace_id"] or None,
                        project_id=requested_scope["project_id"] or None,
                        route=run_route or None,
                        stage_scope=requested_scope["stage_scope"] or None,
                    )
                ),
                "scope": requested_scope,
                "status": (
                    "merged_with_existing_memory"
                    if saved.get("learning_status") == "deduplicated"
                    else "queued_for_future_tasks"
                ),
            },
        }

    @app.post("/api/v1/expert-feedback/{feedback_id}/effect")
    def evaluate_expert_feedback(
        feedback_id: str,
        body: EvolutionEffectBody,
        x_role: str = Header(default="reviewer", alias="X-Role"),
        x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
        x_workspace_id: str = Header(default="", alias="X-Workspace-ID"),
        x_project_id: str = Header(default="", alias="X-Project-ID"),
        x_profile_id: str = Header(default="", alias="X-Profile-ID"),
        x_research_route: str = Header(default="", alias="X-Research-Route"),
        x_evolution_stage_scope: str = Header(
            default="", alias="X-Evolution-Stage-Scope"
        ),
    ) -> dict:
        """Promote feedback only after explicit replay/adjudication evidence."""
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        try:
            rows = load_feedback_index(output_root)
            target = next((row for row in rows if row.get("feedback_id") == feedback_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="feedback not found")
            request_scope = _scope_request(
                tenant_id=x_tenant_id,
                workspace_id=x_workspace_id,
                project_id=x_project_id,
                profile_id=x_profile_id,
                route=x_research_route,
                stage_scope=x_evolution_stage_scope,
            )
            if not _evolution_scope_access(target, request_scope, role=x_role, write=True):
                raise HTTPException(status_code=403, detail="evolution scope mismatch")
            saved = update_feedback_effect_status(
                output_root=output_root,
                feedback_id=feedback_id,
                effect_status=body.effect_status,
                # Keep authorization (X-Role) separate from evidence
                # attribution.  An explicit evaluator id is required by the
                # domain transition guard and must not be silently defaulted
                # to the caller's role.
                evaluator_id=body.evaluator_id,
                evaluation_id=body.evaluation_id,
                reason=body.reason,
                utility_delta=body.metrics.get("utility_delta") if body.metrics else None,
                _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
            )
        except HTTPException:
            raise
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"feedback": saved}

    @app.get("/api/v1/runs/{run_id}/domain/{object_type}")
    def get_domain_objects(run_id: str, object_type: str, x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        if _is_historical_snapshot(read_view(run_id)):
            return []
        allowed = {
            "EvidenceCard",
            "BaselineFindingPacket",
            "WinningMechanismInput",
            "WinningKnowledgeProjection",
            "WinningReasoningNode",
            "WinningMechanismStageOutput",
            "RecallRequest",
            "AuditResult",
        }
        if object_type not in allowed:
            raise HTTPException(status_code=404, detail="domain object type not exposed")
        return [row["payload"] for row in _read_jsonl(service, output_root, run_id, "domain.jsonl") if row.get("type") == object_type]

    @app.get("/api/v1/runs/{run_id}/winning-mechanism")
    def get_winning_mechanism(run_id: str, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        if _is_historical_snapshot(view):
            return {
                "inputs": [],
                "resources": [],
                "reasoning_nodes": [],
                "stages": [],
                "recalls": [],
                "workflow": _interaction_workflow_summary(interaction_rows(run_id, view), view),
                "historical_snapshot": True,
                "message": "原始制胜机理产物未随恢复快照保存。",
            }
        grouped = {
            "inputs": [],
            "resources": [],
            "reasoning_nodes": [],
            "stages": [],
            "recalls": [],
        }
        mapping = {
            "WinningMechanismInput": "inputs",
            "WinningKnowledgeProjection": "resources",
            "WinningReasoningNode": "reasoning_nodes",
            "WinningMechanismStageOutput": "stages",
            "RecallRequest": "recalls",
        }
        for row in _read_jsonl(service, output_root, run_id, "domain.jsonl"):
            target = mapping.get(row.get("type"))
            if target:
                grouped[target].append(row.get("payload", {}))
        grouped["reasoning_nodes"].sort(key=lambda item: (item.get("step", 0), item.get("created_at", "")))
        grouped["workflow"] = _interaction_workflow_summary(
            interaction_rows(run_id, view),
            view,
        )
        try:
            summary = _read_json(service, output_root, run_id, "round_summary.json")
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            summary = {}
        grouped["swarm"] = (
            dict(summary.get("winning_swarm", {}))
            if isinstance(summary, dict)
            and isinstance(summary.get("winning_swarm", {}), dict)
            else {}
        )
        return grouped

    @app.get("/api/v1/runs/{run_id}/trace")
    def get_trace(run_id: str, x_role: str = Header(default="auditor", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"auditor", "admin"})
        if _is_historical_snapshot(read_view(run_id)):
            return []
        return _read_jsonl(service, output_root, run_id, "trace.jsonl")

    @app.get("/api/v1/runs/{run_id}/interactions")
    def get_interactions(
        run_id: str,
        compact: bool = False,
        x_role: str = Header(default="analyst", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        rows = interaction_rows(run_id, view)
        visible_rows = _compact_interactions(rows) if compact else rows
        workflow = _interaction_workflow_summary(rows, view)
        return {
            "run_id": run_id,
            "agents": _interaction_agents_with_runtime(
                interaction_agents,
                rows,
            ),
            "events": visible_rows,
            "workflow": workflow,
            "counts": {
                "events": len(rows),
                "visible_events": len(visible_rows),
                "active_agents": len(workflow["active_agent_ids"]),
                "tool_calls": sum(item["event_type"] == "tool_call" for item in rows),
                "tool_results": sum(item["event_type"] == "tool_result" for item in rows),
                "savepoints": sum(item["event_type"] == "savepoint" for item in rows),
            },
        }

    @app.get("/api/v1/runs/{run_id}/report", response_class=PlainTextResponse)
    def get_report(run_id: str, x_role: str = Header(default="reviewer", alias="X-Role")) -> str:
        # The report is a read-only research artifact.  Analysts already have
        # access to the evidence, winning-mechanism and capability projections
        # that make up the report workspace, and the web client consequently
        # requests this endpoint with ``X-Role: analyst``.  Keep reviewer and
        # auditor access for exports/operations while allowing the analyst UI
        # to render the same immutable report body.
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        view = read_view(run_id)
        if _is_historical_snapshot(view):
            return _historical_snapshot_report(view)
        report_path = _preferred_report_path(_run_root(service, output_root, run_id))
        if report_path is None:
            raise HTTPException(status_code=404, detail="run output not found")
        return _normalize_report_title_for_display(
            report_path.read_text(encoding="utf-8"), view.topic
        )

    @app.get("/api/v1/runs/{run_id}/deliverables")
    def get_deliverables(
        run_id: str,
        x_role: str = Header(default="reviewer", alias="X-Role"),
    ) -> dict:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        branch_deliverables = _read_json(service, output_root, run_id, "branch_deliverables.json")
        payload = {"branch_deliverables": branch_deliverables}
        if str(branch_deliverables.get("branch", "")) == "B":
            payload.update(
                {
                    "demand_cards": _read_json(service, output_root, run_id, "demand_cards.json"),
                    "capability_panorama": _read_json(
                        service, output_root, run_id, "capability_panorama.json"
                    ),
                    "reasoning_traceability": _read_json(
                        service, output_root, run_id, "reasoning_traceability.json"
                    ),
                }
            )
        return payload

    @app.get("/api/v1/runs/{run_id}/manifest")
    def get_manifest(run_id: str, x_role: str = Header(default="auditor", alias="X-Role")) -> dict:
        _require_role(x_role, {"auditor", "admin"})
        return _read_json(service, output_root, run_id, "delivery-manifest.json")

    @app.get("/api/v1/runs/{run_id}/artifacts/{artifact_name}")
    def get_artifact(run_id: str, artifact_name: str, x_role: str = Header(default="reviewer", alias="X-Role")) -> FileResponse:
        _require_role(x_role, {"reviewer", "auditor", "admin"})
        if Path(artifact_name).name != artifact_name:
            raise HTTPException(status_code=400, detail="invalid artifact name")
        path = _run_file(service, output_root, run_id, f"artifacts/{artifact_name}")
        return FileResponse(path)

    # Reattach durable deep jobs when this API process is (re)started.  The
    # eager call covers embedders/tests that instantiate ``TestClient``
    # without entering its lifespan context; the startup hook covers ASGI
    # servers that defer work until application startup.  The repository-side
    # conditional claim keeps the two invocations idempotent.
    try:
        _recover_deep_jobs()
    except Exception:
        # Recovery is best effort at app construction.  A later startup hook
        # or an explicit retry can reconcile a temporarily unavailable DB;
        # never prevent the main API from serving formal run artifacts.
        pass
    # FastAPI exposes startup handlers through the underlying Starlette
    # router; using it directly keeps compatibility with the FastAPI version
    # bundled in the desktop runtime (which does not expose
    # ``add_event_handler`` on the app object).
    app.router.on_startup.append(_recover_deep_jobs)
    return app


def _compact_interactions(rows: list[dict], limit: int = 80) -> list[dict]:
    important = [
        row for row in rows
        if str(row.get("event_type", "")) in _KEY_INTERACTION_EVENT_TYPES
    ]
    selected = important or rows[-min(limit, len(rows)):]
    if len(selected) <= limit:
        return selected
    head_count = min(12, limit // 4)
    return [*selected[:head_count], *selected[-(limit - head_count):]]


def _interaction_workflow_summary(rows: list[dict], view: object) -> dict:
    started = next(
        (row for row in rows if row.get("event_type") == "run_started"),
        {},
    )
    started_details = (
        dict(started.get("details", {}))
        if isinstance(started.get("details"), dict)
        else {}
    )
    blueprint = (
        dict(started_details.get("discovery_blueprint", {}))
        if isinstance(started_details.get("discovery_blueprint"), dict)
        else {}
    )
    meta_events = [
        row for row in rows
        if row.get("event_type") == "discovery_meta_loop_evaluated"
    ]
    meta_details = (
        dict(meta_events[-1].get("details", {}))
        if meta_events and isinstance(meta_events[-1].get("details"), dict)
        else {}
    )
    execution = getattr(view, "execution", {})
    execution = dict(execution) if isinstance(execution, dict) else {}
    l4_step_overrides: list[dict] = []
    for meta_event in meta_events:
        details = meta_event.get("details", {})
        if not isinstance(details, dict):
            continue
        raw_overrides = details.get("step_mode_overrides", [])
        if not isinstance(raw_overrides, list):
            continue
        l4_step_overrides.extend(
            dict(item) for item in raw_overrides if isinstance(item, dict)
        )
    primary_branch = str(
        meta_details.get("primary_branch")
        or blueprint.get("primary_branch")
        or getattr(view, "discovery_branch", "")
    )
    if primary_branch not in BRANCH_BLUEPRINTS:
        primary_branch = {
            "new_winning_mechanism": "A",
            "traditional_gap": "B",
            "war_case_learning": "C",
        }.get(str(getattr(view, "research_route", "")), "")
    mode_branch = primary_branch or "B"
    adaptive_modes = blueprint.get("adaptive_winning_step_modes", {})
    pre_l4_modes = winning_step_modes(
        mode_branch,
        research_route=str(getattr(view, "research_route", "")),
        adaptive_modes=(
            adaptive_modes if isinstance(adaptive_modes, dict) else None
        ),
    )
    resolved_modes = winning_step_modes(
        mode_branch,
        research_route=str(getattr(view, "research_route", "")),
        adaptive_modes=(
            adaptive_modes if isinstance(adaptive_modes, dict) else None
        ),
        l4_overrides=l4_step_overrides,
    )
    execution_profile_id = str(
        getattr(view, "execution_profile_id", "") or "legacy_v1"
    )
    # A terminal completed/approved run is authoritative.  Older or duplicate
    # workers may append a late ``run_failed``/``report_model_failed`` event
    # after the Reporter has already persisted its report; that stale event
    # must not make the replay banner claim that delivery failed.
    view_result = getattr(view, "result", {})
    view_result = view_result if isinstance(view_result, dict) else {}
    run_has_complete_report = (
        str(getattr(view, "status", "")).lower() == "completed"
        and (
        str(view_result.get("audit_status", "")).lower() in {"approved", "passed", "limited", "pending"}
            or bool(view_result.get("report_available"))
        )
    )
    is_dynamic_profile = execution_profile_id == "winning_swarm_dynamic_v2"
    latest_steps: dict[int, dict] = {
        int(definition["step"]): {
            "step": int(definition["step"]),
            "agent_id": str(definition["agent_id"]),
            "label": str(definition["label"]),
            "planned_execution_mode": resolved_modes[int(definition["step"])],
            "execution_mode": (
                "dynamic"
                if is_dynamic_profile
                else resolved_modes[int(definition["step"])]
            ),
            "status": "pending" if is_dynamic_profile else (
                "skipped"
                if resolved_modes[int(definition["step"])] == "skip"
                else "pending"
            ),
            "decision_finalized": False,
            "middle_cycle": 0,
            "result_summary": "",
            "backtrack_count": 0,
        }
        for definition in WINNING_STEP_DEFINITIONS
    }
    dynamic_agents_by_id: dict[str, dict] = {}
    swarm_member_ids: set[str] = set()
    swarm_event_seen = False
    swarm_plan_details: dict = {}
    mission_graph_projection: dict = {}
    role_contracts_by_id: dict[str, dict] = {}
    candidate_lineage_by_id: dict[str, dict] = {}
    merge_receipts_by_id: dict[str, dict] = {}
    ledger_projection: dict = {}
    portfolio_projection: dict = {}
    s6_cards_by_id: dict[str, dict] = {}
    s6_release_gate: dict = {}
    s6_authoring = {
        "started": 0,
        "completed": 0,
        "reused": 0,
        "limited": 0,
        "status": "pending",
    }

    def safe_string_list(value: object, *, limit: int = 24) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return [str(item)[:300] for item in value if str(item).strip()][:limit]

    def update_candidate(hypothesis_id: str, values: dict) -> dict:
        current = candidate_lineage_by_id.setdefault(
            hypothesis_id,
            {
                "hypothesis_id": hypothesis_id,
                "status": "created",
                "source_member_ids": [],
                "merge_targets": [],
                "receipt_ids": [],
            },
        )
        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            current[key] = value
        return current

    def append_candidate_value(
        hypothesis_id: str,
        key: str,
        value: object,
        *,
        limit: int = 24,
    ) -> None:
        if not hypothesis_id or value in (None, ""):
            return
        current = update_candidate(hypothesis_id, {})
        values = current.setdefault(key, [])
        if not isinstance(values, list):
            values = []
            current[key] = values
        text_value = str(value)
        if text_value not in values and len(values) < limit:
            values.append(text_value)

    def update_dynamic_agent(
        dynamic_agent_id: str,
        values: dict,
    ) -> dict:
        current = dynamic_agents_by_id.setdefault(
            dynamic_agent_id,
            {
                "agent_id": dynamic_agent_id,
                "agent_instance_id": dynamic_agent_id,
                "display_name": "动态专用 Agent",
                "status": "planned",
            },
        )
        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            current[key] = value
        return current

    for row in rows:
        event_type = str(row.get("event_type", ""))
        details = row.get("details", {})
        details = details if isinstance(details, dict) else {}
        if event_type == "swarm_planned":
            swarm_event_seen = True
            swarm_plan_details = dict(details)
            continue
        if event_type == "winning_mission_graph_planned":
            swarm_event_seen = True
            graph = details.get("graph", {})
            graph = graph if isinstance(graph, dict) else {}
            graph_id = str(details.get("graph_id") or graph.get("graph_id") or "")
            execution_profile_id = str(graph.get("execution_profile_id", ""))
            mission_graph_projection = {
                "graph_id": graph_id,
                "execution_profile_id": execution_profile_id,
                "status": str(graph.get("status", "planned")),
                "minimum_instances": details.get(
                    "minimum_instances", graph.get("minimum_instances")
                ),
                "maximum_instances": details.get(
                    "maximum_instances", graph.get("maximum_instances")
                ),
                "maximum_concurrency": details.get(
                    "maximum_concurrency", graph.get("maximum_concurrency")
                ),
                "merge_strategy": str(graph.get("merge_strategy", "")),
                "waves": [
                    safe_string_list(item, limit=16)
                    for item in graph.get("waves", [])
                    if isinstance(item, list)
                ][:6],
            }
            swarm_plan_details = {
                **swarm_plan_details,
                "policy_id": execution_profile_id or "winning_swarm_dynamic_v2",
            }
            raw_contracts = graph.get("role_contracts", [])
            if isinstance(raw_contracts, list):
                for raw_contract in raw_contracts:
                    if not isinstance(raw_contract, dict):
                        continue
                    contract_id = str(raw_contract.get("role_contract_id", ""))
                    if not contract_id:
                        continue
                    role_contracts_by_id[contract_id] = {
                        "role_contract_id": contract_id,
                        "archetype": str(raw_contract.get("archetype", "")),
                        "display_name": str(raw_contract.get("display_name", "")),
                        "role_purpose": str(raw_contract.get("purpose", ""))[:600],
                        "mission_node": str(raw_contract.get("mission_node", "")),
                        "merge_targets": safe_string_list(
                            raw_contract.get("merge_targets", []), limit=6
                        ),
                        "trigger_residuals": safe_string_list(
                            raw_contract.get("trigger_residuals", []), limit=8
                        ),
                        "skill_ids": safe_string_list(
                            raw_contract.get("skill_ids", []), limit=8
                        ),
                        "allow_child_spawn": False,
                        "authority_scope": str(
                            raw_contract.get("authority_scope", "bounded_analysis_only")
                        ),
                        "role_contract_version": str(
                            raw_contract.get("schema_version", "2.0")
                        ),
                    }
            raw_instances = graph.get("agent_instances", [])
            if isinstance(raw_instances, list):
                for raw_instance in raw_instances:
                    if not isinstance(raw_instance, dict):
                        continue
                    instance_id = str(
                        raw_instance.get("instance_id")
                        or raw_instance.get("agent_instance_id")
                        or ""
                    ).strip()
                    if not instance_id:
                        continue
                    swarm_member_ids.add(instance_id)
                    contract = role_contracts_by_id.get(
                        str(raw_instance.get("role_contract_id", "")), {}
                    )
                    mission_node = str(
                        raw_instance.get("mission_node")
                        or raw_instance.get("merge_target")
                        or contract.get("mission_node", "")
                    )
                    update_dynamic_agent(
                        instance_id,
                        {
                            "task_id": instance_id,
                            "agent_instance_id": instance_id,
                            "display_name": str(
                                raw_instance.get("display_name")
                                or contract.get("display_name")
                                or "动态专用 Agent"
                            ),
                            "archetype": str(
                                raw_instance.get("archetype")
                                or contract.get("archetype", "")
                            ),
                            "role_purpose": str(contract.get("role_purpose", "")),
                            "role_contract_id": str(
                                raw_instance.get("role_contract_id", "")
                            ),
                            "role_contract_version": str(
                                contract.get("role_contract_version", "2.0")
                            ),
                            "mission_node": mission_node,
                            "merge_target": str(
                                raw_instance.get("merge_target") or mission_node
                            ),
                            "wave": raw_instance.get("wave", 0),
                            "hypothesis_id": str(
                                raw_instance.get("hypothesis_id", "")
                            ),
                            "depends_on": safe_string_list(
                                raw_instance.get("depends_on", []), limit=16
                            ),
                            "trigger_residuals": safe_string_list(
                                raw_instance.get(
                                    "trigger_residuals",
                                    contract.get("trigger_residuals", []),
                                ),
                                limit=8,
                            ),
                            "skill_ids": safe_string_list(
                                contract.get("skill_ids", []), limit=8
                            ),
                            "execution_backend": str(
                                raw_instance.get(
                                    "execution_backend", "independent_codex_cli"
                                )
                            ),
                            "context_isolation": str(
                                raw_instance.get("context_isolation", "ephemeral")
                            ),
                            "allow_child_spawn": False,
                            "expected_quality_gain": raw_instance.get(
                                "expected_quality_gain"
                            ),
                            "status": "planned",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            continue
        if event_type == "winning_s6_card_authoring_started":
            swarm_event_seen = True
            s6_authoring["started"] += 1
            s6_authoring["status"] = "authoring"
            continue
        if event_type in {
            "winning_s6_card_authoring_completed",
            "winning_s6_card_authoring_reused",
            "winning_s6_card_authoring_limited",
            "winning_s6_card_authoring_rescued",
        }:
            swarm_event_seen = True
            counter = {
                "winning_s6_card_authoring_completed": "completed",
                "winning_s6_card_authoring_reused": "reused",
                "winning_s6_card_authoring_limited": "limited",
                "winning_s6_card_authoring_rescued": "completed",
            }[event_type]
            s6_authoring[counter] += 1
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            if event_type == "winning_s6_card_authoring_limited" and hypothesis_id:
                update_candidate(
                    hypothesis_id,
                    {
                        "status": "selected_limited",
                        "selection_status": "selected_limited",
                        "s6_eligible": True,
                        "s6_authoring_failed": True,
                        "s6_failure_type": str(details.get("failure_type", "")),
                        "selection_reason": (
                            "S6独立成稿调用受限；仅保留入选身份和证据供定向重跑，当前不生成能力画像。"
                        ),
                    },
                )
            direction = details.get("direction", {})
            if isinstance(direction, dict) and direction:
                card_id = str(
                    direction.get("hypothesis_id")
                    or details.get("hypothesis_id")
                    or direction.get("name")
                    or f"s6-card-{details.get('card_position', len(s6_cards_by_id) + 1)}"
                ).strip()
                if card_id:
                    s6_cards_by_id[card_id] = dict(direction)
            s6_authoring["status"] = (
                "limited" if event_type.endswith("limited") else "authoring"
            )
            continue
        if event_type == "winning_s6_release_gate_evaluated":
            swarm_event_seen = True
            authored_cards = details.get("authored_cards", [])
            if isinstance(authored_cards, list):
                released_cards: dict[str, dict] = {}
                for index, item in enumerate(authored_cards, start=1):
                    if not isinstance(item, dict):
                        continue
                    card_id = str(
                        item.get("hypothesis_id")
                        or item.get("name")
                        or f"s6-release-card-{index}"
                    ).strip()
                    if card_id:
                        released_cards[card_id] = dict(item)
                if released_cards:
                    s6_cards_by_id = released_cards
            s6_release_gate = {
                "passed": details.get("passed") is True,
                "failed": details.get("failed") is True,
                "limited": details.get("limited") is True,
                "issues": safe_string_list(details.get("issues", []), limit=16),
                "warnings": safe_string_list(details.get("warnings", []), limit=16),
                "card_count": details.get("card_count", len(s6_cards_by_id)),
                "status": (
                    "limited"
                    if details.get("limited") is True
                    else "passed"
                    if details.get("passed") is True
                    else "failed"
                ),
            }
            s6_authoring["status"] = s6_release_gate["status"]
            if details.get("maximum_concurrency") is not None:
                mission_graph_projection["maximum_concurrency"] = details.get(
                    "maximum_concurrency"
                )
            if details.get("maximum_observed_concurrency") is not None:
                mission_graph_projection["maximum_observed_concurrency"] = details.get(
                    "maximum_observed_concurrency"
                )
            continue
        if event_type == "winning_s3_active_agents_materialized":
            swarm_event_seen = True
            active_ids = {
                str(value).strip()
                for value in details.get("active_instance_ids", [])
                if str(value).strip()
            }
            for instance_id, member in dynamic_agents_by_id.items():
                if (
                    str(member.get("mission_node", "")) == "S3"
                    and not str(member.get("hypothesis_id", ""))
                    and instance_id not in active_ids
                ):
                    swarm_member_ids.discard(instance_id)
                    update_dynamic_agent(
                        instance_id,
                        {
                            "status": "skipped",
                            "inactive_capacity": True,
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            mission_graph_projection["active_s3_instances"] = len(active_ids)
            mission_graph_projection["unused_s3_capacity"] = details.get(
                "unused_capacity_count", 0
            )
            continue
        if event_type == "winning_agent_instance_recruited":
            swarm_event_seen = True
            raw_contract = details.get("role_contract", {})
            raw_contract = raw_contract if isinstance(raw_contract, dict) else {}
            raw_instance = details.get("instance", {})
            raw_instance = raw_instance if isinstance(raw_instance, dict) else {}
            contract_id = str(raw_contract.get("role_contract_id", ""))
            if contract_id:
                role_contracts_by_id[contract_id] = {
                    "role_contract_id": contract_id,
                    "archetype": str(raw_contract.get("archetype", "")),
                    "display_name": str(raw_contract.get("display_name", "")),
                    "role_purpose": str(raw_contract.get("purpose", ""))[:600],
                    "mission_node": str(raw_contract.get("mission_node", "")),
                    "merge_targets": safe_string_list(
                        raw_contract.get("merge_targets", []), limit=6
                    ),
                    "trigger_residuals": safe_string_list(
                        raw_contract.get("trigger_residuals", []), limit=8
                    ),
                    "skill_ids": safe_string_list(
                        raw_contract.get("skill_ids", []), limit=8
                    ),
                    "allow_child_spawn": False,
                    "authority_scope": str(
                        raw_contract.get("authority_scope", "bounded_analysis_only")
                    ),
                    "role_contract_version": str(
                        raw_contract.get("schema_version", "2.0")
                    ),
                }
            instance_id = str(
                raw_instance.get("instance_id")
                or details.get("agent_instance_id")
                or row.get("actor", "")
            ).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                contract = role_contracts_by_id.get(contract_id, {})
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "display_name": str(
                            raw_instance.get("display_name")
                            or contract.get("display_name")
                            or "动态专用 Agent"
                        ),
                        "archetype": str(
                            raw_instance.get("archetype")
                            or contract.get("archetype", "")
                        ),
                        "role_purpose": str(contract.get("role_purpose", "")),
                        "role_contract_id": contract_id,
                        "mission_node": str(raw_instance.get("mission_node", "")),
                        "merge_target": str(raw_instance.get("merge_target", "")),
                        "hypothesis_id": str(
                            raw_instance.get("hypothesis_id")
                            or details.get("hypothesis_id", "")
                        ),
                        "depends_on": safe_string_list(
                            raw_instance.get("depends_on", []), limit=16
                        ),
                        "trigger_residuals": safe_string_list(
                            raw_instance.get("trigger_residuals", []), limit=8
                        ),
                        "wave": raw_instance.get("wave", 0),
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral",
                        "allow_child_spawn": False,
                        "recruitment_planned": True,
                        "status": "recruiting",
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type == "winning_agent_waiting":
            # Controller-level heartbeat: refresh the already-known members
            # without creating a fake "winning_swarm_controller" Agent card.
            swarm_event_seen = True
            for waiting in details.get("running_instances", []) if isinstance(details.get("running_instances", []), list) else []:
                if not isinstance(waiting, Mapping):
                    continue
                waiting_id = str(waiting.get("agent_instance_id", "")).strip()
                if not waiting_id:
                    continue
                swarm_member_ids.add(waiting_id)
                update_dynamic_agent(
                    waiting_id,
                    {
                        "agent_instance_id": waiting_id,
                        "mission_node": str(waiting.get("mission_node", "")),
                        "archetype": str(waiting.get("archetype", "")),
                        "batch": waiting.get("batch"),
                        "elapsed_seconds": waiting.get("elapsed_seconds"),
                        "status": "running",
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type in {
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
            "winning_agent_instance_failed",
            "winning_agent_instance_cancelled",
        }:
            swarm_event_seen = True
            instance_id = str(
                details.get("agent_instance_id") or row.get("actor", "")
            ).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                status = {
                    "winning_agent_instance_ready": "queued",
                    "winning_agent_session_started": "running",
                    "winning_agent_session_completed": "completed",
                    "winning_agent_instance_failed": "failed",
                    "winning_agent_instance_cancelled": "pruned",
                }[event_type]
                safe_fields = {
                    key: details.get(key)
                    for key in (
                        "task_id",
                        "agent_instance_id",
                        "display_name",
                        "archetype",
                        "role_purpose",
                        "trigger_residuals",
                        "wave",
                        "batch",
                        "hypothesis_id",
                        "merge_target",
                        "mission_node",
                        "role_contract_id",
                        "depends_on",
                        "provider_type",
                        "execution_backend",
                        "context_isolation",
                        "provider_isolation_id",
                        "process_isolation",
                        "sandbox_mode",
                        "model",
                        "runtime_profile_id",
                        "role_contract_version",
                        "skill_ids",
                        "allow_child_spawn",
                        "expected_quality_gain",
                        "session_ref",
                        "elapsed_seconds",
                        "running_instances",
                        "note",
                    )
                }
                safe_fields.update(
                    {
                        "status": status,
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    }
                )
                if event_type == "winning_agent_instance_failed":
                    safe_fields["failure_type"] = str(
                        details.get("failure_type", "execution_failed")
                    )
                if event_type == "winning_agent_instance_cancelled":
                    safe_fields["prune_reason"] = str(
                        details.get("reason", "unsatisfied_dependency")
                    )
                update_dynamic_agent(instance_id, safe_fields)
            continue
        if event_type in {
            "winning_quality_judge_recruited",
            "winning_quality_judge_started",
            "winning_quality_judge_completed",
            "winning_quality_judge_failed",
        }:
            swarm_event_seen = True
            instance_id = str(row.get("actor", "")).strip()
            if instance_id:
                swarm_member_ids.add(instance_id)
                status = {
                    "winning_quality_judge_recruited": "recruiting",
                    "winning_quality_judge_started": "running",
                    "winning_quality_judge_completed": "completed",
                    "winning_quality_judge_failed": "failed",
                }[event_type]
                role_contract = details.get("role_contract", {})
                role_contract = (
                    role_contract if isinstance(role_contract, dict) else {}
                )
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "display_name": str(
                            role_contract.get(
                                "display_name", "制胜机理质量专家评判"
                            )
                        ),
                        "archetype": "quality_expert_judge",
                        "mission_node": "convergence",
                        "merge_target": "convergence",
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral_read_only",
                        "allow_child_spawn": False,
                        "candidate_count": details.get("candidate_count"),
                        "assessed_count": details.get("assessed_count"),
                        "session_ref": str(details.get("session_ref", "")),
                        "status": status,
                        "failure_type": str(details.get("failure_type", "")),
                        "error_message": str(details.get("error_message", "")),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            continue
        if event_type == "winning_quality_judge_assessed":
            swarm_event_seen = True
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            assessment = details.get("assessment", {})
            assessment = assessment if isinstance(assessment, dict) else {}
            if hypothesis_id:
                update_candidate(
                    hypothesis_id,
                    {
                        "expert_assessment_id": str(
                            assessment.get("assessment_id", "")
                        ),
                        "expert_verdict": str(assessment.get("verdict", "")),
                        "expert_passed": assessment.get("passed") is True,
                        "expert_score": assessment.get("weighted_score"),
                        "expert_dimension_scores": dict(
                            assessment.get("dimension_scores", {})
                        )
                        if isinstance(assessment.get("dimension_scores"), dict)
                        else {},
                        "expert_rejection_reasons": safe_string_list(
                            assessment.get("rejection_reasons", []), limit=8
                        ),
                        "status": (
                            "expert_passed"
                            if assessment.get("passed") is True
                            else "expert_rejected"
                        ),
                    },
                )
            continue
        if event_type in {
            "winning_quality_repair_planned",
            "winning_quality_repair_completed",
            "winning_quality_repair_failed",
        }:
            swarm_event_seen = True
            instance_id = str(row.get("actor", "")).strip()
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            if instance_id:
                status = {
                    "winning_quality_repair_planned": "queued",
                    "winning_quality_repair_completed": "completed",
                    "winning_quality_repair_failed": "failed",
                }[event_type]
                update_dynamic_agent(
                    instance_id,
                    {
                        "agent_instance_id": instance_id,
                        "hypothesis_id": hypothesis_id,
                        "archetype": str(
                            details.get("archetype", "expert_residual_repair")
                        ),
                        "execution_backend": "independent_codex_cli",
                        "context_isolation": "ephemeral",
                        "allow_child_spawn": False,
                        "expert_assessment_id": str(
                            details.get("expert_assessment_id", "")
                        ),
                        "repair_residuals": safe_string_list(
                            details.get("residuals", []), limit=8
                        ),
                        "status": status,
                        "error_message": str(details.get("error_message", "")),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            if hypothesis_id:
                update_candidate(
                    hypothesis_id,
                    {
                        "status": (
                            "expert_repair_completed"
                            if event_type == "winning_quality_repair_completed"
                            else "expert_repair_failed"
                            if event_type == "winning_quality_repair_failed"
                            else "expert_repair_queued"
                        ),
                        "expert_repair_agent_id": instance_id,
                        "expert_repair_merge_status": str(
                            details.get("status", "")
                        ),
                    },
                )
            continue
        if event_type == "winning_candidate_branch_created":
            swarm_event_seen = True
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            actor = str(row.get("actor", "")).strip()
            if hypothesis_id:
                candidate = update_candidate(
                    hypothesis_id,
                    {
                        "status": "created",
                        "mission_node": str(details.get("mission_node", "")),
                        "score": details.get("score"),
                        "title": str(details.get("title", ""))[:300],
                        "equipment_forms": safe_string_list(
                            details.get("equipment_form", []), limit=8
                        ),
                        "primary_equipment_identity": str(
                            details.get("primary_equipment_identity", "")
                        )[:300],
                        "reference_overview": str(
                            details.get("concise_winning_summary", "")
                        )[:1800],
                        "naming_rationale": str(
                            details.get("naming_rationale", "")
                        )[:600],
                        "naming_style": str(details.get("naming_style", ""))[:120],
                        "core_disruptive_difference": str(
                            details.get("core_disruptive_difference", "")
                        )[:600],
                        "created_sequence": row.get("sequence", 0),
                    },
                )
                if actor:
                    append_candidate_value(
                        hypothesis_id, "source_member_ids", actor
                    )
                    update_dynamic_agent(
                        actor,
                        {
                            "hypothesis_id": hypothesis_id,
                            "candidate_score": candidate.get("score"),
                            "ledger_status": "candidate_created",
                        },
                    )
            continue
        if event_type == "winning_candidate_ledger_frozen":
            swarm_event_seen = True
            ledger_projection = {
                "ledger_id": str(details.get("ledger_id", "")),
                "version": details.get("ledger_version", 0),
                "candidate_count": details.get("candidate_count", 0),
                "incremental": details.get("incremental") is True,
                "status": "active",
            }
            continue
        if event_type in {
            "winning_contribution_queued",
            "winning_contribution_rejected",
            "winning_contribution_rebase_required",
            "winning_contribution_merged",
        }:
            swarm_event_seen = True
            contribution_id = str(details.get("contribution_id", "")).strip()
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            merge_target = str(details.get("merge_target", ""))
            actor = str(row.get("actor", "")).strip()
            if hypothesis_id:
                append_candidate_value(
                    hypothesis_id, "merge_targets", merge_target
                )
                if actor:
                    append_candidate_value(
                        hypothesis_id, "source_member_ids", actor
                    )
                status = {
                    "winning_contribution_queued": "contribution_queued",
                    "winning_contribution_rejected": "contribution_rejected",
                    "winning_contribution_rebase_required": "rebase_required",
                    "winning_contribution_merged": "merged",
                }[event_type]
                update_candidate(
                    hypothesis_id,
                    {
                        "status": status,
                        "ledger_version": details.get(
                            "resulting_ledger_version",
                            details.get("to_version"),
                        ),
                        "last_merge_status": details.get("status", status),
                        "rejection_reason": str(details.get("reason", "")),
                    },
                )
            if contribution_id:
                receipt_id = f"event-{contribution_id}-{row.get('sequence', 0)}"
                merge_receipts_by_id[receipt_id] = {
                    "receipt_id": receipt_id,
                    "contribution_id": contribution_id,
                    "hypothesis_id": hypothesis_id,
                    "merge_target": merge_target,
                    "status": str(details.get("status") or event_type.removeprefix("winning_contribution_")),
                    "base_ledger_version": details.get(
                        "base_ledger_version", details.get("from_version")
                    ),
                    "resulting_ledger_version": details.get(
                        "resulting_ledger_version", details.get("to_version")
                    ),
                    "reason": str(details.get("reason", "")),
                }
                append_candidate_value(
                    hypothesis_id, "receipt_ids", receipt_id
                )
            continue
        if event_type == "winning_portfolio_merge_completed":
            swarm_event_seen = True
            selected_ids = safe_string_list(
                details.get("selected_hypothesis_ids", []), limit=8
            )
            rejected_ids = safe_string_list(
                details.get("rejected_hypothesis_ids", []), limit=16
            )
            portfolio_projection = {
                "ledger_id": str(details.get("ledger_id", "")),
                "ledger_version": details.get("ledger_version", 0),
                "selected_hypothesis_ids": selected_ids,
                "rejected_hypothesis_ids": rejected_ids,
                "final_equipment_portfolio": [
                    dict(item)
                    for item in details.get("final_equipment_portfolio", [])
                    if isinstance(item, dict)
                ][:7],
                "quality_gate": (
                    dict(details.get("portfolio_quality_gate", {}))
                    if isinstance(details.get("portfolio_quality_gate"), dict)
                    else {}
                ),
                "status": "completed",
            }
            portfolio_by_id = {
                str(item.get("hypothesis_id", "")): item
                for item in portfolio_projection["final_equipment_portfolio"]
                if str(item.get("hypothesis_id", "")).strip()
            }
            summary = details.get("swarm_summary", {})
            summary = summary if isinstance(summary, dict) else {}
            raw_budget = summary.get("budget", {})
            if isinstance(raw_budget, dict):
                if raw_budget.get("maximum_concurrency") is not None:
                    mission_graph_projection["maximum_concurrency"] = raw_budget.get(
                        "maximum_concurrency"
                    )
                if raw_budget.get("maximum_observed_concurrency") is not None:
                    mission_graph_projection["maximum_observed_concurrency"] = (
                        raw_budget.get("maximum_observed_concurrency")
                    )
            raw_ledger = summary.get("hypothesis_ledger", {})
            if isinstance(raw_ledger, dict):
                ledger_projection = {
                    "ledger_id": str(raw_ledger.get("ledger_id", "")),
                    "version": raw_ledger.get("version", 0),
                    "candidate_count": len(raw_ledger.get("hypotheses", []))
                    if isinstance(raw_ledger.get("hypotheses"), list)
                    else 0,
                    "status": str(raw_ledger.get("status", "active")),
                }
                for raw_candidate in raw_ledger.get("hypotheses", []):
                    if not isinstance(raw_candidate, dict):
                        continue
                    hypothesis_id = str(raw_candidate.get("hypothesis_id", ""))
                    if not hypothesis_id:
                        continue
                    update_candidate(
                        hypothesis_id,
                        {
                            "title": str(raw_candidate.get("title", ""))[:300],
                            "status": (
                                "selected_pending_verification"
                                if hypothesis_id in selected_ids
                                and str(
                                    portfolio_by_id.get(hypothesis_id, {}).get(
                                        "verification_status", ""
                                    )
                                ) == "pending"
                                else "selected"
                                if hypothesis_id in selected_ids
                                else "rejected"
                            ),
                            "s6_eligible": hypothesis_id in selected_ids,
                            "verification_status": str(
                                portfolio_by_id.get(hypothesis_id, {}).get(
                                    "verification_status", "assessed"
                                )
                            ),
                            "confidence_limited": bool(
                                portfolio_by_id.get(hypothesis_id, {}).get(
                                    "confidence_limited", False
                                )
                            ),
                            "selection_reason": (
                                "直接作战装备身份和Query因果成立；因对象证据、成熟度或对抗边界仍需核验，"
                                "按新质性与制胜价值补入S6，画像标记为待核验。"
                                if hypothesis_id in selected_ids
                                and str(
                                    portfolio_by_id.get(hypothesis_id, {}).get(
                                        "verification_status", ""
                                    )
                                ) == "pending"
                                else "经独立Codex按对象证据、Query因果、直接作战属性、"
                                "机制独立性与组合价值完成语义评审，进入本轮 S6 容量。"
                                if hypothesis_id in selected_ids
                                else "未进入本轮 S6 容量，保留为可展开查看的参考武器。"
                            ),
                            "score": raw_candidate.get("score"),
                            "equipment_forms": safe_string_list(
                                raw_candidate.get("equipment_forms", []), limit=8
                            ),
                            "changed_confrontation_variable": str(
                                raw_candidate.get("changed_confrontation_variable", "")
                            )[:300],
                            "mechanism_chain": safe_string_list(
                                raw_candidate.get("mechanism_chain", []), limit=6
                            ),
                            "direct_military_effects": safe_string_list(
                                raw_candidate.get("direct_military_effects", []), limit=6
                            ),
                            "project_function": str(
                                raw_candidate.get("project_function", "")
                            )[:300],
                            "reference_overview": str(
                                raw_candidate.get("reference_overview", "")
                            )[:1800],
                            "novelty_delta": str(
                                raw_candidate.get("novelty_delta", "")
                            )[:300],
                            "decisive_advantage_thesis": str(
                                raw_candidate.get("decisive_advantage_thesis", "")
                            )[:300],
                            "evidence_ids": safe_string_list(
                                raw_candidate.get("evidence_ids", []), limit=16
                            ),
                            "failure_boundaries": safe_string_list(
                                raw_candidate.get("failure_boundaries", []), limit=8
                            ),
                            "validation_plan": safe_string_list(
                                raw_candidate.get("validation_plan", []), limit=8
                            ),
                        },
                    )
            for raw_receipt in summary.get("merge_receipts", []):
                if not isinstance(raw_receipt, dict):
                    continue
                receipt_id = str(raw_receipt.get("receipt_id", ""))
                if not receipt_id:
                    continue
                merge_receipts_by_id[receipt_id] = {
                    key: raw_receipt.get(key)
                    for key in (
                        "receipt_id",
                        "contribution_id",
                        "hypothesis_id",
                        "merge_target",
                        "base_ledger_version",
                        "resulting_ledger_version",
                        "status",
                        "changed_fields",
                        "conflicts",
                        "quality_delta",
                        "rebase_required",
                    )
                }
                append_candidate_value(
                    str(raw_receipt.get("hypothesis_id", "")),
                    "receipt_ids",
                    receipt_id,
                )
            selected_id_set = set(selected_ids)
            rejected_id_set = set(rejected_ids)
            for member_id, member in dynamic_agents_by_id.items():
                hypothesis_id = str(member.get("hypothesis_id", "")).strip()
                if not hypothesis_id:
                    continue
                current_status = str(member.get("status", "planned")).lower()
                if (
                    hypothesis_id in selected_id_set
                    and current_status not in {"failed", "pruned", "skipped"}
                ):
                    update_dynamic_agent(
                        member_id,
                        {
                            "status": "merged",
                            "merge_status": "accepted",
                            "portfolio_status": "selected",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
                elif hypothesis_id in rejected_id_set:
                    update_dynamic_agent(
                        member_id,
                        {
                            "status": (
                                "completed"
                                if current_status == "merged"
                                else current_status
                            ),
                            "portfolio_status": "rejected",
                            "last_event_type": event_type,
                            "last_sequence": row.get("sequence", 0),
                        },
                    )
            continue
        if event_type in {
            "winning_model_queue_started",
            "winning_model_call_started",
            "winning_model_call_progress",
            "winning_model_call_completed",
        }:
            raw_steps = details.get("steps", [details.get("step")])
            raw_steps = raw_steps if isinstance(raw_steps, list) else [raw_steps]
            for raw_step in raw_steps:
                try:
                    step = int(raw_step)
                except (TypeError, ValueError):
                    continue
                if step not in latest_steps:
                    continue
                if latest_steps[step]["status"] != "completed":
                    latest_steps[step]["status"] = "running"
                latest_steps[step].update(
                    {
                        "current_step": str(details.get("current_step", "")),
                        "current_phase": str(details.get("phase", "")),
                        "elapsed_seconds": details.get("elapsed_seconds", 0),
                        "queue_wait_seconds": details.get(
                            "queue_wait_seconds", 0
                        ),
                        "runtime_agent_id": str(row.get("actor", "")),
                    }
                )
            continue
        if event_type in {
            "specialist_recruitment_planned",
            "specialist_spawned",
            "specialist_session_started",
            "specialist_session_completed",
            "specialist_completed",
            "specialist_pruned",
        }:
            swarm_event_seen = True
            dynamic_agent_id = str(
                details.get("agent_instance_id") or row.get("actor", "")
            ).strip()
            if dynamic_agent_id:
                swarm_member_ids.add(dynamic_agent_id)
                safe_fields = {
                    key: details.get(key)
                    for key in (
                        "task_id",
                        "agent_instance_id",
                        "display_name",
                        "archetype",
                        "role_purpose",
                        "trigger_residuals",
                        "wave",
                        "batch",
                        "hypothesis_id",
                        "merge_target",
                        "provider_type",
                        "execution_backend",
                        "context_isolation",
                        "provider_isolation_id",
                        "process_isolation",
                        "sandbox_mode",
                        "model",
                        "runtime_profile_id",
                        "role_contract_version",
                        "skill_ids",
                        "allow_child_spawn",
                        "expected_quality_gain",
                        "incremental_quality",
                        "session_ref",
                        "elapsed_seconds",
                    )
                }
                if event_type in {
                    "specialist_recruitment_planned",
                    "specialist_spawned",
                }:
                    safe_fields["recruitment_planned"] = True
                status = {
                    "specialist_recruitment_planned": "planned",
                    "specialist_spawned": "recruiting",
                    "specialist_session_started": "running",
                    "specialist_session_completed": (
                        "failed"
                        if str(details.get("status", "")).lower() == "failed"
                        else "completed"
                    ),
                    "specialist_completed": "completed",
                    "specialist_pruned": "pruned",
                }[event_type]
                safe_fields["status"] = status
                safe_fields["last_event_type"] = event_type
                safe_fields["last_sequence"] = row.get("sequence", 0)
                if event_type == "specialist_pruned":
                    safe_fields["prune_reason"] = str(
                        details.get("reason", "quality_or_dependency_gate")
                    )
                update_dynamic_agent(dynamic_agent_id, safe_fields)
            continue
        if event_type in {
            "hypothesis_created",
            "hypothesis_merged",
            "hypothesis_rejected",
            "swarm_gate_evaluated",
        }:
            hypothesis_id = str(details.get("hypothesis_id", "")).strip()
            actor = str(row.get("actor", "")).strip()
            if event_type == "hypothesis_merged" and actor in swarm_member_ids:
                update_dynamic_agent(
                    actor,
                    {
                        "status": "merged",
                        "merge_status": "accepted",
                        "incremental_quality": details.get(
                            "incremental_quality"
                        ),
                        "contribution_id": details.get("contribution_id"),
                        "last_event_type": event_type,
                        "last_sequence": row.get("sequence", 0),
                    },
                )
            elif event_type == "hypothesis_created" and actor in swarm_member_ids:
                update_dynamic_agent(
                    actor,
                    {
                        "ledger_status": "candidate_created",
                        "hypothesis_id": hypothesis_id,
                        "candidate_score": details.get("score"),
                    },
                )
            for member_id in swarm_member_ids:
                member = dynamic_agents_by_id.get(member_id, {})
                if not hypothesis_id or member.get("hypothesis_id") != hypothesis_id:
                    continue
                if event_type == "swarm_gate_evaluated":
                    update_dynamic_agent(
                        member_id,
                        {
                            "gate_stage": details.get("stage"),
                            "gate_passed": details.get("passed"),
                            "gate_score": details.get("score"),
                            "gate_residuals": details.get("residuals"),
                        },
                    )
                elif event_type == "hypothesis_rejected":
                    update_dynamic_agent(
                        member_id,
                        {
                            "hypothesis_status": "rejected",
                            "rejection_reasons": details.get(
                                "reasons", details.get("rejection_reasons", [])
                            ),
                        },
                    )
            continue
        if event_type not in {
            "winning_subagent_completed",
            "winning_reasoning_step_completed",
        }:
            continue
        if (
            event_type == "winning_subagent_completed"
            and details.get("execution_mode") == "dynamic"
        ):
            dynamic_agent_id = str(row.get("actor", "")).strip()
            if dynamic_agent_id:
                update_dynamic_agent(
                    dynamic_agent_id,
                    {
                        "display_name": str(
                            details.get("display_name", "动态专用 Agent")
                        ),
                        "merge_target": str(details.get("merge_target", "S3")),
                        "skill_ids": list(details.get("skill_ids", [])),
                        "knowledge_pack_ids": list(
                            details.get("knowledge_pack_ids", [])
                        ),
                        "status": _workflow_step_status(details),
                    },
                )
            continue
        try:
            step = int(details.get("step", 0))
        except (TypeError, ValueError):
            continue
        if step not in range(1, 7):
            continue
        actor = (
            str(row.get("actor", "")).strip()
            if event_type == "winning_subagent_completed"
            else ""
        )
        previous_middle_cycle = _positive_int(
            latest_steps[step].get("middle_cycle")
        )
        projected_middle_cycle = _positive_int(details.get("middle_cycle"))
        event_status = _workflow_step_status(details)
        event_execution_mode = str(details.get("execution_mode", "")).strip()
        preserve_skipped_projection = (
            latest_steps[step].get("status") == "skipped"
            and event_type == "winning_reasoning_step_completed"
        )
        if preserve_skipped_projection:
            event_status = "skipped"
            event_execution_mode = "skip"
        latest_steps[step].update(
            {
                "agent_id": actor or latest_steps[step]["agent_id"],
                "execution_mode": (
                    "skip"
                    if event_status == "skipped"
                    else event_execution_mode
                    or ("dynamic" if is_dynamic_profile else resolved_modes[step])
                ),
                "status": event_status,
                "decision_finalized": True,
                "middle_cycle": (
                    projected_middle_cycle or previous_middle_cycle
                ),
                "result_summary": (
                    latest_steps[step]["result_summary"]
                    if preserve_skipped_projection
                    else str(row.get("summary", ""))
                ),
            }
        )
    # Project live Dynamic-v2 Mission Graph activity back onto the canonical
    # S1-S6 cards.  Dynamic runs can intentionally skip the legacy sequential
    # S-Agent calls, so relying only on winning_subagent_completed leaves the
    # UI at 0/6 while multiple mission-node specialists are actively running.
    dynamic_terminal_statuses = {"completed", "merged", "pruned", "failed", "skipped"}
    dynamic_active_statuses = {"recruiting", "queued", "running"}
    for step in range(1, 7):
        if not mission_graph_projection:
            break
        mission_node = f"S{step}"
        members = [
            item
            for item in dynamic_agents_by_id.values()
            if str(item.get("mission_node") or item.get("merge_target"))
            == mission_node
            and item.get("archetype") != "quality_expert_judge"
            and not bool(item.get("inactive_capacity"))
        ]
        if not members:
            continue
        statuses = {str(item.get("status", "planned")).lower() for item in members}
        successful_count = sum(
            str(item.get("status", "")).lower() in {"completed", "merged"}
            for item in members
        )
        active_count = sum(
            str(item.get("status", "")).lower() in dynamic_active_statuses
            for item in members
        )
        latest_steps[step]["execution_mode"] = "dynamic"
        latest_steps[step]["decision_finalized"] = True
        latest_steps[step]["dynamic_instance_count"] = len(members)
        latest_steps[step]["dynamic_completed_count"] = successful_count
        latest_steps[step]["result_summary"] = (
            f"动态蜂群 {successful_count} / {len(members)} 个实例完成"
        )
        if active_count:
            latest_steps[step]["status"] = "running"
        elif statuses and statuses <= dynamic_terminal_statuses:
            if successful_count:
                latest_steps[step]["status"] = "completed"
            elif "failed" in statuses:
                latest_steps[step]["status"] = "failed"
            else:
                latest_steps[step]["status"] = "skipped"

    # Canonical S1-S6 progress is monotonic. A late residual challenger may
    # still contribute to an earlier merge node, but once a downstream node
    # has started it is misleading to make the stage card appear to return to
    # S3/S4/S5. The dynamic-agent ledger continues to expose that extra work.
    furthest_started_step = max(
        (
            int(node[1:])
            for item in dynamic_agents_by_id.values()
            if (node := str(item.get("mission_node") or item.get("merge_target")))
            in {f"S{step}" for step in range(1, 7)}
            and not bool(item.get("inactive_capacity"))
            and str(item.get("status", "planned")).lower() != "planned"
        ),
        default=0,
    )
    if furthest_started_step >= 3:
        for step in range(1, furthest_started_step):
            if latest_steps[step]["status"] not in {"failed", "skipped"}:
                latest_steps[step]["status"] = "completed"

    for row in rows:
        backtrack_step = _workflow_backtrack_step(row)
        if backtrack_step in latest_steps:
            latest_steps[backtrack_step]["backtrack_count"] += 1
    winning_stage_started = any(
        (
            str(row.get("actor", "")) == "winning_mechanism"
            and str(row.get("event_type", "")) in {"task_received", "tool_call"}
        )
        or str(row.get("event_type", ""))
        in {
            "winning_subagent_completed",
            "winning_reasoning_step_completed",
            "winning_mission_graph_planned",
            "winning_agent_instance_recruited",
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
        }
        for row in rows
    )
    winning_stage_finished = any(
        str(row.get("event_type", ""))
        in {
            "winning_stage_completed",
            "capability_image_created",
            "audit_completed",
            "report_completed",
        }
        for row in rows
    )
    if winning_stage_started and not winning_stage_finished and not is_dynamic_profile:
        step_dependencies: dict[int, tuple[int, ...]] = {
            1: (),
            2: (),
            3: (1, 2),
            4: (3,),
            5: (4,),
            6: (4, 5),
        }
        for step, dependencies in step_dependencies.items():
            if latest_steps[step]["status"] != "pending":
                continue
            if all(
                latest_steps[dependency]["status"] in {"completed", "skipped"}
                for dependency in dependencies
            ):
                latest_steps[step]["status"] = "running"
    step_plan = [latest_steps[step] for step in range(1, 7)]
    dynamic_agents = sorted(
        dynamic_agents_by_id.values(),
        key=lambda item: (
            _positive_int(item.get("wave")),
            _positive_int(item.get("batch")),
            str(item.get("agent_id", "")),
        ),
    )
    swarm_members = [
        item for item in dynamic_agents if item.get("agent_id") in swarm_member_ids
    ]
    supervisor_members = [
        item
        for item in swarm_members
        if item.get("archetype") == "quality_expert_judge"
    ]
    mission_members = [
        item
        for item in swarm_members
        if item.get("archetype") != "quality_expert_judge"
    ]
    provider_types = sorted(
        {
            str(item.get("provider_type", ""))
            for item in swarm_members
            if str(item.get("provider_type", ""))
        }
    )
    execution_backends = sorted(
        {
            str(item.get("execution_backend", ""))
            for item in swarm_members
            if str(item.get("execution_backend", ""))
        }
    )
    wave_numbers = sorted(
        {
            _positive_int(item.get("wave"))
            for item in swarm_members
            if _positive_int(item.get("wave")) > 0
        }
    )
    role_pools = [
        {
            "mission_node": node,
            "count": sum(
                item.get("mission_node") == node for item in mission_members
            ),
            "member_ids": [
                str(item.get("agent_id", ""))
                for item in mission_members
                if item.get("mission_node") == node
            ],
        }
        for node in ("S1", "S2", "S3", "S4", "S5", "S6")
    ]
    swarm_cluster = {
        "enabled": bool(swarm_event_seen or swarm_members),
        "policy_id": str(
            swarm_plan_details.get("policy_id")
            or (
                swarm_plan_details.get("plan", {}).get("policy", {}).get("policy_id")
                if isinstance(swarm_plan_details.get("plan"), dict)
                else ""
            )
            or "winning_swarm_quality_v1"
        ),
        "provider_type": (
            provider_types[0]
            if len(provider_types) == 1
            else "mixed"
            if provider_types
            else ""
        ),
        "execution_backend": (
            execution_backends[0]
            if len(execution_backends) == 1
            else "mixed"
            if execution_backends
            else ""
        ),
        "members": swarm_members,
        "supervisors": supervisor_members,
        "mission_graph": mission_graph_projection,
        "role_pools": role_pools,
        "dynamic_specialists": [
            item for item in mission_members if item.get("recruitment_planned")
        ],
        "candidate_lineage": sorted(
            [
                item
                for item in candidate_lineage_by_id.values()
                if str(item.get("title", "")).strip()
                or safe_string_list(item.get("equipment_forms", []), limit=1)
                or str(item.get("primary_equipment_identity", "")).strip()
            ],
            key=lambda item: (
                -float(item.get("score") or 0),
                str(item.get("hypothesis_id", "")),
            ),
        ),
        "hypothesis_ledger": ledger_projection,
        "merge_receipts": sorted(
            merge_receipts_by_id.values(),
            key=lambda item: (
                _positive_int(item.get("resulting_ledger_version")),
                str(item.get("receipt_id", "")),
            ),
        ),
        "portfolio_decision": portfolio_projection,
        "final_equipment_portfolio": list(
            portfolio_projection.get("final_equipment_portfolio", [])
        ),
        "s6_authored_cards": list(s6_cards_by_id.values()),
        "s6_release_gate": s6_release_gate,
        "s6_authoring": s6_authoring,
        # Keep the public profile id stable for resume/API compatibility while
        # making the actual dynamic-v2 execution semantics explicit to the UI
        # and audit consumers.
        "execution_engine": (
            "winning_mission_graph"
            if is_dynamic_profile
            else "winning_swarm_controller"
        ),
        "creative_pool": (
            "open_query_first"
            if is_dynamic_profile
            else "profile_governed"
        ),
        "s6_input_contract": (
            "query_candidate_winning_logic_only"
            if is_dynamic_profile
            else "profile_compatibility_handoff"
        ),
        "waves": [
            {
                "wave": wave,
                "label": {
                    1: "问题发散",
                    2: "开放创作",
                    3: "组合决策",
                }.get(wave, f"波次 {wave}"),
                "member_ids": [
                    str(item.get("agent_id", ""))
                    for item in mission_members
                    if _positive_int(item.get("wave")) == wave
                ],
            }
            for wave in wave_numbers
        ],
        "counts": {
            # Read-only quality judges supervise convergence but do not consume
            # Mission Graph instance capacity and must not make the UI appear
            # to exceed maximum_instances.
            "total": len(mission_members),
            "planned": sum(
                bool(item.get("recruitment_planned")) for item in mission_members
            ),
            "recruiting": sum(
                item.get("status") == "recruiting" for item in mission_members
            ),
            "running": sum(
                item.get("status") == "running" for item in mission_members
            ),
            "completed": sum(
                item.get("status") == "completed" for item in mission_members
            ),
            "merged": sum(
                item.get("status") == "merged" for item in mission_members
            ),
            "pruned": sum(
                item.get("status") == "pruned" for item in mission_members
            ),
            "failed": sum(
                item.get("status") == "failed" for item in mission_members
            ),
        },
    }
    skipped_agent_ids = {
        str(definition["agent_id"])
        for definition in WINNING_STEP_DEFINITIONS
        if latest_steps[int(definition["step"])]["status"] == "skipped"
        or latest_steps[int(definition["step"])]["execution_mode"] == "skip"
    }
    active_agent_ids: list[str] = []
    for row in rows:
        row_details = row.get("details", {})
        skipped_step = (
            row.get("event_type") == "winning_subagent_completed"
            and isinstance(row_details, dict)
            and (
                row_details.get("execution_mode") == "skip"
                or row_details.get("status") == "skipped_by_branch_blueprint"
            )
        )
        actor = str(row.get("actor", "")).strip()
        if (
            not skipped_step
            and actor
            and actor != "unknown"
            and actor not in skipped_agent_ids
            and actor not in active_agent_ids
        ):
            active_agent_ids.append(actor)
        target = (
            str(row_details.get("target_agent_id", "")).strip()
            if isinstance(row_details, dict)
            else ""
        )
        if (
            target
            and target not in skipped_agent_ids
            and target not in active_agent_ids
        ):
            active_agent_ids.append(target)
    phases = _interaction_workflow_phases(
        rows,
        view=view,
        step_plan=step_plan,
        dynamic_agents=dynamic_agents,
    )
    terminal_failure = next(
        (
            row
            for row in reversed(rows)
            if row.get("event_type") == "run_failed"
        ),
        {},
    )
    terminal_failure_details = terminal_failure.get("details", {})
    terminal_failure_details = (
        terminal_failure_details
        if isinstance(terminal_failure_details, dict)
        else {}
    )
    failure_detail = str(
        terminal_failure_details.get("error")
        or getattr(view, "error", "")
        or ""
    ).strip()
    failed_phase = next(
        (item["id"] for item in phases if item.get("status") == "failed"),
        "",
    )
    run_is_failed = str(getattr(view, "status", "")).lower() == "failed"
    if not run_is_failed:
        # Historical failures remain in the audit timeline, but an active
        # resume must not present them as the current workflow failure.
        failed_phase = ""
        failure_detail = ""
    raw_step_mode_changes = meta_details.get("step_mode_changes", [])
    step_mode_changes = (
        [dict(item) for item in raw_step_mode_changes if isinstance(item, dict)]
        if isinstance(raw_step_mode_changes, list)
        else []
    )
    if not step_mode_changes:
        for item in meta_details.get("step_mode_overrides", []):
            if not isinstance(item, dict):
                continue
            try:
                step = int(item.get("step", 0))
            except (TypeError, ValueError):
                continue
            mode = str(item.get("mode", ""))
            if step not in pre_l4_modes or mode not in {
                "skip", "light", "standard", "deep"
            }:
                continue
            step_mode_changes.append(
                {
                    "step": step,
                    "previous_mode": pre_l4_modes[step],
                    "mode": mode,
                    **(
                        {"reason": str(item["reason"])}
                        if str(item.get("reason", "")).strip()
                        else {}
                    ),
                }
            )
    stage_gates: list[dict] = []
    for layer in ("L1", "L2", "L3"):
        row = next(
            (
                item
                for item in reversed(rows)
                if item.get("event_type")
                in {"winning_stage_completed", "winning_stage_reused"}
                and str(item.get("summary", "")).upper().startswith(layer)
            ),
            None,
        )
        if row is None:
            continue
        summary = str(row.get("summary", ""))
        stage_gates.append(
            {
                "layer": layer,
                "gate_passed": "gate=true" in summary.lower(),
                "summary": summary,
            }
        )
    return {
        "status": str(getattr(view, "status", "")),
        "execution": {
            "profile_id": execution_profile_id,
            "mode": str(started_details.get("mode") or execution.get("mode") or ""),
            "provider": str(
                started_details.get("provider")
                or execution.get("provider")
                or ""
            ),
            "model": str(started_details.get("model") or execution.get("model") or ""),
            "base_url_host": str(started_details.get("base_url_host", "")),
        },
        "discovery": {
            "primary_branch": primary_branch,
            "branch_name": str(
                blueprint.get("branch_name")
                or (
                    BRANCH_BLUEPRINTS[primary_branch].name
                    if primary_branch in BRANCH_BLUEPRINTS
                    else "Agent 正在分析主分支"
                )
            ),
            "secondary_branches": list(
                meta_details.get("secondary_branches")
                or blueprint.get("secondary_branches", [])
            ),
            "blueprint_mode": str(blueprint.get("blueprint_mode", "")),
            "generated_by": str(blueprint.get("generated_by", "")),
            "confidence": blueprint.get("confidence"),
            "baseline_agent_plan": list(blueprint.get("baseline_agent_plan", [])),
            "callback_agent_ids": list(blueprint.get("callback_agent_ids", [])),
        },
        "l4": {
            "cycle": meta_details.get("cycle", len(meta_events)),
            "replan_required": meta_details.get("replan_required") is True,
            "added_secondary_branches": list(
                meta_details.get("added_secondary_branches", [])
            ),
            "step_mode_overrides": list(
                meta_details.get("step_mode_overrides", [])
            ),
            "step_mode_changes": step_mode_changes,
            "dynamic_subagents": list(meta_details.get("dynamic_subagents", [])),
            "focus_questions": list(meta_details.get("focus_questions", [])),
            "rationale": str(meta_details.get("rationale", "")),
            "stop_reason": str(meta_details.get("stop_reason", "")),
        },
        "step_plan": step_plan,
        "dynamic_agents": dynamic_agents,
        "swarm_cluster": swarm_cluster,
        "stage_gates": stage_gates,
        "phases": phases,
        "failure": {
            "phase": "" if run_has_complete_report else failed_phase,
            "detail": "" if run_has_complete_report else failure_detail,
        },
        "loops": {
            "inner": sum(
                row.get("event_type") == "winning_inner_loop_evaluated"
                for row in rows
            ),
            "middle": sum(
                row.get("event_type") == "winning_middle_loop_evaluated"
                for row in rows
            ),
            "outer": sum(
                row.get("event_type") == "winning_outer_loop_evaluated"
                for row in rows
            ),
            "meta": len(meta_events),
        },
        "active_agent_ids": active_agent_ids,
    }


def _workflow_step_status(details: dict) -> str:
    raw_status = str(details.get("status", "completed")).lower()
    if (
        details.get("execution_mode") == "skip"
        or raw_status in {"skipped", "skipped_by_branch_blueprint"}
    ):
        return "skipped"
    if raw_status in {"failed", "error", "cancelled"}:
        return "failed"
    if raw_status in {"pending", "running"}:
        return raw_status
    return "completed"


def _workflow_backtrack_step(row: dict) -> int:
    details = row.get("details", {})
    if not isinstance(details, dict):
        return 0
    event_type = str(row.get("event_type", ""))
    if event_type == "recall_requested":
        return _workflow_target_step(details)
    if details.get("passed") is not False:
        return 0
    next_action = details.get("next_action", {})
    next_action = next_action if isinstance(next_action, dict) else {}
    action = str(
        details.get("recommended_action")
        or details.get("action")
        or next_action.get("action")
        or ("rerun" if details.get("rerun_from_step") else "")
    ).lower()
    if action not in {"retry", "recall", "backtrack", "rerun"}:
        return 0
    return _workflow_target_step(details)


def _workflow_target_step(details: dict) -> int:
    next_action = details.get("next_action", {})
    next_action = next_action if isinstance(next_action, dict) else {}
    candidates = (
        details.get("backtrack_to_step"),
        details.get("rerun_from_step"),
        details.get("target_step"),
        next_action.get("target_step"),
        details.get("step"),
    )
    for value in candidates:
        try:
            step = int(value or 0)
        except (TypeError, ValueError):
            continue
        if step in range(1, 7):
            return step
    node = str(
        details.get("return_node") or details.get("source_layer") or ""
    ).upper()
    if node.startswith("S") and node[1:].isdigit():
        step = int(node[1:])
        return step if step in range(1, 7) else 0
    return {"L1": 1, "L2": 4, "L3": 5}.get(node, 0)


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _interaction_workflow_phases(
    rows: list[dict],
    *,
    view: object,
    step_plan: list[dict],
    dynamic_agents: list[dict],
) -> list[dict]:
    event_types = [str(row.get("event_type", "")) for row in rows]
    event_type_set = set(event_types)

    def has_actor_activity(actor_id: str) -> bool:
        return any(
            str(row.get("actor", "")) == actor_id
            and row.get("event_type") in {
                "agent_task_delegated",
                "task_received",
                "tool_call",
                "tool_result",
            }
            for row in rows
        )

    def phase(
        phase_id: str,
        label: str,
        status: str,
        agent_ids: list[str],
        relevant_types: set[str],
    ) -> dict:
        return {
            "id": phase_id,
            "label": label,
            "status": status,
            "agent_ids": list(dict.fromkeys(agent_ids)),
            "event_count": sum(item in relevant_types for item in event_types),
        }

    baseline_result_agents = {
        str(row.get("actor", ""))
        for row in rows
        if row.get("event_type") == "baseline_result"
        and str(row.get("actor", "")).strip()
    }
    selected_baseline_agents = {
        str(agent_id)
        for agent_id in getattr(view, "selected_agent_ids", [])
        if str(agent_id).strip()
    }
    # A savepoint-bearing baseline result is durable work even when the worker
    # stops before it emits the later batch-summary event.
    baseline_results_complete = bool(baseline_result_agents) and (
        not selected_baseline_agents
        or selected_baseline_agents.issubset(baseline_result_agents)
    )
    blueprint_completed = (
        "discovery_meta_loop_evaluated" in event_type_set
        or baseline_results_complete
    )
    # The worker marks the run as researching before the orchestrator model has
    # returned the discovery blueprint. During that first model call there is
    # intentionally no run_started trace yet, but the UI must still show real
    # activity instead of leaving every phase pending and looking stalled.
    run_status = str(getattr(view, "status", "")).lower()
    blueprint_started = "run_started" in event_type_set or run_status in {
        "planning",
        "researching",
        "recalling",
        "synthesizing",
        "reviewing",
        "reporting",
    }
    baseline_completed = bool(
        event_type_set
        & {
            "baseline_agents_summarized",
            "discovery_convergence_completed",
            "winning_subagent_completed",
            "audit_completed",
            "report_completed",
        }
    ) or baseline_results_complete
    baseline_started = bool(
        event_type_set
        & {
            "baseline_pipeline_started",
            "baseline_discovery_started",
            "baseline_discovery_lane_started",
            "baseline_model_queue_started",
            "baseline_model_call_started",
            "baseline_model_call_progress",
            "baseline_discovery_completed",
            "baseline_analysis_started",
            "baseline_wave_started",
            "baseline_wave_completed",
            "baseline_agent_completed",
            "baseline_result",
        }
    ) or bool(baseline_result_agents)
    convergence_completed = bool(
        event_type_set
        & {
            "discovery_convergence_completed",
            "winning_subagent_completed",
            "audit_completed",
            "report_completed",
        }
    )
    convergence_started = has_actor_activity("convergence_fusion")
    executable_steps = [
        item for item in step_plan if item["execution_mode"] != "skip"
    ]
    # A completed first pass is not the end of the S-Agent phase: the middle
    # critic may still be reviewing the chain or running a targeted S4/S6
    # repair. Only close the phase after its loop/stage gate is persisted.
    # Otherwise the UI can show "completed" for several minutes while a real
    # model call is still active.
    s_agent_gate_completed = bool(
        event_type_set
        & {
            "winning_middle_loop_evaluated",
            "winning_stage_completed",
            "winning_stage_reused",
            "winning_portfolio_merge_completed",
            "capability_image_created",
            "audit_completed",
            "report_completed",
        }
    )
    s_agents_completed = (
        bool(executable_steps)
        and all(item["status"] == "completed" for item in executable_steps)
        and s_agent_gate_completed
    )
    if event_type_set & {"audit_completed", "report_completed"}:
        s_agents_completed = True
    s_agents_started = bool(
        event_type_set
        & {
            "winning_subagent_completed",
            "winning_model_queue_started",
            "winning_model_call_started",
            "winning_model_call_progress",
            "winning_model_call_completed",
            "winning_inner_loop_evaluated",
            "winning_middle_loop_evaluated",
            "winning_outer_loop_evaluated",
            "winning_mission_graph_planned",
            "winning_agent_instance_recruited",
            "winning_agent_instance_ready",
            "winning_agent_session_started",
            "winning_agent_session_completed",
            "winning_portfolio_merge_completed",
        }
    ) or has_actor_activity("winning_mechanism")
    if s_agents_started:
        # S1–S6 only starts after baseline material has converged. Older runs
        # can miss the explicit convergence event when an exception interrupts
        # checkpoint persistence, so preserve the causal progression in replay.
        convergence_completed = True
    audit_pending = bool(
        event_type_set
        & {"audit_model_pending", "audit_model_unavailable"}
    ) and "report_completed" not in event_type_set
    audit_completed = not audit_pending and bool(
        event_type_set & {"audit_completed", "report_completed"}
    )
    audit_started = has_actor_activity("auditor")
    report_status = "pending"
    report_started = False
    report_failure_detail = ""
    for row in rows:
        event_type = str(row.get("event_type", ""))
        actor = str(row.get("actor", ""))
        details = row.get("details", {})
        details = details if isinstance(details, dict) else {}
        targets_reporter = (
            event_type == "agent_task_delegated"
            and str(details.get("target_agent_id", "")) == "reporter"
        )
        reporter_activity = actor == "reporter" and (
            event_type
            in {
                "task_received",
                "tool_call",
                "tool_result",
            }
            or event_type.startswith("report_model_")
        )
        if targets_reporter or reporter_activity:
            report_started = True
            report_status = "running"
            report_failure_detail = ""
        if event_type == "report_model_failed":
            report_started = True
            report_status = "failed"
            report_failure_detail = str(
                details.get("detail") or details.get("reason") or ""
            ).strip()
        elif event_type == "report_completed":
            report_started = True
            report_status = "completed"
            report_failure_detail = ""
    # A historical run may contain a report-completed event emitted before a
    # model-audit timeout was persisted. Never replay that inconsistent pair as
    # a successful report delivery; the audit is the release prerequisite.
    if audit_pending and report_status == "completed":
        report_status = "failed"
        report_failure_detail = "业务审计未完成，报告交付已暂停"
    # Some configuration or delivery failures can stop the run after Reporter
    # activity but before the explicit report_model_failed trace is persisted.
    # Project those terminal failures as failed instead of leaving the phase
    # looking permanently active.
    # A persisted report and an approved/completed run are authoritative even
    # when a late worker writes a stale report_model_failed event or failure
    # marker. Never show a successful delivery as failed.
    run_view = view
    run_result = getattr(run_view, "result", {})
    run_result = run_result if isinstance(run_result, dict) else {}
    run_has_complete_report = (
        str(getattr(run_view, "status", "")).lower() == "completed"
        and (
        str(run_result.get("audit_status", "")).lower() in {"approved", "passed", "limited", "pending"}
            or bool(run_result.get("report_available"))
        )
    )
    if run_status == "failed" and report_started and report_status != "completed" and not run_has_complete_report:
        report_status = "failed"
    if run_has_complete_report:
        report_status = "completed"
        report_failure_detail = ""
    baseline_agents = [
        str(agent_id)
        for row in rows
        if row.get("event_type") in {
            "run_started",
            "baseline_pipeline_started",
            "baseline_wave_started",
            "baseline_wave_completed",
        }
        and isinstance(row.get("details"), dict)
        for agent_id in row["details"].get("agent_ids", [])
        if str(agent_id).strip()
    ]
    if not baseline_agents:
        baseline_agents = [
            str(item) for item in getattr(view, "selected_agent_ids", [])
        ]
    s_agent_ids = [
        str(item["agent_id"])
        for item in step_plan
        if item["execution_mode"] != "skip" and item["status"] != "skipped"
    ]
    s_agent_ids.extend(
        str(item.get("agent_id", ""))
        for item in dynamic_agents
        if item.get("status") not in {"skipped", "pruned", "failed"}
    )
    latest_report_progress = next(
        (
            row
            for row in reversed(rows)
            if str(row.get("event_type", ""))
            in {
                "report_model_queue_started",
                "report_model_call_started",
                "report_model_call_progress",
                "report_model_call_completed",
            }
        ),
        {},
    )
    latest_report_details = latest_report_progress.get("details", {})
    latest_report_details = (
        latest_report_details
        if isinstance(latest_report_details, dict)
        else {}
    )
    report_progress_detail = ""
    if report_status == "running" and latest_report_details:
        current_step = str(
            latest_report_details.get("current_step", "三层九项报告撰写")
        )
        elapsed_seconds = float(
            latest_report_details.get("elapsed_seconds", 0) or 0
        )
        report_progress_detail = current_step
        if elapsed_seconds > 0:
            report_progress_detail += f" · 已耗时 {round(elapsed_seconds)} 秒"

    phases = [
        phase(
            "blueprint",
            "任务理解与发现蓝图",
            "completed" if blueprint_completed else "running" if blueprint_started else "pending",
            ["orchestrator"],
            {"run_started", "discovery_meta_loop_evaluated"},
        ),
        phase(
            "baseline",
            "多源基线研究",
            "completed" if baseline_completed else "running" if baseline_started else "pending",
            baseline_agents,
            {
                "baseline_wave_started",
                "baseline_wave_completed",
                "baseline_agent_completed",
                "baseline_agents_summarized",
                "baseline_pipeline_started",
                "baseline_discovery_started",
                "baseline_discovery_lane_started",
                "baseline_model_queue_started",
                "baseline_model_call_started",
                "baseline_model_call_progress",
                "baseline_model_call_completed",
                "baseline_discovery_completed",
                "baseline_analysis_started",
                "baseline_analysis_completed",
                "baseline_materialization_progress",
            },
        ),
        phase(
            "convergence",
            "发现结果收敛",
            "completed" if convergence_completed else "running" if convergence_started else "pending",
            ["convergence_fusion"],
            {"discovery_convergence_completed"},
        ),
        phase(
            "s_agents",
            "S1-S6 专用 Agent",
            "completed" if s_agents_completed else "running" if s_agents_started else "pending",
            s_agent_ids,
            {
                "winning_subagent_completed",
                "winning_model_queue_started",
                "winning_model_call_started",
                "winning_model_call_progress",
                "winning_model_call_completed",
                "winning_inner_loop_evaluated",
                "winning_middle_loop_evaluated",
                "winning_outer_loop_evaluated",
                "winning_mission_graph_planned",
                "winning_agent_instance_recruited",
                "winning_agent_instance_ready",
                "winning_agent_session_started",
                "winning_agent_session_completed",
                "winning_portfolio_merge_completed",
            },
        ),
        phase(
            "audit",
            "业务审计",
            "pending" if audit_pending else "completed" if audit_completed else "running" if audit_started else "pending",
            ["auditor"],
            {"audit_completed", "audit_model_pending", "audit_model_unavailable", "audit_delivery_blocked"},
        ),
        {
            **phase(
                "report",
                "报告交付",
                report_status,
                ["reporter"],
                {
                    "report_model_queue_started",
                    "report_model_call_started",
                    "report_model_call_progress",
                    "report_model_call_completed",
                    "report_completed",
                    "report_model_failed",
                },
            ),
            "detail": (
                "独立报告生成失败，未使用降级模板；可从检查点恢复"
                if report_status == "failed"
                else report_progress_detail
            ),
            "error": report_failure_detail,
        },
    ]
    if run_status in {"failed", "cancelled"} and not run_has_complete_report:
        phase_order = ["blueprint", "baseline", "convergence", "s_agents", "audit", "report"]
        started = {
            "blueprint": blueprint_started,
            "baseline": baseline_started,
            "convergence": convergence_started or convergence_completed,
            "s_agents": s_agents_started,
            "audit": audit_started,
            "report": report_started,
        }
        active_phase = next(
            (phase_id for phase_id in reversed(phase_order) if started[phase_id]),
            "blueprint",
        )
        for phase_row in phases:
            if phase_row["id"] == active_phase:
                phase_row["status"] = "failed" if run_status == "failed" else "cancelled"
                if active_phase != "report":
                    phase_row["detail"] = "运行在此阶段停止；已保留可恢复检查点"
            elif phase_row["id"] in {"blueprint", "baseline", "convergence", "s_agents", "audit", "report"}:
                phase_row["status"] = (
                    "completed"
                    if phase_order.index(phase_row["id"])
                    < phase_order.index(active_phase)
                    else "pending"
                )
    return phases


def _interaction_agents_with_runtime(
    configured_agents: list[dict],
    rows: list[dict],
) -> list[dict]:
    result = [dict(item) for item in configured_agents]
    known_ids = {str(item.get("agent_id", "")) for item in result}
    for row in rows:
        if row.get("event_type") != "winning_subagent_completed":
            continue
        details = row.get("details", {})
        actor = str(row.get("actor", ""))
        if (
            not isinstance(details, dict)
            or details.get("execution_mode") != "dynamic"
            or not actor
            or actor in known_ids
        ):
            continue
        known_ids.add(actor)
        result.append(
            {
                "agent_id": actor,
                "display_name": str(
                    details.get("display_name", "动态专用 Agent")
                ),
                "description": "由 Codex L4/蓝图按专业缺口生成并在受控 Harness 中执行。",
                "capability_tags": [],
                "tools": [],
                "visible_sections": [],
                "skills": [],
                "skill_ids": list(details.get("skill_ids", [])),
                "shared_skills": [],
                "knowledge_pack_ids": list(
                    details.get("knowledge_pack_ids", [])
                ),
                "knowledge_packs": [],
                "harness_profile": "dynamic_specialist_v1",
                "harness_profile_config": {},
                "system_agent": False,
                "output_contract": "bounded_dynamic_specialist_result",
                "research_policy": {},
                "handoff_policy": {
                    "publish_to": [str(details.get("merge_target", "S3"))]
                },
                "runtime_dynamic": True,
            }
        )
    return result


def _require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise HTTPException(status_code=403, detail="insufficient role")


def _artifact_json(root: Path, name: str) -> dict[str, Any] | list[Any] | None:
    root = Path(root)
    path = root / name
    try:
        # Artifact directories are treated as untrusted, read-only input. Do
        # not follow a sidecar symlink (or a symlink escape from the run root)
        # while reconstructing a historical RunView.
        resolved_root = root.resolve()
        if path.is_symlink() or not path.is_file():
            return None
        resolved_path = path.resolve()
        if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _artifact_run_base_dirs(output_root: Path) -> list[Path]:
    """Return bounded roots in which historical run directories may live.

    Current workers use ``outputs/runs/<run-id>``.  Older direct-run commands
    wrote ``outputs/<run-id>`` instead.  Keep the compatibility lookup limited
    to those two explicit layouts; never walk an arbitrary parent tree looking
    for a user supplied identifier.
    """

    configured = Path(output_root).expanduser().resolve()
    candidates = [configured]
    if configured.name.lower() == "runs":
        candidates.append(configured.parent)
    elif (configured / "runs").is_dir():
        candidates.append(configured / "runs")
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _artifact_run_root(
    output_root: Path,
    run_id: str,
    *,
    require_completion_marker: bool = False,
) -> Path | None:
    """Locate an artifact directory using only approved layouts."""

    if not _is_safe_run_id(run_id):
        return None
    for base in _artifact_run_base_dirs(output_root):
        candidate = base / run_id
        try:
            # Reject symlinked run directories and symlink escapes from a
            # trusted base.  Historical artifacts are read-only API inputs.
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if base != resolved and base not in resolved.parents:
                continue
            if require_completion_marker and not _artifact_has_completion_marker(resolved):
                continue
            return resolved
        except OSError:
            continue
    return None


def _artifact_has_completion_marker(root: Path) -> bool:
    """Whether a directory contains enough durable output to replay a run."""

    # A quality gate is the strongest completion marker.  The remaining files
    # cover older runners that emitted the report/delivery artifacts without a
    # gate sidecar.
    return any(
        (root / name).is_file() and not (root / name).is_symlink()
        for name in (
            "report_quality_gate.json",
            "report.md",
            "report-postfix.md",
            "delivery-manifest.json",
            "branch_deliverables.json",
            "architecture-acceptance.json",
        )
    )


def _artifact_run_view(output_root: Path, run_id: str) -> RunView | None:
    """Build a read-only RunView from a durable research artifact directory."""

    root = _artifact_run_root(output_root, run_id, require_completion_marker=True)
    if root is None:
        return None
    summary = _artifact_json(root, "round_summary.json")
    if not isinstance(summary, dict):
        return None
    quality = _artifact_json(root, "report_quality_gate.json")
    quality = quality if isinstance(quality, dict) else {}
    problem = summary.get("problem", {})
    problem = problem if isinstance(problem, dict) else {}
    provider = summary.get("provider", {})
    provider = provider if isinstance(provider, dict) else {}
    model = str(provider.get("model") or "").strip()
    provider_type = str(provider.get("type") or "").strip()
    # Reporter metadata reflects the task-level selected profile.  Some
    # historical summaries kept the bootstrap CLI provider in ``provider``
    # even when every dynamic agent ran through Queen.
    models = summary.get("agent_models", {})
    if isinstance(models, dict):
        reporter = models.get("reporter", {})
        if isinstance(reporter, dict):
            model = str(reporter.get("model") or model).strip()
            provider_type = str(reporter.get("provider") or provider_type).strip()
    provider_id = (
        "codex_queen" if "queen" in provider_type.lower() or "qwen" in model.lower()
        else "codex"
    )
    evolution_scope = summary.get("evolution_scope", {})
    evolution_scope = evolution_scope if isinstance(evolution_scope, dict) else {}
    evolution_scope = {
        "tenant_id": _bounded_scope_id(evolution_scope.get("tenant_id", "")),
        "workspace_id": _bounded_scope_id(evolution_scope.get("workspace_id", "")),
        "project_id": _bounded_scope_id(evolution_scope.get("project_id", "")),
        "profile_id": _bounded_scope_id(evolution_scope.get("profile_id", "")),
        "stage_scope": _normalized_stage_scope(evolution_scope.get("stage_scope", [])),
    }
    created_at = str(problem.get("created_at") or "").strip()
    if not created_at:
        try:
            created_at = datetime.fromtimestamp(root.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            created_at = now_iso()
    route = str(
        summary.get("resolved_route")
        or problem.get("research_route")
        or "auto"
    )
    branch = problem.get("discovery_branch") or "auto"
    selected = problem.get("selected_agent_ids", [])
    selected = [str(item) for item in selected] if isinstance(selected, list) else []
    quality_score = quality.get("overall_score")
    result = {
        "run_id": run_id,
        "status": "completed",
        "route": route,
        "audit_status": str(
            (summary.get("architecture_conformance") or {}).get("audit_status", "")
            if isinstance(summary.get("architecture_conformance"), dict)
            else ""
        ),
        "quality_score": quality_score,
        "report_available": _preferred_report_path(root) is not None,
        "historical_artifact": True,
        "artifact_root": str(root),
    }
    return RunView(
        run_id=run_id,
        topic=str(problem.get("topic") or run_id),
        research_route=route,
        selected_agent_ids=selected,
        max_rounds=int(problem.get("max_rounds_hint") or 1),
        created_by="artifact-replay",
        execution={
            "mode": "real" if str(summary.get("mode", "real")) == "real" else str(summary.get("mode", "real")),
            "provider": provider_id,
            "model": model,
            "base_url": str(provider.get("base_url_host") or ""),
            "historical_artifact": True,
        },
        status="completed",
        result=result,
        error="",
        analyst_confirmed=True,
        interaction_mode=str(problem.get("interaction_mode") or summary.get("interaction_mode") or "autonomous"),
        discovery_branch=str(branch) if not isinstance(branch, dict) else str(branch.get("primary") or "auto"),
        execution_profile_id="winning_swarm_dynamic_v2",
        report_template_mode="project_argument_v1",
        updated_at=created_at,
        supplemental_information=str(problem.get("supplemental_information") or ""),
        model_profile_id="codex-queen" if provider_id == "codex_queen" else "codex-gpt",
        tenant_id=evolution_scope["tenant_id"],
        workspace_id=evolution_scope["workspace_id"],
        project_id=evolution_scope["project_id"],
        profile_id=evolution_scope["profile_id"],
        stage_scope=evolution_scope["stage_scope"],
    )


def _discover_artifact_runs(output_root: Path) -> list[RunView]:
    rows: list[RunView] = []
    seen_ids: set[str] = set()
    for base in _artifact_run_base_dirs(output_root):
        if not base.is_dir() or base.is_symlink():
            continue
        try:
            children = sorted(base.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for root in children:
            run_id = root.name
            if run_id in seen_ids or not root.is_dir() or root.is_symlink():
                continue
            view = _artifact_run_view(output_root, run_id)
            if view is not None:
                rows.append(view)
                seen_ids.add(run_id)
    return rows


def _run_file(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str) -> Path:
    root = _run_root(service, output_root, run_id)
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="run output not found")
    return path


def _is_historical_snapshot(view: object) -> bool:
    """True when metadata was restored without the original run artifacts."""
    result = getattr(view, "result", {})
    result = result if isinstance(result, dict) else {}
    recovery = result.get("recovery", {})
    return (
        isinstance(recovery, dict)
        and recovery.get("run_artifacts_present") is False
    )


def _historical_snapshot_report(view: object) -> str:
    topic = str(getattr(view, "topic", "本次研究任务"))
    recovery = getattr(view, "result", {}) or {}
    recovery = recovery.get("recovery", {}) if isinstance(recovery, dict) else {}
    source = str(recovery.get("source", "历史任务快照")) if isinstance(recovery, dict) else "历史任务快照"
    return (
        f"# {_branch_report_title(topic, {})}\n\n"
        "> 这是可审计的历史任务快照。原始研究产物目录未随快照保存，系统未伪造报告正文、证据或能力画像。\n\n"
        f"- 快照来源：{source}\n"
        "- 当前可用：任务主题、运行状态、审计元数据与历史交互索引\n"
        "- 详细报告、证据卡和能力画像：原始产物恢复后自动可读；也可重新运行任务生成完整产物。"
    )


def _normalize_report_title_for_display(markdown: str, topic: str) -> str:
    """Apply the global academic title policy to existing report artifacts."""

    title = _branch_report_title(topic, {})
    return re.sub(r"\A\s*#\s+[^\n]+", f"# {title}", str(markdown), count=1)


def _preferred_report_path(run_root: Path) -> Path | None:
    """Return the approved postfix when present, otherwise the original report.

    Postfix regeneration intentionally preserves ``report.md`` for auditability,
    so the repaired postfix is only selected when its companion gate passed.
    A non-passing post-run quality gate is advisory: it must not hide a
    completed task's already persisted report from the workbench.
    """

    root = run_root.resolve()
    postfix_path = (root / "report-postfix.md").resolve()
    postfix_gate_path = (root / "report-quality-gate-postfix.json").resolve()
    if (
        root in postfix_path.parents
        and root in postfix_gate_path.parents
        and postfix_path.is_file()
        and postfix_gate_path.is_file()
    ):
        try:
            gate = json.loads(postfix_gate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            gate = {}
        if gate.get("passed") is True:
            return postfix_path

    # A partial report is an audit artifact, not a public download target.
    # Keep it hidden even if a stale report.md is still on disk.
    failure_path = (root / "report_failure.json").resolve()
    if root in failure_path.parents and failure_path.is_file():
        try:
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(failure, dict):
            status = str(failure.get("status", "")).strip().lower()
            if status in {"failed_quality_gate", "limited_quality_gate"}:
                return None
            if failure.get("partial_report_path") or failure.get(
                "partial_report_available"
            ) is True:
                return None
            if failure.get("report_written") is False:
                return None

    report_path = (root / "report.md").resolve()
    if root in report_path.parents and report_path.is_file():
        return report_path
    return None


def _run_root(service: ResearchApplicationService, output_root: Path, run_id: str) -> Path:
    try:
        view = service.get_run(run_id)
    except (KeyError, NoResultFound, RunNotFoundError) as exc:
        view = _artifact_run_view(output_root, run_id)
        if view is None:
            raise HTTPException(status_code=404, detail="run not found") from exc
    root = _resolve_run_root(output_root, run_id, view.result)
    if root is None:
        run_dir_value = str(view.result.get("run_dir", "")).strip()
        if run_dir_value:
            raise HTTPException(status_code=404, detail="run output not found")
        raise HTTPException(status_code=409, detail="run outputs are not ready")
    if not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=404, detail="run output not found")
    return root


def _read_json(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str):
    return json.loads(_run_file(service, output_root, run_id, relative).read_text(encoding="utf-8"))


def _read_jsonl(service: ResearchApplicationService, output_root: Path, run_id: str, relative: str) -> list[dict]:
    return _jsonl_path(_run_file(service, output_root, run_id, relative))


def _is_safe_run_id(run_id: str) -> bool:
    """Return whether *run_id* can be used as one filesystem path segment.

    Run IDs are opaque values and legacy producers have used punctuation such
    as ``release..1``.  Reject path separators and traversal segments, while
    avoiding the previous substring check that incorrectly rejected otherwise
    safe IDs containing two dots.
    """

    if not run_id or "\x00" in run_id or "/" in run_id or "\\" in run_id:
        return False
    return run_id not in {".", ".."}


def _resolve_run_root(
    output_root: Path,
    run_id: str,
    result: dict | None = None,
) -> Path | None:
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    bases = _artifact_run_base_dirs(output_root)
    primary = output_root.resolve() / run_id
    candidates = [primary]
    if isinstance(result, dict):
        for key in ("run_dir", "artifact_root"):
            value = str(result.get(key, "")).strip()
            if value:
                candidates.append(Path(value).expanduser())
    # A DB row created by an older runner may not contain a path field at all.
    # Reuse the same bounded compatibility layouts as artifact discovery, but
    # only accept a directory that has a completion marker. This prevents a
    # random sibling directory from becoming an API file root for a live run.
    legacy_root = _artifact_run_root(
        output_root,
        run_id,
        require_completion_marker=True,
    )
    if legacy_root is not None:
        candidates.append(legacy_root)
    for candidate in candidates:
        try:
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            # Result metadata is persisted data and may be stale or tampered
            # with. A valid run root is exactly one direct child named after
            # this run under either outputs/runs or the legacy outputs layout.
            # Merely being somewhere below a base is insufficient because it
            # would allow one DB row to read or write another task's files.
            if resolved.name != run_id or resolved.parent not in bases:
                continue
            return resolved
        except OSError:
            continue
    return None


def _public_run_result(
    result: object,
    output_root: Path,
    run_id: str,
    *,
    compact: bool = False,
) -> dict:
    data = dict(result) if isinstance(result, dict) else {}
    root = _resolve_run_root(output_root, run_id, data)
    public = {
        key: value
        for key, value in data.items()
        if key not in {
            "run_dir",
            "report_path",
            "summary_path",
            "capability_images_path",
            "manifest_path",
            "branch_deliverables_path",
            "artifact_root",
        }
    }
    public["report_available"] = bool(
        root is not None and _preferred_report_path(root) is not None
    )
    public["historical_snapshot"] = bool(
        isinstance(data.get("recovery"), dict)
        and data["recovery"].get("run_artifacts_present") is False
    )
    if compact:
        public = {
            key: public[key]
            for key in (
                "run_id",
                "status",
                "route",
                "audit_status",
                "quality_score",
                "report_available",
                "historical_snapshot",
            )
            if key in public
        }
    return public


def _public_artifact_counts(view: object, output_root: Path) -> dict[str, int]:
    """Return card-sized artifact counts without loading artifact bodies."""

    result = getattr(view, "result", {})
    result = result if isinstance(result, dict) else {}
    counts: dict[str, int] = {}
    root = _resolve_run_root(output_root, str(getattr(view, "run_id", "")), result)
    summary: dict[str, Any] = {}
    if root is not None:
        summary_payload = _artifact_json(root, "round_summary.json")
        if isinstance(summary_payload, dict):
            summary = summary_payload
    store_summary = summary.get("store_summary", {})
    store_summary = store_summary if isinstance(store_summary, dict) else {}
    source_materials = summary.get("source_materials", [])
    source_material_count = len(source_materials) if isinstance(source_materials, list) else 0
    evidence_assessments = summary.get("evidence_assessments", [])
    evidence_assessment_count = (
        len(evidence_assessments) if isinstance(evidence_assessments, list) else 0
    )

    def count(*values: object) -> int:
        for value in values:
            try:
                if value is not None and int(value) >= 0:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    persisted = result.get("artifact_counts")
    if isinstance(persisted, dict):
        for key in ("sources", "evidence", "capabilities", "winning_steps", "reports"):
            try:
                counts[key] = max(0, int(persisted.get(key, 0)))
            except (TypeError, ValueError):
                counts[key] = 0
        # Older completed runs persisted only the lifecycle result. Newer runs
        # may have a partial count snapshot. Use the small round summary to
        # backfill zero fields without reading the large artifact bodies.
        counts["sources"] = count(
            source_material_count,
            counts["sources"],
            store_summary.get("baseline_packet_count"),
        )
        counts["evidence"] = count(
            counts["evidence"],
            evidence_assessment_count,
            store_summary.get("materialized_evidence_count"),
            store_summary.get("evidence_count"),
        )
        counts["capabilities"] = count(
            counts["capabilities"], store_summary.get("capability_image_count")
        )
        counts["winning_steps"] = count(
            counts["winning_steps"], store_summary.get("stage_output_count")
        )
        if not counts["reports"] and root is not None and _preferred_report_path(root) is not None:
            counts["reports"] = 1
        return counts

    counts["sources"] = count(
        result.get("source_count"),
        source_material_count,
        store_summary.get("baseline_packet_count"),
    )
    counts["evidence"] = count(
        result.get("evidence_count"),
        evidence_assessment_count,
        store_summary.get("materialized_evidence_count"),
        store_summary.get("evidence_count"),
    )
    counts["capabilities"] = count(
        result.get("capability_count"),
        store_summary.get("capability_image_count"),
    )
    counts["winning_steps"] = count(
        result.get("stage_count"),
        store_summary.get("stage_output_count"),
    )
    if not counts["capabilities"] and root is not None:
        capability_path = root / "capability_images.json"
        try:
            capability_payload = json.loads(capability_path.read_text(encoding="utf-8"))
            capability_rows = (
                capability_payload
                if isinstance(capability_payload, list)
                else capability_payload.get("capability_images", [])
                if isinstance(capability_payload, dict)
                else []
            )
            counts["capabilities"] = (
                len(capability_rows) if isinstance(capability_rows, list) else 0
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    if not counts["evidence"] and root is not None:
        domain_path = root / "domain.jsonl"
        try:
            with domain_path.open("r", encoding="utf-8") as handle:
                total = 0
                materialized = 0
                for line in handle:
                    if '"type": "EvidenceCard"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = row.get("payload", {})
                    if not isinstance(payload, dict):
                        continue
                    total += 1
                    if payload.get("artifact_refs"):
                        materialized += 1
                counts["evidence"] = materialized or total
        except (OSError, UnicodeDecodeError):
            pass
    report_count = count(result.get("report_count"))
    if not report_count:
        report_path = root / "report.md" if root is not None else None
        report_count = 1 if report_path is not None and report_path.is_file() else 0
    counts["reports"] = report_count
    return counts


def _public_run_view(
    view: object,
    output_root: Path,
    *,
    compact: bool = False,
) -> dict:
    data = dict(view.__dict__) if hasattr(view, "__dict__") else dict(view)
    run_id = str(data.get("run_id", ""))
    # Persisted runs may predate a profile rename. Normalize at the read
    # boundary too, so old runs remain inspectable before they are resumed or
    # edited and the UI never has to know the legacy id.
    if data.get("model_profile_id"):
        data["model_profile_id"] = normalize_profile_id(
            str(data["model_profile_id"])
        )
    execution = data.get("execution")
    if isinstance(execution, dict) and execution.get("model_profile_id"):
        execution = dict(execution)
        execution["model_profile_id"] = normalize_profile_id(
            str(execution["model_profile_id"])
        )
        data["execution"] = execution
    data["result"] = _public_run_result(
        data.get("result"), output_root, run_id, compact=compact
    )
    data["artifact_counts"] = _public_artifact_counts(view, output_root)
    return data


def _jsonl_path(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize_favorite_fragment(value: object) -> str:
    """Normalize user-visible card identity without changing snapshot prose."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _normalize_favorite_tags(value: object) -> list[str]:
    """Normalize user-editable favorite tags into a bounded list."""

    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    for item in values:
        tag = " ".join(str(item or "").split()).strip()[:64]
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= 20:
            break
    return result


def _favorite_card_key(row: Mapping[str, object] | object) -> str:
    """Return the stable card key used by the favorites uniqueness fence."""

    if not isinstance(row, Mapping):
        return ""
    for field in ("card_binding_id", "card_id", "capability_id"):
        value = _normalize_favorite_fragment(row.get(field, ""))
        if value:
            return value
    name = _normalize_favorite_fragment(row.get("name") or row.get("capability_name"))
    classification = row.get("capability_classification", {})
    if isinstance(classification, Mapping):
        primary = _normalize_favorite_fragment(
            classification.get("primary_dimension")
            or classification.get("primary")
        )
        secondary = classification.get("secondary_dimensions") or classification.get("secondary") or []
        if isinstance(secondary, (str, bytes)):
            secondary_values = [_normalize_favorite_fragment(secondary)]
        elif isinstance(secondary, (list, tuple, set)):
            secondary_values = [
                _normalize_favorite_fragment(item) for item in secondary
            ]
        else:
            secondary_values = []
        dimensions = "+".join(
            item for item in [primary, *secondary_values] if item
        )
    else:
        dimensions = _normalize_favorite_fragment(classification)
    return "|".join(item for item in (name, dimensions) if item)


def _favorite_card_aliases(row: Mapping[str, object] | object) -> set[str]:
    """Build aliases accepted when a client sends an older card identifier."""

    if not isinstance(row, Mapping):
        return set()
    aliases = {
        _normalize_favorite_fragment(row.get(field, ""))
        for field in (
            "card_binding_id",
            "card_id",
            "capability_id",
            "card_key",
            "name",
            "capability_name",
        )
    }
    key = _favorite_card_key(row)
    if key:
        aliases.add(key)
    return {item for item in aliases if item}


def _favorite_identity_aliases(row: Mapping[str, object] | object) -> set[str]:
    """Return non-ambiguous aliases for persisted favorite identity matching.

    Request compatibility may intentionally accept a bare capability name, but
    using names for persisted-row deduplication can merge two distinct cards
    that happen to share a title.  Projection and legacy favorite migration
    therefore use only explicit IDs/card keys, with the normalized
    name+classification fallback emitted by ``_favorite_card_key`` when no
    stronger identity exists.
    """

    if not isinstance(row, Mapping):
        return set()
    aliases = {
        _normalize_favorite_fragment(row.get(field, ""))
        for field in ("card_binding_id", "card_id", "capability_id", "card_key")
    }
    key = _favorite_card_key(row)
    if key:
        aliases.add(key)
    return {item for item in aliases if item}


def _favorite_portrait_eligibility(row: Mapping[str, object] | object) -> tuple[bool, str]:
    """Enforce the plan's ``formal complete S6`` favorite boundary."""

    if not isinstance(row, Mapping):
        return False, "capability card is invalid"

    def truthy(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().casefold() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
            "是",
            "有",
        }

    def normalized(value: object) -> str:
        return _normalize_favorite_fragment(value)

    # Eligibility is content-first for compatibility with older completed
    # artifacts.  A complete five-module card may therefore carry
    # ``legacy_v1``/``legacy_derived``/``structured_unspecified`` when its
    # provenance tag was not persisted.  Explicit failure/provisional/S5 or
    # reference markers remain hard rejection signals, even if stale prose is
    # present in the artifact.
    authoring_statuses = [
        normalized(row.get("portrait_authoring_status")),
        normalized(row.get("s6_authoring_status")),
    ]
    provenance_statuses = [
        normalized(row.get("analysis_provenance_status")),
        normalized(row.get("provenance_status")),
        normalized(row.get("selection_status")),
    ]
    status_values = [value for value in [*authoring_statuses, *provenance_statuses] if value]
    # A reviewer-approved capability version is promoted to the formal
    # collectible view even when its source was a reference-weapon deep
    # research session.  Keep the original source/provenance fields for audit,
    # but do not let the historical ``reference`` marker block an explicitly
    # verified version.  Pending/rejected/rolled-back versions remain
    # ineligible below.
    version_status = normalized(
        row.get("version_status")
        or row.get("capability_version_status")
        or row.get("research_status")
    )
    reviewed_version = version_status in {"verified", "approved", "accepted"}

    if not reviewed_version and any(
        truthy(row.get(field))
        for field in (
            "is_reference",
            "reference_only",
            "is_reference_equipment",
            "reference_candidate",
        )
    ):
        return False, "reference equipment cannot be favorited"
    if not reviewed_version and any(
        truthy(row.get(field))
        for field in (
            "s6_authoring_failed",
            "authoring_failed",
            "is_temporary",
            "is_provisional",
            "pending_authoring",
        )
    ):
        return False, "only a formal S6 capability portrait can be favorited"
    type_values = [
        normalized(row.get(field))
        for field in ("capability_type", "type", "kind", "card_type")
    ]
    if not reviewed_version and any(
        value in {
            "reference",
            "reference_equipment",
            "reference_candidate",
            "s5",
            "temporary",
            "provisional",
        }
        or re.search(r"(?:^|[_\-\s])(?:reference|temporary|provisional|s5)(?:$|[_\-\s])", value)
        or "参考" in value
        or "临时" in value
        or "待成稿" in value
        for value in [*type_values, *provenance_statuses]
        if value
    ):
        return False, "reference or temporary capability cards cannot be favorited"

    def explicitly_disallowed_status(value: str) -> bool:
        if not value:
            return False
        # This status means the independent S6 authoring completed with
        # editorial warnings. It remains eligible when all five modules are
        # present; the completeness check below is still mandatory.
        if value == "authored_quality_limited" or (
            value == "limited_quality"
            and "authored_quality_limited" in authoring_statuses
        ):
            return False
        # Normalize separators, remove explicit negations such as
        # ``not_limited``, then inspect whole tokens. This catches compound
        # producer statuses (``authoring_failed`` / ``limited_failure``)
        # without misclassifying their explicit negative forms.
        tokenized = re.sub(r"[_\-\s]+", "_", value).strip("_")
        negative_markers = (
            "s5|fallback|limited|pending|provisional|failed|failure|error|"
            "rejected|cancelled|canceled|draft|incomplete|unfinished"
        )
        tokenized = re.sub(
            rf"(?:^|_)(?:not|no|non)_(?:{negative_markers})(?=_|$)",
            "_",
            tokenized,
        ).strip("_")
        if set(tokenized.split("_")).intersection(
            {
                "s5",
                "fallback",
                "limited",
                "pending",
                "provisional",
                "failed",
                "failure",
                "error",
                "rejected",
                "cancelled",
                "canceled",
                "draft",
                "incomplete",
                "unfinished",
            }
        ):
            return True
        return any(
            marker in value
            for marker in (
                "回退",
                "受限",
                "失败",
                "错误",
                "拒绝",
                "驳回",
                "取消",
                "待核验",
                "待验证",
                "待审核",
                "审核中",
                "未核验",
                "未验证",
                "待校准",
                "待成稿",
                "临时",
                "参考",
                "未完成",
                "未成稿",
                "草稿",
            )
        )

    if not reviewed_version and any(
        explicitly_disallowed_status(value)
        for value in [*status_values, *type_values]
    ):
        return False, "only a formal S6 capability portrait can be favorited"
    verification_status = normalized(row.get("verification_status"))
    verification_rejected = not reviewed_version and verification_status in {
        "pending",
        "unverified",
        "rejected",
        "待核验",
        "待验证",
    } or explicitly_disallowed_status(verification_status)
    if verification_rejected or truthy(row.get("confidence_limited")):
        return False, "capability card is pending verification"
    modules = row.get("capability_portrait_modules")
    parsed_modules = parse_capability_portrait_modules(
        row.get("deep_capability_portrait") or row.get("capability_image")
    )
    if isinstance(modules, Mapping):
        # Structured fields are authoritative, but a legacy card may carry a
        # complete labeled portrait alongside an incomplete module map. Fill
        # only missing keys from that parsed text for compatibility.
        modules = {
            **parsed_modules,
            **{
                str(key): value
                for key, value in modules.items()
                if str(value or "").strip()
            },
        }
    else:
        modules = parsed_modules
    required = [key for key, _ in CAPABILITY_PORTRAIT_MODULES]
    if any(not str(modules.get(key, "") or "").strip() for key in required):
        return False, "完整五模块 S6 画像正文是收藏必需项"
    portrait = str(
        row.get("deep_capability_portrait") or row.get("capability_image") or ""
    ).strip()
    if not portrait:
        # A structured five-module card is still a complete portrait after
        # projection; assemble it so snapshots always contain full text.
        portrait = assemble_capability_portrait_modules(
            {
                **dict(modules),
                "capability_classification": row.get(
                    "capability_classification", {}
                ),
            }
        )
    if not portrait:
        return False, "empty capability portrait cannot be favorited"
    # Explicit S6 provenance is preferred, but older completed artifacts may
    # lack the status field.  The complete five-column contract above is the
    # safe compatibility signal for those rows.
    return True, ""


_MECHANICAL_VERIFICATION_FILL_RE = re.compile(
    r"对[^。\n]{1,120}的样机考核还应覆盖[^。\n]{1,120}(?:。|(?=\n|$))"
)


def _strip_mechanical_verification_fill(value: object) -> object:
    """Remove legacy, mechanically repeated verification boilerplate.

    Some completed artifacts were produced by an older formatter that appended
    the same sample-evaluation sentence to every portrait module.  Keep the
    model-authored prose intact while removing only that recognisable sentence
    pattern at the API boundary.
    """

    if isinstance(value, str):
        cleaned = _MECHANICAL_VERIFICATION_FILL_RE.sub("", value)
        return re.sub(r"[；;，, ]{2,}", " ", cleaned).strip()
    if isinstance(value, list):
        return [_strip_mechanical_verification_fill(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_mechanical_verification_fill(item) for key, item in value.items()}
    return value


def _delete_run_output(output_root: Path, run_id: str) -> None:
    if not _is_safe_run_id(run_id) or run_id == ".":
        raise HTTPException(status_code=400, detail="invalid run id")
    root = output_root.resolve()
    target = root / run_id
    if target.is_symlink():
        target.unlink()
        return
    if not target.exists():
        return
    if target.resolve().parent != root:
        raise HTTPException(status_code=400, detail="invalid run output path")
    shutil.rmtree(target)


def _verify_run_deleted(
    service: ResearchApplicationService,
    output_root: Path,
    run_id: str,
) -> None:
    residue: dict[str, int | bool] = {}
    try:
        service.get_run(run_id)
    except (KeyError, NoResultFound):
        pass
    else:
        residue["run"] = True

    inspect_residue = getattr(service.repository, "deletion_residue", None)
    if callable(inspect_residue):
        residue.update(
            {
                name: count
                for name, count in inspect_residue(run_id).items()
                if count
            }
        )

    target = output_root.resolve() / run_id
    if target.exists() or target.is_symlink():
        residue["run_output"] = True
    if residue:
        raise RuntimeError(f"permanent deletion left backend residue: {residue}")


def _capability_api_view(row: dict) -> dict:
    """Enrich v1 capability images for the normative UI without mutating artifacts."""
    result = _strip_mechanical_verification_fill(dict(row))
    if not isinstance(result, dict):
        result = dict(row)
    authoring_status = str(
        result.get("portrait_authoring_status")
        or result.get("s6_authoring_status")
        or ""
    ).strip()
    # A provider-limited S6 result is not a completed capability portrait.
    # Never manufacture five display columns from frozen S5 fields: that path
    # produced plausible-looking but mechanically repeated prose.  Keep the
    # equipment record and provenance, but withhold the portrait until the card
    # receives a complete independent S6 authoring pass.
    portrait_withheld = authoring_status in {
        "authored_fallback_from_frozen_selection",
        "limited_provider_failure",
    } or authoring_status.startswith("limited_fallback")
    if portrait_withheld:
        result["capability_portrait_modules"] = {}
        result["deep_capability_portrait"] = ""
        result["capability_image"] = ""
        result["portrait_module_character_counts"] = {}
        warnings = result.get("portrait_quality_warnings")
        if not isinstance(warnings, list):
            warnings = []
        note = "S6独立成稿未完成；系统已停用回退模板，须定向重跑该装备画像。"
        result["portrait_quality_warnings"] = list(dict.fromkeys([*warnings, note]))
    # Older deliveries placed the classification line at the top of the
    # portrait. Promote it to a structured field so the display remains
    # useful even when the artifact predates the classification schema.
    classification = result.get("capability_classification")
    if not isinstance(classification, dict):
        classification = {}
    if not classification:
        portrait_text = str(result.get("deep_capability_portrait") or result.get("capability_image") or "")
        match = re.search(
            r"能力分类\s*[：:]\s*主\s*[：:]\s*(?P<primary>[^；。]+)"
            r"(?:；\s*辅\s*[：:]\s*(?P<secondary>[^。]+))?",
            portrait_text,
        )
        if match:
            classification = {
                "primary_dimension": match.group("primary").strip(),
                "secondary_dimensions": [
                    item.strip() for item in re.split(r"[、,，]", match.group("secondary") or "") if item.strip()
                ],
                "classification_basis": "由S6按该装备在当前任务场景中的主要战果与关键作战节点归类。",
            }
    result["capability_classification"] = normalize_capability_classification(
        classification
    )
    for prose_field in ("capability_image", "deep_capability_portrait"):
        if prose_field in result:
            result[prose_field] = normalize_capability_portrait_text(
                strip_schema_placeholders(result[prose_field])
            )
    modules = result.get("capability_portrait_modules")
    if isinstance(modules, dict) and not portrait_withheld:
        supplied_module_keys = {
            str(key)
            for key, value in modules.items()
            if str(value or "").strip()
        }
        partial_quality_card = (
            authoring_status == "authored_quality_limited"
            and not all(
                key in supplied_module_keys
                for key in (
                    "overview",
                    "technology_implementation",
                    "operational_process",
                    "capability_effects",
                    "winning_logic",
                )
            )
        )
        normalized_modules = normalize_capability_portrait_modules(
            modules,
            allow_structured_salvage=True,
        )
        # Keep the authored column intact.  Four-hundred characters is an
        # editorial target, not a display ceiling; character-level projection
        # used to leave the final sentence or causal link unfinished.
        result["capability_portrait_modules"] = normalized_modules
        if not partial_quality_card:
            result["portrait_module_character_counts"] = capability_portrait_module_lengths(
                normalized_modules
            )
        rebuilt = assemble_capability_portrait_modules(
            {
                **normalized_modules,
                "capability_classification": result.get("capability_classification", {}),
            }
        )
        if rebuilt and not partial_quality_card:
            result["capability_image"] = rebuilt
            result["deep_capability_portrait"] = rebuilt
    for removed_field in (
        "key_functions",
        "performance_indicators",
        "verification_methods",
    ):
        result.pop(removed_field, None)
    structured = any(
        result.get(key)
        for key in (
            "military_utility",
            "strike_countermeasure_value",
            "novelty",
            "foresight",
            "evidence_basis",
            "agent_contributions",
            "reasoning_refs",
        )
    )
    portrait_authoring_status = str(
        result.get("portrait_authoring_status")
        or result.get("s6_authoring_status")
        or ""
    ).strip()
    # Provenance is content-first.  Older runs can carry a legacy authoring
    # tag while still containing the complete structured value/trace fields;
    # those cards must remain on the same normative display path.
    has_governed_portrait = bool(
        result.get("capability_portrait_modules")
        or result.get("deep_capability_portrait")
        or result.get("capability_image")
    )
    if portrait_authoring_status == "authored_quality_limited":
        result["analysis_provenance_status"] = "limited_quality"
    elif portrait_authoring_status.startswith("s6_authored") or portrait_authoring_status == "authored_semantically_consistent":
        result["analysis_provenance_status"] = "s6_authored"
    elif portrait_authoring_status.startswith("limited") or portrait_authoring_status in {
        "authored_fallback_from_frozen_selection",
        "limited_provider_failure",
    }:
        result["analysis_provenance_status"] = "limited_failure"
    elif structured and has_governed_portrait:
        result["analysis_provenance_status"] = "structured_migrated"
    elif portrait_authoring_status.startswith("legacy"):
        result["analysis_provenance_status"] = "legacy_derived"
    else:
        result["analysis_provenance_status"] = (
            "structured" if structured else "legacy_derived"
        )
    result["portrait_authoring_status"] = portrait_authoring_status or (
        "legacy_v1" if not structured else "structured_unspecified"
    )
    upgrade = result.get("capability_type") == "upgrade"
    image = str(result.get("capability_image", ""))
    if not result.get("equipment_form"):
        result["equipment_form"] = str(result.get("equipment_category", ""))
    if not result.get("operational_mechanism"):
        result["operational_mechanism"] = (
            _capability_labeled_value(image, "深度机制")
            or str(result.get("strike_countermeasure_value", ""))
        )
    if not result.get("development_path"):
        result["development_path"] = str(result.get("foresight", ""))
    if not result.get("mission_effect"):
        result["mission_effect"] = str(
            result.get("strike_countermeasure_value")
            or result.get("military_utility")
            or (
                "以较短工程周期提升现役装备在复杂环境中的体系贡献度、任务适配性和持续保障能力。"
                if upgrade
                else "形成可组合、可扩展、可降级的新型任务能力，缩短从发现问题到产生任务效果的闭环。"
            )
        )
    if not result.get("system_dependencies"):
        result["system_dependencies"] = ["与现有指挥信息、情报侦察和保障体系形成标准化接口", "支持通信受限和局部节点失效条件下的降级运行"]
    if not result.get("risk_boundaries"):
        result["risk_boundaries"] = ["公开证据不足的参数保留区间与置信度，不转化为确定阈值", "不以单一平台性能替代体系任务效果，不假设持续高带宽连接"]
    source_name = str(result.get("name", "")).strip()
    equipment_form = str(
        result.get("equipment_form") or result.get("equipment_category") or ""
    ).strip()
    display_name = source_name or primary_equipment_form_title(equipment_form)
    if source_name and display_name != source_name:
        result["source_name"] = source_name
    result["name"] = display_name
    equipment_identity = "；".join(
        str(value)
        for value in (
            display_name,
            result.get("equipment_form") or result.get("equipment_category"),
            result.get("mission_effect") or result.get("military_utility"),
        )
        if str(value).strip()
    )
    result["problem_statement"] = normalize_capability_problem(
        result.get("capability_gap") or result.get("problem_statement"),
        fallback=f"{display_name}对应的关键任务链存在目标、授权、交战或毁伤评估断点",
    )
    result["operational_process"] = complete_operational_process(
        result.get("operational_process") or result.get("strike_chain_contribution"),
        equipment_identity=equipment_identity,
    )
    result["verification_plan"] = normalize_verification_plan(
        result.get("verification_plan") or result.get("verification"),
        equipment_identity=equipment_identity,
        failure_boundary=(
            result.get("risk_boundaries")
            or result.get("operational_constraints")
            or result.get("upgrade_boundary")
        ),
    )
    portrait_scenario = result.get("target_scenario") or result.get("related_scenario")
    authored_portrait = str(
        result.get("deep_capability_portrait")
        or result.get("capability_image")
        or ""
    ).strip()
    result["deep_capability_portrait"] = _remove_raw_query_from_portrait_lede(
        authored_portrait,
        scenario=portrait_scenario,
    )
    result["confidence"], result["confidence_components"] = (
        calibrate_capability_confidence(result, prior=result.get("confidence"))
    )
    return result


def _suppress_cross_card_capability_contamination(rows: list[dict]) -> list[dict]:
    """Hide legacy prose when a card names a sibling equipment object.

    Older artifacts did not persist hypothesis IDs or semantic checks.  The
    sibling names in the same delivery are still a safe deterministic
    identity index, so a contaminated portrait is marked pending and removed
    from the user-facing payload rather than shown under the wrong weapon.
    """

    aliases = {
        str(row.get("name", "") or "").strip()
        for row in rows
        if isinstance(row, dict) and len(str(row.get("name", "") or "").strip()) >= 4
    }
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        own = str(item.get("name", "") or "").strip()
        prose = " ".join(
            str(item.get(field, "") or "")
            for field in (
                "deep_capability_portrait",
                "capability_image",
                "operational_mechanism",
                "operational_process",
            )
        )
        foreign = next(
            (name for name in sorted(aliases - {own}, key=len, reverse=True) if name in prose),
            "",
        )
        if foreign:
            item["verification_status"] = "pending"
            item["confidence_limited"] = True
            item["identity_consistency_issue"] = f"画像正文疑似串入其他候选装备“{foreign}”"
            item["deep_capability_portrait"] = ""
            item["capability_image"] = ""
        result.append(item)
    return result


def _provisional_s6_capability_rows(portfolio: object) -> list[dict]:
    """Expose completed S6 selections while the final delivery file is pending.

    S6 freezes the selected equipment portfolio before the reporter writes
    ``capability_images.json``.  The portfolio already contains the reviewed
    mechanism, evidence references, failure boundaries and validation path, so
    hiding it until report delivery incorrectly makes completed S6 work appear
    as a reference-only candidate list.
    """

    if not isinstance(portfolio, list):
        return []
    rows: list[dict] = []
    for index, item in enumerate(portfolio, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        equipment_form = str(item.get("equipment_form", "")).strip()
        function = str(item.get("function", "")).strip()
        mechanism = str(item.get("operational_mechanism", "")).strip()
        military_value = str(item.get("military_value", "")).strip()
        development_path = str(item.get("development_path", "")).strip()
        failure_boundary = str(item.get("failure_boundary", "")).strip()
        if not name or not equipment_form:
            continue
        hypothesis_id = str(item.get("hypothesis_id", "")).strip()
        raw_evidence_ids = item.get("direct_evidence_refs", [])
        evidence_ids = (
            [str(value).strip() for value in raw_evidence_ids if str(value).strip()][:12]
            if isinstance(raw_evidence_ids, list)
            else []
        )
        capability_id = (
            f"s6-{hypothesis_id}" if hypothesis_id else f"s6-portfolio-{index:02d}"
        )
        portrait = str(
            item.get("deep_capability_portrait")
            or item.get("capability_portrait")
            or item.get("capability_image")
            or ""
        ).strip()
        provisional = {
                "capability_id": capability_id,
                "name": name,
                "equipment_category": equipment_form,
                "equipment_form": equipment_form,
                "capability_type": str(item.get("type", "new_capability")),
                "source_winning_logic": mechanism or military_value,
                "related_scenario": function,
                "priority": str(item.get("priority", "待定")),
                "capability_gap": function,
                "capability_image": portrait,
                "deep_capability_portrait": portrait,
                "project_function": function,
                "mission_effect": military_value,
                "military_utility": military_value,
                "strike_countermeasure_value": mechanism,
                "novelty": mechanism,
                "foresight": development_path,
                "operational_mechanism": mechanism,
                "development_path": development_path,
                "risk_boundaries": [failure_boundary] if failure_boundary else [],
                "operational_constraints": [failure_boundary] if failure_boundary else [],
                "evidence_ids": evidence_ids,
                "evidence_basis": [f"直接证据：{value}" for value in evidence_ids],
                "agent_contributions": ["S1–S5 完成机理、对抗、工程与证据补强", "S6 完成组合评审与装备画像综合"],
                "reasoning_refs": [f"S6 / {hypothesis_id or capability_id}"],
                "confidence": float(item.get("confidence") or item.get("expert_score") or 0),
                "verification_status": str(item.get("verification_status", "assessed")),
                "confidence_limited": bool(item.get("confidence_limited", False)),
                "selection_quality_status": str(item.get("selection_quality_status", "expert_assessed")),
                "capability_classification": (
                    dict(item.get("capability_classification", {}))
                    if isinstance(item.get("capability_classification", {}), dict)
                    else {}
                ),
                "capability_portrait_modules": (
                    dict(item.get("capability_portrait_modules", {}))
                    if isinstance(item.get("capability_portrait_modules"), dict)
                    else {}
                ),
                "portrait_module_character_counts": (
                    dict(item.get("portrait_module_character_counts", {}))
                    if isinstance(item.get("portrait_module_character_counts"), dict)
                    else {}
                ),
                "portrait_quality_warnings": [
                    str(value).strip()
                    for value in (
                        item.get("s6_authoring_quality_warnings")
                        or item.get("portrait_quality_warnings", [])
                    )
                    if str(value).strip()
                ],
                "portrait_quality_contract_version": str(
                    item.get("portrait_quality_contract_version", "")
                ).strip(),
                "portrait_authoring_status": str(
                    item.get("portrait_authoring_status")
                    or item.get("s6_authoring_status")
                    or "legacy_v1"
                ),
                "provenance_status": "s6_provisional",
            }
        provisional["confidence"], provisional["confidence_components"] = (
            calibrate_capability_confidence(
                provisional,
                prior=(item.get("confidence") or item.get("expert_score") or 0.58),
            )
        )
        rows.append(provisional)
    return rows


def _remove_raw_query_from_portrait_lede(value: object, *, scenario: object = "") -> str:
    """Keep a combat-scene lede, never echo a research Query as that scene."""

    portrait = str(value or "").strip()
    if not portrait:
        return portrait
    raw_scenario = str(scenario or "").strip()
    scenario_is_research_instruction = bool(
        raw_scenario
        and any(
            marker in raw_scenario
            for marker in (
                "深度研究",
                "研究任务",
                "长期记忆",
                "装备研究",
                "发展需求",
            )
        )
    )
    if scenario_is_research_instruction:
        portrait = portrait.replace(raw_scenario, "任务相关作战阶段")
    if raw_scenario and raw_scenario in portrait:
        portrait = portrait.replace(
            f"面向{raw_scenario}，针对",
            "在任务相关作战阶段，针对",
            1,
        )
    # Legacy fallback cards sometimes use the full research instruction as the
    # value after “面向”. It is not a military scene and should not leak into
    # the user-visible capability overview.
    portrait = re.sub(
        r"(概述：?)面向(?:深度研究|理解|长期记忆|研究任务|装备研究)[^，。]{0,360}，针对",
        r"\1在任务相关作战阶段，针对",
        portrait,
        count=1,
    )
    return portrait


def _capability_labeled_value(text: str, label: str) -> str:
    marker = f"{label}："
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1]
    boundaries = [
        tail.find(f"。{next_label}：")
        for next_label in ("军事价值", "深度机制", "前瞻判断", "新颖性", "证据约束")
        if f"。{next_label}：" in tail
    ]
    end = min(boundaries) if boundaries else len(tail)
    return tail[:end].strip("。； ")


def _catalog_payload(agent_path: Path, preset_path: Path) -> dict:
    registry = AgentRegistry.load(agent_path)
    policy = load_preset_policy(preset_path)
    default_provider = configured_provider(fallback="codex")
    provider_registry = ProviderRegistry.load(
        agent_path.parent / "providers.yaml"
    )
    provider_options = provider_registry.public_options()["providers"]
    selected_provider_snapshot = provider_registry.profile_snapshot(default_provider)
    responses_base_url = os.environ.get(
        "EQUIPMENT_DR_BASE_URL", "https://api.openai.com/v1/responses"
    )
    responses_api_key_env = os.environ.get(
        "EQUIPMENT_DR_API_KEY_ENV", "EQUIPMENT_DR_API_KEY"
    )
    codex_base_url = os.environ.get(
        "EQUIPMENT_DR_CODEX_BASE_URL", "https://api.openai.com/v1"
    )
    codex_api_key_env = os.environ.get(
        "EQUIPMENT_DR_CODEX_API_KEY_ENV", "EQUIPMENT_DR_CODEX_API_KEY"
    )
    route_names = {
        "new_winning_mechanism": "新制胜机理",
        "traditional_gap": "传统能力缺口",
        "war_case_learning": "局部战争案例",
    }
    profile_payload = public_profiles()
    return {
        "model_profiles": profile_payload,
        "report_templates": [
            {
                "id": "project_argument_v1",
                "name": "项目论证五章模板（推荐）",
                "description": "需求分析、项目画像、总体方案、关键技术、研制基础；强化国内外案例对比、作战流程和体系贡献。",
                "default": True,
            },
            {
                "id": "three_layer_nine_item",
                "name": "三层九项模板（兼容）",
                "description": "保留需求挖掘、技术攻关、能力图像与效能贡献三层九项结构。",
                "default": False,
            },
        ],
        "execution_profiles": [
            {
                "id": "legacy_v1",
                "name": "传统固定编排",
                "short_name": "传统模式",
                "description": "采用传统固定流程执行，适合兼容回滚、稳定复现和对照研究。",
                "default": False,
                "recommended": False,
                "selectable": True,
                "badge": "兼容",
            },
            {
                "id": "optimized_v2",
                "name": "协同优化编排",
                "short_name": "协同模式",
                "description": "3–4 个业务 Agent 并行研判，随后进入 S1–S6 Cohort 与风险门控，适合普通研究任务。",
                "default": False,
                "recommended": True,
                "selectable": True,
                "badge": "推荐",
            },
            {
                "id": "swarm_quality_v1",
                "name": "质量残差蜂群",
                "short_name": "质量集群",
                "description": "保留 S1–S6 骨架，按质量残差弹性孵化最多 12 个专用 Agent，强化探索、挑战与独立收敛。",
                "default": False,
                "recommended": False,
                "selectable": True,
                "badge": "高质量",
                "evaluation_only": True,
            },
            {
                "id": "winning_swarm_dynamic_v2",
                "name": "Mission Graph 动态蜂群",
                "short_name": "动态蜂群",
                "description": "依据 Mission Graph 动态孵化 8–21 个实例，按依赖事件并行执行，适合复杂任务与最高并发研究。",
                "default": True,
                "recommended": False,
                "selectable": True,
                "badge": "最高并发",
                "evaluation_only": True,
            },
        ],
        # Deep research is an internal child-run profile, not a selectable
        # top-level execution mode.  Keep it discoverable for clients that
        # render the deep-thinking UI without breaking the legacy profile
        # catalog contract used by the run-launcher.
        "deep_research_profiles": [
            {
                "id": "deep_divergence_v1",
                "name": "深度发散研究",
                "short_name": "深研模式",
                "description": "继承当前 Query、结果与证据，仅执行 S3/S4 多维发散、按需检索和 S6 待核验成卡，不重跑 S1–S6。",
                "default": False,
                "recommended": False,
                "selectable": False,
                "badge": "深度追问专用",
            }
        ],
        "interaction_modes": [
            {
                "id": "expert",
                "name": "专家模式",
                "description": "由专家给定主题、边界和发现分支，Codex按显式约束细化执行。",
            },
            {
                "id": "autonomous",
                "name": "智能模式",
                "description": "Codex先执行场景发散和元编排，再动态选择主次发现分支。",
            },
        ],
        "discovery_branches": [
            {
                "id": code,
                "name": spec.name,
                "runtime_route": spec.route,
                "emphasis": list(spec.emphasis),
                "specialist_agent_ids": list(spec.specialist_agent_ids),
                "required_capability_tags": list(spec.required_capability_tags),
                "required_outputs": list(spec.required_outputs),
                "step_modes": [
                    {
                        "step": step,
                        "execution_mode": mode,
                    }
                    for step, mode in winning_step_modes(
                        code,
                        research_route=spec.route,
                    ).items()
                ],
            }
            for code, spec in BRANCH_BLUEPRINTS.items()
        ],
        "routes": [
            {
                "id": route_id,
                "name": route_names.get(route_id, route_id),
                "required_tags": required_tags,
                "optional_tags": policy.optional_capability_tags.get(route_id, []),
            }
            for route_id, required_tags in policy.required_capability_tags.items()
        ],
        "agents": [
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "description": agent.description,
                "capability_tags": agent.capability_tags,
                "tools": agent.tools,
                "visible_sections": agent.context_policy.get("visible_sections", []),
                "skills": agent.skills,
                "skill_ids": agent.skill_ids,
                "shared_skills": agent.shared_skills,
                "knowledge_pack_ids": agent.knowledge_pack_ids,
                "knowledge_packs": agent.knowledge_packs,
                "harness_profile": agent.harness_profile,
                "harness_profile_config": (
                    {
                        "budget": registry.get_harness_profile(agent.harness_profile).budget,
                        "stop_conditions": registry.get_harness_profile(agent.harness_profile).stop_conditions,
                        "phase_tools": registry.get_harness_profile(agent.harness_profile).phase_tools,
                    }
                    if agent.harness_profile
                    else {}
                ),
                "research_policy": agent.research_policy,
                "handoff_policy": agent.handoff_policy,
            }
            for agent in registry.enabled_baseline_agents()
        ],
        "shared_skill_layer": registry.shared_skill_catalog(),
        "knowledge_packs": registry.knowledge_pack_catalog(),
        "provider": {
            "type": "multi_agent_adapter",
            "default_provider": default_provider,
            "available_providers": [
                item["id"] for item in provider_options
            ],
            "provider_options": [
                {
                    **item,
                    "description": str(item.get("description", "")),
                    "credential_configured": bool(
                        os.environ.get(
                            str(item.get("default_api_key_env", "")), ""
                        ).strip()
                    ),
                }
                for item in provider_options
            ],
            "execution_fields": [
                "provider",
                "model",
                "base_url",
                "api_key_env",
                "agent_models",
            ],
            "codex_available": shutil.which(os.environ.get("EQUIPMENT_DR_CODEX_COMMAND", "codex")) is not None,
            "codex_command": os.environ.get("EQUIPMENT_DR_CODEX_COMMAND", "codex"),
            "model": configured_model(
                provider=default_provider,
                fallback=str(
                    selected_provider_snapshot.get("model")
                    if str(selected_provider_snapshot.get("model", "")).strip()
                    and not str(selected_provider_snapshot.get("model", "")).startswith("(")
                    else registry.default_model
                ),
            ),
            "default_base_url": responses_base_url,
            "default_api_key_env": responses_api_key_env,
            "default_codex_base_url": codex_base_url,
            "default_codex_api_key_env": codex_api_key_env,
            "default_mode": os.environ.get("EQUIPMENT_DR_MODE", "fake"),
            "modes": ["fake", "real"],
            "configurable_agent_ids": [
                *registry.all_agent_ids(),
            ],
            "default_agent_models": _agent_model_defaults(),
            "model_profiles": profile_payload,
        },
    }


def _agent_model_defaults() -> dict[str, dict[str, str]]:
    raw = os.environ.get("EQUIPMENT_DR_AGENT_MODELS_JSON", "{}").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(agent_id): {
            key: str(item[key])
            for key in ("provider", "model", "base_url", "api_key_env")
            if key in item and str(item[key]).strip()
        }
        for agent_id, item in value.items()
        if isinstance(item, dict)
    }


def _actual_baseline_agent_ids(rows: list[dict]) -> list[str]:
    activity_types = {
        "baseline_discovery_started",
        "baseline_model_call_started",
        "baseline_analysis_started",
        "baseline_agent_completed",
    }
    plan_types = {
        "run_started",
        "baseline_pipeline_started",
        "baseline_wave_started",
    }
    actual: list[str] = []
    planned: list[str] = []
    for row in rows:
        event_type = str(row.get("event_type", ""))
        if event_type not in activity_types | plan_types:
            continue
        payload = row.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        event = payload.get("event", payload)
        event = event if isinstance(event, dict) else {}
        details = event.get("payload", event)
        details = details if isinstance(details, dict) else {}
        if event_type in activity_types:
            agent_id = str(
                event.get("actor")
                or event.get("agent_id")
                or details.get("agent_id")
                or ""
            ).strip()
            if agent_id and agent_id not in actual:
                actual.append(agent_id)
            continue
        for agent_id in details.get("agent_ids", []):
            normalized = str(agent_id).strip()
            if normalized and normalized not in planned:
                planned.append(normalized)
    return actual or planned


def _interaction_agents(agent_path: Path) -> list[dict]:
    registry = AgentRegistry.load(agent_path)
    agents = []
    for agent_id in registry.all_agent_ids():
        agent = registry.get(agent_id)
        agents.append(
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "description": agent.description,
                "capability_tags": agent.capability_tags,
                "tools": agent.tools,
                "visible_sections": agent.context_policy.get("visible_sections", []),
                "skills": agent.skills,
                "skill_ids": agent.skill_ids,
                "shared_skills": agent.shared_skills,
                "knowledge_pack_ids": agent.knowledge_pack_ids,
                "knowledge_packs": agent.knowledge_packs,
                "harness_profile": agent.harness_profile,
                "harness_profile_config": (
                    {
                        "budget": registry.get_harness_profile(agent.harness_profile).budget,
                        "stop_conditions": registry.get_harness_profile(agent.harness_profile).stop_conditions,
                        "phase_tools": registry.get_harness_profile(agent.harness_profile).phase_tools,
                    }
                    if agent.harness_profile
                    else {}
                ),
                "system_agent": agent.system_agent,
                "output_contract": agent.output_contract,
                "research_policy": agent.research_policy,
                "handoff_policy": agent.handoff_policy,
            }
        )
    return agents


def _validated_execution(value: dict, provider: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("execution configuration must be an object")
    mode = str(value.get("mode") or provider.get("default_mode") or "fake")
    if mode not in {"fake", "real"}:
        raise ValueError("execution mode must be fake or real")
    if mode == "fake":
        return {"mode": "fake", "provider": "fake", "model": "fake"}
    pinned_profile_id = normalize_profile_id(
        str(value.get("model_profile_id") or "").strip()
    )
    pinned_profile: dict[str, str] = {}
    if pinned_profile_id:
        try:
            pinned_profile = profile_execution(pinned_profile_id)
        except (KeyError, OSError, ValueError) as exc:
            raise ValueError(f"unknown model profile: {pinned_profile_id}") from exc
    implicit_responses = not value.get("provider") and any(
        key in value for key in ("base_url", "api_key_env")
    )
    provider_name = str(
        pinned_profile.get("provider")
        or value.get("provider")
        or ("responses" if implicit_responses else provider.get("default_provider"))
        or "codex"
    )
    available = {
        str(item)
        for item in provider.get("available_providers", [])
    }
    if provider_name not in available:
        raise ValueError(
            "real mode provider is not configured: " + provider_name
        )
    provider_default_model = _provider_default_model(provider, provider_name)
    model = str(
        pinned_profile.get("model")
        or value.get("model")
        or provider_default_model
    ).strip()
    if not model or len(model) > 200:
        # If a caller supplied an endpoint, validate its transport boundary
        # before reporting a secondary model-field error.  This makes unsafe
        # HTTP endpoints fail closed with the actionable HTTPS message even
        # when the client omitted a model that would otherwise be filled by a
        # provider default.
        explicit_base_url = str(value.get("base_url") or "").strip()
        if explicit_base_url:
            _validate_endpoint_credentials(
                explicit_base_url,
                str(value.get("api_key_env") or "").strip(),
                label="real mode model",
            )
        raise ValueError("model name is required and must be at most 200 characters")
    if not pinned_profile_id:
        # The server environment is authoritative for runs that do not pin a
        # task-level profile.  This prevents a stale UI or persisted task
        # snapshot from sending a model that the current gateway does not
        # expose.
        model = str(
            configured_model(fallback=str(value.get("model") or provider_default_model))
        ).strip()
        # Route by model, not by a stale persisted provider.  The unified model
        # profile registry is the authoritative model->gateway map: selecting a
        # DeepSeek model must send the run to the DeepSeek-compatible endpoint,
        # while gpt-5.5 must keep using the Codex gateway.
        if not value.get("provider") and not implicit_responses:
            model_profiles = provider.get("model_profiles", {})
            profile_rows = (
                model_profiles.get("profiles", [])
                if isinstance(model_profiles, dict)
                else []
            )
            for profile_row in profile_rows:
                if not isinstance(profile_row, dict):
                    continue
                if str(profile_row.get("model", "")).strip() != model:
                    continue
                routed_provider = str(profile_row.get("provider", "")).strip()
                if routed_provider and routed_provider in available:
                    provider_name = routed_provider
                break
    default_base_url, default_api_key_env = _provider_credentials_defaults(
        provider, provider_name
    )
    base_url = str(
        pinned_profile.get("base_url")
        or value.get("base_url")
        or default_base_url
    ).strip()
    api_key_env = str(
        pinned_profile.get("api_key_env")
        or value.get("api_key_env")
        or default_api_key_env
    ).strip()
    _validate_endpoint_credentials(base_url, api_key_env, label="real mode model")
    provided_agent_models = value.get("agent_models", {})
    if not isinstance(provided_agent_models, dict):
        raise ValueError("agent_models must be an object")
    agent_models: dict[str, dict[str, str]] = {}
    raw_agent_models = {
        **provided_agent_models,
        **provider.get("default_agent_models", {}),
    }
    # Keep the merge rule explicit for callers that construct ``provider``
    # without the API catalog helper.
    for agent_id, env_profile in configured_agent_models().items():
        current = dict(raw_agent_models.get(agent_id, {}))
        current.update(env_profile)
        raw_agent_models[agent_id] = current
    allowed_agent_ids = set(provider.get("configurable_agent_ids", []))
    for agent_id, raw_profile in raw_agent_models.items():
        if agent_id not in allowed_agent_ids:
            raise ValueError(f"unknown configurable agent id: {agent_id}")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"agent model profile must be an object: {agent_id}")
        agent_provider = str(raw_profile.get("provider") or provider_name)
        if agent_provider not in available:
            raise ValueError(f"agent provider is invalid: {agent_id}")
        agent_model = str(raw_profile.get("model") or model).strip()
        agent_default_base_url, agent_default_api_key_env = (
            (base_url, api_key_env)
            if agent_provider == provider_name
            else _provider_credentials_defaults(provider, agent_provider)
        )
        agent_base_url = str(
            raw_profile.get("base_url") or agent_default_base_url
        ).strip()
        agent_api_key_env = str(
            raw_profile.get("api_key_env") or agent_default_api_key_env
        ).strip()
        if not agent_model or len(agent_model) > 200:
            raise ValueError(f"agent model name is invalid: {agent_id}")
        _validate_endpoint_credentials(
            agent_base_url,
            agent_api_key_env,
            label=f"agent model ({agent_id})",
        )
        agent_models[str(agent_id)] = {
            "provider": agent_provider,
            "model": agent_model,
            "base_url": agent_base_url,
            "api_key_env": agent_api_key_env,
        }
    result = {
        "mode": "real",
        "provider": provider_name,
        "model": model,
    }
    profile_id = pinned_profile_id or normalize_profile_id(
        str(os.environ.get("EQUIPMENT_DR_PROFILE", "")).strip()
    )
    if profile_id:
        result["model_profile_id"] = profile_id
    result.update({"base_url": base_url, "api_key_env": api_key_env})
    if agent_models:
        result["agent_models"] = agent_models
    return result


def _provider_credentials_defaults(provider: dict, provider_name: str) -> tuple[str, str]:
    if provider_name == "codex":
        return (
            str(provider.get("default_codex_base_url") or "https://api.openai.com/v1"),
            str(provider.get("default_codex_api_key_env") or "EQUIPMENT_DR_CODEX_API_KEY"),
        )
    if provider_name == "responses":
        return (
            str(provider.get("default_base_url") or "https://api.openai.com/v1/responses"),
            str(provider.get("default_api_key_env") or "EQUIPMENT_DR_API_KEY"),
        )
    for item in provider.get("provider_options", []):
        if str(item.get("id", "")) == provider_name:
            return (
                str(item.get("default_base_url") or "https://api.openai.com/v1"),
                str(item.get("default_api_key_env") or "EQUIPMENT_DR_API_KEY"),
            )
    return (
        str(provider.get("default_base_url") or "https://api.openai.com/v1/responses"),
        str(provider.get("default_api_key_env") or "EQUIPMENT_DR_API_KEY"),
    )


def _provider_default_model(provider: dict, provider_name: str) -> str:
    for item in provider.get("provider_options", []):
        if str(item.get("id", "")) == provider_name:
            return str(item.get("default_model", "")).strip()
    return str(provider.get("model", "")).strip()


def _validate_endpoint_credentials(base_url: str, api_key_env: str, *, label: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} URL must be HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"{label} URL must not contain credentials, query parameters, or fragments"
        )
    if not _valid_environment_name(api_key_env):
        raise ValueError(f"{label} API key environment variable name is invalid")


def _valid_environment_name(value: str) -> bool:
    return bool(value) and (value[0].isalpha() or value[0] == "_") and all(
        character.isalnum() or character == "_" for character in value
    )


def _missing_execution_credentials(execution: dict) -> list[str]:
    if execution.get("mode") != "real":
        return []
    names = {str(execution.get("api_key_env") or "").strip()}
    agent_models = execution.get("agent_models", {})
    if isinstance(agent_models, dict):
        names.update(
            str(profile.get("api_key_env") or "").strip()
            for profile in agent_models.values()
            if isinstance(profile, dict)
        )
    return sorted(
        name for name in names if name and not os.environ.get(name, "").strip()
    )


def _public_trace_interaction(event: dict) -> dict:
    # SqliteRunStore exports TraceProposal metadata around the original
    # TraceEvent. Live runtime events already provide the inner event directly.
    # Normalize both shapes so historical replay after an API restart retains
    # step numbers, agent plans and progress counters.
    nested_event = event.get("payload", {})
    if (
        isinstance(nested_event, dict)
        and nested_event.get("event_id")
        and nested_event.get("event_type") == event.get("event_type")
        and isinstance(nested_event.get("payload", {}), dict)
    ):
        event = nested_event
    event_type = str(event.get("event_type", "trace_event"))
    actor = str(event.get("actor", "orchestrator"))
    return {
        "event_id": str(event.get("event_id", "")),
        "created_at": str(event.get("created_at", "")),
        "actor": actor,
        "event_type": event_type,
        "category": _interaction_category(event_type),
        "title": _interaction_title(event_type, str(event.get("summary", ""))),
        "summary": str(event.get("summary", "")),
        "input_refs": list(event.get("input_refs", [])),
        "output_refs": list(event.get("output_refs", [])),
        "details": sanitize_runtime_payload(event.get("payload", {})),
        "source": "trace",
    }


def _public_session_interaction(event: dict) -> dict | None:
    event_type = str(event.get("event_type", ""))
    allowed = {
        "task_received",
        "tool_call",
        "tool_result",
        "evidence_assessed",
        "baseline_result",
        "savepoint",
    }
    if event_type not in allowed:
        return None
    actor = str(event.get("agent_id", "unknown"))
    safe_keys = {
        "task_id", "title", "summary", "capability_tags", "context_sections",
        "allowed_tools", "round_index", "recall_request", "tool_name", "call_id",
        "arguments", "status", "artifact_refs", "formal_evidence_allowed",
        "evidence_id", "decision", "quality_score", "reasons", "packet_id",
        "evidence_ids", "materialized_artifact_refs", "checkpoint_id", "output_refs",
        "worker_report_id",
    }
    details = {key: value for key, value in event.items() if key in safe_keys}
    tool_name = str(event.get("tool_name", ""))
    summary = str(event.get("summary", ""))
    if not summary:
        summary = tool_name or str(event.get("title", "")) or event_type
    return {
        "event_id": str(event.get("call_id") or event.get("checkpoint_id") or f"{actor}:{event_type}"),
        "created_at": str(event.get("created_at", "")),
        "actor": actor,
        "event_type": event_type,
        "category": _interaction_category(event_type),
        "title": _interaction_title(event_type, tool_name or summary),
        "summary": summary,
        "input_refs": [],
        "output_refs": list(event.get("output_refs", event.get("evidence_ids", []))),
        "details": sanitize_runtime_payload(details),
        "source": "session_projection",
    }


def _interaction_category(event_type: str) -> str:
    if event_type in {"tool_call", "tool_result", "evidence_assessed"}:
        return "tool"
    if "delegated" in event_type or event_type in {"run_started", "task_received"}:
        return "delegation"
    if (
        "reasoning" in event_type
        or "winning_stage" in event_type
        or "winning_subagent" in event_type
        or "winning_model" in event_type
        or "specialist_" in event_type
        or "swarm_" in event_type
        or "hypothesis_" in event_type
        or "winning_inner_loop" in event_type
        or "winning_middle_loop" in event_type
    ):
        return "reasoning"
    if "recall" in event_type:
        return "recall"
    if event_type == "savepoint":
        return "checkpoint"
    if "audit" in event_type:
        return "audit"
    if event_type.startswith("report_model_"):
        return "output"
    return "output"


def _interaction_title(event_type: str, fallback: str) -> str:
    labels = {
        "run_started": "研究任务启动与分解",
        "baseline_pipeline_started": "专业研究流水线启动",
        "baseline_discovery_started": "Agent 开始多源检索",
        "baseline_discovery_lane_completed": "检索通道完成",
        "baseline_discovery_completed": "Agent 多源检索完成",
        "baseline_provider_neutral_source_anchor_fallback": "无托管搜索，转用受控来源锚点",
        "baseline_analysis_completed": "Agent 结构化分析完成",
        "agent_task_delegated": "编排器委派任务",
        "agent_harness_completed": "差异化 Harness 执行完成",
        "task_received": "Agent 接收研究任务",
        "tool_call": "工具调用",
        "tool_result": "工具结果",
        "evidence_assessed": "证据质量评估",
        "baseline_result": "基线研究结果",
        "savepoint": "保存点",
        "baseline_agent_completed": "Agent 任务完成",
        "baseline_agents_summarized": "编排器汇总初检",
        "winning_subagent_completed": "制胜机理细化子 Agent 完成",
        "winning_model_queue_started": "S Agent 等待模型槽位",
        "winning_model_call_started": "S Agent 模型调用启动",
        "winning_model_call_progress": "S Agent 持续执行",
        "winning_model_call_completed": "S Agent 模型调用完成",
        "swarm_planned": "动态制胜 Agent 群规划",
        "winning_s3_s4_naming_plan_allocated": "S3/S4 命名分配完成",
        "winning_query_equipment_blueprint_planned": "Query 装备发散蓝图规划",
        "winning_pre_generation_active_angle_selection_fallback": "制胜维度选择回退",
        "winning_pre_generation_angle_portfolio_planned": "S3/S4 制胜维度分配",
        "winning_s3_active_agents_materialized": "S3/S4 开放创作席位就绪",
        "winning_s3_first_pass_self_admission_completed": "S3/S4 创作首稿完成",
        "winning_s3_s4_candidate_output_bounded": "S3/S4 候选数量边界",
        "winning_s3_s4_creative_iteration_limited": "S3/S4 创作迭代受限",
        "winning_s3_s4_name_authoring_diagnostic": "S3/S4 命名一致性诊断",
        "winning_reasoning_seed_published": "S1/S2 推理种子发布",
        "winning_specialized_seed_authored": "专用 Agent 候选生成",
        "winning_agent_instance_retry_scheduled": "动态 Agent 重试排程",
        "winning_candidate_pre_s5_residual_recorded": "候选进入 S5 前残差记录",
        "winning_candidate_rejected_before_ledger": "候选入账前拒绝",
        "winning_candidate_review_scope_planned": "候选评审范围规划",
        "winning_candidate_summary_quality_advisory": "候选摘要质量提示",
        "winning_contribution_hypothesis_remapped": "候选贡献 ID 重映射",
        "winning_s5_parallel_score_started": "S5 并行评分开始",
        "winning_s5_parallel_score_completed": "S5 并行评分完成",
        "winning_s5_empty_scope_skipped": "S5 空候选范围跳过",
        "winning_s5_contract_gate_rejected": "S5 具体武器合同拒绝",
        "winning_s5_portfolio_fallback_activated": "S5 评分回退启用",
        "winning_full_pool_portfolio_decision": "S5 全池组合判定",
        "winning_full_pool_portfolio_review_repaired": "S5 全池评审修复",
        "winning_full_pool_portfolio_review_rescued": "S5 全池评审救援",
        "winning_full_pool_portfolio_review_completed": "S5 全池评审完成",
        "winning_semantic_clustering_bounded": "候选语义聚类受限",
        "winning_semantic_clustering_failed": "候选语义聚类失败",
        "winning_s5_invalid_decision_rejected": "S5 无效判定拒绝",
        "winning_s5_invalid_merge_rejected": "S5 无效合并拒绝",
        "winning_s5_portfolio_frozen": "S5 多样化组合冻结",
        "winning_s5_handoff_quality_gate_completed": "S5 交接质量门完成",
        "winning_s6_parallel_authoring_configured": "S6 并行画像配置完成",
        "winning_s6_card_authoring_retry_started": "S6 单卡画像重试开始",
        "winning_agent_instance_ready": "动态 Agent 实例就绪",
        "winning_agent_instance_failed": "动态 Agent 实例失败隔离",
        "winning_agent_instance_cancelled": "动态 Agent 实例取消回收",
        "winning_agent_session_started": "动态 Agent 会话启动",
        "winning_agent_session_completed": "动态 Agent 会话完成",
        "winning_agent_waiting": "动态 Agent 持续执行",
        "winning_mission_graph_planned": "动态任务图规划",
        "winning_candidate_branch_created": "候选分支创建",
        "winning_candidate_ledger_frozen": "候选账本更新",
        "winning_contribution_queued": "贡献进入 Merge 队列",
        "winning_contribution_rebase_required": "贡献版本重基",
        "winning_contribution_merged": "贡献定向合并",
        "winning_contribution_rejected": "贡献越界拒绝",
        "winning_portfolio_merge_completed": "S5 多样化装备组合完成",
        "specialist_recruitment_planned": "专用 Agent 招聘合同形成",
        "specialist_spawned": "专用 Agent 招聘与孵化",
        "specialist_session_started": "独立 Codex CLI 会话启动",
        "specialist_session_completed": "独立 Codex CLI 会话结束",
        "specialist_completed": "专用 Agent 业务任务完成",
        "specialist_pruned": "专用 Agent 淘汰回收",
        "winning_specialized_seed_recovered": "动态蜂群专用候选恢复",
        "winning_specialized_seed_empty": "动态蜂群专用候选生成完成",
        "hypothesis_created": "候选制胜假设进入账本",
        "hypothesis_merged": "候选贡献定向合并",
        "hypothesis_rejected": "候选制胜假设淘汰",
        "swarm_gate_evaluated": "动态 Agent 群质量门控",
        "winning_inner_loop_evaluated": "制胜机理内循环批判",
        "winning_middle_loop_evaluated": "制胜机理中循环批判",
        "winning_reasoning_step_completed": "制胜机理六步推理",
        "winning_stage_completed": "制胜机理分层门控",
        "capability_image_created": "能力画像生成",
        "report_model_queue_started": "Reporter 等待模型槽位",
        "report_model_call_started": "Reporter 模型调用启动",
        "report_model_call_progress": "Reporter 持续撰写",
        "report_model_call_completed": "Reporter 模型调用完成",
    }
    return labels.get(event_type, fallback or event_type)
