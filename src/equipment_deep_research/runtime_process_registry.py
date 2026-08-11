from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
from threading import RLock
from time import monotonic, sleep
from typing import Iterator


_current_run_id: ContextVar[str] = ContextVar(
    "equipment_deep_research_current_run_id",
    default="",
)
_lock = RLock()
_process_groups: dict[str, set[int]] = {}
_registration_counts: dict[str, int] = {}
_process_group_hints: dict[tuple[str, int], str] = {}
_active_scopes: set[str] = set()


@dataclass
class RunProcessCleanup:
    run_id: str
    registered_count: int = 0
    orphan_count: int = 0
    terminated_count: int = 0
    forced_count: int = 0


@dataclass
class RunProcessScope:
    run_id: str
    cleanup: RunProcessCleanup | None = None


def current_run_id() -> str:
    scoped = _current_run_id.get().strip()
    if scoped:
        return scoped
    # A production Worker executes one research run at a time. Provider work
    # may move into a raw ThreadPoolExecutor whose contextvars are not copied;
    # the single active Worker scope remains an unambiguous fallback.
    with _lock:
        if len(_active_scopes) == 1:
            return next(iter(_active_scopes))
    return ""


def register_process_group(
    process_group_id: int,
    *,
    run_id: str = "",
    command_hint: str = "",
) -> None:
    owner = str(run_id or current_run_id()).strip()
    process_group_id = int(process_group_id)
    if not owner or process_group_id <= 1 or process_group_id == os.getpgrp():
        return
    with _lock:
        groups = _process_groups.setdefault(owner, set())
        if process_group_id not in groups:
            groups.add(process_group_id)
            _registration_counts[owner] = _registration_counts.get(owner, 0) + 1
        _process_group_hints[(owner, process_group_id)] = str(command_hint).strip()
    _write_registry_entry(owner, process_group_id, command_hint=command_hint)


def release_process_group(process_group_id: int, *, run_id: str = "") -> None:
    owner = str(run_id or current_run_id()).strip()
    process_group_id = int(process_group_id)
    if not owner:
        return
    with _lock:
        groups = _process_groups.get(owner)
        if groups is None:
            return
        groups.discard(process_group_id)
        _process_group_hints.pop((owner, process_group_id), None)
        if not groups:
            _process_groups.pop(owner, None)
    _remove_registry_entry(owner, process_group_id)


def terminate_run_process_groups(
    run_id: str,
    *,
    grace_seconds: float = 1.0,
) -> RunProcessCleanup:
    """Terminate every still-registered process group owned by one run.

    SIGTERM is broadcast to all groups first, so cleanup time is bounded by one
    shared grace window instead of multiplying by the number of parallel Codex
    calls. Survivors receive SIGKILL. The operation is idempotent and scoped to
    process groups explicitly registered by this Worker process.
    """

    owner = str(run_id or "").strip()
    with _lock:
        memory_groups = set(_process_groups.pop(owner, set()))
        memory_hints = {
            process_group_id: _process_group_hints.pop(
                (owner, process_group_id),
                "",
            )
            for process_group_id in memory_groups
        }
        registered_count = _registration_counts.pop(owner, 0)
    durable_groups = _read_registry_entries(owner)
    groups = tuple(sorted(memory_groups | set(durable_groups)))
    cleanup = RunProcessCleanup(
        run_id=owner,
        registered_count=registered_count,
        orphan_count=len(groups),
    )
    if not groups:
        return cleanup

    live_groups: set[int] = set()
    for process_group_id in groups:
        if process_group_id <= 1 or process_group_id == os.getpgrp():
            continue
        command_hint = memory_hints.get(
            process_group_id,
            str(durable_groups.get(process_group_id, {}).get("command_hint", "")),
        )
        if (
            process_group_id not in memory_groups
            and not _durable_group_matches(process_group_id, command_hint)
        ):
            _remove_registry_entry(owner, process_group_id)
            continue
        try:
            os.killpg(process_group_id, signal.SIGTERM)
            live_groups.add(process_group_id)
            cleanup.terminated_count += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            # Do not widen scope or attempt PID-based killing when ownership
            # cannot be established.
            continue
        finally:
            _remove_registry_entry(owner, process_group_id)

    deadline = monotonic() + max(0.0, float(grace_seconds))
    while live_groups and monotonic() < deadline:
        finished = {
            process_group_id
            for process_group_id in live_groups
            if not _process_group_exists(process_group_id)
        }
        live_groups.difference_update(finished)
        if live_groups:
            sleep(0.03)

    for process_group_id in live_groups:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
            cleanup.forced_count += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            continue
    return cleanup


@contextmanager
def task_process_scope(run_id: str) -> Iterator[RunProcessScope]:
    """Bind all provider subprocesses to a run and clean them on scope exit."""

    owner = str(run_id or "").strip()
    scope = RunProcessScope(run_id=owner)
    token = _current_run_id.set(owner)
    with _lock:
        _active_scopes.add(owner)
    try:
        yield scope
    finally:
        # This executes before ResearchWorker writes completed/failed, making
        # the terminal state mean the run no longer owns hidden model workers.
        scope.cleanup = terminate_run_process_groups(owner)
        with _lock:
            _active_scopes.discard(owner)
        _current_run_id.reset(token)


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _registry_root() -> Path | None:
    raw = os.environ.get("EQUIPMENT_DR_PROCESS_REGISTRY_ROOT", "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _safe_run_component(run_id: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(run_id)
    ).strip("-")[:128]


def _registry_path(run_id: str, process_group_id: int) -> Path | None:
    root = _registry_root()
    safe_run_id = _safe_run_component(run_id)
    if root is None or not safe_run_id:
        return None
    return root / safe_run_id / f"{int(process_group_id)}.json"


def _write_registry_entry(
    run_id: str,
    process_group_id: int,
    *,
    command_hint: str,
) -> None:
    path = _registry_path(run_id, process_group_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "process_group_id": int(process_group_id),
                    "worker_pid": os.getpid(),
                    "command_hint": str(command_hint).strip(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        return


def _remove_registry_entry(run_id: str, process_group_id: int) -> None:
    path = _registry_path(run_id, process_group_id)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        pass


def _read_registry_entries(run_id: str) -> dict[int, dict[str, object]]:
    root = _registry_root()
    safe_run_id = _safe_run_component(run_id)
    directory = root / safe_run_id if root is not None and safe_run_id else None
    if directory is None or not directory.is_dir():
        return {}
    entries: dict[int, dict[str, object]] = {}
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            process_group_id = int(payload.get("process_group_id", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if process_group_id > 1 and process_group_id != os.getpgrp():
            entries[process_group_id] = dict(payload)
    return entries


def _durable_group_matches(process_group_id: int, command_hint: str) -> bool:
    """Avoid killing a reused PGID when consuming a stale durable entry."""

    hint = Path(str(command_hint)).name.strip().lower()
    if not hint:
        return False
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pgid=,command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            row_group = int(parts[0])
        except ValueError:
            continue
        if row_group == process_group_id and hint in parts[1].lower():
            return True
    return False
