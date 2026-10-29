"""按本轮验收清单恢复清理，保留首次失败证据。"""
import asyncio
import json
import shutil
from pathlib import Path
from sqlalchemy import select, delete, text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User, OperationLog, AgentEnv, UserConfig
from platform_core.workspace.paths import global_user_data_dir

async def main():
    path = Path('/app/outputs/core-real-chat-16-20261027.json')
    report = json.loads(path.read_text())
    ids = report['identity_ids']
    assert len(ids) == 16 and set(ids) == set(range(2906, 2922))
    runs = [row['run'] for row in report['chats'] if row.get('run')]
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            users = (await db.scalars(select(User).where(User.id.in_(ids)).with_for_update())).all()
            assert all(user.uid.startswith('qacore_7327a49e_') and user.role=='user' for user in users)
            uids = [user.uid for user in users]
            report['real_model_calls'] = [dict(row) for row in (await db.execute(text('SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id=ANY(:runs) GROUP BY status'), {'runs':runs})).mappings().all()]
            assert await db.scalar(text('SELECT count(*) FROM agent_runs WHERE uid=ANY(:uids)'), {'uids':uids}) == 0
            assert await db.scalar(text('SELECT count(*) FROM conversations WHERE uid=ANY(:uids)'), {'uids':uids}) == 0
            await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=ANY(:runs)'), {'runs':runs})
            await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=ANY(:uids)'), {'uids':uids})
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
            await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
            await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
        for uid in uids:
            directory = global_user_data_dir(uid)
            assert directory.name == uid
            if directory.exists(): shutil.rmtree(directory)
        async with pg_manager.get_async_session_context() as db:
            report['accounts_remaining'] = await db.scalar(text('SELECT count(*) FROM users WHERE id=ANY(:ids)'), {'ids':ids})
        report['cleanup_recovery'] = 'completed; SQL helper corrected to use model-call run_id'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'accounts_remaining':report['accounts_remaining'],'real_model_calls':report['real_model_calls']}))
    finally:
        await pg_manager.close()

asyncio.run(main())
