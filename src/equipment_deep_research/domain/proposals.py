from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from equipment_deep_research.domain.models import to_plain


@dataclass(frozen=True)
class DomainWriteProposal:
    proposal_id: str
    object_type: str
    operation: Literal["upsert", "append"]
    payload: dict[str, Any]
    idempotency_key: str

    def to_plain(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "object_type": self.object_type,
            "operation": self.operation,
            "payload": to_plain(self.payload),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class TraceProposal:
    proposal_id: str
    event_type: str
    actor: str
    payload: dict[str, Any]

    def to_plain(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": to_plain(self.payload),
        }
