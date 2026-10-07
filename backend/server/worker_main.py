"""ARQ worker entrypoint."""

import asyncio
import logging.config
import os
import sys

# 必须放在最顶层！
if sys.platform == "win32":
    # 把当前文件 (main.py) 的上一级的上一级（项目根目录）加入 sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from platform_core.services.run_worker import WorkerSettings

__all__ = ["WorkerSettings"]


def main() -> None:
    """沿用 ARQ 默认日志与运行生命周期，装配平台的领取适配。"""
    from arq.logs import default_log_config
    from platform_core.services.arq_worker import run_worker

    logging.config.dictConfig(default_log_config(False))
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
