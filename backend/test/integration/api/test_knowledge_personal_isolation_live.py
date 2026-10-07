"""真实 HTTP 验证个人/公共知识库可见性与超级管理员全局权限。"""

import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, OperationLog, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_personal_knowledge_base_visibility_and_superadmin_access():
    pg_manager.initialize()
    suffix = uuid4().hex[:8]
    uids = [f"kb_{suffix}_{role}" for role in ("owner", "other", "root")]
    kb_id = None
    async with pg_manager.get_async_session_context() as db:
        department_id = await db.scalar(select(Department.id).limit(1))
        users = [
            User(
                uid=uid,
                username=uid,
                password_hash="disabled-test-login",
                department_id=department_id,
                role="superadmin" if index == 2 else "user",
            )
            for index, uid in enumerate(uids)
        ]
        db.add_all(users)
        await db.flush()
        headers = [
            {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}
            for user in users
        ]
        await db.commit()

    owner, other, root = headers
    base_url = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
            response = await client.get("/api/knowledge/types", headers=owner)
            assert response.status_code == 200, response.text

            response = await client.post(
                "/api/knowledge/databases",
                headers=owner,
                json={
                    "database_name": f"pytest_personal_kb_{suffix}",
                    "description": "personal knowledge isolation",
                    "embedding_model_spec": "siliconflow-cn:Pro/BAAI/bge-m3",
                    "kb_type": "milvus",
                    "additional_params": {},
                    "share_config": {"version": 2, "read_scope": None, "manage_scope": None},
                },
            )
            assert response.status_code == 200, response.text
            database = response.json()
            kb_id = database["kb_id"]
            assert database["created_by"] == uids[0]
            assert database["share_config"] == {
                "version": 2,
                "read_scope": None,
                "manage_scope": None,
            }

            owner_rows = (await client.get("/api/knowledge/databases", headers=owner)).json()["databases"]
            owner_row = next(row for row in owner_rows if row["kb_id"] == kb_id)
            assert owner_row["can_manage"] is True

            other_rows = (await client.get("/api/knowledge/databases", headers=other)).json()["databases"]
            assert kb_id not in {row["kb_id"] for row in other_rows}
            root_rows = (await client.get("/api/knowledge/databases", headers=root)).json()["databases"]
            assert kb_id in {row["kb_id"] for row in root_rows}

            response = await client.put(
                f"/api/knowledge/databases/{kb_id}",
                headers=owner,
                json={
                    "name": database["name"],
                    "description": database["description"],
                    "share_config": {
                        "version": 2,
                        "read_scope": {"access_level": "global"},
                        "manage_scope": None,
                    },
                },
            )
            assert response.status_code == 403, response.text
    finally:
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
                if kb_id:
                    response = await client.delete(f"/api/knowledge/databases/{kb_id}", headers=root)
                    assert response.status_code == 200, response.text
        finally:
            async with pg_manager.get_async_session_context() as db:
                user_ids = list(await db.scalars(select(User.id).where(User.uid.in_(uids))))
                await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(user_ids)))
                await db.execute(delete(User).where(User.uid.in_(uids)))
                await db.commit()
            await pg_manager.close()
