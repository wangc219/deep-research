"""Framework-independent run lifecycle and in-process development queue."""

from __future__ import annotations

from dataclasses import replace

from equipment_deep_research.application.dto import CreateRunCommand, RunView
from equipment_deep_research.domain.models import new_stable_id


class InvalidRunTransition(ValueError):
    pass


class InProcessRunQueue:
    def __init__(self) -> None:
        self._pending: list[str] = []

    def enqueue(self, run_id: str) -> None:
        if run_id not in self._pending:
            self._pending.append(run_id)

    def claim(self) -> str | None:
        return self._pending.pop(0) if self._pending else None

    def pending_run_ids(self) -> list[str]:
        return list(self._pending)


class ResearchApplicationService:
    def __init__(self, *, queue: InProcessRunQueue | None = None, repository: object | None = None) -> None:
        self.queue = queue or InProcessRunQueue()
        self.repository = repository
        self._runs: dict[str, RunView] = {}
        self._idempotency: dict[tuple[str, str], RunView] = {}

    def create_run(self, command: CreateRunCommand) -> RunView:
        if not command.topic.strip() or command.max_rounds < 1 or command.max_rounds > 5:
            raise ValueError("topic is required and max_rounds must be 1..5")
        view = RunView(new_stable_id("run"), command.topic, command.research_route, list(command.selected_agent_ids), command.max_rounds, command.created_by)
        self._runs[view.run_id] = view
        self._save(view)
        return view

    def get_run(self, run_id: str) -> RunView:
        if run_id in self._runs:
            return self._runs[run_id]
        if self.repository is not None:
            return self.repository.get(run_id)
        raise KeyError(run_id)

    def list_runs(self) -> list[RunView]:
        if self.repository is not None:
            return self.repository.list()
        return sorted(self._runs.values(), key=lambda item: item.updated_at, reverse=True)

    def start_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"draft", "paused"}, "queued", enqueue=True)

    def pause_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"queued", "planning", "researching", "recalling"}, "pause_requested")

    def resume_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"paused"}, "queued", enqueue=True)

    def cancel_run(self, run_id: str, *, actor: str, idempotency_key: str) -> RunView:
        return self._command(run_id, actor, idempotency_key, {"draft", "queued", "planning", "researching", "paused", "recalling"}, "cancel_requested")

    def _command(self, run_id: str, actor: str, key: str, allowed: set[str], next_status: str, *, enqueue: bool = False) -> RunView:
        if (run_id, key) in self._idempotency:
            return self._idempotency[(run_id, key)]
        current = self.get_run(run_id)
        if current.status not in allowed:
            raise InvalidRunTransition(f"{current.status} cannot transition to {next_status}")
        updated = replace(current, status=next_status)
        self._runs[run_id] = updated
        self._save(updated)
        self._idempotency[(run_id, key)] = updated
        if enqueue:
            self.queue.enqueue(run_id)
        return updated

    def set_status(self, run_id: str, status: str) -> RunView:
        updated = replace(self.get_run(run_id), status=status)
        self._runs[run_id] = updated
        self._save(updated)
        return updated

    def _save(self, view: RunView) -> None:
        if self.repository is not None:
            self.repository.save(view)
