from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.worker_research import (  # noqa: E402
    FollowUpInstruction,
    WorkerSelfCheck,
)


def _check() -> WorkerSelfCheck:
    return WorkerSelfCheck(
        check_id="selfcheck-1",
        assignment_id="assignment-1",
        round_id="round-1",
        topic_alignment="adjacent",
        body_evidence_count=1,
        direct_evidence_count=0,
        partial_evidence_count=1,
        adjacent_evidence_count=0,
        source_diversity=1,
        article_body_read_count=1,
        downloaded_document_read_count=0,
        listing_or_search_only_count=0,
        queries_used=["远海医疗保障"],
        routes_used=["search"],
        browser_actions_used=[],
        javascript_actions_used=[],
        unverified_claims=["缺少任务场景证据"],
        discarded_findings=["把医院体系材料当作舰艇保障需求"],
        contradiction_candidates=[],
        follow_up_required=True,
        follow_up_reason="direct_evidence_missing",
        follow_up_actions_taken=[],
        remaining_blind_spots=["缺少远海场景正文证据"],
        allowed_to_finish=False,
    )


def _instruction() -> FollowUpInstruction:
    return FollowUpInstruction(
        instruction_id="followup-1",
        assignment_id="assignment-1",
        round_id="round-1",
        trigger_check_id="selfcheck-1",
        reason="direct_evidence_missing",
        allowed_tools=["search_sources", "read_document"],
        target_source_id="source-a",
        query_revisions=[{"language": "zh", "query": "远海医疗保障 舰艇"}],
        route_revisions=["站内搜索"],
        expected_outputs=["正文 artifact"],
        stop_after={"max_follow_up_turns": 3},
    )


class WorkerResearchStoreTests(unittest.TestCase):
    def test_export_and_append_only_round_trip_worker_research_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "domain-export.jsonl"
            append_path = Path(tmp) / "domain-append.jsonl"
            store = DomainStore()
            store.upsert_worker_self_check(_check())
            store.upsert_follow_up_instruction(_instruction())

            store.export_jsonl(export_path)
            loaded_export = DomainStore.load_jsonl(export_path)
            store.export_append_only_snapshot(append_path)
            loaded_append = DomainStore.load_jsonl(append_path)

        self.assertEqual(
            loaded_export.worker_self_checks["selfcheck-1"].to_dict(),
            _check().to_dict(),
        )
        self.assertEqual(
            loaded_export.follow_up_instructions["followup-1"].to_dict(),
            _instruction().to_dict(),
        )
        self.assertIn("selfcheck-1", loaded_append.worker_self_checks)
        self.assertIn("followup-1", loaded_append.follow_up_instructions)


if __name__ == "__main__":
    unittest.main()
