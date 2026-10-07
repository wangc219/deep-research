"""装备研究 HTTP 适配层。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config.options import invalidate_option_cache, system_options, update_option_value
from platform_core.services import equipment_research_service as svc
from platform_core.services.equipment_research_task import (
    EQUIPMENT_RESEARCH_CAPACITY_LIMIT,
    EQUIPMENT_RESEARCH_TASK_TYPE,
)
from platform_core.services.task_queue_service import publish_pending_tasks
from platform_core.storage.postgres.models_business import TaskRecord, User
from server.utils.auth_middleware import get_admin_user, get_db, get_required_user

equipment = APIRouter(prefix="/equipment", tags=["equipment"])


class EquipmentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    topic: str
    research_route: str = "auto"
    model_spec: str | None = None
    source_query_id: str | None = Field(default=None, max_length=128)
    source_query_version: int | None = Field(default=None, ge=1)
    knowledge_enabled: bool = True
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)
    supplemental_information: str = Field(default="", max_length=8000)
    interaction_mode: str = Field(default="expert", pattern="^(expert|autonomous)$")
    discovery_branch: str = Field(default="auto", pattern="^(auto|A|B|C|D|E|F|G|H)$")
    execution_profile_id: str = Field(default="", max_length=64)
    report_template_mode: str = Field(default="three_layer_nine_item", max_length=64)
    selected_agent_ids: list[str] = Field(default_factory=list, max_length=32)
    max_rounds: int = Field(default=2, ge=1, le=8)
    payload: dict[str, Any] = Field(default_factory=dict)


class EquipmentRunUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = None
    research_route: str | None = None
    model_spec: str | None = None
    knowledge_enabled: bool | None = None
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)
    payload: dict[str, Any] | None = None


class EquipmentResearchCapacityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int = Field(ge=1, le=EQUIPMENT_RESEARCH_CAPACITY_LIMIT)


class EquipmentQueryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    query: str
    supplemental_information: str = ""
    generation_rationale: str = Field(default="", max_length=2000)
    source_references: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    status: Literal["draft", "published"] = "draft"
    knowledge_enabled: bool = True
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)


class EquipmentQueryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    query: str | None = Field(default=None, min_length=1, max_length=4000)
    supplemental_information: str | None = Field(default=None, max_length=8000)
    generation_rationale: str | None = Field(default=None, max_length=2000)
    source_references: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    knowledge_enabled: bool | None = None
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)


class EquipmentQueryStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, ge=1)


class EquipmentQueryBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_ids: list[str] = Field(min_length=1, max_length=100)
    status: Literal["draft", "published", "archived"]
    versions: dict[str, int] = Field(default_factory=dict)


class EquipmentQueryGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    topic: str
    supplemental_information: str = ""
    reference_urls: list[str] = Field(default_factory=list, max_length=12)
    count: int = Field(default=6, ge=1, le=20)
    model_spec: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    knowledge_enabled: bool = True
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)


class EquipmentCapabilitySection(BaseModel):
    """One authored column of a capability portrait card."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="", max_length=64)
    text: str = Field(default="", max_length=4000)


class EquipmentReferenceWeapon(BaseModel):
    """深研会话绑定的服务器已知参考武器。"""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(min_length=1, max_length=256)
    title: str = Field(default="", max_length=400)
    primary_equipment_identity: str = Field(default="", max_length=400)
    equipment_forms: list[str] = Field(default_factory=list, max_length=8)
    overview: str = Field(default="", max_length=3000)
    score: float | None = None


class EquipmentDeepSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    title: str = ""
    topic: str = ""
    focus: str = ""
    run_id: str | None = None
    model_spec: str | None = None
    agent_slug: str | None = None
    knowledge_enabled: bool = True
    knowledge_ids: list[str] | None = Field(default=None, max_length=64)
    subagents_enabled: bool = True
    active_skill_ids: list[str] = Field(default_factory=list, max_length=12)
    research_mode: Literal["section_deepen", "new_weapon_diverge"] = "section_deepen"
    research_section: str = Field(default="", max_length=64)
    source_feedback_id: str = Field(default="", max_length=128)
    # Set when the session is opened from a capability card so a reopened
    # transcript still knows which card it drills into.
    capability_card_key: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)
    capability_sections: list[EquipmentCapabilitySection] = Field(default_factory=list, max_length=8)
    reference_weapons: list[EquipmentReferenceWeapon] = Field(default_factory=list, max_length=8)


class EquipmentDeepSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=240)
    archived: bool | None = None


class EquipmentDeepMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    model_spec: str | None = None
    focus: str = ""
    create_artifact: bool = False
    active_skill_ids: list[str] = Field(default_factory=list, max_length=12)


class EquipmentDeepBranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_message_id: str = ""
    title: str = "探索分支"


class EquipmentCapabilityVerify(BaseModel):
    """深研能力画像版本核验。"""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        default="verified",
        pattern="^(verified|rejected|rolled_back|pending_verification)$",
    )


class EquipmentExpertFeedbackCreate(BaseModel):
    """与 React 工作台相同口径的专家评分反馈。"""

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(default="", max_length=256)
    hypothesis_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="本任务整体能力画像", max_length=400)
    comment: str = Field(min_length=1, max_length=4000)
    verdict: str = Field(default="needs_revision", pattern="^(approved|needs_revision|rejected)$")
    rating: int | None = Field(default=None, ge=1, le=5)
    dimensions: list[str] = Field(default_factory=list, max_length=16)
    target_agent_ids: list[str] = Field(default_factory=list, max_length=16)
    stage_scope: list[str] = Field(default_factory=list, max_length=16)
    model_dimension_scores: dict[str, float] = Field(default_factory=dict)
    expert_dimension_scores: dict[str, float] = Field(default_factory=dict)
    expert_weighted_score: float | None = Field(default=None, ge=0.0, le=1.0)
    rubric_feedback: dict[str, str] = Field(default_factory=dict, max_length=5)
    rubric_version: str = Field(default="s5_five_dimension_v1", max_length=64)
    reviewer_role: str = Field(default="expert", max_length=64)


class EquipmentExpertFeedbackRollback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1000)


class EquipmentFavoriteCreate(BaseModel):
    """收藏请求只携带服务器可校验的卡片标识。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    card_key: str = Field(default="", max_length=512)
    card_binding_id: str = Field(default="", max_length=256)
    card_id: str = Field(default="", max_length=256)
    capability_id: str = Field(default="", max_length=256)
    capability_name: str = Field(default="", max_length=400)


class EquipmentFavoriteUpdate(BaseModel):
    """收藏快照不可修改，只允许更新个人展示字段。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=20)


async def _research_runtime_snapshot(db: AsyncSession, user: User) -> dict[str, Any]:
    options = await system_options.get(db)
    configured_capacity = min(
        max(int(options.get("equipment_research_max_running") or 1), 1),
        EQUIPMENT_RESEARCH_CAPACITY_LIMIT,
    )
    count_rows = await db.execute(
        select(TaskRecord.status, func.count(TaskRecord.id))
        .where(TaskRecord.type == EQUIPMENT_RESEARCH_TASK_TYPE)
        .group_by(TaskRecord.status)
    )
    counts = {str(status): int(count) for status, count in count_rows.all()}
    active_records = list(
        (
            await db.scalars(
                select(TaskRecord)
                .where(
                    TaskRecord.type == EQUIPMENT_RESEARCH_TASK_TYPE,
                    TaskRecord.status == "running",
                )
                .order_by(TaskRecord.started_at.asc(), TaskRecord.created_at.asc())
            )
        ).all()
    )
    active_tasks = []
    for record in active_records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        active_tasks.append(
            {
                "task_id": record.id,
                "run_id": str(payload.get("run_id") or ""),
                "started_at": record.started_at,
            }
        )
    active_count = len(active_tasks)
    return {
        "configured_capacity": configured_capacity,
        "capacity_limit": EQUIPMENT_RESEARCH_CAPACITY_LIMIT,
        "active_count": active_count,
        "available_slots": max(0, configured_capacity - active_count),
        "pending_count": counts.get("pending", 0),
        "parallel_enabled": configured_capacity > 1,
        "can_manage": user.role in {"admin", "superadmin"},
        "active_tasks": active_tasks,
    }


