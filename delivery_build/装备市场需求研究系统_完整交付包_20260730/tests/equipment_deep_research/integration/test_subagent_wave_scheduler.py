from __future__ import annotations

import asyncio

from equipment_deep_research.domain.messages import AgentExecutionResult, TaskEnvelope
from equipment_deep_research.harness.scheduler import SubagentWaveScheduler


def _task(index: int) -> TaskEnvelope:
    return TaskEnvelope(f"t-{index}", "run", 1, None, f"agent-{index}", [], "research", [], [], [], [], [], [], {}, "packet", "reduce")


def test_wave_respects_concurrency_and_returns_other_results_after_failure() -> None:
    active = 0
    max_active = 0

    async def execute(task: TaskEnvelope) -> AgentExecutionResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(.01)
        active -= 1
        if task.task_id == "t-2":
            raise RuntimeError("planned")
        return AgentExecutionResult(f"exec-{task.task_id}", task.task_id, task.target_agent_id, "completed")

    result = asyncio.run(SubagentWaveScheduler(execute, max_concurrency=2).run_wave([_task(index) for index in range(4)]))
    assert max_active == 2
    assert [item.status for item in result] == ["completed", "completed", "failed", "completed"]
