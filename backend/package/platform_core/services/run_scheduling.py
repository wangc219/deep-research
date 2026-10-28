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


def user_run_limit(lane: str) -> int | None:
    """读取每用户执行配额；auto/0 表示交给对应 Worker 的实时空闲槽背压。"""
    env_name = f"AGENT_USER_{lane.upper()}_MAX_RUNNING"
    raw_value = os.getenv(env_name, {"chat": "2", "deep": "1", "subagent": "auto"}[lane]).strip().casefold()
    if raw_value in {"auto", "none", "unlimited", "0"}:
        return None
    return get_int_env(env_name, {"chat": 2, "deep": 1, "subagent": 2}[lane])


def lane_run_limit(lane: str) -> int | None:
    """返回实时执行池接纳量；None 表示只由 Worker 自身背压。

    子智能体使用资源治理器发布的共享快照，因此所有用户、所有容器看到同一份
    动态容量。它不是任务书或 Agent 数量规则；队列长度仍不受此值限制。
    """

    if lane != "subagent":
        return None
    from platform_core.services.resource_budget import read_budget

    budget = read_budget()
    if budget is None:
        return None
    value = budget.get("subagent_slots")
    if type(value) is not int or value < 0:
        return None
    return value


def tool_parallelism_limit(configured_fallback: int) -> int:
    """为一次模型工具批次返回实时并行度；未启用时保持原配置语义。"""

    adaptive = os.getenv("AGENT_ADAPTIVE_TOOL_PARALLELISM", "false").lower() in {"true", "1", "yes"}
    if not adaptive:
        return max(1, configured_fallback)
    capacity = lane_run_limit("subagent")
    return max(1, capacity) if capacity is not None else max(1, configured_fallback)


def agent_health_key(kind: str) -> str:
    """每个执行池单独续租健康事实，防止其他池掩盖故障。"""
    base = "deep-research:worker:health:agent-run-v1"
    return f"{base}:{kind}" if kind in AGENT_QUEUES else base
