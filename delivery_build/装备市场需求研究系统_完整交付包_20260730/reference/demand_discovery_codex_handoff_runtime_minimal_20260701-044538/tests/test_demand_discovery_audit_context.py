from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.audit_context import (  # noqa: E402
    build_audit_context_bundle,
)


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class AuditContextTests(unittest.TestCase):
    def test_bundle_contains_candidate_judgement_evidence_and_source_summary(self) -> None:
        store = _store()
        judgement = JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(text="远海保障缺口", worker_report_ids=["agent-1"], evidence_ids=["ev-1"])
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[JudgementItem(text="缺少反证", worker_report_ids=["agent-1"])],
            evidence_strength_map={"ev-1": "direct"},
            next_round_plan={"remaining_open_questions": ["缺少反证"]},
            stop_or_continue="stop",
            rationale="ready for audit",
            created_at=NOW,
        )
        store.upsert_judgement_report(judgement)

        bundle = build_audit_context_bundle(
            store,
            candidate_id="cand-1",
            judgement_id="judge-1",
            report_core_conclusion="远海保障存在能力缺口",
            artifact_windows={"artifact-html": "<html>" + ("x" * 5000) + "</html>"},
        )

        text = bundle.render()
        self.assertIn("cand-1", text)
        self.assertIn("judge-1", text)
        self.assertIn("ev-1", text)
        self.assertIn("source_tier", text)
        self.assertIn("report_core_conclusion", text)
        self.assertNotIn("x" * 1000, text)

    def test_bundle_contains_source_quality_assessment_for_open_source_evidence(self) -> None:
        store = _open_source_store()
        store.upsert_judgement_report(
            JudgementReport(
                judgement_id="judge-1",
                round_id="round-1",
                consensus_points=[
                    JudgementItem(text="远海保障缺口", worker_report_ids=["agent-1"], evidence_ids=["ev-1"])
                ],
                contradictions=[],
                partial_coverage=[],
                unique_insights=[],
                blind_spots=[],
                evidence_strength_map={"ev-1": "partial"},
                next_round_plan={},
                stop_or_continue="stop",
                rationale="ready for audit",
                created_at=NOW,
            )
        )

        bundle = build_audit_context_bundle(
            store,
            candidate_id="cand-1",
            judgement_id="judge-1",
            report_core_conclusion="远海保障存在能力缺口",
        )

        evidence_item = bundle.to_dict()["evidence_bundle"][0]
        self.assertEqual(evidence_item["source_quality"]["source_quality_assessment_id"], "sqa-1")
        self.assertEqual(evidence_item["source_quality"]["quality_level"], "usable")
        self.assertEqual(evidence_item["source_quality"]["open_source_lead_id"], "lead-1")
        self.assertEqual(evidence_item["source_quality"]["basis_artifact_refs"], ["artifact:lead-1"])
        self.assertEqual(evidence_item["source_quality"]["body_location_refs"], ["body:lead-1#p1"])
        self.assertIn("正文段落", evidence_item["source_quality"]["reason"])


def _store() -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Fixture",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/article",
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
            claim="远海保障存在能力缺口",
            evidence_summary="正文说明能力缺口",
            excerpt="正文段落",
            source_location="text:article#para:3",
            evidence_assessment="direct",
            created_by="reader",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="远海保障需要补足能力缺口",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _open_source_store() -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="plan-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海医疗保障能力缺口",
            trigger_judgement_id="judge-0",
            trigger_reason="需要开放来源补证",
            queries=["远海 医疗保障 能力 缺口"],
            allowed_result_count=2,
            status="running",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_lead(
        OpenSourceLead(
            lead_id="lead-1",
            plan_id="plan-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海医疗保障能力缺口",
            url="https://open.example.test/article",
            domain="open.example.test",
            title="Open Article",
            snippet="snippet",
            source_name_guess="Open Example",
            search_query="远海 医疗保障 能力 缺口",
            source_scope="open_web",
            quality_status="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_body_artifact(
        OpenSourceBodyArtifact(
            body_id="body-1",
            lead_id="lead-1",
            plan_id="plan-1",
            url="https://open.example.test/article",
            final_url="https://open.example.test/article",
            content_type="text/html",
            artifact_ref="artifact:lead-1",
            simplified_ref="simplified:lead-1",
            body_location_prefix="body:lead-1",
            fetched_by="worker",
            created_at=NOW,
        )
    )
    store.upsert_source_quality_assessment(
        SourceQualityAssessment(
            assessment_id="sqa-1",
            lead_id="lead-1",
            url="https://open.example.test/article",
            domain="open.example.test",
            basis_artifact_refs=["artifact:lead-1"],
            body_location_refs=["body:lead-1#p1"],
            read_document_ref="read:lead-1",
            source_identity="Open Example",
            publisher_or_org="Open Example",
            author="",
            publish_time="2026-06-24",
            is_original_source=True,
            citation_or_reference_signal="正文自述",
            content_type="text/html",
            quality_level="usable",
            risk_flags=[],
            reason="基于 body:lead-1#p1 正文段落判断为可用来源",
            created_by="worker",
            created_at=NOW,
        )
    )
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Open Article",
            source_name="Open Example",
            source_tier="open",
            source_type="open_web",
            publish_time=NOW,
            url_or_path="https://open.example.test/article",
            summary_text="summary",
            summary_source="open_search",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
            open_source_lead_id="lead-1",
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="远海保障存在能力缺口",
            evidence_summary="开放正文说明能力缺口",
            excerpt="正文段落",
            source_location="body:lead-1#p1",
            evidence_assessment="partial",
            created_by="reader",
            created_at=NOW,
            source_quality_assessment_id="sqa-1",
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="远海保障需要补足能力缺口",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=[],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


if __name__ == "__main__":
    unittest.main()
