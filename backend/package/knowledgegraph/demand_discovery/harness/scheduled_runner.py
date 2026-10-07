"""File-backed scheduled runner for demand-discovery autonomy loops."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from knowledgegraph.demand_discovery.domain.store import DomainStore


RunFactory = Callable[["ScheduledTask"], Awaitable[dict[str, Any] | None]]
Clock = Callable[[], datetime]

NEW_EVIDENCE_EVENT_TYPES = {
    "source_seen",
    "source_updated",
    "evidence_created",
    "evidence_updated",
}


@dataclass(frozen=True)
class ScheduledTask:
    task_name: str
    schedule: str = "00:00"
    repeat: str = "daily"
    enabled: bool = True
    max_delay_hours: int | None = None
    task_brief: str = ""
    budget: dict[str, Any] = field(default_factory=dict)
    source_filter: dict[str, Any] = field(default_factory=dict)
    task_type: str = "horizon_scan"
    raw: dict[str, Any] = field(default_factory=dict)


class ScheduledRunner:
    """Poll JSON task definitions and run due tasks once per cooldown window."""

    def __init__(
        self,
        tasks_dir: str | Path,
        done_dir: str | Path,
        run_factory: RunFactory,
        *,
        clock: Clock | None = None,
        poll_interval_s: int = 60,
        single_flight: bool = True,
        domain_store: DomainStore | None = None,
        log_path: str | Path | None = None,
    ) -> None:
        self.tasks_dir = Path(tasks_dir)
        self.done_dir = Path(done_dir)
        self.run_factory = run_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_interval_s = poll_interval_s
        self.single_flight = single_flight
        self.domain_store = domain_store
        self.log_path = Path(log_path) if log_path is not None else self.done_dir.parent / "runner.log"
        self._running_task = ""

    async def run_forever(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self.poll_interval_s)

    async def tick(self) -> list[str]:
        now = _ensure_aware(self.clock())
        triggered: list[str] = []
        for task in self._load_tasks():
            if not self._is_due(task, now):
                continue
            if self.single_flight and self._running_task:
                self._log(f"skip {task.task_name}: single_flight active {self._running_task}")
                continue
            triggered.append(task.task_name)
            if task.task_type == "watchlist_recheck" and not self._watchlist_has_new_evidence(task):
                self._write_done(task, now, "SKIPPED_NO_NEW_EVIDENCE", {"summary": "no watchlist evidence trigger"})
                continue
            self._running_task = task.task_name
            try:
                self._log(f"start {task.task_name}")
                result = await self.run_factory(task)
                self._write_done(task, now, "SUCCESS", result or {})
                self._log(f"success {task.task_name}")
            except Exception as exc:
                self._write_done(task, now, "FAILED", {"error": str(exc)})
                self._log(f"failed {task.task_name}: {exc}")
            finally:
                self._running_task = ""
        return triggered

    def health_check(self) -> list[dict[str, Any]]:
        now = _ensure_aware(self.clock())
        rows: list[dict[str, Any]] = []
        for task in self._load_tasks():
            latest = self._latest_done(task)
            status = "HEALTHY"
            if not task.enabled:
                status = "DISABLED"
            elif latest is None:
                status = "OVERDUE" if self._is_due(task, now) else "NEVER_RUN"
            else:
                text = latest.read_text(encoding="utf-8", errors="replace")
                if "Status: FAILED" in text:
                    status = "ERROR"
                elif self._is_due(task, now):
                    status = "OVERDUE"
            rows.append(
                {
                    "task_name": task.task_name,
                    "status": status,
                    "latest_done": str(latest) if latest else "",
                }
            )
        return rows

    def _load_tasks(self) -> list[ScheduledTask]:
        if not self.tasks_dir.exists():
            return []
        return [
            load_scheduled_task(path)
            for path in sorted(self.tasks_dir.glob("*.json"))
        ]

    def _is_due(self, task: ScheduledTask, now: datetime) -> bool:
        if not task.enabled:
            return False
        if self._cooling_down(task, now):
            return False
        scheduled = _scheduled_datetime(now, task.schedule)
        if now < scheduled:
            return False
        if task.max_delay_hours is not None:
            if now > scheduled + timedelta(hours=task.max_delay_hours):
                return False
        if task.repeat == "weekday" and now.weekday() >= 5:
            return False
        return True

    def _cooling_down(self, task: ScheduledTask, now: datetime) -> bool:
        if task.repeat == "once":
            return self._latest_done(task) is not None
        if task.repeat in {"daily", "weekday"}:
            return self._done_path(task, now).exists()
        latest = self._latest_done(task)
        if latest is None:
            return False
        interval = _repeat_interval(task.repeat)
        if interval is None:
            if task.repeat == "weekly":
                interval = timedelta(days=7)
            else:
                return self._done_path(task, now).exists()
        modified = datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
        return now - modified < interval

    def _write_done(
        self,
        task: ScheduledTask,
        now: datetime,
        status: str,
        result: dict[str, Any],
    ) -> None:
        self.done_dir.mkdir(parents=True, exist_ok=True)
        path = self._done_path(task, now)
        lines = [
            f"# Scheduled Task Done: {task.task_name}",
            "",
            f"Status: {status}",
            f"Run Time: {now.isoformat()}",
            f"Repeat: {task.repeat}",
            "",
            "## Result",
            "```json",
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2),
            "```",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")

    def _done_path(self, task: ScheduledTask, now: datetime) -> Path:
        return self.done_dir / f"{now.date().isoformat()}_{task.task_name}.md"

    def _latest_done(self, task: ScheduledTask) -> Path | None:
        matches = sorted(self.done_dir.glob(f"*_{task.task_name}.md"))
        return matches[-1] if matches else None

    def _watchlist_has_new_evidence(self, task: ScheduledTask) -> bool:
        if self.domain_store is None:
            return False
        view = self.domain_store.watchlist_view()
        if not view:
            return False
        for row in view:
            if not row.get("recheck_conditions"):
                continue
            if self._has_new_evidence_after(str(row.get("trace_event_id", ""))):
                return True
        return False

    def _has_new_evidence_after(self, trace_event_id: str) -> bool:
        if self.domain_store is None or not trace_event_id:
            return False
        after_parked = False
        for event in self.domain_store.trace_events:
            if event.domain_trace_id == trace_event_id:
                after_parked = True
                continue
            if not after_parked:
                continue
            if event.event_type in NEW_EVIDENCE_EVENT_TYPES:
                return True
            if _has_keyword_gate_hit(event.event_type, event.payload):
                return True
        return False

    def _log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = self.clock().isoformat()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")


def load_scheduled_task(path: str | Path) -> ScheduledTask:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ScheduledTask(
        task_name=str(data["task_name"]),
        schedule=str(data.get("schedule", "00:00")),
        repeat=str(data.get("repeat", "daily")),
        enabled=bool(data.get("enabled", True)),
        max_delay_hours=(
            int(data["max_delay_hours"]) if data.get("max_delay_hours") is not None else None
        ),
        task_brief=str(data.get("task_brief", "")),
        budget=dict(data.get("budget", {})),
        source_filter=dict(data.get("source_filter", {})),
        task_type=str(data.get("task_type", "horizon_scan")),
        raw=dict(data),
    )


def _scheduled_datetime(now: datetime, hhmm: str) -> datetime:
    try:
        hour, minute = [int(part) for part in hhmm.split(":", 1)]
    except Exception:
        hour, minute = 0, 0
    return datetime.combine(now.date(), time(hour=hour, minute=minute), tzinfo=now.tzinfo)


def _repeat_interval(repeat: str) -> timedelta | None:
    if repeat.startswith("every_") and repeat.endswith("h"):
        return timedelta(hours=int(repeat[len("every_") : -1]))
    if repeat.startswith("every_") and repeat.endswith("d"):
        return timedelta(days=int(repeat[len("every_") : -1]))
    return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _has_keyword_gate_hit(event_type: str, payload: dict[str, Any]) -> bool:
    lowered = event_type.lower()
    if "keyword" in lowered and any(
        marker in lowered for marker in ("gate", "hit", "match")
    ):
        return True
    score = payload.get("keyword_score")
    if isinstance(score, bool):
        return False
    if isinstance(score, (int, float)) and score > 0:
        return True
    hits = payload.get("keyword_hits")
    if isinstance(hits, dict):
        return any(bool(value) for value in hits.values())
    if isinstance(hits, list):
        return bool(hits)
    return False
