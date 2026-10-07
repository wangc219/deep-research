"""显式启用的真实供应商验收：临时用户的 Query 生成与深研消息，完成后清理。"""

import asyncio
import os
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("EQUIPMENT_TEST_LIVE_MODELS") != "1", reason="需要显式启用真实模型调用"),
]


async def test_query_generation_and_deep_dialogue_use_managed_model():
    """通过真实 HTTP 与后台执行验证平台配置，不读取旧模型 env。"""
    pg_manager.initialize()
    uid = "model_smoke_" + uuid4().hex[:10]
    run_id = generation_id = ""
    result_query_ids = []
    async with pg_manager.get_async_session_context() as db:
        department_id = await db.scalar(select(Department.id).limit(1))
        user = User(
            uid=uid, username=uid, password_hash="disabled-test-login", role="superadmin", department_id=department_id
        )
        db.add(user)
        await db.flush()
        headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}
        await db.commit()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", headers=headers, timeout=60) as client:
        try:
            response = await client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": uid},
                json={
                    "topic": "民用应急照明设备公开资料整理，比较可靠性与维护便利性",
                    "max_rounds": 1,
                },
            )
            assert response.status_code == 201, response.text
            run = response.json()
            run_id = run["run_id"]
            assert run["execution"]["provider"] == "platform"
            assert run["execution"]["model_spec"]
            assert "api_key" not in run["execution"]
            catalog = (await client.get("/api/v1/deep-thinking/capabilities")).json()["model_profiles"]
            assert catalog["managed"] is True
            assert all(":" in item["id"] for item in catalog["profiles"])
            deep_model = os.getenv("EQUIPMENT_TEST_DEEP_MODEL", run["execution"]["model_spec"])
            response = await client.post(
                "/api/v1/query-library/generations",
                headers={"Idempotency-Key": uid},
                json={
                    "topic": "民用应急照明设备的可靠性与日常维护",
                    "count": 1,
                    "supplemental_information": "这是软件集成验收，仅生成一个简短研究问题，不涉及军事用途。",
                },
            )
            assert response.status_code == 202, response.text
            generation_id = response.json()["generation_id"]
            response = await client.post(
                f"/api/v1/runs/{run_id}/deep-sessions",
                headers={"Idempotency-Key": uid},
                json={
                    "title": "统一模型集成验收",
                    "capability_name": "民用应急照明设备",
                    "candidate": {"name": "民用应急照明设备", "description": "公共避难场所断电时提供照明"},
                },
            )
            assert response.status_code == 201, response.text
            session_id = response.json()["session"]["session_id"]
            response = await client.post(
                f"/api/v1/runs/{run_id}/deep-sessions/{session_id}/messages",
                headers={"Idempotency-Key": uid},
                json={
                    "content": "请分析该民用应急照明设备的维护可靠性问题，给出可验证的改进方向。无需生成画像或报告。",
                    "model_profile_id": deep_model,
                },
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job"]["job_id"]
            started = monotonic()
            deadline = started + float(os.getenv("EQUIPMENT_TEST_LIVE_TIMEOUT_SECONDS", "600"))
            last_progress = None
            while monotonic() < deadline:
                generation = (await client.get(f"/api/v1/query-library/generations/{generation_id}")).json()
                result_query_ids = generation.get("result_query_ids", [])
                job_response = await client.get(f"/api/v1/runs/{run_id}/deep-thinking/jobs/{job_id}")
                assert job_response.status_code == 200, job_response.text
                job = job_response.json().get("job", job_response.json())
                progress = (generation["status"], job["status"], job.get("phase"), job.get("stage"))
                if progress != last_progress:
                    print({"elapsed_seconds": round(monotonic() - started), "progress": progress}, flush=True)
                    last_progress = progress
                if generation["status"] in {"completed", "failed", "cancelled"} and job["status"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "partial",
                    "blocked",
                }:
                    break
                await asyncio.sleep(2)
            print(
                {
                    "query_status": generation["status"],
                    "deep_status": job["status"],
                    "model_spec": run["execution"]["model_spec"],
                }
            )
            assert generation["status"] == "completed", generation.get("error")
            assert result_query_ids
            assert generation["provider_snapshot"]["model_spec"] == run["execution"]["model_spec"]
            assert job["status"] == "completed", {
                "status": job["status"],
                "job_id": job_id,
                "elapsed_seconds": round(monotonic() - started),
                "phase": job.get("phase"),
                "stage": job.get("stage"),
            }
            session = (await client.get(f"/api/v1/runs/{run_id}/deep-sessions/{session_id}")).json()["session"]
            assert any(m.get("role") == "assistant" and m.get("content") for m in session.get("messages", [])), session
        finally:
            if generation_id:
                await client.post(f"/api/v1/query-library/generations/{generation_id}/cancel")
                generation = (await client.get(f"/api/v1/query-library/generations/{generation_id}")).json()
                for query_id in generation.get("result_query_ids", result_query_ids):
                    await client.delete(f"/api/v1/query-library/queries/{query_id}")
                await client.delete(f"/api/v1/query-library/generations/{generation_id}")
            if run_id:
                await client.delete(f"/api/v1/runs/{run_id}/permanent")
            async with pg_manager.get_async_session_context() as db:
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                    {"uid": uid},
                )
                await db.execute(delete(User).where(User.uid == uid))
                await db.commit()
    await pg_manager.close()
