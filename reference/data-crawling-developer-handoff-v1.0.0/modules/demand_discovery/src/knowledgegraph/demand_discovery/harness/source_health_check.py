"""Cheap run-start source health checks for demand discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from knowledgegraph.demand_discovery.domain.source_health import (
    SourceHealthSnapshot,
    SourceHealthStatus,
)
from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    WhitelistEntry,
)


@dataclass(frozen=True)
class SourceHealthCheckConfig:
    browser_session_enabled: bool = False
    wechat_session_marker: Path | None = None
    disabled_sources: set[str] = field(default_factory=set)
    ttl_seconds: int = 1800


def check_source_health(
    registry: SourceRegistry,
    *,
    run_id: str,
    config: SourceHealthCheckConfig | None = None,
    checked_at: datetime | None = None,
) -> SourceHealthSnapshot:
    resolved_config = config or SourceHealthCheckConfig()
    resolved_checked_at = checked_at or datetime.now(timezone.utc)
    statuses = [
        _check_entry(
            entry,
            config=resolved_config,
            checked_at=resolved_checked_at,
        )
        for entry in registry.sources
    ]
    snapshot_id = f"health-{_hash(f'{run_id}|{resolved_checked_at.isoformat()}|{len(statuses)}')}"
    return SourceHealthSnapshot(
        snapshot_id=snapshot_id,
        run_id=run_id,
        created_at=resolved_checked_at,
        sources=statuses,
    )


def _check_entry(
    entry: WhitelistEntry,
    *,
    config: SourceHealthCheckConfig,
    checked_at: datetime,
) -> SourceHealthStatus:
    if entry.source_name in config.disabled_sources:
        return SourceHealthStatus(
            source_name=entry.source_name,
            status="disabled",
            provider=_provider_for_entry(entry),
            reason="source_disabled_for_run",
            checked_at=checked_at,
            ttl_seconds=config.ttl_seconds,
        )
    if _is_wechat_session_source(entry):
        if config.wechat_session_marker is None or not config.wechat_session_marker.exists():
            return SourceHealthStatus(
                source_name=entry.source_name,
                status="needs_auth",
                provider="wechat_mp",
                reason="wechat_session_missing",
                checked_at=checked_at,
                ttl_seconds=config.ttl_seconds,
            )
        return SourceHealthStatus(
            source_name=entry.source_name,
            status="ready",
            provider="wechat_mp",
            reason="wechat_session_marker_present",
            checked_at=checked_at,
            ttl_seconds=config.ttl_seconds,
        )
    if entry.fetch_transport == "browser_session":
        if not config.browser_session_enabled:
            return SourceHealthStatus(
                source_name=entry.source_name,
                status="not_configured",
                provider="browser_session",
                reason="browser_session_not_enabled",
                checked_at=checked_at,
                ttl_seconds=config.ttl_seconds,
            )
        return SourceHealthStatus(
            source_name=entry.source_name,
            status="ready",
            provider="browser_session",
            reason="browser_session_enabled",
            checked_at=checked_at,
            ttl_seconds=config.ttl_seconds,
        )
    if entry.fetch_transport == "http" and entry.entry_urls:
        return SourceHealthStatus(
            source_name=entry.source_name,
            status="ready",
            provider="http",
            reason="entry_url_configured",
            checked_at=checked_at,
            ttl_seconds=config.ttl_seconds,
        )
    return SourceHealthStatus(
        source_name=entry.source_name,
        status="not_configured",
        provider=_provider_for_entry(entry),
        reason="no_entry_route_configured",
        checked_at=checked_at,
        ttl_seconds=config.ttl_seconds,
    )


def _is_wechat_session_source(entry: WhitelistEntry) -> bool:
    source_type = entry.source_type.lower()
    return (
        entry.fetch_transport == "browser_session"
        and not entry.hosts
        and (
            source_type in {"wemedia", "wechat", "wechat_mp"}
            or "wechat" in entry.notes.lower()
        )
    )


def _provider_for_entry(entry: WhitelistEntry) -> str:
    if _is_wechat_session_source(entry):
        return "wechat_mp"
    return entry.fetch_transport or "unknown"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
