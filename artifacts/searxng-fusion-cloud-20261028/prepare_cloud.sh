#!/usr/bin/env bash
set -euo pipefail
umask 077

task_root=/opt/deep-research
release_id=searxng-fusion-20261028
backup=/var/backups/deepquest/${release_id}-$(date +%H%M%S)
services=(api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker web)
candidate_container=

cd "$task_root"
exec 9>/var/lock/deepquest-searxng-fusion.lock
flock -n 9

python3 - <<'PY'
from pathlib import Path
import hashlib, json

expected = Path('/tmp/searxng-source.tar.gz.sha256').read_text().strip()
actual = hashlib.sha256(Path('/tmp/searxng-source.tar.gz').read_bytes()).hexdigest()
assert actual == expected, (actual, expected)
base = json.loads(Path('/tmp/searxng-cloud-base-manifest.json').read_text())
for name, digest in base.items():
    path = Path(name)
    if digest is None:
        assert not path.exists(), f'Expected absent before release: {name}'
    else:
        assert path.is_file(), f'Missing baseline file: {name}'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f'Baseline changed: {name}'
print(json.dumps({'source_archive_verified': True, 'baseline_entries': len(base)}))
PY

active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]

test ! -e "$backup"
mkdir -p "$backup"
chmod 700 "$backup"
printf '%s\n' "$backup" > /tmp/searxng-fusion-backup-path
cp -p .env.prod "$backup/env-before"
cp -p acceptance-source-manifest.json "$backup/acceptance-source-manifest-before.json"
cp -p /tmp/searxng-cloud-base-manifest.json "$backup/cloud-base-manifest.json"
cp -p /tmp/searxng-source-manifest.json "$backup/source-manifest.json"
cp -p /tmp/searxng-source.tar.gz.sha256 "$backup/source.tar.gz.sha256"

python3 - <<'PY'
from pathlib import Path
import json

base = json.loads(Path('/tmp/searxng-cloud-base-manifest.json').read_text())
present = [name for name, digest in base.items() if digest is not None]
absent = [name for name, digest in base.items() if digest is None]
Path('/tmp/searxng-present-files.txt').write_text('\n'.join(present) + '\n')
Path('/tmp/searxng-absent-files.json').write_text(json.dumps(absent, indent=2) + '\n')
PY
tar -czf "$backup/source-before.tar.gz" -T /tmp/searxng-present-files.txt
cp -p /tmp/searxng-absent-files.json "$backup/absent-before.json"

python3 - <<'PY'
from pathlib import Path
import json, subprocess

services = ['api', 'worker', 'chat-worker', 'deep-worker', 'subagent-worker', 'equipment-worker', 'equipment-query-worker', 'web']
rows = {}
rollback = ['services:']
rollback_sources = {}
for service in services:
    name = f'deepquest-{service}-1'
    info = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    tag = f'deepquest-rollback-{service}:searxng-fusion-20261028'
    source = rollback_sources.get(info['Image'])
    if source is None:
        inspect = subprocess.run(['docker', 'image', 'inspect', info['Image']], capture_output=True)
        if inspect.returncode == 0:
            source = info['Image']
        else:
            source = f'deepquest-runtime-snapshot:{service}-searxng-fusion-20261028'
            snapshot = subprocess.run(['docker', 'image', 'inspect', source], capture_output=True)
            if snapshot.returncode != 0:
                changes = [
                    'ENTRYPOINT ' + json.dumps(info['Config'].get('Entrypoint') or []),
                    'CMD ' + json.dumps(info['Config'].get('Cmd') or []),
                    'WORKDIR ' + str(info['Config'].get('WorkingDir') or '/app'),
                    'USER ' + str(info['Config'].get('User') or '1000:1000'),
                    'ENV HOME=/home/platform',
                    'ENV RAPIDOCR_MODEL_DIR=/home/platform/.cache/rapidocr/models',
                    'ENV PLAYWRIGHT_BROWSERS_PATH=/opt/wechat-mp-browsers',
                    'ENV UV_PROJECT_ENVIRONMENT=/usr/local',
                    'ENV TZ=Asia/Shanghai',
                ]
                exporter = subprocess.Popen(['docker', 'export', name], stdout=subprocess.PIPE)
                importer = ['docker', 'import']
                for change in changes:
                    importer.extend(['--change', change])
                imported = subprocess.run([*importer, '-', source], stdin=exporter.stdout)
                if exporter.stdout:
                    exporter.stdout.close()
                export_status = exporter.wait()
                if export_status or imported.returncode:
                    raise subprocess.CalledProcessError(export_status or imported.returncode, importer)
        rollback_sources[info['Image']] = source
    subprocess.run(['docker', 'tag', source, tag], check=True)
    rows[service] = {'container': name, 'image_id': info['Image'], 'config_image': info['Config']['Image'], 'rollback_tag': tag}
    rollback.extend([f'  {service}:', f'    image: {tag}'])
