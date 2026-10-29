#!/usr/bin/env bash
# 后端源码未变化；只更新前端确认体验并重新构建前端镜像。
set -euo pipefail
umask 077
cd /opt/deep-research
python3 - <<'PY'
import hashlib,json,tarfile
from pathlib import Path
root=Path('/opt/deep-research');archive=Path('/tmp/deepquest-feedback-confirmation-source-20261026.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='09bfc5865ab1965ad1e6df55e4e08999846908cdb51839befbd52cfe055c173f'
old=json.loads((root/'acceptance-source-manifest.json').read_text())
with tarfile.open(archive) as package:
    new=json.load(package.extractfile('acceptance-source-manifest.json'))
    changed={name for name in new if name in old and new[name]!=old[name]}
    assert set(new)==set(old) and changed=={'web/src/views/equipment/EquipmentCapabilitiesView.vue','web/test/unit/capabilityFeedbackRuntime.test.js'}
    for member in package:
        assert member.name in new or member.name=='acceptance-source-manifest.json'
        assert (root/member.name).resolve().is_relative_to(root)
    package.extractall(root,filter='data')
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in new.items())
Path('/var/lib/deepquest-migration/evidence-20261026/confirmation-source-update.json').write_text(json.dumps({'files':len(new),'changed':sorted(changed),'backend_changes':0,'sha256':'09bfc5865ab1965ad1e6df55e4e08999846908cdb51839befbd52cfe055c173f'},indent=2)+'\n')
PY
bash scripts/cloud.sh build web
touch /var/www/deepquest.maintenance
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 90 web
python3 /tmp/verify_running_release.py > /var/lib/deepquest-migration/evidence-20261026/confirmation-release-integrity.json
rm /var/www/deepquest.maintenance
curl -fsS https://www.deepquest.space/api/system/ready > /var/lib/deepquest-migration/evidence-20261026/confirmation-public-ready.json
echo feedback_in_page_confirmation_online
