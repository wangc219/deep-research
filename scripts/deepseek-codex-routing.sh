#!/usr/bin/env bash

# Configure the Codex endpoint used by the DeepSeek model profile. The
# official API speaks Responses natively; every other host is treated as a
# Chat Completions relay and routed through the local protocol bridge.

deepseek_url_host() {
  local url="${1:-}"
  local authority
  authority="${url#*://}"
  authority="${authority%%/*}"
  authority="${authority##*@}"
  authority="${authority%%:*}"
  printf '%s' "$authority" | tr '[:upper:]' '[:lower:]'
}

deepseek_chat_endpoint() {
  local url="${1%/}"
  case "$url" in
    */chat/completions)
      printf '%s' "$url"
      ;;
    */v1)
      printf '%s/chat/completions' "$url"
      ;;
    *)
      printf '%s/v1/chat/completions' "$url"
      ;;
  esac
}

configure_deepseek_codex_route() {
  local source_url="${EQUIPMENT_DR_DEEPSEEK_BASE_URL:-}"
  local source_host
  local source_scheme
  local key_env="${EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV:-DEEPSEEK_API_KEY}"

  [[ -n "$source_url" ]] || return 0
  if [[ ! "$key_env" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV 不是有效的环境变量名。" >&2
    return 1
  fi

  source_host="$(deepseek_url_host "$source_url")"
  source_scheme="$(printf '%s' "${source_url%%://*}" | tr '[:upper:]' '[:lower:]')"
  export EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV="$key_env"
  export EQUIPMENT_DR_CODEX_DEEPSEEK_MODEL="${EQUIPMENT_DR_DEEPSEEK_MODEL:-deepseek-v4-flash}"

  if [[ "$source_scheme" == "https" && "$source_host" == "api.deepseek.com" ]]; then
    export EQUIPMENT_DR_DEEPSEEK_CODEX_ROUTE="native_responses"
    export EQUIPMENT_DR_DEEPSEEK_BRIDGE_REQUIRED=0
    export EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL="https://api.deepseek.com/"
    return 0
  fi

  export EQUIPMENT_DR_DEEPSEEK_CODEX_ROUTE="chat_bridge"
  export EQUIPMENT_DR_DEEPSEEK_BRIDGE_REQUIRED=1
  export EQUIPMENT_DR_BRIDGE_HOST="${EQUIPMENT_DR_BRIDGE_HOST:-${DEEPSEEK_BRIDGE_HOST:-127.0.0.1}}"
  export EQUIPMENT_DR_BRIDGE_PORT="${EQUIPMENT_DR_BRIDGE_PORT:-${DEEPSEEK_BRIDGE_PORT:-8787}}"
  export EQUIPMENT_DR_BRIDGE_MODEL="${EQUIPMENT_DR_BRIDGE_MODEL:-${EQUIPMENT_DR_DEEPSEEK_MODEL:-}}"
  export EQUIPMENT_DR_BRIDGE_API_KEY_ENV="${EQUIPMENT_DR_BRIDGE_API_KEY_ENV:-$key_env}"
  export EQUIPMENT_DR_BRIDGE_UPSTREAM_URL="$(deepseek_chat_endpoint "${EQUIPMENT_DR_BRIDGE_UPSTREAM_URL:-$source_url}")"
  export EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV="$EQUIPMENT_DR_BRIDGE_API_KEY_ENV"
  export EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL="http://${EQUIPMENT_DR_BRIDGE_HOST}:${EQUIPMENT_DR_BRIDGE_PORT}/v1"
}
