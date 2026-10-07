"""装备研究用例：状态由 PostgreSQL 拥有，Durable Task 仅携带 run_id。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from platform_core.permissions import (
    ResourcePermission,
    has_global_business_access,
    is_shared_legacy_resource,
    resolve_personal_resource_permission,
)
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.repositories.project_repository import ProjectRepository
from platform_core.repositories.user_repository import UserRepository
from platform_core.services.equipment_capability_scoring import enrich_capabilities_with_s5_scores
from platform_core.services.personal_resource_audit_service import audit_superadmin_personal_resource_write
from platform_core.services.task_queue_service import publish_task
from platform_core.services.task_service import Tasker
from platform_core.storage.postgres.models_business import AGENT_RUN_TERMINAL_STATUSES, User
from platform_core.storage.postgres.models_equipment import (
    EQUIPMENT_RUN_ACTIVE_STATUSES,
    EquipmentCapabilityVersion,
    EquipmentDeepBranch,
    EquipmentDeepJob,
    EquipmentDeepMessage,
    EquipmentDeepSession,
    EquipmentExpertFeedback,
    EquipmentFavorite,
    EquipmentQuery,
    EquipmentQueryGeneration,
    EquipmentQueryRevision,
    EquipmentResearchRun,
)
from platform_core.storage.redis import get_async_redis_client
from platform_core.utils.datetime_utils import utc_now_naive
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

EQUIPMENT_RESEARCH_TASK_TYPE = "equipment_research"
STARTABLE = {"draft", "paused"}
CANCELLABLE = set(EQUIPMENT_RUN_ACTIVE_STATUSES) | {"paused"}
DELETABLE = {"draft", "queued", "completed", "failed", "cancelled", "archived"}
logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _canonical_knowledge_scope(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a persisted, validation-safe knowledge scope.

    ``knowledge_ids`` is deliberately not an authorization grant.  It is a
    launch-time upper bound that the knowledge service later intersects with
    the run owner's live permissions.  Keeping ``None`` and ``[]`` distinct
    here prevents an empty selection from silently becoming "all visible".
    """

    canonical = dict(payload or {})
    enabled = canonical.get("knowledge_enabled", True)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="knowledge_enabled 必须是布尔值")

    raw_ids = canonical.get("knowledge_ids", canonical.get("knowledges"))
    if raw_ids is None:
        knowledge_ids: list[str] | None = None
    else:
        if not isinstance(raw_ids, list | tuple):
            raise HTTPException(status_code=422, detail="knowledge_ids 必须是数组或 null")
        knowledge_ids = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, str):
                raise HTTPException(status_code=422, detail="knowledge_ids 只能包含字符串")
            knowledge_id = raw_id.strip()
            if not knowledge_id or knowledge_id in knowledge_ids:
                continue
            if len(knowledge_id) > 256:
                raise HTTPException(status_code=422, detail="knowledge_ids 项过长")
            knowledge_ids.append(knowledge_id)
        if len(knowledge_ids) > 64:
            raise HTTPException(status_code=422, detail="knowledge_ids 最多包含 64 项")

    canonical["knowledge_enabled"] = enabled
    canonical["knowledge_ids"] = knowledge_ids
    return canonical


def _canonical_query_source_references(value: Any) -> list[dict[str, str]]:
    """规范化 Query 来源快照，保持平台 API 与历史 Query 契约一致。"""

    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise HTTPException(status_code=422, detail="source_references 必须是数组")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="source_references 项必须是对象")
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="Query 来源标题不能为空")
        source_kind = "document" if str(raw.get("source_kind") or "web") == "document" else "web"
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "title": title[:500],
                "url": url[:3000],
                "accessed_at": str(raw.get("accessed_at") or "")[:64],
                "relevance_note": str(raw.get("relevance_note") or "")[:1000],
                "source_kind": source_kind,
            }
        )
        if len(result) >= 20:
            break
    return result


async def _publish_stream(run_id: str, event: dict[str, Any]) -> None:
    client = await get_async_redis_client()
    await client.xadd(
        f"equipment:events:{run_id}",
        {"payload": json.dumps(event, ensure_ascii=False)},
        maxlen=5000,
        approximate=True,
    )


async def _require_project(db: AsyncSession, *, user: User, project_id: str):
    """解析当前用户可管理的 Project；全局管理员保留项目真实所有者。"""

    repo = ProjectRepository(db)
    project = (
        await repo.get_by_id(project_id)
        if has_global_business_access(user)
        else await repo.get_for_user(project_id, user.uid)
    )
    if project is None or project.status != "active":
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    return project


async def _require_run(
    db: AsyncSession,
    *,
    user: User,
    run_id: str,
    lock: bool = False,
    mutation: bool = False,
) -> EquipmentResearchRun:
    repo = EquipmentResearchRepository(db)
    run = await repo.lock_run(run_id) if lock else await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    permission = resolve_personal_resource_permission(
        user,
        run.owner_uid,
        shared_legacy=is_shared_legacy_resource(run),
    )
    if permission == ResourcePermission.NONE:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    if mutation and permission != ResourcePermission.MANAGE:
        raise HTTPException(status_code=403, detail="无权修改该研究任务")
    return run


def _run_payload_for_user(run: EquipmentResearchRun, user: User) -> dict[str, Any]:
    """保留历史来源标识，但由当前用户的真实权限决定是否只读。"""

    payload = run.to_dict()
    permission = resolve_personal_resource_permission(
        user,
        run.owner_uid,
        shared_legacy=is_shared_legacy_resource(run),
    )
    payload["historical_snapshot"] = bool(
        getattr(run, "readonly", False)
        or getattr(run, "legacy_source_id", None)
        or getattr(run, "import_batch_id", None)
    )
    payload["readonly"] = permission != ResourcePermission.MANAGE
    return payload


async def _require_query(
    db: AsyncSession,
    *,
    user: User,
    query_id: str,
    mutation: bool = False,
    lock: bool = False,
) -> EquipmentQuery:
    """Resolve one personal Query without leaking foreign-resource presence."""

    repo = EquipmentResearchRepository(db)
    query = await repo.lock_query(query_id) if lock else await repo.get_query(query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="Query 不存在")
    permission = resolve_personal_resource_permission(
        user,
        query.owner_uid,
        shared_legacy=is_shared_legacy_resource(query),
    )
    if permission == ResourcePermission.NONE:
        raise HTTPException(status_code=404, detail="Query 不存在")
    if mutation and permission != ResourcePermission.MANAGE:
        raise HTTPException(status_code=403, detail="无权修改该 Query")
    if mutation and bool(getattr(query, "legacy_source_id", None) or getattr(query, "import_batch_id", None)):
        raise HTTPException(status_code=409, detail="历史 Query 为只读数据")
    return query


async def create_run(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    topic: str,
    research_route: str = "auto",
    model_spec: str | None = None,
    payload: dict[str, Any] | None = None,
    source_query_id: str | None = None,
    source_query_version: int | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    if not topic.strip():
        raise HTTPException(status_code=422, detail="研究主题不能为空")
    project = await _require_project(db, user=user, project_id=project_id)
    normalized_idempotency_key = str(idempotency_key or "").strip()
    request_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "project_id": project_id,
                "topic": topic.strip(),
                "research_route": research_route or "auto",
                "model_spec": str(model_spec or "").strip(),
                "payload": payload or {},
                "source_query_id": source_query_id,
                "source_query_version": source_query_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    repo = EquipmentResearchRepository(db)
    run_id = _new_id("run")
    if normalized_idempotency_key:
        digest = hashlib.sha256(f"{project.uid}:{project.id}:{normalized_idempotency_key}".encode()).hexdigest()
        run_id = f"run-{digest[:32]}"
        replay = await repo.get_run(run_id)
        if replay is not None:
            if str(replay.owner_uid) != str(project.uid) or str(replay.project_id) != str(project.id):
                raise HTTPException(status_code=409, detail="幂等键已被其他资源占用")
            previous_fingerprint = str((replay.payload or {}).get("idempotency_fingerprint") or "")
            if previous_fingerprint and previous_fingerprint != request_fingerprint:
                raise HTTPException(status_code=409, detail="幂等键已用于不同的研究任务参数")
            return replay.to_dict()
    run_payload = dict(payload or {})
    payload_source_query_id = run_payload.pop("source_query_id", None)
    payload_source_query_version = run_payload.pop("source_query_version", None)
    normalized_source_query_id = str(source_query_id or payload_source_query_id or "").strip()
    effective_source_query_version = (
        source_query_version if source_query_version is not None else payload_source_query_version
    )
    if normalized_source_query_id:
        source_query = await _require_query(
            db,
            user=user,
            query_id=normalized_source_query_id,
        )
        # A Query may only seed a Run in the same owner/project domain.  This
        # keeps a superadmin operation global without ever transferring the
        # source owner's resource scope to another user.
        if str(source_query.owner_uid) != str(project.uid) or str(source_query.project_id) != str(project.id):
            raise HTTPException(status_code=422, detail="来源 Query 不属于目标项目")
        if source_query.status != "published":
            raise HTTPException(status_code=409, detail="来源 Query 必须先发布")
        if effective_source_query_version is not None:
            try:
                requested_source_version = int(effective_source_query_version)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="来源 Query 版本无效") from exc
            if int(source_query.version) != requested_source_version:
                raise HTTPException(status_code=409, detail="来源 Query 版本已变化")
        query_payload = dict(source_query.payload or {})
        for key in ("knowledge_enabled", "knowledge_ids"):
            if key not in run_payload and key in query_payload:
                run_payload[key] = query_payload[key]
        run_payload["source_query_id"] = source_query.id
        run_payload["source_query_version"] = int(source_query.version)
        run_payload["query_library"] = {
            "query_id": source_query.id,
            "version": int(source_query.version),
            "source_type": source_query.source_type,
        }
    run_payload = _canonical_knowledge_scope(run_payload)
    from platform_core.services.equipment_model_adapter import default_chat_model_spec

    requested_spec = str(model_spec or run_payload.get("model_spec") or "").strip()
    resolved_spec = requested_spec or await default_chat_model_spec(db)
    if resolved_spec:
        from platform_core.services.equipment_model_adapter import resolve_equipment_model

        try:
            resolved_spec = resolve_equipment_model(resolved_spec)["model_spec"]
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    run = EquipmentResearchRun(
        id=run_id,
        project_id=project_id,
        owner_uid=str(project.uid),
        topic=topic.strip(),
        research_route=research_route or "auto",
        status="draft",
        payload={
            **run_payload,
            "workdir_path": project.workdir_path,
            "directory_mode": project.directory_mode,
            "model_spec": resolved_spec,
            **({"idempotency_fingerprint": request_fingerprint} if normalized_idempotency_key else {}),
        },
    )
    await repo.add_run(run)
    event = await repo.append_event(run.id, "run_created", {"status": "draft", "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def list_runs(*, db: AsyncSession, user: User, project_id: str | None = None, status: str | None = None):
    repo = EquipmentResearchRepository(db)
    runs = await repo.list_runs_for_user(
        owner_uid=None if has_global_business_access(user) else user.uid,
        project_id=project_id,
        status=status,
        include_legacy=True,
    )
    return [_run_payload_for_user(item, user) for item in runs]


async def get_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id)
    return _run_payload_for_user(run, user)


async def get_report(*, db: AsyncSession, user: User, run_id: str) -> str:
    """读取已授权任务的 Markdown 报告，包括迁移后的旧版产物。"""

    run = await _require_run(db, user=user, run_id=run_id)
    for run_root in _research_run_roots(run):
        try:
            resolved_root = run_root.resolve(strict=False)
        except OSError:
            continue
        for filename in ("report-postfix.md", "report.md"):
            candidate = run_root / filename
            if not candidate.is_file() or candidate.is_symlink():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_root)
                return resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError, ValueError):
                logger.warning("读取研究报告失败：%s", candidate, exc_info=True)
    raise HTTPException(status_code=404, detail="研究报告不存在或暂不可读")


async def get_run_interactions(
    *,
    db: AsyncSession,
    user: User,
    run_id: str,
    compact: bool = True,
) -> dict[str, Any]:
    """读取研究交互回放，兼容旧产物目录与平台 Project 工作目录。"""

    run = await _require_run(db, user=user, run_id=run_id)
    trace_rows, summary = await asyncio.to_thread(_load_run_trace_and_summary, run)
    events = [
        event
        for index, row in enumerate(trace_rows)
        if (event := _normalize_research_interaction(row, index=index, run_id=run.id)) is not None
    ]

    # 新平台任务会先把生命周期事件写入 PostgreSQL，再异步形成文件产物。
    # trace 尚未出现时仍应给 Vue 工作台完整、可回放的运行状态。
    if not events:
        events = await _load_postgres_interactions(db, run_id=run.id)
    events = _dedupe_research_interactions(events)
    visible_events = _compact_research_interactions(events) if compact else events
    workflow = _research_interaction_workflow(events, run=run, summary=summary)
    agents = _research_interaction_agents(events, run=run, summary=summary, workflow=workflow)
    return {
        "run_id": run.id,
        "agents": agents,
        "events": visible_events,
        "workflow": workflow,
        "counts": {
            "events": len(events),
            "visible_events": len(visible_events),
            "active_agents": len(workflow["active_agent_ids"]),
            "tool_calls": sum(item["event_type"] == "tool_call" for item in events),
            "tool_results": sum(item["event_type"] == "tool_result" for item in events),
            "savepoints": sum(item["event_type"] == "savepoint" for item in events),
        },
    }


async def list_run_evidence(*, db: AsyncSession, user: User, run_id: str) -> list[dict[str, Any]]:
    """返回任务的 EvidenceCard；没有旧产物时返回空数组而非 404。"""

    run = await _require_run(db, user=user, run_id=run_id)
    rows = await asyncio.to_thread(_load_run_jsonl, run, "domain.jsonl")
    return [
        payload for row in rows if row.get("type") == "EvidenceCard" and isinstance(payload := row.get("payload"), dict)
    ]


async def get_run_winning_mechanism(
    *,
    db: AsyncSession,
    user: User,
    run_id: str,
) -> dict[str, Any]:
    """重建 React 工作台使用的 S1-S6 制胜机理聚合结构。"""

    run = await _require_run(db, user=user, run_id=run_id)
    domain_rows, trace_rows, summary = await asyncio.to_thread(_load_run_domain_trace_and_summary, run)
    grouped: dict[str, Any] = {
        "inputs": [],
        "resources": [],
        "reasoning_nodes": [],
        "stages": [],
        "recalls": [],
        "capability_images": [],
    }
    mapping = {
        "WinningMechanismInput": "inputs",
        "WinningKnowledgeProjection": "resources",
        "WinningReasoningNode": "reasoning_nodes",
        "WinningMechanismStageOutput": "stages",
        "RecallRequest": "recalls",
        "CapabilityImageItem": "capability_images",
    }
    for row in domain_rows:
        target = mapping.get(str(row.get("type") or ""))
        payload = row.get("payload")
        if target and isinstance(payload, dict):
            grouped[target].append(payload)

    _supplement_winning_mechanism(grouped, summary)
    grouped["reasoning_nodes"].sort(key=lambda item: (_safe_int(item.get("step")), str(item.get("created_at") or "")))
    interactions = [
        event
        for index, row in enumerate(trace_rows)
        if (event := _normalize_research_interaction(row, index=index, run_id=run.id)) is not None
    ]
    grouped["workflow"] = _research_interaction_workflow(
        _dedupe_research_interactions(interactions),
        run=run,
        summary=summary,
    )
    grouped["swarm"] = (
        dict(summary.get("winning_swarm") or {}) if isinstance(summary.get("winning_swarm"), dict) else {}
    )
    if grouped["capability_images"] and not grouped["swarm"].get("final_equipment_portfolio"):
        grouped["swarm"]["final_equipment_portfolio"] = list(grouped["capability_images"])
    return grouped


async def update_run(*, db: AsyncSession, user: User, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status != "draft":
        raise HTTPException(status_code=409, detail="仅草稿可以编辑")
    if topic := str(patch.get("topic") or "").strip():
        run.topic = topic
    if route := str(patch.get("research_route") or "").strip():
        run.research_route = route
    run_payload = dict(run.payload or {})
    if "payload" in patch and isinstance(patch["payload"], dict):
        run_payload.update(patch["payload"])
    # Top-level canonical fields win over compatibility payload keys.  Key
    # presence, rather than truthiness, preserves null and empty-list scope.
    if "knowledge_enabled" in patch and patch["knowledge_enabled"] is not None:
        run_payload["knowledge_enabled"] = patch["knowledge_enabled"]
    if "knowledge_ids" in patch:
        run_payload["knowledge_ids"] = patch["knowledge_ids"]
    run.payload = _canonical_knowledge_scope(run_payload)
    if model_spec := str(patch.get("model_spec") or "").strip():
        from platform_core.services.equipment_model_adapter import resolve_equipment_model

        try:
            model_spec = resolve_equipment_model(model_spec)["model_spec"]
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run.payload = {**(run.payload or {}), "model_spec": model_spec}
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_updated", {"status": run.status, "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="update",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def _enqueue(db: AsyncSession, run: EquipmentResearchRun, *, action: str) -> None:
    tasker = Tasker()
    task = await tasker.create_in_session(
        db,
        name=f"装备研究 {run.id}",
        task_type=EQUIPMENT_RESEARCH_TASK_TYPE,
        payload={"run_id": run.id, "action": action},
        payload_match={"run_id": run.id, "action": action},
    )
    await db.commit()
    await publish_task(task.id)


async def _bind_live_model(db: AsyncSession, run: EquipmentResearchRun) -> None:
    from platform_core.services.equipment_model_adapter import (
        bind_equipment_execution,
        default_chat_model_spec,
        is_fake_execution,
    )

    payload = dict(run.payload or {})
    if not is_fake_execution(payload) and not str(payload.get("model_spec") or "").strip():
        payload["model_spec"] = await default_chat_model_spec(db)
    try:
        binding = bind_equipment_execution(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    execution = dict(payload.get("execution") or {})
    execution.update(binding["execution"])
    run.payload = {**payload, "model_spec": binding["model_spec"], "execution": execution}


async def start_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status not in STARTABLE:
        raise HTTPException(status_code=409, detail=f"{run.status} 不能启动")
    await _bind_live_model(db, run)
    run.status = "queued"
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_queued", {"status": "queued", "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="start",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await _enqueue(db, run, action="start")
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def pause_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status not in EQUIPMENT_RUN_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"{run.status} 不能暂停")
    run.status = "pause_requested"
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_pause_requested", {"status": run.status, "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="pause",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def resume_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status not in {"paused", "pause_requested", "failed"}:
        raise HTTPException(status_code=409, detail=f"{run.status} 不能恢复")
    await _bind_live_model(db, run)
    run.status = "queued"
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_resumed", {"status": "queued", "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="resume",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await _enqueue(db, run, action="resume")
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def cancel_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status not in CANCELLABLE:
        raise HTTPException(status_code=409, detail=f"{run.status} 不能取消")
    # Resolve the durable owner before committing the business terminal fact.
    # Cancellation itself happens after commit so the task failure hook cannot
    # deadlock on this transaction's locked research row.
    tasker = Tasker()
    task = await tasker.find_task_by_payload(
        task_type=EQUIPMENT_RESEARCH_TASK_TYPE,
        payload_match={"run_id": run.id},
        statuses={"pending", "running"},
    )
    run.status = "cancelled"
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_cancelled", {"status": "cancelled", "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="cancel",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    if task is not None:
        await tasker.cancel_task(task.id)
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def archive_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    if run.status in EQUIPMENT_RUN_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="进行中的任务不能归档")
    run.status = "archived"
    run.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    event = await repo.append_event(run.id, "run_archived", {"status": "archived", "actor": user.uid})
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="archive",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    await _publish_stream(run.id, event.to_dict())
    return _run_payload_for_user(run, user)


async def delete_run(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    try:
        run = await _require_run(db, user=user, run_id=run_id, lock=True, mutation=True)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        from platform_core.services.equipment_workbench_sync import delete_workbench_draft

        legacy = await asyncio.to_thread(delete_workbench_draft, run_id, user)
        if legacy is None:
            raise exc
        if not legacy["deleted"]:
            raise HTTPException(status_code=409, detail="历史研究任务为只读数据") from exc
        await audit_superadmin_personal_resource_write(
            db,
            actor=user,
            action="delete",
            resource_type="research_run",
            resource_id=run_id,
            owner_uid=str(legacy["owner_uid"] or user.uid),
        )
        await db.commit()
        return {"deleted": True, "run_id": run_id}
    if run.status not in DELETABLE:
        raise HTTPException(status_code=409, detail=f"{run.status} 不能删除")
    await db.delete(run)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete",
        resource_type="research_run",
        resource_id=run.id,
        owner_uid=str(run.owner_uid),
    )
    await db.commit()
    return {"deleted": True, "run_id": run_id}


async def list_events(*, db: AsyncSession, user: User, run_id: str, after_seq: int = 0):
    await _require_run(db, user=user, run_id=run_id)
    repo = EquipmentResearchRepository(db)
    events = await repo.list_events(run_id, after_seq=after_seq)
    return [item.to_dict() for item in events]


async def portal_snapshot(*, db: AsyncSession, user: User) -> dict[str, Any]:
    from platform_core.services.enterprise_service import FEATURES, feature_access
    from platform_core.services.equipment_workbench_sync import load_workbench_snapshot, user_workbench_snapshot

    repo = EquipmentResearchRepository(db)
    owner_uid = None if has_global_business_access(user) else user.uid
    live = user_workbench_snapshot(await asyncio.to_thread(load_workbench_snapshot), user)
    stats = await repo.portal_stats(owner_uid, include_legacy=True)
    stats = {key: max(value, live.get("stats", {}).get(key, 0)) for key, value in stats.items()}
    recent_runs = _merge_by_id(
        [
            item.to_dict()
            for item in await repo.list_runs_for_user(
                owner_uid=owner_uid,
                limit=8,
                include_legacy=True,
            )
        ],
        live.get("runs", []),
        "run_id",
    )[:8]
    recent_queries = _merge_by_id(
        [item.to_dict() for item in await repo.list_queries(owner_uid, limit=8, include_legacy=True)],
        live.get("queries", []),
        "query_id",
    )[:8]
    shortcuts = [
        {"name": "文档知识库", "path": "/extensions"},
        {"name": "智能对话", "path": "/agent"},
        {"name": "研究任务", "path": "/equipment/runs"},
        {"name": "需求 Query", "path": "/equipment/queries"},
        {"name": "深研对话", "path": "/equipment/deep-thinking"},
        {"name": "能力画像", "path": "/equipment/capabilities"},
        {"name": "研究报告", "path": "/equipment/reports"},
    ]
    if user.role in {"admin", "superadmin"}:
        shortcuts.append({"name": "模型设置", "path": "/models"})
    permissions = {feature: await feature_access(db, user, feature) for feature in FEATURES}
    if not permissions["queries"]["can_read"]:
        recent_queries = []
    for key, feature in {
        "runs": "research",
        "completed_runs": "research",
        "queries": "queries",
        "capabilities": "capabilities",
        "deep_sessions": "deep-thinking",
    }.items():
        if not permissions[feature]["can_read"]:
            stats[key] = 0
    shortcut_features = {
        "/extensions": "knowledge",
        "/agent": "agents",
        "/equipment/runs": "research",
        "/equipment/queries": "queries",
        "/equipment/deep-thinking": "deep-thinking",
        "/equipment/capabilities": "capabilities",
        "/equipment/reports": "reports",
    }
    shortcuts = [
        item
        for item in shortcuts
        if item["path"] not in shortcut_features or permissions[shortcut_features[item["path"]]]["can_read"]
    ]
    return {
        "stats": stats,
        "recent_runs": recent_runs,
        "recent_queries": recent_queries,
        "shortcuts": shortcuts,
    }


def _merge_by_id(
    postgres_rows: list[dict[str, Any]],
    live_rows: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in postgres_rows:
        item_id = str(item.get(key) or "")
        if item_id:
            merged[item_id] = item
    for item in live_rows:
        item_id = str(item.get(key) or "")
        if item_id:
            merged[item_id] = {**merged.get(item_id, {}), **item}
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )


async def create_query(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    query_text: str,
    supplemental_information: str = "",
    generation_rationale: str = "",
    source_references: list[dict[str, Any]] | None = None,
    status: str = "draft",
    knowledge_enabled: bool = True,
    knowledge_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not query_text.strip():
        raise HTTPException(status_code=422, detail="Query 不能为空")
    project = await _require_project(db, user=user, project_id=project_id)
    if status not in {"draft", "published"}:
        raise HTTPException(status_code=422, detail="Query 初始状态只能是 draft 或 published")
    owner_uid = str(project.uid)
    fingerprint = hashlib.sha256(f"{owner_uid}:{query_text.strip()}".encode()).hexdigest()
    query_payload = _canonical_knowledge_scope(
        {
            "generation_rationale": generation_rationale.strip(),
            "source_references": _canonical_query_source_references(source_references),
            "knowledge_enabled": knowledge_enabled,
            "knowledge_ids": knowledge_ids,
        }
    )
    repo = EquipmentResearchRepository(db)
    query = EquipmentQuery(
        id=_new_id("query"),
        project_id=project_id,
        owner_uid=owner_uid,
        query_text=query_text.strip(),
        query_fingerprint=fingerprint,
        supplemental_information=supplemental_information,
        status=status,
        source_type="manual",
        payload=query_payload,
    )
    if await repo.get_query_by_fingerprint(fingerprint) is not None:
        raise HTTPException(status_code=409, detail="相同 Query 已存在")
    await repo.add_query(query)
    await repo.add_query_revision(
        EquipmentQueryRevision(query_id=query.id, version=1, change_type="created", snapshot=query.to_dict())
    )
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="query",
        resource_id=query.id,
        owner_uid=str(query.owner_uid),
    )
    await db.commit()
    return query.to_dict()


async def list_queries(
    *,
    db: AsyncSession,
    user: User,
    project_id: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    owner_uid = None if has_global_business_access(user) else user.uid
    rows = [
        item.to_dict()
        for item in await repo.list_queries(
            owner_uid,
            project_id=project_id,
            status=status,
            source_type=source_type,
            search=search,
            limit=limit,
            offset=offset,
            include_legacy=True,
        )
    ]
    total = await repo.count_queries(
        owner_uid,
        project_id=project_id,
        status=status,
        source_type=source_type,
        search=search,
        include_legacy=True,
    )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


async def get_query(*, db: AsyncSession, user: User, query_id: str, include_revisions: bool = True) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    query = await _require_query(db, user=user, query_id=query_id)
    payload = query.to_dict()
    if include_revisions:
        payload["revisions"] = [item.to_dict() for item in await repo.list_query_revisions(query.id)]
    return payload


async def update_query(*, db: AsyncSession, user: User, query_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    changes = dict(changes)
    expected_version = changes.pop("expected_version", None)
    if expected_version is None:
        raise HTTPException(status_code=422, detail="更新 Query 必须提供 expected_version")
    query = await _require_query(db, user=user, query_id=query_id, mutation=True, lock=True)
    if int(expected_version) != int(query.version):
        raise HTTPException(status_code=409, detail="Query 已被其他操作更新，请刷新后重试")
    if query.status == "archived":
        raise HTTPException(status_code=409, detail="已归档 Query 不能编辑")

    next_text = str(changes.get("query", query.query_text)).strip()
    if not next_text:
        raise HTTPException(status_code=422, detail="Query 不能为空")
    next_fingerprint = hashlib.sha256(f"{query.owner_uid}:{next_text}".encode()).hexdigest()
    duplicate = await EquipmentResearchRepository(db).get_query_by_fingerprint(next_fingerprint)
    if duplicate is not None and duplicate.id != query.id:
        raise HTTPException(status_code=409, detail="相同 Query 已存在")

    query.query_text = next_text
    query.query_fingerprint = next_fingerprint
    if "supplemental_information" in changes:
        query.supplemental_information = str(changes["supplemental_information"] or "")
    payload = dict(query.payload or {})
    if "generation_rationale" in changes:
        payload["generation_rationale"] = str(changes["generation_rationale"] or "").strip()
    if "source_references" in changes:
        payload["source_references"] = _canonical_query_source_references(changes["source_references"])
    if "knowledge_enabled" in changes or "knowledge_ids" in changes:
        payload = _canonical_knowledge_scope(
            {
                **payload,
                **({"knowledge_enabled": changes["knowledge_enabled"]} if "knowledge_enabled" in changes else {}),
                **({"knowledge_ids": changes["knowledge_ids"]} if "knowledge_ids" in changes else {}),
            }
        )
    query.payload = payload
    query.version += 1
    query.updated_at = utc_now_naive()
    repo = EquipmentResearchRepository(db)
    await repo.add_query_revision(
        EquipmentQueryRevision(
            query_id=query.id,
            version=query.version,
            change_type="updated",
            snapshot=query.to_dict(),
        )
    )
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="update",
        resource_type="query",
        resource_id=query.id,
        owner_uid=str(query.owner_uid),
    )
    await db.commit()
    return query.to_dict()


async def set_query_status(
    *,
    db: AsyncSession,
    user: User,
    query_id: str,
    status: str,
    expected_version: int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if status not in {"draft", "published", "archived"}:
        raise HTTPException(status_code=422, detail="Query 状态无效")
    repo = EquipmentResearchRepository(db)
    query = await _require_query(db, user=user, query_id=query_id, mutation=True, lock=True)
    if expected_version is not None and int(expected_version) != int(query.version):
        raise HTTPException(status_code=409, detail="Query 已被其他操作更新，请刷新后重试")
    if status == "published" and query.status not in {"draft", "published"}:
        raise HTTPException(status_code=409, detail="只有草稿 Query 可以发布")
    if status == query.status:
        return query.to_dict()
    query.status = status
    query.version += 1
    query.updated_at = utc_now_naive()
    await repo.add_query_revision(
        EquipmentQueryRevision(
            query_id=query.id,
            version=query.version,
            change_type=status,
            snapshot=query.to_dict(),
        )
    )
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action=status,
        resource_type="query",
        resource_id=query.id,
        owner_uid=str(query.owner_uid),
    )
    if commit:
        await db.commit()
    return query.to_dict()


async def publish_query(
    *, db: AsyncSession, user: User, query_id: str, expected_version: int | None = None
) -> dict[str, Any]:
    return await set_query_status(
        db=db,
        user=user,
        query_id=query_id,
        status="published",
        expected_version=expected_version,
    )


async def archive_query(
    *, db: AsyncSession, user: User, query_id: str, expected_version: int | None = None
) -> dict[str, Any]:
    return await set_query_status(
        db=db,
        user=user,
        query_id=query_id,
        status="archived",
        expected_version=expected_version,
    )


async def bulk_set_query_status(
    *,
    db: AsyncSession,
    user: User,
    query_ids: list[str],
    status: str,
    versions: dict[str, int],
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(item.strip() for item in query_ids if item.strip()))
    if not unique_ids:
        raise HTTPException(status_code=422, detail="至少选择一条 Query")
    items = []
    for query_id in unique_ids:
        items.append(
            await set_query_status(
                db=db,
                user=user,
                query_id=query_id,
                status=status,
                expected_version=versions.get(query_id),
                commit=False,
            )
        )
    await db.commit()
    return {"items": items, "count": len(items)}


async def delete_query(*, db: AsyncSession, user: User, query_id: str) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    query = await _require_query(db, user=user, query_id=query_id, mutation=True, lock=True)
    await repo.delete_query(query.id)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete",
        resource_type="query",
        resource_id=query.id,
        owner_uid=str(query.owner_uid),
    )
    await db.commit()
    return {"deleted": True, "query_id": query.id}


