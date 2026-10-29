"""两个普通用户真实运行完整研究与长音频转录；微信音频交接使用公开测试夹具。"""
import asyncio
import io
import json
import secrets
import shutil
import time
import wave
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select, delete, text, or_
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User, Department, Project, TaskRecord, OperationLog, AgentEnv, UserConfig
from platform_core.storage.postgres.models_knowledge import KnowledgeBase, VideoCollectorDevice, VideoCollectorCapture
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion
from platform_core.services.resource_budget import read_budget
from platform_core.services.wxchannels_service import video_owner_prefix
from platform_core.services.collection_artifact_service import manifest_directory
from platform_core.storage.minio.client import get_minio_client
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir
from test_wxchannels_live import test_personal_audio_to_docx_download_and_import

OUT = Path('/app/outputs/resource-governor-acceptance')
OUT.mkdir(parents=True, exist_ok=True)
rows = []
stop = asyncio.Event()
report = {'scope': 'Real full research pipeline and real 121-second SenseVoice/Word/MinIO/index flow; only WeChat audio handoff is a fixture.'}
run_id = kb_id = ''


async def request(row, method, path, **kwargs):
    response = await row['client'].request(method, path, **kwargs)
    assert response.status_code < 400, f'{method} {path}: HTTP {response.status_code}: {response.text[:250]}'
    return response


async def monitor():
    samples = []
    probes = []
    marked = False
    last = time.monotonic()
    while not stop.is_set():
        budget = read_budget() or {}
        samples.append(budget)
        if budget.get('asr_processes', 0) > 0 and not marked:
            (OUT/'asr-active.json').write_text(json.dumps({'asr_active':True}))
            print(json.dumps({'phase':'asr_model_process_active'}),flush=True)
            marked = True
        started = time.monotonic()
        try:
            response = await rows[0]['client'].get('/api/equipment/portal')
            probes.append({'status':response.status_code,'ms':round((time.monotonic()-started)*1000,1)})
        except httpx.HTTPError as error:
            probes.append({'error':type(error).__name__})
        if time.monotonic()-last >= 30:
            print(json.dumps({'phase':'mixed_load_sample','budget':budget}),flush=True)
            last = time.monotonic()
        try:await asyncio.wait_for(stop.wait(),timeout=2)
        except TimeoutError:pass
    report['budget_samples'] = samples
    report['page_probes'] = probes


async def research(row):
    global run_id
    started = time.monotonic()
    folder = 'qa-resource-' + uuid4().hex[:10]
    await request(row,'POST','/api/workspace/directory',json={'parent_path':'/','name':folder})
    project = (await request(row,'POST','/api/projects',json={'name':'资源调度真实研究验收','request_id':row['uid'],
        'workdir':{'mode':'linked','path':folder}})).json()
    run = (await request(row,'POST','/api/equipment/runs',json={
        'project_id':project['id'],'topic':'民用公共避难场所应急照明电池可靠性与维护改进',
        'interaction_mode':'autonomous','execution_profile_id':'winning_swarm_dynamic_v2',
        'report_template_mode':'project_argument_v1','max_rounds':1,'knowledge_enabled':False,
        'supplemental_information':'软件真实验收。聚焦民用应急照明的电池失效、漏检与维护便利性。引用真实公开资料；不得虚构实验数据，明确证据不足。',
        'payload':{'analyst_confirmed':True}})).json()
    run_id = run['run_id']
    report['research_run_id'] = run_id
    await request(row,'POST',f'/api/equipment/runs/{run_id}/start')
    print(json.dumps({'phase':'full_research_started','run_id':run_id}),flush=True)
    last = None
    while time.monotonic()-started < 1800:
        run = (await request(row,'GET',f'/api/equipment/runs/{run_id}')).json()
        state = (run['status'], run.get('stage'))
        if state != last:
            print(json.dumps({'phase':'research_progress','status':run['status'],'stage':run.get('stage'),'seconds':round(time.monotonic()-started,1)}),flush=True)
            last = state
        if run['status'] in {'completed','failed','cancelled','paused'}:break
        await asyncio.sleep(3)
    assert run['status']=='completed', f"Research ended as {run['status']}"
    document = await request(row,'GET',f'/api/equipment/runs/{run_id}/report')
    assert len(document.text)>1000
    (OUT/'research-report.md').write_text(document.text)
    capabilities = (await request(row,'GET',f'/api/equipment/runs/{run_id}/capability-versions')).json()
    capabilities = capabilities.get('versions', []) if isinstance(capabilities,dict) else capabilities
    assert capabilities
    async with pg_manager.get_async_session_context() as db:
        calls = [dict(item) for item in (await db.execute(text('SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id=:run GROUP BY status'),{'run':run_id})).mappings().all()]
        fallback = await db.scalar(text("SELECT count(*) FROM equipment_research_events WHERE run_id=:run AND payload::text LIKE '%winning_s5_portfolio_fallback_activated%'"),{'run':run_id})
    assert sum(item['n'] for item in calls if item['status']=='completed')>0
    assert fallback == 0, 'Research activated low-quality portfolio fallback'
    report['research'] = {'status':'passed','seconds':round(time.monotonic()-started,2),'report_characters':len(document.text),'capability_versions':len(capabilities),'model_calls':calls,'portfolio_fallback_events':fallback}
    print(json.dumps({'phase':'full_research_passed',**report['research']}),flush=True)


