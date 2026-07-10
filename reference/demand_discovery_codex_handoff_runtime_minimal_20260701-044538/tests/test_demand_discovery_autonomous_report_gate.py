from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.audit_rubric import AuditRubric  # noqa: E402
from knowledgegraph.demand_discovery.domain.judgement import JudgementItem, JudgementReport  # noqa: E402
from knowledgegraph.demand_discovery.domain.models import AuditReport, CandidateDemand, EvidenceCard, SourceRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.report import (  # noqa: E402
    determine_autonomous_report_review_status,
    validate_autonomous_report_gate,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryAutonomousReportGateTests(unittest.TestCase):
    def test_autonomous_report_gate_requires_stop_judgement(self) -> None:
        store = _store(collection_decision="use_as_evidence")

        with self.assertRaisesRegex(ValueError, "JudgementReport"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-missing",
            )

    def test_navigation_or_listing_evidence_cannot_singlehandedly_pass(self) -> None:
        store = _store(
            collection_decision="use_as_background",
            source_location="listing:source#item:1",
        )
        store.upsert_judgement_report(_judgement(contradictions=[]))

        with self.assertRaisesRegex(ValueError, "article body or downloaded document body"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-1",
            )

    def test_weak_or_adjacent_evidence_cannot_pass_autonomous_report_gate(self) -> None:
        store = _store(
            collection_decision="use_as_evidence",
            evidence_assessment=(
                "中等偏弱：正文证据明确，但为相邻材料，不直接证明当前调研主题"
            ),
        )
        store.upsert_judgement_report(
            _judgement(
                contradictions=[],
                evidence_strength_map={
                    "ev-1": "中等偏弱：相邻材料，不直接证明当前调研主题"
                },
            )
        )

        with self.assertRaisesRegex(ValueError, "strong or direct"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-1",
            )

    def test_unexplained_contradiction_downgrades_report_status(self) -> None:
        judgement = _judgement(
            contradictions=[
                JudgementItem(
                    text="雷达和光电覆盖边界冲突",
                    worker_report_ids=["agent-1", "agent-2"],
                    evidence_ids=["ev-1"],
                )
            ]
        )

        self.assertEqual(
            determine_autonomous_report_review_status(judgement),
            "needs_revision",
        )
        judgement.next_round_plan["resolved_contradictions"] = ["雷达和光电覆盖边界冲突"]
        self.assertEqual(
            determine_autonomous_report_review_status(judgement),
            "review_ready",
        )


def _store(
    *,
    collection_decision: str,
    evidence_assessment: str = "strong",
    source_location: str = "text:abc#para:0",
) -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Fixture",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/listing",
            summary_text="summary",
            summary_source="manual",
            collection_decision=collection_decision,
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
            claim="需要多源探测",
            evidence_summary="summary",
            excerpt="正文证据" if collection_decision == "use_as_evidence" else "栏目标题",
            source_location=source_location,
            evidence_assessment=evidence_assessment,
            created_by="reader",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="需要多源探测",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=["缺少处置链路"],
            solution_signals=[],
            created_by="synthesis",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="approved",
            scorecard={},
            comments="approved",
            required_rework=[],
            created_by="auditor",
            created_at=NOW,
        )
    )
    return store


def _judgement(
    *,
    contradictions: list[JudgementItem],
    evidence_strength_map: dict[str, str] | None = None,
) -> JudgementReport:
    return JudgementReport(
        judgement_id="judge-1",
        round_id="round-1",
        consensus_points=[
            JudgementItem(
                text="需要多源探测",
                worker_report_ids=["agent-1"],
                evidence_ids=["ev-1"],
            )
        ],
        contradictions=contradictions,
        partial_coverage=[],
        unique_insights=[],
        blind_spots=[],
        evidence_strength_map=evidence_strength_map or {"ev-1": "strong"},
        next_round_plan={},
        stop_or_continue="stop",
        rationale="stop",
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
