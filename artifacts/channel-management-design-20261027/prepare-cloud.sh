#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/channel-management-design-20261027
mkdir -p "$backup" /tmp/channel-management-design-release
chmod 700 "$backup"
cp /tmp/source-manifest.json "$backup/release-manifest.json"
python3 - <<'PY'
from pathlib import Path
import tarfile,json,hashlib
root=Path('/opt/deep-research');backup=Path('/var/backups/deepquest/channel-management-design-20261027')
new=json.loads(Path('/tmp/source-manifest.json').read_text())
old=json.loads((root/'acceptance-source-manifest.json').read_text())
existing=[];new_files=[]
for name in new:
 p=root/name
 if not p.exists():new_files.append(name);continue
 digest=hashlib.sha256(p.read_bytes()).hexdigest()
 if name in old:assert old[name]==digest,'Cloud source drift: '+name
 existing.append(name)
with tarfile.open(backup/'source-before.tar.gz','w:gz') as archive:
 for name in existing:archive.add(root/name,arcname=name)
(backup/'new-files.json').write_text(json.dumps(new_files))
with tarfile.open('/tmp/source.tar.gz') as archive:archive.extractall('/tmp/channel-management-design-release',filter='data')
for name,digest in new.items():assert hashlib.sha256((Path('/tmp/channel-management-design-release')/name).read_bytes()).hexdigest()==digest
print(json.dumps({'verified_files':len(new),'new_files':len(new_files)}))
PY
docker tag "$(docker inspect deepquest-api-1 --format '{{.Image}}')" deepquest-api:before-channel-management-design-20261027
docker tag "$(docker inspect deepquest-web-1 --format '{{.Image}}')" deepquest-web:before-channel-management-design-20261027
python3 - <<'PY'
from pathlib import Path
import json,subprocess
info=json.loads(subprocess.check_output(['docker','inspect','deepquest-api-1']))[0]
p=Path('/var/backups/deepquest/channel-management-design-20261027/runtime.env')
p.write_text('\n'.join(info['Config']['Env'])+'\n');p.chmod(0o600)
Path('/var/backups/deepquest/channel-management-design-20261027/network').write_text(next(iter(info['NetworkSettings']['Networks'])))
root=Path('/tmp/channel-management-design-release')
manifest=json.loads(Path('/tmp/source-manifest.json').read_text())
lines=['FROM deepquest-api:before-channel-management-design-20261027']
for name in manifest:
 if name.startswith('backend/'):lines.append('COPY '+name+' /app/'+name.removeprefix('backend/'))
(root/'Dockerfile.api').write_text('\n'.join(lines)+'\n')
PY
docker build -q -t deepquest-api:channel-management-candidate-20261027 -f /tmp/channel-management-design-release/Dockerfile.api /tmp/channel-management-design-release
network=$(cat "$backup/network")
docker run --rm --network "$network" --env-file "$backup/runtime.env" --volumes-from deepquest-api-1 -e PYTHONPATH=/app/package deepquest-api:channel-management-candidate-20261027 uv run --no-sync --group test pytest -o cache_dir=/tmp/channel-tests test/unit/services/test_wxchannels_service.py test/unit/services/test_video_collector_package.py test/integration/services/test_wechat_channel_repository.py test/integration/services/test_video_collector_repository.py -q --disable-warnings
