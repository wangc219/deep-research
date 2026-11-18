"""通过真实本地 HTTP、Worker 和 PostgreSQL 验收知识治理闭环。"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.storage.postgres.models_knowledge import KnowledgeBase
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _wait_task(test_client, headers: dict[str, str], task_id: str, *, attempts: int = 180) -> dict:
    for _ in range(attempts):
        response = await test_client.get(f"/api/tasks/{task_id}", headers=headers)
        assert response.status_code == 200, response.text
        task = response.json()["task"]
        if task["status"] in {"success", "failed", "cancelled"}:
            return task
        await asyncio.sleep(0.5)
    pytest.fail(f"本地任务 {task_id} 未在限定时间内结束")


async def test_real_governance_source_staging_ingest_and_brief_workflow(
    test_client,
) -> None:
    """分类、数据库来源、暂存审核、正式入库和采集更新简报形成真实闭环。"""
    suffix = uuid4().hex[:12]
    table_name = f"pytest_governance_source_{suffix}"
    root_id = child_id = source_id = subscription_id = kb_id = None
    database_url = make_url(os.environ["POSTGRES_URL"])

    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department).limit(1))
        uid = f"pytest_governance_admin_{suffix}"
        user = User(
            uid=uid,
            username=uid,
            password_hash="no-login",
            role="superadmin",
            department_id=department.id,
        )
        db.add(user)
        await db.flush()
        user_id = user.id
        embedding_spec = await db.scalar(
            select(KnowledgeBase.embedding_model_spec)
            .where(KnowledgeBase.embedding_model_spec.is_not(None))
            .limit(1)
        )
        await db.execute(
            text(
                f'CREATE TABLE "{table_name}" ('
                "id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, updated_at INTEGER NOT NULL)"
            )
        )
        await db.execute(
            text(
                f'INSERT INTO "{table_name}" (id, title, body, updated_at) '
                "VALUES (1, '无人集群协同试验', '本地固定证据：完成协同控制试验。', 1)"
            )
        )
    headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)})}

    try:
        root_response = await test_client.post(
            "/api/knowledge/categories",
            headers=headers,
            json={"name": f"pytest_前沿技术_{suffix}"},
        )
        assert root_response.status_code == 201, root_response.text
        root_id = root_response.json()["id"]

        child_response = await test_client.post(
            "/api/knowledge/categories",
            headers=headers,
            json={"name": "无人系统", "parent_id": root_id},
        )
        assert child_response.status_code == 201, child_response.text
        child_id = child_response.json()["id"]

        kb_response = await test_client.post(
            "/api/knowledge/databases",
            headers=headers,
            json={
                "database_name": f"pytest_governance_{suffix}",
                "description": "知识治理本地闭环验收",
                "embedding_model_spec": embedding_spec or "siliconflow-cn:Pro/BAAI/bge-m3",
                "kb_type": "milvus",
                "additional_params": {},
                "category_id": root_id,
            },
        )
        assert kb_response.status_code == 200, kb_response.text
        kb_id = kb_response.json()["kb_id"]
        assert kb_response.json()["category_id"] == root_id

        credential = {
            "host": database_url.host,
            "port": database_url.port or 5432,
            "database": database_url.database,
            "username": database_url.username,
            "password": database_url.password or "",
        }
        source_response = await test_client.post(
            "/api/knowledge/sources",
            headers=headers,
            json={
                "kb_id": kb_id,
                "category_id": child_id,
                "name": f"pytest_本地只读来源_{suffix}",
                "source_type": "postgresql",
                "config": {
                    "schema": "public",
                    "table": table_name,
                    "columns": ["id", "title", "body", "updated_at"],
                    "content_columns": ["body"],
                    "metadata_columns": ["updated_at"],
                    "title_column": "title",
                    "primary_key": "id",
                    "cursor_column": "updated_at",
                    "max_rows": 10,
                },
                "credential": credential,
                "notify_on_new": True,
            },
        )
        assert source_response.status_code == 201, source_response.text
        source_payload = source_response.json()
        source_id = source_payload["id"]
        assert source_payload["credential_configured"] is True
        assert "credential" not in source_payload
        assert {"host", "port", "database", "username", "password"}.isdisjoint(source_payload["config"])

        connection_test = await test_client.post(
            f"/api/knowledge/sources/{source_id}/test",
            headers=headers,
        )
        assert connection_test.status_code == 200, connection_test.text
        assert connection_test.json()["sample_count"] == 1

        subscription_response = await test_client.post(
            "/api/knowledge/brief-subscriptions",
            headers=headers,
            json={
                "name": f"pytest_无人前沿简报_{suffix}",
                "topics": ["无人系统", "反无人系统"],
                "keywords": ["集群", "协同"],
                "knowledge_ids": [kb_id],
                "source_ids": [source_id],
                "languages": ["zh-CN", "en"],
                "timezone": "Asia/Shanghai",
                "daily_enabled": True,
                "weekly_enabled": True,
                "daily_cron": "0 8 * * *",
                "weekly_cron": "0 9 * * 1",
                "reminder_sensitivity": "standard",
                "significance_threshold": 70,
            },
        )
        assert subscription_response.status_code == 201, subscription_response.text
        subscription_id = subscription_response.json()["id"]

        run_response = await test_client.post(
            f"/api/knowledge/sources/{source_id}/run",
            headers=headers,
        )
        assert run_response.status_code == 202, run_response.text
        source_task = await _wait_task(test_client, headers, run_response.json()["task_id"])
        assert source_task["status"] == "success", source_task

        staging_response = await test_client.get(
            "/api/knowledge/staging",
            headers=headers,
            params={"kb_id": kb_id, "review_status": "pending"},
        )
        assert staging_response.status_code == 200, staging_response.text
        staging = staging_response.json()
        assert staging["total"] == 1
        item = staging["items"][0]
        assert item["category_id"] == child_id
        assert item["version"] == 1
        assert item["knowledge_file_id"] is None

        briefs_response = await test_client.get(
            "/api/knowledge/briefs",
            headers=headers,
            params={"brief_type": "collection_update"},
        )
        assert briefs_response.status_code == 200, briefs_response.text
        brief_list = briefs_response.json()
        assert brief_list["unread_count"] >= 1
        brief = next(row for row in brief_list["items"] if row["subscription_id"] == subscription_id)
        detail_response = await test_client.get(
            f"/api/knowledge/briefs/{brief['id']}",
            headers=headers,
        )
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["sections"]["confirmed_facts"] == []
        assert detail["evidence"][0]["pending_review"] is True
        assert "审核通过前" in detail["summary"]

        review_response = await test_client.post(
            "/api/knowledge/staging/review",
            headers=headers,
            json={
                "kb_id": kb_id,
                "ids": [item["id"]],
                "decision": "approved",
                "note": "本地真实验收通过",
                "category_id": child_id,
            },
        )
        assert review_response.status_code == 200, review_response.text
        ingest_task_id = review_response.json()["items"][0]["task_id"]
        ingest_task = await _wait_task(test_client, headers, ingest_task_id)
        assert ingest_task["status"] == "success", ingest_task

        approved_response = await test_client.get(
            "/api/knowledge/staging",
            headers=headers,
            params={"kb_id": kb_id, "review_status": "approved"},
        )
        assert approved_response.status_code == 200, approved_response.text
        approved = next(row for row in approved_response.json()["items"] if row["id"] == item["id"])
        assert approved["knowledge_file_id"]
        assert approved["ingest_task_id"] == ingest_task_id

        kb_detail = await test_client.get(
            f"/api/knowledge/databases/{kb_id}",
            headers=headers,
            params={"include_files": True},
        )
        assert kb_detail.status_code == 200, kb_detail.text
        files = kb_detail.json()["files"]
        rows = files.values() if isinstance(files, dict) else files
        assert any(row["file_id"] == approved["knowledge_file_id"] for row in rows)
    finally:
        if subscription_id:
            await test_client.delete(
                f"/api/knowledge/brief-subscriptions/{subscription_id}",
                headers=headers,
            )
        if source_id:
            await test_client.delete(f"/api/knowledge/sources/{source_id}", headers=headers)
        if kb_id:
            await test_client.delete(f"/api/knowledge/databases/{kb_id}", headers=headers)
        if child_id:
            await test_client.delete(f"/api/knowledge/categories/{child_id}", headers=headers)
        if root_id:
            await test_client.delete(f"/api/knowledge/categories/{root_id}", headers=headers)
        async with pg_manager.get_async_session_context() as db:
            await db.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            await db.execute(update(User).where(User.id == user_id).values(is_deleted=1))
