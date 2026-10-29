#!/usr/bin/env bash
set -euo pipefail
umask 077
bash /tmp/setup_cloud_tests.sh
docker exec -w /app -e TEST_BASE_URL=http://127.0.0.1:5050 -e EQUIPMENT_TEST_LIVE_MODELS=1 deepquest-api-1 python /tmp/run_live_tests.py test/integration/api/test_native_deep_models_live.py test/e2e/test_agent_async_e2e.py test/e2e/test_real_external_retrieval.py -c /app/pyproject.toml -s -q --tb=short -o cache_dir=/tmp/post-cold-real --junitxml=/app/outputs/migration-20261026-post-cold-real.xml
echo post_cold_real_models_workers_retrieval_passed
