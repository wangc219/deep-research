#!/usr/bin/env bash
# 用户要求先移除全部云部署，业务数据与配置转入受保护备份供后续整体迁移。
set -euo pipefail
umask 077
TASK_ROOT=/opt/deep-research
TASK_BACKUP=/var/backups/deepquest/offline-before-local-optimization-20261025
[[ ! -e "$TASK_BACKUP" ]]
mkdir -p "$TASK_BACKUP"
chmod 700 "$TASK_BACKUP"
python3 - <<'PY'
import json,subprocess
from pathlib import Path
names=subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
info=json.loads(subprocess.check_output(['docker','inspect',*names],text=True)) if names else []
assert info and all(c['Config'].get('Labels',{}).get('com.docker.compose.project')=='deepquest' for c in info)
selected=[{'name':c['Name'].removeprefix('/'),'image_id':c['Image'],'image':c['Config']['Image'],
           'running':c['State']['Running'],'mounts':c['Mounts']} for c in info]
Path('/var/backups/deepquest/offline-before-local-optimization-20261025/inventory-before.json').write_text(json.dumps(selected,indent=2))
PY
cd "$TASK_ROOT"
active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
printf '%s\n' "$active" > "$TASK_BACKUP/active-work-before.log"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]
cp /etc/nginx/sites-available/deepquest "$TASK_BACKUP/nginx-site-before.conf"
systemctl stop nginx
systemctl disable nginx > "$TASK_BACKUP/nginx-disable.log" 2>&1
bash scripts/cloud.sh stop web api worker equipment-worker equipment-query-worker document-research document-websearch > "$TASK_BACKUP/stop-applications.log" 2>&1
docker exec -i deepquest-sandbox-provisioner-1 python - <<'PY'
import os,json
from urllib.request import Request,urlopen
request=Request('http://127.0.0.1:8002/api/sandboxes/quiesce',data=b'',method='POST',headers={'Authorization':'Bearer '+os.environ['SANDBOX_PROVISIONER_TOKEN']})
with urlopen(request,timeout=195) as response:assert json.load(response)['ok'] is True
PY
docker exec deepquest-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TASK_BACKUP/postgres-latest.dump"
test -s "$TASK_BACKUP/postgres-latest.dump"
docker exec -i deepquest-postgres-1 pg_restore -l < "$TASK_BACKUP/postgres-latest.dump" > "$TASK_BACKUP/postgres-restore-catalog.txt"
volume="$(docker volume inspect --format '{{.Mountpoint}}' deepquest_document-research-data)"
tar -czf "$TASK_BACKUP/document-research-data.tar.gz" -C "$volume" .
tar -tzf "$TASK_BACKUP/document-research-data.tar.gz" > "$TASK_BACKUP/document-research-catalog.txt"
bash scripts/cloud.sh down --remove-orphans > "$TASK_BACKUP/compose-down.log" 2>&1
[[ -z "$(docker ps -aq)" ]]
rm -f /etc/nginx/sites-enabled/deepquest /etc/nginx/sites-available/deepquest
rm -f /var/www/deepquest.maintenance
cd /opt
mv "$TASK_ROOT" "$TASK_BACKUP/deployment-and-persistent-data"
python3 - <<'PY'
import json,subprocess,hashlib
from pathlib import Path
root=Path('/var/backups/deepquest/offline-before-local-optimization-20261025')
assert not Path('/opt/deep-research').exists()
assert not subprocess.check_output(['docker','ps','-aq'],text=True).strip()
assert json.loads(subprocess.check_output(['docker','compose','ls','--all','--format','json'],text=True))==[]
assert not list(Path('/etc/nginx/sites-enabled').iterdir())
assert subprocess.run(['systemctl','is-active','--quiet','nginx']).returncode!=0
assert subprocess.run(['systemctl','is-enabled','--quiet','nginx']).returncode!=0
listeners=subprocess.check_output(['ss','-Hlnt'],text=True).splitlines()
blocked_ports={80,443,6050,8088,6432,7379,9002,10000,10001,10091,20530,8474,8687}
ports={int(line.split()[3].rsplit(':',1)[1]) for line in listeners}
assert not ports.intersection(blocked_ports),ports
result={'cloud_deployments_removed':True,'containers_remaining':0,'compose_projects_remaining':0,'active_project_directory_exists':False,
        'nginx_stopped_and_disabled':True,'enabled_sites_remaining':0,'project_ports_closed':True,
        'backup_root':str(root),'latest_postgres_dump_validated':True,'document_data_archive_validated':True,
        'persistent_data_and_configuration_retained':True,'historical_backups_retained':True,
        'postgres_dump_sha256':hashlib.sha256((root/'postgres-latest.dump').read_bytes()).hexdigest()}
(root/'removal-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
PY
chmod 600 "$TASK_BACKUP"/*.*
