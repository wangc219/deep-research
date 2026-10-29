"""公开科研主题最终网页验收，不保存业务记录。"""
import json
import time
from platform_core.agents.toolkits.buildin import tools as web
cases=[
    ("rare-new-name","Altermagnetism experimental spin splitting",[["altermagnetism","altermagnetic","altermagnets"]]),
    ("new-interdisciplinary","Moiré excitons semiconductor heterobilayers",[["moiré","moire"],["exciton","excitons","激子"]]),
    ("cross-disciplinary","Hydrodynamic electron flow in graphene",[["hydrodynamic","viscous"],["electron","electronic"],["graphene"]]),
]
for name,query,groups in cases:
    started=time.monotonic()
    result=web._resilient_web_search("open-websearch",{"query":query,"count":10,"required_term_groups":groups})
    print(json.dumps({"case":name,"query":query,"required_term_groups":groups,"status":result.get("status"),"seconds":round(time.monotonic()-started,2),"returned":len(result.get("results") or []),"distinct_domains":result.get("distinct_domains"),"filtered_irrelevant_count":result.get("filtered_irrelevant_count"),"attempted_providers":result.get("attempted_providers"),"results":result.get("results",[])},ensure_ascii=False),flush=True)
