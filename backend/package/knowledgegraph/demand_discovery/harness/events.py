"""Agent runtime event contract.

``AgentEvent`` is the lifecycle event emitted by the agent loop and harness
(``agent_start``, ``turn_start``, ``message_*``, ``tool_execution_*``,
``turn_end``, ``agent_end``, plus harness-own events). It is a transport-level
record, not a durable domain trace event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    type: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    agent_run_id: str = ""
    timestamp: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "payload": dict(self.payload),
            "agent_run_id": self.agent_run_id,
            "timestamp": self.timestamp,
        }
