"""使用一次性测试身份验证已部署 Query API；不调用模型。"""
import asyncio
import json
from uuid import uuid4

import httpx
from sqlalchemy import delete, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, OperationLog, Project, User
from platform_core.storage.postgres.models_equipment import EquipmentQuery
from platform_core.utils.auth_utils import AuthUtils


async def main():
    marker = "query_check_" + uuid4().hex[:12]
    users = []
    try:
        async with pg_manager.get_async_session_context() as db:
            department = await db.scalar(select(Department.id).limit(1))
            for suffix in ("a", "b"):
                user = User(uid=marker + suffix, username=marker + suffix,
                            password_hash="disabled-validation-login", role="user", department_id=department)
                db.add(user)
                await db.flush()
                users.append(user)
        headers = [{"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(u.id)})} for u in users]
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=30) as client:
            created = await client.post("/api/equipment/queries", headers=headers[0], json={"query": marker + "通信终端研究"})
            assert created.status_code == 200, f"create: {created.status_code}"
            original = created.json()
            query_id = original["query_id"]
            assert (await client.get(f"/api/equipment/queries/{query_id}", headers=headers[1])).status_code == 404
            async with pg_manager.get_async_session_context() as db:
                row = await db.get(EquipmentQuery, query_id)
                row.legacy_source_id = marker
                row.import_batch_id = "workbench-sync"
            results = await asyncio.gather(*[
                client.patch(f"/api/equipment/queries/{query_id}", headers=headers[1],
                             json={"expected_version": 1, "supplemental_information": text})
                for text in ("并发验收甲", "并发验收乙")
            ])
            assert sorted(r.status_code for r in results) == [200, 409]
            current = (await client.get(f"/api/equipment/queries/{query_id}", headers=headers[1])).json()
            assert current["owner_uid"] == users[0].uid
            assert current["last_modified_by"] == users[1].uid
            assert current["payload"]["original_snapshot"]["version"] == 1
            assert not current["readonly"]
            assert (await client.post(f"/api/equipment/queries/{query_id}/publish", headers=headers[1], json={"expected_version": 2})).status_code == 200
            assert (await client.post(f"/api/equipment/queries/{query_id}/archive", headers=headers[1], json={"expected_version": 3})).status_code == 200
            assert (await client.delete(f"/api/equipment/queries/{query_id}?expected_version=3", headers=headers[1])).status_code == 409
            assert (await client.delete(f"/api/equipment/queries/{query_id}?expected_version=4", headers=headers[1])).status_code == 200
        print(json.dumps({"projectless_create": "passed", "private_isolation": "passed", "shared_history_crud": "passed",
                          "concurrent_version_conflict": "passed", "original_snapshot_and_actor": "passed", "stale_delete": "passed",
                          "paid_model_calls": 0}, ensure_ascii=False))
    finally:
        if users:
            async with pg_manager.get_async_session_context() as db:
                uids, ids = [u.uid for u in users], [u.id for u in users]
                await db.execute(delete(EquipmentQuery).where(EquipmentQuery.owner_uid.in_(uids)))
                await db.execute(delete(Project).where(Project.uid.in_(uids)))
                await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
                await db.execute(delete(User).where(User.uid.in_(uids)))


asyncio.run(main())
