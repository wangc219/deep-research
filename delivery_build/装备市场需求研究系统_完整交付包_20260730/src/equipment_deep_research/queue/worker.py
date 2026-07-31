from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable

from sqlalchemy.exc import NoResultFound

from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.delivery.exporter import DeliveryExporter


@dataclass(frozen=True)
class WorkerOutcome:
    run_id: str
    status: str
    error: str = ""


class ResearchWorker:
    def __init__(
        self,
        *,
        service: ResearchApplicationService,
        execute: Callable[[str], dict[str, Any] | None],
        worker_id: str = "research-worker",
        heartbeat_interval_seconds: float = 5.0,
    ) -> None:
        self.service, self.execute, self.worker_id = service, execute, worker_id
        self.heartbeat_interval_seconds = max(0.01, heartbeat_interval_seconds)

    def _ack(self, run_id: str) -> None:
        ack = getattr(self.service.queue, "ack", None)
        if callable(ack):
            ack(run_id)

    @staticmethod
    def _has_complete_delivery(view: Any) -> bool:
        result = getattr(view, "result", {}) or {}
        if result.get("status") != "completed" or result.get("audit_status") != "approved":
            return False
        report_path = str(result.get("report_path", "")).strip()
        return bool(report_path and Path(report_path).is_file())

    def run_once(self) -> WorkerOutcome | None:
        self.service.touch_worker(self.worker_id, status="idle")
        run_id = self.service.queue.claim()
        if run_id is None:
            return None
        try:
            get_run = getattr(self.service, "get_run", None)
            current = get_run(run_id) if callable(get_run) else None
            if current is not None and self._has_complete_delivery(current):
                prior_status = current.status
                self.service.set_result(run_id, current.result)
                self.service.set_status(run_id, "completed")
                self.service.publish_runtime_event(
                    run_id,
                    "run_completion_reconciled",
                    {"prior_status": prior_status, "reason": "complete_delivery_exists"},
                )
                self._ack(run_id)
                self.service.touch_worker(self.worker_id, status="idle")
                return WorkerOutcome(run_id, "completed")
            if current is not None and current.status in {"completed", "cancelled", "archived"}:
                self._ack(run_id)
                self.service.touch_worker(self.worker_id, status="idle")
                return WorkerOutcome(run_id, current.status)
            runtime_health = getattr(self.service, "runtime_health", None)
            health = runtime_health() if callable(runtime_health) else {}
            owned_elsewhere = any(
                worker.get("online")
                and worker.get("current_run_id") == run_id
                and worker.get("worker_id") != self.worker_id
                for worker in health.get("workers", [])
            )
            if owned_elsewhere:
                self._ack(run_id)
                self.service.touch_worker(self.worker_id, status="idle")
                return WorkerOutcome(run_id, "already_active")
            self.service.touch_worker(self.worker_id, status="working", current_run_id=run_id)
            self.service.set_status(run_id, "planning")
        except (KeyError, NoResultFound):
            # The run may be deleted after queue claim but before it becomes active.
            self._ack(run_id)
            self.service.touch_worker(self.worker_id, status="idle")
            return WorkerOutcome(run_id, "deleted")
        try:
            self.service.set_status(run_id, "researching")
            with self._heartbeat_during(run_id):
                result = self.execute(run_id) or {}
            run_dir = result.get("run_dir")
            if run_dir:
                manifest = DeliveryExporter().build_manifest(run_dir)
                result = {
                    **result,
                    "manifest_path": f"{run_dir}/delivery-manifest.json",
                    "manifest_file_count": manifest["file_count"],
                }
            self.service.set_result(run_id, result)
            self.service.set_status(run_id, "completed")
            self._ack(run_id)
            self.service.touch_worker(self.worker_id, status="idle")
            return WorkerOutcome(run_id, "completed")
        except (Exception, asyncio.CancelledError) as exc:
            error = str(exc).strip() or type(exc).__name__
            current = self.service.get_run(run_id)
            if self._has_complete_delivery(current):
                self.service.set_result(run_id, current.result)
                self.service.set_status(run_id, "completed")
                self.service.publish_runtime_event(
                    run_id,
                    "run_completion_reconciled",
                    {"ignored_late_error": error},
                )
                self._ack(run_id)
                self.service.touch_worker(self.worker_id, status="idle")
                return WorkerOutcome(run_id, "completed")
            self.service.set_error(run_id, error)
            self.service.set_status(run_id, "failed")
            self._ack(run_id)
            self.service.touch_worker(self.worker_id, status="idle")
            return WorkerOutcome(run_id, "failed", error)

    @contextmanager
    def _heartbeat_during(self, run_id: str):
        stopped = Event()

        def pulse() -> None:
            while not stopped.wait(self.heartbeat_interval_seconds):
                try:
                    self.service.touch_worker(
                        self.worker_id,
                        status="working",
                        current_run_id=run_id,
                    )
                except Exception:
                    # SQLite contention and other transient persistence errors
                    # must not permanently stop the lease heartbeat.
                    continue

        thread = Thread(target=pulse, name=f"{self.worker_id}-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1.0)
