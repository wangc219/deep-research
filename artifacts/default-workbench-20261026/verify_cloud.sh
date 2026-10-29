#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
docker exec --user 0:0 deepquest-api-1 mkdir -p /tmp/default-workbench-check
docker cp backend/test deepquest-api-1:/tmp/default-workbench-check/test
docker exec -w /app -e TEST_BASE_URL=http://127.0.0.1:5050 deepquest-api-1 python -m pytest /tmp/default-workbench-check/test/integration/api/test_project_api.py -k 'equipment_default_project or queries_without_project' -c /app/pyproject.toml -q --tb=short -o cache_dir=/tmp/default-workbench-cache
curl -fsS https://www.deepquest.space/api/system/ready
