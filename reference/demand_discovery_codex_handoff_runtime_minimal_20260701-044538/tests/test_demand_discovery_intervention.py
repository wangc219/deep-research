from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.event_bus import (  # noqa: E402
    EventBus,
    RuntimeEvent,
)
from knowledgegraph.demand_discovery.harness.intervention import (  # noqa: E402
    FileInbox,
    attach_file_inbox,
)


class FakeHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def abort(self) -> None:
        self.calls.append(("abort", ""))

    def steer(self, text: str) -> None:
        self.calls.append(("steer", text))

    def next_turn(self, text: str) -> None:
        self.calls.append(("next_turn", text))


class DemandDiscoveryInterventionTests(unittest.TestCase):
    def test_file_inbox_consumes_three_supported_files_and_moves_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox_dir = Path(tmp) / "inbox"
            inbox_dir.mkdir()
            (inbox_dir / "stop").write_text("stop now", encoding="utf-8")
            (inbox_dir / "steer.md").write_text("focus on A-tier evidence", encoding="utf-8")
            (inbox_dir / "next_turn.md").write_text("avoid duplicate scans", encoding="utf-8")
            (inbox_dir / "notes.txt").write_text("ignored", encoding="utf-8")

            events = FileInbox(inbox_dir).poll()

            self.assertEqual([event.kind for event in events], ["stop", "steer", "next_turn"])
            self.assertEqual(events[1].text, "focus on A-tier evidence")
            processed = list((inbox_dir / "processed").glob("*"))
            self.assertEqual(len(processed), 3)
            self.assertTrue((inbox_dir / "notes.txt").exists())

    def test_attach_file_inbox_polls_on_save_point_and_publishes_consumed_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox_dir = Path(tmp) / "inbox"
            inbox_dir.mkdir()
            (inbox_dir / "steer.md").write_text("narrow scope", encoding="utf-8")
            (inbox_dir / "next_turn.md").write_text("remember source cap", encoding="utf-8")

            harness = FakeHarness()
            bus = EventBus()
            seen: list[RuntimeEvent] = []
            bus.subscribe(seen.append, categories={"intervention"})
            attach_file_inbox(
                bus,
                harness,
                FileInbox(inbox_dir),
                run_id="run-1",
                agent_run_id="orchestrator",
            )

            bus.publish(RuntimeEvent("agent_runtime", "message_end", "run-1"))
            self.assertEqual(harness.calls, [])

            bus.publish(RuntimeEvent("agent_runtime", "save_point", "run-1"))

            self.assertEqual(
                harness.calls,
                [("steer", "narrow scope"), ("next_turn", "remember source cap")],
            )
            self.assertEqual([event.event_type for event in seen], ["intervention_consumed", "intervention_consumed"])
            self.assertEqual(seen[0].payload["kind"], "steer")


if __name__ == "__main__":
    unittest.main()
