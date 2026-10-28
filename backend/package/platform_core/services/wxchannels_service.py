"""视频号转 Word 用例，共享平台任务、用户权限与私有对象存储。"""

import asyncio
import hashlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes, write_video_docx
from platform_core.knowledge.video_transcriber.utils.ffmpeg import get_ffmpeg_path
from platform_core.knowledge.video_transcriber.utils.transcript_layout import transcript_presentation, video_markdown
from platform_core.knowledge.wxchannels import (
    WxChannelsError,
    WxChannelsMCPClient,
    downloader_endpoint,
    collector_proxy_status,
    prepare_collector_connection,
)
from platform_core.repositories.task_repository import TaskRepository
from platform_core.repositories.wechat_channel_repository import WechatChannelRepository
from platform_core.services.task_service import TaskContext
from platform_core.storage.minio.client import get_minio_client
from platform_core.utils import logger

TASK_TYPE = "wxchannels_transcribe"
CENTRAL_DISCOVERY_TASK_TYPE = "wxchannels_central_discover"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def shared_cloud_collector() -> bool:
    """显式启用运营统一维护的云端微信，默认保留个人模式。"""
    return os.getenv("WX_CHANNELS_SHARED_CLOUD", "false").lower() == "true"


def engine_python() -> str:
    """优先使用与平台依赖隔离的迁移引擎环境。"""
    bundled = Path("/opt/video-asr/bin/python")
    return os.getenv("VIDEO_TRANSCRIBER_PYTHON") or (str(bundled) if bundled.is_file() else sys.executable)


def video_owner_prefix(owner_uid: str) -> str:
    """按用户建立私有产物前缀，单次列举即可恢复去重索引。"""
    return "video-transcripts/" + hashlib.sha256(owner_uid.encode()).hexdigest()[:32] + "/"


def video_object_key(owner_uid: str, oid: str) -> str:
    """按稳定 OID 隔离文档，不使用昵称或临时 nonce 去重。"""
    return video_owner_prefix(owner_uid) + hashlib.sha256(oid.encode()).hexdigest() + ".docx"


def video_completion_key(owner_uid: str, oid: str) -> str:
    """完成标记与 Word 同存储，不受平台任务历史保留期影响。"""
    return video_owner_prefix(owner_uid) + "oid-" + quote(oid, safe="") + ".json"


async def completed_video_oids(owner_uid: str, storage) -> set[str]:
    """一次列举恢复完成视频，文档丢失时允许重试。"""
    prefix = video_owner_prefix(owner_uid)
    objects = await storage.alist_object_metadata(storage.KB_BUCKETS["documents"], prefix)
    names = {item["object_name"] for item in objects}
    candidates = {
        unquote(name[len(prefix) + 4 : -5])
        for name in names
        if name.startswith(prefix + "oid-") and name.endswith(".json")
    }
    return {oid for oid in candidates if video_object_key(owner_uid, oid) in names}


async def store_video_document(owner_uid: str, oid: str, content: bytes, storage):
    """完整 Word 上传成功后再提交完成标记，避免中断产物被误判成功。"""
    uploaded = await storage.aupload_file(
        bucket_name=storage.KB_BUCKETS["documents"],
        object_name=video_object_key(owner_uid, oid),
        data=content,
        content_type=DOCX_TYPE,
    )
    await storage.aupload_file(
        bucket_name=storage.KB_BUCKETS["documents"],
        object_name=video_completion_key(owner_uid, oid),
        data=json.dumps({"oid": oid}).encode(),
        content_type="application/json",
    )
    return uploaded


def video_filename(title: str, oid: str) -> str:
    """生成可下载且不会重名的中文文件名。"""
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" .")[:80] or "视频文字稿"
    suffix = hashlib.sha256(oid.encode()).hexdigest()[:10]
    return f"{title}_{suffix}.docx"


