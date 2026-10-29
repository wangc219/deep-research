"""生产 HTTPS + 真实 Worker 验收 12 个通用入库任务，结束后删除夹具。"""
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import statistics
import time
from uuid import uuid4
import httpx
from sqlalchemy import select,func,text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User,TaskRecord
from platform_core.storage.postgres.models_knowledge import KnowledgeBase,KnowledgeFile
from platform_core.utils.auth_utils import AuthUtils

COUNT=20
TOPICS=['海底电缆监测传感器','森林火险巡护无人机','电池应急照明自检','水库坝体位移观测','城市燃气管道检漏','野外太阳能供电设备','雨水积涝预警装置','海洋浮标通信终端','地震救援生命探测','桥梁结构应变监测','轨道交通温度巡检','风力发电叶片维护','农田灌溉土壤湿度监测','港口集装箱定位终端','高速公路边坡位移监测','冷链运输温度记录','建筑消防烟雾报警','饮用水管网压力检测','矿井通风安全测量','光伏电站电气巡检']
OUT=Path('/app/outputs/upgrade-20-tasks-20261027.json')
async def settled(jobs):
 result=await asyncio.gather(*jobs,return_exceptions=True)
 errors=[r for r in result if isinstance(r,BaseException)]
 if errors:raise RuntimeError('; '.join(str(e) for e in errors))
 return result
