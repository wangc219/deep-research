"""按固定验收账号前缀清理真实探针记录，保留审计并撤销临时权限。"""
import asyncio,json
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import select,update,text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department,User
from platform_core.utils.auth_utils import AuthUtils

async def main():
    pg_manager.initialize()
    uid='acceptance_migration_20261026_cleanup_'+uuid4().hex[:8]
    counts={}
    try:
        async with pg_manager.get_async_session_context() as db:
            user=User(uid=uid,username=uid,password_hash='disabled-acceptance',role='superadmin',department_id=await db.scalar(select(Department.id).limit(1)))
            db.add(user);await db.flush();token=AuthUtils.create_access_token({'sub':str(user.id)});await db.commit()
            targets={}
            for table in ('equipment_queries','equipment_query_generations','equipment_deep_sessions','equipment_research_runs'):
                status="COALESCE(payload->>'status','active')" if table=='equipment_deep_sessions' else 'status'
                targets[table]=(await db.execute(text(f"SELECT id,{status} AS status FROM {table} WHERE starts_with(owner_uid,:prefix)"),{'prefix':'acceptance_migration_20261026_defaults_'})).mappings().all()
            targets['projects']=(await db.execute(text("SELECT id,status FROM projects WHERE starts_with(uid,:prefix)"),{'prefix':'acceptance_migration_20261026_defaults_'})).mappings().all()
        routes={'equipment_queries':'equipment/queries','equipment_query_generations':'equipment/query-generations','equipment_deep_sessions':'equipment/deep-thinking','equipment_research_runs':'equipment/runs','projects':'projects'}
        async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',headers={'Authorization':'Bearer '+token},timeout=60) as client:
            for table,rows in targets.items():
                counts[table]=0
                for row in rows:
                    if row['status'] in {'deleted','archived'}:continue
                    path='/api/'+routes[table]+'/'+row['id'];params={}
                    if table=='equipment_queries':
                        current=await client.get(path);assert current.status_code==200,current.text[:200]
                        params={'expected_version':current.json()['version']}
                    response=await client.delete(path,params=params)
                    assert response.status_code in {200,404},(table,response.status_code,response.text[:300])
                    counts[table]+=1
        result={'scoped_probe_cleanup':'passed','resources':counts,'customer_records_modified':0}
        Path('/app/outputs/migration-20261026-default-probe-cleanup.json').write_text(json.dumps(result,indent=2)+'\n')
        p=Path('/app/outputs/migration-20261026-final-default-project-probe.json')
        d=json.loads(p.read_text());d['cleanup']='passed';p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result))
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(update(User).where(User.uid==uid).values(is_deleted=1,password_hash='disabled-acceptance'));await db.commit()
        await pg_manager.close()

asyncio.run(main())
