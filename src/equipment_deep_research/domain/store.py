from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from equipment_deep_research.domain.models import (
    AuditResult,
    BaselineFindingPacket,
    CapabilityImageItem,
    EvidenceCard,
    ResearchReport,
    TraceEvent,
    WinningMechanismStageOutput,
    now_iso,
    to_plain,
)
from equipment_deep_research.domain.proposals import (
    DomainWriteProposal,
    TraceProposal,
    thaw_plain,
)


class StoreValidationError(ValueError):
    pass


class StoreConflictError(RuntimeError):
    pass


_OBJECT_ID_FIELDS = {
    "ResearchProblem": "problem_id",
    "EvidenceCard": "evidence_id",
    "BaselineFindingPacket": "packet_id",
    "RecallRequest": "recall_id",
    "AgentRecommendation": "recommendation_id",
    "WinningMechanismStageOutput": "stage_id",
    "CapabilityImageItem": "capability_id",
    "AuditResult": "audit_id",
    "ResearchReport": "report_id",
}


@dataclass(frozen=True)
class _ValidatedDomainProposal:
    proposal: DomainWriteProposal
    object_id: str
    payload: dict[str, Any]
    payload_json: str
    proposal_hash: str
    idempotency_hash: str


@dataclass(frozen=True)
class _ValidatedTraceProposal:
    proposal: TraceProposal
    payload: dict[str, Any]
    payload_json: str
    proposal_hash: str


class DomainStore:
    def __init__(self) -> None:
        self.evidence: dict[str, EvidenceCard] = {}
        self.baseline_packets: dict[str, BaselineFindingPacket] = {}
        self.stage_outputs: dict[str, WinningMechanismStageOutput] = {}
        self.capability_images: dict[str, CapabilityImageItem] = {}
        self.audits: dict[str, AuditResult] = {}
        self.reports: dict[str, ResearchReport] = {}

    def add_evidence(self, item: EvidenceCard) -> None:
        self.evidence[item.evidence_id] = item

    def add_baseline_packet(self, item: BaselineFindingPacket) -> None:
        self.baseline_packets[item.packet_id] = item

    def add_stage_output(self, item: WinningMechanismStageOutput) -> None:
        self.stage_outputs[item.stage_id] = item

    def add_capability_image(self, item: CapabilityImageItem) -> None:
        item.validate()
        self.capability_images[item.capability_id] = item

    def add_audit(self, item: AuditResult) -> None:
        self.audits[item.audit_id] = item

    def add_report(self, item: ResearchReport) -> None:
        self.reports[item.report_id] = item

    def evidence_index(self) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "source_title": item.source_title,
                "source_tier": item.source_tier,
                "claim": item.claim,
                "created_by": item.created_by,
            }
            for item in self.evidence.values()
        ]

    def coverage_tags(self) -> set[str]:
        tags: set[str] = set()
        for packet in self.baseline_packets.values():
            tags.update(packet.capability_tags)
        return tags

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        rows.extend({"type": "EvidenceCard", "payload": to_plain(item)} for item in self.evidence.values())
        rows.extend({"type": "BaselineFindingPacket", "payload": to_plain(item)} for item in self.baseline_packets.values())
        rows.extend({"type": "WinningMechanismStageOutput", "payload": to_plain(item)} for item in self.stage_outputs.values())
        rows.extend({"type": "CapabilityImageItem", "payload": to_plain(item)} for item in self.capability_images.values())
        rows.extend({"type": "AuditResult", "payload": to_plain(item)} for item in self.audits.values())
        rows.extend({"type": "ResearchReport", "payload": to_plain(item)} for item in self.reports.values())
        path.write_text(
            "\n".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                for row in rows
            )
            + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def summary(self) -> dict[str, Any]:
        return {
            "evidence_count": len(self.evidence),
            "baseline_packet_count": len(self.baseline_packets),
            "stage_output_count": len(self.stage_outputs),
            "capability_image_count": len(self.capability_images),
            "audit_count": len(self.audits),
            "report_count": len(self.reports),
            "coverage_tags": sorted(self.coverage_tags()),
            "materialized_evidence_count": sum(1 for item in self.evidence.values() if item.artifact_refs),
        }


