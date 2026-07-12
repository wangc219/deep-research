from __future__ import annotations

import json
from threading import Lock
from typing import Any

from sqlalchemy import MetaData, Table, Column, Integer, String, Text, select, delete
from sqlalchemy.engine import Engine

from equipment_deep_research.application.dto import RunView


metadata = MetaData()
runs = Table("runs", metadata, Column("run_id", String(128), primary_key=True), Column("payload", Text, nullable=False))
events = Table("runtime_events", metadata, Column("run_id", String(128), primary_key=True), Column("sequence", Integer, primary_key=True), Column("event_type", String(128), nullable=False), Column("payload", Text, nullable=False))


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
        with self._lock, self.engine.begin() as connection:
            current = connection.execute(select(events.c.sequence).where(events.c.run_id == run_id).order_by(events.c.sequence.desc()).limit(1)).scalar_one_or_none() or 0
            sequence = current + 1
            connection.execute(events.insert().values(run_id=run_id, sequence=sequence, event_type=event_type, payload=json.dumps(payload, ensure_ascii=False, sort_keys=True)))
        return sequence

    def events_after(self, run_id: str, sequence: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(events).where(events.c.run_id == run_id, events.c.sequence > sequence).order_by(events.c.sequence)).mappings().all()
        return [{"run_id": row["run_id"], "sequence": row["sequence"], "event_type": row["event_type"], "payload": json.loads(row["payload"])} for row in rows]
