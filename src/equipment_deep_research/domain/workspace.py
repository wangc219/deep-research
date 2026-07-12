from __future__ import annotations

from dataclasses import dataclass, field
import errno
import ctypes
import os
from pathlib import Path
import secrets
import stat
import sys

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms fail closed below
    fcntl = None  # type: ignore[assignment]


_DIR_FD_FUNCTIONS = (
    ("os.open(dir_fd)", os.open),
    ("os.mkdir(dir_fd)", os.mkdir),
    ("os.stat(dir_fd)", os.stat),
    ("os.rename(dir_fd)", os.rename),
    ("os.unlink(dir_fd)", os.unlink),
)


@dataclass
class RunWorkspace:
    run_dir: Path
    sessions_dir: Path
    artifacts_dir: Path
    checkpoints_dir: Path
    database_path: Path
    output_root: Path
    run_id: str
    _run_fd: int = field(repr=False, compare=False)
    _sessions_fd: int = field(repr=False, compare=False)
    _artifacts_fd: int = field(repr=False, compare=False)
    _checkpoints_fd: int = field(repr=False, compare=False)
    _database_fd: int = field(repr=False, compare=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def run_identity(self) -> tuple[int, int]:
        return _identity(os.fstat(self._require_open_fd(self._run_fd)))

    def dup_run_fd(self) -> int:
        return os.dup(self._require_open_fd(self._run_fd))

    def dup_sessions_fd(self) -> int:
        return os.dup(self._require_open_fd(self._sessions_fd))

    def dup_artifacts_fd(self) -> int:
        return os.dup(self._require_open_fd(self._artifacts_fd))

    def dup_checkpoints_fd(self) -> int:
        return os.dup(self._require_open_fd(self._checkpoints_fd))

    def dup_database_fd(self) -> int:
        return os.dup(self._require_open_fd(self._database_fd))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in (
            self._database_fd,
            self._checkpoints_fd,
            self._artifacts_fd,
            self._sessions_fd,
            self._run_fd,
        ):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def __enter__(self) -> "RunWorkspace":
        self._require_open_fd(self._run_fd)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def write_run_text(self, relative_path: str | Path, text: str) -> None:
        self.write_run_bytes(relative_path, text.encode("utf-8"))

    def write_run_bytes(self, relative_path: str | Path, content: bytes) -> None:
        _RootedAtomicWriter(self._require_open_fd(self._run_fd)).write(
            relative_path,
            content,
        )

    def write_checkpoint_text(self, relative_path: str | Path, text: str) -> None:
        _RootedAtomicWriter(self._require_open_fd(self._checkpoints_fd)).write(
            relative_path,
            text.encode("utf-8"),
        )

    def write_artifact_bytes(self, relative_path: str | Path, content: bytes) -> None:
        _RootedAtomicWriter(self._require_open_fd(self._artifacts_fd)).write(
            relative_path,
            content,
        )

    def read_artifact_bytes(self, relative_path: str | Path) -> bytes:
        return _RootedAtomicWriter(self._require_open_fd(self._artifacts_fd)).read(
            relative_path
        )

    def artifact_file_is_regular(self, relative_path: str | Path) -> bool:
        return _RootedAtomicWriter(
            self._require_open_fd(self._artifacts_fd)
        ).is_regular_file(relative_path)

    def artifact_file_names(self) -> list[str]:
        return _RootedAtomicWriter(
            self._require_open_fd(self._artifacts_fd)
        ).list_regular_file_names(".")

    def run_file_is_regular(self, relative_path: str | Path) -> bool:
        return _RootedAtomicWriter(
            self._require_open_fd(self._run_fd)
        ).is_regular_file(relative_path)

    @classmethod
    def create(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)
        resolved_root, output_fd = open_directory_handle(output_root, create=True)
        run_fd: int | None = None
        sessions_fd: int | None = None
        artifacts_fd: int | None = None
        checkpoints_fd: int | None = None
        database_fd: int | None = None
        try:
            _require_trusted_output_root(os.fstat(output_fd), resolved_root)
            run_fd = _create_directory_at(output_fd, run_id)
            sessions_fd = _create_directory_at(run_fd, "agent_sessions")
            artifacts_fd = _create_directory_at(run_fd, "artifacts")
            checkpoints_fd = _create_directory_at(run_fd, "checkpoints")
            database_fd = _open_at(
                "run.db",
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | _close_on_exec()
                | _no_follow(),
                0o600,
                dir_fd=run_fd,
            )
            _require_regular_file(os.fstat(database_fd), Path("run.db"))
            run_dir = resolved_root / run_id
            return cls(
                run_dir=run_dir,
                sessions_dir=run_dir / "agent_sessions",
                artifacts_dir=run_dir / "artifacts",
                checkpoints_dir=run_dir / "checkpoints",
                database_path=run_dir / "run.db",
                output_root=resolved_root,
                run_id=run_id,
                _run_fd=run_fd,
                _sessions_fd=sessions_fd,
                _artifacts_fd=artifacts_fd,
                _checkpoints_fd=checkpoints_fd,
                _database_fd=database_fd,
            )
        except BaseException:
            _close_descriptors(
                database_fd,
                checkpoints_fd,
                artifacts_fd,
                sessions_fd,
                run_fd,
            )
            raise
        finally:
            os.close(output_fd)

    @classmethod
    def open_existing(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)
        resolved_root, output_fd = open_directory_handle(output_root, create=False)
        run_fd: int | None = None
        sessions_fd: int | None = None
        artifacts_fd: int | None = None
        checkpoints_fd: int | None = None
        database_fd: int | None = None
        try:
            _require_trusted_output_root(os.fstat(output_fd), resolved_root)
            if _lstat_at(run_id, output_fd) is None:
                raise FileNotFoundError(
                    f"run directory does not exist: {resolved_root / run_id}"
                )
            run_fd = _open_directory_at(output_fd, run_id)
            sessions_fd = _open_directory_at(run_fd, "agent_sessions")
            artifacts_fd = _open_directory_at(run_fd, "artifacts")
            checkpoints_fd = _open_directory_at(run_fd, "checkpoints")
            database_stat = _lstat_at("run.db", run_fd)
            if database_stat is None:
                raise FileNotFoundError("run database does not exist: run.db")
            _require_regular_file(database_stat, Path("run.db"))
            database_fd = _open_at(
                "run.db",
                os.O_RDWR | _close_on_exec() | _no_follow(),
                dir_fd=run_fd,
            )
            opened_database = os.fstat(database_fd)
            _require_regular_file(opened_database, Path("run.db"))
            if _identity(database_stat) != _identity(opened_database):
                raise RuntimeError("run.db changed during access")
            run_dir = resolved_root / run_id
            return cls(
                run_dir=run_dir,
                sessions_dir=run_dir / "agent_sessions",
                artifacts_dir=run_dir / "artifacts",
                checkpoints_dir=run_dir / "checkpoints",
                database_path=run_dir / "run.db",
                output_root=resolved_root,
                run_id=run_id,
                _run_fd=run_fd,
                _sessions_fd=sessions_fd,
                _artifacts_fd=artifacts_fd,
                _checkpoints_fd=checkpoints_fd,
                _database_fd=database_fd,
            )
        except BaseException:
            _close_descriptors(
                database_fd,
                checkpoints_fd,
                artifacts_fd,
                sessions_fd,
                run_fd,
            )
            raise
        finally:
            os.close(output_fd)

    def _require_open_fd(self, descriptor: int) -> int:
        if self._closed:
            raise RuntimeError("workspace is closed")
        try:
            os.fstat(descriptor)
        except OSError as exc:
            raise RuntimeError("workspace handle is closed") from exc
        return descriptor


def open_directory_handle(
    path: str | Path,
    *,
    create: bool,
) -> tuple[Path, int]:
    _require_secure_writer_platform()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve(strict=not create)
    if not resolved.is_absolute() or resolved.anchor != os.sep:
        raise ValueError("trusted directory must resolve to an absolute POSIX path")
    filesystem_root = os.stat(os.sep, follow_symlinks=False)
    current_fd = os.open(
        os.sep,
        os.O_RDONLY | _directory_only() | _close_on_exec() | _no_follow(),
    )
    opened_root = os.fstat(current_fd)
    if _identity(filesystem_root) != _identity(opened_root):
        os.close(current_fd)
        raise RuntimeError("filesystem root changed during access")
    try:
        for component in resolved.parts[1:]:
            component_stat = _lstat_at(component, current_fd)
            if component_stat is None:
                if not create:
                    raise FileNotFoundError(f"directory does not exist: {resolved}")
                next_fd = _create_directory_at(current_fd, component)
                os.close(current_fd)
                current_fd = next_fd
                continue
            _require_directory(component_stat, Path(component))
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
                _require_directory(opened_stat, Path(component))
                if _identity(component_stat) != _identity(opened_stat):
                    raise RuntimeError(
                        f"directory changed during access: {component}"
                    )
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return resolved, current_fd
    except BaseException:
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise


def path_from_fd(descriptor: int) -> Path:
    try:
        os.fstat(descriptor)
    except OSError as exc:
        raise RuntimeError("cannot resolve a closed file descriptor") from exc
    if sys.platform == "darwin":
        if fcntl is None:
            raise RuntimeError("secure descriptor path resolution is unavailable")
        command = int(getattr(fcntl, "F_GETPATH", 50))
        raw = fcntl.fcntl(descriptor, command, b"\0" * 1024)
        value = bytes(raw).split(b"\0", 1)[0].decode()
    elif Path(f"/proc/self/fd/{descriptor}").exists():
        value = os.readlink(f"/proc/self/fd/{descriptor}")
        if value.endswith(" (deleted)"):
            raise RuntimeError("bound file has been unlinked")
    else:
        raise RuntimeError("secure descriptor path resolution is unavailable")
    resolved = Path(value)
    if not resolved.is_absolute():
        raise RuntimeError("descriptor path is not absolute")
    return resolved


def _validate_run_id(run_id: str) -> None:
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or Path(run_id).is_absolute()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
    ):
        raise ValueError("run_id must be a single relative path component")


