"""以公开通用学术概念比较AMiner字段检索，不记录论文内容或密钥。"""
import asyncio,json,time
from platform_core.config.options import aminer_api_opts
from platform_core.services.aminer_client import AMinerClient,AMinerError
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:config=await aminer_api_opts.get(db)
  client=AMinerClient(config)
  for field,term in [('keyword','machine learning'),('title','machine learning'),('keyword','graph neural network'),('title','graph neural network')]:
   begun=time.monotonic()
   try:
    r=await client.request('search',{'page':0,'size':5,field:term})
    result={'field':field,'term':term,'status':'ok','returned':len(r['data']),'total':r.get('total')}
   except AMinerError as e:result={'field':field,'term':term,'status':e.status}
   print(json.dumps({**result,'seconds':round(time.monotonic()-begun,3)}),flush=True)
 finally:await pg_manager.close()
asyncio.run(main())
