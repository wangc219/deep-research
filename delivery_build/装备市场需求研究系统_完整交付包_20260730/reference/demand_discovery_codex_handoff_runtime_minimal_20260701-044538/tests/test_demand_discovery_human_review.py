from __future__ import annotations

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
    DemandReport,
    EvidenceCard,
    HumanReviewRecord,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.review import (  # noqa: E402
    PushPlan,
    generate_push_lists,
    push_priority,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from scripts.demand_discovery_review import main as review_main  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryHumanReviewTests(unittest.TestCase):
    def test_append_human_review_updates_report_and_candidate_for_decisions(self) -> None:
        cases = [
            ("approved", "approved", "human_reviewed"),
            ("approved_with_changes", "approved", "human_reviewed"),
            ("needs_revision", "draft", "candidate_demand"),
            ("rejected", "rejected", "demand_report"),
            ("watchlist", "watchlist", "demand_report"),
        ]
        for decision, expected_report_status, expected_candidate_status in cases:
            with self.subTest(decision=decision):
                store = _seed_store()
                record = _review(decision)

                store.append_human_review(record)

                self.assertEqual(
                    store.demand_reports["report-1"].review_status,
                    expected_report_status,
                )
                self.assertEqual(
                    store.candidates["cand-1"].status,
                    expected_candidate_status,
                )
                self.assertEqual(store.human_reviews["review-1"].decision, decision)
                self.assertEqual(store.trace_events[-1].event_type, "human_reviewed")

    def test_sensitive_flag_backfills_from_audit_scorecard(self) -> None:
        store = _seed_store(sensitive_flag=True)

        self.assertTrue(store.demand_reports["report-1"].sensitive_review_required)

    def test_push_priority_rules(self) -> None:
        store = _seed_store()
        report = store.demand_reports["report-1"]
        audit = store.audit_reports["audit-1"]
        review = _review("approved")

        self.assertEqual(push_priority(report, audit, review), "immediate")
        self.assertEqual(push_priority(report, audit, _review("approved_with_changes")), "digest")
        self.assertEqual(push_priority(report, audit, _review("needs_revision")), "hold_for_evidence")
        self.assertEqual(push_priority(report, audit, _review("watchlist")), "watch_pool")
        self.assertEqual(push_priority(report, audit, _review("rejected")), "none")

    def test_generate_push_lists_writes_inbox_and_watchlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _seed_store()
            store.append_human_review(_review("approved"))
            out = PushPlan(Path(tmp) / "inbox.md", Path(tmp) / "watchlist.md")

            generate_push_lists(store, out)

            inbox = out.inbox_path.read_text(encoding="utf-8")
            watchlist = out.watchlist_path.read_text(encoding="utf-8")
            self.assertIn("## Immediate", inbox)
            self.assertIn("report-1", inbox)
            self.assertIn("## Watch Pool", watchlist)

    def test_review_cli_decide_round_trips_store_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "domain.jsonl"
            push_dir = Path(tmp) / "push"
            store = _seed_store()
            store.bind_jsonl(store_path)
            store.append_accepted_proposals([])
            store.export_append_only_snapshot()

            exit_code = review_main(
                [
                    "--store",
                    str(store_path),
                    "--push-dir",
                    str(push_dir),
                    "decide",
                    "report-1",
                    "--decision",
                    "approved",
                    "--reviewer",
                    "张三",
                    "--reason",
                    "证据链完整",
                    "--accepted-claims",
                    "claim one",
                ]
            )

            self.assertEqual(exit_code, 0)
            loaded = DomainStore.load_jsonl(store_path)
            self.assertEqual(
                loaded.demand_reports["report-1"].review_status,
                "approved",
            )
            self.assertIn("review-", next(iter(loaded.human_reviews)))
            self.assertTrue((push_dir / "inbox.md").exists())


def _seed_store(*, sensitive_flag: bool = False) -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source title",
            source_name="Source",
            source_tier="A",
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
            evidence_summary="summary",
            excerpt="excerpt",
            source_location="artifact:text-1#para:1",
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
    store.append_audit(
        AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="approved",
            scorecard=_scorecard(sensitive_flag=sensitive_flag),
            comments="ok",
            required_rework=[],
            created_by="auditor",
            created_at=NOW,
        )
    )
    store.update_candidate_status("cand-1", "demand_report", "promoted", actor="tester")
    store.append_demand_report(
        DemandReport(
            report_id="report-1",
            candidate_id="cand-1",
            title="Report",
            body="body",
            evidence_ids=["ev-1"],
            audit_id="audit-1",
            domain_trace_ids=[],
            created_at=NOW,
        )
    )
    store.update_report_review_status("report-1", "review_ready")
    return store


def _scorecard(*, sensitive_flag: bool) -> dict[str, object]:
    return {
        "sensitive_flag": {
            "verdict": "fail" if sensitive_flag else "pass",
            "reason": "sensitive" if sensitive_flag else "normal",
        },
        "evidence_support": {
            "verdict": "pass",
            "reason": "semantic audit",
            "evidence_reviews": {
                "ev-1": {
                    "evidence_id": "ev-1",
                    "support_level": "direct",
                    "support_type": "inferred_gap",
                    "used_for_core": True,
                    "reason": "body evidence supports the report",
                    "missing_link": "",
                }
            },
        },
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


def _review(decision: str) -> HumanReviewRecord:
    return HumanReviewRecord(
        review_id="review-1",
        report_id="report-1",
        reviewer="reviewer",
        review_time=NOW,
        decision=decision,
        decision_reason="reason",
        accepted_claims=["claim one"],
        rejected_claims=[],
        requested_changes=["revise"] if decision == "needs_revision" else [],
        notes="notes",
    )


if __name__ == "__main__":
    unittest.main()
