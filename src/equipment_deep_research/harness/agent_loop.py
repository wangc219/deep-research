"""Domain-free model/tool loop with immutable per-turn provider inputs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
import inspect
from typing import Any, Literal, cast

from equipment_deep_research.domain.proposals import freeze_plain, thaw_plain
from equipment_deep_research.providers.base import (
    ModelMessage,
    ModelProvider,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


AgentLoopStatus = Literal[
    "completed",
    "max_turns",
    "stopped",
    "budget_exhausted",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class TurnSnapshotInput:
    """Frozen provider input that Task 4 can persist as a turn snapshot."""

    turn_index: int
    messages: Sequence[ModelMessage]
    tools: Sequence[ToolDefinition]
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.options, Mapping):
            raise TypeError("turn options must be an object")
        messages = tuple(self.messages)
        tools = tuple(self.tools)
        if self.turn_index < 1:
            raise ValueError("turn_index must be positive")
        if not all(isinstance(message, ModelMessage) for message in messages):
            raise TypeError("messages must contain only ModelMessage values")
        if not all(isinstance(tool, ToolDefinition) for tool in tools):
            raise TypeError("tools must contain only ToolDefinition values")
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(
            self,
            "options",
            cast(Mapping[str, Any], freeze_plain(self.options)),
        )

    def to_plain(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "messages": [message.to_plain() for message in self.messages],
            "tools": [tool.to_plain() for tool in self.tools],
            "options": thaw_plain(self.options),
        }


@dataclass(frozen=True)
class AgentLoopEvent:
    event_type: str
    run_id: str
    agent_id: str
    turn_index: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    snapshot_input: TurnSnapshotInput | None = None
    message: ModelMessage | None = None
    tool_call: ProviderToolCall | None = None
    tool_result: ToolResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("event payload must be an object")
        if self.snapshot_input is not None and not isinstance(
            self.snapshot_input, TurnSnapshotInput
        ):
            raise TypeError("snapshot_input must be TurnSnapshotInput")
        if self.message is not None and not isinstance(self.message, ModelMessage):
            raise TypeError("message must be ModelMessage")
        if self.tool_call is not None and not isinstance(
            self.tool_call, ProviderToolCall
        ):
            raise TypeError("tool_call must be ProviderToolCall")
        if self.tool_result is not None and not isinstance(self.tool_result, ToolResult):
            raise TypeError("tool_result must be ToolResult")
        object.__setattr__(
            self,
            "payload",
            cast(Mapping[str, Any], freeze_plain(self.payload)),
        )

    def to_plain(self) -> dict[str, Any]:
        value = {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "payload": thaw_plain(self.payload),
        }
        if self.turn_index is not None:
            value["turn_index"] = self.turn_index
        if self.snapshot_input is not None:
            value["snapshot_input"] = self.snapshot_input.to_plain()
        if self.message is not None:
            value["message"] = self.message.to_plain()
        if self.tool_call is not None:
            value["tool_call"] = self.tool_call.to_plain()
        if self.tool_result is not None:
            value["tool_result"] = self.tool_result.to_plain()
        return value


StopCallback = Callable[[TurnSnapshotInput], bool | Awaitable[bool]]
PrepareTurnCallback = Callable[
    [TurnSnapshotInput],
    TurnSnapshotInput | None | Awaitable[TurnSnapshotInput | None],
]
EventCallback = Callable[[AgentLoopEvent], None | Awaitable[None]]


@dataclass(frozen=True)
class AgentLoopConfig:
    run_id: str = "run"
    agent_id: str = "agent"
    max_turns: int = 64
    options: Mapping[str, Any] = field(default_factory=dict)
    permissions: Mapping[str, Any] = field(default_factory=dict)
    prepare_turn: PrepareTurnCallback | None = None
    should_stop: StopCallback | None = None
    budget_exhausted: StopCallback | None = None
    on_event: EventCallback | None = None

    def __post_init__(self) -> None:
        if self.max_turns < 0:
            raise ValueError("max_turns must not be negative")
        if not isinstance(self.options, Mapping):
            raise TypeError("options must be an object")
        if not isinstance(self.permissions, Mapping):
            raise TypeError("permissions must be an object")
        object.__setattr__(
            self,
            "options",
            cast(Mapping[str, Any], freeze_plain(self.options)),
        )
        object.__setattr__(
            self,
            "permissions",
            cast(Mapping[str, Any], freeze_plain(self.permissions)),
        )


@dataclass(frozen=True)
class AgentLoopResult:
    status: AgentLoopStatus
    messages: Sequence[ModelMessage]
    turn_count: int
    turn_snapshots: Sequence[TurnSnapshotInput] = field(default_factory=tuple)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "turn_snapshots", tuple(self.turn_snapshots))

    @property
    def snapshots(self) -> tuple[TurnSnapshotInput, ...]:
        return cast(tuple[TurnSnapshotInput, ...], self.turn_snapshots)

    def to_plain(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "messages": [message.to_plain() for message in self.messages],
            "turn_count": self.turn_count,
            "turn_snapshots": [snapshot.to_plain() for snapshot in self.turn_snapshots],
            "error": self.error,
        }


class AgentLoop:
    """Drive streamed assistant turns and ordered tool-result messages."""

    async def run(
        self,
        messages: Sequence[ModelMessage],
        provider: ModelProvider,
        tools: Sequence[ToolDefinition],
        config: AgentLoopConfig,
    ) -> AgentLoopResult:
        working_messages = list(_freeze_messages(messages))
        base_tools = _freeze_tools(tools)
        snapshots: list[TurnSnapshotInput] = []
        execution_context = ToolExecutionContext(
            run_id=config.run_id,
            agent_id=config.agent_id,
            permissions=config.permissions,
        )

        try:
            for turn_index in range(1, config.max_turns + 1):
                snapshot = TurnSnapshotInput(
                    turn_index=turn_index,
                    messages=working_messages,
                    tools=base_tools,
                    options=config.options,
                )
                if config.prepare_turn is not None:
                    prepared = await _maybe_await(config.prepare_turn(snapshot))
                    if prepared is not None:
                        if not isinstance(prepared, TurnSnapshotInput):
                            raise TypeError("prepare_turn must return TurnSnapshotInput or None")
                        snapshot = TurnSnapshotInput(
                            turn_index=turn_index,
                            messages=prepared.messages,
                            tools=prepared.tools,
                            options=prepared.options,
                        )

                if await _callback_is_true(config.should_stop, snapshot):
                    return await self._complete(
                        "stopped", working_messages, snapshots, config
                    )
                if await _callback_is_true(config.budget_exhausted, snapshot):
                    return await self._complete(
                        "budget_exhausted", working_messages, snapshots, config
                    )

                snapshots.append(snapshot)
                await self._emit(
                    config,
                    "turn_started",
                    turn_index,
                    {"snapshot_input": snapshot.to_plain()},
                    snapshot_input=snapshot,
                )

                assistant = await self._collect_assistant(provider, snapshot)
                working_messages.append(assistant)
                await self._emit(
                    config,
                    "assistant_message",
                    turn_index,
                    {"message": assistant.to_plain()},
                    message=assistant,
                )

                calls = tuple(assistant.tool_calls)
                if not calls:
                    await self._emit(
                        config,
                        "turn_end",
                        turn_index,
                        {"status": "completed"},
                    )
                    return await self._complete(
                        "completed", working_messages, snapshots, config
                    )

                results = await self._execute_calls(
                    calls,
                    snapshot.tools,
                    execution_context,
                )
                for provider_call, result in zip(calls, results, strict=True):
                    message = _tool_message(provider_call, result)
                    working_messages.append(message)
                    await self._emit(
                        config,
                        "tool_result",
                        turn_index,
                        {
                            "tool_call": provider_call.to_plain(),
                            "result": result.to_plain(),
                            "message": message.to_plain(),
                        },
                        message=message,
                        tool_call=provider_call,
                        tool_result=result,
                    )

                turn_status = (
                    "max_turns" if turn_index == config.max_turns else "continued"
                )
                await self._emit(
                    config,
                    "turn_end",
                    turn_index,
                    {"status": turn_status},
                )

            return await self._complete(
                "max_turns", working_messages, snapshots, config
            )
        except asyncio.CancelledError:
            await self._emit(
                config,
                "loop_failed",
                snapshots[-1].turn_index if snapshots else None,
                {"status": "cancelled", "error": "cancelled"},
            )
            raise
        except Exception as exc:
            await self._emit(
                config,
                "loop_failed",
                snapshots[-1].turn_index if snapshots else None,
                {
                    "status": "failed",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return AgentLoopResult(
                status="failed",
                messages=working_messages,
                turn_count=len(snapshots),
                turn_snapshots=snapshots,
                error=str(exc),
            )

    async def _complete(
        self,
        status: AgentLoopStatus,
        messages: Sequence[ModelMessage],
        snapshots: Sequence[TurnSnapshotInput],
        config: AgentLoopConfig,
    ) -> AgentLoopResult:
        await self._emit(
            config,
            "loop_completed",
            snapshots[-1].turn_index if snapshots else None,
            {"status": status, "turn_count": len(snapshots)},
        )
        return AgentLoopResult(
            status=status,
            messages=messages,
            turn_count=len(snapshots),
            turn_snapshots=snapshots,
        )

    async def _emit(
        self,
        config: AgentLoopConfig,
        event_type: str,
        turn_index: int | None,
        payload: Mapping[str, Any],
        *,
        snapshot_input: TurnSnapshotInput | None = None,
        message: ModelMessage | None = None,
        tool_call: ProviderToolCall | None = None,
        tool_result: ToolResult | None = None,
    ) -> None:
        if config.on_event is None:
            return
        event = AgentLoopEvent(
            event_type=event_type,
            run_id=config.run_id,
            agent_id=config.agent_id,
            turn_index=turn_index,
            payload=payload,
            snapshot_input=snapshot_input,
            message=message,
            tool_call=tool_call,
            tool_result=tool_result,
        )
        await _maybe_await(config.on_event(event))

    async def _collect_assistant(
        self,
        provider: ModelProvider,
        snapshot: TurnSnapshotInput,
    ) -> ModelMessage:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        streamed_calls: list[ProviderToolCall] = []
        final_turn: ProviderFinalTurn | None = None

        stream = provider.stream(snapshot.messages, snapshot.tools, snapshot.options)
        if not hasattr(stream, "__aiter__"):
            raise TypeError("ModelProvider.stream must return an async iterator")
        async for event in stream:
            if not isinstance(event, ProviderStreamEvent):
                raise TypeError("provider stream yielded a non-ProviderStreamEvent value")
            if final_turn is not None:
                raise ValueError("provider stream yielded events after the final turn")
            if event.event_type == "text_delta":
                text_parts.append(event.delta)
            elif event.event_type == "reasoning_delta":
                reasoning_parts.append(event.delta)
            elif event.event_type == "tool_call":
                assert event.tool_call is not None
                streamed_calls.append(event.tool_call)
            else:
                assert event.final_turn is not None
                final_turn = event.final_turn

        if final_turn is None:
            raise RuntimeError("provider stream ended without a final turn")

        text = final_turn.text or "".join(text_parts)
        calls = final_turn.tool_calls or tuple(streamed_calls)
        metadata = thaw_plain(final_turn.metadata)
        if final_turn.finish_reason is not None:
            metadata["finish_reason"] = final_turn.finish_reason
        if final_turn.usage:
            metadata["usage"] = thaw_plain(final_turn.usage)
        if reasoning_parts:
            metadata["reasoning"] = "".join(reasoning_parts)
        return ModelMessage(
            role="assistant",
            content=text,
            tool_calls=calls,
            metadata=metadata,
        )

    async def _execute_calls(
        self,
        calls: Sequence[ProviderToolCall],
        tools: Sequence[ToolDefinition],
        context: ToolExecutionContext,
    ) -> tuple[ToolResult, ...]:
        registry = {tool.name: tool for tool in tools}
        duplicate_indexes: set[int] = set()
        seen_call_ids: set[str] = set()
        for index, call in enumerate(calls):
            if call.call_id in seen_call_ids:
                duplicate_indexes.add(index)
            else:
                seen_call_ids.add(call.call_id)

        pending = [
            self._execute_one(
                call,
                registry,
                context,
                duplicate=index in duplicate_indexes,
            )
            for index, call in enumerate(calls)
        ]
        results = await asyncio.gather(*pending)
        return tuple(results)

    async def _execute_one(
        self,
        provider_call: ProviderToolCall,
        registry: Mapping[str, ToolDefinition],
        context: ToolExecutionContext,
        *,
        duplicate: bool,
    ) -> ToolResult:
        if duplicate:
            return _error_result(
                provider_call,
                "duplicate_call_id",
                f"duplicate tool call id: {provider_call.call_id}",
            )
        tool = registry.get(provider_call.name)
        if tool is None:
            return _error_result(
                provider_call,
                "unknown_tool",
                f"unknown tool: {provider_call.name}",
            )
        if not isinstance(provider_call.arguments, Mapping):
            return _error_result(
                provider_call,
                "invalid_arguments",
                "tool arguments must be a JSON object",
            )

        try:
            runtime_call = ToolCall(
                call_id=provider_call.call_id,
                name=provider_call.name,
                arguments=provider_call.arguments,
            )
            _validate_arguments(tool.input_schema, runtime_call.arguments)
        except (TypeError, ValueError) as exc:
            return _error_result(
                provider_call,
                "invalid_arguments",
                str(exc),
            )

        try:
            result = await tool.handler(runtime_call, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _error_result(
                provider_call,
                "handler_error",
                f"tool handler error: {exc}",
                error_type=type(exc).__name__,
            )
        if not isinstance(result, ToolResult):
            return _error_result(
                provider_call,
                "invalid_tool_result",
                "tool handler must return ToolResult",
            )
        if result.call_id != provider_call.call_id:
            return _error_result(
                provider_call,
                "invalid_tool_result",
                "tool result call_id does not match the request",
            )
        return result


def _freeze_messages(messages: Sequence[ModelMessage]) -> tuple[ModelMessage, ...]:
    frozen = tuple(messages)
    if not all(isinstance(message, ModelMessage) for message in frozen):
        raise TypeError("messages must contain only ModelMessage values")
    return frozen


def _freeze_tools(tools: Sequence[ToolDefinition]) -> tuple[ToolDefinition, ...]:
    frozen = tuple(tools)
    if not all(isinstance(tool, ToolDefinition) for tool in frozen):
        raise TypeError("tools must contain only ToolDefinition values")
    names = [tool.name for tool in frozen]
    if len(names) != len(set(names)):
        raise ValueError("tool names must be unique")
    return frozen


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _callback_is_true(
    callback: StopCallback | None,
    snapshot: TurnSnapshotInput,
) -> bool:
    if callback is None:
        return False
    return bool(await _maybe_await(callback(snapshot)))


def _tool_message(call: ProviderToolCall, result: ToolResult) -> ModelMessage:
    result_plain = result.to_plain()
    metadata: dict[str, Any] = {"tool_result": result_plain}
    error_code = result.details.get("error_code")
    if error_code is not None:
        metadata["error_code"] = error_code
    return ModelMessage(
        role="tool",
        content=result.content,
        tool_call_id=call.call_id,
        name=call.name,
        is_error=result.is_error,
        metadata=metadata,
    )


def _error_result(
    call: ProviderToolCall,
    error_code: str,
    content: str,
    **details: Any,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        content=content,
        details={
            "error_code": error_code,
            "tool_name": call.name,
            **details,
        },
        is_error=True,
    )


def _validate_arguments(
    schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> None:
    _validate_schema_value(schema, arguments, path="arguments")


def _validate_schema_value(schema: Mapping[str, Any], value: Any, *, path: str) -> None:
    declared = schema.get("type")
    if declared is None and path == "arguments":
        declared = "object"

    if declared == "object":
        if not isinstance(value, Mapping):
            raise ValueError(f"{path} expected object, got {type(value).__name__}")
        required = schema.get("required", ())
        if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
            raise ValueError(f"{path} schema required must be an array")
        for key in required:
            if key not in value:
                raise ValueError(f"missing required argument: {key!r}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"{path} schema properties must be an object")
        for key, child_schema in properties.items():
            if key not in value:
                continue
            if not isinstance(child_schema, Mapping):
                raise ValueError(f"{path}.{key} schema must be an object")
            _validate_schema_value(child_schema, value[key], path=f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ValueError(f"unexpected argument: {sorted(extras)[0]!r}")
    elif declared == "array":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{path} expected array, got {type(value).__name__}")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema_value(item_schema, item, path=f"{path}[{index}]")
    elif declared == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} expected string, got {type(value).__name__}")
    elif declared == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} expected integer, got {type(value).__name__}")
    elif declared == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} expected number, got {type(value).__name__}")
    elif declared == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} expected boolean, got {type(value).__name__}")
    elif declared == "null":
        if value is not None:
            raise ValueError(f"{path} expected null, got {type(value).__name__}")
    elif declared is not None:
        raise ValueError(f"unsupported schema type: {declared!r}")

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ValueError(f"{path} must be one of {list(enum)!r}")


__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "AgentLoopEvent",
    "AgentLoopResult",
    "AgentLoopStatus",
    "EventCallback",
    "PrepareTurnCallback",
    "StopCallback",
    "TurnSnapshotInput",
]
