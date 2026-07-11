from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.domain.models import new_stable_id, now_iso, to_plain


@dataclass(frozen=True)
class RuntimeEvent:
    category: str
    event_type: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    event_id: str = field(default_factory=lambda: new_stable_id("event"))
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def to_plain(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "payload": to_plain(self.payload),
            "sequence": self.sequence,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }
