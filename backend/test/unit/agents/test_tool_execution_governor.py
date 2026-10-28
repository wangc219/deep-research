from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage

from platform_core.agents.harness import tool_execution as module
from platform_core.agents.harness.tool_execution import ToolExecutionGovernorMiddleware, scope_tools


def _requests(names: list[str], modes: list[str]) -> list[ToolCallRequest]:
    calls = [{"id": f"call-{index}", "name": name, "args": {}, "type": "tool_call"} for index, name in enumerate(names)]
    tools = [SimpleNamespace(name=name, metadata={"concurrency": mode}) for name, mode in zip(names, modes)]
    runtime = SimpleNamespace(
        tools=tools,
        context=SimpleNamespace(run_id="run-1", runtime_scope_id="scope-1", thread_id="thread-1"),
    )
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}
    return [
        ToolCallRequest(tool_call=call, tool=tool, state=state, runtime=runtime) for call, tool in zip(calls, tools)
    ]


@pytest.mark.asyncio
async def test_governor_bounds_parallel_tools_and_preserves_exclusive_barriers(monkeypatch) -> None:
    streamed: list[dict] = []
    monkeypatch.setattr(module, "get_stream_writer", lambda: streamed.append)
    middleware = ToolExecutionGovernorMiddleware(max_parallel_tools=2)
    requests = _requests(
        ["parallel-a", "parallel-b", "exclusive", "parallel-c"],
        ["parallel", "parallel", "exclusive", "parallel"],
    )
    active = 0
    peak = 0
    timeline: list[tuple[str, str]] = []
    lock = asyncio.Lock()

    async def handler(request):
        nonlocal active, peak
        name = request.tool_call["name"]
        async with lock:
            active += 1
            peak = max(peak, active)
            timeline.append(("start", name))
        await asyncio.sleep(0.02)
        async with lock:
            timeline.append(("end", name))
            active -= 1
        return ToolMessage(content=name, tool_call_id=request.tool_call["id"])

    results = await asyncio.gather(*(middleware.awrap_tool_call(request, handler) for request in requests))

    assert [result.content for result in results] == [
        "parallel-a",
        "parallel-b",
        "exclusive",
        "parallel-c",
    ]
    assert peak == 2
    assert timeline.index(("end", "parallel-a")) < timeline.index(("start", "exclusive"))
    assert timeline.index(("end", "parallel-b")) < timeline.index(("start", "exclusive"))
    assert timeline.index(("end", "exclusive")) < timeline.index(("start", "parallel-c"))
    assert any(event["event_type"] == "tool_queued" for event in streamed)
    assert streamed[-1]["status"] == "completed"
    assert all(event["type"] == "platform_core.agent_harness" for event in streamed)


@pytest.mark.asyncio
async def test_governor_propagates_cancellation_and_releases_active_slot(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_stream_writer", lambda: lambda _event: None)
    middleware = ToolExecutionGovernorMiddleware(max_parallel_tools=1)
    requests = _requests(["first", "second"], ["parallel", "parallel"])
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def handler(request):
        if request.tool_call["name"] == "first":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    first = asyncio.create_task(middleware.awrap_tool_call(requests[0], handler))
    await first_started.wait()
    second = asyncio.create_task(middleware.awrap_tool_call(requests[1], handler))
    await asyncio.sleep(0)
    assert not second_started.is_set()

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.wait_for(second, timeout=0.2)
    assert second_started.is_set()


@pytest.mark.asyncio
async def test_governor_releases_slot_after_repeated_cancellation(monkeypatch) -> None:
    """外层被重复取消时，独立结算任务仍会唤醒后续调用。"""

    monkeypatch.setattr(module, "get_stream_writer", lambda: lambda _event: None)
    middleware = ToolExecutionGovernorMiddleware(max_parallel_tools=1)
    requests = _requests(["first", "second"], ["parallel", "parallel"])
    first_started = asyncio.Event()
    release_entered = asyncio.Event()
    allow_release = asyncio.Event()
    second_started = asyncio.Event()
    real_release = middleware._scheduler.release

    async def delayed_release(batch):
        release_entered.set()
        await allow_release.wait()
        return await real_release(batch)

    monkeypatch.setattr(middleware._scheduler, "release", delayed_release)

    async def handler(request):
        if request.tool_call["name"] == "first":
            first_started.set()
            await asyncio.Event().wait()
        second_started.set()
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    first = asyncio.create_task(middleware.awrap_tool_call(requests[0], handler))
    await first_started.wait()
    second = asyncio.create_task(middleware.awrap_tool_call(requests[1], handler))
    first.cancel()
    await release_entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    allow_release.set()
    await asyncio.wait_for(second_started.wait(), timeout=0.2)
    await asyncio.wait_for(second, timeout=0.2)


@pytest.mark.asyncio
async def test_governor_isolates_progress_observer_failures(monkeypatch) -> None:
    """用户进度通道异常不能改变工具调用结果。"""

    def broken_writer(_event):
        raise RuntimeError("stream unavailable")

    monkeypatch.setattr(module, "get_stream_writer", lambda: broken_writer)
    middleware = ToolExecutionGovernorMiddleware(max_parallel_tools=1)
    request = _requests(["search"], ["parallel"])[0]

    async def handler(current):
        return ToolMessage(content="result", tool_call_id=current.tool_call["id"])

    result = await middleware.awrap_tool_call(request, handler)

    assert result.content == "result"


def test_scope_tools_hides_child_bindings_without_mutating_input() -> None:
    read = SimpleNamespace(name="read")
    write = SimpleNamespace(name="write")
    original = [read, write]

    scoped = scope_tools(
        original,
        root_scope_id="conversation",
        scope_id="subagent",
        hidden=frozenset({"write"}),
    )

    assert scoped == [read]
    assert original == [read, write]


def test_scope_tools_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate tool name"):
        scope_tools(
            [SimpleNamespace(name="search"), SimpleNamespace(name="search")],
            root_scope_id="conversation",
            scope_id="agent",
        )
