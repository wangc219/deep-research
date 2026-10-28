"""知识库导航中的视频号转 DOCX 接口。"""

import io
import zipfile
import time
from urllib.parse import quote
from typing import Literal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, File, Form, UploadFile, Header
from pydantic import BaseModel, Field, field_validator
from starlette.responses import Response

from platform_core.knowledge.wxchannels import WxChannelsError
from platform_core.services import wxchannels_service as service
from platform_core.services.collection_artifact_service import artifact_id, read_manifest
from platform_core.services.task_service import tasker
from platform_core.services import video_collector_service as personal
from platform_core.repositories.video_collector_repository import VideoCollectorRepository
from platform_core.repositories.video_collector_repository import CollectorConflict
from platform_core.repositories.wechat_channel_repository import WechatChannelRepository
from platform_core.utils.upload_utils import read_upload_with_limit
from platform_core.storage.minio.client import StorageError
from platform_core.storage.postgres.models_business import User
from server.utils.auth_middleware import get_required_user
from server.utils.knowledge_permissions import require_knowledge_base_manage

router = APIRouter(prefix="/wxchannels", tags=["wxchannels"])


async def authenticated_device(x_collector_device: str = Header(...), authorization: str = Header(...)):
    """设备令牌不能调用用户管理、知识库或普通平台任务接口。"""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or len(token) != 64:
        raise HTTPException(401, detail="采集端凭据无效")
    device = await VideoCollectorRepository().authenticate(x_collector_device, token)
    if device is None:
        raise HTTPException(401, detail="采集端凭据无效或已撤销")
    return device


class DeviceEnrollment(BaseModel):
    """客户端生成设备秘密，服务端仅保存摘要。"""

    device_id: str = Field(pattern=r"^wxd_[a-f0-9]{32}$")
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=100)
    platform: Literal["macos", "windows"]


@router.post("/collector/devices")
async def enroll_device(request: DeviceEnrollment, user: User = Depends(get_required_user)):
    """幂等配对当前用户的视频号设备。"""
    try:
        return await VideoCollectorRepository().enroll(user.uid, **request.model_dump())
    except CollectorConflict as error:
        raise HTTPException(409, detail=str(error)) from error


@router.get("/collector/devices")
async def devices(user: User = Depends(get_required_user)):
    """查看当前用户的采集端。"""
    return {"items": await VideoCollectorRepository().list_owned(user.uid)}


@router.delete("/collector/devices/{device_id}")
async def revoke_device(device_id: str, user: User = Depends(get_required_user)):
    """撤销配对并停止尚未结束的采集。"""
    if not await VideoCollectorRepository().revoke(user.uid, device_id):
        raise HTTPException(404, detail="采集端不存在")
    return {"status": "revoked"}


class VideosRequest(BaseModel):
    """使用昵称或 @finder 账号分页发现视频。"""

    account: str = Field(min_length=1, max_length=200)
    max_pages: int | None = Field(None, ge=1, le=100, description="留空默认最新两页，完整同步需显式开启")
    max_videos: int | None = Field(None, ge=1, le=150, description="留空选择已加载的全部未转录视频")
    full_refresh: bool = False
    load_more: bool = False
    collection_mode: Literal["personal", "central"] = "central"
    device_id: str | None = Field(None, max_length=64)

    @field_validator("account")
    @classmethod
    def valid_account(cls, value):
        """拒绝仅含空白的输入。"""
        value = value.strip()
        if not value:
            raise ValueError("请输入视频号昵称或账号 ID")
        return value


class TranscribeRequest(VideosRequest):
    """DOCX 是固定交付格式，输出目录由平台控制。"""

    max_videos: int | None = Field(20, ge=1, le=150)
    language: str = Field("zh", pattern="^(zh|en|yue|ja|ko|auto)$")
    timeout_seconds: int = Field(3600, ge=30, le=7200)
    video_oids: list[str] = Field(default_factory=list, max_length=100)


