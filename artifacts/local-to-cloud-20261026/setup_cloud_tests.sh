#!/usr/bin/env bash
# 测试夹具使用校验过的源码副本；线上服务始终从新构建镜像运行。
set -euo pipefail
docker cp /tmp/deepquest-final-source-20261026.tar.gz deepquest-api-1:/tmp/verified-source-fixtures.tar.gz
docker exec --user 0:0 -i deepquest-api-1 python - <<'PY'
import hashlib,tarfile
from pathlib import Path
archive=Path('/tmp/verified-source-fixtures.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='b7ba92354f1cf677a5fa378260d0b3ae103eb78c7fc4c7b684313c64b6ef3609'
root=Path('/workspace');assert not root.exists();root.mkdir()
with tarfile.open(archive) as source:source.extractall(root,filter='data')
(root/'outputs').mkdir()
(root/'artifacts/full-acceptance-20261025').mkdir(parents=True)
PY
docker cp /tmp/run_live_tests.py deepquest-api-1:/tmp/run_live_tests.py
docker cp /tmp/run_domain_regression.py deepquest-api-1:/workspace/artifacts/full-acceptance-20261025/run_domain_regression.py
docker cp /tmp/real_research_flow.py deepquest-api-1:/tmp/real_research_flow.py
docker cp /tmp/real_anchor_phase_probe.py deepquest-api-1:/tmp/real_anchor_phase_probe.py
docker exec --user 0:0 deepquest-api-1 chown -R 1000:1000 /workspace
docker exec --user 0:0 deepquest-api-1 ln -s /workspace/backend/test /app/test
printf 'verified_source_test_fixtures_ready\n'
