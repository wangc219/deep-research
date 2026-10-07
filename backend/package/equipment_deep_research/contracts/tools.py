"""Tool invocation contracts shared by providers, harnesses and executors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import inspect
from typing import Any, Awaitable, Callable, cast

from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal, freeze_plain, thaw_plain


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", cast(Mapping[str, Any], freeze_plain(self.arguments)))

    def to_plain(self) -> dict[str, Any]:
        return {"call_id": self.call_id, "name": self.name, "arguments": thaw_plain(self.arguments)}


@dataclass(frozen=True)
class ToolExecutionContext:
    run_id: str
    agent_id: str
    permissions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", cast(Mapping[str, Any], freeze_plain(self.permissions)))

    def to_plain(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "agent_id": self.agent_id, "permissions": thaw_plain(self.permissions)}


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    details: Mapping[str, Any] = field(default_factory=dict)
    domain_proposals: Sequence[DomainWriteProposal] = field(default_factory=tuple)
    trace_proposals: Sequence[TraceProposal] = field(default_factory=tuple)
    is_error: bool = False

    def __post_init__(self) -> None:
        try:
            domain_proposals = tuple(self.domain_proposals)
            trace_proposals = tuple(self.trace_proposals)
        except TypeError as exc:
            raise TypeError("proposals must be iterable") from exc
        if not all(isinstance(item, DomainWriteProposal) for item in domain_proposals):
            raise TypeError("domain_proposals must contain only DomainWriteProposal values")
        if not all(isinstance(item, TraceProposal) for item in trace_proposals):
            raise TypeError("trace_proposals must contain only TraceProposal values")
        object.__setattr__(self, "details", cast(Mapping[str, Any], freeze_plain(self.details)))
        object.__setattr__(self, "domain_proposals", domain_proposals)
        object.__setattr__(self, "trace_proposals", trace_proposals)

    def to_plain(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "content": self.content,
            "details": thaw_plain(self.details),
            "domain_proposals": [item.to_plain() for item in self.domain_proposals],
            "trace_proposals": [item.to_plain() for item in self.trace_proposals],
            "is_error": self.is_error,
        }


ToolHandler = Callable[[ToolCall, ToolExecutionContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not (inspect.iscoroutinefunction(self.handler) or inspect.iscoroutinefunction(getattr(self.handler, "__call__", None))):
            raise TypeError("ToolDefinition handler must be async callable")
        object.__setattr__(self, "input_schema", cast(Mapping[str, Any], freeze_plain(self.input_schema)))

    def to_plain(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": thaw_plain(self.input_schema)}


__all__ = ["ToolCall", "ToolExecutionContext", "ToolResult", "ToolHandler", "ToolDefinition"]
