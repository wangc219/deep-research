"""只读发布前检查，保持用户运行不被重启中断。"""
import asyncio
import json
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            tasks=await db.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('pending','running','queued')"))
            runs=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('pending','running','cancel_requested')"))
            print(json.dumps({"active_tasks":tasks,"active_agent_runs":runs}))
            assert tasks+runs == 0, "Waiting for user work to drain; do not interrupt"
    finally:
        await pg_manager.close()
asyncio.run(main())