Path('/var/backups/deepquest/' + Path('/tmp/searxng-fusion-backup-path').read_text().strip().split('/')[-1] + '/images-before.json').write_text(json.dumps(rows, indent=2) + '\n')
Path('/var/backups/deepquest/' + Path('/tmp/searxng-fusion-backup-path').read_text().strip().split('/')[-1] + '/rollback.yaml').write_text('\n'.join(rollback) + '\n')
PY

restore_prepare() {
  trap - ERR
  echo '候选准备失败，恢复发布前源码、环境和镜像标签' >&2
  cd "$task_root"
  tar --no-same-owner -xzf "$backup/source-before.tar.gz"
  python3 - <<PY
from pathlib import Path
import json
for name in json.loads(Path('$backup/absent-before.json').read_text()):
    path = Path(name)
    if path.is_file() or path.is_symlink():
        path.unlink()
PY
  cp -p "$backup/env-before" .env.prod
  cp -p "$backup/acceptance-source-manifest-before.json" acceptance-source-manifest.json
  if [[ -n "$candidate_container" ]]; then
    docker rm -f "$candidate_container" >/dev/null 2>&1 || true
  fi
  python3 - <<PY
from pathlib import Path
import json, subprocess
rows=json.loads(Path('$backup/images-before.json').read_text())
for service in ('api','web'):
    subprocess.run(['docker','tag',rows[service]['rollback_tag'],rows[service]['config_image']],check=True)
PY
  docker rm -f deepquest-searxng-1 >/dev/null 2>&1 || true
  exit 1
}
trap restore_prepare ERR

tar --no-same-owner -xzf /tmp/searxng-source.tar.gz
bash scripts/migrate-environment.sh .env.prod
python3 - <<'PY'
from pathlib import Path
values = {}
for line in Path('.env.prod').read_text().splitlines():
    if line and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key] = value
assert values.get('SEARXNG_SECRET', '').strip(), 'SEARXNG_SECRET was not generated'
assert values.get('SEARXNG_URL', 'http://searxng:8080') == 'http://searxng:8080'
print('searxng_environment_ready=true')
PY
bash scripts/cloud.sh config --quiet
bash scripts/cloud.sh pull searxng
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 searxng

compose_config="$(bash scripts/cloud.sh config --format json)"
api_tag="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["api"]["image"])' <<<"$compose_config")"
web_tag="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["web"]["image"])' <<<"$compose_config")"
bash scripts/cloud.sh build api
candidate_api_id="$(docker image inspect "$api_tag" --format '{{.Id}}')"
docker tag "$candidate_api_id" deepquest-api:searxng-fusion-candidate-20261028
printf '%s\n' "$candidate_api_id" > "$backup/candidate-api-id"
candidate_api_probe="$(docker create --entrypoint /bin/true deepquest-api:searxng-fusion-candidate-20261028)"
docker inspect "$candidate_api_probe" --format '{{.Image}}' > "$backup/candidate-api-runtime-id"
docker rm "$candidate_api_probe" >/dev/null

bash scripts/cloud.sh build web
candidate_web_id="$(docker image inspect "$web_tag" --format '{{.Id}}')"
docker tag "$candidate_web_id" deepquest-web:searxng-fusion-candidate-20261028
printf '%s\n' "$candidate_web_id" > "$backup/candidate-web-id"
candidate_web_probe="$(docker create --entrypoint /bin/true deepquest-web:searxng-fusion-candidate-20261028)"
docker inspect "$candidate_web_probe" --format '{{.Image}}' > "$backup/candidate-web-runtime-id"
docker rm "$candidate_web_probe" >/dev/null

