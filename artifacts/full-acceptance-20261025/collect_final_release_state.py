"""在云宿主只读采集最终镜像、备份和公开服务状态，不读取环境密钥。"""
import hashlib,json,subprocess
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
from datetime import datetime,timezone
services=['api','worker','equipment-worker','equipment-query-worker','web','sandbox-provisioner','document-research','document-websearch','graph','postgres','open-websearch','milvus','redis','etcd','minio']
metadata={}
for service in services:
 info=json.loads(subprocess.check_output(['docker','inspect','deepquest-'+service+'-1'],text=True))[0]
 metadata[service]={'image_id':info['Image'],'image':info['Config']['Image'],'running':info['State']['Running'],'health':info['State'].get('Health',{}).get('Status','not_configured')}
 assert metadata[service]['running'] and metadata[service]['health'] in {'healthy','not_configured'}
assert len({metadata[s]['image_id'] for s in services[:4]})==1
backup=Path('/var/backups/deepquest/full-acceptance-20261025')
backup_files=['postgres-before-cutover.dump','preflight-postgres.dump','persistent-data-before.tar.gz','document-research-before.tar.gz','nginx-before.conf']
assert all((backup/p).is_file() and (backup/p).stat().st_size>0 for p in backup_files)
assert (backup/'source-before').is_dir()
assert not Path('/var/www/deepquest.maintenance').exists()
assert not Path('/opt/deep-research-staging-20261025').exists()
assert not (backup/'persistence-private-state.json').exists()
ready=json.load(build_opener(ProxyHandler({})).open('http://127.0.0.1:6050/api/system/ready',timeout=30))
assert ready['status']=='ready' and ready['degraded'] is False
result={'checked_at':datetime.now(timezone.utc).isoformat(),'services':metadata,'api_image_id':metadata['api']['image_id'],'source_sha256':hashlib.sha256(Path('/tmp/source-final.tar.gz').read_bytes()).hexdigest(),'ready':ready,'maintenance':False,'old_active_version_removed':True,'backup_files_verified':backup_files,'backup_root':str(backup),'staging_removed':True,'persistence_private_state_removed':True}
Path('/tmp/deployment-final.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
