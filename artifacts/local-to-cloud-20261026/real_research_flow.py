"""在云端以独立普通用户运行真实 Query 及完整研究报告，不用 fake 模型。"""
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
    """通过公开接口交付报告，并由模型计量表证明实际供应商调用。"""
    pg_manager.initialize()
    uid = 'research_acceptance_' + uuid4().hex[:12]
    run_id = generation_id = ''
    async with pg_manager.get_async_session_context() as db:
        department = await db.scalar(select(Department.id).limit(1))
        user = User(uid=uid, username=uid, password_hash='disabled-acceptance', role='user', department_id=department)
        db.add(user)
        await db.flush()
        token = AuthUtils.create_access_token({'sub':str(user.id)})
        await db.commit()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:5050', headers={'Authorization':'Bearer '+token}, timeout=90) as c:
        async def request(method, path, body=None):
            response = await c.request(method, path, json=body)
            assert response.status_code == 200, (path, response.status_code, response.text[:1600])
            return response.json()
        try:
            directory = 'acceptance-research-' + uuid4().hex[:10]
            await request('POST','/api/workspace/directory', {'parent_path':'/', 'name':directory})
            project = await request('POST','/api/projects', {'name':'本地整体迁移云端真实研究验收', 'request_id':uid,
                                      'workdir':{'mode':'linked','path':directory}})
            generation = await request('POST','/api/equipment/query-generations',{
                'project_id':project['id'], 'topic':'长期断电地下安置点自检电池应急灯自主续照研究',
                'count':1,'knowledge_enabled':False,
                'supplemental_information':'软件验收：只研究民用防灾设施，不涉及军事用途，区分事实与待验证假设。'})
            generation_id = generation['generation_id']
            run = await request('POST','/api/equipment/runs',{
                'project_id':project['id'], 'topic':'长期断电地下安置点的自检电池应急灯自主续照能力',
                'interaction_mode':'autonomous','execution_profile_id':'winning_swarm_dynamic_v2',
                'report_template_mode':'project_argument_v1','max_rounds':1,'knowledge_enabled':False,
                'supplemental_information':'这是软件真实验收。聚焦民用应急照明，提出维护便利性与可验证的改进方案。引用公开资料，标明证据不足；不得虚构实验数据。',
                'payload':{'analyst_confirmed':True}})
            run_id=run['run_id']
            assert run['payload']['execution'].get('mode','real') != 'fake' if 'execution' in run['payload'] else True
            await request('POST',f'/api/equipment/runs/{run_id}/start')
            print(json.dumps({'started':True,'run_id':run_id,'generation_id':generation_id,'owner_uid':uid}),flush=True)
            started=monotonic();last=None
            while monotonic()-started < 1500:
                run=await request('GET',f'/api/equipment/runs/{run_id}')
                generation=await request('GET',f'/api/equipment/query-generations/{generation_id}')
                state=(run['status'],generation['status'])
                if state != last:
                    print(json.dumps({'elapsed':round(monotonic()-started),'run':state[0],'query':state[1]},ensure_ascii=False),flush=True);last=state
                if run['status'] in {'completed','failed','cancelled','paused'} and generation['status'] in {'completed','failed','cancelled'}:break
                await asyncio.sleep(3)
            assert generation['status']=='completed',generation
            query_ids=generation.get('query_ids') or generation.get('payload',{}).get('query_ids') or []
            assert len(query_ids)==1,generation
            query=await request('GET',f'/api/equipment/queries/{query_ids[0]}')
            assert query['query'] and query['source_type']=='agent',query
            published=await request('POST',f'/api/equipment/queries/{query_ids[0]}/publish',{'expected_version':query['version']})
            assert published['status']=='published'
            assert run['status']=='completed',{'run_id':run_id,'status':run['status'],'payload':run.get('payload')}
            report=await c.get(f'/api/equipment/runs/{run_id}/report')
            assert report.status_code==200 and len(report.text)>1000,(report.status_code,report.text[:300])
            Path('/app/outputs/migration-20261026-real-research-report.md').write_text(report.text)
            capabilities=await request('GET',f'/api/equipment/runs/{run_id}/capability-versions')
            versions=capabilities['versions']
            formal=[row for row in versions if row.get('source')=='formal_s6']
            assert 5 <= len(formal) <= 6, {'formal_count':len(formal)}
            assert len({row['hypothesis_id'] for row in formal})==len(formal)
            async with pg_manager.get_async_session_context() as db:
                calls=(await db.execute(text('SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id=:id GROUP BY status'),{'id':run_id})).mappings().all()
                completed=sum(row['n'] for row in calls if row['status']=='completed')
                fallback=await db.scalar(text("SELECT count(*) FROM equipment_research_events WHERE run_id=:id AND payload::text LIKE '%winning_s5_portfolio_fallback_activated%'"),{'id':run_id})
                assert fallback==0,{'s5_fallback_events':fallback}
            assert completed>0, [dict(r) for r in calls]
            Path('/app/outputs/migration-20261026-research-result.json').write_text(json.dumps({'run_id':run_id,'query_id':query_ids[0],'report_characters':len(report.text),'capability_versions':len(versions),'formal_capabilities':len(formal),'completed_model_calls':completed,'model_call_outcomes':[dict(r) for r in calls],'s5_fallback_events':fallback},ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'real_research_passed':True,'run_id':run_id,'query_id':query_ids[0],
                       'report_characters':len(report.text),'capability_versions':len(versions),'completed_model_calls':completed,'s5_fallback_events':fallback},ensure_ascii=False),flush=True)
        finally:
            if run_id:
                current=await request('GET',f'/api/equipment/runs/{run_id}')
                if current['status'] not in {'completed','failed','cancelled','archived'}:
                    await request('POST',f'/api/equipment/runs/{run_id}/cancel')
            if generation_id:
                current=await request('GET',f'/api/equipment/query-generations/{generation_id}')
                if current['status'] not in {'completed','failed','cancelled'}:
                    await request('POST',f'/api/equipment/query-generations/{generation_id}/cancel')
            async with pg_manager.get_async_session_context() as db:
                await db.execute(update(User).where(User.uid==uid).values(is_deleted=1,password_hash='disabled-acceptance'))
                await db.commit()
    await pg_manager.close()

asyncio.run(main())
