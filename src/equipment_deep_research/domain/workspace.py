from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import secrets
import stat


_DIR_FD_FUNCTIONS = (
    ("os.open(dir_fd)", os.open),
    ("os.stat(dir_fd)", os.stat),
    ("os.rename(dir_fd)", os.rename),
    ("os.unlink(dir_fd)", os.unlink),
)


@dataclass(frozen=True)
class RunWorkspace:
    run_dir: Path
    sessions_dir: Path
    artifacts_dir: Path
    checkpoints_dir: Path
    database_path: Path
    output_root: Path
    run_id: str

    def write_run_text(self, relative_path: str | Path, text: str) -> None:
        self.write_run_bytes(relative_path, text.encode("utf-8"))

    def write_run_bytes(self, relative_path: str | Path, content: bytes) -> None:
        _RootedAtomicWriter(self.run_dir).write(relative_path, content)

    def write_checkpoint_text(self, relative_path: str | Path, text: str) -> None:
        _RootedAtomicWriter(self.checkpoints_dir).write(
            relative_path,
            text.encode("utf-8"),
        )

    def write_artifact_bytes(self, relative_path: str | Path, content: bytes) -> None:
        _RootedAtomicWriter(self.run_dir).write(
            Path("artifacts") / _relative_workspace_path(relative_path),
            content,
        )

    def read_artifact_bytes(self, relative_path: str | Path) -> bytes:
        return _RootedAtomicWriter(self.run_dir).read(
            Path("artifacts") / _relative_workspace_path(relative_path)
        )

    def artifact_file_is_regular(self, relative_path: str | Path) -> bool:
        return _RootedAtomicWriter(self.run_dir).is_regular_file(
            Path("artifacts") / _relative_workspace_path(relative_path)
        )

    def artifact_file_names(self) -> list[str]:
        return _RootedAtomicWriter(self.run_dir).list_regular_file_names("artifacts")

    def session_relative_path(self, relative_path: str | Path) -> Path:
        return Path(self.run_id) / "agent_sessions" / _relative_workspace_path(
            relative_path
        )

    def run_file_is_regular(self, relative_path: str | Path) -> bool:
        return _RootedAtomicWriter(self.run_dir).is_regular_file(relative_path)

    @classmethod
    def create(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)

        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        resolved_root = output_root.resolve()
        requested_run_dir = output_root / run_id
        requested_run_dir.mkdir(exist_ok=False)
        run_dir = requested_run_dir.resolve(strict=True)
        if run_dir.parent != resolved_root:
            raise ValueError("run_id must stay within output_root")

        sessions_dir = run_dir / "agent_sessions"
        artifacts_dir = run_dir / "artifacts"
        checkpoints_dir = run_dir / "checkpoints"
        for path in (sessions_dir, artifacts_dir, checkpoints_dir):
            path.mkdir(exist_ok=False)
        return cls(
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            artifacts_dir=artifacts_dir,
            checkpoints_dir=checkpoints_dir,
            database_path=run_dir / "run.db",
            output_root=resolved_root,
            run_id=run_id,
        )

    @classmethod
    def open_existing(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)
        output_root = Path(output_root)
        if not output_root.exists():
            raise FileNotFoundError(f"output_root does not exist: {output_root}")
        if not output_root.is_dir():
            raise ValueError("output_root must be a directory")
        resolved_root = output_root.resolve(strict=True)
        requested_run_dir = output_root / run_id
        if not requested_run_dir.exists():
            raise FileNotFoundError(f"run directory does not exist: {requested_run_dir}")
        _require_directory(requested_run_dir, "run_dir")
        resolved_run = requested_run_dir.resolve(strict=True)
        if resolved_run.parent != resolved_root:
            raise ValueError("run_dir must stay within output_root")
        run_dir = resolved_run

        sessions_dir = run_dir / "agent_sessions"
        artifacts_dir = run_dir / "artifacts"
        checkpoints_dir = run_dir / "checkpoints"
        for path, label in (
            (sessions_dir, "agent_sessions"),
            (artifacts_dir, "artifacts"),
            (checkpoints_dir, "checkpoints"),
        ):
            _require_directory(path, label)
            if path.resolve(strict=True).parent != resolved_run:
                raise ValueError(f"{label} must stay within run_dir")

        database_path = run_dir / "run.db"
        if not database_path.exists():
            raise FileNotFoundError(f"run database does not exist: {database_path}")
        if database_path.is_symlink():
            raise ValueError("run.db must not be a symlink")
        if not database_path.is_file():
            raise ValueError("run.db must be a regular file")
        if database_path.resolve(strict=True).parent != resolved_run:
            raise ValueError("run.db must stay within run_dir")
        return cls(
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            artifacts_dir=artifacts_dir,
            checkpoints_dir=checkpoints_dir,
            database_path=database_path,
            output_root=resolved_root,
            run_id=run_id,
        )


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


def _require_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if not path.is_dir():
        raise ValueError(f"{label} must be a directory")


class _RootedAtomicWriter:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

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
        relative = (
            Path()
            if candidate == Path(".")
            else _relative_workspace_path(candidate)
        )
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
        if self.root_dir.is_symlink():
            raise ValueError(f"workspace root must not be a symlink: {self.root_dir}")
        try:
            current_fd = os.open(
                self.root_dir,
                os.O_RDONLY | _directory_only() | _close_on_exec() | _no_follow(),
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise ValueError(
                    f"workspace root must not be a symlink: {self.root_dir}"
                ) from exc
            raise
        try:
            root_stat = os.fstat(current_fd)
            if not stat.S_ISDIR(root_stat.st_mode):
                raise ValueError(f"workspace root must be a directory: {self.root_dir}")
            for component in relative.parts[:-1]:
                component_stat = _lstat_at(component, current_fd)
                if component_stat is None:
                    raise FileNotFoundError(
                        f"workspace path ancestor does not exist: {component}"
                    )
                if not stat.S_ISDIR(component_stat.st_mode):
                    raise ValueError(
                        f"workspace path ancestor is not a directory: {component}"
                    )
                next_fd = _open_at(
                    component,
                    os.O_RDONLY
                    | _directory_only()
                    | _close_on_exec()
                    | _no_follow(),
                    dir_fd=current_fd,
                )
                opened_stat = os.fstat(next_fd)
                if _identity(component_stat) != _identity(opened_stat):
                    os.close(next_fd)
                    raise RuntimeError(
                        f"workspace path changed during access: {component}"
                    )
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise


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


def _no_follow() -> int:
    return int(getattr(os, "O_NOFOLLOW", 0))


def _directory_only() -> int:
    return int(getattr(os, "O_DIRECTORY", 0))


def _close_on_exec() -> int:
    return int(getattr(os, "O_CLOEXEC", 0))
