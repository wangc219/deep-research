"""Offline fake provider for deterministic harness tests.

``FakeProvider`` returns queued :class:`FakeResponse` items in order, each of
which becomes a streamed :class:`AssistantMessage`. A response can be static
text + tool calls, or a callable factory inspecting the context and call state.
This lets tests drive the agent loop and harness without any network or API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Callable

from knowledgegraph.demand_discovery.harness.event_stream import AsyncEventStream
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock
from knowledgegraph.demand_discovery.llm.types import AssistantMessage, LLMContext


ResponseFactory = Callable[[LLMContext, dict], AssistantMessage]


@dataclass
class FakeResponse:
    """One queued provider response.

    Provide either ``text`` (with optional ``tool_calls``) for a static
    response, or ``factory`` for a dynamic one. ``tool_calls`` is a list of
    ``{"id", "name", "arguments"}`` dicts.
    """

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    factory: ResponseFactory | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def build(self, context: LLMContext, state: dict) -> AssistantMessage:
        if self.factory is not None:
            message = self.factory(context, state)
            if not message.usage:
                message.usage = _estimate_usage(context, message)
            return message
        blocks: list[AssistantContentBlock] = []
        if self.text:
            blocks.append(AssistantContentBlock(type="text", text=self.text))
        for call in self.tool_calls:
            blocks.append(
                AssistantContentBlock(
                    type="tool_call",
                    id=call.get("id", ""),
                    name=call.get("name", ""),
                    arguments=dict(call.get("arguments", {})),
                )
            )
        message = AssistantMessage(content=blocks, usage=dict(self.usage))
        if not message.usage:
            message.usage = _estimate_usage(context, message)
        return message


class FakeProvider:
    """A queue-driven provider compatible with the agent loop's provider seam."""

    def __init__(self) -> None:
        self._responses: list[FakeResponse] = []
        self._call_count = 0

    def set_responses(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)

    def append_responses(self, responses: list[FakeResponse]) -> None:
        self._responses.extend(responses)

    def pending_count(self) -> int:
        return len(self._responses)

    def stream(
        self,
        context: LLMContext,
        tools: list[Any],
        options: dict[str, Any],
    ) -> AsyncEventStream:
        """Produce the next queued response as a streamed assistant message."""

        stream = AsyncEventStream()
        self._call_count += 1
        state = {"call_count": self._call_count}

        if not self._responses:
            message = AssistantMessage(
                content=[],
                is_error=True,
                error_message="fake provider queue exhausted",
            )
            stream.push(_event("start"))
            stream.push(_event("error", {"message": message.error_message}))
            stream.end(message)
            return stream

        response = self._responses.pop(0)
        stream.push(_event("start"))
        try:
            message = response.build(context, state)
        except Exception as exc:  # convert raised factory error to provider error
            stream.error(str(exc))
            return stream

        for block in message.content:
            if block.type == "text" and block.text:
                stream.push(_event("text_delta", {"text": block.text}))
            elif block.type == "tool_call":
                stream.push(
                    _event(
                        "toolcall_delta",
                        {
                            "id": block.id,
                            "name": block.name,
                            "arguments": dict(block.arguments),
                        },
                    )
                )
        stream.push(_event("done"))
        stream.end(message)
        return stream


def _event(event_type: str, payload: dict[str, Any] | None = None):
    from knowledgegraph.demand_discovery.llm.types import ProviderEvent

    return ProviderEvent(type=event_type, payload=payload or {})


def _estimate_usage(context: LLMContext, message: AssistantMessage) -> dict[str, Any]:
    input_chars = sum(_message_chars(item) for item in context.messages)
    output_chars = sum(_block_chars(block) for block in message.content)
    return {
        "input_tokens": max(math.ceil(input_chars / 4), 1),
        "output_tokens": max(math.ceil(output_chars / 4), 1),
        "input_token_details": {"cached_tokens": 0},
    }


def _message_chars(message: Any) -> int:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return sum(_block_chars(block) for block in content)
    return len(str(content))


def _block_chars(block: AssistantContentBlock) -> int:
    if block.type == "text":
        return len(block.text)
    if block.type == "tool_call":
        return len(block.name) + len(json.dumps(block.arguments, sort_keys=True))
    return len(block.text)
