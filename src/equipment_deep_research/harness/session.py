from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any


_LOCKS_GUARD = Lock()
_PATH_LOCKS: dict[str, RLock] = {}


class JsonlSessionStore:
    """Thread-safe append-only JSONL storage for recoverable agent sessions."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        _reject_symlinks(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlinks(self.path)
        key = str(self.path.absolute())
        with _LOCKS_GUARD:
            self._lock = _PATH_LOCKS.setdefault(key, RLock())

    def append(self, record: Mapping[str, Any]) -> None:
        if not isinstance(record, Mapping):
            raise TypeError("session records must be JSON objects")
        encoded = (
            json.dumps(
                dict(record),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        with self._lock:
            _reject_symlinks(self.path)
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except OSError as exc:
                if self.path.is_symlink():
                    raise ValueError("session path must not be a symlink") from exc
                raise
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            _reject_symlinks(self.path)
            if not self.path.exists():
                return []
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags)
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                lines = handle.readlines()

        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                raise ValueError(f"blank JSONL record at line {line_number}")
            record = json.loads(line, parse_constant=_reject_json_constant)
            if not isinstance(record, dict):
                raise ValueError(f"JSONL record at line {line_number} is not an object")
            records.append(record)
        return records

    def read_tail(self, limit: int = 1) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("tail limit must be non-negative")
        if limit == 0:
            return []
        return self.read_all()[-limit:]

    def tail(self, limit: int = 1) -> list[dict[str, Any]]:
        return self.read_tail(limit)


def _reject_symlinks(path: Path) -> None:
    candidates = (path, path.parent)
    if any(candidate.is_symlink() for candidate in candidates):
        raise ValueError("session path must not be a symlink")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")
