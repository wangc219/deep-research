"""采集成果的沙盒工作区列表、同步及批量下载。"""

import asyncio
import os
import tempfile
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from platform_core.services import collection_artifact_service as service
from platform_core.storage.postgres.models_business import User
from server.utils.auth_middleware import get_required_user

router = APIRouter(prefix="/collection-artifacts", tags=["collection-artifacts"])
Source = Literal["wechat-articles", "wxchannels"]


class Selection(BaseModel):
    """只接受来源清单内的成果标识，不接受服务器文件路径。"""

    ids: list[str] = Field(min_length=1, max_length=100)


@router.get("/{source}")
async def artifacts(source: Source, user: User = Depends(get_required_user)):
    """读取当前用户已发布成果及可恢复的同步错误。"""
    return await asyncio.to_thread(service.list_artifacts, user.uid, source)


@router.post("/{source}/sync")
async def sync(source: Source, user: User = Depends(get_required_user)):
    """补齐历史成果；下载和转录仍沿用对应模块的任务流程。"""
    try:
        if source == "wechat-articles":
            return await asyncio.to_thread(service.sync_articles, user.uid)
        return await service.sync_videos(user.uid)
    except (OSError, ValueError) as error:
        raise HTTPException(409, "成果同步暂未完成，请稍后重试") from error


@router.post("/{source}/archive")
async def archive(source: Source, selection: Selection, user: User = Depends(get_required_user)):
    """流式返回有界 ZIP，下载结束或失败时删除临时打包文件。"""
    fd, path = tempfile.mkstemp(prefix="collection-artifacts-", suffix=".zip")
    os.close(fd)
    try:
        await asyncio.to_thread(service.archive_artifacts, user.uid, source, selection.ids, path)
    except (OSError, ValueError) as error:
        os.unlink(path)
        raise HTTPException(409, "部分成果不可下载或超出大小限制，请刷新或减少选择后重试") from error
    except BaseException:
        os.unlink(path)
        raise
    return FileResponse(path, filename=f"{service.SOURCES[source]}.zip", background=BackgroundTask(os.unlink, path))
