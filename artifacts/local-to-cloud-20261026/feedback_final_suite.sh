#!/usr/bin/env bash
set -euo pipefail
umask 077
bash /tmp/setup_cloud_tests.sh
docker cp /var/lib/deepquest-migration/test-fixture-outputs/. deepquest-api-1:/workspace/outputs/
docker exec --user 0:0 deepquest-api-1 chown -R 1000:1000 /workspace/outputs
for task_script in audit_runtime verify_s5_delivery verify_business feedback_ui_fixture fingerprint_persistence; do
  docker cp "/tmp/$task_script.py" "deepquest-api-1:/tmp/$task_script.py"
done
docker exec -w /workspace/backend deepquest-api-1 python -m pytest test/unit -m 'not slow' -q --tb=short -o cache_dir=/tmp/feedback-final-unit --junitxml=/app/outputs/migration-20261026-feedback-unit.xml
docker exec -w /app -e TEST_BASE_URL=http://127.0.0.1:5050 deepquest-api-1 python /tmp/run_live_tests.py test/integration/api -c /app/pyproject.toml -q --tb=short -o cache_dir=/tmp/feedback-final-http --junitxml=/app/outputs/migration-20261026-feedback-http.xml
echo feedback_final_unit_and_http_passed
