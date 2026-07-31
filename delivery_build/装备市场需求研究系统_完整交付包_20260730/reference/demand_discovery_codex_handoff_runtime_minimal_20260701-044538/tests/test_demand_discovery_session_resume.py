from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.session_store import (  # noqa: E402
    JsonlSessionStore,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


class DemandDiscoverySessionResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_appended_is_persisted_before_turn_finishes(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "call-slow", "name": "slow_tool", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )
        started = asyncio.Event()

        async def slow_tool(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            started.set()
            await asyncio.sleep(0.1)
            return ToolResult(call.id, call.name, "slow result", {})

        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            harness = DiscoveryHarness(
                provider=provider,
                tools=[
                    ToolDefinition(
                        "slow_tool",
                        "",
                        {"type": "object", "properties": {}},
                        slow_tool,
                    )
                ],
                session_store=JsonlSessionStore(session_path, run_id="run-resume"),
                run_id="run-resume",
            )
            task = asyncio.create_task(harness.prompt("go"))
            await asyncio.wait_for(started.wait(), timeout=1.0)

            rows = _jsonl(session_path)
            message_roles = [
                row["payload"].get("role")
                for row in rows
                if row.get("type") == "message"
            ]
            self.assertEqual(message_roles[:2], ["user", "assistant"])

            await task

    def test_from_session_drops_orphan_messages_after_save_point(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            store = JsonlSessionStore(session_path, run_id="run-crash")
            store.append(
                "message",
                {"role": "user", "content": "kept", "timestamp": 0},
                run_id="run-crash",
            )
            save = store.append("save_point", {}, run_id="run-crash")
            store.append(
                "message",
                {"role": "assistant", "content": [], "timestamp": 0},
                run_id="run-crash",
            )

            harness = DiscoveryHarness.from_session(
                session_path,
                provider=FakeProvider(),
                tools=[],
                domain_store=DomainStore(),
            )

            rows = _jsonl(session_path)
            recovered = [row for row in rows if row.get("type") == "recovered_from_crash"]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["payload"]["dropped_entries"], 1)
            self.assertEqual(recovered[0]["payload"]["after_entry_id"], save.entry_id)
            self.assertEqual([message.content for message in harness.messages], ["kept"])

    async def test_next_turn_queue_survives_resume_with_double_bucket_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            provider = FakeProvider()
            provider.set_responses([FakeResponse(text="first"), FakeResponse(text="second")])
            harness = DiscoveryHarness(
                provider=provider,
                session_store=JsonlSessionStore(session_path, run_id="run-queue"),
                run_id="run-queue",
            )
            harness.next_turn("carry-me")

            restored = DiscoveryHarness.from_session(
                session_path,
                provider=provider,
                tools=[],
                domain_store=DomainStore(),
            )

            await restored.prompt("one")
            self.assertEqual(restored.pending_next_turn_count(), 1)
            await restored.prompt("two")
            self.assertEqual(restored.pending_next_turn_count(), 0)

    async def test_next_turn_carry_survives_resume_after_first_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            provider = FakeProvider()
            provider.set_responses([FakeResponse(text="first")])
            harness = DiscoveryHarness(
                provider=provider,
                session_store=JsonlSessionStore(session_path, run_id="run-carry"),
                run_id="run-carry",
            )
            harness.next_turn("carry-me")
            await harness.prompt("one")
            self.assertEqual(harness.pending_next_turn_count(), 1)

            restored_provider = _RecordingProvider()
            restored_provider.set_responses([FakeResponse(text="second")])
            restored = DiscoveryHarness.from_session(
                session_path,
                provider=restored_provider,
                tools=[],
                domain_store=DomainStore(),
            )

            await restored.prompt("two")

            self.assertEqual(restored.pending_next_turn_count(), 0)
            first_request_contents = [
                str(message.content)
                for message in restored_provider.request_messages[0]
            ]
            self.assertIn("carry-me", first_request_contents)

    def test_domain_store_jsonl_round_trip_rebuilds_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "domain.jsonl"
            store = DomainStore()
            store.bind_jsonl(path)
            domain = [
                DomainWriteProposal(
                    "upsert",
                    "SourceRecord",
                    {
                        "source_id": "src-1",
                        "title": "Source",
                        "source_name": "Demo",
                        "source_tier": "A",
                        "source_type": "demo",
                        "url_or_path": "demo://src-1",
                    },
                )
            ]
            trace = [
                DomainTraceProposal(
                    "source_seen",
                    "SourceRecord",
                    "src-1",
                    "source seen",
                    output_refs=["src-1"],
                )
            ]
            for proposal in domain:
                store.apply_domain_proposal(proposal)
            for proposal in trace:
                store.append_trace_from_proposal(proposal)
            store.append_accepted_proposals(domain)
            store.append_accepted_trace_events(store.trace_events)

            restored = DomainStore.load_jsonl(path)

            self.assertEqual(restored.to_run_state(), store.to_run_state())


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class _RecordingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_messages: list[list] = []

    def stream(self, context, tools, options):
        self.request_messages.append(list(context.messages))
        return super().stream(context, tools, options)


if __name__ == "__main__":
    unittest.main()
