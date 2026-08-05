from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import contextmanager
import os
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
        self._transient_resume_attempts: dict[str, int] = {}

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
            transient_resume_limit = _configured_transient_resume_limit()
            transient_resume_count = self._transient_resume_count(run_id)
            if (
                transient_resume_count < transient_resume_limit
                and _is_transient_checkpoint_failure(error)
            ):
                attempt = transient_resume_count + 1
                self._transient_resume_attempts[run_id] = attempt
                self.service.publish_runtime_event(
                    run_id,
                    "run_transient_resume_scheduled",
                    {
                        "attempt": attempt,
                        "maximum_attempts": transient_resume_limit,
                        "reason": "retryable_provider_or_network_failure",
                        "error": error,
                        "resume_mode": "checkpoint_pending_tasks_only",
                    },
                )
                self.service.set_status(run_id, "queued")
                self._ack(run_id)
                retry = getattr(self.service.queue, "retry", None)
                if callable(retry):
                    retry(run_id)
                else:
                    self.service.queue.enqueue(run_id)
                self.service.touch_worker(self.worker_id, status="idle")
                return WorkerOutcome(run_id, "queued", error)
            self.service.set_error(run_id, error)
            self.service.set_status(run_id, "failed")
            self._ack(run_id)
            self.service.touch_worker(self.worker_id, status="idle")
            return WorkerOutcome(run_id, "failed", error)

    def _transient_resume_count(self, run_id: str) -> int:
        durable_count = 0
        repository = getattr(self.service, "repository", None)
        events_after = getattr(repository, "events_after", None)
        if callable(events_after):
            try:
                durable_count = sum(
                    row.get("event_type") == "run_transient_resume_scheduled"
                    for row in events_after(run_id, 0)
                )
            except Exception:
                durable_count = 0
        return max(
            durable_count,
            self._transient_resume_attempts.get(run_id, 0),
        )

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


def _configured_transient_resume_limit() -> int:
    raw_value = os.environ.get("EQUIPMENT_DR_TRANSIENT_RESUME_ATTEMPTS", "1")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 1
    return min(3, max(0, value))


def _is_transient_checkpoint_failure(error: str) -> bool:
    normalized = str(error or "").lower()
    return any(
        signal in normalized
        for signal in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "network",
            "temporarily unavailable",
            "timed out",
            "request timeout",
            "read timeout",
            "connect timeout",
            "stream disconnected",
            "upstream",
            "internal server error",
            "response failed",
        )
    )
