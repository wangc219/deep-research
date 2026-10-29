"""只采样本轮临时身份，验证用户配额与执行池确实分离。"""
import asyncio
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.services.run_scheduling import run_lane

async def main():
    pg_manager.initialize()
    maxima = Counter()
    totals = Counter()
    workers = {}
    try:
        for _ in range(600):
            async with pg_manager.get_async_session_context() as db:
                rows = (await db.execute(text("SELECT uid,source,run_type,agent_slug,worker_id FROM agent_runs WHERE uid LIKE 'qacore_%' AND status='running'"))).mappings().all()
            counts = Counter((row['uid'], run_lane(SimpleNamespace(**row))) for row in rows)
            lanes = Counter()
            for (_, lane), count in counts.items():
                maxima[lane] = max(maxima[lane], count)
                lanes[lane] += count
            for lane, count in lanes.items(): totals[lane] = max(totals[lane], count)
            for row in rows:
                lane = run_lane(SimpleNamespace(**row))
                workers.setdefault(lane, set()).add(row['worker_id'].rsplit(':', 1)[0])
            await asyncio.sleep(.1)
        result = {'maximum_running_per_user': dict(maxima), 'maximum_total_running': dict(totals), 'execution_owners_per_lane': {key:sorted(value) for key,value in workers.items()}}
        Path('/app/outputs/core-user-capacity-observations.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    finally:
        await pg_manager.close()

asyncio.run(main())
