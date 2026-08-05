"""Framework-independent run lifecycle and in-process development queue."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
from threading import Lock

from equipment_deep_research.application.dto import CreateRunCommand, RunView, UpdateRunCommand
from equipment_deep_research.domain.models import new_stable_id, now_iso


class InvalidRunTransition(ValueError):
    pass


PERMANENTLY_DELETABLE_STATUSES = frozenset(
    {"draft", "queued", "completed", "failed", "cancelled", "archived"}
)


class InProcessRunQueue:
    def __init__(self) -> None:
        self._pending: list[str] = []
        self._lock = Lock()

    def enqueue(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._pending:
                self._pending.append(run_id)

    def claim(self) -> str | None:
        with self._lock:
            return self._pending.pop(0) if self._pending else None

    def pending_run_ids(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._pending = [item for item in self._pending if item != run_id]


def _configured_worker_concurrency() -> int:
    raw_value = os.environ.get("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "2")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 1
    return min(8, max(1, value))


def _configured_worker_stale_after_seconds() -> int:
    raw_value = os.environ.get("EQUIPMENT_DR_WORKER_STALE_AFTER_SECONDS", "60")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 60
    return max(30, value)


class ResearchApplicationService:
    def __init__(self, *, queue: InProcessRunQueue | None = None, repository: object | None = None) -> None:
        self.queue = queue or InProcessRunQueue()
        self.repository = repository
        self._runs: dict[str, RunView] = {}
        self._idempotency: dict[tuple[str, str], RunView] = {}

    def create_run(self, command: CreateRunCommand) -> RunView:
        if not command.topic.strip() or command.max_rounds < 1 or command.max_rounds > 5:
            raise ValueError("topic is required and max_rounds must be 1..5")
        view = RunView(
            new_stable_id("run"),
            command.topic,
            command.research_route,
            list(command.selected_agent_ids),
            command.max_rounds,
            command.created_by,
            execution=dict(command.execution),
            analyst_confirmed=command.analyst_confirmed,
            interaction_mode=command.interaction_mode,
            discovery_branch=command.discovery_branch,
            execution_profile_id=command.execution_profile_id,
            report_template_mode=command.report_template_mode,
            supplemental_information=command.supplemental_information.strip(),
        )
        self._runs[view.run_id] = view
        self._save(view)
        self._event(view.run_id, "run_created", {"status": view.status, "actor": command.created_by})
        return view

    def get_run(self, run_id: str) -> RunView:
        if self.repository is not None:
            view = self.repository.get(run_id)
            self._runs[run_id] = view
            return view
        if run_id in self._runs:
            return self._runs[run_id]
        raise KeyError(run_id)

    def list_runs(self) -> list[RunView]:
        if self.repository is not None:
            return self.repository.list()
        return sorted(self._runs.values(), key=lambda item: item.updated_at, reverse=True)

    def update_run(
        self,
        run_id: str,
        command: UpdateRunCommand,
        *,
        actor: str,
    ) -> RunView:
        current = self.get_run(run_id)
        if current.status != "draft":
            raise InvalidRunTransition(f"{current.status} cannot transition to updated draft")
        if not command.topic.strip() or command.max_rounds < 1 or command.max_rounds > 5:
            raise ValueError("topic is required and max_rounds must be 1..5")
        updated = replace(
            current,
            topic=command.topic.strip(),
            research_route=command.research_route,
            selected_agent_ids=list(command.selected_agent_ids),
            max_rounds=command.max_rounds,
            execution=dict(command.execution),
            analyst_confirmed=command.analyst_confirmed,
            interaction_mode=command.interaction_mode,
            discovery_branch=command.discovery_branch,
            execution_profile_id=command.execution_profile_id,
            report_template_mode=(
                command.report_template_mode or current.report_template_mode
            ),
            supplemental_information=(
                current.supplemental_information
                if command.supplemental_information is None
                else command.supplemental_information.strip()
            ),
            updated_at=now_iso(),
        )
        self._runs[run_id] = updated
        self._save(updated)
        self._event(
            run_id,
            "run_updated",
            {
                "actor": actor,
                "research_route": updated.research_route,
                "selected_agent_ids": updated.selected_agent_ids,
                "max_rounds": updated.max_rounds,
                "execution": {
                    key: value
                    for key, value in updated.execution.items()
                    if key != "api_key"
                },
                "analyst_confirmed": updated.analyst_confirmed,
                "interaction_mode": updated.interaction_mode,
                "discovery_branch": updated.discovery_branch,
                "execution_profile_id": updated.execution_profile_id,
                "report_template_mode": updated.report_template_mode,
                "supplemental_information_present": bool(
                    updated.supplemental_information
                ),
            },
        )
        return updated

    def archive_run(self, run_id: str, *, actor: str) -> RunView:
        current = self.get_run(run_id)
        if current.status not in {"draft", "completed", "failed", "cancelled"}:
            raise InvalidRunTransition(f"{current.status} cannot transition to archived")
        updated = replace(current, status="archived", updated_at=now_iso())
        self._runs[run_id] = updated
        self._save(updated)
        self._event(run_id, "run_archived", {"actor": actor, "prior_status": current.status})
        return updated

    def delete_run(self, run_id: str, *, allow_active: bool = False) -> RunView:
        current = self.get_run(run_id)
        if current.status not in PERMANENTLY_DELETABLE_STATUSES and not allow_active:
            raise InvalidRunTransition(f"{current.status} cannot be permanently deleted")
        remove = getattr(self.repository, "delete_run", None)
        if callable(remove):
            remove(run_id)
        self._runs.pop(run_id, None)
        self._idempotency = {
            key: value for key, value in self._idempotency.items() if key[0] != run_id
        }
        remove_pending = getattr(self.queue, "remove", None)
        if callable(remove_pending):
            remove_pending(run_id)
        return current

    def start_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"draft", "paused"}, "queued", enqueue=True)

    def pause_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"queued", "planning", "researching", "recalling"}, "pause_requested")

    def resume_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(
            run_id,
            actor,
            idempotency_key,
            {"paused", "failed"},
            "queued",
            enqueue=True,
            clear_error=True,
        )

    def cancel_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"draft", "queued", "planning", "researching", "paused", "recalling"}, "cancel_requested")

    def _command(
        self,
        run_id: str,
        actor: str,
        key: str,
        allowed: set[str],
        next_status: str,
        *,
        enqueue: bool = False,
        clear_error: bool = False,
    ) -> RunView:
        if (run_id, key) in self._idempotency:
            return self._idempotency[(run_id, key)]
        current = self.get_run(run_id)
        if current.status not in allowed:
            raise InvalidRunTransition(f"{current.status} cannot transition to {next_status}")
        updated = replace(
            current,
            status=next_status,
            error="" if clear_error else current.error,
            updated_at=now_iso(),
        )
        self._runs[run_id] = updated
        self._save(updated)
        self._idempotency[(run_id, key)] = updated
        if enqueue:
            self.queue.enqueue(run_id)
        self._event(run_id, "run_status_changed", {"status": next_status, "actor": actor})
        return updated

    def set_status(self, run_id: str, status: str) -> RunView:
        updated = replace(self.get_run(run_id), status=status, updated_at=now_iso())
        self._runs[run_id] = updated
        self._save(updated)
        self._event(run_id, "run_status_changed", {"status": status})
        return updated

    def set_result(self, run_id: str, result: dict) -> RunView:
        updated = replace(self.get_run(run_id), result=dict(result), error="", updated_at=now_iso())
        self._runs[run_id] = updated
        self._save(updated)
        self._event(run_id, "run_result_saved", {"result": dict(result)})
        return updated

    def recover_orphaned_runs(self, *, stale_after_seconds: int | None = None) -> list[str]:
        """Requeue active runs that are no longer owned by an online worker."""
        stale_after_seconds = (
            _configured_worker_stale_after_seconds()
            if stale_after_seconds is None
            else max(0, stale_after_seconds)
        )
        now = datetime.now(timezone.utc)
        recovered: list[str] = []
        for view in self.list_runs():
            if view.status not in {"planning", "researching", "recalling"}:
                continue
            try:
                age = max(
                    0.0,
                    (now - datetime.fromisoformat(view.updated_at)).total_seconds(),
                )
            except (TypeError, ValueError):
                age = float("inf")
            if age <= stale_after_seconds:
                continue
            # Re-read both task and worker state immediately before requeueing.
            # This closes the startup race where another worker claims the task
            # after the first recovery snapshot was taken.
            current = self.get_run(view.run_id)
            if current.status not in {"planning", "researching", "recalling"}:
                continue
            try:
                current_age = max(
                    0.0,
                    (datetime.now(timezone.utc) - datetime.fromisoformat(current.updated_at)).total_seconds(),
                )
            except (TypeError, ValueError):
                current_age = float("inf")
            active_run_ids = {
                str(worker.get("current_run_id", ""))
                for worker in self.runtime_health(
                    stale_after_seconds=stale_after_seconds
                ).get("workers", [])
                if worker.get("online") and worker.get("current_run_id")
            }
            if (
                current_age <= stale_after_seconds
                or view.run_id in active_run_ids
                or view.run_id in set(self.queue.pending_run_ids())
            ):
                continue
            retry = getattr(self.queue, "retry", None)
            if callable(retry):
                retry(view.run_id)
            else:
                self.queue.enqueue(view.run_id)
            self.set_status(view.run_id, "queued")
            self.publish_runtime_event(
                view.run_id,
                "run_recovered",
                {
                    "prior_status": current.status,
                    "status": "queued",
                    "reason": "worker_interrupted",
                },
            )
            recovered.append(view.run_id)
        return recovered

    def set_error(self, run_id: str, error: str) -> RunView:
        updated = replace(self.get_run(run_id), error=error, updated_at=now_iso())
        self._runs[run_id] = updated
        self._save(updated)
        self._event(run_id, "run_failed", {"error": error})
        return updated

    def publish_runtime_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        self._event(run_id, event_type, payload)

    def touch_worker(self, worker_id: str, *, status: str, current_run_id: str = "") -> None:
        touch = getattr(self.repository, "touch_worker", None)
        if callable(touch):
            touch(worker_id, updated_at=now_iso(), status=status, current_run_id=current_run_id)

    def runtime_health(self, *, stale_after_seconds: int | None = None) -> dict:
        stale_after_seconds = (
            _configured_worker_stale_after_seconds()
            if stale_after_seconds is None
            else max(0, stale_after_seconds)
        )
        rows = []
        load = getattr(self.repository, "worker_heartbeats", None)
        if callable(load):
            rows = load()
        now = datetime.now(timezone.utc)
        active = []
        for row in rows:
            try:
                age = max(0.0, (now - datetime.fromisoformat(row["updated_at"])).total_seconds())
            except (KeyError, TypeError, ValueError):
                age = float("inf")
            active.append({**row, "age_seconds": round(age, 1), "online": age <= stale_after_seconds})
        online_workers = [item for item in active if item["online"]]
        online_workers.sort(key=lambda item: str(item.get("worker_id", "")))
        for slot_index, worker in enumerate(online_workers, start=1):
            worker["slot_index"] = slot_index
        active_workers = [
            item
            for item in online_workers
            if item.get("status") == "working" and item.get("current_run_id")
        ]
        configured_capacity = _configured_worker_concurrency()
        worker_capacity = len(online_workers)
        pending = self.queue.pending_run_ids()
        return {
            "status": "ready" if online_workers else "degraded",
            "worker_online": bool(online_workers),
            "workers": active,
            "configured_worker_capacity": configured_capacity,
            "worker_capacity": worker_capacity,
            "online_worker_count": len(online_workers),
            "active_count": len(active_workers),
            "idle_count": sum(item.get("status") == "idle" for item in online_workers),
            "available_slots": max(0, len(online_workers) - len(active_workers)),
            "parallel_enabled": len(online_workers) > 1,
            "utilization_percent": round(
                len(active_workers) / worker_capacity * 100,
                1,
            ) if worker_capacity else 0.0,
            "active_run_ids": [str(item["current_run_id"]) for item in active_workers],
            "pending_count": len(pending),
            "pending_run_ids": pending,
        }

    def _save(self, view: RunView) -> None:
        if self.repository is not None:
            self.repository.save(view)

    def _event(self, run_id: str, event_type: str, payload: dict) -> None:
        append = getattr(self.repository, "append_event", None)
        if callable(append):
            append(run_id, event_type, payload)
