"""冻结本地写入后，生成与架构无关的完整迁移快照。"""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path('/Users/wangchen/.codex/private-migrations/local-to-cloud-20261026')
SNAPSHOT = PRIVATE / 'snapshot'
SNAPSHOT.mkdir(mode=0o700, exist_ok=True)
names = ['equipmentresearch3-'+service+'-1' for service in ('api','worker','document-research','sandbox-provisioner','graph')]
containers = json.loads(subprocess.check_output(['docker','inspect',*names], text=True))
assert all(not c['State']['Running'] for c in containers)
api = containers[0]
runtime_env = PRIVATE / 'local-runtime.env'
values = api['Config']['Env']
assert all('\n' not in v for v in values)
runtime_env.write_text('\n'.join(values)+'\n')
runtime_env.chmod(0o600)
with (SNAPSHOT/'postgres.dump').open('wb') as output:
    subprocess.run(['docker','exec','equipmentresearch3-postgres-1','pg_dump','-U','postgres','-d','yuxi','-Fc'], stdout=output, check=True)
with (SNAPSHOT/'postgres.dump').open('rb') as source:
    subprocess.run(['docker','exec','-i','equipmentresearch3-postgres-1','pg_restore','-l'], stdin=source,
                   stdout=subprocess.DEVNULL, check=True)
subprocess.run(['docker','run','--rm','--name','deepquest-local-logical-export',
    '--user','0:0','--volumes-from','equipmentresearch3-api-1',
    '--network','equipmentresearch3_app-network','--env-file',str(runtime_env),
    '-v',str(SNAPSHOT)+':/migration','-v',str(ROOT/'artifacts/local-to-cloud-20261026/logical_payload.py')+':/tmp/logical_payload.py:ro',
    api['Config']['Image'],'python','/tmp/logical_payload.py','export','/migration/logical'], check=True)
(SNAPSHOT/'graph').mkdir(exist_ok=True)
subprocess.run(['docker','run','--rm','--name','deepquest-local-graph-export','--user','0:0',
    '--volumes-from','equipmentresearch3-graph-1','-v',str(SNAPSHOT/'graph')+':/migration',
    '--entrypoint','neo4j-admin',containers[-1]['Config']['Image'],
    'database','dump','neo4j','--to-path=/migration','--overwrite-destination=true'], check=True)
(SNAPSHOT/'document-research').mkdir(exist_ok=True)
subprocess.run(['docker','cp','equipmentresearch3-document-research-1:/var/lib/document-research/.',str(SNAPSHOT/'document-research')], check=True)
with (SNAPSHOT/'application-files.tar.gz').open('wb') as output:
    subprocess.run(['tar','-czf','-','--exclude=.DS_Store','-C',str(ROOT),'outputs',
                    '-C',str(ROOT/'docker/volumes/yuxi'),'threads','skill-sources','skill-projections'],stdout=output,check=True)
manifest = {}
for path in sorted(SNAPSHOT.rglob('*')):
    if path.is_file():
        with path.open('rb') as source:
            manifest[path.relative_to(SNAPSHOT).as_posix()] = {'size':path.stat().st_size,
                'sha256':hashlib.file_digest(source,'sha256').hexdigest()}
(SNAPSHOT/'snapshot-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
result = {'consistent_snapshot':'completed','data_source':'local','files':len(manifest),
          'bytes':sum(i['size'] for i in manifest.values()),'postgres_logical_dump_validated':True,
          'graph_format':'neo4j-admin dump','application_files':'outputs + active threads + skills',
          'private_location':str(SNAPSHOT)}
(ROOT/'artifacts/local-to-cloud-20261026/local-snapshot-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
