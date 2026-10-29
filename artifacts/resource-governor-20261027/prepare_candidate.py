"""备份并验证候选镜像、轻量健康检查和真实 PostgreSQL 容量场景。"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

root = Path('/opt/deep-research')
backup = Path('/var/backups/deepquest/resource-governor-20261027')
backup.mkdir(parents=True, mode=0o700, exist_ok=True)
incoming = json.loads(Path('/tmp/source-manifest.json').read_text())
manifest = json.loads((root/'acceptance-source-manifest.json').read_text())
assert not (backup/'source-before.tar.gz').exists(), 'Preserve first backup'
with tarfile.open(backup/'source-before.tar.gz','w:gz') as out:
    for name in incoming:
        path = root/name
        if path.exists():
            if name in manifest:assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest[name],name
            out.add(path,arcname=name)
shutil.copy2(root/'.env.prod',backup/'env.prod-before')
(backup/'env.prod-before').chmod(0o600)
stage = Path('/tmp/resource-governor-candidate')
stage.mkdir(exist_ok=True)
with tarfile.open('/tmp/release.tar.gz') as archive:archive.extractall(stage)
test = Path('backend/test/integration/services/test_durable_task_repository.py')
(stage/test).parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(root/test,stage/test)
api = json.loads(subprocess.check_output(['docker','inspect','deepquest-api-1'],text=True))[0]
subprocess.run(['docker','tag',api['Image'],'deepquest-api:before-resource-governor-20261027'],check=True)
(stage/'Dockerfile').write_text('FROM deepquest-api:before-resource-governor-20261027\nCOPY --chown=1000:1000 backend/package/platform_core/ /app/package/platform_core/\nCOPY --chown=1000:1000 backend/server/ /app/server/\nCOPY backend/test/ /app/test/\n')
with (backup/'build.log').open('w') as stream:
    subprocess.run(['docker','build','--pull=false','-t','deepquest-api:resource-governor-candidate-20261027',str(stage)],stdout=stream,stderr=subprocess.STDOUT,check=True)
env=dict(value.split('=',1) for value in api['Config']['Env'])
keys={'POSTGRES_URL','REDIS_URL','PYTHONPATH','JWT_SECRET_KEY','API_KEY_DERIVATION_SECRET'}
envfile=Path('/tmp/resource-governor-test.env')
envfile.write_text('\n'.join(key+'='+value for key,value in env.items() if key in keys)+'\n')
envfile.chmod(0o600)
network=next(iter(api['NetworkSettings']['Networks']))
base=['docker','run','--rm','--user','0','--network',network,'--env-file',str(envfile),'--entrypoint','python','deepquest-api:resource-governor-candidate-20261027']
try:
    subprocess.run([*base,'-m','pytest','/app/test/unit/services/test_resource_budget.py','/app/test/unit/server/test_worker_health.py',
        '/app/test/integration/services/test_durable_task_repository.py::test_durable_capacity_reserves_worker_slots_for_agent_runs',
        '/app/test/integration/services/test_durable_task_repository.py::test_research_capacity_is_atomic_across_concurrent_claims',
        '/app/test/integration/services/test_durable_task_repository.py::test_generic_capacity_is_shared_and_atomic_for_mixed_types',
        '-q','--tb=short','-c','/app/pyproject.toml','-o','cache_dir=/tmp/governor-tests'],check=True)
    started=time.monotonic()
    old=subprocess.run(['docker','exec','deepquest-worker-1','arq','--check','server.worker_main.WorkerSettings'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    old_seconds=time.monotonic()-started
    started=time.monotonic()
    subprocess.run([*base,'-m','server.worker_health'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
    new_seconds=time.monotonic()-started
finally:envfile.unlink(missing_ok=True)
graph=json.loads(subprocess.check_output(['docker','inspect','deepquest-graph-1'],text=True))[0]
old_command=graph['Config']['Healthcheck']['Test'][1]
new_command=json.loads(Path('/tmp/graph-health-command.json').read_text())
times=[]
for command in [old_command,new_command]:
    started=time.monotonic()
    result=subprocess.run(['docker','exec','deepquest-graph-1','sh','-c',command],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    assert result.returncode==0,'Graph query health check failed'
    times.append(round(time.monotonic()-started,3))
result={'worker_old_check_seconds':round(old_seconds,3),'worker_old_check_exit_code':old.returncode,'worker_new_check_seconds_including_container_start':round(new_seconds,3),
    'graph_old_query_check_seconds':times[0],'graph_new_query_check_seconds':times[1]}
(root/'outputs/resource-governor-health-benchmark.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
