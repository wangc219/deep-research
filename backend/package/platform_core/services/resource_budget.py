"""按真实主机余量调节新任务接纳与 ASR 线程，不中断已有任务。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import time
from pathlib import Path

_ASR_PROCESSES: set[int] = set()


def governor_enabled() -> bool:
    """仅在显式启用的云端环境应用动态预算。"""
    return os.getenv("RESOURCE_GOVERNOR_ENABLED", "false").lower() in {"true", "1", "yes"}


def budget_path() -> Path:
    """多个业务容器通过现有持久卷共享不含用户数据的预算。"""
    return Path(os.getenv("RESOURCE_BUDGET_PATH", "/app/outputs/runtime/resource-budget.json"))


def _adaptive_subagent_slots(
    *,
    cores: int,
    available_mib: float,
    other_cpu: float,
    interactive: int,
) -> int:
    """按实时物理余量计算新子智能体接纳量，不设置业务数量上限。

    子智能体大部分时间等待模型和检索 I/O，因此允许每核多个在途任务；内存与
    CPU 压力会立即降低新任务接纳量，但不会取消已经运行的任务。服务器扩容后
    结果随核心和内存线性增长，不需要再修改固定的 Agent 数量配置。
    """

    if available_mib < 2560:
        return 0
    memory_reserve_mib = 3072 if interactive else 2048
    memory_slots = max(0, math.floor((available_mib - memory_reserve_mib) / 384))
    cpu_headroom = max(0.25, 1.0 - max(0.0, min(1.0, other_cpu)))
    io_slots_per_core = 4 if interactive else 5
    cpu_slots = max(1, math.floor(max(1, cores) * io_slots_per_core * cpu_headroom))
    return min(memory_slots, cpu_slots)


def adaptive_worker_max_jobs(*, cores: int | None = None, total_mib: float | None = None) -> int:
    """返回 ARQ 的资源派生接纳窗口；它只是轮询窗口，不是 Agent 业务配额。"""

    resolved_cores = max(1, int(cores or os.cpu_count() or 1))
    if total_mib is None:
        try:
            total_mib = next(
                int(line.split()[1]) / 1024
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal:")
            )
        except (OSError, ValueError, StopIteration):
            total_mib = resolved_cores * 2048
    # 窗口必须高于正常动态接纳量，避免 ARQ 自身成为固定瓶颈；最终是否开跑仍由
    # resource-budget 的实时快照和 PostgreSQL 原子领取决定。
    return max(resolved_cores * 8, math.floor(float(total_mib) / 512), 4)


def plan_budget(*, cores: int, available_mib: float, other_cpu: float, interactive: int, research: int) -> dict:
    """空闲时借用全部核心，交互或内存压力出现时减少新增重任务。"""
    reserve = 1.0 if interactive else 0.25 if research else 0.0
    threads = (
        cores
        if other_cpu < 0.15 and not interactive and not research
        else math.floor(cores * (1 - other_cpu) - reserve)
    )
    critical = available_mib < 2560
    pressure = available_mib < 4096 or (other_cpu > 0.8 and interactive > 0)
    return {
        "asr_threads": max(1, min(cores, 1 if critical else threads)),
        "research_slots": 0 if critical else 1 if available_mib < 4096 else 2 if pressure else 8,
        "bulk_slots": 0 if critical else 4 if pressure else 1000,
        "subagent_slots": _adaptive_subagent_slots(
            cores=cores,
            available_mib=available_mib,
            other_cpu=other_cpu,
            interactive=interactive,
        ),
        "memory_pressure": critical or available_mib < 4096,
    }


def read_budget() -> dict | None:
    """失联或损坏的预算按保守档处理，不把旧空闲状态长期当事实。"""
    if not governor_enabled():
        return None
    try:
        value = json.loads(budget_path().read_text())
        valid = (
            isinstance(value, dict)
            and all(
                type(value.get(key)) is int and 0 <= value[key] <= limit
                for key, limit in [
                    ("asr_threads", os.cpu_count() or 1),
                    ("research_slots", 8),
                    ("bulk_slots", 1000),
                ]
            )
            and type(value.get("subagent_slots")) is int
            and value["subagent_slots"] >= 0
        )
        if (
            valid
            and type(value.get("memory_pressure")) is bool
            and value["asr_threads"] >= 1
            and 0 <= time.time() - float(value["observed_at"]) <= 12
        ):
            return value
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        available = next(
            int(line.split()[1]) / 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
    except (OSError, ValueError, StopIteration):
        available = 4096
    return {
        **plan_budget(
            cores=os.cpu_count() or 1,
            available_mib=available,
            other_cpu=0.75,
            interactive=1,
            research=0,
        ),
        "stale": True,
    }


def asr_threads() -> int:
    """模型初始化和每个音频块使用相同的线程预算。"""
    budget = read_budget()
    if budget is not None:
        return int(budget["asr_threads"])
    return max(1, int(os.getenv("OMP_NUM_THREADS", "2")))


def refresh_asr_threads() -> None:
    """独立识别进程在音频块边界调整 Torch 池，不改变模型或音频内容。"""
    if not governor_enabled():
        return
    threads = asr_threads()
    import torch

    if threads != torch.get_num_threads():
        torch.set_num_threads(threads)


def register_asr_process(pid: int) -> None:
    """记录本 Worker 的识别子进程，以免将其有效计算误当竞争负载。"""
    _ASR_PROCESSES.add(pid)


def unregister_asr_process(pid: int) -> None:
    """回收完成或取消的识别进程采样身份。"""
    _ASR_PROCESSES.discard(pid)


def sample_host() -> dict:
    """读取内核主机指标与本 Worker 的识别 CPU 计时。"""
    cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    memory = dict(
        (line.split(":")[0], int(line.split()[1]))
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith(("MemAvailable:", "MemTotal:"))
    )
    processes = {}
    for pid in tuple(_ASR_PROCESSES):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            processes[pid] = int(fields[11]) + int(fields[12])
        except (OSError, ValueError, IndexError):
            continue
    return {
        "total": sum(cpu),
        "idle": cpu[3] + cpu[4],
        "available_mib": memory["MemAvailable"] / 1024,
        "asr_cpu": processes,
    }


async def resource_governor() -> None:
    """由后台 Worker 单独采样；加速需连续安全样本，降档立即作用于新边界。"""
    from sqlalchemy import text
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.services.agent_request_queue_service import recover_pending_dispatches
    from platform_core.services.task_queue_service import publish_pending_tasks
    from platform_core.utils.logging_config import logger

    path = budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = sample_host()
    last_threads = min(2, os.cpu_count() or 1)
    last_subagent_slots = 1
    safe_samples = subagent_safe_samples = 0
    previous_slots = (2, 4, last_subagent_slots)
    while True:
        await asyncio.sleep(2)
        try:
            current = sample_host()
            total = max(1, current["total"] - previous["total"])
            busy = 1 - (current["idle"] - previous["idle"]) / total
            asr_delta = sum(
                max(0, ticks - previous["asr_cpu"].get(pid, ticks)) for pid, ticks in current["asr_cpu"].items()
            )
            other_cpu = max(0, min(1, busy - asr_delta / total))
            previous = current
            async with pg_manager.get_async_session_context() as db:
                interactive = await db.scalar(
                    text(
                        "SELECT count(*) FROM agent_runs "
                        "WHERE status IN ('running','cancel_requested') AND run_type <> 'subagent'"
                    )
                )
                subagents = await db.scalar(
                    text(
                        "SELECT count(*) FROM agent_runs "
                        "WHERE status IN ('running','cancel_requested') AND run_type = 'subagent'"
                    )
                )
                research = await db.scalar(
                    text("SELECT count(*) FROM tasks WHERE type='equipment_research' AND status='running'")
                )
            budget = plan_budget(
                cores=os.cpu_count() or 1,
                available_mib=current["available_mib"],
                other_cpu=other_cpu,
                interactive=interactive,
                research=research,
            )
            if budget["asr_threads"] > last_threads:
                safe_samples += 1
                if safe_samples < 3:
                    budget["asr_threads"] = last_threads
            else:
                safe_samples = 0
            last_threads = budget["asr_threads"]
            if budget["subagent_slots"] > last_subagent_slots:
                subagent_safe_samples += 1
                if subagent_safe_samples < 3:
                    budget["subagent_slots"] = last_subagent_slots
            else:
                subagent_safe_samples = 0
            last_subagent_slots = budget["subagent_slots"]
            value = {
                **budget,
                "observed_at": time.time(),
                "available_mib": round(current["available_mib"], 1),
                "cpu_busy_percent": round(busy * 100, 1),
                "cpu_other_percent": round(other_cpu * 100, 1),
                "interactive_running": interactive,
                "subagent_running": subagents,
                "research_running": research,
                "asr_processes": len(current["asr_cpu"]),
            }
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=path.parent, prefix=".resource-budget-", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(value, stream)
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            slots = (budget["research_slots"], budget["bulk_slots"], budget["subagent_slots"])
            if any(current_slot > previous_slot for current_slot, previous_slot in zip(slots, previous_slots)):
                await publish_pending_tasks()
                await recover_pending_dispatches()
            previous_slots = slots
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resource governor sample failed; stale budgets use conservative limits")
