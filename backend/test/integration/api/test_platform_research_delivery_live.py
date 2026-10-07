"""平台研究任务的真实 HTTP、队列、Worker 与文件交付验收；模型使用 fake。"""

import asyncio
import shutil
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.repositories.task_repository import TERMINAL_TASK_STATUSES
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, Project, TaskRecord, User
from platform_core.storage.postgres.models_equipment import EquipmentArtifactRef, EquipmentResearchRun
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir, user_workdir_host_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_platform_research_preserves_profile_and_publishes_delivery():
    """验证软件执行契约与交付文件，不生成真实研究结论或调用外部模型。"""
    pg_manager.initialize()
    uid = "delivery_test_" + uuid4().hex[:12]
    run_id = ""
    async with pg_manager.get_async_session_context() as db:
        department_id = await db.scalar(select(Department.id).limit(1))
        user = User(uid=uid, username=uid, password_hash="disabled", role="user", department_id=department_id)
        db.add(user)
        await db.flush()
        headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}

    async with httpx.AsyncClient(base_url="http://web", headers=headers, timeout=60) as client:
        try:
            directory = "delivery-" + uuid4().hex[:12]
            response = await client.post("/api/workspace/directory", json={"parent_path": "/", "name": directory})
            assert response.status_code == 200, response.text
            response = await client.post(
                "/api/projects",
                json={
                    "name": "隔离软件交付验收",
                    "request_id": uid,
                    "workdir": {"mode": "linked", "path": directory},
                },
            )
            assert response.status_code == 200, response.text
            project = response.json()
            response = await client.post(
                "/api/equipment/runs",
                json={
                    "project_id": project["id"],
                    "topic": "民用应急照明设备维护的软件交付验收",
                    "payload": {
                        "execution": {"mode": "fake"},
                        "max_rounds": 1,
                        "execution_profile_id": "winning_swarm_dynamic_v2",
                        "report_template_mode": "project_argument_v1",
                        "interaction_mode": "autonomous",
                        "analyst_confirmed": True,
                    },
                },
            )
            assert response.status_code == 200, response.text
            run_id = response.json()["run_id"]
            response = await client.post(f"/api/equipment/runs/{run_id}/start")
            assert response.status_code == 200, response.text
            started = monotonic()
            previous = None
            while monotonic() - started < 300:
                response = await client.get(f"/api/equipment/runs/{run_id}")
                assert response.status_code == 200, response.text
                run = response.json()
                if run["status"] != previous:
                    print({"status": run["status"], "elapsed_seconds": round(monotonic() - started)}, flush=True)
                    previous = run["status"]
                if run["status"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(1)
            assert run["status"] == "completed", {"run_id": run_id, "status": run["status"], "error": run.get("error")}
            async with pg_manager.get_async_session_context() as db:
                artifact = await db.scalar(select(EquipmentArtifactRef).where(EquipmentArtifactRef.run_id == run_id))
                assert artifact is not None and artifact.relative_path == run["artifact_relpath"]
                assert artifact.sha256 == run["artifact_sha256"]
            root = user_workdir_host_dir(uid, project["workdir_path"]) / run["artifact_relpath"]
            assert root.is_dir()
            reports = list(root.glob("report*.md"))
            assert reports and any(path.stat().st_size for path in reports)
            relative = reports[0].relative_to(user_workdir_host_dir(uid, project["workdir_path"]))
            response = await client.get("/api/workspace/file", params={"path": f"{directory}/{relative}"})
            assert response.status_code == 200, response.text
            response = await client.get("/api/equipment/reports")
            assert response.status_code == 200, response.text
            assert any(item["run_id"] == run_id for item in response.json())
        finally:
            if run_id:
                for _ in range(30):
                    async with pg_manager.get_async_session_context() as db:
                        records = list(
                            (
                                await db.scalars(
                                    select(TaskRecord).where(
                                        TaskRecord.payload["run_id"].as_string() == run_id,
                                    )
                                )
                            ).all()
                        )
                    if all(record.status in TERMINAL_TASK_STATUSES for record in records):
                        break
                    await asyncio.sleep(1)
                assert all(record.status in TERMINAL_TASK_STATUSES for record in records), {
                    "cleanup_deferred": True,
                    "uid": uid,
                    "run_id": run_id,
                }
            async with pg_manager.get_async_session_context() as db:
                await db.execute(delete(TaskRecord).where(TaskRecord.payload["run_id"].as_string() == run_id))
                await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.owner_uid == uid))
                await db.execute(delete(Project).where(Project.uid == uid))
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                    {"uid": uid},
                )
                await db.execute(delete(User).where(User.uid == uid))
            root = global_user_data_dir(uid)
            assert root.name == uid and uid.startswith("delivery_test_")
            if root.exists():
                shutil.rmtree(root)
            await pg_manager.close()
