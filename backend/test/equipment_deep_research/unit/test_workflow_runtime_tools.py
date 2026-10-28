from __future__ import annotations

import asyncio

from equipment_deep_research.agents.provider import ResponsesAgentProvider
from equipment_deep_research.contracts.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider


def _tool(handler) -> ToolDefinition:
    return ToolDefinition(
        name="lookup_knowledge",
        description="Look up bounded knowledge",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        handler=handler,
    )


def test_collect_stream_keeps_empty_tools_on_the_legacy_single_turn_path() -> None:
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="unchanged",
                        usage={"input_tokens": 2, "output_tokens": 1},
                        metadata={"request_id": "legacy"},
                    )
                )
            ]
        ]
    )
    host = ResponsesAgentProvider(backend)

    text, metadata = asyncio.run(
        host._collect_stream(
            backend,
            [ModelMessage(role="user", content="answer directly")],
            {},
        )
    )

    assert text == "unchanged"
    assert len(backend.inputs) == 1
    assert backend.inputs[0][1] == ()
    assert metadata["usage"] == {"input_tokens": 2, "output_tokens": 1}
    assert metadata["request_id"] == "legacy"
    assert "tool_loop_turns" not in metadata
    assert "turn_metadata" not in metadata


def test_collect_stream_does_not_execute_tool_when_model_answers_directly() -> None:
    calls: list[str] = []

    async def lookup(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        calls.append(call.call_id)
        return ToolResult(call.call_id, "unexpected")

    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="direct answer",
                        usage={"total_tokens": 7},
                        metadata={"request_id": "direct"},
                        finish_reason="stop",
                    )
                )
            ]
        ]
    )
    host = ResponsesAgentProvider(backend)

    text, metadata = asyncio.run(
        host._collect_stream(
            backend,
            [ModelMessage(role="user", content="use a tool only if needed")],
            {},
            tools=[_tool(lookup)],
        )
    )

    assert text == "direct answer"
    assert calls == []
    assert len(backend.inputs) == 1
    assert [tool.name for tool in backend.inputs[0][1]] == ["lookup_knowledge"]
    assert metadata["usage"] == {"total_tokens": 7}
    assert metadata["tool_loop_turns"] == 1
    assert metadata["finish_reason"] == "stop"


