from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from equipment_deep_research.application.factory import build_application_service
from equipment_deep_research.application.worker_pool_config import (
    ensure_worker_capacity_config,
    read_worker_capacity,
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
    ) -> None:
        self.project_root = project_root.resolve()
        self.output_root = output_root.resolve()
        self.database_url = database_url
        self.initial_capacity = initial_capacity
        self.poll_interval = max(0.2, poll_interval)
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

        for slot in range(1, desired + 1):
            if slot not in self.processes:
                self.processes[slot] = self._spawn(slot)

        worker_states = {
            str(item.get("worker_id", "")): item
            for item in self.service.runtime_health().get("workers", [])
        }
        for slot in sorted(
            (item for item in self.processes if item > desired),
            reverse=True,
        ):
            state = worker_states.get(self._worker_id(slot), {})
            if state.get("status") == "working" and state.get("current_run_id"):
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
            env=os.environ.copy(),
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
        try:
            self.service.touch_worker(self._worker_id(slot), status="stopped")
        except Exception:
            pass

    @staticmethod
    def _worker_id(slot: int) -> str:
        return f"research-worker-{slot}"


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
