#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/channel-management-design-20261027
python3 - <<'PY'
from pathlib import Path
import json,hashlib,shutil
p=Path('web/src/views/WxChannelsView.vue');manifest=json.loads(Path('acceptance-source-manifest.json').read_text())
assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest[str(p)]
shutil.copy2(p,'/var/backups/deepquest/channel-management-design-20261027/web-view-before-responsive.vue')
PY
image=$(docker inspect deepquest-web-1 --format '{{.Config.Image}}')
docker tag "$(docker inspect deepquest-web-1 --format '{{.Image}}')" deepquest-web:before-channel-aligned-20261027
mkdir -p /tmp/channel-responsive
tar --no-same-owner -xzf /tmp/responsive-web.tar.gz -C /tmp/channel-responsive
cat > /tmp/channel-responsive/Dockerfile <<'EOF'
FROM deepquest-web:before-channel-aligned-20261027
COPY dist/ /usr/share/nginx/html/
EOF
docker build -q -t deepquest-web:channel-aligned-20261027 /tmp/channel-responsive
rollback() {
 docker tag deepquest-web:before-channel-aligned-20261027 "$image"
 cp "$backup/web-view-before-responsive.vue" web/src/views/WxChannelsView.vue
 bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 120 web
}
trap rollback ERR
docker tag deepquest-web:channel-aligned-20261027 "$image"
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 120 web
cp /tmp/channel-responsive/web/src/views/WxChannelsView.vue web/src/views/WxChannelsView.vue
python3 - <<'PY'
from pathlib import Path
import json,hashlib
p=Path('acceptance-source-manifest.json');old=json.loads(p.read_text());new=json.loads(Path('/tmp/responsive-manifest.json').read_text())
for name,digest in new.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
old.update(new);p.write_text(json.dumps(old,indent=2))
print('Article-aligned layout deployed and source verified')
PY
trap - ERR
