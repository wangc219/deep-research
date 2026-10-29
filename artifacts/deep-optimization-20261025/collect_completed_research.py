"""独立核对实际研究终态、报告、画像和模型计量，不把 Query 的拒绝记录算通过。"""
import asyncio,json
from pathlib import Path
from sqlalchemy import select,text
import httpx
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun
from platform_core.utils.auth_utils import AuthUtils
async def main():
 pg_manager.initialize()
 try:
  state=json.loads(Path('/app/outputs/deep-optimization-20261025-ui-state.json').read_text())
  async with pg_manager.get_async_session_context() as db:
   run=await db.get(EquipmentResearchRun,'run-63cb44f5-53f4-4a04-a52f-6cfc17abd429')
   print(json.dumps({'observed_run_status':run.status}),flush=True)
   assert run.status=='completed',run.status
   user=await db.scalar(select(User).where(User.uid==state['uid']));assert user.role=='superadmin' and not user.is_deleted
   token=AuthUtils.create_access_token({'sub':str(user.id)})
   rows=(await db.execute(text('SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id=:id GROUP BY status'),{'id':run.id})).mappings().all()
   completed=sum(r['n'] for r in rows if r['status']=='completed')
   fallback=await db.scalar(text("SELECT count(*) FROM equipment_research_events WHERE run_id=:id AND payload::text LIKE '%winning_s5_portfolio_fallback_activated%'"),{'id':run.id})
   assert completed>0 and fallback==0
  async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',headers={'Authorization':'Bearer '+token},timeout=60,trust_env=False) as client:
   report=await client.get('/api/equipment/runs/'+run.id+'/report');assert report.status_code==200 and len(report.text)>1000
   versions=await client.get('/api/equipment/runs/'+run.id+'/capability-versions');assert versions.status_code==200 and versions.json()
   Path('/app/outputs/deep-optimization-20261025-real-research-report.md').write_text(report.text)
   valid_query=json.loads(Path('/app/outputs/deep-optimization-20261025-valid-query.json').read_text());assert valid_query['valid_query_generation']=='passed'
   result={'real_research_status':'completed','run_id':run.id,'report_characters':len(report.text),'capability_versions':len(versions.json()),'completed_model_calls':completed,'model_call_outcomes':[dict(r) for r in rows],'s5_fallback_events':fallback,'valid_equipment_query':valid_query,'initial_maintenance_query':'rejected_by_domain_validation_not_counted_as_passed'}
   Path('/app/outputs/deep-optimization-20261025-research-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
   print(json.dumps(result,ensure_ascii=False))
 finally:await pg_manager.close()
asyncio.run(main())
