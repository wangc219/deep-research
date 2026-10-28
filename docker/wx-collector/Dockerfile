FROM lscr.io/linuxserver/webtop@sha256:a62457e276e56991f0d8b8c879e2cbce2ac198e4446af2773503470c5ccbd81d AS collector-build
RUN apt-get update && apt-get install -y --no-install-recommends golang-go gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY collector-source/ /src/
RUN CGO_ENABLED=1 GOMAXPROCS=2 go build -mod=vendor -p=2 -trimpath \
    -tags 'with_gvisor,embed_frontend_inject' -ldflags='-s -w -X main.Mode=release' \
    -o /build/wx_video_download .

FROM lscr.io/linuxserver/webtop@sha256:a62457e276e56991f0d8b8c879e2cbce2ac198e4446af2773503470c5ccbd81d
ENV DEBIAN_FRONTEND=noninteractive LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8 \
    LIBGL_ALWAYS_SOFTWARE=1 WX_IN_DOCKER=1 \
    WX_VIDEO_HOME=/config/wx_video_download \
    WX_VIDEO_SEED_HOME=/usr/local/share/wx_video_download \
    WX_CHANNELS_DOWNLOAD_CONFIG_FILEPATH=/config/wx_video_download/config.yaml \
    WX_VIDEO_RUN_AS_ROOT=false WECHAT_BIN=/usr/bin/wechat
COPY WeChatLinux_x86_64.deb /tmp/WeChatLinux_x86_64.deb
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates locales procps psmisc iproute2 iptables nftables sudo \
    libcap2-bin xdotool xclip libnss3-tools fonts-wqy-zenhei fonts-noto-color-emoji \
    openssl python3 /tmp/WeChatLinux_x86_64.deb \
    && sed -i 's/# *zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen && rm /tmp/WeChatLinux_x86_64.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=collector-build /build/wx_video_download /usr/local/share/wx_video_download/wx_video_download
COPY config.yaml /usr/local/share/wx_video_download/config.yaml
COPY rootfs/ /
RUN chmod +x /usr/local/bin/wx-* /custom-cont-init.d/* \
    && touch /usr/local/share/wx_video_download/global.js
EXPOSE 2022
