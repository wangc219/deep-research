"""Low-level agent loop: LLM turns, tool calls, queues, and lifecycle events.

``AgentLoop`` is the demand-discovery translation of Pi's ``agent-loop.ts``. It
deliberately carries no domain or session state. It only:

- appends the incoming user message(s) to the working context,
- streams each provider response into a final assistant message,
- batches and executes the assistant's tool calls,
- appends tool result messages in the original tool-call order,
- emits the lifecycle event sequence, and
- calls ``prepare_next_turn`` before each subsequent provider request.

Higher-level concerns (phase state machine, save point, pending domain/trace
proposal flushes, session persistence, context projection) belong to the
harness, not here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from knowledgegraph.demand_discovery.harness.cancellation import (
    CancelToken,
    RunCancelled,
)
from knowledgegraph.demand_discovery.harness.context_cleanup import (
    annotate_transient_tool_error,
    apply_transient_cleanup,
)
from knowledgegraph.demand_discovery.harness.event_stream import (
    AsyncEventStream,
    StreamError,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent
from knowledgegraph.demand_discovery.harness.tools import (
    BeforeToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
)
from knowledgegraph.demand_discovery.harness.tool_result_mediator import (
    MediatedToolResult,
)
from knowledgegraph.demand_discovery.harness.types import (
    AgentMessage,
    AssistantContentBlock,
    ToolCall,
    ToolResult,
)


@dataclass
class TurnState:
    """Mutable per-run state passed to ``prepare_next_turn``.

    ``prepare_next_turn`` may inspect and replace ``messages`` / ``tools`` /
    ``options`` before the next provider request, or set ``stop`` to end the
    loop early.
    """

    messages: list[AgentMessage]
    tools: list[ToolDefinition]
    options: dict[str, Any] = field(default_factory=dict)
    stop: bool = False


@dataclass
class AgentLoopConfig:
    """Configuration for one :meth:`AgentLoop.run` invocation."""

    run_id: str = "run"
    agent_run_id: str = "agent"
    worker_id: str = "worker"
    system_prompt: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    max_turns: int = 64
    cancel_token: CancelToken = field(default_factory=CancelToken)
    before_tool_call: BeforeToolCall | None = None
    tool_result_mediator: Callable[[ToolResult], MediatedToolResult] | None = None
    prepare_next_turn: Callable[[TurnState], Any] | None = None
    # Pi-style steering / follow-up injection. ``get_steering_messages`` is
    # drained after every turn (mid-work intervention); ``get_follow_up_messages``
    # is drained only when the loop would otherwise stop (no tool calls, no
    # steering). Both return a list of messages to append and continue, or an
    # empty list to inject nothing.
    get_steering_messages: Callable[[], list[AgentMessage]] | None = None
    get_follow_up_messages: Callable[[], list[AgentMessage]] | None = None
    on_event: Callable[[AgentEvent], None] | None = None


class AgentLoop:
    """Stateless driver of the LLM-turn / tool-call cycle."""

    def run(
        self,
        messages: list[AgentMessage],
        provider: Any,
        tools: list[ToolDefinition],
        config: AgentLoopConfig,
    ) -> AsyncEventStream:
        """Start the loop and return a stream of :class:`AgentEvent`.

        The stream's ``result()`` is the final message list (user message,
        assistant messages, and tool result messages in original call order).
        """

        stream = AsyncEventStream()
        asyncio.ensure_future(self._run(stream, messages, provider, tools, config))
        return stream

    async def _run(
        self,
        stream: AsyncEventStream,
        messages: list[AgentMessage],
        provider: Any,
        tools: list[ToolDefinition],
        config: AgentLoopConfig,
    ) -> None:
        registry = ToolRegistry()
        for tool in tools:
            registry.register(tool)
        registry.set_before_tool_call(config.before_tool_call)

        state = TurnState(
            messages=list(messages),
            tools=list(tools),
            options=dict(config.options),
        )
        exec_ctx = ToolExecutionContext(
            run_id=config.run_id,
            agent_run_id=config.agent_run_id,
            worker_id=config.worker_id,
            permissions={},
            cancel_token=config.cancel_token,
        )

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            event = AgentEvent(
                type=event_type,
                run_id=config.run_id,
                payload=payload,
                agent_run_id=config.agent_run_id,
            )
            if config.on_event is not None:
                config.on_event(event)
            stream.push(event)

        try:
            emit("agent_start", {})
            turn_index = 0
            turn_open = False
            first_turn = True

            while turn_index < config.max_turns:
                config.cancel_token.raise_if_cancelled()
                if not first_turn and config.prepare_next_turn is not None:
                    maybe = config.prepare_next_turn(state)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    if state.stop:
                        break
                first_turn = False

                turn_index += 1
                turn_open = True
                emit("turn_start", {"turn": turn_index})

                assistant = await self._stream_assistant(
                    stream, provider, state, config, emit
                )
                state.messages.append(assistant)
                emit("message_appended", {"message": assistant.to_dict()})

                calls = self._tool_calls_from(assistant)
                if not calls:
                    # No tool calls. Drain steering first (mid-work injection),
                    # then follow-up (continue after an apparent stop). If both
                    # are empty, the turn — and the loop — ends.
                    injected = self._drain(config.get_steering_messages)
                    if not injected:
                        injected = self._drain(config.get_follow_up_messages)
                    if injected:
                        state.messages.extend(injected)
                        for message in injected:
                            emit("message_appended", {"message": message.to_dict()})
                        emit("turn_end", {"turn": turn_index})
                        turn_open = False
                        continue
                    emit("turn_end", {"turn": turn_index})
                    turn_open = False
                    break

                results = await self._execute_tool_calls(
                    stream, registry, calls, exec_ctx, state, emit
                )

                # append tool result messages in original tool-call order
                mediated_stop_requested = False
                for call in calls:
                    result = results[call.id]
                    mediated = self._mediate_tool_result(result, config, emit)
                    if mediated is not None:
                        mediated_stop_requested = (
                            mediated_stop_requested
                            or mediated.pause_requested
                            or mediated.terminate_turn
                        )
                        if mediated.pause_requested or mediated.terminate_turn:
                            result.terminate = True
                    message = result.to_message()
                    annotate_transient_tool_error(message, result)
                    if mediated is not None:
                        message.content = mediated.message_content
                        message.metadata.update(
                            {
                                "control_event": dict(mediated.control_event),
                                "debug_refs": list(mediated.debug_refs),
                                "pause_requested": mediated.pause_requested,
                                "terminate_turn": mediated.terminate_turn,
                                "transient_cleanup": dict(
                                    mediated.transient_cleanup
                                ),
                            }
                        )
                    state.messages.append(message)
                    emit("message_appended", {"message": message.to_dict()})
                    if mediated is not None and not result.is_error:
                        apply_transient_cleanup(
                            state.messages, mediated.transient_cleanup
                        )

                # steering messages injected during the turn are appended after
                # the tool results, before the next provider request
                injected = self._drain(config.get_steering_messages)
                state.messages.extend(injected)
                for message in injected:
                    emit("message_appended", {"message": message.to_dict()})

                emit("turn_end", {"turn": turn_index})
                turn_open = False

                if mediated_stop_requested:
                    break
                if results and all(r.terminate for r in results.values()):
                    break

            emit("agent_end", {})
            stream.end(state.messages)
        except RunCancelled as exc:
            if turn_open:
                emit("turn_end", {"turn": turn_index, "aborted": True, "reason": str(exc)})
            emit("agent_end", {"aborted": True, "reason": str(exc)})
            stream.end(state.messages)
        except Exception as exc:  # surface as a terminal stream error
            stream.error(str(exc))

    async def _stream_assistant(
        self,
        stream: AsyncEventStream,
        provider: Any,
        state: TurnState,
        config: AgentLoopConfig,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> AgentMessage:
        """Consume one provider response into a final assistant message."""

        from knowledgegraph.demand_discovery.llm.types import (
            AssistantMessage,
            LLMContext,
        )

        context = LLMContext(
            messages=list(state.messages),
            system_prompt=config.system_prompt,
            metadata={
                "run_id": config.run_id,
                "agent_run_id": config.agent_run_id,
                "worker_id": config.worker_id,
            },
        )
        emit("message_start", {})
        config.cancel_token.raise_if_cancelled()

        try:
            options = {**dict(state.options), "cancel_token": config.cancel_token}
            provider_stream = provider.stream(context, state.tools, options)
            async for _event in self._consume_provider_events(
                provider_stream, config.cancel_token
            ):
                config.cancel_token.raise_if_cancelled()
                # Only content deltas count as message updates; start/done/error
                # are lifecycle markers, not incremental content.
                if getattr(_event, "type", "") in (
                    "text_delta",
                    "thinking_delta",
                    "toolcall_delta",
                ):
                    emit("message_update", {})
            config.cancel_token.raise_if_cancelled()
            assistant_message = provider_stream.result()
        except RunCancelled:
            raise
        except StreamError as exc:
            assistant_message = AssistantMessage(
                content=[],
                is_error=True,
                error_message=str(exc),
            )
        except Exception as exc:
            assistant_message = AssistantMessage(
                content=[],
                is_error=True,
                error_message=str(exc),
            )

        blocks: list[AssistantContentBlock] = list(assistant_message.content)
        metadata: dict[str, Any] = {}
        error_message = getattr(assistant_message, "error_message", "")
        usage = dict(getattr(assistant_message, "usage", {}) or {})
        if error_message:
            metadata["error_message"] = error_message
        if usage:
            metadata["usage"] = usage
        message = AgentMessage(
            role="assistant",
            content=blocks,
            timestamp=0,
            is_error=getattr(assistant_message, "is_error", False),
            metadata=metadata,
        )
        emit(
            "message_end",
            {
                "is_error": message.is_error,
                "error_message": error_message,
                "usage": usage,
            },
        )
        return message

    @staticmethod
    async def _consume_provider_events(
        provider_stream: AsyncEventStream,
        cancel_token: CancelToken,
    ):
        iterator = provider_stream.__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=0.05)
                if not done:
                    cancel_token.raise_if_cancelled()
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                yield event
                pending = asyncio.create_task(iterator.__anext__())
        except RunCancelled:
            if not pending.done():
                pending.cancel()
            raise
        except Exception:
            if not pending.done():
                pending.cancel()
            raise

    @staticmethod
    def _drain(
        getter: Callable[[], list[AgentMessage]] | None,
    ) -> list[AgentMessage]:
        """Pull queued steering / follow-up messages, if a getter is set."""

        if getter is None:
            return []
        return list(getter() or [])

    @staticmethod
    def _tool_calls_from(message: AgentMessage) -> list[ToolCall]:
        if not isinstance(message.content, list):
            return []
        return [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.arguments))
            for b in message.content
            if b.type == "tool_call"
        ]

    @staticmethod
    def _mediate_tool_result(
        result: ToolResult,
        config: AgentLoopConfig,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> MediatedToolResult | None:
        if config.tool_result_mediator is None:
            return None
        mediated = config.tool_result_mediator(result)
        emit(
            "tool_result_mediated",
            {
                "tool_call_id": result.tool_call_id,
                "tool_name": result.tool_name,
                "control_event": dict(mediated.control_event),
                "debug_refs": list(mediated.debug_refs),
                "pause_requested": mediated.pause_requested,
                "terminate_turn": mediated.terminate_turn,
                "transient_cleanup": dict(mediated.transient_cleanup),
            },
        )
        return mediated

    async def _execute_tool_calls(
        self,
        stream: AsyncEventStream,
        registry: ToolRegistry,
        calls: list[ToolCall],
        exec_ctx: ToolExecutionContext,
        state: TurnState,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> dict[str, ToolResult]:
        """Execute a batch of tool calls; return results keyed by call id.

        ``tool_execution_end`` events fire in completion order, but the returned
        mapping lets the caller append result messages in original call order.
        Sequential execution is forced if any called tool declares it.
        """

        names = [c.name for c in calls]
        sequential = registry.requires_sequential(names)
        results: dict[str, ToolResult] = {}

        for call in calls:
            exec_ctx.cancel_token.raise_if_cancelled()
            exec_ctx.budget_state = str(state.options.get("budget_state", "normal"))
            emit("tool_execution_start", {"tool_call_id": call.id, "name": call.name})

        if sequential:
            for call in calls:
                exec_ctx.cancel_token.raise_if_cancelled()
                exec_ctx.budget_state = str(
                    state.options.get("budget_state", "normal")
                )
                result = await registry.execute(call, exec_ctx)
                exec_ctx.cancel_token.raise_if_cancelled()
                results[call.id] = result
                emit(
                    "tool_execution_end",
                    {
                        "tool_call_id": call.id,
                        "is_error": result.is_error,
                        "domain_proposals": list(result.domain_proposals),
                        "trace_proposals": list(result.trace_proposals),
                    },
                )
            return results

        async def run_one(call: ToolCall) -> tuple[str, ToolResult]:
            exec_ctx.cancel_token.raise_if_cancelled()
            exec_ctx.budget_state = str(state.options.get("budget_state", "normal"))
            result = await registry.execute(call, exec_ctx)
            exec_ctx.cancel_token.raise_if_cancelled()
            return call.id, result

        pending = [asyncio.ensure_future(run_one(c)) for c in calls]
        try:
            while pending:
                exec_ctx.cancel_token.raise_if_cancelled()
                done, pending = await asyncio.wait(
                    pending,
                    timeout=0.05,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for finished in done:
                    call_id, result = await finished
                    results[call_id] = result
                    emit(
                        "tool_execution_end",
                        {
                            "tool_call_id": call_id,
                            "is_error": result.is_error,
                            "domain_proposals": list(result.domain_proposals),
                            "trace_proposals": list(result.trace_proposals),
                        },
                    )
        except RunCancelled:
            for task in pending:
                task.cancel()
            raise
        return results
