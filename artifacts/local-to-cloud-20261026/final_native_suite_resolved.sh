#!/usr/bin/env bash
set -euo pipefail
umask 077
cp /opt/deep-research/outputs/migration-20261026-latest-unit.xml /opt/deep-research/outputs/migration-20261026-latest-unit-initial.xml
docker exec --user 0:0 -i deepquest-api-1 python - <<'PY'
import json,shutil,sqlite3
from pathlib import Path
source=Path('/app/outputs');target=Path('/workspace/outputs')
for name in ('application.db','query-library.db'):shutil.copy2(source/name,target/name)
with sqlite3.connect('file:/app/outputs/application.db?mode=ro',uri=True) as db:
    ids={row[0] for row in db.execute('SELECT run_id FROM runs')}
for path in sorted((source/'runs').iterdir()):
    if path.is_dir() and not path.name.startswith('.') and path.name not in ids and (path/'round_summary.json').is_file():
        if not isinstance(json.loads((path/'round_summary.json').read_text()),dict):continue
        shutil.copytree(path,target/'runs'/path.name,dirs_exist_ok=True)
        break
else:raise RuntimeError('缺少真实历史产物测试夹具')
PY
docker exec --user 0:0 deepquest-api-1 chown -R 1000:1000 /workspace/outputs
for task_script in audit_runtime verify_s5_delivery verify_business feedback_ui_fixture fingerprint_persistence cleanup_acceptance final_default_project_probe; do
  docker cp "/tmp/$task_script.py" "deepquest-api-1:/tmp/$task_script.py"
done
docker exec -w /workspace/backend deepquest-api-1 python -m pytest test/unit -m 'not slow' -q --tb=short -o cache_dir=/tmp/latest-native-unit --junitxml=/app/outputs/migration-20261026-latest-unit.xml
docker exec -w /app -e TEST_BASE_URL=http://127.0.0.1:5050 deepquest-api-1 python /tmp/run_live_tests.py test/integration -c /app/pyproject.toml -q --tb=short -o cache_dir=/tmp/latest-native-integration --junitxml=/app/outputs/migration-20261026-latest-integration.xml
docker exec -w /app deepquest-api-1 python /tmp/final_default_project_probe.py
docker exec -w /app deepquest-api-1 python /tmp/verify_business.py
docker exec -w /app deepquest-api-1 python /tmp/verify_s5_delivery.py
echo final_complete_source_native_acceptance_passed