@equipment.get("/portal")
async def get_portal(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    """登录后领域知识总门户聚合数据。"""
    return await svc.portal_snapshot(db=db, user=current_user)


@equipment.get("/runtime")
async def get_research_runtime(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """返回研究任务的实时并行容量与排队状态。"""

    return await _research_runtime_snapshot(db, current_user)


@equipment.put("/runtime/capacity")
async def update_research_capacity(
    body: EquipmentResearchCapacityUpdate,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """热更新研究任务容量；缩容不会取消已经取得 lease 的任务。"""

    await update_option_value(
        db,
        system_options.key,
        {"equipment_research_max_running": body.capacity},
        current_user.username,
    )
    await db.commit()
    await invalidate_option_cache(system_options.key)
    # 旧容量下已消费但未 claim 的 ARQ 消息可能已经结束；扩容后立即补发 pending intent。
    await publish_pending_tasks()
    return await _research_runtime_snapshot(db, current_user)


@equipment.get("/runs")
async def list_runs(
    project_id: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_runs(db=db, user=current_user, project_id=project_id, status=status)


@equipment.post("/runs")
async def create_run(
    body: EquipmentRunCreate,
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    # Keep legacy payload callers working while making the canonical fields
    # first-class.  ``model_fields_set`` is essential here: omitted means
    # "use the payload/query default", whereas an explicit null knowledge_ids
    # means "all knowledge bases currently visible to the eventual run owner".
    payload = dict(body.payload)
    if "knowledge_enabled" in body.model_fields_set:
        payload["knowledge_enabled"] = body.knowledge_enabled
    if "knowledge_ids" in body.model_fields_set:
        payload["knowledge_ids"] = body.knowledge_ids
    payload.update(
        {
            "supplemental_information": body.supplemental_information,
            "interaction_mode": body.interaction_mode,
            "discovery_branch": body.discovery_branch,
            "execution_profile_id": body.execution_profile_id,
            "report_template_mode": body.report_template_mode,
            "selected_agent_ids": body.selected_agent_ids,
            "max_rounds": body.max_rounds,
        }
    )
    return await svc.create_run(
        db=db,
        user=current_user,
        project_id=body.project_id,
        topic=body.topic,
        research_route=body.research_route,
        model_spec=body.model_spec,
        payload=payload,
        source_query_id=body.source_query_id,
        source_query_version=body.source_query_version,
        idempotency_key=idempotency_key,
    )


@equipment.get("/runs/{run_id}")
async def get_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.get_run(db=db, user=current_user, run_id=run_id)


@equipment.get("/runs/{run_id}/interactions")
async def get_run_interactions(
    run_id: str,
    compact: bool = Query(True),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_run_interactions(
        db=db,
        user=current_user,
        run_id=run_id,
        compact=compact,
    )


@equipment.get("/runs/{run_id}/evidence")
async def list_run_evidence(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_run_evidence(db=db, user=current_user, run_id=run_id)


@equipment.get("/runs/{run_id}/winning-mechanism")
async def get_run_winning_mechanism(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_run_winning_mechanism(db=db, user=current_user, run_id=run_id)


@equipment.get("/runs/{run_id}/report", response_class=PlainTextResponse)
async def get_report(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_report(db=db, user=current_user, run_id=run_id)


@equipment.patch("/runs/{run_id}")
async def update_run(
    run_id: str,
    body: EquipmentRunUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    # ``exclude_unset`` preserves the three knowledge scope states:
    # omitted=unchanged, null=all currently visible, []=none.
    return await svc.update_run(
        db=db,
        user=current_user,
        run_id=run_id,
        patch=body.model_dump(exclude_unset=True),
    )


@equipment.post("/runs/{run_id}/start")
async def start_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.start_run(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.pause_run(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.resume_run(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.cancel_run(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/archive")
async def archive_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.archive_run(db=db, user=current_user, run_id=run_id)


@equipment.delete("/runs/{run_id}")
async def delete_run(run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.delete_run(db=db, user=current_user, run_id=run_id)


@equipment.get("/runs/{run_id}/events")
async def list_events(
    run_id: str,
    after_seq: int = Query(0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_events(db=db, user=current_user, run_id=run_id, after_seq=after_seq)


@equipment.get("/queries")
async def list_queries(
    project_id: str | None = None,
    status: Literal["draft", "published", "archived"] | None = None,
    source_type: Literal["manual", "agent", "import", "imported"] | None = None,
    search: str = Query(default="", max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_queries(
        db=db,
        user=current_user,
        project_id=project_id,
        status=status,
        source_type=source_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@equipment.post("/queries")
async def create_query(
    body: EquipmentQueryCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_query(
        db=db,
        user=current_user,
        project_id=body.project_id,
        query_text=body.query,
        supplemental_information=body.supplemental_information,
        generation_rationale=body.generation_rationale,
        source_references=body.source_references,
        status=body.status,
        knowledge_enabled=body.knowledge_enabled,
        knowledge_ids=body.knowledge_ids,
    )


@equipment.get("/queries/{query_id}")
async def get_query(
    query_id: str,
    include_revisions: bool = True,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_query(
        db=db,
        user=current_user,
        query_id=query_id,
        include_revisions=include_revisions,
    )


@equipment.patch("/queries/{query_id}")
async def update_query(
    query_id: str,
    body: EquipmentQueryUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.update_query(
        db=db,
        user=current_user,
        query_id=query_id,
        changes=body.model_dump(exclude_unset=True),
    )


@equipment.post("/queries/{query_id}/publish")
async def publish_query(
    query_id: str,
    body: EquipmentQueryStatus | None = None,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.publish_query(
        db=db,
        user=current_user,
        query_id=query_id,
        expected_version=body.expected_version if body is not None else None,
    )


@equipment.post("/queries/{query_id}/archive")
async def archive_query(
    query_id: str,
    body: EquipmentQueryStatus | None = None,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.archive_query(
        db=db,
        user=current_user,
        query_id=query_id,
        expected_version=body.expected_version if body is not None else None,
    )


@equipment.delete("/queries/{query_id}")
async def delete_query(
    query_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.delete_query(db=db, user=current_user, query_id=query_id)


@equipment.post("/queries/bulk-status")
async def bulk_set_query_status(
    body: EquipmentQueryBulkStatus,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.bulk_set_query_status(
        db=db,
        user=current_user,
        query_ids=body.query_ids,
        status=body.status,
        versions=body.versions,
    )


@equipment.get("/query-model-options")
async def get_query_model_options(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    del current_user
    return await svc.get_query_model_options(db=db)


@equipment.post("/query-generations")
async def submit_query_generation(
    body: EquipmentQueryGenerate,
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.submit_query_generation(
        db=db,
        user=current_user,
        project_id=body.project_id,
        topic=body.topic,
        supplemental_information=body.supplemental_information,
        reference_urls=body.reference_urls,
        count=body.count,
        model_spec=body.model_spec or str(body.model_settings.get("model_spec") or "") or None,
        knowledge_enabled=body.knowledge_enabled,
        knowledge_ids=body.knowledge_ids,
        idempotency_key=idempotency_key,
    )


@equipment.get("/query-generations")
async def list_query_generations(
    project_id: str | None = None,
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_query_generations(
        db=db,
        user=current_user,
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@equipment.get("/query-generations/{generation_id}")
async def get_query_generation(
    generation_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    return await svc.get_query_generation(db=db, user=current_user, generation_id=generation_id)


@equipment.post("/query-generations/{generation_id}/cancel")
async def cancel_query_generation(
    generation_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.cancel_query_generation(db=db, user=current_user, generation_id=generation_id)


@equipment.post("/query-generations/{generation_id}/retry")
async def retry_query_generation(
    generation_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.retry_query_generation(db=db, user=current_user, generation_id=generation_id)


@equipment.delete("/query-generations/{generation_id}")
async def delete_query_generation(
    generation_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.delete_query_generation(db=db, user=current_user, generation_id=generation_id)


@equipment.get("/capabilities")
async def list_capabilities(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.list_capabilities(db=db, user=current_user)


@equipment.get("/runs/{run_id}/capability-versions")
async def list_capability_versions(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_capability_versions_for_run(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/capability-versions/{version_id}/verify")
async def verify_capability_version(
    run_id: str,
    version_id: str,
    body: EquipmentCapabilityVerify,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.mutate_capability_version(
        db=db,
        user=current_user,
        run_id=run_id,
        version_id=version_id,
        action="verify",
        verification_status=body.status,
    )


@equipment.delete("/runs/{run_id}/capability-versions/{version_id}")
async def delete_capability_version(
    run_id: str,
    version_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.mutate_capability_version(
        db=db, user=current_user, run_id=run_id, version_id=version_id, action="delete"
    )


@equipment.post("/runs/{run_id}/capability-versions/{version_id}/restore")
async def restore_capability_version(
    run_id: str,
    version_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.mutate_capability_version(
        db=db, user=current_user, run_id=run_id, version_id=version_id, action="restore"
    )


@equipment.delete("/runs/{run_id}/capability-versions/{version_id}/permanent")
async def purge_capability_version(
    run_id: str,
    version_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.mutate_capability_version(
        db=db, user=current_user, run_id=run_id, version_id=version_id, action="purge"
    )


@equipment.get("/runs/{run_id}/expert-feedback")
async def list_expert_feedback(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_expert_feedback(db=db, user=current_user, run_id=run_id)


@equipment.post("/runs/{run_id}/expert-feedback")
async def create_expert_feedback(
    run_id: str,
    body: EquipmentExpertFeedbackCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_expert_feedback(
        db=db,
        user=current_user,
        run_id=run_id,
        feedback=body.model_dump(),
    )


@equipment.post("/runs/{run_id}/expert-feedback/{feedback_id}/rollback")
async def rollback_expert_feedback(
    run_id: str,
    feedback_id: str,
    body: EquipmentExpertFeedbackRollback,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.rollback_expert_feedback(
        db=db,
        user=current_user,
        run_id=run_id,
        feedback_id=feedback_id,
        reason=body.reason,
    )


@equipment.get("/favorites")
async def list_favorites(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str = Query(default="", max_length=400),
    capability_type: str = Query(default="", max_length=64),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_favorites(
        db=db,
        user=current_user,
        offset=offset,
        limit=limit,
        search=search,
        capability_type=capability_type,
    )


@equipment.post("/favorites")
async def create_favorite(
    body: EquipmentFavoriteCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    payload = body.model_dump()
    run_id = payload.pop("run_id")
    return await svc.create_favorite(
        db=db,
        user=current_user,
        run_id=run_id,
        card_identifiers=payload,
    )


@equipment.get("/favorites/{favorite_id}")
async def get_favorite(
    favorite_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_favorite(db=db, user=current_user, favorite_id=favorite_id)


@equipment.patch("/favorites/{favorite_id}")
async def update_favorite(
    favorite_id: str,
    body: EquipmentFavoriteUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.update_favorite(
        db=db,
        user=current_user,
        favorite_id=favorite_id,
        changes=body.model_dump(exclude_unset=True),
    )


@equipment.delete("/favorites/{favorite_id}")
async def delete_favorite(
    favorite_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.delete_favorite(db=db, user=current_user, favorite_id=favorite_id)


@equipment.get("/deep-thinking")
async def list_deep_sessions(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    return await svc.list_deep_sessions(db=db, user=current_user)


@equipment.get("/deep-thinking/context-options")
async def get_deep_context_options(
    run_id: str = Query(..., min_length=1, max_length=128),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_deep_context_options(db=db, user=current_user, run_id=run_id)


@equipment.post("/deep-thinking")
async def create_deep_session(
    body: EquipmentDeepSessionCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_deep_session(
        db=db,
        user=current_user,
        project_id=body.project_id,
        title=body.title,
        topic=body.topic,
        focus=body.focus,
        run_id=body.run_id,
        model_spec=body.model_spec,
        agent_slug=body.agent_slug,
        knowledge_enabled=body.knowledge_enabled,
        knowledge_ids=body.knowledge_ids,
        subagents_enabled=body.subagents_enabled,
        active_skill_ids=body.active_skill_ids,
        research_mode=body.research_mode,
        research_section=body.research_section,
        source_feedback_id=body.source_feedback_id,
        capability_card_key=body.capability_card_key,
        capability_name=body.capability_name,
        capability_sections=[item.model_dump() for item in body.capability_sections],
        reference_weapons=[item.model_dump() for item in body.reference_weapons],
    )


@equipment.get("/deep-thinking/{session_id}")
async def get_deep_session(
    session_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    return await svc.get_deep_session(db=db, user=current_user, session_id=session_id)


@equipment.patch("/deep-thinking/{session_id}")
async def update_deep_session(
    session_id: str,
    body: EquipmentDeepSessionUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.update_deep_session(
        db=db,
        user=current_user,
        session_id=session_id,
        changes=body.model_dump(exclude_unset=True),
    )


@equipment.delete("/deep-thinking/{session_id}")
async def delete_deep_session(
    session_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.delete_deep_session(db=db, user=current_user, session_id=session_id)


@equipment.post("/deep-thinking/{session_id}/messages")
async def send_deep_message(
    session_id: str,
    body: EquipmentDeepMessageCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.send_deep_message(
        db=db,
        user=current_user,
        session_id=session_id,
        content=body.content,
        model_spec=body.model_spec,
        focus=body.focus,
        create_artifact=body.create_artifact,
        active_skill_ids=body.active_skill_ids,
    )


@equipment.post("/deep-thinking/{session_id}/branches")
async def fork_deep_session(
    session_id: str,
    body: EquipmentDeepBranchCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.fork_deep_session(
        db=db,
        user=current_user,
        session_id=session_id,
        from_message_id=body.from_message_id,
        title=body.title,
    )


@equipment.get("/reports")
async def list_reports(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    runs = await svc.list_runs(db=db, user=current_user, status="completed")
    return [
        {"run_id": item["run_id"], "topic": item["topic"], "artifact_relpath": item["artifact_relpath"]}
        for item in runs
    ]
