"""Project HTTP 适配层。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.permissions import has_global_business_access
from server.utils.auth_middleware import get_db, get_required_user
from platform_core.services.project_service import (
    create_project_view,
    delete_project_view,
    ensure_equipment_project_view,
    list_history_candidates_view,
    list_projects_view,
    rename_project_view,
)
from platform_core.storage.postgres.models_business import User

projects = APIRouter(prefix="/projects", tags=["projects"])


class ProjectWorkdirCreate(BaseModel):
    """Project Workdir 创建意图。"""

    model_config = ConfigDict(extra="forbid")

    mode: str = "managed"
    path: str | None = None


class ProjectCreate(BaseModel):
    """独立 Project 创建请求。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, max_length=128)
    name: str
    owner_uid: str | None = Field(None, max_length=64)
    workdir: ProjectWorkdirCreate


class ProjectUpdate(BaseModel):
    """Project 可修改字段。"""

    model_config = ConfigDict(extra="forbid")

    name: str


@projects.get("")
async def list_projects(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户可选择的 Project。"""
    return await list_projects_view(uid=str(current_user.uid), db=db, actor=current_user)


@projects.post("")
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """独立创建 managed 或 linked Project。"""
    owner_uid = str(payload.owner_uid or current_user.uid)
    if owner_uid != str(current_user.uid):
        if not has_global_business_access(current_user):
            raise HTTPException(status_code=404, detail="目标用户不存在")
        owner = await db.scalar(select(User).where(User.uid == owner_uid, User.is_deleted == 0))
        if owner is None:
            raise HTTPException(status_code=404, detail="目标用户不存在")
    return await create_project_view(
        uid=owner_uid,
        request_id=payload.request_id,
        name=payload.name,
        directory_mode=payload.workdir.mode,
        workdir_path=payload.workdir.path,
        db=db,
        actor=current_user,
    )


@projects.post("/defaults/equipment")
async def ensure_equipment_project(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """确保当前用户首次进入装备深研时拥有默认 Project。"""
    return await ensure_equipment_project_view(uid=str(current_user.uid), db=db)


@projects.get("/history-candidates")
async def list_history_candidates(
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """列出可作为目录快捷选择的历史 Conversation。"""
    return await list_history_candidates_view(
        uid=str(current_user.uid), db=db, query=q, limit=limit, offset=offset, actor=current_user
    )


@projects.put("/{project_id}")
async def rename_project(
    project_id: str,
    payload: ProjectUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """重命名当前用户的 Project。"""
    return await rename_project_view(
        uid=str(current_user.uid), project_id=project_id, name=payload.name, db=db, actor=current_user
    )


@projects.delete("/{project_id}")
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """软删除当前用户的 Project 及其中对话。"""
    return await delete_project_view(uid=str(current_user.uid), project_id=project_id, db=db, actor=current_user)
