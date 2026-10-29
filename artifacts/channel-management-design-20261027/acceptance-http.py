"""云端普通用户的真实 HTTP、Worker 与私有目录验收；不采集或转录真实媒体。"""
import asyncio
import json
import secrets
import shutil
import time
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select, text

from platform_core.services import wxchannels_service as service
from platform_core.services.task_service import tasker
from platform_core.storage.minio.client import get_minio_client
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import AgentEnv, Department, OperationLog, TaskRecord, User, UserConfig
from platform_core.storage.postgres.models_knowledge import VideoCollectorCapture, VideoCollectorDevice, WechatChannel, WechatChannelVideo
from platform_core.utils.auth_utils import AuthUtils
from platform_core.workspace.paths import global_user_data_dir

BASE = 'https://www.deepquest.space/api/knowledge/wxchannels'

async def main():
    pg_manager.initialize()
    identities = []
    tasks = []
    uid_prefix = 'qachannel_' + uuid4().hex[:12]
    device_id = 'wxd_' + uuid4().hex
    device_token = secrets.token_hex(32)
    summary = {'ordinary_users': 2, 'range_checks': [], 'passed': False}
    storage = get_minio_client()
    started = time.monotonic()
    try:
        async with pg_manager.get_async_session_context() as db:
            department = await db.scalar(select(Department).limit(1))
            for i in range(2):
                uid = uid_prefix + '_' + str(i)
                row = User(uid=uid, username=uid, password_hash='disabled-acceptance-login', role='user', department_id=department.id)
                db.add(row)
                await db.flush()
                identities.append({'id': row.id, 'uid': uid})
        headers = [{'Authorization': 'Bearer ' + AuthUtils.create_access_token({'sub': str(row['id'])})} for row in identities]
        device_headers = {'Authorization': 'Bearer ' + device_token, 'X-Collector-Device': device_id}
        state = {'channels_ready': True, 'mcp_available': True, 'wechat_available': True, 'ffmpeg_available': True}
        async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
            async def call(method, path, *, identity=0, body=None, device=False, expected=200):
                response = await client.request(method, BASE + path,
                    headers=device_headers if device else headers[identity], json=body)
                assert response.status_code == expected, f'{method} {path}: HTTP {response.status_code}'
                return response.json()

            async def heartbeat():
                return (await call('POST', '/collector/heartbeat', body=state, device=True)).get('job')

            async def wait_job(task_id):
                for _ in range(120):
                    job = await heartbeat()
                    if job and job['task_id'] == task_id:
                        return job
                    await asyncio.sleep(0.5)
                raise AssertionError('Worker did not claim acceptance discovery')

            await call('POST', '/collector/devices', body={'device_id': device_id, 'token': device_token,
                'name': 'temporary channel acceptance', 'platform': 'macos'})
            await heartbeat()
            await service.store_video_document(identities[0]['uid'], 'v126', b'acceptance completed marker fixture', storage)
            source = {'account': 'acceptance@finder', 'collection_mode': 'personal', 'device_id': device_id}
            for count in [5, 10, 15, 20, None]:
                begun = time.monotonic()
                result = await call('POST', '/videos', body={**source, 'max_pages': None, 'max_videos': count})
                task_id = result['task_id'];tasks.append(task_id)
                job = await wait_job(task_id)
                if len(tasks) > 1:
                    assert len(job['known_oids']) == 127
                    assert job['resolved_username'] == 'acceptance@finder'
                supplied = ([{'oid': f'v{i}', 'title': f'验收视频{i}', 'published_at': 1700000000 + i}
                            for i in range(127)] if len(tasks) == 1 else
                            [{'oid': 'v125', 'title': '更新后的标题', 'published_at': 1700000125}])
                await call('POST', '/collector/event', device=True, body={
                    'task_id': task_id, 'execution_id': job['execution_id'], 'sequence': 1,
                    'kind': 'video_list', 'username': 'acceptance@finder', 'finished': True,
                    'history_complete': len(tasks) == 1, 'videos': supplied})
                for _ in range(120):
                    await heartbeat()
                    task = await call('GET', '/tasks/' + task_id)
                    if task['status'] in {'success','failed','cancelled'}:break
                    await asyncio.sleep(0.5)
                assert task['status'] == 'success', task.get('error')
                data = task['result']
                assert data['total_count'] == 127 and data['completed_count'] == 1
                expected = 126 if count is None else count
                assert len(data['videos']) == expected
                assert data['videos'][0]['oid'] == 'v125'
                assert data['new_count'] == (127 if len(tasks) == 1 else 0)
                summary['range_checks'].append({'range': count if count else 'all', 'returned': expected,
                    'elapsed_seconds': round(time.monotonic() - begun, 3)})
            channel = (await call('GET', '/channels'))['items'][0]
            assert channel['video_count'] == 127 and channel['history_complete']
            assert (await call('GET', '/channels', identity=1))['items'] == []
            await call('GET', '/channels/' + channel['id'] + '/videos', identity=1, expected=404)
            await call('DELETE', '/channels/' + channel['id'], identity=1, expected=404)
            first = await call('GET', '/channels/' + channel['id'] + '/videos?limit=50')
            second = await call('GET', '/channels/' + channel['id'] + '/videos?offset=50&limit=50')
            assert len(first['videos']) == len(second['videos']) == 50
            assert first['videos'][0]['completed'] is True
            filtered = await call('GET', '/channels/' + channel['id'] + '/videos?keyword=%E6%9B%B4%E6%96%B0&published_after=1700000120&published_before=1700000126')
            assert filtered['total_count'] == 1 and filtered['videos'][0]['oid'] == 'v125'
            assert (await call('GET', '/channels/' + channel['id'] + '/videos?keyword=%25'))['total_count'] == 0
            await call('GET', '/channels/' + channel['id'] + '/videos?published_after=10&published_before=1', expected=422)
            summary['title_date_and_completion_filters_passed'] = True
            assert not {v['oid'] for v in first['videos']} & {v['oid'] for v in second['videos']}
            summary.update({'persisted_history':127, 'incremental_preserved_old_rows':True,
                'cross_user_read_delete_blocked':True,'pagination_passed':True})
            # Verify nullable all submission and cancel it before requesting any actual audio.
            submitted = await call('POST','/transcribe',body={**source,'max_videos':None},expected=202)
            assert submitted['submitted'];tasks.append(submitted['task_id'])
            await call('POST','/tasks/' + submitted['task_id'] + '/cancel',body={})
            # Full refresh bypasses the incremental boundary in the next device job.
            refresh = await call('POST','/videos',body={**source,'max_videos':5,'full_refresh':True})
            tasks.append(refresh['task_id'])
            job = await wait_job(refresh['task_id'])
            assert job['known_oids'] == []
            await call('POST','/tasks/' + refresh['task_id'] + '/cancel',body={})
            await call('DELETE', '/channels/' + channel['id'])
            assert (await call('GET','/channels'))['items'] == []
            assert await storage.astat_file(storage.KB_BUCKETS['documents'], service.video_object_key(identities[0]['uid'],'v126')) is not None
            summary.update({'all_submission_accepted':True,'full_refresh_bypasses_cache':True,
                'removing_list_keeps_documents':True,'passed':True})
    finally:
        for task_id in tasks:await tasker.cancel_task(task_id)
        for _ in range(80):
            states = [await tasker.get_task(task_id) for task_id in tasks]
            if all(not row or row['status'] in {'success','failed','cancelled'} for row in states):break
            await asyncio.sleep(0.5)
        assert all(not row or row['status'] in {'success','failed','cancelled'} for row in states)
        uids=[row['uid'] for row in identities]; ids=[row['id'] for row in identities]
        await asyncio.sleep(1)
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(VideoCollectorCapture).where(VideoCollectorCapture.task_id.in_(tasks)))
            await db.execute(delete(VideoCollectorDevice).where(VideoCollectorDevice.device_id==device_id))
            await db.execute(delete(TaskRecord).where(TaskRecord.id.in_(tasks)))
            await db.execute(delete(WechatChannel).where(WechatChannel.owner_uid.in_(uids)))
            await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=ANY(:uids)'), {'uids':uids})
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
            await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
            await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
        for uid in uids:
            await storage.adelete_objects_by_prefix(storage.KB_BUCKETS['documents'],service.video_owner_prefix(uid))
            folder=global_user_data_dir(uid)
            assert folder.name==uid
            shutil.rmtree(folder,ignore_errors=True)
        async with pg_manager.get_async_session_context() as db:
            remaining = {}
            for label,query in {
                'accounts':select(func.count()).select_from(User).where(User.id.in_(ids)),
                'tasks':select(func.count()).select_from(TaskRecord).where(TaskRecord.id.in_(tasks)),
                'devices':select(func.count()).select_from(VideoCollectorDevice).where(VideoCollectorDevice.device_id==device_id),
                'captures':select(func.count()).select_from(VideoCollectorCapture).where(VideoCollectorCapture.task_id.in_(tasks)),
                'channels':select(func.count()).select_from(WechatChannel).where(WechatChannel.owner_uid.in_(uids)),
            }.items():remaining[label]=await db.scalar(query)
            remaining['request_metrics']=await db.scalar(text('SELECT count(*) FROM platform_request_metrics WHERE uid=ANY(:uids)'),{'uids':uids})
            remaining['test_schemas']=await db.scalar(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 'pytest_channels_%' OR schema_name LIKE 'pytest_video_%'"))
        remaining['objects']=0
        for uid in uids:
            remaining['objects']+=len(await storage.alist_object_metadata(storage.KB_BUCKETS['documents'],service.video_owner_prefix(uid)))
        remaining['user_directories']=sum(global_user_data_dir(uid).exists() for uid in uids)
        from platform_core.services.run_queue_service import get_arq_pool
        pool=await get_arq_pool()
        for pattern in ('arq:result:*','arq:job:*'):
            async for key in pool.scan_iter(match=pattern):
                data=await pool.get(key)
                if data and any(task.encode() in data for task in tasks):
                    await pool.delete(key)
        remaining['redis_test_payloads']=0
        async for key in pool.scan_iter(match='arq:*'):
            if await pool.type(key) != b'string':continue
            data=await pool.get(key)
            if data and any(task.encode() in data for task in tasks):remaining['redis_test_payloads']+=1
        summary['cleanup_remaining']=remaining
        assert not any(remaining.values()),remaining
        summary['elapsed_seconds']=round(time.monotonic()-started,3)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        await pg_manager.close()

asyncio.run(main())
