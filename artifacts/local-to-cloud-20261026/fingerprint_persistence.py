"""只记录关键业务表的行数与指纹，用于容器冷重建前后对照。"""

import hashlib
import json
import os
import sys
from pathlib import Path
import psycopg
from psycopg import sql

stage=sys.argv[1]
assert stage in {'before','after'}
tables=('projects','equipment_research_runs','equipment_capability_versions','equipment_expert_feedback',
        'equipment_deep_sessions','equipment_queries','knowledge_files','knowledge_chunks')
uri=os.environ['POSTGRES_URL'].replace('+asyncpg','').replace('+psycopg','')
result={}
with psycopg.connect(uri) as db:
    for table in tables:
        count=0
        digest=hashlib.sha256()
        with db.cursor(name='persistence_'+table) as cursor:
            cursor.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY id').format(sql.Identifier(table)))
            for row in cursor:
                digest.update(json.dumps(json.loads(row[0]),sort_keys=True,ensure_ascii=False).encode()+b'\n')
                count+=1
        result[table]={'rows':count,'sha256':digest.hexdigest()}
path=Path('/app/outputs/migration-20261026-persistence-'+stage+'.json')
path.write_text(json.dumps(result,indent=2)+'\n')
if stage=='after':
    before=json.loads(path.with_name('migration-20261026-persistence-before.json').read_text())
    assert result==before, {'changed_tables':[table for table in tables if before[table]!=result[table]]}
print(json.dumps({'stage':stage,'tables':result,'unchanged':stage=='after'}))
