from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass
import math
from types import MappingProxyType
from typing import Any, Literal, cast

from equipment_deep_research.domain.models import to_plain


def freeze_plain(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("runtime payload floats must be finite")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_plain(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_plain(item) for item in value)
    if is_dataclass(value):
        return freeze_plain(to_plain(value))
    raise TypeError(
        f"runtime payloads require JSON-compatible values, got {type(value).__name__}"
    )


def thaw_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class DomainWriteProposal:
    proposal_id: str
    object_type: str
    operation: Literal["upsert", "append"]
    payload: Mapping[str, Any]
    idempotency_key: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            cast(Mapping[str, Any], freeze_plain(self.payload)),
        )

    def to_plain(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "object_type": self.object_type,
            "operation": self.operation,
            "payload": thaw_plain(self.payload),
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class TraceProposal:
    proposal_id: str
    event_type: str
    actor: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            cast(Mapping[str, Any], freeze_plain(self.payload)),
        )

    def to_plain(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": thaw_plain(self.payload),
        }