async def list_capabilities(*, db: AsyncSession, user: User):
    repo = EquipmentResearchRepository(db)
    persisted = await repo.list_capability_versions(
        None if has_global_business_access(user) else user.uid,
        include_legacy=True,
    )
    payloads = [
        item.snapshot | {"id": item.id, "run_id": item.run_id}
        for item in persisted
        if str((item.snapshot or {}).get("status") or "").lower() != "deleted"
    ]
    payloads = await _enrich_deep_parent_metadata(repo, payloads)
    # Runs imported before the PostgreSQL capability ledger was introduced
    # still own authoritative S6 cards in their immutable artifact directory.
    # Project those cards as formal baselines so the capability workspace and
    # every jump from the run list remain useful without rewriting history.
    covered_run_ids = {str(item.run_id or "") for item in persisted}
    runs = await repo.list_runs_for_user(
        owner_uid=None if has_global_business_access(user) else user.uid,
        limit=200,
        include_legacy=True,
    )
    for run in runs:
        if run.id in covered_run_ids:
            continue
        counts = run.to_dict().get("artifact_counts") or {}
        if int(counts.get("capabilities") or 0) <= 0:
            continue
        payloads.extend(await asyncio.to_thread(_artifact_capability_payloads, run))
    run_by_id = {str(run.id): run for run in runs}
    enriched: list[dict[str, Any]] = []
    for run_id in dict.fromkeys(str(item.get("run_id") or "") for item in payloads):
        rows = [item for item in payloads if str(item.get("run_id") or "") == run_id]
        run = run_by_id.get(run_id)
        if run is None:
            enriched.extend(rows)
            continue
        summary = await asyncio.to_thread(_load_run_json, run, "round_summary.json")
        enriched.extend(enrich_capabilities_with_s5_scores(rows, summary))
    return enriched


def _capability_version_payload(item: EquipmentCapabilityVersion) -> dict[str, Any]:
    snapshot = dict(item.snapshot or {})
    formal = item.id.startswith("baseline-") or str(snapshot.get("status") or "").lower() == "formal"
    status = str(snapshot.get("status") or snapshot.get("verification_status") or "").lower()
    if formal:
        status = "formal"
    elif not status:
        status = "pending_verification"
    return (
        item.to_dict()
        | snapshot
        | {
            "version_id": item.id,
            "version_no": snapshot.get("version_no") or snapshot.get("version") or (1 if formal else None),
            "status": status,
        }
    )


def _apply_deep_parent_metadata(
    payloads: list[dict[str, Any]],
    sessions: dict[str, EquipmentDeepSession],
) -> list[dict[str, Any]]:
    """Project the originating formal card onto deep versions without rewriting history."""
    enriched: list[dict[str, Any]] = []
    for item in payloads:
        row = dict(item)
        session_id = str(row.get("session_id") or "").strip()
        session = sessions.get(session_id)
        session_payload = dict(session.payload or {}) if session is not None else {}
        parent_key = str(
            row.get("parent_capability_id")
            or row.get("parent_card_key")
            or session_payload.get("capability_card_key")
            or ""
        ).strip()
        parent_name = str(row.get("parent_capability_name") or session_payload.get("capability_name") or "").strip()
        if parent_key:
            row["parent_capability_id"] = parent_key[:256]
            row["parent_card_key"] = parent_key[:256]
        if parent_name:
            row["parent_capability_name"] = parent_name[:400]
        enriched.append(row)
    return enriched


async def _enrich_deep_parent_metadata(
    repo: EquipmentResearchRepository,
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    session_ids = {
        str(item.get("session_id") or "").strip()
        for item in payloads
        if str(item.get("session_id") or "").strip()
        and not (item.get("parent_capability_id") or item.get("parent_card_key"))
    }
    sessions: dict[str, EquipmentDeepSession] = {}
    # Keep one AsyncSession query in flight at a time; SQLAlchemy sessions are
    # not safe for concurrent gathers.
    for session_id in session_ids:
        session = await repo.get_deep_session(session_id)
        if session is not None:
            sessions[session_id] = session
    return _apply_deep_parent_metadata(payloads, sessions)


async def list_capability_versions_for_run(*, db: AsyncSession, user: User, run_id: str):
    run = await _require_run(db, user=user, run_id=run_id)
    rows = await EquipmentResearchRepository(db).list_capability_versions_for_run(
        owner_uid=str(run.owner_uid), run_id=run.id, limit=200
    )
    versions = [_capability_version_payload(item) for item in rows]
    versions = await _enrich_deep_parent_metadata(EquipmentResearchRepository(db), versions)
    if not versions:
        versions = await asyncio.to_thread(_artifact_capability_payloads, run)
    else:
        summary = await asyncio.to_thread(_load_run_json, run, "round_summary.json")
        versions = enrich_capabilities_with_s5_scores(versions, summary)
    return {"run_id": run.id, "versions": versions}


async def mutate_capability_version(
    *,
    db: AsyncSession,
    user: User,
    run_id: str,
    version_id: str,
    action: str,
    verification_status: str = "",
):
    run = await _require_run(db, user=user, run_id=run_id, mutation=True)
    repo = EquipmentResearchRepository(db)
    item = await repo.get_capability_version(version_id)
    if item is None or item.run_id != run.id or str(item.owner_uid) != str(run.owner_uid):
        raise HTTPException(status_code=404, detail="能力画像版本不存在")
    snapshot = dict(item.snapshot or {})
    current = _capability_version_payload(item)["status"]
    if current == "formal":
        raise HTTPException(status_code=422, detail="正式 S6 基线不可修改")
    if action == "delete":
        if current != "deleted":
            snapshot["status_before_delete"] = current
            snapshot["status"] = "deleted"
    elif action == "restore":
        if current != "deleted":
            raise HTTPException(status_code=409, detail="只有已隐藏版本可以恢复")
        snapshot["status"] = str(snapshot.pop("status_before_delete", "pending_verification"))
    elif action == "purge":
        if current != "deleted":
            raise HTTPException(status_code=409, detail="只有已隐藏版本可以永久删除")
        await repo.delete_capability_version(item.id)
        await db.commit()
        return {"deleted": True, "version_id": item.id}
    elif action == "verify":
        normalized = str(verification_status or "").strip().lower()
        if normalized not in {"verified", "rejected", "rolled_back", "pending_verification"}:
            raise HTTPException(status_code=422, detail="能力画像核验状态无效")
        snapshot["status"] = normalized
        snapshot["verification_status"] = normalized
    else:
        raise HTTPException(status_code=422, detail="能力画像版本操作无效")
    item.snapshot = snapshot
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action=f"capability_version_{action}",
        resource_type="equipment_capability_version",
        resource_id=item.id,
        owner_uid=str(item.owner_uid),
    )
    await db.commit()
    await db.refresh(item)
    return {"version": _capability_version_payload(item)}


def _feedback_payload(item: EquipmentExpertFeedback) -> dict[str, Any]:
    return dict(item.feedback or {}) | {
        "feedback_id": item.id,
        "run_id": item.run_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


async def list_expert_feedback(*, db: AsyncSession, user: User, run_id: str):
    run = await _require_run(db, user=user, run_id=run_id)
    rows = await EquipmentResearchRepository(db).list_expert_feedback(
        owner_uid=str(run.owner_uid), run_id=run.id, limit=200
    )
    return [_feedback_payload(item) for item in rows if (item.feedback or {}).get("status") != "rolled_back"]


async def create_expert_feedback(*, db: AsyncSession, user: User, run_id: str, feedback: dict[str, Any]):
    run = await _require_run(db, user=user, run_id=run_id, mutation=True)
    comment = str(feedback.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="反馈意见不能为空")
    payload = dict(feedback)
    payload["comment"] = comment
    allowed_score_dimensions = {
        "innovation",
        "demand",
        "feasibility",
        "effectiveness",
        "development",
    }
    payload["rubric_feedback"] = {
        str(key): str(value or "").strip()[:1000]
        for key, value in dict(payload.get("rubric_feedback") or {}).items()
        if key in allowed_score_dimensions and str(value or "").strip()
    }
    payload["status"] = "active"
    item = EquipmentExpertFeedback(
        id=_new_id("feedback"),
        project_id=run.project_id,
        owner_uid=run.owner_uid,
        run_id=run.id,
        feedback=payload,
    )
    await EquipmentResearchRepository(db).add_expert_feedback(item)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="equipment_expert_feedback",
        resource_id=item.id,
        owner_uid=str(item.owner_uid),
    )
    await db.commit()
    await db.refresh(item)
    return {"feedback": _feedback_payload(item)}


async def rollback_expert_feedback(*, db: AsyncSession, user: User, run_id: str, feedback_id: str, reason: str = ""):
    run = await _require_run(db, user=user, run_id=run_id, mutation=True)
    repo = EquipmentResearchRepository(db)
    item = await repo.get_expert_feedback(feedback_id)
    if item is None or item.run_id != run.id or str(item.owner_uid) != str(run.owner_uid):
        raise HTTPException(status_code=404, detail="专家反馈不存在")
    payload = dict(item.feedback or {})
    payload["status"] = "rolled_back"
    payload["rollback_reason"] = str(reason or "").strip()
    item.feedback = payload
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="rollback",
        resource_type="equipment_expert_feedback",
        resource_id=item.id,
        owner_uid=str(item.owner_uid),
    )
    await db.commit()
    await db.refresh(item)
    return {"feedback": _feedback_payload(item)}


_FAVORITE_MODULE_FIELDS = (
    ("overview", "概述", ("problem_statement", "capability_gap"), ("problem_statement",)),
    (
        "technology_implementation",
        "装备与技术实现",
        ("scientific_principle", "technical_principle", "implementation_concept"),
        ("technology_implementation",),
    ),
    ("operational_process", "关键作战流程", ("operational_process", "operational_mechanism"), ("operational_process",)),
    (
        "capability_effects",
        "形成能力与作战效果",
        ("capability_outcome", "direct_military_effects"),
        ("capability_effects",),
    ),
    (
        "winning_logic",
        "制胜逻辑机理",
        ("winning_mechanism", "source_winning_logic", "winning_logic"),
        ("winning_logic",),
    ),
)
_FAVORITE_ALIAS_FIELDS = (
    "version_id",
    "card_key",
    "card_binding_id",
    "card_id",
    "capability_id",
    "hypothesis_id",
    "equipment_name",
    "name",
    "primary_equipment_identity",
    "title",
    "capability_name",
)


