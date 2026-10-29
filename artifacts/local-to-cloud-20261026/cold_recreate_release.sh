#!/usr/bin/env bash
# 重建容器并保留全部卷；核实持久化和真实业务读取。
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_EVIDENCE=/var/lib/deepquest-migration/evidence-20261026
docker exec -w /app deepquest-api-1 python /tmp/audit_runtime.py > "$TASK_EVIDENCE/cold-pre-audit.log"
python3 - <<'PY'
import json
from pathlib import Path
assert all(value==0 for value in json.loads(Path('outputs/migration-20261026-runtime-audit.json').read_text())['active'].values())
PY
docker exec -w /app deepquest-api-1 python /tmp/fingerprint_persistence.py before > "$TASK_EVIDENCE/cold-persistence-before.log"
docker ps --filter label=com.docker.compose.project=deepquest --format '{{.Names}} {{.ID}}' > "$TASK_EVIDENCE/cold-containers-before.txt"
touch /var/www/deepquest.maintenance
bash scripts/cloud.sh stop web api worker equipment-worker equipment-query-worker document-research
docker exec -i deepquest-sandbox-provisioner-1 python - <<'PY'
import json,os
from urllib.request import Request,urlopen
request=Request('http://127.0.0.1:8002/api/sandboxes/quiesce?timeout_seconds=180',data=b'',method='POST',headers={'Authorization':'Bearer '+os.environ['SANDBOX_PROVISIONER_TOKEN']})
with urlopen(request,timeout=195) as response:assert json.load(response)['ok'] is True
PY
bash scripts/cloud.sh stop sandbox-provisioner document-websearch open-websearch milvus graph etcd minio redis postgres
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 postgres redis minio etcd graph
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 milvus open-websearch document-websearch document-research sandbox-provisioner
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker equipment-worker equipment-query-worker web
for task_script in fingerprint_persistence audit_runtime verify_s5_delivery verify_business feedback_ui_fixture; do
  docker cp "/tmp/$task_script.py" "deepquest-api-1:/tmp/$task_script.py"
done
docker exec -w /app deepquest-api-1 python /tmp/fingerprint_persistence.py after > "$TASK_EVIDENCE/cold-persistence-after.log"
docker exec -w /app deepquest-api-1 python /tmp/verify_s5_delivery.py > "$TASK_EVIDENCE/cold-s5.log"
docker exec -w /app deepquest-api-1 python /tmp/feedback_ui_fixture.py cloud verify > "$TASK_EVIDENCE/cold-feedback.log"
docker exec -w /app deepquest-api-1 python /tmp/verify_business.py > "$TASK_EVIDENCE/cold-business.log"
python3 /tmp/verify_running_release.py > "$TASK_EVIDENCE/cold-release-integrity.json"
docker ps --filter label=com.docker.compose.project=deepquest --format '{{.Names}} {{.ID}}' > "$TASK_EVIDENCE/cold-containers-after.txt"
python3 - <<'PY'
from pathlib import Path
p=Path('/var/lib/deepquest-migration/evidence-20261026')
before=dict(row.split() for row in (p/'cold-containers-before.txt').read_text().splitlines())
after=dict(row.split() for row in (p/'cold-containers-after.txt').read_text().splitlines())
assert set(before)==set(after)
assert all(before[name]!=after[name] for name in before)
assert not Path('/var/backups/deepquest').exists()
print('all_application_and_infrastructure_containers_recreated_data_retained')
PY
rm /var/www/deepquest.maintenance
curl -fsS https://www.deepquest.space/api/system/ready > "$TASK_EVIDENCE/cold-public-ready.json"
echo cold_recreation_acceptance_passed
