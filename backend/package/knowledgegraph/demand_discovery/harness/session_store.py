"""Append-only session stores for harness replay state.

Session entries record replay-oriented runtime state: messages, save points,
active pointers, and model/tool changes. They are not formal domain evidence;
that boundary belongs to ``DomainTraceStore``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass
class SessionEntry:
    """One append-only session record."""

    entry_id: str
    parent_id: str
    run_id: str
    type: str
    timestamp: int
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "parent_id": self.parent_id,
            "run_id": self.run_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionEntry":
        return cls(
            entry_id=str(data["entry_id"]),
            parent_id=str(data.get("parent_id", "")),
            run_id=str(data.get("run_id", "")),
            type=str(data["type"]),
            timestamp=int(data.get("timestamp", 0)),
            payload=dict(data.get("payload", {})),
        )


class MemorySessionStore:
    """In-memory append-only session store."""

    def __init__(self) -> None:
        self._entries: list[SessionEntry] = []
        self._active_leaf_id = ""
        self._clock = 0

    @property
    def active_leaf_id(self) -> str:
        return self._active_leaf_id

    def append(
        self,
        entry_type: str,
        payload: dict[str, Any],
        run_id: str,
        parent_id: str | None = None,
        timestamp: int | None = None,
    ) -> SessionEntry:
        """Append an entry and make it the active leaf."""

        entry = self._make_entry(entry_type, payload, run_id, parent_id, timestamp)
        self._append_entry(entry)
        self._active_leaf_id = entry.entry_id
        return entry

    def set_active_leaf(
        self,
        entry_id: str,
        run_id: str,
        timestamp: int | None = None,
    ) -> SessionEntry:
        """Record an active pointer change without rewriting history."""

        entry = self._make_entry(
            "active_pointer",
            {"active_leaf_id": entry_id},
            run_id,
            parent_id=self._active_leaf_id,
            timestamp=timestamp,
        )
        self._append_entry(entry)
        self._active_leaf_id = entry_id
        return entry

    def restore_active_leaf(self) -> str:
        return self._active_leaf_id

    def entries(self) -> list[SessionEntry]:
        return list(self._entries)

    def _make_entry(
        self,
        entry_type: str,
        payload: dict[str, Any],
        run_id: str,
        parent_id: str | None,
        timestamp: int | None,
    ) -> SessionEntry:
        if timestamp is None:
            self._clock += 1
            timestamp = self._clock
        return SessionEntry(
            entry_id=f"session-{uuid4().hex}",
            parent_id=self._active_leaf_id if parent_id is None else parent_id,
            run_id=run_id,
            type=entry_type,
            timestamp=timestamp,
            payload=dict(payload),
        )

    def _append_entry(self, entry: SessionEntry) -> None:
        self._entries.append(entry)


class JsonlSessionStore(MemorySessionStore):
    """Append-only JSONL session store with a small in-memory mirror."""

    def __init__(self, path: str | Path, run_id: str = "") -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__()
        if self.path.exists() and self.path.stat().st_size > 0:
            self._load_existing()
        else:
            self._write_json(
                {"type": "session_header", "version": 1, "run_id": run_id}
            )

    def _append_entry(self, entry: SessionEntry) -> None:
        super()._append_entry(entry)
        self._write_json(entry.to_dict())

    def _write_json(self, data: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _load_existing(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("type") == "session_header":
                self.run_id = str(data.get("run_id", self.run_id))
                continue
            entry = SessionEntry.from_dict(data)
            self._entries.append(entry)
            if entry.type == "active_pointer":
                self._active_leaf_id = str(entry.payload.get("active_leaf_id", ""))
            else:
                self._active_leaf_id = entry.entry_id
            self._clock = max(self._clock, entry.timestamp)
