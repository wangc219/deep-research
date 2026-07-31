from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.context_pack import (  # noqa: E402
    ContextPackBuilder,
)
from knowledgegraph.demand_discovery.harness.trace_store import (  # noqa: E402
    DomainTraceEvent,
    DomainTraceStore,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)


def _run_state() -> dict:
    return {
        "sources": [
            {
                "source_id": "src-1",
                "title": "A source",
                "source_tier": "A",
                "summary_text": "official context",
            }
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "source_id": "src-1",
                "claim": "new operating constraints are emerging",
                "evidence_summary": "constraint signal",
                "excerpt": "short source excerpt",
                "raw_payload": "DO_NOT_COPY_FULL_EVIDENCE_JSON",
            }
        ],
        "candidates": [
            {
                "candidate_id": "cand-1",
                "title": "Candidate title",
                "demand_statement": "Need a better capability in this scenario.",
                "status": "candidate_demand",
                "evidence_ids": ["ev-1"],
                "open_questions": ["which scenario is strongest?"],
                "solution_signals": ["related concept"],
                "internal_notes": "DO_NOT_COPY_FULL_CANDIDATE_JSON",
            }
        ],
        "documents": [
            {
                "artifact_ref": "artifact://doc-1",
                "title": "Long document",
                "text": "opening visible excerpt. "
                + ("middle body should stay behind artifact ref. " * 80)
                + "TAIL_SHOULD_NOT_APPEAR",
            }
        ],
        "open_questions": ["what evidence is still missing?"],
        "excluded_directions": ["pure technology hotspot without scenario"],
        "audit_scorecard": {"evidence_quality": "visible to audit worker"},
    }


class DemandDiscoveryContextPackTests(unittest.TestCase):
    def test_roles_receive_different_context_projections(self) -> None:
        builder = ContextPackBuilder()

        scanner = builder.build("horizon_scanner", "scan sources", _run_state(), 600)
        audit = builder.build("audit_worker", "audit candidate", _run_state(), 600)

        self.assertNotEqual(scanner.sections, audit.sections)
        self.assertIn("sources", scanner.sections)
        self.assertNotIn("audit_scorecard", scanner.sections)
        self.assertIn("audit_scorecard", audit.sections)
        self.assertIn("candidate_index", audit.sections)

    def test_evidence_and_candidates_are_summarized_not_copied(self) -> None:
        pack = ContextPackBuilder().build(
            "audit_worker", "audit candidate", _run_state(), 600
        )
        rendered = pack.render()

        self.assertIn("ev-1", rendered)
        self.assertIn("new operating constraints", rendered)
        self.assertIn("cand-1", rendered)
        self.assertNotIn("DO_NOT_COPY_FULL_EVIDENCE_JSON", rendered)
        self.assertNotIn("DO_NOT_COPY_FULL_CANDIDATE_JSON", rendered)

    def test_long_document_text_uses_artifact_refs_and_excerpts(self) -> None:
        pack = ContextPackBuilder().build(
            "reading_worker", "read document", _run_state(), 400
        )
        rendered = pack.render()

        self.assertIn("artifact://doc-1", rendered)
        self.assertIn("opening visible excerpt", rendered)
        self.assertNotIn("TAIL_SHOULD_NOT_APPEAR", rendered)

    def test_compaction_preserves_ids_questions_and_exclusions(self) -> None:
        builder = ContextPackBuilder()
        events = [
            DomainTraceEvent(
                domain_trace_id="dt-ev-1",
                trace_id="trace-1",
                event_type="evidence_created",
                actor="test",
                target_type="EvidenceCard",
                target_id="ev-1",
                output_refs=["ev-1"],
                summary="created evidence",
            ),
            {
                "target_type": "CandidateDemand",
                "target_id": "cand-1",
                "output_refs": ["cand-1"],
                "payload": {
                    "open_questions": ["which scenario is strongest?"],
                    "excluded_directions": ["pure technology hotspot"],
                },
            },
        ]

        summary = builder.compact_trace_segment(events, policy={})

        self.assertEqual(summary.evidence_ids, ["ev-1"])
        self.assertEqual(summary.candidate_ids, ["cand-1"])
        self.assertEqual(summary.open_questions, ["which scenario is strongest?"])
        self.assertEqual(summary.excluded_directions, ["pure technology hotspot"])


class DemandDiscoveryHarnessContextPackIntegrationTests(unittest.TestCase):
    def test_harness_rebuilds_context_snapshot_at_save_point(self) -> None:
        provider = FakeProvider()
        provider.set_responses([FakeResponse(text="done")])
        builder = ContextPackBuilder()
        harness = DiscoveryHarness(provider=provider, context_builder=builder)
        save_point_payloads: list[dict] = []
        harness.subscribe(
            lambda event: save_point_payloads.append(event.payload)
            if event.type == "save_point"
            else None
        )

        asyncio.run(harness.prompt("scan this topic"))

        self.assertIsNotNone(harness.context_snapshot)
        self.assertEqual(harness.context_snapshot.task_brief, "scan this topic")
        self.assertTrue(save_point_payloads[-1]["context_rebuilt"])

    def test_context_snapshot_includes_trace_only_evidence_ids(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "probe", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )

        async def probe(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content="probe evidence",
                details={},
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-probe",
                        payload_summary="created ev-probe",
                        output_refs=["ev-probe"],
                    )
                ],
            )

        trace_store = DomainTraceStore()
        harness = DiscoveryHarness(
            provider=provider,
            tools=[
                ToolDefinition(
                    "probe",
                    "",
                    {"type": "object", "properties": {}},
                    probe,
                )
            ],
            trace_store=trace_store,
            context_builder=ContextPackBuilder(),
        )

        asyncio.run(harness.prompt("probe trace"))

        self.assertIn("ev-probe", harness.context_snapshot.render())


if __name__ == "__main__":
    unittest.main()
