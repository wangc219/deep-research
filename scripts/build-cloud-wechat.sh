#!/usr/bin/env bash
# 从已准备并校验过的 amd64 源码及官方微信安装包构建集中采集器。
set -euo pipefail
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
context_dir="${1:?Usage: build-cloud-wechat.sh /absolute/prepared-context [image-tag]}"
image_tag="${2:-deepquest-wx-collector:linux-amd64-20261027}"
test -f "$context_dir/collector-source/go.mod"
test -d "$context_dir/collector-source/vendor"
test -f "$context_dir/WeChatLinux_x86_64.deb"
test "$(dpkg-deb -f "$context_dir/WeChatLinux_x86_64.deb" Architecture)" = amd64
cp "$root_dir/docker/wx-collector/config.yaml" "$context_dir/config.yaml"
cp -a "$root_dir/docker/wx-collector/rootfs/." "$context_dir/rootfs/"
docker build --platform linux/amd64 -f "$root_dir/docker/wx-collector/Dockerfile" -t "$image_tag" "$context_dir"