async def video(row, peer):
    global kb_id
    started = time.monotonic()
    async with pg_manager.get_async_session_context() as db:
        spec = await db.scalar(select(KnowledgeBase.embedding_model_spec).where(KnowledgeBase.embedding_model_spec.is_not(None)).limit(1))
    library = (await request(row,'POST','/api/knowledge/databases',json={'database_name':row['uid'],'description':'资源调度真实语音验收',
        'kb_type':'milvus','embedding_model_spec':spec or 'siliconflow-cn:Pro/BAAI/bge-m3','additional_params':{}})).json()
    kb_id = library['kb_id']
    report['knowledge_id'] = kb_id
    await test_personal_audio_to_docx_download_and_import(row['client'], dict(row['client'].headers), {'headers':dict(peer['client'].headers)}, {'kb_id':kb_id})
    report['video'] = {'status':'passed','seconds':round(time.monotonic()-started,2),'audio_seconds':report['audio_fixture_seconds'],
        'real_components':['HTTPS upload','ARQ','SenseVoice','punctuation','DOCX','MinIO','vector index'], 'fixture_component':'WeChat audio handoff only'}
    print(json.dumps({'phase':'video_docx_and_index_passed',**report['video']}),flush=True)


async def cleanup():
    errors=[]
    if len(rows) != 2:
        report['cleanup_errors'] = []
        for row in rows: await row['client'].aclose()
        return
    uids=[row['uid'] for row in rows]
    ids=[row['id'] for row in rows]
    try:
        if run_id:
            current=(await request(rows[0],'GET','/api/equipment/runs/'+run_id)).json()
            if current['status'] not in {'completed','failed','cancelled','draft','archived'}:
                await request(rows[0],'POST','/api/equipment/runs/'+run_id+'/cancel')
                for _ in range(90):
                    current=(await request(rows[0],'GET','/api/equipment/runs/'+run_id)).json()
                    if current['status'] in {'completed','failed','cancelled','archived'}:break
                    await asyncio.sleep(1)
            assert current['status'] in {'completed','failed','cancelled','draft','archived'}
        async with pg_manager.get_async_session_context() as db:
            conditions = [TaskRecord.payload['operator_id'].as_string().in_(uids)]
            if run_id: conditions.append(TaskRecord.payload['run_id'].as_string()==run_id)
            if kb_id: conditions.append(TaskRecord.payload['kb_id'].as_string()==kb_id)
            targets=(await db.scalars(select(TaskRecord).where(or_(*conditions)))).all()
            task_ids=[task.id for task in targets]
            report['task_outcomes']=[{'type':task.type,'status':task.status} for task in targets]
        for task in targets:
            if task.status not in {'success','failed','cancelled'}:
                row=rows[1] if task.payload.get('operator_id')==rows[1]['uid'] else rows[0]
                await request(row,'POST','/api/tasks/'+task.id+'/cancel')
                for _ in range(90):
                    state=(await request(row,'GET','/api/tasks/'+task.id)).json()['task']['status']
                    if state in {'success','failed','cancelled'}:break
                    await asyncio.sleep(1)
                assert state in {'success','failed','cancelled'},'Active task cannot be deleted'
        if kb_id:await request(rows[1],'DELETE','/api/knowledge/databases/'+kb_id)
        if run_id:await request(rows[0],'DELETE','/api/equipment/runs/'+run_id)
        storage=get_minio_client()
        prefix=video_owner_prefix(rows[1]['uid'])
        for item in list(storage.client.list_objects(storage.KB_BUCKETS['documents'],prefix=prefix,recursive=True)):
            storage.client.remove_object(storage.KB_BUCKETS['documents'],item.object_name)
        async with pg_manager.get_async_session_context() as db:
            users=(await db.scalars(select(User).where(User.id.in_(ids)).with_for_update())).all()
            assert len(users)==2 and all(user.uid in uids and user.uid.startswith(('qares_','qavid_')) and user.role=='user' for user in users)
            devices=(await db.scalars(select(VideoCollectorDevice.device_id).where(VideoCollectorDevice.owner_uid.in_(uids)))).all()
            await db.execute(delete(VideoCollectorCapture).where(VideoCollectorCapture.device_id.in_(devices)))
            await db.execute(delete(VideoCollectorDevice).where(VideoCollectorDevice.device_id.in_(devices)))
            await db.execute(delete(TaskRecord).where(TaskRecord.id.in_(task_ids)))
            await db.execute(delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.owner_uid.in_(uids)))
            await db.execute(delete(Project).where(Project.uid.in_(uids)))
            await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=:run'),{'run':run_id})
            await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=ANY(:uids)'),{'uids':uids})
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
            await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
            await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
        for uid in uids:
            folder=global_user_data_dir(uid)
            assert folder.name==uid
            if folder.exists():shutil.rmtree(folder)
            shutil.rmtree(manifest_directory(uid),ignore_errors=True)
        async with pg_manager.get_async_session_context() as db:
            report['accounts_remaining']=await db.scalar(text('SELECT count(*) FROM users WHERE id=ANY(:ids)'),{'ids':ids})
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    report['cleanup_errors']=errors
    for row in rows:await row['client'].aclose()


