#!/usr/bin/env bash
# 大文件传输期间先恢复已完整传输的逻辑存储，应用继续关闭。
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_SNAPSHOT=/var/lib/deepquest-migration/local-20261026
TASK_EVIDENCE=/var/lib/deepquest-migration/evidence-20261026
mkdir -p "$TASK_EVIDENCE"
test ! -e "$TASK_EVIDENCE/logical-restored"
python3 - <<'PY'
import hashlib,json
from pathlib import Path
p=Path('/var/lib/deepquest-migration/local-20261026')
m=json.loads(Path('/tmp/deepquest-snapshot-manifest-20261026.json').read_text())
for name,item in m.items():
    if name=='application-files.tar.gz':continue
    path=p/name
    assert path.resolve().is_relative_to(p) and path.stat().st_size==item['size']
    with path.open('rb') as source:assert hashlib.file_digest(source,'sha256').hexdigest()==item['sha256'],name
assert not Path('/var/backups/deepquest').exists()
print('logical_snapshot_hashes_verified')
PY
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 postgres redis minio etcd open-websearch
docker exec -i deepquest-postgres-1 sh -c 'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$TASK_SNAPSHOT/postgres.dump"
touch "$TASK_EVIDENCE/postgres-restored"
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 milvus
bash scripts/cloud.sh run --rm --no-deps --user 0:0 \
  -v "$TASK_SNAPSHOT:/migration:ro" \
  -v /tmp/deepquest-logical-payload-20261026.py:/tmp/logical_payload.py:ro \
  api python /tmp/logical_payload.py restore /migration/logical > "$TASK_EVIDENCE/logical-restore.log" 2>&1
touch "$TASK_EVIDENCE/logical-restored"
printf 'logical_restore_and_hash_verification=passed\n'
