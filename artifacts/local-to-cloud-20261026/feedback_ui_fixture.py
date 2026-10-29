"""为真实页面验收建立可清理的合成画像，所有反馈均经 HTTP 写入。"""

import asyncio
import json
import sys
import httpx
from sqlalchemy import select, delete
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Project, User
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion, EquipmentResearchRun
from platform_core.utils.auth_utils import AuthUtils


async def main():
    scope = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else 'seed'
    assert scope in {'local', 'cloud'} and action in {'seed', 'cleanup', 'append', 'verify', 'rollback', 'rollback_latest'}
    prefix = 'feedback-ui-' + scope + '-20261026'
    run_id, version_id = prefix + '-run', prefix + '-version'
    dimensions = ('innovation', 'demand', 'feasibility', 'effectiveness', 'development')
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(select(User).where(User.username == 'Hitsz504', User.is_deleted == 0))
            assert user is not None
            token = AuthUtils.create_access_token({'sub': str(user.id)})
            if action == 'cleanup':
                await db.execute(delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.id == version_id))
                await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.id == run_id))
                await db.execute(delete(Project).where(Project.id == prefix))
                await db.commit()
                print(json.dumps({'synthetic_fixture_removed': prefix}))
                return
            if action == 'seed':
                assert await db.get(Project, prefix) is None
                db.add(Project(id=prefix, uid=user.uid, name='合成反馈页面验收（测试后清理）', selection_status='selectable', directory_mode='managed', workdir_path=prefix, status='active'))
                await db.flush()
                db.add(EquipmentResearchRun(id=run_id, project_id=prefix, owner_uid=user.uid, topic='合成验收：民用应急照明反馈，不代表真实研究结论', research_route='auto', status='draft', payload={}))
                await db.flush()
                db.add(EquipmentCapabilityVersion(id=version_id, project_id=prefix, owner_uid=user.uid, run_id=run_id,
                    snapshot={'capability_id':'feedback-test-card', 'hypothesis_id':prefix+'-candidate', 'name':'合成验收：民用应急照明画像', 'version_no':1, 'source':'formal_s6', 'status':'formal', 'overview':'此卡仅用于反馈显示、排序和回滚验收，不属于真实模型研究成果。', 's5_dimension_scores':dict.fromkeys(dimensions,0.6)}))
                await db.commit()
        async with httpx.AsyncClient(base_url='http://127.0.0.1:5050', headers={'Authorization':'Bearer '+token}, timeout=30) as client:
            base = f'/api/equipment/runs/{run_id}/expert-feedback'
            if action in {'seed', 'append'}:
                labels = [f'合成验收记录 {index}：请补充民用照明的可验证证据，不作为实际专家评价。' for index in range(1,5)] if action == 'seed' else ['合成验收：第二终端新增记录，验证自动同步，不作为实际专家评价。']
                for comment in labels:
                    response = await client.post(base, json={'capability_id':'feedback-test-card', 'capability_version_id':version_id, 'comment':comment, 'verdict':'needs_revision', 'expert_dimension_scores':dict.fromkeys(dimensions,0.8), 'rubric_feedback':{'innovation':'合成建议：补充与既有自检方案的差异证据。'}, 'target_agent_ids':['S5'], 'stage_scope':['S5']})
                    assert response.status_code == 200, (response.status_code, response.text[:300])
            response = await client.get(base, params={'include_rolled_back':'true'})
            assert response.status_code == 200
            rows = response.json()
            if action in {'rollback', 'rollback_latest'}:
                target=rows[0] if action=='rollback_latest' else rows[-1]
                response = await client.post(base+'/'+target['feedback_id']+'/rollback', json={'reason':'按用户确认完成合成反馈回滚，验证审计保留，不作为实际专家评价。'})
                assert response.status_code == 200, response.text[:300]
                rows = (await client.get(base, params={'include_rolled_back':'true'})).json()
            assert len(rows) >= 4
            print(json.dumps({'scope':scope, 'run_id':run_id, 'feedback_count':len(rows), 'rolled_back':sum(row.get('status')=='rolled_back' for row in rows), 'latest_comment':rows[0]['comment'], 'utc_timestamps':all(row['created_at'].endswith('Z') for row in rows)},ensure_ascii=False))
    finally:
        await pg_manager.close()


asyncio.run(main())
