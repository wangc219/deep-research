"""只读核对指定失败轮次的引用URL和调用统计，不输出会话正文或凭据。"""
import asyncio,json
from html.parser import HTMLParser
from collections import Counter
from sqlalchemy import select,text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Message
class Citations(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.urls=[]
 def handle_starttag(self,tag,attrs):
  if tag=='cite':
   u=dict(attrs).get('source','')
   if u.startswith(('https://','http://')):self.urls.append(u)
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   counts=(await db.execute(text("SELECT endpoint,status,result->>'status' AS provider_status,count(*) AS calls,sum(CASE WHEN jsonb_array_length(COALESCE((result::jsonb)->'data','[]'::jsonb))=0 THEN 1 ELSE 0 END) AS empty_responses FROM academic_retrieval_calls WHERE root_run_id=:root GROUP BY endpoint,status,result->>'status' ORDER BY endpoint,status"),{'root':'f02c0fb9-e161-40a1-a68a-f1bc8fc587ff'})).mappings().all()
   messages=(await db.scalars(select(Message).where(Message.run_id=='6cfc640d-e4ee-407a-aa2b-43bdacb17642').order_by(Message.id))).all()
   tools={};allowed=set();answers=[];kinds=Counter();unparsed=[]
   for m in messages:
    kinds[(m.role,m.message_type)]+=1
    meta=m.extra_metadata or {}
    for call in meta.get('tool_calls',[]):tools[call.get('id')]=call.get('name')
    if m.role=='tool' or m.message_type=='tool_result':
     try:result=json.loads(m.content)
     except (ValueError,TypeError):unparsed.append({'metadata_keys':sorted(meta),'message_type':m.message_type});continue
     if isinstance(result,dict):
      for item in result.get('results') or []:
       if isinstance(item,dict) and isinstance(item.get('url'),str):allowed.add(item['url'])
    elif m.role in {'assistant','ai'}:
     parser=Citations();parser.feed(m.content)
     if parser.urls:answers.append(sorted(set(parser.urls)))
   print(json.dumps({'call_summary':[dict(r) for r in counts],'message_kinds':{str(k):v for k,v in kinds.items()},'tool_names':sorted(set(n for n in tools.values() if n)),'retrieved_source_urls':sorted(allowed),'answer_citations':answers,'unrecognized_tool_payload_shapes':unparsed},ensure_ascii=False))
 finally:await pg_manager.close()
asyncio.run(main())
