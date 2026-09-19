#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_dotenv_defaults() {
  local explicit_dotenv="${EQUIPMENT_DR_ENV_FILE:-}"
  local line name index dotenv
  local -a dotenv_files=()
  local -a override_names=()
  local -a override_values=()

  if [[ -n "$explicit_dotenv" ]]; then
    [[ "$explicit_dotenv" == /* ]] || explicit_dotenv="$ROOT/$explicit_dotenv"
    dotenv_files+=("$explicit_dotenv")
  else
    # Unified primary file. Legacy `.env.codex` remains an optional overlay.
    [[ -f "$ROOT/.env" ]] && dotenv_files+=("$ROOT/.env")
    [[ -f "$ROOT/.env.codex" ]] && dotenv_files+=("$ROOT/.env.codex")
  fi
  # `.env.local` is secret-free UI activation (profile id / swarm overrides).
  [[ -f "$ROOT/.env.local" ]] && dotenv_files+=("$ROOT/.env.local")
  (( ${#dotenv_files[@]} > 0 )) || return 0

  # Capture only variables that existed before loading any project file. This
  # lets later files override earlier ones while preserving explicit shell overrides.
  local captured_names="|"
  for name in EQUIPMENT_DR_PROFILE EQUIPMENT_DR_PROVIDER EQUIPMENT_DR_MODEL; do
    if printenv "$name" >/dev/null 2>&1; then
      captured_names+="$name|"
      override_names+=("$name")
      override_values+=("${!name}")
    fi
  done
  for dotenv in "${dotenv_files[@]}"; do
    [[ -f "$dotenv" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
      name="${line%%=*}"
      if [[ "$captured_names" != *"|$name|"* ]] && printenv "$name" >/dev/null 2>&1; then
        captured_names+="$name|"
        override_names+=("$name")
        override_values+=("${!name}")
      fi
    done < "$dotenv"
  done

  set -a
  for dotenv in "${dotenv_files[@]}"; do
    [[ -f "$dotenv" ]] && source "$dotenv"
  done
  set +a

  for ((index = 0; index < ${#override_names[@]}; index++)); do
    printf -v "${override_names[$index]}" '%s' "${override_values[$index]}"
    export "${override_names[$index]}"
  done

  # Resolve the selected unified profile after dotenv files are loaded. Only
  # metadata assignments are emitted; credentials remain in their referenced
  # environment variables. Explicit process variables still win.
  local profile_python="${EQUIPMENT_DR_PYTHON_BIN:-}"
  if [[ -z "$profile_python" && -x "$ROOT/.venv/bin/python" ]]; then
    profile_python="$ROOT/.venv/bin/python"
  fi
  profile_python="${profile_python:-python3}"
  if [[ -n "${EQUIPMENT_DR_PROFILE:-}" ]] && [[ -x "$profile_python" || "$profile_python" == "python3" || "$profile_python" == "python" ]]; then
    local profile_assignment profile_name profile_value
    while IFS='=' read -r profile_name profile_value; do
      [[ "$profile_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      [[ "$captured_names" == *"|$profile_name|"* ]] && continue
      export "$profile_name=$profile_value"
    done < <(PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$profile_python" "$ROOT/scripts/model-profile.py" env "$EQUIPMENT_DR_PROFILE" 2>/dev/null || true)
  fi

  # Legacy .env/.env.codex files may carry a historical all-GPT
  # EQUIPMENT_DR_AGENT_MODELS_JSON map. That stale map must not pin every
  # routed agent to a single model id (which makes a DeepSeek / relay profile
  # send an unsupported model and return 404). Keep role-level routing through
  # .env.local or EQUIPMENT_DR_AGENT_*_MODEL variables instead.
  if [[ ! -f "$ROOT/.env.local" ]] || ! grep -qE '^[[:space:]]*EQUIPMENT_DR_AGENT_MODELS_JSON=' "$ROOT/.env.local"; then
    export EQUIPMENT_DR_AGENT_MODELS_JSON='{}'
  fi
  if [[ ! -f "$ROOT/.env.local" ]] || ! grep -qE '^[[:space:]]*EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON=' "$ROOT/.env.local"; then
    export EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON='{}'
  fi

  # Optional DeepSeek-only overlay for experiments. Prefer putting DeepSeek
  # settings in `.env`. When EQUIPMENT_DR_DEEPSEEK_ENV_FILE is set (or the
  # legacy `.env.codex-deepseek` still exists), project only DeepSeek fields.
  local deepseek_env_file="${EQUIPMENT_DR_DEEPSEEK_ENV_FILE:-}"
  if [[ -z "$deepseek_env_file" && -f "$ROOT/.env.codex-deepseek" ]]; then
    # Skip the deprecated stub that no longer carries assignments.
    if grep -qE '^[[:space:]]*EQUIPMENT_DR_DEEPSEEK_(MODEL|BASE_URL)=' "$ROOT/.env.codex-deepseek"; then
      deepseek_env_file="$ROOT/.env.codex-deepseek"
    fi
  fi
  if [[ -n "$deepseek_env_file" ]]; then
    [[ "$deepseek_env_file" == /* ]] || deepseek_env_file="$ROOT/$deepseek_env_file"
  fi
  if [[ -n "$deepseek_env_file" && -f "$deepseek_env_file" ]]; then
    local assignment assignment_name
    while IFS= read -r -d '' assignment; do
      assignment_name="${assignment%%=*}"
      [[ "$captured_names" == *"|$assignment_name|"* ]] && continue
      export "$assignment"
    done < <(
      set -a
      source "$deepseek_env_file"
      set +a
      printf '%s\0' \
        "EQUIPMENT_DR_DEEPSEEK_MODEL=${EQUIPMENT_DR_DEEPSEEK_MODEL:-}" \
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL=${EQUIPMENT_DR_DEEPSEEK_BASE_URL:-}" \
        "EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV=${EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV:-DEEPSEEK_API_KEY}"
      deepseek_key_env="${EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV:-DEEPSEEK_API_KEY}"
      if [[ "$deepseek_key_env" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        printf '%s\0' "$deepseek_key_env=${!deepseek_key_env-}"
      fi
    )
  fi
}

load_dotenv_defaults

# Prepare the dedicated Codex endpoints used by the DeepSeek and Queen task
# profiles. These do not alter the GPT Codex endpoint.
source "$ROOT/scripts/deepseek-codex-routing.sh"
configure_deepseek_codex_route

# Task selection uses ``model_profile_id`` (UI / API), not a process-wide
# EQUIPMENT_DR_PROFILE. Clear only that activation flag so each research task
# can pick GPT or DeepSeek independently.
#
# Keep EQUIPMENT_DR_MODEL / EQUIPMENT_DR_DEEPSEEK_MODEL / base URLs / API keys:
# those are gateway deployment settings that profiles resolve through
# ``model_env`` / ``base_url_env``. Unsetting them makes doctor report
# "接口可达，但模型不在 /models 列表" with an empty model id, and breaks
# relay-station adapters that expect the configured model string.
unset EQUIPMENT_DR_PROFILE

PYTHON_BIN="${EQUIPMENT_DR_PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]] \
    && "$ROOT/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  else
    if ! command -v python3 >/dev/null 2>&1 \
      || ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      echo "项目要求 Python 3.11+；可通过 EQUIPMENT_DR_PYTHON_BIN 指定兼容解释器。" >&2
      exit 1
    fi
    echo "正在为当前机器重建 Python 虚拟环境..."
    python3 -m venv --clear "$ROOT/.venv"
    PYTHON_BIN="$ROOT/.venv/bin/python"
  fi
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "项目要求 Python 3.11+；可通过 EQUIPMENT_DR_PYTHON_BIN 指定兼容解释器。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
  echo "正在安装 Python 项目依赖..."
  "$PYTHON_BIN" -m pip install -r "$ROOT/requirements.txt"
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "未找到 Node.js/npm，无法启动 Web 前端。" >&2
  exit 1
fi
if [[ ! -x "$ROOT/apps/web/node_modules/.bin/vite" ]] \
  || ! node -e "require('$ROOT/apps/web/node_modules/vite/package.json')" >/dev/null 2>&1; then
  echo "正在为当前机器安装 Web 项目依赖..."
  npm --prefix "$ROOT/apps/web" ci
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
export EQUIPMENT_DR_APP_DB="${EQUIPMENT_DR_APP_DB:-sqlite:///$ROOT/outputs/application.db}"
export EQUIPMENT_DR_QUERY_LIBRARY_DB="${EQUIPMENT_DR_QUERY_LIBRARY_DB:-sqlite:///$ROOT/outputs/query-library.db}"
export EQUIPMENT_DR_PROJECT_ROOT="$ROOT"
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}}"
export EQUIPMENT_DR_WEB_HOST="${EQUIPMENT_DR_WEB_HOST:-0.0.0.0}"
export EQUIPMENT_DR_WEB_PORT="${EQUIPMENT_DR_WEB_PORT:-5173}"
export EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY="${EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY:-2}"
if [[ ! "$EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY" =~ ^[1-8]$ ]]; then
  echo "EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY 必须为 1 到 8。" >&2
  exit 1
fi
# Worker capacity controls concurrent research runs. Codex model concurrency is
# a separate, per-run limit used by internal waves such as parallel S6 card
# authoring, even when the deployment has only one Worker slot.
export EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY="${EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY:-8}"
export EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX="${EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX:-8}"
export EQUIPMENT_DR_REPORTER_MODEL_CONCURRENCY="${EQUIPMENT_DR_REPORTER_MODEL_CONCURRENCY:-12}"
export EQUIPMENT_DR_REPORT_COLUMN_TIMEOUT_SECONDS="${EQUIPMENT_DR_REPORT_COLUMN_TIMEOUT_SECONDS:-1200}"
export EQUIPMENT_DR_REPORT_RETRY_TIMEOUT_SECONDS="${EQUIPMENT_DR_REPORT_RETRY_TIMEOUT_SECONDS:-600}"
export EQUIPMENT_DR_REPORT_FALLBACK_TIMEOUT_SECONDS="${EQUIPMENT_DR_REPORT_FALLBACK_TIMEOUT_SECONDS:-900}"
export EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK="${EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK:-1}"
export EQUIPMENT_DR_S6_CODEX_CONCURRENCY="${EQUIPMENT_DR_S6_CODEX_CONCURRENCY:-8}"

RUNTIME_DIR="${EQUIPMENT_DR_RUNTIME_DIR:-$ROOT/outputs/runtime}"
export EQUIPMENT_DR_WORKER_POOL_CONFIG="${EQUIPMENT_DR_WORKER_POOL_CONFIG:-$RUNTIME_DIR/research-worker-pool.json}"
LOCK_DIR="$RUNTIME_DIR/start-local.lock"
mkdir -p "$RUNTIME_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  existing_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "本项目已由进程 $existing_pid 启动；请勿重复运行 start-local.sh。" >&2
    exit 1
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"

"$PYTHON_BIN" -m equipment_deep_research.query_library import-seeds >/dev/null

pids=()
process_names=()
stopping=0

append_descendants() {
  local parent="$1"
  local child
  while IFS= read -r child; do
    [[ "$child" =~ ^[0-9]+$ ]] || continue
    shutdown_targets+=("$child")
    append_descendants "$child"
  done < <(pgrep -P "$parent" 2>/dev/null || true)
}

stop() {
  (( stopping == 0 )) || return 0
  stopping=1
  trap - EXIT INT TERM

  local pid index alive
  local -a shutdown_targets=("${pids[@]:-}")
  for pid in "${pids[@]:-}"; do
    append_descendants "$pid"
  done

  # Stop descendants before their parents. Codex CLI creates a new process
  # session per model turn, so killing only the Worker PID can otherwise leave
  # an active model process behind after an abnormal shutdown.
  for ((index = ${#shutdown_targets[@]} - 1; index >= 0; index--)); do
    kill -TERM "${shutdown_targets[$index]}" 2>/dev/null || true
  done

  for _ in {1..50}; do
    alive=0
    for pid in "${shutdown_targets[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        alive=1
        break
      fi
    done
    (( alive == 0 )) && break
    sleep 0.1
  done

  for pid in "${shutdown_targets[@]}"; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  wait "${pids[@]:-}" 2>/dev/null || true
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap stop EXIT
trap 'exit 130' INT TERM

deepseek_route="${EQUIPMENT_DR_DEEPSEEK_CODEX_ROUTE:-}"
deepseek_key_env="${EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV:-DEEPSEEK_API_KEY}"
deepseek_key_value=""
if [[ "$deepseek_key_env" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  deepseek_key_value="${!deepseek_key_env-}"
fi
if [[ "${EQUIPMENT_DR_REQUIRE_DEEPSEEK:-0}" == "1" ]]; then
  if [[ -z "$deepseek_route" ]]; then
    echo "未配置 EQUIPMENT_DR_DEEPSEEK_BASE_URL。" >&2
    exit 1
  fi
  if [[ -z "$deepseek_key_value" ]]; then
    echo "缺少 DeepSeek 凭据: $deepseek_key_env" >&2
    exit 1
  fi
fi

if [[ "$deepseek_route" == "chat_bridge" ]]; then
  if [[ "${EQUIPMENT_DR_BRIDGE_MANAGED_EXTERNALLY:-0}" == "1" ]]; then
    echo "DeepSeek Codex 路由: 第三方 Chat Completions 中转站 -> 外部托管 Responses bridge"
  elif [[ -n "$deepseek_key_value" ]]; then
    PYTHONPATH="$ROOT/src" "$PYTHON_BIN" "$ROOT/scripts/responses_chat_bridge.py" &
    bridge_pid="$!"
    pids+=("$bridge_pid")
    process_names+=("DeepSeek Responses bridge")

    bridge_ready=0
    for _ in {1..50}; do
      if curl -fsS "http://${EQUIPMENT_DR_BRIDGE_HOST}:${EQUIPMENT_DR_BRIDGE_PORT}/health" >/dev/null 2>&1; then
        bridge_ready=1
        break
      fi
      if ! kill -0 "$bridge_pid" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
    if [[ "$bridge_ready" != "1" ]]; then
      echo "DeepSeek 第三方中转桥接器启动失败或未在 5 秒内就绪。" >&2
      exit 1
    fi
    echo "DeepSeek Codex 路由: 第三方 Chat Completions 中转站 -> 本地 Responses bridge"
  fi
elif [[ "$deepseek_route" == "native_responses" ]]; then
  echo "DeepSeek Codex 路由: 官方原生 Responses API（不启动 bridge）"
fi

"$PYTHON_BIN" -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port "${EQUIPMENT_DR_API_PORT:-8000}" --no-access-log &
api_pid="$!"
pids+=("$api_pid")
process_names+=("API")

# Vite starts faster than Uvicorn and immediately requests catalog/health data.
# Wait for the API readiness endpoint first so a normal restart does not flash a
# false offline state or emit avoidable proxy ECONNREFUSED errors.
api_ready=0
for _ in {1..50}; do
  # The port may already be served by an older API process.  Only accept the
  # health response while the API process launched above is still alive;
  # otherwise a stale listener can make this startup continue and spawn
  # Workers that are immediately orphaned when the new API exits.
  if kill -0 "$api_pid" 2>/dev/null \
    && curl -fsS "http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}/api/v1/health" >/dev/null 2>&1; then
    api_ready=1
    break
  fi
  if ! kill -0 "$api_pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ "$api_ready" != "1" ]]; then
  echo "API 启动失败或未在 5 秒内就绪。" >&2
  exit 1
fi

"$PYTHON_BIN" -m equipment_deep_research.interfaces.worker_pool \
  --project-root "$ROOT" \
  --output-root "$ROOT/outputs/runs" \
  --initial-capacity "$EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY" \
  --poll-interval 0.5 &
pids+=("$!")
process_names+=("research-worker-pool")
"$PYTHON_BIN" -m equipment_deep_research.query_library worker \
  --poll-interval 1 \
  --max-idle-poll-interval "${EQUIPMENT_DR_QUERY_MAX_IDLE_POLL_INTERVAL:-10}" &
pids+=("$!")
process_names+=("query-worker")
(
  cd apps/web
  exec ./node_modules/.bin/vite --host "$EQUIPMENT_DR_WEB_HOST" --port "$EQUIPMENT_DR_WEB_PORT" --strictPort
) &
pids+=("$!")
process_names+=("Web")

# Fail fast when a port conflict or startup error terminates any child. Without
# this check, a duplicate launch could leave an orphan Worker polling forever.
sleep 1
for pid in "${pids[@]}"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "本地服务启动失败；已停止本次启动产生的其余进程。" >&2
    exit 1
  fi
done

detect_lan_ip() {
  local interface lan_ip
  if command -v route >/dev/null 2>&1 && command -v ipconfig >/dev/null 2>&1; then
    interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
    if [[ -n "$interface" ]]; then
      lan_ip="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
    fi
  elif command -v hostname >/dev/null 2>&1; then
    lan_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s' "${lan_ip:-127.0.0.1}"
}

web_access_host="$EQUIPMENT_DR_WEB_HOST"
if [[ "$web_access_host" == "0.0.0.0" || "$web_access_host" == "::" ]]; then
  web_access_host="$(detect_lan_ip)"
fi

echo "API（仅本机）: http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}"
echo "Web（本机）: http://127.0.0.1:$EQUIPMENT_DR_WEB_PORT"
echo "Web（内网）: http://$web_access_host:$EQUIPMENT_DR_WEB_PORT"
echo "API、可动态伸缩的研究 Worker 池、Query 生成 Worker 与 Web 已统一启动；按 Ctrl+C 停止。"

# Bash 3.2 on macOS has no `wait -n`. Poll the small fixed child set so any
# component that exits later tears down the whole local stack instead of
# leaving Workers or Vite running indefinitely.
while true; do
  for ((index = 0; index < ${#pids[@]}; index++)); do
    if ! kill -0 "${pids[$index]}" 2>/dev/null; then
      wait "${pids[$index]}" 2>/dev/null || child_status="$?"
      echo "${process_names[$index]} 已退出（状态 ${child_status:-0}）；正在停止其余本地进程。" >&2
      exit "${child_status:-1}"
    fi
  done
  sleep 1
done