class ImportRequest(BaseModel):
    """仅选择当前用户任务内已完成的文字稿。"""

    task_id: str
    indexes: list[int] = Field(min_length=1, max_length=100)


async def owned_task(task_id: str, user: User) -> dict:
    """所有状态、取消、文件和入库操作共用相同的归属校验。"""
    task = await tasker.get_task(task_id)
    if (
        not task
        or task["type"] not in {service.TASK_TYPE, "wxchannels_discover", service.CENTRAL_DISCOVERY_TASK_TYPE}
        or task["payload"].get("operator_id") != user.uid
    ):
        raise HTTPException(404, detail="视频号任务不存在")
    return task


def public_task(task: dict, workspace_items: dict | None = None) -> dict:
    """结果只投影用户所需字段，不向前端暴露对象存储位置。"""
    result = task.get("result") or {}
    return {
        key: task.get(key)
        for key in ("id", "status", "progress", "message", "created_at", "updated_at", "cancel_requested")
    } | {
        "account": task["payload"]["account"],
        "collection_mode": task["payload"].get("collection_mode", "central"),
        "error": "任务执行失败，请检查连接或重试" if task.get("error") else None,
        "result": {
            **{key: value for key, value in result.items() if key != "completed_oids"},
            "items": [
                service.present_transcript_item(item)
                | (
                    {"workspace_path": record["primary_path"]}
                    if (record := (workspace_items or {}).get(artifact_id(item.get("oid", ""))))
                    else {}
                )
                for item in result.get("items", [])
            ],
        },
    }


@router.get("/status")
async def status(mode: Literal["personal", "central"] = "central", user: User = Depends(get_required_user)):
    """检查集成服务是否具备转换条件。"""
    state = await service.connection_status(include_collector=mode == "central")
    state["devices"] = await VideoCollectorRepository().list_owned(user.uid)
    return state


@router.post("/connect")
async def connect(user: User = Depends(get_required_user)):
    """已运行的微信采集器可直接复用，用户无需配置 MCP。"""
    try:
        state = await service.connect_existing_collector()
    except WxChannelsError as error:
        raise HTTPException(409, detail=str(error)) from error
    state["devices"] = await VideoCollectorRepository().list_owned(user.uid)
    return state


@router.get("/channels")
async def channels(user: User = Depends(get_required_user)):
    """无需连接微信即可查看本人保存的视频号。"""
    return {"items": await WechatChannelRepository().list_owned(user.uid)}


@router.get("/channels/{channel_id}/videos")
async def channel_videos(
    channel_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    keyword: str = Query("", max_length=200),
    published_after: int | None = Query(None, ge=0),
    published_before: int | None = Query(None, ge=0),
    user: User = Depends(get_required_user),
):
    """分页浏览当前用户的视频历史列表。"""
    if published_after is not None and published_before is not None and published_after > published_before:
        raise HTTPException(422, detail="开始日期不能晚于结束日期")
    result = await WechatChannelRepository().videos(
        user.uid,
        channel_id,
        offset=offset,
        limit=limit,
        keyword=keyword.strip(),
        published_after=published_after,
        published_before=published_before,
    )
    if result is None:
        raise HTTPException(404, detail="视频号不存在")
    completed = await service.completed_video_oids(user.uid, service.get_minio_client())
    result["videos"] = [{**video, "completed": video["oid"] in completed} for video in result["videos"]]
    return result


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, user: User = Depends(get_required_user)):
    """移除本人保存的列表，不删除已经生成的成果。"""
    if not await WechatChannelRepository().delete(user.uid, channel_id):
        raise HTTPException(404, detail="视频号不存在")
    if service.shared_cloud_collector():
        from platform_core.services.run_queue_service import get_arq_pool

        await (await get_arq_pool()).delete("wxchannels:cursor:v1:" + channel_id)
    return {"deleted": True}


