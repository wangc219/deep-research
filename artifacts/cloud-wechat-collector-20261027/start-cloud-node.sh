#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/cloud-wechat-collector-20261027
mkdir -p "$backup"
chmod 700 "$backup"
test "$(sha256sum scripts/cloud.sh | cut -d' ' -f1)" = de52033a69e072afcdda5e803fc17a8f1cdebe91033e5d6cf632db27507f04f0
cp scripts/cloud.sh "$backup/cloud.sh-before"
cp acceptance-source-manifest.json "$backup/source-manifest-before.json"
docker image inspect deepquest-wx-collector:linux-amd64-20261027 --format '{{.Id}}' > "$backup/image-id"
python3 - <<'PY'
import tarfile,json,hashlib
from pathlib import Path
manifest=json.loads(Path('/tmp/source-manifest.json').read_text())
with tarfile.open('/tmp/source.tar.gz') as archive:
 for item in archive:
  assert item.name in manifest or item.isdir(),item.name
  assert (Path('/opt/deep-research')/item.name).resolve().is_relative_to('/opt/deep-research')
 archive.extractall('/opt/deep-research',filter='data')
for name,digest in manifest.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
PY
mkdir -p docker/volumes/wx-collector
chmod 700 docker/volumes/wx-collector
CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh config --quiet
CLOUD_WECHAT_COLLECTOR=1 bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 wx-collector
python3 - <<'PY'
import json,subprocess,hashlib
from pathlib import Path
info=json.loads(subprocess.check_output(['docker','inspect','deepquest-wx-collector-1']))[0]
assert not info['HostConfig']['Privileged']
assert info['HostConfig']['Memory']==3*1024**3
assert info['HostConfig']['NanoCpus']==1250000000
assert info['HostConfig']['PortBindings']['3000/tcp'][0]['HostIp']=='127.0.0.1'
assert '2022/tcp' not in info['HostConfig']['PortBindings']
assert all(not mount['Destination'].startswith('/var/run/docker.sock') for mount in info['Mounts'])
p=Path('acceptance-source-manifest.json');manifest=json.loads(p.read_text())
manifest.update(json.loads(Path('/tmp/source-manifest.json').read_text()));p.write_text(json.dumps(manifest,indent=2))
print(json.dumps({'collector_container':info['Name'],'health':info['State']['Health']['Status'],'memory_limit_gib':3,'cpu_limit':1.25,'desktop_bind':'127.0.0.1:6300','public_collector_ports':0,'production_routing_changed':False}))
PY
curl -fsS --max-time 15 https://www.deepquest.space/api/system/ready > "$backup/production-ready.json"
