#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

load_dotenv_defaults() {
  local dotenv="${EQUIPMENT_DR_ENV_FILE:-}"
  if [[ -z "$dotenv" ]]; then
    if [[ -f "$ROOT/.env.codex" ]]; then
      dotenv="$ROOT/.env.codex"
    else
      dotenv="$ROOT/.env"
    fi
  fi
  if [[ "$dotenv" != /* ]]; then
    dotenv="$ROOT/$dotenv"
  fi
  [[ -f "$dotenv" ]] || return 0

  local line name index
  local -a override_names=()
  local -a override_values=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    name="${line%%=*}"
    if printenv "$name" >/dev/null 2>&1; then
      override_names+=("$name")
      override_values+=("${!name}")
    fi
  done < "$dotenv"

  set -a
  # .env is a local deployment file controlled by the project owner.
  source "$dotenv"
  set +a

  for ((index = 0; index < ${#override_names[@]}; index++)); do
    printf -v "${override_names[$index]}" '%s' "${override_values[$index]}"
    export "${override_names[$index]}"
  done
}

load_dotenv_defaults

PYTHON_BIN="${EQUIPMENT_DR_PYTHON_BIN:-python3}"
if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1 \
    && python -c 'import uvicorn' >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "未找到已安装 uvicorn 的 Python；可通过 EQUIPMENT_DR_PYTHON_BIN 指定项目解释器。" >&2
    exit 1
  fi
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
export EQUIPMENT_DR_APP_DB="${EQUIPMENT_DR_APP_DB:-sqlite:///$ROOT/outputs/application.db}"
export EQUIPMENT_DR_PROJECT_ROOT="$ROOT"
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}}"
export EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY="${EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY:-4}"
if [[ ! "$EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY" =~ ^[1-8]$ ]]; then
  echo "EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY 必须为 1 到 8。" >&2
  exit 1
fi
if (( EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY > 1 )); then
  export EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY="${EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY:-4}"
fi

RUNTIME_DIR="${EQUIPMENT_DR_RUNTIME_DIR:-$ROOT/outputs/runtime}"
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

pids=()
stop() {
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap stop EXIT INT TERM

"$PYTHON_BIN" -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port "${EQUIPMENT_DR_API_PORT:-8000}" --no-access-log &
api_pid="$!"
pids+=("$api_pid")

# Vite starts faster than Uvicorn and immediately requests catalog/health data.
# Wait for the API readiness endpoint first so a normal restart does not flash a
# false offline state or emit avoidable proxy ECONNREFUSED errors.
api_ready=0
for _ in {1..50}; do
  if curl -fsS "http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}/api/v1/health" >/dev/null 2>&1; then
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

for ((slot = 1; slot <= EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY; slot++)); do
  if (( slot == 1 )); then
    "$PYTHON_BIN" -m equipment_deep_research.interfaces.worker \
      --project-root "$ROOT" \
      --output-root "$ROOT/outputs/runs" \
      --worker-id "research-worker-$slot" \
      --poll-interval 1 \
      --max-idle-poll-interval 5 &
  else
    "$PYTHON_BIN" -m equipment_deep_research.interfaces.worker \
      --project-root "$ROOT" \
      --output-root "$ROOT/outputs/runs" \
      --worker-id "research-worker-$slot" \
      --poll-interval 1 \
      --max-idle-poll-interval 5 \
      --disable-orphan-recovery &
  fi
  pids+=("$!")
done
(
  cd apps/web
  exec ./node_modules/.bin/vite --host 127.0.0.1 --port "${EQUIPMENT_DR_WEB_PORT:-5173}" --strictPort
) &
pids+=("$!")

# Fail fast when a port conflict or startup error terminates any child. Without
# this check, a duplicate launch could leave an orphan Worker polling forever.
sleep 1
for pid in "${pids[@]}"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "本地服务启动失败；已停止本次启动产生的其余进程。" >&2
    exit 1
  fi
done

echo "API: http://127.0.0.1:${EQUIPMENT_DR_API_PORT:-8000}"
echo "Web: http://127.0.0.1:${EQUIPMENT_DR_WEB_PORT:-5173}"
echo "API、${EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY} 个并行 Worker 与 Web 已统一启动；按 Ctrl+C 停止。"
wait
