"""Framework-independent run lifecycle and in-process development queue."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
from threading import Lock

from sqlalchemy.exc import NoResultFound

from equipment_deep_research.application.dto import CreateRunCommand, RunView, UpdateRunCommand
from equipment_deep_research.application.worker_pool_config import read_worker_capacity
from equipment_deep_research.domain.models import new_stable_id, now_iso
from equipment_deep_research.runtime_identity import RUNTIME_BUILD_HASH
from equipment_deep_research.runtime_process_registry import (
    terminate_run_process_groups,
)


class InvalidRunTransition(ValueError):
    pass


class RunNotFoundError(KeyError):
    """Raised when a requested research run no longer exists."""


PERMANENTLY_DELETABLE_STATUSES = frozenset(
    {"draft", "queued", "completed", "failed", "cancelled", "archived"}
)

# Every user-facing phase that can be left behind by an interrupted Worker.
# Keep this aligned with interfaces.worker.runtime_status_for_event(): later
# orchestration milestones replace ``researching`` with these more precise
# phases, but the run still needs the same orphan-recovery treatment.
ACTIVE_RUN_STATUSES = frozenset(
    {
        "planning",
        "researching",
        "recalling",
        "synthesizing",
        "reviewing",
        "reporting",
    }
)


class InProcessRunQueue:
    def __init__(self, *, generation: str = RUNTIME_BUILD_HASH) -> None:
        self._pending: list[str] = []
        self._lock = Lock()
        self.generation = str(generation)

    def enqueue(self, run_id: str, *, allow_claimed: bool = False) -> None:
        with self._lock:
            if run_id not in self._pending:
                self._pending.append(run_id)

    def claim(self, *, generation: str | None = None) -> str | None:
        if generation is not None and str(generation) != self.generation:
            return None
        with self._lock:
            return self._pending.pop(0) if self._pending else None

    def pending_run_ids(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._pending = [item for item in self._pending if item != run_id]


def _configured_worker_concurrency() -> int:
    return read_worker_capacity()


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
            try:
                view = self.repository.get(run_id)
            except NoResultFound as exc:
                raise RunNotFoundError(run_id) from exc
            self._runs[run_id] = view
            return view
        if run_id in self._runs:
            return self._runs[run_id]
        raise RunNotFoundError(run_id)

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

    def resume_run(
        self,
        run_id: str,
        *,
        actor: str,
        idempotency_key: str,
        execution: dict | None = None,
    ) -> RunView:
        current = self.get_run(run_id)
        # A stale UI can issue Resume while the previous Worker is still
        # alive.  Do not enqueue a second execution in that window; the
        # existing Worker owns the checkpoint and will either finish or fail
        # with a recoverable savepoint.
        active_run_ids = {
            str(worker.get("current_run_id", ""))
            for worker in self.runtime_health().get("workers", [])
            if worker.get("online") and worker.get("current_run_id")
        }
        if run_id in active_run_ids:
            raise InvalidRunTransition("run is already executing; duplicate resume was ignored")
        resumable_completed_delivery = (
            current.status == "completed"
            and str(current.result.get("audit_status", "")).strip().lower()
            not in {"approved", "passed"}
        )
        allowed_statuses = {"paused", "failed"}
        if resumable_completed_delivery:
            allowed_statuses.add("completed")
        if current.status not in allowed_statuses:
            raise InvalidRunTransition(
                f"{current.status} cannot transition to queued"
            )
        refreshed_execution = dict(execution or current.execution)
        if refreshed_execution != current.execution:
            updated = replace(
                current,
                execution=refreshed_execution,
                updated_at=now_iso(),
            )
            self._runs[run_id] = updated
            self._save(updated)
            self._event(
                run_id,
                "run_resume_execution_refreshed",
                {
                    "actor": actor,
                    "provider": refreshed_execution.get("provider", ""),
                    "model": refreshed_execution.get("model", ""),
                    "base_url": refreshed_execution.get("base_url", ""),
                    "api_key_env": refreshed_execution.get("api_key_env", ""),
                    "agent_model_count": len(
                        refreshed_execution.get("agent_models", {})
                    ),
                },
            )
        return self._command(
            run_id,
            actor,
            idempotency_key,
            allowed_statuses,
            "queued",
            enqueue=True,
            clear_error=True,
            allow_claimed_enqueue=True,
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
        allow_claimed_enqueue: bool = False,
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
            try:
                self.queue.enqueue(run_id, allow_claimed=allow_claimed_enqueue)
            except TypeError:
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
        """Stop orphaned active runs and require an explicit user resume."""
        stale_after_seconds = (
            _configured_worker_stale_after_seconds()
            if stale_after_seconds is None
            else max(0, stale_after_seconds)
        )
        now = datetime.now(timezone.utc)
        recovered: list[str] = []
        for view in self.list_runs():
            if view.status not in ACTIVE_RUN_STATUSES:
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
            if current.status not in ACTIVE_RUN_STATUSES:
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
            # Include the last durable dynamic-session identity when the
            # orphan reaper has to intervene.  This turns a vague "Worker
            # interrupted" card into an actionable checkpoint without
            # guessing whether the CLI process itself failed.
            stuck_detail = ""
            events_after = getattr(self.repository, "events_after", None)
            if callable(events_after):
                try:
                    recent_events = events_after(view.run_id, 0)
                    for recent in reversed(recent_events):
                        if recent.get("event_type") not in {
                            "winning_agent_session_started",
                            "winning_agent_waiting",
                        }:
                            continue
                        raw_payload = recent.get("payload", {})
                        event_payload = (
                            raw_payload.get("event", raw_payload)
                            if isinstance(raw_payload, dict)
                            else {}
                        )
                        details = (
                            event_payload.get("payload", event_payload)
                            if isinstance(event_payload, dict)
                            else {}
                        )
                        running_instances = details.get("running_instances", [])
                        waiting_actor = ""
                        waiting_node = ""
                        if isinstance(running_instances, list) and running_instances:
                            first_running = running_instances[0]
                            if isinstance(first_running, dict):
                                waiting_actor = str(
                                    first_running.get("agent_instance_id", "")
                                ).strip()
                                waiting_node = str(
                                    first_running.get("mission_node", "")
                                ).strip()
                        actor = str(
                            waiting_actor
                            or details.get("agent_instance_id")
                            or event_payload.get("actor")
                            or ""
                        ).strip()
                        node = str(
                            waiting_node
                            or details.get("mission_node")
                            or details.get("merge_target")
                            or ""
                        ).strip()
                        if actor and actor != "winning_swarm_controller":
                            stuck_detail = (
                                f"（最后活动实例：{actor}"
                                + (f"，节点 {node}" if node else "")
                                + "）"
                            )
                            break
                except Exception:
                    stuck_detail = ""
            error = (
                "执行 Worker 已中断，检查点已保留"
                + stuck_detail
                + "；请人工点击“从断点继续”，系统不会自动恢复。"
            )
            cleanup = terminate_run_process_groups(view.run_id)
            self.publish_runtime_event(
                view.run_id,
                "run_orphan_process_cleanup",
                {
                    "terminal_status": "failed",
                    "reason": "stale_worker_recovery",
                    "registered_process_groups": cleanup.registered_count,
                    "orphan_process_groups": cleanup.orphan_count,
                    "terminated_process_groups": cleanup.terminated_count,
                    "forced_process_groups": cleanup.forced_count,
                    "status": "released",
                },
            )
            self.set_error(view.run_id, error)
            self.set_status(view.run_id, "failed")
            self.publish_runtime_event(
                view.run_id,
                "run_manual_resume_required",
                {
                    "prior_status": current.status,
                    "status": "failed",
                    "reason": "worker_interrupted",
                    "resume_mode": "manual_checkpoint_resume_only",
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
        # Runtime progress is durable activity.  A long Codex turn can emit
        # progress events for several minutes without changing the public
        # phase/status, so using ``RunView.updated_at`` alone would make the
        # orphan reaper classify a live Worker as dead.  Refresh the run lease
        # before appending the event; this is deliberately not a status
        # transition and therefore does not create duplicate UI state events.
        try:
            current = self.get_run(run_id)
            if current.status in ACTIVE_RUN_STATUSES:
                touched = replace(current, updated_at=now_iso())
                self._runs[run_id] = touched
                self._save(touched)
        except (KeyError, LookupError, NoResultFound):
            # A run may be deleted while a late telemetry event is flushing.
            # The event sink is diagnostic and must not resurrect the run or
            # invalidate the Worker result.
            pass
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
            active.append({
                **row,
                "age_seconds": round(age, 1),
                "online": age <= stale_after_seconds and row.get("status") != "stopped",
            })
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
        capacity_transition = (
            "scaling_up"
            if worker_capacity < configured_capacity
            else "scaling_down"
            if worker_capacity > configured_capacity
            else "stable"
        )
        pending = self.queue.pending_run_ids()
        return {
            "status": "ready" if online_workers else "degraded",
            "worker_online": bool(online_workers),
            "workers": active,
            "configured_worker_capacity": configured_capacity,
            "capacity_transition": capacity_transition,
            "capacity_limit": 8,
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