def _favorite_fragment(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _favorite_aliases(card: dict[str, Any]) -> set[str]:
    return {normalized for field in _FAVORITE_ALIAS_FIELDS if (normalized := _favorite_fragment(card.get(field)))}


def _favorite_portrait_modules(card: dict[str, Any]) -> dict[str, str]:
    """把历代能力画像统一成收藏所需的五模块快照。"""

    raw_modules = card.get("capability_portrait_modules")
    modules = dict(raw_modules) if isinstance(raw_modules, dict) else {}
    raw_draft = card.get("capability_card_draft")
    draft = dict(raw_draft) if isinstance(raw_draft, dict) else {}
    normalized: dict[str, str] = {}
    for key, _label, card_fields, draft_fields in _FAVORITE_MODULE_FIELDS:
        candidates = [modules.get(key)]
        if key == "technology_implementation":
            candidates.append(modules.get("technology"))
        elif key == "capability_effects":
            candidates.append(modules.get("outcome"))
        candidates.extend(card.get(field) for field in card_fields)
        candidates.extend(draft.get(field) for field in draft_fields)
        text = next((str(value).strip() for value in candidates if str(value or "").strip()), "")
        if text:
            normalized[key] = text

    source = str(card.get("deep_capability_portrait") or card.get("capability_image") or "").strip()
    if source and len(normalized) < len(_FAVORITE_MODULE_FIELDS):
        aliases = {
            "概述": "overview",
            "装备与技术实现": "technology_implementation",
            "关键作战流程": "operational_process",
            "形成能力与作战效果": "capability_effects",
            "制胜逻辑机理与对抗边界": "winning_logic",
            "制胜逻辑机理": "winning_logic",
            "制胜逻辑": "winning_logic",
        }
        pattern = re.compile(
            rf"(?:^|\n)\s*(?:#{{1,6}}\s*)?(?:\d+[.、]\s*)?({'|'.join(map(re.escape, aliases))})\s*[：:]?\s*"
        )
        matches = list(pattern.finditer(source))
        for index, match in enumerate(matches):
            key = aliases[match.group(1)]
            text = source[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(source)].strip()
            if text and key not in normalized:
                normalized[key] = text
    return normalized


def _favorite_card_key(card: dict[str, Any]) -> str:
    for field in ("card_binding_id", "card_key", "capability_id", "hypothesis_id", "version_id", "id"):
        value = " ".join(str(card.get(field) or "").split()).strip()
        if value:
            return value[:512]
    return ""


def _normalize_favorite_tags(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    tags: list[str] = []
    for raw in value:
        tag = " ".join(str(raw or "").split()).strip()[:80]
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) == 20:
            break
    return tags


async def _require_favorite(
    db: AsyncSession,
    *,
    user: User,
    favorite_id: str,
    mutation: bool = False,
) -> EquipmentFavorite:
    item = await EquipmentResearchRepository(db).get_favorite(favorite_id)
    if item is None:
        raise HTTPException(status_code=404, detail="收藏不存在")
    permission = resolve_personal_resource_permission(user, item.owner_uid)
    if permission == ResourcePermission.NONE:
        raise HTTPException(status_code=404, detail="收藏不存在")
    if mutation and permission != ResourcePermission.MANAGE:
        raise HTTPException(status_code=403, detail="无权修改该收藏")
    return item


async def _favorite_payload(
    repo: EquipmentResearchRepository,
    item: EquipmentFavorite,
) -> dict[str, Any]:
    snapshot = dict(item.snapshot or {})
    run = await repo.get_run(str(item.run_id)) if item.run_id else None
    payload = item.to_dict()
    payload.update(
        {
            "source_topic": str(run.topic if run is not None else snapshot.get("source_topic") or ""),
            "source_status": str(run.status if run is not None else snapshot.get("source_status") or "deleted"),
            "source_deleted": run is None,
        }
    )
    return payload


async def list_favorites(
    *,
    db: AsyncSession,
    user: User,
    offset: int = 0,
    limit: int = 50,
    search: str = "",
    capability_type: str = "",
) -> dict[str, Any]:
    """分页读取当前账户的 PostgreSQL 收藏快照。"""

    repo = EquipmentResearchRepository(db)
    rows = await repo.list_favorites(
        None if has_global_business_access(user) else str(user.uid),
        limit=2000,
    )
    projected = [await _favorite_payload(repo, item) for item in rows]
    normalized_search = _favorite_fragment(search)
    normalized_type = _favorite_fragment(capability_type)

    def included(item: dict[str, Any]) -> bool:
        snapshot = dict(item.get("snapshot") or {})
        if normalized_type and _favorite_fragment(snapshot.get("capability_type")) != normalized_type:
            return False
        if not normalized_search:
            return True
        haystack = " ".join(
            str(value or "")
            for value in (
                item.get("display_name"),
                item.get("note"),
                item.get("source_topic"),
                snapshot.get("equipment_name"),
                snapshot.get("name"),
                snapshot.get("title"),
            )
        ).casefold()
        return normalized_search in haystack

    filtered = [item for item in projected if included(item)]
    start = max(offset, 0)
    page_size = max(1, min(limit, 200))
    items = filtered[start : start + page_size]
    return {
        "items": items,
        "favorites": items,
        "total": len(filtered),
        "offset": start,
        "limit": page_size,
    }


async def get_favorite(*, db: AsyncSession, user: User, favorite_id: str) -> dict[str, Any]:
    item = await _require_favorite(db, user=user, favorite_id=favorite_id)
    return {"favorite": await _favorite_payload(EquipmentResearchRepository(db), item)}


async def create_favorite(
    *,
    db: AsyncSession,
    user: User,
    run_id: str,
    card_identifiers: dict[str, str],
) -> dict[str, Any]:
    """由服务器解析能力版本并保存不可变快照，拒绝客户端注入卡片正文。"""

    run = await _require_run(db, user=user, run_id=run_id)
    repo = EquipmentResearchRepository(db)
    versions = await repo.list_capability_versions_for_run(
        owner_uid=str(run.owner_uid),
        run_id=run.id,
        limit=200,
    )
    cards = [_capability_version_payload(item) for item in versions]
    if not cards:
        cards = await asyncio.to_thread(_artifact_capability_payloads, run)
    requested = {normalized for value in card_identifiers.values() if (normalized := _favorite_fragment(value))}
    matches = [card for card in cards if not requested or requested.intersection(_favorite_aliases(card))]
    if not requested and len(cards) == 1:
        matches = cards
    if not matches:
        raise HTTPException(status_code=404, detail="研究任务中不存在该能力画像")
    if len(matches) > 1:
        raise HTTPException(status_code=422, detail="能力画像标识不唯一，请使用卡片或能力 ID")
    card = dict(matches[0])
    status = str(card.get("status") or "").strip().lower()
    if status == "deleted":
        raise HTTPException(status_code=422, detail="已隐藏的能力画像不能收藏")
    modules = _favorite_portrait_modules(card)
    if len(modules) != len(_FAVORITE_MODULE_FIELDS):
        raise HTTPException(status_code=422, detail="仅完整五模块能力画像可收藏")
    card_key = _favorite_card_key(card)
    if not card_key:
        raise HTTPException(status_code=422, detail="能力画像缺少稳定标识")

    owner_uid = str(user.uid)
    existing = await repo.find_favorite(owner_uid=owner_uid, run_id=run.id, card_key=card_key)
    if existing is not None:
        return {
            "favorite": await _favorite_payload(repo, existing),
            "created": False,
            "idempotent": True,
        }

    snapshot = dict(card)
    snapshot.update(
        {
            "run_id": run.id,
            "source_run_id": run.id,
            "source_topic": run.topic,
            "source_status": run.status,
            "capability_portrait_modules": modules,
            "favorite_card_key": card_key,
            "favorite_snapshot_version": "platform-v1",
        }
    )
    item = EquipmentFavorite(
        id=_new_id("favorite"),
        project_id=run.project_id,
        owner_uid=owner_uid,
        run_id=run.id,
        card_key=card_key,
        snapshot=snapshot,
        display_name="",
        note="",
        tags=[],
    )
    try:
        await repo.add_favorite(item)
    except IntegrityError:
        await db.rollback()
        existing = await repo.find_favorite(owner_uid=owner_uid, run_id=run.id, card_key=card_key)
        if existing is None:
            raise HTTPException(status_code=409, detail="收藏写入冲突") from None
        return {
            "favorite": await _favorite_payload(repo, existing),
            "created": False,
            "idempotent": True,
        }
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="equipment_favorite",
        resource_id=item.id,
        owner_uid=item.owner_uid,
    )
    await db.commit()
    await db.refresh(item)
    return {
        "favorite": await _favorite_payload(repo, item),
        "created": True,
        "idempotent": False,
    }


async def update_favorite(
    *,
    db: AsyncSession,
    user: User,
    favorite_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    item = await _require_favorite(db, user=user, favorite_id=favorite_id, mutation=True)
    if not changes:
        raise HTTPException(status_code=422, detail="至少提供一个可编辑收藏字段")
    if "display_name" in changes:
        item.display_name = " ".join(str(changes.get("display_name") or "").split()).strip()[:400]
    if "note" in changes:
        item.note = str(changes.get("note") or "").strip()[:4000]
    if "tags" in changes:
        item.tags = _normalize_favorite_tags(changes.get("tags"))
    item.updated_at = utc_now_naive()
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="update",
        resource_type="equipment_favorite",
        resource_id=item.id,
        owner_uid=str(item.owner_uid),
    )
    await db.commit()
    await db.refresh(item)
    return {"favorite": await _favorite_payload(EquipmentResearchRepository(db), item), "updated": True}


async def delete_favorite(*, db: AsyncSession, user: User, favorite_id: str) -> dict[str, Any]:
    item = await _require_favorite(db, user=user, favorite_id=favorite_id, mutation=True)
    payload = await _favorite_payload(EquipmentResearchRepository(db), item)
    await EquipmentResearchRepository(db).delete_favorite(item.id)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete",
        resource_type="equipment_favorite",
        resource_id=item.id,
        owner_uid=str(item.owner_uid),
    )
    await db.commit()
    return {"deleted": True, "favorite_id": item.id, "favorite": payload}


async def list_deep_sessions(*, db: AsyncSession, user: User):
    repo = EquipmentResearchRepository(db)
    return [
        item.to_dict()
        for item in await repo.list_deep_sessions(
            None if has_global_business_access(user) else user.uid,
            limit=200,
            include_legacy=True,
        )
    ]


async def _require_deep_session(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    mutation: bool = False,
    lock: bool = False,
) -> EquipmentDeepSession:
    """校验个人深研会话的读取或修改权限。"""

    repo = EquipmentResearchRepository(db)
    session = await repo.lock_deep_session(session_id) if lock else await repo.get_deep_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="深研对话不存在")
    permission = resolve_personal_resource_permission(
        user,
        session.owner_uid,
        shared_legacy=is_shared_legacy_resource(session),
    )
    if permission == ResourcePermission.NONE:
        raise HTTPException(status_code=404, detail="深研对话不存在")
    if mutation and permission != ResourcePermission.MANAGE:
        raise HTTPException(status_code=403, detail="无权修改该深研对话")
    if mutation and bool(getattr(session, "legacy_source_id", None) or getattr(session, "import_batch_id", None)):
        raise HTTPException(status_code=409, detail="历史深研对话为只读数据")
    return session


def _require_active_deep_session(session: EquipmentDeepSession) -> None:
    if str((session.payload or {}).get("status") or "active").lower() == "archived":
        raise HTTPException(status_code=409, detail="已归档的深研对话不能继续操作，请先恢复")


async def _lock_native_deep_conversation(db: AsyncSession, session: EquipmentDeepSession):
    """Lock and verify the platform Conversation bound to a native session."""

    payload = dict(session.payload or {})
    if payload.get("runtime") != "agent":
        return None
    thread_id = str(payload.get("thread_id") or "").strip()
    if not thread_id:
        raise HTTPException(status_code=409, detail="深研对话缺少平台线程绑定")

    from platform_core.repositories.conversation_repository import ConversationRepository

    conversation = await ConversationRepository(db).lock_conversation_by_thread_id(thread_id)
    if conversation is None or str(conversation.uid) != str(session.owner_uid):
        raise HTTPException(status_code=404, detail="深研对话线程不存在")
    return conversation


async def _deep_execution_user(db: AsyncSession, *, actor: User, owner_uid: str) -> User:
    """全局管理员修改他人会话时沿用资源所有者运行域，审计仍记录真实操作者。"""

    if str(actor.uid) == str(owner_uid):
        return actor
    if not has_global_business_access(actor):
        raise HTTPException(status_code=404, detail="深研对话不存在")
    owner = await UserRepository(db).get_by_uid(str(owner_uid))
    if owner is None or owner.is_deleted:
        raise HTTPException(status_code=409, detail="深研对话所有者已停用，无法继续执行")
    return owner


async def get_deep_context_options(*, db: AsyncSession, user: User, run_id: str) -> dict[str, Any]:
    """返回当前用户可用于定向深研的能力画像与参考武器。"""
    run = await _require_run(db, user=user, run_id=run_id)
    repo = EquipmentResearchRepository(db)
    versions = await repo.list_capability_versions_for_run(
        owner_uid=str(run.owner_uid),
        run_id=run.id,
        limit=100,
    )
    capability_sources: list[Any] = list(versions)
    if not capability_sources:
        capability_sources = await asyncio.to_thread(_artifact_capability_payloads, run)
    capability_cards = [_project_deep_context_card(item) for item in capability_sources]
    capability_cards = [item for item in capability_cards if item]
    formal_hypothesis_ids = {
        str(item.get("hypothesis_id") or "").strip()
        for item in capability_cards
        if str(item.get("hypothesis_id") or "").strip()
    }
    reference_weapons = await asyncio.to_thread(
        _load_reference_weapons,
        run,
        formal_hypothesis_ids,
    )
    return {
        "run": {
            "run_id": run.id,
            "project_id": run.project_id,
            "topic": run.topic,
            "status": run.status,
        },
        "selected_weapons": capability_cards,
        "capability_cards": capability_cards,
        "reference_weapons": reference_weapons,
    }


def _project_deep_context_card(version: Any) -> dict[str, Any]:
    if isinstance(version, dict):
        snapshot = dict(version.get("snapshot") or version)
        version_id = str(version.get("version_id") or version.get("id") or "")
        run_id = str(version.get("run_id") or snapshot.get("run_id") or "")
    else:
        snapshot = dict(version.snapshot or {})
        version_id = str(version.id)
        run_id = str(version.run_id or "")
    name = str(
        snapshot.get("name") or snapshot.get("primary_equipment_identity") or snapshot.get("title") or ""
    ).strip()
    card_key = str(
        snapshot.get("card_binding_id") or snapshot.get("card_key") or snapshot.get("capability_id") or version_id
    ).strip()
    if not name or not card_key:
        return {}
    return {
        "id": version_id,
        "run_id": run_id,
        "card_key": card_key[:256],
        "card_binding_id": str(snapshot.get("card_binding_id") or "")[:256],
        "capability_id": str(snapshot.get("capability_id") or "")[:256],
        "hypothesis_id": str(snapshot.get("hypothesis_id") or "")[:256],
        "name": name[:400],
        "primary_equipment_identity": str(snapshot.get("primary_equipment_identity") or "")[:400],
        "equipment_form": snapshot.get("equipment_form") or snapshot.get("equipment_forms") or "",
        "deep_capability_portrait": str(
            snapshot.get("deep_capability_portrait") or snapshot.get("capability_image") or ""
        )[:24000],
        "capability_portrait_modules": (
            dict(snapshot.get("capability_portrait_modules") or {})
            if isinstance(snapshot.get("capability_portrait_modules"), dict)
            else {}
        ),
    }


def _load_reference_weapons(run: EquipmentResearchRun, formal_hypothesis_ids: set[str]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for root in _research_run_roots(run):
        trace_path = root / "trace.jsonl"
        if not trace_path.is_file() or trace_path.is_symlink():
            continue
        try:
            with trace_path.open("r", encoding="utf-8") as stream:
                for index, line in enumerate(stream):
                    if index >= 30000:
                        break
                    try:
                        record = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    envelope = record.get("payload") if isinstance(record.get("payload"), dict) else record
                    details = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else envelope
                    hypothesis_id = str(details.get("hypothesis_id") or "").strip()
                    if not hypothesis_id:
                        continue
                    event_type = str(details.get("event_type") or envelope.get("event_type") or "")
                    if event_type != "winning_candidate_branch_created" and hypothesis_id not in candidates:
                        continue
                    item = candidates.setdefault(hypothesis_id, {"hypothesis_id": hypothesis_id})
                    title = str(
                        details.get("title") or details.get("name") or details.get("primary_equipment_identity") or ""
                    ).strip()
                    if title:
                        item["title"] = title[:400]
                    identity = str(details.get("primary_equipment_identity") or title).strip()
                    if identity:
                        item["primary_equipment_identity"] = identity[:400]
                    forms = details.get("equipment_forms", details.get("equipment_form", []))
                    if isinstance(forms, str):
                        forms = [forms]
                    if isinstance(forms, list):
                        item["equipment_forms"] = [
                            str(value).strip()[:400] for value in forms[:8] if str(value).strip()
                        ]
                    overview = str(
                        details.get("reference_overview") or details.get("concise_winning_summary") or ""
                    ).strip()
                    if overview:
                        item["overview"] = overview[:3000]
                    if details.get("score") is not None:
                        try:
                            item["score"] = float(details["score"])
                        except (TypeError, ValueError):
                            pass
                    if details.get("s6_eligible") is not None:
                        item["s6_eligible"] = bool(details["s6_eligible"])
        except (OSError, UnicodeError):
            logger.warning("读取研究任务参考武器失败：%s", trace_path, exc_info=True)
        if candidates:
            break

    rows = [
        item
        for hypothesis_id, item in candidates.items()
        if hypothesis_id not in formal_hypothesis_ids
        and item.get("s6_eligible") is not True
        and str(item.get("title") or item.get("primary_equipment_identity") or "").strip()
    ]
    rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("title") or "")))
    return rows[:24]


