"""临时测试管理员执行既有真实子任务 E2E，核对跨池执行后清理所有测试记录。"""
import asyncio
import json
import secrets
import shutil
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import select, delete, text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User, Department, AgentRun, OperationLog, AgentEnv, UserConfig
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir
from test.live_api_cleanup import cleanup_test_chat_resources
from test_subagent_stream_e2e import test_subagent_stream_records_run_and_shares_output_files

async def main():
    uid = 'qachild_' + uuid4().hex[:12]
    report = {'scope': 'real parent-child model/tool/file/SSE flow across independent workers'}
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            password = secrets.token_urlsafe(24)
            user = User(uid=uid, username=uid, password_hash=AuthUtils.hash_password(password), role='admin', department_id=await db.scalar(select(Department.id).limit(1)))
            db.add(user)
            await db.flush()
            user_id = user.id
        report['identity_id'] = user_id
        async with httpx.AsyncClient(base_url='https://www.deepquest.space', timeout=120, trust_env=False) as client:
            login = await client.post('/api/auth/token',data={'username':uid,'password':password})
            assert login.status_code == 200
            headers = {'Authorization':'Bearer ' + login.json()['access_token']}
            try:
                await test_subagent_stream_records_run_and_shares_output_files(client, headers)
                report['status'] = 'passed'
            except BaseException as error:
                report['status'] = 'failed'
                report['error'] = type(error).__name__ + ': ' + str(error)
            finally:
                async with pg_manager.get_async_session_context() as db:
                    report['executions'] = [dict(row) for row in (await db.execute(text('SELECT ar.id,ar.run_type,ar.status,a.worker_id FROM agent_runs ar JOIN agent_run_attempts a ON a.run_id=ar.id WHERE ar.uid=:uid'),{'uid':uid})).mappings().all()]
                    run_ids = (await db.scalars(select(AgentRun.id).where(AgentRun.uid==uid))).all()
                for _ in range(90):
                    async with pg_manager.get_async_session_context() as db:
                        active = (await db.scalars(select(AgentRun.id).where(AgentRun.uid==uid,AgentRun.status.notin_({'completed','failed','cancelled','interrupted'})))).all()
                    if not active:break
                    for run_id in active:await client.post('/api/agent/runs/'+run_id+'/cancel',headers=headers)
                    await asyncio.sleep(1)
                await cleanup_test_chat_resources(client, headers, owner_uid=uid)
                async with pg_manager.get_async_session_context() as db:
                    current = await db.scalar(select(User).where(User.id==user_id).with_for_update())
                    assert current.uid==uid and uid.startswith('qachild_')
                    await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=ANY(:runs)'), {'runs':list(run_ids)})
                    await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=:uid'), {'uid':uid})
                    for model,column,value in [(OperationLog,OperationLog.user_id,user_id),(AgentEnv,AgentEnv.uid,uid),(UserConfig,UserConfig.uid,uid)]:
                        await db.execute(delete(model).where(column==value))
                    await db.delete(current)
                directory = global_user_data_dir(uid)
                assert directory.name==uid
                if directory.exists():shutil.rmtree(directory)
                async with pg_manager.get_async_session_context() as db:
                    report['accounts_remaining'] = await db.scalar(text('SELECT count(*) FROM users WHERE id=:id'),{'id':user_id})
    finally:
        Path('/app/outputs/worker-isolation-subagent-20261027.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
        await pg_manager.close()
    assert report['status']=='passed' and report['accounts_remaining']==0

asyncio.run(main())
