from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
from threading import RLock
from typing import Any
from urllib.parse import quote

from equipment_deep_research.domain.models import (
    AgentRecommendation,
    AuditResult,
    BaselineFindingPacket,
    CapabilityImageItem,
    EvidenceCard,
    RecallRequest,
    ResearchProblem,
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
from equipment_deep_research.domain.workspace import RunWorkspace, path_from_fd


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
    "RunCheckpoint": "checkpoint_id",
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
        self.problems: dict[str, ResearchProblem] = {}
        self.evidence: dict[str, EvidenceCard] = {}
        self.baseline_packets: dict[str, BaselineFindingPacket] = {}
        self.recall_requests: dict[str, RecallRequest] = {}
        self.recommendations: dict[str, AgentRecommendation] = {}
        self.stage_outputs: dict[str, WinningMechanismStageOutput] = {}
        self.capability_images: dict[str, CapabilityImageItem] = {}
        self.audits: dict[str, AuditResult] = {}
        self.reports: dict[str, ResearchReport] = {}

    def add_problem(self, item: ResearchProblem) -> None:
        self.problems[item.problem_id] = item

    def add_evidence(self, item: EvidenceCard) -> None:
        self.evidence[item.evidence_id] = item

    def add_baseline_packet(self, item: BaselineFindingPacket) -> None:
        self.baseline_packets[item.packet_id] = item

    def add_recall_request(self, item: RecallRequest) -> None:
        self.recall_requests[item.recall_id] = item

    def add_recommendation(self, item: AgentRecommendation) -> None:
        self.recommendations[item.recommendation_id] = item

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
        path.write_text(self.jsonl_text(), encoding="utf-8")

    def jsonl_text(self) -> str:
        rows: list[dict[str, Any]] = []
        rows.extend({"type": "ResearchProblem", "payload": to_plain(item)} for item in self.problems.values())
        rows.extend({"type": "EvidenceCard", "payload": to_plain(item)} for item in self.evidence.values())
        rows.extend({"type": "BaselineFindingPacket", "payload": to_plain(item)} for item in self.baseline_packets.values())
        rows.extend({"type": "RecallRequest", "payload": to_plain(item)} for item in self.recall_requests.values())
        rows.extend({"type": "AgentRecommendation", "payload": to_plain(item)} for item in self.recommendations.values())
        rows.extend({"type": "WinningMechanismStageOutput", "payload": to_plain(item)} for item in self.stage_outputs.values())
        rows.extend({"type": "CapabilityImageItem", "payload": to_plain(item)} for item in self.capability_images.values())
        rows.extend({"type": "AuditResult", "payload": to_plain(item)} for item in self.audits.values())
        rows.extend({"type": "ResearchReport", "payload": to_plain(item)} for item in self.reports.values())
        return "\n".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            for row in rows
        ) + ("\n" if rows else "")

    def summary(self) -> dict[str, Any]:
        return {
            "problem_count": len(self.problems),
            "evidence_count": len(self.evidence),
            "baseline_packet_count": len(self.baseline_packets),
            "recall_request_count": len(self.recall_requests),
            "recommendation_count": len(self.recommendations),
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
        path.write_text(self.jsonl_text(), encoding="utf-8")

    def jsonl_text(self) -> str:
        return "\n".join(
            json.dumps(
                {"type": "TraceEvent", "payload": to_plain(event)},
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            for event in self.events
        ) + ("\n" if self.events else "")

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


class _ConnectionLease:
    def __init__(self, connection: sqlite3.Connection, lock: RLock) -> None:
        self._connection = connection
        self._lock = lock
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.release()


class SqliteRunStore:
    @classmethod
    def for_workspace(
        cls,
        workspace: RunWorkspace,
        *,
        run_id: str,
        busy_timeout_ms: int = 5000,
    ) -> "SqliteRunStore":
        store: SqliteRunStore | None = None
        try:
            with ExitStack() as handles:
                database_fd = workspace.dup_database_fd()
                handles.callback(os.close, database_fd)
                database_dir_fd = workspace.dup_run_fd()
                handles.callback(os.close, database_dir_fd)
                store = cls(
                    workspace.database_path,
                    run_id=run_id,
                    busy_timeout_ms=busy_timeout_ms,
                    database_fd=database_fd,
                    database_dir_fd=database_dir_fd,
                )
            return store
        except BaseException:
            if store is not None:
                store.close()
            raise

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        busy_timeout_ms: int = 5000,
        database_fd: int | None = None,
        database_dir_fd: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.run_id = _required_text(run_id, "run_id")
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be positive")
        self.busy_timeout_ms = busy_timeout_ms
        self._connection_lock = RLock()
        self._database_fd: int | None = None
        self._database_dir_fd: int | None = None
        self._sqlite_handle_fd: int | None = None
        self._connection: sqlite3.Connection | None = None
        try:
            connection_path = self._prepare_connection_path(
                database_fd=database_fd,
                database_dir_fd=database_dir_fd,
            )
            descriptors_before = (
                _open_descriptor_stats() if self._database_fd is not None else {}
            )
            sqlite_target: str | Path = connection_path
            connect_kwargs: dict[str, Any] = {}
            if self._database_fd is not None:
                sqlite_target = f"file:{quote(str(connection_path))}?mode=rw"
                connect_kwargs["uri"] = True
            self._connection = sqlite3.connect(
                sqlite_target,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
                check_same_thread=False,
                **connect_kwargs,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._connection.execute("PRAGMA foreign_keys=ON")
            if self._database_fd is not None:
                try:
                    self._sqlite_handle_fd = _duplicate_new_matching_descriptor(
                        expected=os.fstat(self._database_fd),
                        descriptors_before=descriptors_before,
                    )
                except RuntimeError:
                    self._sqlite_handle_fd = _duplicate_reused_sqlite_descriptor(
                        expected=os.fstat(self._database_fd),
                        descriptors_before=descriptors_before,
                        connection=self._connection,
                    )
            self._initialize()
        except BaseException:
            self.close()
            raise

    def _prepare_connection_path(
        self,
        *,
        database_fd: int | None,
        database_dir_fd: int | None,
    ) -> Path:
        if database_dir_fd is not None and database_fd is None:
            raise ValueError("database_dir_fd requires database_fd")
        if database_fd is None:
            if self.path.is_symlink():
                raise ValueError("SQLite path must not be a symlink")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink():
                raise ValueError("SQLite path must not be a symlink")
            return self.path
        try:
            self._database_fd = os.dup(database_fd)
        except OSError as exc:
            raise ValueError("database_fd must be open") from exc
        bound_stat = os.fstat(self._database_fd)
        if not stat.S_ISREG(bound_stat.st_mode):
            raise ValueError("database_fd must reference a regular file")
        connection_path = path_from_fd(self._database_fd)
        current_stat = os.stat(connection_path, follow_symlinks=False)
        if _file_identity(bound_stat) != _file_identity(current_stat):
            raise RuntimeError("bound SQLite file changed before connection")
        if database_dir_fd is not None:
            try:
                self._database_dir_fd = os.dup(database_dir_fd)
            except OSError as exc:
                raise ValueError("database_dir_fd must be open") from exc
            if not stat.S_ISDIR(os.fstat(self._database_dir_fd).st_mode):
                raise ValueError("database_dir_fd must reference a directory")
        if self._database_dir_fd is not None:
            directory_stat = os.stat(
                self.path.name,
                dir_fd=self._database_dir_fd,
                follow_symlinks=False,
            )
            if _file_identity(bound_stat) != _file_identity(directory_stat):
                raise RuntimeError("bound SQLite directory does not contain run.db")
            self._reject_legacy_sqlite_sidecars()
        return connection_path

    def _reject_legacy_sqlite_sidecars(self) -> None:
        if self._database_fd is None or self._database_dir_fd is None:
            return
        header = os.pread(self._database_fd, 20, 0)
        if len(header) >= 20 and (header[18] == 2 or header[19] == 2):
            raise RuntimeError(
                "legacy WAL SQLite databases require an offline trusted migration"
            )
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.stat(
                    f"{self.path.name}{suffix}",
                    dir_fd=self._database_dir_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            raise RuntimeError(
                f"legacy SQLite sidecar requires an offline trusted migration: {suffix}"
            )

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        self._connection = None
        sqlite_descriptor = getattr(self, "_sqlite_handle_fd", None)
        self._sqlite_handle_fd = None
        descriptor = getattr(self, "_database_fd", None)
        self._database_fd = None
        directory_descriptor = getattr(self, "_database_dir_fd", None)
        self._database_dir_fd = None
        try:
            if connection is not None:
                connection.close()
        finally:
            for owned_descriptor in (
                sqlite_descriptor,
                descriptor,
                directory_descriptor,
            ):
                if owned_descriptor is not None:
                    try:
                        os.close(owned_descriptor)
                    except OSError:
                        pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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

            domains_to_write, traces_to_write = self._preflight_writes(
                connection, domains, traces
            )
            for item in domains_to_write:
                self._write_domain(connection, item, committed_at)

            next_sequence = self._last_trace_sequence(connection)
            for item in traces_to_write:
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
            summary = {
                "run_id": self.run_id,
                "checkpoint_id": checkpoint_id,
                "last_checkpoint": checkpoint_id,
                "object_count": sum(object_counts.values()),
                "trace_count": trace_count,
                "last_trace_sequence": self._last_trace_sequence(connection),
                "last_runtime_event_sequence": (
                    self._last_runtime_event_sequence(connection)
                ),
                "object_counts": object_counts,
            }
        finally:
            connection.close()
        summary["unresolved_session_writes"] = self.unresolved_session_writes()
        return summary

    def unresolved_session_writes(
        self,
        *,
        agent_id: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events = self.trace_events(after_sequence=0)
        resolved_marker_ids = {
            str(_session_marker_payload(event["payload"]).get("marker_id"))
            for event in events
            if event["event_type"] == "session_reconciled"
            and _session_marker_payload(event["payload"]).get("marker_id")
        }
        markers: list[dict[str, Any]] = []
        for event in events:
            if event["event_type"] != "session_write_failed":
                continue
            payload = _session_marker_payload(event["payload"])
            marker_id = str(payload.get("marker_id") or event["proposal_id"])
            marker_agent_id = str(payload.get("agent_id") or event["actor"])
            marker_task_id = str(payload.get("task_id") or "")
            if marker_id in resolved_marker_ids:
                continue
            if agent_id is not None and marker_agent_id != agent_id:
                continue
            if task_id is not None and marker_task_id != task_id:
                continue
            markers.append(
                {
                    "marker_id": marker_id,
                    "run_id": self.run_id,
                    "checkpoint_id": payload.get("committed_checkpoint_id"),
                    "batch_hash": payload.get("batch_hash"),
                    "turn_index": payload.get("turn_index"),
                    "task_id": marker_task_id,
                    "agent_id": marker_agent_id,
                    "execution_id": payload.get("execution_id"),
                    "session_ref": payload.get("session_ref"),
                    "session_event": payload.get("session_event"),
                    "trace_sequence": event["sequence"],
                }
            )
        return markers

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

    def allocate_runtime_event_sequence(self) -> int:
        """Atomically advance and return this run's durable runtime sequence."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT last_sequence
                FROM runtime_event_state
                WHERE run_id = ?
                """,
                (self.run_id,),
            ).fetchone()
            if row is None:
                current = self._last_trace_sequence(connection)
                connection.execute(
                    """
                    INSERT INTO runtime_event_state (run_id, last_sequence)
                    VALUES (?, ?)
                    """,
                    (self.run_id, current),
                )
            else:
                current = int(row["last_sequence"])
            next_sequence = current + 1
            connection.execute(
                """
                UPDATE runtime_event_state
                SET last_sequence = ?
                WHERE run_id = ?
                """,
                (next_sequence, self.run_id),
            )
            connection.commit()
            return next_sequence
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def last_runtime_event_sequence(self) -> int:
        connection = self._connect()
        try:
            return self._last_runtime_event_sequence(connection)
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

    def domain_objects(self, *, object_type: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT object_type, object_id, payload_json, updated_at
            FROM domain_objects
            WHERE run_id = ?
        """
        parameters: list[Any] = [self.run_id]
        if object_type is not None:
            sql += " AND object_type = ?"
            parameters.append(object_type)
        sql += " ORDER BY object_type, object_id"
        connection = self._connect()
        try:
            rows = connection.execute(sql, parameters).fetchall()
            return [
                {
                    "type": str(row["object_type"]),
                    "object_id": str(row["object_id"]),
                    "payload": json.loads(row["payload_json"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ]
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
            journal_mode = connection.execute("PRAGMA journal_mode=MEMORY").fetchone()[0]
            if str(journal_mode).lower() != "memory":
                raise RuntimeError("SQLite memory journal mode is unavailable")
            connection.execute("PRAGMA synchronous=FULL")
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
                CREATE TABLE IF NOT EXISTS runtime_event_state (
                    run_id TEXT PRIMARY KEY,
                    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0)
                );
                CREATE INDEX IF NOT EXISTS domain_objects_run_type
                    ON domain_objects (run_id, object_type);
                CREATE INDEX IF NOT EXISTS trace_events_run_sequence
                    ON trace_events (run_id, run_sequence);
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO runtime_event_state (run_id, last_sequence)
                SELECT ?, COALESCE(MAX(run_sequence), 0)
                FROM trace_events
                WHERE run_id = ?
                """,
                (self.run_id, self.run_id),
            )
        finally:
            connection.close()

    def _connect(self) -> _ConnectionLease:
        self._connection_lock.acquire()
        connection = self._connection
        if connection is None:
            self._connection_lock.release()
            raise RuntimeError("SQLite store is closed")
        try:
            self._verify_bound_database_handles()
        except BaseException:
            self._connection_lock.release()
            raise
        return _ConnectionLease(connection, self._connection_lock)

    def _verify_bound_database_handles(self) -> None:
        if self._database_fd is None:
            return
        if self._sqlite_handle_fd is None:
            raise RuntimeError("SQLite bound database audit handle is missing")
        expected = os.fstat(self._database_fd)
        audited = os.fstat(self._sqlite_handle_fd)
        if _file_identity(expected) != _file_identity(audited):
            raise RuntimeError("SQLite bound database handle changed")
        if self._database_dir_fd is not None:
            current = os.stat(
                self.path.name,
                dir_fd=self._database_dir_fd,
                follow_symlinks=False,
            )
            if _file_identity(expected) != _file_identity(current):
                raise RuntimeError("SQLite bound database name changed")

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

    def _preflight_writes(
        self,
        connection: sqlite3.Connection,
        domains: Sequence[_ValidatedDomainProposal],
        traces: Sequence[_ValidatedTraceProposal],
    ) -> tuple[list[_ValidatedDomainProposal], list[_ValidatedTraceProposal]]:
        existing_proposals, existing_idempotency = self._check_ledger(
            connection,
            domains,
            traces,
        )
        seen_idempotency = set(existing_idempotency)
        object_writes: dict[tuple[str, str], _ValidatedDomainProposal] = {}
        domains_to_write: list[_ValidatedDomainProposal] = []
        for item in domains:
            proposal = item.proposal
            if proposal.proposal_id in existing_proposals:
                continue
            if proposal.idempotency_key in seen_idempotency:
                continue
            object_key = (proposal.object_type, item.object_id)
            previous = object_writes.get(object_key)
            if previous is not None:
                raise StoreConflictError(
                    "batch object conflict for "
                    f"{proposal.object_type}/{item.object_id}: "
                    f"{previous.proposal.proposal_id} and {proposal.proposal_id}"
                )
            object_writes[object_key] = item
            domains_to_write.append(item)
            seen_idempotency.add(proposal.idempotency_key)

        for item in domains_to_write:
            proposal = item.proposal
            if proposal.operation != "append":
                continue
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

        traces_to_write = [
            item
            for item in traces
            if item.proposal.proposal_id not in existing_proposals
        ]
        return domains_to_write, traces_to_write

    def _write_domain(
        self,
        connection: sqlite3.Connection,
        item: _ValidatedDomainProposal,
        committed_at: str,
    ) -> None:
        proposal = item.proposal
        if proposal.operation == "append":
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

    def _last_runtime_event_sequence(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            """
            SELECT last_sequence
            FROM runtime_event_state
            WHERE run_id = ?
            """,
            (self.run_id,),
        ).fetchone()
        if row is None:
            return self._last_trace_sequence(connection)
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


def _session_marker_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("payload")
    if (
        payload.get("event_type") in {"session_write_failed", "session_reconciled"}
        and isinstance(nested, Mapping)
    ):
        return nested
    return payload


def _file_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _descriptor_directory() -> Path:
    if Path("/dev/fd").is_dir():
        return Path("/dev/fd")
    if Path("/proc/self/fd").is_dir():
        return Path("/proc/self/fd")
    raise RuntimeError("SQLite descriptor auditing is unavailable")


def _open_descriptor_numbers() -> set[int]:
    try:
        return {
            int(name)
            for name in os.listdir(_descriptor_directory())
            if name.isdigit()
        }
    except OSError as exc:
        raise RuntimeError("SQLite descriptor auditing is unavailable") from exc


def _open_descriptor_stats() -> dict[int, os.stat_result]:
    values: dict[int, os.stat_result] = {}
    for descriptor in _open_descriptor_numbers():
        try:
            values[descriptor] = os.fstat(descriptor)
        except OSError:
            continue
    return values


def _duplicate_new_matching_descriptor(
    *,
    expected: os.stat_result,
    descriptors_before: Mapping[int, os.stat_result],
) -> int:
    expected_identity = _file_identity(expected)
    for descriptor, value in _open_descriptor_stats().items():
        previous = descriptors_before.get(descriptor)
        if previous is not None and _file_identity(previous) == _file_identity(value):
            continue
        if stat.S_ISREG(value.st_mode) and _file_identity(value) == expected_identity:
            return os.dup(descriptor)
    raise RuntimeError("SQLite did not retain a handle to the bound database file")


def _duplicate_reused_sqlite_descriptor(
    *,
    expected: os.stat_result,
    descriptors_before: Mapping[int, os.stat_result],
    connection: sqlite3.Connection,
) -> int:
    expected_identity = _file_identity(expected)
    current = _open_descriptor_stats()
    new_regular = [
        value
        for descriptor, value in current.items()
        if stat.S_ISREG(value.st_mode)
        and (
            descriptor not in descriptors_before
            or _file_identity(descriptors_before[descriptor]) != _file_identity(value)
        )
    ]
    if new_regular:
        raise RuntimeError("SQLite opened a database outside the bound inode")
    database_rows = connection.execute("PRAGMA database_list").fetchall()
    if len(database_rows) != 1:
        raise RuntimeError("SQLite database handle audit is ambiguous")
    database_path = Path(str(database_rows[0][2]))
    current_path_stat = os.stat(database_path, follow_symlinks=False)
    if _file_identity(current_path_stat) != expected_identity:
        raise RuntimeError("SQLite database path no longer references the bound inode")
    for descriptor, value in current.items():
        if stat.S_ISREG(value.st_mode) and _file_identity(value) == expected_identity:
            return os.dup(descriptor)
    raise RuntimeError("SQLite reusable database handle disappeared")


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
