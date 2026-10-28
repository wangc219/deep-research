"""云机重启时等待向量服务就绪，再启动 API 或知识任务 Worker。"""

import asyncio
import os
import time

import httpx


async def wait_for_milvus(url: str, *, timeout: float = 120, interval: float = 2) -> None:
    """有界等待健康检查；超时失败退出，业务进程仍执行自己的启动校验。"""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        while True:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Milvus dependency did not become healthy before startup timeout")
            await asyncio.sleep(min(interval, remaining))


if __name__ == "__main__":
    print("Waiting for knowledge backend readiness", flush=True)
    asyncio.run(wait_for_milvus(os.getenv("MILVUS_HEALTH_URL", "http://milvus:9091/healthz")))
    print("Knowledge backend ready", flush=True)
