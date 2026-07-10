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
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.report_consistency import (  # noqa: E402
    validate_report_consistency,
)
from knowledgegraph.demand_discovery.domain.report_context import (  # noqa: E402
    CuratedReportItem,
    ReportContextBundle,
    ReportContextMaterial,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import generate_demand_report_tool  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class ReportConsistencyGateTests(unittest.TestCase):
    def test_rejects_evidence_outside_bundle_and_blocked_claims(self) -> None:
        errors = validate_report_consistency(
            _bundle(blocked_claims=["已形成成熟装备体系"]),
            report_body="核心结论：已形成成熟装备体系。引用 ev-2。",
            evidence_ids=["ev-2"],
            domain_trace_ids=["dt-candidate", "dt-audit"],
        )

        self.assertIn("evidence_id not allowed by ReportContextBundle: ev-2", errors)
        self.assertIn("blocked claim appears in report body: 已形成成熟装备体系", errors)

    def test_report_tool_uses_bundle_review_status_for_degraded_business_outcome(self) -> None:
        store = _seed_store()
        bundle = _bundle(review_status="needs_revision", required_caveats=["样本有限"])
        store.upsert_report_context_bundle(bundle)
        tool = generate_demand_report_tool(store)

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-report",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "body": "样本有限，因此只能形成阶段性判断。",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                        "domain_trace_ids": ["dt-candidate", "dt-audit"],
                        "report_context_bundle_id": bundle.bundle_id,
                        "review_status": "needs_revision",
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "reporter", {}),
            )
        )

        self.assertFalse(result.is_error, result.content)
        payload = next(
            proposal.payload
            for proposal in result.domain_proposals
            if proposal.object_type == "DemandReport"
        )
        self.assertEqual(payload["review_status"], "needs_revision")

    def test_report_tool_fails_on_consistency_error_without_demand_report(self) -> None:
        store = _seed_store()
        bundle = _bundle(required_caveats=["样本有限"])
        store.upsert_report_context_bundle(bundle)
        tool = generate_demand_report_tool(store)

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-report",
                    tool.name,
                    {
                        "report_id": "report-1",
                        "candidate_id": "cand-1",
                        "title": "Report",
                        "body": "核心结论：可直接定论。",
                        "evidence_ids": ["ev-1"],
                        "audit_id": "audit-1",
                        "domain_trace_ids": ["dt-candidate"],
                        "report_context_bundle_id": bundle.bundle_id,
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "reporter", {}),
            )
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.domain_proposals, [])
        self.assertIn("required caveat missing", result.content)


def _bundle(
    *,
    review_status: str = "needs_revision",
    blocked_claims: list[str] | None = None,
    required_caveats: list[str] | None = None,
) -> ReportContextBundle:
    return ReportContextBundle(
        bundle_id="rcb-1",
        run_id="run-1",
        topic="远海医疗保障能力缺口",
        candidate_id="cand-1",
        judgement_id="judge-1",
        audit_id="audit-1",
        review_status=review_status,
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
        blocked_claims=list(blocked_claims or []),
        required_caveats=list(required_caveats or []),
        created_at=NOW,
    )


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


if __name__ == "__main__":
    unittest.main()
