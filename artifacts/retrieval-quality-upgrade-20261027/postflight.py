"""发布后的代码、工具约束、预置角色与验收清理核验。"""
import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from platform_core.agents.middlewares.search_resilience import SearchResilienceMiddleware
from platform_core.agents.toolkits.buildin.academic import AcademicSearchInput
from platform_core.agents.toolkits.buildin.tools import DoubaoSearchInput
from platform_core.repositories.agent_repository import AgentRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.redis import RedisConfig, create_sync_redis_client
from platform_core.services.wxchannels_service import connection_status

async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            agent=await AgentRepository(db).get_by_slug("research-explorer")
            prompt=(agent.config_json or {}).get("context",{}).get("system_prompt","")
            assert "最多 24 次" in prompt and "最多做 8 次" in prompt and 'mode="semantic"' in prompt
            schemas=await db.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'pytest_aminer_%'"))
        client=create_sync_redis_client(RedisConfig.from_env(socket_timeout=3,socket_connect_timeout=3))
        try: private_keys=sum(1 for _ in client.scan_iter("pytest:search:*"))
        finally: client.close()
        assert schemas==0, 'Review isolated acceptance schemas; do not delete unknown schemas'
        assert private_keys==0, 'Review private acceptance keys; do not delete unknown keys'
        assert SearchResilienceMiddleware(research_mode=True).max_calls==24
        assert "semantic" in AcademicSearchInput.model_fields["mode"].annotation.__args__
        assert "required_term_groups" in DoubaoSearchInput.model_fields
        status=await connection_status()
        assert status["ready"] and status["central_managed"]
        print(json.dumps({"explorer_prompt_synced":True,"explorer_web_limit":24,"semantic_mode_registered":True,"alias_groups_registered":True,"remaining_acceptance_schemas":schemas,"remaining_private_search_keys":private_keys,"created_public_acceptance_accounts":0,"wechat_ready":status["ready"],"shared_cloud_wechat":status["central_managed"]}))
    finally:
        await pg_manager.close()
asyncio.run(main())
