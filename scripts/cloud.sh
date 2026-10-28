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

build_api_image() {
  local cache_root="${CLOUD_BUILDKIT_CACHE_DIR:-/var/cache/deepquest-buildkit/api}"
  case "$cache_root" in
    ""|/|/var|/var/cache|/opt|/opt/deep-research)
      echo "拒绝使用过宽的 BuildKit 缓存目录: $cache_root" >&2
      return 2
      ;;
  esac

  local cache_current="${cache_root%/}/current"
  local cache_next="${cache_root%/}/next"
  local cache_previous="${cache_root%/}/previous"
  mkdir -p "$cache_root"
  rm -rf -- "$cache_next"
  export CLOUD_BUILDKIT_CACHE_FROM="$cache_current"
  export CLOUD_BUILDKIT_CACHE_TO="$cache_next"

  if ! "${compose[@]}" build "$@" api; then
    rm -rf -- "$cache_next"
    return 1
  fi
  if [[ ! -f "$cache_next/index.json" ]]; then
    echo "BuildKit 未生成预期的本地缓存索引: $cache_next/index.json" >&2
    return 1
  fi

  rm -rf -- "$cache_previous"
  if [[ -e "$cache_current" ]]; then
    mv "$cache_current" "$cache_previous"
  fi
  mv "$cache_next" "$cache_current"
  rm -rf -- "$cache_previous"
}

if [[ "${1:-}" == "document-init" ]]; then
  shift
  exec "${compose[@]}" run --rm --no-deps document-research init "$@"
fi

# 业务代码发布只构建一次共享 API 镜像；所有执行池随后复用同一镜像。
# 稳定的 ASR/Playwright 层由 Dockerfile 顺序和宿主机持久缓存共同保证命中。
if [[ "${1:-}" == "app-up" ]]; then
  shift
  build_api_image
  exec "${compose[@]}" up -d --no-build "$@" \
    api worker equipment-worker equipment-query-worker \
    chat-worker deep-worker subagent-worker
fi

# 保持既有 `cloud.sh build api` 用法，同时自动维护持久缓存。带其他服务名的
# 组合构建仍交给 docker compose 原样处理。
if [[ "${1:-}" == "build" ]]; then
  only_api=true
  has_api=false
  build_options=()
  for arg in "${@:2}"; do
    if [[ "$arg" == "api" ]]; then
      has_api=true
    elif [[ "$arg" == -* ]]; then
      build_options+=("$arg")
    else
      only_api=false
    fi
  done
  if [[ "$has_api" == "true" && "$only_api" == "true" ]]; then
    build_api_image "${build_options[@]}"
    exit $?
  fi
fi

exec "${compose[@]}" "$@"
