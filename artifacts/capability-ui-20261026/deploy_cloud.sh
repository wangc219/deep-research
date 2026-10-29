#!/usr/bin/env bash
# Code-only frontend release. It does not read, restore, migrate, or delete business data.
set -euo pipefail
umask 077
cd /opt/deep-research

exec 9>/var/lock/deepquest-default-workbench-deploy.lock
flock -n 9

python3 - <<'PY'
import hashlib
import json
import tarfile
from pathlib import Path

root = Path('/opt/deep-research')
archive = Path('/tmp/deepquest-capability-ui-source-20261026.tar.gz')
expected = 'b931915c6aa238e9868e67ae392ca65bba85a0a69e1317e6a7d35a7865a0c59c'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
old = json.loads((root / 'acceptance-source-manifest.json').read_text())
with tarfile.open(archive) as package:
    new = json.load(package.extractfile('acceptance-source-manifest.json'))
    changed = {name for name in new if name in old and new[name] != old[name]}
    expected_changed = {
        'web/src/assets/css/equipment-workbench-live.css',
        'web/src/assets/css/main.css',
        'web/src/components/equipment/CapabilityPortraitCard.vue',
        'web/src/views/equipment/EquipmentCapabilitiesView.vue',
        'web/test/unit/equipmentCapabilitiesViewIntegration.test.js',
        'web/test/unit/equipmentReportComponents.test.js',
    }
    assert set(new) == set(old)
    assert changed in (expected_changed, set())
    for member in package:
        assert member.name in new or member.name == 'acceptance-source-manifest.json'
        assert (root / member.name).resolve().is_relative_to(root)
    package.extractall(root, filter='data')
assert all(
    (root / name).is_file()
    and hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    for name, digest in new.items()
)
evidence = Path('/var/lib/deepquest-migration/evidence-20261026/capability-ui-source-update.json')
evidence.write_text(json.dumps({
    'source_files': len(new),
    'changed': sorted(expected_changed),
    'source_already_current': not changed,
    'added': [],
    'removed': [],
    'archive_sha256': expected,
    'business_data_touched': False,
}, ensure_ascii=False, indent=2) + '\n')
PY

bash scripts/cloud.sh build web

maintenance=/var/www/deepquest.maintenance
touch "$maintenance"
cleanup() { rm -f "$maintenance"; }
trap cleanup EXIT

bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 120 web
web_container="$(bash scripts/cloud.sh ps -q web)"
web_image="$(bash scripts/cloud.sh images -q web)"
running_image="$(docker inspect --format '{{.Image}}' "$web_container")"
test -n "$web_container"
test -n "$web_image"
test "$running_image" = "sha256:$web_image"
docker exec "$web_container" sh -c "grep -R -q '默认仅展示概述' /usr/share/nginx/html/assets"
curl -fsS http://127.0.0.1:6050/api/system/ready >/tmp/deepquest-capability-ui-local-ready.json

rm -f "$maintenance"
trap - EXIT
curl -fsS https://www.deepquest.space/api/system/ready >/tmp/deepquest-capability-ui-public-ready.json

python3 - "$web_image" "$running_image" <<'PY'
import json
import sys
from pathlib import Path

Path('/var/lib/deepquest-migration/evidence-20261026/capability-ui-release.json').write_text(
    json.dumps({
        'web_image': sys.argv[1],
        'running_web_image': sys.argv[2],
        'source_verified': True,
        'built_from_cloud_source': True,
        'collapsed_portrait_copy_present': True,
        'local_ready': json.loads(Path('/tmp/deepquest-capability-ui-local-ready.json').read_text()),
        'public_ready': json.loads(Path('/tmp/deepquest-capability-ui-public-ready.json').read_text()),
        'business_data_touched': False,
    }, ensure_ascii=False, indent=2) + '\n'
)
PY

echo capability_ui_release_online
