# 在构建期准备桌面采集程序，网页用户无需安装 Go 或手动编译。
FROM golang:1.27-bookworm AS video-collectors
ARG GOPROXY=https://proxy.golang.org,direct
ENV GOPROXY=${GOPROXY}
WORKDIR /source
COPY vendor/wx_channels_download /source/vendor/wx_channels_download
COPY scripts/build-video-collectors.sh /source/scripts/build-video-collectors.sh
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    VIDEO_COLLECTOR_BIN_DIR=/collectors bash /source/scripts/build-video-collectors.sh

# 使用轻量级Python基础镜像
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
COPY --from=node:24-slim /usr/local/bin /usr/local/bin
COPY --from=node:24-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node:24-slim /usr/local/include /usr/local/include
COPY --from=node:24-slim /usr/local/share /usr/local/share

# 设置工作目录
WORKDIR /app

# 环境变量设置
ENV TZ=Asia/Shanghai \
    UV_PROJECT_ENVIRONMENT="/usr/local" \
    UV_COMPILE_BYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# 设置 npm 镜像源，为 MCP 和 Skills 安装依赖
RUN npm config set registry https://registry.npmmirror.com --global \
    && npm cache clean --force

# 设置代理和时区，更换镜像源，安装系统依赖 - 合并为一个RUN减少层数
RUN set -ex \
    # (A) 设置时区
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    # (B) 替换清华源 (针对 Debian Bookworm 的新版格式)
    && sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|security.debian.org/debian-security|mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    # (C) 安装必要的系统库
    && apt-get update \
    && apt-get install -y --no-install-recommends --fix-missing \
        curl \
        ffmpeg \
        fonts-liberation \
        fonts-noto-cjk \
        git \
        libpq5 \
        libsm6 \
        libxext6 \
        libreoffice-calc-nogui \
        libreoffice-impress-nogui \
        libreoffice-writer-nogui \
    # (D) 清理垃圾，减小体积
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 大体积、低频变化的运行时依赖必须位于业务源码 COPY 之前。这样修改 Agent、
# API 或 Worker Python 代码时，只重建后面的轻量应用层。

# 视频号识别引擎使用独立的 Python 3.12，避免污染平台模型依赖。
ARG INSTALL_VIDEO_TRANSCRIBER=true
ARG VIDEO_PIP_INDEX_URL=https://pypi.org/simple
ARG VIDEO_TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
COPY backend/video-transcriber-requirements.txt /app/video-transcriber-requirements.txt
ENV UV_PYTHON_INSTALL_DIR=/opt/video-python
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_VIDEO_TRANSCRIBER" = "true" ]; then \
      uv venv --python 3.12 /opt/video-asr \
      && if [ "$(uname -m)" = "x86_64" ]; then \
        uv --no-config pip install --index-url "$VIDEO_TORCH_INDEX_URL" --no-deps \
          --python /opt/video-asr/bin/python 'torch==2.5.1+cpu' 'torchaudio==2.5.1+cpu'; \
      fi \
      && sed '/^--extra-index-url /d' /app/video-transcriber-requirements.txt > /tmp/video-transcriber-runtime.txt \
      && uv --no-config pip install --index-url "$VIDEO_PIP_INDEX_URL" \
          --python /opt/video-asr/bin/python -r /tmp/video-transcriber-runtime.txt \
      && rm /tmp/video-transcriber-runtime.txt; \
    fi

# 公众号原版应用使用独立依赖环境，并安装 PDF 所需 Chromium。
ARG WECHAT_MP_PIP_INDEX_URL=https://pypi.org/simple
ARG PLAYWRIGHT_DOWNLOAD_HOST
COPY backend/wechat_mp/requirements-mp.txt /app/wechat-mp-requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python /usr/local/bin/python /opt/wechat-mp \
    && uv --no-config pip install --index-url "$WECHAT_MP_PIP_INDEX_URL" \
        --python /opt/wechat-mp/bin/python -r /app/wechat-mp-requirements.txt \
    && PLAYWRIGHT_DOWNLOAD_HOST="$PLAYWRIGHT_DOWNLOAD_HOST" \
        PLAYWRIGHT_BROWSERS_PATH=/opt/wechat-mp-browsers /opt/wechat-mp/bin/playwright install --with-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/wechat-mp-browsers

# 编译产物、入口和运行身份同样与业务 Python 源码解耦。
COPY --from=video-collectors /collectors /app/video_collector/bin
COPY vendor/wx_channels_download /app/vendor/wx_channels_download
COPY docker/api-entrypoint.sh /usr/local/bin/deep-research-entrypoint
RUN groupadd --gid 1000 platform \
    && useradd --uid 1000 --gid 1000 --create-home platform \
    && mkdir -p /app/runtime /home/platform/.cache/rapidocr/models \
    && chown -R 1000:1000 /app/runtime /home/platform \
    && chmod 0755 /usr/local/bin/deep-research-entrypoint

# 复制项目配置文件
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/.python-version /app/.python-version
COPY backend/uv.lock /app/uv.lock

# 依赖层只依赖锁文件和包元数据；修改业务代码不重新安装全部依赖。
COPY backend/package/pyproject.toml backend/package/README.md /app/package/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --group test --no-dev --frozen --no-install-project --no-install-package platform-core

COPY backend/package /app/package
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --group test --no-dev --frozen

# 高频变化的业务源码集中在镜像尾部。
COPY backend/wechat_mp /app/wechat_mp

# 复制 server 代码
COPY backend/server /app/server
COPY backend/video_collector /app/video_collector

ENV HOME=/home/platform \
    RAPIDOCR_MODEL_DIR=/home/platform/.cache/rapidocr/models

USER 1000:1000

ENTRYPOINT ["/usr/local/bin/deep-research-entrypoint"]