async def connection_status(*, include_collector: bool = True) -> dict:
    """分开报告下载器、MCP、微信连接和本地音频处理依赖。"""
    endpoint = urlsplit(downloader_endpoint())
    base = urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))
    state = {
        "api_available": False,
        "mcp_available": False,
        "wechat_available": False,
        "proxy_ready": False,
        "certificate_ready": False,
        "ffmpeg_available": bool(get_ffmpeg_path()),
    }
    if include_collector:
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(base + "/api/mcp/status")
                response.raise_for_status()
                state["api_available"] = True
                state["mcp_available"] = response.json().get("data", {}).get("enabled") is True
                response = await client.get(base + "/api/channels/status")
                response.raise_for_status()
                state["wechat_available"] = response.json().get("data", {}).get("available") is True
                state.update(await collector_proxy_status(client, base))
        except (httpx.HTTPError, ValueError, AttributeError, WxChannelsError):
            pass
    # API 与 Worker 使用同一构建镜像；独立 Python 运行环境由部署变量显式指定。
    try:
        process = await asyncio.create_subprocess_exec(
            engine_python(),
            "-c",
            "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(x) "
            "for x in ('torch','torchaudio','funasr','modelscope')) else 1)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), 10)
            state["asr_available"] = process.returncode == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    except OSError:
        state["asr_available"] = False
    state["ready"] = all(state.values())
    state["message"] = (
        "已就绪，可以获取视频并开始转写"
        if state["ready"]
        else "下载器未连接，请启动视频号采集端"
        if not state["api_available"]
        else "请在视频号采集端启用 MCP"
        if not state["mcp_available"]
        else "微信采集证书尚未完成本机信任，请在采集程序中完成系统授权"
        if not state["certificate_ready"]
        else "电脑微信采集代理未生效，正在等待恢复连接"
        if not state["proxy_ready"]
        else "请在已登录的微信中打开视频号页面"
        if not state["wechat_available"]
        else "服务器未安装 FFmpeg"
        if not state["ffmpeg_available"]
        else "服务器未安装 SenseVoice 运行环境，请按部署文档启用"
    )
    state["central_managed"] = shared_cloud_collector()
    if state["central_managed"] and not state["wechat_available"]:
        state["message"] = "云端微信等待管理员登录并打开视频号页面"
    return state


async def connect_existing_collector() -> dict:
    """与 video_text 一样检查 MCP、证书和实际系统代理，恢复已授权的连接。"""
    endpoint = urlsplit(downloader_endpoint())
    base = urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            await prepare_collector_connection(client, base)
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise WxChannelsError("微信采集程序尚未启动，请启动后重新进入微信视频号") from error
    return await connection_status()


def walk_dicts(value):
    """遍历下载器返回的嵌套账号结果。"""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


async def resolve_username(client: WxChannelsMCPClient, account: str) -> str:
    """精确匹配昵称，重名时要求使用稳定的视频号账号 ID。"""
    if account.endswith("@finder"):
        return account
    matches = set()
    for item in walk_dicts(await client.search_accounts(account)):
        contact = item.get("contact") if isinstance(item.get("contact"), dict) else item
        if str(contact.get("nickname", "")).strip() == account and contact.get("username"):
            matches.add(str(contact["username"]).strip())
    if len(matches) == 1:
        return matches.pop()
    if matches:
        raise WxChannelsError("找到多个同名视频号，请使用账号 ID：" + "、".join(sorted(matches)))
    raise WxChannelsError("未找到视频号，请确认完整昵称或使用 @finder 账号 ID")


async def run_central_video_discovery(context: TaskContext) -> dict:
    """首次仅获取最新两页，更多历史由用户显式加载，进度与取消持久化。"""
    payload = context.payload
    await context.set_progress(0, "正在加载更多历史" if payload.get("load_more") else "正在按所选范围加载最新视频")
    result = await cancellable(
        context,
        discover_videos(
            payload["operator_id"],
            payload["account"],
            payload.get("max_pages"),
            payload.get("max_videos"),
            payload.get("full_refresh", False),
            payload.get("load_more", False),
            payload.get("requested_at"),
        ),
    )
    await context.set_progress(100, "视频列表已保存")
    return result


async def discover_videos(
    owner_uid: str,
    account: str,
    max_pages: int | None = None,
    max_videos: int | None = None,
    full_refresh: bool = False,
    load_more: bool = False,
    requested_at: float | None = None,
) -> dict:
    """先保存账号，每批最多两页；延续源游标且不重扫之前的历史。"""
    repository = WechatChannelRepository()
    saved = await repository.find(owner_uid, account)
    pages = (
        max_pages
        if full_refresh
        else min(max_pages or (2 if load_more else max(2, ((max_videos or 20) + 14) // 15)), 10)
    )
    pool, marker, snapshot = None, "", None
    cursor = {"marker": "", "pages": 0}
    if shared_cloud_collector():
        from platform_core.services.run_queue_service import get_arq_pool

        pool = await get_arq_pool()
        if saved:
            if load_more and saved["history_complete"]:
                return await saved_video_discovery(owner_uid, {**saved, "new_count": 0}, max_videos)
            cached_cursor = await pool.get("wxchannels:cursor:v1:" + saved["id"])
            if cached_cursor:
                cursor = json.loads(cached_cursor)
            if load_more:
                marker = cursor["marker"]
        cache_key = (
            "wxchannels:shared-page:v1:"
            + hashlib.sha256(
                (downloader_endpoint() + "|" + account + "|" + marker + "|" + str(pages)).encode()
            ).hexdigest()
        )
        cached = await pool.get(cache_key) if not full_refresh else None
        snapshot = json.loads(cached) if cached else None
        if snapshot and snapshot["fetched_at"] < (requested_at or time.time()):
            snapshot = None
    if snapshot:
        username = snapshot["username"]
        channel = await repository.merge(
            owner_uid, account, username, snapshot["videos"], complete=snapshot["history_complete"]
        )
        next_marker = snapshot["next_marker"]
    else:
        async with WxChannelsMCPClient(downloader_endpoint(), timeout=60) as client:
            username = saved["username"] if saved else await resolve_username(client, account)
            # 搜索结果立即入目录，历史抓取失败时不丢失已添加的视频号。
            await repository.merge(owner_uid, account, username, [], complete=False)
            videos = await client.iter_account_videos(username, pages, **({"start_marker": marker} if marker else {}))
        complete = getattr(client, "history_complete", pages is None)
        next_marker = getattr(client, "next_marker", "")
        metadata = [{"oid": v.oid, "nid": v.nid, "title": v.title, "published_at": v.published_at} for v in videos]
        channel = await repository.merge(owner_uid, account, username, metadata, complete=complete)
        if pool:
            if metadata:
                identities = "wxchannels:identity:v1:" + hashlib.sha256(username.encode()).hexdigest()
                await pool.hset(identities, mapping={v["oid"]: json.dumps(v) for v in metadata})
                await pool.expire(identities, 604800)
            if not full_refresh:
                await pool.set(
                    cache_key,
                    json.dumps(
                        {
                            "fetched_at": time.time(),
                            "username": username,
                            "videos": metadata,
                            "history_complete": complete,
                            "next_marker": next_marker,
                        }
                    ),
                    ex=60,
                )
    if pool:
        # 更新最新页不覆盖用户已加载到的较早位置。
        cursor_key = "wxchannels:cursor:v1:" + channel["id"]
        advanced_pages = (cursor["pages"] if load_more else 0) + (pages or 0)
        if load_more or full_refresh or advanced_pages > cursor["pages"]:
            await pool.set(cursor_key, json.dumps({"marker": next_marker, "pages": advanced_pages}))
    return await saved_video_discovery(owner_uid, channel, max_videos)


async def saved_video_discovery(owner_uid: str, channel: dict, max_videos: int | None) -> dict:
    """中央和个人采集共用完整历史索引及当前用户完成标记。"""
    repository = WechatChannelRepository()
    storage = get_minio_client()
    completed = await completed_video_oids(owner_uid, storage)
    result = await repository.pending_videos(owner_uid, channel["id"], completed, max_videos)
    return {
        **result,
        "username": channel["username"],
        "new_count": channel["new_count"],
        "channel_id": channel["id"],
        "history_complete": channel["history_complete"],
        "has_more": not channel["history_complete"],
    }


async def list_owned_tasks(owner_uid: str) -> list[dict]:
    """从 PostgreSQL 恢复当前用户的全部任务历史。"""
    records = await TaskRepository().list_by_payload_values(
        task_type=TASK_TYPE,
        payload_key="operator_id",
        payload_values={owner_uid},
    )
    return [record.to_dict() for record in records]


async def cancellable(context: TaskContext, operation):
    """在长时间提取和模型推理期间响应平台取消或 lease 丢失。"""
    future = asyncio.ensure_future(operation)
    try:
        while not future.done():
            await context.raise_if_cancelled()
            await asyncio.wait({future}, timeout=0.75)
        return await future
    finally:
        if not future.done():
            future.cancel()
            await asyncio.gather(future, return_exceptions=True)


async def transcribe_audio(audio: Path, output: Path, language: str, timeout: int) -> dict:
    """识别与标点分进程顺序加载，取消时终止模型进程并回收内存。"""
    env = dict(os.environ)
    package_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("OMP_NUM_THREADS", "2")
    env.setdefault("MKL_NUM_THREADS", "2")
    from platform_core.services.resource_budget import register_asr_process, unregister_asr_process

    for punctuation in (False, True):
        arguments = ["--punctuate"] if punctuation else []
        log_path = output.with_suffix(".log")
        with log_path.open("wb") as diagnostic:
            process = await asyncio.create_subprocess_exec(
                engine_python(),
                "-m",
                "platform_core.knowledge.video_transcriber.runner",
                *arguments,
                str(audio),
                str(output),
                language,
                env=env,
                start_new_session=os.name != "nt",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=diagnostic,
            )
            register_asr_process(process.pid)
            try:
                await asyncio.wait_for(process.wait(), min(timeout, 600) if punctuation else timeout)
                if process.returncode or not output.is_file():
                    with log_path.open("rb") as log:
                        log.seek(max(0, log_path.stat().st_size - 6000))
                        logger.error("视频识别诊断：{}", log.read().decode("utf-8", errors="replace"))
                    raise WxChannelsError("语音识别失败，请检查 SenseVoice 依赖、可用内存、模型缓存和音轨后重试")
            finally:
                unregister_asr_process(process.pid)
                if process.returncode is None:
                    if os.name == "nt":
                        process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    await process.wait()
    result = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(result.get("text"), str) or not result["text"].strip():
        raise WxChannelsError("未识别到有效语音")
    return result


async def run_wxchannels_transcribe(context: TaskContext) -> dict:
    """逐条提取临时音频、转写和存储，失败隔离且每条完成立即持久化。"""
    payload = context.payload
    if payload.get("collection_mode") == "personal":
        from platform_core.services.video_collector_service import run_personal_video_transcribe

        return await run_personal_video_transcribe(context)
    storage = get_minio_client()
    owner_uid = payload["operator_id"]
    history = await list_owned_tasks(owner_uid)
    completed = await completed_video_oids(owner_uid, storage)
    carried = [
        item
        for task in history
        if task["id"] == context.task_id
        for item in (task.get("result") or {}).get("items", [])
        if item["status"] == "completed"
    ]
    result = {
        "account": payload["account"],
        "items": carried,
        "skipped_count": 0,
        "completed_count": len(carried),
        "failed_count": 0,
    }
    await context.set_result(result)
    await context.set_progress(0, "正在获取视频列表")
    async with WxChannelsMCPClient(downloader_endpoint(), timeout=payload["timeout_seconds"]) as client:
        username = await cancellable(context, resolve_username(client, payload["account"]))
        result["username"] = username
        selected = set(payload.get("video_oids") or [])
        if not selected and shared_cloud_collector():
            saved = await WechatChannelRepository().find(owner_uid, payload["account"])
            if saved:
                pending_saved = await WechatChannelRepository().pending_videos(
                    owner_uid, saved["id"], completed, payload["max_videos"]
                )
                selected = {item["oid"] for item in pending_saved["videos"]}
                if not selected:
                    result.update(total_count=0, skipped_count=pending_saved["completed_count"])
                    await context.set_result(result)
                    await context.set_progress(100, "已加载视频均已转换，可先加载更多历史")
                    return result
        videos = None
        if selected and shared_cloud_collector():
            from platform_core.knowledge.wxchannels import WxVideo
            from platform_core.services.run_queue_service import get_arq_pool

            pool = await get_arq_pool()
            identities = "wxchannels:identity:v1:" + hashlib.sha256(username.encode()).hexdigest()
            cached = await pool.hmget(identities, sorted(selected))
            if all(cached):
                videos = [WxVideo(**json.loads(item)) for item in cached]
        if videos is None:
            videos = await cancellable(
                context,
                client.iter_account_videos(
                    username,
                    payload["max_pages"],
                    selected_oids=selected,
                    max_videos=payload["max_videos"],
                    skip_oids=completed,
                ),
            )
        if not videos:
            raise WxChannelsError("该视频号没有可处理的视频")
        if selected:
            videos = [video for video in videos if video.oid in selected]
            if len({video.oid for video in videos}) != len(selected):
                raise WxChannelsError("部分选中视频已不在列表中，请重新获取视频")
        pending = []
        for video in videos:
            await context.raise_if_cancelled()
            if (
                video.oid not in completed
                or await storage.astat_file(storage.KB_BUCKETS["documents"], video_object_key(owner_uid, video.oid))
                is None
            ):
                pending.append(video)
            else:
                result["skipped_count"] += 1
        # 已转换视频不占用本次数量配额。
        pending.sort(key=lambda video: video.published_at, reverse=True)
        if payload["max_videos"] is not None:
            pending = pending[: max(0, payload["max_videos"] - len(carried))]
        result["total_count"] = len(pending)
        await context.set_result(result)
        for index, video in enumerate(pending):
            await context.raise_if_cancelled()
            item = {"index": len(result["items"]), "oid": video.oid, "title": video.title, "status": "extracting"}
            result["items"].append(item)
            await context.set_result(result)
            await context.set_progress(index / len(pending) * 100, f"提取音频 {index + 1}/{len(pending)}")
            try:
                with TemporaryDirectory(prefix="knowledge_video_") as temporary:
                    folder = Path(temporary)
                    audio = await cancellable(
                        context,
                        client.extract_audio_stream(
                            video,
                            folder / "audio.wav",
                            timeout_seconds=payload["timeout_seconds"],
                        ),
                    )
                    item["status"] = "transcribing"
                    await context.set_result(result)
                    await context.set_message(f"语音转写 {index + 1}/{len(pending)}")
                    transcript = await cancellable(
                        context,
                        transcribe_audio(
                            audio,
                            folder / "transcript.json",
                            payload["language"],
                            payload["timeout_seconds"],
                        ),
                    )
                    await context.raise_if_cancelled()
                    document = write_video_docx(
                        folder / "transcript.docx", video.title, transcript["text"], payload["account"]
                    )
                    from platform_core.services.collection_artifact_service import publish_video

                    artifact = await asyncio.to_thread(
                        publish_video,
                        owner_uid,
                        video.oid,
                        video.title,
                        transcript["text"],
                        document.read_bytes(),
                        payload["account"],
                    )
                    uploaded = await store_video_document(owner_uid, video.oid, document.read_bytes(), storage)
                    item.update(
                        transcript,
                        status="completed",
                        object_key=uploaded.object_name,
                        filename=video_filename(video.title, video.oid),
                        workspace_path=artifact["primary_path"],
                    )
                    result["completed_count"] += 1
            except asyncio.CancelledError:
                item.update(status="cancelled", error="任务已停止，可重新提交未完成视频")
                await context.set_result(result)
                raise
            except Exception:
                logger.exception("视频号转写失败 task={} item={}", context.task_id, index)
                item.update(status="failed", error="处理失败，请检查连接、模型环境和音轨后重试")
                result["failed_count"] += 1
            await context.set_result(result)
            await context.set_progress((index + 1) / len(pending) * 100, f"已处理 {index + 1}/{len(pending)}")
    if result["failed_count"] and not result["completed_count"]:
        raise WxChannelsError("本次视频均处理失败，可在执行记录中重试")
    await context.set_progress(100, "转换结束" if pending else "视频均已转换，已自动跳过")
    return result


def present_transcript_item(item: dict) -> dict:
    """历史任务在读取时使用当前排版，不修改原始识别文本和完成记录。"""
    public = {key: value for key, value in item.items() if key != "object_key"}
    if item.get("status") == "completed":
        public.update(transcript_presentation(item.get("title", ""), item.get("text", "")))
    return public


async def export_transcript_document(item: dict, account: str) -> bytes:
    """已有文字稿按当前版式导出；缺少源文本的旧记录仍可下载原文件。"""
    if isinstance(item.get("text"), str) and item["text"].strip():
        return await asyncio.to_thread(video_docx_bytes, item.get("title", ""), item["text"], account)
    storage = get_minio_client()
    return await storage.adownload_file(storage.KB_BUCKETS["documents"], item["object_key"])


async def import_transcripts(owner_uid: str, kb_id: str, task: dict, indexes: list[int]) -> dict:
    """将已授权的文字稿复制入知识库，在同一事务中创建标准索引任务。"""
    from sqlalchemy import func, select

    from platform_core.repositories.knowledge_base_repository import KnowledgeBaseRepository
    from platform_core.services.task_service import tasker
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_knowledge import KnowledgeFile

    selected = set(indexes)
    items = [
        item
        for item in (task.get("result") or {}).get("items", [])
        if item["index"] in selected and item["status"] == "completed"
    ]
    if len(items) != len(selected):
        raise ValueError("只能导入已完成且属于当前任务的文字稿")
    storage = get_minio_client()
    file_ids = []
    async with pg_manager.get_async_session_context() as session:
        # 与知识库文件操作共用目录树锁，重复导入保留已有文件和索引状态。
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(kb_id))))
        for item in items:
            file_id = "video_" + hashlib.sha256(f"{kb_id}\0{owner_uid}\0{item['oid']}".encode()).hexdigest()[:40]
            if not await session.scalar(select(KnowledgeFile.file_id).where(KnowledgeFile.file_id == file_id)):
                text = video_markdown(item["title"], item["text"], task["payload"]["account"], item["oid"])
                data = text.encode("utf-8")
                uploaded = await storage.aupload_file(
                    bucket_name=storage.KB_BUCKETS["documents"],
                    object_name=f"{kb_id}/video/{file_id}.md",
                    data=data,
                    content_type="text/markdown; charset=utf-8",
                )
                session.add(
                    KnowledgeFile(
                        file_id=file_id,
                        kb_id=kb_id,
                        filename=item["filename"].removesuffix(".docx") + ".md",
                        file_type="md",
                        path=uploaded.url,
                        minio_url=uploaded.url,
                        markdown_file=uploaded.url,
                        status="parsed",
                        content_type="file",
                        content_hash=hashlib.sha256(data).hexdigest(),
                        file_size=len(data),
                        created_by=owner_uid,
                        processing_params={
                            "video_source": {
                                "oid": item["oid"],
                                "task_id": task["id"],
                                "account": task["payload"]["account"],
                            }
                        },
                    )
                )
            file_ids.append(file_id)
        scope = {"kb_id": kb_id, "file_ids": sorted(file_ids), "operator_id": owner_uid}
        index_task, created = await tasker.create_unique_in_session(
            session,
            name="视频号文字稿入库",
            task_type="knowledge_index",
            payload={**scope, "params": {}},
            payload_match=scope,
        )
    if created:
        await tasker.publish(index_task)
    await KnowledgeBaseRepository().refresh_stats(kb_id)
    return {"task_id": index_task.id, "created": created, "file_ids": file_ids}
