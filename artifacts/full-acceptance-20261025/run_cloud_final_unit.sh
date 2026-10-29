#!/usr/bin/env bash
# 在新版容器和现有生产数据库上使用独立测试身份验收；不输出任何凭据。
set -euo pipefail
umask 077
TASK_ROOT=/opt/deep-research
TASK_LOGS=/var/backups/deepquest/full-acceptance-20261025/cloud-acceptance
mkdir -p "$TASK_LOGS"
chmod 700 "$TASK_LOGS"
docker cp "$TASK_ROOT/backend/test" deepquest-api-1:/app/test
docker cp /tmp/run_live_tests.py deepquest-api-1:/tmp/run_live_tests.py
docker cp /tmp/run_multimodal_acceptance.py deepquest-api-1:/tmp/run_multimodal_acceptance.py
docker cp /tmp/source-final.tar.gz deepquest-api-1:/tmp/acceptance-source.tar.gz
docker exec deepquest-api-1 sh -c 'mkdir -p /tmp/acceptance-source && tar -xzf /tmp/acceptance-source.tar.gz -C /tmp/acceptance-source'
docker exec -i deepquest-api-1 python - <<'PY'
# 仓库级单元测试需要部署镜像之外的 Docker/迁移源码；历史 SQLite 使用独立合成样本。
from pathlib import Path
import sqlite3,json
root=Path('/tmp/acceptance-source/outputs')
root.mkdir(exist_ok=True)
with sqlite3.connect(root/'application.db') as db:
    db.execute('CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, payload TEXT)')
    db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',('fixture-run',json.dumps({'status':'completed'})))
    for table in ('runtime_events','capability_versions'):
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)')
        db.execute(f'INSERT OR IGNORE INTO {table} VALUES (1)')
with sqlite3.connect(root/'query-library.db') as db:
    for table in ('query_library_items','query_library_revisions','query_generation_jobs'):
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)')
        db.execute(f'INSERT OR IGNORE INTO {table} VALUES (1)')
run=root/'runs/artifact-only'
run.mkdir(parents=True,exist_ok=True)
(run/'round_summary.json').write_text(json.dumps({'problem':{'topic':'迁移单元测试合成样本'}}))
PY

docker exec -w /tmp/acceptance-source/backend -e PYTHONPATH=/app/package:/app deepquest-api-1 python -m pytest test/unit -m 'not slow' -q --tb=short -o cache_dir=/tmp/cloud-acceptance-unit --junitxml=/app/outputs/full-acceptance-20261025-cloud-unit.xml > "$TASK_LOGS/unit-after-s5.log" 2>&1
