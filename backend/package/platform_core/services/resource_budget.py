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
        "memory_pressure": critical or available_mib < 4096,
    }


def read_budget() -> dict | None:
    """失联或损坏的预算按保守档处理，不把旧空闲状态长期当事实。"""
    if not governor_enabled():
        return None
    try:
        value = json.loads(budget_path().read_text())
        valid = isinstance(value, dict) and all(
            type(value.get(key)) is int and 0 <= value[key] <= limit
            for key, limit in [("asr_threads", os.cpu_count() or 1), ("research_slots", 8), ("bulk_slots", 1000)]
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
    critical = available < 2560
    return {
        "asr_threads": 1 if critical else min(2, os.cpu_count() or 1),
        "research_slots": 0 if critical else 2,
        "bulk_slots": 0 if critical else 4,
        "memory_pressure": available < 4096,
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
    from platform_core.services.task_queue_service import publish_pending_tasks
    from platform_core.utils.logging_config import logger

    path = budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = sample_host()
    last_threads, safe_samples, previous_slots = min(2, os.cpu_count() or 1), 0, (2, 4)
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
                    text("SELECT count(*) FROM agent_runs WHERE status IN ('running','cancel_requested')")
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
            value = {
                **budget,
                "observed_at": time.time(),
                "available_mib": round(current["available_mib"], 1),
                "cpu_busy_percent": round(busy * 100, 1),
                "cpu_other_percent": round(other_cpu * 100, 1),
                "interactive_running": interactive,
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
            slots = (budget["research_slots"], budget["bulk_slots"])
            if any(current > previous for current, previous in zip(slots, previous_slots)):
                await publish_pending_tasks()
            previous_slots = slots
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resource governor sample failed; stale budgets use conservative limits")
