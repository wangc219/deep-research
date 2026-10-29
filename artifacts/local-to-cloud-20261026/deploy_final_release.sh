#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_EVIDENCE=/var/lib/deepquest-migration/evidence-20261026
docker exec -w /app deepquest-api-1 python /tmp/audit_runtime.py > "$TASK_EVIDENCE/feedback-predeploy-audit.log"
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/opt/deep-research/outputs/migration-20261026-runtime-audit.json')
assert all(value==0 for value in json.loads(p.read_text())['active'].values())
PY
test "$(systemctl show deepquest-final2-build-20261026 --property=Result --value)" = success
test "$(systemctl show deepquest-final2-build-20261026 --property=ActiveState --value)" = inactive
touch /var/www/deepquest.maintenance
python3 - <<'PY'
from pathlib import Path
p=Path('.env.prod')
lines=[line for line in p.read_text().splitlines() if not line.startswith('DEEP_RESEARCH_VERSION=')]
p.write_text('\n'.join(lines)+'\nDEEP_RESEARCH_VERSION=optimized-local-20261026-final\n')
p.chmod(0o600)
PY
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker equipment-worker equipment-query-worker web
python3 /tmp/verify_running_release.py > "$TASK_EVIDENCE/final-release-integrity.json"
rm /var/www/deepquest.maintenance
curl -fsS https://www.deepquest.space/api/system/ready > "$TASK_EVIDENCE/final-public-ready.json"
echo feedback_new_release_online
