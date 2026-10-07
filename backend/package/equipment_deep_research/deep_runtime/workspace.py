"""File-backed workspace, session, and long-term memory for deep research.

This module is the small persistence boundary used by the nanobot-adapted
dialogue runtime.  SQL remains the authoritative application ledger, while
this workspace keeps a portable, inspectable working tree beside a run:

``.deep_research/``
    ``manifest.json``      workspace/equipment identity lock
    ``config/``             user or deployment configuration
    ``skills/``             procedural knowledge resources
    ``plugins/``            installed capability packages
    ``sessions/``           complete append-only conversation transcripts
    ``memory/``             bounded journal and durable Dream memory
    ``checkpoints/``        resumable runtime snapshots
    ``artifacts/``          task outputs and exports

The model-facing context is intentionally built from a short living window
and a bounded working-memory checkpoint.  The complete transcript and the
long-term journal stay outside that prompt.  ``Dream`` is an explicit,
incremental consolidation operation: it consumes new journal entries, merges
structured facts, writes ``MEMORY.md`` atomically, and advances its cursor only
after all writes succeed.

The implementation uses ordinary files so a workspace can be copied,
inspected, or resumed without a service dependency.  All paths are validated
as descendants of the workspace state directory and writes are atomic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from threading import RLock
from typing import Any, Iterator
from uuid import uuid4

from equipment_deep_research.domain.workspace import register_deep_workspace_factory


WORKSPACE_SCHEMA_VERSION = "deep-workspace-v1"
MEMORY_SCHEMA_VERSION = "deep-memory-v1"
SESSION_SCHEMA_VERSION = "deep-session-v1"
MAX_HISTORY_ENTRY_CHARS = 8_000
MAX_MEMORY_CHARS = 96_000
MAX_FACTS = 240
MAX_FACT_CHARS = 1_200
MAX_SESSION_RECORD_CHARS = 48_000
MAX_WORKING_MEMORY_CHARS = 24_000
MAX_DREAM_BATCH = 32
MAX_WORKSPACE_RESOURCE_BYTES = 2 * 1024 * 1024
MAX_RESOURCE_VERSIONS = 24

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}$")
_MANAGED_MEMORY_START = "<!-- deep-research:managed-memory:start -->"
_MANAGED_MEMORY_END = "<!-- deep-research:managed-memory:end -->"


def _resource_line_changes(
    base: Sequence[str], variant: Sequence[str]
) -> list[tuple[int, int, tuple[str, ...]]]:
    matcher = difflib.SequenceMatcher(None, list(base), list(variant), autojunk=False)
    return [
        (start, end, tuple(variant[replacement_start:replacement_end]))
        for tag, start, end, replacement_start, replacement_end in matcher.get_opcodes()
        if tag != "equal"
    ]


def _resource_changes_overlap(
    left: tuple[int, int, tuple[str, ...]],
    right: tuple[int, int, tuple[str, ...]],
) -> bool:
    left_start, left_end, _ = left
    right_start, right_end, _ = right
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    if left_start == left_end:
        return right_start <= left_start < right_end
    if right_start == right_end:
        return left_start <= right_start < left_end
    return max(left_start, right_start) < min(left_end, right_end)


def _render_resource_changes(
    base: Sequence[str],
    changes: Sequence[tuple[int, int, tuple[str, ...]]],
    start: int,
    end: int,
) -> list[str]:
    output: list[str] = []
    cursor = start
    for change_start, change_end, replacement in sorted(changes, key=lambda item: (item[0], item[1])):
        output.extend(base[cursor:change_start])
        output.extend(replacement)
        cursor = max(cursor, change_end)
    output.extend(base[cursor:end])
    return output


def _three_way_resource_merge(
    base: bytes,
    ours: bytes,
    theirs: bytes,
) -> dict[str, Any]:
    """Merge UTF-8 resource text and expose explicit conflict markers."""

    try:
        base_text = base.decode("utf-8")
        ours_text = ours.decode("utf-8")
        theirs_text = theirs.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("workspace resource merge requires UTF-8 text") from exc
    base_lines = base_text.splitlines(keepends=True)
    ours_lines = ours_text.splitlines(keepends=True)
    theirs_lines = theirs_text.splitlines(keepends=True)
    ours_changes = _resource_line_changes(base_lines, ours_lines)
    theirs_changes = _resource_line_changes(base_lines, theirs_lines)
    pending: list[tuple[str, tuple[int, int, tuple[str, ...]]]] = [
        *(('ours', item) for item in ours_changes),
        *(('theirs', item) for item in theirs_changes),
    ]
    merged: list[str] = []
    conflicts: list[dict[str, Any]] = []
    cursor = 0
    while pending:
        pending.sort(key=lambda item: (item[1][0], item[1][1], item[0]))
        group = [pending.pop(0)]
        expanded = True
        while expanded:
            expanded = False
            remaining: list[tuple[str, tuple[int, int, tuple[str, ...]]]] = []
            for candidate in pending:
                if any(_resource_changes_overlap(candidate[1], item[1]) for item in group):
                    group.append(candidate)
                    expanded = True
                else:
                    remaining.append(candidate)
            pending = remaining
        region_start = min(item[1][0] for item in group)
        region_end = max(item[1][1] for item in group)
        merged.extend(base_lines[cursor:region_start])
        ours_group = [item[1] for item in group if item[0] == "ours"]
        theirs_group = [item[1] for item in group if item[0] == "theirs"]
        if ours_group and theirs_group:
            ours_rendered = _render_resource_changes(base_lines, ours_group, region_start, region_end)
            theirs_rendered = _render_resource_changes(base_lines, theirs_group, region_start, region_end)
            if ours_rendered == theirs_rendered:
                merged.extend(ours_rendered)
            else:
                merged.extend(["<<<<<<< ours\n", *ours_rendered, "=======\n", *theirs_rendered, ">>>>>>> theirs\n"])
                conflicts.append({
                    "base_start_line": region_start + 1,
                    "base_end_line": max(region_start + 1, region_end),
                    "ours_lines": len(ours_rendered),
                    "theirs_lines": len(theirs_rendered),
                })
        else:
            selected = ours_group or theirs_group
            merged.extend(_render_resource_changes(base_lines, selected, region_start, region_end))
        cursor = max(cursor, region_end)
    merged.extend(base_lines[cursor:])
    content = "".join(merged)
    return {
        "content": content,
        "conflicted": bool(conflicts),
        "conflicts": conflicts,
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "current_sha256": hashlib.sha256(ours).hexdigest(),
        "incoming_sha256": hashlib.sha256(theirs).hexdigest(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _text(value: Any, limit: int = 1_200) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def _json_plain(value: Any) -> Any:
    """Convert common immutable containers into JSON-native values."""

    if isinstance(value, Mapping):
        return {str(key): _json_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _encode(value: Any) -> str:
    return json.dumps(
        _json_plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode_object(text: str, fallback: Any = None) -> Any:
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()[:32]


def _safe_component(value: Any, *, label: str = "name") -> str:
    candidate = _text(value, 160)
    if not candidate or not _SAFE_COMPONENT.fullmatch(candidate):
        raise ValueError(f"invalid workspace {label}")
    return candidate


def _safe_relative(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or not candidate.parts:
        raise ValueError("workspace path must be relative")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("workspace path must stay within the workspace")
    if any("\x00" in part for part in candidate.parts):
        raise ValueError("workspace path contains a NUL byte")
    return candidate


def _assert_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"workspace directory must not be a symlink: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"workspace path is not a directory: {path}")


def _mkdir(path: Path) -> None:
    """Create a private directory tree while rejecting symlink components."""

    path = path.expanduser()
    # System temporary roots are commonly symlinks on macOS (for example
    # ``/tmp`` -> ``/private/tmp``).  Resolve trusted ancestors first, while
    # still rejecting the requested directory itself when it is a symlink.
    if path.is_symlink():
        raise ValueError(f"workspace path contains a symlink: {path}")
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve(strict=False)
    current = Path(path.anchor or os.sep)
    for component in path.parts[1:] if path.anchor else path.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"workspace path contains a symlink: {current}")
        if current.exists():
            if not current.is_dir():
                raise ValueError(f"workspace path is not a directory: {current}")
            continue
        current.mkdir(mode=0o700)


def _assert_regular(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"workspace file must not be a symlink: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"workspace path is not a regular file: {path}")


def _atomic_write(path: Path, data: str | bytes, *, mode: int = 0o600) -> None:
    _mkdir(path.parent)
    _assert_regular(path)
    payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            mode,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("workspace write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_line(path: Path, record: Mapping[str, Any]) -> None:
    _mkdir(path.parent)
    _assert_regular(path)
    line = (_encode(record) + "\n").encode("utf-8")
    with open(path, "ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    _assert_regular(path)
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            value = _decode_object(raw)
            if isinstance(value, dict):
                yield value


def _read_last_jsonl_object(path: Path) -> dict[str, Any] | None:
    """Read the last valid JSON object without scanning a healthy journal.

    ``append_history`` keeps a cursor sidecar for the fast path.  A crash can
    leave the journal append durable while the sidecar still points at the
    previous row, so callers need to compare the sidecar with the durable
    tail before allocating another cursor.  History entries are bounded, but
    the fallback full scan below also handles an unusually large metadata
    record or a truncated final chunk.
    """

    if not path.exists():
        return None
    _assert_regular(path)
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return None
            read_size = min(size, 128 * 1024)
            handle.seek(size - read_size)
            data = handle.read()
    except (OSError, UnicodeError):
        return None

    for raw in reversed(data.splitlines()):
        if not raw.strip():
            continue
        try:
            value = _decode_object(raw.decode("utf-8"), None)
        except (UnicodeDecodeError, AttributeError):
            value = None
        if isinstance(value, dict):
            return value

    # A valid final record may be larger than the bounded tail read.  Falling
    # back to the normal iterator keeps cursor recovery correct in that case.
    last: dict[str, Any] | None = None
    for value in _read_jsonl(path):
        last = value
    return last


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    schema_version: str
    workspace_id: str
    identity: dict[str, Any]
    identity_fingerprint: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "identity": _json_plain(self.identity),
            "identity_fingerprint": self.identity_fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkspaceManifest":
        identity = value.get("identity")
        identity = dict(identity) if isinstance(identity, Mapping) else {}
        fingerprint = _text(value.get("identity_fingerprint"), 64)
        if not fingerprint and identity:
            fingerprint = _fingerprint(identity)
        return cls(
            schema_version=_text(value.get("schema_version"), 80)
            or WORKSPACE_SCHEMA_VERSION,
            workspace_id=_text(value.get("workspace_id"), 160),
            identity=identity,
            identity_fingerprint=fingerprint,
            created_at=_text(value.get("created_at"), 80) or _now(),
            updated_at=_text(value.get("updated_at"), 80) or _now(),
        )


class WorkspaceResourceConflict(ValueError):
    """Raised when a resource changed after the caller read its version."""

    def __init__(self, message: str, *, expected: str = "", current: str = "") -> None:
        super().__init__(message)
        self.expected = str(expected or "")
        self.current = str(current or "")


@dataclass(frozen=True, slots=True)
class DreamBatch:
    """Unprocessed journal entries presented to a Dream/consolidator turn."""

    prompt: str
    since_cursor: int
    through_cursor: int
    entries: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DreamResult:
    """Durable result of one successful or no-op consolidation."""

    changed: bool
    since_cursor: int
    through_cursor: int
    processed_entries: int
    added_facts: int
    total_facts: int
    memory_path: str
    log_path: str
    summary: str = ""


class _WorkspaceLock:
    """Reentrant per-instance lock backed by a shared file lock on POSIX."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread = RLock()
        self._depth = 0
        self._descriptor: int | None = None
        self._fcntl: Any = None

    def __enter__(self) -> "_WorkspaceLock":
        self._thread.acquire()
        try:
            if self._depth == 0:
                _assert_regular(self.path)
                self._descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
                if not stat.S_ISREG(os.fstat(self._descriptor).st_mode):
                    raise ValueError("workspace lock must be a regular file")
                try:
                    import fcntl
                except ImportError:
                    fcntl = None
                self._fcntl = fcntl
                if fcntl is not None:
                    fcntl.flock(self._descriptor, fcntl.LOCK_EX)
            self._depth += 1
            return self
        except BaseException:
            if self._depth == 0 and self._descriptor is not None:
                os.close(self._descriptor)
                self._descriptor = None
            self._thread.release()
            raise

    def __exit__(self, *_args: Any) -> None:
        try:
            self._depth -= 1
            if self._depth == 0 and self._descriptor is not None:
                try:
                    if self._fcntl is not None:
                        self._fcntl.flock(self._descriptor, self._fcntl.LOCK_UN)
                finally:
                    os.close(self._descriptor)
                    self._descriptor = None
        finally:
            self._thread.release()


