"""装备研究领域 PostgreSQL 模型，挂在业务 Base 上由 migrator 统一建表。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from platform_core.storage.postgres.models_business import Base, JSON_VALUE
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now_naive

EQUIPMENT_RUN_STATUSES = (
    "draft",
    "queued",
    "planning",
    "researching",
    "recalling",
    "synthesizing",
    "reviewing",
    "reporting",
    "completed",
    "failed",
    "cancelled",
    "paused",
    "pause_requested",
    "archived",
)
EQUIPMENT_RUN_ACTIVE_STATUSES = (
    "queued",
    "planning",
    "researching",
    "recalling",
    "synthesizing",
    "reviewing",
    "reporting",
    "pause_requested",
)
EQUIPMENT_RUN_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "archived")
EQUIPMENT_RUN_STATUS_SQL = ", ".join(f"'{status}'" for status in EQUIPMENT_RUN_STATUSES)


def _json_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _artifact_counts(payload: dict[str, Any]) -> dict[str, int]:
    """统一新旧任务的产物计数投影。"""
    result = _json_object(payload.get("result"))
    counts = {str(key): _nonnegative_int(value) for key, value in _json_object(result.get("artifact_counts")).items()}
    counts.update(
        {str(key): _nonnegative_int(value) for key, value in _json_object(payload.get("artifact_counts")).items()}
    )
    aliases = {
        "sources": ("source_count", "sources_count"),
        "evidence": ("evidence_count",),
        "capabilities": ("capability_count", "capabilities_count"),
        "winning_steps": ("winning_step_count", "stage_count"),
        "deep_sessions": ("deep_session_count",),
    }
    for target, source_keys in aliases.items():
        if target in counts:
            continue
        for source in source_keys:
            if source in payload or source in result:
                counts[target] = _nonnegative_int(payload.get(source, result.get(source)))
                break

    # Historical workbench imports persist ``round_summary.json`` below the
    # payload's ``summary`` key.  Those runs predate the compact
    # ``artifact_counts`` contract, but the authoritative DomainStore counts
    # are still present in ``store_summary``.  Backfill only absent/zero values
    # so a newer explicit positive snapshot always remains authoritative.
    summary = _json_object(payload.get("summary")) or _json_object(result.get("summary"))
    store_summary = _json_object(summary.get("store_summary"))
    summary_aliases = {
        "sources": ("baseline_packet_count",),
        "evidence": ("materialized_evidence_count", "evidence_count"),
        "capabilities": ("capability_image_count",),
        "winning_steps": ("stage_output_count",),
        "reports": ("report_count",),
    }
    for target, source_keys in summary_aliases.items():
        if counts.get(target, 0) > 0:
            continue
        for source in source_keys:
            projected = _nonnegative_int(store_summary.get(source))
            if projected > 0:
                counts[target] = projected
                break

    has_report = bool(payload.get("has_report") or result.get("report_available") or result.get("report_path"))
    if counts.get("reports", 0) <= 0:
        counts["reports"] = 1 if has_report else 0
    return counts


class EquipmentResearchRun(Base):
    """装备研究任务事实表。"""

    __tablename__ = "equipment_research_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({EQUIPMENT_RUN_STATUS_SQL})", name="ck_equipment_research_runs_status"),
        Index("ix_equipment_research_runs_owner_updated", "owner_uid", "updated_at"),
        Index("ix_equipment_research_runs_project_status", "project_id", "status"),
        Index("ix_equipment_research_runs_legacy", "legacy_source_id"),
    )

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    topic = Column(Text, nullable=False)
    research_route = Column(String(64), nullable=False, default="auto")
    status = Column(String(32), nullable=False, default="draft")
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    legacy_source_id = Column(String(128), nullable=True)
    derived_from_legacy_run_id = Column(String(128), nullable=True)
    import_batch_id = Column(String(64), nullable=True)
    artifact_relpath = Column(String(1024), nullable=False, default="")
    artifact_sha256 = Column(String(64), nullable=False, default="")
    readonly = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        return {
            "run_id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "topic": self.topic,
            "research_route": self.research_route,
            "status": self.status,
            "payload": payload,
            "knowledge_enabled": payload.get("knowledge_enabled", True),
            # Three-state contract: None=all owner-visible, []=disabled,
            # non-empty=list that may only narrow the server-authorized set.
            "knowledge_ids": payload.get("knowledge_ids"),
            "supplemental_information": payload.get("supplemental_information", ""),
            "interaction_mode": payload.get("interaction_mode", "expert"),
            "discovery_branch": payload.get("discovery_branch", "auto"),
            "execution_profile_id": payload.get("execution_profile_id", ""),
            "report_template_mode": payload.get("report_template_mode", "three_layer_nine_item"),
            "selected_agent_ids": list(payload.get("selected_agent_ids") or []),
            "max_rounds": _positive_int(payload.get("max_rounds"), 2),
            "execution": _json_object(payload.get("execution")),
            "result": _json_object(payload.get("result")),
            "artifact_counts": _artifact_counts(payload),
            "source_query_id": payload.get("source_query_id"),
            "source_query_version": payload.get("source_query_version"),
            "error": self.error,
            "legacy_source_id": self.legacy_source_id,
            "derived_from_legacy_run_id": self.derived_from_legacy_run_id,
            "import_batch_id": self.import_batch_id,
            "artifact_relpath": self.artifact_relpath,
            "artifact_sha256": self.artifact_sha256,
            "readonly": bool(self.readonly),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentResearchEvent(Base):
    """装备研究业务事件；PostgreSQL 为最终事实，Redis 仅用于投递。"""

    __tablename__ = "equipment_research_events"
    __table_args__ = (Index("ix_equipment_research_events_run_seq", "run_id", "sequence"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(128),
        ForeignKey("equipment_research_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(128), nullable=False)
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload or {}),
            "created_at": format_utc_datetime(self.created_at),
        }


class EquipmentQuery(Base):
    """需求 Query。"""

    __tablename__ = "equipment_queries"
    __table_args__ = (
        UniqueConstraint("query_fingerprint", name="uq_equipment_queries_fingerprint"),
        Index("ix_equipment_queries_project_status", "project_id", "status"),
    )

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    query_text = Column(Text, nullable=False)
    query_fingerprint = Column(String(64), nullable=False)
    supplemental_information = Column(Text, nullable=False, default="")
    status = Column(String(32), nullable=False, default="draft")
    source_type = Column(String(32), nullable=False, default="manual")
    version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    legacy_source_id = Column(String(128), nullable=True)
    import_batch_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        return {
            "query_id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "query": self.query_text,
            "query_fingerprint": self.query_fingerprint,
            "supplemental_information": self.supplemental_information,
            "status": self.status,
            "source_type": self.source_type,
            "version": self.version,
            "payload": payload,
            "generation_id": payload.get("generation_id", ""),
            "generation_rationale": payload.get("generation_rationale", ""),
            "demand_chain": dict(payload.get("demand_chain") or {}),
            "quality_review": dict(payload.get("quality_review") or {}),
            "source_references": list(payload.get("source_references") or []),
            "source_disclaimer": "Query 生成参考线索，不等同于后续研究结论的正式证据。",
            "knowledge_enabled": payload.get("knowledge_enabled", True),
            "knowledge_ids": payload.get("knowledge_ids"),
            "legacy_source_id": self.legacy_source_id,
            "import_batch_id": self.import_batch_id,
            "readonly": bool(self.legacy_source_id or self.import_batch_id),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentQueryRevision(Base):
    """Query 修订记录。"""

    __tablename__ = "equipment_query_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(String(128), ForeignKey("equipment_queries.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    change_type = Column(String(64), nullable=False)
    snapshot = Column(JSON_VALUE, nullable=False, default=dict)
    changed_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.id,
            "query_id": self.query_id,
            "version": self.version,
            "change_type": self.change_type,
            "snapshot": dict(self.snapshot or {}),
            "changed_at": format_utc_datetime(self.changed_at),
        }


class EquipmentQueryGeneration(Base):
    """Query 生成任务。"""

    __tablename__ = "equipment_query_generations"

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    topic = Column(String(500), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    legacy_source_id = Column(String(128), nullable=True)
    import_batch_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        query_ids = list(payload.get("query_ids") or [])
        return {
            "generation_id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "topic": self.topic,
            "status": self.status,
            "payload": payload,
            "model_spec": payload.get("model_spec", ""),
            "model_config": {"model_spec": payload.get("model_spec", "")},
            "requested_count": payload.get("count", 0),
            "count": payload.get("count", 0),
            "stage": payload.get("stage", self.status),
            "reference_urls": list(payload.get("reference_urls") or []),
            "search_queries": list(payload.get("search_queries") or []),
            "source_references": list(payload.get("source_references") or []),
            "provider_snapshot": dict(payload.get("provider_snapshot") or {}),
            "attempts": int(payload.get("attempts") or 0),
            "query_ids": query_ids,
            "result_query_ids": query_ids,
            "knowledge_enabled": payload.get("knowledge_enabled", True),
            "knowledge_ids": payload.get("knowledge_ids"),
            "error": payload.get("error", ""),
            "legacy_source_id": self.legacy_source_id,
            "import_batch_id": self.import_batch_id,
            "readonly": bool(self.legacy_source_id or self.import_batch_id),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentCapabilityVersion(Base):
    """能力画像版本。"""

    __tablename__ = "equipment_capability_versions"

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    run_id = Column(String(128), ForeignKey("equipment_research_runs.id", ondelete="SET NULL"), nullable=True)
    snapshot = Column(JSON_VALUE, nullable=False, default=dict)
    legacy_source_id = Column(String(128), nullable=True)
    import_batch_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "run_id": self.run_id,
            "snapshot": dict(self.snapshot or {}),
            "legacy_source_id": self.legacy_source_id,
            "created_at": format_utc_datetime(self.created_at),
        }


class EquipmentFavorite(Base):
    """收藏。"""

    __tablename__ = "equipment_favorites"
    __table_args__ = (
        UniqueConstraint("owner_uid", "run_id", "card_key", name="uq_equipment_favorites_owner_run_card"),
    )

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    run_id = Column(String(128), ForeignKey("equipment_research_runs.id", ondelete="SET NULL"), nullable=True)
    card_key = Column(String(512), nullable=False)
    snapshot = Column(JSON_VALUE, nullable=False, default=dict)
    display_name = Column(String(400), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    tags = Column(JSON_VALUE, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        snapshot = dict(self.snapshot or {})
        source_run_id = str(self.run_id or snapshot.get("source_run_id") or snapshot.get("run_id") or "")
        return {
            "favorite_id": self.id,
            "id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "run_id": source_run_id,
            "card_key": self.card_key,
            "snapshot": snapshot,
            "display_name": self.display_name,
            "note": self.note,
            "tags": list(self.tags or []),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentExpertFeedback(Base):
    """专家反馈。"""

    __tablename__ = "equipment_expert_feedback"

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    run_id = Column(String(128), ForeignKey("equipment_research_runs.id", ondelete="CASCADE"), nullable=False)
    feedback = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)


class EquipmentDeepSession(Base):
    """深度思考会话。"""

    __tablename__ = "equipment_deep_sessions"

    id = Column(String(128), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    run_id = Column(String(128), ForeignKey("equipment_research_runs.id", ondelete="SET NULL"), nullable=True)
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    legacy_source_id = Column(String(128), nullable=True)
    import_batch_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        return {
            "session_id": self.id,
            "project_id": self.project_id,
            "owner_uid": self.owner_uid,
            "run_id": self.run_id,
            "payload": payload,
            "title": payload.get("title", "深研对话"),
            "topic": payload.get("topic", ""),
            "model_spec": payload.get("model_spec", ""),
            "status": payload.get("status", "active"),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentDeepMessage(Base):
    """深度思考消息。"""

    __tablename__ = "equipment_deep_messages"

    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), ForeignKey("equipment_deep_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False, default="")
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "payload": dict(self.payload or {}),
            "created_at": format_utc_datetime(self.created_at),
        }


class EquipmentDeepBranch(Base):
    """深度思考分支。"""

    __tablename__ = "equipment_deep_branches"

    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), ForeignKey("equipment_deep_sessions.id", ondelete="CASCADE"), nullable=False)
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        return {
            "branch_id": self.id,
            "session_id": self.session_id,
            "title": payload.get("title", "探索分支"),
            "child_session_id": payload.get("child_session_id", ""),
            "from_message_id": payload.get("from_message_id", ""),
            "payload": payload,
            "created_at": format_utc_datetime(self.created_at),
        }


class EquipmentDeepJob(Base):
    """深度思考作业。"""

    __tablename__ = "equipment_deep_jobs"

    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), ForeignKey("equipment_deep_sessions.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    updated_at = Column(DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload or {})
        return {
            "job_id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "payload": payload,
            "model_spec": payload.get("model_spec", ""),
            "error": payload.get("error", ""),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class EquipmentDeepSteer(Base):
    """深度思考纠偏。"""

    __tablename__ = "equipment_deep_steers"

    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), ForeignKey("equipment_deep_sessions.id", ondelete="CASCADE"), nullable=False)
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)


class EquipmentArtifactRef(Base):
    """研究产物相对路径与哈希。"""

    __tablename__ = "equipment_artifact_refs"

    id = Column(String(128), primary_key=True)
    run_id = Column(
        String(128),
        ForeignKey("equipment_research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path = Column(String(1024), nullable=False)
    sha256 = Column(String(64), nullable=False, default="")
    byte_size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.id,
            "run_id": self.run_id,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "created_at": format_utc_datetime(self.created_at),
        }


class EquipmentLegacyImportBatch(Base):
    """历史 SQLite 导入批次。"""

    __tablename__ = "equipment_legacy_import_batches"

    id = Column(String(64), primary_key=True)
    owner_uid = Column(String(64), ForeignKey("users.uid", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(32), nullable=False, default="imported")
    report = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    rolled_back_at = Column(DateTime, nullable=True)
