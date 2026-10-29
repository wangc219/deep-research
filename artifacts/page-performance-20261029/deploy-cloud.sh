#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup="$(cat /tmp/deepquest-page-performance-backup-path)"
exec 9>/var/lock/deepquest-page-performance.lock
flock -n 9
python3 - "$backup" <<'PY'
from pathlib import Path
import json,hashlib,sys,subprocess
r=Path('/opt/deep-research');b=Path(sys.argv[1])
for f,h in json.loads((b/'cloud-source-baseline.json').read_text()).items():
 assert hashlib.sha256((r/f).read_bytes()).hexdigest()==h,f'发布前源码发生变化: {f}'
assert subprocess.check_output(['docker','inspect','deepquest-web-1','--format','{{.Image}}'],text=True).strip()==(b/'image-before').read_text().strip(),'Web 镜像已变化'
assert subprocess.check_output(['docker','image','inspect','deepquest-web:page-performance-candidate-20261029','--format','{{.Id}}'],text=True).strip()==(b/'image-candidate').read_text().strip(),'候选镜像已变化'
PY
cat > "$backup/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/deep-research
backup="$(cd "$(dirname "$0")" && pwd)"
tar --no-same-owner -xzf "$backup/source-before.tar.gz"
python3 - "$backup" <<'PY'
from pathlib import Path
import json,sys
b=Path(sys.argv[1])
for f in json.loads((b/'absent-before.json').read_text()):
 p=Path(f)
 if p.is_file():p.unlink()
if (b/'manifest-before.json').exists():Path('acceptance-source-manifest.json').write_bytes((b/'manifest-before.json').read_bytes())
PY
docker tag "$(cat "$backup/image-before")" "$(cat "$backup/config-image")"
bash scripts/cloud.sh up -d --no-deps --force-recreate web
cp -p "$backup/host-nginx-before.conf" /etc/nginx/sites-available/deepquest
nginx -t
systemctl reload nginx
curl -fsS --max-time 15 http://127.0.0.1:6050/api/system/ready
ROLLBACK
chmod 700 "$backup/rollback.sh"
rollback_on_error() {
  trap - ERR
  bash "$backup/rollback.sh"
  exit 1
}
trap rollback_on_error ERR

tar --no-same-owner -xzf "$backup/release-source.tar.gz"
cp docker/nginx/cloud.conf /etc/nginx/sites-available/deepquest
nginx -t

docker tag deepquest-web:page-performance-candidate-20261029 "$(cat "$backup/config-image")"
bash scripts/cloud.sh up -d --no-deps --force-recreate web
systemctl reload nginx
curl -fsS --retry 5 --retry-delay 1 --retry-all-errors --max-time 20 http://127.0.0.1:8088/ > "$backup/live-internal.html"
cmp "$backup/live-internal.html" "$backup/candidate.html"
curl -fsS --max-time 20 https://www.deepquest.space/api/system/ready > "$backup/live-ready.json"
curl -fsS --max-time 20 https://www.deepquest.space/ > "$backup/live-public.html"
cmp "$backup/live-public.html" "$backup/candidate.html"
python3 - "$backup" <<'PY'
from pathlib import Path
import json,hashlib,sys,subprocess
b=Path(sys.argv[1]);r=Path('/opt/deep-research')
files=json.loads((b/'release-files.json').read_text())
hashes={f:hashlib.sha256((r/f).read_bytes()).hexdigest() for f in files}
for f,h in hashes.items():assert h==hashlib.sha256((b/'candidate'/f).read_bytes()).hexdigest(),f
old={row['Names']:row['ID'] for row in map(json.loads,(b/'containers-before.json').read_text().splitlines()) if row['Names']!='deepquest-web-1'}
current={row['Names']:row['ID'] for row in map(json.loads,subprocess.check_output(['docker','ps','--no-trunc','--format','{{json .}}'],text=True).splitlines())}
for name,id in old.items():assert current.get(name)==id,f'非 Web 容器发生变化: {name}'
manifest=r/'acceptance-source-manifest.json'
data=json.loads(manifest.read_text()) if manifest.exists() else {}
data.update(hashes);manifest.write_text(json.dumps(data,indent=2)+'\n')
(b/'source-after-hashes.json').write_text(json.dumps(hashes,indent=2))
report={'status':'deployed','backup':str(b),'web_image':subprocess.check_output(['docker','inspect','deepquest-web-1','--format','{{.Image}}'],text=True).strip(),'untouched_containers':len(old),'source_files':len(files),'public_html_verified':True}
(b/'deploy-result.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
PY
trap - ERR
