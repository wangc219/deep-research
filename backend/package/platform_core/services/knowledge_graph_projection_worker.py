"""知识图谱 PostgreSQL outbox 的独立后台投影消费者。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.utils.logging_config import logger

DEFAULT_PROJECTION_BATCH_SIZE = 20
DEFAULT_PROJECTION_POLL_SECONDS = 2.0


class KnowledgeGraphProjectionWorker:
    """只消费持久化投影事件，不参与抽取或权威知识写入。"""

    def __init__(
        self,
        graph_service: MilvusGraphService | None = None,
        *,
        batch_size: int | None = None,
        poll_seconds: float | None = None,
    ):
        self.graph_service = graph_service or MilvusGraphService()
        self.batch_size = batch_size or _positive_int_env(
            "KNOWLEDGE_GRAPH_PROJECTION_BATCH_SIZE",
            DEFAULT_PROJECTION_BATCH_SIZE,
        )
        self.poll_seconds = poll_seconds or _positive_float_env(
            "KNOWLEDGE_GRAPH_PROJECTION_POLL_SECONDS",
            DEFAULT_PROJECTION_POLL_SECONDS,
        )

    async def run_once(self) -> dict[str, int]:
        """消费一个有界批次，便于测试、运维手动触发和循环复用。"""
        return await self.graph_service.replay_projection_outbox(None, limit=self.batch_size)

    async def run_forever(self) -> None:
        """持续投影；空队列时等待，满批时立即继续排空积压。"""
        while True:
            try:
                result = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("知识图谱 outbox 后台消费失败", exc_info=True)
                await asyncio.sleep(self.poll_seconds)
                continue

            if result["claimed"] < self.batch_size:
                await asyncio.sleep(self.poll_seconds)


def start_knowledge_graph_projection_worker(ctx: dict[str, Any]) -> None:
    """把消费者挂到 worker 生命周期，由统一 shutdown 负责取消。"""
    if "knowledge_graph_projection_task" in ctx:
        return
    worker = KnowledgeGraphProjectionWorker()
    ctx["knowledge_graph_projection_worker"] = worker
    ctx["knowledge_graph_projection_task"] = asyncio.create_task(worker.run_forever())


async def stop_knowledge_graph_projection_worker(ctx: dict[str, Any]) -> None:
    """停止后台消费者并等待取消完成。"""
    task = ctx.pop("knowledge_graph_projection_task", None)
    ctx.pop("knowledge_graph_projection_worker", None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须是正数")
    return value
