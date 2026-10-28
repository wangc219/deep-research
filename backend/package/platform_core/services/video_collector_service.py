"""个人微信视频号采集端与云端识别流程的衔接。"""

import asyncio
import hashlib
import io
import time
import wave
from uuid import uuid4
from pathlib import Path
from tempfile import TemporaryDirectory

from platform_core.repositories.video_collector_repository import VideoCollectorRepository
from platform_core.repositories.video_collector_repository import CollectorConflict
from platform_core.services import wxchannels_service as video
from platform_core.services.task_service import tasker
from platform_core.storage.minio.client import get_minio_client


def audio_prefix(task_id: str, execution_id: str) -> str:
    """每次 Worker 执行使用独立的临时音频空间。"""
    digest = hashlib.sha256(execution_id.encode()).hexdigest()[:24]
    return f"video-audio/{task_id}/{digest}/"


async def require_personal_device(owner_uid: str, device_id: str):
    """提交任务前检查配对归属、在线状态及实测采集能力。"""
    devices = await VideoCollectorRepository().list_owned(owner_uid)
    device = next((item for item in devices if item["device_id"] == device_id), None)
    if not device or not device["online"] or not device["state"].get("channels_ready"):
        raise CollectorConflict("请选择属于自己的在线视频采集端，并在该电脑登录微信、打开视频号页面")
    return device


async def stage_audio(device, *, task_id, execution_id, sequence, oid, title, content):
    """校验临时 WAV 并按当前设备租约交接，不上传微信凭据和原视频。"""
    task = await tasker.get_task(task_id)
    if (
        not task
        or task["type"] != video.TASK_TYPE
        or task["status"] != "running"
        or task["worker_id"] != execution_id
        or task.get("cancel_requested")
        or task["payload"].get("operator_id") != device.owner_uid
        or task["payload"].get("device_id") != device.device_id
        or task["payload"].get("collection_mode") != "personal"
    ):
        raise CollectorConflict("当前采集端没有本次任务的回传权限")
    try:
        with wave.open(io.BytesIO(content)) as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (
                1,
                2,
                16000,
                "NONE",
            ):
                raise ValueError("请回传 16 kHz 单声道 PCM WAV")
            if not 0 < audio.getnframes() <= 16000 * 7200:
                raise ValueError("音轨为空或超过两小时限制")
    except (wave.Error, EOFError) as error:
        raise ValueError("音频格式无效") from error
    client = get_minio_client()
    key = audio_prefix(task_id, execution_id) + str(sequence) + "_" + uuid4().hex + ".wav"
    retained = False
    try:
        await client.aupload_file(
            bucket_name=client.KB_BUCKETS["documents"], object_name=key, data=content, content_type="audio/wav"
        )
        retained = await VideoCollectorRepository().receive(
            device,
            task_id=task_id,
            execution_id=execution_id,
            sequence=sequence,
            kind="audio",
            detail={"oid": oid, "title": title, "object_key": key},
        )
        return retained
    finally:
        if not retained:
            await client.adelete_file(client.KB_BUCKETS["documents"], key)


async def wait_captures(context):
    """设备断线、撤销或平台取消时停止等待。"""
    await context.raise_if_cancelled()
    devices = await VideoCollectorRepository().list_owned(context.payload["operator_id"])
    device = next((item for item in devices if item["device_id"] == context.payload["device_id"]), None)
    if not device or not device["online"]:
        raise CollectorConflict("个人微信采集端已断线或被撤销，请重新连接后重试")
    return await VideoCollectorRepository().captures(context.task_id, context.worker_id)


async def run_personal_video_discovery(context):
    """分页发现由用户电脑执行，平台只接收公开视频标识与简介。"""
    await context.set_message("等待个人微信采集端获取视频列表")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        rows = await wait_captures(context)
        for row in rows:
            if row.detail.get("error"):
                raise CollectorConflict(row.detail["error"])
        if rows and rows[-1].detail.get("finished", True):
            if [row.sequence for row in rows] != list(range(1, rows[-1].sequence + 1)):
                await asyncio.sleep(0.75)
                continue
            data = rows[-1].detail
            videos = {item["oid"]: item for row in rows for item in row.detail["videos"]}
            channel = await video.WechatChannelRepository().merge(
                context.payload["operator_id"],
                context.payload["account"],
                data["username"],
                list(videos.values()),
                complete=data.get("history_complete", True) and context.payload.get("max_pages") is None,
            )
            result = await video.saved_video_discovery(
                context.payload["operator_id"], channel, context.payload.get("max_videos")
            )
            await VideoCollectorRepository().cleanup(context.task_id, context.worker_id)
            return result
        await asyncio.sleep(0.75)
    raise CollectorConflict("采集端获取视频超时，请重新打开微信视频号页面后重试")


