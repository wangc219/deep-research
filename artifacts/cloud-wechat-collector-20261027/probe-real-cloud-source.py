import asyncio,json,time
from sqlalchemy import select
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import WechatChannel
from platform_core.knowledge.wxchannels import WxChannelsMCPClient
from platform_core.services.wxchannels_service import resolve_username,connection_status

async def main():
 pg_manager.initialize()
 started=time.monotonic()
 try:
  state=await connection_status()
  print(json.dumps({'stage':'connection','ready':state['ready'],'wechat':state['wechat_available'],'proxy':state['proxy_ready']}),flush=True)
  async with pg_manager.get_async_session_context() as db:
   username=await db.scalar(select(WechatChannel.username).where(WechatChannel.account=='火研所').limit(1))
  assert username
  async with WxChannelsMCPClient(timeout=60) as client:
   videos=await client.iter_account_videos(username,1)
   assert videos
   print(json.dumps({'stage':'video_list','returned_videos':len(videos),'elapsed_seconds':round(time.monotonic()-started,3)}),flush=True)
   resolved=await resolve_username(client,'火研所')
   assert resolved==username
   print(json.dumps({'stage':'search','exact_match':True,'total_elapsed_seconds':round(time.monotonic()-started,3)}),flush=True)
 finally:await pg_manager.close()
asyncio.run(main())
