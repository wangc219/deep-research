#!/usr/bin/env bash
# 停止文件写入者和动态沙盒后，以一次性证明执行存储迁移；成功后由运维启动应用。
set -euo pipefail
umask 077
compose=(docker compose "$@")
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
proof_file=""
cleanup() {
  if [[ -n "$proof_file" ]]; then rm -f "$proof_file"; fi
}
trap cleanup EXIT

# 先关闭沙盒入口，再仅启动控制器执行全量退出，避免旧进程继续接受创建请求。
"${compose[@]}" stop api worker sandbox-provisioner
services="$("${compose[@]}" config --services)"
for service in equipment-worker equipment-query-worker; do
  if [[ $'\n'"$services"$'\n' == *$'\n'"$service"$'\n'* ]]; then
    "${compose[@]}" stop "$service"
  fi
done
"${compose[@]}" up -d --no-deps --build --wait sandbox-provisioner
"${compose[@]}" exec -T sandbox-provisioner python - <<'PY'
import json
import os
from urllib.request import Request, urlopen
request = Request(
    'http://127.0.0.1:8002/api/sandboxes/quiesce?timeout_seconds=180',
    data=b'', method='POST',
    headers={'Authorization': 'Bearer ' + os.environ['SANDBOX_PROVISIONER_TOKEN']},
)
with urlopen(request, timeout=195) as response:
    result = json.load(response)
if result.get('ok') is not True:
    raise RuntimeError('沙盒未确认全部退出，拒绝执行存储迁移')
PY
"${compose[@]}" stop sandbox-provisioner
running="$("${compose[@]}" ps --status running --services)"
for service in api worker sandbox-provisioner equipment-worker equipment-query-worker; do
  if [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]]; then
    echo "文件写入者仍在运行：${service}；拒绝迁移。" >&2
    exit 1
  fi
done
"${compose[@]}" up -d --wait postgres
# Docker Desktop 只保证项目共享目录可作为宿主 bind source；macOS 的
# TMPDIR 位于 /var/folders，传给 Linux VM 时会被当作不存在目录。
proof_file="$(mktemp "$project_root/.deepquest-migration.XXXXXX")"
quiescence_token="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
printf '%s\n' "$quiescence_token" > "$proof_file"
# token 只传给一次性进程，不写入长期环境配置。
# 证明文件挂在独立的 /run 路径，避免 Docker Desktop 对已有
# /app/legacy-saves bind mount 再叠加单文件挂载时把目标解析成目录。
"${compose[@]}" run --rm --no-deps \
  -v "$proof_file:/run/storage-migration-quiescence-proof:ro" \
  -e "DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_TOKEN=$quiescence_token" \
  -e "DEEP_RESEARCH_STORAGE_MIGRATION_QUIESCENCE_FILE=/run/storage-migration-quiescence-proof" \
  storage-migrator
printf '存储迁移完成；应用保持停止，请使用相同 Compose 配置启动。\n'
