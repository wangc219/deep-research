"""对最终阶段参数做真实供应商探针，核对正文、时限与 PostgreSQL 阶段归属。"""
import asyncio,json,time
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text
from equipment_deep_research.agents.provider import ResponsesAgentProvider
from equipment_deep_research.providers.openai_compatible import OpenAICompatibleProvider
from equipment_deep_research.providers.base import ModelMessage
from platform_core.models.providers.cache import model_cache
from platform_core.services.equipment_model_usage import create_equipment_call_observer
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize();probe_id='optimization-anchor-'+uuid4().hex[:12]
 try:
  info=model_cache.get_model_info('siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash');assert info
  observer=create_equipment_call_observer(provider_id='platform',model=info.model_id,base_url=info.base_url,api_key=info.api_key,isolation_key=probe_id)
  provider=OpenAICompatibleProvider(provider_id='platform',model=info.model_id,base_url=info.base_url,api_key=info.api_key,observer=observer,structured_mode='none')
  host=ResponsesAgentProvider(provider)
  host.configure_run_budget({'codex_concurrency':3,'wall_clock_deadlines_enabled':False,'maximum_model_calls':30,'maximum_model_calls_with_residuals':30})
  async def call(index):
   started=time.monotonic()
   content,_=await host._collect_stream(provider,[ModelMessage('system','你在整理已有来源入口。只写待核验的公开资料线索，不声称已经浏览或验证网络。'),ModelMessage('user','已有入口为 https://www.mem.gov.cn/ 。针对民用避难场所应急照明装置，列出两条需要核验的设备能力线索，明确区分假设与事实。100字内。')],{'max_output_tokens':900,'_provider_timeout_seconds':20,'_provider_retry_attempts':1},progress={'phase':'source_anchor_reasoning','run_id':probe_id,'agent_id':'anchor-probe-'+str(index)})
   assert content.strip()
   return {'nonempty_visible_output':True,'seconds':round(time.monotonic()-started,2)}
  outputs=await asyncio.wait_for(asyncio.gather(*(call(i) for i in range(3))),timeout=25)
  async with pg_manager.get_async_session_context() as db:
   rows=(await db.execute(text('SELECT phase,status FROM platform_model_calls WHERE run_id=:id'),{'id':probe_id})).mappings().all()
   assert len(rows)==3 and all(r['phase']=='source_anchor_reasoning' and r['status']=='completed' for r in rows),rows
  result={'real_source_anchor_phase_probe':'passed','calls':outputs,'phase_attribution':'passed','timeout_seconds':20,'original_bounded_timeout_retained':True}
  Path('/app/outputs/deep-optimization-20261025-anchor-phase-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
 finally:
  async with pg_manager.get_async_session_context() as db:
   await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=:id'),{'id':probe_id});await db.commit()
  await pg_manager.close()
asyncio.run(main())
