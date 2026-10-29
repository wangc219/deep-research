#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup="/opt/backups/deepquest-page-performance-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup/candidate"
cp /tmp/release-{source,dist}.tar.gz /tmp/cloud-source-baseline.json /tmp/release-files.json "$backup/"
python3 - "$backup" <<'PY'
from pathlib import Path
import json,hashlib,sys,subprocess,tarfile
r=Path('/opt/deep-research');b=Path(sys.argv[1])
base=json.loads((b/'cloud-source-baseline.json').read_text())
for f,h in base.items():
 assert hashlib.sha256((r/f).read_bytes()).hexdigest()==h, f'云端源码发生变化: {f}'
files=json.loads((b/'release-files.json').read_text())
absent=[f for f in files if not (r/f).exists()]
(b/'absent-before.json').write_text(json.dumps(absent))
with tarfile.open(b/'source-before.tar.gz','w:gz') as tf:
 for f in files:
  if f not in absent: tf.add(r/f,arcname=f)
info=json.loads(subprocess.check_output(['docker','inspect','deepquest-web-1']))[0]
(b/'web-before.json').write_text(json.dumps(info,indent=2))
(b/'image-before').write_text(info['Image'])
(b/'config-image').write_text(info['Config']['Image'])
(b/'networks').write_text('\n'.join(info['NetworkSettings']['Networks']))
(b/'containers-before.json').write_text(subprocess.check_output(['docker','ps','--no-trunc','--format','{{json .}}'],text=True))
manifest=r/'acceptance-source-manifest.json'
if manifest.exists():(b/'manifest-before.json').write_bytes(manifest.read_bytes())
PY
cp -p /etc/nginx/sites-available/deepquest "$backup/host-nginx-before.conf"
tar --no-same-owner -xzf "$backup/release-source.tar.gz" -C "$backup/candidate"
tar --no-same-owner -xzf "$backup/release-dist.tar.gz" -C "$backup/candidate"
base_tag="deepquest-web:page-performance-base-$(date +%Y%m%d-%H%M%S)"
docker tag "$(cat "$backup/image-before")" "$base_tag"
cat > "$backup/candidate/Dockerfile" <<DOCKER
FROM $base_tag
COPY dist /usr/share/nginx/html
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \\; && find /usr/share/nginx/html -type f -exec chmod 644 {} \\;
DOCKER
docker build -t deepquest-web:page-performance-candidate-20261029 "$backup/candidate"
docker image inspect deepquest-web:page-performance-candidate-20261029 --format '{{.Id}}' > "$backup/image-candidate"
network="$(sed -n '/app-network/{p;q;}' "$backup/networks")"
test -n "$network"
docker run --rm -d --name deepquest-page-performance-candidate --network "$network" -p 127.0.0.1:18089:80 deepquest-web:page-performance-candidate-20261029
trap 'docker stop deepquest-page-performance-candidate >/dev/null 2>&1 || true' EXIT
for n in $(seq 1 15); do
  if curl -fsS http://127.0.0.1:18089/ > "$backup/candidate.html"; then break; fi
  sleep 1
done
docker exec deepquest-page-performance-candidate nginx -t
curl -fsS http://127.0.0.1:18089/api/system/health > "$backup/candidate-health.json"
python3 - "$backup" <<'PY'
from pathlib import Path
import sys,re,http.client,gzip,json
b=Path(sys.argv[1]);html=(b/'candidate.html').read_text()
urls=re.findall(r'(?:src|href)="(/assets/[^"]+)"',html)
c=http.client.HTTPConnection('127.0.0.1',18089,timeout=15)
results=[]
for url in urls:
 c.request('GET',url,headers={'Accept-Encoding':'gzip'});r=c.getresponse();body=r.read()
 assert r.status==200,(url,r.status)
 assert 'immutable' in r.getheader('Cache-Control',''),url
 if url.endswith(('.js','.css')) and (b/'candidate/dist'/url.lstrip('/')).stat().st_size >= 1024:
  assert r.getheader('Content-Encoding')=='gzip',url
  assert gzip.decompress(body)==(b/'candidate/dist'/url.lstrip('/')).read_bytes(),url
 results.append({'path':url,'bytes':len(body),'encoding':r.getheader('Content-Encoding')})
c.request('GET','/assets/missing-page-performance.js');r=c.getresponse();r.read();assert r.status==404
c.request('GET','/assets/index-B8D4OJ4E.js');r=c.getresponse();r.read();assert r.status==200,'旧会话资源未保留'
(b/'candidate-validation.json').write_text(json.dumps(results,indent=2))
print(json.dumps({'candidate_assets':results,'old_assets_retained':True}))
PY
printf '%s\n' "$backup" > /tmp/deepquest-page-performance-backup-path
printf 'candidate_prepared=%s\n' "$backup"
