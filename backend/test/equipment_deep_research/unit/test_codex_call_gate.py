import asyncio
import subprocess
import threading
import time

import pytest

from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.codex import CodexCliProvider
from equipment_deep_research.providers.codex_call_gate import CodexCallGate


@pytest.mark.anyio
async def test_codex_gate_is_fair_and_reports_queue_wait():
    gate = CodexCallGate(key="test", maximum=1, minimum=1)
    first = await gate.acquire(priority="normal")
    order: list[str] = []

    async def queued(name: str, priority: str):
        lease = await gate.acquire(priority=priority)
        order.append(name)
        await lease.release(success=True, elapsed_seconds=0.01)
        return lease

    normal = asyncio.create_task(queued("normal", "normal"))
    critical = asyncio.create_task(queued("critical", "critical"))
    await asyncio.sleep(0)
    await first.release(success=True, elapsed_seconds=0.01)
    normal_lease, critical_lease = await asyncio.gather(normal, critical)

    assert order == ["critical", "normal"]
    assert critical_lease.queue_wait_seconds >= 0
    assert normal_lease.queue_wait_seconds >= 0
    assert gate.snapshot()["active"] == 0


@pytest.mark.anyio
async def test_codex_gate_round_robins_same_priority_runs():
    gate = CodexCallGate(key="run-fairness", maximum=1, minimum=1)
    first = await gate.acquire(priority="normal", fairness_key="run-a")
    order: list[str] = []

    async def queued(name: str, run_id: str):
        lease = await gate.acquire(priority="normal", fairness_key=run_id)
        order.append(name)
        await lease.release(success=True, elapsed_seconds=0.01)

    run_a_first = asyncio.create_task(queued("a-1", "run-a"))
    run_a_second = asyncio.create_task(queued("a-2", "run-a"))
    run_b_first = asyncio.create_task(queued("b-1", "run-b"))
    await asyncio.sleep(0)
    await first.release(success=True, elapsed_seconds=0.01)
    await asyncio.gather(run_a_first, run_a_second, run_b_first)

    assert order == ["b-1", "a-1", "a-2"]


@pytest.mark.anyio
async def test_codex_gate_cancellation_removes_waiter_and_capacity_backs_off():
    gate = CodexCallGate(key="test", maximum=2, minimum=1)
    first = await gate.acquire()
    second = await gate.acquire()
    waiting = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert gate.snapshot()["queue_depth"] == 0

    await first.release(
        success=False,
        elapsed_seconds=0.1,
        capacity_failure=True,
    )
    await second.release(success=True, elapsed_seconds=0.1)
    assert gate.snapshot()["limit"] == 1
    assert gate.snapshot()["queue_depth"] == 0


@pytest.mark.anyio
async def test_codex_provider_instances_share_model_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MIN_CONCURRENCY", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_GATE_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_GATE_BACKOFF_JITTER_SECONDS", "0")
    stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}'
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_execute(command, prompt):
        nonlocal active, peak
        del prompt
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    first = CodexCliProvider(
        workspace_path=tmp_path,
        model="shared-model",
        include_default_skills=False,
    )
    second = CodexCliProvider(
        workspace_path=tmp_path,
        model="shared-model",
        include_default_skills=False,
    )
    monkeypatch.setattr(first, "_execute", fake_execute)
    monkeypatch.setattr(second, "_execute", fake_execute)

    async def collect(provider):
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "gate")],
                [],
                {},
            )
        ]

    results = await asyncio.gather(collect(first), collect(second))
    assert peak == 1
    metadata = [result[-1].final_turn.metadata for result in results]
    assert all(item["codex_gate_limit"] == 1 for item in metadata)
    assert sum(float(item["codex_gate_queue_wait_total_seconds"]) > 0 for item in metadata) == 1


@pytest.mark.anyio
async def test_codex_gate_file_slots_coordinate_independent_api_workers(tmp_path):
    first_gate = CodexCallGate(
        key="cross-worker",
        maximum=1,
        minimum=1,
        lock_root=tmp_path,
    )
    second_gate = CodexCallGate(
        key="cross-worker",
        maximum=1,
        minimum=1,
        lock_root=tmp_path,
    )
    first = await first_gate.acquire()
    waiting = asyncio.create_task(second_gate.acquire())
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await first.release(success=True, elapsed_seconds=0.01)
    second = await asyncio.wait_for(waiting, timeout=1)
    await second.release(success=True, elapsed_seconds=0.01)
