from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.state_machine import STATUSES  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import (  # noqa: E402
    build_domain_tools,
)
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainWriteProposal,
    ToolCall,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)


def _get_tool(tools: list[ToolDefinition], name: str) -> ToolDefinition:
    return next(tool for tool in tools if tool.name == name)


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "worker-1", {})


def _seed_store() -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Journal",
            source_tier="A",
            source_type="journal",
            publish_time=NOW,
            url_or_path="https://example.test/source",
            summary_text="summary",
            summary_source="structured_abstract",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="claim",
            evidence_summary="summary",
            excerpt="excerpt",
            source_location="p1",
            evidence_assessment="strong",
            created_by="tester",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="original statement",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="tester",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


class DemandDiscoveryDomainToolsTests(unittest.TestCase):
    def test_domain_tool_schemas_define_required_properties(self) -> None:
        for tool in build_domain_tools():
            schema = tool.parameters_schema
            properties = schema.get("properties", {})
            self.assertEqual(schema.get("type"), "object", tool.name)
            for required in schema.get("required", []):
                self.assertIn(required, properties, tool.name)

    def test_candidate_status_schema_exposes_state_machine_enum(self) -> None:
        tool = _get_tool(build_domain_tools(), "create_or_update_candidate")

        status_schema = tool.parameters_schema["properties"]["status"]

        self.assertEqual(status_schema["type"], "string")
        self.assertEqual(status_schema["enum"], sorted(STATUSES))

    def test_source_record_proposal_accepts_common_publication_date_formats(self) -> None:
        store = DomainStore()

        store.apply_domain_proposal(
            DomainWriteProposal(
                "upsert",
                "SourceRecord",
                {
                    "source_id": "src-slash-date",
                    "title": "Slash date source",
                    "source_name": "Open",
                    "source_tier": "B",
                    "source_type": "media",
                    "publish_time": "2026/04/21",
                    "url_or_path": "https://example.test/slash",
                    "summary_source": "lead_summary",
                    "collection_decision": "use_as_background",
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                },
            )
        )
        store.apply_domain_proposal(
            DomainWriteProposal(
                "upsert",
                "SourceRecord",
                {
                    "source_id": "src-rss-date",
                    "title": "RSS date source",
                    "source_name": "Open",
                    "source_tier": "B",
                    "source_type": "media",
                    "publish_time": "Sun, 28 Jun 2026 08:00:00 -0400",
                    "url_or_path": "https://example.test/rss",
                    "summary_source": "lead_summary",
                    "collection_decision": "use_as_background",
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                },
            )
        )

        self.assertEqual(store.sources["src-slash-date"].publish_time.date().isoformat(), "2026-04-21")
        self.assertEqual(store.sources["src-rss-date"].publish_time.year, 2026)

    def test_create_evidence_card_returns_separated_channels(self) -> None:
        tool = _get_tool(build_domain_tools(), "create_evidence_card")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "evidence_id": "ev-2",
                        "source_id": "src-1",
                        "claim": "new constraint",
                        "evidence_summary": "constraint evidence",
                        "excerpt": "quoted text",
                        "source_location": "p2",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertIn("ev-2", result.content)
        self.assertEqual(result.details["evidence_id"], "ev-2")
        self.assertNotIn("domain_proposals", result.details)
        self.assertEqual(result.domain_proposals[0].object_type, "EvidenceCard")
        self.assertEqual(result.trace_proposals[0].event_type, "evidence_created")

    def test_create_or_update_candidate_emits_proposals_only(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "create_or_update_candidate")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "candidate_id": "cand-2",
                        "title": "New candidate",
                        "demand_statement": "Need capability.",
                        "evidence_ids": ["ev-1"],
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.domain_proposals[0].object_type, "CandidateDemand")
        self.assertEqual(result.trace_proposals[0].target_id, "cand-2")
        self.assertIsNone(store.candidates.get("cand-2"))

    def test_create_or_update_candidate_normalizes_proposed_status_alias(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "create_or_update_candidate")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "candidate_id": "cand-2",
                        "title": "New candidate",
                        "demand_statement": "Need capability.",
                        "status": "proposed",
                        "evidence_ids": ["ev-1"],
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.domain_proposals[0].payload["status"],
            "candidate_demand",
        )

    def test_create_or_update_candidate_rejects_unknown_status_without_proposals(
        self,
    ) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "create_or_update_candidate")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "candidate_id": "cand-2",
                        "title": "New candidate",
                        "demand_statement": "Need capability.",
                        "status": "draft",
                        "evidence_ids": ["ev-1"],
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("unknown candidate status: draft", result.content)
        self.assertEqual(result.domain_proposals, [])
        self.assertEqual(result.trace_proposals, [])

    def test_invalid_evidence_id_blocks_candidate_update(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "create_or_update_candidate")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "candidate_id": "cand-2",
                        "title": "New candidate",
                        "demand_statement": "Need capability.",
                        "evidence_ids": ["missing"],
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.domain_proposals, [])
        self.assertEqual(result.trace_proposals, [])

    def test_audit_tool_does_not_mutate_candidate_body(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store, rubric=None), "run_audit")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    id="call-1",
                    name=tool.name,
                    arguments={
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": {
                            "evidence_support": {
                                "verdict": "pass",
                                "reason": "direct evidence supports candidate",
                                "evidence_reviews": {
                                    "ev-1": {
                                        "evidence_id": "ev-1",
                                        "support_level": "direct",
                                        "support_type": "inferred_gap",
                                        "used_for_core": True,
                                        "reason": "fixture evidence supports candidate",
                                        "missing_link": "",
                                    }
                                },
                            }
                        },
                        "comments": "candidate body should stay unchanged",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(
            store.get_candidate("cand-1").demand_statement,
            "original statement",
        )
        self.assertEqual(result.domain_proposals[0].object_type, "AuditReport")

    def test_harness_flushes_domain_proposals_at_save_point(self) -> None:
        store = _seed_store()
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "create_or_update_candidate",
                            "arguments": {
                                "candidate_id": "cand-2",
                                "title": "New candidate",
                                "demand_statement": "Need capability.",
                                "evidence_ids": ["ev-1"],
                            },
                        }
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=build_domain_tools(store),
            domain_store=store,
        )

        asyncio.run(harness.prompt("create candidate"))

        self.assertEqual(store.get_candidate("cand-2").title, "New candidate")
        self.assertEqual(
            [event.event_type for event in store.trace_events],
            ["candidate_created"],
        )

    def test_harness_flushes_candidate_status_alias_at_save_point(self) -> None:
        store = _seed_store()
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "create_or_update_candidate",
                            "arguments": {
                                "candidate_id": "cand-2",
                                "title": "New candidate",
                                "demand_statement": "Need capability.",
                                "status": "proposed",
                                "evidence_ids": ["ev-1"],
                            },
                        }
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=build_domain_tools(store),
            domain_store=store,
        )

        asyncio.run(harness.prompt("create candidate"))

        self.assertEqual(store.get_candidate("cand-2").status, "candidate_demand")
        self.assertEqual(harness.phase, "idle")

    def test_harness_rejects_unmatched_domain_trace_pair(self) -> None:
        store = _seed_store()

        async def bad_tool(call, ctx):
            from knowledgegraph.demand_discovery.harness.types import (
                DomainTraceProposal,
                DomainWriteProposal,
                ToolResult,
            )

            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content="bad",
                details={},
                domain_proposals=[
                    DomainWriteProposal(
                        action="upsert",
                        object_type="CandidateDemand",
                        payload={
                            "candidate_id": "cand-bad",
                            "title": "Bad",
                            "demand_statement": "Bad",
                            "status": "candidate_demand",
                            "evidence_ids": ["ev-1"],
                            "open_questions": [],
                            "solution_signals": [],
                            "created_by": "tester",
                        },
                    )
                ],
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-x",
                        payload_summary="wrong trace",
                    )
                ],
            )

        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "bad_tool", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=[
                ToolDefinition(
                    "bad_tool",
                    "",
                    {"type": "object", "properties": {}},
                    bad_tool,
                )
            ],
            domain_store=store,
        )

        with self.assertRaises(Exception):
            asyncio.run(harness.prompt("bad"))
        self.assertNotIn("cand-bad", store.candidates)
        self.assertEqual(harness.phase, "idle")


if __name__ == "__main__":
    unittest.main()