@router.post("/videos")
async def videos(request: VideosRequest, user: User = Depends(get_required_user)):
    """列出尚未转换的视频。"""
    if request.collection_mode == "personal":
        try:
            await personal.require_personal_device(user.uid, request.device_id)
        except CollectorConflict as error:
            return {"videos": [], "error": str(error)}
        saved = await WechatChannelRepository().find(user.uid, request.account)
        sync_payload = {
            "known_oids": saved["known_oids"]
            if saved and saved["history_complete"] and not request.full_refresh
            else [],
            "resolved_username": saved["username"] if saved else None,
        }
        task, created = await tasker.enqueue_unique_by_payload(
            name=f"个人视频号列表 · {request.account}",
            task_type="wxchannels_discover",
            payload={**request.model_dump(), **sync_payload, "operator_id": user.uid},
            payload_match={**request.model_dump(), "operator_id": user.uid},
            timeout_seconds=900,
        )
        return {"task_id": task.id, "created": created}
    if service.shared_cloud_collector():
        task, created = await tasker.enqueue_unique_by_payload(
            name=f"云端视频号列表 · {request.account}",
            task_type=service.CENTRAL_DISCOVERY_TASK_TYPE,
            payload={**request.model_dump(), "operator_id": user.uid, "requested_at": time.time()},
            payload_match={**request.model_dump(), "operator_id": user.uid},
            timeout_seconds=900,
        )
        return {"task_id": task.id, "created": created}
    try:
        return await service.discover_videos(
            user.uid, request.account, request.max_pages, request.max_videos, request.full_refresh, request.load_more
        )
    except WxChannelsError as error:
        return {"videos": [], "error": str(error)}


@router.post("/transcribe", status_code=202)
async def transcribe(request: TranscribeRequest, user: User = Depends(get_required_user)):
    """统一任务系统提供串行推理容量、持久化和重复提交互斥。"""
    state = await service.connection_status(include_collector=request.collection_mode == "central")
    if request.collection_mode == "personal":
        try:
            await personal.require_personal_device(user.uid, request.device_id)
        except CollectorConflict as error:
            return {"submitted": False, "error": str(error)}
        ready = state["asr_available"] and state["ffmpeg_available"]
    else:
        ready = state["ready"]
    if not ready:
        return {"submitted": False, "error": state["message"]}
    video_count = len(request.video_oids) if request.video_oids else request.max_videos
    task, created = await tasker.enqueue_unique_by_payload(
        name=f"视频号转 DOCX · {request.account}",
        task_type=service.TASK_TYPE,
        payload={**request.model_dump(), "operator_id": user.uid},
        payload_match={"operator_id": user.uid},
        timeout_seconds=(
            min(tasker.default_timeout_seconds, video_count * request.timeout_seconds * 2 + 600)
            if video_count is not None
            else tasker.default_timeout_seconds
        ),
    )
    return {"submitted": True, "task_id": task.id, "created": created}


@router.get("/tasks")
async def tasks(limit: int = Query(30, ge=1, le=100), user: User = Depends(get_required_user)):
    """刷新后恢复当前用户的历史及活动任务。"""
    records = await service.list_owned_tasks(user.uid)
    records.sort(key=lambda task: task["status"] not in {"pending", "running"})
    workspace_items = read_manifest(user.uid, "wxchannels")["items"]
    return {"tasks": [public_task(task, workspace_items) for task in records[:limit]]}


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, user: User = Depends(get_required_user)):
    """获取逐视频进度和文字预览。"""
    task = await owned_task(task_id, user)
    return public_task(task, read_manifest(user.uid, "wxchannels")["items"])


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str, user: User = Depends(get_required_user)):
    """用户只能停止自己的视频号任务。"""
    await owned_task(task_id, user)
    await tasker.cancel_task(task_id)
    return {"requested": True}


@router.delete("/tasks/{task_id}")
async def delete_history(task_id: str, user: User = Depends(get_required_user)):
    """只删除本人已结束的历史记录，保留工作区成果和视频去重记录。"""
    await owned_task(task_id, user)
    if not await tasker.delete_task(task_id):
        raise HTTPException(409, detail="任务仍在执行或记录已更新，请刷新后重试")
    return {"deleted": True}


