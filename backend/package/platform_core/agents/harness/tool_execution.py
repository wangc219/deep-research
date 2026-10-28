"""智能对话工具调用的有界并发、独占屏障与进度事件。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
import logging
from typing import Any, Literal, TypedDict

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command


ToolConcurrency = Literal["parallel", "exclusive"]
ToolExecutionEventType = Literal["tool_queued", "tool_started", "tool_finished", "tool_failed"]
ToolHandler = Callable[[Any], Awaitable[ToolMessage | Command[Any]]]
logger = logging.getLogger(__name__)


class ToolExecutionEvent(TypedDict):
    """写入现有追加事件流的工具生命周期事件。"""

    type: Literal["platform_core.agent_harness"]
    event_type: ToolExecutionEventType
    status: str
    message: str
    run_id: str | None
    scope_id: str | None
    tool_name: str
    tool_call_id: str
    concurrency: ToolConcurrency
    batch_index: int
    batch_size: int
    active_tools: int
    pending_tools: int
    completed_tools: int


@dataclass(frozen=True, slots=True)
class ToolBatch:
    """模型单次响应中的有序工具调用批次。"""

    key: tuple[str, ...]
    index: int
    modes: tuple[ToolConcurrency, ...]


@dataclass(slots=True)
class _BatchState:
    modes: tuple[ToolConcurrency, ...]
    active: set[int] = field(default_factory=set)
    waiting: set[int] = field(default_factory=set)
    completed: set[int] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ToolBatchProgress:
    active: int
    pending: int
    completed: int
    total: int


class BoundedToolScheduler:
    """按模型顺序保留独占屏障，并滚动填充并行执行槽位。"""

    def __init__(
        self,
        max_parallel_tools: int,
        capacity_resolver: Callable[[], int] | None = None,
    ) -> None:
        if max_parallel_tools < 1:
            raise ValueError("max_parallel_tools must be positive")
        self.max_parallel_tools = max_parallel_tools
        self._capacity_resolver = capacity_resolver
        self._condition = asyncio.Condition()
        self._batches: dict[tuple[str, ...], _BatchState] = {}

    async def acquire(
        self,
        batch: ToolBatch,
        *,
        on_wait: Callable[[ToolBatchProgress], None] | None = None,
    ) -> tuple[bool, ToolBatchProgress]:
        """等待调用可执行，返回是否发生排队及当前批次进度。"""

        async with self._condition:
            state = self._batches.setdefault(batch.key, _BatchState(batch.modes))
            if state.modes != batch.modes:
                raise RuntimeError("tool batch modes changed while executing")
            waited = not self._can_start(state, batch.index)
            if waited:
                state.waiting.add(batch.index)
                if on_wait is not None:
                    on_wait(self._progress(state))
            try:
                await self._condition.wait_for(lambda: self._can_start(state, batch.index))
            except BaseException:
                state.waiting.discard(batch.index)
                state.completed.add(batch.index)
                self._condition.notify_all()
                self._discard_if_settled(batch.key, state)
                raise
            state.waiting.discard(batch.index)
            state.active.add(batch.index)
            return waited, self._progress(state)

    async def release(self, batch: ToolBatch) -> ToolBatchProgress:
        """结算一个调用，并唤醒不再受屏障阻塞的调用。"""

        async with self._condition:
            state = self._batches.get(batch.key)
            if state is None:
                return ToolBatchProgress(active=0, pending=0, completed=len(batch.key), total=len(batch.key))
            state.active.discard(batch.index)
            state.waiting.discard(batch.index)
            state.completed.add(batch.index)
            progress = self._progress(state)
            self._condition.notify_all()
            self._discard_if_settled(batch.key, state)
            return progress

    def _can_start(self, state: _BatchState, index: int) -> bool:
        if index in state.completed or index in state.active:
            return False
        mode = state.modes[index]
        if mode == "exclusive":
            return not state.active and all(previous in state.completed for previous in range(index))
        if len(state.active) >= self._parallel_limit():
            return False
        return all(state.modes[previous] != "exclusive" or previous in state.completed for previous in range(index))

    def _parallel_limit(self) -> int:
        if self._capacity_resolver is None:
            return self.max_parallel_tools
        try:
            return max(1, int(self._capacity_resolver()))
        except Exception:  # noqa: BLE001 - 动态快照异常时保留原配置，不阻断工具执行
            logger.warning("Failed to resolve adaptive tool capacity", exc_info=True)
            return self.max_parallel_tools

    @staticmethod
    def _progress(state: _BatchState) -> ToolBatchProgress:
        total = len(state.modes)
        return ToolBatchProgress(
            active=len(state.active),
            pending=max(0, total - len(state.active) - len(state.completed)),
            completed=len(state.completed),
            total=total,
        )

    def _discard_if_settled(self, key: tuple[str, ...], state: _BatchState) -> None:
        if len(state.completed) == len(state.modes) and not state.active and not state.waiting:
            self._batches.pop(key, None)


class ToolExecutionGovernorMiddleware(AgentMiddleware):
    """自动治理主智能体与子智能体的真实工具执行。"""

    def __init__(
        self,
        *,
        max_parallel_tools: int = 4,
        capacity_resolver: Callable[[], int] | None = None,
    ) -> None:
        self.max_parallel_tools = max_parallel_tools
        self._scheduler = BoundedToolScheduler(max_parallel_tools, capacity_resolver)
        self._settlements: set[asyncio.Task[ToolBatchProgress]] = set()

    def wrap_tool_call(self, request, handler):
        # 生产对话均走异步执行；同步入口保持既有行为。
        return handler(request)

    async def awrap_tool_call(self, request, handler: ToolHandler):
        batch = _tool_batch(request)
        tool_call = request.tool_call
        tool_name = str(tool_call.get("name") or "unknown")
        tool_call_id = str(tool_call.get("id") or f"{tool_name}:{batch.index}")
        mode = batch.modes[batch.index]

        def emit_waiting(progress: ToolBatchProgress) -> None:
            _emit_harness_event(
                request,
                event_type="tool_queued",
                status="waiting",
                message=f"工具执行排队中：{tool_name}",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                mode=mode,
                batch=batch,
                progress=progress,
            )

        try:
            _waited, progress = await self._scheduler.acquire(batch, on_wait=emit_waiting)
        except asyncio.CancelledError:
            await self._settle_call(
                request,
                batch=batch,
                event_type="tool_failed",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                mode=mode,
            )
            raise
        _emit_harness_event(
            request,
            event_type="tool_started",
            status="working",
            message=f"正在执行工具：{tool_name}",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            mode=mode,
            batch=batch,
            progress=progress,
        )

        outcome = "tool_finished"
        try:
            return await handler(request)
        except BaseException:
            outcome = "tool_failed"
            raise
        finally:
            await self._settle_call(
                request,
                event_type=outcome,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                mode=mode,
                batch=batch,
            )

    async def _settle_call(
        self,
        request,
        *,
        event_type: Literal["tool_finished", "tool_failed"],
        tool_name: str,
        tool_call_id: str,
        mode: ToolConcurrency,
        batch: ToolBatch,
    ) -> ToolBatchProgress:
        """即使执行任务被重复取消，也让批次槽位在后台完成结算。"""

        async def settle() -> ToolBatchProgress:
            progress = await self._scheduler.release(batch)
            failed = event_type == "tool_failed"
            completed = progress.completed == progress.total
            _emit_harness_event(
                request,
                event_type=event_type,
                status="failed" if failed else ("completed" if completed else "working"),
                message=(
                    f"工具执行失败：{tool_name}；批次进度 {progress.completed}/{progress.total}"
                    if failed
                    else (
                        f"工具批次已完成：{progress.completed}/{progress.total}"
                        if completed
                        else f"工具批次执行中：{progress.completed}/{progress.total}"
                    )
                ),
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                mode=mode,
                batch=batch,
                progress=progress,
            )
            return progress

        settlement = asyncio.create_task(settle())
        self._settlements.add(settlement)
        settlement.add_done_callback(self._settlements.discard)
        try:
            return await asyncio.shield(settlement)
        except asyncio.CancelledError:
            settlement.add_done_callback(_consume_background_result)
            raise


def scope_tools(
    tools: Sequence[Any],
    *,
    root_scope_id: str,
    scope_id: str,
    hidden: frozenset[str] = frozenset(),
) -> list[Any]:
    """按当前 Agent 作用域生成稳定工具快照。"""

    from platform_core.agents.harness.scoped_registry import ScopedRegistry

    bindings: dict[str, Any] = {}
    for tool in tools:
        name = str(getattr(tool, "name", "")).strip()
        if not name:
            raise ValueError("tool name must not be empty")
        if name in bindings:
            raise ValueError(f"duplicate tool name in scope: {name}")
        bindings[name] = tool
    root = ScopedRegistry(root_scope_id, bindings)
    return list(root.child(scope_id, hidden=hidden).snapshot().values())


def _tool_batch(request) -> ToolBatch:
    calls = _latest_tool_calls(request.state)
    current = request.tool_call
    current_id = str(current.get("id") or "")
    if not calls or current_id not in {str(call.get("id") or "") for call in calls}:
        calls = [current]

    runtime_tools = getattr(getattr(request, "runtime", None), "tools", None) or []
    tools_by_name = {str(getattr(tool, "name", "")): tool for tool in runtime_tools if str(getattr(tool, "name", ""))}
    if request.tool is not None:
        tools_by_name[str(getattr(request.tool, "name", ""))] = request.tool

    ids: list[str] = []
    modes: list[ToolConcurrency] = []
    index = 0
    for call_index, call in enumerate(calls):
        name = str(call.get("name") or "unknown")
        call_id = str(call.get("id") or f"{name}:{call_index}")
        ids.append(call_id)
        modes.append(_tool_concurrency(tools_by_name.get(name)))
        if call_id == current_id:
            index = call_index
    return ToolBatch(key=tuple(ids), index=index, modes=tuple(modes))


def _latest_tool_calls(state: Any) -> list[dict[str, Any]]:
    if isinstance(state, dict):
        messages = state.get("messages") or []
    elif isinstance(state, list | tuple):
        messages = state
    else:
        messages = getattr(state, "messages", None) or []
    for message in reversed(messages):
        calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        if isinstance(calls, list) and calls:
            return [call for call in calls if isinstance(call, dict)]
    return []


def _tool_concurrency(tool: Any) -> ToolConcurrency:
    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, dict):
        mode = metadata.get("concurrency")
        if mode in {"parallel", "exclusive"}:
            return mode
        supports_parallel = metadata.get("supports_parallel_tool_calls")
        if supports_parallel is False:
            return "exclusive"
    return "parallel"


def _emit_harness_event(
    request,
    *,
    event_type: ToolExecutionEventType,
    status: str,
    message: str,
    tool_name: str,
    tool_call_id: str,
    mode: ToolConcurrency,
    batch: ToolBatch,
    progress: ToolBatchProgress,
) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    context = getattr(getattr(request, "runtime", None), "context", None)
    event: ToolExecutionEvent = {
        "type": "platform_core.agent_harness",
        "event_type": event_type,
        "status": status,
        "message": message,
        "run_id": getattr(context, "run_id", None),
        "scope_id": getattr(context, "runtime_scope_id", None) or getattr(context, "thread_id", None),
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "concurrency": mode,
        "batch_index": batch.index,
        "batch_size": len(batch.key),
        "active_tools": progress.active,
        "pending_tools": progress.pending,
        "completed_tools": progress.completed,
    }
    try:
        writer(event)
    except Exception:
        logger.exception("Agent Harness event observer failed for %s", event_type)


def _consume_background_result(task: asyncio.Task[ToolBatchProgress]) -> None:
    """回收重复取消后继续运行的结算任务异常。"""

    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Tool-call settlement failed after caller cancellation")


__all__ = [
    "BoundedToolScheduler",
    "ToolBatch",
    "ToolBatchProgress",
    "ToolConcurrency",
    "ToolExecutionGovernorMiddleware",
    "ToolExecutionEvent",
    "ToolExecutionEventType",
    "scope_tools",
]
