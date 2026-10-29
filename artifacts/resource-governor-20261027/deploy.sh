#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/resource-governor-20261027
docker exec -i deepquest-api-1 python <<'PY'
import asyncio
from sqlalchemy import text
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  async with pg_manager.get_async_session_context() as db:
   active=await db.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('pending','running','queued')"))
   active+=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('pending','running','cancel_requested')"))
   assert active==0,'Deployment waits for active work to drain'
 finally:await pg_manager.close()
asyncio.run(main())
PY
docker exec deepquest-postgres-1 sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl -Fc' > "$backup/database-before.dump"
test -s "$backup/database-before.dump"
docker exec -i deepquest-postgres-1 pg_restore -l < "$backup/database-before.dump" > "$backup/database-catalog.txt"
task_image=$(docker inspect deepquest-api-1 --format '{{.Config.Image}}')
tar --no-same-owner -xzf /tmp/release.tar.gz
python3 - <<'PY'
from pathlib import Path
import re
p=Path('.env.prod');value=p.read_text();key='CLOUD_RESOURCE_GOVERNOR_ENABLED'
pattern=r'(?m)^'+key+r'=.*$'
value=re.sub(pattern,key+'=true',value) if re.search(pattern,value) else value.rstrip()+'\n'+key+'=true\n'
p.write_text(value);p.chmod(0o600)
PY
bash scripts/cloud.sh config --quiet
touch /var/www/deepquest.maintenance
rollback() {
  cp "$backup/env.prod-before" .env.prod
  tar --no-same-owner -xzf "$backup/source-before.tar.gz"
  docker tag deepquest-api:before-resource-governor-20261027 "$task_image"
  bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 graph worker chat-worker deep-worker subagent-worker api
  rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
bash scripts/cloud.sh stop -t 30 api worker chat-worker deep-worker subagent-worker
docker tag deepquest-api:resource-governor-candidate-20261027 "$task_image"
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 graph
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 api
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/ready.json"
trap - ERR
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text())
for name,digest in json.loads(Path('/tmp/source-manifest.json').read_text()).items():
 assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
 manifest[name]=digest
p.write_text(json.dumps(manifest,indent=2))
print('Resource governor and lightweight authenticated health probes deployed')
PY
