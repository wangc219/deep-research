"""公开科研长尾样本验收；不创建账户、对话或任务记录。"""
import asyncio
import json
import time
from platform_core.config.options import aminer_api_opts
from platform_core.services.aminer_client import AMinerClient, normalize_paper
from platform_core.storage.postgres.manager import pg_manager
from platform_core.agents.toolkits.buildin import tools as web

CASES = [
    {"name":"rare-new-name", "query":"Experimental evidence for altermagnetism and spin splitting", "term":"altermagnetism", "aliases":["altermagnetism", "交错磁性"]},
    {"name":"new-interdisciplinary", "query":"Moiré excitons in semiconductor heterobilayers", "term":"moiré excitons", "aliases":["moiré", "moire", "莫尔"]},
    {"name":"cross-disciplinary", "query":"Hydrodynamic electron flow in graphene", "term":"hydrodynamic electron flow", "aliases":["hydrodynamic", "viscous", "流体动力学"]},
]

async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            config=await aminer_api_opts.get(db)
        client=AMinerClient(config)
        for case in CASES:
            row={"case":case["name"],"query":case["query"]}
            for mode,payload in [
                ("search",{"keyword":case["term"],"page":0,"size":10}),
                ("title_search",{"title":case["term"],"page":1,"size":10}),
                ("semantic_search",{"query":case["query"],"query_type":"auto","any_terms":case["aliases"][:2],"sort":"relevance"}),
            ]:
                started=time.monotonic()
                try:
                    response=await client.request(mode,payload)
                    papers=[normalize_paper(item) for item in response["data"] if isinstance(item,dict)]
                    ids=[paper["id"] for paper in papers if paper["id"]]
                    if ids:
                        try:
                            info=await client.request("info",{"ids":ids})
                            enriched={paper["id"]:paper for item in info["data"] if isinstance(item,dict) for paper in [normalize_paper(item)]}
                            papers=[{**paper,**enriched.get(paper["id"],{})} for paper in papers]
                        except Exception as exc:
                            row[mode+"_enrichment_status"]=type(exc).__name__
                    matches=[paper for paper in papers if any(web._term_matches_text(alias,(paper["title"]+" "+paper["content"]).casefold()) for alias in case["aliases"])]
                    row[mode]={"status":"ok","seconds":round(time.monotonic()-started,2),"returned":len(papers),"identity_matches":len(matches),"total":response.get("total"),"samples":[{"title":p["title"],"url":p["url"],"content_level":p["content_level"],"excerpt":p["content"][:350]} for p in papers]}
                except Exception as exc:
                    row[mode]={"status":getattr(exc,"status",type(exc).__name__),"seconds":round(time.monotonic()-started,2)}
            print(json.dumps({"academic":row},ensure_ascii=False),flush=True)
        # 使用既有共享协调器限流；只读公开检索，不改供应商健康设置。
        for case in CASES:
            started=time.monotonic()
            response=await asyncio.to_thread(web._resilient_web_search,"open-websearch",{"query":case["query"],"count":10,"required_term_groups":[case["aliases"]]})
            print(json.dumps({"web":{"case":case["name"],"status":response.get("status"),"seconds":round(time.monotonic()-started,2),"returned":len(response.get("results") or []),"distinct_domains":response.get("distinct_domains"),"attempted_providers":response.get("attempted_providers"),"samples":[{key:item.get(key) for key in ("title","url","content","source_tier")} for item in response.get("results") or []]}},ensure_ascii=False),flush=True)
    finally:
        await pg_manager.close()

asyncio.run(main())
