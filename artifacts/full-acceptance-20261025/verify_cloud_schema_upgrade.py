"""仅在生产备份的隔离 PostgreSQL 副本上演练迁移，禁止连接线上库。"""

import asyncio
import json
import os

from sqlalchemy import text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage_migrations.v077_mcp_access import MCP_ACCESS_SCHEMA_STATEMENTS


async def main():
    """验证旧版实际数据保留、目标 schema 和重复执行幂等性。"""
    assert '@deepquest-acceptance-postgres-20261025:' in os.environ['POSTGRES_URL']
    pg_manager.initialize()
    try:
        async def counts():
            async with pg_manager.get_async_session_context() as db:
                result = {}
                for name in ('users', 'conversations', 'messages', 'agent_runs', 'tasks',
                             'knowledge_bases', 'knowledge_files', 'knowledge_chunks'):
                    result[name] = await db.scalar(text(f'SELECT count(*) FROM {name}'))
                legacy = {}
                for name in ('wechat_article_destinations', 'wechat_subscriptions', 'wechat_article_archives'):
                    exists = await db.scalar(text('SELECT to_regclass(:name)'), {'name': name})
                    legacy[name] = await db.scalar(text(f'SELECT count(*) FROM {name}')) if exists else 0
                old_tasks = await db.scalar(text("SELECT count(*) FROM tasks WHERE type IN ('wechat_article_ingest','wechat_account_discover')"))
                return result, legacy, old_tasks

        versions_before = await pg_manager.get_schema_versions()
        before, legacy, old_tasks = await counts()
        assert not any(legacy.values()) and not old_tasks, {
            'reason': '迁移会删除非空旧文章数据，必须先安排数据转换', 'legacy_counts': legacy,
            'legacy_tasks': old_tasks,
        }
        for _ in range(2):
            async with pg_manager.async_engine.begin() as connection:
                for statement in MCP_ACCESS_SCHEMA_STATEMENTS:
                    await connection.execute(text(statement))
            await pg_manager.upgrade_knowledge_schema_v3_to_v4()
            await pg_manager.upgrade_knowledge_schema_v5_to_v6()
            await pg_manager.record_schema_version('business', 14)
            await pg_manager.record_schema_version('knowledge', 6)
            after, _, _ = await counts()
            assert after == before, {'before': before, 'after': after}
        await pg_manager.require_current_schema()
        print(json.dumps({
            'schema_upgrade_rehearsal': 'passed', 'source': 'production_backup_isolated_clone',
            'versions_before': versions_before, 'versions_after': await pg_manager.get_schema_versions(),
            'business_and_knowledge_rows_preserved': before, 'legacy_article_counts': legacy,
            'idempotent_twice': True,
        }, ensure_ascii=False), flush=True)
    finally:
        await pg_manager.close()


asyncio.run(main())
