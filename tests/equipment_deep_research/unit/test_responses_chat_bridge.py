from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_bridge():
    path = Path(__file__).parents[3] / "scripts" / "responses_chat_bridge.py"
    spec = importlib.util.spec_from_file_location("responses_chat_bridge_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_request_payload_reserves_reasoning_tokens(monkeypatch):
    bridge = _load_bridge()
    monkeypatch.setattr(bridge, "TOKEN_RESERVE", 8192)
    monkeypatch.setattr(bridge, "MAX_UPSTREAM_TOKENS", 24000)
    payload = bridge._request_payload({"model": "x", "input": [], "max_output_tokens": 12000})
    assert payload["max_tokens"] == 20192


def test_length_retry_rebuilds_json_request_with_larger_budget(monkeypatch):
    bridge = _load_bridge()
    monkeypatch.setattr(bridge, "TOKEN_RESERVE", 8192)
    monkeypatch.setattr(bridge, "MAX_UPSTREAM_TOKENS", 24000)
    seen: list[dict] = []

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append(json.loads(request.data.decode()))
        if len(seen) == 1:
            return _Response({"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]})
        return _Response({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)
    result = bridge._post_upstream({"model": "x", "messages": [], "max_tokens": 12000})
    assert result["choices"][0]["finish_reason"] == "stop"
    assert [item["max_tokens"] for item in seen] == [12000, 24000]


def test_messages_preserve_responses_tool_outputs_for_chat_upstream():
    bridge = _load_bridge()
    messages = bridge._messages(
        [
            {"type": "function_call", "call_id": "call-1", "name": "search_sources", "arguments": {"query": "无人机"}},
            {"type": "function_call_output", "call_id": "call-1", "output": "结果"},
        ]
    )
    assert messages[0]["tool_calls"][0]["function"]["name"] == "search_sources"
    assert messages[1] == {"role": "tool", "tool_call_id": "call-1", "content": "结果"}


def test_chat_tool_call_is_emitted_as_responses_function_call():
    bridge = _load_bridge()
    events = bridge._responses_events(
        {
            "id": "resp-tools",
            "model": "x",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "search_sources", "arguments": '{"query":"无人机"}'},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
        }
    )
    assert any(event["type"] == "response.function_call_arguments.done" for event in events)
    done = next(event for event in events if event["type"] == "response.output_item.done")
    assert done["item"]["name"] == "search_sources"
