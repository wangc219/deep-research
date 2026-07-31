"""Run-local source health snapshot for demand discovery acquisition."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SOURCE_HEALTH_STATUSES = {
    "ready",
    "degraded",
    "needs_auth",
    "unreachable",
    "not_configured",
    "disabled",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SourceHealthStatus:
    source_name: str
    status: str
    provider: str = ""
    reason: str = ""
    action: str = ""
    checked_at: datetime | None = None
    ttl_seconds: int = 1800

    def __post_init__(self) -> None:
        normalized = str(self.status).strip()
        if normalized not in SOURCE_HEALTH_STATUSES:
            raise ValueError(f"unknown source health status: {self.status}")
        object.__setattr__(self, "status", normalized)
        if not self.action:
            object.__setattr__(self, "action", source_health_action(normalized))
        if self.ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "provider": self.provider,
            "reason": self.reason,
            "action": self.action,
            "checked_at": _datetime_to_json(self.checked_at),
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceHealthStatus":
        return source_health_status_from_dict(data)


@dataclass(frozen=True)
class SourceHealthSnapshot:
    snapshot_id: str
    run_id: str
    created_at: datetime = field(default_factory=_now)
    sources: list[SourceHealthStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "created_at": _datetime_to_json(self.created_at),
            "sources": [item.to_dict() for item in self.sources],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceHealthSnapshot":
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            run_id=str(data["run_id"]),
            created_at=_datetime_from_json(data.get("created_at")) or _now(),
            sources=[
                source_health_status_from_dict(item)
                for item in data.get("sources", [])
                if isinstance(item, dict)
            ],
        )

    def status_for(self, source_name: str) -> SourceHealthStatus | None:
        for item in self.sources:
            if item.source_name == source_name:
                return item
        return None


def source_health_status_from_dict(data: dict[str, Any]) -> SourceHealthStatus:
    return SourceHealthStatus(
        source_name=str(data["source_name"]),
        status=str(data["status"]),
        provider=str(data.get("provider", "")),
        reason=str(data.get("reason", "")),
        action=str(data.get("action", "")),
        checked_at=_datetime_from_json(data.get("checked_at")),
        ttl_seconds=int(data.get("ttl_seconds", 1800)),
    )


def source_health_action(status: str) -> str:
    if status == "needs_auth":
        return "pause_for_user_auth"
    if status == "unreachable":
        return "skip_source_for_this_round"
    if status == "not_configured":
        return "skip_until_configured"
    if status == "disabled":
        return "skip_disabled_source"
    if status == "degraded":
        return "continue_with_caution"
    return "continue"


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime_from_json(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)
