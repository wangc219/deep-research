"""校验云端源码、运行镜像和上线后的服务错误计数，不输出配置凭据。"""
from pathlib import Path
import json
import hashlib
import subprocess

root=Path('/opt/deep-research')
incoming=json.loads(Path('/tmp/source-manifest.json').read_text())
manifest_path=root/'acceptance-source-manifest.json'
manifest=json.loads(manifest_path.read_text())
for name,digest in incoming.items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
    manifest[name]=digest
manifest_path.write_text(json.dumps(manifest,indent=2))
paths={name.removeprefix('backend/'):digest for name,digest in incoming.items() if name.startswith('backend/package/')}
code="import sys,json,hashlib;from pathlib import Path;paths=json.loads(sys.argv[1]);print(json.dumps({p:hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest() for p in paths}))"
actual=json.loads(subprocess.check_output(['docker','exec','deepquest-api-1','python','-c',code,json.dumps(paths)],text=True))
assert actual==paths
names=['deepquest-api-1','deepquest-worker-1','deepquest-chat-worker-1','deepquest-deep-worker-1','deepquest-subagent-worker-1']
containers=json.loads(subprocess.check_output(['docker','inspect',*names],text=True))
assert len({row['Image'] for row in containers})==1
result={'source_files_verified':len(incoming),'runtime_files_verified':len(paths),'same_api_worker_image':True,
    'containers':[{'name':row['Name'],'health':row['State']['Health']['Status'],'oom':row['State']['OOMKilled'],'restarts':row['RestartCount']} for row in containers]}
assert all(row['health']=='healthy' and not row['oom'] for row in result['containers'])
logs=subprocess.check_output(['docker','logs','deepquest-api-1'],stderr=subprocess.STDOUT,text=True)
statuses=[]
for line in logs.splitlines():
    if '" ' not in line or 'HTTP/' not in line:continue
    value=line.rsplit('" ',1)[-1].split(' ',1)[0]
    if value.isdigit() and len(value)==3:statuses.append(int(value))
result['api_http_5xx_since_resource_fix']=sum(status>=500 for status in statuses)
result['api_http_requests_since_resource_fix']=len(statuses)
assert result['api_http_5xx_since_resource_fix']==0
print(json.dumps(result),flush=True)
