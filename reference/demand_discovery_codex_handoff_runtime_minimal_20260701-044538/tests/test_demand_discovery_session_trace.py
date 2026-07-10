from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.session_store import (  # noqa: E402
    JsonlSessionStore,
    MemorySessionStore,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.trace_store import (  # noqa: E402
    DomainTraceEvent,
    DomainTraceStore,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


class DemandDiscoverySessionStoreTests(unittest.TestCase):
    def test_memory_session_store_appends_and_restores_active_leaf(self) -> None:
        store = MemorySessionStore()

        first = store.append("message", {"role": "user"}, run_id="run-1")
        second = store.append("message", {"role": "assistant"}, run_id="run-1")
        pointer = store.set_active_leaf(first.entry_id, run_id="run-1")

        self.assertEqual(store.active_leaf_id, first.entry_id)
        self.assertEqual(store.restore_active_leaf(), first.entry_id)
        self.assertEqual(second.parent_id, first.entry_id)
        self.assertEqual(pointer.type, "active_pointer")
        self.assertEqual(
            [entry.type for entry in store.entries()],
            ["message", "message", "active_pointer"],
        )

    def test_jsonl_session_store_writes_header_and_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            store = JsonlSessionStore(path)

            entry = store.append("message", {"role": "user"}, run_id="run-1")
            store.set_active_leaf(entry.entry_id, run_id="run-1")

            lines = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(lines[0]["type"], "session_header")
        self.assertEqual(lines[1]["type"], "message")
        self.assertEqual(lines[2]["type"], "active_pointer")
        self.assertEqual(lines[2]["payload"]["active_leaf_id"], entry.entry_id)


class DemandDiscoveryTraceStoreTests(unittest.TestCase):
    def _event(
        self,
        event_type: str,
        target_type: str,
        target_id: str,
        input_refs: list[str],
        output_refs: list[str],
    ) -> DomainTraceEvent:
        return DomainTraceEvent(
            domain_trace_id=f"dt-{target_id}",
            trace_id="trace-1",
            event_type=event_type,
            actor="test",
            target_type=target_type,
            target_id=target_id,
            input_refs=input_refs,
            output_refs=output_refs,
            summary=f"{event_type} {target_id}",
        )

    def test_domain_trace_store_returns_report_lineage(self) -> None:
        store = DomainTraceStore()
        for event in [
            self._event("source_seen", "SourceRecord", "src-1", [], ["src-1"]),
            self._event(
                "evidence_created",
                "EvidenceCard",
                "ev-1",
                ["src-1"],
                ["ev-1"],
            ),
            self._event(
                "candidate_created",
                "CandidateDemand",
                "cand-1",
                ["ev-1"],
                ["cand-1"],
            ),
            self._event(
                "audit_completed",
                "AuditReport",
                "audit-1",
                ["cand-1"],
                ["audit-1"],
            ),
            self._event(
                "report_generated",
                "DemandReport",
                "report-1",
                ["cand-1", "audit-1"],
                ["report-1"],
            ),
        ]:
            store.append(event)

        lineage = store.get_report_trace("report-1")

        self.assertEqual(
            [event.target_id for event in lineage],
            ["src-1", "ev-1", "cand-1", "audit-1", "report-1"],
        )

    def test_report_lineage_uses_latest_audit_event_for_duplicate_audit_id(self) -> None:
        store = DomainTraceStore()
        for event in [
            self._event("source_seen", "SourceRecord", "src-1", [], ["src-1"]),
            self._event(
                "evidence_created",
                "EvidenceCard",
                "ev-1",
                ["src-1"],
                ["ev-1"],
            ),
            self._event(
                "candidate_created",
                "CandidateDemand",
                "cand-1",
                ["ev-1"],
                ["cand-1"],
            ),
            DomainTraceEvent(
                domain_trace_id="dt-audit-rejected",
                trace_id="trace-1",
                event_type="audit_completed",
                actor="test",
                target_type="AuditReport",
                target_id="audit-1",
                input_refs=["cand-1"],
                output_refs=["audit-1"],
                summary="audit rejected",
                decision="rejected",
            ),
            DomainTraceEvent(
                domain_trace_id="dt-audit-approved",
                trace_id="trace-1",
                event_type="audit_completed",
                actor="test",
                target_type="AuditReport",
                target_id="audit-1",
                input_refs=["cand-1"],
                output_refs=["audit-1"],
                summary="audit approved",
                decision="approved",
            ),
            self._event(
                "report_generated",
                "DemandReport",
                "report-1",
                ["cand-1", "audit-1", "ev-1"],
                ["report-1"],
            ),
        ]:
            store.append(event)

        lineage = store.get_report_trace("report-1")
        audit_events = [
            event for event in lineage if event.event_type == "audit_completed"
        ]

        self.assertEqual([event.domain_trace_id for event in audit_events], ["dt-audit-approved"])
        self.assertEqual([event.decision for event in audit_events], ["approved"])

    def test_domain_trace_store_rejects_runtime_events(self) -> None:
        store = DomainTraceStore()

        with self.assertRaises(TypeError):
            store.append(AgentEvent(type="turn_end", run_id="run-1", payload={}))


class DemandDiscoveryHarnessStoreIntegrationTests(unittest.TestCase):
    def test_harness_writes_session_and_trace_at_save_point(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "trace_tool", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )

        async def trace_tool(
            call: ToolCall, ctx: ToolExecutionContext
        ) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content="created trace",
                details={},
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-1",
                        payload_summary="created ev-1",
                        output_refs=["ev-1"],
                    )
                ],
            )

        session_store = MemorySessionStore()
        trace_store = DomainTraceStore()
        harness = DiscoveryHarness(
            provider=provider,
            tools=[
                ToolDefinition(
                    "trace_tool",
                    "",
                    {"type": "object", "properties": {}},
                    trace_tool,
                )
            ],
            session_store=session_store,
            trace_store=trace_store,
        )
        trace_counts_at_tool_end: list[int] = []

        def observe(event: AgentEvent) -> None:
            if event.type == "tool_execution_end":
                trace_counts_at_tool_end.append(len(trace_store.events()))

        harness.subscribe(observe)

        asyncio.run(harness.prompt("go"))

        self.assertEqual(trace_counts_at_tool_end, [0])
        self.assertEqual(len(trace_store.events()), 1)
        self.assertEqual(trace_store.events()[0].target_id, "ev-1")
        self.assertIn(
            "save_point",
            [entry.type for entry in session_store.entries()],
        )
        self.assertIn(
            "message",
            [entry.type for entry in session_store.entries()],
        )


if __name__ == "__main__":
    unittest.main()
