"""真实 PostgreSQL 验证研究执行返回与取消之间的终态竞争。"""

import asyncio
import os
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import delete, select, text

from platform_core.services import equipment_research_task as task
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, Project, User
from platform_core.utils.auth_utils import AuthUtils
from platform_core.storage.postgres.models_equipment import (
    EquipmentArtifactRef,
    EquipmentCapabilityVersion,
    EquipmentResearchEvent,
    EquipmentResearchRun,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("cancellation", ["committed", "inflight", "none"])
async def test_cancelled_run_cannot_be_completed_by_late_domain_result(monkeypatch, cancellation):
    """模拟慢外部执行，不调用模型，取消提交后拒绝迟到的完成和产物。"""
    pg_manager.initialize()
    uid = "terminal_test_" + uuid4().hex[:12]
    project_id, run_id = str(uuid4()), str(uuid4())
    entered, release = Event(), Event()
    job = None
    monkeypatch.setattr(task, "get_async_redis_client", AsyncMock(return_value=SimpleNamespace(xadd=AsyncMock())))

    def domain(_run, **_kwargs):
        entered.set()
        assert release.wait(10), "test must release the simulated external executor"
        return {
            "result": {
                "status": "completed",
                "artifact_counts": {"sources": 2, "evidence": 1, "capabilities": 3, "reports": 1},
            },
            "events": [],
            "artifact_relpath": "outputs/test-only",
            "artifact_sha256": "0" * 64,
            "capability_images": [
                {
                    "capability_id": "capability-terminal-race",
                    "card_binding_id": "s6-card-terminal-race",
                    "hypothesis_id": "hypothesis-terminal-race",
                    "name": "终态竞争测试画像",
                    "capability_portrait_modules": {
                        "overview": "概述",
                        "technology_implementation": "技术实现",
                        "operational_process": "作战流程",
                        "capability_effects": "能力效果",
                        "winning_logic": "制胜逻辑",
                    },
                }
            ],
        }

    monkeypatch.setattr(task, "_run_domain", domain)
    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            user = User(uid=uid, username=uid, password_hash="disabled", role="user", department_id=department_id)
            db.add(user)
            await db.flush()
            headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}
            db.add(
                Project(
                    id=project_id,
                    uid=uid,
                    name=uid,
                    selection_status="selectable",
                    directory_mode="managed",
                    workdir_path="projects/" + project_id,
                )
            )
            await db.flush()
            db.add(
                EquipmentResearchRun(
                    id=run_id,
                    project_id=project_id,
                    owner_uid=uid,
                    topic="通用执行测试",
                    status="queued",
                    error="previous attempt failed",
                )
            )
        job = asyncio.create_task(task.run_equipment_research(SimpleNamespace(payload={"run_id": run_id})))
        assert await asyncio.to_thread(entered.wait, 5)
        if cancellation == "committed":
            async with httpx.AsyncClient(
                base_url=os.getenv("TEST_BASE_URL", "http://web"), headers=headers, timeout=15
            ) as client:
                response = await client.post(f"/api/equipment/runs/{run_id}/cancel")
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "cancelled"
        elif cancellation == "inflight":
            async with pg_manager.get_async_session_context() as db:
                run = await EquipmentResearchRepository(db).lock_run(run_id)
                run.status = "cancelled"
                await db.flush()
                release.set()
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(job), 0.1)
        release.set()
        result = await asyncio.wait_for(job, 5)
        async with pg_manager.get_async_session_context() as db:
            run = await db.get(EquipmentResearchRun, run_id)
            cancel = cancellation != "none"
            expected = "cancelled" if cancel else "completed"
            assert run.status == expected
            assert result["status"] == expected
            if expected == "completed":
                assert run.error == ""
                assert run.payload["result"]["artifact_counts"]["capabilities"] == 3
            artifact_id = await db.scalar(select(EquipmentArtifactRef.id).where(EquipmentArtifactRef.run_id == run_id))
            assert artifact_id == (None if cancel else f"artifact-{run_id}")
            capability_rows = (
                await db.scalars(
                    select(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.run_id == run_id)
                )
            ).all()
            assert len(capability_rows) == (0 if cancel else 1)
            if capability_rows:
                assert capability_rows[0].snapshot["status"] == "formal"
                assert capability_rows[0].snapshot["source"] == "formal_s6"
            events = (
                await db.scalars(select(EquipmentResearchEvent).where(EquipmentResearchEvent.run_id == run_id))
            ).all()
            assert sum(event.payload.get("status") == "completed" for event in events) == (0 if cancel else 1)
        repeated = await task._set_status(run_id, "completed", artifact_relpath="late-duplicate")
        assert repeated.status == expected
    finally:
        release.set()
        if job is not None:
            await asyncio.gather(job, return_exceptions=True)
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.run_id == run_id))
            await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.id == run_id))
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
            await db.execute(
                text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                {"uid": uid},
            )
            await db.execute(delete(User).where(User.uid == uid))
        await pg_manager.close()
