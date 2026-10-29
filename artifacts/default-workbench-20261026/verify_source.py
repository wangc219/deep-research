"""核对云端源码与实际运行的个人工作台相关 Python 文件。"""
import hashlib
import json
from pathlib import Path
import subprocess

manifest=json.loads(Path('/tmp/default-workbench-expected-source.json').read_text())
root=Path('/opt/deep-research')
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==sha for p,sha in manifest.items())
runtime={f"/app/{p.removeprefix('backend/')}":sha for p,sha in manifest.items() if p.startswith('backend/')}
code="import json,hashlib,sys; from pathlib import Path; m=json.load(sys.stdin); bad=[p for p,h in m.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]; print(json.dumps({'checked':len(m),'mismatches':bad})); assert not bad"
result=subprocess.run(['docker','exec','-i','deepquest-api-1','python','-c',code],input=json.dumps(runtime),text=True,capture_output=True,check=True)
print(result.stdout.strip())
services=['api','worker','equipment-worker','equipment-query-worker']
images={s:subprocess.check_output(['docker','inspect','--format','{{.Image}}',f'deepquest-{s}-1'],text=True).strip() for s in services}
assert len(set(images.values()))==1,images
print(json.dumps({'cloud_source_files':len(manifest),'workers_share_api_image':True,'api_image':images['api']}))
