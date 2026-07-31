FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISPLAY=:99 \
    CHROME_BIN=/usr/bin/chromium \
    CRAWLER_DATA_ROOT=/workspace/data \
    PYTHONPATH=/workspace/modules/demand_discovery/src:/workspace/modules/mineru/src:/workspace/modules/wechat/wechat_mp_collector:/workspace/modules/cnki:/workspace/modules/journal

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        curl \
        fonts-noto-cjk \
        novnc \
        openbox \
        websockify \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt
RUN python -m pip install --no-cache-dir -r /workspace/requirements.txt \
    && python -m playwright install chromium

COPY . /workspace
RUN chmod +x /workspace/bin/start-novnc.sh \
    && mkdir -p /workspace/data/raw /workspace/data/processed /workspace/runtime/sessions

CMD ["python", "crawler.py", "--help"]
