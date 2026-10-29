#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /tmp/acceptance-citation-build
cat > Dockerfile <<'DOCKER'
FROM deepquest-api:acceptance-20261025
COPY academic_retrieval_service.py /app/package/platform_core/services/academic_retrieval_service.py
DOCKER
docker build --pull=false --network=none -t deepquest-api:acceptance-citation-candidate . > /tmp/citation-image-build.log 2>&1
cd /opt/deep-research
DEEP_RESEARCH_VERSION=acceptance-citation-candidate bash scripts/cloud.sh run --rm --no-deps --name deepquest-acceptance-citation-check --entrypoint python \
 -v /opt/deep-research/backend/test:/app/test:ro -v /tmp/acceptance-citation-build/test_academic_retrieval.py:/app/test/integration/services/test_academic_retrieval.py:ro -v /tmp/run_live_tests.py:/tmp/run_live_tests.py:ro \
 -e PYTHONPATH=/app/package:/app -e TEST_BASE_URL=http://web -e RUN_AMINER_MODEL_PROBE=1 -e AMINER_PROBE_MODEL=siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash -e AMINER_PROBE_REPORT_DIR=/app/outputs/full-acceptance-20261025-academic-results \
 api /tmp/run_live_tests.py test/integration/services/test_academic_retrieval.py test/unit/services/test_aminer.py test/unit/services/test_aminer_mcp.py -s -q --tb=short \
 -o cache_dir=/tmp/cloud-academic-citation --junitxml=/app/outputs/full-acceptance-20261025-cloud-academic-citation-final.xml > /tmp/cloud-academic-citation-final.log 2>&1
