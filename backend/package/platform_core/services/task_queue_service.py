from __future__ import annotations

import os
from functools import partial

from platform_core.repositories.task_repository import TaskRepository
from platform_core.services.run_queue_service import get_arq_pool
from platform_core.services.task_registry import get_failure_task_definition, get_task_definition
from platform_core.utils.logging_config import logger

TASK_LEASE_SECONDS = 30.0
TASK_HEARTBEAT_SECONDS = 10.0
TASK_RECONCILIATION_SECONDS = 30.0
TASK_RECONCILIATION_HEALTH_KEY = "deep-research:worker:health:durable-task-reconciliation-v1"
TASK_RECONCILIATION_HEALTH_TTL_SECONDS = int(TASK_RECONCILIATION_SECONDS * 2 + 5)
DEFAULT_DURABLE_TASK_QUEUE = "arq:queue"
EQUIPMENT_QUERY_TASK_TYPE = "equipment_query_generation"
EQUIPMENT_QUERY_TASK_QUEUE = "deep-research:queue:durable:equipment-query"
EQUIPMENT_QUERY_WORKER_KIND = "equipment-query"


def task_queue_name(task_type: str) -> str:
    """让 Query 生成只进入版本一致的专用执行队列。"""

    if task_type == EQUIPMENT_QUERY_TASK_TYPE:
        return EQUIPMENT_QUERY_TASK_QUEUE
    return DEFAULT_DURABLE_TASK_QUEUE


def durable_task_worker_kind() -> str:
    """读取 Durable Task 执行角色，并拒绝静默回落到错误队列。"""

    kind = os.getenv("DURABLE_TASK_WORKER_KIND", "general").strip().casefold()
    if kind not in {"general", EQUIPMENT_QUERY_WORKER_KIND}:
        raise ValueError("DURABLE_TASK_WORKER_KIND 配置无效")
    return kind


def durable_task_worker_queue() -> str:
    """返回当前 Durable Task worker 唯一允许消费的队列。"""

    if durable_task_worker_kind() == EQUIPMENT_QUERY_WORKER_KIND:
        return EQUIPMENT_QUERY_TASK_QUEUE
    return DEFAULT_DURABLE_TASK_QUEUE


def durable_task_worker_type() -> str | None:
    """返回专用 worker 的任务类型约束；通用 worker 不额外限制。"""

    if durable_task_worker_kind() == EQUIPMENT_QUERY_WORKER_KIND:
        return EQUIPMENT_QUERY_TASK_TYPE
    return None


def durable_task_worker_health_key() -> str:
    """为专用 Query worker 提供独立健康租约，避免被通用 worker 掩盖。"""

    kind = durable_task_worker_kind()
    if kind == EQUIPMENT_QUERY_WORKER_KIND:
        return "deep-research:worker:health:durable-task-equipment-query-v1"
    return ""


async def publish_task(task_id: str, *, task_type: str | None = None) -> None:
    """把已提交的 PG Task 发布为 ARQ 唤醒消息；重复消息由数据库 claim 拒绝。"""
    if task_type is None:
        record = await TaskRepository().get_by_id(task_id)
        if record is None:
            raise ValueError(f"Durable Task 不存在: {task_id}")
        task_type = str(record.type or "")
    pool = await get_arq_pool()
    queue_name = task_queue_name(task_type)
    if queue_name == DEFAULT_DURABLE_TASK_QUEUE:
        await pool.enqueue_job("process_task", task_id)
        return
    await pool.enqueue_job("process_task", task_id, _queue_name=queue_name)


async def finalize_task_failure(session, record, error: str) -> None:
    """在 Task 失败事务内执行已注册的领域收敛。"""
    handler_version = 1 if record.handler_version is None else int(record.handler_version)
    try:
        definition = get_failure_task_definition(record.type, handler_version)
    except ValueError:
        logger.error(
            "Cannot finalize unknown durable task: task_id=%s, type=%s, handler_version=%s",
            record.id,
            record.type,
            handler_version,
        )
        return
    handler = definition.load_failure_handler()
    if handler is not None:
        await handler(session, record, error)


async def reconcile_and_publish_tasks() -> list[tuple[str, str, int]]:
    """收敛失联 owner，并发布所有当前 pending Task。"""
    repository = TaskRepository()
    reconciled = await repository.reconcile_expired_leases(
        before_fail=finalize_task_failure,
    )
    await publish_pending_tasks()
    await repository.prune_terminal()
    return reconciled


async def publish_pending_tasks(*, limit: int = 200) -> list[str]:
    """重发 PG 中待执行的任务；重复 ARQ 消息由 task_id/attempt 去重。"""
    published: list[str] = []
    repository = TaskRepository()
    for record in await repository.list_pending(limit=limit):
        try:
            get_task_definition(record.type)
        except ValueError as exc:
            logger.error("Cannot publish unknown durable task: task_id=%s, type=%s", record.id, record.type)
            await repository.fail_pending(record.id, error=str(exc))
            continue
        handler_version = 1 if record.handler_version is None else int(record.handler_version)
        if record.cancel_requested:
            try:
                failure_definition = get_failure_task_definition(record.type, handler_version)
            except ValueError:
                failure_definition = None
            failure_handler = failure_definition.load_failure_handler() if failure_definition is not None else None
            before_cancel = partial(failure_handler, error="任务已取消") if failure_handler is not None else None
            await repository.request_cancel(record.id, before_cancel=before_cancel)
            continue
        try:
            get_task_definition(record.type, handler_version)
        except ValueError as exc:
            error = str(exc)
            logger.error("Cannot rebuild durable task: task_id=%s, type=%s", record.id, record.type)
            try:
                failure_definition = get_failure_task_definition(record.type, handler_version)
            except ValueError:
                failure_definition = None
            failure_handler = failure_definition.load_failure_handler() if failure_definition is not None else None
            before_fail = partial(failure_handler, error=error) if failure_handler is not None else None
            await repository.fail_pending(record.id, error=error, before_fail=before_fail)
            continue
        await publish_task(record.id, task_type=record.type)
        published.append(record.id)
    return published
