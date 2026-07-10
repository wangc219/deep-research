from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    DomainTraceEvent,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.cancellation import CancelToken  # noqa: E402
from knowledgegraph.demand_discovery.harness.event_bus import RuntimeEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduled_runner import (  # noqa: E402
    ScheduledTask,
    ScheduledRunner,
    load_scheduled_task,
)
import scripts.demand_discovery_scheduler as scheduler_cli  # noqa: E402


NOW = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)


class DemandDiscoveryScheduledRunnerTests(unittest.TestCase):
    def test_tick_triggers_due_task_and_writes_done_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "horizon.json",
                {
                    "task_name": "horizon_scan_daily",
                    "schedule": "08:00",
                    "repeat": "daily",
                    "enabled": True,
                    "max_delay_hours": 6,
                    "task_brief": "scan A/B sources",
                },
            )
            calls: list[str] = []

            async def run_factory(task):
                calls.append(task.task_name)
                return {"summary": "ok", "signals": ["cand-1"]}

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                log_path=root / "runner.log",
            )

            triggered = asyncio.run(runner.tick())

            self.assertEqual(triggered, ["horizon_scan_daily"])
            self.assertEqual(calls, ["horizon_scan_daily"])
            done = root / "done" / "2026-06-15_horizon_scan_daily.md"
            self.assertTrue(done.exists())
            self.assertIn("Status: SUCCESS", done.read_text(encoding="utf-8"))

    def test_tick_skips_not_due_disabled_overdue_and_existing_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "disabled.json",
                {"task_name": "disabled", "repeat": "daily", "enabled": False},
            )
            _write_task(
                root / "tasks" / "future.json",
                {
                    "task_name": "future",
                    "schedule": "09:00",
                    "repeat": "daily",
                    "enabled": True,
                },
            )
            _write_task(
                root / "tasks" / "overdue.json",
                {
                    "task_name": "overdue",
                    "schedule": "01:00",
                    "repeat": "daily",
                    "enabled": True,
                    "max_delay_hours": 2,
                },
            )
            _write_task(
                root / "tasks" / "done.json",
                {
                    "task_name": "done",
                    "schedule": "07:00",
                    "repeat": "daily",
                    "enabled": True,
                },
            )
            (root / "done").mkdir()
            (root / "done" / "2026-06-15_done.md").write_text("done", encoding="utf-8")

            async def run_factory(task):
                raise AssertionError("no task should run")

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                log_path=root / "runner.log",
            )

            self.assertEqual(asyncio.run(runner.tick()), [])

    def test_failed_task_still_writes_failed_done_and_health_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "bad.json",
                {
                    "task_name": "bad",
                    "schedule": "08:00",
                    "repeat": "daily",
                    "enabled": True,
                },
            )

            async def run_factory(task):
                raise RuntimeError("provider failed")

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                log_path=root / "runner.log",
            )

            self.assertEqual(asyncio.run(runner.tick()), ["bad"])
            done_text = (root / "done" / "2026-06-15_bad.md").read_text(encoding="utf-8")
            self.assertIn("Status: FAILED", done_text)
            health = {row["task_name"]: row["status"] for row in runner.health_check()}
            self.assertEqual(health["bad"], "ERROR")

    def test_once_task_runs_only_once_across_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "once.json",
                {
                    "task_name": "once",
                    "schedule": "08:00",
                    "repeat": "once",
                    "enabled": True,
                },
            )
            calls: list[str] = []

            async def run_factory(task):
                calls.append(task.task_name)
                return {}

            current = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: current,
                log_path=root / "runner.log",
            )

            self.assertEqual(asyncio.run(runner.tick()), ["once"])
            current = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
            self.assertEqual(asyncio.run(runner.tick()), [])
            self.assertEqual(calls, ["once"])

    def test_single_flight_skips_when_existing_run_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "task.json",
                {"task_name": "task", "schedule": "08:00", "repeat": "daily", "enabled": True},
            )

            async def run_factory(task):
                return {}

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                single_flight=True,
                log_path=root / "runner.log",
            )
            runner._running_task = "other"

            self.assertEqual(asyncio.run(runner.tick()), [])

    def test_watchlist_recheck_skips_run_without_new_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "watch.json",
                {
                    "task_name": "watchlist_recheck_weekly",
                    "task_type": "watchlist_recheck",
                    "schedule": "08:00",
                    "repeat": "weekly",
                    "enabled": True,
                },
            )
            store = DomainStore()
            store.upsert_candidate(
                CandidateDemand(
                    candidate_id="weak-1",
                    title="Weak signal",
                    demand_statement="needs more evidence",
                    status="weak_signal",
                    evidence_ids=[],
                    open_questions=[],
                    solution_signals=[],
                    created_by="tester",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            store.append_trace(
                _trace(
                    "parked-1",
                    "signal_parked",
                    "CandidateDemand",
                    "weak-1",
                    payload={"recheck_conditions": ["出现新的 A/B 级来源"]},
                )
            )
            calls: list[str] = []

            async def run_factory(task):
                calls.append(task.task_name)
                return {}

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                domain_store=store,
                log_path=root / "runner.log",
            )

            self.assertEqual(asyncio.run(runner.tick()), ["watchlist_recheck_weekly"])
            self.assertEqual(calls, [])
            self.assertIn(
                "SKIPPED_NO_NEW_EVIDENCE",
                (root / "done" / "2026-06-15_watchlist_recheck_weekly.md").read_text(encoding="utf-8"),
            )

    def test_watchlist_recheck_runs_when_new_source_trace_appears_after_park(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_task(
                root / "tasks" / "watch.json",
                {
                    "task_name": "watchlist_recheck_weekly",
                    "task_type": "watchlist_recheck",
                    "schedule": "08:00",
                    "repeat": "weekly",
                    "enabled": True,
                },
            )
            store = DomainStore()
            store.upsert_candidate(
                CandidateDemand(
                    candidate_id="weak-1",
                    title="Weak signal",
                    demand_statement="needs more evidence",
                    status="weak_signal",
                    evidence_ids=[],
                    open_questions=[],
                    solution_signals=[],
                    created_by="tester",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            store.append_trace(
                _trace(
                    "parked-1",
                    "signal_parked",
                    "CandidateDemand",
                    "weak-1",
                    payload={"recheck_conditions": ["出现新的 A/B 级来源"]},
                )
            )
            store.append_trace(
                _trace("source-1", "source_seen", "SourceRecord", "src-new")
            )
            calls: list[str] = []

            async def run_factory(task):
                calls.append(task.task_name)
                return {}

            runner = ScheduledRunner(
                root / "tasks",
                root / "done",
                run_factory,
                clock=lambda: NOW,
                domain_store=store,
                log_path=root / "runner.log",
            )

            self.assertEqual(asyncio.run(runner.tick()), ["watchlist_recheck_weekly"])
            self.assertEqual(calls, ["watchlist_recheck_weekly"])

    def test_scheduler_cli_run_factory_wires_inbox_budget_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(
                mode="fake",
                output_root=str(root / "runs"),
                source_whitelist=str(
                    PROJECT_ROOT
                    / "configs"
                    / "demand_discovery"
                    / "source_whitelist.yaml"
                ),
                api_key_env="DEMAND_DISCOVERY_API_KEY",
                endpoint_mode="responses_compatible",
                base_url="https://api.openai.com",
                endpoint_path="",
                model="fake",
            )
            task = ScheduledTask(
                task_name="bounded",
                task_brief="bounded task",
                budget={
                    "max_tokens": 11,
                    "max_tool_calls": 2,
                    "max_wall_clock_ms": 1234,
                },
            )

            class CapturingHarness:
                instance = None

                def __init__(self, **kwargs):
                    self.kwargs = kwargs
                    self.calls: list[tuple[str, str]] = []
                    CapturingHarness.instance = self

                def abort(self) -> None:
                    self.calls.append(("abort", ""))

                def steer(self, text: str) -> None:
                    self.calls.append(("steer", text))

                def next_turn(self, text: str) -> None:
                    self.calls.append(("next_turn", text))

                async def prompt(self, text: str):
                    run_dir = self.kwargs["session_store"].path.parent
                    inbox = run_dir / "inbox"
                    inbox.mkdir(parents=True, exist_ok=True)
                    (inbox / "steer.md").write_text("narrow scheduled task", encoding="utf-8")
                    self.kwargs["event_bus"].publish(
                        RuntimeEvent(
                            "agent_runtime",
                            "save_point",
                            self.kwargs["run_id"],
                            agent_run_id="orchestrator",
                        )
                    )
                    return SimpleNamespace(is_error=False, metadata={})

            run = scheduler_cli._run_factory(args, {})
            original_harness = scheduler_cli.DiscoveryHarness
            try:
                scheduler_cli.DiscoveryHarness = CapturingHarness
                result = asyncio.run(run(task))
            finally:
                scheduler_cli.DiscoveryHarness = original_harness

            harness = CapturingHarness.instance
            self.assertIsNotNone(harness)
            self.assertIsInstance(harness.kwargs["budget"], RunBudget)
            self.assertEqual(harness.kwargs["budget"].max_tokens, 11)
            self.assertEqual(harness.kwargs["budget"].max_tool_calls, 2)
            self.assertEqual(harness.kwargs["budget"].max_wall_clock_ms, 1234)
            self.assertIsInstance(harness.kwargs["cancel_token"], CancelToken)
            self.assertEqual(harness.calls, [("steer", "narrow scheduled task")])
            inbox_path = Path(result["inbox_path"])
            self.assertTrue(inbox_path.exists())
            self.assertEqual(len(list(inbox_path.glob("processed/*_steer.md"))), 1)

    def test_load_default_task_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.json"
            _write_task(
                path,
                {
                    "task_name": "horizon",
                    "repeat": "every_7d",
                    "budget": {"max_tokens": 10},
                    "source_filter": {"tiers": ["A"]},
                },
            )

            task = load_scheduled_task(path)

            self.assertEqual(task.task_name, "horizon")
            self.assertEqual(task.repeat, "every_7d")
            self.assertEqual(task.budget["max_tokens"], 10)
            self.assertEqual(task.source_filter["tiers"], ["A"])


def _write_task(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _trace(
    trace_id: str,
    event_type: str,
    target_type: str,
    target_id: str,
    *,
    payload: dict | None = None,
) -> DomainTraceEvent:
    return DomainTraceEvent(
        domain_trace_id=trace_id,
        trace_id="test",
        event_type=event_type,
        actor="tester",
        target_type=target_type,
        target_id=target_id,
        input_refs=[],
        output_refs=[target_id],
        summary=event_type,
        decision=None,
        rationale=None,
        model=None,
        prompt_id=None,
        tool_refs=[],
        runtime_event_id=None,
        created_at=NOW,
        payload=payload or {},
    )


if __name__ == "__main__":
    unittest.main()
