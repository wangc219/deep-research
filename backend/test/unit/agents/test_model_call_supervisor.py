"""通用模型调用监督器的取消、超时与进度事件测试。"""

import asyncio

import pytest

from equipment_deep_research.harness.model_calls import (
    ModelCallPolicy,
    ModelCallSupervisor,
    ModelCallTimeoutError,
)
from platform_core.agents.middlewares import model_call_supervisor as middleware_module
from platform_core.agents.middlewares.model_call_supervisor import ModelCallSupervisorMiddleware


@pytest.mark.asyncio
async def test_model_call_supervisor_returns_first_success_and_emits_terminal_events():
    events = []

    async def observe(event):
        events.append(event)

    async def factory(attempt: int):
        return f"result-{attempt}"

    result = await ModelCallSupervisor(
        ModelCallPolicy(total_timeout_seconds=1, attempt_timeout_seconds=1)
    ).run(factory, observer=observe)

    assert result == "result-1"
    assert [event.kind for event in events] == ["started", "completed"]


@pytest.mark.asyncio
async def test_model_call_supervisor_reports_waiting_without_restarting_the_call():
    events = []
    calls = 0

    async def observe(event):
        events.append(event)

    async def factory(_attempt: int):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.04)
        return "done"

    result = await ModelCallSupervisor(
        ModelCallPolicy(
            total_timeout_seconds=1,
            attempt_timeout_seconds=1,
            feedback_interval_seconds=0.01,
        )
    ).run(factory, observer=observe)

    assert result == "done"
    assert calls == 1
    assert "waiting" in [event.kind for event in events]
    assert events[-1].kind == "completed"


@pytest.mark.asyncio
async def test_model_call_supervisor_timeout_cancels_every_attempt():
    cancelled_attempts = []

    async def factory(attempt: int):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled_attempts.append(attempt)

    with pytest.raises(ModelCallTimeoutError) as exc_info:
        await ModelCallSupervisor(
            ModelCallPolicy(
                total_timeout_seconds=0.08,
                attempt_timeout_seconds=0.03,
                max_attempts=2,
                feedback_interval_seconds=0.01,
            )
        ).run(factory)

    assert exc_info.value.attempts == 2
    assert cancelled_attempts == [1, 2]


@pytest.mark.asyncio
async def test_model_call_supervisor_observer_failure_does_not_corrupt_result():
    async def factory(_attempt: int):
        return "ok"

    async def broken_observer(_event):
        raise RuntimeError("projection failed")

    assert (
        await ModelCallSupervisor(
            ModelCallPolicy(total_timeout_seconds=1, attempt_timeout_seconds=1)
        ).run(factory, observer=broken_observer)
        == "ok"
    )


@pytest.mark.asyncio
async def test_model_call_supervisor_propagates_external_cancellation():
    child_cancelled = asyncio.Event()

    async def factory(_attempt: int):
        try:
            await asyncio.sleep(10)
        finally:
            child_cancelled.set()

    task = asyncio.create_task(
        ModelCallSupervisor(
            ModelCallPolicy(total_timeout_seconds=10, attempt_timeout_seconds=10)
        ).run(factory)
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert child_cancelled.is_set()


@pytest.mark.asyncio
async def test_model_call_middleware_projects_waiting_and_completed_events(monkeypatch):
    streamed = []
    monkeypatch.setattr(middleware_module, "get_stream_writer", lambda: streamed.append)
    middleware = ModelCallSupervisorMiddleware(timeout_seconds=1, feedback_interval_seconds=0.01)

    async def handler(_request):
        await asyncio.sleep(0.03)
        return "response"

    result = await middleware.awrap_model_call(object(), handler)

    assert result == "response"
    statuses = [event["status"] for event in streamed]
    assert statuses[-1] == "completed"
    assert "waiting" in statuses
    assert all(event["type"] == "platform_core.model_call_progress" for event in streamed)