def _research_run_roots(run: EquipmentResearchRun) -> list[Path]:
    roots: list[Path] = []
    run_id = str(run.id or "").strip()
    if not run_id or Path(run_id).name != run_id:
        return roots
    workdir_path = str((run.payload or {}).get("workdir_path") or "").strip()
    if workdir_path:
        try:
            from platform_core.workspace.paths import user_workdir_host_dir

            host_dir = user_workdir_host_dir(str(run.owner_uid), workdir_path)
            resolved_host_dir = host_dir.resolve(strict=True)
            artifact_relpath = str(getattr(run, "artifact_relpath", "") or "").strip()
            if artifact_relpath:
                relative = Path(artifact_relpath)
                if not relative.is_absolute() and ".." not in relative.parts:
                    candidate = host_dir / relative
                    if relative.name in {
                        "report.md",
                        "report-postfix.md",
                        "trace.jsonl",
                        "domain.jsonl",
                        "round_summary.json",
                    }:
                        candidate = candidate.parent
                    try:
                        candidate.resolve(strict=False).relative_to(resolved_host_dir)
                    except (OSError, ValueError):
                        pass
                    else:
                        roots.append(candidate)
            conventional = host_dir / "outputs" / "equipment-research" / run_id
            try:
                conventional.resolve(strict=False).relative_to(resolved_host_dir)
            except (OSError, ValueError):
                pass
            else:
                roots.append(conventional)
        except (OSError, RuntimeError, ValueError):
            logger.warning("无法定位研究任务工作目录：%s", run.id, exc_info=True)

    legacy_root = Path(os.environ.get("EQUIPMENT_DR_OUTPUT_ROOT", "/app/outputs/runs")).expanduser()
    try:
        resolved_legacy_root = legacy_root.resolve(strict=False)
        legacy_candidate = legacy_root / run_id
        legacy_candidate.resolve(strict=False).relative_to(resolved_legacy_root)
    except (OSError, ValueError):
        pass
    else:
        roots.append(legacy_candidate)

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


