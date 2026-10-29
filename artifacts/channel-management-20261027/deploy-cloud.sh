#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/channel-management-20261027
exec 9>/var/lock/deepquest-channel-management.lock
flock -n 9
# Read-only drain guard: do not interrupt genuine user work.
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
tar --no-same-owner -xzf /tmp/web-dist.tar.gz -C /tmp/channel-management-release
cat > /tmp/channel-management-release/Dockerfile.web <<'EOF'
FROM deepquest-web:before-channel-management-20261027
COPY dist/ /usr/share/nginx/html/
EOF
docker build -q -t deepquest-web:channel-management-candidate-20261027 -f /tmp/channel-management-release/Dockerfile.web /tmp/channel-management-release
api_image=$(docker inspect deepquest-api-1 --format '{{.Config.Image}}')
web_image=$(docker inspect deepquest-web-1 --format '{{.Config.Image}}')
network=$(cat "$backup/network")
touch /var/www/deepquest.maintenance
rollback() {
  docker tag deepquest-api:before-channel-management-20261027 "$api_image"
  docker tag deepquest-web:before-channel-management-20261027 "$web_image"
  docker run --rm --network "$network" --env-file "$backup/runtime.env" --volumes-from deepquest-api-1 --entrypoint python deepquest-api:before-channel-management-20261027 -c 'import asyncio; from platform_core.storage.postgres.manager import pg_manager; exec("async def m():\n pg_manager.initialize()\n await pg_manager.record_schema_version(\"knowledge\",6)\n await pg_manager.close()\n"); asyncio.run(m())'
  tar --no-same-owner -xzf "$backup/source-before.tar.gz"
  bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker api web
  rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
bash scripts/cloud.sh stop -t 45 api worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
docker run --rm -i --network "$network" --env-file "$backup/runtime.env" --volumes-from deepquest-api-1 --entrypoint python deepquest-api:channel-management-candidate-20261027 <<'PY'
import asyncio
from platform_core.storage.postgres.manager import pg_manager
async def main():
 pg_manager.initialize()
 try:
  versions=await pg_manager.get_schema_versions()
  assert versions['knowledge']==6
  await pg_manager.upgrade_knowledge_schema_v6_to_v7()
  await pg_manager.record_schema_version('knowledge',7)
  await pg_manager.require_current_schema()
 finally:await pg_manager.close()
asyncio.run(main())
PY
tar --no-same-owner -xzf /tmp/source.tar.gz
docker tag deepquest-api:channel-management-candidate-20261027 "$api_image"
docker tag deepquest-web:channel-management-candidate-20261027 "$web_image"
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api web
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/ready.json"
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('acceptance-source-manifest.json');old=json.loads(p.read_text());new=json.loads(Path('/tmp/source-manifest.json').read_text())
for name,digest in new.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
old.update(new);p.write_text(json.dumps(old,indent=2))
print(json.dumps({'deployed_source_files':len(new),'knowledge_schema':7,'readiness':'passed'}))
PY
trap - ERR
