"""Core message, tool, and proposal contracts for the demand discovery harness.

These dataclasses are the stable low-level contracts shared by the agent loop,
the harness, the provider adapters, and the domain tools. They intentionally
carry no domain logic; domain semantics live in ``domain/`` and are only
referenced here through ``DomainWriteProposal`` / ``DomainTraceProposal``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssistantContentBlock:
    """A single block inside an assistant message.

    ``type`` is ``"text"`` for prose or ``"tool_call"`` for a requested tool
    invocation. Tool-call blocks use ``id`` / ``name`` / ``arguments``.
    """

    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "id": self.id,
            "name": self.name,
            "arguments": dict(self.arguments),
        }


@dataclass
class AgentMessage:
    """An internal message in the agent conversation.

    ``content`` is either a plain string (user / tool_result messages) or a
    list of :class:`AssistantContentBlock` (assistant messages). ``role`` is
    one of ``"user"``, ``"assistant"``, ``"tool_result"``, ``"system"``.
    """

    role: str
    content: str | list[AssistantContentBlock]
    timestamp: int
    tool_call_id: str = ""
    tool_name: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if isinstance(self.content, list):
            content: Any = [block.to_dict() for block in self.content]
        else:
            content = self.content
        return {
            "role": self.role,
            "content": content,
            "timestamp": self.timestamp,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "is_error": self.is_error,
            "metadata": dict(self.metadata),
        }


class UserMessage(AgentMessage):
    """Convenience constructor for a user-role message.

    Implemented as a plain subclass (not a second ``@dataclass``) so the
    ``AgentMessage`` field machinery is reused without a conflicting generated
    ``__init__``.
    """

    def __init__(
        self,
        content: str,
        timestamp: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            role="user",
            content=content,
            timestamp=timestamp,
            metadata=metadata or {},
        )


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": dict(self.arguments),
        }


@dataclass
class DomainWriteProposal:
    """A proposed write to a domain object.

    Tools emit these instead of mutating the domain store directly. The harness
    validates and flushes accepted proposals at the save point. ``object_type``
    names a core/supplement domain object (``SourceRecord``, ``EvidenceCard``,
    ``CandidateDemand``, ``AuditReport``, ``DemandReport``); ``action`` is one
    of ``upsert`` / ``merge`` / ``append``.
    """

    action: str
    object_type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "object_type": self.object_type,
            "payload": dict(self.payload),
        }


@dataclass
class DomainTraceProposal:
    """A proposed append to the domain trace.

    Each accepted :class:`DomainWriteProposal` must have a matching trace
    proposal so source -> evidence -> candidate -> audit -> report lineage can
    be reconstructed. ``input_refs`` / ``output_refs`` carry the domain ids
    needed for that lineage.
    """

    event_type: str
    target_type: str
    target_id: str
    payload_summary: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "payload_summary": self.payload_summary,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "payload": dict(self.payload),
        }


@dataclass
class ToolResult:
    """The four-channel result of a tool execution.

    - ``content``: short model-readable summary; enters the tool result message.
    - ``details``: structured result for program / UI / debug; carries no
      executable domain write.
    - ``domain_proposals``: proposed domain object writes, flushed at save point.
    - ``trace_proposals``: proposed domain trace events, flushed at save point.
    """

    tool_call_id: str
    tool_name: str
    content: str
    details: dict[str, Any]
    domain_proposals: list[DomainWriteProposal] = field(default_factory=list)
    trace_proposals: list[DomainTraceProposal] = field(default_factory=list)
    is_error: bool = False
    terminate: bool = False

    def to_message(self, timestamp: int = 0) -> AgentMessage:
        """Project this result into a ``tool_result`` message for the context."""

        return AgentMessage(
            role="tool_result",
            content=self.content,
            timestamp=timestamp,
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            is_error=self.is_error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "content": self.content,
            "details": dict(self.details),
            "domain_proposals": [p.to_dict() for p in self.domain_proposals],
            "trace_proposals": [p.to_dict() for p in self.trace_proposals],
            "is_error": self.is_error,
            "terminate": self.terminate,
        }
