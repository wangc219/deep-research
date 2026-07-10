"""Passive runtime event bus and progress snapshots for demand discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.events import AgentEvent


@dataclass
class RuntimeEvent:
    """Observable runtime event.

    Runtime events are passive observability records. They must not carry
    provider credentials or raw oversized payloads.
    """

    category: str
    event_type: str
    run_id: str
    agent_run_id: str = ""
    parent_event_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "agent_run_id": self.agent_run_id,
            "parent_event_id": self.parent_event_id,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


EventHandler = Callable[[RuntimeEvent], None]


class EventBus:
    """Synchronous publish/subscribe bus with filtering and redaction."""

    def __init__(self) -> None:
        self._subscribers: list[
            tuple[EventHandler, set[str] | None, str | None]
        ] = []
        self._clock = 0
        self.listener_error_count = 0

    def subscribe(
        self,
        handler: EventHandler,
        *,
        categories: set[str] | None = None,
        run_id: str | None = None,
    ) -> Callable[[], None]:
        record = (handler, set(categories) if categories else None, run_id)
        self._subscribers.append(record)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(record)
            except ValueError:
                pass

        return unsubscribe

    def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        self._clock += 1
        safe_event = RuntimeEvent(
            category=event.category,
            event_type=event.event_type,
            run_id=event.run_id,
            agent_run_id=event.agent_run_id,
            parent_event_id=event.parent_event_id,
            payload=redact(event.payload),
            timestamp=event.timestamp or self._clock,
        )
        for handler, categories, run_id in list(self._subscribers):
            if categories is not None and safe_event.category not in categories:
                continue
            if run_id is not None and safe_event.run_id != run_id:
                continue
            try:
                handler(safe_event)
            except Exception:
                self.listener_error_count += 1
        return safe_event


def runtime_event_from_agent(
    event: AgentEvent,
    *,
    category: str = "agent_runtime",
    parent_event_id: str = "",
) -> RuntimeEvent:
    return RuntimeEvent(
        category=category,
        event_type=event.type,
        run_id=event.run_id,
        agent_run_id=event.agent_run_id,
        parent_event_id=parent_event_id or str(event.payload.get("parent_event_id", "")),
        payload=dict(event.payload),
        timestamp=event.timestamp,
    )


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "headers",
    "token",
    "secret",
    "password",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000].rstrip() + "...<truncated>"
    return value


class ProgressWriter:
    """Writes a compact run progress snapshot for human monitoring."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(
        self,
        *,
        run_id: str,
        task_brief: str,
        worker_states: list[Any],
        domain_store: DomainStore,
        budget: RunBudget | None = None,
        recent_events: list[RuntimeEvent] | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        budget_summary = budget.remaining_summary() if budget is not None else {}
        lines = [
            f"# Demand Discovery Progress: {run_id}",
            "",
            f"Task: {task_brief}",
            "",
            "## Workers",
        ]
        if worker_states:
            for state in worker_states:
                lines.append(
                    "- "
                    f"{state.agent_run_id} | {state.role} | {state.status} | "
                    f"{state.task_brief}"
                )
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Domain Counts",
                f"- sources: {len(domain_store.sources)}",
                f"- evidence: {len(domain_store.evidence)}",
                f"- candidates: {len(domain_store.candidates)}",
                f"- audits: {len(domain_store.audit_reports)}",
                f"- reports: {len(domain_store.demand_reports)}",
                "",
                "## Budget",
            ]
        )
        if budget_summary:
            for key, value in budget_summary.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- not configured")

        lines.extend(["", "## Recent Events"])
        for event in recent_events or []:
            lines.append(
                "- "
                f"{event.timestamp} | {event.category} | {event.event_type} | "
                f"{event.agent_run_id}"
            )
        if not recent_events:
            lines.append("- none")

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
