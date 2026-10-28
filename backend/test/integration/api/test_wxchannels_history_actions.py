"""真实 HTTP/PostgreSQL 验证历史删除的归属和终态限制。"""

from uuid import uuid4
import shutil

import httpx
import pytest
from sqlalchemy import delete, select, update

from platform_core.services.wxchannels_service import TASK_TYPE
from platform_core.services import collection_artifact_service as artifacts
from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, TaskRecord, User
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import user_workspace_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
BASE = "/api/knowledge/wxchannels/tasks"


async def test_history_delete_preserves_other_users_and_running_tasks():
    """使用专属测试用户与未投递任务验证授权、终态删除及刷新事实。"""
    identities = []
    records = {}
    oid = "history-actions-" + uuid4().hex
    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department).limit(1))
        for _ in range(2):
            uid = "pytest_wx_history_" + uuid4().hex
            user = User(uid=uid, username=uid, password_hash="no-login", role="user", department_id=department.id)
            db.add(user)
            await db.flush()
            identities.append(
                (user.id, uid, {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})})
            )
        for status in ("success", "failed", "cancelled", "pending", "running"):
            task_id = uuid4().hex
            records[status] = task_id
            db.add(
                TaskRecord(
                    id=task_id,
                    name="历史操作验收",
                    type=TASK_TYPE,
                    status=status,
                    payload={"operator_id": identities[0][1], "account": "pytest history"},
                    result={
                        "items": [
                            {
                                "oid": oid,
                                "index": 0,
                                "status": "completed",
                                "title": "历史按钮测试",
                                "text": "测试文字稿",
                                "filename": "测试.docx",
                            }
                        ]
                    }
                    if status == "success"
                    else {},
                )
            )
        unrelated = uuid4().hex
        db.add(
            TaskRecord(
                id=unrelated,
                name="其他类型任务",
                type="not_wxchannels",
                status="success",
                payload={"operator_id": identities[0][1]},
            )
        )
    try:
        artifact = artifacts.publish_video(
            identities[0][1],
            oid,
            "历史按钮测试",
            "测试文字稿",
            video_docx_bytes("历史按钮测试", "测试文字稿"),
            "pytest history",
        )
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=30) as client:
            owner, other = identities[0][2], identities[1][2]
            assert (await client.get("/api/tasks", headers=other)).json()["summary"]["total"] == 0
            assert (await client.get(f"/api/tasks/{records['success']}", headers=owner)).status_code == 200
            assert (await client.get(f"/api/tasks/{records['success']}", headers=other)).status_code == 404
            assert (await client.post(f"/api/tasks/{records['running']}/cancel", headers=other)).status_code == 404
            assert (await client.delete(f"/api/tasks/{records['success']}", headers=other)).status_code == 404
            assert (await client.get("/api/knowledge/databases", headers=owner)).status_code == 200
            assert (await client.get("/api/knowledge/databases", headers=other)).status_code == 200
            assert (await client.get(BASE, headers=other)).json()["tasks"] == []
            assert (await client.get(f"{BASE}/{records['success']}/items/0/docx", headers=owner)).status_code == 200
            assert (await client.get(f"{BASE}/{records['success']}/items/0/docx", headers=other)).status_code == 404
            own_artifacts = (await client.get("/api/knowledge/collection-artifacts/wxchannels", headers=owner)).json()[
                "items"
            ]
            assert [item["id"] for item in own_artifacts] == [artifact["id"]]
            assert (await client.get("/api/knowledge/collection-artifacts/wxchannels", headers=other)).json()[
                "items"
            ] == []
            assert (
                await client.get("/api/workspace/file", params={"path": artifact["import_path"]}, headers=other)
            ).status_code == 404
            initial = (await client.get(f"{BASE}/{records['success']}", headers=owner)).json()
            assert initial["result"]["items"][0]["workspace_path"] == artifact["primary_path"]
            assert (await client.delete(f"{BASE}/{records['success']}")).status_code == 401
            assert (await client.delete(f"{BASE}/{records['success']}", headers=other)).status_code == 404
            assert (await client.delete(f"{BASE}/{unrelated}", headers=owner)).status_code == 404
            for status in ("pending", "running"):
                assert (await client.delete(f"{BASE}/{records[status]}", headers=owner)).status_code == 409
                assert (await client.get(f"{BASE}/{records[status]}", headers=owner)).json()["status"] == status
            for status in ("success", "failed", "cancelled"):
                response = await client.delete(f"{BASE}/{records[status]}", headers=owner)
                assert response.status_code == 200 and response.json()["deleted"]
                assert (await client.get(f"{BASE}/{records[status]}", headers=owner)).status_code == 404
            remaining = (await client.get(BASE, headers=owner)).json()["tasks"]
            assert {item["id"] for item in remaining} == {records["pending"], records["running"]}
            markdown = await client.get("/api/workspace/file", params={"path": artifact["import_path"]}, headers=owner)
            assert markdown.status_code == 200 and "测试文字稿" in markdown.text
        async with pg_manager.get_async_session_context() as db:
            assert await db.get(TaskRecord, records["success"]) is None
            assert await db.get(TaskRecord, unrelated) is not None
    finally:
        for _, uid, _ in identities:
            shutil.rmtree(user_workspace_dir(uid), ignore_errors=True)
            shutil.rmtree(artifacts.manifest_directory(uid), ignore_errors=True)
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(TaskRecord).where(TaskRecord.id.in_([*records.values(), unrelated])))
            await db.execute(
                update(User).where(User.id.in_([identity[0] for identity in identities])).values(is_deleted=True)
            )
