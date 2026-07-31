from __future__ import annotations

from dataclasses import replace
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
    AuditReport,
    CandidateDemand,
    DemandReport,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.report import (  # noqa: E402
    determine_autonomous_report_review_status,
    validate_autonomous_report_gate,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class AutonomousReportGateEvidenceSupportTests(unittest.TestCase):
    def test_adjacent_only_audit_downgrades_to_needs_revision(self) -> None:
        store = _store_with_audit("adjacent", audit_conclusion="approved")
        judgement = store.judgement_reports["judge-1"]
        audit = store.audit_reports["audit-1"]

        status = determine_autonomous_report_review_status(
            judgement,
            audit=audit,
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "needs_revision")

    def test_unassessed_evidence_downgrades_and_records_rework(self) -> None:
        store = _store_with_audit("unassessed", audit_conclusion="needs_revision")
        audit = store.audit_reports["audit-1"]
        judgement = store.judgement_reports["judge-1"]

        status = determine_autonomous_report_review_status(
            judgement,
            audit=audit,
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "needs_revision")
        self.assertTrue(audit.required_rework)

    def test_direct_evidence_with_semantic_audit_can_pass_gate(self) -> None:
        store = _store_with_audit("direct", audit_conclusion="approved")

        validate_autonomous_report_gate(
            store,
            candidate_id="cand-1",
            audit_id="audit-1",
            evidence_ids=["ev-1"],
            judgement_id="judge-1",
            review_status="review_ready",
        )
        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "review_ready")

    def test_evidence_support_doubt_downgrades_review_status(self) -> None:
        store = _store_with_audit(
            "direct",
            audit_conclusion="approved",
            evidence_support_verdict="doubt",
        )

        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "needs_revision")
        with self.assertRaisesRegex(ValueError, "evidence_support verdict"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-1",
                review_status="review_ready",
            )

    def test_key_rubric_doubt_downgrades_review_status(self) -> None:
        store = _store_with_audit(
            "direct",
            audit_conclusion="approved",
            rubric_overrides={
                "evidence_supports_candidate": {
                    "verdict": "doubt",
                    "reason": "candidate support still needs review",
                }
            },
        )

        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "needs_revision")
        with self.assertRaisesRegex(ValueError, "evidence_supports_candidate"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-1",
                review_status="review_ready",
            )

    def test_missing_required_rubric_item_downgrades_review_status(self) -> None:
        for item_id in ["evidence_supports_candidate", "core_conclusion_supported"]:
            with self.subTest(item_id=item_id):
                store = _store_with_audit(
                    "direct",
                    audit_conclusion="approved",
                    omit_rubric_items={item_id},
                )

                status = determine_autonomous_report_review_status(
                    store.judgement_reports["judge-1"],
                    audit=store.audit_reports["audit-1"],
                    store=store,
                    evidence_ids=["ev-1"],
                )

                self.assertEqual(status, "needs_revision")
                with self.assertRaisesRegex(ValueError, item_id):
                    validate_autonomous_report_gate(
                        store,
                        candidate_id="cand-1",
                        audit_id="audit-1",
                        evidence_ids=["ev-1"],
                        judgement_id="judge-1",
                        review_status="review_ready",
                    )

    def test_needs_revision_report_can_be_appended_with_non_approved_semantic_audit(self) -> None:
        store = _store_with_audit("unassessed", audit_conclusion="needs_revision")
        store.candidates["cand-1"] = replace(
            store.candidates["cand-1"],
            status="demand_report",
        )
        report = DemandReport(
            report_id="report-1",
            candidate_id="cand-1",
            title="Needs revision report",
            body="## 审计结论\nsemantic audit\n\n## 必要返工\n- 证据未完成语义审查",
            evidence_ids=["ev-1"],
            audit_id="audit-1",
            domain_trace_ids=[],
            created_at=NOW,
            review_status="needs_revision",
        )

        appended = store.append_demand_report(report)

        self.assertEqual(appended.review_status, "needs_revision")

    def test_review_ready_still_requires_approved_audit(self) -> None:
        store = _store_with_audit("direct", audit_conclusion="needs_revision")
        store.candidates["cand-1"] = replace(
            store.candidates["cand-1"],
            status="demand_report",
        )
        report = DemandReport(
            report_id="report-1",
            candidate_id="cand-1",
            title="Invalid ready report",
            body="body",
            evidence_ids=["ev-1"],
            audit_id="audit-1",
            domain_trace_ids=[],
            created_at=NOW,
            review_status="review_ready",
        )

        with self.assertRaisesRegex(ValueError, "review_ready report requires approved audit"):
            store.append_demand_report(report)

    def test_listing_location_cannot_be_review_ready_even_when_audit_marks_direct(self) -> None:
        store = _store_with_audit(
            "direct",
            audit_conclusion="approved",
            source_location="listing:source#item:1",
        )

        with self.assertRaisesRegex(ValueError, "article body or downloaded document body"):
            validate_autonomous_report_gate(
                store,
                candidate_id="cand-1",
                audit_id="audit-1",
                evidence_ids=["ev-1"],
                judgement_id="judge-1",
                review_status="review_ready",
            )

    def test_watchlist_recommendation_with_recheck_conditions_sets_watchlist(self) -> None:
        store = _store_with_audit(
            "adjacent",
            audit_conclusion="approved",
            recommended_report_status="watchlist",
            recheck_conditions=["等待新的 A/B 级正文来源确认该信号"],
        )

        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "watchlist")
        validate_autonomous_report_gate(
            store,
            candidate_id="cand-1",
            audit_id="audit-1",
            evidence_ids=["ev-1"],
            judgement_id="judge-1",
            review_status="watchlist",
        )

    def test_watchlist_recommendation_without_recheck_conditions_needs_revision(self) -> None:
        store = _store_with_audit(
            "adjacent",
            audit_conclusion="approved",
            recommended_report_status="watchlist",
            recheck_conditions=[],
        )

        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "needs_revision")

    def test_watchlist_recommendation_cannot_override_irrelevant_core_support(self) -> None:
        store = _store_with_audit(
            "irrelevant",
            audit_conclusion="approved",
            recommended_report_status="watchlist",
            recheck_conditions=["等待新来源"],
        )

        status = determine_autonomous_report_review_status(
            store.judgement_reports["judge-1"],
            audit=store.audit_reports["audit-1"],
            store=store,
            evidence_ids=["ev-1"],
        )

        self.assertEqual(status, "rejected")


