from __future__ import annotations

import json
from threading import Lock
import time
from typing import Any

from sqlalchemy import MetaData, Table, Column, Integer, String, Text, select, delete, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from equipment_deep_research.application.dto import RunView


metadata = MetaData()
runs = Table("runs", metadata, Column("run_id", String(128), primary_key=True), Column("payload", Text, nullable=False))
events = Table("runtime_events", metadata, Column("run_id", String(128), primary_key=True), Column("sequence", Integer, primary_key=True), Column("event_type", String(128), nullable=False), Column("payload", Text, nullable=False))
queue_items = Table("run_queue", metadata, Column("run_id", String(128), primary_key=True), Column("status", String(32), nullable=False), Column("ordinal", Integer, autoincrement=True, nullable=False, unique=True))
worker_heartbeats = Table("worker_heartbeats", metadata, Column("worker_id", String(128), primary_key=True), Column("updated_at", String(64), nullable=False), Column("status", String(32), nullable=False), Column("current_run_id", String(128), nullable=False, default=""))


class SqlRunRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = Lock()
        metadata.create_all(engine)

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
        return sorted((RunView(**json.loads(row)) for row in rows), key=lambda item: item.updated_at, reverse=True)

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
            connection.execute(delete(events).where(events.c.run_id == run_id))
            connection.execute(delete(queue_items).where(queue_items.c.run_id == run_id))
            connection.execute(
                update(worker_heartbeats)
                .where(worker_heartbeats.c.current_run_id == run_id)
                .values(status="idle", current_run_id="")
            )
            connection.execute(delete(runs).where(runs.c.run_id == run_id))

    def deletion_residue(self, run_id: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            return {
                "runs": len(connection.execute(select(runs.c.run_id).where(runs.c.run_id == run_id)).all()),
                "runtime_events": len(connection.execute(select(events.c.run_id).where(events.c.run_id == run_id)).all()),
                "run_queue": len(connection.execute(select(queue_items.c.run_id).where(queue_items.c.run_id == run_id)).all()),
                "worker_heartbeats": len(connection.execute(select(worker_heartbeats.c.worker_id).where(worker_heartbeats.c.current_run_id == run_id)).all()),
            }


class SqlRunQueue:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = Lock()
        metadata.create_all(engine)

    def enqueue(self, run_id: str) -> None:
        with self._lock, self.engine.begin() as connection:
            existing = connection.execute(
                select(queue_items.c.status, queue_items.c.ordinal).where(
                    queue_items.c.run_id == run_id
                )
            ).mappings().one_or_none()
            if existing is None:
                next_ordinal = (connection.execute(select(queue_items.c.ordinal).order_by(queue_items.c.ordinal.desc()).limit(1)).scalar_one_or_none() or 0) + 1
                connection.execute(queue_items.insert().values(run_id=run_id, status="pending", ordinal=next_ordinal))
            elif existing["status"] != "pending":
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
                    .values(status="pending", ordinal=next_ordinal)
                )

    def claim(self) -> str | None:
        candidate = (
            select(queue_items.c.run_id)
            .where(queue_items.c.status == "pending")
            .order_by(queue_items.c.ordinal)
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(queue_items)
            .where(
                queue_items.c.run_id == candidate,
                queue_items.c.status == "pending",
            )
            .values(status="claimed")
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
            connection.execute(update(queue_items).where(queue_items.c.run_id == run_id).values(status="pending"))

    def remove(self, run_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(queue_items).where(queue_items.c.run_id == run_id))

    def pending_run_ids(self) -> list[str]:
        with self.engine.connect() as connection:
            return [str(item) for item in connection.execute(select(queue_items.c.run_id).where(queue_items.c.status == "pending").order_by(queue_items.c.ordinal)).scalars().all()]
