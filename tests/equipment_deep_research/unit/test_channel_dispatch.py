from __future__ import annotations

import asyncio
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor

import pytest

from equipment_deep_research.deep_runtime.channel import (
    InboundMessage,
    OutboundMessage,
    dispatch_channel_call,
    dispatch_channel_call_async,
)


def test_dispatch_preserves_private_dependencies_and_complete_result():
    dependency = object()
    observed = []
    request_scope = ContextVar("channel_test_scope", default="missing")
    token = request_scope.set("trusted-scope")
    message = InboundMessage(
        "web", "user", "session", "First paragraph\n\n- Item one\n- Item two",
        message_id="job-1", session_key_override="server:session:branch",
        payload={"session_id": "forged", "dependency": "forged", "authoring_requested": True},
    )
    result = {"items": [f"item-{index}" for index in range(40)],
              "provider_metadata": {"api_key": "private"}, "answer": "answer\n\nparagraph"}

    def execute(payload):
        assert payload["dependency"] is dependency
        assert payload["session_id"] == "trusted-session"
        assert payload["authoring_requested"] is False
        assert payload["question"] == message.content
        assert payload["session_key"] == "server:session:branch"
        assert payload["inbound_message"] is message
        assert "message_bus" not in payload
        assert request_scope.get() == "trusted-scope"
        # Existing synchronous callbacks may own their own asyncio loop.
        return asyncio.run(async_result())

    async def async_result():
        return result

    try:
        actual = dispatch_channel_call(
            execute, message, host_payload={"dependency": dependency,
                "session_id": "trusted-session", "authoring_requested": False},
            observer=observed.append,
        )
    finally:
        request_scope.reset(token)
    assert actual is result
    assert len(actual["items"]) == 40
    assert len(observed) == 1
    assert len(observed[0].payload["items"]) == 16
    assert observed[0].payload["provider_metadata"] == "<redacted>"
    assert observed[0].reply_to == "job-1"
    assert observed[0].metadata["session_key"] == "server:session:branch"


def test_dispatch_supports_async_callbacks_and_observer_failures():
    async def execute(payload):
        return {"answer": payload["question"]}

    async def observer(_message):
        raise RuntimeError("optional observer unavailable")

    result = asyncio.run(dispatch_channel_call_async(
        execute, InboundMessage("cli", "user", "session", "question"),
        host_payload={}, observer=observer,
    ))
    assert result == {"answer": "question"}


def test_dispatch_propagates_host_failure_without_publishing_success():
    class OwnershipLost(RuntimeError):
        pass

    observed = []

    def execute(_payload):
        raise OwnershipLost("claim lost")

    with pytest.raises(OwnershipLost, match="claim lost"):
        dispatch_channel_call(execute, InboundMessage("web", "u", "s", "question"),
                              host_payload={}, observer=observed.append)
    assert observed == []


def test_dispatch_isolates_concurrent_sessions_and_event_loops():
    def request(index):
        message = InboundMessage("web", "u", f"session-{index}", f"question-{index}")
        return dispatch_channel_call(
            lambda payload: {"session": payload["chat_id"], "answer": payload["question"]},
            message, host_payload={},
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(request, range(12)))
    assert results == [{"session": f"session-{index}", "answer": f"question-{index}"} for index in range(12)]


def test_message_content_preserves_layout_and_redacts_secrets():
    content = "Paragraph\n\n- First\n- Second\napi_key=private"
    for message in (InboundMessage("cli", "u", "s", content), OutboundMessage("cli", "s", content)):
        assert "Paragraph\n\n- First\n- Second" in message.content
        assert "api_key=private" not in message.content


def test_async_dispatch_cancellation_never_publishes_success():
    observed = []

    async def execute(_payload):
        raise asyncio.CancelledError()

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await dispatch_channel_call_async(
                execute, InboundMessage("web", "u", "s", "question"),
                host_payload={}, observer=observed.append,
            )
        assert observed == []
        result = await dispatch_channel_call_async(
            lambda _payload: {"answer": "next session"}, InboundMessage("cli", "u", "next", "question"),
            host_payload={}, observer=observed.append,
        )
        assert result["answer"] == "next session"
        assert len(observed) == 1

    asyncio.run(scenario())
