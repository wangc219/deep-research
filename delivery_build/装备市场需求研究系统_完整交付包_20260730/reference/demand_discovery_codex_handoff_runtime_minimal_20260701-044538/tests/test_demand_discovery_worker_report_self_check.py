from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.worker_research import WorkerSelfCheck  # noqa: E402
from knowledgegraph.demand_discovery.harness.worker_report import (  # noqa: E402
    WorkerReport,
    normalize_worker_report_evidence_policy,
    parse_worker_text,
)


class WorkerReportSelfCheckTests(unittest.TestCase):
    def test_parse_worker_text_captures_reader_sop_sections(self) -> None:
        parsed = parse_worker_text(
            """
findings:
- 未找到足够正文证据

evidence_ready_for_judge: false

stop_reason:
- whitelist_exhausted

remaining_gaps:
- 缺少公开正文交叉验证

suggested_next_routes:
- open_search_candidate true; query=远海保障 能力缺口

need_more_sources: true

risks:
- 白名单结果重复
"""
        )

        self.assertFalse(parsed["evidence_ready_for_judge"])
        self.assertEqual(parsed["stop_reason"], "whitelist_exhausted")
        self.assertEqual(parsed["remaining_gaps"], ["缺少公开正文交叉验证"])
        self.assertEqual(
            parsed["suggested_next_routes"],
            ["open_search_candidate true; query=远海保障 能力缺口"],
        )
        self.assertTrue(parsed["need_more_sources"])

    def test_strong_finding_without_evidence_is_demoted(self) -> None:
        report = WorkerReport(
            agent_run_id="agent-1",
            role="reader",
            status="completed",
            partial_findings=["强结论：远海保障存在体系缺口"],
            evidence_refs=[],
            open_questions=[],
            discarded_findings=[],
        )

        normalized = normalize_worker_report_evidence_policy(report)

        self.assertEqual(normalized.partial_findings, [])
        self.assertIn("强结论：远海保障存在体系缺口", normalized.discarded_findings)
        self.assertIn(
            "strong finding missing evidence refs",
            normalized.evidence_quality_notes,
        )

    def test_self_check_and_follow_up_fields_are_serialized(self) -> None:
        self_check = WorkerSelfCheck(
            check_id="selfcheck-1",
            assignment_id="assignment-1",
            round_id="round-1",
            topic_alignment="direct",
            body_evidence_count=1,
            direct_evidence_count=1,
            partial_evidence_count=0,
            adjacent_evidence_count=0,
            source_diversity=1,
            article_body_read_count=1,
            downloaded_document_read_count=0,
            listing_or_search_only_count=0,
            queries_used=["远海保障"],
            routes_used=["search"],
            browser_actions_used=[],
            javascript_actions_used=[],
            unverified_claims=[],
            discarded_findings=[],
            contradiction_candidates=[],
            follow_up_required=False,
            follow_up_reason="",
            follow_up_actions_taken=[],
            remaining_blind_spots=[],
            allowed_to_finish=True,
        )
        report = WorkerReport(
            agent_run_id="agent-1",
            role="reader",
            status="completed",
            assignment_id="assignment-1",
            source_id="source-a",
            queries_used=["远海保障"],
            routes_used=["search"],
            self_check=self_check,
            follow_up_instructions=["followup-1"],
            follow_up_attempt_count=1,
            artifact_refs=["artifact-1"],
            evidence_refs=["ev-1"],
            partial_findings=["远海保障缺口由 ev-1 支撑"],
        )

        data = report.to_dict()

        self.assertEqual(data["assignment_id"], "assignment-1")
        self.assertEqual(data["source_id"], "source-a")
        self.assertEqual(data["self_check"]["check_id"], "selfcheck-1")
        self.assertEqual(data["follow_up_attempt_count"], 1)
        self.assertEqual(data["artifact_refs"], ["artifact-1"])


if __name__ == "__main__":
    unittest.main()
