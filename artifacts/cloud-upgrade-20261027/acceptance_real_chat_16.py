"""16 个普通账号通过生产 HTTPS 同时执行真实模型短对话，结束后精确清理。"""
import asyncio
import json
import secrets
import shutil
import statistics
import time
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User, OperationLog, AgentEnv, UserConfig, Conversation, AgentRun
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir
from live_api_cleanup import cleanup_test_chat_resources, make_test_conversation_metadata, make_test_conversation_title

OUT = Path('/app/outputs/core-real-chat-16-20261027.json')
rows = []
extra_chats = []
deep = {}
probes = []
report = {'scope': '16 ordinary users, 20 real provider short chats plus one native deep turn, public HTTPS; not full reports/ASR mixed-load acceptance'}
stop = asyncio.Event()


async def request(row, method, path, **kwargs):
    response = await row['client'].request(method, path, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f'{method} {path.split("?")[0]}: HTTP {response.status_code}')
    return response.json()


async def chat(row):
    default = await request(row, 'GET', '/api/agent/default')
    agent = default['agent']
    slug = agent['slug']
    thread = await request(row, 'POST', '/api/chat/thread', json={
        'agent_id': slug, 'title': make_test_conversation_title('capacity-real-chat'),
        'metadata': make_test_conversation_metadata('capacity-real-chat', e2e=True)})
    row['thread'] = thread.get('thread_id') or thread.get('id')
    started = time.monotonic()
    result = await request(row, 'POST', '/api/agent/runs', json={
        'agent_slug': slug, 'thread_id': row['thread'],
        'query': '这是网站并发验收。不要调用工具，只输出：17×19=323。不要添加解释。',
        'meta': {'request_id': 'qa-core-' + uuid4().hex}})
    row['run'] = result['run_id']
    row['accepted_seconds'] = round(time.monotonic() - started, 3)
    while time.monotonic() - started < 240:
        run = (await request(row, 'GET', '/api/agent/runs/' + row['run']))['run']
        if run['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
            row['status'] = run['status']
            if run['status'] != 'completed':
                raise RuntimeError('Real chat did not complete: ' + run['status'])
            result = await request(row, 'GET', '/api/agent/runs/' + row['run'] + '/result')
            assert '323' in str(result.get('output') or ''), 'Missing expected model answer'
            history = await request(row, 'GET', '/api/chat/thread/' + row['thread'] + '/history')
            assert '323' in json.dumps(history, ensure_ascii=False), 'Answer missing from persisted history'
            row['seconds'] = round(time.monotonic() - started, 3)
            row['timing'] = result.get('timing', {})
            return
        await asyncio.sleep(.5)
    raise TimeoutError('Real chat exceeded 240 seconds')


async def probe():
    while not stop.is_set():
        started = time.monotonic()
        response = await rows[0]['client'].get('/api/equipment/portal')
        probes.append({'status': response.status_code, 'ms': round((time.monotonic() - started)*1000, 1)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=.5)
        except TimeoutError:
            pass


async def deep_chat(row):
    while not row.get('thread'):
        await asyncio.sleep(.1)
    async with pg_manager.get_async_session_context() as db:
        project_id = await db.scalar(select(Conversation.project_id).where(Conversation.thread_id == row['thread'], Conversation.uid == row['uid']))
    session = await request(row, 'POST', '/api/equipment/deep-thinking', json={
        'project_id': project_id, 'title': make_test_conversation_title('capacity-native-deep'),
        'topic': '民用公共避难场所应急照明的日常维护', 'knowledge_enabled': False, 'subagents_enabled': False})
    deep['session_id'] = session.get('session_id') or session.get('id')
    started = time.monotonic()
    response = await request(row, 'POST', '/api/equipment/deep-thinking/' + deep['session_id'] + '/messages', json={
        'content': '这是网站并发验收。本轮只用100字以内说明民用应急照明电池日常维护的原则。无需外部检索，不调用工具，不创建报告或能力卡。'})
    deep['run'] = response['request']['run_id']
    while time.monotonic() - started < 240:
        run = (await request(row, 'GET', '/api/agent/runs/' + deep['run']))['run']
        if run['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
            deep['status'] = run['status']
            assert run['status'] == 'completed', 'Native deep turn failed'
            result = await request(row, 'GET', '/api/agent/runs/' + deep['run'] + '/result')
            assert str(result.get('output') or '').strip(), 'Native deep output empty'
            deep['seconds'] = round(time.monotonic() - started, 3)
            deep['timing'] = result.get('timing', {})
            return
        await asyncio.sleep(.5)
    raise TimeoutError('Native deep turn exceeded 240 seconds')


async def main():
    pg_manager.initialize()
    monitor = None
    try:
        async with pg_manager.get_async_session_context() as db:
            department = await db.scalar(select(Department.id).limit(1))
            batch = uuid4().hex[:8]
            for index in range(16):
                uid = f'qacore_{batch}_{index:02d}'
                password = secrets.token_urlsafe(24)
                user = User(uid=uid, username=uid, password_hash=AuthUtils.hash_password(password), role='user', department_id=department)
                db.add(user)
                await db.flush()
                rows.append({'uid': uid, 'id': user.id, 'password': password,
                    'client': httpx.AsyncClient(base_url='https://www.deepquest.space', timeout=60, trust_env=False)})
        report['identity_ids'] = [row['id'] for row in rows]
        for row in rows:
            login = await request(row, 'POST', '/api/auth/token', data={'username': row['uid'], 'password': row.pop('password')})
            row['client'].headers['Authorization'] = 'Bearer ' + login['access_token']
        print(json.dumps({'phase': '16_ordinary_users_logged_in'}), flush=True)
        monitor = asyncio.create_task(probe())
        started = time.monotonic()
        extra_chats.extend({'id': rows[0]['id'], 'uid': rows[0]['uid'], 'client': rows[0]['client']} for _ in range(4))
        results = await asyncio.gather(*(chat(row) for row in [*rows, *extra_chats]), deep_chat(rows[0]), return_exceptions=True)
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['errors'] = [type(error).__name__ + ': ' + str(error) for error in results if isinstance(error, BaseException)]
        report['completed'] = sum(row.get('status') == 'completed' and 'seconds' in row for row in [*rows, *extra_chats])
        report['chats'] = [{key: row[key] for key in ['id', 'run', 'status', 'seconds', 'accepted_seconds', 'timing'] if key in row} for row in [*rows, *extra_chats]]
        report['native_deep'] = deep
        stop.set()
        await monitor
        report['page_probes'] = probes
        async with pg_manager.get_async_session_context() as db:
            report['real_model_calls'] = [dict(row) for row in (await db.execute(text(
                'SELECT status,count(*) AS n FROM platform_model_calls WHERE run_id = ANY(:runs) GROUP BY status'),
                {'runs': [row['run'] for row in [*rows, *extra_chats, deep] if row.get('run')]})).mappings().all()]
        print(json.dumps({'phase': 'chat_test_finished', 'completed': report['completed'], 'errors': report['errors']}), flush=True)
    finally:
        stop.set()
        if monitor:
            await asyncio.gather(monitor, return_exceptions=True)
        failures = []
        for row in rows:
            try:
                if row is rows[0] and deep.get('session_id'):
                    if deep.get('run'):
                        await request(row, 'POST', '/api/agent/runs/' + deep['run'] + '/cancel')
                        for _ in range(60):
                            current = (await request(row, 'GET', '/api/agent/runs/' + deep['run']))['run']
                            if current['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}: break
                            await asyncio.sleep(1)
                    await request(row, 'DELETE', '/api/equipment/deep-thinking/' + deep['session_id'])
                if row.get('run'):
                    run = (await request(row, 'GET', '/api/agent/runs/' + row['run']))['run']
                    if run['status'] not in {'completed', 'failed', 'cancelled', 'interrupted'}:
                        await request(row, 'POST', '/api/agent/runs/' + row['run'] + '/cancel')
                        for _ in range(60):
                            run = (await request(row, 'GET', '/api/agent/runs/' + row['run']))['run']
                            if run['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                                break
                            await asyncio.sleep(1)
                async with pg_manager.get_async_session_context() as db:
                    owned_run_ids = (await db.scalars(select(AgentRun.id).where(AgentRun.uid == row['uid']))).all()
                await cleanup_test_chat_resources(row['client'], dict(row['client'].headers), owner_uid=row['uid'])
                async with pg_manager.get_async_session_context() as db:
                    user = await db.scalar(select(User).where(User.id == row['id']).with_for_update())
                    assert user.uid == row['uid'] and user.uid.startswith('qacore_') and user.role == 'user'
                    await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=ANY(:runs)'), {'runs': list(owned_run_ids)})
                    await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=:uid'), {'uid': row['uid']})
                    for model, column, value in [(OperationLog, OperationLog.user_id, row['id']), (AgentEnv, AgentEnv.uid, row['uid']), (UserConfig, UserConfig.uid, row['uid'])]:
                        await db.execute(delete(model).where(column == value))
                    await db.delete(user)
                directory = global_user_data_dir(row['uid'])
                assert directory.name == row['uid']
                if directory.exists():
                    shutil.rmtree(directory)
            except Exception as error:
                failures.append({'id': row['id'], 'error': type(error).__name__ + ': ' + str(error)})
            finally:
                await row['client'].aclose()
        report['cleanup_errors'] = failures
        async with pg_manager.get_async_session_context() as db:
            report['accounts_remaining'] = len((await db.scalars(select(User.id).where(User.id.in_([r['id'] for r in rows])))).all())
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(json.dumps({'report': str(OUT), 'completed': report.get('completed'), 'cleanup_errors': failures, 'accounts_remaining': report['accounts_remaining']}), flush=True)
        await pg_manager.close()
    assert report['completed'] == 20 and deep.get('status') == 'completed' and not report['errors'] and not report['cleanup_errors'] and report['accounts_remaining'] == 0


asyncio.run(main())
