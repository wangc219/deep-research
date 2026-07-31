from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    DemandReport,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.report import (  # noqa: E402
    REQUIRED_SECTIONS,
)
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
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


class DemandDiscoveryReportSkeletonTests(unittest.TestCase):
    def test_report_tool_rejects_missing_required_section(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "generate_demand_report")
        sections = _sections()
        sections.pop("capability_gap")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "sections": sections,
                        "demand_type": "explicit",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("missing required report section", result.content)
        self.assertEqual(result.domain_proposals, [])

    def test_report_tool_rejects_invalid_demand_type(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "generate_demand_report")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "sections": _sections(),
                        "demand_type": "trend",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("invalid demand_type", result.content)

    def test_report_tool_renders_evidence_and_source_audit_sections(self) -> None:
        store = _seed_store()
        tool = _get_tool(build_domain_tools(store), "generate_demand_report")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "sections": _sections(),
                        "demand_type": "inferred",
                        "related_technical_directions": ["direction A"],
                        "solution_clues": ["solution signal"],
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        payload = next(
            proposal.payload
            for proposal in result.domain_proposals
            if proposal.object_type == "DemandReport"
        )
        body = payload["body"]
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, body)
        self.assertIn("## Supporting Evidence", body)
        self.assertIn("ev-1", body)
        self.assertIn("claim one", body)
        self.assertIn("## Source Audit", body)
        self.assertIn("src-1", body)
        self.assertIn("Source title", body)
        self.assertIn("A", body)
        self.assertEqual(payload["evidence_ids"], ["ev-1"])

    def test_report_tool_schema_exposes_required_sections_and_demand_type_enum(self) -> None:
        tool = _get_tool(build_domain_tools(_seed_store()), "generate_demand_report")

        properties = tool.parameters_schema["properties"]
        sections_schema = properties["sections"]
        demand_type_schema = properties["demand_type"]

        self.assertEqual(sections_schema["type"], "object")
        self.assertEqual(sections_schema["required"], REQUIRED_SECTIONS)
        self.assertFalse(sections_schema["additionalProperties"])
        self.assertEqual(
            sorted(sections_schema["properties"].keys()),
            sorted(REQUIRED_SECTIONS),
        )
        self.assertEqual(demand_type_schema["enum"], ["explicit", "inferred"])

    def test_report_generation_promotes_candidate_to_demand_report(self) -> None:
        store = _seed_store()
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "call-report",
                            "name": "generate_demand_report",
                            "arguments": {
                                "report_id": "report-1",
                                "candidate_id": "cand-1",
                                "title": "Report",
                                "sections": _sections(),
                                "demand_type": "explicit",
                                "evidence_ids": ["ev-1"],
                                "audit_id": "audit-1",
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

        asyncio.run(harness.prompt("generate report"))

        self.assertIn("report-1", store.demand_reports)
        self.assertEqual(store.demand_reports["report-1"].review_status, "review_ready")
        self.assertEqual(store.get_candidate("cand-1").status, "demand_report")
        self.assertEqual(
            [event.event_type for event in store.trace_events],
            ["candidate_updated", "report_consistency_checked", "report_generated"],
        )

    def test_report_tool_requires_approved_audit(self) -> None:
        for store, arguments, expected_message in [
            (
                _seed_store(with_audit=False),
                {
                    "report_id": "report-1",
                    "candidate_id": "cand-1",
                    "title": "Report",
                    "sections": _sections(),
                    "demand_type": "explicit",
                    "evidence_ids": ["ev-1"],
                },
                "approved audit_id is required",
            ),
            (
                _seed_store(audit_conclusion="needs_revision"),
                {
                    "report_id": "report-1",
                    "candidate_id": "cand-1",
                    "title": "Report",
                    "sections": _sections(),
                    "demand_type": "explicit",
                    "evidence_ids": ["ev-1"],
                    "audit_id": "audit-1",
                },
                "audit audit-1 is not approved",
            ),
        ]:
            with self.subTest(expected_message=expected_message):
                tool = _get_tool(build_domain_tools(store), "generate_demand_report")

                result = asyncio.run(
                    tool.execute(
                        ToolCall("call-1", tool.name, arguments),
                        _ctx(),
                    )
                )

                self.assertTrue(result.is_error)
                self.assertIn(expected_message, result.content)
                self.assertEqual(result.domain_proposals, [])
                self.assertEqual(result.trace_proposals, [])
                self.assertNotIn("report-1", store.demand_reports)
                self.assertEqual(
                    store.get_candidate("cand-1").status,
                    "candidate_demand",
                )

    def test_report_tool_requires_minimum_evidence_gate(self) -> None:
        for store, arguments, expected_message in [
            (
                _seed_store(),
                {
                    "report_id": "report-1",
                    "candidate_id": "cand-1",
                    "title": "Report",
                    "sections": _sections(),
                    "demand_type": "explicit",
                    "evidence_ids": [],
                    "audit_id": "audit-1",
                },
                "at least one evidence_id is required",
            ),
            (
                _seed_store(source_tier="C"),
                {
                    "report_id": "report-1",
                    "candidate_id": "cand-1",
                    "title": "Report",
                    "sections": _sections(),
                    "demand_type": "explicit",
                    "evidence_ids": ["ev-1"],
                    "audit_id": "audit-1",
                },
                "minimum evidence requirement not met",
            ),
            (
                _seed_store(evidence_excerpt=None),
                {
                    "report_id": "report-1",
                    "candidate_id": "cand-1",
                    "title": "Report",
                    "sections": _sections(),
                    "demand_type": "explicit",
                    "evidence_ids": ["ev-1"],
                    "audit_id": "audit-1",
                },
                "minimum evidence requirement not met",
            ),
        ]:
            with self.subTest(expected_message=expected_message):
                tool = _get_tool(build_domain_tools(store), "generate_demand_report")

                result = asyncio.run(
                    tool.execute(
                        ToolCall("call-1", tool.name, arguments),
                        _ctx(),
                    )
                )

                self.assertTrue(result.is_error)
                self.assertIn(expected_message, result.content)
                self.assertEqual(result.domain_proposals, [])
                self.assertEqual(result.trace_proposals, [])
                self.assertNotIn("report-1", store.demand_reports)
                self.assertEqual(
                    store.get_candidate("cand-1").status,
                    "candidate_demand",
                )

    def test_report_tool_rejects_semantic_audit_doubt(self) -> None:
        store = _seed_store(evidence_support_verdict="doubt")
        tool = _get_tool(build_domain_tools(store), "generate_demand_report")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "sections": _sections(),
                        "demand_type": "inferred",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("evidence_support verdict", result.content)
        self.assertEqual(result.domain_proposals, [])
        self.assertEqual(store.get_candidate("cand-1").status, "candidate_demand")

    def test_report_tool_rejects_missing_required_semantic_rubric_item(self) -> None:
        store = _seed_store(omit_rubric_items={"core_conclusion_supported"})
        tool = _get_tool(build_domain_tools(store), "generate_demand_report")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "sections": _sections(),
                        "demand_type": "inferred",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("core_conclusion_supported", result.content)
        self.assertEqual(result.domain_proposals, [])
        self.assertEqual(store.get_candidate("cand-1").status, "candidate_demand")

    def test_store_rejects_report_without_approved_audit(self) -> None:
        for store, audit_id, expected_message in [
            (_seed_store(with_audit=False), "", "approved audit_id is required"),
            (
                _seed_store(audit_conclusion="needs_revision"),
                "audit-1",
                "audit audit-1 is not approved",
            ),
        ]:
            with self.subTest(expected_message=expected_message):
                store.update_candidate_status(
                    "cand-1", "demand_report", "promoted", actor="tester"
                )

                with self.assertRaisesRegex(ValueError, expected_message):
                    store.append_demand_report(
                        DemandReport(
                            report_id="report-1",
                            candidate_id="cand-1",
                            title="Report",
                            body="body",
                            evidence_ids=["ev-1"],
                            audit_id=audit_id,
                            domain_trace_ids=[],
                            created_at=NOW,
                        )
                    )

    def test_store_rejects_report_without_minimum_evidence(self) -> None:
        for store, evidence_ids, expected_message in [
            (_seed_store(), [], "at least one evidence_id is required"),
            (
                _seed_store(source_tier="C"),
                ["ev-1"],
                "minimum evidence requirement not met",
            ),
            (
                _seed_store(evidence_excerpt=None),
                ["ev-1"],
                "minimum evidence requirement not met",
            ),
        ]:
            with self.subTest(expected_message=expected_message):
                store.update_candidate_status(
                    "cand-1", "demand_report", "promoted", actor="tester"
                )

                with self.assertRaisesRegex(ValueError, expected_message):
                    store.append_demand_report(
                        DemandReport(
                            report_id="report-1",
                            candidate_id="cand-1",
                            title="Report",
                            body="body",
                            evidence_ids=evidence_ids,
                            audit_id="audit-1",
                            domain_trace_ids=[],
                            created_at=NOW,
                        )
                    )

    def test_store_rejects_conflicting_audit_decision_for_same_audit_id(self) -> None:
        store = _seed_store(audit_conclusion="approved")

        with self.assertRaisesRegex(
            ValueError,
            "audit_id audit-1 already exists with conclusion approved",
        ):
            store.append_audit(
                AuditReport(
                    audit_id="audit-1",
                    candidate_id="cand-1",
                    conclusion="rejected",
                    scorecard={},
                    comments="changed decision",
                    required_rework=["more evidence"],
                    created_by="tester",
                    created_at=NOW,
                )
            )

        self.assertEqual(store.audit_reports["audit-1"].conclusion, "approved")

    def test_run_audit_tool_rejects_conflicting_existing_audit_id(self) -> None:
        store = _seed_store(audit_conclusion="approved")
        tool = _get_tool(build_domain_tools(store), "run_audit")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "rejected",
                        "scorecard": {},
                        "comments": "changed decision",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("audit_id audit-1 already exists", result.content)
        self.assertEqual(result.domain_proposals, [])
        self.assertEqual(result.trace_proposals, [])


def _sections() -> dict[str, str]:
    return {section: f"{section} text" for section in REQUIRED_SECTIONS}


def _seed_store(
    *,
    with_audit: bool = True,
    audit_conclusion: str = "approved",
    source_tier: str = "A",
    evidence_excerpt: str | None = "supporting excerpt",
    evidence_support_verdict: str = "pass",
    rubric_overrides: dict[str, dict[str, str]] | None = None,
    omit_rubric_items: set[str] | None = None,
) -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source title",
            source_name="Source",
            source_tier=source_tier,
            source_type="journal",
            publish_time=NOW,
            url_or_path="https://example.test/source",
            summary_text="summary",
            summary_source="structured",
            collection_decision="use_as_evidence",
            author_or_org="Org",
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
            claim="claim one",
            evidence_summary="evidence summary",
            excerpt=evidence_excerpt,
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
            demand_statement="Need capability.",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="tester",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    if with_audit:
        store.append_audit(
            AuditReport(
                audit_id="audit-1",
                candidate_id="cand-1",
                conclusion=audit_conclusion,
                scorecard=_scorecard(
                    evidence_support_verdict=evidence_support_verdict,
                    rubric_overrides=rubric_overrides,
                    omit_rubric_items=omit_rubric_items,
                ),
                comments="ok",
                required_rework=[],
                created_by="tester",
                created_at=NOW,
            )
        )
    return store


def _scorecard(
    *,
    evidence_support_verdict: str = "pass",
    rubric_overrides: dict[str, dict[str, str]] | None = None,
    omit_rubric_items: set[str] | None = None,
) -> dict[str, object]:
    scorecard: dict[str, object] = {
        "evidence_support": {
            "verdict": evidence_support_verdict,
            "reason": "semantic audit",
            "evidence_reviews": {
                "ev-1": {
                    "evidence_id": "ev-1",
                    "support_level": "direct",
                    "support_type": "inferred_gap",
                    "used_for_core": True,
                    "reason": "body evidence supports the candidate",
                    "missing_link": "",
                }
            },
        }
    }
    scorecard.update(_passing_review_ready_rubric_items())
    for item_id, row in (rubric_overrides or {}).items():
        scorecard[item_id] = dict(row)
    for item_id in omit_rubric_items or set():
        scorecard.pop(item_id, None)
    return scorecard


def _passing_review_ready_rubric_items() -> dict[str, dict[str, str]]:
    return {
        "evidence_supports_candidate": {
            "verdict": "pass",
            "reason": "cited evidence semantically supports the candidate",
        },
        "core_conclusion_supported": {
            "verdict": "pass",
            "reason": "core conclusion is directly supported",
        },
        "adjacent_evidence_limited": {
            "verdict": "pass",
            "reason": "no adjacent evidence is used as core support",
        },
        "unassessed_evidence_handled": {
            "verdict": "pass",
            "reason": "all cited evidence is assessed",
        },
    }


def _get_tool(tools: list[ToolDefinition], name: str) -> ToolDefinition:
    return next(tool for tool in tools if tool.name == name)


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "worker-1", {})


if __name__ == "__main__":
    unittest.main()
