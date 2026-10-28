"""真实 HTTP/队列验证全部分页参数、分块列表及跨任务持久去重。"""

import asyncio
import secrets
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from platform_core.services import wxchannels_service as service
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
BASE = "/api/knowledge/wxchannels"


async def test_default_all_pages_and_chunked_latest_discovery():
    """只模拟个人微信端回传，API、持久完成记录、任务和跨分块去重使用真实服务。"""
    uid = "pytest_wx_latest_" + uuid4().hex
    device_id = "wxd_" + uuid4().hex
    token = secrets.token_hex(32)
    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department).limit(1))
        user = User(uid=uid, username=uid, password_hash="no-login", role="admin", department_id=department.id)
        db.add(user)
        await db.flush()
        user_id = user.id
    headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)})}
    device_headers = {"Authorization": "Bearer " + token, "X-Collector-Device": device_id}
    state = {"channels_ready": True, "mcp_available": True, "wechat_available": True, "ffmpeg_available": True}
    storage = service.get_minio_client()
    await service.store_video_document(uid, "done", b"completed transcript fixture", storage)
    task_ids = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=60) as client:

        async def heartbeat():
            """保活并读取当前真实执行租约。"""
            response = await client.post(BASE + "/collector/heartbeat", headers=device_headers, json=state)
            assert response.status_code == 200, response.text
            return response.json().get("job")

        async def wait_job(task_id):
            """等待 Worker 领取，不调用实际微信或识别服务。"""
            for _ in range(60):
                job = await heartbeat()
                if job and job["task_id"] == task_id:
                    return job
                await asyncio.sleep(0.5)
            pytest.fail("Worker 未领取任务")

        try:
            response = await client.post(
                BASE + "/collector/devices",
                headers=headers,
                json={"device_id": device_id, "token": token, "name": "pytest latest", "platform": "macos"},
            )
            assert response.status_code == 200, response.text
            await heartbeat()
            source = {"account": "pytest latest", "collection_mode": "personal", "device_id": device_id}
            for invalid in ({"max_pages": 0}, {"max_pages": 101}, {"max_videos": 101}):
                response = await client.post(BASE + "/transcribe", headers=headers, json={**source, **invalid})
                assert response.status_code == 422
            for all_pages in ({}, {"max_pages": None}):
                response = await client.post(BASE + "/videos", headers=headers, json={**source, **all_pages})
                assert response.status_code == 200, response.text
                task_id = response.json()["task_id"]
                task_ids.append(task_id)
                job = await wait_job(task_id)
                assert job["max_pages"] is None
                event = {
                    "task_id": task_id,
                    "execution_id": job["execution_id"],
                    "kind": "video_list",
                    "username": "latest@finder",
                }
                first = {
                    **event,
                    "sequence": 1,
                    "finished": False,
                    "videos": [
                        {"oid": str(i), "title": f"视频{i}", "published_at": 1700000000 + i} for i in range(2000)
                    ],
                }
                response = await client.post(BASE + "/collector/event", headers=device_headers, json=first)
                assert response.status_code == 200, response.text
                response = await client.post(BASE + "/collector/event", headers=device_headers, json=first)
                assert response.json()["created"] is False
                response = await client.get(BASE + "/tasks/" + task_id, headers=headers)
                assert response.json()["status"] == "running"
                response = await client.post(
                    BASE + "/collector/event",
                    headers=device_headers,
                    json={
                        **event,
                        "sequence": 2,
                        "finished": True,
                        "videos": [
                            {"oid": "done", "title": "已完成，无近期任务历史", "published_at": 1900000000},
                            {"oid": "newest", "title": "最新", "published_at": 1800000000},
                            {"oid": "0", "title": "跨页重复旧视频", "published_at": 1700000000},
                        ],
                    },
                )
                assert response.status_code == 200, response.text
                for _ in range(60):
                    await heartbeat()
                    task = (await client.get(BASE + "/tasks/" + task_id, headers=headers)).json()
                    if task["status"] in {"success", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(0.5)
                assert task["status"] == "success", task
                result = task["result"]
                assert result["total_count"] == 2002 and result["completed_count"] == 1
                assert len(result["videos"]) == 2001
                assert [item["oid"] for item in result["videos"][:2]] == ["newest", "1999"]
                assert result["videos"][-1]["oid"] == "0"
                assert not any(item["oid"] == "done" for item in result["videos"])
        finally:
            for task_id in task_ids:
                await client.post(BASE + f"/tasks/{task_id}/cancel", headers=headers)
            await client.delete(BASE + "/collector/devices/" + device_id, headers=headers)
            await storage.adelete_objects_by_prefix(storage.KB_BUCKETS["documents"], service.video_owner_prefix(uid))
            async with pg_manager.get_async_session_context() as db:
                await db.execute(update(User).where(User.id == user_id).values(is_deleted=True))
