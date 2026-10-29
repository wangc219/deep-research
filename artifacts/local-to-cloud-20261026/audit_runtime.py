"""汇总活动任务和真实调用失败类型，输出不含密钥与正文的审计结果。"""

import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from platform_core.config.options import system_options
from platform_core.storage.postgres.manager import pg_manager


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            active = {}
            for name in ('agent_runs','equipment_research_runs','tasks'):
                active[name] = await db.scalar(text(f'SELECT count(*) FROM {name} WHERE status IN (:a,:b,:c,:d)'),
                    {'a':'queued','b':'running','c':'pending','d':'researching'})
            active['acceptance_users'] = await db.scalar(text("SELECT count(*) FROM users WHERE is_deleted=0 AND (uid LIKE 'acceptance_migration_%' OR uid LIKE 'research_acceptance_%' OR uid LIKE 'migration_verify_%')"))
            failures = (await db.execute(text("SELECT phase,status,error_type,duration_ms FROM platform_model_calls WHERE run_id=:id AND status <> 'completed' ORDER BY created_at"),
                {'id':'run-ed464daf-f4af-4e2e-b008-bc0b9bbfeea8'})).mappings().all()
            options = await system_options.get(db)
            result = {'active':active,'full_research_non_success_calls':[dict(r) for r in failures],
                      'effective_research_slots':options['equipment_research_max_running']}
        Path('/app/outputs/migration-20261026-runtime-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))
    finally:
        await pg_manager.close()


asyncio.run(main())
