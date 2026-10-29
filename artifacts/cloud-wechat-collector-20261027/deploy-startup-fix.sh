#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
mkdir -p /var/tmp/deepquest-cloud-wechat/startup-fix
tar --no-same-owner -xzf /tmp/startup-fix.tar.gz -C /var/tmp/deepquest-cloud-wechat/startup-fix
docker tag deepquest-wx-collector:linux-amd64-20261027 deepquest-wx-collector:before-proxy-startup-20261027
cat > /var/tmp/deepquest-cloud-wechat/startup-fix/Dockerfile <<'EOF'
FROM deepquest-wx-collector:before-proxy-startup-20261027
COPY docker/wx-collector/rootfs/ /
RUN chmod +x /usr/local/bin/wx-ensure-proxy /usr/local/bin/wx-start-wechat
EOF
docker build -q -t deepquest-wx-collector:linux-amd64-20261027 /var/tmp/deepquest-cloud-wechat/startup-fix
tar --no-same-owner -xzf /tmp/startup-fix.tar.gz
for script in wx-ensure-proxy wx-start-wechat; do
 docker cp "docker/wx-collector/rootfs/usr/local/bin/$script" "deepquest-wx-collector-1:/usr/local/bin/$script"
 docker exec deepquest-wx-collector-1 chmod +x "/usr/local/bin/$script"
done
docker exec -u abc deepquest-wx-collector-1 /usr/local/bin/wx-ensure-proxy
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text());new=json.loads(Path('/tmp/startup-fix-manifest.json').read_text())
for name,digest in new.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
manifest.update(new);p.write_text(json.dumps(manifest,indent=2))
PY
