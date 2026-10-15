#!/usr/bin/env bash
# 云端配置固定叠加，避免运维时意外暴露 API 端口。
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"
exec docker compose --env-file .env.prod -f compose.prod.yaml -f compose.cloud.yaml "$@"
