"""Structured cross-agent handoff channel; raw context is never transferable."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from typing import Any


_TYPES = {"task_assigned", "handoff_ready", "recall_requested", "recall_completed", "coverage_limited", "stage_completed"}
_FORBIDDEN = {"raw_session", "raw_sessions", "raw_messages", "messages", "provider_headers", "authorization"}


@dataclass(frozen=True)
class AgentMessageEnvelope:
    message_id: str
    message_type: str
    sender: str
    recipient: str | None
    object_refs: list[str]
    payload: dict[str, Any]
    capability_tags: list[str] = field(default_factory=list)


class OrchestrationMessageBus:
    def __init__(self) -> None:
        self._messages: list[AgentMessageEnvelope] = []
        self._delivered: dict[str, set[str]] = defaultdict(set)

    def publish(self, message: AgentMessageEnvelope) -> None:
        if message.message_type not in _TYPES:
            raise ValueError("unsupported orchestration message type")
        serialized = json.dumps(message.payload, ensure_ascii=False)
        if len(serialized.encode()) > 32768:
            raise ValueError("orchestration payload exceeds 32KB")
        if any(key in serialized.lower() for key in _FORBIDDEN):
            raise ValueError("raw session payloads are forbidden in orchestration messages")
        self._messages.append(message)

    def drain_for(self, agent_id: str, capability_tags: list[str]) -> list[AgentMessageEnvelope]:
        capability_set = set(capability_tags)
        result = []
        for message in self._messages:
            if message.message_id in self._delivered[agent_id]:
                continue
            if message.recipient not in {None, agent_id} and not capability_set.intersection(message.capability_tags):
                continue
            self._delivered[agent_id].add(message.message_id)
            result.append(message)
        return result

    def history(self) -> tuple[AgentMessageEnvelope, ...]:
        return tuple(self._messages)
