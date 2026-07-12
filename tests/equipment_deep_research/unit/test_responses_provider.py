from __future__ import annotations

from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.responses import assistant_from_events, build_request_payload, parse_sse_event
from equipment_deep_research.tools.definitions import ToolCall, ToolDefinition, ToolExecutionContext, ToolResult


async def _handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
    return ToolResult(call.call_id, "ok")


SEARCH_TOOL = ToolDefinition("search_sources", "Search public sources", {"type": "object"}, _handler)


def test_responses_payload_uses_gpt55_and_declared_tools() -> None:
    payload = build_request_payload(
        model="gpt-5.5", messages=[ModelMessage("user", "研究主题")], tools=[SEARCH_TOOL],
        options={"reasoning_effort": "high", "max_output_tokens": 12000},
    )
    assert payload["model"] == "gpt-5.5"
    assert payload["tools"][0]["name"] == "search_sources"
    assert payload["reasoning"]["effort"] == "high"


def test_sse_parser_reconstructs_text_and_tool_arguments() -> None:
    lines = [
        'data: {"type":"response.output_text.delta","delta":"检索完成。"}',
        'data: {"type":"response.function_call_arguments.delta","item_id":"call-1","name":"search_sources","delta":"{\\"query\\":\\"低空无人机"}',
        'data: {"type":"response.function_call_arguments.delta","item_id":"call-1","delta":" 威胁 趋势\\"}"}',
        'data: {"type":"response.completed","response":{"status":"completed","usage":{"output_tokens":12}}}',
    ]
    events = [item for line in lines if (item := parse_sse_event(line))]
    turn = assistant_from_events(events)
    assert turn.text == "检索完成。"
    assert turn.tool_calls and turn.tool_calls[0].name == "search_sources"
    assert turn.tool_calls[0].arguments == {"query": "低空无人机 威胁 趋势"}
    assert turn.usage["output_tokens"] == 12
