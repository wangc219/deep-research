#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
exec 9>/var/lock/deepquest-default-workbench-deploy.lock
flock -n 9
python3 - <<'PY'
import hashlib,json,tarfile
from pathlib import Path
root=Path('/opt/deep-research')
archive=Path('/tmp/deepquest-default-workbench-source-20261026.tar.gz')
expected=Path('/tmp/deepquest-default-workbench-source-20261026.sha256').read_text().split()[0]
assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
with tarfile.open(archive) as package:
    manifest=json.load(package.extractfile('acceptance-source-manifest.json'))
    for member in package:
        assert member.name in manifest or member.name=='acceptance-source-manifest.json'
        assert (root/member.name).resolve().is_relative_to(root)
    package.extractall(root,filter='data')
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in manifest.items())
print(json.dumps({'verified_source_files':len(manifest),'archive_sha256':expected}))
PY
DEEP_RESEARCH_VERSION=optimized-local-20261026-default-workbench bash scripts/cloud.sh build api web
python3 - <<'PY'
from pathlib import Path
p=Path('.env.prod')
lines=[s for s in p.read_text().splitlines() if not s.startswith('DEEP_RESEARCH_VERSION=')]
p.write_text('\n'.join(lines)+'\nDEEP_RESEARCH_VERSION=optimized-local-20261026-default-workbench\n')
p.chmod(0o600)
PY
touch /var/www/deepquest.maintenance
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker equipment-worker equipment-query-worker web
curl -fsS http://127.0.0.1:6050/api/system/ready
rm /var/www/deepquest.maintenance
curl -fsS https://www.deepquest.space/api/system/ready
echo default_workbench_release_online
