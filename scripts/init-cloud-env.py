#!/usr/bin/env python3
"""为独立云部署生成一次性生产配置；已有配置绝不覆盖。"""

import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parent.parent
    settings = {
        "COMPOSE_PROJECT_NAME": "deepquest",
        "DEEP_RESEARCH_ENV": "production",
        "DEEP_RESEARCH_ENV_FILE": ".env.prod",
        "DEEP_RESEARCH_INSTANCE_ID": secrets.token_hex(16),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "API_KEY_DERIVATION_SECRET": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "MINIO_ACCESS_KEY": "dq" + secrets.token_hex(10),
        "MINIO_SECRET_KEY": secrets.token_hex(32),
        "NEO4J_PASSWORD": secrets.token_hex(24),
        "SANDBOX_PROVISIONER_TOKEN": secrets.token_hex(32),
        "SEARXNG_SECRET": secrets.token_hex(32),
        "DEEP_RESEARCH_CORS_ORIGINS": "https://www.deepquest.space",
        "EQUIPMENT_ALLOW_SELF_REGISTRATION": "false",
        "ARQ_MAX_JOBS": "4",
        "API_POSTGRES_POOL_SIZE": "8",
        "API_POSTGRES_MAX_OVERFLOW": "4",
        "API_LANGGRAPH_POSTGRES_POOL_SIZE": "4",
        "WORKER_POSTGRES_POOL_SIZE": "8",
        "WORKER_POSTGRES_MAX_OVERFLOW": "4",
        "WORKER_LANGGRAPH_POSTGRES_POOL_SIZE": "8",
        "API_REDIS_MAX_CONNECTIONS": "32",
        "WORKER_REDIS_MAX_CONNECTIONS": "32",
        "POSTGRES_MAX_CONNECTIONS": "100",
        "SANDBOX_DELETE_CONCURRENCY": "4",
        "SANDBOX_IMAGE": "deepquest-sandbox-runtime:1.11.0-artifacts",
        "SANDBOX_RUNTIME_PROFILE": "core",
        "SANDBOX_IDLE_TIMEOUT_SECONDS": "120",
        "WEB_SEARCH_PROVIDER": "open-websearch",
        "OPEN_WEBSEARCH_URL": "http://open-websearch:3210",
        "OPEN_WEBSEARCH_ENGINES": "bing,duckduckgo",
        "SEARXNG_URL": "http://searxng:8080",
    }
    path = root / ".env.prod"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in settings.items()))
    (root / "outputs" / "runs").mkdir(parents=True, exist_ok=True)
    print(f"生产配置已创建：{path}（权限 0600）")


if __name__ == "__main__":
    main()
