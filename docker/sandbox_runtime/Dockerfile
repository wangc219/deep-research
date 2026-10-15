ARG SANDBOX_BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0
FROM ${SANDBOX_BASE_IMAGE}

USER root
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt /opt/artifact-requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/artifact-python \
    && /opt/artifact-python/bin/pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r /opt/artifact-requirements.txt \
    && ln -sf /opt/artifact-python/bin/python /usr/local/bin/python \
    && ln -sf /opt/artifact-python/bin/pip /usr/local/bin/pip
ENV PATH="/opt/artifact-python/bin:${PATH}" \
    MPLBACKEND=Agg
