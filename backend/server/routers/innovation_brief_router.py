"""前沿技术创意简报中心 HTTP 接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.permissions import ResourcePermission
from platform_core.services.innovation_brief_service import (
    create_brief_run,
    create_subscription,
    delete_subscription,
    get_brief,
    list_brief_runs,
    list_briefs,
    list_subscriptions,
    mark_brief_read,
    update_subscription,
)
from platform_core.services.knowledge_governance_service import user_tenant_id
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_knowledge_governance import KnowledgeSource
from server.utils.auth_middleware import get_db, get_required_user
from server.utils.knowledge_permissions import ensure_knowledge_base_permission

router = APIRouter()


class BriefSubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    topics: list[str] = Field(default_factory=list, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    knowledge_ids: list[str] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    languages: list[str] = Field(default_factory=lambda: ["zh-CN", "en"])
    timezone: str = "Asia/Shanghai"
    daily_enabled: bool = True
    weekly_enabled: bool = True
    daily_cron: str = "0 8 * * *"
    weekly_cron: str = "0 9 * * 1"
    reminder_sensitivity: Literal["conservative", "standard", "sensitive"] = "standard"
    significance_threshold: float = Field(default=70, ge=0, le=100)
    open_discovery_enabled: bool = True
    research_explorer_enabled: bool = True
    enabled: bool = True


class BriefSubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    topics: list[str] | None = Field(default=None, max_length=100)
    keywords: list[str] | None = Field(default=None, max_length=100)
    knowledge_ids: list[str] | None = Field(default=None, max_length=50)
    source_ids: list[str] | None = Field(default=None, max_length=100)
    languages: list[str] | None = None
    timezone: str | None = None
    daily_enabled: bool | None = None
    weekly_enabled: bool | None = None
    daily_cron: str | None = None
    weekly_cron: str | None = None
    reminder_sensitivity: Literal["conservative", "standard", "sensitive"] | None = None
    significance_threshold: float | None = Field(default=None, ge=0, le=100)
    open_discovery_enabled: bool | None = None
    research_explorer_enabled: bool | None = None
    enabled: bool | None = None


class BriefRunRequest(BaseModel):
    brief_type: Literal["daily", "weekly"] = "daily"


class BriefReadRequest(BaseModel):
    read: bool = True


async def _validate_scope_permissions(
    db: AsyncSession,
    current_user: User,
    knowledge_ids: list[str] | None,
    source_ids: list[str] | None,
) -> None:
    kb_ids = {str(item) for item in knowledge_ids or [] if str(item).strip()}
    if source_ids:
        rows = list(
            (
                await db.scalars(
                    select(KnowledgeSource).where(
                        KnowledgeSource.tenant_id == user_tenant_id(current_user),
                        KnowledgeSource.id.in_(source_ids),
                    )
                )
            ).all()
        )
        kb_ids.update(row.kb_id for row in rows)
    for kb_id in kb_ids:
        await ensure_knowledge_base_permission(kb_id, current_user, ResourcePermission.READ)


@router.get("/brief-subscriptions")
async def get_brief_subscriptions(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_subscriptions(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
    )


@router.post("/brief-subscriptions", status_code=status.HTTP_201_CREATED)
async def post_brief_subscription(
    body: BriefSubscriptionCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await _validate_scope_permissions(db, current_user, body.knowledge_ids, body.source_ids)
    return await create_subscription(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
        data=body.model_dump(),
    )


@router.patch("/brief-subscriptions/{subscription_id}")
async def patch_brief_subscription(
    subscription_id: str,
    body: BriefSubscriptionUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    values = body.model_dump(exclude_unset=True)
    await _validate_scope_permissions(db, current_user, values.get("knowledge_ids"), values.get("source_ids"))
    return await update_subscription(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
        subscription_id=subscription_id,
        data=values,
    )


@router.delete("/brief-subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_brief_subscription(
    subscription_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_subscription(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
        subscription_id=subscription_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/brief-subscriptions/{subscription_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_brief_subscription(
    subscription_id: str,
    body: BriefRunRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_brief_run(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
        subscription_id=subscription_id,
        brief_type=body.brief_type,
    )


@router.get("/brief-subscriptions/runs")
async def get_brief_run_history(
    subscription_id: str | None = None,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_brief_runs(
        db,
        tenant_id=user_tenant_id(current_user),
        owner_uid=current_user.uid,
        subscription_id=subscription_id,
    )


@router.get("/briefs")
async def get_briefs(
    brief_type: str | None = Query(default=None),
    unread: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_briefs(
        db,
        owner_uid=current_user.uid,
        brief_type=brief_type,
        unread=unread,
        page=page,
        page_size=page_size,
    )


@router.get("/briefs/{brief_id}")
async def get_brief_detail(
    brief_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_brief(db, owner_uid=current_user.uid, brief_id=brief_id)


@router.post("/briefs/{brief_id}/read")
async def set_brief_read(
    brief_id: str,
    body: BriefReadRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await mark_brief_read(db, owner_uid=current_user.uid, brief_id=brief_id, read=body.read)
