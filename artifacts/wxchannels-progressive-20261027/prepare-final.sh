#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/wxchannels-progressive-20261027
mkdir -p "$backup" /var/tmp/deepquest-wxchannels-progressive/candidate
chmod 700 "$backup"
python3 - <<'PY'
from pathlib import Path
import json,tarfile,hashlib,subprocess
root=Path('/opt/deep-research');backup=Path('/var/backups/deepquest/wxchannels-progressive-20261027')
new=json.loads(Path('/tmp/deepquest-wxchannels-progressive-source-manifest.json').read_text());old=json.loads((root/'acceptance-source-manifest.json').read_text())
with tarfile.open(backup/'source-before.tar.gz','w:gz') as archive:
 for name in new:
  p=root/name
  if not p.exists():continue
  if name in old:assert hashlib.sha256(p.read_bytes()).hexdigest()==old[name],name
  archive.add(p,arcname=name)
with tarfile.open('/tmp/deepquest-wxchannels-progressive-source.tar.gz') as archive:archive.extractall('/var/tmp/deepquest-wxchannels-progressive/candidate',filter='data')
for name,digest in new.items():assert hashlib.sha256((Path('/var/tmp/deepquest-wxchannels-progressive/candidate')/name).read_bytes()).hexdigest()==digest
info=json.loads(subprocess.check_output(['docker','inspect','deepquest-api-1']))[0]
p=backup/'runtime.env';p.write_text('\n'.join(info['Config']['Env'])+'\n');p.chmod(0o600)
(backup/'network').write_text(next(iter(info['NetworkSettings']['Networks'])))
lines=['FROM deepquest-api:before-progressive-20261027']
for name in new:
 if name.startswith('backend/'):lines.append('COPY '+name+' /app/'+name.removeprefix('backend/'))
Path('/var/tmp/deepquest-wxchannels-progressive/candidate/Dockerfile').write_text('\n'.join(lines)+'\n')
PY
docker tag "$(docker inspect deepquest-api-1 --format '{{.Image}}')" deepquest-api:before-progressive-20261027
docker build -q -t deepquest-api:progressive-candidate-20261027 /var/tmp/deepquest-wxchannels-progressive/candidate
