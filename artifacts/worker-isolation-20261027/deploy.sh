#!/usr/bin/env bash
set -euo pipefail
umask 077
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
   count=await db.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('running','pending','queued')"))
   count+=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('running','pending','queued','cancel_requested')"))
   assert count==0, 'Active work must drain before worker replacement'
  print('Production tasks drained')
 finally: await pg_manager.close()
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
p=Path('.env.prod');content=p.read_text()
for line in Path('configs/cloud/4c16g.env.example').read_text().splitlines():
 if not line or line.startswith('#'):continue
 key,value=line.split('=',1)
 if key=='COMPOSE_PROFILES':
  previous=re.search(r'(?m)^COMPOSE_PROFILES=(.*)$',content)
  if previous:value=','.join(dict.fromkeys([*previous[1].strip('"\'').split(','),'agent-pools']))
 pattern=r'(?m)^'+re.escape(key)+r'=.*$'
 content=re.sub(pattern,key+'='+value,content) if re.search(pattern,content) else content.rstrip()+'\n'+key+'='+value+'\n'
p.write_text(content);p.chmod(0o600)
PY
bash scripts/cloud.sh config --quiet
touch /var/www/deepquest.maintenance
rollback() {
  echo 'Deploy failed; restoring previous image and capacity config'
  bash scripts/cloud.sh stop -t 30 chat-worker deep-worker subagent-worker || true
  cp "$backup/env.prod-before" .env.prod
  tar --no-same-owner -xzf "$backup/source-before.tar.gz"
  docker tag deepquest-api:before-worker-isolation-20261027 "$task_image"
  bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 150 worker api
  rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
bash scripts/cloud.sh stop -t 30 api worker
docker tag deepquest-api:worker-isolation-candidate-20261027 "$task_image"
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 api
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/ready.json"
trap - ERR
python3 - <<'PY'
from pathlib import Path
import json,hashlib
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text())
incoming=json.loads(Path('/tmp/source-manifest.json').read_text())
for name,digest in incoming.items():
 assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
 manifest[name]=digest
p.write_text(json.dumps(manifest,indent=2))
print('Four worker pools online; readiness passed; source manifest updated')
PY
