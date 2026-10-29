"""对照真实运行文件与 PostgreSQL，核实 S5 入选到正式画像的交付数量。"""

import asyncio
import json
from pathlib import Path
from sqlalchemy import select
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion, EquipmentResearchRun
from platform_core.services.equipment_research_task import resolve_research_workdir
from platform_core.services.equipment_capability_scoring import enrich_capabilities_with_s5_scores


async def main():
    pg_manager.initialize()
    results = []
    try:
        async with pg_manager.get_async_session_context() as db:
            for run_id in ('run-63cb44f5-53f4-4a04-a52f-6cfc17abd429', 'run-ed464daf-f4af-4e2e-b008-bc0b9bbfeea8'):
                run = await db.get(EquipmentResearchRun, run_id)
                rows = (await db.scalars(select(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.run_id == run_id))).all()
                cards = [dict(row.snapshot or {}) for row in rows]
                formal = [card for card in cards if card.get('source') == 'formal_s6']
                summary_path = resolve_research_workdir(run) / 'outputs' / 'equipment-research' / run_id / 'round_summary.json'
                summary = json.loads(summary_path.read_text())
                stages = summary.get('winning_mechanism', {}).get('stages', [])
                directions = [direction for stage in stages for direction in (stage.get('outputs') or {}).get('core_agent_concept_directions', [])]
                selected = {row['hypothesis_id']: row for row in directions if row.get('hypothesis_id') and row.get('s5_dimension_scores')}
                delivered = {card['hypothesis_id'] for card in formal}
                assert len(formal) == len(delivered) == 6
                assert set(selected) == delivered, {'s5_ids':sorted(selected), 'delivered_ids':sorted(delivered)}
                projected = enrich_capabilities_with_s5_scores(formal, summary)
                assert all(card['s5_dimension_scores'] == {key:round(float(value),4) for key,value in selected[card['hypothesis_id']]['s5_dimension_scores'].items()} for card in projected)
                results.append({'run_id': run_id, 'versions': len(cards), 'formal_cards': len(formal),
                    's5_selected':len(selected), 's5_to_formal_identity_and_scores':'passed',
                    'identities': [{'capability_id': card.get('capability_id'), 'hypothesis_id': card.get('hypothesis_id'), 'version_no': card.get('version_no'), 'has_s5_scores': bool(card.get('s5_dimension_scores'))} for card in formal],
                    'stages': [stage.get('stage_id') for stage in stages]})
        result_path = Path('/app/outputs/migration-20261026-research-result.json')
        if result_path.exists():
            result = json.loads(result_path.read_text())
            actual = next(row for row in results if row['run_id'] == result['run_id'])
            if result.get('capability_versions') != actual['versions']:
                result['previous_count_correction'] = {'previous': result['capability_versions'], 'reason':'此前误对响应对象的两个字段计数；改为 versions 数组逐项核实。'}
            result['capability_versions'] = actual['versions']
            result['formal_capabilities'] = actual['formal_cards']
            result['s5_to_formal_identity_and_scores'] = 'passed'
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        Path('/app/outputs/migration-20261026-s5-delivery.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(results, ensure_ascii=False))
    finally:
        await pg_manager.close()


asyncio.run(main())
