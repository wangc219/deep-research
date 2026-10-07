from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

from equipment_deep_research.application.factory import build_application_service
from equipment_deep_research.application.worker_pool_config import (
    ensure_worker_capacity_config,
    read_worker_capacity,
)
from equipment_deep_research.runtime_identity import (
    RUNTIME_BUILD_HASH,
    versioned_worker_id,
)


class ResearchWorkerPool:
    def __init__(
        self,
        *,
        project_root: Path,
        output_root: Path,
        database_url: str | None,
        initial_capacity: int,
        poll_interval: float = 0.5,
        runtime_generation: str = RUNTIME_BUILD_HASH,
    ) -> None:
        self.project_root = project_root.resolve()
        self.output_root = output_root.resolve()
        self.database_url = database_url
        self.initial_capacity = initial_capacity
        self.poll_interval = max(0.2, poll_interval)
        self.runtime_generation = str(runtime_generation)
        self.service = build_application_service(database_url)
        self.processes: dict[int, subprocess.Popen[bytes]] = {}
        self.stopping = False

    def run(self) -> int:
        ensure_worker_capacity_config(self.initial_capacity)
        while not self.stopping:
            self.reconcile()
            time.sleep(self.poll_interval)
        self.stop_all()
        return 0

    def reconcile(self) -> None:
        desired = read_worker_capacity(fallback=self.initial_capacity)
        for slot, process in list(self.processes.items()):
            if process.poll() is not None:
                self.processes.pop(slot, None)
                self._mark_stopped(slot)

        runtime_workers = self.service.runtime_health().get("workers", [])
        worker_states = {
            str(item.get("worker_id", "")): item
            for item in runtime_workers
        }
        internal_count = sum(
            bool(item.get("online"))
            and item.get("status") == "internal"
            and bool(item.get("current_run_id"))
            for item in runtime_workers
        )
        # Internal S6/finalization owners retain their run lease but no longer
        # count as research slots. Add one replacement process for each owner;
        # ordinary scale-down removes the replacement after the owner returns.
        target_processes = desired + internal_count
        if sum(bool(item.get("online")) for item in runtime_workers) > desired:
            self._reap_idle_stale_workers(worker_states)
        for slot in range(1, target_processes + 1):
            if slot not in self.processes:
                existing = worker_states.get(self._worker_id(slot), {})
                if existing.get("online") and existing.get("status") != "stopped":
                    # A prior supervisor may have terminated without taking its
                    # children down.  Do not launch another process with the
                    # same durable heartbeat identity: the newcomer would
                    # overwrite the live owner's lease and orphan recovery
                    # could then requeue an actively executing run.
                    continue
                self.processes[slot] = self._spawn(slot)

        for slot in sorted(
            (item for item in self.processes if item > target_processes),
            reverse=True,
        ):
            state = worker_states.get(self._worker_id(slot), {})
            if state.get("status") in {"working", "internal"} and state.get(
                "current_run_id"
            ):
                continue
            process = self.processes.pop(slot)
            self._terminate(process)
            self._mark_stopped(slot)

    def stop_all(self) -> None:
        for slot, process in sorted(self.processes.items(), reverse=True):
            self._terminate(process)
            self._mark_stopped(slot)
        self.processes.clear()

    def _spawn(self, slot: int) -> subprocess.Popen[bytes]:
        command = [
            sys.executable,
            "-m",
            "equipment_deep_research.interfaces.worker",
            "--project-root",
            str(self.project_root),
            "--output-root",
            str(self.output_root),
            "--worker-id",
            self._worker_id(slot),
            "--runtime-generation",
            self.runtime_generation,
            "--poll-interval",
            "1",
            "--max-idle-poll-interval",
            "5",
        ]
        if slot > 1:
            command.append("--disable-orphan-recovery")
        process = subprocess.Popen(
            command,
            cwd=self.project_root,
            env={
                **os.environ.copy(),
                "EQUIPMENT_DR_BUILD_HASH": self.runtime_generation,
            },
            start_new_session=True,
        )
        print(f"研究槽位 #{slot} 已启动（PID {process.pid}）", flush=True)
        return process

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)

    def _mark_stopped(self, slot: int) -> None:
        self._mark_worker_stopped(self._worker_id(slot))

    def _mark_worker_stopped(self, worker_id: str) -> None:
        try:
            self.service.touch_worker(worker_id, status="stopped")
        except Exception:
            pass

    def _reap_idle_stale_workers(
        self,
        worker_states: dict[str, dict[str, object]],
    ) -> None:
        """Stop orphaned Workers from an older runtime generation.

        A previous local supervisor can terminate without taking its Worker
        children down.  Those processes keep fresh heartbeats, so the API
        counts them as real slots even though the current pool cannot shrink
        them through ``self.processes``.  Only exact same-project Worker
        commands are considered, and a Worker holding a run is never stopped.
        """

        current_suffix = f"@{self.runtime_generation[:12]}"
        for process in self._local_worker_processes():
            raw_worker_id = str(process.get("worker_id", ""))
            generation = str(process.get("runtime_generation", ""))
            if generation == self.runtime_generation or raw_worker_id.endswith(
                current_suffix
            ):
                continue

            candidate_ids = [raw_worker_id]
            if generation:
                candidate_ids.insert(0, versioned_worker_id(raw_worker_id, generation))
            else:
                candidate_ids.append(
                    versioned_worker_id(raw_worker_id, self.runtime_generation)
                )
            state_id = next(
                (
                    worker_id
                    for worker_id in candidate_ids
                    if worker_id in worker_states
                    and bool(worker_states[worker_id].get("online"))
                ),
                "",
            )
            if not state_id or state_id.endswith(current_suffix):
                continue
            state = worker_states[state_id]
            if state.get("status") == "working" and state.get("current_run_id"):
                continue

            self._terminate_external_worker(
                int(process["pid"]),
                int(process["pgid"]),
            )
            self._mark_worker_stopped(state_id)

    def _local_worker_processes(self) -> list[dict[str, object]]:
        """Return scoped Worker processes without matching unrelated Python jobs."""

        try:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,pgid=,command="],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return []
        if completed.returncode != 0:
            return []

        rows: list[dict[str, object]] = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) != 3:
                continue
            try:
                pid, pgid = int(parts[0]), int(parts[1])
                command = shlex.split(parts[2])
            except (ValueError, TypeError):
                continue
            if pid <= 1 or pid == os.getpid():
                continue
            if not _runs_worker_module(command):
                continue
            # ``ps`` renders argv as plain text and does not preserve the
            # quoting around paths containing spaces.  Consume path values up
            # to the next option so a workspace such as ``equipment research``
            # can still be matched to its orphaned Workers.
            project_root = _command_option(
                command,
                "--project-root",
                consume_until_option=True,
            )
            output_root = _command_option(
                command,
                "--output-root",
                consume_until_option=True,
            )
            worker_id = _command_option(command, "--worker-id")
            if not project_root or not output_root or not worker_id:
                continue
            try:
                same_project = Path(project_root).resolve() == self.project_root
                same_output = Path(output_root).resolve() == self.output_root
            except OSError:
                continue
            if not same_project or not same_output:
                continue
            rows.append(
                {
                    "pid": pid,
                    "pgid": pgid,
                    "worker_id": worker_id,
                    "runtime_generation": _command_option(
                        command,
                        "--runtime-generation",
                    ),
                }
            )
        return rows

    def _terminate_external_worker(self, pid: int, pgid: int) -> None:
        del pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def _worker_id(self, slot: int) -> str:
        return versioned_worker_id(
            f"research-worker-{slot}", self.runtime_generation
        )


def _command_option(
    command: list[str],
    option: str,
    *,
    consume_until_option: bool = False,
) -> str:
    try:
        value_start = command.index(option) + 1
    except (ValueError, IndexError):
        return ""
    if value_start >= len(command):
        return ""
    if not consume_until_option:
        return command[value_start]
    value_end = next(
        (
            index
            for index in range(value_start + 1, len(command))
            if command[index].startswith("--")
        ),
        len(command),
    )
    return " ".join(command[value_start:value_end])


def _runs_worker_module(command: list[str]) -> bool:
    return any(
        command[index : index + 2]
        == ["-m", "equipment_deep_research.interfaces.worker"]
        for index in range(max(0, len(command) - 1))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervise a dynamically sized research Worker pool.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--output-root", default="outputs/runs")
    parser.add_argument("--initial-capacity", type=int, default=2)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    args = parser.parse_args(argv)
    pool = ResearchWorkerPool(
        project_root=Path(args.project_root),
        output_root=Path(args.output_root),
        database_url=args.database_url,
        initial_capacity=args.initial_capacity,
        poll_interval=args.poll_interval,
    )

    def request_stop(_signum: int, _frame: object) -> None:
        pool.stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return pool.run()


if __name__ == "__main__":
    raise SystemExit(main())
