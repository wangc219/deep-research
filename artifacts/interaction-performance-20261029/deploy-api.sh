#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
b="$(cat /tmp/deepquest-interaction-api-backup-path)"
exec 9>/var/lock/deepquest-interaction-api.lock
flock -n 9
python3 - "$b" <<'PY'
from pathlib import Path
import subprocess,sys
b=Path(sys.argv[1]);p=Path('backend/package/platform_core/services/equipment_research_service.py')
assert p.read_bytes()==(b/'cloud-service-before.py').read_bytes(),'发布前宿主源码已变化'
assert subprocess.check_output(['docker','inspect','deepquest-api-1','--format','{{.Image}}'],text=True).strip()==(b/'image-before').read_text().strip(),'API 版本已变化'
assert subprocess.check_output(['docker','image','inspect','deepquest-api:interaction-candidate-20261029','--format','{{.Id}}'],text=True).strip()==(b/'image-candidate').read_text().strip(),'候选镜像已变化'
PY
cat > "$b/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
b="$(cd "$(dirname "$0")" && pwd)"
cp "$b/cloud-service-before.py" backend/package/platform_core/services/equipment_research_service.py
docker tag "$(cat "$b/image-before")" "$(cat "$b/config-image")"
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api
python3 - "$b" <<'PY'
from pathlib import Path
import sys,json,hashlib
b=Path(sys.argv[1]);p=Path('acceptance-source-manifest.json');data=json.loads(p.read_text());name='backend/package/platform_core/services/equipment_research_service.py'
data[name]=hashlib.sha256(Path(name).read_bytes()).hexdigest();p.write_text(json.dumps(data,indent=2)+'\n')
PY
ROLLBACK
chmod 700 "$b/rollback.sh"
rollback_on_error() { trap - ERR; bash "$b/rollback.sh"; exit 1; }
trap rollback_on_error ERR
cp "$b/cloud-service-after.py" backend/package/platform_core/services/equipment_research_service.py
docker tag deepquest-api:interaction-candidate-20261029 "$(cat "$b/config-image")"
bash scripts/cloud.sh up -d --no-deps --force-recreate --wait --wait-timeout 180 api
curl -fsS --retry 3 --retry-delay 1 --retry-all-errors --max-time 15 https://www.deepquest.space/api/system/ready > "$b/ready.json"
python3 - "$b" <<'PY'
from pathlib import Path
import sys,json,hashlib,subprocess
b=Path(sys.argv[1]);name='backend/package/platform_core/services/equipment_research_service.py'
assert Path(name).read_bytes()==(b/'cloud-service-after.py').read_bytes()
assert subprocess.check_output(['docker','exec','deepquest-api-1','cat','/app/package/platform_core/services/equipment_research_service.py'])==Path(name).read_bytes()
old={r['Names']:r['ID'] for r in map(json.loads,(b/'containers-before.json').read_text().splitlines()) if r['Names']!='deepquest-api-1'}
now={r['Names']:r['ID'] for r in map(json.loads,subprocess.check_output(['docker','ps','--no-trunc','--format','{{json .}}'],text=True).splitlines())}
for n,id in old.items(): assert now.get(n)==id,f'其他容器已变化: {n}'
p=Path('acceptance-source-manifest.json');data=json.loads(p.read_text());data[name]=hashlib.sha256(Path(name).read_bytes()).hexdigest();p.write_text(json.dumps(data,indent=2)+'\n')
result={'status':'deployed','backup':str(b),'api_image':subprocess.check_output(['docker','inspect','deepquest-api-1','--format','{{.Image}}'],text=True).strip(),'untouched_containers':len(old)}
(b/'deploy-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
PY
trap - ERR