bash scripts/cloud.sh run --rm --no-deps \
  -v /opt/deep-research/backend/test:/app/test:ro \
  api python -m pytest -q \
  test/unit/services/test_searxng_service.py \
  test/unit/services/test_web_search_coordinator.py \
  test/unit/agents/test_parallel_research_search.py \
  test/unit/agents/test_search_resilience.py \
  test/unit/agents/test_web_search_provider.py \
  test/unit/config/test_open_websearch_compose.py \
  test/unit/config/test_options.py \
  test/unit/middlewares/test_academic_evidence.py \
  test/equipment_deep_research/unit/test_query_domain_contract.py | tee "$backup/candidate-tests.log"

candidate_container=deepquest-searxng-candidate-api
docker rm -f "$candidate_container" >/dev/null 2>&1 || true
bash scripts/cloud.sh run -d --no-deps --name "$candidate_container" api >/dev/null
for attempt in $(seq 1 90); do
  if docker exec "$candidate_container" python -c \
    "import httpx; r=httpx.get('http://127.0.0.1:5050/api/system/health',timeout=3); r.raise_for_status()" \
    >/dev/null 2>&1
  then
    break
  fi
  if [[ "$attempt" = 90 ]]; then
    docker logs "$candidate_container" --tail 100
    exit 1
  fi
  sleep 2
done
docker exec -i "$candidate_container" python - <<'PY' | tee "$backup/candidate-api-smoke.json"
import asyncio,json
import httpx
from sqlalchemy import select
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.utils.auth_utils import AuthUtils

async def main():
    async with pg_manager.get_async_session_context() as db:
        user=await db.scalar(select(User).where(User.role.in_(['superadmin','admin'])).order_by(User.id).limit(1))
        assert user is not None
        token=AuthUtils.create_access_token({'sub':str(user.id)})
    headers={'Authorization':'Bearer '+token}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:5050',timeout=20) as client:
        health=await client.get('/api/system/health')
        ready=await client.get('/api/system/ready')
        openapi=await client.get('/openapi.json')
        search=await client.post('/api/system/web-search/test',headers=headers)
    assert health.status_code==200,health.text
    assert ready.status_code==200,ready.text
    assert '/api/system/web-search/test' in openapi.json()['paths']
    assert search.status_code==200,search.text
    payload=search.json()
    assert payload['container_status']=='ok',payload
    print(json.dumps({'health':health.json()['status'],'ready':ready.json()['status'],'web_search_test':payload},ensure_ascii=False))

asyncio.run(main())
PY
docker rm -f "$candidate_container" >/dev/null
candidate_container=

bash scripts/cloud.sh run --rm --no-deps \
  -v /tmp/evaluate_three_channel.py:/app/evaluate_three_channel.py:ro \
  api python /app/evaluate_three_channel.py | tee "$backup/candidate-quality.jsonl"

python3 - <<PY
from pathlib import Path
import json
lines=Path('$backup/candidate-quality.jsonl').read_text().splitlines()
reports=[json.loads(line)['final_report'] for line in lines if line.startswith('{') and '"final_report"' in line]
assert len(reports)==1
summary=reports[0]['summary']
assert summary['all_three_attempted'] is True, summary
assert summary['hard_constraint_leaks']==0, summary
assert summary['total_unique_candidates']>0, summary
print(json.dumps({'candidate_gate':'passed','summary':summary},ensure_ascii=False))
PY

python3 - <<PY
from pathlib import Path
import json
report={
  'status':'prepared',
  'backup':'$backup',
  'candidate_api_id':Path('$backup/candidate-api-id').read_text().strip(),
  'candidate_web_id':Path('$backup/candidate-web-id').read_text().strip(),
  'searxng_health':json.loads(__import__('subprocess').check_output(['docker','inspect','deepquest-searxng-1']))[0]['State'].get('Health',{}).get('Status'),
}
Path('$backup/prepare-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
PY
trap - ERR

