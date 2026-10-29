"""核对本轮精确测试清单，并删除其短期 Redis 事件与队列副本。"""
import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.services.run_queue_service import get_redis_client, close_queue_clients

async def main():
    resources=json.loads(Path('/tmp/isolation-test-resource-ids.json').read_text())
    ids=resources['identity_ids'];known=set(resources['run_ids'])
    assert len(ids)==65
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            queries={
                'test_accounts':("SELECT count(*) FROM users WHERE id=ANY(:ids)",{'ids':ids}),
                'test_operation_logs':("SELECT count(*) FROM operation_logs WHERE user_id=ANY(:ids)",{'ids':ids}),
                'test_agent_runs':("SELECT count(*) FROM agent_runs WHERE uid LIKE 'qacore_%' OR uid LIKE 'qachild_%'",{}),
                'test_conversations':("SELECT count(*) FROM conversations WHERE uid LIKE 'qacore_%' OR uid LIKE 'qachild_%'",{}),
                'test_projects':("SELECT count(*) FROM projects WHERE uid LIKE 'qacore_%' OR uid LIKE 'qachild_%'",{}),
                'test_deep_sessions':("SELECT count(*) FROM equipment_deep_sessions WHERE owner_uid LIKE 'qacore_%' OR owner_uid LIKE 'qachild_%'",{}),
                'test_request_metrics':("SELECT count(*) FROM platform_request_metrics WHERE uid LIKE 'qacore_%' OR uid LIKE 'qachild_%'",{}),
                'known_test_model_calls':("SELECT count(*) FROM platform_model_calls WHERE run_id=ANY(:runs)",{'runs':list(known)}),
                'isolated_test_schemas':("SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 'pytest_user_capacity_%' OR schema_name LIKE 'pytest_resource_pool_%'",{}),
            }
            remaining={name:await db.scalar(text(query),args) for name,(query,args) in queries.items()}
        assert all(count==0 for count in remaining.values()),remaining
        redis=await get_redis_client()
        # 元数据同时包含本轮专用身份前缀；不输出、修改其他用户的事件内容。
        async for key in redis.scan_iter(match='run:events:*',count=100):
            for _,fields in await redis.xrange(key,count=3):
                try:
                    event=json.loads(fields.get('payload','{}')).get('payload',{})
                except (ValueError,TypeError):continue
                uid=event.get('uid','') if isinstance(event,dict) else ''
                if isinstance(uid,str) and uid.startswith(('qacore_','qachild_')):
                    known.add(key.removeprefix('run:events:'))
                    break
        removed=0
        for run in known:
            removed+=await redis.delete('run:events:'+run,'run:cancel:'+run,'arq:result:run:'+run,'arq:job:run:'+run,'arq:in-progress:run:'+run)
            for queue in ['arq:queue','deep-research:queue:chat','deep-research:queue:deep','deep-research:queue:subagent']:
                await redis.zrem(queue,'run:'+run)
        remaining['known_test_redis_events']=sum([bool(await redis.exists('run:events:'+run)) for run in known])
        async with pg_manager.get_async_session_context() as db:
            connections=await db.scalar(text('SELECT count(*) FROM pg_stat_activity'))
            maximum=await db.scalar(text('SHOW max_connections'))
            active=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('pending','running','cancel_requested')"))
        result={'test_identities':len(ids),'test_run_ids_checked':len(known),'redis_keys_removed':removed,'remaining':remaining,'active_agent_runs':active,'postgres_connections':connections,'postgres_max_connections':int(maximum)}
        print(json.dumps(result),flush=True)
    finally:
        await close_queue_clients()
        await pg_manager.close()

asyncio.run(main())
