#!/usr/bin/env bash
# 构建网站一键连接包所需的 macOS / Windows 程序；无需用户安装 Go。
set -euo pipefail
video_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
video_binary_dir="${VIDEO_COLLECTOR_BIN_DIR:-$video_repo_root/backend/video_collector/bin}"
cd "$video_repo_root/vendor/wx_channels_download"
for video_target in darwin/arm64 darwin/amd64 windows/amd64 windows/arm64; do
  video_os="${video_target%/*}"
  video_arch="${video_target#*/}"
  video_extension=''
  if [[ "$video_os" == windows ]]; then video_extension='.exe'; fi
  mkdir -p "$video_binary_dir/$video_os-$video_arch"
  GOOS="$video_os" GOARCH="$video_arch" CGO_ENABLED=0 go build -tags 'embed_inject,embed_frontend_inject' -trimpath -ldflags='-s -w' \
    -o "$video_binary_dir/$video_os-$video_arch/video-downloader$video_extension" .
done
