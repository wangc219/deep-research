#!/usr/bin/env bash
# 只将本机采集端转发到平台私有容器网络，SSH 私钥由用户自行保存。
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo '用法: bash scripts/video-channels-tunnel.sh 云服务器地址 SSH私钥路径' >&2
  exit 2
fi
exec ssh -N -T -i "$2" -p "${VIDEO_BRIDGE_SSH_PORT:-2222}" \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -R 0.0.0.0:2022:127.0.0.1:2022 "video@$1"
