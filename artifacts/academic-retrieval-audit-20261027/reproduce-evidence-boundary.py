"""只用虚构的通用论文元数据复现来源兼容边界，不调用外部服务。"""
import json
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from platform_core.agents.middlewares.academic_evidence import AcademicEvidenceMiddleware
base='https://doi.org/10.1000/audit-example'
other='https://example.org/audit-public-paper'
def call(name,identity,url):
 return [AIMessage('',tool_calls=[{'id':identity,'name':name,'args':{}}]),ToolMessage(json.dumps({'results':[{'id':identity,'title':'Synthetic audit fixture','url':url,'content_level':'abstract'}]}),tool_call_id=identity)]
def check(messages,url):
 result=AcademicEvidenceMiddleware().after_model({'messages':[HumanMessage('Synthetic citation compatibility audit'),*messages,AIMessage(f'<cite source="{url}" type="url">1</cite>')]},None)
 return 'correction_requested' if result else 'accepted_or_not_checked'
report={'exact_aminer_source':check(call('academic_search','a',base),base),
 'rewritten_url':check(call('academic_search','a',base),base+'/'),
 'mcp_source_with_aminer_results':check([*call('academic_search','a',base),*call('openalex_search_works','b',other)],other),
 'subagent_source_with_aminer_results':check([*call('academic_search','a',base),*call('subagent_await','b',other)],other),
 'mcp_only_without_aminer_results':check(call('openalex_search_works','b',other),other)}
assert report['exact_aminer_source']=='accepted_or_not_checked'
assert all(report[k]=='correction_requested' for k in ['rewritten_url','mcp_source_with_aminer_results','subagent_source_with_aminer_results'])
print(json.dumps(report,indent=2))
