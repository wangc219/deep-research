"""显式启用的原生深研入口真实模型验收，使用独立测试用户与项目。"""

import asyncio
import os
import shutil
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text
from test.live_api_cleanup import cleanup_test_chat_resources, make_test_conversation_title, make_test_resource_id

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import AgentRun, Department, Project, User
from platform_core.storage.postgres.models_equipment import EquipmentDeepSession
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("EQUIPMENT_TEST_LIVE_MODELS") != "1", reason="需要显式启用真实模型调用"),
]


async def test_native_deep_message_reaches_worker_transcript_and_usage():
    """保留默认深研角色与统一模型配置，核对平台原生运行和计量事实。"""
    pg_manager.initialize()
    uid = "native_smoke_" + uuid4().hex[:12]
    request_id = ""
    async with pg_manager.get_async_session_context() as db:
        department_id = await db.scalar(select(Department.id).limit(1))
        user = User(
            uid=uid, username=uid, password_hash="disabled-test-login", role="superadmin", department_id=department_id
        )
        db.add(user)
        await db.flush()
        headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}
        await db.commit()

    async with httpx.AsyncClient(base_url="http://web", headers=headers, timeout=60) as client:
        try:
            directory_name = "native-deep-" + uuid4().hex[:12]
            response = await client.post(
                "/api/workspace/directory",
                json={"parent_path": "/", "name": directory_name},
            )
            assert response.status_code == 200, response.text
            response = await client.post(
                "/api/projects",
                json={
                    "name": make_test_conversation_title("native-deep"),
                    "request_id": make_test_resource_id("native-deep"),
                    "workdir": {"mode": "linked", "path": directory_name},
                },
            )
            assert response.status_code == 200, response.text
            project_id = response.json()["id"]
            response = await client.post(
                "/api/equipment/deep-thinking",
                json={
                    "project_id": project_id,
                    "title": make_test_conversation_title("native-deep"),
                    "topic": "民用应急照明设备日常维护",
                },
            )
            assert response.status_code == 200, response.text
            session = response.json()
            session_id = session["session_id"]
            model_spec = session["model_spec"]
            assert model_spec
            assert session["payload"]["runtime"] == "agent"
            response = await client.post(
                f"/api/equipment/deep-thinking/{session_id}/messages",
                json={
                    "content": (
                        "这是民用软件集成验收。请给出应急照明设备日常维护的三个通用检查项，"
                        "简短回答即可，不生成报告或画像。"
                    ),
                },
            )
            assert response.status_code == 200, response.text
            request_id = response.json()["request"]["request_id"]
            started = monotonic()
            previous = None
            while monotonic() - started < float(os.getenv("EQUIPMENT_TEST_LIVE_TIMEOUT_SECONDS", "600")):
                response = await client.get(f"/api/equipment/deep-thinking/{session_id}")
                assert response.status_code == 200, response.text
                detail = response.json()
                job = next(job for job in detail["jobs"] if job.get("payload", {}).get("request_id") == request_id)
                if job["status"] != previous:
                    print({"elapsed_seconds": round(monotonic() - started), "status": job["status"]}, flush=True)
                    previous = job["status"]
                if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                    break
                await asyncio.sleep(2)
            assert job["status"] == "completed", {
                "status": job["status"],
                "error": job.get("error"),
                "request_id": request_id,
            }
            assert any(message["role"] == "assistant" and message.get("content") for message in detail["messages"])
            async with pg_manager.get_async_session_context() as db:
                run = await db.scalar(select(AgentRun).where(AgentRun.request_id == request_id))
                assert run.source == "equipment_deep_research"
                assert run.external_id == session_id
                rows = (
                    (
                        await db.execute(
                            text("SELECT model_spec,surface,status FROM platform_model_calls WHERE run_id=:run_id"),
                            {"run_id": run.id},
                        )
                    )
                    .mappings()
                    .all()
                )
                assert rows
                assert all(row["model_spec"] == model_spec and row["surface"] == "深研对话" for row in rows)
                assert any(row["status"] == "completed" for row in rows)
        finally:
            if request_id:
                await client.post(f"/api/agent/requests/{request_id}/cancel")
            for _ in range(100):
                async with pg_manager.get_async_session_context() as db:
                    active = list(
                        (
                            await db.scalars(
                                select(AgentRun.id).where(
                                    AgentRun.uid == uid,
                                    AgentRun.status.notin_(["completed", "failed", "cancelled", "interrupted"]),
                                )
                            )
                        ).all()
                    )
                if not active:
                    break
                for run_id in active:
                    await client.post(f"/api/agent/runs/{run_id}/cancel")
                await asyncio.sleep(0.2)
            assert not active, {"cleanup_pending_runs": active, "test_uid": uid}
            async with pg_manager.get_async_session_context() as db:
                await db.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.owner_uid == uid))
                await db.commit()
            await cleanup_test_chat_resources(client, headers, owner_uid=uid)
            async with pg_manager.get_async_session_context() as db:
                await db.execute(delete(Project).where(Project.uid == uid))
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                    {"uid": uid},
                )
                await db.execute(delete(User).where(User.uid == uid))
                await db.commit()
            root = global_user_data_dir(uid)
            assert root.name == uid and uid.startswith("native_smoke_")
            if root.exists():
                shutil.rmtree(root)
            await pg_manager.close()
