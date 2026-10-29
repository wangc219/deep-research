"""核对活动源码、容器镜像、运行代码、凭据权限及服务 readiness。"""
import hashlib,json,subprocess
from pathlib import Path
from urllib.request import urlopen
root=Path('/opt/deep-research');manifest=json.loads((root/'acceptance-source-manifest.json').read_text())
assert all((root/p).is_file() and hashlib.sha256((root/p).read_bytes()).hexdigest()==sha for p,sha in manifest.items())
def docker(*args):
 return subprocess.check_output(['docker',*args],text=True)
services=['api','worker','equipment-worker','equipment-query-worker']
ids={s:docker('inspect','--format','{{.Image}}',f'deepquest-{s}-1').strip() for s in services}
assert len(set(ids.values()))==1,ids
assert ids['api']==docker('image','inspect','--format','{{.Id}}','deepquest-api:optimized-local-20261026-default-workbench').strip()
assert docker('image','inspect','--format','{{.Architecture}}',ids['api']).strip()=='amd64'
assert docker('inspect','--format','{{.Image}}','deepquest-web-1').strip()==docker('image','inspect','--format','{{.Id}}','deepquest-web-document-research:local').strip()
files={('/app/'+p.removeprefix('backend/')):sha for p,sha in manifest.items()
       if (p.startswith('backend/package/') or p.startswith('backend/server/')) and p.endswith('.py')}
code="""import json,hashlib,sys
from pathlib import Path
files=json.load(sys.stdin)
bad=[p for p,sha in files.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha]
print(json.dumps({'runtime_python_files':len(files),'mismatches':bad}))
assert not bad,bad
"""
r=subprocess.run(['docker','exec','-i','deepquest-api-1','python','-c',code],input=json.dumps(files),text=True,capture_output=True,check=True)
runtime=json.loads(r.stdout);assert not runtime['mismatches']
image_result=subprocess.run(['docker','run','--rm','--network','none','-i','--entrypoint','python',ids['api'],'-c',code],input=json.dumps(files),text=True,capture_output=True,check=True)
immutable=json.loads(image_result.stdout);assert not immutable['mismatches']
controller=docker('exec','deepquest-sandbox-provisioner-1','python','-c',"import hashlib; print(hashlib.sha256(open('/app/app.py','rb').read()).hexdigest())").strip()
assert controller==manifest['docker/sandbox_provisioner/app.py']
for name in ['.env.prod','.env.admin','docker/sandbox_provisioner/sandbox.env']:
 p=root/name
 if p.exists():assert p.stat().st_mode & 0o077 ==0,(name,oct(p.stat().st_mode &0o777))
with urlopen('http://127.0.0.1:6050/api/system/ready',timeout=15) as response: ready=json.load(response)
assert ready['status']=='ready' and ready.get('degraded') is False,ready
with urlopen('http://127.0.0.1:8088',timeout=15) as response:html=response.read().decode();assert 'id="app"' in html
public=[]
for s in ['api','web','postgres','redis','minio','graph','milvus','sandbox-provisioner','document-research']:
 info=json.loads(docker('inspect',f'deepquest-{s}-1'))[0]
 for port,bindings in (info['NetworkSettings']['Ports'] or {}).items():
  for binding in bindings or []:
   if binding['HostIp'] not in ['127.0.0.1','::1']:public.append([s,port,binding['HostIp']])
assert not public,public
print(json.dumps({'release_integrity':'passed','source_files':len(manifest),'runtime_python_files':runtime['runtime_python_files'],
 'all_application_workers_same_image':True,'immutable_image_python_hashes':'passed','api_image_id':ids['api'],'api_architecture':'amd64','web_new_build_running':True,'sandbox_controller_hash':'passed','credentials_permissions':'passed',
 'core_readiness':ready,'internal_ports_private':True},ensure_ascii=False))
