#!/usr/bin/env bash
set -euo pipefail
umask 077
TASK_ROOT=/opt/deep-research
TASK_LOGS=/var/backups/deepquest/full-acceptance-20261025/cloud-acceptance
cd "$TASK_ROOT"
python3 - <<'PY'
import xml.etree.ElementTree as E
p='/opt/deep-research/outputs/full-acceptance-20261025-cloud-academic-citation-final.xml'
cases=list(E.parse(p).iter('testcase'))
assert len(cases)==72 and all(c.find('error') is None and c.find('skipped') is None for c in cases)
failed=[c.attrib['name'] for c in cases if c.find('failure') is not None]
assert failed==['test_live_model_routes_and_executes_academic_tools[technology_cabin]'],failed
resolved=list(E.parse('/opt/deep-research/outputs/full-acceptance-20261025-cloud-academic-citation-resolved.xml').iter('testcase'))
assert len(resolved)==1 and resolved[0].attrib['name']==failed[0]
assert all(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in resolved)
PY
active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]
cd /tmp
sha256sum -c source-final.sha256
cd "$TASK_ROOT"
old_image="$(docker inspect --format '{{.Image}}' deepquest-api-1)"
docker tag "$old_image" deepquest-api:before-citation-final-20261025
tar -xzf /tmp/source-final.tar.gz -C "$TASK_ROOT"
docker tag deepquest-api:acceptance-citation-candidate deepquest-api:acceptance-20261025
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 240 api worker equipment-worker equipment-query-worker > "$TASK_LOGS/citation-promote.log" 2>&1
python3 /tmp/verify_running_release.py > "$TASK_LOGS/release-integrity-citation-final.json"
docker cp "$TASK_ROOT/backend/test" deepquest-api-1:/app/test
docker cp /tmp/run_live_tests.py deepquest-api-1:/tmp/run_live_tests.py
docker exec -e PYTHONPATH=/app/package:/app -e TEST_BASE_URL=https://www.deepquest.space deepquest-api-1 python /tmp/run_live_tests.py \
 test/e2e/test_agent_async_e2e.py test/e2e/test_real_external_retrieval.py -s -q --tb=short \
 -o cache_dir=/tmp/citation-public-smoke --junitxml=/app/outputs/full-acceptance-20261025-cloud-citation-public-final.xml > "$TASK_LOGS/citation-public-final.log" 2>&1
docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py
printf 'citation_release_promoted=true\n'