def _require_trusted_output_root(value: os.stat_result, path: Path) -> None:
    if value.st_uid != os.geteuid():
        raise PermissionError(f"output root must be owned by the current user: {path}")
    if value.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PermissionError(
            f"output root must not be group/world writable: {path}"
        )


class _RootedAtomicWriter:
    def __init__(self, root_fd: int) -> None:
        self.root_fd = root_fd

    def write(self, relative_path: str | Path, content: bytes) -> None:
        _require_secure_writer_platform()
        relative = _relative_workspace_path(relative_path)
        parent_fd = self._open_parent(relative)
        temporary_name = f".{relative.name}.{secrets.token_hex(8)}.tmp"
        descriptor: int | None = None
        temporary_created = False
        try:
            existing = _lstat_at(relative.name, parent_fd)
            if existing is not None:
                _require_regular_file(existing, relative)
            descriptor = _open_at(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | _close_on_exec()
                | _no_follow(),
                0o600,
                dir_fd=parent_fd,
            )
            temporary_created = True
            _write_all(descriptor, content)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.rename(
                temporary_name,
                relative.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary_created = False
            os.fsync(parent_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            os.close(parent_fd)

    def is_regular_file(self, relative_path: str | Path) -> bool:
        _require_secure_writer_platform()
        relative = _relative_workspace_path(relative_path)
        parent_fd = self._open_parent(relative)
        try:
            existing = _lstat_at(relative.name, parent_fd)
            if existing is None:
                return False
            _require_regular_file(existing, relative)
            descriptor = _open_at(
                relative.name,
                os.O_RDONLY | _close_on_exec() | _no_follow(),
                dir_fd=parent_fd,
            )
            try:
                opened = os.fstat(descriptor)
                _require_regular_file(opened, relative)
                if _identity(existing) != _identity(opened):
                    raise RuntimeError(
                        f"workspace path changed during access: {relative}"
                    )
            finally:
                os.close(descriptor)
            return True
        finally:
            os.close(parent_fd)

    def read(self, relative_path: str | Path) -> bytes:
        _require_secure_writer_platform()
        relative = _relative_workspace_path(relative_path)
        parent_fd = self._open_parent(relative)
        descriptor: int | None = None
        try:
            existing = _lstat_at(relative.name, parent_fd)
            if existing is None:
                raise FileNotFoundError(relative)
            _require_regular_file(existing, relative)
            descriptor = _open_at(
                relative.name,
                os.O_RDONLY | _close_on_exec() | _no_follow(),
                dir_fd=parent_fd,
            )
            opened = os.fstat(descriptor)
            _require_regular_file(opened, relative)
            if _identity(existing) != _identity(opened):
                raise RuntimeError(f"workspace path changed during access: {relative}")
            return _read_all(descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def list_regular_file_names(self, relative_dir: str | Path) -> list[str]:
        _require_secure_writer_platform()
        _require_secure_list_platform()
        candidate = Path(relative_dir)
        relative = Path() if candidate == Path(".") else _relative_workspace_path(candidate)
        directory_fd = self._open_parent(relative / ".list")
        try:
            names: list[str] = []
            for name in sorted(os.listdir(directory_fd)):
                value = _lstat_at(name, directory_fd)
                if value is not None and stat.S_ISREG(value.st_mode):
                    names.append(name)
            return names
        finally:
            os.close(directory_fd)

    def _open_parent(self, relative: Path) -> int:
        try:
            current_fd = os.dup(self.root_fd)
        except OSError as exc:
            raise RuntimeError("workspace root handle is closed") from exc
        try:
            root_stat = os.fstat(current_fd)
            _require_directory(root_stat, Path("."))
            for component in relative.parts[:-1]:
                component_stat = _lstat_at(component, current_fd)
                if component_stat is None:
                    raise FileNotFoundError(
                        f"workspace path ancestor does not exist: {component}"
                    )
                _require_directory(component_stat, Path(component))
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
                    _require_directory(opened_stat, Path(component))
                    if _identity(component_stat) != _identity(opened_stat):
                        raise RuntimeError(
                            f"workspace path changed during access: {component}"
                        )
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


def _create_directory_at(parent_fd: int, name: str) -> int:
    temporary_name = f".{name}.{secrets.token_hex(16)}.creating"
    descriptor: int | None = None
    published = False
    os.mkdir(temporary_name, 0o700, dir_fd=parent_fd)
    try:
        descriptor = _open_directory_at(parent_fd, temporary_name)
        created_identity = _identity(os.fstat(descriptor))
        _rename_noreplace_at(parent_fd, temporary_name, name)
        published = True
        published_stat = _lstat_at(name, parent_fd)
        if published_stat is None or _identity(published_stat) != created_identity:
            raise RuntimeError(f"created directory changed during publication: {name}")
        return descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        if not published:
            try:
                os.rmdir(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def _rename_noreplace_at(
    parent_fd: int,
    source: str,
    destination: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise RuntimeError("atomic no-replace directory publication is unavailable")
        result = renameatx_np(
            parent_fd,
            source_bytes,
            parent_fd,
            destination_bytes,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RuntimeError("atomic no-replace directory publication is unavailable")
        result = renameat2(
            parent_fd,
            source_bytes,
            parent_fd,
            destination_bytes,
            1,  # RENAME_NOREPLACE
        )
    else:
        raise RuntimeError("atomic no-replace directory publication is unavailable")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), destination)


def _open_directory_at(parent_fd: int, name: str) -> int:
    existing = _lstat_at(name, parent_fd)
    if existing is None:
        raise FileNotFoundError(f"directory does not exist: {name}")
    _require_directory(existing, Path(name))
    descriptor = _open_at(
        name,
        os.O_RDONLY | _directory_only() | _close_on_exec() | _no_follow(),
        dir_fd=parent_fd,
    )
    opened = os.fstat(descriptor)
    try:
        _require_directory(opened, Path(name))
        if _identity(existing) != _identity(opened):
            raise RuntimeError(f"directory changed during access: {name}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _relative_workspace_path(path: str | Path) -> Path:
    candidate = Path(path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("workspace path must stay within its trusted root")
    return candidate


def _require_secure_writer_platform() -> None:
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    missing: list[str] = []
    if _no_follow() == 0:
        missing.append("O_NOFOLLOW")
    if _directory_only() == 0:
        missing.append("O_DIRECTORY")
    if getattr(os, "O_EXCL", 0) == 0:
        missing.append("O_EXCL")
    for name, function in _DIR_FD_FUNCTIONS:
        if function not in supports_dir_fd:
            missing.append(name)
    if missing:
        raise RuntimeError(
            "secure workspace path operations require " + ", ".join(missing)
        )


def _require_secure_list_platform() -> None:
    if os.listdir not in getattr(os, "supports_fd", set()):
        raise RuntimeError("secure workspace path operations require os.listdir(fd)")


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
            raise ValueError(f"workspace path contains a symlink: {path}") from exc
        raise


def _lstat_at(path: str, dir_fd: int) -> os.stat_result | None:
    try:
        value = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode):
        raise ValueError(f"workspace path contains a symlink: {path}")
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if attributes & reparse_flag:
        raise ValueError(f"workspace path contains a symlink: {path}")
    return value


def _require_directory(value: os.stat_result, path: Path) -> None:
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"workspace path is not a directory: {path}")


def _require_regular_file(value: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"workspace path is not a regular file: {path}")


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written < 1:
            raise OSError("workspace write made no progress")
        view = view[written:]


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _close_descriptors(*descriptors: int | None) -> None:
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


def _no_follow() -> int:
    return int(getattr(os, "O_NOFOLLOW", 0))


def _directory_only() -> int:
    return int(getattr(os, "O_DIRECTORY", 0))


def _close_on_exec() -> int:
    return int(getattr(os, "O_CLOEXEC", 0))
