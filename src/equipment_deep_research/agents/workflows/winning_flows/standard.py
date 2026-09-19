"""Ordinary S-step scheduling; a dynamic scheduler is not a swarm execution mode."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any


async def run_standard_steps(
    selected_steps: Sequence[int],
    *,
    middle_cycle: int,
    middle_feedback: list[str] | None,
    accumulated: dict[str, Any],
    commit_step: Callable[..., Any],
    run_step: Callable[..., Any],
    step_dependency_map: Mapping[int, Sequence[int]],
    plan_step_waves: Callable[[set[int]], list[tuple[int, ...]]],
) -> None:
    """Run dependency-ready S steps, or fixed waves when the pipeline is disabled."""
    selected = set(selected_steps)
    use_pipeline = (
        os.environ.get(
            "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER",
            "1",
        ).strip()
        != "0"
    )
    if not use_pipeline:
        # 传统固定波次调度（向后兼容，设 =0 可回退）。
        for wave in plan_step_waves(selected):
            prior_step_outputs = dict(accumulated)
            outcomes = await asyncio.gather(
                *(
                    run_step(
                        index,
                        middle_cycle=middle_cycle,
                        prior_step_outputs=prior_step_outputs,
                        middle_feedback=middle_feedback,
                    )
                    for index in wave
                )
            )
            for outcome in sorted(
                outcomes,
                key=lambda item: int(item["run"]["step"]),
            ):
                commit_step(outcome)
        return

    # 动态流水线调度：步骤依赖满足后立即启动，无需等待同波次
    # 其他步骤。skip/复用步骤视为依赖已满足；提交后立即唤醒调度器
    # 检查新就绪步骤，使 S4 完成即可启动 S6（若 S5 也已完成）。
    satisfied = {index for index in range(1, 7) if index not in selected}
    pending = set(selected)
    running: dict[int, asyncio.Task] = {}
    failures: list[BaseException] = []
    wake = asyncio.Event()

    async def run_and_commit(index: int) -> None:
        try:
            outcome = await run_step(
                index,
                middle_cycle=middle_cycle,
                prior_step_outputs=dict(accumulated),
                middle_feedback=middle_feedback,
            )
            commit_step(outcome)
            satisfied.add(index)
        except BaseException as exc:
            failures.append(exc)
        finally:
            running.pop(index, None)
            wake.set()

    while pending or running:
        if failures:
            pending_tasks = list(running.values())
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                await asyncio.gather(
                    *pending_tasks,
                    return_exceptions=True,
                )
            raise failures[0]
        ready = sorted(
            index
            for index in pending
            if all(dep in satisfied for dep in step_dependency_map[index])
        )
        for index in ready:
            pending.discard(index)
            running[index] = asyncio.create_task(run_and_commit(index))
        if not running:
            # 依赖无法满足（异常情况）：退化为串行启动剩余步骤。
            if pending:
                fallback = min(pending)
                pending.discard(fallback)
                running[fallback] = asyncio.create_task(run_and_commit(fallback))
            else:
                break
        wake.clear()
        await wake.wait()
    if failures:
        raise failures[0]
