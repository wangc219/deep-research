#!/usr/bin/env bash
set -euo pipefail

# Thin alias: unified config lives in `.env`.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export EQUIPMENT_DR_ENV_FILE="${EQUIPMENT_DR_ENV_FILE:-$ROOT/.env}"
exec "$ROOT/scripts/start-local.sh"
