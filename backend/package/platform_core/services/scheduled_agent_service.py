"""用户 Agent 定时任务的用例、校验和 worker 调度。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadDateError, CroniterError, croniter
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from platform_core.agents.buildin import AgentBackendNotFoundError, get_agent_backend
from platform_core.agents.tool_approval import normalize_tool_approval_mode
from platform_core.repositories.agent_repository import AgentRepository
from platform_core.repositories.project_repository import ProjectRepository
from platform_core.repositories.scheduled_agent_repository import ScheduledAgentRepository
from platform_core.permissions import has_global_business_access
from platform_core.services.agent_request_service import AgentRequestInput, RunOrigin, submit_agent_request
from platform_core.services.input_message_service import build_chat_input_message
from platform_core.services.personal_resource_audit_service import audit_superadmin_personal_resource_write
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import ScheduledAgentJob, ScheduledAgentRun, User
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now_naive
from platform_core.utils.logging_config import logger

SCHEDULED_AGENT_SOURCE = "scheduled_agent"
AGENT_CONVERSATION_TARGET = "agent_conversation"
EQUIPMENT_RESEARCH_TARGET = "equipment_research"
SCHEDULED_TARGET_TYPES = {AGENT_CONVERSATION_TARGET, EQUIPMENT_RESEARCH_TARGET}
MAX_PROMPT_LENGTH = 32_000
MAX_NAME_LENGTH = 255
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def build_request_id(prefix: str, value: str) -> str:
    """为调度对象生成稳定、长度受限的 ID。"""
    return f"{prefix[:16]}-{hashlib.sha256(value.encode()).hexdigest()[:47]}"


def _normalize_request_id(value: str) -> str:
    """校验客户端持有的稳定请求 ID。"""
    request_id = str(value or "").strip()
    if not 8 <= len(request_id) <= 64 or REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise HTTPException(status_code=422, detail="request_id 必须是 8 到 64 位字母、数字或 ._:-")
    return request_id


def _intent_hash(data: dict) -> str:
    """为规范化创建意图生成稳定摘要。"""
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def validate_schedule(cron_expression: str, timezone: str) -> tuple[str, str]:
    """校验 cron 表达式和 IANA 时区。"""
    expression = str(cron_expression or "").strip()
    if not expression:
        raise HTTPException(status_code=422, detail="cron_expression 不能为空")
    try:
        if len(expression.split()) != 5 or not croniter.is_valid(expression):
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="cron_expression 不是有效的 5 段 cron 表达式") from None
    zone = str(timezone or "").strip()
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail="timezone 必须是有效的 IANA 时区") from None
    try:
        next_run_at(expression, zone, utc_now_naive())
    except (CroniterBadDateError, CroniterError, OverflowError, ValueError):
        raise HTTPException(status_code=422, detail="cron_expression 没有可计算的下一次触发时间") from None
    return expression, zone


def next_run_at(cron_expression: str, timezone: str, after: datetime) -> datetime:
    """计算下一次 UTC 触发时间，数据库统一保存无时区 UTC。"""
    zone = ZoneInfo(timezone)
    local_after = after.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    next_local = croniter(cron_expression, local_after).get_next(datetime)
    return next_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _normalize_text(value: str, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field} 不能为空")
    if len(normalized) > maximum:
        raise HTTPException(status_code=422, detail=f"{field} 不能超过 {maximum} 个字符")
    return normalized


def _normalize_target_config(target_type: str, data: dict) -> tuple[str, dict, str, str]:
    """规范化任务目标，并返回 target_type/config/agent_slug/prompt。"""
    normalized_type = str(target_type or AGENT_CONVERSATION_TARGET).strip()
    if normalized_type not in SCHEDULED_TARGET_TYPES:
        raise HTTPException(status_code=422, detail="target_type 不受支持")
    agent_slug = str(data.get("agent_slug") or "").strip()
    prompt = str(data.get("prompt") or "").strip()
    raw_config = data.get("target_config") or {}
    if not isinstance(raw_config, dict):
        raise HTTPException(status_code=422, detail="target_config 必须是对象")
    if normalized_type == AGENT_CONVERSATION_TARGET:
        return (
            normalized_type,
            {},
            _normalize_text(agent_slug, "agent_slug", 64),
            _normalize_text(prompt, "prompt", MAX_PROMPT_LENGTH),
        )

    topic = _normalize_text(raw_config.get("topic") or prompt, "研究主题", MAX_PROMPT_LENGTH)
    source_query_id = str(raw_config.get("source_query_id") or "").strip() or None
    source_query_version = raw_config.get("source_query_version")
    if source_query_version in (None, ""):
        source_query_version = None
    else:
        try:
            source_query_version = int(source_query_version)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="来源 Query 版本无效") from None
        if source_query_version < 1:
            raise HTTPException(status_code=422, detail="来源 Query 版本无效")
    max_rounds = raw_config.get("max_rounds", 2)
    try:
        max_rounds = int(max_rounds)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="max_rounds 必须是整数") from None
    if not 1 <= max_rounds <= 10:
        raise HTTPException(status_code=422, detail="max_rounds 必须在 1 到 10 之间")
    knowledge_ids = raw_config.get("knowledge_ids")
    if knowledge_ids is not None and not isinstance(knowledge_ids, list):
        raise HTTPException(status_code=422, detail="knowledge_ids 必须是数组或 null")
    selected_agent_ids = raw_config.get("selected_agent_ids") or []
    if not isinstance(selected_agent_ids, list):
        raise HTTPException(status_code=422, detail="selected_agent_ids 必须是数组")
    query_version_policy = str(raw_config.get("query_version_policy") or "latest").strip()
    if query_version_policy not in {"latest", "pinned"}:
        raise HTTPException(status_code=422, detail="query_version_policy 不受支持")
    if query_version_policy == "latest":
        source_query_version = None
    config = {
        "topic": topic,
        "source_query_id": source_query_id,
        "source_query_version": source_query_version,
        "query_version_policy": query_version_policy,
        "research_route": str(raw_config.get("research_route") or "auto").strip() or "auto",
        "execution_profile_id": str(
            raw_config.get("execution_profile_id") or "winning_swarm_dynamic_v2"
        ).strip(),
        "interaction_mode": str(raw_config.get("interaction_mode") or "expert").strip(),
        "discovery_branch": str(raw_config.get("discovery_branch") or "auto").strip(),
        "supplemental_information": str(raw_config.get("supplemental_information") or "").strip(),
        "knowledge_enabled": bool(raw_config.get("knowledge_enabled", True)),
        "knowledge_ids": [str(item) for item in knowledge_ids] if knowledge_ids is not None else None,
        "report_template_mode": str(
            raw_config.get("report_template_mode") or "three_layer_nine_item"
        ).strip(),
        "selected_agent_ids": [str(item) for item in selected_agent_ids if str(item).strip()],
        "max_rounds": max_rounds,
    }
    return normalized_type, config, "", topic


async def _validate_project(project_id: str, user: User, db: AsyncSession):
    """锁定任务绑定的活动 Project，直到调用方提交事务。"""
    project = await ProjectRepository(db).lock_active_for_user(project_id, str(user.uid))
    if not project:
        raise HTTPException(status_code=404, detail="Project 不存在或不可访问")
    return project


async def _validate_agent(agent_slug: str, user: User, db: AsyncSession):
    repo = AgentRepository(db)
    agent = await repo.get_visible_by_slug(slug=agent_slug, user=user, kind="main")
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在或不可访问")
    try:
        get_agent_backend(agent.backend_id)
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return agent


async def _job_for_actor(
    repo: ScheduledAgentRepository,
    *,
    job_id: str,
    actor: User,
    lock: bool,
) -> ScheduledAgentJob | None:
    """按普通用户 owner-only、管理员全局业务权限读取定时任务。"""

    owner_uid = None if has_global_business_access(actor) else str(actor.uid)
    return await repo.get_job(job_id, owner_uid, lock=lock)


async def _job_execution_user(job: ScheduledAgentJob, actor: User, db: AsyncSession) -> User:
    """管理员代管时恢复任务所有者身份，避免 Project、Workdir 与运行数据漂移。"""

    owner_uid = str(getattr(job, "uid", actor.uid))
    if owner_uid == str(actor.uid):
        return actor
    owner = await db.scalar(select(User).where(User.uid == owner_uid, User.is_deleted == 0))
    if owner is None:
        raise HTTPException(status_code=404, detail="任务所有者不存在或已停用")
    return owner


def _new_scheduled_run(
    *,
    job: ScheduledAgentJob,
    trigger: str,
    occurrence_key: str,
    scheduled_for: datetime,
    active_run: bool,
    identity: str | None = None,
) -> ScheduledAgentRun:
    """从任务快照创建一次触发意图。"""
    identity = identity or f"{job.id}:{occurrence_key}"
    return ScheduledAgentRun(
        id=build_request_id("scheduled-run", identity),
        job_id=job.id,
        request_id=build_request_id("scheduled-request", identity),
        thread_id=build_request_id("scheduled-thread", identity),
        trigger=trigger,
        occurrence_key=occurrence_key,
        scheduled_for=scheduled_for,
        project_id=job.project_id,
        target_type=getattr(job, "target_type", AGENT_CONVERSATION_TARGET),
        target_config=dict(getattr(job, "target_config", None) or {}),
        agent_slug=job.agent_slug,
        conversation_title=job.name,
        prompt=job.prompt,
        tool_approval_mode=job.tool_approval_mode,
        model_spec=job.model_spec,
        status="skipped" if active_run else "dispatching",
        error_message="上一次运行尚未结束" if active_run else None,
    )


async def _create_run_record(
    *,
    repo: ScheduledAgentRepository,
    job: ScheduledAgentJob,
    trigger: str,
    occurrence_key: str,
    scheduled_for: datetime,
) -> ScheduledAgentRun:
    """创建包含配置快照且禁止重叠的执行记录。"""
    return await repo.add_run(
        _new_scheduled_run(
            job=job,
            trigger=trigger,
            occurrence_key=occurrence_key,
            scheduled_for=scheduled_for,
            active_run=await repo.has_active_run(job.id),
        )
    )


async def list_scheduled_jobs(*, user: User, db: AsyncSession) -> dict:
    """普通用户列出自己的定时任务；全局管理员列出全部任务。"""
    repo = ScheduledAgentRepository(db)
    owner_uid = None if has_global_business_access(user) else str(user.uid)
    jobs = await repo.list_jobs(owner_uid)
    runs_by_job: dict[str, list[dict]] = {job.id: [] for job in jobs}
    for scheduled_run, request, run, equipment_run in await repo.list_recent_runs(
        [job.id for job in jobs], owner_uid, 3
    ):
        runs_by_job[scheduled_run.job_id].append(
            _execution_to_dict(scheduled_run, request, run, equipment_run)
        )
    result = []
    for job in jobs:
        item = job.to_dict()
        item["runs"] = runs_by_job[job.id]
        result.append(item)
    return {"jobs": result}


def _execution_to_dict(scheduled_run, request, run, equipment_run=None) -> dict:
    """以 Request/Run 为执行状态事实源，装配调度记录摘要。"""
    data = scheduled_run.to_dict()
    if getattr(scheduled_run, "target_type", AGENT_CONVERSATION_TARGET) == EQUIPMENT_RESEARCH_TARGET:
        data["conversation_available"] = False
        data["result_available"] = equipment_run is not None
        if equipment_run is not None:
            data["status"] = equipment_run.status
            data["error_message"] = equipment_run.error or None
            data["completed_at"] = (
                format_utc_datetime(equipment_run.updated_at)
                if equipment_run.status in {"completed", "failed", "cancelled", "archived"}
                else None
            )
            data["open_path"] = f"/equipment/runs/{equipment_run.id}"
        return data
    data["conversation_available"] = request is not None
    if scheduled_run.status != "submitted" or request is None:
        return data

    data["run_id"] = request.dispatched_run_id
    if request.status != "dispatched" or run is None:
        data["status"] = request.status
        data["error_message"] = request.error_message
        return data

    data["status"] = run.status
    data["error_message"] = run.error_message
    data["completed_at"] = format_utc_datetime(run.finished_at)
    return data


async def create_scheduled_job(*, user: User, db: AsyncSession, data: dict) -> dict:
    """按稳定请求 ID 幂等创建用户定时任务。"""
    repo = ScheduledAgentRepository(db)
    request_id = _normalize_request_id(data.get("request_id"))
    project_id = _normalize_text(data.get("project_id"), "project_id", 64)
    name = _normalize_text(data.get("name"), "name", MAX_NAME_LENGTH)
    target_type, target_config, agent_slug, prompt = _normalize_target_config(
        data.get("target_type", AGENT_CONVERSATION_TARGET), data
    )
    expression, timezone = validate_schedule(data.get("cron_expression"), data.get("timezone"))
    model_spec = str(data.get("model_spec") or "").strip() or None
    if model_spec and len(model_spec) > 512:
        raise HTTPException(status_code=422, detail="model_spec 不能超过 512 个字符")
    try:
        tool_approval_mode = normalize_tool_approval_mode(data.get("tool_approval_mode", "default"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    intent_hash = _intent_hash(
        {
            "project_id": project_id,
            "target_type": target_type,
            "target_config": target_config,
            "agent_slug": agent_slug,
            "name": name,
            "prompt": prompt,
            "tool_approval_mode": tool_approval_mode,
            "model_spec": model_spec,
            "cron_expression": expression,
            "timezone": timezone,
            "enabled": bool(data.get("enabled", True)),
        }
    )
    existing = await repo.get_job_by_creation_request(str(user.uid), request_id)
    if existing is not None:
        if existing.creation_intent_hash != intent_hash:
            raise HTTPException(status_code=409, detail="request_id 已用于其他定时任务创建意图")
        return existing.to_dict()

    await _validate_project(project_id, user, db)
    if target_type == AGENT_CONVERSATION_TARGET:
        await _validate_agent(agent_slug, user, db)
    now = utc_now_naive()
    job = ScheduledAgentJob(
        id=str(uuid.uuid4()),
        uid=str(user.uid),
        creation_request_id=request_id,
        creation_intent_hash=intent_hash,
        project_id=project_id,
        target_type=target_type,
        target_config=target_config,
        agent_slug=agent_slug,
        name=name,
        prompt=prompt,
        tool_approval_mode=tool_approval_mode,
        model_spec=model_spec,
        cron_expression=expression,
        timezone=timezone,
        enabled=bool(data.get("enabled", True)),
        next_run_at=next_run_at(expression, timezone, now),
        created_at=now,
        updated_at=now,
    )
    try:
        await repo.add_job(job)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await repo.get_job_by_creation_request(str(user.uid), request_id)
        if replay is None:
            raise HTTPException(status_code=409, detail="定时任务创建冲突")
        if replay.creation_intent_hash != intent_hash:
            raise HTTPException(status_code=409, detail="request_id 已用于其他定时任务创建意图")
        job = replay
    return job.to_dict()


async def update_scheduled_job(*, job_id: str, user: User, db: AsyncSession, data: dict) -> dict | None:
    """更新可管理任务；管理员代管时继续使用任务所有者的运行域。"""
    repo = ScheduledAgentRepository(db)
    job = await _job_for_actor(repo, job_id=job_id, actor=user, lock=True)
    if not job:
        return None
    execution_user = await _job_execution_user(job, user, db)
    owner_uid = str(getattr(job, "uid", user.uid))
    if "project_id" in data:
        project_id = _normalize_text(data["project_id"], "project_id", 64)
        await _validate_project(project_id, execution_user, db)
        job.project_id = project_id
    if "name" in data:
        job.name = _normalize_text(data["name"], "name", MAX_NAME_LENGTH)
    if {"target_type", "target_config", "agent_slug", "prompt"}.intersection(data):
        target_input = {
            "target_config": data.get("target_config", getattr(job, "target_config", {})),
            "agent_slug": data.get("agent_slug", getattr(job, "agent_slug", "")),
            "prompt": data.get("prompt", getattr(job, "prompt", "")),
        }
        target_type, target_config, agent_slug, prompt = _normalize_target_config(
            data.get("target_type", getattr(job, "target_type", AGENT_CONVERSATION_TARGET)),
            target_input,
        )
        if target_type == AGENT_CONVERSATION_TARGET:
            await _validate_agent(agent_slug, execution_user, db)
        job.target_type = target_type
        job.target_config = target_config
        job.agent_slug = agent_slug
        job.prompt = prompt
    if "tool_approval_mode" in data:
        try:
            job.tool_approval_mode = normalize_tool_approval_mode(data["tool_approval_mode"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    if "model_spec" in data:
        model_spec = str(data["model_spec"] or "").strip() or None
        if model_spec and len(model_spec) > 512:
            raise HTTPException(status_code=422, detail="model_spec 不能超过 512 个字符")
        job.model_spec = model_spec
    expression = data.get("cron_expression", job.cron_expression)
    timezone = data.get("timezone", job.timezone)
    expression, timezone = validate_schedule(expression, timezone)
    if expression != job.cron_expression or timezone != job.timezone:
        job.next_run_at = next_run_at(expression, timezone, utc_now_naive())
    job.cron_expression, job.timezone = expression, timezone
    now = utc_now_naive()
    if "enabled" in data:
        enabled = bool(data["enabled"])
        if enabled and not job.enabled:
            job.next_run_at = next_run_at(expression, timezone, now)
        job.enabled = enabled
    job.updated_at = now
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="update_scheduled_agent_job",
        resource_type="scheduled_agent_job",
        resource_id=job_id,
        owner_uid=owner_uid,
    )
    await db.commit()
    return job.to_dict()


async def delete_scheduled_job(*, job_id: str, user: User, db: AsyncSession) -> bool:
    """软删除任务定义，保留触发记录与 AgentRun。"""
    repo = ScheduledAgentRepository(db)
    job = await _job_for_actor(repo, job_id=job_id, actor=user, lock=True)
    if not job:
        return False
    owner_uid = str(getattr(job, "uid", user.uid))
    await repo.delete_job(job)
    await audit_superadmin_personal_resource_write(
        db,
        actor=user,
        action="delete_scheduled_agent_job",
        resource_type="scheduled_agent_job",
        resource_id=job_id,
        owner_uid=owner_uid,
    )
    await db.commit()
    return True


async def run_scheduled_job_now(
    *,
    job_id: str,
    request_id: str,
    user: User,
    db: AsyncSession,
) -> dict | None:
    """按稳定请求 ID 幂等创建手动触发记录。"""
    repo = ScheduledAgentRepository(db)
    request_id = _normalize_request_id(request_id)
    job = await _job_for_actor(repo, job_id=job_id, actor=user, lock=True)
    if not job:
        return None
    execution_user = await _job_execution_user(job, user, db)
    owner_uid = str(getattr(job, "uid", user.uid))
    identity = f"{owner_uid}:manual:{request_id}"
    run_id = build_request_id("scheduled-run", identity)
    run = await repo.get_run(run_id)
    if run is not None and run.job_id != job.id:
        raise HTTPException(status_code=409, detail="request_id 已用于其他立即运行意图")
    if run is None:
        await _validate_project(job.project_id, execution_user, db)
        if job.target_type == AGENT_CONVERSATION_TARGET:
            await _validate_agent(job.agent_slug, execution_user, db)
        now = utc_now_naive()
        run = _new_scheduled_run(
            job=job,
            trigger="manual",
            occurrence_key=f"manual:{request_id}",
            scheduled_for=now,
            active_run=await repo.has_active_run(job.id),
            identity=identity,
        )
        try:
            await repo.add_run(run)
            await audit_superadmin_personal_resource_write(
                db,
                actor=user,
                action="run_scheduled_agent_job_now",
                resource_type="scheduled_agent_job",
                resource_id=job_id,
                owner_uid=owner_uid,
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            replay = await repo.get_run(run_id)
            if replay is None:
                raise HTTPException(status_code=409, detail="立即运行请求冲突")
            if replay.job_id != job.id:
                raise HTTPException(status_code=409, detail="request_id 已用于其他立即运行意图")
            run = replay
    else:
        await audit_superadmin_personal_resource_write(
            db,
            actor=user,
            action="run_scheduled_agent_job_now",
            resource_type="scheduled_agent_job",
            resource_id=job_id,
            owner_uid=owner_uid,
        )
        await db.commit()
    if run.status != "dispatching":
        return run.to_dict()
    return await dispatch_scheduled_run(scheduled_run_id=run.id)


async def _settle_dispatch_error(
    scheduled_run_id: str,
    error: Exception,
    *,
    terminal: bool,
) -> dict | None:
    """串行重查 Request；仅明确不可重试错误终结触发记录。"""
    async with pg_manager.get_async_session_context() as db:
        scheduled_run = await db.scalar(
            select(ScheduledAgentRun).where(ScheduledAgentRun.id == scheduled_run_id).with_for_update()
        )
        if scheduled_run is None:
            return None
        request = None
        run = None
        equipment_run = None
        if scheduled_run.status == "dispatching":
            if scheduled_run.target_type == EQUIPMENT_RESEARCH_TARGET:
                if scheduled_run.equipment_run_id:
                    from platform_core.storage.postgres.models_equipment import EquipmentResearchRun

                    equipment_run = await db.get(EquipmentResearchRun, scheduled_run.equipment_run_id)
            else:
                request, run = await ScheduledAgentRepository(db).get_request_and_run(
                    scheduled_run.request_id
                )
            if request is not None or equipment_run is not None:
                scheduled_run.status = "submitted"
            elif terminal:
                scheduled_run.status = "failed"
                scheduled_run.error_message = str(error)
            if request is not None or equipment_run is not None or terminal:
                await db.commit()
        return _execution_to_dict(scheduled_run, request, run, equipment_run)


async def _dispatch_equipment_research(
    *,
    db: AsyncSession,
    scheduled_run: ScheduledAgentRun,
    job: ScheduledAgentJob,
    user: User,
) -> dict:
    """幂等创建并启动一次独立装备研究任务。"""
    from platform_core.services.equipment_research_service import create_run, start_run
    from platform_core.storage.postgres.models_equipment import EquipmentResearchRun

    config = dict(scheduled_run.target_config or {})
    topic = str(config.pop("topic", "") or scheduled_run.prompt).strip()
    source_query_id = config.pop("source_query_id", None)
    source_query_version = config.pop("source_query_version", None)
    research_route = str(config.pop("research_route", "auto") or "auto")
    created = await create_run(
        db=db,
        user=user,
        project_id=scheduled_run.project_id,
        topic=topic,
        research_route=research_route,
        model_spec=scheduled_run.model_spec,
        payload={
            **config,
            "scheduled_job_id": job.id,
            "scheduled_run_id": scheduled_run.id,
            "schedule_trigger": scheduled_run.trigger,
        },
        source_query_id=source_query_id,
        source_query_version=source_query_version,
        idempotency_key=f"scheduled:{scheduled_run.id}",
    )
    scheduled_run.equipment_run_id = str(created["run_id"])
    if str(created.get("status") or "") in {"draft", "paused"}:
        await start_run(db=db, user=user, run_id=scheduled_run.equipment_run_id)
    scheduled_run.status = "submitted"
    scheduled_run.error_message = None
    job.updated_at = utc_now_naive()
    await db.commit()
    equipment_run = await db.get(EquipmentResearchRun, scheduled_run.equipment_run_id)
    return _execution_to_dict(scheduled_run, None, None, equipment_run)


async def dispatch_scheduled_run(*, scheduled_run_id: str) -> dict | None:
    """将持久触发意图幂等提交到对话或装备研究执行链路。"""
    try:
        async with pg_manager.get_async_session_context() as db:
            scheduled_run = await db.scalar(
                select(ScheduledAgentRun).where(ScheduledAgentRun.id == scheduled_run_id).with_for_update()
            )
            if scheduled_run is None or scheduled_run.status != "dispatching":
                return scheduled_run.to_dict() if scheduled_run else None
            job = await db.get(ScheduledAgentJob, scheduled_run.job_id)
            user = (
                await db.scalar(select(User).where(User.uid == job.uid, User.is_deleted == 0).with_for_update())
                if job
                else None
            )
            if job is None or user is None:
                scheduled_run.status = "cancelled"
                scheduled_run.error_message = "任务已删除、停用或用户不存在"
                await db.commit()
                return scheduled_run.to_dict()
            if scheduled_run.trigger == "scheduled" and (not job.enabled or job.deleted_at is not None):
                scheduled_run.status = "cancelled"
                scheduled_run.error_message = "任务已停用或删除"
                await db.commit()
                return scheduled_run.to_dict()
            await _validate_project(scheduled_run.project_id, user, db)
            if scheduled_run.target_type == EQUIPMENT_RESEARCH_TARGET:
                return await _dispatch_equipment_research(
                    db=db,
                    scheduled_run=scheduled_run,
                    job=job,
                    user=user,
                )
            await _validate_agent(scheduled_run.agent_slug, user, db)
            await submit_agent_request(
                request_input=AgentRequestInput(
                    agent_slug=scheduled_run.agent_slug,
                    thread_id=scheduled_run.thread_id,
                    request_id=scheduled_run.request_id,
                    input_message=build_chat_input_message(scheduled_run.prompt),
                    origin=RunOrigin(
                        source=SCHEDULED_AGENT_SOURCE,
                        channel="worker",
                        external_id=scheduled_run.id,
                        metadata={"scheduled_job_id": job.id, "scheduled_run_id": scheduled_run.id},
                    ),
                    request_metadata={"scheduled_job_id": job.id, "scheduled_run_id": scheduled_run.id},
                    tool_approval_mode=scheduled_run.tool_approval_mode,
                    model_spec=scheduled_run.model_spec,
                    queue_policy="enqueue",
                    create_conversation=True,
                    conversation_title=scheduled_run.conversation_title,
                    conversation_project_id=scheduled_run.project_id,
                ),
                current_user=user,
                db=db,
            )
            scheduled_run.status = "submitted"
            job.updated_at = utc_now_naive()
            await db.commit()
            request, run = await ScheduledAgentRepository(db).get_request_and_run(scheduled_run.request_id)
            return _execution_to_dict(scheduled_run, request, run)
    except HTTPException as exc:
        settled = await _settle_dispatch_error(scheduled_run_id, exc, terminal=True)
        if settled is None:
            raise
        return settled
    except Exception as exc:
        settled = await _settle_dispatch_error(scheduled_run_id, exc, terminal=False)
        if settled is not None and settled["status"] == "submitted":
            return settled
        raise


async def recover_scheduled_dispatches(*, limit: int = 100) -> int:
    """恢复 worker 中断后遗留的定时触发意图。"""
    async with pg_manager.get_async_session_context() as db:
        records = await ScheduledAgentRepository(db).list_dispatching_runs(
            before=utc_now_naive() - timedelta(seconds=30),
            limit=limit,
        )
    recovered = 0
    for record in records:
        try:
            await dispatch_scheduled_run(scheduled_run_id=record.id)
            recovered += 1
        except Exception:
            logger.error(f"恢复定时任务触发失败: scheduled_run={record.id}", exc_info=True)
    return recovered


async def _claim_due_run(*, db: AsyncSession, now: datetime) -> ScheduledAgentRun | None:
    """在一个事务中领取到期任务、推进计划并创建触发意图。"""
    repo = ScheduledAgentRepository(db)
    while job := await repo.claim_due_job(now=now):
        scheduled_for = job.next_run_at
        try:
            job.next_run_at = next_run_at(job.cron_expression, job.timezone, now)
        except (CroniterError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
            job.enabled = False
            job.updated_at = now
            await db.commit()
            logger.error(
                f"已停用无法计算下次触发时间的定时任务: scheduled_job={job.id}",
                exc_info=True,
            )
            continue
        job.updated_at = now
        run = await _create_run_record(
            repo=repo,
            job=job,
            trigger="scheduled",
            occurrence_key=f"scheduled:{scheduled_for.isoformat()}",
            scheduled_for=scheduled_for,
        )
        await db.commit()
        return run
    return None


async def claim_and_dispatch_due_jobs(*, limit: int = 20) -> int:
    """批量领取到期任务并提交对应 AgentRun。"""
    count = 0
    for _ in range(max(0, limit)):
        async with pg_manager.get_async_session_context() as db:
            run = await _claim_due_run(db=db, now=utc_now_naive())
            if run is None:
                break
            run_id = run.id
        if run.status == "dispatching":
            try:
                await dispatch_scheduled_run(scheduled_run_id=run_id)
            except Exception:
                logger.error(f"提交到期定时任务失败: scheduled_run={run_id}", exc_info=True)
        count += 1
    return count
