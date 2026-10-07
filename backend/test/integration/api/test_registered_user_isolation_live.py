"""真实 HTTP 验证自助注册、超级管理员管理和注册用户数据隔离。"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Conversation, Department, OperationLog, Project, User
from platform_core.storage.postgres.models_equipment import (
    EquipmentDeepSession,
    EquipmentFavorite,
    EquipmentQuery,
    EquipmentResearchRun,
)
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_registered_users_are_managed_and_strictly_isolated():
    pg_manager.initialize()
    suffix = uuid4().hex[:8]
    root_uid = f"regroot_{suffix}"
    usernames = [f"rega_{suffix}", f"regb_{suffix}"]
    passwords = [f"RegisterA!{suffix}", f"RegisterB!{suffix}"]
    phone_suffix = str(int(suffix, 16) % 100_000_000).zfill(8)
    phones = ["137" + phone_suffix, "138" + phone_suffix]
    project_ids = [str(uuid4()), str(uuid4())]
    run_ids: list[str] = []
    query_ids: list[str] = []
    session_ids: list[str] = []
    favorite_ids: list[str] = []
    registered_uids: list[str] = []
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
            db.add(root)
            await db.flush()
            root_id = int(root.id)
            user_ids.append(root_id)
            root_headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(root_id)})}
            await db.commit()

        base_url = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
        async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
            config = await client.get("/api/auth/registration-config")
            assert config.status_code == 200, config.text
            assert config.json()["enabled"] is True
            assert department_id in {item["id"] for item in config.json()["departments"]}

            registration_payloads = []
            for username, password, phone in zip(usernames, passwords, phones):
                body = {"username": username, "password": password, "department_id": department_id}
                if phone:
                    body["phone_number"] = phone
                response = await client.post("/api/auth/register", json=body)
                assert response.status_code == 201, response.text
                registered = response.json()
                assert registered["role"] == "user"
                assert registered["department_id"] == department_id
                assert registered["access_token"]
                registration_payloads.append(registered)
                registered_uids.append(registered["uid"])
                user_ids.append(int(registered["user_id"]))

            response = await client.post(
                "/api/auth/register",
                json={
                    "username": f"inject_{suffix}",
                    "password": passwords[0],
                    "role": "superadmin",
                },
            )
            assert response.status_code == 422, response.text

            response = await client.post(
                "/api/auth/register",
                json={"username": usernames[0], "password": passwords[0]},
            )
            assert response.status_code == 409, response.text

            login_identifiers = [registered_uids[0], phones[1]]
            user_headers = []
            for identifier, password in zip(login_identifiers, passwords):
                response = await client.post(
                    "/api/auth/token",
                    data={"username": identifier, "password": password},
                )
                assert response.status_code == 200, response.text
                assert response.json()["role"] == "user"
                user_headers.append({"Authorization": "Bearer " + response.json()["access_token"]})

            for registered in registration_payloads:
                response = await client.get(
                    "/api/auth/users/page",
                    headers=root_headers,
                    params={"search": registered["uid"], "limit": 20},
                )
                assert response.status_code == 200, response.text
                assert int(registered["user_id"]) in {item["id"] for item in response.json()["items"]}
            assert (await client.get("/api/auth/users/page", headers=user_headers[0])).status_code == 403

            async with pg_manager.get_async_session_context() as db:
                for index, uid in enumerate(registered_uids):
                    db.add(
                        Project(
                            id=project_ids[index],
                            uid=uid,
                            name=f"注册用户隔离项目 {index}",
                            selection_status="selectable",
                            workdir_path=f"projects/{project_ids[index]}",
                            directory_mode="managed",
                        )
                    )
                await db.commit()

            for index, headers in enumerate(user_headers):
                response = await client.post(
                    "/api/equipment/runs",
                    headers=headers,
                    json={
                        "project_id": project_ids[index],
                        "topic": f"注册用户研究 {suffix} {index}",
                        "payload": {"source": "registered-user-isolation"},
                    },
                )
                assert response.status_code == 200, response.text
                run_ids.append(response.json()["run_id"])

                response = await client.post(
                    "/api/equipment/queries",
                    headers=headers,
                    json={
                        "project_id": project_ids[index],
                        "query": f"注册用户 Query {suffix} {index}",
                    },
                )
                assert response.status_code == 200, response.text
                query_ids.append(response.json()["query_id"])

                response = await client.post(
                    "/api/equipment/deep-thinking",
                    headers=headers,
                    json={
                        "project_id": project_ids[index],
                        "run_id": run_ids[index],
                        "title": f"注册用户深研 {index}",
                        "topic": f"隔离主题 {index}",
                    },
                )
                assert response.status_code == 200, response.text
                session_ids.append(response.json()["session_id"])

            async with pg_manager.get_async_session_context() as db:
                for index, uid in enumerate(registered_uids):
                    favorite_id = f"favorite-{uuid4()}"
                    favorite_ids.append(favorite_id)
                    db.add(
                        EquipmentFavorite(
                            id=favorite_id,
                            project_id=project_ids[index],
                            owner_uid=uid,
                            run_id=run_ids[index],
                            card_key=f"card-{index}",
                            snapshot={"name": f"个人收藏 {index}"},
                            display_name=f"个人收藏 {index}",
                            note="",
                            tags=[],
                        )
                    )
                await db.commit()

            for index, headers in enumerate(user_headers):
                other = 1 - index
                runs = await client.get("/api/equipment/runs", headers=headers)
                assert runs.status_code == 200, runs.text
                assert {item["run_id"] for item in runs.json()} == {run_ids[index]}
                assert (await client.get(f"/api/equipment/runs/{run_ids[other]}", headers=headers)).status_code == 404

                queries = await client.get("/api/equipment/queries", headers=headers)
                assert queries.status_code == 200, queries.text
                assert {item["query_id"] for item in queries.json()} == {query_ids[index]}
                assert (
                    await client.post(f"/api/equipment/queries/{query_ids[other]}/publish", headers=headers)
                ).status_code == 404

                sessions = await client.get("/api/equipment/deep-thinking", headers=headers)
                assert sessions.status_code == 200, sessions.text
                assert {item["session_id"] for item in sessions.json()} == {session_ids[index]}
                assert (
                    await client.get(f"/api/equipment/deep-thinking/{session_ids[other]}", headers=headers)
                ).status_code == 404

                favorites = await client.get("/api/equipment/favorites", headers=headers)
                assert favorites.status_code == 200, favorites.text
                assert {item["favorite_id"] for item in favorites.json()["items"]} == {favorite_ids[index]}
                assert (
                    await client.get(f"/api/equipment/favorites/{favorite_ids[other]}", headers=headers)
                ).status_code == 404

            assert set(run_ids) <= {
                item["run_id"] for item in (await client.get("/api/equipment/runs", headers=root_headers)).json()
            }
            assert set(query_ids) <= {
                item["query_id"] for item in (await client.get("/api/equipment/queries", headers=root_headers)).json()
            }
            assert set(session_ids) <= {
                item["session_id"]
                for item in (await client.get("/api/equipment/deep-thinking", headers=root_headers)).json()
            }
            assert set(favorite_ids) <= {
                item["favorite_id"]
                for item in (await client.get("/api/equipment/favorites", headers=root_headers)).json()["items"]
            }

            new_display_name = f"managed_{suffix}"
            response = await client.put(
                f"/api/auth/users/{registration_payloads[0]['user_id']}",
                headers=root_headers,
                json={"username": new_display_name},
            )
            assert response.status_code == 200, response.text
            assert response.json()["username"] == new_display_name
            me = await client.get("/api/auth/me", headers=user_headers[0])
            assert me.status_code == 200, me.text
            assert me.json()["username"] == new_display_name

            response = await client.delete(
                f"/api/auth/users/{registration_payloads[0]['user_id']}",
                headers=root_headers,
            )
            assert response.status_code == 200, response.text
            assert (await client.get("/api/auth/me", headers=user_headers[0])).status_code == 401
            assert (await client.get("/api/auth/me", headers=user_headers[1])).status_code == 200
    finally:
        async with pg_manager.get_async_session_context() as db:
            thread_ids = list(
                await db.scalars(
                    select(EquipmentDeepSession.payload).where(EquipmentDeepSession.project_id.in_(project_ids))
                )
            )
            normalized_thread_ids = {
                str(payload.get("thread_id") or "") for payload in thread_ids if isinstance(payload, dict)
            }
            await db.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.project_id.in_(project_ids)))
            await db.execute(delete(EquipmentFavorite).where(EquipmentFavorite.project_id.in_(project_ids)))
            await db.execute(delete(EquipmentQuery).where(EquipmentQuery.project_id.in_(project_ids)))
            await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.project_id.in_(project_ids)))
            if normalized_thread_ids:
                await db.execute(
                    text(
                        "DELETE FROM conversation_stats WHERE conversation_id IN "
                        "(SELECT id FROM conversations WHERE thread_id = ANY(:thread_ids))"
                    ),
                    {"thread_ids": list(normalized_thread_ids)},
                )
                await db.execute(delete(Conversation).where(Conversation.thread_id.in_(normalized_thread_ids)))
            await db.execute(delete(Project).where(Project.id.in_(project_ids)))
            current_user_ids = list(await db.scalars(select(User.id).where(User.uid.in_([root_uid, *registered_uids]))))
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(current_user_ids)))
            await db.execute(
                text("DELETE FROM platform_request_metrics WHERE uid = ANY(:uids)"),
                {"uids": [root_uid, *registered_uids]},
            )
            await db.execute(delete(User).where(User.id.in_(current_user_ids)))
            await db.commit()
        await pg_manager.close()
