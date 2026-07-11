from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Any, Awaitable, Callable

from equipment_deep_research.domain.models import to_plain
from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_plain(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": to_plain(self.arguments),
        }


@dataclass(frozen=True)
class ToolExecutionContext:
    run_id: str
    agent_id: str
    permissions: dict[str, Any] = field(default_factory=dict)

    def to_plain(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "permissions": to_plain(self.permissions),
        }


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    details: dict[str, Any] = field(default_factory=dict)
    domain_proposals: list[DomainWriteProposal] = field(default_factory=list)
    trace_proposals: list[TraceProposal] = field(default_factory=list)
    is_error: bool = False

    def to_plain(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "content": self.content,
            "details": to_plain(self.details),
            "domain_proposals": [proposal.to_plain() for proposal in self.domain_proposals],
            "trace_proposals": [proposal.to_plain() for proposal in self.trace_proposals],
            "is_error": self.is_error,
        }


ToolHandler = Callable[[ToolCall, ToolExecutionContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def __post_init__(self) -> None:
        async_callable = inspect.iscoroutinefunction(self.handler) or inspect.iscoroutinefunction(
            getattr(self.handler, "__call__", None)
        )
        if not async_callable:
            raise TypeError("ToolDefinition handler must be async callable")

    def to_plain(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": to_plain(self.input_schema),
        }
