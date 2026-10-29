#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
mkdir -p /var/tmp/deepquest-cloud-wechat/web-final
tar --no-same-owner -xzf /tmp/shared-cloud-web-final.tar.gz -C /var/tmp/deepquest-cloud-wechat/web-final
image=$(docker inspect deepquest-web-1 --format '{{.Config.Image}}')
docker tag "$(docker inspect deepquest-web-1 --format '{{.Image}}')" deepquest-web:before-shared-cloud-final-20261027
cat > /var/tmp/deepquest-cloud-wechat/web-final/Dockerfile <<'EOF'
FROM deepquest-web:before-shared-cloud-final-20261027
COPY dist/ /usr/share/nginx/html/
EOF
docker build -q -t deepquest-web:shared-cloud-final-20261027 /var/tmp/deepquest-cloud-wechat/web-final
docker tag deepquest-web:shared-cloud-final-20261027 "$image"
CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 120 web
cp /var/tmp/deepquest-cloud-wechat/web-final/web/src/views/WxChannelsView.vue web/src/views/WxChannelsView.vue
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('acceptance-source-manifest.json');m=json.loads(p.read_text());n='web/src/views/WxChannelsView.vue';m[n]=hashlib.sha256(Path(n).read_bytes()).hexdigest();p.write_text(json.dumps(m,indent=2))
PY
