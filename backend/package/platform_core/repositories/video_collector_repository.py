"""本机微信采集端的配对、心跳与租约交接。"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import TaskRecord
from platform_core.storage.postgres.models_knowledge import VideoCollectorCapture, VideoCollectorDevice
from platform_core.utils.datetime_utils import utc_now, utc_now_naive


class CollectorConflict(ValueError):
    """采集端或任务已经撤销、重启或结束。"""


VIDEO_TASK_TYPES = {"wxchannels_transcribe", "wxchannels_discover"}


class VideoCollectorRepository:
    """平台数据库是配对和执行授权的唯一事实来源。"""

    async def enroll(self, owner_uid: str, *, device_id: str, token: str, name: str, platform: str):
        """客户端生成令牌，幂等重放相同请求；撤销记录不会被重放复活。"""
        digest = hashlib.sha256(f"{device_id}:{token}".encode()).hexdigest()
        async with pg_manager.get_async_session_context() as session:
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(device_id))))
            device = await session.get(VideoCollectorDevice, device_id)
            if device:
                if (
                    device.owner_uid != owner_uid
                    or not secrets.compare_digest(device.token_digest, digest)
                    or device.revoked_at
                ):
                    raise CollectorConflict("采集端标识已被使用或撤销，请创建新的配对")
                return self.device_dict(device)
            device = VideoCollectorDevice(
                device_id=device_id, token_digest=digest, name=name, owner_uid=owner_uid, platform=platform, state={}
            )
            session.add(device)
            await session.flush()
            return self.device_dict(device)

    async def authenticate(self, device_id: str, token: str):
        """配对凭据只授权该设备的采集操作，不授予用户账户权限。"""
        async with pg_manager.get_async_session_context() as session:
            device = await session.get(VideoCollectorDevice, device_id)
            digest = hashlib.sha256(f"{device_id}:{token}".encode()).hexdigest()
            if not device or device.revoked_at or not secrets.compare_digest(device.token_digest, digest):
                return None
            return device

    async def list_owned(self, owner_uid: str):
        """返回连接与真实环境检查状态，离线状态由服务器心跳时间计算。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(VideoCollectorDevice)
                    .where(VideoCollectorDevice.owner_uid == owner_uid, VideoCollectorDevice.revoked_at.is_(None))
                    .order_by(VideoCollectorDevice.created_at.desc())
                )
            ).all()
            return [self.device_dict(row) for row in rows]

    async def revoke(self, owner_uid: str, device_id: str):
        """保留撤销墓碑，同时请求停止该设备尚未结束的任务。"""
        async with pg_manager.get_async_session_context() as session:
            device = await session.get(VideoCollectorDevice, device_id, with_for_update=True)
            if not device or device.owner_uid != owner_uid:
                return False
            device.revoked_at = utc_now()
            tasks = (
                await session.scalars(
                    select(TaskRecord)
                    .where(
                        TaskRecord.type.in_(
                            {
                                "wxchannels_transcribe",
                                "wxchannels_discover",
                            }
                        ),
                        TaskRecord.status.in_(["pending", "running"]),
                        TaskRecord.payload["device_id"].as_string() == device_id,
                        TaskRecord.payload["operator_id"].as_string() == owner_uid,
                    )
                    .with_for_update()
                )
            ).all()
            for task in tasks:
                task.cancel_requested = 1
            return True

    async def captures(self, task_id: str, execution_id: str):
        """Worker 只消费当前执行的交接物。"""
        async with pg_manager.get_async_session_context() as session:
            return (
                await session.scalars(
                    select(VideoCollectorCapture)
                    .where(VideoCollectorCapture.task_id == task_id, VideoCollectorCapture.execution_id == execution_id)
                    .order_by(VideoCollectorCapture.sequence)
                )
            ).all()

    async def cleanup(self, task_id: str, execution_id: str):
        """只释放本次执行交接记录，不触碰其他执行和归档。"""
        async with pg_manager.get_async_session_context() as session:
            await session.execute(
                delete(VideoCollectorCapture).where(
                    VideoCollectorCapture.task_id == task_id, VideoCollectorCapture.execution_id == execution_id
                )
            )

    @staticmethod
    def device_dict(device):
        """从最后心跳判断在线状态，不把平台标识当成已验证能力。"""
        online = bool(device.last_seen_at and device.last_seen_at > utc_now() - timedelta(seconds=20))
        return {
            "device_id": device.device_id,
            "name": device.name,
            "platform": device.platform,
            "online": online,
            "state": device.state or {},
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        }

    async def heartbeat(self, device_id: str, state: dict):
        """仅下发绑定到当前设备及用户的运行任务。"""
        async with pg_manager.get_async_session_context() as session:
            device = await session.get(VideoCollectorDevice, device_id, with_for_update=True)
            if not device or device.revoked_at:
                raise CollectorConflict("采集端配对已撤销")
            device.state = {**state, "channel_capable": True}
            device.last_seen_at = utc_now()
            task = await session.scalar(
                select(TaskRecord)
                .where(
                    TaskRecord.type.in_(VIDEO_TASK_TYPES),
                    TaskRecord.status == "running",
                    TaskRecord.payload["device_id"].as_string() == device_id,
                    TaskRecord.payload["operator_id"].as_string() == device.owner_uid,
                    TaskRecord.lease_expires_at > utc_now_naive(),
                )
                .order_by(TaskRecord.created_at)
                .limit(1)
            )
            if not task or (task.type == "wxchannels_transcribe" and not isinstance(task.result, dict)):
                return None
            return {
                "task_id": task.id,
                "execution_id": task.worker_id,
                "task_type": task.type,
                "cancel_requested": bool(task.cancel_requested),
                "account": task.payload["account"],
                "max_pages": task.payload["max_pages"],
                "known_oids": task.payload.get("known_oids", []),
                "resolved_username": task.payload.get("resolved_username"),
                "max_videos": task.payload.get("max_videos", 100),
                "processed_count": sum(
                    item.get("status") in {"completed", "failed"} for item in (task.result or {}).get("items", [])
                ),
                "video_oids": task.payload.get("video_oids", []),
                "completed_oids": (task.result or {}).get("completed_oids", []),
            }

    async def receive(self, device, *, task_id, execution_id, sequence, kind, detail):
        """拒绝跨用户、跨设备、失效租约和超量的交接；同序号回传可重放。"""
        identity = hashlib.sha256(f"{task_id}:{execution_id}:{sequence}".encode()).hexdigest()
        async with pg_manager.get_async_session_context() as session:
            task = await session.get(TaskRecord, task_id, with_for_update=True)
            live_device = await session.get(VideoCollectorDevice, device.device_id)
            if (
                not live_device
                or live_device.revoked_at
                or not task
                or task.type not in VIDEO_TASK_TYPES
                or task.status != "running"
                or task.cancel_requested
                or task.worker_id != execution_id
                or not task.lease_expires_at
                or task.lease_expires_at <= utc_now_naive()
                or task.payload.get("device_id") != device.device_id
                or task.payload.get("operator_id") != device.owner_uid
                or task.payload.get("collection_mode") != "personal"
            ):
                raise CollectorConflict("任务已停止、配对已撤销或执行租约已变化")
            limit = 101 if task.type == "wxchannels_discover" else (task.payload.get("max_videos", 100) or 202000) + 1
            if sequence < 1 or sequence > limit:
                raise CollectorConflict("回传序号超过本次采集上限")
            if (task.type == "wxchannels_discover" and kind != "video_list") or (
                task.type == "wxchannels_transcribe" and kind not in {"audio", "complete"}
            ):
                raise CollectorConflict("回传内容与任务类型不匹配")
            if await session.get(VideoCollectorCapture, identity):
                return False
            session.add(
                VideoCollectorCapture(
                    capture_id=identity,
                    task_id=task_id,
                    execution_id=execution_id,
                    device_id=device.device_id,
                    sequence=sequence,
                    kind=kind,
                    detail=detail,
                )
            )
            return True
