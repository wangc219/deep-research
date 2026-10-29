#!/usr/bin/env bash
# One-time, value-preserving migration from legacy environment and state names.
set -euo pipefail

TASK_ENV_FILE="${1:-.env}"
[[ -f "$TASK_ENV_FILE" ]] || exit 0

TASK_MAPPINGS=(
  ENV ENV_FILE VERSION INSTANCE_ID STATE_DIR API_PORT WEB_PORT SANDBOX_PORT
  NEO4J_HTTP_PORT NEO4J_BOLT_PORT MINIO_API_PORT MINIO_CONSOLE_PORT
  MILVUS_PORT MILVUS_HEALTH_PORT POSTGRES_PORT REDIS_PORT MINERU_PORT PADDLEX_PORT
  CORS_ORIGINS DATASET_PERSIST_BATCH_SIZE RUNTIME_DIR USER_DATA_DIR
  LEGACY_STORAGE_DIR SKILL_DATA_DIR SKILL_PROJECTION_DIR JOB_TIMEOUT_SECONDS
  CODE_REVISION URL_WHITELIST NETWORK_RETRY_BUDGET_SECONDS BRAND_FILE_PATH
  SUPER_ADMIN_NAME SUPER_ADMIN_PASSWORD
  STORAGE_MIGRATION_QUIESCENCE_TOKEN STORAGE_MIGRATION_QUIESCENCE_FILE
)

task_read_env_value() {
  local name="$1"
  awk -v name="$name" '
    index($0, name "=") == 1 && !found {
      print substr($0, length(name) + 2)
      found = 1
    }
  ' "$TASK_ENV_FILE"
}

task_set_env_value() {
  local name="$1" value="$2"
  ENV_VALUE="$value" awk -v name="$name" '
    $0 ~ "^" name "=" {
      if (!updated) {
        print name "=" ENVIRON["ENV_VALUE"]
        updated = 1
      }
      next
    }
    { print }
    END {
      if (!updated) print name "=" ENVIRON["ENV_VALUE"]
    }
  ' "$TASK_ENV_FILE" > "${TASK_ENV_FILE}.tmp"
  mv "${TASK_ENV_FILE}.tmp" "$TASK_ENV_FILE"
}

task_remove_env_key() {
  local name="$1"
  awk -v name="$name" '$0 !~ "^" name "=" { print }' "$TASK_ENV_FILE" > "${TASK_ENV_FILE}.tmp"
  mv "${TASK_ENV_FILE}.tmp" "$TASK_ENV_FILE"
}

task_generate_hex() {
  local length="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$length"
  else
    od -An -N "$length" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

TASK_MIGRATED=0
for TASK_SUFFIX in "${TASK_MAPPINGS[@]}"; do
  TASK_OLD_NAME="YUXI_${TASK_SUFFIX}"
  TASK_NEW_NAME="DEEP_RESEARCH_${TASK_SUFFIX}"
  if grep -qE "^${TASK_OLD_NAME}=" "$TASK_ENV_FILE"; then
    if ! grep -qE "^${TASK_NEW_NAME}=" "$TASK_ENV_FILE"; then
      task_set_env_value "$TASK_NEW_NAME" "$(task_read_env_value "$TASK_OLD_NAME")"
    fi
    task_remove_env_key "$TASK_OLD_NAME"
    TASK_MIGRATED=$((TASK_MIGRATED + 1))
  fi
done

# SearXNG 只在内部网络提供 API，但仍使用独立 secret。旧部署通过官方
# platform.sh 入口启动时在 Compose 解析前自动、幂等补全。
TASK_SEARXNG_SECRET="$(task_read_env_value SEARXNG_SECRET)"
if [[ ${#TASK_SEARXNG_SECRET} -lt 32 ]]; then
  task_set_env_value SEARXNG_SECRET "$(task_generate_hex 32)"
  TASK_MIGRATED=$((TASK_MIGRATED + 1))
fi

# The unified platform uses a product-neutral state directory. Preserve an
# existing deployment in place and retain its historical PostgreSQL database
# name only when migrating real state; fresh deployments use deep_research.
TASK_STATE_ROOT="$(task_read_env_value DEEP_RESEARCH_STATE_DIR)"
TASK_STATE_ROOT="${TASK_STATE_ROOT:-./docker/volumes}"
TASK_LEGACY_STATE_DIR="${TASK_STATE_ROOT%/}/yuxi"
TASK_PLATFORM_STATE_DIR="${TASK_STATE_ROOT%/}/platform"
if [[ -d "$TASK_LEGACY_STATE_DIR" && ! -e "$TASK_PLATFORM_STATE_DIR" ]]; then
  mv "$TASK_LEGACY_STATE_DIR" "$TASK_PLATFORM_STATE_DIR"
  if ! grep -qE '^POSTGRES_DB=' "$TASK_ENV_FILE"; then
    task_set_env_value POSTGRES_DB yuxi
  fi
  if ! grep -qE '^MILVUS_DB=' "$TASK_ENV_FILE"; then
    task_set_env_value MILVUS_DB yuxi
  fi
  TASK_MIGRATED=$((TASK_MIGRATED + 1))
  echo "✅ 已将历史状态目录迁移为 ${TASK_PLATFORM_STATE_DIR}"
fi

chmod 600 "$TASK_ENV_FILE"
if (( TASK_MIGRATED > 0 )); then
  echo "✅ 已完成 ${TASK_MIGRATED} 项平台兼容迁移"
fi