@router.get("/tasks/{task_id}/items/{index}/docx")
async def download(task_id: str, index: int, user: User = Depends(get_required_user)):
    """经归属校验代理私有 Word 文件，不提供公开存储链接。"""
    task = await owned_task(task_id, user)
    item = next(
        (
            item
            for item in (task.get("result") or {}).get("items", [])
            if item["index"] == index and item["status"] == "completed"
        ),
        None,
    )
    if not item:
        raise HTTPException(404, detail="文字稿不存在")
    try:
        content = await service.export_transcript_document(item, task["payload"]["account"])
    except StorageError as error:
        raise HTTPException(404, detail="文字稿文件不存在，可重新转换") from error
    return Response(
        content,
        media_type=service.DOCX_TYPE,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["filename"])},
    )


@router.get("/tasks/{task_id}/archive")
async def archive(task_id: str, user: User = Depends(get_required_user)):
    """批量导出任务内已完成的 Word 文档。"""
    task = await owned_task(task_id, user)
    items = [item for item in (task.get("result") or {}).get("items", []) if item["status"] == "completed"]
    if not items:
        raise HTTPException(404, detail="暂无可下载的文档")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as output:
        for item in items:
            try:
                content = await service.export_transcript_document(item, task["payload"]["account"])
            except StorageError as error:
                raise HTTPException(404, detail="部分文字稿文件不存在，请重新转换") from error
            output.writestr(item["filename"], content)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="video-transcripts.zip"'},
    )


@router.post("/databases/{kb_id}/import")
async def import_documents(kb_id: str, request: ImportRequest, user: User = Depends(require_knowledge_base_manage)):
    """目标知识库管理权限和来源任务所有权必须同时满足。"""
    task = await owned_task(request.task_id, user)
    try:
        return await service.import_transcripts(user.uid, kb_id, task, sorted(set(request.indexes)))
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error


class VideoHeartbeat(BaseModel):
    """个人电脑实测的视频号环境，不要求本地安装识别模型。"""

    proxy_ready: bool = False
    channels_ready: bool = False
    mcp_available: bool = False
    wechat_available: bool = False
    ffmpeg_available: bool = False
    message: str = Field("", max_length=500)
    version: str = Field("1.0", max_length=30)


class VideoListItem(BaseModel):
    """只向云端交接公开视频 ID 与简介。"""

    oid: str = Field(min_length=1, max_length=128)
    title: str = Field("", max_length=20000)
    published_at: int = Field(0, ge=0)


class VideoEvent(BaseModel):
    """有界、可幂等重放的个人采集端事件。"""

    task_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    execution_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1, le=202001)
    kind: Literal["video_list", "complete"]
    videos: list[VideoListItem] = Field(default_factory=list, max_length=2000)
    finished: bool = True
    history_complete: bool = True
    username: str = Field("", max_length=200)
    error: str = Field("", max_length=500)
    skipped_count: int = Field(0, ge=0, le=202000)


@router.post("/collector/heartbeat")
async def collector_heartbeat(request: VideoHeartbeat, device=Depends(authenticated_device)):
    """个人端主动连接平台，只领取绑定自己的任务。"""
    try:
        return {"job": await VideoCollectorRepository().heartbeat(device.device_id, request.model_dump())}
    except CollectorConflict as error:
        raise HTTPException(409, detail=str(error)) from error


@router.post("/collector/event")
async def collector_event(request: VideoEvent, device=Depends(authenticated_device)):
    """接收视频发现结果或采集结束信号。"""
    try:
        created = await VideoCollectorRepository().receive(
            device,
            task_id=request.task_id,
            execution_id=request.execution_id,
            sequence=request.sequence,
            kind=request.kind,
            detail=request.model_dump(exclude={"task_id", "execution_id", "sequence", "kind"}),
        )
        return {"received": True, "created": created}
    except CollectorConflict as error:
        raise HTTPException(409, detail=str(error)) from error


