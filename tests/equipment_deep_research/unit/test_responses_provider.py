from __future__ import annotations

import asyncio
from http.client import RemoteDisconnected
import json

import equipment_deep_research.providers.responses as responses_module
import pytest
from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.responses import ProviderRetryableError, ResponsesProvider, assistant_from_events, build_request_payload, parse_sse_event
from equipment_deep_research.tools.definitions import ToolCall, ToolDefinition, ToolExecutionContext, ToolResult


async def _handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
    return ToolResult(call.call_id, "ok")


SEARCH_TOOL = ToolDefinition("search_sources", "Search public sources", {"type": "object"}, _handler)


class _TerminalSseResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        yield b'data: {"type":"response.output_text.delta","delta":"ok"}\n'
        yield b'data: {"type":"response.completed","response":{"status":"completed"}}\n'
        raise AssertionError("provider must stop reading after the terminal SSE event")


def test_responses_provider_stops_at_terminal_event_without_waiting_for_eof(monkeypatch) -> None:
    monkeypatch.setattr(responses_module, "urlopen", lambda *_args, **_kwargs: _TerminalSseResponse())
    provider = ResponsesProvider(
        model="gpt-5.5",
        base_url="https://gateway.example/v1/responses",
        api_key="test-key",
    )

    lines = provider._post({"model": "gpt-5.5", "input": [], "stream": True})

    assert len(lines) == 2
    assert "response.completed" in lines[-1]


@pytest.mark.parametrize("error", [TimeoutError("read timed out"), RemoteDisconnected("closed")])
def test_responses_provider_classifies_transient_disconnect_as_retryable(monkeypatch, error) -> None:
    monkeypatch.setattr(
        responses_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    provider = ResponsesProvider(
        model="gpt-5.5",
        base_url="https://gateway.example/v1/responses",
        api_key="test-key",
    )

    with pytest.raises(ProviderRetryableError):
        provider._post({"model": "gpt-5.5", "input": [], "stream": True})


def test_responses_provider_retries_transient_network_failures(monkeypatch) -> None:
    provider = ResponsesProvider(
        model="gpt-5.5",
        base_url="https://gateway.example/v1/responses",
        api_key="test-key",
    )
    attempts = 0

    def post(_payload):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderRetryableError("temporary failure")
        return ['data: {"type":"response.completed","response":{"status":"completed"}}\n']

    monkeypatch.setattr(provider, "_post", post)
    monkeypatch.setattr(responses_module.asyncio, "sleep", lambda _seconds: _completed_sleep())

    async def collect():
        return [event async for event in provider.stream([], [], {})]

    events = asyncio.run(collect())

    assert attempts == 3
    assert events[-1].event_type == "final"


def test_responses_provider_honors_single_attempt_budget(monkeypatch) -> None:
    provider = ResponsesProvider(
        model="gpt-5.5",
        base_url="https://gateway.example/v1/responses",
        api_key="test-key",
    )
    attempts = 0

    def post(_payload):
        nonlocal attempts
        attempts += 1
        raise ProviderRetryableError("temporary failure")

    monkeypatch.setattr(provider, "_post", post)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [], [], {"_provider_retry_attempts": 1}
            )
        ]

    with pytest.raises(ProviderRetryableError):
        asyncio.run(collect())

    assert attempts == 1


async def _completed_sleep() -> None:
    return None


def test_responses_payload_uses_gpt55_and_declared_tools() -> None:
    payload = build_request_payload(
        model="gpt-5.5", messages=[ModelMessage("user", "研究主题")], tools=[SEARCH_TOOL],
        options={"reasoning_effort": "high", "max_output_tokens": 12000},
    )
    assert payload["model"] == "gpt-5.5"
    assert payload["tools"][0]["name"] == "search_sources"
    assert payload["reasoning"]["effort"] == "high"


def test_responses_payload_thaws_nested_frozen_tool_schema_for_json() -> None:
    tool = ToolDefinition(
        "nested",
        "Nested schema",
        {"type": "object", "properties": {"query": {"type": "string"}}},
        _handler,
    )
    payload = build_request_payload(
        model="gpt-5.5",
        messages=[ModelMessage("user", {"topic": "低空无人机"})],
        tools=[tool],
        options={},
    )
    json.dumps(payload)
    assert payload["tools"][0]["parameters"]["properties"]["query"] == {"type": "string"}


def test_responses_payload_enables_hosted_web_search_and_source_export() -> None:
    payload = build_request_payload(
        model="gpt-5.5",
        messages=[ModelMessage("user", "研究主题")],
        tools=[],
        options={
            "web_search": {"search_context_size": "high", "external_web_access": True},
            "include_web_sources": True,
            "require_web_search": True,
        },
    )
    assert payload["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "high",
            "external_web_access": True,
        }
    ]
    assert payload["include"] == ["web_search_call.action.sources"]
    assert payload["tool_choice"] == {"type": "web_search"}


def test_responses_payload_can_omit_search_context_size(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_SEARCH_CONTEXT_SIZE_MODE", "omit")
    payload = build_request_payload(
        model="kimi-k3",
        messages=[ModelMessage("user", "研究主题")],
        tools=[],
        options={"web_search": {"search_context_size": "low"}},
    )
    assert payload["tools"] == [{"type": "web_search"}]


def test_responses_payload_enforces_compact_output_schema() -> None:
    payload = build_request_payload(
        model="gpt-5.5",
        messages=[ModelMessage("user", "研究主题")],
        tools=[],
        options={
            "output_schema": {
                "summary": "string",
                "sources": [{"title": "string", "url": "https URL"}],
            }
        },
    )

    output_format = payload["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False
    assert output_format["schema"]["properties"]["sources"]["items"][
        "required"
    ] == ["title", "url"]


def test_output_text_done_does_not_duplicate_streamed_deltas() -> None:
    turn = assistant_from_events(
        [
            ("response.output_text.delta", {"delta": '{"ok":'}),
            ("response.output_text.delta", {"delta": "true}"}),
            ("response.output_text.done", {"text": '{"ok":true}'}),
            ("response.completed", {"response": {"status": "completed"}}),
        ]
    )

    assert turn.text == '{"ok":true}'


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


def test_sse_parser_exports_web_queries_and_deduplicated_sources() -> None:
    events = [
        (
            "response.completed",
            {
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "web_search_call",
                            "action": {
                                "type": "search",
                                "query": "低空无人机 探测",
                                "sources": [
                                    {"url": "https://example.org/a", "title": "Source A"}
                                ],
                            },
                        },
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "annotations": [
                                        {"type": "url_citation", "url": "https://example.org/a", "title": "Source A"},
                                        {"type": "url_citation", "url": "https://example.org/b", "title": "Source B"},
                                    ],
                                }
                            ],
                        },
                    ],
                }
            },
        )
    ]
    turn = assistant_from_events(events)
    assert list(turn.metadata["search_queries"]) == ["低空无人机 探测"]
    assert [dict(item) for item in turn.metadata["web_sources"]] == [
        {"url": "https://example.org/a", "title": "Source A", "snippet": ""},
        {"url": "https://example.org/b", "title": "Source B", "snippet": ""},
    ]
