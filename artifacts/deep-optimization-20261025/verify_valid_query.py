"""对明确设备能力需求做真实 Query 验收，不放宽领域校验。"""
import asyncio,json
from pathlib import Path
from time import monotonic
import httpx
from sqlalchemy import select
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun
from platform_core.utils.auth_utils import AuthUtils
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   run=await db.get(EquipmentResearchRun,'run-63cb44f5-53f4-4a04-a52f-6cfc17abd429')
   user=await db.scalar(select(User).where(User.uid==run.owner_uid))
   assert user.is_deleted==0
   token=AuthUtils.create_access_token({'sub':str(user.id)})
  async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',headers={'Authorization':'Bearer '+token},timeout=60,trust_env=False) as c:
   async def req(method,path,**kwargs):
    r=await c.request(method,path,**kwargs);assert r.status_code==200,(path,r.status_code,r.text[:500]);return r.json()
   job=await req('POST','/api/equipment/query-generations',json={'project_id':run.project_id,'topic':'地下避难场所民用应急照明设备：在持续断电与电池异常时自动保持照明并告警','count':1,'knowledge_enabled':False,'supplemental_information':'生成一项可研发的民用救援设备能力需求。聚焦可自检电池异常、自动切换电源并持续提供照明的实体装置，说明对象、场景、作用链和可检验设备能力。不要写管理规范、维护规程、组织流程或纯软件评价框架。仅用于软件功能验收，不涉及武器使用或攻击。'})
   start=monotonic();jid=job['generation_id']
   print(json.dumps({'generation_id':jid,'project_id':run.project_id}),flush=True)
   while monotonic()-start<300:
    job=await req('GET','/api/equipment/query-generations/'+jid)
    if job['status'] in {'completed','failed','cancelled'}:break
    await asyncio.sleep(1)
   assert job['status']=='completed',job.get('error')
   ids=job['query_ids'];assert len(ids)==1
   q=await req('GET','/api/equipment/queries/'+ids[0])
   published=await req('POST','/api/equipment/queries/'+ids[0]+'/publish',json={'expected_version':q['version']})
   assert published['status']=='published'
   result={'valid_query_generation':'passed','query_published':'passed','generation_id':jid,'query_id':ids[0],'query':q['query'],'seconds':round(monotonic()-start)}
   Path('/app/outputs/deep-optimization-20261025-valid-query.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
   print(json.dumps(result,ensure_ascii=False))
 finally:await pg_manager.close()
asyncio.run(main())
