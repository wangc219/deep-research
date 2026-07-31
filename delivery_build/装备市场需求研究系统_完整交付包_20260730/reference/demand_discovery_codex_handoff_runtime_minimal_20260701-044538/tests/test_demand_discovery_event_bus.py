from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.event_bus import (  # noqa: E402
    EventBus,
    ProgressWriter,
    RuntimeEvent,
)
from knowledgegraph.demand_discovery.harness.scheduler import WorkerState  # noqa: E402


class DemandDiscoveryEventBusTests(unittest.TestCase):
    def test_subscribe_filter_unsubscribe_and_listener_errors_are_isolated(self) -> None:
        bus = EventBus()
        seen: list[str] = []

        unsubscribe = bus.subscribe(
            lambda event: seen.append(event.event_type),
            categories={"scheduler"},
            run_id="run-1",
        )
        bus.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("boom")))

        bus.publish(RuntimeEvent("scheduler", "worker_started", "run-1"))
        bus.publish(RuntimeEvent("harness", "save_point", "run-1"))
        unsubscribe()
        bus.publish(RuntimeEvent("scheduler", "worker_completed", "run-1"))

        self.assertEqual(seen, ["worker_started"])
        self.assertEqual(bus.listener_error_count, 3)

    def test_publish_redacts_headers_and_secret_like_keys(self) -> None:
        bus = EventBus()
        seen: list[RuntimeEvent] = []
        bus.subscribe(seen.append)

        bus.publish(
            RuntimeEvent(
                "provider_stream",
                "request",
                "run-1",
                payload={
                    "headers": {"Authorization": "Bearer SECRET"},
                    "api_key": "SECRET",
                    "nested": {"authorization": "SECRET"},
                    "text": "x" * 6000,
                },
            )
        )

        payload = seen[0].payload
        self.assertEqual(payload["headers"], "<redacted>")
        self.assertEqual(payload["api_key"], "<redacted>")
        self.assertEqual(payload["nested"]["authorization"], "<redacted>")
        self.assertLess(len(payload["text"]), 1200)

    def test_progress_writer_records_worker_and_budget_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.md"
            writer = ProgressWriter(path)
            state = WorkerState(
                run_id="run-1",
                agent_run_id="agent-1",
                worker_id="reader",
                role="reader",
                task_brief="read",
                context_pack=ContextPack("reader", "read", {}, 200),
                status="completed",
                parent_event_id="parent",
            )
            writer.write(
                run_id="run-1",
                task_brief="topic",
                worker_states=[state],
                domain_store=DomainStore(),
                budget=RunBudget(max_tool_calls=10),
                recent_events=[
                    RuntimeEvent("scheduler", "worker_completed", "run-1")
                ],
            )

            text = path.read_text(encoding="utf-8")
            self.assertIn("run-1", text)
            self.assertIn("reader", text)
            self.assertIn("completed", text)
            self.assertIn("worker_completed", text)


if __name__ == "__main__":
    unittest.main()
