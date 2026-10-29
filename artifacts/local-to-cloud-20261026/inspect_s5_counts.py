"""检查实际运行画像与动态策略数量，不输出证据正文或模型密钥。"""
import json,os
import psycopg
from psycopg.rows import dict_row

uri=os.environ['POSTGRES_URL'].replace('+asyncpg','').replace('+psycopg','')
run_id='run-ed464daf-f4af-4e2e-b008-bc0b9bbfeea8'
with psycopg.connect(uri,row_factory=dict_row) as db:
    run=db.execute('SELECT research_route,payload FROM equipment_research_runs WHERE id=%s',(run_id,)).fetchone()
    versions=db.execute('SELECT id,snapshot FROM equipment_capability_versions WHERE run_id=%s ORDER BY created_at',(run_id,)).fetchall()
def collect(obj,path=''):
    result=[]
    if isinstance(obj,dict):
        for key,value in obj.items():
            here=path+'/'+key
            if key in {'execution_profile_id','execution_profile','policy_id','finalist_minimum','finalist_maximum','candidate_count_contract','selected_candidate_ids','selected_hypothesis_ids'}:
                result.append({'path':here,'value':value})
            if key in {'concept_directions','capability_profiles','selected_candidates','finalists','candidates'} and isinstance(value,list):
                result.append({'path':here,'count':len(value)})
            if key not in {'messages','report','report_markdown','report_text','api_key'}:result.extend(collect(value,here))
    elif isinstance(obj,list):
        for i,value in enumerate(obj):result.extend(collect(value,path+'/'+str(i)))
    return result
print(json.dumps({'run_id':run_id,'research_route':run['research_route'],'count_configuration':collect(run['payload']),
 'versions':[{'id':v['id'],'keys':list(v['snapshot']),'identity':{k:v['snapshot'].get(k) for k in ('capability_id','name','version_no','source','hypothesis_id')},'nested_counts':collect(v['snapshot'])} for v in versions]},ensure_ascii=False))
