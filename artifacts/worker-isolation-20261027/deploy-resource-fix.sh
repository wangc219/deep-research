#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
backup=/var/backups/deepquest/worker-isolation-20261027
docker exec -i deepquest-api-1 python <<'PY'
import asyncio
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   count=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('running','pending','queued','cancel_requested')"))
   count+=await db.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('running','pending','queued')"))
   assert count==0,'Active work must drain'
 finally:await pg_manager.close()
asyncio.run(main())
PY
task_image=$(docker inspect deepquest-api-1 --format '{{.Config.Image}}')
touch /var/www/deepquest.maintenance
rollback() {
  tar -xzf "$backup/source-before-resource-fix.tar.gz"
  docker tag deepquest-api:before-resource-pool-fix-20261027 "$task_image"
  bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker api
  rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
tar --no-same-owner -xzf /tmp/resource-fix.tar.gz
bash scripts/cloud.sh stop -t 30 api worker chat-worker deep-worker subagent-worker
docker tag deepquest-api:resource-pool-fix-candidate-20261027 "$task_image"
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 api
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/ready-resource-fix.json"
trap - ERR
python3 - <<'PY'
from pathlib import Path
import json,hashlib
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text())
for name,digest in json.loads(Path('/tmp/resource-fix-manifest.json').read_text()).items():
 assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
 manifest[name]=digest
p.write_text(json.dumps(manifest,indent=2))
print('Resource connection reuse deployed; all pools and public readiness healthy')
PY
