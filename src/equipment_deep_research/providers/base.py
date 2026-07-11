"""Domain-free contracts shared by model providers and the agent loop."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast, runtime_checkable

from equipment_deep_research.domain.proposals import freeze_plain, thaw_plain
from equipment_deep_research.tools.definitions import ToolDefinition


MessageRole = Literal["system", "developer", "user", "assistant", "tool"]
ProviderEventType = Literal[
    "text_delta",
    "reasoning_delta",
    "tool_call",
    "final",
]


@dataclass(frozen=True)
class ProviderToolCall:
    """A provider-produced tool request before runtime validation."""

    call_id: str
    name: str
    arguments: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str):
            raise TypeError("provider tool call_id must be a string")
        if not isinstance(self.name, str):
            raise TypeError("provider tool name must be a string")
        if not self.call_id:
            raise ValueError("provider tool call_id must not be empty")
        if not self.name:
            raise ValueError("provider tool name must not be empty")
        object.__setattr__(self, "arguments", freeze_plain(self.arguments))

    def to_plain(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": thaw_plain(self.arguments),
        }


@dataclass(frozen=True)
class ModelMessage:
    """A provider-facing message with a stable plain-JSON projection."""

    role: MessageRole
    content: Any = ""
    tool_calls: Sequence[ProviderToolCall] = field(default_factory=tuple)
    tool_call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.role, str):
            raise TypeError("message role must be a string")
        if self.role not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {self.role!r}")
        if self.tool_call_id is not None and not isinstance(self.tool_call_id, str):
            raise TypeError("message tool_call_id must be a string")
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("message name must be a string")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("message metadata must be an object")
        calls = tuple(self.tool_calls)
        if not all(isinstance(call, ProviderToolCall) for call in calls):
            raise TypeError("tool_calls must contain only ProviderToolCall values")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        object.__setattr__(self, "content", freeze_plain(self.content))
        object.__setattr__(self, "tool_calls", calls)
        object.__setattr__(
            self,
            "metadata",
            cast(Mapping[str, Any], freeze_plain(self.metadata)),
        )

    def to_plain(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "role": self.role,
            "content": thaw_plain(self.content),
        }
        if self.tool_calls:
            value["tool_calls"] = [call.to_plain() for call in self.tool_calls]
        if self.tool_call_id is not None:
            value["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            value["name"] = self.name
        if self.is_error:
            value["is_error"] = True
        if self.metadata:
            value["metadata"] = thaw_plain(self.metadata)
        return value


@dataclass(frozen=True)
class ProviderFinalTurn:
    """The authoritative final state of one streamed assistant turn."""

    text: str = ""
    tool_calls: Sequence[ProviderToolCall] = field(default_factory=tuple)
    finish_reason: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("provider final turn text must be a string")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise TypeError("provider finish_reason must be a string")
        if not isinstance(self.usage, Mapping):
            raise TypeError("provider usage must be an object")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("provider metadata must be an object")
        calls = tuple(self.tool_calls)
        if not all(isinstance(call, ProviderToolCall) for call in calls):
            raise TypeError("tool_calls must contain only ProviderToolCall values")
        object.__setattr__(self, "tool_calls", calls)
        object.__setattr__(
            self,
            "usage",
            cast(Mapping[str, Any], freeze_plain(self.usage)),
        )
        object.__setattr__(
            self,
            "metadata",
            cast(Mapping[str, Any], freeze_plain(self.metadata)),
        )

    def to_plain(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "text": self.text,
            "tool_calls": [call.to_plain() for call in self.tool_calls],
            "usage": thaw_plain(self.usage),
            "metadata": thaw_plain(self.metadata),
        }
        if self.finish_reason is not None:
            value["finish_reason"] = self.finish_reason
        return value


@dataclass(frozen=True)
class ProviderStreamEvent:
    """One typed item in a provider's real async event stream."""

    event_type: ProviderEventType
    delta: str = ""
    tool_call: ProviderToolCall | None = None
    final_turn: ProviderFinalTurn | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str):
            raise TypeError("provider event_type must be a string")
        if not isinstance(self.delta, str):
            raise TypeError("provider event delta must be a string")
        if self.event_type in {"text_delta", "reasoning_delta"}:
            if self.tool_call is not None or self.final_turn is not None:
                raise ValueError(f"{self.event_type} cannot carry a tool call or final turn")
        elif self.event_type == "tool_call":
            if self.tool_call is None or self.final_turn is not None or self.delta:
                raise ValueError("tool_call events require exactly one tool_call")
        elif self.event_type == "final":
            if self.final_turn is None or self.tool_call is not None or self.delta:
                raise ValueError("final events require exactly one final_turn")
        else:
            raise ValueError(f"unsupported provider event type: {self.event_type!r}")

    @classmethod
    def text_delta(cls, delta: str) -> ProviderStreamEvent:
        return cls("text_delta", delta=delta)

    @classmethod
    def reasoning_delta(cls, delta: str) -> ProviderStreamEvent:
        return cls("reasoning_delta", delta=delta)

    @classmethod
    def tool_call_event(cls, tool_call: ProviderToolCall) -> ProviderStreamEvent:
        return cls("tool_call", tool_call=tool_call)

    @classmethod
    def final(cls, turn: ProviderFinalTurn) -> ProviderStreamEvent:
        return cls("final", final_turn=turn)

    def to_plain(self) -> dict[str, Any]:
        value: dict[str, Any] = {"event_type": self.event_type}
        if self.delta:
            value["delta"] = self.delta
        if self.tool_call is not None:
            value["tool_call"] = self.tool_call.to_plain()
        if self.final_turn is not None:
            value["final_turn"] = self.final_turn.to_plain()
        return value


@runtime_checkable
class ModelProvider(Protocol):
    """A model backend whose ``stream`` result is an async iterator."""

    def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...


# Readable compatibility names for provider and harness implementations.
AgentMessage = ModelMessage
AssistantTurn = ProviderFinalTurn
ProviderEvent = ProviderStreamEvent
ToolCallRequest = ProviderToolCall


__all__ = [
    "AgentMessage",
    "AssistantTurn",
    "MessageRole",
    "ModelMessage",
    "ModelProvider",
    "ProviderEvent",
    "ProviderEventType",
    "ProviderFinalTurn",
    "ProviderStreamEvent",
    "ProviderToolCall",
    "ToolCallRequest",
]
