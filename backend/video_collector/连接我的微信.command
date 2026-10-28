#!/bin/bash
set -euo pipefail
video_bundle_root="$(cd -- "$(dirname -- "$0")" && pwd)"
video_uv_dir="$HOME/.research-video-collector/tools"
video_pause_on_error() {
  echo '连接未完成。请保留上方错误信息；检查网络后重新双击。'
  read -r -p '按回车关闭窗口…' || true
}
trap video_pause_on_error ERR
if command -v uv >/dev/null 2>&1; then
  video_uv_command="$(command -v uv)"
elif [[ -x "$video_uv_dir/uv" ]]; then
  video_uv_command="$video_uv_dir/uv"
else
  echo '首次使用，正在自动准备连接环境。请保持网络连接。'
  curl --fail --location --silent --show-error --connect-timeout 15 --max-time 120 --retry 2 https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$video_uv_dir" UV_NO_MODIFY_PATH=1 sh
  video_uv_command="$video_uv_dir/uv"
fi
cd "$video_bundle_root"
echo '正在准备微信连接，已安装的环境会自动复用。请保持此窗口运行。'
"$video_uv_command" --no-config run --no-project --python 3.12 --with httpx --with imageio-ffmpeg bootstrap.py
