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
   count=await db.scalar(text("SELECT count(*) FROM agent_runs WHERE status IN ('running','pending','queued','cancel_requested')"))
   count+=await db.scalar(text("SELECT count(*) FROM tasks WHERE status IN ('running','pending','queued')"))
   assert count==0, 'Active work must drain'
 finally:await pg_manager.close()
asyncio.run(main())
PY
cp .env.prod "$backup/env.prod-before-memory-tune"
cp configs/cloud/4c16g.env.example "$backup/4c16g-before-memory-tune"
cp /tmp/4c16g.env.example configs/cloud/4c16g.env.example
cp /tmp/CLOUD_CAPACITY.md docs/CLOUD_CAPACITY.md
python3 - <<'PY'
from pathlib import Path
import re
p=Path('.env.prod');content=p.read_text()
for line in Path('configs/cloud/4c16g.env.example').read_text().splitlines():
 if not line or line.startswith('#'):continue
 key,value=line.split('=',1)
 if key=='COMPOSE_PROFILES':continue
 pattern=r'(?m)^'+re.escape(key)+r'=.*$'
 content=re.sub(pattern,key+'='+value,content) if re.search(pattern,content) else content.rstrip()+'\n'+key+'='+value+'\n'
p.write_text(content);p.chmod(0o600)
PY
bash scripts/cloud.sh config --quiet
touch /var/www/deepquest.maintenance
rollback() {
  cp "$backup/env.prod-before-memory-tune" .env.prod
  cp "$backup/4c16g-before-memory-tune" configs/cloud/4c16g.env.example
  bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker api
  rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
bash scripts/cloud.sh stop -t 30 api worker chat-worker deep-worker subagent-worker
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 180 api
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/ready-memory-tune.json"
trap - ERR
python3 - <<'PY'
from pathlib import Path
import json,hashlib
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text())
for name in ['configs/cloud/4c16g.env.example','docs/CLOUD_CAPACITY.md']:
 manifest[name]=hashlib.sha256(Path(name).read_bytes()).hexdigest()
p.write_text(json.dumps(manifest,indent=2))
print('Memory capacity applied: chat16/deep4/subagent8; per-user3/2/4')
PY
