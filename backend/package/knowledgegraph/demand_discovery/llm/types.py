"""LLM-facing contracts: provider context, assistant message, provider events.

These types sit at the provider boundary. ``LLMContext`` is what the harness
hands to a provider; ``AssistantMessage`` is the normalized final message a
provider returns; ``ProviderEvent`` is the normalized streaming event a
provider emits while producing that message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledgegraph.demand_discovery.harness.types import (
    AssistantContentBlock,
    ToolCall,
)


@dataclass
class LLMContext:
    """The conversation context handed to a provider for one request.

    ``messages`` are internal :class:`AgentMessage`-like objects. The provider
    adapter is responsible for converting them to the wire format; the fake
    provider only inspects ``len(messages)``.
    """

    messages: list[Any] = field(default_factory=list)
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssistantMessage:
    """A normalized final assistant message returned by a provider.

    ``content`` is a list of :class:`AssistantContentBlock`. Convenience
    accessors ``text()`` and ``tool_calls()`` derive the flat text and the
    requested tool calls from the blocks.
    """

    content: list[AssistantContentBlock] = field(default_factory=list)
    is_error: bool = False
    error_message: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return "".join(
            block.text for block in self.content if block.type == "text"
        )

    def tool_calls(self) -> list[ToolCall]:
        return [
            ToolCall(id=block.id, name=block.name, arguments=dict(block.arguments))
            for block in self.content
            if block.type == "tool_call"
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": [block.to_dict() for block in self.content],
            "is_error": self.is_error,
            "error_message": self.error_message,
            "usage": dict(self.usage),
        }


@dataclass
class ProviderEvent:
    """A normalized streaming event emitted by a provider.

    ``type`` is one of ``start``, ``text_delta``, ``thinking_delta``,
    ``toolcall_delta``, ``done``, ``error``.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "payload": dict(self.payload)}
