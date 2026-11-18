"""知识分类、统一来源与暂存审核 HTTP 接口。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.knowledge.runtime import knowledge_base
from platform_core.services.knowledge_governance_service import (
    create_category,
    create_source,
    create_source_run,
    delete_category,
    delete_source,
    list_category_tree,
    list_source_runs,
    list_sources,
    list_staging_items,
    review_staging_items,
    source_governance_enabled,
    test_source_connection,
    update_category,
    update_source,
    user_tenant_id,
)
from platform_core.storage.postgres.models_business import User
from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from server.utils.knowledge_permissions import ensure_knowledge_base_permission
from platform_core.permissions import ResourcePermission

router = APIRouter()


async def require_source_governance_enabled() -> None:
    """在禁用环境中用 404 隐藏来源治理接口。"""
    if not source_governance_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = None
    description: str = ""
    sort_order: int = 0
    active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: str | None = None
    description: str | None = None
    sort_order: int | None = None
    active: bool | None = None


class SourceCreate(BaseModel):
    kb_id: str
    category_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    source_type: Literal["upload", "postgresql", "mysql", "website", "web_search"]
    config: dict[str, Any] = Field(default_factory=dict)
    credential: dict[str, Any] | None = None
    enabled: bool = True
    notify_on_new: bool = False
    cron_expression: str | None = None
    timezone: str = "Asia/Shanghai"


class SourceUpdate(BaseModel):
    category_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    credential: dict[str, Any] | None = None
    enabled: bool | None = None
    notify_on_new: bool | None = None
    cron_expression: str | None = None
    timezone: str | None = None


class StagingReview(BaseModel):
    kb_id: str
    ids: list[str] = Field(min_length=1, max_length=100)
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)
    category_id: str | None = None


async def _require_source_manage(
    db: AsyncSession,
    current_user: User,
    source_id: str,
) -> dict:
    response = await list_sources(db, tenant_id=user_tenant_id(current_user))
    source = next((item for item in response["items"] if item["id"] == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="知识来源不存在")
    await ensure_knowledge_base_permission(source["kb_id"], current_user, ResourcePermission.MANAGE)
    return source


@router.get("/categories")
async def get_categories(
    include_inactive: bool = False,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    databases = await knowledge_base.get_databases_by_uid(current_user.uid)
    can_include_inactive = include_inactive and current_user.role in {"admin", "superadmin"}
    return await list_category_tree(
        db,
        tenant_id=user_tenant_id(current_user),
        include_inactive=can_include_inactive,
        accessible_kb_ids={item.kb_id for item in databases},
    )


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def post_category(
    body: CategoryCreate,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_category(
        db,
        tenant_id=user_tenant_id(current_user),
        user_uid=current_user.uid,
        data=body.model_dump(),
    )


@router.patch("/categories/{category_id}")
async def patch_category(
    category_id: str,
    body: CategoryUpdate,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_category(
        db,
        tenant_id=user_tenant_id(current_user),
        category_id=category_id,
        data=body.model_dump(exclude_unset=True),
    )


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_category(
    category_id: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_category(db, tenant_id=user_tenant_id(current_user), category_id=category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources")
async def get_sources(
    kb_id: str = Query(...),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_knowledge_base_permission(kb_id, current_user, ResourcePermission.MANAGE)
    return await list_sources(db, tenant_id=user_tenant_id(current_user), kb_id=kb_id)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def post_source(
    body: SourceCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_knowledge_base_permission(body.kb_id, current_user, ResourcePermission.MANAGE)
    return await create_source(
        db,
        tenant_id=user_tenant_id(current_user),
        user_uid=current_user.uid,
        data=body.model_dump(),
    )


@router.patch("/sources/{source_id}")
async def patch_source(
    source_id: str,
    body: SourceUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_source_manage(db, current_user, source_id)
    return await update_source(
        db,
        tenant_id=user_tenant_id(current_user),
        source_id=source_id,
        user_uid=current_user.uid,
        data=body.model_dump(exclude_unset=True),
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_source(
    source_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_source_manage(db, current_user, source_id)
    await delete_source(db, tenant_id=user_tenant_id(current_user), source_id=source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sources/{source_id}/test")
async def test_source(
    source_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_source_manage(db, current_user, source_id)
    return await test_source_connection(db, tenant_id=user_tenant_id(current_user), source_id=source_id)


@router.post("/sources/{source_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_source(
    source_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_source_manage(db, current_user, source_id)
    return await create_source_run(
        db,
        tenant_id=user_tenant_id(current_user),
        source_id=source_id,
        owner_uid=current_user.uid,
    )


@router.get("/sources/{source_id}/runs")
async def get_source_runs(
    source_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_source_manage(db, current_user, source_id)
    return await list_source_runs(db, tenant_id=user_tenant_id(current_user), source_id=source_id)


@router.get("/staging")
async def get_staging(
    kb_id: str = Query(...),
    review_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_knowledge_base_permission(kb_id, current_user, ResourcePermission.MANAGE)
    return await list_staging_items(
        db,
        tenant_id=user_tenant_id(current_user),
        kb_id=kb_id,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )


@router.post("/staging/review")
async def review_staging(
    body: StagingReview,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_knowledge_base_permission(body.kb_id, current_user, ResourcePermission.MANAGE)
    return await review_staging_items(
        db,
        tenant_id=user_tenant_id(current_user),
        kb_id=body.kb_id,
        user_uid=current_user.uid,
        ids=body.ids,
        decision=body.decision,
        note=body.note,
        category_id=body.category_id,
    )
