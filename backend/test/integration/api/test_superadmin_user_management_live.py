"""真实 HTTP 验证超级管理员的全局用户增删改查能力。"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, OperationLog, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_superadmin_user_crud_and_role_management():
    pg_manager.initialize()
    suffix = uuid4().hex[:8]
    root_uid = f"ucrud_{suffix}_root"
    ordinary_uid = f"ucrud_{suffix}_user"
    managed_uid = ""
    user_ids: list[int] = []

    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            assert department_id is not None
            root = User(
                uid=root_uid,
                username=root_uid,
                password_hash="disabled-test-login",
                role="superadmin",
                department_id=department_id,
            )
            ordinary = User(
                uid=ordinary_uid,
                username=ordinary_uid,
                password_hash="disabled-test-login",
                role="user",
                department_id=department_id,
            )
            db.add_all([root, ordinary])
            await db.flush()
            user_ids.extend([int(root.id), int(ordinary.id)])
            root_headers = {
                "Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(root.id)})
            }
            ordinary_headers = {
                "Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(ordinary.id)})
            }
            await db.commit()

        base_url = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
        create_username = f"crud_{suffix}"
        updated_username = f"edited_{suffix}"
        initial_password = f"Initial!{suffix}"
        updated_password = f"Updated!{suffix}"
        phone_number = "139" + str(int(suffix, 16) % 100_000_000).zfill(8)

        async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
            assert (await client.get("/api/auth/users/page", headers=ordinary_headers)).status_code == 403
            assert (
                await client.post(
                    "/api/auth/users",
                    headers=ordinary_headers,
                    json={"username": "blocked_user", "password": initial_password, "role": "user"},
                )
            ).status_code == 403

            response = await client.post(
                "/api/auth/users",
                headers=root_headers,
                json={
                    "username": create_username,
                    "password": initial_password,
                    "role": "user",
                    "department_id": department_id,
                },
            )
            assert response.status_code == 200, response.text
            created = response.json()
            managed_uid = created["uid"]
            managed_id = int(created["id"])
            user_ids.append(managed_id)
            assert created["role"] == "user"
            assert created["department_id"] == department_id

            response = await client.get(
                "/api/auth/users/page",
                headers=root_headers,
                params={"search": create_username, "limit": 20},
            )
            assert response.status_code == 200, response.text
            assert managed_id in {item["id"] for item in response.json()["items"]}

            response = await client.get(f"/api/auth/users/{managed_id}", headers=root_headers)
            assert response.status_code == 200, response.text
            assert response.json()["uid"] == managed_uid

            response = await client.put(
                f"/api/auth/users/{managed_id}",
                headers=root_headers,
                json={"role": "superadmin"},
            )
            assert response.status_code == 400, response.text

            assert (
                await client.put(
                    f"/api/auth/users/{managed_id}",
                    headers=ordinary_headers,
                    json={"username": "blocked_update"},
                )
            ).status_code == 403
            assert (
                await client.delete(f"/api/auth/users/{managed_id}", headers=ordinary_headers)
            ).status_code == 403

            response = await client.put(
                f"/api/auth/users/{managed_id}",
                headers=root_headers,
                json={
                    "username": updated_username,
                    "password": updated_password,
                    "phone_number": phone_number,
                    "role": "admin",
                },
            )
            assert response.status_code == 200, response.text
            updated = response.json()
            assert updated["username"] == updated_username
            assert updated["phone_number"] == phone_number
            assert updated["role"] == "admin"
            assert updated["uid"] == managed_uid

            response = await client.post(
                "/api/auth/token",
                data={"username": managed_uid, "password": updated_password},
            )
            assert response.status_code == 200, response.text
            managed_headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            assert response.json()["role"] == "admin"

            response = await client.delete(f"/api/auth/users/{managed_id}", headers=root_headers)
            assert response.status_code == 200, response.text
            assert response.json()["success"] is True
            assert (await client.get(f"/api/auth/users/{managed_id}", headers=root_headers)).status_code == 404
            assert (await client.get("/api/auth/me", headers=managed_headers)).status_code == 401
            assert (
                await client.delete(f"/api/auth/users/{user_ids[0]}", headers=root_headers)
            ).status_code == 400
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(user_ids)))
            await db.execute(
                text("DELETE FROM platform_request_metrics WHERE uid = ANY(:uids)"),
                {"uids": [root_uid, ordinary_uid, managed_uid] if managed_uid else [root_uid, ordinary_uid]},
            )
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        await pg_manager.close()
