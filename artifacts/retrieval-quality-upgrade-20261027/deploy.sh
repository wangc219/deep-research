#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/retrieval-quality-20261027
exec 9>/var/lock/deepquest-retrieval-release.lock
flock -n 9
python3 - <<'PY'
from pathlib import Path
import json,subprocess,hashlib
backup=Path('/var/backups/deepquest/retrieval-quality-20261027')
images=json.loads((backup/'images.json').read_text())
for name,info in images.items():
 current=json.loads(subprocess.check_output(['docker','inspect','deepquest-'+name+'-1']))[0]
 assert current['Image']==info['id'], 'Runtime changed since preparation: '+name
manifest=json.loads(Path('/tmp/deepquest-retrieval-source-manifest.json').read_text())
candidate=json.loads(subprocess.check_output(['docker','inspect','deepquest-api:retrieval-candidate-20261027']))[0]['Id']
(backup/'candidate-image-id').write_text(candidate)
old=json.loads(Path('acceptance-source-manifest.json').read_text())
for name in manifest:
 if name in old:assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==old[name],name
(backup/'absent-before.json').write_text(json.dumps([name for name in manifest if not Path(name).exists()]))
lines=['services:']
for name in images:lines.extend(['  '+name+':','    image: deepquest-api:before-retrieval-'+name+'-20261027'])
(backup/'rollback.yaml').write_text('\n'.join(lines)+'\n')
PY
docker exec -i deepquest-api-1 python < /tmp/deepquest-retrieval-drain-check.py
cp -p acceptance-source-manifest.json "$backup/manifest-before.json"
cp -p .env.prod "$backup/env-before"
rollback() {
 trap - ERR
 echo 'Release failed; restoring exact previous service images and sources' >&2
 tar --no-same-owner -xzf "$backup/source-final-before.tar.gz"
 python3 - <<'PY'
from pathlib import Path
import json
for name in json.loads(Path('/var/backups/deepquest/retrieval-quality-20261027/absent-before.json').read_text()):Path(name).unlink(missing_ok=True)
PY
 cp -p "$backup/manifest-before.json" acceptance-source-manifest.json
 if [[ -n "${api_tag:-}" ]]; then docker tag deepquest-api:before-retrieval-api-20261027 "$api_tag"; fi
 bash scripts/cloud.sh -f "$backup/rollback.yaml" up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
 rm -f /var/www/deepquest.maintenance
 exit 1
}
trap rollback ERR
touch /var/www/deepquest.maintenance
docker exec -i deepquest-api-1 python < /tmp/deepquest-retrieval-drain-check.py
bash scripts/cloud.sh stop -t 45 api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
tar --no-same-owner -xzf /tmp/deepquest-retrieval-source.tar.gz
api_tag=$(docker inspect deepquest-api-1 --format '{{.Config.Image}}')
docker tag deepquest-api:retrieval-candidate-20261027 "$api_tag"
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api
python3 - <<'PY'
from pathlib import Path
import json,hashlib,subprocess
backup=Path('/var/backups/deepquest/retrieval-quality-20261027')
new=json.loads(Path('/tmp/deepquest-retrieval-source-manifest.json').read_text());old=json.loads(Path('acceptance-source-manifest.json').read_text())
for name,digest in new.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
candidate=(backup/'candidate-image-id').read_text()
services=json.loads((backup/'images.json').read_text())
for name in services:
 info=json.loads(subprocess.check_output(['docker','inspect','deepquest-'+name+'-1']))[0]
 assert info['Image']==candidate, name+' did not adopt candidate'
 assert info['State']['Running'],name
 if 'Health' in info['State']:assert info['State']['Health']['Status']=='healthy',name
old.update(new);Path('acceptance-source-manifest.json').write_text(json.dumps(old,indent=2))
print(json.dumps({'deployed_services':list(services),'verified_source_files':len(new),'image':candidate}))
PY
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 20 https://www.deepquest.space/api/system/ready > "$backup/ready-after.json"
trap - ERR
echo 'Retrieval release healthy'
