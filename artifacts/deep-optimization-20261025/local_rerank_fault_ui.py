"""为真实本地页面建立独立故障注入样本，不修改用户原知识库或模型配置。"""
import asyncio,json,sys
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import select,update
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department,User
from platform_core.utils.auth_utils import AuthUtils
STATE=Path('/app/outputs/deep-optimization-20261025-ui-state.json')
async def main():
 pg_manager.initialize()
 state={}
 try:
  async with pg_manager.get_async_session_context() as db:
   if sys.argv[1] in {'cleanup','probe','recover'}:
    state=json.loads(STATE.read_text());user=await db.scalar(select(User).where(User.uid==state['uid']))
   else:
    await db.execute(update(User).where(User.uid.startswith('optimization_ui_')).values(is_deleted=1,password_hash='disabled-test-login'))
    uid='optimization_ui_'+uuid4().hex[:12]
    department=await db.scalar(select(Department.id).limit(1))
    user=User(uid=uid,username=uid,password_hash='disabled-test-login',role='superadmin',department_id=department)
    db.add(user);await db.flush();state['uid']=uid
   token=AuthUtils.create_access_token({'sub':str(user.id)})
   await db.commit()
  async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',headers={'Authorization':'Bearer '+token},timeout=60,trust_env=False) as client:
   async def req(method,path,**kwargs):
    r=await client.request(method,path,**kwargs);assert r.status_code==200,(path,r.status_code,r.text[:300]);return r.json()
   if sys.argv[1] in {'probe','recover'}:
    params={'use_reranker':True,'reranker_model':('siliconflow-cn:Pro/BAAI/bge-reranker-v2-m3' if sys.argv[1]=='recover' else 'optimization:unavailable'),'similarity_threshold':0,'final_top_k':3}
    if sys.argv[1]=='recover':await req('PUT','/api/knowledge/databases/'+state['kb_id']+'/query-params',json=params)
    results=await req('POST','/api/knowledge/databases/'+state['kb_id']+'/query-test',json={'query':'应急照明电池如何维护','meta':params})
    assert isinstance(results,list) and results and all(c.get('rerank_status')==('completed' if sys.argv[1]=='recover' else 'degraded') and (('rerank_score' in c)==(sys.argv[1]=='recover')) for c in results),results
    print(json.dumps({'ui_kb_id':state['kb_id'],'query_mode':sys.argv[1],'query_verification':'passed','vector_results_preserved':len(results)},ensure_ascii=False))
   elif sys.argv[1]=='cleanup':
    await req('DELETE','/api/knowledge/databases/'+state['kb_id'])
   else:
    kb=await req('POST','/api/knowledge/databases',json={'database_name':'本地优化验收_重排故障提示','description':'独立合成资料，用于检验故障时保留召回与明确提示。','kb_type':'milvus','embedding_model_spec':'siliconflow-cn:Pro/BAAI/bge-m3','additional_params':{},'share_config':{'version':2,'read_scope':{'access_level':'user','user_uids':[state['uid'],'Hitsz504']},'manage_scope':None}})
    state['kb_id']=kb['kb_id'];STATE.write_text(json.dumps(state));STATE.chmod(0o600)
    prefix='/api/knowledge/databases/'+state['kb_id']
    body='应急照明维护：每月检查电池和电缆，测试备用电源与照明时长。该记录仅用于本地软件故障验收，不代表真实产品参数。'
    upload=await req('POST','/api/knowledge/files/upload?kb_id='+state['kb_id'],files={'file':('optimization.txt',body.encode(),'text/plain')})
    added=await req('POST',prefix+'/documents/add',json={'items':[upload['file_path']],'params':{'content_hashes':{upload['file_path']:upload['content_hash']},'file_sizes':{upload['file_path']:upload['size']}}})
    fid=added['items'][0]['file_id']
    async def finish(task_id):
     for _ in range(180):
      task=(await req('GET','/api/tasks/'+task_id))['task']
      if task['status'] in {'success','failed','cancelled'}:assert task['status']=='success',task;return
      await asyncio.sleep(1)
     raise RuntimeError('test task timeout')
    await finish((await req('POST',prefix+'/documents/parse',json={'file_ids':[fid],'params':{}}))['task_id'])
    await finish((await req('POST',prefix+'/documents/index',json={'file_ids':[fid]}))['task_id'])
    params={'use_reranker':True,'reranker_model':'optimization:unavailable','similarity_threshold':0,'final_top_k':3}
    await req('PUT',prefix+'/query-params',json=params)
    results=await req('POST',prefix+'/query-test',json={'query':'应急照明电池如何维护','meta':params})
    assert results and all(c.get('rerank_status')=='degraded' and 'rerank_score' not in c for c in results),results
    print(json.dumps({'ui_kb_id':state['kb_id'],'query_mode':sys.argv[1],'query_verification':'passed','vector_results_preserved':len(results)},ensure_ascii=False))
  if sys.argv[1]=='cleanup':
   async with pg_manager.get_async_session_context() as db:
    await db.execute(update(User).where(User.uid==state['uid']).values(is_deleted=1,password_hash='disabled-test-login'));await db.commit()
   STATE.unlink();print('ui_fault_resources_retired=true')
 finally:await pg_manager.close()
asyncio.run(main())
