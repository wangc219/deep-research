"""16个普通账号使用真实云端微信；验证后仅删除本批账号和相关数据。"""
import asyncio,io,json,secrets,shutil,statistics,time,zipfile,hashlib
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import delete,func,select,text
from platform_core.services import wxchannels_service as service,collection_artifact_service as artifacts
from platform_core.knowledge.wxchannels import WxChannelsMCPClient
from platform_core.services.task_service import tasker
from platform_core.storage.minio.client import get_minio_client
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department,User,TaskRecord,OperationLog,UserConfig,AgentEnv
from platform_core.storage.postgres.models_knowledge import WechatChannel,WechatChannelVideo,VideoCollectorCapture,KnowledgeBase
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir,user_workspace_dir
from platform_core.services.run_queue_service import get_arq_pool

BASE='https://www.deepquest.space'; PREFIX='/api/knowledge/wxchannels'
rows=[];tasks=[];kb_id=None;metrics=[];cache_keys=[]
summary={'ordinary_accounts':16,'source':'Linux cloud WeChat','passed':False}
ledger=Path('/app/outputs/shared-cloud-acceptance-private.json')

def stamp(stage,**values):print(json.dumps({'stage':stage,**values},ensure_ascii=False),flush=True)

def save_ledger():
 ledger.write_text(json.dumps({'uids':[r['uid'] for r in rows],'ids':[r['id'] for r in rows],'tasks':tasks,'kb_id':kb_id}));ledger.chmod(0o600)

async def req(i,method,path,expected=200,**kwargs):
 begun=time.monotonic();response=await rows[i]['client'].request(method,path,**kwargs)
 metrics.append(time.monotonic()-begun)
 assert response.status_code==expected,f'{method} {path.split("?")[0]} HTTP {response.status_code}'
 return response

async def call(i,method,path,expected=200,**kwargs):return (await req(i,method,PREFIX+path,expected,**kwargs)).json()

async def finish(i,tid,timeout=900):
 begun=time.monotonic();last=None
 while time.monotonic()-begun<timeout:
  result=await call(i,'GET','/tasks/'+tid)
  phase=(result['status'],result['message'])
  if i==0 and phase!=last:stamp('task_progress',status=phase[0],message=phase[1]);last=phase
  if result['status'] in {'success','failed','cancelled'}:
   assert result['status']=='success',f'Cloud task {result["status"]}'
   return result,time.monotonic()-begun
  await asyncio.sleep(.6)
 raise AssertionError('Cloud task acceptance timed out')

async def settled(jobs):
 results=await asyncio.gather(*jobs,return_exceptions=True)
 errors=[str(r) for r in results if isinstance(r,BaseException)]
 assert not errors,errors
 return results

