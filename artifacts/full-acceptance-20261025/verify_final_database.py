"""只读核对原数据、任务终态和本轮临时身份撤销。"""
import asyncio,json
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   expected={'users':6,'conversations':82,'messages':2142,'agent_runs':77,'tasks':10,'knowledge_bases':1,'knowledge_files':6,'knowledge_chunks':91}
   actual={}
   for table in expected:
    actual[table]=int(await db.scalar(text(f"SELECT count(*) FROM {table} WHERE created_at < TIMESTAMP '2026-10-25 09:30:00'")))
   assert actual==expected,actual
   users=int(await db.scalar(text("SELECT count(*) FROM users WHERE (uid LIKE 'browser_acceptance_%' OR uid LIKE 'research_acceptance_%' OR uid LIKE 'acceptance_20261025_%' OR uid LIKE 'persistence_acceptance_%') AND is_deleted=0")))
   assert users==0,users
   print(json.dumps({'original_data_counts':actual,'matches_precutover_backup':True,'active_browser_research_acceptance_identities':users}))
 finally:await pg_manager.close()
asyncio.run(main())
