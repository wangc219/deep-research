from __future__ import annotations

from collections.abc import Mapping
import errno
import json
import os
from pathlib import Path
import stat
from threading import Lock, RLock
from typing import Any

from equipment_deep_research.domain.workspace import open_directory_handle


_LOCKS_GUARD = Lock()


class _PathLockEntry:
    def __init__(self) -> None:
        self.lock = RLock()
        self.owners = 0


_PATH_LOCKS: dict[str, _PathLockEntry] = {}


def _json_plain(value: Any) -> Any:
    """Recursively convert supported containers to JSON-native containers."""

    if isinstance(value, Mapping):
        return {str(key): _json_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_plain(item) for item in value]
    return value


class UnsupportedPlatformError(RuntimeError):
    pass


class JsonlSessionStore:
    """Rooted, thread-safe append-only JSONL session storage."""

    def __init__(
        self,
        path: str | Path,
        *,
        root_dir: Path | None = None,
        anchor_dir: Path | None = None,
        root_fd: int | None = None,
        root_label: Path | None = None,
    ) -> None:
        _require_secure_platform()
        self._lock_key: str | None = None
        roots_provided = sum(
            value is not None for value in (root_dir, anchor_dir, root_fd)
        )
        if roots_provided != 1:
            raise ValueError(
                "provide exactly one of root_dir, anchor_dir, or root_fd"
            )
        if root_fd is not None:
            try:
                self._root_fd = os.dup(root_fd)
            except OSError as exc:
                raise ValueError("root_fd must reference an open directory") from exc
            root_stat = os.fstat(self._root_fd)
            if not stat.S_ISDIR(root_stat.st_mode):
                self.close()
                raise ValueError("root_fd must reference a directory")
            self.root_dir = Path(root_label) if root_label is not None else Path(".")
            self.anchor_dir = None
            try:
                self.relative_path = _relative_handle_path(path)
            except BaseException:
                self.close()
                raise
        else:
            requested_root = Path(anchor_dir if anchor_dir is not None else root_dir)
            self.root_dir, self._root_fd = open_directory_handle(
                requested_root,
                create=anchor_dir is None,
            )
            self.anchor_dir = self.root_dir if anchor_dir is not None else None
            try:
                self.relative_path = _relative_session_path(
                    path,
                    requested_root=requested_root,
                    canonical_root=self.root_dir,
                )
            except BaseException:
                self.close()
                raise
        self.path = self.root_dir / self.relative_path
        root_identity = _identity(os.fstat(self._root_fd))
        key = f"{root_identity}\0{self.relative_path.as_posix()}"
        with _LOCKS_GUARD:
            entry = _PATH_LOCKS.setdefault(key, _PathLockEntry())
            entry.owners += 1
            self._lock = entry.lock
            self._lock_key = key
        try:
            with self._lock:
                self._validate_existing_path()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        descriptor = getattr(self, "_root_fd", None)
        lock_key = getattr(self, "_lock_key", None)
        if descriptor is None and lock_key is None:
            return
        self._root_fd = None
        self._lock_key = None
        try:
            if descriptor is not None:
                os.close(descriptor)
        except OSError:
            pass
        finally:
            if lock_key is not None:
                with _LOCKS_GUARD:
                    entry = _PATH_LOCKS.get(lock_key)
                    if entry is not None and entry.lock is self._lock:
                        entry.owners -= 1
                        if entry.owners == 0:
                            _PATH_LOCKS.pop(lock_key, None)

    def __enter__(self) -> "JsonlSessionStore":
        self._require_root_fd()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def append(self, record: Mapping[str, Any]) -> None:
        _require_secure_platform()
        if not isinstance(record, Mapping):
            raise TypeError("session records must be JSON objects")
        # Provider metadata may expose immutable Mapping implementations (for
        # example MappingProxyType).  ``dict(record)`` only normalizes the
        # outer object, leaving nested mappings for ``json.dumps`` to reject.
        # Normalize recursively at the persistence boundary so real provider
        # telemetry remains append-only and replayable just like fake-mode
        # records.
        normalized = _json_plain(record)
        encoded = (
            json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with self._lock:
            self._append_dir_fd(encoded)

    def read_all(self) -> list[dict[str, Any]]:
        _require_secure_platform()
        with self._lock:
            lines = self._read_lines_dir_fd()

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
        current_fd = os.dup(self._require_root_fd())
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

    def _require_root_fd(self) -> int:
        descriptor = self._root_fd
        if descriptor is None:
            raise RuntimeError("session store is closed")
        return descriptor


def _relative_handle_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise ValueError("session path must stay within root_fd")
    if not candidate.parts:
        raise ValueError("session path must name a file within root_fd")
    return candidate


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


def _require_secure_platform() -> None:
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    missing: list[str] = []
    if _no_follow() == 0:
        missing.append("O_NOFOLLOW")
    if _directory_only() == 0:
        missing.append("O_DIRECTORY")
    for name, function in (
        ("os.open(dir_fd)", os.open),
        ("os.mkdir(dir_fd)", os.mkdir),
        ("os.stat(dir_fd)", os.stat),
    ):
        if function not in supports_dir_fd:
            missing.append(name)
    if missing:
        raise UnsupportedPlatformError(
            "secure session path operations require " + ", ".join(missing)
        )


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
