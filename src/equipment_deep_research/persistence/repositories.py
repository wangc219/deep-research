from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from threading import Lock
import time
from typing import Any
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
    delete,
    update,
    func,
    inspect as sqlalchemy_inspect,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from equipment_deep_research.application.dto import RunView
from equipment_deep_research.domain.conversation import (
    DEFAULT_BRANCH_ID,
    LIVE_STEER_MODES,
    branch_message_path,
    merge_branch_working_memory,
    normalize_branch_id,
    normalize_steer_mode,
)
from equipment_deep_research.runtime_identity import (
    RUNTIME_BUILD_HASH,
    claimed_queue_status,
    pending_queue_status,
)


metadata = MetaData()
runs = Table("runs", metadata, Column("run_id", String(128), primary_key=True), Column("payload", Text, nullable=False))
events = Table("runtime_events", metadata, Column("run_id", String(128), primary_key=True), Column("sequence", Integer, primary_key=True), Column("event_type", String(128), nullable=False), Column("payload", Text, nullable=False))
queue_items = Table("run_queue", metadata, Column("run_id", String(128), primary_key=True), Column("status", String(32), nullable=False), Column("ordinal", Integer, autoincrement=True, nullable=False, unique=True))
worker_heartbeats = Table("worker_heartbeats", metadata, Column("worker_id", String(128), primary_key=True), Column("updated_at", String(64), nullable=False), Column("status", String(32), nullable=False), Column("current_run_id", String(128), nullable=False, default=""))
favorites = Table(
    "favorites",
    metadata,
    Column("favorite_id", String(128), primary_key=True),
    Column("scope", String(32), nullable=False),
    Column("owner_id", String(128), nullable=False),
    Column("run_id", String(128), nullable=False),
    Column("card_binding_id", String(256), nullable=False, default=""),
    Column("capability_id", String(256), nullable=False, default=""),
    Column("card_key", String(512), nullable=False),
    Column("snapshot_json", Text, nullable=False),
    # Mutable presentation metadata deliberately lives outside snapshot_json;
    # the five-module capability portrait remains an immutable source snapshot.
    Column("display_name", String(400), nullable=False, default=""),
    Column("note", Text, nullable=False, default=""),
    Column("tags_json", Text, nullable=False, default="[]"),
    Column("source_topic", Text, nullable=False, default=""),
    Column("source_status", String(32), nullable=False, default=""),
    Column("source_deleted", Integer, nullable=False, default=0),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    UniqueConstraint(
        "scope",
        "owner_id",
        "run_id",
        "card_key",
        name="uq_favorites_scope_owner_run_card",
    ),
)
# Lightweight indexes keep the public favorites page responsive when a
# workspace has accumulated many immutable snapshots.  They are additive and
# safe for existing SQLite databases because ``create_all`` creates only the
# missing objects.
Index("ix_favorites_scope_owner_created", favorites.c.scope, favorites.c.owner_id, favorites.c.created_at)
Index("ix_favorites_run_id", favorites.c.run_id)

