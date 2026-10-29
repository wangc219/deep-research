"""独立复核验收身份、对象和事件已清除，再删除云端验收文件。"""
import asyncio
import json
import os
import sqlite3
import shutil
import hashlib
import re
from urllib.parse import unquote
from pathlib import Path
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
from platform_core.services.run_queue_service import get_redis_client, close_queue_clients
from platform_core.storage.minio.client import get_minio_client
from platform_core.services.wxchannels_service import video_owner_prefix
from platform_core.services.collection_artifact_service import manifest_directory
from platform_core.workspace.paths import global_user_data_dir


async def main():
    targets=json.loads(Path('/tmp/qagov-cleanup-targets.json').read_text())
    ids=targets['user_ids'];runs=targets['run_ids'];kbs=targets['kb_ids'];tasks=targets['task_ids']
    assert len(ids)==len(set(ids))==20 and len(kbs)==2
    pg_manager.initialize()
    try:
        remaining={}
        async with pg_manager.get_async_session_context() as db:
            for name,query,args in [
                ('accounts','SELECT count(*) FROM users WHERE id=ANY(:ids)',{'ids':ids}),
                ('operation_logs','SELECT count(*) FROM operation_logs WHERE user_id=ANY(:ids)',{'ids':ids}),
                ('agent_runs','SELECT count(*) FROM agent_runs WHERE id=ANY(:runs)',{'runs':runs}),
                ('model_calls','SELECT count(*) FROM platform_model_calls WHERE run_id=ANY(:runs)',{'runs':runs}),
                ('tasks','SELECT count(*) FROM tasks WHERE id=ANY(:ids)',{'ids':tasks}),
                ('knowledge','SELECT count(*) FROM knowledge_bases WHERE kb_id=ANY(:ids)',{'ids':kbs}),
                ('knowledge_files','SELECT count(*) FROM knowledge_files WHERE kb_id=ANY(:ids)',{'ids':kbs}),
            ]:
                remaining[name]=await db.scalar(text(query),args)
            for table,column in [('projects','uid'),('equipment_capability_versions','owner_uid'),('equipment_research_runs','owner_uid'),
                ('equipment_deep_sessions','owner_uid'),('conversations','uid'),('wechat_collector_devices','owner_uid'),('platform_request_metrics','uid')]:
                remaining['test_'+table]=await db.scalar(text(f"SELECT count(*) FROM {table} WHERE {column} LIKE 'qares_%' OR {column} LIKE 'qavid_%' OR {column} LIKE 'qacore_%'"))
            remaining['test_schemas']=await db.scalar(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name LIKE 'pytest_durable_task_%'"))
        assert all(value==0 for value in remaining.values()),remaining
        redis=await get_redis_client()
        for run in runs:
            await redis.delete('run:events:'+run,'run:cancel:'+run,'equipment:events:'+run,'arq:result:run:'+run,'arq:job:run:'+run)
            for queue in ['arq:queue','deep-research:queue:chat','deep-research:queue:deep','deep-research:queue:subagent']:
                await redis.zrem(queue,'run:'+run)
        remaining['redis_test_events']=sum([bool(await redis.exists('run:events:'+run)) or bool(await redis.exists('equipment:events:'+run)) for run in runs])
        storage=get_minio_client()
        prefixes=[*kbs,*[video_owner_prefix(uid) for uid in targets['known_owner_uids']],*['video-audio/'+task+'/' for task in tasks]]
        remaining['test_objects']=sum(sum(1 for _ in storage.client.list_objects(bucket.name,prefix=prefix,recursive=True)) for bucket in storage.client.list_buckets() for prefix in prefixes)
        # 两次测试均使用合成的 pytest-video OID，实际视频号 OID 不采用此前缀。
        historical_removed=0
        synthetic=[item for item in storage.client.list_objects(storage.KB_BUCKETS['documents'],prefix='video-transcripts/',recursive=True) if '/oid-pytest-video-' in item.object_name]
        for item in synthetic:
            name=item.object_name.rsplit('/',1)[1]
            oid=unquote(name.removeprefix('oid-').removesuffix('.json'))
            assert re.fullmatch(r'pytest-video-[a-f0-9]{32}',oid),'Only the exact synthetic E2E OID format may be removed'
            document=item.object_name.rsplit('/',1)[0]+'/'+hashlib.sha256(oid.encode()).hexdigest()+'.docx'
            storage.client.remove_object(storage.KB_BUCKETS['documents'],document)
            storage.client.remove_object(storage.KB_BUCKETS['documents'],item.object_name)
            historical_removed+=1
        remaining['synthetic_video_completion_objects']=sum('/oid-pytest-video-' in item.object_name for item in storage.client.list_objects(storage.KB_BUCKETS['documents'],prefix='video-transcripts/',recursive=True))
        from pymilvus import connections,utility
        connections.connect(alias='qagov_cleanup',uri=os.environ['MILVUS_URI'],token=os.getenv('MILVUS_TOKEN',''))
        try:
            names=utility.list_collections(using='qagov_cleanup')
            remaining['test_vector_collections']=sum(any(name==kb or name.startswith(kb+'_') for kb in kbs) for name in names)
        finally:connections.disconnect('qagov_cleanup')
        parent=global_user_data_dir('qares_validation_only').parent
        remaining['test_user_directories']=sum(1 for pattern in ['qares_*','qavid_*','qacore_*'] for _ in parent.glob(pattern))
        remaining['test_collection_manifests']=sum(manifest_directory(uid).exists() for uid in targets['known_owner_uids'])
        outbox=Path('/app/outputs/model-call-outbox.db')
        remaining['test_model_call_outbox']=0
        if outbox.exists():
            with sqlite3.connect(outbox) as db:
                remaining['test_model_call_outbox']=sum(db.execute("SELECT count(*) FROM pending_model_calls WHERE json_extract(payload,'$.run_id')=?",(run,)).fetchone()[0] for run in runs)
        assert all(value==0 for value in remaining.values()),remaining
        # 只移除本轮生成的音频、Word、报告和采样副本；实时资源预算属于运行组件。
        roots=[Path('/app/outputs/resource-governor-acceptance'),Path('/app/outputs/resource-governor-overlap')]
        removed_files=0
        for folder in roots:
            if folder.exists():
                removed_files+=sum(path.is_file() for path in folder.rglob('*'))
                shutil.rmtree(folder)
        for file in ['/tmp/governor-speech.wav','/app/test/fixtures/video_transcriber/speech.wav']:
            Path(file).unlink(missing_ok=True)
        remaining['cloud_test_output_directories']=sum(folder.exists() for folder in roots)
        result={'test_identities_checked':20,'remaining':remaining,'temporary_output_files_removed':removed_files,
            'historical_synthetic_video_pairs_removed':historical_removed,
            'only_retained':'aggregate metrics without report body, audio, transcript or credentials'}
        print(json.dumps(result),flush=True)
    finally:
        await close_queue_clients()
        await pg_manager.close()

asyncio.run(main())
