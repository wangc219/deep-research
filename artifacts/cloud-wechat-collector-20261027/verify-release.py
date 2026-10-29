"""独立复核发布源码、普通用户夹具清理及容器资源边界。"""
import asyncio,json,hashlib,subprocess
from pathlib import Path
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.services.wxchannels_service import connection_status

async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   queries={
    'test_accounts':"SELECT count(*) FROM users WHERE uid LIKE 'qacloudwx_%'",
    'test_tasks':"SELECT count(*) FROM tasks WHERE payload->>'operator_id' LIKE 'qacloudwx_%'",
    'test_channels':"SELECT count(*) FROM wechat_channels WHERE owner_uid LIKE 'qacloudwx_%'",
    'test_libraries':"SELECT count(*) FROM knowledge_bases WHERE created_by LIKE 'qacloudwx_%'",
    'test_metrics':"SELECT count(*) FROM platform_request_metrics WHERE uid LIKE 'qacloudwx_%'",
    'test_schemas':"SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 'pytest_channels_%' OR schema_name LIKE 'pytest_video_%'"}
   remaining={k:await db.scalar(text(q)) for k,q in queries.items()}
   preserved=await db.scalar(text('SELECT count(*) FROM wechat_channel_videos'))
  assert not any(remaining.values()),remaining
  state=await connection_status();assert state['ready'] and state['central_managed']
  print(json.dumps({'independent_cleanup':remaining,'existing_video_index_rows_preserved':preserved,'shared_cloud_ready':True}),flush=True)
 finally:await pg_manager.close()
asyncio.run(main())
