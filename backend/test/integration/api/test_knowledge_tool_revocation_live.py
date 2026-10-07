"""真实 PostgreSQL 授权变更必须影响同一聊天运行时的后续工具调用。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from platform_core.agents.toolkits.kbs import tools
from platform_core.knowledge.runtime import knowledge_base
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_knowledge import KnowledgeBase

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("change", ["revoke", "delete_user", "disable_in_session"])
async def test_existing_runtime_cannot_reuse_revoked_knowledge(monkeypatch, change):
    """仅模拟向量检索，身份、资源授权和撤销提交均使用真实数据库。"""
    pg_manager.initialize()
    marker = "kb_acl_" + uuid4().hex[:12]
    sharing = {"version": 2, "read_scope": {"access_level": "user", "user_uids": [marker]}, "manage_scope": None}
    async with pg_manager.get_async_session_context() as db:
        db.add(User(uid=marker, username=marker, password_hash="disabled-test-login", role="user"))
        db.add(
            KnowledgeBase(
                kb_id=marker, name=marker, kb_type="milvus", created_by=marker + "_owner", share_config=sharing
            )
        )
        await db.commit()
    runtime = SimpleNamespace(context=SimpleNamespace(uid=marker, knowledges=[marker]))
    retrieve = AsyncMock(return_value={"results": ["authorized"]})
    monkeypatch.setattr(knowledge_base, "retrieve", retrieve)
    try:
        result = await tools.query_kb.coroutine(kb_id=marker, query_text="test", runtime=runtime)
        assert result == {"results": ["authorized"]}
        assert len(runtime.context._visible_knowledge_bases) == 1

        async with pg_manager.get_async_session_context() as db:
            if change == "revoke":
                await db.execute(
                    update(KnowledgeBase)
                    .where(KnowledgeBase.kb_id == marker)
                    .values(share_config={"version": 2, "read_scope": None, "manage_scope": None})
                )
            elif change == "delete_user":
                await db.execute(update(User).where(User.uid == marker).values(is_deleted=1))
            else:
                runtime.context.knowledges = []
            await db.commit()

        result = await tools.query_kb.coroutine(kb_id=marker, query_text="test", runtime=runtime)
        assert isinstance(result, str) and "无法获取" in result
        assert retrieve.await_count == 1, "撤销后不应检索或触发嵌入/重排费用"
        assert runtime.context._visible_knowledge_bases == []
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(KnowledgeBase).where(KnowledgeBase.kb_id == marker))
            await db.execute(delete(User).where(User.uid == marker))
            await db.commit()
        await pg_manager.close()