async def main():
    pg_manager.initialize()
    observer=None
    try:
        with wave.open('/tmp/governor-speech.wav') as source:
            params=source.getparams();audio=source.readframes(source.getnframes())
        target=Path('/app/test/fixtures/video_transcriber/speech.wav');target.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(target),'wb') as output:
            output.setparams(params);output.writeframes(audio*16)
        report['audio_fixture_seconds']=round(params.nframes*16/params.framerate,3)
        async with pg_manager.get_async_session_context() as db:
            department=await db.scalar(select(Department.id).limit(1))
            for prefix in ['qares_','qavid_']:
                uid=prefix+uuid4().hex[:12];password=secrets.token_urlsafe(24)
                user=User(uid=uid,username=uid,password_hash=AuthUtils.hash_password(password),role='user',department_id=department)
                db.add(user);await db.flush()
                rows.append({'id':user.id,'uid':uid,'password':password,'client':httpx.AsyncClient(base_url='https://www.deepquest.space',timeout=90,trust_env=False)})
        report['identity_ids']=[row['id'] for row in rows]
        for row in rows:
            response=await request(row,'POST','/api/auth/token',data={'username':row['uid'],'password':row.pop('password')})
            row['client'].headers['Authorization']='Bearer '+response.json()['access_token']
        observer=asyncio.create_task(monitor())
        results=await asyncio.gather(research(rows[0]),video(rows[1],rows[0]),return_exceptions=True)
        report['errors']=[type(error).__name__+': '+str(error) for error in results if isinstance(error,BaseException)]
    finally:
        stop.set()
        if observer:await asyncio.gather(observer,return_exceptions=True)
        await cleanup()
        (OUT/'heavy-mix-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'phase':'heavy_mix_finished','errors':report.get('errors'),'cleanup_errors':report['cleanup_errors'],'accounts_remaining':report.get('accounts_remaining')}),flush=True)
        await pg_manager.close()
    assert not report['errors'] and not report['cleanup_errors'] and report['accounts_remaining']==0


asyncio.run(main())