async def run_personal_video_transcribe(context):
    """临时音频由个人电脑上传，SenseVoice、Word、存储与入库在云端共用。"""
    payload = context.payload
    storage = get_minio_client()
    completed = await video.completed_video_oids(payload["operator_id"], storage)
    result = {
        "account": payload["account"],
        "items": [],
        "completed_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "completed_oids": sorted(completed),
    }
    await context.set_result(result)
    await context.set_message("等待个人微信采集端提取音频")
    seen = set()
    prefix = audio_prefix(context.task_id, context.worker_id)
    try:
        while True:
            rows = await wait_captures(context)
            for row in rows:
                if row.capture_id in seen:
                    continue
                if row.kind == "complete":
                    result["skipped_count"] = row.detail.get("skipped_count", 0)
                    await context.set_result(result)
                    if row.detail.get("error"):
                        raise CollectorConflict(row.detail["error"])
                    if result["failed_count"] and not result["completed_count"]:
                        raise CollectorConflict("本次视频均处理失败，可查看记录并重试")
                    await context.set_progress(100, "转换结束")
                    return result
                data = row.detail
                item = {
                    "index": len(result["items"]),
                    "oid": data["oid"],
                    "title": data["title"],
                    "status": "transcribing",
                }
                result["items"].append(item)
                await context.set_result(result)
                await context.set_message(f"语音转写第 {len(result['items'])} 条视频")
                try:
                    with TemporaryDirectory(prefix="knowledge_video_") as temporary:
                        folder = Path(temporary)
                        audio = folder / "audio.wav"
                        audio.write_bytes(
                            await storage.adownload_file(storage.KB_BUCKETS["documents"], data["object_key"])
                        )
                        transcript = await video.cancellable(
                            context,
                            video.transcribe_audio(
                                audio,
                                folder / "transcript.json",
                                payload["language"],
                                payload["timeout_seconds"],
                            ),
                        )
                        await context.raise_if_cancelled()
                        document = video.write_video_docx(
                            folder / "transcript.docx", data["title"], transcript["text"], payload["account"]
                        )
                        from platform_core.services.collection_artifact_service import publish_video

                        artifact = await asyncio.to_thread(
                            publish_video,
                            payload["operator_id"],
                            data["oid"],
                            data["title"],
                            transcript["text"],
                            document.read_bytes(),
                            payload["account"],
                        )
                        uploaded = await video.store_video_document(
                            payload["operator_id"],
                            data["oid"],
                            document.read_bytes(),
                            storage,
                        )
                        item.update(
                            transcript,
                            status="completed",
                            object_key=uploaded.object_name,
                            filename=video.video_filename(data["title"], data["oid"]),
                            workspace_path=artifact["primary_path"],
                        )
                        result["completed_count"] += 1
                except asyncio.CancelledError:
                    item.update(status="cancelled", error="任务已停止")
                    await context.set_result(result)
                    raise
                except Exception:
                    video.logger.exception("个人视频转写失败 task={}", context.task_id)
                    item.update(status="failed", error="语音识别失败，请检查模型环境与音轨")
                    result["failed_count"] += 1
                finally:
                    await storage.adelete_file(storage.KB_BUCKETS["documents"], data["object_key"])
                seen.add(row.capture_id)
                await context.set_result(result)
                await context.set_progress(
                    min(95, len(result["items"]) / (payload["max_videos"] or (len(result["items"]) + 1)) * 100)
                )
            await asyncio.sleep(0.75)
    finally:
        await storage.adelete_objects_by_prefix(storage.KB_BUCKETS["documents"], prefix)
        await VideoCollectorRepository().cleanup(context.task_id, context.worker_id)
