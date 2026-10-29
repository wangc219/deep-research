import asyncio,json
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   remaining={}
   for name,sql in {
    'acceptance_accounts':"SELECT count(*) FROM users WHERE uid LIKE 'qachannel_%'",
    'acceptance_tasks':"SELECT count(*) FROM tasks WHERE payload->>'operator_id' LIKE 'qachannel_%'",
    'acceptance_channels':"SELECT count(*) FROM wechat_channels WHERE owner_uid LIKE 'qachannel_%'",
    'acceptance_devices':"SELECT count(*) FROM wechat_collector_devices WHERE owner_uid LIKE 'qachannel_%'",
    'acceptance_metrics':"SELECT count(*) FROM platform_request_metrics WHERE uid LIKE 'qachannel_%'",
    'isolated_test_schemas':"SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 'pytest_channels_%' OR schema_name LIKE 'pytest_video_%'"
   }.items():remaining[name]=await db.scalar(text(sql))
   assert not any(remaining.values()),remaining
   print(json.dumps({'remaining':remaining,'verified':True}))
 finally:await pg_manager.close()
asyncio.run(main())