# Deep-research is deliberately persisted separately from the legacy run
# event stream.  ``runtime_events`` is keyed by run_id and is used by the S1-S6
# worker; using it for a conversation would mix cursors and make SSE replay
# non-deterministic.  These append-oriented tables are safe to create on an
# existing SQLite database and keep the original capability snapshot intact.
deep_sessions = Table(
    "deep_sessions", metadata,
    Column("session_id", String(128), primary_key=True),
    Column("parent_run_id", String(128), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("title", String(240), nullable=False, default=""),
    Column("card_binding_id", String(256), nullable=False, default=""),
    Column("hypothesis_id", String(256), nullable=False, default=""),
    Column("scope_json", Text, nullable=False, default="{}"),
    Column("query_snapshot_json", Text, nullable=False, default="{}"),
    Column("query_snapshot_hash", String(128), nullable=False, default=""),
    Column("result_snapshot_hash", String(128), nullable=False, default=""),
    Column("working_memory_json", Text, nullable=False, default="{}"),
    Column("status", String(32), nullable=False, default="active"),
    Column("created_by", String(128), nullable=False, default="analyst"),
    Column("idempotency_key", String(256), nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)
Index("ix_deep_sessions_parent", deep_sessions.c.parent_run_id, deep_sessions.c.updated_at)

deep_messages = Table(
    "deep_messages", metadata,
    Column("session_id", String(128), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("message_id", String(128), nullable=False, unique=True),
    Column("parent_message_id", String(128), nullable=False, default=""),
    Column("branch_id", String(128), nullable=False, default="main"),
    Column("turn_id", String(128), nullable=False, default=""),
    Column("message_kind", String(32), nullable=False, default="message"),
    Column("role", String(24), nullable=False),
    Column("content", Text, nullable=False),
    Column("status", String(32), nullable=False, default="completed"),
    Column("artifact_refs_json", Text, nullable=False, default="[]"),
    Column("version_refs_json", Text, nullable=False, default="[]"),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("created_at", String(64), nullable=False),
)

deep_jobs = Table(
    "deep_jobs", metadata,
    Column("job_id", String(128), primary_key=True),
    Column("parent_run_id", String(128), nullable=False),
    Column("session_id", String(128), nullable=False, default=""),
    Column("child_run_id", String(128), nullable=False, default=""),
    Column("parent_job_id", String(128), nullable=False, default=""),
    Column("branch_id", String(128), nullable=False, default="main"),
    Column("root_message_id", String(128), nullable=False, default=""),
    Column("checkpoint_json", Text, nullable=False, default="{}"),
    Column("state_version", Integer, nullable=False, default=1),
    Column("claim_token", String(128), nullable=False, default=""),
    Column("steer_closed", Integer, nullable=False, default=0),
    Column("kind", String(64), nullable=False, default="deep_divergence_v1"),
    Column("stage", String(64), nullable=False, default="queued"),
    Column("status", String(32), nullable=False, default="queued"),
    Column("idempotency_key", String(256), nullable=False, default=""),
    Column("fingerprint", String(128), nullable=False, default=""),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("error", Text, nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    UniqueConstraint("parent_run_id", "idempotency_key", name="uq_deep_jobs_parent_idempotency"),
)
Index("ix_deep_jobs_parent", deep_jobs.c.parent_run_id, deep_jobs.c.created_at)
# Fingerprints are the canonical de-duplication key for reference research
# requests (parent run + hypothesis + query snapshot + focus).  Keep a plain
# index in the declarative schema so opening a legacy database that already
# contains duplicate fingerprints never fails migration.  New databases get
# an additional partial unique fence in ``_ensure_deep_indexes``.
Index("ix_deep_jobs_parent_fingerprint", deep_jobs.c.parent_run_id, deep_jobs.c.fingerprint)
Index(
    "ix_deep_jobs_session_branch_order",
    deep_jobs.c.session_id,
    deep_jobs.c.branch_id,
    deep_jobs.c.status,
    deep_jobs.c.created_at,
)

deep_branches = Table(
    "deep_branches", metadata,
    Column("branch_id", String(128), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("parent_branch_id", String(128), nullable=False, default=""),
    Column("forked_from_message_id", String(128), nullable=False, default=""),
    Column("title", String(240), nullable=False, default=""),
    Column("status", String(32), nullable=False, default="active"),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)
Index("ix_deep_branches_session", deep_branches.c.session_id, deep_branches.c.created_at)

deep_steers = Table(
    "deep_steers", metadata,
    Column("steer_id", String(128), primary_key=True),
    Column("client_steer_id", String(128), nullable=False),
    Column("job_id", String(128), nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("message_id", String(128), nullable=False),
    Column("branch_id", String(128), nullable=False, default="main"),
    Column("mode", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("queue_order", Integer, nullable=False),
    Column("status", String(32), nullable=False, default="pending"),
    Column("applied_stage", String(64), nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    UniqueConstraint("job_id", "client_steer_id", name="uq_deep_steers_job_client"),
)
Index("ix_deep_steers_job_queue", deep_steers.c.job_id, deep_steers.c.status, deep_steers.c.queue_order)

capability_versions = Table(
    "capability_versions", metadata,
    Column("version_id", String(128), primary_key=True),
    Column("parent_run_id", String(128), nullable=False),
    Column("card_binding_id", String(256), nullable=False),
    Column("hypothesis_id", String(256), nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("parent_version_id", String(128), nullable=False, default=""),
    Column("base_version_id", String(128), nullable=False, default=""),
    Column("base_snapshot_hash", String(128), nullable=False, default=""),
    Column("diff_json", Text, nullable=False, default="{}"),
    Column("source", String(128), nullable=False, default="deep-thinking"),
    Column("evidence_refs_json", Text, nullable=False, default="[]"),
    Column("snapshot_json", Text, nullable=False, default="{}"),
    Column("status", String(32), nullable=False, default="pending_verification"),
    # Soft deletion keeps the immutable review/audit record recoverable while
    # removing it from ordinary capability projections.  Restore returns to
    # the exact prior review state instead of silently downgrading a verified
    # version to a pending draft.
    Column("previous_status", String(32), nullable=False, default=""),
    # Reviewed capability history survives source-run deletion for audit and
    # favorite snapshots.  Pending drafts remain tied to the source and are
    # removed by ``delete_run``.
    Column("source_deleted", Integer, nullable=False, default=0),
    Column("source_status", String(32), nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    # ``card_binding_id`` is the server-owned identity of a card/hypothesis
    # lineage.  Follow-up versions for one hypothesis append v2, v3, ... .
    # Include hypothesis_id in the fence as a guard against an accidentally
    # reused binding; genuinely new hypotheses should still receive a new
    # binding from the canonical candidate resolver.
    UniqueConstraint("parent_run_id", "card_binding_id", "hypothesis_id", "version_no", name="uq_capability_version_no"),
)
Index("ix_capability_versions_lineage", capability_versions.c.parent_run_id, capability_versions.c.card_binding_id, capability_versions.c.hypothesis_id, capability_versions.c.version_no)

deep_events = Table(
    "deep_events", metadata,
    Column("stream_id", String(256), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("event_id", String(128), nullable=False, unique=True),
    Column("event_type", String(64), nullable=False),
    Column("session_id", String(128), nullable=False, default=""),
    Column("job_id", String(128), nullable=False, default=""),
    Column("parent_run_id", String(128), nullable=False),
    Column("child_run_id", String(128), nullable=False, default=""),
    Column("stage", String(64), nullable=False, default="queued"),
    Column("status", String(32), nullable=False, default="queued"),
    Column("state_version", Integer, nullable=False, default=0),
    Column("progress", Integer, nullable=False, default=0),
    Column("delta_json", Text, nullable=False, default="{}"),
    Column("evidence_refs_json", Text, nullable=False, default="[]"),
    Column("artifact_refs_json", Text, nullable=False, default="[]"),
    Column("version_refs_json", Text, nullable=False, default="[]"),
    Column("error", Text, nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
)

deep_idempotency = Table(
    "deep_idempotency", metadata,
    Column("scope_key", String(256), primary_key=True),
    Column("operation", String(96), primary_key=True),
    Column("idempotency_key", String(256), primary_key=True),
    Column("request_hash", String(128), nullable=False),
    Column("resource_id", String(128), nullable=False, default=""),
    Column("response_json", Text, nullable=False, default="{}"),
    Column("created_at", String(64), nullable=False),
)

# Channel delivery claims are kept separate from API mutation idempotency.
# This table is intentionally tiny and append/update oriented: a platform
# retry only needs a fingerprint, a short processing lease, and the bounded
# public response that can be replayed after another worker completes it.
gateway_deliveries = Table(
    "gateway_deliveries", metadata,
    Column("delivery_key", String(256), primary_key=True),
    Column("fingerprint", String(128), nullable=False),
    Column("status", String(24), nullable=False, default="processing"),
    Column("owner_token", String(128), nullable=False, default=""),
    Column("response_json", Text, nullable=False, default="{}"),
    Column("expires_at", String(64), nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)
Index("ix_gateway_deliveries_expiry", gateway_deliveries.c.expires_at)

# Optional nanobot-style durable channel broker.  It is intentionally separate
# from the research ledger: workers can claim public channel envelopes without
# gaining access to sessions, provider state, or Agent Core internals.
message_bus = Table(
    "message_bus",
    metadata,
    Column("delivery_id", String(128), primary_key=True),
    Column("direction", String(16), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("status", String(16), nullable=False, default="queued"),
    Column("owner", String(160), nullable=False, default=""),
    Column("lease_until", String(64), nullable=False, default=""),
    Column("created_at", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
)
Index("ix_message_bus_claim", message_bus.c.direction, message_bus.c.status, message_bus.c.sequence)

deep_run_links = Table(
    "deep_run_links", metadata,
    Column("parent_run_id", String(128), primary_key=True),
    Column("child_run_id", String(128), primary_key=True),
    Column("job_id", String(128), nullable=False, default=""),
    Column("relation", String(64), nullable=False, default="deep_research"),
    Column("created_at", String(64), nullable=False),
)


def _favorite_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retryable_sqlite_lock(exc: BaseException) -> bool:
    """Return whether a SQL write may be retried after SQLite lock pressure.

    SQLite reports transient writer contention as ``OperationalError`` with
    backend-specific wording (``database is locked``/``busy``).  Do not
    retry arbitrary operational failures such as malformed SQL or missing
    tables; those indicate a real deployment problem and must surface.
    """

    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).casefold()
    return "database is locked" in message or "database is busy" in message or "busy" in message


def _favorite_bool(value: Any) -> bool:
    """Decode SQLite/legacy boolean values without treating ``"false"`` as true."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() not in {
        "",
        "0",
        "false",
        "no",
        "off",
        "none",
        "null",
    }


def _normalize_favorite_tags(value: Any) -> list[str]:
    """Normalize user-editable tags into a bounded, deterministic list."""

    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    for item in values:
        tag = " ".join(str(item or "").split()).strip()[:64]
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= 20:
            break
    return result


def _favorite_row_to_dict(row: Any) -> dict[str, Any]:
    """Decode a SQL/fallback row into the API-facing favorite shape."""

    if row is None:
        return {}
    raw = dict(row) if not isinstance(row, dict) else dict(row)
    snapshot = raw.pop("snapshot_json", "")
    tags_json = raw.pop("tags_json", "[]")
    try:
        decoded = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    except (TypeError, ValueError, json.JSONDecodeError):
        decoded = {}
    if not isinstance(decoded, dict):
        decoded = {}
    try:
        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
    except (TypeError, ValueError, json.JSONDecodeError):
        tags = []
    if not isinstance(tags, list):
        tags = []
    raw["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    raw["tags_json"] = json.dumps(raw["tags"], ensure_ascii=False)
    # Keep the flattened card fields used by the existing API while also
    # exposing the immutable payload in both forms.  ``snapshot_json`` is
    # useful to clients that persist/export the raw record, and ``snapshot``
    # gives newer clients a structured object without another decode step.
    # Re-serializing the decoded object also normalizes legacy rows whose JSON
    # used non-deterministic whitespace or key ordering.
    raw["snapshot_json"] = json.dumps(decoded, ensure_ascii=False, sort_keys=True)
    raw["snapshot"] = dict(decoded)
    # Metadata wins over stale values accidentally persisted in the snapshot.
    raw["source_deleted"] = _favorite_bool(raw.get("source_deleted", False))
    raw["favorited"] = True
    return {**decoded, **raw}


class SqlGatewayDeliveryStore:
    """SQLite/Postgres-friendly durable store for channel delivery claims.

    The store is deliberately host-owned and has no dependency on the Agent
    Core.  A processing row is a lease: an expired lease can be reclaimed,
    while a completed row is replayable until its TTL elapses.  The owner
    token prevents a stale worker from completing a claim that another worker
    has already reclaimed.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = Lock()
        metadata.create_all(engine)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _expired(value: Any, now: datetime) -> bool:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= now

    @staticmethod
    def _row(row: Mapping[str, Any], *, owner: bool = False) -> dict[str, Any]:
        raw = dict(row)
        response: Any
        try:
            response = json.loads(raw.get("response_json", "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            response = {}
        return {
            "status": "owner" if owner else str(raw.get("status", "processing") or "processing"),
            "fingerprint": str(raw.get("fingerprint", "") or ""),
            # Never hand another worker the current owner's fencing token.
            "owner_token": str(raw.get("owner_token", "") or "") if owner else "",
            "response": response,
            "expires_at": str(raw.get("expires_at", "") or ""),
        }

    def _validate(self, key: str, fingerprint: str) -> tuple[str, str]:
        normalized_key = str(key or "").strip()
        normalized_fingerprint = str(fingerprint or "").strip()
        if not normalized_key or len(normalized_key) > 256:
            raise ValueError("gateway delivery key is missing or invalid")
        if not normalized_fingerprint or len(normalized_fingerprint) > 128:
            raise ValueError("gateway delivery fingerprint is missing or invalid")
        return normalized_key, normalized_fingerprint

    def claim(
        self,
        key: str,
        *,
        fingerprint: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        normalized_key, normalized_fingerprint = self._validate(key, fingerprint)
        ttl = max(1, min(int(ttl_seconds), 86_400))
        for attempt in range(8):
            now = self._now()
            expires = (now + timedelta(seconds=ttl)).isoformat()
            owner_token = uuid4().hex
            try:
                with self._lock, self.engine.begin() as connection:
                    # Keep the bounded replay ledger from growing forever;
                    # expired processing leases are safe to reclaim under the
                    # same owner-token fence used for normal completion.
                    connection.execute(
                        delete(gateway_deliveries).where(
                            gateway_deliveries.c.expires_at <= now.isoformat()
                        )
                    )
                    current = connection.execute(
                        select(gateway_deliveries).where(
                            gateway_deliveries.c.delivery_key == normalized_key
                        )
                    ).mappings().one_or_none()
                    if current is not None:
                        if str(current.get("fingerprint", "")) != normalized_fingerprint:
                            raise ValueError("gateway message id has conflicting content")
                        if self._expired(current.get("expires_at"), now):
                            connection.execute(
                                delete(gateway_deliveries).where(
                                    gateway_deliveries.c.delivery_key == normalized_key,
                                    gateway_deliveries.c.fingerprint == normalized_fingerprint,
                                )
                            )
                        else:
                            return self._row(current)
                    connection.execute(
                        gateway_deliveries.insert().values(
                            delivery_key=normalized_key,
                            fingerprint=normalized_fingerprint,
                            status="processing",
                            owner_token=owner_token,
                            response_json="{}",
                            expires_at=expires,
                            created_at=now.isoformat(),
                            updated_at=now.isoformat(),
                        )
                    )
                return {
                    "status": "owner",
                    "fingerprint": normalized_fingerprint,
                    "owner_token": owner_token,
                    "response": {},
                    "expires_at": expires,
                }
            except IntegrityError:
                # Another process won the insert. Read it on a fresh
                # connection so the failed transaction cannot poison retry.
                with self.engine.connect() as connection:
                    current = connection.execute(
                        select(gateway_deliveries).where(
                            gateway_deliveries.c.delivery_key == normalized_key
                        )
                    ).mappings().one_or_none()
                if current is not None:
                    if str(current.get("fingerprint", "")) != normalized_fingerprint:
                        raise ValueError("gateway message id has conflicting content")
                    return self._row(current)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to claim gateway delivery")

    def get(self, key: str, *, fingerprint: str) -> dict[str, Any] | None:
        normalized_key, normalized_fingerprint = self._validate(key, fingerprint)
        now = self._now()
        with self.engine.connect() as connection:
            current = connection.execute(
                select(gateway_deliveries).where(
                    gateway_deliveries.c.delivery_key == normalized_key
                )
            ).mappings().one_or_none()
        if current is None:
            return None
        if str(current.get("fingerprint", "")) != normalized_fingerprint:
            raise ValueError("gateway message id has conflicting content")
        if self._expired(current.get("expires_at"), now):
            return None
        return self._row(current)

    def complete(
        self,
        key: str,
        *,
        fingerprint: str,
        owner_token: str,
        response: Mapping[str, Any],
        ttl_seconds: int,
    ) -> None:
        normalized_key, normalized_fingerprint = self._validate(key, fingerprint)
        now = self._now()
        expires = (now + timedelta(seconds=max(1, min(int(ttl_seconds), 86_400)))).isoformat()
        payload = json.dumps(response, ensure_ascii=False, sort_keys=True)
        with self._lock, self.engine.begin() as connection:
            connection.execute(
                update(gateway_deliveries).where(
                    gateway_deliveries.c.delivery_key == normalized_key,
                    gateway_deliveries.c.fingerprint == normalized_fingerprint,
                    gateway_deliveries.c.status == "processing",
                    gateway_deliveries.c.owner_token == str(owner_token),
                ).values(
                    status="completed",
                    owner_token="",
                    response_json=payload,
                    expires_at=expires,
                    updated_at=now.isoformat(),
                )
            )

    def release(self, key: str, *, fingerprint: str, owner_token: str) -> None:
        normalized_key, normalized_fingerprint = self._validate(key, fingerprint)
        with self._lock, self.engine.begin() as connection:
            connection.execute(
                delete(gateway_deliveries).where(
                    gateway_deliveries.c.delivery_key == normalized_key,
                    gateway_deliveries.c.fingerprint == normalized_fingerprint,
                    gateway_deliveries.c.status == "processing",
                    gateway_deliveries.c.owner_token == str(owner_token),
                )
            )


class SqlMessageBusStore:
    """Durable cross-process broker for bounded public channel envelopes.

    Claims are short leases.  A worker that crashes without acknowledging an
    inbound envelope leaves it available for another worker after the lease;
    acknowledgements are fenced by the owner id.  Outbound messages are acked
    when consumed by a channel adapter, matching the local queue contract.
    """

    def __init__(self, engine: Engine, *, lease_seconds: float = 30.0) -> None:
        self.engine = engine
        self.lease_seconds = max(0.2, min(float(lease_seconds), 86_400.0))
        self._lock = Lock()
        self._closed = False
        metadata.create_all(engine)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _direction(value: str) -> str:
        direction = str(value or "").strip().lower()
        if direction not in {"inbound", "outbound"}:
            raise ValueError("message bus direction must be inbound or outbound")
        return direction

    def _publish(self, direction: str, message: Any) -> str:
        direction = self._direction(direction)
        if self._closed:
            raise RuntimeError("message bus store is closed")
        if not hasattr(message, "to_plain"):
            raise TypeError("message must expose to_plain()")
        payload = message.to_plain()
        if not isinstance(payload, Mapping):
            raise TypeError("message projection must be an object")
        try:
            encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("message payload is not JSON serializable") from exc
        if len(encoded.encode("utf-8")) > 128_000:
            raise ValueError("message payload exceeds 128000 bytes")
        delivery_id = f"delivery-{uuid4().hex}"
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(func.max(message_bus.c.sequence)).where(message_bus.c.direction == direction)
                    ).scalar_one_or_none()
                    sequence = int(current or 0) + 1
                    connection.execute(
                        message_bus.insert().values(
                            delivery_id=delivery_id,
                            direction=direction,
                            payload_json=encoded,
                            status="queued",
                            owner="",
                            lease_until="",
                            created_at=self._now().isoformat(),
                            sequence=sequence,
                        )
                    )
                return delivery_id
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to publish message")

    def publish_inbound(self, message: Any) -> str:
        return self._publish("inbound", message)

    def publish_outbound(self, message: Any) -> str:
        return self._publish("outbound", message)

    def _claim(self, direction: str, consumer_id: str) -> dict[str, Any] | None:
        direction = self._direction(direction)
        owner = str(consumer_id or "").strip()[:160]
        if not owner:
            raise ValueError("consumer_id must not be empty")
        if self._closed:
            return None
        for attempt in range(8):
            now = self._now()
            lease_until = (now + timedelta(seconds=self.lease_seconds)).isoformat()
            try:
                with self._lock, self.engine.begin() as connection:
                    # Requeue only expired claims for this direction.  This is
                    # idempotent and lets a restarted worker recover messages.
                    connection.execute(
                        update(message_bus)
                        .where(
                            message_bus.c.direction == direction,
                            message_bus.c.status == "claimed",
                            message_bus.c.lease_until <= now.isoformat(),
                        )
                        .values(status="queued", owner="", lease_until="")
                    )
                    row = connection.execute(
                        select(message_bus).where(
                            message_bus.c.direction == direction,
                            message_bus.c.status == "queued",
                        )
                        .order_by(message_bus.c.sequence.asc(), message_bus.c.delivery_id.asc())
                        .limit(1)
                    ).mappings().one_or_none()
                    if row is None:
                        return None
                    result = connection.execute(
                        update(message_bus)
                        .where(
                            message_bus.c.delivery_id == row["delivery_id"],
                            message_bus.c.status == "queued",
                        )
                        .values(status="claimed", owner=owner, lease_until=lease_until)
                    )
                    if not result.rowcount:
                        continue
                    try:
                        payload = json.loads(str(row["payload_json"]))
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise RuntimeError("durable message payload is corrupted") from exc
                if not isinstance(payload, Mapping):
                    raise RuntimeError("durable message payload must be an object")
                return {
                    "delivery_id": str(row["delivery_id"]),
                    "payload": dict(payload),
                    "owner": owner,
                    "lease_until": lease_until,
                }
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def claim_inbound(self, consumer_id: str) -> Mapping[str, Any] | None:
        return self._claim("inbound", consumer_id)

    def claim_outbound(self, consumer_id: str) -> Mapping[str, Any] | None:
        return self._claim("outbound", consumer_id)

    def _ack(self, direction: str, delivery_id: str, consumer_id: str) -> None:
        direction = self._direction(direction)
        delivery = str(delivery_id or "").strip()
        owner = str(consumer_id or "").strip()[:160]
        if not delivery or not owner:
            return
        with self._lock, self.engine.begin() as connection:
            connection.execute(
                delete(message_bus).where(
                    message_bus.c.delivery_id == delivery,
                    message_bus.c.direction == direction,
                    message_bus.c.status == "claimed",
                    message_bus.c.owner == owner,
                )
            )

    def ack_inbound(self, delivery_id: str, consumer_id: str) -> None:
        self._ack("inbound", delivery_id, consumer_id)

    def ack_outbound(self, delivery_id: str, consumer_id: str) -> None:
        self._ack("outbound", delivery_id, consumer_id)

    def close(self) -> None:
        self._closed = True


class SqlRunRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = Lock()
        metadata.create_all(engine)
        self._ensure_favorite_columns()
        self._ensure_deep_columns()
        self._ensure_deep_indexes()

    def _ensure_deep_indexes(self) -> None:
        """Install the non-empty fingerprint uniqueness fence when possible.

        A pre-release build could have emitted duplicate fingerprint rows.
        Preserve those records rather than making startup fail; the repository
        still converges future requests on the oldest canonical row.
        """

        try:
            indexes = sqlalchemy_inspect(self.engine).get_indexes("deep_jobs")
        except (KeyError, OperationalError):
            return
        fingerprint_index_exists = any(str(item.get("name")) == "uq_deep_jobs_parent_fingerprint" for item in indexes)
        # This partial index is SQLite-specific; the application currently
        # uses SQLite for the durable ledger.  Other dialects retain the plain
        # lookup index and repository-level de-duplication.
        if self.engine.dialect.name == "sqlite" and not fingerprint_index_exists:
            try:
                with self._lock, self.engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_deep_jobs_parent_fingerprint "
                        "ON deep_jobs(parent_run_id, fingerprint) WHERE fingerprint <> ''"
                    )
            except IntegrityError:
                # Existing duplicates are retained for audit/replay.  Do not
                # delete or rewrite history during a schema migration.
                pass
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc):
                    raise

        # The branch-order fence is queried on every deep turn.  Keep an
        # explicit migration statement for databases created before the
        # declarative index was added; ``create_all`` does not retrofit every
        # index on all supported SQLite versions.
        if self.engine.dialect.name == "sqlite":
            try:
                if not any(
                    str(item.get("name")) == "ix_deep_jobs_session_branch_order"
                    for item in indexes
                ):
                    with self._lock, self.engine.begin() as connection:
                        connection.exec_driver_sql(
                            "CREATE INDEX IF NOT EXISTS ix_deep_jobs_session_branch_order "
                            "ON deep_jobs(session_id, branch_id, status, created_at)"
                        )
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc):
                    raise

        # Capability version numbering is scoped to hypothesis identity.  Add
        # an explicit unique fence for legacy databases created before the
        # hypothesis column participated in the declarative constraint.
        if self.engine.dialect.name != "sqlite":
            return
        try:
            indexes = sqlalchemy_inspect(self.engine).get_indexes("capability_versions")
            if not any(str(item.get("name")) == "uq_capability_version_hypothesis" for item in indexes):
                with self._lock, self.engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_version_hypothesis "
                        "ON capability_versions(parent_run_id, card_binding_id, hypothesis_id, version_no)"
                    )
        except IntegrityError:
            # Preserve pre-existing duplicate history; repository-level retry
            # and the declarative fence protect all newly written rows.
            return
        except OperationalError as exc:
            if not _retryable_sqlite_lock(exc):
                raise

    def _ensure_deep_columns(self) -> None:
        """Apply additive deep-ledger columns to databases from older builds."""

        additions = {
            "deep_sessions": {
                "working_memory_json": "ALTER TABLE deep_sessions ADD COLUMN working_memory_json TEXT NOT NULL DEFAULT '{}'",
            },
            "deep_messages": {
                "version_refs_json": "ALTER TABLE deep_messages ADD COLUMN version_refs_json TEXT NOT NULL DEFAULT '[]'",
                "metadata_json": "ALTER TABLE deep_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
                "parent_message_id": "ALTER TABLE deep_messages ADD COLUMN parent_message_id TEXT NOT NULL DEFAULT ''",
                "branch_id": "ALTER TABLE deep_messages ADD COLUMN branch_id TEXT NOT NULL DEFAULT 'main'",
                "turn_id": "ALTER TABLE deep_messages ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''",
                "message_kind": "ALTER TABLE deep_messages ADD COLUMN message_kind TEXT NOT NULL DEFAULT 'message'",
            },
            "deep_jobs": {
                "branch_id": "ALTER TABLE deep_jobs ADD COLUMN branch_id TEXT NOT NULL DEFAULT 'main'",
                "root_message_id": "ALTER TABLE deep_jobs ADD COLUMN root_message_id TEXT NOT NULL DEFAULT ''",
                "checkpoint_json": "ALTER TABLE deep_jobs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'",
                "state_version": "ALTER TABLE deep_jobs ADD COLUMN state_version INTEGER NOT NULL DEFAULT 1",
                "claim_token": "ALTER TABLE deep_jobs ADD COLUMN claim_token TEXT NOT NULL DEFAULT ''",
                "steer_closed": "ALTER TABLE deep_jobs ADD COLUMN steer_closed INTEGER NOT NULL DEFAULT 0",
            },
            "deep_events": {
                "state_version": "ALTER TABLE deep_events ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0",
            },
            "capability_versions": {
                "source_deleted": "ALTER TABLE capability_versions ADD COLUMN source_deleted INTEGER NOT NULL DEFAULT 0",
                "source_status": "ALTER TABLE capability_versions ADD COLUMN source_status TEXT NOT NULL DEFAULT ''",
                "previous_status": "ALTER TABLE capability_versions ADD COLUMN previous_status TEXT NOT NULL DEFAULT ''",
            },
        }
        for table_name, table_additions in additions.items():
            try:
                columns = {
                    str(column["name"])
                    for column in sqlalchemy_inspect(self.engine).get_columns(table_name)
                }
            except (KeyError, OperationalError):
                continue
            for name, statement in table_additions.items():
                if name in columns:
                    continue
                try:
                    with self._lock, self.engine.begin() as connection:
                        connection.exec_driver_sql(statement)
                except OperationalError:
                    # Another API worker may have applied this additive
                    # migration concurrently.  Re-inspect and tolerate only
                    # that benign race.
                    try:
                        columns = {
                            str(column["name"])
                            for column in sqlalchemy_inspect(self.engine).get_columns(table_name)
                        }
                    except (KeyError, OperationalError):
                        raise
                    if name not in columns:
                        raise

    def _ensure_favorite_columns(self) -> None:
        """Add mutable favorite metadata to databases created by older builds."""

        try:
            columns = {
                str(column["name"])
                for column in sqlalchemy_inspect(self.engine).get_columns("favorites")
            }
        except (KeyError, OperationalError):
            return
        additions = {
            "display_name": "ALTER TABLE favorites ADD COLUMN display_name TEXT NOT NULL DEFAULT ''",
            "note": "ALTER TABLE favorites ADD COLUMN note TEXT NOT NULL DEFAULT ''",
            "tags_json": "ALTER TABLE favorites ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
        }
        for name, statement in additions.items():
            if name in columns:
                continue
            try:
                with self._lock, self.engine.begin() as connection:
                    connection.exec_driver_sql(statement)
            except OperationalError:
                # Another API worker may have applied the same additive
                # migration between inspect() and ALTER TABLE. Re-inspect and
                # tolerate only that benign race; real schema errors surface.
                try:
                    columns = {
                        str(column["name"])
                        for column in sqlalchemy_inspect(self.engine).get_columns("favorites")
                    }
                except (KeyError, OperationalError):
                    raise
                if name not in columns:
                    raise

    def save(self, view: RunView) -> None:
        payload = json.dumps(view.__dict__, ensure_ascii=False, sort_keys=True)
        with self._lock, self.engine.begin() as connection:
            connection.execute(delete(runs).where(runs.c.run_id == view.run_id))
            connection.execute(runs.insert().values(run_id=view.run_id, payload=payload))

    def get(self, run_id: str) -> RunView:
        with self.engine.connect() as connection:
            row = connection.execute(select(runs.c.payload).where(runs.c.run_id == run_id)).scalar_one()
        return RunView(**json.loads(row))

    def list(self) -> list[RunView]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(runs.c.payload)).scalars().all()
        views = [RunView(**json.loads(row)) for row in rows]
        # Child runs created by deep research are embedded in their parent
        # task and must not pollute the top-level task navigator.
        views = [item for item in views if not str((item.execution or {}).get("parent_run_id", "")).strip()]
        return sorted(views, key=lambda item: item.updated_at, reverse=True)

    # ------------------------------------------------------------------
    # Deep-thinking ledger (append-only messages/events and version chain)
    # ------------------------------------------------------------------
    @staticmethod
    def _json(value: Any, default: str = "{}") -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _decode(value: Any, fallback: Any) -> Any:
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
            return decoded
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def create_deep_session(self, *, session_id: str, parent_run_id: str, kind: str,
                            title: str = "", card_binding_id: str = "", hypothesis_id: str = "",
                            scope: dict | None = None, query_snapshot: dict | None = None,
                            result_snapshot_hash: str = "", created_by: str = "analyst",
                            idempotency_key: str = "") -> dict[str, Any]:
        now = _favorite_now_iso()
        query = dict(query_snapshot or {})
        query_hash = __import__("hashlib").sha256(self._json(query).encode()).hexdigest()
        values = {
            "session_id": str(session_id), "parent_run_id": str(parent_run_id),
            "kind": str(kind), "title": str(title or "")[:240],
            "card_binding_id": str(card_binding_id or ""), "hypothesis_id": str(hypothesis_id or ""),
            "scope_json": self._json(scope or {}), "query_snapshot_json": self._json(query),
            "query_snapshot_hash": query_hash, "result_snapshot_hash": str(result_snapshot_hash or ""),
            "working_memory_json": "{}",
            "status": "active", "created_by": str(created_by or "analyst"),
            "idempotency_key": str(idempotency_key or ""), "created_at": now, "updated_at": now,
        }
        # Keep the duplicate read outside the failed transaction.  Querying
        # on the same SQLAlchemy connection after an IntegrityError can raise
        # ``PendingRollbackError`` and turn an idempotent retry into a 500.
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    connection.execute(deep_sessions.insert().values(**values))
                    connection.execute(
                        deep_branches.insert().values(
                            branch_id=f"{session_id}:{DEFAULT_BRANCH_ID}",
                            session_id=str(session_id),
                            parent_branch_id="",
                            forked_from_message_id="",
                            title="主线",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                return self._deep_session_row(values)
            except IntegrityError:
                with self.engine.connect() as connection:
                    row = connection.execute(
                        select(deep_sessions).where(
                            deep_sessions.c.session_id == str(session_id)
                        )
                    ).mappings().one_or_none()
                if row is not None:
                    return self._deep_session_row(row)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to create deep session")

    def _deep_session_row(self, row: Any) -> dict[str, Any]:
        raw = dict(row)
        raw["scope"] = self._decode(raw.pop("scope_json", "{}"), {})
        raw["query_snapshot"] = self._decode(raw.pop("query_snapshot_json", "{}"), {})
        raw["working_memory"] = self._decode(raw.pop("working_memory_json", "{}"), {})
        return raw

    def get_deep_session(self, session_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(deep_sessions).where(deep_sessions.c.session_id == str(session_id))).mappings().one_or_none()
        return self._deep_session_row(row) if row else None

    def list_deep_sessions(self, parent_run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(deep_sessions).where(deep_sessions.c.parent_run_id == str(parent_run_id)).order_by(deep_sessions.c.updated_at.desc())).mappings().all()
        return [self._deep_session_row(row) for row in rows]

    def list_deep_sessions_history(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        kinds: Sequence[str] | None = None,
        include_archived: bool = True,
        tenant_id: str = "",
        workspace_id: str = "",
        project_id: str = "",
        profile_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return recent directed deep-research sessions across parent runs."""

        bounded_limit = max(1, min(int(limit or 200), 500))
        bounded_offset = max(0, int(offset or 0))
        wanted_kinds = {
            str(item or "").strip().lower().replace("_", "-")
            for item in (kinds or ())
            if str(item or "").strip()
        }
        clauses: list[Any] = []
        if wanted_kinds:
            clauses.append(deep_sessions.c.kind.in_(sorted(wanted_kinds)))
        if not include_archived:
            clauses.append(deep_sessions.c.status != "archived")
        statement = select(deep_sessions)
        if clauses:
            statement = statement.where(*clauses)
        statement = statement.order_by(deep_sessions.c.updated_at.desc())
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        requested_scope = {
            "tenant_id": str(tenant_id or "").strip(),
            "workspace_id": str(workspace_id or "").strip(),
            "project_id": str(project_id or "").strip(),
            "profile_id": str(profile_id or "").strip(),
        }
        scope_supplied = any(requested_scope.values())
        sessions: list[dict[str, Any]] = []
        for raw_row in rows:
            row = self._deep_session_row(raw_row)
            item_scope = row.get("scope")
            item_scope = item_scope if isinstance(item_scope, Mapping) else {}
            normalized_item_scope = {
                key: str(item_scope.get(key, "") or "").strip()
                for key in requested_scope
            }
            if scope_supplied:
                if any(
                    value and normalized_item_scope[key] != value
                    for key, value in requested_scope.items()
                ):
                    continue
            elif any(normalized_item_scope.values()):
                # An unscoped history request may read only legacy/unscoped
                # sessions.  Treating an empty request as a wildcard would
                # expose every tenant in local-header deployments.
                continue
            sessions.append(row)
        sessions = sessions[bounded_offset : bounded_offset + bounded_limit]
        parent_ids = sorted(
            {
                str(item.get("parent_run_id", "") or "").strip()
                for item in sessions
                if str(item.get("parent_run_id", "") or "").strip()
            }
        )
        topics: dict[str, str] = {}
        if parent_ids:
            with self.engine.connect() as connection:
                run_rows = connection.execute(
                    select(runs.c.run_id, runs.c.payload).where(
                        runs.c.run_id.in_(parent_ids)
                    )
                ).all()
            for run_id, payload in run_rows:
                try:
                    data = json.loads(payload) if isinstance(payload, str) else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    data = {}
                if isinstance(data, Mapping):
                    topics[str(run_id)] = str(data.get("topic", "") or "").strip()
        enriched: list[dict[str, Any]] = []
        for item in sessions:
            row = dict(item)
            parent_id = str(row.get("parent_run_id", "") or "").strip()
            snapshot = (
                row.get("query_snapshot")
                if isinstance(row.get("query_snapshot"), Mapping)
                else {}
            )
            context = (
                snapshot.get("context")
                if isinstance(snapshot.get("context"), Mapping)
                else {}
            )
            focused = context.get("focused_equipment")
            focused = focused if isinstance(focused, Mapping) else {}
            candidate = context.get("candidate")
            candidate = candidate if isinstance(candidate, Mapping) else {}
            query_text = str(snapshot.get("query", "") or "").strip()
            run_topic = topics.get(parent_id, "")
            capability_name = next(
                (
                    str(value).strip()
                    for value in (
                        context.get("capability_name"),
                        focused.get("name"),
                        focused.get("title"),
                        candidate.get("name"),
                        candidate.get("title"),
                        row.get("title"),
                    )
                    if str(value or "").strip()
                ),
                "",
            )
            row["run_id"] = parent_id
            row["run_topic"] = run_topic
            row["query"] = query_text or run_topic
            row["query_group_key"] = (
                __import__("hashlib")
                .sha256(str(row["query"] or "").strip().encode("utf-8"))
                .hexdigest()
                if str(row["query"] or "").strip()
                else str(row.get("query_snapshot_hash", "") or parent_id)
            )
            row["capability_name"] = capability_name
            row["capability_id"] = str(
                context.get("capability_id")
                or candidate.get("capability_id")
                or focused.get("capability_id")
                or ""
            ).strip()
            enriched.append(row)
        return enriched

    def update_deep_session(
        self,
        session_id: str,
        *,
        status: str | None = None,
        result_snapshot_hash: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": _favorite_now_iso()}
        if status is not None:
            normalized = str(status).strip().lower()
            if normalized not in {
                "active",
                "running",
                "completed",
                "failed",
                "cancelled",
                "partial",
                "blocked",
                "archived",
            }:
                raise ValueError("invalid deep session status")
            values["status"] = normalized
        if title is not None:
            values["title"] = str(title or "").strip()[:240]
        if result_snapshot_hash is not None:
            values["result_snapshot_hash"] = str(result_snapshot_hash or "")[:128]
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    # Cancellation is a durable terminal fence.  A detached
                    # deep worker can finish after an analyst cancels the
                    # session; returning the current row instead of applying
                    # the stale status prevents the worker from resurrecting
                    # a cancelled session (and keeps restart recovery
                    # deterministic).  Other statuses remain intentionally
                    # reopenable so an analyst can continue a failed/partial
                    # conversation explicitly.
                    current = connection.execute(
                        select(deep_sessions).where(
                            deep_sessions.c.session_id == str(session_id)
                        )
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    current_status = str(current.get("status", "")).strip().lower()
                    requested_status = str(values.get("status", "")).strip().lower()
                    if (
                        requested_status
                        and current_status == "cancelled"
                        and requested_status not in {"cancelled", "archived"}
                    ):
                        return self._deep_session_row(current)
                    # Archiving is a management state as well as a terminal
                    # worker fence.  An expert may explicitly restore it to
                    # active, but a late worker must not turn an archived
                    # transcript back into completed/running.
                    if (
                        requested_status
                        and current_status == "archived"
                        and requested_status not in {"archived", "active"}
                    ):
                        return self._deep_session_row(current)
                    result = connection.execute(
                        update(deep_sessions)
                        .where(deep_sessions.c.session_id == str(session_id))
                        .values(**values)
                    )
                    if not result.rowcount:
                        return None
                return self.get_deep_session(session_id)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def update_deep_working_memory(
        self, session_id: str, memory: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Replace the bounded model-facing checkpoint for one conversation."""

        encoded = self._json(dict(memory or {}), "{}")
        if len(encoded) > 24000:
            raise ValueError("deep working memory exceeds 24000 characters")
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(deep_sessions)
                .where(deep_sessions.c.session_id == str(session_id))
                .values(
                    working_memory_json=encoded,
                    updated_at=_favorite_now_iso(),
                )
            )
            if not result.rowcount:
                return None
        return self.get_deep_session(session_id)

    def update_deep_branch_working_memory(
        self,
        session_id: str,
        *,
        branch_id: str,
        checkpoint: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Atomically upsert one branch checkpoint without losing siblings."""

        session_key = str(session_id)
        wanted = normalize_branch_id(branch_id)
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    row = connection.execute(
                        select(deep_sessions).where(
                            deep_sessions.c.session_id == session_key
                        )
                    ).mappings().one_or_none()
                    if row is None:
                        return None
                    current_encoded = str(row.get("working_memory_json", "{}") or "{}")
                    current = self._decode(current_encoded, {})
                    merged = merge_branch_working_memory(
                        current if isinstance(current, Mapping) else {},
                        wanted,
                        checkpoint,
                    )
                    encoded = self._json(merged, "{}")
                    if len(encoded) > 24000:
                        raise ValueError("deep working memory exceeds 24000 characters")
                    result = connection.execute(
                        update(deep_sessions)
                        .where(
                            deep_sessions.c.session_id == session_key,
                            deep_sessions.c.working_memory_json == current_encoded,
                        )
                        .values(
                            working_memory_json=encoded,
                            updated_at=_favorite_now_iso(),
                        )
                    )
                    if not result.rowcount:
                        continue
                return self.get_deep_session(session_key)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def create_deep_branch(
        self,
        *,
        session_id: str,
        branch_id: str,
        forked_from_message_id: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Create a conversation branch rooted at an existing visible message."""

        session_key = str(session_id)
        logical_branch = normalize_branch_id(branch_id)
        storage_branch = f"{session_key}:{logical_branch}"
        now = _favorite_now_iso()
        with self._lock, self.engine.begin() as connection:
            existing = connection.execute(
                select(deep_branches).where(deep_branches.c.branch_id == storage_branch)
            ).mappings().one_or_none()
            if existing is not None:
                raise ValueError("deep branch id already exists")
            source = connection.execute(
                select(deep_messages).where(
                    deep_messages.c.session_id == session_key,
                    deep_messages.c.message_id == str(forked_from_message_id),
                )
            ).mappings().one_or_none()
            if source is None:
                raise ValueError("fork source message not found")
            parent_branch = normalize_branch_id(source.get("branch_id"))
            values = {
                "branch_id": storage_branch,
                "session_id": session_key,
                "parent_branch_id": parent_branch,
                "forked_from_message_id": str(forked_from_message_id),
                "title": str(title or "探索分支").strip()[:240],
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            connection.execute(deep_branches.insert().values(**values))
            session_row = connection.execute(
                select(deep_sessions).where(deep_sessions.c.session_id == session_key)
            ).mappings().one_or_none()
            if session_row is not None:
                encoded_memory = str(
                    session_row.get("working_memory_json", "{}") or "{}"
                )
                stored_memory = self._decode(encoded_memory, {})
                if isinstance(stored_memory, Mapping):
                    branches = stored_memory.get("branches")
                    if isinstance(branches, Mapping):
                        parent_checkpoint = branches.get(parent_branch)
                    else:
                        parent_checkpoint = (
                            stored_memory
                            if normalize_branch_id(stored_memory.get("branch_id"))
                            == parent_branch
                            else None
                        )
                    if isinstance(parent_checkpoint, Mapping):
                        checkpoint_source = parent_checkpoint.get(
                            "source_checkpoint", {}
                        )
                        checkpoint_source = (
                            checkpoint_source
                            if isinstance(checkpoint_source, Mapping)
                            else {}
                        )
                        checkpoint_sequence = int(
                            checkpoint_source.get("assistant_sequence", 0) or 0
                        )
                        fork_sequence = int(source.get("sequence", 0) or 0)
                        # A latest checkpoint can seed a fork only when it was
                        # produced no later than the selected fork message.
                        # This prevents later main-line decisions from leaking
                        # into a branch created from an older point in history.
                        if not checkpoint_sequence or checkpoint_sequence <= fork_sequence:
                            inherited = dict(parent_checkpoint)
                            inherited["branch_id"] = logical_branch
                            inherited["inherited_from"] = {
                                "branch_id": parent_branch,
                                "message_id": str(forked_from_message_id)[:128],
                                "sequence": fork_sequence,
                            }
                            merged = merge_branch_working_memory(
                                stored_memory,
                                logical_branch,
                                inherited,
                            )
                            next_encoded = self._json(merged, "{}")
                            if len(next_encoded) > 24000:
                                raise ValueError(
                                    "deep working memory exceeds 24000 characters"
                                )
                            connection.execute(
                                update(deep_sessions)
                                .where(deep_sessions.c.session_id == session_key)
                                .values(
                                    working_memory_json=next_encoded,
                                    updated_at=now,
                                )
                            )
        return self._deep_branch_row(values)

    @staticmethod
    def _deep_branch_row(row: Any) -> dict[str, Any]:
        result = dict(row)
        stored = str(result.get("branch_id", ""))
        prefix = f"{result.get('session_id', '')}:"
        if stored.startswith(prefix):
            result["branch_id"] = stored[len(prefix):]
        return result

    def list_deep_branches(self, session_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(deep_branches)
                .where(deep_branches.c.session_id == str(session_id))
                .order_by(deep_branches.c.created_at)
            ).mappings().all()
        if not rows:
            return [{
                "branch_id": DEFAULT_BRANCH_ID,
                "session_id": str(session_id),
                "parent_branch_id": "",
                "forked_from_message_id": "",
                "title": "主线",
                "status": "active",
            }]
        return [self._deep_branch_row(row) for row in rows]

    def delete_deep_session(
        self, session_id: str, *, parent_run_id: str = ""
    ) -> dict[str, Any] | None:
        """Permanently remove one idle conversation and its transient ledger.

        Capability versions are intentionally retained: deleting a transcript
        must not silently remove a capability card that an expert already
        fixed to the capability page.  A live worker is fenced so it cannot
        append orphaned messages after the session row disappears.
        """

        session_key = str(session_id)
        parent_key = str(parent_run_id or "").strip()
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    clauses = [deep_sessions.c.session_id == session_key]
                    if parent_key:
                        clauses.append(deep_sessions.c.parent_run_id == parent_key)
                    current = connection.execute(
                        select(deep_sessions).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None

                    jobs = connection.execute(
                        select(deep_jobs).where(
                            deep_jobs.c.session_id == session_key
                        )
                    ).mappings().all()
                    live_jobs = [
                        row
                        for row in jobs
                        if str(row.get("status", "")).strip().lower()
                        in {"queued", "running"}
                        or (
                            str(row.get("status", "")).strip().lower()
                            == "completed"
                            and str(row.get("stage", "")).strip().lower()
                            not in {"", "publish"}
                        )
                    ]
                    if live_jobs:
                        raise ValueError(
                            "deep session has a running job and cannot be deleted"
                        )

                    job_ids = [str(row.get("job_id", "")) for row in jobs]
                    connection.execute(
                        delete(deep_messages).where(
                            deep_messages.c.session_id == session_key
                        )
                    )
                    connection.execute(
                        delete(deep_branches).where(
                            deep_branches.c.session_id == session_key
                        )
                    )
                    connection.execute(
                        delete(deep_steers).where(
                            deep_steers.c.session_id == session_key
                        )
                    )
                    event_filter = deep_events.c.session_id == session_key
                    if job_ids:
                        event_filter = event_filter | deep_events.c.job_id.in_(job_ids)
                        connection.execute(
                            delete(deep_run_links).where(
                                deep_run_links.c.job_id.in_(job_ids)
                            )
                        )
                    connection.execute(delete(deep_events).where(event_filter))
                    connection.execute(
                        delete(deep_jobs).where(deep_jobs.c.session_id == session_key)
                    )
                    idempotency_resources = [session_key, *job_ids]
                    connection.execute(
                        delete(deep_idempotency).where(
                            (deep_idempotency.c.scope_key == session_key)
                            | deep_idempotency.c.resource_id.in_(
                                idempotency_resources
                            )
                        )
                    )
                    connection.execute(
                        delete(deep_sessions).where(
                            deep_sessions.c.session_id == session_key
                        )
                    )
                return self._deep_session_row(current)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def _resolve_deep_parent_message(
        self,
        connection: Any,
        *,
        session_id: str,
        branch_id: str,
        parent_message_id: str = "",
    ) -> str:
        """Resolve a parent on the exact visible branch captured by the client."""

        rows = connection.execute(
            select(deep_messages)
            .where(deep_messages.c.session_id == str(session_id))
            .order_by(deep_messages.c.sequence)
        ).mappings().all()
        branch_rows = connection.execute(
            select(deep_branches)
            .where(deep_branches.c.session_id == str(session_id))
            .order_by(deep_branches.c.created_at)
        ).mappings().all()
        logical_branches = [self._deep_branch_row(row) for row in branch_rows]
        visible = branch_message_path(rows, branch_id, logical_branches)
        requested = str(parent_message_id or "").strip()
        if requested:
            if not any(str(row.get("message_id", "")) == requested for row in visible):
                raise ValueError("parent message is not visible on the selected branch")
            return requested
        same_branch = [
            row
            for row in rows
            if normalize_branch_id(row.get("branch_id")) == branch_id
        ]
        if same_branch:
            return str(same_branch[-1].get("message_id", "") or "")
        branch = next(
            (
                row
                for row in logical_branches
                if normalize_branch_id(row.get("branch_id")) == branch_id
            ),
            None,
        )
        return str((branch or {}).get("forked_from_message_id", "") or "")

    def append_deep_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        status: str = "completed",
        artifact_refs: list[str] | None = None,
        version_refs: list[str] | None = None,
        parent_message_id: str = "",
        branch_id: str = DEFAULT_BRANCH_ID,
        turn_id: str = "",
        message_kind: str = "message",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _favorite_now_iso()
        normalized_branch = normalize_branch_id(branch_id)
        normalized_role = str(role or "user").strip().lower()
        for attempt in range(5):
            try:
                with self._lock, self.engine.begin() as connection:
                    # ``turn_id`` is the durable idempotency boundary for a
                    # visible turn.  A worker can finish writing the assistant
                    # row and then fail while persisting working memory; an
                    # explicit retry must update/replay that row instead of
                    # appending a second assistant message.  Keep the lookup
                    # scoped to role/kind/branch so one turn can still carry
                    # its user and assistant messages independently.
                    turn_key = str(turn_id or "").strip()[:128]
                    message_kind_key = str(message_kind or "message")[:32]
                    if turn_key and normalized_role == "assistant":
                        existing = connection.execute(
                            select(deep_messages).where(
                                deep_messages.c.session_id == str(session_id),
                                deep_messages.c.turn_id == turn_key,
                                deep_messages.c.branch_id == normalized_branch,
                                deep_messages.c.message_kind == message_kind_key,
                                deep_messages.c.role == normalized_role,
                            ).order_by(deep_messages.c.sequence).limit(1)
                        ).mappings().first()
                        if existing is not None:
                            existing_dict = dict(existing)
                            existing_artifacts = self._decode(
                                existing_dict.get("artifact_refs_json", "[]"), []
                            )
                            existing_versions = self._decode(
                                existing_dict.get("version_refs_json", "[]"), []
                            )
                            # Preserve references already published by the
                            # first attempt while allowing a retry to add a
                            # version/artifact that became durable later.
                            merged_artifacts = list(existing_artifacts or [])
                            for value in list(artifact_refs or []):
                                if value not in merged_artifacts:
                                    merged_artifacts.append(value)
                            merged_artifacts = merged_artifacts[:16]
                            merged_versions = list(existing_versions or [])
                            for value in list(version_refs or []):
                                if value not in merged_versions:
                                    merged_versions.append(value)
                            merged_versions = merged_versions[:16]
                            merged_metadata = self._decode(
                                existing_dict.get("metadata_json", "{}"), {}
                            )
                            if not isinstance(merged_metadata, dict):
                                merged_metadata = {}
                            if isinstance(metadata, Mapping):
                                merged_metadata.update(dict(metadata))
                            update_values = {
                                "content": str(content)[:8000],
                                "status": str(status),
                                "artifact_refs_json": self._json(merged_artifacts, "[]"),
                                "version_refs_json": self._json(merged_versions, "[]"),
                                "metadata_json": self._json(merged_metadata, "{}"),
                            }
                            connection.execute(
                                update(deep_messages)
                                .where(
                                    deep_messages.c.session_id == str(session_id),
                                    deep_messages.c.sequence
                                    == int(existing_dict.get("sequence", 0) or 0),
                                )
                                .values(**update_values)
                            )
                            existing_dict.update(update_values)
                            existing_dict["artifact_refs"] = merged_artifacts
                            existing_dict["version_refs"] = merged_versions
                            existing_dict["metadata"] = merged_metadata
                            existing_dict.pop("artifact_refs_json", None)
                            existing_dict.pop("version_refs_json", None)
                            existing_dict.pop("metadata_json", None)
                            return existing_dict
                    seq = (connection.execute(select(deep_messages.c.sequence).where(deep_messages.c.session_id == str(session_id)).order_by(deep_messages.c.sequence.desc()).limit(1)).scalar_one_or_none() or 0) + 1
                    resolved_parent = self._resolve_deep_parent_message(
                        connection,
                        session_id=str(session_id),
                        branch_id=normalized_branch,
                        parent_message_id=parent_message_id,
                    )
                    values = {
                        "session_id": str(session_id),
                        "sequence": seq,
                        "message_id": f"message-{uuid4().hex}",
                        "parent_message_id": resolved_parent,
                        "branch_id": normalized_branch,
                        "turn_id": turn_key,
                        "message_kind": message_kind_key,
                        "role": normalized_role,
                        "content": str(content)[:8000],
                        "status": str(status),
                        "artifact_refs_json": self._json(list(artifact_refs or []), "[]"),
                        "version_refs_json": self._json(list(version_refs or []), "[]"),
                        "metadata_json": self._json(dict(metadata or {}), "{}"),
                        "created_at": now,
                    }
                    connection.execute(deep_messages.insert().values(**values))
                return {
                    **values,
                    "artifact_refs": self._decode(values["artifact_refs_json"], []),
                    "version_refs": self._decode(values["version_refs_json"], []),
                    "metadata": self._decode(values["metadata_json"], {}),
                }
            except IntegrityError:
                if attempt >= 4: raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 4:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to append deep message")

    def list_deep_messages(self, session_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(deep_messages).where(deep_messages.c.session_id == str(session_id), deep_messages.c.sequence > int(after)).order_by(deep_messages.c.sequence)).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            item["artifact_refs"] = self._decode(item.pop("artifact_refs_json", "[]"), [])
            item["version_refs"] = self._decode(item.pop("version_refs_json", "[]"), [])
            item["metadata"] = self._decode(item.pop("metadata_json", "{}"), {})
            result.append(item)
        return result

    def create_or_get_deep_job(
        self,
        *,
        job_id: str,
        parent_run_id: str,
        session_id: str = "",
        kind: str = "deep_divergence_v1",
        idempotency_key: str = "",
        fingerprint: str = "",
        payload: dict | None = None,
        child_run_id: str = "",
        parent_job_id: str = "",
        branch_id: str = DEFAULT_BRANCH_ID,
        root_message_id: str = "",
        checkpoint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _favorite_now_iso()
        fingerprint_value = str(fingerprint or "").strip()
        values = {
            "job_id": str(job_id),
            "parent_run_id": str(parent_run_id),
            "session_id": str(session_id or ""),
            "child_run_id": str(child_run_id or ""),
            "parent_job_id": str(parent_job_id or ""),
            "branch_id": normalize_branch_id(branch_id),
            "root_message_id": str(root_message_id or "")[:128],
            "checkpoint_json": self._json(dict(checkpoint or {})),
            "state_version": 1,
            "claim_token": "",
            "steer_closed": 0,
            "kind": str(kind),
            "stage": "queued",
            "status": "queued",
            "idempotency_key": str(idempotency_key or ""),
            "fingerprint": fingerprint_value,
            "payload_json": self._json(payload or {}),
            "error": "",
            "created_at": now,
            "updated_at": now,
        }
        # The API normally claims the request in ``deep_idempotency`` before
        # reaching this method.  Keep a database-level fence here as well:
        # direct repository users and two API processes can race between their
        # read and insert.  On a uniqueness conflict the competing row may
        # have a different job_id, so looking up only ``job_id`` (the previous
        # implementation) could raise ``NoResultFound`` and lose the job.
        parent = str(parent_run_id)
        idem = str(idempotency_key or "")
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    if idem:
                        existing = connection.execute(
                            select(deep_jobs).where(
                                deep_jobs.c.parent_run_id == parent,
                                deep_jobs.c.idempotency_key == idem,
                            )
                        ).mappings().one_or_none()
                        if existing:
                            return self._deep_job_row(existing)
                    if fingerprint_value:
                        existing = connection.execute(
                            select(deep_jobs).where(
                                deep_jobs.c.parent_run_id == parent,
                                deep_jobs.c.fingerprint == fingerprint_value,
                            ).order_by(deep_jobs.c.created_at, deep_jobs.c.job_id).limit(1)
                        ).mappings().first()
                        if existing:
                            return self._deep_job_row(existing)
                    connection.execute(deep_jobs.insert().values(**values))
                return self._deep_job_row(values)
            except IntegrityError:
                # Re-read outside the failed transaction.  This handles both
                # the composite idempotency constraint and a duplicate job_id
                # generated by a retry.
                with self.engine.connect() as connection:
                    row = None
                    if idem:
                        row = connection.execute(
                            select(deep_jobs).where(
                                deep_jobs.c.parent_run_id == parent,
                                deep_jobs.c.idempotency_key == idem,
                            )
                        ).mappings().one_or_none()
                    if row is None:
                        row = connection.execute(
                            select(deep_jobs).where(deep_jobs.c.job_id == str(job_id))
                        ).mappings().one_or_none()
                if row is not None:
                    return self._deep_job_row(row)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to create deep job")

    def save_deep_run_link(self, *, parent_run_id: str, child_run_id: str, job_id: str = "", relation: str = "deep_research") -> dict[str, Any]:
        values = {"parent_run_id": str(parent_run_id), "child_run_id": str(child_run_id), "job_id": str(job_id or ""), "relation": str(relation), "created_at": _favorite_now_iso()}
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    try: connection.execute(deep_run_links.insert().values(**values))
                    except IntegrityError: pass
                return values
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return values

    def list_deep_run_links(self, parent_run_id: str = "") -> list[dict[str, Any]]:
        stmt = select(deep_run_links)
        if parent_run_id: stmt = stmt.where(deep_run_links.c.parent_run_id == str(parent_run_id))
        with self.engine.connect() as connection: rows = connection.execute(stmt.order_by(deep_run_links.c.created_at.desc())).mappings().all()
        return [dict(row) for row in rows]

    def get_deep_job_by_fingerprint(
        self, parent_run_id: str, fingerprint: str
    ) -> dict[str, Any] | None:
        """Return the canonical job for a non-empty request fingerprint.

        ``first()`` is intentional for compatibility with databases created
        before the partial unique index was introduced; those may contain
        duplicate legacy rows, but a caller still gets a deterministic winner
        and can converge future retries on it.
        """

        value = str(fingerprint or "").strip()
        if not value:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(
                select(deep_jobs)
                .where(
                    deep_jobs.c.parent_run_id == str(parent_run_id),
                    deep_jobs.c.fingerprint == value,
                )
                .order_by(deep_jobs.c.created_at, deep_jobs.c.job_id)
                .limit(1)
            ).mappings().first()
        return self._deep_job_row(row) if row is not None else None

    def _deep_job_row(self, row: Any) -> dict[str, Any]:
        raw = dict(row)
        raw["payload"] = self._decode(raw.pop("payload_json", "{}"), {})
        raw["checkpoint"] = self._decode(raw.pop("checkpoint_json", "{}"), {})
        raw["steer_closed"] = bool(raw.get("steer_closed", 0))
        return raw

    def get_deep_job(self, job_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(deep_jobs).where(deep_jobs.c.job_id == str(job_id))).mappings().one_or_none()
        return self._deep_job_row(row) if row else None

    def list_deep_jobs(self, parent_run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(deep_jobs).where(deep_jobs.c.parent_run_id == str(parent_run_id)).order_by(deep_jobs.c.created_at.desc())).mappings().all()
        return [self._deep_job_row(row) for row in rows]

    def list_recoverable_deep_jobs(self) -> list[dict[str, Any]]:
        """Return deep jobs that may need a dispatcher after process restart.

        The API's deep dispatcher is intentionally in-process, so its thread
        table disappears when a worker is restarted.  Keep the recovery query
        in the durable repository rather than deriving it from sidecar files;
        terminal jobs are never re-enqueued and parent/child identity remains
        bound to the SQLite row.
        """

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(deep_jobs)
                .where(deep_jobs.c.status.in_(("queued", "running", "partial")))
                .order_by(deep_jobs.c.created_at)
            ).mappings().all()
        return [self._deep_job_row(row) for row in rows]

    def touch_deep_job(
        self,
        job_id: str,
        *,
        expected_statuses: Sequence[str] = ("queued", "running", "partial"),
        claim_token: str = "",
    ) -> dict[str, Any] | None:
        """Refresh a live deep-job lease without emitting a public event.

        Long-running child monitors otherwise leave ``updated_at`` frozen
        while waiting for the normal research worker.  Restart recovery could
        then reclaim a healthy job as stale and execute it twice.  This tiny
        heartbeat is intentionally separate from ``update_deep_job`` so lease
        refreshes do not flood the SSE stream with duplicate stage summaries.
        """

        statuses = tuple(
            str(item).strip().lower()
            for item in expected_statuses
            if str(item).strip()
        )
        if not statuses:
            return self.get_deep_job(job_id)
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    clauses = [
                        deep_jobs.c.job_id == str(job_id),
                        deep_jobs.c.status.in_(statuses),
                    ]
                    if str(claim_token or "").strip():
                        clauses.append(
                            deep_jobs.c.claim_token == str(claim_token).strip()
                        )
                    result = connection.execute(
                        update(deep_jobs)
                        .where(*clauses)
                        .values(updated_at=_favorite_now_iso())
                    )
                    if not result.rowcount:
                        return self.get_deep_job(job_id)
                return self.get_deep_job(job_id)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def update_deep_job(
        self,
        job_id: str,
        *,
        stage: str | None = None,
        status: str | None = None,
        error: str | None = None,
        child_run_id: str | None = None,
        session_id: str | None = None,
        checkpoint: Mapping[str, Any] | None = None,
        claim_token: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": _favorite_now_iso()}
        if stage is not None:
            normalized_stage = str(stage).strip().lower()
            if normalized_stage not in {
                "context",
                "s3_divergence",
                "council_critique",
                "s4_mapping",
                "retrieval",
                "s5_adjudication",
                "s6_authoring",
                "validation",
                "publish",
                "queued",
            }:
                raise ValueError("invalid deep job stage")
            values["stage"] = normalized_stage
        if status is not None:
            normalized_status = str(status).strip().lower()
            if normalized_status not in {
                "queued",
                "running",
                "completed",
                "partial",
                "failed",
                "blocked",
                "cancelled",
            }:
                raise ValueError("invalid deep job status")
            values["status"] = normalized_status
        for key, value in (("error", error), ("child_run_id", child_run_id)):
            if value is not None: values[key] = str(value)[:4000]
        if session_id is not None:
            values["session_id"] = str(session_id)[:128]
        if checkpoint is not None:
            encoded_checkpoint = self._json(dict(checkpoint), "{}")
            if len(encoded_checkpoint) > 64000:
                raise ValueError("deep job checkpoint exceeds 64000 characters")
            values["checkpoint_json"] = encoded_checkpoint
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    # Terminal cancellation/failure/verification boundaries
                    # are monotonic.  A detached API worker can finish a
                    # stale child after another process cancelled the job;
                    # never let that late writer resurrect the row.  Reads of
                    # the current row are returned to the caller so it can
                    # still render the authoritative terminal state.
                    current_row = connection.execute(
                        select(deep_jobs).where(deep_jobs.c.job_id == str(job_id))
                    ).mappings().one_or_none()
                    if current_row is None:
                        return None
                    current_status = str(current_row.get("status", "")).strip().lower()
                    current_stage = str(current_row.get("stage", "")).strip().lower()
                    expected_claim = str(claim_token or "").strip()
                    current_claim = str(current_row.get("claim_token", "") or "").strip()
                    if expected_claim and current_claim != expected_claim:
                        return self._deep_job_row(
                            {**dict(current_row), "_claim_rejected": True}
                        )
                    # ``completed`` is a per-stage status (S3/S4/S6 and
                    # retrieval all emit it), so it is terminal only once the
                    # publish stage is reached.  Cancellation, however, is a
                    # global terminal fence and must not be resurrected by a
                    # late child/dispatcher callback.
                    terminal_now = current_status in {
                        "failed",
                        "blocked",
                        "cancelled",
                    } or (
                        current_status == "partial"
                        and current_stage in {"validation", "publish"}
                    ) or (
                        current_stage == "publish" and current_status == "completed"
                    )
                    if terminal_now:
                        # Ordinary worker updates freeze at the first terminal
                        # publish boundary.  Comparing status alone is
                        # insufficient because a late stage can also report
                        # ``completed`` while replacing the final checkpoint.
                        # An identical retry is satisfied by returning the
                        # current row; explicit reruns reopen it through
                        # ``requeue_deep_job``.
                        terminal_row = self._deep_job_row(current_row)
                        # This marker is an in-process hand-off to callers
                        # that need to distinguish an idempotent terminal
                        # replay from the transition that first crossed the
                        # fence. It is never persisted and must be stripped
                        # before a public/API projection is built.
                        terminal_row["_already_terminal"] = True
                        return terminal_row
                    current_version = max(1, int(current_row.get("state_version", 1) or 1))
                    clauses = [
                        deep_jobs.c.job_id == str(job_id),
                        deep_jobs.c.state_version == current_version,
                    ]
                    if expected_claim:
                        clauses.append(deep_jobs.c.claim_token == expected_claim)
                    result = connection.execute(
                        update(deep_jobs)
                        .where(*clauses)
                        .values(**values, state_version=current_version + 1)
                    )
                    if not result.rowcount:
                        refreshed = connection.execute(
                            select(deep_jobs).where(
                                deep_jobs.c.job_id == str(job_id)
                            )
                        ).mappings().one_or_none()
                        if refreshed is None:
                            return None
                        rejected = expected_claim and str(
                            refreshed.get("claim_token", "") or ""
                        ).strip() != expected_claim
                        refreshed_row = self._deep_job_row(
                            {**dict(refreshed), "_claim_rejected": bool(rejected)}
                        )
                        refreshed_status = str(
                            refreshed_row.get("status", "") or ""
                        ).strip().lower()
                        refreshed_stage = str(
                            refreshed_row.get("stage", "") or ""
                        ).strip().lower()
                        refreshed_terminal = refreshed_status in {
                            "failed",
                            "blocked",
                            "cancelled",
                        } or (
                            refreshed_status == "partial"
                            and refreshed_stage in {"validation", "publish"}
                        ) or (
                            refreshed_status == "completed"
                            and refreshed_stage == "publish"
                        )
                        if refreshed_terminal:
                            refreshed_row["_already_terminal"] = True
                        return refreshed_row
                return self.get_deep_job(job_id)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def bind_deep_job_session(
        self,
        job_id: str,
        *,
        parent_run_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Atomically bind a reserved job and inherit a concurrent cancel."""

        job_key = str(job_id)
        parent_key = str(parent_run_id)
        session_key = str(session_id)
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(deep_jobs).where(
                            deep_jobs.c.job_id == job_key,
                            deep_jobs.c.parent_run_id == parent_key,
                        )
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    existing_session = str(current.get("session_id", "") or "").strip()
                    if existing_session and existing_session != session_key:
                        raise ValueError("deep job is already bound to another session")
                    session = connection.execute(
                        select(deep_sessions).where(
                            deep_sessions.c.session_id == session_key,
                            deep_sessions.c.parent_run_id == parent_key,
                        )
                    ).mappings().one_or_none()
                    if session is None:
                        raise ValueError("deep session not found for job binding")
                    current_version = max(
                        1, int(current.get("state_version", 1) or 1)
                    )
                    result = connection.execute(
                        update(deep_jobs)
                        .where(
                            deep_jobs.c.job_id == job_key,
                            deep_jobs.c.parent_run_id == parent_key,
                            deep_jobs.c.state_version == current_version,
                        )
                        .values(
                            session_id=session_key,
                            state_version=current_version + 1,
                            updated_at=_favorite_now_iso(),
                        )
                    )
                    if not result.rowcount:
                        continue
                    if str(current.get("status", "") or "").strip().lower() == "cancelled":
                        connection.execute(
                            update(deep_sessions)
                            .where(deep_sessions.c.session_id == session_key)
                            .values(status="cancelled", updated_at=_favorite_now_iso())
                        )
                return self.get_deep_job(job_key)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def requeue_deep_job(
        self,
        job_id: str,
        *,
        parent_run_id: str = "",
        allowed_statuses: Sequence[str] = ("partial", "failed", "blocked", "cancelled"),
    ) -> dict[str, Any] | None:
        """Requeue an explicitly retried terminal/partial deep job.

        ``update_deep_job`` intentionally fences terminal publish rows, so a
        stale worker cannot resurrect them.  An analyst retry is a deliberate
        mutation and needs a separate conditional operation that can reopen
        only the bounded retry states.  The existing job id/fingerprint is
        preserved, preventing duplicate child runs and keeping the lineage
        auditable.
        """

        statuses = tuple(
            str(item).strip().lower()
            for item in allowed_statuses
            if str(item).strip()
        ) or ("partial", "failed", "blocked", "cancelled")
        parent = str(parent_run_id or "").strip()
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    clauses = [
                        deep_jobs.c.job_id == str(job_id),
                        deep_jobs.c.status.in_(statuses),
                    ]
                    if parent:
                        clauses.append(deep_jobs.c.parent_run_id == parent)
                    current = connection.execute(
                        select(deep_jobs).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    current_status = str(current.get("status", "")).strip().lower()
                    current_stage = str(current.get("stage", "")).strip().lower()
                    # ``partial`` is also used as a live hand-off marker
                    # while S3/S4/S6 work is still running.  Only the
                    # validation/publish boundary is retryable; reopening an
                    # earlier partial row would clear a live claim and let a
                    # second dispatcher execute the same child concurrently.
                    if current_status == "partial" and current_stage not in {
                        "validation",
                        "publish",
                    }:
                        # A live worker keeps its claim while reporting a
                        # stage-level partial hand-off (notably S6 child
                        # authoring).  Do not clear that lease and start a
                        # second dispatcher.  A row without a claim is a
                        # restart/legacy projection and may be explicitly
                        # resumed; the normal worker claim fence still
                        # protects active rows.
                        if str(current.get("claim_token", "") or "").strip():
                            return None
                    if current_status == "cancelled":
                        session_key = str(current.get("session_id", "") or "").strip()
                        if session_key:
                            connection.execute(
                                update(deep_sessions)
                                .where(
                                    deep_sessions.c.session_id == session_key,
                                    deep_sessions.c.parent_run_id
                                    == str(current.get("parent_run_id", "")),
                                    deep_sessions.c.status == "cancelled",
                                )
                                .values(
                                    status="active",
                                    updated_at=_favorite_now_iso(),
                                )
                            )
                    current_version = max(
                        1, int(current.get("state_version", 1) or 1)
                    )
                    clauses.extend(
                        (
                            deep_jobs.c.state_version == current_version,
                            deep_jobs.c.stage == current_stage,
                        )
                    )
                    # Keep the child identity and payload.  A retry resumes
                    # validation/projection when a child already completed;
                    # recovery will recreate the child only when no id exists.
                    result = connection.execute(
                        update(deep_jobs)
                        .where(*clauses)
                        .values(
                            stage="queued",
                            status="queued",
                            error="",
                            claim_token="",
                            state_version=current_version + 1,
                            steer_closed=0,
                            updated_at=_favorite_now_iso(),
                        )
                    )
                    if not result.rowcount:
                        return None
                return self.get_deep_job(job_id)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def claim_deep_job(
        self,
        job_id: str,
        *,
        recover: bool = False,
        stale_after_seconds: float = 90.0,
    ) -> dict[str, Any] | None:
        """Atomically claim a deep job for one in-process dispatcher.

        ``deep_jobs`` is shared by API workers, while the actual dispatcher is
        intentionally local to an API process.  A plain read followed by a
        status update lets two workers execute the same queued job after a
        reconnect.  This method turns the status transition into a conditional
        write: only one worker can move ``queued`` to ``running``.  A stale
        ``running``/``partial`` row may be reclaimed after a process crash;
        the conditional ``updated_at`` predicate prevents a live worker that
        has just advanced the row from being stolen by a second worker.

        The returned repository row carries the private claim token so the
        owning dispatcher can fence later writes. The API's public job
        projection removes it; ownership and provider metadata never enter
        the public event ledger.
        """

        job_key = str(job_id or "").strip()
        if not job_key:
            return None
        try:
            stale_seconds = max(0.0, float(stale_after_seconds))
        except (TypeError, ValueError):
            stale_seconds = 90.0

        def _stale(updated_at: Any) -> bool:
            value = str(updated_at or "").strip()
            if not value:
                return True
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - parsed).total_seconds()
                return age >= stale_seconds
            except (TypeError, ValueError, OverflowError):
                return True

        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    row = connection.execute(
                        select(deep_jobs).where(deep_jobs.c.job_id == job_key)
                    ).mappings().one_or_none()
                    if row is None:
                        return None
                    current_status = str(row.get("status", "")).strip().lower()
                    current_updated = str(row.get("updated_at", "") or "")
                    eligible = current_status == "queued"
                    if recover and current_status in {"running", "partial"}:
                        eligible = _stale(current_updated)
                    if not eligible:
                        return None
                    # A capability portrait conversation is a linear stream
                    # per branch.  Two API workers may receive consecutive
                    # turns at the same time; allow only the oldest queued
                    # turn to claim while a predecessor is queued or live.
                    # Different branches remain independently parallel.
                    session_key = str(row.get("session_id", "") or "").strip()
                    branch_key = normalize_branch_id(row.get("branch_id"))
                    if session_key:
                        predecessors = connection.execute(
                            select(
                                deep_jobs.c.job_id,
                                deep_jobs.c.status,
                                deep_jobs.c.stage,
                                deep_jobs.c.updated_at,
                                deep_jobs.c.created_at,
                            )
                            .where(
                                deep_jobs.c.session_id == session_key,
                                deep_jobs.c.branch_id == branch_key,
                                deep_jobs.c.status.in_(("queued", "running", "partial")),
                            )
                        ).mappings().all()
                        current_created = str(row.get("created_at", "") or "")
                        current_id = str(row.get("job_id", "") or "")
                        for predecessor in predecessors:
                            predecessor_id = str(predecessor.get("job_id", "") or "")
                            if predecessor_id == current_id:
                                continue
                            predecessor_created = str(
                                predecessor.get("created_at", "") or ""
                            )
                            older = predecessor_created < current_created or (
                                predecessor_created == current_created
                                and predecessor_id < current_id
                            )
                            if not older:
                                continue
                            predecessor_status = str(
                                predecessor.get("status", "") or ""
                            ).strip().lower()
                            predecessor_stage = str(
                                predecessor.get("stage", "") or ""
                            ).strip().lower()
                            if predecessor_status == "queued":
                                return None
                            if predecessor_status == "partial" and predecessor_stage in {
                                "validation",
                                "publish",
                            }:
                                # This is an explicit retry/publish boundary,
                                # not live authoring. A new user turn may
                                # continue the branch while the old partial
                                # result remains available for replay.
                                continue
                            if not _stale(predecessor.get("updated_at")):
                                return None
                    # Preserve a partial stage while reclaiming it; the next
                    # worker will emit the normal visible stage transition.
                    result = connection.execute(
                        update(deep_jobs)
                        .where(
                            deep_jobs.c.job_id == job_key,
                            deep_jobs.c.status == current_status,
                            deep_jobs.c.updated_at == current_updated,
                        )
                        .values(
                            status="running",
                            error="",
                            claim_token=f"claim-{uuid4().hex}",
                            state_version=max(
                                1, int(row.get("state_version", 1) or 1)
                            ) + 1,
                            updated_at=_favorite_now_iso(),
                        )
                    )
                    if not result.rowcount:
                        # Another worker won the conditional update.  Return
                        # no row so its dispatcher remains the sole owner.
                        return None
                    if recover:
                        connection.execute(
                            update(deep_steers)
                            .where(
                                deep_steers.c.job_id == job_key,
                                deep_steers.c.status == "claimed",
                            )
                            .values(status="pending", updated_at=_favorite_now_iso())
                        )
                return self.get_deep_job(job_key)
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    @staticmethod
    def _deep_steer_row(row: Any) -> dict[str, Any]:
        return dict(row)

    def deep_job_claim_matches(self, job_id: str, claim_token: str) -> bool:
        token = str(claim_token or "").strip()
        if not token:
            return False
        with self.engine.connect() as connection:
            current = connection.execute(
                select(deep_jobs.c.claim_token).where(
                    deep_jobs.c.job_id == str(job_id)
                )
            ).scalar_one_or_none()
        return str(current or "").strip() == token

    @staticmethod
    def _deep_job_accepts_steers(row: Mapping[str, Any]) -> bool:
        status = str(row.get("status", "")).strip().lower()
        stage = str(row.get("stage", "")).strip().lower()
        if bool(row.get("steer_closed", 0)):
            return False
        if status in {"queued", "running", "partial"}:
            return True
        return status == "completed" and stage not in {"", "publish"}

    def enqueue_deep_steer(
        self,
        *,
        job_id: str,
        content: str,
        mode: str = "steer",
        client_steer_id: str,
        branch_id: str = DEFAULT_BRANCH_ID,
        parent_message_id: str = "",
    ) -> dict[str, Any]:
        """Persist a user steering message and its durable receipt atomically."""

        job_key = str(job_id or "").strip()
        client_key = str(client_steer_id or "").strip()[:128]
        steer_content = str(content or "").strip()[:8000]
        steer_mode = normalize_steer_mode(mode)
        normalized_branch = normalize_branch_id(branch_id)
        if not job_key or not client_key:
            raise ValueError("job_id and client_steer_id are required")
        if not steer_content:
            raise ValueError("steering content is required")

        for attempt in range(8):
            now = _favorite_now_iso()
            try:
                with self._lock, self.engine.begin() as connection:
                    existing = connection.execute(
                        select(deep_steers).where(
                            deep_steers.c.job_id == job_key,
                            deep_steers.c.client_steer_id == client_key,
                        )
                    ).mappings().one_or_none()
                    if existing is not None:
                        return self._deep_steer_row(existing)

                    job = connection.execute(
                        select(deep_jobs).where(deep_jobs.c.job_id == job_key)
                    ).mappings().one_or_none()
                    if job is None:
                        raise ValueError("deep job not found")
                    if not self._deep_job_accepts_steers(job):
                        raise ValueError("deep job no longer accepts steering")
                    session_id = str(job.get("session_id", "") or "")
                    if not session_id:
                        raise ValueError("deep job is not bound to a session")
                    job_branch = normalize_branch_id(job.get("branch_id"))
                    if normalized_branch != job_branch:
                        raise ValueError("steering branch does not match the active job")

                    queue_order = int(
                        connection.execute(
                            select(func.max(deep_steers.c.queue_order)).where(
                                deep_steers.c.job_id == job_key
                            )
                        ).scalar_one_or_none()
                        or 0
                    ) + 1
                    sequence = int(
                        connection.execute(
                            select(func.max(deep_messages.c.sequence)).where(
                                deep_messages.c.session_id == session_id
                            )
                        ).scalar_one_or_none()
                        or 0
                    ) + 1
                    resolved_parent = self._resolve_deep_parent_message(
                        connection,
                        session_id=session_id,
                        branch_id=normalized_branch,
                        parent_message_id=parent_message_id,
                    )

                    message_id = f"message-{uuid4().hex}"
                    connection.execute(
                        deep_messages.insert().values(
                            session_id=session_id,
                            sequence=sequence,
                            message_id=message_id,
                            parent_message_id=resolved_parent,
                            branch_id=normalized_branch,
                            turn_id=job_key,
                            message_kind="steer",
                            role="user",
                            content=steer_content,
                            status="queued" if steer_mode == "queue" else "accepted",
                            artifact_refs_json="[]",
                            version_refs_json="[]",
                            created_at=now,
                        )
                    )
                    values = {
                        "steer_id": f"steer-{uuid4().hex}",
                        "client_steer_id": client_key,
                        "job_id": job_key,
                        "session_id": session_id,
                        "message_id": message_id,
                        "branch_id": normalized_branch,
                        "mode": steer_mode,
                        "content": steer_content,
                        "queue_order": queue_order,
                        "status": "pending",
                        "applied_stage": "",
                        "created_at": now,
                        "updated_at": now,
                    }
                    connection.execute(deep_steers.insert().values(**values))
                    return self._deep_steer_row(values)
            except IntegrityError:
                with self.engine.connect() as connection:
                    existing = connection.execute(
                        select(deep_steers).where(
                            deep_steers.c.job_id == job_key,
                            deep_steers.c.client_steer_id == client_key,
                        )
                    ).mappings().one_or_none()
                if existing is not None:
                    return self._deep_steer_row(existing)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to enqueue deep steering")

    def claim_deep_steers(
        self,
        job_id: str,
        *,
        live_only: bool = True,
        limit: int = 32,
        claim_token: str = "",
    ) -> list[dict[str, Any]]:
        """Atomically claim pending steering inputs in FIFO order."""

        job_key = str(job_id or "").strip()
        capped_limit = max(1, min(int(limit), 100))
        with self._lock, self.engine.begin() as connection:
            expected_claim = str(claim_token or "").strip()
            if expected_claim:
                owner = connection.execute(
                    select(deep_jobs.c.claim_token).where(
                        deep_jobs.c.job_id == job_key
                    )
                ).scalar_one_or_none()
                if str(owner or "").strip() != expected_claim:
                    return []
            clauses = [
                deep_steers.c.job_id == job_key,
                deep_steers.c.status == "pending",
            ]
            if live_only:
                clauses.append(deep_steers.c.mode.in_(tuple(LIVE_STEER_MODES)))
            rows = connection.execute(
                select(deep_steers)
                .where(*clauses)
                .order_by(deep_steers.c.queue_order, deep_steers.c.created_at)
                .limit(capped_limit)
            ).mappings().all()
            steer_ids = [str(row["steer_id"]) for row in rows]
            if not steer_ids:
                return []
            now = _favorite_now_iso()
            connection.execute(
                update(deep_steers)
                .where(
                    deep_steers.c.steer_id.in_(steer_ids),
                    deep_steers.c.status == "pending",
                )
                .values(status="claimed", updated_at=now)
            )
            return [
                self._deep_steer_row({**dict(row), "status": "claimed", "updated_at": now})
                for row in rows
            ]

    def mark_deep_steers_applied(
        self,
        steer_ids: Sequence[str],
        *,
        stage: str,
        claim_token: str = "",
    ) -> list[dict[str, Any]]:
        ids = [str(item) for item in steer_ids if str(item).strip()]
        if not ids:
            return []
        now = _favorite_now_iso()
        with self._lock, self.engine.begin() as connection:
            expected_claim = str(claim_token or "").strip()
            if expected_claim:
                job_ids = connection.execute(
                    select(deep_steers.c.job_id).where(
                        deep_steers.c.steer_id.in_(ids)
                    )
                ).scalars().all()
                if not job_ids or len(set(job_ids)) != 1:
                    return []
                owner = connection.execute(
                    select(deep_jobs.c.claim_token).where(
                        deep_jobs.c.job_id == str(job_ids[0])
                    )
                ).scalar_one_or_none()
                if str(owner or "").strip() != expected_claim:
                    return []
            connection.execute(
                update(deep_steers)
                .where(
                    deep_steers.c.steer_id.in_(ids),
                    deep_steers.c.status == "claimed",
                )
                .values(status="applied", applied_stage=str(stage)[:64], updated_at=now)
            )
            connection.execute(
                update(deep_messages)
                .where(
                    deep_messages.c.message_id.in_(
                        select(deep_steers.c.message_id).where(
                            deep_steers.c.steer_id.in_(ids)
                        )
                    )
                )
                .values(status="applied")
            )
            rows = connection.execute(
                select(deep_steers)
                .where(deep_steers.c.steer_id.in_(ids))
                .order_by(deep_steers.c.queue_order)
            ).mappings().all()
        return [self._deep_steer_row(row) for row in rows]

    def list_deep_steers(
        self, job_id: str, *, statuses: Sequence[str] = ()
    ) -> list[dict[str, Any]]:
        clauses = [deep_steers.c.job_id == str(job_id)]
        normalized = [str(item).strip().lower() for item in statuses if str(item).strip()]
        if normalized:
            clauses.append(deep_steers.c.status.in_(normalized))
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(deep_steers)
                .where(*clauses)
                .order_by(deep_steers.c.queue_order, deep_steers.c.created_at)
            ).mappings().all()
        return [self._deep_steer_row(row) for row in rows]

    def cancel_deep_steer(self, job_id: str, steer_id: str) -> dict[str, Any] | None:
        now = _favorite_now_iso()
        with self._lock, self.engine.begin() as connection:
            row = connection.execute(
                select(deep_steers).where(
                    deep_steers.c.job_id == str(job_id),
                    deep_steers.c.steer_id == str(steer_id),
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            if str(row.get("status", "")) != "pending":
                return self._deep_steer_row(row)
            connection.execute(
                update(deep_steers)
                .where(deep_steers.c.steer_id == str(steer_id))
                .values(status="cancelled", updated_at=now)
            )
            connection.execute(
                update(deep_messages)
                .where(deep_messages.c.message_id == str(row.get("message_id", "")))
                .values(status="cancelled")
            )
        return self._deep_steer_row({**dict(row), "status": "cancelled", "updated_at": now})

    def close_and_park_deep_steers(
        self, job_id: str, *, claim_token: str = ""
    ) -> list[dict[str, Any]]:
        """Close intake before draining unresolved inputs at a terminal boundary."""

        job_key = str(job_id)
        now = _favorite_now_iso()
        with self._lock, self.engine.begin() as connection:
            clauses = [deep_jobs.c.job_id == job_key]
            expected_claim = str(claim_token or "").strip()
            if expected_claim:
                clauses.append(deep_jobs.c.claim_token == expected_claim)
            result = connection.execute(
                update(deep_jobs)
                .where(*clauses)
                .values(
                    steer_closed=1,
                    state_version=deep_jobs.c.state_version + 1,
                    updated_at=now,
                )
            )
            if not result.rowcount:
                return []
            rows = connection.execute(
                select(deep_steers)
                .where(
                    deep_steers.c.job_id == job_key,
                    deep_steers.c.status.in_(("pending", "claimed")),
                )
                .order_by(deep_steers.c.queue_order, deep_steers.c.created_at)
            ).mappings().all()
            steer_ids = [str(row["steer_id"]) for row in rows]
            if steer_ids:
                connection.execute(
                    update(deep_steers)
                    .where(deep_steers.c.steer_id.in_(steer_ids))
                    .values(status="parked", updated_at=now)
                )
                connection.execute(
                    update(deep_messages)
                    .where(
                        deep_messages.c.message_id.in_(
                            [str(row["message_id"]) for row in rows]
                        )
                    )
                    .values(status="parked")
                )
        return [
            self._deep_steer_row({**dict(row), "status": "parked", "updated_at": now})
            for row in rows
        ]

    def cancel_deep_jobs(
        self,
        parent_run_id: str,
        *,
        reason: str = "parent run cancelled",
        include_partial: bool = False,
    ) -> list[dict[str, Any]]:
        """Cancel active deep jobs owned by a parent run atomically.

        The API dispatcher may be running in another process, so an in-memory
        cancellation Event is not sufficient.  This durable transition is
        the cross-worker fence: workers check the job status at stage
        boundaries and child-run monitors observe the same terminal state.
        The returned rows are the canonical pre-transition identities, which
        lets the application layer terminate any associated child processes.
        """

        parent = str(parent_run_id)
        active_statuses = ["queued", "running"]
        if include_partial:
            active_statuses.append("partial")
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    rows = connection.execute(
                        select(deep_jobs)
                        .where(
                            deep_jobs.c.parent_run_id == parent,
                            deep_jobs.c.status.in_(active_statuses),
                        )
                        .order_by(deep_jobs.c.created_at, deep_jobs.c.job_id)
                    ).mappings().all()
                    if not rows:
                        return []
                    now = _favorite_now_iso()
                    connection.execute(
                        update(deep_jobs)
                        .where(
                            deep_jobs.c.parent_run_id == parent,
                            deep_jobs.c.status.in_(active_statuses),
                        )
                        .values(
                            stage="publish",
                            status="cancelled",
                            error=str(reason or "parent run cancelled")[:4000],
                            claim_token="",
                            state_version=deep_jobs.c.state_version + 1,
                            updated_at=now,
                        )
                    )
                    session_ids = {
                        str(row.get("session_id", "")).strip()
                        for row in rows
                        if str(row.get("session_id", "")).strip()
                    }
                    if session_ids:
                        connection.execute(
                            update(deep_sessions)
                            .where(deep_sessions.c.session_id.in_(session_ids))
                            .values(status="cancelled", updated_at=now)
                        )
                return [self._deep_job_row(row) for row in rows]
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return []

    def append_deep_event(self, *, stream_id: str, parent_run_id: str, event_type: str, session_id: str = "", job_id: str = "", stage: str = "queued", status: str = "queued", state_version: int = 0, progress: float = 0.0, delta: dict | None = None, evidence_refs: list[str] | None = None, artifact_refs: list[str] | None = None, version_refs: list[str] | None = None, child_run_id: str = "", error: str = "") -> dict[str, Any]:
        now = _favorite_now_iso()
        # Progress is telemetry supplied by asynchronous workers.  A broken
        # provider/adapter can hand us NaN/Infinity (or a non-numeric value),
        # which previously raised while converting to an integer and dropped
        # the entire public stage event.  Persist a finite, bounded value so
        # the ledger remains append-only and SSE replay stays lossless.
        try:
            progress_value = float(progress)
        except (TypeError, ValueError, OverflowError):
            progress_value = 0.0
        if not math.isfinite(progress_value):
            progress_value = 0.0
        progress_i = max(
            0,
            min(
                100,
                int(
                    progress_value * 100
                    if progress_value <= 1
                    else progress_value
                ),
            ),
        )
        for attempt in range(5):
            try:
                with self._lock, self.engine.begin() as connection:
                    seq = (connection.execute(select(deep_events.c.sequence).where(deep_events.c.stream_id == str(stream_id)).order_by(deep_events.c.sequence.desc()).limit(1)).scalar_one_or_none() or 0) + 1
                    values = {"stream_id": str(stream_id), "sequence": seq, "event_id": f"deep-event-{uuid4().hex}", "event_type": str(event_type), "session_id": str(session_id or ""), "job_id": str(job_id or ""), "parent_run_id": str(parent_run_id), "child_run_id": str(child_run_id or ""), "stage": str(stage), "status": str(status), "state_version": max(0, int(state_version or 0)), "progress": progress_i, "delta_json": self._json(delta or {}), "evidence_refs_json": self._json(list(evidence_refs or []), "[]"), "artifact_refs_json": self._json(list(artifact_refs or []), "[]"), "version_refs_json": self._json(list(version_refs or []), "[]"), "error": str(error or "")[:1000], "created_at": now}
                    connection.execute(deep_events.insert().values(**values))
                return self._deep_event_row(values)
            except IntegrityError:
                if attempt >= 4: raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 4:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to append deep event")

    def _deep_event_row(self, row: Any) -> dict[str, Any]:
        raw = dict(row)
        for column, key, fallback in (("delta_json", "delta", {}), ("evidence_refs_json", "evidence_refs", []), ("artifact_refs_json", "artifact_refs", []), ("version_refs_json", "version_refs", [])):
            raw[key] = self._decode(raw.pop(column, ""), fallback)
        try:
            progress = float(raw.get("progress", 0))
        except (TypeError, ValueError, OverflowError):
            progress = 0.0
        raw["progress"] = (
            max(0.0, min(1.0, progress / 100.0))
            if math.isfinite(progress)
            else 0.0
        )
        return raw

    def deep_events_after(self, stream_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(deep_events).where(deep_events.c.stream_id == str(stream_id), deep_events.c.sequence > int(after)).order_by(deep_events.c.sequence)).mappings().all()
        return [self._deep_event_row(row) for row in rows]

    def deep_event_sequence_for_id(self, stream_id: str, event_id: str) -> int | None:
        """Resolve an SSE ``Last-Event-ID`` to the stream sequence.

        Deep events expose both a stable opaque ``event_id`` and a monotonic
        per-stream ``sequence``.  Browsers normally send the value from the
        SSE ``id`` field (which is the sequence in our transport), while some
        clients persist ``event_id`` instead.  Supporting both keeps replay
        lossless across reconnects without making the public event payload
        depend on a particular cursor representation.
        """

        value = str(event_id or "").strip()
        if not value:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(
                select(deep_events.c.sequence)
                .where(
                    deep_events.c.stream_id == str(stream_id),
                    deep_events.c.event_id == value,
                )
            ).scalar_one_or_none()
        return int(row) if row is not None else None

    def save_capability_version(self, *, version_id: str, parent_run_id: str, card_binding_id: str, hypothesis_id: str, snapshot: dict, diff: dict | None = None, base_snapshot_hash: str = "", source: str = "deep-thinking", evidence_refs: list[str] | None = None, status: str = "pending_verification", parent_version_id: str = "", base_version_id: str = "") -> dict[str, Any]:
        now = _favorite_now_iso()
        parent = str(parent_run_id)
        binding = str(card_binding_id)
        hypothesis = str(hypothesis_id or "")
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    # A retry with the same version id is safe to replay.
                    existing_by_id = connection.execute(
                        select(capability_versions).where(
                            capability_versions.c.version_id == str(version_id)
                        )
                    ).mappings().one_or_none()
                    if existing_by_id:
                        if (
                            str(existing_by_id.get("parent_run_id", "")) != parent
                            or str(existing_by_id.get("card_binding_id", "")) != binding
                            or str(existing_by_id.get("hypothesis_id", "")) != hypothesis
                        ):
                            raise ValueError("version_id already belongs to another capability lineage")
                        return self._capability_version_row(existing_by_id)
                    existing = connection.execute(
                        select(capability_versions)
                        .where(
                            capability_versions.c.parent_run_id == parent,
                            capability_versions.c.card_binding_id == binding,
                            capability_versions.c.hypothesis_id == hypothesis,
                        )
                        .order_by(capability_versions.c.version_no.desc())
                        .limit(1)
                    ).mappings().one_or_none()
                    version_no = int(existing["version_no"] if existing else 0) + 1

                    # Validate explicit lineage references server-side.  A
                    # browser may only point at a version in this exact
                    # parent/binding/hypothesis chain; otherwise a new
                    # hypothesis could accidentally inherit another card's
                    # history.
                    parent_ref = str(parent_version_id or (existing["version_id"] if existing else ""))
                    base_ref = str(base_version_id or "")
                    lineage_rows = connection.execute(
                        select(capability_versions.c.version_id,
                               capability_versions.c.version_no,
                               capability_versions.c.base_version_id)
                        .where(
                            capability_versions.c.parent_run_id == parent,
                            capability_versions.c.card_binding_id == binding,
                            capability_versions.c.hypothesis_id == hypothesis,
                        )
                    ).mappings().all()
                    lineage_by_id = {str(row["version_id"]): row for row in lineage_rows}
                    if parent_ref and parent_ref not in lineage_by_id:
                        raise ValueError("parent_version_id does not belong to capability lineage")
                    if base_ref and base_ref not in lineage_by_id:
                        raise ValueError("base_version_id does not belong to capability lineage")
                    if not base_ref:
                        # The first row is the immutable formal baseline when
                        # present.  Propagate that root for v3+; for a new
                        # hypothesis, v1 is its own base once inserted.
                        roots = [row for row in lineage_rows if int(row["version_no"] or 0) == 1]
                        base_ref = str(roots[0]["version_id"]) if roots else ""
                    previous_snapshot = {}
                    if existing:
                        previous_snapshot = self._decode(existing.get("snapshot_json", "{}"), {})
                    normalized_diff = self._capability_diff(
                        previous_snapshot if isinstance(previous_snapshot, dict) else {},
                        dict(snapshot or {}),
                        diff,
                    )
                    values = {
                        "version_id": str(version_id),
                        "parent_run_id": parent,
                        "card_binding_id": binding,
                        "hypothesis_id": hypothesis,
                        "version_no": version_no,
                        "parent_version_id": parent_ref,
                        "base_version_id": base_ref,
                        "base_snapshot_hash": str(base_snapshot_hash or ""),
                        "diff_json": self._json(normalized_diff),
                        "source": str(source),
                        "evidence_refs_json": self._json(list(evidence_refs or []), "[]"),
                        "snapshot_json": self._json(snapshot),
                        "status": str(status),
                        "previous_status": "",
                        "source_deleted": 0,
                        "source_status": "",
                        "created_at": now,
                        "updated_at": now,
                    }
                    connection.execute(capability_versions.insert().values(**values))
                return self._capability_version_row(values)
            except IntegrityError:
                # Another process may have claimed this version number.  If
                # it was the same id, replay it; otherwise retry after the
                # newly committed row becomes visible and recompute MAX.
                with self.engine.connect() as connection:
                    row = connection.execute(
                        select(capability_versions).where(
                            capability_versions.c.version_id == str(version_id)
                        )
                    ).mappings().one_or_none()
                if row is not None:
                    return self._capability_version_row(row)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unable to save capability version")

    @staticmethod
    def _capability_diff(previous: dict[str, Any], current: dict[str, Any], supplied: dict | None) -> dict[str, Any]:
        """Return a stable, module-level diff while retaining caller metadata.

        Deep-research callers historically supplied ``source``/``focus`` only.
        Keep those fields for compatibility, but always add a deterministic
        ``modules`` map so consumers can render exactly which capability
        modules changed.  Values are JSON-safe snapshots rather than hidden
        provider metadata.
        """
        result = dict(supplied or {}) if isinstance(supplied, dict) else {}
        keys = sorted(set(previous) | set(current))
        modules: dict[str, dict[str, Any]] = {}
        changed: list[str] = []
        for key in keys:
            before = previous.get(key)
            after = current.get(key)
            if before == after:
                state = "unchanged"
            elif key not in previous:
                state = "added"
                changed.append(key)
            elif key not in current:
                state = "removed"
                changed.append(key)
            else:
                state = "changed"
                changed.append(key)
            modules[str(key)] = {"status": state, "before": before, "after": after}
        result["modules"] = modules
        result["changed_modules"] = changed
        result["module_count"] = len(changed)
        return result

    def ensure_capability_baseline(self, *, parent_run_id: str, card_binding_id: str,
                                   hypothesis_id: str = "", snapshot: dict | None = None,
                                   evidence_refs: list[str] | None = None) -> dict[str, Any]:
        """Register an immutable formal v1 snapshot exactly once.

        Deep-research versions are appended after this baseline when a
        follow-up targets an existing S6 card.  New hypotheses can skip this
        helper and naturally start at version 1.
        """
        parent = str(parent_run_id)
        binding = str(card_binding_id)
        now = _favorite_now_iso()
        hypothesis = str(hypothesis_id or "")
        values = {
            "version_id": f"baseline-{uuid4().hex}",
            "parent_run_id": parent,
            "card_binding_id": binding,
            "hypothesis_id": hypothesis,
            "version_no": 1,
            "parent_version_id": "",
            "base_version_id": "",
            "base_snapshot_hash": "",
            "diff_json": self._json({"baseline": True}),
            "source": "formal_s6",
            "evidence_refs_json": self._json(list(evidence_refs or []), "[]"),
            "snapshot_json": self._json(dict(snapshot or {})),
            "status": "formal",
            "previous_status": "",
            "source_deleted": 0,
            "source_status": "",
            "created_at": now,
            "updated_at": now,
        }
        # The pre-read and insert are intentionally separate transactions so a
        # duplicate race never queries through a failed transaction.  The
        # unique (parent, binding, version_no) fence makes this idempotent.
        for attempt in range(8):
            with self.engine.connect() as connection:
                existing = connection.execute(
                    select(capability_versions)
                    .where(
                        capability_versions.c.parent_run_id == parent,
                        capability_versions.c.card_binding_id == binding,
                        capability_versions.c.hypothesis_id == hypothesis,
                    )
                    .order_by(capability_versions.c.version_no)
                    .limit(1)
                ).mappings().first()
            if existing:
                return self._capability_version_row(existing)
            try:
                with self._lock, self.engine.begin() as connection:
                    connection.execute(capability_versions.insert().values(**values))
                return self._capability_version_row(values)
            except IntegrityError:
                with self.engine.connect() as connection:
                    existing = connection.execute(
                        select(capability_versions)
                        .where(
                            capability_versions.c.parent_run_id == parent,
                            capability_versions.c.card_binding_id == binding,
                            capability_versions.c.hypothesis_id == hypothesis,
                        )
                        .order_by(capability_versions.c.version_no)
                        .limit(1)
                    ).mappings().first()
                if existing:
                    return self._capability_version_row(existing)
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))

    def _capability_version_row(self, row: Any) -> dict[str, Any]:
        raw = dict(row)
        for column, key, fallback in (("diff_json", "diff", {}), ("evidence_refs_json", "evidence_refs", []), ("snapshot_json", "snapshot", {})):
            raw[key] = self._decode(raw.pop(column, ""), fallback)
        # SQLite stores the source-deletion marker as an integer.  Expose a
        # proper boolean in the API projection while remaining compatible
        # with legacy rows created before the column existed.
        raw["source_deleted"] = bool(raw.get("source_deleted", 0))
        return raw

    def list_capability_versions(self, parent_run_id: str, card_binding_id: str = "") -> list[dict[str, Any]]:
        clauses = [capability_versions.c.parent_run_id == str(parent_run_id)]
        if card_binding_id: clauses.append(capability_versions.c.card_binding_id == str(card_binding_id))
        with self.engine.connect() as connection:
            rows = connection.execute(select(capability_versions).where(*clauses).order_by(capability_versions.c.card_binding_id, capability_versions.c.hypothesis_id, capability_versions.c.version_no)).mappings().all()
        return [self._capability_version_row(row) for row in rows]

    def get_capability_version(
        self, version_id: str, *, parent_run_id: str = ""
    ) -> dict[str, Any] | None:
        clauses = [capability_versions.c.version_id == str(version_id)]
        if str(parent_run_id).strip():
            clauses.append(capability_versions.c.parent_run_id == str(parent_run_id))
        with self.engine.connect() as connection:
            row = connection.execute(
                select(capability_versions).where(*clauses)
            ).mappings().one_or_none()
        return self._capability_version_row(row) if row else None

    def verify_capability_version(
        self,
        version_id: str,
        *,
        status: str,
        parent_run_id: str = "",
    ) -> dict[str, Any] | None:
        """Apply a review decision without crossing run boundaries.

        The parent predicate is included in the UPDATE itself so a caller
        cannot mutate a version from another run between an ownership read and
        the write.  Formal S6 baselines are immutable and therefore cannot be
        reviewed through this endpoint.
        """

        if status not in {
            "verified",
            "rejected",
            "rolled_back",
            "pending_verification",
        }:
            raise ValueError("invalid verification status")
        clauses = [capability_versions.c.version_id == str(version_id)]
        if str(parent_run_id).strip():
            clauses.append(capability_versions.c.parent_run_id == str(parent_run_id))
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(capability_versions).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    if str(current.get("status", "")) == "formal":
                        raise ValueError("formal capability version is immutable")
                    connection.execute(
                        update(capability_versions)
                        .where(*clauses)
                        .values(status=status, updated_at=_favorite_now_iso())
                    )
                return self.get_capability_version(
                    version_id, parent_run_id=parent_run_id
                )
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def delete_capability_version(
        self, version_id: str, *, parent_run_id: str = ""
    ) -> dict[str, Any] | None:
        """Soft-delete one non-formal version while preserving audit history."""

        clauses = [capability_versions.c.version_id == str(version_id)]
        if str(parent_run_id).strip():
            clauses.append(capability_versions.c.parent_run_id == str(parent_run_id))
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(capability_versions).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    status = str(current.get("status", "") or "")
                    if status == "formal":
                        raise ValueError("formal capability version is immutable")
                    if status != "deleted":
                        connection.execute(
                            update(capability_versions)
                            .where(*clauses)
                            .values(
                                status="deleted",
                                previous_status=status or "pending_verification",
                                updated_at=_favorite_now_iso(),
                            )
                        )
                return self.get_capability_version(
                    version_id, parent_run_id=parent_run_id
                )
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def restore_capability_version(
        self, version_id: str, *, parent_run_id: str = ""
    ) -> dict[str, Any] | None:
        """Restore one soft-deleted version to its previous review state."""

        clauses = [capability_versions.c.version_id == str(version_id)]
        if str(parent_run_id).strip():
            clauses.append(capability_versions.c.parent_run_id == str(parent_run_id))
        allowed = {
            "pending_verification", "verified", "rejected", "rolled_back",
            "cancelled", "failed", "blocked", "partial",
        }
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(capability_versions).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    if str(current.get("status", "") or "") != "deleted":
                        raise ValueError("capability version is not deleted")
                    previous = str(current.get("previous_status", "") or "")
                    restored_status = previous if previous in allowed else "pending_verification"
                    connection.execute(
                        update(capability_versions)
                        .where(*clauses)
                        .values(
                            status=restored_status,
                            previous_status="",
                            updated_at=_favorite_now_iso(),
                        )
                    )
                return self.get_capability_version(
                    version_id, parent_run_id=parent_run_id
                )
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def purge_capability_version(
        self, version_id: str, *, parent_run_id: str = ""
    ) -> dict[str, Any] | None:
        """Permanently remove one soft-deleted deep version from the ledger.

        Formal baselines and live (non-deleted) rows are rejected.  Soft-delete
        remains the reversible default; purge is an explicit second step so a
        mistaken hide can still be restored.
        """

        clauses = [capability_versions.c.version_id == str(version_id)]
        if str(parent_run_id).strip():
            clauses.append(capability_versions.c.parent_run_id == str(parent_run_id))
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(capability_versions).where(*clauses)
                    ).mappings().one_or_none()
                    if current is None:
                        return None
                    status = str(current.get("status", "") or "").strip().lower()
                    if status == "formal":
                        raise ValueError("formal capability version is immutable")
                    if status != "deleted":
                        raise ValueError(
                            "only soft-deleted capability versions can be purged"
                        )
                    snapshot = self._capability_version_row(current)
                    connection.execute(
                        delete(capability_versions).where(*clauses)
                    )
                return snapshot
            except OperationalError as exc:
                if not _retryable_sqlite_lock(exc) or attempt >= 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        return None

    def claim_deep_idempotency(self, *, scope_key: str, operation: str, idempotency_key: str, request_hash: str, resource_id: str = "", response: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return an existing claim or atomically record a new request.

        A reused key with a different request fingerprint is rejected by the
        caller; a matching claim is returned for safe response replay.
        """
        now = _favorite_now_iso()
        scope = str(scope_key)
        op = str(operation)
        key = str(idempotency_key)
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    existing = connection.execute(
                        select(deep_idempotency).where(
                            deep_idempotency.c.scope_key == scope,
                            deep_idempotency.c.operation == op,
                            deep_idempotency.c.idempotency_key == key,
                        )
                    ).mappings().one_or_none()
                    if existing:
                        if str(existing["request_hash"]) != str(request_hash):
                            raise ValueError("Idempotency-Key was already used with a different request")
                        raw = dict(existing)
                        raw["response"] = self._decode(raw.pop("response_json", "{}"), {})
                        return raw
                    values = {
                        "scope_key": scope,
                        "operation": op,
                        "idempotency_key": key,
                        "request_hash": str(request_hash),
                        "resource_id": str(resource_id or ""),
                        "response_json": self._json(response or {}),
                        "created_at": now,
                    }
                    connection.execute(deep_idempotency.insert().values(**values))
                return None
            except IntegrityError:
                # Cross-process claim race.  Read the winner and apply the
                # same request-hash conflict semantics as the fast path.
                with self.engine.connect() as connection:
                    existing = connection.execute(
                        select(deep_idempotency).where(
                            deep_idempotency.c.scope_key == scope,
                            deep_idempotency.c.operation == op,
                            deep_idempotency.c.idempotency_key == key,
                        )
                    ).mappings().one_or_none()
                if existing is not None:
                    if str(existing["request_hash"]) != str(request_hash):
                        raise ValueError("Idempotency-Key was already used with a different request")
                    raw = dict(existing)
                    raw["response"] = self._decode(raw.pop("response_json", "{}"), {})
                    return raw
                if attempt >= 7:
                    raise
                time.sleep(0.002 * (attempt + 1))
        raise RuntimeError("unable to claim deep idempotency key")

    def complete_deep_idempotency(self, *, scope_key: str, operation: str, idempotency_key: str, resource_id: str = "", response: dict | None = None) -> None:
        with self._lock, self.engine.begin() as connection:
            connection.execute(update(deep_idempotency).where(deep_idempotency.c.scope_key == str(scope_key), deep_idempotency.c.operation == str(operation), deep_idempotency.c.idempotency_key == str(idempotency_key)).values(resource_id=str(resource_id or ""), response_json=self._json(response or {})))

    def release_deep_idempotency(
        self,
        *,
        scope_key: str,
        operation: str,
        idempotency_key: str,
    ) -> None:
        """Release an in-flight claim after a failed mutation.

        Claims are inserted before a potentially fallible write so concurrent
        requests are fenced.  If that write fails before a durable response
        exists, retaining the empty claim would make every retry return
        ``409 already in progress`` forever.  Deleting only the exact
        scope/operation/key tuple lets a caller safely retry after the
        transient failure while preserving all unrelated replay records.

        The response predicate is intentional: completion can race with a
        cleanup path (for example when the HTTP worker times out immediately
        after committing the replay response).  A late cleanup must never
        delete a completed claim and reopen a mutation for duplication.
        """

        with self._lock, self.engine.begin() as connection:
            connection.execute(
                delete(deep_idempotency).where(
                    deep_idempotency.c.scope_key == str(scope_key),
                    deep_idempotency.c.operation == str(operation),
                    deep_idempotency.c.idempotency_key == str(idempotency_key),
                    # New claims use ``{}`` as the empty response marker.
                    # Keep the empty-string variant for rows written by a
                    # pre-ledger adapter, but do not delete a populated
                    # response even when cleanup runs after completion.
                    deep_idempotency.c.response_json.in_(("{}", "")),
                )
            )

    # ------------------------------------------------------------------
    # Immutable capability-card favorites
    # ------------------------------------------------------------------
    def save_favorite(
        self,
        *,
        scope: str,
        owner_id: str,
        run_id: str,
        card_key: str,
        favorite_id: str = "",
        card_binding_id: str = "",
        capability_id: str = "",
        snapshot: dict[str, Any] | None = None,
        display_name: str = "",
        note: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
        source_topic: str = "",
        source_status: str = "",
        source_deleted: bool = False,
    ) -> dict[str, Any]:
        """Persist an immutable capability snapshot and return the canonical row.

        ``scope + owner_id + run_id + card_key`` is the application idempotency
        key.  The unique constraint is the cross-process fence; callers may
        safely retry a POST after a network timeout without creating a second
        favorite.
        """

        scope = str(scope or "global").strip() or "global"
        owner_id = str(owner_id or "workspace").strip() or "workspace"
        run_id = str(run_id or "").strip()
        card_key = str(card_key or "").strip()
        if not run_id or not card_key:
            raise ValueError("run_id and card_key are required")
        now = _favorite_now_iso()
        # The API may provide a request-local ID so it can distinguish the
        # transaction that actually won a concurrent uniqueness race from a
        # retry that received the already-persisted canonical row. Direct
        # repository callers can omit it and still get an internally
        # generated identifier.
        favorite_id = str(favorite_id or "").strip() or f"favorite-{uuid4().hex}"
        serialized = json.dumps(
            dict(snapshot or {}), ensure_ascii=False, sort_keys=True
        )
        normalized_tags = _normalize_favorite_tags(tags)
        values = {
            "favorite_id": favorite_id,
            "scope": scope,
            "owner_id": owner_id,
            "run_id": run_id,
            "card_binding_id": str(card_binding_id or "").strip(),
            "capability_id": str(capability_id or "").strip(),
            "card_key": card_key,
            "snapshot_json": serialized,
            "display_name": str(display_name or "").strip()[:400],
            "note": str(note or "").strip()[:4000],
            "tags_json": json.dumps(normalized_tags, ensure_ascii=False),
            "source_topic": str(source_topic or "").strip(),
            "source_status": str(source_status or "").strip(),
            "source_deleted": 1 if source_deleted else 0,
            "created_at": now,
            "updated_at": now,
        }
        # SQLite (and most supported SQLAlchemy dialects) reports a duplicate
        # unique key as IntegrityError.  Read the existing row and return it;
        # this makes the operation idempotent across API worker processes.
        try:
            with self._lock, self.engine.begin() as connection:
                connection.execute(favorites.insert().values(**values))
        except IntegrityError:
            existing = self.find_favorite(
                scope=scope,
                owner_id=owner_id,
                run_id=run_id,
                card_key=card_key,
            )
            if existing is not None:
                return existing
            # A concurrent transaction may not have become visible at the
            # first read on a busy backend.  Bounded retry preserves the same
            # semantics without leaking a dialect-specific exception.
            for attempt in range(7):
                time.sleep(0.005 * (attempt + 1))
                existing = self.find_favorite(
                    scope=scope,
                    owner_id=owner_id,
                    run_id=run_id,
                    card_key=card_key,
                )
                if existing is not None:
                    return existing
            raise
        saved = self.get_favorite(favorite_id)
        return saved or _favorite_row_to_dict(values)

    def get_favorite(self, favorite_id: str) -> dict[str, Any] | None:
        favorite_id = str(favorite_id or "").strip()
        if not favorite_id:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(
                select(favorites).where(favorites.c.favorite_id == favorite_id)
            ).mappings().one_or_none()
        return _favorite_row_to_dict(row) if row is not None else None

    def find_favorite(
        self,
        *,
        scope: str,
        owner_id: str,
        run_id: str,
        card_key: str,
    ) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(favorites).where(
                    favorites.c.scope == str(scope),
                    favorites.c.owner_id == str(owner_id),
                    favorites.c.run_id == str(run_id),
                    favorites.c.card_key == str(card_key),
                )
            ).mappings().one_or_none()
        return _favorite_row_to_dict(row) if row is not None else None

    def list_favorites(
        self,
        *,
        scope: str = "global",
        owner_id: str = "workspace",
        run_id: str = "",
        offset: int = 0,
        limit: int = 50,
        search: str = "",
        capability_type: str = "",
    ) -> dict[str, Any]:
        """List snapshots in reverse creation order with server-side filters."""

        scope = str(scope or "global").strip() or "global"
        owner_id = str(owner_id or "workspace").strip() or "workspace"
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 200))
        search = str(search or "").strip().lower()
        capability_type = str(capability_type or "").strip()
        with self.engine.connect() as connection:
            conditions = [
                favorites.c.scope == scope,
                favorites.c.owner_id == owner_id,
            ]
            if str(run_id or "").strip():
                conditions.append(favorites.c.run_id == str(run_id).strip())
            rows = connection.execute(
                select(favorites)
                .where(*conditions)
                .order_by(favorites.c.created_at.desc(), favorites.c.favorite_id.desc())
            ).mappings().all()
        decoded = [_favorite_row_to_dict(row) for row in rows]
        if search:
            decoded = [
                row
                for row in decoded
                if search
                in " ".join(
                    str(row.get(key, ""))
                    for key in (
                        "name",
                        "display_name",
                        "note",
                        "tags",
                        "source_topic",
                        "card_key",
                        "capability_id",
                        "card_binding_id",
                    )
                ).lower()
            ]
        if capability_type:
            decoded = [
                row
                for row in decoded
                if str(row.get("capability_type", "")).strip() == capability_type
            ]
        total = len(decoded)
        page = decoded[offset : offset + limit]
        return {
            "items": page,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
            "scope": scope,
            "owner_id": owner_id,
        }

    def delete_favorite(self, favorite_id: str) -> dict[str, Any] | None:
        existing = self.get_favorite(favorite_id)
        if existing is None:
            return None
        with self._lock, self.engine.begin() as connection:
            connection.execute(
                delete(favorites).where(favorites.c.favorite_id == str(favorite_id))
            )
        return existing

    def update_favorite(
        self,
        favorite_id: str,
        *,
        display_name: str | None = None,
        note: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        """Update presentation metadata while preserving the source snapshot."""

        favorite_id = str(favorite_id or "").strip()
        if not favorite_id:
            return None
        values: dict[str, Any] = {}
        if display_name is not None:
            values["display_name"] = str(display_name).strip()[:400]
        if note is not None:
            values["note"] = str(note).strip()[:4000]
        if tags is not None:
            values["tags_json"] = json.dumps(
                _normalize_favorite_tags(tags), ensure_ascii=False
            )
        if not values:
            return self.get_favorite(favorite_id)
        values["updated_at"] = _favorite_now_iso()
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(favorites)
                .where(favorites.c.favorite_id == favorite_id)
                .values(**values)
            )
            if not result.rowcount:
                return None
        return self.get_favorite(favorite_id)

    def mark_favorites_source_deleted(
        self,
        run_id: str,
        *,
        source_status: str = "deleted",
    ) -> int:
        """Detach favorites from a permanently removed source run.

        The snapshot remains queryable and is intentionally not cascaded with
        the run deletion.  Return the number of rows touched for diagnostics.
        """

        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(favorites)
                .where(favorites.c.run_id == str(run_id))
                .values(
                    source_deleted=1,
                    source_status=str(source_status or "deleted"),
                    updated_at=_favorite_now_iso(),
                )
            )
            return int(result.rowcount or 0)

    def update_favorites_source_status(
        self,
        run_id: str,
        *,
        source_status: str,
        source_deleted: bool = False,
    ) -> int:
        with self._lock, self.engine.begin() as connection:
            result = connection.execute(
                update(favorites)
                .where(favorites.c.run_id == str(run_id))
                .values(
                    source_status=str(source_status or ""),
                    source_deleted=1 if source_deleted else 0,
                    updated_at=_favorite_now_iso(),
                )
            )
            return int(result.rowcount or 0)

    # Small semantic aliases keep the repository ergonomic for service code
    # and preserve compatibility with callers that use CRUD verbs directly.
    def add_favorite(self, **values: Any) -> dict[str, Any]:
        return self.save_favorite(**values)

    def get_favorites(self, **filters: Any) -> dict[str, Any]:
        return self.list_favorites(**filters)

    def remove_favorite(self, favorite_id: str) -> dict[str, Any] | None:
        return self.delete_favorite(favorite_id)

    def mark_source_deleted(self, run_id: str, *, source_status: str = "deleted") -> int:
        return self.mark_favorites_source_deleted(
            run_id,
            source_status=source_status,
        )

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    current = connection.execute(
                        select(events.c.sequence)
                        .where(events.c.run_id == run_id)
                        .order_by(events.c.sequence.desc())
                        .limit(1)
                    ).scalar_one_or_none() or 0
                    sequence = current + 1
                    connection.execute(
                        events.insert().values(
                            run_id=run_id,
                            sequence=sequence,
                            event_type=event_type,
                            payload=serialized,
                        )
                    )
                return sequence
            except IntegrityError:
                # Each Worker owns a separate repository instance, so its
                # in-process lock cannot serialize sequence allocation across
                # processes. Re-read MAX(sequence) after a short bounded backoff.
                if attempt == 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        raise RuntimeError("unreachable event append retry state")

    def events_after(self, run_id: str, sequence: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(events).where(events.c.run_id == run_id, events.c.sequence > sequence).order_by(events.c.sequence)).mappings().all()
        return [{"run_id": row["run_id"], "sequence": row["sequence"], "event_type": row["event_type"], "payload": json.loads(row["payload"])} for row in rows]

    def actual_baseline_agent_ids_by_run(
        self,
        run_ids: list[str],
    ) -> dict[str, list[str]]:
        """Return unique baseline Agents that actually entered execution.

        The submitted ``selected_agent_ids`` can differ from the A-H blueprint
        after specialist expansion.  Runtime activity is therefore the source
        of truth; plan events are used only for older runs that lack per-Agent
        progress events.
        """
        normalized_ids = list(dict.fromkeys(str(item) for item in run_ids if item))
        if not normalized_ids:
            return {}
        activity_types = {
            "baseline_discovery_started",
            "baseline_model_call_started",
            "baseline_analysis_started",
            "baseline_agent_completed",
        }
        plan_types = {
            "run_started",
            "baseline_pipeline_started",
            "baseline_wave_started",
        }
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    events.c.run_id,
                    events.c.event_type,
                    events.c.payload,
                )
                .where(
                    events.c.run_id.in_(normalized_ids),
                    events.c.event_type.in_(activity_types | plan_types),
                )
                .order_by(events.c.run_id, events.c.sequence)
            ).mappings().all()

        actual: dict[str, list[str]] = {run_id: [] for run_id in normalized_ids}
        planned: dict[str, list[str]] = {run_id: [] for run_id in normalized_ids}
        for row in rows:
            run_id = str(row["run_id"])
            payload = json.loads(row["payload"])
            event = payload.get("event", payload) if isinstance(payload, dict) else {}
            event = event if isinstance(event, dict) else {}
            details = event.get("payload", event)
            details = details if isinstance(details, dict) else {}
            if row["event_type"] in activity_types:
                agent_id = str(
                    event.get("actor")
                    or event.get("agent_id")
                    or details.get("agent_id")
                    or ""
                ).strip()
                if agent_id and agent_id not in actual[run_id]:
                    actual[run_id].append(agent_id)
                continue
            for agent_id in details.get("agent_ids", []):
                normalized = str(agent_id).strip()
                if normalized and normalized not in planned[run_id]:
                    planned[run_id].append(normalized)
        return {
            run_id: actual[run_id] or planned[run_id]
            for run_id in normalized_ids
        }

    def touch_worker(self, worker_id: str, *, updated_at: str, status: str, current_run_id: str = "") -> None:
        with self._lock, self.engine.begin() as connection:
            connection.execute(delete(worker_heartbeats).where(worker_heartbeats.c.worker_id == worker_id))
            connection.execute(worker_heartbeats.insert().values(worker_id=worker_id, updated_at=updated_at, status=status, current_run_id=current_run_id))

    def worker_heartbeats(self) -> list[dict[str, str]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(worker_heartbeats)).mappings().all()
        return [dict(row) for row in rows]

    def delete_run(self, run_id: str) -> None:
        with self._lock, self.engine.begin() as connection:
            # Resolve and remove deep-research descendants before deleting the
            # parent.  The relation is carried in the child execution payload
            # for compatibility with older databases that predate a link
            # table; only exact parent ids are considered.
            all_rows = connection.execute(select(runs.c.run_id, runs.c.payload)).mappings().all()
            descendants: set[str] = {str(run_id)}
            changed = True
            while changed:
                changed = False
                for row in all_rows:
                    rid = str(row.get("run_id", ""))
                    if rid in descendants:
                        continue
                    try:
                        payload = json.loads(row.get("payload", "{}"))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        payload = {}
                    parent = str((payload.get("execution") or {}).get("parent_run_id", ""))
                    if parent in descendants:
                        descendants.add(rid); changed = True
                # Newer deep jobs persist parent/child linkage in the
                # dedicated table. Include those descendants even when the
                # child run payload predates the embedded execution marker.
                link_rows = connection.execute(
                    select(deep_run_links.c.parent_run_id, deep_run_links.c.child_run_id)
                ).all()
                for parent_id, child_id in link_rows:
                    if str(parent_id) in descendants and str(child_id) not in descendants:
                        descendants.add(str(child_id)); changed = True
            # Favorites are independent immutable snapshots.  Detach them in
            # the same transaction as the run-row deletion so callers that
            # delete through the application service (rather than the API
            # helper) cannot accidentally orphan a live source reference.
            connection.execute(
                update(favorites)
                .where(favorites.c.run_id.in_(descendants))
                .values(
                    source_deleted=1,
                    source_status="deleted",
                    updated_at=_favorite_now_iso(),
                )
            )
            connection.execute(delete(events).where(events.c.run_id.in_(descendants)))
            connection.execute(delete(queue_items).where(queue_items.c.run_id.in_(descendants)))
            connection.execute(
                update(worker_heartbeats)
                .where(worker_heartbeats.c.current_run_id.in_(descendants))
                .values(status="idle", current_run_id="")
            )
            session_ids = [str(row[0]) for row in connection.execute(select(deep_sessions.c.session_id).where(deep_sessions.c.parent_run_id.in_(descendants))).all()]
            if session_ids:
                connection.execute(delete(deep_messages).where(deep_messages.c.session_id.in_(session_ids)))
            connection.execute(delete(deep_events).where(deep_events.c.parent_run_id.in_(descendants)))
            connection.execute(delete(deep_jobs).where(deep_jobs.c.parent_run_id.in_(descendants)))
            connection.execute(delete(deep_sessions).where(deep_sessions.c.parent_run_id.in_(descendants)))
            # Keep the auditable portion of the capability version chain when
            # its source run is permanently removed.  Formal S6 v1 and any
            # reviewer decision (verified/rejected/rolled_back) are immutable
            # history; only provisional, unreviewed deep versions are
            # cleaned.  Mark retained rows so exports/favorites can explain
            # that their source run is no longer available.
            retained_statuses = ("formal", "verified", "rejected", "rolled_back")
            # Preserve lineage ancestors needed by a reviewed descendant.  A
            # verified v3 may legitimately point through a provisional v2;
            # deleting v2 would otherwise leave an auditable chain broken.
            version_rows = connection.execute(
                select(capability_versions).where(
                    capability_versions.c.parent_run_id.in_(descendants)
                )
            ).mappings().all()
            by_id = {str(row["version_id"]): row for row in version_rows}
            keep_ids = {
                str(row["version_id"])
                for row in version_rows
                if str(row.get("status", "")) in retained_statuses
            }
            # Before removing provisional rows, reconnect retained descendants
            # to the nearest retained ancestor.  This preserves a traversable
            # audit chain while still honoring the rule that unreviewed drafts
            # are deleted with their source run.
            rewires: dict[str, dict[str, str]] = {}
            for row in version_rows:
                version = str(row["version_id"])
                if version not in keep_ids:
                    continue
                updates: dict[str, str] = {}
                for field in ("parent_version_id", "base_version_id"):
                    ancestor = str(row.get(field, "") or "")
                    seen: set[str] = set()
                    while ancestor and ancestor not in keep_ids and ancestor in by_id and ancestor not in seen:
                        seen.add(ancestor)
                        ancestor = str(by_id[ancestor].get(field if field == "base_version_id" else "parent_version_id", "") or "")
                    if ancestor != str(row.get(field, "") or ""):
                        updates[field] = ancestor
                if updates:
                    rewires[version] = updates
            for version, updates in rewires.items():
                connection.execute(
                    update(capability_versions)
                    .where(capability_versions.c.version_id == version)
                    .values(**updates, updated_at=_favorite_now_iso())
                )
            if keep_ids:
                connection.execute(
                    update(capability_versions)
                    .where(capability_versions.c.version_id.in_(keep_ids))
                    .values(
                        source_deleted=1,
                        source_status="deleted",
                        updated_at=_favorite_now_iso(),
                    )
                )
            delete_ids = [str(row["version_id"]) for row in version_rows if str(row["version_id"]) not in keep_ids]
            if delete_ids:
                connection.execute(
                    delete(capability_versions).where(
                        capability_versions.c.version_id.in_(delete_ids)
                    )
                )
            # Idempotency claims are scoped either to the parent run (session,
            # reference-research, cancellation and verification operations) or
            # to a deep session (message/merge operations).  Remove both kinds
            # so a permanently deleted run cannot retain replayable responses
            # or leak an old resource id when the run id is later reused.
            idempotency_scopes = descendants | set(session_ids)
            if idempotency_scopes:
                connection.execute(
                    delete(deep_idempotency).where(
                        deep_idempotency.c.scope_key.in_(idempotency_scopes)
                    )
                )
            connection.execute(
                delete(deep_run_links).where(
                    (deep_run_links.c.parent_run_id.in_(descendants))
                    | (deep_run_links.c.child_run_id.in_(descendants))
                )
            )
            connection.execute(delete(runs).where(runs.c.run_id.in_(descendants)))

    def deletion_residue(self, run_id: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            result = {
                "runs": len(connection.execute(select(runs.c.run_id).where(runs.c.run_id == run_id)).all()),
                "runtime_events": len(connection.execute(select(events.c.run_id).where(events.c.run_id == run_id)).all()),
                "run_queue": len(connection.execute(select(queue_items.c.run_id).where(queue_items.c.run_id == run_id)).all()),
                "worker_heartbeats": len(connection.execute(select(worker_heartbeats.c.worker_id).where(worker_heartbeats.c.current_run_id == run_id)).all()),
            }
            deep_counts = {
                "deep_sessions": len(connection.execute(select(deep_sessions.c.session_id).where(deep_sessions.c.parent_run_id == run_id)).all()),
                "deep_jobs": len(connection.execute(select(deep_jobs.c.job_id).where(deep_jobs.c.parent_run_id == run_id)).all()),
                "deep_events": len(connection.execute(select(deep_events.c.event_id).where(deep_events.c.parent_run_id == run_id)).all()),
                "capability_versions": len(connection.execute(select(capability_versions.c.version_id).where(capability_versions.c.parent_run_id == run_id)).all()),
            }
            result.update({key: value for key, value in deep_counts.items() if value})
            return result


class SqlRunQueue:
    def __init__(self, engine: Engine, *, generation: str = RUNTIME_BUILD_HASH) -> None:
        self.engine = engine
        self._lock = Lock()
        self.generation = str(generation)
        self._pending_status = pending_queue_status(self.generation)
        self._claimed_status = claimed_queue_status(self.generation)
        metadata.create_all(engine)

    def enqueue(self, run_id: str, *, allow_claimed: bool = False) -> None:
        for attempt in range(8):
            try:
                with self._lock, self.engine.begin() as connection:
                    existing = connection.execute(
                        select(queue_items.c.status, queue_items.c.ordinal).where(
                            queue_items.c.run_id == run_id
                        )
                    ).mappings().one_or_none()
                    if existing is None:
                        next_ordinal = (
                            connection.execute(
                                select(queue_items.c.ordinal)
                                .order_by(queue_items.c.ordinal.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            or 0
                        ) + 1
                        connection.execute(
                            queue_items.insert().values(
                                run_id=run_id,
                                status=self._pending_status,
                                ordinal=next_ordinal,
                            )
                        )
                    elif str(existing["status"]).startswith("claimed"):
                        if not allow_claimed:
                            # A claimed row represents a live Worker lease.
                            # Never turn it back into pending merely because a
                            # second resume request arrived: doing so lets
                            # another Worker execute the same run concurrently.
                            return
                        # The service has already verified that no live Worker
                        # owns this run; a stale claim can be reopened.
                        next_ordinal = (
                            connection.execute(
                                select(queue_items.c.ordinal)
                                .order_by(queue_items.c.ordinal.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            or 0
                        ) + 1
                        connection.execute(
                            update(queue_items)
                            .where(queue_items.c.run_id == run_id)
                            .values(status=self._pending_status, ordinal=next_ordinal)
                        )
                    elif existing["status"] != self._pending_status:
                        # A failed/completed attempt leaves an acked row for audit and
                        # idempotency.  Resuming the same run must make that row
                        # claimable again and place it behind already-pending work.
                        next_ordinal = (
                            connection.execute(
                                select(queue_items.c.ordinal)
                                .order_by(queue_items.c.ordinal.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            or 0
                        ) + 1
                        connection.execute(
                            update(queue_items)
                            .where(queue_items.c.run_id == run_id)
                            .values(status=self._pending_status, ordinal=next_ordinal)
                        )
                return
            except IntegrityError:
                # Queue instances live in separate API/Worker processes, so
                # two starters may both observe the same maximum ordinal.
                # Re-read the durable queue after a short bounded backoff.
                if attempt == 7:
                    raise
                time.sleep(0.005 * (attempt + 1))

    def claim(self, *, generation: str | None = None) -> str | None:
        if str(generation or self.generation) != self.generation:
            return None
        candidate = (
            select(queue_items.c.run_id)
            .where(queue_items.c.status == self._pending_status)
            .order_by(queue_items.c.ordinal)
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(queue_items)
            .where(
                queue_items.c.run_id == candidate,
                queue_items.c.status == self._pending_status,
            )
            .values(status=self._claimed_status)
            .returning(queue_items.c.run_id)
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement).scalar_one_or_none()
        return str(row) if row is not None else None

    def ack(self, run_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(queue_items).where(queue_items.c.run_id == run_id).values(status="acked"))

    def retry(self, run_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(queue_items).where(queue_items.c.run_id == run_id).values(status=self._pending_status))

    def remove(self, run_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(queue_items).where(queue_items.c.run_id == run_id))

    def pending_run_ids(self) -> list[str]:
        with self.engine.connect() as connection:
            return [str(item) for item in connection.execute(select(queue_items.c.run_id).where(queue_items.c.status == self._pending_status).order_by(queue_items.c.ordinal)).scalars().all()]
