#!/usr/bin/env bash
# 仅恢复本地快照，所有校验通过前保持公网服务关闭。
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_SNAPSHOT=/var/lib/deepquest-migration/local-20261026
TASK_EVIDENCE=/var/lib/deepquest-migration/evidence-20261026
mkdir -p "$TASK_EVIDENCE"
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path('/var/lib/deepquest-migration/local-20261026')
manifest=json.loads((root/'snapshot-manifest.json').read_text())
for name,item in manifest.items():
    path=root/name
    assert path.resolve().is_relative_to(root) and path.is_file()
    assert path.stat().st_size==item['size']
    with path.open('rb') as source:assert hashlib.file_digest(source,'sha256').hexdigest()==item['sha256'],name
assert not Path('/var/backups/deepquest').exists()
print(json.dumps({'local_snapshot_files_verified':len(manifest),'old_cloud_backup_exists':False}))
PY
test -f "$TASK_EVIDENCE/logical-restored"
if [[ ! -f "$TASK_EVIDENCE/application-files-restored" ]]; then
python3 - <<'PY'
import shutil,tarfile
from pathlib import Path
root=Path('/opt/deep-research')
platform=root/'docker/volumes/platform'
assert not any(p.is_file() or p.is_symlink() for d in (root/'outputs',platform) for p in d.rglob('*'))
platform.mkdir(parents=True,exist_ok=True)
with tarfile.open('/var/lib/deepquest-migration/local-20261026/application-files.tar.gz') as archive:
    for member in archive:
        if any(part.startswith('._') or part=='.DS_Store' for part in Path(member.name).parts):
            continue  # macOS资源叉和Finder元数据不属于业务文件。
        if member.name=='outputs' or member.name.startswith('outputs/'):
            target=root
        else:
            assert member.name.split('/')[0] in {'threads','skill-sources','skill-projections'}
            target=platform
        assert (target/member.name).resolve().is_relative_to(target)
        if member.issym():
            assert member.name.startswith('outputs/') and '/runtime/codex-homes/' in member.name and '/tmp/arg0/' in member.name
            assert Path(member.name).name in {'applypatch','apply_patch','codex-execve-wrapper'}
            continue  # 旧进程生成的临时二进制链接不跨架构复用。
        assert not member.islnk(), '需单独核对迁移硬链接'
        archive.extract(member,target,filter='data')
print('local_application_files_extracted')
PY
chown -R 1000:1000 outputs docker/volumes/platform
touch "$TASK_EVIDENCE/application-files-restored"
fi
if [[ ! -f "$TASK_EVIDENCE/graph-document-restored" ]]; then
bash scripts/cloud.sh create graph document-research
docker run --rm --user 0:0 --volumes-from deepquest-graph-1 \
  -v "$TASK_SNAPSHOT/graph:/migration:ro" --entrypoint neo4j-admin neo4j:5.26.29 \
  database load neo4j --from-path=/migration --overwrite-destination=true > "$TASK_EVIDENCE/graph-load.log" 2>&1
docker run --rm --user 0:0 --volumes-from deepquest-document-research-1 \
  -v "$TASK_SNAPSHOT/document-research:/migration:ro" --entrypoint python \
  deepquest-document-research:local -c 'import shutil;from pathlib import Path;p=Path("/var/lib/document-research");assert not list(p.iterdir());shutil.copytree("/migration",p,dirs_exist_ok=True)'
docker run --rm --user 0:0 --volumes-from deepquest-document-research-1 \
  --entrypoint python deepquest-document-research:local -c 'import os;from pathlib import Path;p=Path("/var/lib/document-research");os.chown(p,1000,1000);[(os.chown(x,1000,1000)) for x in p.rglob("*")]'
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 graph
touch "$TASK_EVIDENCE/graph-document-restored"
fi
# 本地已经完成现代存储迁移；这里只运行幂等核对，不导入旧云资料。
TASK_QUIESCENCE_TOKEN="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
printf '%s\n' "$TASK_QUIESCENCE_TOKEN" > docker/volumes/platform/.storage-migration-quiesced
trap 'rm -f docker/volumes/platform/.storage-migration-quiesced' EXIT
bash scripts/cloud.sh run --rm --no-deps \
  -e "DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN=$TASK_QUIESCENCE_TOKEN" \
  storage-migrator > "$TASK_EVIDENCE/storage-check.log" 2>&1
rm -f docker/volumes/platform/.storage-migration-quiesced
unset TASK_QUIESCENCE_TOKEN
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 300 sandbox-provisioner api worker equipment-worker equipment-query-worker document-websearch document-research web
curl -fsS http://127.0.0.1:6050/api/system/ready > "$TASK_EVIDENCE/readiness.json"
printf 'migration_stage=local_data_restored_runtime_ready_public_closed\n'
