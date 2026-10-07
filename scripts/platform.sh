#!/usr/bin/env bash
# Deep Research 一体化系统的唯一运行入口。
# start 自动完成首次初始化、构建和启动；up 仅启动已有镜像。
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"

# Shell-level compatibility is intentionally isolated here. Compose and the
# application use only DEEP_RESEARCH_* as their primary contract.
TASK_COMPAT_SUFFIXES=(
  ENV_FILE VERSION INSTANCE_ID STATE_DIR API_PORT WEB_PORT SANDBOX_PORT
  NEO4J_HTTP_PORT NEO4J_BOLT_PORT MINIO_API_PORT MINIO_CONSOLE_PORT
  MILVUS_PORT MILVUS_HEALTH_PORT POSTGRES_PORT REDIS_PORT MINERU_PORT PADDLEX_PORT
  CORS_ORIGINS DATASET_PERSIST_BATCH_SIZE
)
for TASK_SUFFIX in "${TASK_COMPAT_SUFFIXES[@]}"; do
  TASK_OLD_NAME="YUXI_${TASK_SUFFIX}"
  TASK_NEW_NAME="DEEP_RESEARCH_${TASK_SUFFIX}"
  if [[ -z "${!TASK_NEW_NAME+x}" && -n "${!TASK_OLD_NAME+x}" ]]; then
    export "${TASK_NEW_NAME}=${!TASK_OLD_NAME}"
  fi
done

TASK_MODE="${PLATFORM_MODE:-local}"
case "$TASK_MODE" in
  local) TASK_COMPOSE=(-f compose.yaml -f compose.local.yaml) ;;
  dev) TASK_COMPOSE=(-f compose.yaml) ;;
  prod) TASK_COMPOSE=(-f compose.prod.yaml) ;;
  *) echo 'PLATFORM_MODE 仅支持 local、dev、prod' >&2; exit 2 ;;
esac
if [[ "$TASK_MODE" == prod ]]; then
  TASK_ENV="${DEEP_RESEARCH_ENV_FILE:-.env.prod}"
else
  TASK_ENV="${DEEP_RESEARCH_ENV_FILE:-.env}"
fi

TASK_ACTION="${1:-up}"
if [[ $# -gt 0 ]]; then shift; fi

# start 是面向用户的一键入口。仅在默认本地配置缺失或安全项不完整时运行初始化，
# 避免每次启动都重复扫描和拉取基础镜像。
if [[ "$TASK_ACTION" == "start" ]]; then
  echo '🚀 Deep Research 一体化系统'
  echo '================================'
  if [[ "$TASK_MODE" != "prod" && "$TASK_ENV" == ".env" ]]; then
    if [[ ! -f "$TASK_ENV" ]] || ! bash scripts/init.sh --validate-security-env >/dev/null 2>&1; then
      bash scripts/init.sh
    else
      echo '✅ 系统配置已就绪'
    fi
  fi
fi

if [[ ! -f "$TASK_ENV" ]]; then
  echo "缺少 ${TASK_ENV}；请先运行 bash scripts/platform.sh start 完成初始化。" >&2
  exit 1
fi
bash scripts/migrate-environment.sh "$TASK_ENV"
TASK_FILE_WEB_PORT="$(awk -F= '/^DEEP_RESEARCH_WEB_PORT=/{print substr($0, index($0, "=") + 1); exit}' "$TASK_ENV")"
if [[ "$TASK_MODE" == "prod" ]]; then
  TASK_DEFAULT_WEB_PORT=80
else
  TASK_DEFAULT_WEB_PORT=5173
fi
TASK_WEB_PORT="${DEEP_RESEARCH_WEB_PORT:-${TASK_FILE_WEB_PORT:-$TASK_DEFAULT_WEB_PORT}}"
TASK_COMPOSE=(--env-file "$TASK_ENV" "${TASK_COMPOSE[@]}")
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-2}"
case "$TASK_ACTION" in
  start)
    echo '🛠️  正在构建 Deep Research...'
    docker compose "${TASK_COMPOSE[@]}" build "$@"
    echo '▶️  正在启动 Deep Research...'
    docker compose "${TASK_COMPOSE[@]}" up -d "$@"
    echo "✅ Deep Research 已启动：http://localhost:${TASK_WEB_PORT}"
    ;;
  up) docker compose "${TASK_COMPOSE[@]}" up -d "$@" ;;
  build) docker compose "${TASK_COMPOSE[@]}" build "$@" ;;
  update)
    docker compose "${TASK_COMPOSE[@]}" build "$@"
    docker compose "${TASK_COMPOSE[@]}" up -d "$@"
    ;;
  stop) docker compose "${TASK_COMPOSE[@]}" stop "$@" ;;
  status) docker compose "${TASK_COMPOSE[@]}" ps "$@" ;;
  logs) docker compose "${TASK_COMPOSE[@]}" logs --tail 100 "$@" ;;
  config) docker compose "${TASK_COMPOSE[@]}" config --quiet ;;
  *) echo '用法: bash scripts/platform.sh {start|up|build|update|stop|status|logs|config} [服务名...]' >&2; exit 2 ;;
esac
