"""通过实际HTTP读取迁移资料、PDF、检索和旧报告，不输出正文或认证信息。"""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select, text, update
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils


async def main():
    pg_manager.initialize()
    uid = 'migration_verify_' + uuid4().hex[:12]
    kb = 'kb_zcfj9omke9'
    run = 'run-63cb44f5-53f4-4a04-a52f-6cfc17abd429'
    try:
        async with pg_manager.get_async_session_context() as db:
            department = await db.scalar(select(Department.id).limit(1))
            user = User(uid=uid, username=uid, password_hash='disabled-migration-verify', role='superadmin', department_id=department)
            db.add(user)
            await db.flush()
            token = AuthUtils.create_access_token({'sub': str(user.id)})
            await db.commit()
            count = await db.scalar(text('SELECT count(*) FROM knowledge_files WHERE kb_id=:kb AND is_folder=false'), {'kb':kb})
            assert count == 93, count
            file = (await db.execute(text("SELECT file_id,content_hash FROM knowledge_files WHERE kb_id=:kb AND file_type='pdf' AND is_folder=false ORDER BY file_size ASC NULLS LAST LIMIT 1"), {'kb':kb})).mappings().one()
            query = await db.scalar(text('SELECT content FROM knowledge_chunks WHERE kb_id=:kb ORDER BY id LIMIT 1'), {'kb':kb})
            assert query
        async with httpx.AsyncClient(base_url='http://127.0.0.1:5050', headers={'Authorization':'Bearer '+token}, timeout=120) as client:
            file_id = file['file_id']
            download = await client.get(f'/api/knowledge/databases/{kb}/documents/{file_id}/download')
            assert download.status_code == 200, download.status_code
            assert download.content.startswith(b'%PDF')
            if file['content_hash'] and len(file['content_hash']) == 64:
                assert hashlib.sha256(download.content).hexdigest() == file['content_hash']
            preview = await client.get('/api/workspace/knowledge/file', params={'kb_id':kb,'file_id':file_id})
            assert preview.status_code == 200, preview.status_code
            results = await client.post(f'/api/knowledge/databases/{kb}/query-test', json={'query':query[:120], 'meta':{}})
            assert results.status_code == 200, results.status_code
            payload = results.json()
            assert isinstance(payload,list) and payload, str(type(payload))
            report = await client.get(f'/api/equipment/runs/{run}/report')
            assert report.status_code == 200 and len(report.text) > 1000, report.status_code
            versions = await client.get(f'/api/equipment/runs/{run}/capability-versions')
            assert versions.status_code == 200
            version_rows = versions.json()['versions']
            formal = [row for row in version_rows if row.get('source') == 'formal_s6']
            assert 5 <= len(formal) <= 6, {'formal_count':len(formal)}
            new_run = 'run-ed464daf-f4af-4e2e-b008-bc0b9bbfeea8'
            new_report = await client.get(f'/api/equipment/runs/{new_run}/report')
            assert new_report.status_code == 200 and len(new_report.text) == 19932
            new_versions = (await client.get(f'/api/equipment/runs/{new_run}/capability-versions')).json()['versions']
            assert len(new_versions) == 6 and len({card['hypothesis_id'] for card in new_versions}) == 6
            result = {'migrated_technical_library_files':count,'original_pdf_download':'passed',
                      'original_pdf_bytes':len(download.content),'original_file_preview':'passed',
                      'existing_library_real_retrieval':'passed','retrieved_chunks':len(payload),
                      'migrated_report_characters':len(report.text),'migrated_capability_versions':len(version_rows),
                      'new_cloud_report_characters':len(new_report.text),'new_cloud_capability_versions':len(new_versions)}
            Path('/app/outputs/migration-20261026-business-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False))
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(update(User).where(User.uid==uid).values(is_deleted=1,password_hash='disabled-migration-verify'))
            await db.commit()
        await pg_manager.close()


asyncio.run(main())
