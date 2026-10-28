"""轻量检查 Worker 的 Redis 健康租约，避免每次探测导入 Agent 后端。"""

import os
from redis import Redis
from platform_core.services.run_scheduling import agent_health_key, worker_kind


def main() -> None:
    """健康事实需存在且 TTL 合法；连接与读取失败返回非零。"""
    interval = float(os.getenv("WORKER_HEALTH_INTERVAL_SECONDS", "5"))
    with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2) as client:
        key = agent_health_key(worker_kind())
        value, ttl = client.get(key), client.pttl(key)
        if not value or not 0 < ttl <= (interval + 1) * 1000:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