class TraceStore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def append(self, event: TraceEvent) -> None:
        self.events.append(event)

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                json.dumps(
                    {"type": "TraceEvent", "payload": to_plain(event)},
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                for event in self.events
            )
            + ("\n" if self.events else ""),
            encoding="utf-8",
        )

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "event_type": event.event_type,
                "actor": event.actor,
                "summary": event.summary,
                "output_refs": list(event.output_refs),
            }
            for event in self.events
        ]


class SqliteRunStore:
    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.run_id = _required_text(run_id, "run_id")
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self.busy_timeout_ms = busy_timeout_ms
        if self.path.is_symlink():
            raise ValueError("SQLite path must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("SQLite path must not be a symlink")
        self._initialize()

    def commit(
        self,
        domain_proposals: Sequence[DomainWriteProposal],
        trace_proposals: Sequence[TraceProposal],
    ) -> str:
        domains, traces = self._validate_proposals(domain_proposals, trace_proposals)
        proposal_records = [
            {"channel": "domain", **item.proposal.to_plain()} for item in domains
        ] + [{"channel": "trace", **item.proposal.to_plain()} for item in traces]
        proposal_records.sort(
            key=lambda record: (str(record["proposal_id"]), str(record["channel"]))
        )
        request_json = _strict_json(proposal_records)
        request_fingerprint = _hash_text(request_json)
        proposal_keys_json = _strict_json(
            [
                {
                    "channel": record["channel"],
                    "proposal_id": record["proposal_id"],
                    **(
                        {"idempotency_key": record["idempotency_key"]}
                        if record["channel"] == "domain"
                        else {}
                    ),
                }
                for record in proposal_records
            ]
        )
        checkpoint_id = f"checkpoint-{_hash_text(f'{self.run_id}:{request_fingerprint}')[:24]}"
        committed_at = now_iso()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_checkpoint = connection.execute(
                """
                SELECT checkpoint_id
                FROM savepoints
                WHERE run_id = ? AND request_fingerprint = ?
                """,
                (self.run_id, request_fingerprint),
            ).fetchone()
            if existing_checkpoint is not None:
                connection.commit()
                return str(existing_checkpoint["checkpoint_id"])

            existing_proposals, existing_idempotency = self._check_ledger(
                connection, domains, traces
            )
            written_idempotency: set[str] = set(existing_idempotency)
            for item in domains:
                proposal = item.proposal
                if proposal.proposal_id in existing_proposals:
                    continue
                if proposal.idempotency_key in written_idempotency:
                    continue
                self._write_domain(connection, item, committed_at)
                written_idempotency.add(proposal.idempotency_key)

            next_sequence = self._last_trace_sequence(connection)
            for item in traces:
                if item.proposal.proposal_id in existing_proposals:
                    continue
                next_sequence += 1
                connection.execute(
                    """
                    INSERT INTO trace_events (
                        run_id, run_sequence, proposal_id, event_type, actor,
                        payload_json, created_at, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.run_id,
                        next_sequence,
                        item.proposal.proposal_id,
                        item.proposal.event_type,
                        item.proposal.actor,
                        item.payload_json,
                        committed_at,
                        "1.0",
                    ),
                )

            ordinal = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM savepoints WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO savepoints (
                    checkpoint_id, run_id, ordinal, request_fingerprint,
                    proposal_keys_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    self.run_id,
                    ordinal,
                    request_fingerprint,
                    proposal_keys_json,
                    committed_at,
                ),
            )
            self._record_ledger(connection, domains, traces, checkpoint_id, committed_at)
            connection.commit()
            return checkpoint_id
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.rollback()
            raise StoreConflictError(f"SQLite savepoint conflict: {exc}") from exc
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def recover(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            checkpoint = connection.execute(
                """
                SELECT checkpoint_id
                FROM savepoints
                WHERE run_id = ?
                ORDER BY ordinal DESC
                LIMIT 1
                """,
                (self.run_id,),
            ).fetchone()
            counts = connection.execute(
                """
                SELECT object_type, COUNT(*) AS item_count
                FROM domain_objects
                WHERE run_id = ?
                GROUP BY object_type
                ORDER BY object_type
                """,
                (self.run_id,),
            ).fetchall()
            object_counts = {
                str(row["object_type"]): int(row["item_count"]) for row in counts
            }
            trace_count = self._trace_count(connection)
            checkpoint_id = (
                str(checkpoint["checkpoint_id"]) if checkpoint is not None else None
            )
            return {
                "run_id": self.run_id,
                "checkpoint_id": checkpoint_id,
                "last_checkpoint": checkpoint_id,
                "object_count": sum(object_counts.values()),
                "trace_count": trace_count,
                "last_trace_sequence": self._last_trace_sequence(connection),
                "object_counts": object_counts,
            }
        finally:
            connection.close()

    def count(self, object_type: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT COUNT(*) AS item_count
                FROM domain_objects
                WHERE run_id = ? AND object_type = ?
                """,
                (self.run_id, object_type),
            ).fetchone()
            return int(row["item_count"])
        finally:
            connection.close()

    def object_count(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS item_count FROM domain_objects WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            return int(row["item_count"])
        finally:
            connection.close()

    def trace_count(self) -> int:
        connection = self._connect()
        try:
            return self._trace_count(connection)
        finally:
            connection.close()

    def last_trace_sequence(self) -> int:
        connection = self._connect()
        try:
            return self._last_trace_sequence(connection)
        finally:
            connection.close()

    def trace_events(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        sql = """
            SELECT run_sequence, proposal_id, event_type, actor, payload_json,
                   created_at, schema_version
            FROM trace_events
            WHERE run_id = ? AND run_sequence > ?
            ORDER BY run_sequence
        """
        parameters: list[Any] = [self.run_id, after_sequence]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        connection = self._connect()
        try:
            rows = connection.execute(sql, parameters).fetchall()
            return [self._trace_row_to_plain(row) for row in rows]
        finally:
            connection.close()

    def export_domain_jsonl(self, path: Path) -> None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT object_type, payload_json
                FROM domain_objects
                WHERE run_id = ?
                ORDER BY object_type, object_id
                """,
                (self.run_id,),
            ).fetchall()
            records = [
                {"type": str(row["object_type"]), "payload": json.loads(row["payload_json"])}
                for row in rows
            ]
        finally:
            connection.close()
        _write_jsonl(path, records)

    def export_trace_jsonl(self, path: Path) -> None:
        records = [
            {"type": "TraceEvent", "payload": event}
            for event in self.trace_events(after_sequence=0)
        ]
        _write_jsonl(path, records)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS domain_objects (
                    run_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    PRIMARY KEY (run_id, object_type, object_id)
                );
                CREATE TABLE IF NOT EXISTS trace_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    run_sequence INTEGER NOT NULL,
                    proposal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    UNIQUE (run_id, run_sequence),
                    UNIQUE (run_id, proposal_id)
                );
                CREATE TABLE IF NOT EXISTS savepoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    proposal_keys_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, ordinal),
                    UNIQUE (run_id, request_fingerprint)
                );
                CREATE TABLE IF NOT EXISTS proposal_ledger (
                    run_id TEXT NOT NULL,
                    key_kind TEXT NOT NULL,
                    key_value TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, key_kind, key_value)
                );
                CREATE INDEX IF NOT EXISTS domain_objects_run_type
                    ON domain_objects (run_id, object_type);
                CREATE INDEX IF NOT EXISTS trace_events_run_sequence
                    ON trace_events (run_id, run_sequence);
                """
            )
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _validate_proposals(
        self,
        domain_proposals: Sequence[DomainWriteProposal],
        trace_proposals: Sequence[TraceProposal],
    ) -> tuple[list[_ValidatedDomainProposal], list[_ValidatedTraceProposal]]:
        try:
            domain_values = list(domain_proposals)
            trace_values = list(trace_proposals)
        except TypeError as exc:
            raise StoreValidationError("proposals must be finite sequences") from exc
        if not all(isinstance(item, DomainWriteProposal) for item in domain_values):
            raise StoreValidationError("domain proposals must contain DomainWriteProposal values")
        if not all(isinstance(item, TraceProposal) for item in trace_values):
            raise StoreValidationError("trace proposals must contain TraceProposal values")

        domains = [self._validate_domain(item) for item in domain_values]
        traces = [self._validate_trace(item) for item in trace_values]
        proposal_ids: dict[str, str] = {}
        idempotency_keys: dict[str, str] = {}
        unique_domains: list[_ValidatedDomainProposal] = []
        unique_traces: list[_ValidatedTraceProposal] = []
        for item in domains:
            proposal_id = item.proposal.proposal_id
            existing = proposal_ids.get(proposal_id)
            if existing is not None:
                if existing != item.proposal_hash:
                    raise StoreConflictError(f"proposal_id conflict: {proposal_id}")
                continue
            proposal_ids[proposal_id] = item.proposal_hash
            idem = item.proposal.idempotency_key
            existing_idem = idempotency_keys.get(idem)
            if existing_idem is not None and existing_idem != item.idempotency_hash:
                raise StoreConflictError(f"idempotency key conflict: {idem}")
            idempotency_keys[idem] = item.idempotency_hash
            unique_domains.append(item)
        for item in traces:
            proposal_id = item.proposal.proposal_id
            existing = proposal_ids.get(proposal_id)
            if existing is not None:
                if existing != item.proposal_hash:
                    raise StoreConflictError(f"proposal_id conflict: {proposal_id}")
                continue
            proposal_ids[proposal_id] = item.proposal_hash
            unique_traces.append(item)
        return unique_domains, unique_traces

    def _validate_domain(self, proposal: DomainWriteProposal) -> _ValidatedDomainProposal:
        _required_text(proposal.proposal_id, "proposal_id", StoreValidationError)
        _required_text(proposal.idempotency_key, "idempotency_key", StoreValidationError)
        if proposal.operation not in {"upsert", "append"}:
            raise StoreValidationError(f"unsupported operation: {proposal.operation}")
        id_field = _OBJECT_ID_FIELDS.get(proposal.object_type)
        if id_field is None:
            raise StoreValidationError(
                f"unsupported object_type: {proposal.object_type}"
            )
        payload = thaw_plain(proposal.payload)
        if not isinstance(payload, dict):
            raise StoreValidationError("domain proposal payload must be a JSON object")
        object_id = _required_text(payload.get(id_field), id_field, StoreValidationError)
        _required_text(payload.get("schema_version"), "schema_version", StoreValidationError)
        _validate_created_at(payload.get("created_at"))
        try:
            payload_json = _strict_json(payload)
        except (TypeError, ValueError) as exc:
            raise StoreValidationError(f"invalid domain payload: {exc}") from exc
        proposal_hash = _hash_json(
            {
                "channel": "domain",
                "object_type": proposal.object_type,
                "operation": proposal.operation,
                "payload": payload,
                "idempotency_key": proposal.idempotency_key,
            }
        )
        idempotency_hash = _hash_json(
            {
                "object_type": proposal.object_type,
                "operation": proposal.operation,
                "payload": payload,
            }
        )
        return _ValidatedDomainProposal(
            proposal,
            object_id,
            payload,
            payload_json,
            proposal_hash,
            idempotency_hash,
        )

    def _validate_trace(self, proposal: TraceProposal) -> _ValidatedTraceProposal:
        _required_text(proposal.proposal_id, "proposal_id", StoreValidationError)
        _required_text(proposal.event_type, "event_type", StoreValidationError)
        _required_text(proposal.actor, "actor", StoreValidationError)
        payload = thaw_plain(proposal.payload)
        if not isinstance(payload, dict):
            raise StoreValidationError("trace proposal payload must be a JSON object")
        try:
            payload_json = _strict_json(payload)
        except (TypeError, ValueError) as exc:
            raise StoreValidationError(f"invalid trace payload: {exc}") from exc
        proposal_hash = _hash_json(
            {
                "channel": "trace",
                "event_type": proposal.event_type,
                "actor": proposal.actor,
                "payload": payload,
            }
        )
        return _ValidatedTraceProposal(
            proposal, payload, payload_json, proposal_hash
        )

    def _check_ledger(
        self,
        connection: sqlite3.Connection,
        domains: Sequence[_ValidatedDomainProposal],
        traces: Sequence[_ValidatedTraceProposal],
    ) -> tuple[set[str], set[str]]:
        existing_proposals: set[str] = set()
        existing_idempotency: set[str] = set()
        for item in [*domains, *traces]:
            row = connection.execute(
                """
                SELECT content_hash FROM proposal_ledger
                WHERE run_id = ? AND key_kind = 'proposal_id' AND key_value = ?
                """,
                (self.run_id, item.proposal.proposal_id),
            ).fetchone()
            if row is None:
                continue
            if row["content_hash"] != item.proposal_hash:
                raise StoreConflictError(
                    f"proposal_id conflict: {item.proposal.proposal_id}"
                )
            existing_proposals.add(item.proposal.proposal_id)
        for item in domains:
            key = item.proposal.idempotency_key
            row = connection.execute(
                """
                SELECT content_hash FROM proposal_ledger
                WHERE run_id = ? AND key_kind = 'idempotency_key' AND key_value = ?
                """,
                (self.run_id, key),
            ).fetchone()
            if row is None:
                continue
            if row["content_hash"] != item.idempotency_hash:
                raise StoreConflictError(f"idempotency key conflict: {key}")
            existing_idempotency.add(key)
        return existing_proposals, existing_idempotency

    def _write_domain(
        self,
        connection: sqlite3.Connection,
        item: _ValidatedDomainProposal,
        committed_at: str,
    ) -> None:
        proposal = item.proposal
        if proposal.operation == "append":
            existing = connection.execute(
                """
                SELECT 1 FROM domain_objects
                WHERE run_id = ? AND object_type = ? AND object_id = ?
                """,
                (self.run_id, proposal.object_type, item.object_id),
            ).fetchone()
            if existing is not None:
                raise StoreConflictError(
                    f"append conflict for {proposal.object_type}/{item.object_id}"
                )
            connection.execute(
                """
                INSERT INTO domain_objects (
                    run_id, object_type, object_id, payload_json, schema_version,
                    created_at, updated_at, proposal_id, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    proposal.object_type,
                    item.object_id,
                    item.payload_json,
                    item.payload["schema_version"],
                    item.payload["created_at"],
                    committed_at,
                    proposal.proposal_id,
                    proposal.idempotency_key,
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO domain_objects (
                run_id, object_type, object_id, payload_json, schema_version,
                created_at, updated_at, proposal_id, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, object_type, object_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                schema_version = excluded.schema_version,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                proposal_id = excluded.proposal_id,
                idempotency_key = excluded.idempotency_key
            """,
            (
                self.run_id,
                proposal.object_type,
                item.object_id,
                item.payload_json,
                item.payload["schema_version"],
                item.payload["created_at"],
                committed_at,
                proposal.proposal_id,
                proposal.idempotency_key,
            ),
        )

    def _record_ledger(
        self,
        connection: sqlite3.Connection,
        domains: Sequence[_ValidatedDomainProposal],
        traces: Sequence[_ValidatedTraceProposal],
        checkpoint_id: str,
        created_at: str,
    ) -> None:
        for item in [*domains, *traces]:
            connection.execute(
                """
                INSERT OR IGNORE INTO proposal_ledger (
                    run_id, key_kind, key_value, content_hash,
                    checkpoint_id, created_at
                ) VALUES (?, 'proposal_id', ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    item.proposal.proposal_id,
                    item.proposal_hash,
                    checkpoint_id,
                    created_at,
                ),
            )
        for item in domains:
            connection.execute(
                """
                INSERT OR IGNORE INTO proposal_ledger (
                    run_id, key_kind, key_value, content_hash,
                    checkpoint_id, created_at
                ) VALUES (?, 'idempotency_key', ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    item.proposal.idempotency_key,
                    item.idempotency_hash,
                    checkpoint_id,
                    created_at,
                ),
            )

    def _trace_count(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM trace_events WHERE run_id = ?",
            (self.run_id,),
        ).fetchone()
        return int(row["item_count"])

    def _last_trace_sequence(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(run_sequence), 0) AS last_sequence
            FROM trace_events
            WHERE run_id = ?
            """,
            (self.run_id,),
        ).fetchone()
        return int(row["last_sequence"])

    def _trace_row_to_plain(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": int(row["run_sequence"]),
            "proposal_id": str(row["proposal_id"]),
            "event_type": str(row["event_type"]),
            "actor": str(row["actor"]),
            "payload": json.loads(row["payload_json"]),
            "created_at": str(row["created_at"]),
            "schema_version": str(row["schema_version"]),
        }


def _required_text(
    value: Any,
    field_name: str,
    error_type: type[ValueError] = ValueError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field_name} must be a non-empty string")
    return value


def _validate_created_at(value: Any) -> str:
    created_at = _required_text(value, "created_at", StoreValidationError)
    try:
        parsed = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise StoreValidationError("created_at must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise StoreValidationError("created_at must include a timezone")
    return created_at


def _strict_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def _hash_json(value: Any) -> str:
    return _hash_text(_strict_json(value))


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path = Path(path)
    if path.is_symlink():
        raise ValueError("JSONL export path must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_strict_json(dict(record)) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
