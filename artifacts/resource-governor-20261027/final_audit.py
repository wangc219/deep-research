"""输出最终资源、部署与站点健康事实；不输出任何环境凭据。"""
import hashlib
import json
import subprocess
from pathlib import Path
from datetime import datetime, UTC

root=Path('/opt/deep-research')
manifest=json.loads(Path('/tmp/source-manifest.json').read_text())
for name,digest in manifest.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
runtime={name.removeprefix('backend/'):digest for name,digest in manifest.items() if name.startswith(('backend/package/','backend/server/'))}
code="import json,sys,hashlib;from pathlib import Path;x=json.loads(sys.argv[1]);print(json.dumps({p:hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest() for p in x}))"
actual=json.loads(subprocess.check_output(['docker','exec','deepquest-api-1','python','-c',code,json.dumps(runtime)],text=True))
assert actual==runtime
names=subprocess.check_output(['docker','ps','-q'],text=True).split()
containers=json.loads(subprocess.check_output(['docker','inspect',*names],text=True))
assert all(row['Config']['Labels'].get('com.docker.compose.project')=='deepquest' for row in containers)
services=[]
for row in containers:
    cfg=row['HostConfig']
    services.append({'name':row['Name'],'project':row['Config']['Labels'].get('com.docker.compose.project'),
        'health':row['State'].get('Health',{}).get('Status'),'oom':row['State']['OOMKilled'],'restarts':row['RestartCount'],
        'cpu_quota':cfg['CpuQuota'],'nano_cpus':cfg['NanoCpus'],'memory_limit':cfg['Memory']})
scope=json.loads(Path('/tmp/qagov-audit-scope.json').read_text())
since=datetime.fromtimestamp(scope['test_started_epoch'],UTC).isoformat()
logs=subprocess.check_output(['docker','logs','--since',since,'deepquest-api-1'],stderr=subprocess.STDOUT,text=True)
statuses=[]
for line in logs.splitlines():
    if '" ' not in line or 'HTTP/' not in line:continue
    value=line.rsplit('" ',1)[-1].split(' ',1)[0]
    if len(value)==3 and value.isdigit():statuses.append(int(value))
ready=json.loads(subprocess.check_output(['curl','-fsS','--max-time','15','https://www.deepquest.space/api/system/ready'],text=True))
assert ready['status']=='ready' and not ready['degraded']
memory={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:','MemFree:','Buffers:','Cached:','SwapTotal:','SwapFree:'))}
result={'runtime_files_verified':len(runtime),'source_files_verified':len(manifest),'project_container_count':len(services),'only_one_business_project':True,
    'services':services,'api_requests_during_acceptance':len(statuses),'api_5xx_during_acceptance':sum(status>=500 for status in statuses),
    'readiness':ready['status'],'memory_mib':{key:round(value/1024,1) for key,value in memory.items()},
    'budget':json.loads((root/'outputs/runtime/resource-budget.json').read_text())}
assert result['api_5xx_during_acceptance']==0
print(json.dumps(result),flush=True)