def _store_with_audit(
    level: str,
    *,
    audit_conclusion: str,
    source_location: str = "text:article#para:3",
    evidence_support_verdict: str | None = None,
    recommended_report_status: str = "",
    recheck_conditions: list[str] | None = None,
    rubric_overrides: dict[str, dict[str, str]] | None = None,
    omit_rubric_items: set[str] | None = None,
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
            source_location=source_location,
            evidence_assessment=level,
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
    store.upsert_judgement_report(
        JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(
                    text="远海保障缺口",
                    worker_report_ids=["agent-1"],
                    evidence_ids=["ev-1"],
                )
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={"ev-1": level},
            next_round_plan={},
            stop_or_continue="stop",
            rationale="stop",
            created_at=NOW,
        )
    )
    rework = ["证据未完成语义审查"] if level == "unassessed" else []
    scorecard = {
        "evidence_support": {
            "verdict": evidence_support_verdict
            or ("pass" if level == "direct" else "doubt"),
            "reason": "semantic audit",
            "evidence_reviews": {
                "ev-1": {
                    "support_level": level,
                    "support_type": (
                        "irrelevant"
                        if level == "irrelevant"
                        else "inferred_gap"
                        if level == "direct"
                        else "context_only"
                    ),
                    "used_for_core": True,
                    "reason": "audit reason",
                    "missing_link": "" if level == "direct" else "缺少能力缺口推理链",
                }
            },
        }
    }
    if recommended_report_status:
        support = scorecard["evidence_support"]
        support["recommended_report_status"] = recommended_report_status
        support["status_reason"] = "audit disposition"
        support["recheck_conditions"] = list(recheck_conditions or [])
    scorecard.update(_passing_review_ready_rubric_items())
    for item_id, row in (rubric_overrides or {}).items():
        scorecard[item_id] = dict(row)
    for item_id in omit_rubric_items or set():
        scorecard.pop(item_id, None)
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion=audit_conclusion,
            scorecard=scorecard,
            comments="semantic audit",
            required_rework=rework,
            created_by="auditor",
            created_at=NOW,
        )
    )
    return store


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


if __name__ == "__main__":
    unittest.main()
