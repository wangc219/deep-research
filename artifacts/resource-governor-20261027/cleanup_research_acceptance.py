"""清除保留在项目中的验收画像版本，再按精确身份完成验收数据清理。"""
import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from sqlalchemy import select, delete, text, or_, func
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User, Project, TaskRecord, OperationLog, AgentEnv, UserConfig
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion
from platform_core.storage.postgres.models_knowledge import VideoCollectorDevice, VideoCollectorCapture
from platform_core.services.collection_artifact_service import manifest_directory
from platform_core.services.wxchannels_service import video_owner_prefix
from platform_core.storage.minio.client import get_minio_client
from platform_core.workspace.paths import global_user_data_dir


async def main():
    path=Path('/app/outputs/resource-governor-acceptance/heavy-mix-result.json')
    report=json.loads(path.read_text())
    ids=report['identity_ids'];run=report['research_run_id']
    assert len(ids)==2 and run=='run-76e7d32f-25ad-4f3e-9c61-61ff3cd2754f'
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            users=(await db.scalars(select(User).where(User.id.in_(ids)).with_for_update())).all()
            uids=[user.uid for user in users]
            assert set(uids)=={'qares_8e3504a67ea9','qavid_821829043ffc'}
            assert all(user.role=='user' for user in users)
            tasks=(await db.scalars(select(TaskRecord).where(or_(TaskRecord.payload['operator_id'].as_string().in_(uids),
                TaskRecord.payload['run_id'].as_string()==run,TaskRecord.payload['kb_id'].as_string()==report['knowledge_id'])))).all()
            assert all(task.status in {'success','failed','cancelled'} for task in tasks)
            task_ids=[task.id for task in tasks]
            versions=await db.scalar(select(func.count()).select_from(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.owner_uid.in_(uids)))
            assert versions>0
            report['research']['capability_response_key_count']=report['research'].pop('capability_versions')
            report['research']['capability_versions']=versions
            report['research']['capability_count_verified_from']='PostgreSQL owned capability rows before deletion; original API response has run_id and versions keys'
            await db.execute(delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.owner_uid.in_(uids)))
            devices=(await db.scalars(select(VideoCollectorDevice.device_id).where(VideoCollectorDevice.owner_uid.in_(uids)))).all()
            await db.execute(delete(VideoCollectorCapture).where(VideoCollectorCapture.device_id.in_(devices)))
            await db.execute(delete(VideoCollectorDevice).where(VideoCollectorDevice.device_id.in_(devices)))
            await db.execute(delete(TaskRecord).where(TaskRecord.id.in_(task_ids)))
            await db.execute(delete(Project).where(Project.uid.in_(uids)))
            await db.execute(text('DELETE FROM platform_model_calls WHERE run_id=:run'),{'run':run})
            await db.execute(text('DELETE FROM platform_request_metrics WHERE uid=ANY(:uids)'),{'uids':uids})
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(ids)))
            await db.execute(delete(AgentEnv).where(AgentEnv.uid.in_(uids)))
            await db.execute(delete(UserConfig).where(UserConfig.uid.in_(uids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
        storage=get_minio_client()
        for uid in uids:
            prefix=video_owner_prefix(uid)
            for obj in list(storage.client.list_objects(storage.KB_BUCKETS['documents'],prefix=prefix,recursive=True)):
                storage.client.remove_object(storage.KB_BUCKETS['documents'],obj.object_name)
            folder=global_user_data_dir(uid)
            assert folder.name==uid
            if folder.exists():shutil.rmtree(folder)
            shutil.rmtree(manifest_directory(uid),ignore_errors=True)
        for task in task_ids:
            for obj in list(storage.client.list_objects(storage.KB_BUCKETS['documents'],prefix='video-audio/'+task+'/',recursive=True)):
                storage.client.remove_object(storage.KB_BUCKETS['documents'],obj.object_name)
        outbox=Path('/app/outputs/model-call-outbox.db')
        if outbox.exists():
            with sqlite3.connect(outbox) as db:
                db.execute("DELETE FROM pending_model_calls WHERE json_extract(payload,'$.run_id')=?",(run,))
        async with pg_manager.get_async_session_context() as db:
            report['accounts_remaining']=await db.scalar(select(func.count()).select_from(User).where(User.id.in_(ids)))
        report['cleanup_recovery_note']='Source run deletion preserves capability versions; explicitly removed only the test owners versions before deleting their projects.'
        report['cleanup_errors_before_recovery']=report['cleanup_errors']
        report['cleanup_errors']=[]
        report['cleaned_task_ids']=task_ids
        report['test_owner_uids']=uids
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'accounts_remaining':report['accounts_remaining'],'capability_versions_verified_and_deleted':versions,'tasks_deleted':len(task_ids)}),flush=True)
    finally:await pg_manager.close()

asyncio.run(main())
