"""并发分段下载公开镜像，逐个核验原始摘要后导入；不使用仓库凭据。"""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

BASE='https://ghcr.nju.edu.cn/v2/linuxserver/webtop'
DIGEST='sha256:a62457e276e56991f0d8b8c879e2cbce2ac198e4446af2773503470c5ccbd81d'
ROOT=Path('/var/tmp/deepquest-cloud-wechat/base-oci')
BLOBS=ROOT/'blobs/sha256'
BLOBS.mkdir(parents=True,exist_ok=True)
headers={'Accept':'application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json'}
with urllib.request.urlopen(urllib.request.Request(BASE+'/manifests/'+DIGEST,headers=headers),timeout=30) as response: raw=response.read()
assert hashlib.sha256(raw).hexdigest()==DIGEST.split(':')[1]
manifest=json.loads(raw);(BLOBS/DIGEST.split(':')[1]).write_bytes(raw)
objects=[manifest['config'],*manifest['layers']]
chunks=[]
for item in objects:
    target=BLOBS/item['digest'].split(':')[1]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==item['digest'].split(':')[1]:continue
    with target.open('wb') as file:file.truncate(item['size'])
    size=item['size'];step=16*1024*1024
    for offset in range(0,size,step):chunks.append((item,target,offset,min(size-1,offset+step-1)))

def fetch(chunk):
    item,target,start,end=chunk
    for attempt in range(4):
        try:
            request=urllib.request.Request(BASE+'/blobs/'+item['digest'],headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(request,timeout=60) as response:
                assert response.status==206 or (response.status==200 and start==0 and end+1==item['size'])
                if response.status==206:assert response.headers['Content-Range'].startswith(f'bytes {start}-{end}/')
                data=response.read(end-start+2)
            assert len(data)==end-start+1
            descriptor=os.open(target,os.O_WRONLY)
            try:assert os.pwrite(descriptor,data,start)==len(data)
            finally:os.close(descriptor)
            return len(data)
        except Exception:
            if attempt==3:raise
            time.sleep(attempt+1)

done=0
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    for size in pool.map(fetch,chunks):
        done+=size
        if done//(64*1024*1024)!=(done-size)//(64*1024*1024):print(json.dumps({'downloaded_mib':round(done/1024**2)}),flush=True)
for item in objects:
    target=BLOBS/item['digest'].split(':')[1]
    with target.open('rb') as file: digest=hashlib.file_digest(file,'sha256').hexdigest()
    assert digest==item['digest'].split(':')[1],item['digest']
(ROOT/'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
index={'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json','manifests':[{'mediaType':manifest['mediaType'],'digest':DIGEST,'size':len(raw),'annotations':{'org.opencontainers.image.ref.name':'deepquest-webtop-base:validated','io.containerd.image.name':'deepquest-webtop-base:validated'},'platform':{'architecture':'amd64','os':'linux'}}]}
(ROOT/'index.json').write_text(json.dumps(index))
archive=ROOT.parent/'base.oci.tar'
with tarfile.open(archive,'w') as package:
    for name in ['oci-layout','index.json','blobs']:package.add(ROOT/name,arcname=name)
subprocess.run(['docker','load','-i',str(archive)],check=True)
loaded=subprocess.check_output(['docker','image','inspect','deepquest-webtop-base:validated','--format','{{.Id}}'],text=True).strip()
assert loaded==manifest['config']['digest']
print(json.dumps({'verified_base_manifest':DIGEST,'image_id':loaded,'objects_verified':len(objects)}),flush=True)
