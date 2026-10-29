"""只读核对生产任务、模型调用和实际执行容量，不输出用户内容或凭据。"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from platform_core.config.options import system_options
from platform_core.services.task_service import resolve_task_capacity
from platform_core.storage.postgres.manager import pg_manager


async def main():
    pg_manager.initialize()
    try:
        result = {"capacity": {}}
        for kind in ["equipment_research", "equipment_query_generation", "equipment_deep_turn", "wxchannels_transcribe", "knowledge_ingest"]:
            result["capacity"][kind] = await resolve_task_capacity(kind)
        options = await system_options.get()
        result["live_research_setting"] = options.get("equipment_research_max_running")
        path = Path('/app/outputs/runtime/research-worker-pool.json')
        result["legacy_research_pool"] = json.loads(path.read_text()) if path.exists() else None
        async with pg_manager.get_async_session_context() as db:
            queries = {
                "active_tasks": "SELECT type,status,count(*) FROM tasks WHERE status IN ('running','pending','queued') GROUP BY type,status",
                "active_agent_runs": "SELECT run_type,status,count(*) FROM agent_runs WHERE status IN ('running','pending','queued') GROUP BY run_type,status",
                "agent_runs_last_day": "SELECT run_type,status,count(*) FROM agent_runs WHERE created_at > now()-interval '24 hours' GROUP BY run_type,status",
                "research_last_day": "SELECT status,count(*) FROM equipment_research_runs WHERE created_at > now()-interval '24 hours' GROUP BY status",
                "db_connections": "SELECT state,count(*) FROM pg_stat_activity GROUP BY state",
            }
            for key, query in queries.items():
                result[key] = [list(row) for row in (await db.execute(text(query))).all()]
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    finally:
        await pg_manager.close()


asyncio.run(main())
