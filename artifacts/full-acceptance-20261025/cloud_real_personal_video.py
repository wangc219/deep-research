"""本机真实微信视频采集，云端真实 ASR、Word、存储与入库验收。"""
import io,json,os,secrets,subprocess,sys,time,zipfile
from pathlib import Path
from uuid import uuid4
import httpx
from docx import Document

root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
private=json.loads(Path('/tmp/deepquest-browser-private-state.json').read_text())
base='/api/knowledge/wxchannels'
config_path=Path('/tmp/deepquest-video-private-state.json')
device='wxd_'+uuid4().hex;kb_id=None;collector=None;tasks=[]
os.umask(0o077)
with httpx.Client(base_url='http://127.0.0.1:18088',timeout=120) as client:
    auth=client.post('/api/auth/token',data={'username':private['uid'],'password':private['password']})
    auth.raise_for_status();client.headers['Authorization']='Bearer '+auth.json()['access_token']
    def req(method,path,**kw):
        response=client.request(method,path,**kw)
        response.raise_for_status();return response.json()
    def finish(task_id):
        tasks.append(task_id)
        for _ in range(360):
            task=req('GET',base+'/tasks/'+task_id)
            if task['status'] in {'success','failed','cancelled'}:
                assert task['status']=='success',task
                return task
            time.sleep(2)
        raise RuntimeError('真实采集任务超时')
    try:
        token=secrets.token_hex(32)
        req('POST',base+'/collector/devices',json={'device_id':device,'token':token,'name':'cloud real acceptance Mac','platform':'macos'})
        config_path.write_text(json.dumps({'platform_url':'http://127.0.0.1:18088','device_id':device,'token':token}))
        config_path.chmod(0o600)
        log=(out/'cloud-personal-collector.log').open('w')
        collector=subprocess.Popen([sys.executable,str(root/'backend/video_collector/collector.py'),'--config',str(config_path)],
                 env={**os.environ,'PYTHONPATH':str(root/'backend/package')+':'+str(root/'backend')},stdout=log,stderr=subprocess.STDOUT)
        for _ in range(45):
            devices=req('GET',base+'/collector/devices')['items']
            if any(d['device_id']==device and d.get('state',{}).get('channels_ready') for d in devices):break
            assert collector.poll() is None,'真实采集进程提前退出'
            time.sleep(2)
        else:raise RuntimeError('真实微信设备未就绪')
        source={'account':'央视新闻','max_pages':1,'collection_mode':'personal','device_id':device}
        discovered=req('POST',base+'/videos',json=source)
        task=finish(discovered['task_id']);videos=task['result']['videos']
        assert videos,videos
        chosen=next((v for v in videos if '腊' in v['title'] or '四季食单' in v['title']),videos[0])
        print(json.dumps({'real_cloud_discovery':True,'videos':len(videos),'selected_title':chosen['title']},ensure_ascii=False),flush=True)
        converted=req('POST',base+'/transcribe',json={**source,'video_oids':[chosen['oid']],'max_videos':1,'timeout_seconds':600})
        task=finish(converted['task_id']);result=task['result']
        assert result['completed_count']==1 and result.get('failed_count',0)==0,result
        word=client.get(base+f"/tasks/{converted['task_id']}/items/0/docx");word.raise_for_status()
        (out/'cloud-real-wechat-video.docx').write_bytes(word.content)
        doc=Document(io.BytesIO(word.content));text='\n'.join(p.text for p in doc.paragraphs)
        assert len(text)>120,text
        archive=client.get(base+f"/tasks/{converted['task_id']}/archive");archive.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:assert len(bundle.namelist())==1
        kb=req('POST','/api/knowledge/databases',json={'database_name':'pytest_cloud_real_video_'+uuid4().hex[:8],
            'kb_type':'milvus','description':'云端真实视频入库验收','embedding_model_spec':'siliconflow-cn:Pro/BAAI/bge-m3',
            'additional_params':{},'share_config':{'version':2,'read_scope':{'access_level':'user','user_uids':[private['uid']]},'manage_scope':None}})
        kb_id=kb['kb_id']
        imported=req('POST',base+f'/databases/{kb_id}/import',json={'task_id':converted['task_id'],'indexes':[0]})
        assert len(imported['file_ids'])==1,imported
        for _ in range(180):
            indexed=req('GET','/api/tasks/'+imported['task_id'])['task']
            if indexed['status'] in {'success','failed','cancelled'}:
                assert indexed['status']=='success',indexed
                break
            time.sleep(1)
        else:raise RuntimeError('真实文字稿入库超时')
        recalled=req('POST',f'/api/knowledge/databases/{kb_id}/query',json={'query':chosen['title'][:80],'meta':{'final_top_k':3,'similarity_threshold':0}})
        assert chosen['oid'] in json.dumps(recalled,ensure_ascii=False),recalled
        print(json.dumps({'cloud_real_video_passed':True,'cloud_asr':'passed','word_characters':len(text),
              'word_download':'passed','zip_download':'passed','knowledge_import':'passed','task_id':converted['task_id']},ensure_ascii=False),flush=True)
    finally:
        for tid in tasks:
            try:
                t=req('GET',base+'/tasks/'+tid)
                if t['status'] not in {'success','failed','cancelled'}:req('POST',base+'/tasks/'+tid+'/cancel')
            except Exception:pass
        if collector:
            collector.terminate()
            try:collector.wait(timeout=15)
            except subprocess.TimeoutExpired:collector.kill();collector.wait()
        req('DELETE',base+'/collector/devices/'+device)
        if kb_id:req('DELETE','/api/knowledge/databases/'+kb_id)
        config_path.unlink(missing_ok=True)
