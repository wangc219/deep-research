#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_EVIDENCE=/var/lib/deepquest-migration/evidence-20261026
docker exec -w /app deepquest-api-1 python /tmp/audit_runtime.py > "$TASK_EVIDENCE/latest-cold-pre-audit.log"
python3 - <<'PY'
import json
from pathlib import Path
assert all(value==0 for value in json.loads(Path('outputs/migration-20261026-runtime-audit.json').read_text())['active'].values())
PY
docker exec -w /app deepquest-api-1 python /tmp/fingerprint_persistence.py before > "$TASK_EVIDENCE/latest-cold-persistence-before.log"
docker inspect --format '{{.Name}} {{.Id}}' deepquest-api-1 deepquest-worker-1 deepquest-equipment-worker-1 deepquest-equipment-query-worker-1 deepquest-web-1 > "$TASK_EVIDENCE/latest-apps-before.txt"
touch /var/www/deepquest.maintenance
bash scripts/cloud.sh stop web api worker equipment-worker equipment-query-worker
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker equipment-worker equipment-query-worker web
for task_script in fingerprint_persistence audit_runtime verify_s5_delivery verify_business feedback_ui_fixture cleanup_acceptance; do
  docker cp "/tmp/$task_script.py" "deepquest-api-1:/tmp/$task_script.py"
done
docker exec -w /app deepquest-api-1 python /tmp/fingerprint_persistence.py after > "$TASK_EVIDENCE/latest-cold-persistence-after.log"
docker exec -w /app deepquest-api-1 python /tmp/feedback_ui_fixture.py cloud verify > "$TASK_EVIDENCE/latest-cold-feedback.log"
docker exec -w /app deepquest-api-1 python /tmp/verify_business.py > "$TASK_EVIDENCE/latest-cold-business.log"
docker exec -w /app deepquest-api-1 python /tmp/verify_s5_delivery.py > "$TASK_EVIDENCE/latest-cold-s5.log"
python3 /tmp/verify_running_release.py > "$TASK_EVIDENCE/latest-release-integrity.json"
docker inspect --format '{{.Name}} {{.Id}}' deepquest-api-1 deepquest-worker-1 deepquest-equipment-worker-1 deepquest-equipment-query-worker-1 deepquest-web-1 > "$TASK_EVIDENCE/latest-apps-after.txt"
python3 - <<'PY'
from pathlib import Path
p=Path('/var/lib/deepquest-migration/evidence-20261026')
before=dict(row.split() for row in (p/'latest-apps-before.txt').read_text().splitlines())
after=dict(row.split() for row in (p/'latest-apps-after.txt').read_text().splitlines())
assert len(before)==len(after)==5 and all(before[name]!=after[name] for name in before)
assert not Path('/var/backups/deepquest').exists()
PY
rm /var/www/deepquest.maintenance
curl -fsS https://www.deepquest.space/api/system/ready > "$TASK_EVIDENCE/latest-cold-public-ready.json"
echo latest_five_application_containers_recreated_data_unchanged
