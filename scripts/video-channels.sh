#!/usr/bin/env bash
# 从仓库内源码构建桌面采集端；运行时数据不进入 vendor。
set -euo pipefail
video_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
video_runtime_dir="${VIDEO_COLLECTOR_RUNTIME_DIR:-$video_project_root/outputs/video-collector}"
video_binary="$video_runtime_dir/wx-video-collector"
case "${1:-help}" in
  build)
    mkdir -p "$video_runtime_dir"
    cd "$video_project_root/vendor/wx_channels_download"
    go build -tags 'embed_inject,embed_frontend_inject' -o "$video_binary" .
    ;;
  start)
    if [[ ! -x "$video_binary" ]]; then bash "$0" build; fi
    shift
    exec "$video_binary" --workdir "$video_runtime_dir" "$@"
    ;;
  status)
    curl --fail --silent --show-error http://127.0.0.1:2022/api/channels/status
    ;;
  *)
    echo '用法: bash scripts/video-channels.sh build | start | status'
    ;;
esac