class DeepWorkspace:
    """Portable external state space for one equipment research identity."""

    def __init__(
        self,
        root: Path,
        state_dir: Path,
        manifest: WorkspaceManifest,
    ) -> None:
        self.root = root
        self.state_dir = state_dir
        self.manifest = manifest
        self._lock = _WorkspaceLock(state_dir / ".state.lock")
        self.memory = DeepMemoryStore(self)
        self.sessions = DeepSessionStore(self)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        workspace_id: str = "",
        identity: Mapping[str, Any] | None = None,
        state_dir_name: str = ".deep_research",
    ) -> "DeepWorkspace":
        requested_root = Path(root).expanduser()
        if requested_root.exists() and requested_root.is_symlink():
            raise ValueError("workspace root must not be a symlink")
        _mkdir(requested_root)
        root_path = requested_root.resolve()
        state_candidate = str(state_dir_name or "").strip()
        state_parts = Path(state_candidate).parts
        if (
            not state_candidate
            or len(state_parts) != 1
            or state_parts[0] in {".", ".."}
            or any(char in state_candidate for char in ("/", "\\", "\x00"))
        ):
            raise ValueError("invalid workspace state directory")
        state_name = state_parts[0]
        state_dir = root_path / state_name
        if state_dir.exists() and state_dir.is_symlink():
            raise ValueError("workspace state directory must not be a symlink")
        _mkdir(state_dir)
        for name in (
            "config",
            "skills",
            "plugins",
            "sessions",
            "memory",
            "checkpoints",
            "artifacts",
            "resource_history",
        ):
            _mkdir(state_dir / name)
        manifest_path = state_dir / "manifest.json"
        requested_identity = dict(identity or {})
        requested_workspace_id = _text(workspace_id, 160)
        if manifest_path.exists():
            _assert_regular(manifest_path)
            raw = _decode_object(manifest_path.read_text(encoding="utf-8"), {})
            if not isinstance(raw, Mapping):
                raise ValueError("workspace manifest is malformed")
            manifest = WorkspaceManifest.from_dict(raw)
            if requested_workspace_id and manifest.workspace_id != requested_workspace_id:
                raise ValueError("workspace identity namespace mismatch")
            if requested_identity:
                requested_fingerprint = _fingerprint(requested_identity)
                if (
                    manifest.identity_fingerprint
                    and manifest.identity_fingerprint != requested_fingerprint
                ):
                    raise ValueError("workspace equipment identity mismatch")
                if not manifest.identity:
                    manifest = WorkspaceManifest(
                        schema_version=manifest.schema_version,
                        workspace_id=manifest.workspace_id,
                        identity=requested_identity,
                        identity_fingerprint=requested_fingerprint,
                        created_at=manifest.created_at,
                        updated_at=_now(),
                    )
                    _atomic_write(manifest_path, _encode(manifest.to_dict()))
        else:
            final_id = requested_workspace_id or (
                f"equipment:{_fingerprint(requested_identity)}"
                if requested_identity
                else f"workspace:{_fingerprint(str(root_path))}"
            )
            manifest = WorkspaceManifest(
                schema_version=WORKSPACE_SCHEMA_VERSION,
                workspace_id=final_id,
                identity=requested_identity,
                identity_fingerprint=(
                    _fingerprint(requested_identity) if requested_identity else ""
                ),
                created_at=_now(),
                updated_at=_now(),
            )
            _atomic_write(manifest_path, _encode(manifest.to_dict()))
        return cls(root_path, state_dir, manifest)

    @classmethod
    def open_equipment(
        cls,
        root: str | Path,
        *,
        workspace_id: str,
        identity: Mapping[str, Any],
    ) -> "DeepWorkspace":
        """Keep each canonical equipment's state separate inside one run."""
        if not identity:
            raise ValueError("equipment workspace requires an identity")
        root_path = Path(root).expanduser()
        _mkdir(root_path)
        root_path = root_path.resolve()
        parent = root_path / ".deep_research"
        _mkdir(parent)
        legacy_manifest = parent / "manifest.json"
        if legacy_manifest.exists():
            _assert_regular(legacy_manifest)
            legacy = WorkspaceManifest.from_dict(_decode_object(legacy_manifest.read_text(encoding="utf-8"), {}))
            if legacy.identity_fingerprint == _fingerprint(dict(identity)) and legacy.workspace_id == workspace_id:
                return cls.open(root_path, workspace_id=workspace_id, identity=identity)
        parent = parent / "equipment"
        _mkdir(parent)
        scope = _fingerprint(dict(identity))
        workspace = cls.open(
            parent,
            state_dir_name=scope,
            workspace_id=f"{workspace_id}:equipment:{scope}",
            identity=identity,
        )
        workspace.root = root_path
        return workspace

    @classmethod
    def from_run_workspace(
        cls,
        run_workspace: Any,
        *,
        identity: Mapping[str, Any] | None = None,
        equipment_scoped: bool = False,
    ) -> "DeepWorkspace":
        """Bind file state to an existing ``RunWorkspace`` without copying it."""

        # Resolve the path from the already bound descriptor.  ``run_dir`` is
        # a convenience label and may point at a replacement after a rename;
        # the descriptor is the identity that RunWorkspace has authenticated.
        run_id = _text(getattr(run_workspace, "run_id", ""), 160)
        if not run_id:
            raise ValueError("run workspace must expose run_dir and run_id")
        duplicate = run_workspace.dup_run_fd()
        try:
            from equipment_deep_research.domain.workspace import path_from_fd

            run_dir = path_from_fd(duplicate)
        finally:
            os.close(duplicate)
        if equipment_scoped:
            return cls.open_equipment(run_dir, workspace_id=f"run:{run_id}", identity=dict(identity or {}))
        return cls.open(run_dir, workspace_id=f"run:{run_id}", identity=identity)

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.json"

    @property
    def memory_dir(self) -> Path:
        return self.state_dir / "memory"

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "sessions"

    @property
    def checkpoints_dir(self) -> Path:
        return self.state_dir / "checkpoints"

    @property
    def artifacts_dir(self) -> Path:
        return self.state_dir / "artifacts"

    @property
    def config_dir(self) -> Path:
        return self.state_dir / "config"

    @property
    def skills_dir(self) -> Path:
        return self.state_dir / "skills"

    @property
    def plugins_dir(self) -> Path:
        return self.state_dir / "plugins"

    @property
    def resource_history_dir(self) -> Path:
        return self.state_dir / "resource_history"

    @property
    def workspace_id(self) -> str:
        return self.manifest.workspace_id

    @property
    def identity_fingerprint(self) -> str:
        return self.manifest.identity_fingerprint

    def assert_identity(self, identity: Mapping[str, Any]) -> None:
        requested = dict(identity or {})
        if not requested:
            raise ValueError("equipment identity is required")
        if self.identity_fingerprint != _fingerprint(requested):
            raise ValueError("workspace equipment identity mismatch")

    def touch(self) -> WorkspaceManifest:
        with self._lock:
            current = WorkspaceManifest(
                schema_version=self.manifest.schema_version,
                workspace_id=self.manifest.workspace_id,
                identity=dict(self.manifest.identity),
                identity_fingerprint=self.manifest.identity_fingerprint,
                created_at=self.manifest.created_at,
                updated_at=_now(),
            )
            _atomic_write(self.manifest_path, _encode(current.to_dict()))
            self.manifest = current
            return current

    def _resource_dir(self, kind: str) -> Path:
        normalized = _safe_component(kind, label="resource kind").lower()
        mapping = {
            "config": self.config_dir,
            "skill": self.skills_dir,
            "skills": self.skills_dir,
            "plugin": self.plugins_dir,
            "plugins": self.plugins_dir,
        }
        try:
            return mapping[normalized]
        except KeyError as exc:
            raise ValueError("unsupported workspace resource kind") from exc

    def _resource_kind(self, kind: str) -> str:
        normalized = _safe_component(kind, label="resource kind").lower()
        if normalized in {"skills", "skill"}:
            return "skill"
        if normalized in {"plugins", "plugin"}:
            return "plugin"
        if normalized == "config":
            return "config"
        raise ValueError("unsupported workspace resource kind")

    def _resource_history_path(self, kind: str, relative: Path) -> Path:
        canonical = self._resource_kind(kind)
        digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:32]
        return self.resource_history_dir / canonical / digest

    def _record_resource_version(
        self,
        kind: str,
        relative: Path,
        payload: bytes,
        *,
        deleted: bool = False,
    ) -> dict[str, Any]:
        created_at = _now()
        content_hash = hashlib.sha256(payload).hexdigest()
        version_id = f"{created_at.replace(':', '').replace('.', '')}-{uuid4().hex[:10]}"
        record = {
            "version_id": version_id,
            "kind": self._resource_kind(kind),
            "name": relative.as_posix(),
            "sha256": content_hash,
            "bytes": len(payload),
            "created_at": created_at,
            "deleted": bool(deleted),
            "content_base64": base64.b64encode(payload).decode("ascii"),
        }
        directory = self._resource_history_path(kind, relative)
        _atomic_write(directory / f"{version_id}.json", _encode(record))
        versions = sorted(
            (path for path in directory.glob("*.json") if path.is_file()),
            key=lambda path: path.name,
            reverse=True,
        )
        for stale in versions[MAX_RESOURCE_VERSIONS:]:
            _assert_regular(stale)
            stale.unlink()
        return record

    def write_resource(
        self,
        kind: str,
        name: str | Path,
        content: str | bytes,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        relative = _safe_relative(name)
        path = self._resource_dir(kind) / relative
        payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(payload) > MAX_WORKSPACE_RESOURCE_BYTES:
            raise ValueError("workspace resource exceeds size limit")
        with self._lock:
            _assert_regular(path)
            existing = path.read_bytes() if path.exists() else None
            current_hash = hashlib.sha256(existing).hexdigest() if existing is not None else ""
            expected = str(expected_sha256 or "").strip().lower()
            if expected and expected != current_hash:
                raise WorkspaceResourceConflict(
                    f"workspace resource changed: expected {expected}, current {current_hash}",
                    expected=expected,
                    current=current_hash,
                )
            if existing == payload:
                return path
            _atomic_write(path, payload)
            self._record_resource_version(kind, relative, payload)
            self.touch()
        return path

    def read_resource(self, kind: str, name: str | Path) -> bytes:
        relative = _safe_relative(name)
        path = self._resource_dir(kind) / relative
        with self._lock:
            _assert_regular(path)
            payload = path.read_bytes()
        if len(payload) > MAX_WORKSPACE_RESOURCE_BYTES:
            raise ValueError("workspace resource exceeds size limit")
        return payload

    def list_resources(self, kind: str) -> list[str]:
        root = self._resource_dir(kind)
        result: list[str] = []
        with self._lock:
            if not root.exists():
                return result
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"workspace resource contains a symlink: {path}")
                if path.is_file():
                    result.append(path.relative_to(root).as_posix())
        return result

    def delete_resource(self, kind: str, name: str | Path) -> bool:
        """Delete one workspace resource without following symlinks."""

        relative = _safe_relative(name)
        path = self._resource_dir(kind) / relative
        with self._lock:
            _assert_regular(path)
            if not path.exists():
                return False
            previous = path.read_bytes()
            self._record_resource_version(kind, relative, previous, deleted=True)
            path.unlink()
            self.touch()
        return True

    def list_resource_versions(
        self,
        kind: str,
        name: str | Path,
        *,
        limit: int = MAX_RESOURCE_VERSIONS,
    ) -> list[dict[str, Any]]:
        relative = _safe_relative(name)
        directory = self._resource_history_path(kind, relative)
        bounded = max(1, min(int(limit), MAX_RESOURCE_VERSIONS))
        result: list[dict[str, Any]] = []
        with self._lock:
            if not directory.exists():
                return result
            for path in sorted(directory.glob("*.json"), key=lambda item: item.name, reverse=True)[:bounded]:
                _assert_regular(path)
                raw = _decode_object(path.read_text(encoding="utf-8"), {})
                if not isinstance(raw, Mapping):
                    continue
                result.append({
                    "version_id": str(raw.get("version_id", "")),
                    "kind": self._resource_kind(kind),
                    "name": relative.as_posix(),
                    "sha256": str(raw.get("sha256", "")),
                    "bytes": int(raw.get("bytes", 0) or 0),
                    "created_at": str(raw.get("created_at", "")),
                    "deleted": bool(raw.get("deleted", False)),
                })
        return result

    def read_resource_version(self, kind: str, name: str | Path, version_id: str) -> bytes:
        relative = _safe_relative(name)
        version = _safe_component(version_id, label="version")
        path = self._resource_history_path(kind, relative) / f"{version}.json"
        with self._lock:
            _assert_regular(path)
            raw = _decode_object(path.read_text(encoding="utf-8"), {})
        if not isinstance(raw, Mapping):
            raise FileNotFoundError(version)
        try:
            payload = base64.b64decode(str(raw.get("content_base64", "")), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("workspace resource history is malformed") from exc
        if len(payload) > MAX_WORKSPACE_RESOURCE_BYTES:
            raise ValueError("workspace resource exceeds size limit")
        return payload

    def restore_resource_version(
        self,
        kind: str,
        name: str | Path,
        version_id: str,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        """Restore a historical snapshot through the same optimistic fence."""

        payload = self.read_resource_version(kind, name, version_id)
        relative = _safe_relative(name)
        with self._lock:
            current_path = self._resource_dir(kind) / relative
            _assert_regular(current_path)
            current = current_path.read_bytes() if current_path.exists() else None
            current_hash = hashlib.sha256(current).hexdigest() if current is not None else ""
            expected = str(expected_sha256 or "").strip().lower()
            if expected and expected != current_hash:
                raise WorkspaceResourceConflict(
                    f"workspace resource changed: expected {expected}, current {current_hash}",
                    expected=expected,
                    current=current_hash,
                )
        return self.write_resource(
            kind,
            relative,
            payload,
            expected_sha256=current_hash,
        )

    def merge_resource_version(
        self,
        kind: str,
        name: str | Path,
        base_version_id: str,
        incoming: str | bytes,
    ) -> dict[str, Any]:
        """Preview a three-way merge from one historical version.

        ``base_version_id`` is the editor's ancestor, the current file is
        ``ours`` and ``incoming`` is the editor draft.  The method never
        writes; callers must review conflicts and use ``write_resource`` with
        the returned current hash to commit.
        """

        base = self.read_resource_version(kind, name, base_version_id)
        relative = _safe_relative(name)
        current_path = self._resource_dir(kind) / relative
        with self._lock:
            _assert_regular(current_path)
            current = current_path.read_bytes() if current_path.exists() else b""
        payload = incoming.encode("utf-8") if isinstance(incoming, str) else bytes(incoming)
        if len(payload) > MAX_WORKSPACE_RESOURCE_BYTES:
            raise ValueError("workspace resource exceeds size limit")
        result = _three_way_resource_merge(base, current, payload)
        result.update({
            "kind": self._resource_kind(kind),
            "name": relative.as_posix(),
            "base_version_id": str(base_version_id),
        })
        return result

    def merge_plugin_package(
        self,
        plugin_id: str,
        *,
        base_versions: Mapping[str, str],
        incoming_files: Mapping[str, str],
    ) -> dict[str, Any]:
        """Preview a package-level merge without creating a half-installed plugin."""

        package = _safe_component(plugin_id, label="plugin id")
        if not isinstance(base_versions, Mapping) or not isinstance(incoming_files, Mapping):
            raise ValueError("plugin package merge requires file maps")
        if len(incoming_files) > 128 or len(base_versions) > 128:
            raise ValueError("plugin package merge exceeds file limit")
        normalized_incoming: dict[str, str] = {}
        normalized_base: dict[str, str] = {}
        for raw_name, content in incoming_files.items():
            relative = _safe_relative(str(raw_name))
            if not relative.parts or relative.parts[0] != package:
                raise ValueError("plugin package file must remain under its plugin directory")
            value = str(content)
            if len(value.encode("utf-8")) > MAX_WORKSPACE_RESOURCE_BYTES:
                raise ValueError("workspace resource exceeds size limit")
            normalized_incoming[relative.as_posix()] = value
        for raw_name, version_id in base_versions.items():
            relative = _safe_relative(str(raw_name))
            if not relative.parts or relative.parts[0] != package:
                raise ValueError("plugin base version must remain under its plugin directory")
            normalized_base[relative.as_posix()] = _safe_component(version_id, label="version")
        current_names = {
            name for name in self.list_resources("plugin")
            if PurePosixPath(name).parts and PurePosixPath(name).parts[0] == package
        }
        names = sorted(current_names | set(normalized_incoming) | set(normalized_base))
        files: list[dict[str, Any]] = []
        for name in names:
            base_version = normalized_base.get(name, "")
            incoming = normalized_incoming.get(name)
            current_path = self._resource_dir("plugin") / _safe_relative(name)
            current_exists = current_path.exists()
            if incoming is None:
                if not base_version:
                    continue
                base_payload = self.read_resource_version("plugin", name, base_version)
                current_payload = current_path.read_bytes() if current_exists else b""
                if current_payload == base_payload:
                    files.append({
                        "name": name,
                        "action": "delete",
                        "content": "",
                        "conflicted": False,
                        "base_version_id": base_version,
                        "current_sha256": hashlib.sha256(current_payload).hexdigest(),
                    })
                else:
                    files.append({
                        "name": name,
                        "action": "delete",
                        "content": "",
                        "conflicted": True,
                        "conflicts": [{"reason": "server_changed_before_delete"}],
                        "base_version_id": base_version,
                        "current_sha256": hashlib.sha256(current_payload).hexdigest(),
                    })
                continue
            if base_version:
                merged = self.merge_resource_version("plugin", name, base_version, incoming)
                files.append({"name": name, "action": "upsert", **merged})
            elif current_exists:
                files.append({
                    "name": name,
                    "action": "upsert",
                    "content": incoming,
                    "conflicted": True,
                    "conflicts": [{"reason": "new_file_collides_with_server_file"}],
                    "current_sha256": hashlib.sha256(current_path.read_bytes()).hexdigest(),
                })
            else:
                payload = incoming.encode("utf-8")
                files.append({
                    "name": name,
                    "action": "upsert",
                    "content": incoming,
                    "conflicted": False,
                    "conflicts": [],
                    "current_sha256": "",
                    "incoming_sha256": hashlib.sha256(payload).hexdigest(),
                })
        return {
            "plugin_id": package,
            "files": files,
            "conflicted": any(bool(item.get("conflicted")) for item in files),
            "atomic_ready": not any(bool(item.get("conflicted")) for item in files),
        }

    def apply_plugin_package_merge(
        self,
        plugin_id: str,
        *,
        base_versions: Mapping[str, str],
        incoming_files: Mapping[str, str],
    ) -> dict[str, Any]:
        """Apply a conflict-free package preview under the workspace lock.

        The operation rechecks every base version while holding the
        inter-process workspace lock.  If a filesystem error occurs during
        the batch, prior bytes are restored before the error is propagated.
        This gives callers an all-or-nothing application result for the
        package transaction while preserving per-file history snapshots.
        """

        with self._lock:
            preview = self.merge_plugin_package(
                plugin_id,
                base_versions=base_versions,
                incoming_files=incoming_files,
            )
            if not preview["atomic_ready"]:
                return {**preview, "applied": False}
            before: dict[str, bytes | None] = {}
            # History is part of the package transaction too.  Snapshot the
            # affected per-file journals before writing so a late failure
            # cannot leave audit entries for a package that was rolled back.
            history_before: dict[Path, bytes] = {}
            history_dirs: set[Path] = set()
            changed = False
            try:
                for item in preview["files"]:
                    name = str(item["name"])
                    path = self._resource_dir("plugin") / _safe_relative(name)
                    _assert_regular(path)
                    before[name] = path.read_bytes() if path.exists() else None
                    history_dir = self._resource_history_path("plugin", _safe_relative(name))
                    history_dirs.add(history_dir)
                    if history_dir.exists():
                        _assert_directory(history_dir)
                        for history_file in history_dir.glob("*.json"):
                            _assert_regular(history_file)
                            history_before[history_file] = history_file.read_bytes()
                for item in preview["files"]:
                    name = str(item["name"])
                    path = self._resource_dir("plugin") / _safe_relative(name)
                    if item["action"] == "delete":
                        if path.exists():
                            previous = path.read_bytes()
                            self._record_resource_version("plugin", _safe_relative(name), previous, deleted=True)
                            path.unlink()
                            changed = True
                        continue
                    payload = str(item.get("content", "")).encode("utf-8")
                    if before.get(name) == payload:
                        continue
                    _atomic_write(path, payload)
                    self._record_resource_version("plugin", _safe_relative(name), payload)
                    changed = True
                if changed:
                    self.touch()
            except Exception:
                for name, payload in before.items():
                    path = self._resource_dir("plugin") / _safe_relative(name)
                    if payload is None:
                        if path.exists():
                            path.unlink()
                    else:
                        _atomic_write(path, payload)
                for history_dir in history_dirs:
                    if history_dir.exists():
                        _assert_directory(history_dir)
                        for history_file in history_dir.glob("*.json"):
                            if history_file not in history_before:
                                _assert_regular(history_file)
                                history_file.unlink()
                    for history_file, payload in history_before.items():
                        if history_file.parent == history_dir:
                            _atomic_write(history_file, payload)
                raise
            return {**preview, "applied": True}

    def write_artifact(self, name: str | Path, content: str | bytes) -> Path:
        relative = _safe_relative(name)
        path = self.artifacts_dir / relative
        _atomic_write(path, content)
        self.touch()
        return path

    def read_artifact(self, name: str | Path) -> bytes:
        relative = _safe_relative(name)
        path = self.artifacts_dir / relative
        _assert_regular(path)
        return path.read_bytes()

    def write_checkpoint(self, name: str | Path, checkpoint: Mapping[str, Any]) -> Path:
        relative = _safe_relative(name)
        path = self.checkpoints_dir / relative
        payload = _encode(checkpoint)
        if len(payload) > MAX_WORKING_MEMORY_CHARS * 3:
            raise ValueError("workspace checkpoint exceeds size limit")
        _atomic_write(path, payload)
        self.touch()
        return path

    def read_checkpoint(self, name: str | Path) -> dict[str, Any] | None:
        relative = _safe_relative(name)
        path = self.checkpoints_dir / relative
        if not path.exists():
            return None
        _assert_regular(path)
        value = _decode_object(path.read_text(encoding="utf-8"), None)
        return dict(value) if isinstance(value, Mapping) else None


class DeepMemoryStore:
    """Long-term journal and incremental Dream consolidation."""

    def __init__(self, workspace: DeepWorkspace) -> None:
        self.workspace = workspace
        self.memory_file = workspace.memory_dir / "MEMORY.md"
        self.facts_file = workspace.memory_dir / "facts.jsonl"
        self.history_file = workspace.memory_dir / "history.jsonl"
        self.cursor_file = workspace.memory_dir / ".cursor"
        self.dream_cursor_file = workspace.memory_dir / ".dream_cursor"
        self.dream_log_file = workspace.memory_dir / "dream-log.jsonl"

    def read_memory(self) -> str:
        if not self.memory_file.exists():
            return ""
        _assert_regular(self.memory_file)
        return self.memory_file.read_text(encoding="utf-8")[:MAX_MEMORY_CHARS]

    # Nanobot-compatible vocabulary kept at this boundary makes migration
    # straightforward for callers that previously used MemoryStore directly.
    def get_memory_context(self) -> str:
        value = self.read_memory()
        return f"## Long-term Memory\n{value}" if value else ""

    def write_memory(self, content: str) -> None:
        value = str(content or "")
        if len(value) > MAX_MEMORY_CHARS:
            raise ValueError("long-term memory exceeds size limit")
        _atomic_write(self.memory_file, value)
        self.workspace.touch()

    def _counter(self, path: Path) -> int:
        if not path.exists():
            return 0
        _assert_regular(path)
        try:
            value = int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return 0
        return max(0, value)

    def _history_cursor_max(self, counter: int) -> int:
        """Return the durable maximum cursor, repairing a stale sidecar view.

        The sidecar and JSONL row are written in separate filesystem
        operations.  If the process dies between those writes, the sidecar
        can lag behind a durable row.  Comparing the sidecar with the tail is
        constant-time on the normal path; a mismatch triggers a bounded
        recovery scan so malformed or externally edited journals cannot cause
        cursor reuse.
        """

        tail = _read_last_jsonl_object(self.history_file)
        tail_cursor: int | None = None
        if isinstance(tail, Mapping):
            try:
                candidate = int(tail.get("cursor", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                candidate = -1
            if candidate >= 0:
                tail_cursor = candidate
        if tail_cursor is not None and tail_cursor == counter:
            return counter

        maximum = max(0, counter)
        for item in _read_jsonl(self.history_file):
            try:
                candidate = int(item.get("cursor", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if candidate >= 0:
                maximum = max(maximum, candidate)
        return maximum

    def latest_cursor(self) -> int:
        return self._history_cursor_max(self._counter(self.cursor_file))

    def get_latest_cursor(self) -> int:
        return self.latest_cursor()

    def last_dream_cursor(self) -> int:
        # A manually edited or interrupted sidecar must not point beyond the
        # durable journal; clamping it keeps a future batch from being skipped.
        return min(self._counter(self.dream_cursor_file), self.latest_cursor())

    def get_last_dream_cursor(self) -> int:
        return self.last_dream_cursor()

    def set_last_dream_cursor(self, cursor: int) -> None:
        with self.workspace._lock:
            value = max(0, int(cursor))
            if value > self.latest_cursor():
                raise ValueError("Dream cursor cannot exceed the history cursor")
            _atomic_write(self.dream_cursor_file, str(value))

    def _next_cursor(self) -> int:
        return self.latest_cursor() + 1

    def append_history(
        self,
        content: Any,
        *,
        session_id: str = "",
        branch_id: str = "main",
        role: str = "assistant",
        metadata: Mapping[str, Any] | None = None,
        max_chars: int = MAX_HISTORY_ENTRY_CHARS,
    ) -> int:
        value = str(content or "").replace("\x00", "").strip()
        value = value[: max(1, int(max_chars or MAX_HISTORY_ENTRY_CHARS))]
        with self.workspace._lock:
            cursor = self._next_cursor()
            record = {
                "cursor": cursor,
                "timestamp": _now(),
                "session_id": _text(session_id, 160),
                "branch_id": _text(branch_id, 160) or "main",
                "role": _text(role, 24).lower() or "assistant",
                "content": value,
                "metadata": _json_plain(dict(metadata or {})),
            }
            _append_line(self.history_file, record)
            _atomic_write(self.cursor_file, str(cursor))
            self.workspace.touch()
            return cursor

    def read_history(
        self,
        *,
        since_cursor: int = 0,
        limit: int = MAX_DREAM_BATCH,
    ) -> list[dict[str, Any]]:
        floor = max(0, int(since_cursor or 0))
        result: list[dict[str, Any]] = []
        for item in _read_jsonl(self.history_file):
            try:
                cursor = int(item.get("cursor", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if cursor <= floor:
                continue
            content = _text(item.get("content"), MAX_HISTORY_ENTRY_CHARS)
            if not content:
                continue
            item = dict(item)
            item["cursor"] = cursor
            item["content"] = content
            result.append(item)
            if len(result) >= max(1, min(int(limit or MAX_DREAM_BATCH), MAX_DREAM_BATCH)):
                break
        return result

    @property
    def dream_prompt_file(self) -> Path:
        return self.workspace.config_dir / "dream.md"

    @staticmethod
    def dream_session_key() -> str:
        return f"dream:{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"

    def raw_archive(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        session_id: str = "",
        branch_id: str = "main",
    ) -> int:
        """Persist a bounded raw checkpoint when a summarizer degrades."""

        lines: list[str] = []
        for item in list(messages)[:32]:
            if not isinstance(item, Mapping):
                continue
            role = _text(item.get("role"), 24).upper() or "TURN"
            content = _text(item.get("content"), 1_000)
            if content:
                lines.append(f"{role}: {content}")
        return self.append_history(
            "[RAW CHECKPOINT]\n" + "\n".join(lines),
            session_id=session_id,
            branch_id=branch_id,
            role="checkpoint",
        )

    def build_dream_prompt(self, *, max_entries: int = MAX_DREAM_BATCH) -> DreamBatch | None:
        with self.workspace._lock:
            return self._build_dream_prompt(max_entries=max_entries)

    def _build_dream_prompt(self, *, max_entries: int) -> DreamBatch | None:
        since = self.last_dream_cursor()
        entries = self.read_history(since_cursor=since, limit=max_entries)
        if not entries:
            return None
        lines = [
            "You are the deep-research memory consolidator.",
            "Extract durable equipment-research facts, decisions, assumptions, and open frontiers.",
            "Do not copy credentials, hidden reasoning, or transient tool metadata.",
            "Return concise structured facts; preserve uncertainty instead of inventing evidence.",
            "",
            "## New journal entries",
        ]
        for item in entries:
            timestamp = _text(item.get("timestamp"), 40)
            role = _text(item.get("role"), 20).upper() or "TURN"
            scope = f"session={_text(item.get('session_id'), 160)} branch={_text(item.get('branch_id'), 160)}"
            lines.append(f"[{timestamp}] [{scope}] {role}: {_text(item.get('content'), 1_000)}")
        return DreamBatch(
            prompt="\n".join(lines),
            since_cursor=since,
            # Commit the last row in file order.  Taking ``max`` here can skip
            # a lower cursor that follows an externally reordered row; the
            # next Dream batch can safely replay an earlier row, while it
            # cannot recover one that was skipped by a high-water mark.
            through_cursor=int(entries[-1].get("cursor", since)),
            entries=tuple(dict(item) for item in entries),
        )

    def read_context(self, *, session_id: str, branch_id: str = "main", max_chars: int = 2400) -> str:
        """Project scoped durable findings without importing sibling hypotheses."""
        existing = self.read_memory()
        start = existing.find(_MANAGED_MEMORY_START)
        end = existing.rfind(_MANAGED_MEMORY_END)
        manual = existing if start < 0 else existing[:start]
        if start >= 0 and end >= start:
            manual += existing[end + len(_MANAGED_MEMORY_END):]
        rows = [
            "[{}] {}".format(
                "/".join(filter(None, (
                    _text(row.get("kind"), 64),
                    _text(row.get("stance"), 32),
                    f"subject={_text(row.get('subject_key'), 120)}"
                    if _text(row.get("subject_key"), 120)
                    else "",
                ))),
                row["text"],
            )
            for row in self._read_facts()
            if row.get("session_id") == session_id
            and (row.get("branch_id") or "main") == branch_id
        ]
        budget = max(0, min(int(max_chars), 12000))
        manual = manual.strip()[:budget // 2] if rows else manual.strip()[:budget]
        available = max(0, budget - len(manual) - 1)
        return (manual + "\n" + "\n".join(rows)[-available:] if available else manual).strip()[:budget]

    def _read_facts(self) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for item in _read_jsonl(self.facts_file):
            text = _text(item.get("text") or item.get("fact"), MAX_FACT_CHARS)
            if not text:
                continue
            row = dict(item)
            row["text"] = text
            row["fact_id"] = _text(row.get("fact_id"), 64) or _fingerprint(
                {
                    "kind": _text(row.get("kind"), 64),
                    "text": text.casefold(),
                }
            )
            facts.append(row)
        return facts[-MAX_FACTS:]

    @staticmethod
    def _facts_from_inputs(
        *,
        facts: Sequence[Any] | None,
        summary: str,
        working_memory: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def add(
            kind: Any,
            value: Any,
            *,
            source: str = "dream",
            session_id: str = "",
            branch_id: str = "",
            stance: str = "",
            subject_key: str = "",
        ) -> None:
            text = _text(value, MAX_FACT_CHARS)
            if not text:
                return
            row = {"kind": _text(kind, 64) or "fact", "text": text, "source": source}
            normalized_stance = _text(stance, 32).lower()
            if normalized_stance:
                row["stance"] = normalized_stance
            normalized_subject = _text(subject_key, 160)
            if normalized_subject:
                row["subject_key"] = normalized_subject
            if session_id:
                row.update({"session_id": _text(session_id, 160), "branch_id": _text(branch_id, 160) or "main"})
            rows.append(row)

        for item in facts or ():
            if isinstance(item, Mapping):
                add(
                    item.get("kind") or item.get("category") or "fact",
                    item.get("text") or item.get("fact") or item.get("content"),
                    source="model",
                    session_id=item.get("session_id", ""),
                    branch_id=item.get("branch_id", ""),
                    stance=item.get("stance", ""),
                    subject_key=item.get("subject_key", ""),
                )
            else:
                add("fact", item, source="model")
        add("summary", summary)
        memory = working_memory if isinstance(working_memory, Mapping) else {}
        for item in memory.get("candidate_directions", []) if isinstance(memory.get("candidate_directions"), list) else []:
            if isinstance(item, Mapping):
                name = _text(item.get("name"), 180)
                angle = _text(item.get("winning_angle") or item.get("innovation_thesis"), 600)
                if name:
                    add("frontier", f"{name}: {angle}" if angle else name, source="working_memory")
        for item in memory.get("assumption_ledger", []) if isinstance(memory.get("assumption_ledger"), list) else []:
            if isinstance(item, Mapping):
                assumption = _text(item.get("assumption"), 600)
                status = _text(item.get("status"), 48)
                if assumption:
                    add("assumption", f"{assumption} ({status})" if status else assumption, source="working_memory")
        for key, kind in (("decisions", "decision"), ("rejected_directions", "rejected")):
            raw = memory.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, Mapping):
                    candidate = _text(item.get("candidate") or item.get("candidate_name"), 220)
                    reason = _text(item.get("reason") or item.get("decisive_issue"), 600)
                    if candidate:
                        add(kind, f"{candidate}: {reason}" if reason else candidate, source="working_memory")
        for item in memory.get("research_gaps", []) if isinstance(memory.get("research_gaps"), list) else []:
            add("open_frontier", item, source="working_memory")
        return rows

    def _render_managed_memory(self, facts: Sequence[Mapping[str, Any]], summary: str) -> str:
        """Render a bounded managed block while preserving its delimiters.

        A plain ``result[:MAX_MEMORY_CHARS]`` truncation can cut the closing
        marker when a Dream returns many facts.  Once that happens the next
        consolidation treats the old block as manual text and appends another
        block, steadily corrupting the memory file.  We budget the managed
        rows against the manual prefix/suffix and always retain both markers.
        """

        existing = self.read_memory()
        start = existing.find(_MANAGED_MEMORY_START)
        end_marker_start = existing.rfind(_MANAGED_MEMORY_END)
        has_complete_block = (
            start >= 0
            and end_marker_start >= start
        )
        if start >= 0:
            # If a prior write was interrupted before its end marker, discard
            # the incomplete managed tail and rebuild it deterministically.
            prefix = existing[:start].rstrip()
            suffix = (
                existing[end_marker_start + len(_MANAGED_MEMORY_END) :].strip("\n")
                if has_complete_block
                else ""
            )
        else:
            prefix = existing.rstrip()
            suffix = ""

        if prefix:
            leading = prefix + "\n\n"
        elif start < 0 and not existing.strip():
            leading = "# Deep Research Memory\n\n"
        else:
            leading = ""
        trailing = "\n\n" + suffix + "\n" if suffix else "\n"

        rows: list[tuple[str, str]] = []
        for item in facts[-MAX_FACTS:]:
            kind = _text(item.get("kind"), 64) or "fact"
            stance = _text(item.get("stance"), 32)
            if stance:
                kind = f"{kind} / {stance}"
            text = _text(item.get("text"), MAX_FACT_CHARS)
            subject_key = _text(item.get("subject_key"), 160)
            if subject_key and text:
                text = f"[{subject_key}] {text}"
            if text:
                rows.append((kind, text))
        summary_text = _text(summary, 1_000)

        def build_block(selected: Sequence[tuple[str, str]], latest: str) -> str:
            body = [
                _MANAGED_MEMORY_START,
                f"## Consolidated research memory ({_now()})",
            ]
            grouped: dict[str, list[str]] = {}
            for kind, text in selected:
                grouped.setdefault(kind, []).append(text)
            for kind, values in grouped.items():
                body.append(f"### {kind}")
                for value in values:
                    body.append(f"- {value}")
            if latest:
                body.extend(("### latest consolidation", f"- {latest}"))
            body.append(_MANAGED_MEMORY_END)
            return "\n".join(body)

        budget = max(0, MAX_MEMORY_CHARS - len(leading) - len(trailing))
        selected = list(rows)
        # Drop oldest facts first.  This retains the most recent research
        # state while keeping a deterministic, bounded representation.
        while selected and len(build_block(selected, summary_text)) > budget:
            selected.pop(0)

        if len(build_block(selected, summary_text)) > budget:
            empty_length = len(build_block(selected, ""))
            summary_budget = max(0, budget - empty_length - len("### latest consolidation\n- "))
            summary_text = summary_text[:summary_budget]
        if len(build_block(selected, summary_text)) > budget:
            selected = []
            summary_text = ""

        managed = build_block(selected, summary_text)
        result = leading + managed + trailing
        if len(result) <= MAX_MEMORY_CHARS:
            return result

        # The existing manual text may itself consume the entire cap.  Trim
        # its tail only as a last resort; the managed delimiters remain intact.
        room_for_manual = max(0, MAX_MEMORY_CHARS - len(managed) - 1)
        manual = (leading + trailing)[:room_for_manual]
        return manual + managed + "\n"

    def consolidate_dream(
        self,
        *,
        facts: Sequence[Any] | None = None,
        summary: str = "",
        working_memory: Mapping[str, Any] | None = None,
        max_entries: int = MAX_DREAM_BATCH,
        advance_cursor: bool = True,
        batch: DreamBatch | None = None,
    ) -> DreamResult:
        """Merge a bounded Dream result and advance the cursor transactionally.

        ``facts`` is intentionally supplied by the model-facing Dream turn;
        this method never pretends that a raw transcript is verified fact. If
        no structured result is returned, the working-memory projection is
        still useful as a clearly labelled checkpoint.
        """

        with self.workspace._lock:
            since = self.last_dream_cursor()
            if batch is not None:
                if batch.since_cursor != since or batch.through_cursor > self.latest_cursor():
                    raise ValueError("stale Dream batch")
            else:
                batch = self.build_dream_prompt(max_entries=max_entries)
            if batch is None and not facts and not summary and not working_memory:
                return DreamResult(
                    changed=False,
                    since_cursor=since,
                    through_cursor=since,
                    processed_entries=0,
                    added_facts=0,
                    total_facts=len(self._read_facts()),
                    memory_path=str(self.memory_file),
                    log_path=str(self.dream_log_file),
                )
            through = batch.through_cursor if batch is not None else since
            new_rows = self._facts_from_inputs(
                facts=facts,
                summary=summary,
                working_memory=working_memory,
            )
            existing = self._read_facts()
            seen = {str(item.get("fact_id", "")) for item in existing}
            added: list[dict[str, Any]] = []
            for row in new_rows:
                row = dict(row)
                key = {
                    "kind": _text(row.get("kind"), 64),
                    "text": _text(row.get("text"), MAX_FACT_CHARS).casefold(),
                }
                if row.get("stance"):
                    key["stance"] = _text(row.get("stance"), 32)
                if row.get("subject_key"):
                    key["subject_key"] = _text(row.get("subject_key"), 160).casefold()
                if row.get("session_id"):
                    key.update({"session_id": row["session_id"], "branch_id": row["branch_id"]})
                row["fact_id"] = _fingerprint(key)
                if row["fact_id"] in seen:
                    continue
                seen.add(row["fact_id"])
                row.update({"created_at": _now(), "cursor": through})
                added.append(row)
            all_facts = (existing + added)[-MAX_FACTS:]
            if batch is not None and not new_rows:
                # Preserve a clearly marked checkpoint rather than silently
                # losing a successful Dream run with an empty model response.
                # This must also run when older durable facts already exist;
                # checking ``all_facts`` alone would advance the cursor while
                # dropping the newly supplied journal batch.
                excerpt = _text(batch.entries[-1].get("content"), 600)
                if excerpt:
                    checkpoint_key = {"kind": "checkpoint", "text": excerpt.casefold()}
                    if batch.entries[-1].get("session_id"):
                        checkpoint_key.update({"session_id": batch.entries[-1]["session_id"], "branch_id": batch.entries[-1].get("branch_id", "main")})
                    row = {
                        "fact_id": _fingerprint(checkpoint_key),
                        "kind": "checkpoint",
                        "text": excerpt,
                        "source": "journal",
                        "created_at": _now(),
                        "cursor": through,
                        "session_id": batch.entries[-1].get("session_id", ""),
                        "branch_id": batch.entries[-1].get("branch_id", "main"),
                    }
                    if row["fact_id"] not in seen:
                        all_facts = (existing + [row])[-MAX_FACTS:]
                        added = [row]
            rendered = self._render_managed_memory(all_facts, summary)
            previous = self.read_memory()
            changed = rendered != previous
            if changed:
                _atomic_write(self.memory_file, rendered)
            # Rewrite facts atomically as a compact journal.  Keeping this
            # alongside MEMORY.md makes copy/resume deterministic.
            if added or (all_facts and not self.facts_file.exists()):
                payload = "".join(_encode(item) + "\n" for item in all_facts)
                _atomic_write(self.facts_file, payload)
            log_record = {
                "timestamp": _now(),
                "since_cursor": since,
                "through_cursor": through,
                "processed_entries": len(batch.entries) if batch is not None else 0,
                "added_facts": len(added),
                "summary": _text(summary, 1_000),
                "changed": changed,
            }
            _append_line(self.dream_log_file, log_record)
            self.workspace.touch()
            # The cursor is the commit marker for the incremental batch.  It
            # must be the final write so a failed facts/memory/audit update is
            # retried instead of being skipped on the next Dream run.
            if advance_cursor and batch is not None:
                _atomic_write(self.dream_cursor_file, str(through))
            return DreamResult(
                changed=changed,
                since_cursor=since,
                through_cursor=through,
                processed_entries=len(batch.entries) if batch is not None else 0,
                added_facts=len(added),
                total_facts=len(all_facts),
                memory_path=str(self.memory_file),
                log_path=str(self.dream_log_file),
                summary=_text(summary, 1_000),
            )


class DeepSessionStore:
    """Complete transcript and branch working-memory persistence."""

    def __init__(self, workspace: DeepWorkspace) -> None:
        self.workspace = workspace

    def _path(self, session_id: str) -> Path:
        return self.workspace.sessions_dir / f"{_safe_component(session_id, label='session id')}.jsonl"

    def _branch_path(self, session_id: str, branch_id: str) -> Path:
        return self.workspace.memory_dir / "branches" / _safe_component(session_id, label="session id") / f"{_safe_component(branch_id, label='branch id')}.json"

    def create(self, session_id: str, *, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        path = self._path(session_id)
        with self.workspace._lock:
            if not path.exists():
                record = {
                    "_type": "metadata",
                    "schema_version": SESSION_SCHEMA_VERSION,
                    "session_id": _safe_component(session_id, label="session id"),
                    "workspace_id": self.workspace.workspace_id,
                    "created_at": _now(),
                    "updated_at": _now(),
                    "metadata": _json_plain(dict(metadata or {})),
                }
                _append_line(path, record)
            return self.load(session_id) or {
                "session_id": session_id,
                "messages": [],
                "working_memory": {},
                "metadata": dict(metadata or {}),
            }

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: Any,
        branch_id: str = "main",
        message_id: str = "",
        metadata: Mapping[str, Any] | None = None,
        status: str = "completed",
    ) -> dict[str, Any]:
        with self.workspace._lock:
            session = self.create(session_id)
            messages = session.get("messages", [])
            sequence = len(messages) + 1
            row = {
                "_type": "message",
                "message_id": _text(message_id, 160) or f"{session_id}-{sequence}",
                "sequence": sequence,
                "role": _text(role, 24).lower() or "user",
                "content": str(content or "")[:MAX_SESSION_RECORD_CHARS],
                "branch_id": _text(branch_id, 160) or "main",
                "status": _text(status, 32) or "completed",
                "metadata": _json_plain(dict(metadata or {})),
                "created_at": _now(),
            }
            _append_line(self._path(session_id), row)
            # The journal is intentionally a compact semantic archive, while
            # this JSONL transcript remains complete and replayable.
            self.workspace.memory.append_history(
                f"{row['role']}: {row['content']}",
                session_id=session_id,
                branch_id=row["branch_id"],
                role=row["role"],
            )
            self._touch_session_metadata(session_id)
            return row

    def save_working_memory(
        self,
        session_id: str,
        checkpoint: Mapping[str, Any],
        *,
        branch_id: str = "main",
    ) -> Path:
        payload = _json_plain(dict(checkpoint or {}))
        encoded = _encode(payload)
        if len(encoded) > MAX_WORKING_MEMORY_CHARS:
            raise ValueError("working memory exceeds size limit")
        path = self._branch_path(session_id, _text(branch_id, 160) or "main")
        with self.workspace._lock:
            self.create(session_id)
            _atomic_write(path, encoded)
            _append_line(
                self._path(session_id),
                {
                    "_type": "checkpoint",
                    "branch_id": _text(branch_id, 160) or "main",
                    "working_memory": payload,
                    "created_at": _now(),
                },
            )
            self._touch_session_metadata(session_id)
        return path

    def load_working_memory(self, session_id: str, *, branch_id: str = "main") -> dict[str, Any]:
        path = self._branch_path(session_id, _text(branch_id, 160) or "main")
        if path.exists():
            _assert_regular(path)
            value = _decode_object(path.read_text(encoding="utf-8"), {})
            return dict(value) if isinstance(value, Mapping) else {}
        session = self.load(session_id)
        branches = session.get("branches", {}) if isinstance(session, Mapping) else {}
        value = branches.get(_text(branch_id, 160) or "main", {}) if isinstance(branches, Mapping) else {}
        return dict(value) if isinstance(value, Mapping) else {}

    def _touch_session_metadata(self, session_id: str) -> None:
        path = self._path(session_id)
        rows = list(_read_jsonl(path))
        if not rows:
            return
        metadata = dict(rows[0])
        metadata["updated_at"] = _now()
        rest = rows[1:]
        payload = "".join(_encode(metadata if index == 0 else item) + "\n" for index, item in enumerate([metadata, *rest]))
        _atomic_write(path, payload)

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        rows = list(_read_jsonl(path))
        if not rows:
            return None
        metadata = dict(rows[0]) if rows[0].get("_type") == "metadata" else {}
        messages = [dict(item) for item in rows[1:] if item.get("_type") == "message"]
        checkpoints = [dict(item) for item in rows[1:] if item.get("_type") == "checkpoint"]
        branches: dict[str, dict[str, Any]] = {}
        for item in checkpoints:
            branch = _text(item.get("branch_id"), 160) or "main"
            value = item.get("working_memory")
            if isinstance(value, Mapping):
                branches[branch] = dict(value)
        if branches:
            working_memory = branches.get("main") or next(iter(branches.values()))
        else:
            working_memory = {}
        return {
            "session_id": _text(metadata.get("session_id"), 160) or session_id,
            "workspace_id": _text(metadata.get("workspace_id"), 160),
            "created_at": _text(metadata.get("created_at"), 80),
            "updated_at": _text(metadata.get("updated_at"), 80),
            "metadata": metadata.get("metadata", {}) if isinstance(metadata.get("metadata"), Mapping) else {},
            "messages": messages,
            "checkpoints": checkpoints,
            "branches": branches,
            "working_memory": working_memory,
        }

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.workspace.sessions_dir.glob("*.jsonl")):
            if path.is_symlink():
                raise ValueError(f"session file must not be a symlink: {path}")
            item = self.load(path.stem)
            if item is not None:
                rows.append(item)
        return rows

    def build_context(
        self,
        session_id: str,
        *,
        branch_id: str = "main",
        current_question: str = "",
        turn_limit: int = 2,
        budget: int = 12_000,
    ) -> dict[str, Any]:
        session = self.load(session_id) or {
            "session_id": session_id,
            "messages": [],
            "working_memory": {},
        }
        messages = session.get("messages", [])
        memory = self.load_working_memory(session_id, branch_id=branch_id)
        # Keep this dependency lazy: deep_conversation remains usable without
        # importing the file-backed workspace during package initialization.
        from equipment_deep_research.domain.conversation import (
            branch_message_path,
            conversation_context_usage,
            living_transcript,
            normalize_branch_id,
            working_memory_prompt,
        )

        # A session transcript is complete, but a branch context must contain
        # only the requested branch ancestry.  Passing all messages here would
        # leak sibling explorations into the model window after a fork.
        branch_messages = branch_message_path(
            messages,
            normalize_branch_id(branch_id),
            session.get("checkpoints", [])
            if isinstance(session.get("checkpoints", []), Sequence)
            else [],
        )
        living = living_transcript(branch_messages, turn_limit=turn_limit)
        projected = working_memory_prompt(memory)
        usage = conversation_context_usage(
            messages=branch_messages,
            working_memory=memory,
            current_question=current_question,
            budget=budget,
        )
        durable_limit = min(12_000, max(1, int(budget or 12_000)))
        durable = self.workspace.memory.read_context(session_id=session_id, branch_id=branch_id, max_chars=durable_limit)
        return {
            "session_id": session_id,
            "branch_id": _text(branch_id, 160) or "main",
            "living_transcript": living,
            "working_memory": projected,
            "long_term_memory": durable[:durable_limit],
            "long_term_memory_truncated": len(durable) > durable_limit,
            "context_usage": usage,
            "transcript_count": (
                len(branch_messages) if isinstance(branch_messages, list) else 0
            ),
        }


# Explicit aliases make the boundary discoverable to callers that use the
# domain vocabulary rather than the implementation name.
ResearchWorkspace = DeepWorkspace
MemoryStore = DeepMemoryStore
SessionStore = DeepSessionStore

# Register the adapter at the composition boundary.  The domain workspace
# never imports this module, which keeps low-level secure file operations
# independent from the dialogue runtime.
register_deep_workspace_factory(DeepWorkspace.from_run_workspace)


__all__ = [
    "WORKSPACE_SCHEMA_VERSION",
    "MEMORY_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "DeepWorkspace",
    "DeepMemoryStore",
    "DeepSessionStore",
    "DreamBatch",
    "DreamResult",
    "WorkspaceManifest",
    "ResearchWorkspace",
    "MemoryStore",
    "SessionStore",
]
