"""真实 HTTP 验证超级管理员对个人研究资源的全局管理与强制审计。"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Conversation, Department, OperationLog, Project, User
from platform_core.storage.postgres.models_equipment import (
    EquipmentDeepSession,
    EquipmentQuery,
    EquipmentResearchRun,
)
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_superadmin_globally_manages_owner_resources_without_taking_ownership():
    """超级管理员可读写他人资源，普通用户仍严格 owner-only。"""

    pg_manager.initialize()
    marker = "superadmin_manage_" + uuid4().hex[:12]
    project_id = str(uuid4())
    uids = [marker + suffix for suffix in ("owner", "other", "root")]
    owner_uid, other_uid, root_uid = uids
    user_ids: list[int] = []
    run_id = query_id = parent_session_id = child_session_id = ""

    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            users = []
            for index, uid in enumerate(uids):
                user = User(
                    uid=uid,
                    username=uid,
                    password_hash="disabled-test-login",
                    role="superadmin" if index == 2 else "user",
                    department_id=department_id,
                )
                db.add(user)
                await db.flush()
                users.append(user)
                user_ids.append(int(user.id))
            db.add(
                Project(
                    id=project_id,
                    uid=owner_uid,
                    name=marker,
                    selection_status="selectable",
                    workdir_path="projects/" + project_id,
                    directory_mode="managed",
                )
            )
            await db.commit()

        owner, other, root = [
            {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)})}
            for user_id in user_ids
        ]
        base_url = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
        async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
            response = await client.post(
                "/api/equipment/runs",
                headers=root,
                json={"project_id": project_id, "topic": marker + " run", "payload": {"marker": marker}},
            )
            assert response.status_code == 200, response.text
            run = response.json()
            run_id = run["run_id"]
            assert run["owner_uid"] == owner_uid

            assert (await client.get(f"/api/equipment/runs/{run_id}", headers=owner)).status_code == 200
            assert (await client.get(f"/api/equipment/runs/{run_id}", headers=other)).status_code == 404
            assert (await client.get(f"/api/equipment/runs/{run_id}", headers=root)).status_code == 200
            assert run_id in {item["run_id"] for item in (await client.get("/api/equipment/runs", headers=root)).json()}
            assert run_id not in {
                item["run_id"] for item in (await client.get("/api/equipment/runs", headers=other)).json()
            }

            response = await client.patch(
                f"/api/equipment/runs/{run_id}",
                headers=root,
                json={"topic": marker + " updated", "payload": {"managed_by": root_uid}},
            )
            assert response.status_code == 200, response.text
            assert response.json()["owner_uid"] == owner_uid
            assert response.json()["topic"] == marker + " updated"

            response = await client.post(
                "/api/equipment/queries",
                headers=root,
                json={"project_id": project_id, "query": marker + " query"},
            )
            assert response.status_code == 200, response.text
            query = response.json()
            query_id = query["query_id"]
            assert query["owner_uid"] == owner_uid
            assert (await client.post(f"/api/equipment/queries/{query_id}/publish", headers=other)).status_code == 404
            response = await client.post(f"/api/equipment/queries/{query_id}/publish", headers=root)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "published"
            assert response.json()["owner_uid"] == owner_uid
            assert query_id in {
                item["query_id"] for item in (await client.get("/api/equipment/queries", headers=root)).json()
            }
            assert query_id not in {
                item["query_id"] for item in (await client.get("/api/equipment/queries", headers=other)).json()
            }

            response = await client.post(
                "/api/equipment/deep-thinking",
                headers=root,
                json={
                    "project_id": project_id,
                    "run_id": run_id,
                    "title": marker + " deep",
                    "topic": marker,
                },
            )
            assert response.status_code == 200, response.text
            parent = response.json()
            parent_session_id = parent["session_id"]
            assert parent["owner_uid"] == owner_uid
            assert (
                await client.get(f"/api/equipment/deep-thinking/{parent_session_id}", headers=owner)
            ).status_code == 200
            assert (
                await client.get(f"/api/equipment/deep-thinking/{parent_session_id}", headers=other)
            ).status_code == 404
            assert (
                await client.get(f"/api/equipment/deep-thinking/{parent_session_id}", headers=root)
            ).status_code == 200

            response = await client.post(
                f"/api/equipment/deep-thinking/{parent_session_id}/branches",
                headers=root,
                json={"title": marker + " branch"},
            )
            assert response.status_code == 200, response.text
            child = response.json()["session"]
            child_session_id = child["session_id"]
            assert child["owner_uid"] == owner_uid
            assert (
                await client.get(f"/api/equipment/deep-thinking/{child_session_id}", headers=owner)
            ).status_code == 200
            assert (
                await client.get(f"/api/equipment/deep-thinking/{child_session_id}", headers=other)
            ).status_code == 404

            response = await client.delete(f"/api/equipment/runs/{run_id}", headers=root)
            assert response.status_code == 200, response.text
            assert response.json() == {"deleted": True, "run_id": run_id}

        async with pg_manager.get_async_session_context() as db:
            assert await db.get(EquipmentResearchRun, run_id) is None
            stored_query = await db.get(EquipmentQuery, query_id)
            assert stored_query is not None and stored_query.owner_uid == owner_uid
            sessions = list(
                (
                    await db.scalars(
                        select(EquipmentDeepSession).where(
                            EquipmentDeepSession.id.in_([parent_session_id, child_session_id])
                        )
                    )
                ).all()
            )
            assert {item.owner_uid for item in sessions} == {owner_uid}
            assert {item.run_id for item in sessions} == {None}
            thread_ids = {str((item.payload or {}).get("thread_id") or "") for item in sessions}
            conversations = list(
                (await db.scalars(select(Conversation).where(Conversation.thread_id.in_(thread_ids)))).all()
            )
            assert len(conversations) == 2
            assert {item.uid for item in conversations} == {owner_uid}
            assert {item.project_id for item in conversations} == {project_id}

            logs = list(
                (
                    await db.scalars(
                        select(OperationLog)
                        .where(OperationLog.user_id == user_ids[2])
                        .order_by(OperationLog.id.asc())
                    )
                ).all()
            )
            details = [json.loads(item.details) for item in logs if item.details and item.details.startswith("{")]
            successes = [item for item in details if item.get("audit_stage") == "success"]
            attempts = [item for item in details if item.get("audit_stage") == "attempt"]
            expected_successes = {
                ("research_run", run_id, "create"),
                ("research_run", run_id, "update"),
                ("research_run", run_id, "delete"),
                ("query", query_id, "create"),
                ("query", query_id, "publish"),
                ("deep_session", parent_session_id, "create"),
                ("deep_session", child_session_id, "fork"),
            }
            actual_successes = {
                (item.get("resource_type"), item.get("resource_id"), item.get("action")) for item in successes
            }
            assert expected_successes <= actual_successes
            for item in successes:
                if (item.get("resource_type"), item.get("resource_id"), item.get("action")) in expected_successes:
                    assert item["actor_uid"] == root_uid
                    assert item["owner_uid"] == owner_uid
                    assert item["cross_user"] is True
            attempt_paths = {item.get("path") for item in attempts}
            assert {
                "/api/equipment/runs",
                f"/api/equipment/runs/{run_id}",
                "/api/equipment/queries",
                f"/api/equipment/queries/{query_id}/publish",
                "/api/equipment/deep-thinking",
                f"/api/equipment/deep-thinking/{parent_session_id}/branches",
            } <= attempt_paths
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.project_id == project_id))
            await db.execute(
                text(
                    "DELETE FROM conversation_stats WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE project_id=:project_id AND uid=:uid)"
                ),
                {"project_id": project_id, "uid": owner_uid},
            )
            await db.execute(
                delete(Conversation).where(
                    Conversation.project_id == project_id,
                    Conversation.uid == owner_uid,
                )
            )
            await db.execute(delete(EquipmentQuery).where(EquipmentQuery.project_id == project_id))
            await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.project_id == project_id))
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.execute(text("DELETE FROM platform_request_metrics WHERE uid = ANY(:uids)"), {"uids": uids})
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(user_ids)))
            await db.execute(delete(User).where(User.uid.in_(uids)))
            await db.commit()
        await pg_manager.close()
