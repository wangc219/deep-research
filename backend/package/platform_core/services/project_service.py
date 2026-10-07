"""Project 创建、选择与历史目录复用用例。"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from platform_core.repositories.project_repository import ProjectRepository
from platform_core.permissions import has_global_business_access
from platform_core.services.personal_resource_audit_service import audit_superadmin_personal_resource_write
from platform_core.storage.postgres.models_business import Project
from platform_core.utils.datetime_utils import utc_now_naive
from platform_core.workspace.paths import allocate_default_user_workdir_path, normalize_workdir_path
from platform_core.workspace.workdir import Workdir

MAX_PROJECT_NAME_LENGTH = 255
DEFAULT_EQUIPMENT_PROJECT_NAME = "武器装备深研"


async def _lock_project_workdir_changes(*, db, uid: str) -> None:
    """串行化同一用户的 linked Project 绑定与测试目录删除。"""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"project-workdir:{uid}"},
    )


def _normalize_project_name(name: str | None, *, required: bool) -> str | None:
    """规范化并校验 Project 名称。"""
    normalized_name = (name or "").strip()
    if required and not normalized_name:
        raise HTTPException(status_code=422, detail="项目名称不能为空")
    if len(normalized_name) > MAX_PROJECT_NAME_LENGTH:
        raise HTTPException(status_code=422, detail="项目名称过长")
    return normalized_name or None


def _require_matching_creation_intent(project: Project, *, name: str, workdir_path: str) -> None:
    """要求已有 Project 仍有效且匹配当前幂等创建意图。"""
    if project.status == "deleted":
        raise HTTPException(status_code=409, detail="request_id 已用于已删除的 Project")
    if project.name != name or project.directory_mode != "linked" or project.workdir_path != workdir_path:
        raise HTTPException(status_code=409, detail="request_id 已用于其他 Project 创建意图")


async def create_project_record(
    *,
    uid: str,
    name: str | None,
    directory_mode: str,
    selection_status: str,
    db,
    workdir_path: str | None = None,
    idempotency_key: str | None = None,
) -> Project:
    """在当前事务内创建 Project，但不提交或物化 managed 目录。"""
    normalized_name = _normalize_project_name(name, required=selection_status == "selectable")
    if directory_mode not in {"managed", "linked"}:
        raise HTTPException(status_code=422, detail="directory_mode 必须是 managed 或 linked")
    if selection_status not in {"implicit", "selectable"}:
        raise HTTPException(status_code=422, detail="selection_status 非法")

    project_id = str(uuid.uuid4())
    if directory_mode == "managed":
        if workdir_path is not None:
            raise HTTPException(status_code=422, detail="managed Project 不接受 workdir_path")
        normalized_path = allocate_default_user_workdir_path(str(uid), project_id)
    else:
        if workdir_path is None:
            raise HTTPException(status_code=422, detail="linked Project 必须指定 workdir_path")
        try:
            normalized_path = normalize_workdir_path(workdir_path)
            await _lock_project_workdir_changes(db=db, uid=str(uid))
            Workdir.open_existing(str(uid), normalized_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="目录不存在") from exc
        except (NotADirectoryError, PermissionError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    project = Project(
        id=project_id,
        uid=str(uid),
        name=normalized_name,
        selection_status=selection_status,
        workdir_path=normalized_path,
        directory_mode=directory_mode,
        idempotency_key=idempotency_key.strip() if idempotency_key else None,
    )
    return await ProjectRepository(db).add(project)


async def create_implicit_project(*, uid: str, db, idempotency_key: str | None = None) -> Project:
    """为新 Conversation 创建 implicit managed Project。"""
    return await create_project_record(
        uid=uid,
        name=None,
        directory_mode="managed",
        selection_status="implicit",
        db=db,
        idempotency_key=idempotency_key,
    )


async def ensure_equipment_project_view(*, uid: str, db) -> dict:
    """返回当前用户的首个可选 Project；没有时创建装备深研默认项目。"""

    normalized_uid = str(uid)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"default-equipment-project:{normalized_uid}"},
    )
    repository = ProjectRepository(db)
    projects = await repository.list_selectable_for_user(normalized_uid)
    if projects:
        return projects[0].to_dict()

    project = await create_project_record(
        uid=normalized_uid,
        name=DEFAULT_EQUIPMENT_PROJECT_NAME,
        directory_mode="managed",
        selection_status="selectable",
        db=db,
    )
    await db.commit()
    return project.to_dict()


async def create_project_view(
    *, uid: str, request_id: str, name: str, directory_mode: str, workdir_path: str | None, db, actor=None
) -> dict:
    """幂等创建 selectable Project。"""
    normalized_request_id = (request_id or "").strip()
    if not normalized_request_id:
        raise HTTPException(status_code=422, detail="request_id 不能为空")
    if directory_mode != "linked" or not (workdir_path or "").strip():
        raise HTTPException(status_code=422, detail="手动创建项目必须选择目录")
    repository = ProjectRepository(db)
    existing = await repository.get_by_idempotency_key(normalized_request_id, str(uid))
    normalized_name = _normalize_project_name(name, required=True)
    try:
        normalized_path = normalize_workdir_path(workdir_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if existing is not None:
        _require_matching_creation_intent(
            existing,
            name=normalized_name,
            workdir_path=normalized_path,
        )
        return existing.to_dict()

    try:
        project = await create_project_record(
            uid=uid,
            name=name,
            directory_mode=directory_mode,
            selection_status="selectable",
            workdir_path=workdir_path,
            db=db,
            idempotency_key=normalized_request_id,
        )
        if actor is not None:
            await audit_superadmin_personal_resource_write(
                db,
                actor=actor,
                action="create_project",
                resource_type="project",
                resource_id=project.id,
                owner_uid=project.uid,
            )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await repository.get_by_idempotency_key(normalized_request_id, str(uid))
        if replay is None:
            raise HTTPException(status_code=409, detail="Project 创建冲突")
        _require_matching_creation_intent(
            replay,
            name=normalized_name,
            workdir_path=normalized_path,
        )
        project = replay
    return project.to_dict()


async def list_projects_view(*, uid: str, db, actor=None) -> list[dict]:
    """普通用户列出自己的 Project；全局管理员列出全部 Project。"""
    owner_uid = None if actor is not None and has_global_business_access(actor) else str(uid)
    repository = ProjectRepository(db)
    projects = (
        await repository.list_selectable_for_user(str(uid))
        if actor is None
        else await repository.list_selectable(owner_uid)
    )
    return [project.to_dict() for project in projects]


async def rename_project_view(*, uid: str, project_id: str, name: str, db, actor=None) -> dict:
    """重命名可管理的 selectable Project，并保持资源所有者不变。"""
    normalized_name = _normalize_project_name(name, required=True)
    repository = ProjectRepository(db)
    owner_scope = None if actor is not None and has_global_business_access(actor) else str(uid)
    project = (
        await repository.lock_active_selectable_for_user(project_id, str(uid))
        if actor is None
        else await repository.lock_active_selectable(project_id, owner_scope)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")

    project.name = normalized_name
    project.updated_at = utc_now_naive()
    if actor is not None:
        await audit_superadmin_personal_resource_write(
            db,
            actor=actor,
            action="rename_project",
            resource_type="project",
            resource_id=project.id,
            owner_uid=project.uid,
        )
    await db.commit()
    await db.refresh(project)
    return project.to_dict()


async def delete_project_view(*, uid: str, project_id: str, db, actor=None) -> dict:
    """软删除可管理的 Project 及其 Conversation，保留 Workdir 字节。"""
    repository = ProjectRepository(db)
    owner_scope = None if actor is not None and has_global_business_access(actor) else str(uid)
    project = (
        await repository.lock_active_selectable_for_user(project_id, str(uid))
        if actor is None
        else await repository.lock_active_selectable(project_id, owner_scope)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project 不存在")

    deleted_conversations = await repository.soft_delete_with_conversations(
        project,
        deleted_at=utc_now_naive(),
    )
    if actor is not None:
        await audit_superadmin_personal_resource_write(
            db,
            actor=actor,
            action="delete_project",
            resource_type="project",
            resource_id=project.id,
            owner_uid=project.uid,
        )
    await db.commit()
    return {"message": "删除成功", "deleted_conversations": deleted_conversations}


async def list_history_candidates_view(
    *, uid: str, db, query: str = "", limit: int = 20, offset: int = 0, actor=None
) -> dict:
    """列出可作为目录快捷入口的历史 Conversation；管理员使用全局视图。"""
    owner_uid = None if actor is not None and has_global_business_access(actor) else str(uid)
    conversations = await ProjectRepository(db).list_history_candidates(owner_uid)
    normalized_query = (query or "").strip().lower()
    items = []
    seen_workdirs = set()
    for item, workdir_path in conversations:
        if workdir_path in seen_workdirs:
            continue
        if (
            normalized_query
            and normalized_query not in (item.title or "").lower()
            and normalized_query not in (item.agent_id or "").lower()
        ):
            continue
        seen_workdirs.add(workdir_path)
        items.append(
            {
                "thread_id": item.thread_id,
                "title": item.title,
                "agent_id": item.agent_id,
                **({"uid": str(getattr(item, "uid", uid))} if owner_uid is None else {}),
                "workdir_path": workdir_path,
                "updated_at": item.updated_at.isoformat(),
            }
        )
    return {"items": items[offset : offset + limit], "has_more": len(items) > offset + limit}
