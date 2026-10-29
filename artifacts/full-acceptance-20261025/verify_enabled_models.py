"""逐一真实调用已启用模型，只保存脱敏状态和输出结构。"""
import asyncio, contextlib, json, logging, math, sys, time
from pathlib import Path
from platform_core.models.chat import select_model
from platform_core.models.embed import select_embedding_model
from platform_core.models.rerank import get_reranker
from platform_core.models.providers.service import get_all_model_providers, resolve_api_key
from platform_core.storage.postgres.manager import pg_manager
from platform_core.utils.logging_config import logger

async def probe(provider, model):
    key=resolve_api_key(provider)
    params=(model.get('extra') or {}).get('parameters',{})
    base=model.get('base_url_override') or provider.base_url
    kind=model['type']
    if kind=='chat':
        client=select_model(f"{provider.provider_id}:{model['id']}",model_params=params)
        result=await client.call([{'role':'user','content':'Reply with the single word READY.'}],stream=False)
        assert str(result.content or '').strip(),'empty_response'
        return {'response_nonempty':True}
    if kind=='embedding':
        client=select_embedding_model(f"{provider.provider_id}:{model['id']}")
        vectors=await client.aencode(['真实验收文档检索','应急照明电池状态监测'])
        assert len(vectors)==2 and all(v and all(math.isfinite(x) for x in v) for v in vectors)
        return {'vectors':2,'dimension':len(vectors[0])}
    client=get_reranker(f"{provider.provider_id}:{model['id']}")
    try:
        scores=await client._batch_rerank('应急照明电池',['应急照明电池监测','水果沙拉'],max_length=512)
        assert len(scores)==2 and all(math.isfinite(x) for x in scores)
        return {'scores':2}
    finally: await client.aclose()

async def main():
    pg_manager.initialize()
    results=[]
    try:
        async with pg_manager.get_async_session_context() as db: providers=await get_all_model_providers(db)
        for provider in providers:
            for model in provider.enabled_models or []:
                row={'provider':provider.provider_id,'model':model['id'],'type':model['type']}
                if provider.provider_id=='alibaba-cn':
                    row.update(status='deferred_by_user')
                else:
                    start=time.monotonic()
                    try:
                        with contextlib.redirect_stdout(sys.stderr):
                            detail=await asyncio.wait_for(probe(provider,model),timeout=90)
                        row.update(status='passed',**detail)
                    except Exception as exc:
                        status=getattr(exc,'status_code',None) or getattr(getattr(exc,'response',None),'status_code',None)
                        row.update(status='failed',exception_type=type(exc).__name__,http_status=status or (403 if '403' in str(exc) else None),
                                   upstream_model_disabled='model disabled' in str(exc).lower())
                    row['seconds']=round(time.monotonic()-start,2)
                results.append(row)
                print(json.dumps(row,ensure_ascii=False),flush=True)
        Path('/tmp/enabled-model-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    finally: await pg_manager.close()

logging.disable(logging.CRITICAL)
logger.remove()
asyncio.run(main())
