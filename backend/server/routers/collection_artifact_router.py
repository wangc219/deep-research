"""采集成果的沙盒工作区列表、同步及批量下载。"""

import asyncio
import os
import tempfile
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from platform_core.services import collection_artifact_service as service
from platform_core.permissions import ResourcePermission
from platform_core.services.knowledge_governance_service import ensure_category_for_kb, user_tenant_id
from platform_core.storage.postgres.models_business import User
from server.utils.auth_middleware import get_db, get_required_user
from server.utils.knowledge_permissions import ensure_knowledge_base_permission

router = APIRouter(prefix="/collection-artifacts", tags=["collection-artifacts"])
Source = Literal["wechat-articles", "wxchannels"]


class Selection(BaseModel):
    """只接受来源清单内的成果标识，不接受服务器文件路径。"""

    ids: list[str] = Field(min_length=1, max_length=100)


class IngestSelection(Selection):
    kb_id: str
    category_id: str | None = None


@router.get("/{source}")
async def artifacts(
    source: Source,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """读取当前用户已发布成果及可恢复的同步错误。"""
    projection = await asyncio.to_thread(service.list_artifacts, user.uid, source)
    return await service.sync_artifact_records(db, uid=user.uid, source=source, projection=projection)


@router.post("/{source}/sync")
async def sync(
    source: Source,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """补齐历史成果；下载和转录仍沿用对应模块的任务流程。"""
    try:
        if source == "wechat-articles":
            projection = await asyncio.to_thread(service.sync_articles, user.uid)
        else:
            projection = await service.sync_videos(user.uid)
        return await service.sync_artifact_records(db, uid=user.uid, source=source, projection=projection)
    except (OSError, ValueError) as error:
        raise HTTPException(409, "成果同步暂未完成，请稍后重试") from error


@router.post("/{source}/archive")
async def archive(source: Source, selection: Selection, user: User = Depends(get_required_user)):
    """流式返回有界 ZIP，下载结束或失败时删除临时打包文件。"""
    fd, path = tempfile.mkstemp(prefix="collection-artifacts-", suffix=".zip")
    os.close(fd)
    try:
        await asyncio.to_thread(service.archive_artifacts, user.uid, source, selection.ids, path)
    except service.ArtifactArchiveError as error:
        os.unlink(path)
        raise HTTPException(409, error.detail) from error
    except (OSError, ValueError) as error:
        os.unlink(path)
        raise HTTPException(
            409,
            {
                "code": "archive_failed",
                "message": str(error),
                "failures": [],
                "limit_bytes": service.MAX_ARCHIVE_BYTES,
            },
        ) from error
    except BaseException:
        os.unlink(path)
        raise
    return FileResponse(path, filename=f"{service.SOURCES[source]}.zip", background=BackgroundTask(os.unlink, path))


@router.post("/{source}/ingest", status_code=202)
async def ingest(
    source: Source,
    selection: IngestSelection,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """统一编排成果入库，逐项返回任务、失败阶段和幂等状态。"""
    await ensure_knowledge_base_permission(selection.kb_id, user, ResourcePermission.MANAGE)
    await ensure_category_for_kb(
        db,
        tenant_id=user_tenant_id(user),
        kb_id=selection.kb_id,
        category_id=selection.category_id,
    )
    projection = await asyncio.to_thread(service.list_artifacts, user.uid, source)
    await service.sync_artifact_records(db, uid=user.uid, source=source, projection=projection)
    return await service.ingest_artifacts(
        db,
        uid=user.uid,
        source=source,
        ids=selection.ids,
        kb_id=selection.kb_id,
        category_id=selection.category_id,
    )
