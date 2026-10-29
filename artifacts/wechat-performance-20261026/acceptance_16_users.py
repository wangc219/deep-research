"""16 个真实普通账号的 HTTPS 并发、私有数据和文件交付验收；结束后清理全部夹具。"""
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import statistics
import time
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, text
from platform_core.services import collection_artifact_service as artifacts
from platform_core.services import wechat_mp_service as mp
from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, TaskRecord, User, OperationLog, AgentEnv, UserConfig
from platform_core.storage.postgres.models_knowledge import KnowledgeBase
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import user_workspace_dir

ORIGIN='https://www.deepquest.space'
OUT=Path('/app/outputs/wechat-16-users-20261026.json')
rows=[]
metrics=[]
report={'ordinary_accounts':16,'origin':ORIGIN}
semaphore=asyncio.Semaphore(48)

def timing(values):
    values=sorted(values)
    return {'count':len(values),'p50_ms':round(statistics.median(values)*1000,1),'p95_ms':round(values[min(len(values)-1,int(len(values)*.95))]*1000,1),'max_ms':round(max(values)*1000,1)}

async def request(row,method,path,expected=200,**kwargs):
    async with semaphore:
        started=time.monotonic()
        response=await row['client'].request(method,path,**kwargs)
        metrics.append({'path':path.split('?')[0],'seconds':time.monotonic()-started,'status':response.status_code})
    assert response.status_code==expected, f'{method} {path.split("?")[0]} returned {response.status_code}'
    return response

