"""复验已完成的真实微信采集任务，不重复识别同一音频。"""
import io,json,time,zipfile
from pathlib import Path
from uuid import uuid4
import httpx
from docx import Document
private=json.loads(Path('/tmp/deepquest-browser-private-state.json').read_text())
out=Path(__file__).resolve().parent;base='/api/knowledge/wxchannels';kb=None
with httpx.Client(base_url='http://127.0.0.1:18088',timeout=120) as c:
    r=c.post('/api/auth/token',data={'username':private['uid'],'password':private['password']});r.raise_for_status()
    c.headers['Authorization']='Bearer '+r.json()['access_token']
    def req(method,path,**kwargs):
        r=c.request(method,path,**kwargs);r.raise_for_status();return r.json()
    completed=[t for t in req('GET',base+'/tasks')['tasks'] if t['status']=='success' and t['account']=='央视新闻' and t.get('result',{}).get('completed_count')==1]
    task=sorted(completed,key=lambda t:t['created_at'],reverse=True)[0]
    item=task['result']['items'][0];task_id=task['id']
    response=c.get(base+f'/tasks/{task_id}/items/0/docx');response.raise_for_status()
    (out/'cloud-real-wechat-video.docx').write_bytes(response.content)
    text='\n'.join(p.text for p in Document(io.BytesIO(response.content)).paragraphs)
    assert len(text)>120 and item['text'][:50] in text
    response=c.get(base+f'/tasks/{task_id}/archive');response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:assert len(archive.namelist())==1
    try:
        kb=req('POST','/api/knowledge/databases',json={'database_name':'pytest_cloud_real_video_'+uuid4().hex[:8],
            'kb_type':'milvus','description':'云端真实视频入库验收','embedding_model_spec':'siliconflow-cn:Pro/BAAI/bge-m3',
            'additional_params':{},'share_config':{'version':2,'read_scope':{'access_level':'user','user_uids':[private['uid']]},'manage_scope':None}})['kb_id']
        imported=req('POST',base+f'/databases/{kb}/import',json={'task_id':task_id,'indexes':[0]})
        assert len(imported['file_ids'])==1
        for _ in range(180):
            indexed=req('GET','/api/tasks/'+imported['task_id'])['task']
            if indexed['status'] in {'success','failed','cancelled'}:
                assert indexed['status']=='success',indexed
                break
            time.sleep(1)
        else:raise RuntimeError('视频文字稿入库未完成')
        recalled=req('POST',f'/api/knowledge/databases/{kb}/query',json={'query':item['title'][:80],'meta':{'final_top_k':3,'similarity_threshold':0}})
        assert item['oid'] in json.dumps(recalled,ensure_ascii=False),recalled
        assert item['text'][:50] in json.dumps(recalled,ensure_ascii=False),recalled
        print(json.dumps({'cloud_real_video_passed':True,'source_account':'央视新闻','source_title':item['title'],
            'task_id':task_id,'completed_count':1,'failed_count':0,'word_characters':len(text),'word_download':'passed',
            'zip_download':'passed','knowledge_index':'passed','real_vector_recall':'passed'},ensure_ascii=False))
    finally:
        if kb:req('DELETE','/api/knowledge/databases/'+kb)