_MAX_RESEARCH_ARTIFACT_RECORDS = 50_000
_MAX_RESEARCH_ARTIFACT_LINE_BYTES = 4 * 1024 * 1024
_SENSITIVE_ARTIFACT_KEYS = {
    "api_key",
    "authorization",
    "password",
    "access_token",
    "refresh_token",
    "credentials",
    "credential",
    "client_secret",
}
_COMPACT_RESEARCH_EVENT_LIMIT = 120
_RESEARCH_AGENT_NAMES = {
    "orchestrator": "主控 Agent",
    "operational_employment": "作战运用 Agent",
    "combat_scenario": "作战场景 Agent",
    "international_situation": "国际态势 Agent",
    "opponent_monitoring": "对手监测 Agent",
    "system_confrontation": "体系对抗 Agent",
    "weapon_equipment": "武器装备 Agent",
    "case_research": "战例研究 Agent",
    "technology_radar": "技术雷达 Agent",
    "cross_domain_fusion": "跨域融合 Agent",
    "nontraditional_security": "非传统安全 Agent",
    "winning_mechanism": "制胜机理 Agent",
    "winning_swarm_controller": "动态蜂群主控 Agent",
    "auditor": "业务审计 Agent",
    "reporter": "研究报告 Agent",
}
_WINNING_STEP_META = (
    (1, "winning_s1_opponent", "对手分析 Agent"),
    (2, "winning_s2_operations", "作战运用审查 Agent"),
    (3, "winning_s3_breakthrough", "突破口思考 Agent"),
    (4, "winning_s4_capability", "装备能力映射 Agent"),
    (5, "winning_s5_gap", "创新颠覆候选组合评审 Agent"),
    (6, "winning_s6_image", "能力图像综合 Agent"),
)
_LOOP_EVENT_TYPES = {
    "inner": "winning_inner_loop_evaluated",
    "middle": "winning_middle_loop_evaluated",
    "outer": "winning_outer_loop_evaluated",
    "meta": "discovery_meta_loop_evaluated",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _artifact_key_is_sensitive(key: object) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_ARTIFACT_KEYS or normalized.endswith("_secret")


def _sanitize_research_artifact(value: Any, *, depth: int = 0) -> Any:
    """Remove credentials from artifact-backed responses without mutating source data."""

    if depth > 32:
        return None
    if isinstance(value, dict):
        return {
            str(key): _sanitize_research_artifact(item, depth=depth + 1)
            for key, item in value.items()
            if not _artifact_key_is_sensitive(key)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_research_artifact(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_research_artifact_path(run_root: Path, relative_name: str) -> Path | None:
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    try:
        if run_root.is_symlink() or not run_root.is_dir():
            return None
        resolved_root = run_root.resolve(strict=True)
        candidate = run_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved


def _read_research_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("rb") as stream:
            for index, raw_line in enumerate(stream):
                if index >= _MAX_RESEARCH_ARTIFACT_RECORDS:
                    break
                if not raw_line.strip() or len(raw_line) > _MAX_RESEARCH_ARTIFACT_LINE_BYTES:
                    continue
                try:
                    value = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    rows.append(_sanitize_research_artifact(value))
    except OSError:
        logger.warning("读取研究 JSONL 失败：%s", path, exc_info=True)
    return rows


def _load_run_jsonl(run: EquipmentResearchRun, filename: str) -> list[dict[str, Any]]:
    for run_root in _research_run_roots(run):
        path = _safe_research_artifact_path(run_root, filename)
        if path is not None:
            return _read_research_jsonl(path)
    return []


def _artifact_capability_payloads(run: EquipmentResearchRun) -> list[dict[str, Any]]:
    """Project legacy S6 artifacts into the platform capability contract.

    Historical runs predate ``equipment_capability_versions``. Their
    ``CapabilityImageItem`` rows and ``capability_images.json`` files are
    immutable run artifacts, so they can safely act as version-1 formal
    baselines when the database ledger has no rows for that run.
    """

    cards = [
        dict(payload)
        for row in _load_run_jsonl(run, "domain.jsonl")
        if row.get("type") == "CapabilityImageItem" and isinstance(payload := row.get("payload"), dict)
    ]
    if not cards:
        for run_root in _research_run_roots(run):
            path = _safe_research_artifact_path(run_root, "capability_images.json")
            if path is None:
                continue
            try:
                if path.stat().st_size > _MAX_RESEARCH_ARTIFACT_LINE_BYTES * 16:
                    break
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                logger.warning("读取历史能力画像失败：%s", path, exc_info=True)
                break
            if isinstance(value, dict):
                value = value.get("capability_images") or value.get("items") or value.get("cards") or []
            if isinstance(value, list):
                cards = [_sanitize_research_artifact(dict(item)) for item in value if isinstance(item, dict)]
            break

    cards = enrich_capabilities_with_s5_scores(
        cards,
        _load_run_json(run, "round_summary.json"),
    )
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_snapshot in enumerate(cards, start=1):
        snapshot = dict(raw_snapshot)
        binding = str(
            snapshot.get("card_binding_id") or snapshot.get("capability_id") or snapshot.get("hypothesis_id") or index
        ).strip()
        hypothesis = str(snapshot.get("hypothesis_id") or "").strip()
        identity = f"{run.id}:{binding}:{hypothesis}"
        version_id = f"baseline-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        if version_id in seen:
            continue
        seen.add(version_id)
        snapshot.update(
            {
                "run_id": run.id,
                "source": "formal_s6",
                "status": "formal",
                "version_no": 1,
            }
        )
        payloads.append(
            snapshot
            | {
                "id": version_id,
                "version_id": version_id,
                "project_id": run.project_id,
                "owner_uid": str(run.owner_uid),
                "run_id": run.id,
                "snapshot": snapshot,
                "legacy_source_id": version_id,
            }
        )
    return payloads


def _load_run_json(run: EquipmentResearchRun, filename: str) -> dict[str, Any]:
    for run_root in _research_run_roots(run):
        path = _safe_research_artifact_path(run_root, filename)
        if path is None:
            continue
        try:
            if path.stat().st_size > _MAX_RESEARCH_ARTIFACT_LINE_BYTES * 16:
                return {}
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            logger.warning("读取研究 JSON 失败：%s", path, exc_info=True)
            return {}
        return _sanitize_research_artifact(value) if isinstance(value, dict) else {}
    return {}


def _load_run_trace_and_summary(
    run: EquipmentResearchRun,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _load_run_jsonl(run, "trace.jsonl"), _load_run_json(run, "round_summary.json")


def _load_run_domain_trace_and_summary(
    run: EquipmentResearchRun,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return (
        _load_run_jsonl(run, "domain.jsonl"),
        _load_run_jsonl(run, "trace.jsonl"),
        _load_run_json(run, "round_summary.json"),
    )


def _unwrap_research_event(row: dict[str, Any]) -> dict[str, Any]:
    candidate = row
    for _ in range(6):
        direct_event = candidate.get("event")
        payload = candidate.get("payload")
        payload_event = payload.get("event") if isinstance(payload, dict) else None
        if isinstance(direct_event, dict) and direct_event.get("event_type"):
            candidate = direct_event
            continue
        if isinstance(payload_event, dict) and payload_event.get("event_type"):
            candidate = payload_event
            continue
        if candidate.get("type") == "TraceEvent" and isinstance(payload, dict):
            candidate = payload
            continue
        if (
            candidate.get("event_type")
            and isinstance(payload, dict)
            and payload.get("event_id")
            and payload.get("event_type") == candidate.get("event_type")
        ):
            candidate = payload
            continue
        break
    return candidate


def _string_list(value: Any, *, limit: int = 500) -> list[Any]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [_sanitize_research_artifact(item) for item in list(value)[:limit]]


def _normalize_research_interaction(
    row: dict[str, Any],
    *,
    index: int,
    run_id: str,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    candidate = _unwrap_research_event(row)
    candidate_payload = candidate.get("payload")
    explicit_details = candidate.get("details")
    details = (
        explicit_details
        if isinstance(explicit_details, dict)
        else candidate_payload
        if isinstance(candidate_payload, dict)
        else {}
    )
    event_type = str(
        candidate.get("event_type") or row.get("event_type") or details.get("event_type") or "trace_event"
    ).strip()
    if not event_type:
        return None
    sequence = _safe_int(row.get("sequence", candidate.get("sequence")), index + 1)
    actor = str(
        candidate.get("actor")
        or details.get("actor")
        or details.get("agent_id")
        or details.get("agent_instance_id")
        or "orchestrator"
    ).strip()
    summary = str(
        candidate.get("summary")
        or details.get("summary")
        or details.get("message")
        or details.get("detail")
        or details.get("status")
        or event_type
    ).strip()
    return {
        "event_id": str(candidate.get("event_id") or row.get("event_id") or f"{run_id}:{sequence}:{event_type}"),
        "sequence": sequence,
        "event_type": event_type,
        "actor": actor,
        "created_at": str(candidate.get("created_at") or row.get("created_at") or ""),
        "summary": summary,
        "details": _sanitize_research_artifact(details),
        "input_refs": _string_list(candidate.get("input_refs")),
        "output_refs": _string_list(candidate.get("output_refs")),
        "source": str(candidate.get("source") or row.get("source") or "trace"),
    }


def _dedupe_research_interactions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("event_id") or "").strip() or "|".join(
            str(event.get(field) or "") for field in ("sequence", "event_type", "actor", "created_at", "summary")
        )
        deduped[key] = event
    return sorted(
        deduped.values(),
        key=lambda item: (
            _safe_int(item.get("sequence")),
            str(item.get("created_at") or ""),
            str(item.get("event_id") or ""),
        ),
    )


def _is_key_research_event(event_type: str) -> bool:
    return event_type.startswith(
        (
            "run_",
            "knowledge_",
            "discovery_",
            "baseline_",
            "winning_",
            "specialist_",
            "recall_",
            "capability_",
            "audit_",
            "report_",
        )
    ) or event_type in {"tool_call", "tool_result", "savepoint", "status_changed"}


def _compact_research_interactions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    important = [item for item in events if _is_key_research_event(str(item.get("event_type") or ""))]
    selected = important or events
    if len(selected) <= _COMPACT_RESEARCH_EVENT_LIMIT:
        return selected
    head_count = 16
    return [*selected[:head_count], *selected[-(_COMPACT_RESEARCH_EVENT_LIMIT - head_count) :]]


async def _load_postgres_interactions(db: AsyncSession, *, run_id: str) -> list[dict[str, Any]]:
    repo = EquipmentResearchRepository(db)
    events: list[dict[str, Any]] = []
    after_sequence = 0
    for _ in range(_MAX_RESEARCH_ARTIFACT_RECORDS // 200):
        rows = await repo.list_events(run_id, after_seq=after_sequence, limit=200)
        if not rows:
            break
        for row in rows:
            raw = row.to_dict() if hasattr(row, "to_dict") else row
            if not isinstance(raw, dict):
                continue
            event = _normalize_research_interaction(raw, index=len(events), run_id=run_id)
            if event is not None:
                events.append(event)
        next_sequence = max(
            (
                _safe_int(getattr(row, "sequence", None) or (row.get("sequence") if isinstance(row, dict) else 0))
                for row in rows
            ),
            default=0,
        )
        if len(rows) < 200 or next_sequence <= after_sequence:
            break
        after_sequence = next_sequence
    return events


def _event_step(event: dict[str, Any]) -> int:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    step = _safe_int(details.get("step"))
    if step:
        return step
    node = str(details.get("mission_node") or details.get("merge_target") or "")
    match = re.search(r"(?:^|[^A-Z])S([1-6])(?:$|[^0-9])", node.upper())
    if match:
        return int(match.group(1))
    match = re.search(r"winning_s([1-6])", str(event.get("event_type") or "").lower())
    return int(match.group(1)) if match else 0


def _dynamic_status(event_type: str, current: str = "planned") -> str:
    if "failed" in event_type:
        return "failed"
    if "cancelled" in event_type:
        return "cancelled"
    if "pruned" in event_type or "rejected" in event_type:
        return "pruned"
    if "merged" in event_type:
        return "merged"
    if "completed" in event_type:
        return "completed"
    if any(token in event_type for token in ("started", "ready", "waiting", "spawned")):
        return "running"
    if "recruited" in event_type or "recruitment_planned" in event_type:
        return "recruiting"
    return current


def _dynamic_member_id(value: dict[str, Any]) -> str:
    return str(
        value.get("agent_instance_id")
        or value.get("instance_id")
        or value.get("task_id")
        or value.get("agent_id")
        or value.get("id")
        or ""
    ).strip()


def _project_dynamic_agents(
    events: list[dict[str, Any]], summary: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    mission_graph: dict[str, Any] = {}
    for event in events:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        event_type = str(event.get("event_type") or "")
        if event_type == "winning_mission_graph_planned":
            raw_graph = details.get("graph", details.get("mission_graph", {}))
            if isinstance(raw_graph, dict):
                mission_graph = dict(raw_graph)
                contracts = {
                    str(item.get("role_contract_id") or ""): item
                    for item in raw_graph.get("role_contracts", [])
                    if isinstance(item, dict) and item.get("role_contract_id")
                }
                for item in raw_graph.get("agent_instances", raw_graph.get("tasks", [])):
                    if not isinstance(item, dict):
                        continue
                    member_id = _dynamic_member_id(item)
                    if not member_id:
                        continue
                    contract = contracts.get(str(item.get("role_contract_id") or ""), {})
                    members[member_id] = {
                        **contract,
                        **item,
                        "agent_instance_id": member_id,
                        "display_name": item.get("display_name") or contract.get("display_name") or "动态专用 Agent",
                        "mission_node": item.get("mission_node")
                        or item.get("merge_target")
                        or contract.get("mission_node", ""),
                        "status": str(item.get("status") or "planned"),
                    }
        if not (
            event_type.startswith(("winning_agent_", "specialist_", "winning_contribution_"))
            or event_type == "winning_subagent_completed"
        ):
            continue
        instance = details.get("instance") if isinstance(details.get("instance"), dict) else {}
        member_id = _dynamic_member_id(instance) or _dynamic_member_id(details) or str(event.get("actor") or "")
        if not member_id or member_id in _RESEARCH_AGENT_NAMES:
            continue
        previous = members.get(member_id, {"agent_instance_id": member_id})
        members[member_id] = {
            **previous,
            **instance,
            **details,
            "agent_instance_id": member_id,
            "display_name": details.get("display_name")
            or instance.get("display_name")
            or previous.get("display_name")
            or "动态专用 Agent",
            "mission_node": details.get("mission_node")
            or instance.get("mission_node")
            or details.get("merge_target")
            or previous.get("mission_node", ""),
            "merge_target": details.get("merge_target")
            or instance.get("merge_target")
            or previous.get("merge_target", ""),
            "status": _dynamic_status(event_type, str(details.get("status") or previous.get("status") or "planned")),
        }
    if not mission_graph:
        swarm = summary.get("winning_swarm") if isinstance(summary.get("winning_swarm"), dict) else {}
        candidate_graph = swarm.get("mission_graph") if isinstance(swarm, dict) else {}
        if isinstance(candidate_graph, dict):
            mission_graph = dict(candidate_graph)
    return list(members.values()), mission_graph


def _summary_reasoning_nodes(summary: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    six_step = summary.get("six_step_reasoning")
    if not isinstance(six_step, dict):
        return result
    for value in six_step.values():
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict) and _safe_int(candidate.get("step")) in range(1, 7):
                result.append(dict(candidate))
    return result


def _candidate_rows(summary: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    def add(value: Any) -> None:
        if not isinstance(value, dict):
            return
        key = str(
            value.get("hypothesis_id")
            or value.get("card_binding_id")
            or value.get("capability_id")
            or value.get("name")
            or value.get("title")
            or ""
        ).strip()
        if key:
            candidates[key] = {**candidates.get(key, {}), **value, "hypothesis_id": value.get("hypothesis_id") or key}

    swarm = summary.get("winning_swarm") if isinstance(summary.get("winning_swarm"), dict) else {}
    ledger = swarm.get("hypothesis_ledger") if isinstance(swarm.get("hypothesis_ledger"), dict) else {}
    hypotheses = ledger.get("hypotheses", []) if isinstance(ledger, dict) else []
    if isinstance(hypotheses, dict):
        hypotheses = list(hypotheses.values())
    if isinstance(hypotheses, list):
        for item in hypotheses:
            add(item)
    final_merge = swarm.get("final_merge") if isinstance(swarm.get("final_merge"), dict) else {}
    for field in ("final_equipment_portfolio", "portfolio", "selected_candidates", "hypotheses"):
        rows = final_merge.get(field, []) if isinstance(final_merge, dict) else []
        if isinstance(rows, list):
            for item in rows:
                add(item)
    for event in events:
        candidate_event = str(event.get("event_type") or "")
        if not any(token in candidate_event for token in ("hypothesis", "candidate", "portfolio", "s6_card")):
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        for field in ("candidate", "hypothesis", "portfolio_item", "direction"):
            add(details.get(field))
        for field in ("candidates", "hypotheses", "portfolio", "final_equipment_portfolio", "authored_cards"):
            rows = details.get(field, [])
            if isinstance(rows, list):
                for item in rows:
                    add(item)
        add(details)
    return list(candidates.values())


def _research_interaction_workflow(
    events: list[dict[str, Any]],
    *,
    run: EquipmentResearchRun,
    summary: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(getattr(run, "payload", None) or {})
    start_details = next(
        (
            item.get("details")
            for item in events
            if item.get("event_type") == "run_started" and isinstance(item.get("details"), dict)
        ),
        {},
    )
    selection = start_details.get("agent_selection") if isinstance(start_details.get("agent_selection"), dict) else {}
    blueprint = summary.get("discovery_blueprint")
    if not isinstance(blueprint, dict):
        blueprint = start_details.get("discovery_blueprint")
    if not isinstance(blueprint, dict):
        blueprint = selection.get("discovery_blueprint")
    blueprint = dict(blueprint) if isinstance(blueprint, dict) else {}
    dynamic_agents, mission_graph = _project_dynamic_agents(events, summary)
    reasoning_nodes = _summary_reasoning_nodes(summary)

    step_plan: list[dict[str, Any]] = []
    adaptive_modes = blueprint.get("adaptive_winning_step_modes", {})
    adaptive_modes = adaptive_modes if isinstance(adaptive_modes, dict) else {}
    for step, agent_id, label in _WINNING_STEP_META:
        step_events = [item for item in events if _event_step(item) == step]
        members = [
            item
            for item in dynamic_agents
            if _safe_int(str(item.get("mission_node") or item.get("merge_target") or "").replace("S", "")) == step
        ]
        node = next((item for item in reversed(reasoning_nodes) if _safe_int(item.get("step")) == step), {})
        event_types = {str(item.get("event_type") or "") for item in step_events}
        if any("failed" in item for item in event_types):
            status = "failed"
        elif node or any("completed" in item or "merged" in item for item in event_types):
            status = "completed"
        elif any("skipped" in item for item in event_types):
            status = "skipped"
        elif any(any(token in item for token in ("started", "running", "ready", "waiting")) for item in event_types):
            status = "running"
        else:
            status = "pending"
        latest = step_events[-1] if step_events else {}
        step_plan.append(
            {
                "step": step,
                "agent_id": agent_id,
                "label": label,
                "status": status,
                "execution_mode": "dynamic" if members else str(adaptive_modes.get(str(step)) or "standard"),
                "dynamic_agents": members,
                "result_summary": str(node.get("summary") or latest.get("summary") or ""),
                "backtrack_count": sum(
                    "recall" in str(item.get("event_type") or "") or "backtrack" in str(item.get("event_type") or "")
                    for item in step_events
                ),
            }
        )

    selected_agent_ids = list(payload.get("selected_agent_ids") or [])
    if isinstance(summary.get("selected_agent_ids"), list):
        selected_agent_ids.extend(summary["selected_agent_ids"])
    selected_agent_ids.extend(
        item.get("agent_id") for item in blueprint.get("baseline_agent_plan", []) if isinstance(item, dict)
    )
    selected_agent_ids.extend(str(item.get("actor") or "") for item in events)
    selected_agent_ids.extend(_dynamic_member_id(item) for item in dynamic_agents)
    active_agent_ids = list(dict.fromkeys(str(item).strip() for item in selected_agent_ids if str(item).strip()))

    candidates = _candidate_rows(summary, events)
    portfolio = [
        item
        for item in candidates
        if item.get("s6_eligible") is True
        or str(item.get("selection_status") or item.get("portfolio_status") or "")
        in {"selected", "selected_limited", "final"}
    ]
    failure_event = next(
        (item for item in reversed(events) if "failed" in str(item.get("event_type") or "")),
        None,
    )
    loops = {}
    for key, event_type in _LOOP_EVENT_TYPES.items():
        rows = [item for item in events if item.get("event_type") == event_type]
        loops[key] = {
            "count": len(rows),
            "latest": str(rows[-1].get("summary") or "") if rows else "",
            "details": dict(rows[-1].get("details") or {}) if rows else {},
        }
    return {
        "status": str(getattr(run, "status", "") or ""),
        "failure": (
            {
                "phase": (failure_event.get("details") or {}).get("phase"),
                "detail": failure_event.get("summary") or getattr(run, "error", ""),
            }
            if failure_event
            else {"detail": str(getattr(run, "error", "") or "")}
            if getattr(run, "error", "")
            else {}
        ),
        "active_agent_ids": active_agent_ids,
        "discovery": {
            **blueprint,
            "primary_branch": blueprint.get("primary_branch")
            or payload.get("discovery_branch")
            or getattr(run, "research_route", ""),
            "secondary_branches": list(blueprint.get("secondary_branches") or []),
            "baseline_agent_plan": list(blueprint.get("baseline_agent_plan") or []),
        },
        "execution": dict(payload.get("execution") or {}),
        "step_plan": step_plan,
        "loops": loops,
        "dynamic_agents": dynamic_agents,
        "swarm_cluster": {
            "enabled": bool(dynamic_agents or mission_graph),
            "members": dynamic_agents,
            "mission_graph": mission_graph,
            "candidate_lineage": candidates,
            "final_equipment_portfolio": portfolio,
            "counts": {
                "total": len(dynamic_agents),
                "running": sum(item.get("status") == "running" for item in dynamic_agents),
                "completed": sum(item.get("status") in {"completed", "merged"} for item in dynamic_agents),
                "merged": sum(item.get("status") == "merged" for item in dynamic_agents),
                "pruned": sum(item.get("status") in {"pruned", "failed", "cancelled"} for item in dynamic_agents),
            },
        },
    }


def _research_interaction_agents(
    events: list[dict[str, Any]],
    *,
    run: EquipmentResearchRun,
    summary: dict[str, Any],
    workflow: dict[str, Any],
) -> list[dict[str, Any]]:
    del events, run, summary
    dynamic_ids = {_dynamic_member_id(item) for item in workflow.get("dynamic_agents", []) if isinstance(item, dict)}
    result = []
    for agent_id in workflow.get("active_agent_ids", []):
        if agent_id in dynamic_ids:
            continue
        result.append(
            {
                "agent_id": agent_id,
                "display_name": _RESEARCH_AGENT_NAMES.get(agent_id, agent_id),
                "harness_profile": "winning_step_v1" if agent_id.startswith("winning_s") else "受控运行",
                "skill_ids": [],
            }
        )
    return result


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(item) for item in value.values() if isinstance(item, dict)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _supplement_winning_mechanism(grouped: dict[str, Any], summary: dict[str, Any]) -> None:
    winning = summary.get("winning_mechanism")
    winning = winning if isinstance(winning, dict) else {}
    aliases = {
        "inputs": ("inputs",),
        "resources": ("resources", "resource_projections"),
        "reasoning_nodes": ("reasoning_nodes",),
        "stages": ("stages",),
        "recalls": ("recalls", "recall_requests"),
    }
    for target, fields in aliases.items():
        if grouped[target]:
            continue
        for field in fields:
            rows = _as_dict_list(winning.get(field))
            if rows:
                grouped[target].extend(rows)
                break
    if not grouped["reasoning_nodes"]:
        grouped["reasoning_nodes"].extend(_summary_reasoning_nodes(summary))
    if not grouped["recalls"]:
        grouped["recalls"].extend(_as_dict_list(summary.get("recall_requests")))


async def _resolve_requested_model(db: AsyncSession, model_spec: str | None) -> dict[str, Any]:
    from platform_core.services.equipment_model_adapter import default_chat_model_spec, resolve_equipment_model

    spec = str(model_spec or "").strip() or await default_chat_model_spec(db)
    try:
        return resolve_equipment_model(spec)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _enqueue_typed(
    db: AsyncSession,
    *,
    name: str,
    task_type: str,
    payload: dict[str, Any],
    match: dict[str, Any],
) -> None:
    tasker = Tasker()
    task = await tasker.create_in_session(db, name=name, task_type=task_type, payload=payload, payload_match=match)
    await db.commit()
    await publish_task(task.id)


async def submit_query_generation(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    topic: str,
    supplemental_information: str = "",
    reference_urls: list[str] | None = None,
    count: int = 6,
    model_spec: str | None = None,
    knowledge_enabled: bool = True,
    knowledge_ids: list[str] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    if not topic.strip():
        raise HTTPException(status_code=422, detail="生成主题不能为空")
    project = await _require_project(db, user=user, project_id=project_id)
    from equipment_deep_research.query_library.quality import sanitize_reference_urls

    try:
        normalized_reference_urls = list(sanitize_reference_urls(reference_urls or []))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_idempotency_key = str(idempotency_key or "").strip()
    request_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "project_id": project.id,
                "topic": topic.strip(),
                "supplemental_information": supplemental_information,
                "reference_urls": normalized_reference_urls,
                "count": count,
                "model_spec": str(model_spec or "").strip(),
                "knowledge_enabled": knowledge_enabled,
                "knowledge_ids": knowledge_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    generation_id = _new_id("qgen")
    repo = EquipmentResearchRepository(db)
    if normalized_idempotency_key:
        digest = hashlib.sha256(f"{project.uid}:{project.id}:{normalized_idempotency_key}".encode()).hexdigest()
        generation_id = f"qgen-{digest[:32]}"
        replay = await repo.get_generation(generation_id)
        if replay is not None:
            previous_fingerprint = str((replay.payload or {}).get("idempotency_fingerprint") or "")
            if previous_fingerprint and previous_fingerprint != request_fingerprint:
                raise HTTPException(status_code=409, detail="幂等键已用于不同的 Query 生成参数")
            return replay.to_dict()
    runtime = await _resolve_requested_model(db, model_spec)
    from platform_core.services.equipment_query_task import EQUIPMENT_QUERY_TASK_TYPE

    query_scope = _canonical_knowledge_scope(
        {
            "knowledge_enabled": knowledge_enabled,
            "knowledge_ids": knowledge_ids,
        }
    )
    generation = EquipmentQueryGeneration(
        id=generation_id,
        project_id=project_id,
        owner_uid=str(project.uid),
        topic=topic.strip()[:500],
        status="queued",
        payload={
            "model_spec": runtime["model_spec"],
            "supplemental_information": supplemental_information,
            "reference_urls": normalized_reference_urls,
            "count": max(1, min(int(count or 6), 20)),
            "stage": "queued",
            "attempts": 0,
            "idempotency_fingerprint": request_fingerprint if normalized_idempotency_key else "",
            **query_scope,
        },
    )
    await repo.add_generation(generation)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="query_generation",
        resource_id=generation.id,
        owner_uid=str(generation.owner_uid),
    )
    await _enqueue_typed(
        db,
        name=f"Query 生成 {generation.id}",
        task_type=EQUIPMENT_QUERY_TASK_TYPE,
        payload={"generation_id": generation.id},
        match={"generation_id": generation.id},
    )
    return generation.to_dict()


async def list_query_generations(
    *,
    db: AsyncSession,
    user: User,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    owner_uid = None if has_global_business_access(user) else user.uid
    rows = [
        item.to_dict()
        for item in await repo.list_generations(
            owner_uid,
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    ]
    total = await repo.count_generations(owner_uid, project_id=project_id, status=status)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


async def _require_query_generation(
    db: AsyncSession,
    *,
    user: User,
    generation_id: str,
    mutation: bool = False,
    lock: bool = False,
) -> EquipmentQueryGeneration:
    repo = EquipmentResearchRepository(db)
    job = await repo.lock_generation(generation_id) if lock else await repo.get_generation(generation_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    permission = resolve_personal_resource_permission(user, job.owner_uid)
    if permission == ResourcePermission.NONE or (
        not has_global_business_access(user) and job.import_batch_id == "workbench-sync"
    ):
        raise HTTPException(status_code=404, detail="生成任务不存在")
    if mutation and permission != ResourcePermission.MANAGE:
        raise HTTPException(status_code=403, detail="无权修改该生成任务")
    if mutation and bool(getattr(job, "legacy_source_id", None) or getattr(job, "import_batch_id", None)):
        raise HTTPException(status_code=409, detail="历史 Query 生成任务为只读数据")
    return job


async def get_query_generation(*, db: AsyncSession, user: User, generation_id: str) -> dict[str, Any]:
    job = await _require_query_generation(db, user=user, generation_id=generation_id)
    return job.to_dict()


async def cancel_query_generation(*, db: AsyncSession, user: User, generation_id: str) -> dict[str, Any]:
    job = await _require_query_generation(
        db,
        user=user,
        generation_id=generation_id,
        mutation=True,
        lock=True,
    )
    if job.status in {"completed", "failed", "cancelled"}:
        if job.status == "cancelled":
            return job.to_dict()
        raise HTTPException(status_code=409, detail="已结束的生成任务不能取消")
    from platform_core.services.equipment_query_task import EQUIPMENT_QUERY_TASK_TYPE

    tasker = Tasker()
    task = await tasker.find_task_by_payload(
        task_type=EQUIPMENT_QUERY_TASK_TYPE,
        payload_match={"generation_id": generation_id},
        statuses={"pending", "running"},
    )
    if task is not None:
        await tasker.cancel_task(task.id)
    payload = dict(job.payload or {})
    payload["stage"] = "cancelled"
    payload["error"] = ""
    job.payload = payload
    job.status = "cancelled"
    job.updated_at = utc_now_naive()
    await db.commit()
    return job.to_dict()


async def retry_query_generation(*, db: AsyncSession, user: User, generation_id: str) -> dict[str, Any]:
    job = await _require_query_generation(
        db,
        user=user,
        generation_id=generation_id,
        mutation=True,
        lock=True,
    )
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败或已取消的生成任务可以重试")
    from platform_core.services.equipment_query_task import EQUIPMENT_QUERY_TASK_TYPE

    tasker = Tasker()
    active = await tasker.find_task_by_payload(
        task_type=EQUIPMENT_QUERY_TASK_TYPE,
        payload_match={"generation_id": generation_id},
        statuses={"pending", "running"},
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="生成任务仍在停止中，请稍后重试")
    payload = dict(job.payload or {})
    payload.update(
        {
            "stage": "queued",
            "error": "",
            "query_ids": [],
            "attempts": int(payload.get("attempts") or 0) + 1,
        }
    )
    job.payload = payload
    job.status = "queued"
    job.updated_at = utc_now_naive()
    await _enqueue_typed(
        db,
        name=f"Query 生成重试 {generation_id}",
        task_type=EQUIPMENT_QUERY_TASK_TYPE,
        payload={"generation_id": generation_id},
        match={"generation_id": generation_id},
    )
    return job.to_dict()


async def delete_query_generation(*, db: AsyncSession, user: User, generation_id: str) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    job = await _require_query_generation(
        db,
        user=user,
        generation_id=generation_id,
        mutation=True,
        lock=True,
    )
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="运行中的生成任务不能删除，请先取消")
    owner_uid = str(job.owner_uid)
    await repo.delete_generation(job.id)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete",
        resource_type="query_generation",
        resource_id=job.id,
        owner_uid=owner_uid,
    )
    await db.commit()

    from platform_core.services.equipment_query_task import EQUIPMENT_QUERY_TASK_TYPE

    tasker = Tasker()
    task = await tasker.find_task_by_payload(
        task_type=EQUIPMENT_QUERY_TASK_TYPE,
        payload_match={"generation_id": generation_id},
    )
    if task is not None and task.status in {"success", "failed", "cancelled"}:
        await tasker.delete_task(task.id)
    return {"deleted": True, "generation_id": generation_id}


async def get_query_model_options(*, db: AsyncSession) -> dict[str, Any]:
    """复用平台模型目录，Query 不再维护第二套供应商配置。"""

    from platform_core.models.providers.cache import model_cache
    from platform_core.services.equipment_model_adapter import default_chat_model_spec

    default_model = await default_chat_model_spec(db)
    return {
        "managed": True,
        "default_model": default_model,
        "models": [
            {
                "id": item.spec,
                "model_spec": item.spec,
                "label": item.display_name or item.model_id,
                "provider": item.provider_id,
                "credential_configured": bool(item.api_key),
            }
            for item in model_cache.get_all_specs("chat")
        ],
    }


async def create_deep_session(
    *,
    db: AsyncSession,
    user: User,
    project_id: str,
    title: str = "",
    topic: str = "",
    focus: str = "",
    run_id: str | None = None,
    model_spec: str | None = None,
    agent_slug: str | None = None,
    knowledge_enabled: bool = True,
    knowledge_ids: list[str] | None = None,
    subagents_enabled: bool = True,
    active_skill_ids: list[str] | None = None,
    research_mode: str = "section_deepen",
    research_section: str = "",
    source_feedback_id: str = "",
    capability_card_key: str = "",
    capability_name: str = "",
    capability_sections: list[dict[str, Any]] | None = None,
    reference_weapons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    project = await _require_project(db, user=user, project_id=project_id)
    execution_user = await _deep_execution_user(db, actor=user, owner_uid=str(project.uid))
    try:
        runtime = await _resolve_requested_model(db, model_spec)
    except HTTPException as exc:
        # Creating a bound conversation must not wait on API keys; the native
        # chat selector validates credentials when the first turn is sent.
        if exc.status_code != 422:
            raise
        from platform_core.services.equipment_model_adapter import default_chat_model_spec

        runtime = {"model_spec": str(model_spec or "").strip() or await default_chat_model_spec(db)}
    resolved_run_id = None
    query_snapshot: list[str] | None = None
    effective_knowledge_enabled = bool(knowledge_enabled)
    resolved_knowledge_ids = (
        list(dict.fromkeys(value.strip() for value in knowledge_ids if value.strip()))[:64]
        if knowledge_ids is not None
        else None
    )
    if run_id:
        run = await _require_run(db, user=user, run_id=run_id, mutation=True)
        if str(run.project_id) != str(project.id) or str(run.owner_uid) != str(project.uid):
            raise HTTPException(status_code=422, detail="研究任务不属于所选项目")
        resolved_run_id = run.id
        topic = topic or run.topic
        run_payload = dict(getattr(run, "payload", None) or {})
        query_snapshot = [
            str(run.topic or "").strip(),
            str(run_payload.get("supplemental_information") or "").strip(),
        ]
        effective_knowledge_enabled = effective_knowledge_enabled and bool(run_payload.get("knowledge_enabled", True))
        if "knowledge_ids" in run_payload:
            run_knowledge_ids = run_payload.get("knowledge_ids")
            if isinstance(run_knowledge_ids, list):
                bounded_run_ids = list(
                    dict.fromkeys(str(value).strip() for value in run_knowledge_ids if str(value).strip())
                )[:64]
                if resolved_knowledge_ids is None:
                    resolved_knowledge_ids = bounded_run_ids
                else:
                    allowed_run_ids = set(bounded_run_ids)
                    resolved_knowledge_ids = [value for value in resolved_knowledge_ids if value in allowed_run_ids]
    requested_references = [item for item in (reference_weapons or [])[:8] if isinstance(item, dict)]
    source_feedback_snapshot: dict[str, Any] | None = None
    normalized_feedback_id = str(source_feedback_id or "").strip()
    if normalized_feedback_id:
        if not resolved_run_id:
            raise HTTPException(status_code=422, detail="专家反馈深研必须关联研究任务")
        feedback = await EquipmentResearchRepository(db).get_expert_feedback(normalized_feedback_id)
        if (
            feedback is None
            or str(feedback.run_id) != str(resolved_run_id)
            or str(feedback.owner_uid) != str(project.uid)
            or (feedback.feedback or {}).get("status") == "rolled_back"
        ):
            raise HTTPException(status_code=422, detail="来源专家反馈无效或不属于该研究任务")
        feedback_payload = dict(feedback.feedback or {})
        source_feedback_snapshot = {
            "feedback_id": feedback.id,
            "capability_id": str(feedback_payload.get("capability_id") or "")[:256],
            "capability_name": str(feedback_payload.get("capability_name") or "")[:400],
            "comment": str(feedback_payload.get("comment") or "")[:4000],
            "verdict": str(feedback_payload.get("verdict") or "")[:64],
            "expert_weighted_score": feedback_payload.get("expert_weighted_score"),
            "rubric_feedback": dict(feedback_payload.get("rubric_feedback") or {}),
        }
    canonical_references: list[dict[str, Any]] = []
    if requested_references:
        if not resolved_run_id:
            raise HTTPException(status_code=422, detail="参考武器必须关联研究任务")
        context_options = await get_deep_context_options(db=db, user=user, run_id=resolved_run_id)
        by_hypothesis = {
            str(item.get("hypothesis_id") or ""): item
            for item in context_options["reference_weapons"]
            if str(item.get("hypothesis_id") or "")
        }
        for requested in requested_references:
            hypothesis_id = str(requested.get("hypothesis_id") or "").strip()
            canonical = by_hypothesis.get(hypothesis_id)
            if canonical is None:
                raise HTTPException(status_code=422, detail="所选参考武器不属于该研究任务")
            if hypothesis_id not in {item["hypothesis_id"] for item in canonical_references}:
                canonical_references.append(canonical)
    from platform_core.repositories.conversation_repository import ConversationRepository
    from platform_core.services.equipment_deep_integration_service import (
        CAPABILITY_PORTRAIT_AGENT_SLUG,
        DEEP_SESSION_SCHEMA_VERSION,
        NEW_WEAPON_DIVERGE_MODE,
        WEAPON_SCHEME_AGENT_SLUG,
        normalize_deep_research_mode,
        resolve_deep_agent,
    )

    normalized_section = str(research_section or "").strip()[:64]
    normalized_research_mode = normalize_deep_research_mode(research_mode)
    requested_agent_slug = agent_slug
    if not str(requested_agent_slug or "").strip() and normalized_section == "装备与技术实现":
        requested_agent_slug = WEAPON_SCHEME_AGENT_SLUG
    elif not str(requested_agent_slug or "").strip() and normalized_research_mode == NEW_WEAPON_DIVERGE_MODE:
        requested_agent_slug = CAPABILITY_PORTRAIT_AGENT_SLUG
    agent = await resolve_deep_agent(
        db=db,
        user=execution_user,
        requested_slug=requested_agent_slug,
    )

    repo = EquipmentResearchRepository(db)
    session_id = _new_id("thinking")
    thread_id = f"equipment-deep-{uuid4()}"
    session_title = (title or topic or "深研对话").strip()[:240] or "深研对话"
    await ConversationRepository(db).add_conversation(
        uid=str(execution_user.uid),
        agent_id=agent.slug,
        title=session_title,
        thread_id=thread_id,
        metadata={
            "source": "equipment_deep_research",
            "schema_version": DEEP_SESSION_SCHEMA_VERSION,
            "equipment_deep_session_id": session_id,
            "equipment_run_id": resolved_run_id,
            "model_spec": runtime["model_spec"],
        },
        project_id=project.id,
    )
    session_payload = {
        "schema_version": DEEP_SESSION_SCHEMA_VERSION,
        "title": session_title,
        "topic": (topic or "").strip()[:500],
        "focus": (focus or "").strip()[:1600],
        "model_spec": runtime["model_spec"],
        "status": "active",
        "kind": "deep-thinking",
        "runtime": "agent",
        "thread_id": thread_id,
        "agent_slug": agent.slug,
        "agent_name": agent.name,
        "knowledge_enabled": effective_knowledge_enabled,
        "subagents_enabled": bool(subagents_enabled),
        "active_skill_ids": list(dict.fromkeys(active_skill_ids or []))[:12],
        "research_mode": normalized_research_mode,
        "research_section": normalized_section,
        "source_feedback_id": normalized_feedback_id,
        "source_feedback_snapshot": source_feedback_snapshot,
        # A card-launched session keeps its binding so reopening it can
        # still offer column-scoped follow-ups against the same card.
        "capability_card_key": str(capability_card_key or "").strip()[:256],
        "capability_name": str(capability_name or "").strip()[:400],
        "capability_sections": [
            {
                "label": str(item.get("label", "") or "").strip()[:64],
                "text": str(item.get("text", "") or "").strip()[:4000],
            }
            for item in (capability_sections or [])[:8]
            if str(item.get("label", "") or "").strip() and str(item.get("text", "") or "").strip()
        ],
        "reference_weapons": canonical_references,
    }
    if resolved_knowledge_ids is not None:
        session_payload["knowledge_ids"] = resolved_knowledge_ids
    if query_snapshot is not None:
        # Immutable launch-time grouping snapshot.  Later Run edits must not
        # silently move an existing conversation to another Query group.
        session_payload["query_snapshot"] = query_snapshot

    session = EquipmentDeepSession(
        id=session_id,
        project_id=project_id,
        owner_uid=str(execution_user.uid),
        run_id=resolved_run_id,
        payload=session_payload,
    )
    await repo.add_deep_session(session)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="create",
        resource_type="deep_session",
        resource_id=session.id,
        owner_uid=str(session.owner_uid),
    )
    await db.commit()
    return session.to_dict()


async def get_deep_session(*, db: AsyncSession, user: User, session_id: str) -> dict[str, Any]:
    repo = EquipmentResearchRepository(db)
    session = await _require_deep_session(db, user=user, session_id=session_id)
    session_payload = dict(session.payload or {})
    thread_id = str(session_payload.get("thread_id") or "")
    if session_payload.get("runtime") == "agent" and thread_id:
        from platform_core.repositories.agent_run_repository import AgentRunRepository
        from platform_core.repositories.conversation_repository import ConversationRepository

        conversation_repo = ConversationRepository(db)
        conversation = await conversation_repo.get_conversation_by_thread_id(thread_id)
        if conversation is None or conversation.uid != str(session.owner_uid):
            raise HTTPException(status_code=404, detail="深研对话线程不存在")
        messages = []
        for item in await conversation_repo.get_messages(conversation.id):
            message = item.to_dict()
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if item.role == "user" and metadata.get("display_content"):
                message["content"] = str(metadata["display_content"])
            messages.append(message)
        run_repo = AgentRunRepository(db)
        native_runs = await run_repo.list_top_level_runs_by_origin(
            uid=str(session.owner_uid),
            source="equipment_deep_research",
            external_id=session.id,
            limit=50,
        )
        native_run_by_request = {item.request_id: item for item in native_runs}
        projected_request_ids: set[str] = set()
        jobs = []
        for item in await repo.list_deep_jobs(session_id):
            job = item.to_dict()
            request_id = str((item.payload or {}).get("request_id") or "")
            run = native_run_by_request.get(request_id) if request_id else None
            if run is not None:
                job["status"] = run.status
                job["run_id"] = run.id
                job["error"] = run.error_message or ""
                projected_request_ids.add(run.request_id)
            jobs.append(job)
        for run in native_runs:
            if run.request_id in projected_request_ids:
                continue
            jobs.append(
                {
                    "job_id": f"agent-run:{run.id}",
                    "session_id": session.id,
                    "status": run.status,
                    "run_id": run.id,
                    "model_spec": str((run.input_payload or {}).get("model_spec") or ""),
                    "error": run.error_message or "",
                    "payload": {
                        "runtime": "agent",
                        "request_id": run.request_id,
                        "source": run.source,
                    },
                    "created_at": run.to_dict()["created_at"],
                    "updated_at": run.to_dict()["updated_at"],
                }
            )
        from platform_core.services.equipment_deep_integration_service import get_session_research_context

        research_context = await get_session_research_context(db=db, user=user, session=session)
        branches = [item.to_dict() for item in await repo.list_deep_branches(session_id)]
    else:
        messages = [item.to_dict() for item in await repo.list_deep_messages(session_id)]
        jobs = [item.to_dict() for item in await repo.list_deep_jobs(session_id)]
        research_context = None
        branches = [item.to_dict() for item in await repo.list_deep_branches(session_id)]
    return {
        **session.to_dict(),
        "messages": messages,
        "jobs": jobs,
        "research_context": research_context,
        "branches": branches,
    }


async def update_deep_session(
    *,
    db: AsyncSession,
    user: User,
    session_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Rename, archive, or restore a deep session and its native Conversation."""

    unsupported = set(changes) - {"title", "archived"}
    if unsupported:
        raise HTTPException(status_code=422, detail="包含不支持的深研对话字段")
    if not changes:
        raise HTTPException(status_code=422, detail="未提供深研对话更新内容")

    normalized_title: str | None = None
    if "title" in changes:
        raw_title = changes["title"]
        if not isinstance(raw_title, str):
            raise HTTPException(status_code=422, detail="深研对话标题必须是字符串")
        normalized_title = raw_title.strip()
        if not normalized_title:
            raise HTTPException(status_code=422, detail="深研对话标题不能为空")
        if len(normalized_title) > 240:
            raise HTTPException(status_code=422, detail="深研对话标题不能超过 240 个字符")

    archived: bool | None = None
    if "archived" in changes:
        archived = changes["archived"]
        if not isinstance(archived, bool):
            raise HTTPException(status_code=422, detail="archived 必须是布尔值")

    session = await _require_deep_session(
        db,
        user=user,
        session_id=session_id,
        mutation=True,
        lock=True,
    )
    conversation = await _lock_native_deep_conversation(db, session)
    payload = dict(session.payload or {})
    now = utc_now_naive()
    if normalized_title is not None:
        payload["title"] = normalized_title
        if conversation is not None:
            conversation.title = normalized_title
    if archived is not None:
        status = "archived" if archived else "active"
        payload["status"] = status
        if conversation is not None:
            conversation.status = status

    session.payload = payload
    session.updated_at = now
    if conversation is not None:
        conversation.updated_at = now

    action = "rename"
    if archived is True:
        action = "archive"
    elif archived is False:
        action = "restore"
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action=action,
        resource_type="deep_session",
        resource_id=session.id,
        owner_uid=str(session.owner_uid),
    )
    await db.commit()
    return {"session": session.to_dict()}


async def delete_deep_session(*, db: AsyncSession, user: User, session_id: str) -> dict[str, Any]:
    """Delete the equipment projection while only soft-deleting Conversation."""

    repo = EquipmentResearchRepository(db)
    session = await _require_deep_session(
        db,
        user=user,
        session_id=session_id,
        mutation=True,
        lock=True,
    )
    conversation = await _lock_native_deep_conversation(db, session)
    payload = dict(session.payload or {})

    native_runs = []
    if payload.get("runtime") == "agent":
        from platform_core.repositories.agent_run_repository import AgentRunRepository

        native_runs = await AgentRunRepository(db).list_top_level_runs_by_origin(
            uid=str(session.owner_uid),
            source="equipment_deep_research",
            external_id=session.id,
            limit=1000,
        )
        if any(
            str(run.status) not in AGENT_RUN_TERMINAL_STATUSES or bool(getattr(run, "runtime_cleanup_pending", False))
            for run in native_runs
        ):
            raise HTTPException(
                status_code=409,
                detail="当前对话仍有平台任务运行，请先取消或等待完成后再删除",
            )

    native_by_request_id = {str(run.request_id): run for run in native_runs}
    native_by_run_id = {str(run.id): run for run in native_runs}
    active_jobs = []
    for job in await repo.list_nonterminal_deep_jobs(session.id):
        job_payload = dict(job.payload or {})
        native_run = native_by_request_id.get(str(job_payload.get("request_id") or ""))
        if native_run is None:
            native_run = native_by_run_id.get(str(job_payload.get("run_id") or ""))
        if (
            job_payload.get("runtime") == "agent"
            and native_run is not None
            and str(native_run.status) in AGENT_RUN_TERMINAL_STATUSES
            and not bool(getattr(native_run, "runtime_cleanup_pending", False))
        ):
            # Native jobs intentionally project AgentRun state at read time;
            # their compatibility row may therefore still say "queued".
            continue
        active_jobs.append(job)
    if active_jobs:
        raise HTTPException(
            status_code=409,
            detail="当前对话仍有研究任务运行，请先取消或等待完成后再删除",
        )

    if conversation is not None:
        conversation.status = "deleted"
        conversation.updated_at = utc_now_naive()
    await repo.delete_deep_session(session.id)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete",
        resource_type="deep_session",
        resource_id=session.id,
        owner_uid=str(session.owner_uid),
    )
    await db.commit()
    return {"deleted": True, "session_id": session.id}


async def send_deep_message(
    *,
    db: AsyncSession,
    user: User,
    session_id: str,
    content: str,
    model_spec: str | None = None,
    focus: str = "",
    create_artifact: bool = False,
    active_skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="消息不能为空")
    if len(text) > 8000:
        raise HTTPException(status_code=422, detail="消息过长")
    repo = EquipmentResearchRepository(db)
    session = await _require_deep_session(
        db,
        user=user,
        session_id=session_id,
        mutation=True,
        lock=True,
    )
    _require_active_deep_session(session)
    execution_user = await _deep_execution_user(db, actor=user, owner_uid=str(session.owner_uid))
    runtime = await _resolve_requested_model(db, model_spec or str((session.payload or {}).get("model_spec") or ""))
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="send_message",
        resource_type="deep_session",
        resource_id=session.id,
        owner_uid=str(session.owner_uid),
    )
    session_payload = dict(session.payload or {})
    if session_payload.get("runtime") == "agent" and session_payload.get("thread_id"):
        return await _send_agent_deep_message(
            db=db,
            user=execution_user,
            actor_uid=str(user.uid),
            session=session,
            content=text,
            runtime=runtime,
            focus=focus,
            create_artifact=create_artifact,
            active_skill_ids=active_skill_ids or [],
        )

    user_message = EquipmentDeepMessage(
        id=_new_id("dmsg"),
        session_id=session_id,
        role="user",
        content=text,
        payload={"model_spec": runtime["model_spec"]},
    )
    await repo.add_deep_message(user_message)
    job = EquipmentDeepJob(
        id=_new_id("djob"),
        session_id=session_id,
        status="queued",
        payload={"model_spec": runtime["model_spec"], "user_message_id": user_message.id},
    )
    await repo.add_deep_job(job)
    session_payload = dict(session.payload or {})
    session_payload["model_spec"] = runtime["model_spec"]
    session.payload = session_payload
    session.updated_at = utc_now_naive()
    from platform_core.services.equipment_deep_task import EQUIPMENT_DEEP_TASK_TYPE

    await _enqueue_typed(
        db,
        name=f"深研对话 {job.id}",
        task_type=EQUIPMENT_DEEP_TASK_TYPE,
        payload={"session_id": session_id, "job_id": job.id},
        match={"job_id": job.id},
    )
    return {"session": session.to_dict(), "job": job.to_dict(), "user_message": user_message.to_dict()}


async def _send_agent_deep_message(
    *,
    db: AsyncSession,
    user: User,
    actor_uid: str,
    session: EquipmentDeepSession,
    content: str,
    runtime: dict[str, Any],
    focus: str,
    create_artifact: bool,
    active_skill_ids: list[str],
) -> dict[str, Any]:
    """把定向深研消息提交到统一 AgentRun，复用知识库、工具与 Subagent。"""
    from platform_core.services.agent_request_service import AgentRequestInput, RunOrigin, submit_agent_request
    from platform_core.services.input_message_service import build_chat_input_message

    payload = dict(session.payload or {})
    request_id = str(uuid4())
    agent_slug = str(payload.get("agent_slug") or "deep-research")
    requested_skills = list(dict.fromkeys([*(payload.get("active_skill_ids") or []), *active_skill_ids]))[:12]

    response = await submit_agent_request(
        request_input=AgentRequestInput(
            agent_slug=agent_slug,
            thread_id=str(payload["thread_id"]),
            request_id=request_id,
            input_message=build_chat_input_message(content, None),
            origin=RunOrigin(
                source="equipment_deep_research",
                channel="web",
                external_id=session.id,
                metadata={"equipment_deep_session_id": session.id, "equipment_run_id": session.run_id},
            ),
            request_metadata={
                "equipment_deep_session_id": session.id,
                "display_content": content,
                "equipment_deep_focus": focus,
                "equipment_create_artifact": bool(create_artifact),
                "equipment_active_skill_ids": requested_skills,
                "equipment_admin_actor_uid": actor_uid if actor_uid != str(user.uid) else "",
            },
            model_spec=runtime["model_spec"],
            queue_policy="enqueue",
        ),
        current_user=user,
        db=db,
    )

    job = EquipmentDeepJob(
        id=_new_id("djob"),
        session_id=session.id,
        status=str(response.get("status") or "queued"),
        payload={
            "model_spec": runtime["model_spec"],
            "request_id": request_id,
            "run_id": response.get("run_id"),
            "runtime": "agent",
        },
    )
    await EquipmentResearchRepository(db).add_deep_job(job)
    payload["model_spec"] = runtime["model_spec"]
    if focus.strip():
        payload["focus"] = focus.strip()[:1600]
    payload["active_skill_ids"] = requested_skills
    session.payload = payload
    session.updated_at = utc_now_naive()
    await db.commit()
    return {"session": session.to_dict(), "job": job.to_dict(), "request": response}


async def fork_deep_session(
    *,
    db: AsyncSession,
    user: User,
    session_id: str,
    from_message_id: str = "",
    title: str = "探索分支",
) -> dict[str, Any]:
    """把研究分支建成独立的平台原生会话，并保留父会话上下文引用。"""
    repo = EquipmentResearchRepository(db)
    parent = await _require_deep_session(
        db,
        user=user,
        session_id=session_id,
        mutation=True,
        lock=True,
    )
    _require_active_deep_session(parent)
    execution_user = await _deep_execution_user(db, actor=user, owner_uid=str(parent.owner_uid))
    parent_payload = dict(parent.payload or {})
    if parent_payload.get("runtime") != "agent" or not parent_payload.get("thread_id"):
        raise HTTPException(status_code=409, detail="历史兼容会话暂不支持平台原生分支")

    from platform_core.repositories.conversation_repository import ConversationRepository

    parent_conversation = await ConversationRepository(db).get_conversation_by_thread_id(
        str(parent_payload["thread_id"])
    )
    if parent_conversation is None or parent_conversation.uid != str(execution_user.uid):
        raise HTTPException(status_code=404, detail="父会话线程不存在")
    normalized_message_id = str(from_message_id or "").strip()
    if normalized_message_id:
        messages = await ConversationRepository(db).get_messages(parent_conversation.id)
        if normalized_message_id not in {str(item.id) for item in messages}:
            raise HTTPException(status_code=422, detail="分支起点消息不属于当前会话")

    child_id = _new_id("thinking")
    branch_id = _new_id("branch")
    thread_id = f"equipment-deep-{uuid4()}"
    branch_title = str(title or "探索分支").strip()[:240] or "探索分支"
    await ConversationRepository(db).add_conversation(
        uid=str(execution_user.uid),
        agent_id=str(parent_payload.get("agent_slug") or "deep-research"),
        title=branch_title,
        thread_id=thread_id,
        metadata={
            "source": "equipment_deep_research",
            "schema_version": parent_payload.get("schema_version"),
            "equipment_deep_session_id": child_id,
            "equipment_run_id": parent.run_id,
            "parent_equipment_deep_session_id": parent.id,
            "branch_id": branch_id,
            "model_spec": parent_payload.get("model_spec"),
        },
        project_id=parent.project_id,
    )
    child = EquipmentDeepSession(
        id=child_id,
        project_id=parent.project_id,
        owner_uid=str(execution_user.uid),
        run_id=parent.run_id,
        payload={
            **parent_payload,
            "title": branch_title,
            "status": "active",
            "thread_id": thread_id,
            "parent_session_id": parent.id,
            "branch_id": branch_id,
            "branch_from_message_id": normalized_message_id,
        },
    )
    await repo.add_deep_session(child)
    branch = EquipmentDeepBranch(
        id=branch_id,
        session_id=parent.id,
        payload={
            "title": branch_title,
            "child_session_id": child.id,
            "from_message_id": normalized_message_id,
        },
    )
    await repo.add_deep_branch(branch)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="fork",
        resource_type="deep_session",
        resource_id=child.id,
        owner_uid=str(child.owner_uid),
    )
    await db.commit()
    return {"session": child.to_dict(), "branch": branch.to_dict()}
