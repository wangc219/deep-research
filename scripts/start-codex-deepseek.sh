#!/usr/bin/env bash
set -euo pipefail

# DeepSeek via Codex CLI. Official DeepSeek uses native Responses; third-party
# relay hosts are bridged automatically.
# Fill EQUIPMENT_DR_DEEPSEEK_* in `.env`, then:
#   ./scripts/start-codex-deepseek.sh
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${EQUIPMENT_DR_ENV_FILE:-$ROOT/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "未找到 $ENV_FILE。请复制 .env.example 为 .env，并填写 DeepSeek 区块。" >&2
  exit 1
fi
export EQUIPMENT_DR_ENV_FILE="$ENV_FILE"

set -a
source "$ENV_FILE"
set +a
export EQUIPMENT_DR_PROVIDER=codex_deepseek
export EQUIPMENT_DR_MODE=real
export EQUIPMENT_DR_MODEL="${EQUIPMENT_DR_DEEPSEEK_MODEL:-${EQUIPMENT_DR_MODEL:-deepseek-v4-flash}}"
export EQUIPMENT_DR_REQUIRE_DEEPSEEK=1
"$ROOT/scripts/start-local.sh"