def test_collect_stream_runs_one_tool_round_then_hides_all_tools() -> None:
    observed: list[tuple[dict, dict]] = []

    async def lookup(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        observed.append((call.to_plain(), context.to_plain()))
        return ToolResult(
            call.call_id,
            "bounded enterprise result",
            details={"citation": "kb-1/file-2/chunk-3"},
        )

    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        tool_calls=[
                            ProviderToolCall(
                                "call-1",
                                "lookup_knowledge",
                                {"query": "radar"},
                            )
                        ],
                        usage={
                            "input_tokens": 3,
                            "output_tokens": 1,
                            "total_tokens": 4,
                            "input_tokens_details": {"cached_tokens": 1},
                        },
                        metadata={"request_id": "turn-1", "phase": "lookup"},
                        finish_reason="tool_calls",
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="grounded final answer",
                        usage={
                            "input_tokens": 5,
                            "output_tokens": 2,
                            "total_tokens": 7,
                            "input_tokens_details": {"cached_tokens": 2},
                        },
                        metadata={"request_id": "turn-2", "phase": "answer"},
                        finish_reason="stop",
                    )
                )
            ],
        ]
    )
    host = ResponsesAgentProvider(backend)
    options = {
        "web_search": {"search_context_size": "high"},
        "require_web_search": True,
        "include_web_sources": True,
        "_tool_permissions": {"knowledge_ids": ["kb-1"]},
    }

    text, metadata = asyncio.run(
        host._collect_stream(
            backend,
            [ModelMessage(role="user", content="research radar")],
            options,
            tools=[_tool(lookup)],
            progress={"run_id": "run-7", "agent_id": "equipment-agent"},
        )
    )

    assert text == "grounded final answer"
    assert len(backend.inputs) == 2
    assert [tool.name for tool in backend.inputs[0][1]] == ["lookup_knowledge"]
    assert backend.inputs[1][1] == ()
    assert "require_web_search" not in backend.inputs[0][2]
    assert "tool_choice" not in backend.inputs[0][2]
    assert "_tool_permissions" not in backend.inputs[0][2]
    assert "web_search" in backend.inputs[0][2]
    assert "web_search" not in backend.inputs[1][2]
    assert "include_web_sources" not in backend.inputs[1][2]

    second_turn_messages = backend.inputs[1][0]
    assert [message.role for message in second_turn_messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert second_turn_messages[-1].content == "bounded enterprise result"
    assert second_turn_messages[-1].tool_call_id == "call-1"
    assert second_turn_messages[-1].name == "lookup_knowledge"
    assert observed == [
        (
            {
                "call_id": "call-1",
                "name": "lookup_knowledge",
                "arguments": {"query": "radar"},
            },
            {
                "run_id": "run-7",
                "agent_id": "equipment-agent",
                "permissions": {"knowledge_ids": ["kb-1"]},
            },
        )
    ]
    assert metadata["usage"] == {
        "input_tokens": 8,
        "output_tokens": 3,
        "total_tokens": 11,
        "input_tokens_details": {"cached_tokens": 3},
    }
    assert metadata["request_id"] == "turn-2"
    assert metadata["phase"] == "answer"
    assert metadata["finish_reason"] == "stop"
    assert metadata["tool_loop_turns"] == 2
    assert [turn["request_id"] for turn in metadata["turn_metadata"]] == [
        "turn-1",
        "turn-2",
    ]


def test_collect_stream_does_not_offer_or_execute_tools_for_unsupported_provider() -> None:
    calls: list[str] = []

    async def lookup(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        calls.append(call.call_id)
        return ToolResult(call.call_id, "unexpected")

    class UnsupportedProvider(ScriptedFakeProvider):
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(streaming=True, function_tools=False)

    backend = UnsupportedProvider([[ProviderStreamEvent.final(ProviderFinalTurn(text="fallback answer"))]])
    host = ResponsesAgentProvider(backend)

    text, metadata = asyncio.run(
        host._collect_stream(
            backend,
            [ModelMessage(role="user", content="answer")],
            {},
            tools=[_tool(lookup)],
        )
    )

    assert text == "fallback answer"
    assert calls == []
    assert len(backend.inputs) == 1
    assert backend.inputs[0][1] == ()
    assert "tool_loop_turns" not in metadata


def test_collect_stream_never_executes_a_second_round_tool_request() -> None:
    calls: list[str] = []

    async def lookup(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        del context
        calls.append(call.call_id)
        return ToolResult(call.call_id, "first result")

    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(tool_calls=[ProviderToolCall("call-1", "lookup_knowledge", {"query": "first"})])
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="bounded answer",
                        tool_calls=[ProviderToolCall("call-2", "lookup_knowledge", {"query": "second"})],
                    )
                )
            ],
        ]
    )
    host = ResponsesAgentProvider(backend)

    text, metadata = asyncio.run(
        host._collect_stream(
            backend,
            [ModelMessage(role="user", content="answer")],
            {},
            tools=[_tool(lookup)],
        )
    )

    assert text == "bounded answer"
    assert calls == ["call-1"]
    assert len(backend.inputs) == 2
    assert backend.inputs[1][1] == ()
    assert metadata["tool_loop_turns"] == 2


def test_structured_phase_controls_reasoning_without_progress_subscriber() -> None:
    """没有进度订阅时，S5 阶段仍必须取得可解析正文并保留调用参数。"""
    backend = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(text='{"decisions":[]}'))]])
    backend.provider_type = "chat_completions"
    host = ResponsesAgentProvider(backend)
    options = {"phase": "winning_swarm_dynamic_portfolio_review_fast", "max_output_tokens": 8000}
    text, _ = asyncio.run(host._collect_stream(backend, [], options))
    assert text == '{"decisions":[]}'
    sent = backend.inputs[0][2]
    assert sent["_disable_hidden_reasoning"] is True
    assert sent["phase"] == options["phase"] and sent["max_output_tokens"] == 8000


def test_progress_phase_reaches_provider_usage_and_bounds_source_anchor_reasoning():
    """进度中的阶段既控制正文预算，也必须进入供应商计量，调用者原参数不变。"""
    backend = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(text="来源线索待核验"))]])
    backend.provider_type = "chat_completions"
    host = ResponsesAgentProvider(backend)
    options = {"max_output_tokens": 900, "_provider_timeout_seconds": 20}
    text, _ = asyncio.run(
        host._collect_stream(
            backend,
            [],
            options,
            progress={"phase": "source_anchor_reasoning", "run_id": "phase-test", "agent_id": "anchor"},
        )
    )
    sent = backend.inputs[0][2]
    assert text == "来源线索待核验"
    assert sent["phase"] == "source_anchor_reasoning"
    assert sent["_run_id"] == "phase-test"
    assert sent["_disable_hidden_reasoning"] is True
    assert sent["_provider_timeout_seconds"] == 20
    assert options == {"max_output_tokens": 900, "_provider_timeout_seconds": 20}
