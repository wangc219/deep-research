from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from functools import wraps
import json
from typing import Any

import pytest

from equipment_deep_research.harness.agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    AgentLoopEvent,
    TurnSnapshotInput,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
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


def async_test(function: Any) -> Any:
    @wraps(function)
    def run(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(function(*args, **kwargs))

    return run


def user(text: str) -> ModelMessage:
    return ModelMessage(role="user", content=text)


def call(call_id: str, name: str, arguments: Any | None = None) -> ProviderToolCall:
    return ProviderToolCall(
        call_id=call_id,
        name=name,
        arguments={} if arguments is None else arguments,
    )


def assistant_text(text: str) -> list[ProviderStreamEvent]:
    return [
        ProviderStreamEvent.text_delta(text),
        ProviderStreamEvent.final(ProviderFinalTurn()),
    ]


def assistant_with_calls(
    calls: Sequence[ProviderToolCall],
) -> list[ProviderStreamEvent]:
    return [
        ProviderStreamEvent.final(ProviderFinalTurn(tool_calls=tuple(calls)))
    ]


class ScriptedProvider:
    def __init__(self, turns: Sequence[Sequence[ProviderStreamEvent]]) -> None:
        self._turns = list(turns)
        self.inputs: list[
            tuple[
                Sequence[ModelMessage],
                Sequence[ToolDefinition],
                dict[str, Any],
            ]
        ] = []

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: dict[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        self.inputs.append((messages, tools, options))
        for event in self._turns.pop(0):
            await asyncio.sleep(0)
            yield event


def config(**overrides: Any) -> AgentLoopConfig:
    values = {
        "run_id": "run-1",
        "agent_id": "agent-a",
        "max_turns": 8,
    }
    values.update(overrides)
    return AgentLoopConfig(**values)


def tool(
    name: str,
    handler: Any,
    *,
    schema: dict[str, Any] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} test tool",
        input_schema=schema or {"type": "object"},
        handler=handler,
    )


def test_provider_contracts_are_strict_json_values_without_shared_containers() -> None:
    arguments = {"nested": {"items": ["original"]}}
    metadata = {"source": {"ids": ["r1"]}}
    provider_call = ProviderToolCall("c1", "echo", arguments)
    message = ModelMessage(
        role="assistant",
        content="done",
        tool_calls=[provider_call],
        metadata=metadata,
    )
    event = ProviderStreamEvent.final(
        ProviderFinalTurn(text="done", tool_calls=[provider_call], metadata=metadata)
    )

    arguments["nested"]["items"].append("mutated")
    metadata["source"]["ids"].append("mutated")

    assert provider_call.arguments["nested"]["items"] == ("original",)
    assert message.metadata["source"]["ids"] == ("r1",)
    json.dumps(event.to_plain(), allow_nan=False)

    with pytest.raises(TypeError, match="call_id"):
        ProviderToolCall(1, "echo", {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="text"):
        ProviderFinalTurn(text=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="delta"):
        ProviderStreamEvent.text_delta(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="metadata"):
        ModelMessage(role="user", content="x", metadata=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="options"):
        AgentLoopConfig(options=[])  # type: ignore[arg-type]


@async_test
async def test_loop_executes_parallel_calls_but_appends_results_in_call_order() -> None:
    completion_order: list[str] = []

    async def slow(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        await asyncio.sleep(0.03)
        completion_order.append(call.call_id)
        return ToolResult(call.call_id, "slow result")

    async def fast(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        await asyncio.sleep(0)
        completion_order.append(call.call_id)
        return ToolResult(call.call_id, "fast result")

    provider = ScriptedProvider(
        [
            assistant_with_calls([call("c1", "slow"), call("c2", "fast")]),
            assistant_text("done"),
        ]
    )

    result = await AgentLoop().run(
        [user("start")],
        provider,
        [tool("slow", slow), tool("fast", fast)],
        config(),
    )

    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert completion_order == ["c2", "c1"]
    assert [message.tool_call_id for message in tool_messages] == ["c1", "c2"]
    assert result.turn_count == 2
    assert result.status == "completed"


@async_test
async def test_assistant_without_tool_calls_terminates_after_collecting_stream_text() -> None:
    provider = ScriptedProvider([assistant_text("hello world")])

    result = await AgentLoop().run([user("start")], provider, [], config())

    assert result.status == "completed"
    assert result.turn_count == 1
    assert result.messages[-1].role == "assistant"
    assert result.messages[-1].content == "hello world"


@async_test
async def test_unknown_tool_becomes_structured_error_result() -> None:
    provider = ScriptedProvider(
        [assistant_with_calls([call("c1", "missing")]), assistant_text("done")]
    )

    result = await AgentLoop().run([user("start")], provider, [], config())

    message = next(item for item in result.messages if item.role == "tool")
    assert message.tool_call_id == "c1"
    assert message.is_error is True
    assert message.metadata["error_code"] == "unknown_tool"


@async_test
async def test_handler_error_does_not_cancel_sibling_call() -> None:
    sibling_completed = asyncio.Event()

    async def fail(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del call, context
        await asyncio.sleep(0)
        raise RuntimeError("handler exploded")

    async def sibling(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        await asyncio.sleep(0.01)
        sibling_completed.set()
        return ToolResult(call.call_id, "ok")

    provider = ScriptedProvider(
        [
            assistant_with_calls([call("c1", "fail"), call("c2", "sibling")]),
            assistant_text("done"),
        ]
    )

    result = await AgentLoop().run(
        [user("start")],
        provider,
        [tool("fail", fail), tool("sibling", sibling)],
        config(),
    )

    messages = [item for item in result.messages if item.role == "tool"]
    assert sibling_completed.is_set()
    assert messages[0].is_error is True
    assert messages[0].metadata["error_code"] == "handler_error"
    assert messages[1].content == "ok"


@async_test
async def test_duplicate_call_id_and_invalid_arguments_are_explicit_errors() -> None:
    executed: list[str] = []

    async def echo(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        executed.append(call.call_id)
        return ToolResult(call.call_id, str(call.arguments["value"]))

    echo_tool = tool(
        "echo",
        echo,
        schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
    )
    provider = ScriptedProvider(
        [
            assistant_with_calls(
                [
                    call("c1", "echo", {"value": "first"}),
                    call("c1", "echo", {"value": "duplicate"}),
                    call("c3", "echo", {"value": 3}),
                    call("c4", "echo", ["not", "an", "object"]),
                ]
            ),
            assistant_text("done"),
        ]
    )

    result = await AgentLoop().run([user("start")], provider, [echo_tool], config())

    messages = [item for item in result.messages if item.role == "tool"]
    assert executed == ["c1"]
    assert [item.metadata.get("error_code") for item in messages] == [
        None,
        "duplicate_call_id",
        "invalid_arguments",
        "invalid_arguments",
    ]


@async_test
async def test_provider_stream_error_returns_failed_result_and_event() -> None:
    class FailingProvider:
        async def stream(
            self,
            messages: Sequence[ModelMessage],
            tools: Sequence[ToolDefinition],
            options: dict[str, Any],
        ) -> AsyncIterator[ProviderStreamEvent]:
            del messages, tools, options
            yield ProviderStreamEvent.text_delta("partial")
            raise RuntimeError("provider unavailable")

    events: list[AgentLoopEvent] = []
    result = await AgentLoop().run(
        [user("start")],
        FailingProvider(),
        [],
        config(on_event=events.append),
    )

    assert result.status == "failed"
    assert result.error == "provider unavailable"
    assert [event.event_type for event in events] == ["turn_started", "loop_failed"]


@async_test
async def test_max_turns_has_explicit_status() -> None:
    async def echo(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        return ToolResult(call.call_id, "ok")

    provider = ScriptedProvider([assistant_with_calls([call("c1", "echo")])])

    result = await AgentLoop().run(
        [user("start")], provider, [tool("echo", echo)], config(max_turns=1)
    )

    assert result.status == "max_turns"
    assert result.turn_count == 1


@pytest.mark.parametrize(
    ("callback_name", "expected_status"),
    [("should_stop", "stopped"), ("budget_exhausted", "budget_exhausted")],
)
@async_test
async def test_external_stop_callbacks_have_explicit_status(
    callback_name: str, expected_status: str
) -> None:
    provider = ScriptedProvider([assistant_text("must not run")])

    async def stop(_: TurnSnapshotInput) -> bool:
        return True

    result = await AgentLoop().run(
        [user("start")],
        provider,
        [],
        config(**{callback_name: stop}),
    )

    assert result.status == expected_status
    assert result.turn_count == 0
    assert provider.inputs == []


@async_test
async def test_each_provider_call_receives_frozen_isolated_inputs() -> None:
    mutable_options = {"nested": {"items": ["original"]}}
    observed: list[tuple[type[Any], type[Any], type[Any]]] = []

    class InspectingProvider(ScriptedProvider):
        async def stream(
            self,
            messages: Sequence[ModelMessage],
            tools: Sequence[ToolDefinition],
            options: dict[str, Any],
        ) -> AsyncIterator[ProviderStreamEvent]:
            observed.append((type(messages), type(tools), type(options)))
            with pytest.raises(AttributeError):
                messages.append(user("mutated"))  # type: ignore[attr-defined]
            with pytest.raises(AttributeError):
                tools.append(None)  # type: ignore[attr-defined]
            with pytest.raises(TypeError):
                options["new"] = True
            with pytest.raises(AttributeError):
                options["nested"]["items"].append("mutated")
            async for event in super().stream(messages, tools, options):
                yield event

    provider = InspectingProvider([assistant_text("done")])
    loop_config = config(options=mutable_options)
    mutable_options["nested"]["items"].append("outside mutation")

    result = await AgentLoop().run([user("start")], provider, [], loop_config)

    assert result.status == "completed"
    assert observed
    assert provider.inputs[0][2]["nested"]["items"] == ("original",)
    assert isinstance(result.messages, tuple)
    assert isinstance(result.turn_snapshots, tuple)


@async_test
async def test_event_order_matches_persistence_contract() -> None:
    async def echo(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        return ToolResult(call.call_id, "ok")

    events: list[AgentLoopEvent] = []
    provider = ScriptedProvider(
        [assistant_with_calls([call("c1", "echo")]), assistant_text("done")]
    )

    result = await AgentLoop().run(
        [user("start")],
        provider,
        [tool("echo", echo)],
        config(on_event=events.append),
    )

    assert [event.event_type for event in events] == [
        "turn_started",
        "assistant_message",
        "tool_result",
        "turn_end",
        "turn_started",
        "assistant_message",
        "turn_end",
        "loop_completed",
    ]
    assert events[0].snapshot_input is result.turn_snapshots[0]
    assert events[1].message is result.messages[1]
    assert events[2].tool_call is result.messages[1].tool_calls[0]
    assert events[2].tool_result is not None
    assert events[2].tool_result.call_id == "c1"
    assert events[2].message is result.messages[2]


@async_test
async def test_cancellation_propagates_after_emitting_cancelled_status() -> None:
    entered = asyncio.Event()

    class BlockingProvider:
        async def stream(
            self,
            messages: Sequence[ModelMessage],
            tools: Sequence[ToolDefinition],
            options: dict[str, Any],
        ) -> AsyncIterator[ProviderStreamEvent]:
            del messages, tools, options
            entered.set()
            await asyncio.Event().wait()
            yield ProviderStreamEvent.final(ProviderFinalTurn())

    events: list[AgentLoopEvent] = []
    task = asyncio.create_task(
        AgentLoop().run(
            [user("start")],
            BlockingProvider(),
            [],
            config(on_event=events.append),
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert events[-1].event_type == "loop_failed"
    assert events[-1].payload["status"] == "cancelled"
