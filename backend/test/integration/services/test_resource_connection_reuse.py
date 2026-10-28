"""真实 PostgreSQL 单连接验证资源列表复用外层 Session 且保持用户权限。"""

import os
import sys
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from platform_core.agents.context import resolve_agent_resource_options
from platform_core.knowledge.manager import KnowledgeBaseManager
from platform_core.knowledge.factory import KnowledgeBaseFactory
from platform_core.knowledge.implementations.milvus import MilvusKB
from platform_core.storage.postgres.models_knowledge import KnowledgeBase
from platform_core.storage.postgres.manager import pg_manager


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resource_options_reuse_caller_connection_and_preserve_privacy(monkeypatch, tmp_path):
    schema = "pytest_resource_pool_" + uuid4().hex
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        connect_args={"server_settings": {"search_path": schema}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def owned_session():
        async with factory() as db:
            yield db

    monkeypatch.setattr(pg_manager, "get_async_session_context", owned_session)
    manager = KnowledgeBaseManager(str(tmp_path))
    monkeypatch.setitem(KnowledgeBaseFactory._kb_types, "milvus", MilvusKB)
    monkeypatch.setitem(sys.modules, "platform_core.knowledge.runtime", SimpleNamespace(knowledge_base=manager))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(KnowledgeBase.__table__.create)
        async with factory() as db:
            db.add(
                KnowledgeBase(
                    kb_id="owned",
                    name="Private",
                    kb_type="milvus",
                    created_by="owner",
                    share_config={
                        "version": 2,
                        "read_scope": {"access_level": "user", "user_uids": ["owner"], "department_ids": []},
                        "manage_scope": None,
                    },
                )
            )
            await db.commit()
            await db.execute(text("SELECT 1"))
            owner = {"uid": "owner", "role": "user", "department_id": None, "tenant_id": "default"}
            peer = {**owner, "uid": "peer"}
            assert [
                row["key"]
                for row in (await resolve_agent_resource_options({"knowledges"}, db=db, user=owner))["knowledges"]
            ] == ["owned"]
            assert (await resolve_agent_resource_options({"knowledges"}, db=db, user=peer))["knowledges"] == []
            assert db.in_transaction() and engine.sync_engine.pool.checkedout() == 1
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
