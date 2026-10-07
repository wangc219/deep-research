from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from equipment_deep_research.providers.codex import CodexCliProvider
from equipment_deep_research.runtime_process_registry import (
    register_process_group,
    release_process_group,
    task_process_scope,
    terminate_run_process_groups,
)


def _wait_until_gone(process_id: int, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.03)
    return False


def test_task_process_scope_terminates_registered_orphan_before_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(tmp_path / "registry"),
    )
    process = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        with task_process_scope("run-scope-cleanup") as scope:
            register_process_group(process.pid, command_hint="sleep")

        process.wait(timeout=3)
        assert scope.cleanup is not None
        assert scope.cleanup.registered_count == 1
        assert scope.cleanup.orphan_count == 1
        assert scope.cleanup.terminated_count == 1
        assert not (tmp_path / "registry" / "run-scope-cleanup").exists()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def test_released_process_group_is_not_killed_by_terminal_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(tmp_path / "registry"),
    )
    process = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    try:
        with task_process_scope("run-normal-release") as scope:
            register_process_group(process.pid, command_hint="sleep")
            release_process_group(process.pid)

        assert scope.cleanup is not None
        assert scope.cleanup.registered_count == 1
        assert scope.cleanup.orphan_count == 0
        assert process.poll() is None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def test_durable_registry_allows_replacement_worker_to_kill_crash_orphan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "registry"
    pid_path = tmp_path / "orphan.pid"
    monkeypatch.setenv("EQUIPMENT_DR_PROCESS_REGISTRY_ROOT", str(registry_root))
    helper = (
        "import pathlib, subprocess, sys; "
        "from equipment_deep_research.runtime_process_registry import register_process_group; "
        "child=subprocess.Popen(['/bin/sleep','60'], start_new_session=True, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "register_process_group(child.pid, run_id='run-crashed-worker', command_hint='sleep'); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", helper, str(pid_path)],
        cwd=Path(__file__).resolve().parents[3],
        env={
            **os.environ,
            "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT": str(registry_root),
            "PYTHONPATH": os.pathsep.join(
                filter(
                    None,
                    [
                        str(Path(__file__).resolve().parents[3] / "src"),
                        os.environ.get("PYTHONPATH", ""),
                    ],
                )
            ),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    orphan_pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        cleanup = terminate_run_process_groups("run-crashed-worker")

        assert cleanup.orphan_count == 1
        assert cleanup.terminated_count == 1
        assert _wait_until_gone(orphan_pid)
        assert not (registry_root / "run-crashed-worker").exists()
    finally:
        try:
            os.killpg(orphan_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_codex_provider_releases_global_task_registration_on_normal_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(tmp_path / "registry"),
    )
    provider = CodexCliProvider(
        command=sys.executable,
        workspace_path=tmp_path,
        include_default_skills=False,
    )

    with task_process_scope("run-provider-normal") as scope:
        result = asyncio.run(
            provider._execute_async(
                [sys.executable, "-c", "print('done')"],
                "",
                timeout_seconds=5,
            )
        )

    assert result.returncode == 0
    assert scope.cleanup is not None
    assert scope.cleanup.registered_count == 1
    assert scope.cleanup.orphan_count == 0
