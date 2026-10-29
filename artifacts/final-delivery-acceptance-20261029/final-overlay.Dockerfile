FROM deepquest-api:optimized-local-20261026-default-workbench

USER root
COPY --chown=1000:1000 backend/package /app/package
COPY --chown=1000:1000 backend/server /app/server
COPY --chown=1000:1000 backend/wechat_mp /app/wechat_mp
USER 1000:1000
