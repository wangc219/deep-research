"""Query 生成专用 Durable Task worker。"""

from __future__ import annotations

import logging.config
import uuid

from arq.worker import func

from platform_core.config import get_int_env
from platform_core.services.arq_worker import run_worker
from platform_core.services.run_queue_service import close_queue_clients
from platform_core.services.task_queue_service import (
    EQUIPMENT_QUERY_TASK_QUEUE,
    EQUIPMENT_QUERY_TASK_TYPE,
    durable_task_worker_health_key,
)
from platform_core.services.task_service import TASKER_DEFAULT_TIMEOUT_SECONDS, process_task
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.redis import get_arq_redis_settings
from platform_core.utils.auth_utils import AuthUtils

WORKER_ID = f"equipment-query-worker-{uuid.uuid4().hex}"


async def _startup(ctx: dict) -> None:
    """只初始化 Query 生成所需的安全、数据库与检索配置。"""

    if not isinstance(ctx, dict):
        raise TypeError("ARQ worker context 必须是字典")
    AuthUtils.require_security_secrets()
    ctx["worker_id"] = WORKER_ID
    ctx["durable_task_type_filter"] = EQUIPMENT_QUERY_TASK_TYPE
    pg_manager.initialize()
    await pg_manager.require_current_schema()

    from platform_core.config.options import (
        ensure_options_in_db,
        invalidate_option_cache,
        publish_web_search_runtime_options,
        system_options,
        web_search_opts,
    )

    async with pg_manager.get_async_session_context() as session:
        synced_options = await ensure_options_in_db(session)
        web_search_stored = next(
            (dict(record.value or {}) for record in (synced_options or []) if record.key == web_search_opts.key),
            {},
        )
        await session.commit()
    await invalidate_option_cache(system_options.key)
    await publish_web_search_runtime_options(web_search_stored)


async def _shutdown(_ctx: dict) -> None:
    """释放专用 worker 的队列与数据库连接。"""

    await close_queue_clients()
    await pg_manager.close()


class WorkerSettings:
    """只消费 Query 生成专用队列，并保留任务类型二次校验。"""

    functions = [func(process_task, timeout=TASKER_DEFAULT_TIMEOUT_SECONDS + 30)]
    queue_name = EQUIPMENT_QUERY_TASK_QUEUE
    max_jobs = get_int_env("ARQ_MAX_JOBS", 4)
    poll_delay = 0.05
    max_tries = 2
    retry_jobs = True
    job_timeout = int(TASKER_DEFAULT_TIMEOUT_SECONDS + 30)
    keep_result = 60
    health_check_interval = 5
    health_check_key = durable_task_worker_health_key()
    on_startup = _startup
    on_shutdown = _shutdown
    redis_settings = get_arq_redis_settings()


def main() -> None:
    """启动 Query 生成专用 ARQ worker。"""

    from arq.logs import default_log_config

    logging.config.dictConfig(default_log_config(False))
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
