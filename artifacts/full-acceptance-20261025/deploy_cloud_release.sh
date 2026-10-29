#!/usr/bin/env bash
# 仅在本地放行后执行；生产数据保留，旧源码转入受保护的恢复备份。
set -euo pipefail
umask 077
TASK_ROOT=/opt/deep-research
TASK_RELEASE=/opt/deep-research-release-20261025
TASK_BACKUP=/var/backups/deepquest/full-acceptance-20261025
TASK_OLD="$TASK_BACKUP/source-before"
TASK_PHASE=preflight
trap 'printf "deployment_error_phase=%s\nbackup=%s\n" "$TASK_PHASE" "$TASK_BACKUP" >&2' ERR

test "${1:-}" = --apply
python3 - <<'PY'
import hashlib,json
from pathlib import Path
d=json.loads(Path('/tmp/full-acceptance-local-gate.json').read_text())
assert d['release_allowed'] is True
assert d['source_sha256']==hashlib.sha256(Path('/tmp/source-final.tar.gz').read_bytes()).hexdigest()
PY
test ! -e "$TASK_OLD"
cd /tmp
sha256sum -c source-final.sha256
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path('/opt/deep-research-release-20261025')
manifest=json.loads((root/'acceptance-source-manifest.json').read_text())
bad=[name for name,sha in manifest.items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha]
assert not bad, bad
print('source_manifest_verified='+str(len(manifest)))
PY
active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]
mkdir -p "$TASK_BACKUP"
chmod 700 "$TASK_BACKUP"
cp /etc/nginx/sites-available/deepquest "$TASK_BACKUP/nginx-before.conf"
for service in api web document-research sandbox-provisioner; do
    image="$(docker inspect --format '{{.Image}}' "deepquest-$service-1")"
    if docker image inspect "$image" >/dev/null 2>&1; then
        docker tag "$image" "deepquest-$service:before-full-acceptance-20261025"
    else
        # 被覆盖的固定 local 标签可能已失去镜像元数据；运行中容器仍可完整导出恢复。
        docker export "deepquest-$service-1" > "$TASK_BACKUP/$service-rootfs-before.tar"
        docker inspect --format '{{json .Config}}' "deepquest-$service-1" > "$TASK_BACKUP/$service-image-config-before.json"
    fi
done
TASK_PHASE=quiesce
touch /var/www/deepquest.maintenance
cd "$TASK_ROOT"
bash scripts/cloud.sh stop api worker equipment-worker equipment-query-worker web document-research document-websearch sandbox-provisioner
docker exec deepquest-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TASK_BACKUP/postgres-before-cutover.dump"
bash scripts/cloud.sh stop graph milvus etcd minio redis postgres
TASK_PHASE=backup
tar -czf "$TASK_BACKUP/persistent-data-before.tar.gz" -C "$TASK_ROOT" outputs docker/volumes
document_volume="$(docker volume inspect --format '{{.Mountpoint}}' deepquest_document-research-data)"
tar -czf "$TASK_BACKUP/document-research-before.tar.gz" -C "$document_volume" .
install -m 600 "$TASK_ROOT/.env.prod" "$TASK_RELEASE/.env.prod"
if test -f "$TASK_ROOT/.env.admin"; then install -m 600 "$TASK_ROOT/.env.admin" "$TASK_RELEASE/.env.admin"; fi
install -m 600 "$TASK_ROOT/docker/sandbox_provisioner/sandbox.env" "$TASK_RELEASE/docker/sandbox_provisioner/sandbox.env"
TASK_PHASE=source-cutover
mv "$TASK_ROOT" "$TASK_OLD"
mv "$TASK_RELEASE" "$TASK_ROOT"
test ! -e "$TASK_ROOT/outputs"
test ! -e "$TASK_ROOT/docker/volumes"
mv "$TASK_OLD/outputs" "$TASK_ROOT/outputs"
mv "$TASK_OLD/docker/volumes" "$TASK_ROOT/docker/volumes"
python3 - <<'PY'
from pathlib import Path
p=Path('/opt/deep-research/.env.prod')
lines=[line for line in p.read_text().splitlines() if not line.startswith('DEEP_RESEARCH_VERSION=')]
p.write_text('\n'.join(lines)+'\nDEEP_RESEARCH_VERSION=acceptance-20261025\n')
p.chmod(0o600)
PY
mkdir -p "$TASK_ROOT/outputs/video-models"
cp -a /opt/deep-research-staging-20261025/acceptance-asr/models/. "$TASK_ROOT/outputs/video-models/"
chown -R 1000:1000 "$TASK_ROOT/outputs/video-models"
cd "$TASK_ROOT"
bash scripts/cloud.sh config --quiet
TASK_PHASE=database-migration
bash scripts/cloud.sh up -d --no-deps postgres redis minio etcd graph milvus open-websearch
for attempt in $(seq 1 60); do
    if docker exec deepquest-postgres-1 sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then break; fi
    sleep 1
done
export DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
printf '%s\n' "$DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN" > docker/volumes/platform/.storage-migration-quiesced
bash scripts/cloud.sh run --rm --no-deps -e DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN storage-migrator
rm -f docker/volumes/platform/.storage-migration-quiesced
unset DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN
TASK_PHASE=start-new-runtime
install -m 644 docker/nginx/cloud.conf /etc/nginx/sites-available/deepquest
nginx -t
systemctl reload nginx
bash scripts/cloud.sh up -d --no-deps --force-recreate sandbox-provisioner api worker equipment-worker equipment-query-worker document-websearch document-research web
for attempt in $(seq 1 120); do
    if curl -fsS http://127.0.0.1:6050/api/system/ready > "$TASK_BACKUP/new-readiness.json"; then break; fi
    if [[ "$attempt" = 120 ]]; then exit 1; fi
    sleep 2
done
chmod 600 "$TASK_BACKUP"/*.*
printf 'deployment_stage=runtime-ready-awaiting-cloud-acceptance\nbackup=%s\nmaintenance=enabled\n' "$TASK_BACKUP"
