from __future__ import annotations

from collections.abc import Mapping
import errno
import json
import os
from pathlib import Path
import stat
from threading import Lock, RLock
from typing import Any


_LOCKS_GUARD = Lock()
_PATH_LOCKS: dict[str, RLock] = {}


class JsonlSessionStore:
    """Rooted, thread-safe append-only JSONL session storage."""

    def __init__(self, path: str | Path, *, root_dir: Path) -> None:
        requested_root = Path(root_dir)
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root_dir = requested_root.resolve(strict=True)
        if not self.root_dir.is_dir():
            raise ValueError("root_dir must resolve to a directory")
        self.relative_path = _relative_session_path(
            path,
            requested_root=requested_root,
            canonical_root=self.root_dir,
        )
        self.path = self.root_dir / self.relative_path
        self._access_mode = _secure_access_mode()
        key = f"{self.root_dir}\0{self.relative_path.as_posix()}"
        with _LOCKS_GUARD:
            self._lock = _PATH_LOCKS.setdefault(key, RLock())
        with self._lock:
            self._validate_existing_path()

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
        with self._lock:
            if self._access_mode == "dir_fd":
                self._append_dir_fd(encoded)
            else:
                self._append_fallback(encoded)

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._access_mode == "dir_fd":
                lines = self._read_lines_dir_fd()
            else:
                lines = self._read_lines_fallback()

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

    def _validate_existing_path(self) -> None:
        if self._access_mode == "dir_fd":
            parent_fd = self._open_parent_dir_fd(create=False)
            if parent_fd is None:
                return
            try:
                file_stat = _lstat_at(self.relative_path.name, parent_fd)
                if file_stat is None:
                    return
                _require_regular_file(file_stat, self.path)
                descriptor = _open_at(
                    self.relative_path.name,
                    os.O_RDONLY | _close_on_exec() | _no_follow(),
                    dir_fd=parent_fd,
                )
                try:
                    _require_same_file(file_stat, os.fstat(descriptor), self.path)
                finally:
                    os.close(descriptor)
            finally:
                os.close(parent_fd)
            return
        snapshots = self._fallback_parent_snapshots(create=False)
        if snapshots is None:
            return
        file_stat = _lstat_path(self.path)
        if file_stat is None:
            return
        _require_regular_file(file_stat, self.path)
        descriptor = os.open(
            self.path,
            os.O_RDONLY | _close_on_exec() | _no_follow(),
        )
        try:
            _require_same_file(file_stat, os.fstat(descriptor), self.path)
            self._recheck_fallback_snapshots(snapshots)
        finally:
            os.close(descriptor)

    def _append_dir_fd(self, encoded: bytes) -> None:
        parent_fd = self._open_parent_dir_fd(create=True)
        assert parent_fd is not None
        descriptor: int | None = None
        try:
            existing = _lstat_at(self.relative_path.name, parent_fd)
            if existing is not None:
                _require_regular_file(existing, self.path)
            descriptor = _open_at(
                self.relative_path.name,
                os.O_APPEND
                | os.O_CREAT
                | os.O_WRONLY
                | _close_on_exec()
                | _no_follow(),
                0o600,
                dir_fd=parent_fd,
            )
            opened = os.fstat(descriptor)
            _require_regular_file(opened, self.path)
            if existing is not None:
                _require_same_file(existing, opened, self.path)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def _read_lines_dir_fd(self) -> list[str]:
        parent_fd = self._open_parent_dir_fd(create=False)
        if parent_fd is None:
            return []
        descriptor: int | None = None
        try:
            existing = _lstat_at(self.relative_path.name, parent_fd)
            if existing is None:
                return []
            _require_regular_file(existing, self.path)
            descriptor = _open_at(
                self.relative_path.name,
                os.O_RDONLY | _close_on_exec() | _no_follow(),
                dir_fd=parent_fd,
            )
            _require_same_file(existing, os.fstat(descriptor), self.path)
        finally:
            os.close(parent_fd)
        assert descriptor is not None
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            return handle.readlines()

    def _open_parent_dir_fd(self, *, create: bool) -> int | None:
        current_fd = os.open(
            self.root_dir,
            os.O_RDONLY | _directory_only() | _close_on_exec() | _no_follow(),
        )
        try:
            for component in self.relative_path.parts[:-1]:
                component_stat = _lstat_at(component, current_fd)
                if component_stat is None:
                    if not create:
                        os.close(current_fd)
                        return None
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    component_stat = _lstat_at(component, current_fd)
                    if component_stat is None:
                        raise RuntimeError("session directory disappeared during creation")
                _require_directory(component_stat, self.path.parent)
                next_fd = _open_at(
                    component,
                    os.O_RDONLY
                    | _directory_only()
                    | _close_on_exec()
                    | _no_follow(),
                    dir_fd=current_fd,
                )
                opened_stat = os.fstat(next_fd)
                try:
                    _require_same_file(component_stat, opened_stat, self.path.parent)
                except BaseException:
                    os.close(next_fd)
                    raise
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise

    def _append_fallback(self, encoded: bytes) -> None:
        snapshots = self._fallback_parent_snapshots(create=True)
        assert snapshots is not None
        existing = _lstat_path(self.path)
        if existing is not None:
            _require_regular_file(existing, self.path)
        descriptor = os.open(
            self.path,
            os.O_APPEND
            | os.O_CREAT
            | os.O_WRONLY
            | _close_on_exec()
            | _no_follow(),
            0o600,
        )
        try:
            opened = os.fstat(descriptor)
            _require_regular_file(opened, self.path)
            current = _lstat_path(self.path)
            if current is None:
                raise RuntimeError("session file disappeared after opening")
            _require_same_file(current, opened, self.path)
            if existing is not None:
                _require_same_file(existing, opened, self.path)
            self._recheck_fallback_snapshots(snapshots)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            self._recheck_fallback_snapshots(snapshots)
        finally:
            os.close(descriptor)

    def _read_lines_fallback(self) -> list[str]:
        snapshots = self._fallback_parent_snapshots(create=False)
        if snapshots is None:
            return []
        existing = _lstat_path(self.path)
        if existing is None:
            return []
        _require_regular_file(existing, self.path)
        descriptor = os.open(
            self.path,
            os.O_RDONLY | _close_on_exec() | _no_follow(),
        )
        try:
            _require_same_file(existing, os.fstat(descriptor), self.path)
            self._recheck_fallback_snapshots(snapshots)
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                return handle.readlines()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _fallback_parent_snapshots(
        self,
        *,
        create: bool,
    ) -> list[tuple[Path, tuple[int, int]]] | None:
        snapshots: list[tuple[Path, tuple[int, int]]] = []
        current = self.root_dir
        root_stat = os.lstat(current)
        _require_directory(root_stat, current)
        snapshots.append((current, _identity(root_stat)))
        for component in self.relative_path.parts[:-1]:
            current = current / component
            _require_within_root(current, self.root_dir)
            component_stat = _lstat_path(current)
            if component_stat is None:
                if not create:
                    return None
                try:
                    os.mkdir(current, 0o700)
                except FileExistsError:
                    pass
                component_stat = _lstat_path(current)
                if component_stat is None:
                    raise RuntimeError("session directory disappeared during creation")
            _require_directory(component_stat, current)
            if current.resolve(strict=True) != current:
                raise ValueError(f"session path contains a symlink: {current}")
            snapshots.append((current, _identity(component_stat)))
        _require_within_root(self.path, self.root_dir)
        return snapshots

    def _recheck_fallback_snapshots(
        self,
        snapshots: list[tuple[Path, tuple[int, int]]],
    ) -> None:
        for path, identity in snapshots:
            current = os.lstat(path)
            _require_directory(current, path)
            if _identity(current) != identity:
                raise RuntimeError(f"session path changed during access: {path}")
        _require_within_root(self.path, self.root_dir)