async def settled(*jobs):
    results = await asyncio.gather(*jobs, return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise RuntimeError('; '.join(type(error).__name__+': '+str(error) for error in errors))
    return results

async def clean_rows(targets):
    errors=[]
    # All HTTP phases are fully settled before deletion starts.
    for row in targets:
        if row.get('ingest_task_id'):
            for _ in range(60):
                response=await row['client'].get('/api/tasks/'+row['ingest_task_id'])
                if response.status_code==404 or response.json()['task']['status'] in {'success','failed','cancelled'}:break
                await row['client'].post('/api/tasks/'+row['ingest_task_id']+'/cancel')
                await asyncio.sleep(1)
            else:raise RuntimeError('Cannot clean an active ingest task')
        if row.get('kb_id'):
            response=await row['client'].delete('/api/knowledge/databases/'+row['kb_id'])
            if response.status_code!=200: errors.append('knowledge_library_'+str(response.status_code))
        if row.get('client'): await row['client'].aclose()
        key=mp.owner_key(row['uid'])
        directory=mp.owner_directory(key)
        pid=directory/'worker.pid'
        if pid.exists():
            number=int(pid.read_text())
            command=Path(f'/proc/{number}/cmdline')
            if command.exists() and b'platform_worker.py' in command.read_bytes():
                os.kill(number,signal.SIGTERM)
                for _ in range(50):
                    if not command.exists():break
                    await asyncio.sleep(.1)
        shutil.rmtree(directory,ignore_errors=True)
        shutil.rmtree(artifacts.manifest_directory(row['uid']),ignore_errors=True)
        shutil.rmtree(user_workspace_dir(row['uid']).parent,ignore_errors=True)
        sockets=Path(os.getenv('WECHAT_MP_SOCKET_ROOT','/tmp/platform-wechat-mp'))
        (sockets/(key[:32]+'.sock')).unlink(missing_ok=True)
        (sockets/(key+'.lock')).unlink(missing_ok=True)
    ids=[row['id'] for row in targets];uids=[row['uid'] for row in targets]
    async with pg_manager.get_async_session_context() as db:
        actual=(await db.scalars(select(User).where(User.id.in_(ids)).with_for_update())).all()
        assert all(user.uid in uids and user.uid.startswith('qa16_') and user.role=='user' for user in actual)
        await db.execute(delete(TaskRecord).where(TaskRecord.payload['operator_id'].as_string().in_(uids)))
        await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
        await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
        await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
        await db.execute(delete(User).where(User.id.in_(ids)))
    async with pg_manager.get_async_session_context() as db:
        queries={'accounts_remaining':select(User.id).where(User.uid.in_(uids)),
          'tasks_remaining':select(TaskRecord.id).where(TaskRecord.payload['operator_id'].as_string().in_(uids)),
          'libraries_remaining':select(KnowledgeBase.kb_id).where(KnowledgeBase.created_by.in_(uids)),
          'operation_logs_remaining':select(OperationLog.id).where(OperationLog.user_id.in_(ids)),
          'profiles_remaining':select(UserConfig.uid).where(UserConfig.uid.in_(uids)),
          'agent_env_remaining':select(AgentEnv.uid).where(AgentEnv.uid.in_(uids))}
        remaining={name:len((await db.scalars(query)).all()) for name,query in queries.items()}
    remaining['private_directories_remaining']=sum(mp.owner_directory(mp.owner_key(uid)).exists() or user_workspace_dir(uid).parent.exists() or artifacts.manifest_directory(uid).exists() for uid in uids)
    remaining['errors']=errors
    return remaining

async def main():
    pg_manager.initialize()
    batch=uuid4().hex[:6]
    try:
        async with pg_manager.get_async_session_context() as db:
            department=await db.scalar(select(Department.id).limit(1))
            spec=await db.scalar(select(KnowledgeBase.embedding_model_spec).where(KnowledgeBase.embedding_model_spec.is_not(None)).limit(1))
            for index in range(16):
                uid=f'qa16_{batch}_{index:02d}'
                password=secrets.token_urlsafe(24)
                user=User(uid=uid,username=uid,password_hash=AuthUtils.hash_password(password),role='user',department_id=department)
                db.add(user);await db.flush()
                rows.append({'uid':uid,'id':user.id,'password':password,'task_id':uuid4().hex,'marker':f'PRIVATE-{uid}',
                             'client':httpx.AsyncClient(base_url=ORIGIN,timeout=90,trust_env=False)})
            for row in rows:
                doc=video_docx_bytes(row['marker'],row['marker'])
                artifact=artifacts.publish_video(row['uid'],row['uid'],row['marker'],row['marker'],doc,row['uid'])
                row['artifact']=artifact
                db.add(TaskRecord(id=row['task_id'],name=row['marker'],type='wxchannels_transcribe',status='success',
                    payload={'operator_id':row['uid'],'account':row['uid']},result={'completed_count':1,'items':[{'index':0,'oid':row['uid'],'title':row['marker'],'text':row['marker'],'status':'completed','filename':'验收.docx'}]}))
                folder=mp.owner_directory(mp.register_owner(row['uid']))
                article=folder/'articles_full'/row['uid'];article.mkdir(parents=True)
                (article/'正文.md').write_text(row['marker'])
                (folder/'download_history.json').write_text(json.dumps([{'title':row['marker'],'account':row['uid'],'success':True,'path':str(article),'url':'https://mp.weixin.qq.com/s/qa16'}]))
                (folder/'accounts.json').write_text(json.dumps([{'fakeid':row['uid'],'nickname':row['marker']}]))
        print(json.dumps({'phase':'16_ordinary_accounts_created'}),flush=True)
        async def login(row):
            response=await request(row,'POST','/api/auth/token',data={'username':row['uid'],'password':row['password']})
            row['client'].headers['Authorization']='Bearer '+response.json()['access_token']
        await settled(*(login(row) for row in rows))
        report['real_password_logins']='16/16 passed'
        print(json.dumps({'phase':'16_real_logins_passed'}),flush=True)
        async def session(row):
            response=await request(row,'POST','/api/wechat-mp/session',json={})
            document=response.json()['document']
            assert 'nav-articles' in document
            row['asset']=re.search(r'src="(/api/wechat-mp/app/js/[^"?]+\?v=[a-f0-9]+)"',document)[1]
        await settled(*(session(row) for row in rows))
        report['isolated_mp_sessions']='16/16 passed'
        print(json.dumps({'phase':'16_mp_sessions_passed'}),flush=True)
        async def create_library(row):
            response=await request(row,'POST','/api/knowledge/databases',json={'database_name':row['uid'],'description':row['marker'],'kb_type':'milvus','embedding_model_spec':spec or 'siliconflow-cn:Pro/BAAI/bge-m3','additional_params':{}})
            row['kb_id']=response.json()['kb_id']
        await settled(*(create_library(row) for row in rows))
        all_kbs={row['kb_id'] for row in rows}
        report['private_knowledge_libraries']='16/16 created'
        print(json.dumps({'phase':'16_private_libraries_created'}),flush=True)
        started_index=len(metrics)
        async def verify(row):
            tasks=(await request(row,'GET','/api/knowledge/wxchannels/tasks')).json()['tasks']
            assert {task['id'] for task in tasks}=={row['task_id']}
            generic=(await request(row,'GET','/api/tasks')).json()
            assert {task['id'] for task in generic['tasks']}=={row['task_id']} and generic['summary']['total']==1
            history=(await request(row,'GET','/api/wechat-mp/app/api/articles/history')).json()['history']
            assert {item['title'] for item in history}=={row['marker']}
            accounts=(await request(row,'GET','/api/wechat-mp/app/api/accounts')).json()['accounts']
            assert {item['nickname'] for item in accounts}=={row['marker']}
            libraries=(await request(row,'GET','/api/knowledge/databases')).json()['databases']
            assert {library['kb_id'] for library in libraries}&all_kbs=={row['kb_id']}
            asset=await request(row,'GET',row['asset'])
            assert 'immutable' in asset.headers['cache-control']
        for _ in range(4):await settled(*(verify(row) for row in rows))
        warm=metrics[started_index:]
        report['warm_concurrent_requests']=timing([item['seconds'] for item in warm])
        report['warm_success_rate']='100%'
        assert report['warm_concurrent_requests']['p95_ms']<2000, 'Warm request p95 exceeds 2 seconds'
        print(json.dumps({'phase':'384_concurrent_requests_passed',**report['warm_concurrent_requests']}),flush=True)
        for index,row in enumerate(rows):
            peer=rows[(index+1)%16]
            await request(row,'GET',f"/api/knowledge/wxchannels/tasks/{peer['task_id']}",expected=404)
            await request(row,'GET',f"/api/tasks/{peer['task_id']}",expected=404)
            response=await row['client'].get('/api/workspace/file',params={'path':peer['artifact']['import_path']})
            assert response.status_code in {403,404}
            response=await row['client'].get(f"/api/knowledge/databases/{peer['kb_id']}")
            assert response.status_code in {403,404}
            response=await row['client'].get('/api/wechat-mp/app/api/articles/serve-file',params={'path':str(mp.owner_directory(mp.owner_key(peer['uid']))/'articles_full'/peer['uid']/'正文.md')})
            assert response.status_code==404
        report['cross_account_access']='80/80 rejected'
        async def files(row):
            content=(row['marker']+'\n').encode()*2048
            await request(row,'POST','/api/workspace/upload',data={'parent_path':row['artifact']['folder']},files=[('files',('验收上传.txt',content,'text/plain'))])
            downloaded=await request(row,'GET','/api/workspace/download',params={'path':row['artifact']['folder']+'/验收上传.txt'})
            assert downloaded.content==content
            word=await request(row,'GET',f"/api/knowledge/wxchannels/tasks/{row['task_id']}/items/0/docx")
            assert word.content.startswith(b'PK')
        await settled(*(files(row) for row in rows))
        report['parallel_upload_download_word']='16/16 passed'
        print(json.dumps({'phase':'16_file_deliveries_passed'}),flush=True)
        async def ingest(row):
            staged=(await request(row,'POST','/api/knowledge/files/import-workspace',json={'kb_id':row['kb_id'],'paths':[row['artifact']['import_path']]})).json()['items'][0]
            response=await request(row,'POST',f"/api/knowledge/databases/{row['kb_id']}/documents",json={'items':[staged['file_path']],'params':{'content_type':'file','auto_index':True,'content_hashes':{staged['file_path']:staged['content_hash']},'file_sizes':{staged['file_path']:staged['size']}}})
            row['ingest_task_id']=response.json()['task_id']
            started=time.monotonic()
            while time.monotonic()-started<240:
                task=(await request(row,'GET','/api/tasks/'+row['ingest_task_id'])).json()['task']
                if task['status'] in {'success','failed','cancelled'}:break
                await asyncio.sleep(1)
            assert task['status']=='success', 'knowledge ingest did not succeed: '+str(task.get('error') or task['status'])
            row['ingest_seconds']=time.monotonic()-started
            result=(await request(row,'POST',f"/api/knowledge/databases/{row['kb_id']}/query",json={'query':row['marker'],'meta':{'top_k':3,'score_threshold':0,'use_rerank':False}})).json()
            assert result.get('status')=='success' and row['marker'] in json.dumps(result,ensure_ascii=False), 'Own indexed document not retrieved'
        await settled(*(ingest(row) for row in rows))
        report['real_knowledge_ingest_and_retrieval']='16/16 passed'
        report['ingest_completion']=timing([row['ingest_seconds'] for row in rows])
        print(json.dumps({'phase':'16_real_ingest_and_retrieval_passed'}),flush=True)
        report['passed']=True
    except Exception as exc:
        report['passed']=False;report['error_type']=type(exc).__name__;report['error']=str(exc)
        print(json.dumps({'phase':'failed','error':str(exc)}),flush=True)
    finally:
        report['cleanup']=await clean_rows(rows)
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)
        await pg_manager.close()
        assert not report['cleanup']['errors'] and all(value==0 for key,value in report['cleanup'].items() if key!='errors')
        assert report.get('passed'), report.get('error')

if __name__ == '__main__':
    asyncio.run(main())