async def main():
 pg_manager.initialize();kb_id=None;task_ids=[];staged=[];stop=asyncio.Event();monitors=[];peak=0;connections=0;latencies=[]
 report={'count':COUNT,'scope':'20 个生产知识库解析、向量入库任务；使用当前管理员的私有临时知识库，不新增账户。'}
 async with pg_manager.get_async_session_context() as db:
  user=await db.scalar(select(User).where(User.username=='Hitsz504',User.is_deleted==0))
  model=await db.scalar(select(KnowledgeBase.embedding_model_spec).where(KnowledgeBase.embedding_model_spec.is_not(None)).limit(1))
 token=AuthUtils.create_access_token({'sub':str(user.id)},expires_delta=timedelta(minutes=10))
 async with httpx.AsyncClient(base_url='https://www.deepquest.space',headers={'Authorization':'Bearer '+token},timeout=90,trust_env=False) as client:
  async def call(method,path,**kwargs):
   r=await client.request(method,path,**kwargs);assert r.status_code==200,f'{method} {path} returned {r.status_code}';return r.json()
  async def monitor():
   nonlocal peak,connections
   tick=0
   while not stop.is_set():
    async with pg_manager.get_async_session_context() as db:
     count=await db.scalar(select(func.count()).select_from(TaskRecord).where(TaskRecord.payload['kb_id'].as_string()==kb_id,TaskRecord.status=='running'))
     peak=max(peak,count)
     if tick%10==0:connections=max(connections,await db.scalar(text('SELECT count(*) FROM pg_stat_activity')))
    tick+=1
    await asyncio.sleep(.1)
  async def probes():
   while not stop.is_set():
    start=time.monotonic();await call('GET','/api/dashboard/stats');latencies.append((time.monotonic()-start)*1000)
    ready=await call('GET','/api/system/ready');assert ready['status']=='ready'
    await asyncio.sleep(.5)
  try:
   marker='qa_capacity_'+uuid4().hex[:12];report['fixture_marker']=marker
   kb_id=(await call('POST','/api/knowledge/databases',json={'database_name':marker,'description':'可删除的并发验收资料','kb_type':'milvus','embedding_model_spec':model,'additional_params':{},'share_config':{'version':2,'read_scope':None,'manage_scope':None}}))['kb_id']
   report['kb_id']=kb_id
   async def upload(index,topic):
    body=(f'# {topic}\n\n验收标记 {marker}_{index:02d}\n\n'+(f'{topic}需要定期检查传感器状态、通信链路、电源余量及环境适应性。记录采样时间与现场条件，发现异常后复核测量结果并安排维护。\n'*10)).encode()
    item=await call('POST','/api/knowledge/files/upload',params={'kb_id':kb_id},files={'file':(f'capacity_{index:02d}.md',body,'text/markdown')})
    staged.append(item)
   await settled([upload(i,topic) for i,topic in enumerate(TOPICS)])
   monitors=[asyncio.create_task(monitor()),asyncio.create_task(probes())]
   started=time.monotonic()
   async def enqueue(item):
    result=await call('POST',f'/api/knowledge/databases/{kb_id}/documents',json={'items':[item['file_path']],'params':{'content_type':'file','auto_index':True,'content_hashes':{item['file_path']:item['content_hash']},'file_sizes':{item['file_path']:item['size']}}})
    task_ids.append(result['task_id'])
   await settled([enqueue(item) for item in staged])
   print(json.dumps({'phase':'20_real_ingest_tasks_submitted'}),flush=True)
   while time.monotonic()-started<180:
    async with pg_manager.get_async_session_context() as db:
     tasks=(await db.execute(select(TaskRecord.id,TaskRecord.status).where(TaskRecord.id.in_(task_ids)))).all()
    if len(tasks)==COUNT and all(r.status in {'success','failed','cancelled'} for r in tasks):break
    await asyncio.sleep(.2)
   assert len(tasks)==COUNT and all(r.status=='success' for r in tasks),'Real ingest tasks did not all succeed'
   report['completion_seconds']=round(time.monotonic()-started,2)
   async with pg_manager.get_async_session_context() as db:
    files=(await db.scalars(select(KnowledgeFile).where(KnowledgeFile.kb_id==kb_id))).all()
   assert len(files)==COUNT and all(f.status in {'indexed','done'} and f.chunk_count>0 for f in files),'Not all documents indexed'
   for i in (0,9,19):
    query=await call('POST',f'/api/knowledge/databases/{kb_id}/query',json={'query':TOPICS[i],'meta':{'top_k':3,'score_threshold':0,'use_rerank':False}})
    assert query['status']=='success' and f'{marker}_{i:02d}' in json.dumps(query,ensure_ascii=False),'Indexed document retrieval failed'
   report['tasks_successful']=COUNT;report['files_indexed']=COUNT;report['retrieval_probes_successful']=3;report['passed']=True
  except Exception as exc:
   report['passed']=False;report['error']=str(exc);print(json.dumps({'phase':'failed','error':str(exc)}),flush=True)
  finally:
   stop.set()
   monitor_results=await asyncio.gather(*monitors,return_exceptions=True)
   report['monitor_errors']=[type(r).__name__ for r in monitor_results if isinstance(r,BaseException)]
   report['peak_simultaneous_running']=peak;report['peak_postgres_connections']=connections
   if latencies:
    values=sorted(latencies);report['dashboard_under_load']={'requests':len(values),'p50_ms':round(statistics.median(values),1),'p95_ms':round(values[min(len(values)-1,int(len(values)*.95))],1),'max_ms':round(max(values),1)}
   # Do not delete active task facts or a knowledge library still being processed.
   for task_id in task_ids:
    task=(await call('GET','/api/tasks/'+task_id))['task']
    if task['status'] in {'pending','queued','running'}:await call('POST','/api/tasks/'+task_id+'/cancel')
   for _ in range(120):
    async with pg_manager.get_async_session_context() as db:
     active=await db.scalar(select(func.count()).select_from(TaskRecord).where(TaskRecord.id.in_(task_ids),TaskRecord.status.in_(['pending','queued','running'])))
    if not active:break
    await asyncio.sleep(.5)
   assert not active,'Active tasks prevent safe fixture cleanup'
   if kb_id:await call('DELETE','/api/knowledge/databases/'+kb_id)
   for task_id in task_ids:await call('DELETE','/api/tasks/'+task_id)
   async with pg_manager.get_async_session_context() as db:
    remaining={'tasks':await db.scalar(select(func.count()).select_from(TaskRecord).where(TaskRecord.id.in_(task_ids))), 'knowledge_libraries':await db.scalar(select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.kb_id==kb_id)), 'files':await db.scalar(select(func.count()).select_from(KnowledgeFile).where(KnowledgeFile.kb_id==kb_id))}
   report['cleanup_remaining']=remaining
   OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False),flush=True)
 await pg_manager.close()
 assert report.get('passed') and not report['monitor_errors'] and not any(report['cleanup_remaining'].values()),'Acceptance failed'
asyncio.run(main())
