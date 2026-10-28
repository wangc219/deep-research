FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120
WORKDIR /opt/document-research

COPY document_research/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.lock \
    && groupadd --gid 1000 document-research \
    && useradd --uid 1000 --gid 1000 --no-create-home document-research \
    && mkdir -p /var/lib/document-research \
    && chown 1000:1000 /var/lib/document-research \
    && chmod 700 /var/lib/document-research

COPY document_research/*.py ./document_research/
COPY docker/document-research/entrypoint.py ./container-entrypoint.py

USER 1000:1000
EXPOSE 4198
ENTRYPOINT ["python", "/opt/document-research/container-entrypoint.py"]
CMD ["serve"]
