"""真实 PostgreSQL 与运行中 API 的跨用户隔离回归；仅创建和删除本测试的数据。"""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, OperationLog, User
from platform_core.storage_migrations.v073_enterprise import ENTERPRISE_SCHEMA_STATEMENTS
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_enterprise_real_http_isolation():
    pg_manager.initialize()
    suffix = uuid4().hex[:8]
    uids = [f"ent_{suffix}_{role}" for role in ("a", "b", "root")]
    run_ids, query_ids, favorite_ids, rule_ids = [], [], [], []
    session_ids = []
    tenant_ids, department_ids = [], []
    async with pg_manager.get_async_session_context() as db:
        # Existing data survives repeated additive migration.
        for _ in range(2):
            for statement in ENTERPRISE_SCHEMA_STATEMENTS:
                await db.execute(text(statement))
        department_id = await db.scalar(select(Department.id).limit(1))
        users = [
            User(
                uid=uid,
                username=uid,
                password_hash="disabled-test-login",
                department_id=department_id,
                role="superadmin" if i == 2 else "user",
            )
            for i, uid in enumerate(uids)
        ]
        db.add_all(users)
        await db.flush()
        headers = [{"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(u.id)})} for u in users]
        await db.commit()
    a, b, root = headers
    base = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
    async with httpx.AsyncClient(base_url=base, timeout=45) as client:
        try:
            response = await client.post(
                "/api/enterprise/tenants", headers=root, json={"name": f"隔离测试企业 {suffix}"}
            )
            assert response.status_code == 201, response.text
            tenant_id = response.json()["id"]
            tenant_ids.append(tenant_id)
            admin_uid = f"ent_{suffix}_dept"
            uids.append(admin_uid)
            response = await client.post(
                "/api/departments",
                headers=root,
                json={
                    "name": f"隔离测试部门 {suffix}",
                    "tenant_id": tenant_id,
                    "admin_uid": admin_uid,
                    "admin_password": uuid4().hex,
                },
            )
            assert response.status_code == 201, response.text
            department_ids.append(response.json()["id"])
            async with pg_manager.get_async_session_context() as db:
                admin_id = await db.scalar(select(User.id).where(User.uid == admin_uid))
            tenant_admin = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(admin_id)})}
            org = await client.get("/api/enterprise/organization", headers=tenant_admin)
            assert org.status_code == 200, org.text
            assert {t["id"] for t in org.json()["tenants"]} == {tenant_id}
            assert {u["uid"] for u in org.json()["users"]} == {admin_uid}
            response = await client.put(
                f"/api/enterprise/departments/{department_ids[0]}",
                headers=root,
                json={"tenant_id": tenant_id, "parent_id": department_id},
            )
            assert response.status_code == 422, response.text
            for path in (
                "/api/v1/runs",
                "/api/v1/query-library/queries",
                "/api/v1/favorites",
                "/api/v1/deep-sessions/history",
            ):
                assert (await client.get(path)).status_code == 401
            for h in (a, b):
                response = await client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "same-key"},
                    json={
                        "topic": f"企业隔离回归 {suffix}",
                        "execution": {"mode": "fake"},
                        "tenant_id": "spoofed",
                        "workspace_id": "spoofed",
                    },
                )
                assert response.status_code == 201, response.text
                run_ids.append(response.json()["run_id"])
                response = await client.post(
                    "/api/v1/query-library/queries", headers=h, json={"query": f"同一企业隔离测试问题 {suffix}"}
                )
                assert response.status_code == 201, response.text
                query_ids.append(response.json()["query_id"])
            assert run_ids[0] != run_ids[1] and query_ids[0] != query_ids[1]
            draft = (await client.get(f"/api/v1/runs/{run_ids[0]}", headers=a)).json()
            response = await client.patch(
                f"/api/v1/runs/{run_ids[0]}",
                headers=a,
                json={
                    "topic": f"编辑草稿回归 {suffix}",
                    **{key: draft[key] for key in ("research_route", "selected_agent_ids", "max_rounds")},
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["execution"]["mode"] == "fake"
            response = await client.post(
                f"/api/v1/runs/{run_ids[0]}/start", headers={**a, "Idempotency-Key": "start-owned-fake"}
            )
            assert response.status_code == 200, response.text
            for _ in range(60):
                response = await client.get(f"/api/v1/runs/{run_ids[0]}", headers=a)
                state = response.json()["status"]
                if state in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(1)
            assert state == "completed", response.text
            for tail in ("/capabilities", "/report"):
                response = await client.get(f"/api/v1/runs/{run_ids[0]}{tail}", headers=a)
                assert response.status_code == 200, response.text
            for h, run_id in zip((a, b), run_ids):
                response = await client.post(
                    f"/api/v1/runs/{run_id}/deep-sessions",
                    headers={**h, "Idempotency-Key": "same-session"},
                    json={"title": f"个人深研 {suffix}"},
                )
                assert response.status_code == 201, response.text
                session_ids.append(response.json()["session"]["session_id"])
            for h, expected in ((a, {session_ids[0]}), (b, {session_ids[1]})):
                response = await client.get("/api/v1/deep-sessions/history", headers=h)
                assert response.status_code == 200, response.text
                assert {s["session_id"] for s in response.json()["items"]} == expected
            response = await client.get("/api/v1/deep-sessions/history", headers=root)
            assert set(session_ids) <= {s["session_id"] for s in response.json()["items"]}
            response = await client.post(
                f"/api/v1/runs/{run_ids[0]}/deep-sessions",
                headers={**root, "Idempotency-Key": "superadmin-managed-session"},
                json={"title": "超级管理员代管个人对话"},
            )
            assert response.status_code == 201, response.text
            assert response.json()["scope"]["workspace_id"] == uids[0]
            async with pg_manager.get_async_session_context() as db:
                root_user_id = await db.scalar(select(User.id).where(User.uid == uids[2]))
                audit_rows = list(
                    (
                        await db.execute(
                            select(OperationLog.details).where(OperationLog.user_id == root_user_id)
                        )
                    ).scalars()
                )
            audit_payloads = []
            for details in audit_rows:
                try:
                    audit_payloads.append(json.loads(details or "{}"))
                except (TypeError, ValueError):
                    continue
            assert any(
                item.get("audit_stage") == "attempt"
                and item.get("actor_uid") == uids[2]
                and item.get("path") == f"/api/v1/runs/{run_ids[0]}/deep-sessions"
                for item in audit_payloads
            )
            for path, data in (
                ("/api/v1/runs", {"execution": ["invalid"]}),
                ("/api/v1/query-library/generations", {"model_config": ["invalid"]}),
            ):
                assert (await client.post(path, headers=a, json=data)).status_code == 422
            forged = {
                **b,
                "X-Role": "admin",
                "X-User-ID": uids[0],
                "X-Tenant-ID": "default",
                "X-Workspace-ID": uids[0],
                "X-Authenticated-Roles": "admin",
                "X-Tenant-Cross-Scope": "true",
            }
            for tail in (
                "",
                "/capabilities",
                "/report",
                "/events",
                "/artifacts/report.md",
                "/deep-sessions",
                f"/deep-sessions/{session_ids[0]}",
                f"/deep-sessions/{session_ids[0]}/events",
            ):
                response = await client.get(f"/api/v1/runs/{run_ids[0]}{tail}", headers=forged)
                assert response.status_code == 404, (tail, response.text)
            for action in ("start", "stop", "resume"):
                assert (await client.post(f"/api/v1/runs/{run_ids[0]}/{action}", headers=forged)).status_code == 404
            response = await client.get("/api/v1/runs?limit=1", headers=b)
            assert response.status_code == 200, response.text
            assert response.json()["total"] == 1 and response.json()["items"][0]["run_id"] == run_ids[1]
            assert (await client.get(f"/api/v1/runs/{run_ids[0]}", headers=root)).status_code == 200
            assert (await client.get(f"/api/v1/query-library/queries/{query_ids[0]}", headers=b)).status_code == 404
            response = await client.get("/api/v1/query-library/queries?limit=1", headers=b)
            assert response.json()["total"] == 1
            assert (
                await client.patch(
                    f"/api/v1/query-library/queries/{query_ids[0]}",
                    headers=b,
                    json={"expected_version": 1, "query": "stolen"},
                )
            ).status_code == 404
            # Favorites use the same database and API as the embedded workbench.
            from equipment_deep_research.application.factory import build_application_service

            backend_root = Path(__file__).resolve().parents[3]
            workspace_root = backend_root.parent if backend_root.name == "backend" else backend_root
            shared_database_url = os.getenv(
                "ENTERPRISE_TEST_APP_DB",
                f"sqlite:///{workspace_root / 'outputs' / 'application.db'}",
            )
            repository = build_application_service(database_url=shared_database_url).repository
            for uid, run_id in zip(uids, run_ids):
                fav = repository.save_favorite(
                    scope="private", owner_id=uid, run_id=run_id, card_key="test", snapshot={"name": "隔离测试卡片"}
                )
                favorite_ids.append(fav["favorite_id"])
            response = await client.get("/api/v1/favorites?scope=global", headers=b)
            assert response.status_code == 200, response.text
            assert response.json()["total"] == 1
            assert response.json()["items"][0]["owner_id"] == uids[1]
            assert (await client.get(f"/api/v1/favorites/{favorite_ids[0]}", headers=forged)).status_code == 404
            assert (await client.get(f"/api/v1/favorites/{favorite_ids[0]}", headers=root)).status_code == 200
            # Explicit user rule immediately blocks both old and new endpoints.
            response = await client.put(
                "/api/enterprise/permissions",
                headers=root,
                json={
                    "tenant_id": "default",
                    "subject_type": "user",
                    "subject_id": uids[1],
                    "feature": "queries",
                    "can_read": True,
                    "can_write": False,
                },
            )
            assert response.status_code == 200, response.text
            rule_ids.append(response.json()["id"])
            assert (
                await client.post("/api/v1/query-library/queries", headers=b, json={"query": "denied"})
            ).status_code == 403
            assert (await client.post("/api/equipment/queries", headers=b, json={})).status_code == 403
            assert (await client.get("/api/v1/query-library/queries", headers=b)).status_code == 200
            response = await client.put(
                "/api/enterprise/permissions",
                headers=root,
                json={
                    "tenant_id": "default",
                    "subject_type": "user",
                    "subject_id": uids[1],
                    "feature": "queries",
                    "can_read": False,
                    "can_write": False,
                },
            )
            assert response.status_code == 200, response.text
            portal = await client.get("/api/equipment/portal", headers=b)
            assert portal.status_code == 200, portal.text
            assert portal.json()["recent_queries"] == [] and portal.json()["stats"]["queries"] == 0
            assert (await client.get("/api/enterprise/organization", headers=b)).status_code == 403
            monitoring = await client.get("/api/enterprise/monitoring", headers=root)
            assert monitoring.status_code == 200, monitoring.text
            assert monitoring.json()["totals"]["requests"] > 0
            # Check cycle validation against PostgreSQL rather than an in-memory double.
            response = await client.put(
                f"/api/enterprise/departments/{department_id}",
                headers=root,
                json={"tenant_id": "default", "parent_id": department_id},
            )
            assert response.status_code == 422, response.text
        finally:
            for rule_id in rule_ids:
                await client.delete(f"/api/enterprise/permissions/{rule_id}", headers=root)
            for favorite_id in favorite_ids:
                await client.delete(f"/api/v1/favorites/{favorite_id}", headers=root)
            for query_id in query_ids:
                await client.delete(f"/api/v1/query-library/queries/{query_id}", headers=root)
            for run_id in run_ids:
                await client.delete(f"/api/v1/runs/{run_id}/permanent", headers=root)
            async with pg_manager.get_async_session_context() as db:
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid = ANY(:uids)"), {"uids": uids})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid = ANY(:uids))"),
                    {"uids": uids},
                )
                await db.execute(delete(User).where(User.uid.in_(uids)))
                await db.execute(delete(Department).where(Department.id.in_(department_ids)))
                for tenant_id in tenant_ids:
                    await db.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant_id})
                await db.commit()
    await pg_manager.close()
