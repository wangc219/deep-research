"""Structured cross-agent handoff channel; raw context is never transferable."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from typing import Any

from equipment_deep_research.domain.models import now_iso


_TYPES = {"task_assigned", "handoff_ready", "recall_requested", "recall_completed", "coverage_limited", "stage_completed"}
_FORBIDDEN = {"raw_session", "raw_sessions", "raw_messages", "messages", "provider_headers", "authorization"}
_STATUSES = {"ready", "completed", "failed", "limited", "timeout", "cancelled"}


@dataclass(frozen=True)
class AgentMessageEnvelope:
    message_id: str
    message_type: str
    sender: str
    recipient: str | None
    object_refs: list[str]
    payload: dict[str, Any]
    capability_tags: list[str] = field(default_factory=list)
    status: str = "ready"
    return_node: str = ""
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def validate(self) -> None:
        if not self.message_id.strip() or not self.sender.strip():
            raise ValueError("orchestration message requires message_id and sender")
        if self.status not in _STATUSES:
            raise ValueError(f"unsupported orchestration message status: {self.status}")
        if _contains_forbidden_key(self.payload):
            raise ValueError("raw session payloads are forbidden in orchestration messages")
        if len(self.object_refs) != len(set(self.object_refs)):
            raise ValueError("orchestration object_refs must be unique")
        if len(self.capability_tags) != len(set(self.capability_tags)):
            raise ValueError("orchestration capability_tags must be unique")

    def to_plain(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "message_type": self.message_type,
            "sender": self.sender,
            "recipient": self.recipient,
            "object_refs": list(self.object_refs),
            "payload": dict(self.payload),
            "capability_tags": list(self.capability_tags),
            "status": self.status,
            "return_node": self.return_node,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


class OrchestrationMessageBus:
    def __init__(self) -> None:
        self._messages: list[AgentMessageEnvelope] = []
        self._delivered: dict[str, set[str]] = defaultdict(set)
        # ``drain_for`` is called at every agent turn.  Keep a per-agent
        # cursor for the common case where capabilities are stable so each
        # call only inspects messages published since the previous drain.
        # Capability changes reset the cursor: an older message that did not
        # match the old capability set may become relevant after a handoff.
        self._drain_cursors: dict[str, tuple[frozenset[str], int]] = {}

    def publish(self, message: AgentMessageEnvelope) -> None:
        if message.message_type not in _TYPES:
            raise ValueError("unsupported orchestration message type")
        message.validate()
        serialized = json.dumps(message.payload, ensure_ascii=False)
        if len(serialized.encode()) > 32768:
            raise ValueError("orchestration payload exceeds 32KB")
        self._messages.append(message)

    def drain_for(self, agent_id: str, capability_tags: list[str]) -> list[AgentMessageEnvelope]:
        capability_set = set(capability_tags)
        capability_key = frozenset(capability_set)
        previous = self._drain_cursors.get(agent_id)
        start = previous[1] if previous and previous[0] == capability_key else 0
        result = []
        for message in self._messages[start:]:
            if message.message_id in self._delivered[agent_id]:
                continue
            if message.recipient not in {None, agent_id} and not capability_set.intersection(message.capability_tags):
                continue
            self._delivered[agent_id].add(message.message_id)
            result.append(message)
        self._drain_cursors[agent_id] = (capability_key, len(self._messages))
        return result

    def history(self) -> tuple[AgentMessageEnvelope, ...]:
        return tuple(self._messages)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN or _contains_forbidden_key(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False
