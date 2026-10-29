"""真实模型生成与无项目参数的归属验收；使用独立临时用户和明确民用题目。"""

import asyncio
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4
import httpx
from sqlalchemy import select, update, text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils


async def main():
    pg_manager.initialize()
    uid='acceptance_migration_20261026_defaults_'+uuid4().hex[:8]
    project_id=run_id=session_id=generation_id=''
    try:
        async with pg_manager.get_async_session_context() as db:
            user=User(uid=uid, username=uid, password_hash='disabled-acceptance',role='user',department_id=await db.scalar(select(Department.id).limit(1)))
            db.add(user);await db.flush()
            token=AuthUtils.create_access_token({'sub':str(user.id)})
            await db.commit()
        async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',headers={'Authorization':'Bearer '+token},timeout=90) as client:
            async def call(method,path,body=None):
                r=await client.request(method,path,json=body)
                assert r.status_code==200,(path,r.status_code,r.text[:500])
                return r.json()
            try:
                initial=await call('GET','/api/projects')
                assert len(initial)==1 and initial[0]['uid']==uid
                project_id=initial[0]['id']
                created=await asyncio.gather(
                    call('POST','/api/equipment/runs',{'topic':'民用照明设备维护验收','knowledge_enabled':False,'payload':{'analyst_confirmed':True}}),
                    call('POST','/api/equipment/deep-thinking',{'title':'合成默认工作台归属验收','topic':'民用照明资料','knowledge_enabled':False,'subagents_enabled':False}),
                    call('POST','/api/equipment/query-generations',{'topic':'偏远民用安置点自主应急照明供电终端持续运行能力研究','count':1,'knowledge_enabled':False,'supplemental_information':'软件真实验收。用户明确要求民用研究范围，仅生成一条自主应急照明供电系统的能力需求研究命题。说明长期断电约束、供电装备所需能力与验证边界，聚焦设备能力，避免转成维护规程，不涉及军事用途。'}))
                run,deep,generation=created
                run_id=run['run_id'];session_id=deep['session_id'];generation_id=generation['generation_id']
                assert run['project_id']==deep['project_id']==generation['project_id']==project_id
                started=monotonic()
                while monotonic()-started<300:
                    generation=await call('GET',f'/api/equipment/query-generations/{generation_id}')
                    if generation['status'] in {'completed','failed','cancelled'}:break
                    await asyncio.sleep(2)
                assert generation['status']=='completed',{'status':generation['status']}
                ids=generation.get('query_ids') or generation.get('payload',{}).get('query_ids') or []
                assert len(ids)==1
                query=await call('GET',f'/api/equipment/queries/{ids[0]}')
                assert query['source_type']=='agent' and query['query'] and query['project_id']==project_id
                async with pg_manager.get_async_session_context() as db:
                    calls=await db.scalar(text("SELECT count(*) FROM platform_model_calls WHERE run_id=:run AND status='completed'"),{'run':generation_id})
                    assert calls>0
                await call('PUT',f'/api/projects/{project_id}',{'name':'合成验收自定义工作台'})
                renamed=await call('POST','/api/projects/defaults/equipment')
                assert renamed['id']==project_id and renamed['name']=='合成验收自定义工作台'
                projects=await call('GET','/api/projects')
                assert len(projects)==1
                result={'default_project_created_on_entry':True,'run_deep_and_query_same_owned_project':True,'real_query_completed':True,'query_source':'agent','successful_model_calls':calls,'manual_project_rename_keeps_identity':True,'owned_projects':len(projects)}
                Path('/app/outputs/migration-20261026-final-default-project-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps(result,ensure_ascii=False))
            finally:
                if generation_id:
                    generation=await call('GET',f'/api/equipment/query-generations/{generation_id}')
                    if generation['status'] not in {'completed','failed','cancelled'}:await call('POST',f'/api/equipment/query-generations/{generation_id}/cancel')
                    for query_id in generation.get('query_ids') or generation.get('payload',{}).get('query_ids') or []:
                        current=await call('GET',f'/api/equipment/queries/{query_id}')
                        await call('DELETE',f'/api/equipment/queries/{query_id}?expected_version={current["version"]}')
                if session_id:await call('DELETE',f'/api/equipment/deep-thinking/{session_id}')
                if run_id:await call('DELETE',f'/api/equipment/runs/{run_id}')
                if project_id:await call('DELETE',f'/api/projects/{project_id}')
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(update(User).where(User.uid==uid).values(is_deleted=1,password_hash='disabled-acceptance'))
            await db.commit()
        await pg_manager.close()


asyncio.run(main())
