#!/usr/bin/env bash
set -euo pipefail
umask 077
cp /opt/deep-research/outputs/migration-20261026-latest-integration.xml /opt/deep-research/outputs/migration-20261026-latest-integration-initial.xml
docker exec -w /app -e TEST_BASE_URL=http://127.0.0.1:5050 deepquest-api-1 python /tmp/run_live_tests.py test/integration -c /app/pyproject.toml -q --tb=short -o cache_dir=/tmp/latest-integration-final --junitxml=/app/outputs/migration-20261026-latest-integration.xml
docker exec -w /app deepquest-api-1 python /tmp/final_default_project_probe.py
docker exec -w /app deepquest-api-1 python /tmp/verify_business.py
docker exec -w /app deepquest-api-1 python /tmp/verify_s5_delivery.py
echo final_complete_source_native_acceptance_passed