async def main():
 global kb_id
 pg_manager.initialize();storage=get_minio_client();started=time.monotonic();pool=await get_arq_pool()
 try:
  async with pg_manager.get_async_session_context() as db:
   dep=await db.scalar(select(Department.id).limit(1))
   spec=await db.scalar(select(KnowledgeBase.embedding_model_spec).where(KnowledgeBase.embedding_model_spec.is_not(None)).limit(1))
   batch=uuid4().hex[:8]
   for n in range(16):
    uid=f'qacloudwx_{batch}_{n:02d}';password=secrets.token_urlsafe(24)
    row=User(uid=uid,username=uid,password_hash=AuthUtils.hash_password(password),role='user',department_id=dep)
    db.add(row);await db.flush()
    rows.append({'uid':uid,'id':row.id,'password':password,'client':httpx.AsyncClient(base_url=BASE,trust_env=False,timeout=120)})
  save_ledger()
  async def login(i):
   auth=(await req(i,'POST','/api/auth/token',data={'username':rows[i]['uid'],'password':rows[i]['password']})).json()
   rows[i]['client'].headers['Authorization']='Bearer '+auth['access_token']
   state=await call(i,'GET','/status')
   assert state['central_managed'] and state['ready'] and not state['devices']
  await settled([login(i) for i in range(16)]);stamp('ordinary_login',users=16,ready_without_devices=True)
  for account in ['火研所','央视新闻']:
   key='wxchannels:shared-feed:v1:'+hashlib.sha256((service.downloader_endpoint()+'|'+account).encode()).hexdigest()
   cache_keys.append(key);await pool.delete(key)
  ranges=[5,10,15,20,None]
  begun=time.monotonic()
  async def submit(i):
   result=await call(i,'POST','/videos',json={'account':'火研所','max_videos':ranges[i%5]})
   tid=result['task_id'];tasks.append(tid);rows[i]['discovery']=tid;return tid
  tids=await settled([submit(i) for i in range(16)]);save_ledger()
  results=await settled([finish(i,tid) for i,tid in enumerate(tids)])
  channels=[]
  for i,(task,seconds) in enumerate(results):
   result=task['result'];assert result['history_complete'] and result['total_count']>=567
   assert result['completed_count']==0
   assert len(result['videos'])==(ranges[i%5] or result['total_count'])
   items=(await call(i,'GET','/channels'))['items'];assert len(items)==1
   channels.append(items[0]['id']);assert items[0]['video_count']==result['total_count']
  assert len(set(channels))==16
  snapshot=json.loads(await pool.get(cache_keys[0]))
  assert set(snapshot)=={'fetched_at','history_complete','username','videos'}
  async with pg_manager.get_async_session_context() as db:
   records=(await db.scalars(select(TaskRecord).where(TaskRecord.id.in_(tids)))).all()
   assert all(r.payload['requested_at']<=snapshot['fetched_at'] for r in records)
  durations=sorted(v[1] for v in results)
  summary['discovery']={'concurrent_users':16,'source_videos':results[0][0]['result']['total_count'],'wall_seconds':round(time.monotonic()-begun,3),'p50_seconds':round(statistics.median(durations),3),'max_seconds':round(max(durations),3),'all_five_ranges_passed':True,'private_channel_ids':16,'snapshot_public_metadata_only':True}
  stamp('concurrent_discovery',**summary['discovery'])
  await settled([call(i,'GET',f'/channels/{channels[(i+1)%16]}/videos',expected=404) for i in range(16)])
  await settled([call(i,'DELETE',f'/channels/{channels[(i+1)%16]}',expected=404) for i in range(16)])
  await settled([call(i,'GET',f'/tasks/{tids[(i+1)%16]}',expected=404) for i in range(16)])
  # Explicit update issued after the snapshot must fetch again, preserving history.
  refresh=await call(0,'POST','/videos',json={'account':'火研所','max_videos':5})
  tasks.append(refresh['task_id']);save_ledger();updated,seconds=await finish(0,refresh['task_id'])
  next_snapshot=json.loads(await pool.get(cache_keys[0]));assert next_snapshot['fetched_at']>snapshot['fetched_at']
  assert updated['result']['channel_id']==channels[0] and updated['result']['new_count']==0
  summary['explicit_incremental_refresh_seconds']=round(seconds,3)
  # Select a short public video. Never log source URLs or transcript contents.
  async with WxChannelsMCPClient(timeout=90) as source:
   username=await service.resolve_username(source,'央视新闻');videos=await source.iter_account_videos(username,1)
   def duration(video):
    media=(video.raw or {}).get('objectDesc',{}).get('media') or [{}]
    return media[0].get('videoPlayLen') or media[0].get('duration') or 999999
   chosen=min(videos,key=duration)
  begun=time.monotonic()
  submitted=await call(0,'POST','/transcribe',expected=202,json={'account':'央视新闻','max_pages':1,'max_videos':1,'video_oids':[chosen.oid],'timeout_seconds':900})
  assert submitted['submitted'];tid=submitted['task_id'];tasks.append(tid);save_ledger()
  task,seconds=await finish(0,tid,timeout=1200);result=task['result']
  assert result['completed_count']==1 and result['failed_count']==0
  word=await req(0,'GET',PREFIX+f'/tasks/{tid}/items/0/docx')
  with zipfile.ZipFile(io.BytesIO(word.content)) as archive:
   xml=archive.read('word/document.xml').decode();assert len(result['items'][0]['text'])>20
  zipped=await req(0,'GET',PREFIX+f'/tasks/{tid}/archive')
  with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:assert len(archive.namelist())==1
  assert result['items'][0]['workspace_path']
  for i in range(1,16):
   await call(i,'GET',f'/tasks/{tid}',expected=404)
   await req(i,'GET',PREFIX+f'/tasks/{tid}/items/0/docx',expected=404)
   assert (await call(i,'GET','/tasks'))['tasks']==[]
  summary['transcription']={'real_cloud_audio':True,'asr_and_punctuation':True,'word_and_zip_download':True,'workspace_published':True,'characters':len(result['items'][0]['text']),'word_bytes':len(word.content),'elapsed_seconds':round(time.monotonic()-begun,3),'cross_user_document_blocked':15}
  stamp('real_transcription',**summary['transcription'])
  assert spec,'No configured embedding model for knowledge acceptance'
  kb=(await req(0,'POST','/api/knowledge/databases',json={'database_name':'qacloudwx_'+batch,'kb_type':'milvus','description':'temporary shared-cloud acceptance','embedding_model_spec':spec,'additional_params':{}})).json()
  kb_id=kb['kb_id'];save_ledger()
  imported=await call(0,'POST',f'/databases/{kb_id}/import',json={'task_id':tid,'indexes':[0]});tasks.append(imported['task_id']);save_ledger()
  for _ in range(300):
   state=(await req(0,'GET','/api/tasks/'+imported['task_id'])).json()['task']
   if state['status'] in {'success','failed','cancelled'}:assert state['status']=='success';break
   await asyncio.sleep(1)
  else:raise AssertionError('Knowledge indexing timeout')
  recalled=(await req(0,'POST',f'/api/knowledge/databases/{kb_id}/query',json={'query':chosen.title[:80],'meta':{'final_top_k':3,'similarity_threshold':0}})).json()
  assert chosen.oid in json.dumps(recalled,ensure_ascii=False)
  other=await rows[1]['client'].post(PREFIX+f'/databases/{kb_id}/import',json={'task_id':tid,'indexes':[0]});assert other.status_code in {403,404}
  summary.update(knowledge_import_and_retrieval=True,cross_user_read_delete_blocked=True,passed=True)
  stamp('knowledge_import',indexed=True,retrievable=True,private=True)
 finally:
  for tid in tasks:await tasker.cancel_task(tid)
  for _ in range(120):
   states=[await tasker.get_task(tid) for tid in tasks]
   if all(not t or t['status'] in {'success','failed','cancelled'} for t in states):break
   await asyncio.sleep(.5)
  assert all(not t or t['status'] in {'success','failed','cancelled'} for t in states),'Cannot delete active tasks'
  if kb_id:
   response=await rows[0]['client'].delete('/api/knowledge/databases/'+kb_id);assert response.status_code==200
  await asyncio.sleep(3)
  ids=[r['id'] for r in rows];uids=[r['uid'] for r in rows]
  async with pg_manager.get_async_session_context() as db:
   await db.execute(delete(VideoCollectorCapture).where(VideoCollectorCapture.task_id.in_(tasks)))
   await db.execute(delete(TaskRecord).where(TaskRecord.id.in_(tasks)))
   await db.execute(delete(WechatChannel).where(WechatChannel.owner_uid.in_(uids)))
   await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=ANY(:uids)'),{'uids':uids})
   await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
   await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
   await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
   await db.execute(delete(User).where(User.id.in_(ids)))
  for r in rows:
   uid=r['uid'];await r['client'].aclose()
   await storage.adelete_objects_by_prefix(storage.KB_BUCKETS['documents'],service.video_owner_prefix(uid))
   shutil.rmtree(global_user_data_dir(uid),ignore_errors=True)
   shutil.rmtree(user_workspace_dir(uid).parent,ignore_errors=True)
   shutil.rmtree(artifacts.manifest_directory(uid),ignore_errors=True)
  if kb_id:await storage.adelete_objects_by_prefix(storage.KB_BUCKETS['documents'],kb_id+'/')
  for key in cache_keys:await pool.delete(key)
  async for key in pool.scan_iter(match='arq:*'):
   if await pool.type(key)!=b'string':continue
   data=await pool.get(key)
   if data and any(s.encode() in data for s in tasks+uids):await pool.delete(key)
  async with pg_manager.get_async_session_context() as db:
   queries={'accounts':select(func.count()).select_from(User).where(User.id.in_(ids)),
    'tasks':select(func.count()).select_from(TaskRecord).where(TaskRecord.payload['operator_id'].as_string().in_(uids)),
    'channels':select(func.count()).select_from(WechatChannel).where(WechatChannel.owner_uid.in_(uids)),
    'libraries':select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.created_by.in_(uids)),
    'logs':select(func.count()).select_from(OperationLog).where(OperationLog.user_id.in_(ids)),
    'profiles':select(func.count()).select_from(UserConfig).where(UserConfig.uid.in_(uids)),
    'agent_env':select(func.count()).select_from(AgentEnv).where(AgentEnv.uid.in_(uids))}
   remaining={name:await db.scalar(query) for name,query in queries.items()}
   remaining['request_metrics']=await db.scalar(text('SELECT count(*) FROM platform_request_metrics WHERE uid=ANY(:uids)'),{'uids':uids})
  remaining['objects']=sum([len(await storage.alist_object_metadata(storage.KB_BUCKETS['documents'],service.video_owner_prefix(uid))) for uid in uids])
  remaining['directories']=sum(global_user_data_dir(uid).exists() or user_workspace_dir(uid).parent.exists() or artifacts.manifest_directory(uid).exists() for uid in uids)
  remaining['redis_payloads']=0
  async for key in pool.scan_iter(match='arq:*'):
   if await pool.type(key)!=b'string':continue
   data=await pool.get(key)
   if data and any(s.encode() in data for s in tasks+uids):remaining['redis_payloads']+=1
  summary['cleanup_remaining']=remaining;assert not any(remaining.values()),remaining
  ordered=sorted(metrics);summary['http']={'count':len(ordered),'p50_ms':round(statistics.median(ordered)*1000,1),'p95_ms':round(ordered[int(len(ordered)*.95)]*1000,1),'max_ms':round(max(ordered)*1000,1)}
  summary['elapsed_seconds']=round(time.monotonic()-started,3)
  Path('/app/outputs/shared-cloud-acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));stamp('final',**summary)
  ledger.unlink(missing_ok=True);await pg_manager.close()
asyncio.run(main())
