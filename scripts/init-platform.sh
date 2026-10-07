#!/usr/bin/env bash
# 保留旧入口名称，统一使用同一套初始化逻辑。
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/init.sh" "$@"
