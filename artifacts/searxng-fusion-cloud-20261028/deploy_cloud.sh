#!/usr/bin/env bash
set -euo pipefail
umask 077

task_root=/opt/deep-research
backup="$(cat /tmp/searxng-fusion-backup-path)"
services=(api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker web)
worker_services=(worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker)

cd "$task_root"
exec 9>/var/lock/deepquest-searxng-fusion.lock
flock -n 9
test -d "$backup"

python3 - <<PY
from pathlib import Path
import hashlib,json,subprocess
base=json.loads(Path('$backup/images-before.json').read_text())
for service,row in base.items():
    current=json.loads(subprocess.check_output(['docker','inspect',row['container']]))[0]
    assert current['Image']==row['image_id'], f'Runtime image changed since prepare: {service}'
expected=json.loads(Path('$backup/source-manifest.json').read_text())
for name,digest in expected.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest, f'Prepared source changed: {name}'
assert subprocess.check_output(['docker','image','inspect','deepquest-api:searxng-fusion-candidate-20261028','--format','{{.Id}}'],text=True).strip()==Path('$backup/candidate-api-id').read_text().strip()
assert subprocess.check_output(['docker','image','inspect','deepquest-web:searxng-fusion-candidate-20261028','--format','{{.Id}}'],text=True).strip()==Path('$backup/candidate-web-id').read_text().strip()
print(json.dumps({'precutover_verified':True,'services':len(base)}))
PY

active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]

rollback() {
  trap - ERR
  echo '正式切换失败，恢复精确旧镜像、源码、环境与 manifest' >&2
  cd "$task_root"
  tar --no-same-owner -xzf "$backup/source-before.tar.gz"
  python3 - <<PY
from pathlib import Path
import json,subprocess
for name in json.loads(Path('$backup/absent-before.json').read_text()):
    path=Path(name)
    if path.is_file() or path.is_symlink(): path.unlink()
rows=json.loads(Path('$backup/images-before.json').read_text())
for service in ('api','web'):
    subprocess.run(['docker','tag',rows[service]['rollback_tag'],rows[service]['config_image']],check=True)
PY
  cp -p "$backup/env-before" .env.prod
  cp -p "$backup/acceptance-source-manifest-before.json" acceptance-source-manifest.json
  bash scripts/cloud.sh -f "$backup/rollback.yaml" up -d --no-deps --force-recreate --wait --wait-timeout 240 \
    worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker api web || true
  docker rm -f deepquest-searxng-1 >/dev/null 2>&1 || true
  rm -f /var/www/deepquest.maintenance
  curl -fsS --max-time 30 http://127.0.0.1:6050/api/system/ready > "$backup/rollback-ready.json" || true
  exit 1
}
trap rollback ERR

touch /var/www/deepquest.maintenance
active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]

bash scripts/cloud.sh stop -t 45 api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker web
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 searxng
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 \
  worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 web

curl -fsS --max-time 30 http://127.0.0.1:6050/api/system/ready > "$backup/ready-internal.json"
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 30 https://www.deepquest.space/api/system/ready > "$backup/ready-public.json"

docker exec -i deepquest-api-1 python - <<'PY' > "$backup/searxng-live-smoke.json"
import json,time
import httpx
started=time.monotonic()
r=httpx.post('http://searxng:8080/search',data={'q':'altermagnetism','format':'json','engines':'wikipedia,arxiv','language':'all','safesearch':'0'},timeout=10)
r.raise_for_status()
data=r.json()
print(json.dumps({'status':'ok','seconds':round(time.monotonic()-started,3),'results':len(data.get('results') or []),'unresponsive_engines':data.get('unresponsive_engines') or []}))
PY

python3 - <<PY
from pathlib import Path
import hashlib,json,subprocess
expected=json.loads(Path('$backup/source-manifest.json').read_text())
old=json.loads(Path('acceptance-source-manifest.json').read_text())
api_id=Path('$backup/candidate-api-runtime-id').read_text().strip()
web_id=Path('$backup/candidate-web-runtime-id').read_text().strip()
for name,digest in expected.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
for service in ('api','worker','chat-worker','deep-worker','subagent-worker','equipment-worker','equipment-query-worker'):
    info=json.loads(subprocess.check_output(['docker','inspect',f'deepquest-{service}-1']))[0]
    assert info['Image']==api_id,(service,info['Image'],api_id)
    assert info['State']['Running'],service
    if info['State'].get('Health'): assert info['State']['Health']['Status']=='healthy',service
web=json.loads(subprocess.check_output(['docker','inspect','deepquest-web-1']))[0]
assert web['Image']==web_id,(web['Image'],web_id)
searx=json.loads(subprocess.check_output(['docker','inspect','deepquest-searxng-1']))[0]
assert searx['State']['Health']['Status']=='healthy'
old.update(expected)
Path('acceptance-source-manifest.json').write_text(json.dumps(old,indent=2)+'\n')
report={'status':'deployed','api_image':api_id,'web_image':web_id,'source_files':len(expected),'searxng_image':searx['Image'],'backup':'$backup'}
Path('$backup/deploy-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
PY

trap - ERR
echo 'SearXNG fusion release healthy'
