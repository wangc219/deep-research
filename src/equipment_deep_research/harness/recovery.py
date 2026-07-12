from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, cast

from equipment_deep_research.domain.identifiers import validate_internal_identifier
from equipment_deep_research.domain.messages import FINALIZE_TASK_ID, RunCheckpoint
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
from equipment_deep_research.domain.proposals import TraceProposal
from equipment_deep_research.domain.store import DomainStore, SqliteRunStore, TraceStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.scheduler import WorkerReport
from equipment_deep_research.harness.session import JsonlSessionStore


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryState:
    workspace: RunWorkspace
    sqlite_store: SqliteRunStore
    checkpoint: RunCheckpoint
    problem: ResearchProblem
    domain_store: DomainStore
    trace_store: TraceStore
    source_materials: list[dict[str, Any]]
    worker_reports: list[WorkerReport]
    session_tails: dict[str, list[dict[str, Any]]]
    last_savepoint_id: str

    def close(self) -> None:
        try:
            self.sqlite_store.close()
        finally:
            self.workspace.close()

    def __enter__(self) -> "RecoveryState":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class RecoveryManager:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root)

    def load(
        self,
        run_id: str,
        *,
        topic: str | None = None,
        research_route: str | None = None,
        resolved_route: str | None = None,
        selected_agent_ids: list[str] | None = None,
        config_fingerprint: str | None = None,
    ) -> RecoveryState:
        workspace = RunWorkspace.open_existing(self.output_root, run_id)
        sqlite_store: SqliteRunStore | None = None
        try:
            database_fd = workspace.dup_database_fd()
            database_dir_fd = workspace.dup_run_fd()
            try:
                sqlite_store = SqliteRunStore(
                    workspace.database_path,
                    run_id=run_id,
                    database_fd=database_fd,
                    database_dir_fd=database_dir_fd,
                )
            finally:
                os.close(database_fd)
                os.close(database_dir_fd)
            recovery_summary = sqlite_store.recover()
            last_savepoint = recovery_summary.get("last_checkpoint")
            if not isinstance(last_savepoint, str) or not last_savepoint:
                raise RecoveryError("run database has no committed savepoint")

            self._reconcile_unresolved_sessions(workspace, sqlite_store)
            checkpoint = self._load_checkpoint(sqlite_store, run_id)
            self._validate_identity(
                checkpoint,
                topic=topic,
                research_route=research_route,
                resolved_route=resolved_route,
                selected_agent_ids=selected_agent_ids,
                config_fingerprint=config_fingerprint,
            )
            domain_store = _restore_domain_store(sqlite_store.domain_objects())
            problem = self._load_problem(
                domain_store,
                topic=topic,
                research_route=research_route,
                resolved_route=resolved_route,
                selected_agent_ids=selected_agent_ids,
            )
            checkpoint = _normalize_unfinished_tasks(checkpoint)
            trace_store = _restore_trace_store(sqlite_store.trace_events())
            worker_reports = _restore_worker_reports(checkpoint.worker_reports)
            session_tails = self._load_session_tails(
                workspace,
                checkpoint,
                worker_reports,
            )
            latest_summary = sqlite_store.recover()
            latest_savepoint = latest_summary.get("last_checkpoint")
            if not isinstance(latest_savepoint, str) or not latest_savepoint:
                raise RecoveryError("run database lost its committed savepoint")
            return RecoveryState(
                workspace=workspace,
                sqlite_store=sqlite_store,
                checkpoint=checkpoint,
                problem=problem,
                domain_store=domain_store,
                trace_store=trace_store,
                source_materials=_dedupe_plain_rows(checkpoint.source_materials),
                worker_reports=worker_reports,
                session_tails=session_tails,
                last_savepoint_id=latest_savepoint,
            )
        except sqlite3.DatabaseError as exc:
            try:
                if sqlite_store is not None:
                    sqlite_store.close()
            finally:
                workspace.close()
            raise RecoveryError(f"SQLite run database is invalid: {exc}") from exc
        except BaseException:
            try:
                if sqlite_store is not None:
                    sqlite_store.close()
            finally:
                workspace.close()
            raise

    @staticmethod
    def _load_checkpoint(sqlite_store: SqliteRunStore, run_id: str) -> RunCheckpoint:
        rows = sqlite_store.domain_objects(object_type="RunCheckpoint")
        if len(rows) != 1:
            raise RecoveryError(
                f"run database must contain exactly one RunCheckpoint, found {len(rows)}"
            )
        try:
            checkpoint = RunCheckpoint.from_plain(rows[0]["payload"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError(f"RunCheckpoint is invalid: {exc}") from exc
        if checkpoint.run_id != run_id:
            raise RecoveryError("RunCheckpoint run_id mismatch")
        return checkpoint

    @staticmethod
    def _load_problem(
        domain_store: DomainStore,
        *,
        topic: str | None,
        research_route: str | None,
        resolved_route: str | None,
        selected_agent_ids: list[str] | None,
    ) -> ResearchProblem:
        problems = list(domain_store.problems.values())
        if len(problems) != 1:
            raise RecoveryError(
                f"run database must contain exactly one ResearchProblem, found {len(problems)}"
            )
        problem = problems[0]
        if topic is not None and problem.topic != topic:
            raise RecoveryError("ResearchProblem topic mismatch")
        if research_route is not None and problem.research_route != research_route:
            raise RecoveryError("ResearchProblem research route mismatch")
        if resolved_route is not None and problem.resolved_route() != resolved_route:
            raise RecoveryError("ResearchProblem resolved route mismatch")
        if (
            selected_agent_ids is not None
            and problem.selected_agent_ids != selected_agent_ids
        ):
            raise RecoveryError("ResearchProblem selected agent mismatch")
        return problem

    @staticmethod
    def _validate_identity(
        checkpoint: RunCheckpoint,
        *,
        topic: str | None,
        research_route: str | None,
        resolved_route: str | None,
        selected_agent_ids: list[str] | None,
        config_fingerprint: str | None,
    ) -> None:
        if topic is not None and checkpoint.topic != topic:
            raise RecoveryError("resume topic mismatch")
        if research_route is not None and checkpoint.research_route != research_route:
            raise RecoveryError("resume research route mismatch")
        if resolved_route is not None and checkpoint.resolved_route != resolved_route:
            raise RecoveryError("resume resolved route mismatch")
        if (
            selected_agent_ids is not None
            and checkpoint.selected_agent_ids != selected_agent_ids
        ):
            raise RecoveryError("resume selected agent mismatch")
        if (
            config_fingerprint is not None
            and checkpoint.config_fingerprint != config_fingerprint
        ):
            raise RecoveryError("resume configuration mismatch")

    @staticmethod
    def _reconcile_unresolved_sessions(
        workspace: RunWorkspace,
        sqlite_store: SqliteRunStore,
    ) -> None:
        markers = sqlite_store.unresolved_session_writes()
        for marker in markers:
            marker_id = _marker_text(marker, "marker_id")
            checkpoint_id = _marker_text(marker, "checkpoint_id")
            batch_hash = _marker_text(marker, "batch_hash")
            session_ref = _marker_text(marker, "session_ref")
            execution_id = _marker_text(marker, "execution_id")
            task_id = _marker_text(marker, "task_id")
            agent_id = _marker_text(marker, "agent_id")
            turn_index = marker.get("turn_index")
            if isinstance(turn_index, bool) or not isinstance(turn_index, int):
                raise RecoveryError(
                    f"session reconciliation marker {marker_id} has invalid turn_index"
                )
            session: JsonlSessionStore | None = None
            try:
                root_fd = workspace.dup_sessions_fd()
                try:
                    session = JsonlSessionStore(
                        session_ref,
                        root_fd=root_fd,
                        root_label=workspace.sessions_dir,
                    )
                finally:
                    os.close(root_fd)
                records = session.read_all()
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                if session is not None:
                    session.close()
                raise RecoveryError(
                    f"cannot open reconciliation session {session_ref}: {exc}"
                ) from exc
            try:
                if not any(
                    row.get("event_type") == "savepoint"
                    and row.get("checkpoint_id") == checkpoint_id
                    and row.get("batch_hash") == batch_hash
                    for row in records
                ):
                    session.append(
                        {
                            "event_type": "savepoint",
                            "execution_id": execution_id,
                            "task_id": task_id,
                            "agent_id": agent_id,
                            "turn_index": turn_index,
                            "checkpoint_id": checkpoint_id,
                            "batch_hash": batch_hash,
                            "recovered": True,
                            "reconciliation_marker_id": marker_id,
                            "created_at": now_iso(),
                            "schema_version": "1.0",
                        }
                    )
                    records = [*records, {"event_type": "savepoint"}]
                if not any(
                    row.get("event_type") == "session_reconciled"
                    and row.get("reconciliation_marker_id") == marker_id
                    for row in records
                ):
                    session.append(
                        {
                            "event_type": "session_reconciled",
                            "execution_id": execution_id,
                            "task_id": task_id,
                            "agent_id": agent_id,
                            "turn_index": turn_index,
                            "checkpoint_id": checkpoint_id,
                            "batch_hash": batch_hash,
                            "reconciliation_marker_id": marker_id,
                            "created_at": now_iso(),
                            "schema_version": "1.0",
                        }
                    )
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                raise RecoveryError(
                    f"cannot update reconciliation session {session_ref}: {exc}"
                ) from exc
            finally:
                session.close()
            reconciled_event = TraceEvent(
                event_id=f"{marker_id}-reconciled",
                event_type="session_reconciled",
                actor=agent_id,
                summary=f"session write reconciled for {task_id}",
                payload={
                    "marker_id": marker_id,
                    "checkpoint_id": checkpoint_id,
                    "batch_hash": batch_hash,
                    "turn_index": turn_index,
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "session_ref": session_ref,
                    "recovery_status": "reconciled",
                },
            )
            sqlite_store.commit(
                (),
                (
                    TraceProposal(
                        proposal_id=reconciled_event.event_id,
                        event_type=reconciled_event.event_type,
                        actor=agent_id,
                        payload=to_plain(reconciled_event),
                    ),
                ),
            )

    @staticmethod
    def _load_session_tails(
        workspace: RunWorkspace,
        checkpoint: RunCheckpoint,
        worker_reports: list[WorkerReport],
    ) -> dict[str, list[dict[str, Any]]]:
        reports_by_agent = {report.agent_id: report for report in worker_reports}
        tails: dict[str, list[dict[str, Any]]] = {}
        for agent_id in checkpoint.selected_agent_ids:
            validated_agent_id = validate_internal_identifier(
                agent_id,
                field_name="agent_id",
            )
            session_ref = f"{validated_agent_id}.jsonl"
            try:
                root_fd = workspace.dup_sessions_fd()
                try:
                    session = JsonlSessionStore(
                        session_ref,
                        root_fd=root_fd,
                        root_label=workspace.sessions_dir,
                    )
                finally:
                    os.close(root_fd)
                try:
                    records = session.read_all()
                finally:
                    session.close()
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                raise RecoveryError(f"agent session is invalid for {agent_id}: {exc}") from exc
            if not records and f"baseline:{agent_id}" in checkpoint.completed_task_ids:
                raise RecoveryError(f"completed agent session is missing: {agent_id}")
            tails[agent_id] = records[-2:]
            report = reports_by_agent.get(agent_id)
            if report is not None and Path(report.session_path).name != session_ref:
                raise RecoveryError(f"worker report session mismatch for {agent_id}")
        return tails


def _normalize_unfinished_tasks(checkpoint: RunCheckpoint) -> RunCheckpoint:
    statuses = {
        task_id: "pending" if status == "running" else status
        for task_id, status in checkpoint.task_statuses.items()
    }
    ordered_tasks = [
        *[f"baseline:{agent_id}" for agent_id in checkpoint.selected_agent_ids],
        FINALIZE_TASK_ID,
    ]
    completed = [
        task_id for task_id in ordered_tasks if statuses.get(task_id) == "completed"
    ]
    pending = [
        task_id for task_id in ordered_tasks if statuses.get(task_id) != "completed"
    ]
    normalized = replace(
        checkpoint,
        completed_task_ids=completed,
        pending_task_ids=pending,
        task_statuses=statuses,
        status=(
            "completed"
            if statuses.get(FINALIZE_TASK_ID) == "completed"
            and all(status == "completed" for status in statuses.values())
            else "running"
        ),
    )
    normalized.validate()
    return normalized


def _restore_domain_store(rows: list[dict[str, Any]]) -> DomainStore:
    store = DomainStore()
    for row in rows:
        object_type = row["type"]
        payload = dict(cast(Mapping[str, Any], row["payload"]))
        try:
            if object_type == "ResearchProblem":
                store.add_problem(ResearchProblem(**payload))
            elif object_type == "EvidenceCard":
                store.add_evidence(EvidenceCard(**payload))
            elif object_type == "BaselineFindingPacket":
                store.add_baseline_packet(BaselineFindingPacket(**payload))
            elif object_type == "RecallRequest":
                store.add_recall_request(RecallRequest(**payload))
            elif object_type == "AgentRecommendation":
                store.add_recommendation(AgentRecommendation(**payload))
            elif object_type == "WinningMechanismStageOutput":
                payload["recall_requests"] = [
                    RecallRequest(**dict(item))
                    for item in payload.get("recall_requests", [])
                ]
                store.add_stage_output(WinningMechanismStageOutput(**payload))
            elif object_type == "CapabilityImageItem":
                store.add_capability_image(CapabilityImageItem(**payload))
            elif object_type == "AuditResult":
                store.add_audit(AuditResult(**payload))
            elif object_type == "ResearchReport":
                store.add_report(ResearchReport(**payload))
        except (TypeError, ValueError) as exc:
            raise RecoveryError(f"cannot restore {object_type}: {exc}") from exc
    return store


def _restore_trace_store(rows: list[dict[str, Any]]) -> TraceStore:
    trace = TraceStore()
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, dict) and {
            "event_id",
            "event_type",
            "actor",
            "summary",
            "created_at",
            "schema_version",
        } <= payload.keys():
            try:
                event = TraceEvent(**payload)
            except TypeError as exc:
                raise RecoveryError(f"trace event is invalid: {exc}") from exc
        else:
            event = TraceEvent(
                event_id=str(row["proposal_id"]),
                event_type=str(row["event_type"]),
                actor=str(row["actor"]),
                summary=str(
                    payload.get("summary", row["event_type"])
                    if isinstance(payload, dict)
                    else row["event_type"]
                ),
                payload=dict(payload) if isinstance(payload, dict) else {"value": payload},
                created_at=str(row["created_at"]),
                schema_version=str(row["schema_version"]),
            )
        trace.append(event)
    return trace


def _restore_worker_reports(rows: list[dict[str, Any]]) -> list[WorkerReport]:
    reports: list[WorkerReport] = []
    by_agent: dict[str, WorkerReport] = {}
    for row in rows:
        try:
            report = WorkerReport(**row)
        except (TypeError, ValueError) as exc:
            raise RecoveryError(f"worker report is invalid: {exc}") from exc
        existing = by_agent.get(report.agent_id)
        if existing is not None:
            if existing != report:
                raise RecoveryError(
                    f"conflicting worker reports for agent {report.agent_id}"
                )
            continue
        by_agent[report.agent_id] = report
        reports.append(report)
    return reports


def _dedupe_plain_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        if encoded in seen:
            continue
        seen.add(encoded)
        unique.append(dict(row))
    return unique


def _marker_text(marker: Mapping[str, Any], key: str) -> str:
    value = marker.get(key)
    if not isinstance(value, str) or not value:
        marker_id = marker.get("marker_id", "unknown")
        raise RecoveryError(
            f"session reconciliation marker {marker_id} has invalid {key}"
        )
    return value


__all__ = ["RecoveryError", "RecoveryManager", "RecoveryState"]
