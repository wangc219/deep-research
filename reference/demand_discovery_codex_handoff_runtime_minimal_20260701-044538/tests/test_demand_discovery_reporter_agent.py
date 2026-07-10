from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.report_context import (  # noqa: E402
    CuratedReportItem,
    ReportContextBundle,
    ReportContextMaterial,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.reporter import run_reporter_agent  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class ReporterAgentTests(unittest.TestCase):
    def test_reporter_agent_writes_demand_report_through_allowed_tools(self) -> None:
        store = _seed_store()
        bundle = _bundle()
        store.upsert_report_context_bundle(bundle)
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
                                "body": "样本有限，因此只能形成阶段性判断。",
                                "evidence_ids": ["ev-1"],
                                "audit_id": "audit-1",
                                "domain_trace_ids": ["dt-candidate", "dt-audit"],
                                "report_context_bundle_id": "rcb-1",
                            },
                        }
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_reporter_agent(
                    provider=provider,
                    store=store,
                    artifacts=ArtifactStore(Path(tmp) / "artifacts"),
                    bundle_id="rcb-1",
                    session_path=Path(tmp) / "reporter.jsonl",
                    system_prompt="reporter system",
                )
            )

        self.assertEqual(result.report_id, "report-1")
        self.assertIn("report-1", store.demand_reports)
        self.assertEqual(store.demand_reports["report-1"].review_status, "needs_revision")
        self.assertIn("report_generated", [event.event_type for event in store.trace_events])
        self.assertEqual(provider.pending_count(), 0)

    def test_reporter_prompt_exposes_full_report_context_bundle(self) -> None:
        store = _seed_store()
        bundle = _bundle()
        store.upsert_report_context_bundle(bundle)
        provider = FakeProvider()

        def assert_bundle_visible(context, state):
            del state
            prompt_text = "\n\n".join(str(message.content) for message in context.messages)
            if "report_context_bundle" not in prompt_text or "curated_items" not in prompt_text:
                raise AssertionError("ReportContextBundle was not visible to reporter")
            return AssistantMessage(
                content=[
                    AssistantContentBlock(
                        type="tool_call",
                        id="call-report",
                        name="generate_demand_report",
                        arguments={
                            "report_id": "report-1",
                            "candidate_id": "cand-1",
                            "title": "Report",
                            "body": "样本有限，因此只能形成阶段性判断。",
                            "evidence_ids": ["ev-1"],
                            "audit_id": "audit-1",
                            "domain_trace_ids": ["dt-candidate", "dt-audit"],
                            "report_context_bundle_id": "rcb-1",
                        },
                    )
                ]
            )

        provider.set_responses(
            [FakeResponse(factory=assert_bundle_visible), FakeResponse(text="done")]
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_reporter_agent(
                    provider=provider,
                    store=store,
                    artifacts=ArtifactStore(Path(tmp) / "artifacts"),
                    bundle_id="rcb-1",
                    session_path=Path(tmp) / "reporter.jsonl",
                    system_prompt="reporter system",
                )
            )

        self.assertEqual(result.report_id, "report-1")


def _seed_store() -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Official",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/a",
            summary_text="summary",
            summary_source="manual",
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
            excerpt="正文窗口",
            source_location="text:abc#para:1",
            evidence_assessment="direct",
            created_by="reader",
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
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="needs_revision",
            scorecard={"evidence_support": {"evidence_reviews": {}}},
            comments="needs more evidence",
            required_rework=["样本有限"],
            created_by="auditor",
            created_at=NOW,
        )
    )
    return store


def _bundle() -> ReportContextBundle:
    return ReportContextBundle(
        bundle_id="rcb-1",
        run_id="run-1",
        topic="远海医疗保障能力缺口",
        candidate_id="cand-1",
        judgement_id="judge-1",
        audit_id="audit-1",
        review_status="needs_revision",
        control_brief={},
        lineage_trace=[
            {"domain_trace_id": "dt-candidate", "event_type": "candidate_synthesized"},
            {"domain_trace_id": "dt-audit", "event_type": "audit_completed"},
        ],
        materials=[
            ReportContextMaterial(
                material_id="mat-1",
                material_type="evidence",
                title="证据",
                summary="summary",
                refs={"evidence_ids": ["ev-1"]},
                window_text="正文窗口",
                source_location="text:abc#para:1",
                allowed_report_uses=["core"],
                risk_flags=[],
            )
        ],
        curated_items=[
            CuratedReportItem(
                item_id="cur-1",
                material_ids=["mat-1"],
                report_use="core",
                claim_summary="存在能力缺口",
                curation_reason="direct",
            )
        ],
        verifier_warnings=[],
        allowed_evidence_ids=["ev-1"],
        blocked_claims=[],
        required_caveats=["样本有限"],
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