@router.post("/collector/audio")
async def collector_audio(
    file: UploadFile = File(...),
    task_id: str = Form(..., pattern=r"^[a-f0-9]{32}$"),
    execution_id: str = Form(..., min_length=1, max_length=128),
    sequence: int = Form(..., ge=1, le=202000),
    oid: str = Form(..., min_length=1, max_length=128),
    title: str = Form("", max_length=20000),
    device=Depends(authenticated_device),
):
    """只接收当前设备的临时音频，并限制上传大小。"""
    try:
        content = await read_upload_with_limit(
            file, max_size_bytes=256 * 1024 * 1024, too_large_message="音频不能超过 256 MB"
        )
        created = await personal.stage_audio(
            device, task_id=task_id, execution_id=execution_id, sequence=sequence, oid=oid, title=title, content=content
        )
        return {"received": True, "created": created}
    except CollectorConflict as error:
        raise HTTPException(409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error


@router.get("/collector/download")
async def collector_download(user: User = Depends(get_required_user)):
    """提供跨设备运行所需的源码，不打包用户数据库、证书或登录凭据。"""
    root = Path(__file__).resolve().parents[2]
    package = root / "package/platform_core/knowledge"
    collector = root / "video_collector"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as output:
        for path in collector.glob("*"):
            if path.is_file() and path.suffix in {".py", ".txt", ".md", ".sh", ".ps1"}:
                output.write(path, path.name)
        vendor = root / "vendor/wx_channels_download"
        if not vendor.is_dir():
            vendor = root.parent / "vendor/wx_channels_download"
        if vendor.is_dir():
            for path in vendor.rglob("*"):
                if path.is_file() and not any(part in {".git", "node_modules", "__pycache__"} for part in path.parts):
                    output.write(path, "downloader/" + path.relative_to(vendor).as_posix())
        output.write(package / "wxchannels.py", "platform_core/knowledge/wxchannels.py")
        output.write(
            package / "video_transcriber/utils/ffmpeg/__init__.py",
            "platform_core/knowledge/video_transcriber/utils/ffmpeg/__init__.py",
        )
        for directory in [
            "platform_core",
            "platform_core/knowledge",
            "platform_core/knowledge/video_transcriber",
            "platform_core/knowledge/video_transcriber/utils",
        ]:
            output.writestr(directory + "/__init__.py", "")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="video-collector.zip"'},
    )


class ConnectionPackageRequest(BaseModel):
    """浏览器为当前用户生成可重放的设备凭据。"""

    device_id: str = Field(pattern=r"^wxd_[a-f0-9]{32}$")
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=100)
    platform: Literal["macos", "windows"]
    platform_url: str = Field(min_length=1, max_length=2048)


@router.post("/collector/package")
async def connection_package(request: ConnectionPackageRequest, user: User = Depends(get_required_user)):
    """一键完成配对与打包；返回内容禁止被中间代理缓存。"""
    import asyncio
    from urllib.parse import urlsplit
    from platform_core.services.video_collector_package import build_connection_package
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_knowledge import VideoCollectorDevice

    origin = urlsplit(request.platform_url)
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.path not in {"", "/"}
        or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise HTTPException(422, detail="平台需要 HTTPS 地址，本机测试可使用 localhost")
    root = Path(__file__).resolve().parents[2]
    try:
        package = await asyncio.to_thread(build_connection_package, root, request.model_dump())
        await VideoCollectorRepository().enroll(user.uid, **request.model_dump(exclude={"platform_url"}))
        async with pg_manager.get_async_session_context() as session:
            device = await session.get(VideoCollectorDevice, request.device_id, with_for_update=True)
            if not device or device.revoked_at or device.owner_uid != user.uid:
                raise CollectorConflict("设备配对已撤销")
            device.state = {**(device.state or {}), "channel_capable": True}
    except FileNotFoundError as error:
        raise HTTPException(503, detail="采集程序尚未准备好，请联系管理员完成部署") from error
    except CollectorConflict as error:
        raise HTTPException(409, detail=str(error)) from error
    return Response(
        package,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="connect-wechat.zip"',
            "Cache-Control": "no-store, private",
        },
    )
