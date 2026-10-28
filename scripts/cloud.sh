#!/usr/bin/env bash
# 云端配置固定叠加，避免运维时意外暴露 API 端口。
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-1}"

compose=(
  docker compose
  --env-file .env.prod
)

# 容量参数独立于凭据；升级服务器后可显式叠加新的容量档位。
if [[ -n "${CLOUD_CAPACITY_ENV_FILE:-}" ]]; then
  if [[ ! -r "$CLOUD_CAPACITY_ENV_FILE" ]]; then
    echo "容量配置文件不可读: $CLOUD_CAPACITY_ENV_FILE" >&2
    exit 1
  fi
  compose+=(--env-file "$CLOUD_CAPACITY_ENV_FILE")
fi

compose+=(
  -f compose.prod.yaml
  -f docker/document-research/compose.yaml
  -f compose.cloud.yaml
)

if [[ "${VIDEO_CENTRAL_BRIDGE:-0}" == "1" ]]; then
  compose+=(-f compose.video-bridge.yaml --profile video-bridge)
fi

if [[ "${CLOUD_WECHAT_COLLECTOR:-0}" == "1" ]]; then
  compose+=(-f compose.wx-collector.yaml --profile cloud-wechat)
fi

if [[ "${1:-}" == "document-init" ]]; then
  shift
  exec "${compose[@]}" run --rm --no-deps document-research init "$@"
fi

exec "${compose[@]}" "$@"