def _relative_session_path(
    path: str | Path,
    *,
    requested_root: Path,
    canonical_root: Path,
) -> Path:
    candidate = Path(path)
    if any(part == ".." for part in candidate.parts):
        raise ValueError("session path must stay within root_dir")
    if candidate.is_absolute():
        candidate_absolute = Path(os.path.abspath(candidate))
        roots = (
            Path(os.path.abspath(requested_root)),
            canonical_root,
        )
        relative: Path | None = None
        for root in roots:
            try:
                relative = candidate_absolute.relative_to(root)
                break
            except ValueError:
                continue
        if relative is None:
            raise ValueError("session path must stay within root_dir")
    else:
        relative = candidate
    parts = tuple(part for part in relative.parts if part not in {"", "."})
    if not parts or any(part in {"..", os.sep} for part in parts):
        raise ValueError("session path must name a file within root_dir")
    normalized = Path(*parts)
    _require_within_root(canonical_root / normalized, canonical_root)
    return normalized


def _secure_access_mode() -> str:
    if _no_follow() == 0:
        raise RuntimeError(
            "secure session path operations require O_NOFOLLOW; refusing unsafe fallback"
        )
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    if (
        _directory_only() != 0
        and os.open in supports_dir_fd
        and os.mkdir in supports_dir_fd
        and os.stat in supports_dir_fd
    ):
        return "dir_fd"
    if all(callable(getattr(os, name, None)) for name in ("lstat", "fstat", "open")):
        return "fallback"
    raise RuntimeError("secure session path operations are unavailable on this platform")


def _open_at(
    path: str,
    flags: int,
    mode: int = 0o777,
    *,
    dir_fd: int,
) -> int:
    try:
        return os.open(path, flags, mode, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(f"session path contains a symlink: {path}") from exc
        raise


def _lstat_at(path: str, dir_fd: int) -> os.stat_result | None:
    try:
        result = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if _is_link_like(result):
        raise ValueError(f"session path contains a symlink: {path}")
    return result


def _lstat_path(path: Path) -> os.stat_result | None:
    try:
        result = os.lstat(path)
    except FileNotFoundError:
        return None
    if _is_link_like(result):
        raise ValueError(f"session path contains a symlink: {path}")
    return result


def _is_link_like(value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _require_directory(value: os.stat_result, path: Path) -> None:
    if _is_link_like(value):
        raise ValueError(f"session path contains a symlink: {path}")
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"session path ancestor is not a directory: {path}")


def _require_regular_file(value: os.stat_result, path: Path) -> None:
    if _is_link_like(value):
        raise ValueError(f"session path contains a symlink: {path}")
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"session path is not a regular file: {path}")


def _require_same_file(
    expected: os.stat_result,
    actual: os.stat_result,
    path: Path,
) -> None:
    if _identity(expected) != _identity(actual):
        raise RuntimeError(f"session path changed during access: {path}")


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _require_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("session path must stay within root_dir") from exc


def _write_all(descriptor: int, encoded: bytes) -> None:
    view = memoryview(encoded)
    while view:
        written = os.write(descriptor, view)
        if written < 1:
            raise OSError("session append made no progress")
        view = view[written:]


def _no_follow() -> int:
    return int(getattr(os, "O_NOFOLLOW", 0))


def _directory_only() -> int:
    return int(getattr(os, "O_DIRECTORY", 0))


def _close_on_exec() -> int:
    return int(getattr(os, "O_CLOEXEC", 0))


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")
