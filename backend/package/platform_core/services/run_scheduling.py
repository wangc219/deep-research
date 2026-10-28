"""普通聊天、深研与子任务的独立执行队列及用户配额。"""

from __future__ import annotations

import os
from platform_core.config import get_int_env

AGENT_QUEUES = {
    "chat": "deep-research:queue:chat",
    "deep": "deep-research:queue:deep",
    "subagent": "deep-research:queue:subagent",
}
DEEP_AGENT_SLUGS = {"deep-research", "weapon-equipment-scheme", "equipment-capability-portrait"}


def split_agent_queues() -> bool:
    """显式启用分池；未配置的现有部署继续使用统一队列。"""
    return os.getenv("AGENT_RUN_SPLIT_QUEUES", "false").lower() in {"true", "1", "yes"}


def worker_kind() -> str:
    """无效执行角色在启动时失败，防止静默消费错误队列。"""
    kind = os.getenv("AGENT_WORKER_KIND", "unified")
    if kind not in {"unified", "background", *AGENT_QUEUES}:
        raise ValueError("AGENT_WORKER_KIND 配置无效")
    return kind


def run_lane(run) -> str:
    """按服务端持久来源划分队列，子任务独立运行以免父任务占满执行槽。"""
    if run.run_type == "subagent":
        return "subagent"
    if run.source == "equipment_deep_research" or run.agent_slug in DEEP_AGENT_SLUGS:
        return "deep"
    return "chat"


def user_run_limit(lane: str) -> int:
    """配额按用户与业务池分别计算，避免同一用户独占所有执行槽。"""
    return get_int_env(f"AGENT_USER_{lane.upper()}_MAX_RUNNING", {"chat": 2, "deep": 1, "subagent": 2}[lane])


def agent_health_key(kind: str) -> str:
    """每个执行池单独续租健康事实，防止其他池掩盖故障。"""
    base = "deep-research:worker:health:agent-run-v1"
    return f"{base}:{kind}" if kind in AGENT_QUEUES else base
