#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/wxchannels-progressive-20261027
exec 9>/var/lock/deepquest-progressive.lock
flock -n 9
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
cp -p .env.prod "$backup/env-before"
cp -p acceptance-source-manifest.json "$backup/manifest-before.json"
api_image=$(docker inspect deepquest-api-1 --format '{{.Config.Image}}')
web_image=$(docker inspect deepquest-web-1 --format '{{.Config.Image}}')
docker tag "$(docker inspect deepquest-web-1 --format '{{.Image}}')" deepquest-web:before-progressive-20261027
mkdir -p /var/tmp/deepquest-wxchannels-progressive/web-candidate
tar --no-same-owner -xzf /tmp/progressive-web-dist.tar.gz -C /var/tmp/deepquest-wxchannels-progressive/web-candidate
cat > /var/tmp/deepquest-wxchannels-progressive/web-candidate/Dockerfile <<'EOF'
FROM deepquest-web:before-progressive-20261027
COPY dist/ /usr/share/nginx/html/
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \; \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} \;
EOF
docker build -q -t deepquest-web:progressive-candidate-20261027 /var/tmp/deepquest-wxchannels-progressive/web-candidate
rollback() {
 cp -p "$backup/env-before" .env.prod
 docker tag deepquest-api:before-progressive-20261027 "$api_image"
 docker tag deepquest-web:before-progressive-20261027 "$web_image"
 tar --no-same-owner -xzf "$backup/source-before.tar.gz"
 cp -p "$backup/manifest-before.json" acceptance-source-manifest.json
 bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api worker web
 rm -f /var/www/deepquest.maintenance
}
trap rollback ERR
touch /var/www/deepquest.maintenance
bash scripts/cloud.sh stop -t 45 api worker
python3 - <<'PY'
from pathlib import Path
p=Path('.env.prod');lines=p.read_text().splitlines();updates={'WX_CHANNELS_MCP_URL':'http://wx-collector:2022/mcp','WX_CHANNELS_SHARED_CLOUD':'true'}
lines=[line for line in lines if line.partition('=')[0] not in updates]
p.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n')
PY
tar --no-same-owner -xzf /tmp/deepquest-wxchannels-progressive-source.tar.gz
docker tag deepquest-api:progressive-candidate-20261027 "$api_image"
docker tag deepquest-web:progressive-candidate-20261027 "$web_image"
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 worker
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api web
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text());new=json.loads(Path('/tmp/deepquest-wxchannels-progressive-source-manifest.json').read_text())
for name,digest in new.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
manifest.update(new);p.write_text(json.dumps(manifest,indent=2))
PY
docker exec -i deepquest-api-1 python <<'PY'
import asyncio,json
from platform_core.services.wxchannels_service import connection_status
async def main():
 state=await connection_status();assert state['central_managed'] and state['ready'];print(json.dumps({'shared_cloud':True,'wechat_ready':state['ready']}))
asyncio.run(main())
PY
rm -f /var/www/deepquest.maintenance
curl -fsS --max-time 20 https://www.deepquest.space/api/system/ready > "$backup/ready.json"
trap - ERR
printf 'Shared cloud release healthy\n'
