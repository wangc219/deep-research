from __future__ import annotations

import asyncio

from equipment_deep_research.agents.provider import ResponsesAgentProvider
from equipment_deep_research.providers.fake import ScriptedFakeProvider


def test_run_call_gates_are_isolated_and_inherit_codex_concurrency(monkeypatch) -> None:
    """Each run gets its own configured gate while retaining its per-run cap."""

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget({"codex_concurrency": 2})

    first = provider.call_gate_for_run("run-a")
    second = provider.call_gate_for_run("run-b")

    assert first is not second
    assert provider.call_gate_for_run("run-a") is first
    assert first.snapshot()["limit"] == 2
    assert second.snapshot()["limit"] == 2

    first_leases = [first.try_acquire(priority="critical") for _ in range(2)]
    second_leases = [second.try_acquire(priority="critical") for _ in range(2)]
    try:
        # A single run remains capped at codex_concurrency.
        assert all(first_leases)
        assert first.try_acquire(priority="critical") is None
        assert all(second_leases)
        assert second.try_acquire(priority="critical") is None
    finally:
        for lease in first_leases:
            if lease is not None:
                # The elapsed value is irrelevant to this isolation assertion;
                # use a successful zero-duration release to keep the gate tidy.
                first.release(0.0, success=True)
        for lease in second_leases:
            if lease is not None:
                second.release(0.0, success=True)


def test_run_core_text_routes_nested_run_id_to_internal_options(monkeypatch) -> None:
    """The run identity selects the gate without becoming model-visible input."""

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    captured_options: dict[str, object] = {}

    async def fake_collect_stream(
        selected_provider,
        messages,
        options,
        **kwargs,
    ):
        del selected_provider, messages, kwargs
        captured_options.update(options)
        return "ok", {}

    monkeypatch.setattr(provider, "_collect_stream", fake_collect_stream)

    payload = {"input": {"run_id": "run-nested", "mission_node": "S3"}}
    asyncio.run(
        provider._run_core_text(
            "winning_swarm_frontier_equipment_miner",
            "system",
            payload,
            128,
            phase="winning_swarm_dynamic_s3",
        )
    )

    assert captured_options["_run_id"] == "run-nested"
    assert payload == {"input": {"run_id": "run-nested", "mission_node": "S3"}}


def test_queued_calls_do_not_starve_model_completion_executor(monkeypatch) -> None:
    """一个 I/O 线程也能处理大量排队模型的计量，不能被槽位等待者耗尽。"""
    from concurrent.futures import ThreadPoolExecutor
    from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    class ObservedProvider(ScriptedFakeProvider):
        async def stream(self, messages, tools, options):
            await asyncio.sleep(0.02)
            await asyncio.to_thread(lambda: None)
            yield ProviderStreamEvent.final(ProviderFinalTurn(text="completed"))

    async def exercise():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        backend = ObservedProvider([])
        host = ResponsesAgentProvider(backend)
        host.configure_run_budget(
            {
                "codex_concurrency": 1,
                "wall_clock_deadlines_enabled": False,
                "maximum_model_calls": 100,
                "maximum_model_calls_with_residuals": 100,
            }
        )
        results = await asyncio.wait_for(
            asyncio.gather(*[host._collect_stream(backend, [], {"_run_id": "executor-regression"}) for _ in range(12)]),
            timeout=3,
        )
        assert all(text == "completed" for text, _ in results)
        gate = host.call_gate_for_run("executor-regression")
        assert gate.snapshot()["active"] == 0
        assert gate.snapshot()["priority_waiters"] == 0

    asyncio.run(exercise())


def test_cancelled_async_waiter_releases_priority_registration(monkeypatch) -> None:
    """取消尚未取得槽位的关键任务时，不得遗留优先级或活动租约。"""
    from equipment_deep_research.agents.performance import AdaptiveCallGate

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    async def exercise():
        gate = AdaptiveCallGate()
        gate.configure_concurrency(1)
        assert gate.try_acquire(priority="critical") is not None
        pending = asyncio.create_task(gate.acquire_async(priority="critical"))
        await asyncio.sleep(0.03)
        assert gate.snapshot()["priority_waiters"] == 1
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        assert gate.snapshot()["priority_waiters"] == 0
        assert gate.snapshot()["active"] == 1
        gate.release(0, success=True)
        assert gate.snapshot()["active"] == 0

    asyncio.run(exercise())


def test_async_gate_wakes_on_release_without_polling(monkeypatch):
    """槽位等待不使用轮询定时器，线程释放通过通知唤醒事件循环。"""
    from equipment_deep_research.agents.performance import AdaptiveCallGate

    async def forbidden_sleep(*args, **kwargs):
        raise AssertionError("gate must not poll")

    async def exercise():
        gate = AdaptiveCallGate()
        gate.configure_concurrency(1)
        assert gate.try_acquire(priority="critical")
        monkeypatch.setattr("equipment_deep_research.agents.performance.asyncio.sleep", forbidden_sleep)
        pending = asyncio.create_task(gate.acquire_async(priority="critical"))
        registered = asyncio.Event()
        asyncio.get_running_loop().call_soon(registered.set)
        await registered.wait()
        assert gate.snapshot()["async_waiters"] == 1
        gate.release(0, success=True)
        await asyncio.wait_for(pending, timeout=1)
        gate.release(0, success=True)
        assert gate.snapshot()["async_waiters"] == 0
        assert gate.snapshot()["active"] == 0

    asyncio.run(exercise())


def test_gate_notifications_cross_event_loops_and_threads(monkeypatch):
    """一个共享gate中的两个循环都能接到外部线程释放的通知。"""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from equipment_deep_research.agents.performance import AdaptiveCallGate

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")
    gate = AdaptiveCallGate()
    gate.configure_concurrency(1)
    assert gate.try_acquire(priority="critical")
    done = [Event(), Event()]

    async def enter(index):
        await asyncio.wait_for(gate.acquire_async(priority="critical"), timeout=2)
        gate.release(0, success=True)
        done[index].set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = [pool.submit(asyncio.run, enter(i)) for i in range(2)]
        deadline = monotonic() + 2
        while gate.snapshot()["async_waiters"] < 2 and monotonic() < deadline:
            sleep(0.001)
        assert gate.snapshot()["async_waiters"] == 2
        gate.release(0, success=True)
        for worker in workers:
            worker.result(timeout=3)
    assert all(event.is_set() for event in done)
    assert gate.snapshot()["active"] == 0
    assert gate.snapshot()["priority_waiters"] == 0


def test_cancelling_last_priority_waiter_unblocks_background_slot(monkeypatch):
    """关键等待者取消后立即通知可用后台槽位，不能等下一次模型完成。"""
    from equipment_deep_research.agents.performance import AdaptiveCallGate

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    async def exercise():
        gate = AdaptiveCallGate()
        gate.configure_concurrency(1)
        gate.try_acquire(priority="critical")
        critical = asyncio.create_task(gate.acquire_async(priority="critical"))
        background = asyncio.create_task(gate.acquire_async())
        await asyncio.sleep(0.01)
        critical.cancel()
        try:
            await critical
        except asyncio.CancelledError:
            pass
        gate.release(0, success=True)
        await asyncio.wait_for(background, timeout=1)
        gate.release(0, success=True)
        assert gate.snapshot()["active"] == 0
        assert gate.snapshot()["priority_waiters"] == 0
        assert gate.snapshot()["async_waiters"] == 0

    asyncio.run(exercise())
