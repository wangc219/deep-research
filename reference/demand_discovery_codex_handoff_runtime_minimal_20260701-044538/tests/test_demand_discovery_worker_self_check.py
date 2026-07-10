from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.worker_research import (  # noqa: E402
    FollowUpInstruction,
    evaluate_worker_self_check,
)


class WorkerSelfCheckTests(unittest.TestCase):
    def test_weak_alignment_requires_follow_up(self) -> None:
        check = evaluate_worker_self_check(
            assignment_id="assignment-1",
            round_id="round-1",
            topic_alignment="weak",
            body_evidence_count=1,
            direct_evidence_count=0,
            partial_evidence_count=0,
            adjacent_evidence_count=1,
            article_body_read_count=1,
            downloaded_document_read_count=0,
            listing_or_search_only_count=0,
            unverified_claims=["需要证明该材料直接讨论目标 topic"],
            strong_finding_count=1,
            strong_finding_evidence_ref_count=0,
            queries_used=["综合保障 能力缺口"],
            routes_used=["source-search"],
        )

        self.assertFalse(check.allowed_to_finish)
        self.assertTrue(check.follow_up_required)
        self.assertEqual(check.follow_up_reason, "topic_alignment_weak")
        self.assertIn("需要证明该材料直接讨论目标 topic", check.remaining_blind_spots)

    def test_direct_evidence_allows_finish(self) -> None:
        check = evaluate_worker_self_check(
            assignment_id="assignment-2",
            round_id="round-1",
            topic_alignment="direct",
            body_evidence_count=1,
            direct_evidence_count=1,
            partial_evidence_count=0,
            adjacent_evidence_count=0,
            article_body_read_count=1,
            downloaded_document_read_count=0,
            listing_or_search_only_count=0,
            unverified_claims=[],
            strong_finding_count=1,
            strong_finding_evidence_ref_count=1,
            queries_used=["military logistics contested environment"],
            routes_used=["source-search"],
        )

        self.assertTrue(check.allowed_to_finish)
        self.assertFalse(check.follow_up_required)

    def test_listing_only_never_passes(self) -> None:
        check = evaluate_worker_self_check(
            assignment_id="assignment-3",
            round_id="round-1",
            topic_alignment="direct",
            body_evidence_count=0,
            direct_evidence_count=0,
            partial_evidence_count=0,
            adjacent_evidence_count=0,
            article_body_read_count=0,
            downloaded_document_read_count=0,
            listing_or_search_only_count=3,
            unverified_claims=[],
            strong_finding_count=0,
            strong_finding_evidence_ref_count=0,
            queries_used=["naval medical support"],
            routes_used=["listing-page"],
        )

        self.assertFalse(check.allowed_to_finish)
        self.assertEqual(check.follow_up_reason, "body_evidence_missing")
        self.assertIn("只读取到 listing/search/home 页面", check.remaining_blind_spots)

    def test_follow_up_instruction_serializes_allowed_tools(self) -> None:
        instruction = FollowUpInstruction(
            instruction_id="followup-1",
            assignment_id="assignment-1",
            round_id="round-1",
            trigger_check_id="selfcheck-1",
            reason="direct_evidence_missing",
            allowed_tools=["search_sources", "fetch_page", "read_document"],
            target_source_id="source-a",
            query_revisions=[{"language": "zh", "query": "远海补给 医疗保障 能力缺口"}],
            route_revisions=["站内搜索", "专题栏目"],
            expected_outputs=["至少一个正文 artifact", "解释 direct/adjacent 判断"],
            stop_after={"max_follow_up_turns": 3, "max_new_pages": 5},
        )

        data = instruction.to_dict()
        self.assertEqual(data["reason"], "direct_evidence_missing")
        self.assertEqual(
            data["allowed_tools"], ["search_sources", "fetch_page", "read_document"]
        )
        self.assertIn("远海补给", instruction.to_prompt())


if __name__ == "__main__":
    unittest.main()
