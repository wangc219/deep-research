"""撤下本轮专用验收账号的测试对话，保留研究报告及真实客户资料。"""

import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            count=await db.scalar(text("SELECT count(*) FROM conversations WHERE starts_with(uid,:prefix) AND status <> 'deleted'"),{'prefix':'acceptance_migration_20261026_'})
            await db.execute(text("UPDATE conversations SET status='deleted' WHERE starts_with(uid,:prefix) AND status <> 'deleted'"),{'prefix':'acceptance_migration_20261026_'})
            active=await db.scalar(text("SELECT count(*) FROM users WHERE starts_with(uid,:prefix) AND is_deleted=0"),{'prefix':'acceptance_migration_20261026_'})
            assert active==0,{'active_temporary_users':active}
            await db.commit()
        result={'test_conversations_hidden':count,'active_temporary_users':active,'customer_conversations_modified':0,'real_research_reports_retained':True}
        Path('/app/outputs/migration-20261026-test-cleanup.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally:
        await pg_manager.close()


asyncio.run(main())
