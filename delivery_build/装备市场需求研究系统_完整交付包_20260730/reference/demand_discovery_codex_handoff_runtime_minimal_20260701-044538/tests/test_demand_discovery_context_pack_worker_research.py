from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.worker_research import (  # noqa: E402
    FollowUpInstruction,
    WorkerSelfCheck,
)
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder  # noqa: E402


class ContextPackWorkerResearchTests(unittest.TestCase):
    def test_context_pack_includes_worker_self_check_without_full_html(self) -> None:
        store = DomainStore()
        store.upsert_worker_self_check(
            WorkerSelfCheck(
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
                queries_used=["极地通信保障"],
                routes_used=["search"],
                browser_actions_used=[],
                javascript_actions_used=[],
                unverified_claims=["缺少任务场景"],
                discarded_findings=["把通用通信材料当作极地保障需求"],
                contradiction_candidates=[],
                follow_up_required=True,
                follow_up_reason="direct_evidence_missing",
                follow_up_actions_taken=[],
                remaining_blind_spots=["缺少极地场景正文"],
                allowed_to_finish=False,
            )
        )
        store.upsert_follow_up_instruction(
            FollowUpInstruction(
                instruction_id="followup-1",
                assignment_id="assignment-1",
                round_id="round-1",
                trigger_check_id="selfcheck-1",
                reason="direct_evidence_missing",
                allowed_tools=["search_sources", "read_document"],
                target_source_id="source-a",
                query_revisions=[{"language": "zh", "query": "极地 通信保障"}],
                route_revisions=["站内搜索"],
                expected_outputs=["正文 artifact"],
                stop_after={"max_follow_up_turns": 2},
            )
        )

        pack = ContextPackBuilder().build(
            agent_role="reading_worker",
            task_brief="极地通信保障能力缺口",
            run_state={
                "worker_self_checks": [
                    item.to_dict() for item in store.worker_self_checks.values()
                ],
                "follow_up_instructions": [
                    item.to_dict() for item in store.follow_up_instructions.values()
                ],
                "artifacts": [
                    {"artifact_id": "artifact-html", "content": "<html>" + ("x" * 5000)}
                ],
            },
            token_budget=1200,
        )

        text = pack.render()
        self.assertIn("selfcheck-1", text)
        self.assertIn("direct_evidence_missing", text)
        self.assertIn("followup-1", text)
        self.assertNotIn("x" * 1000, text)


if __name__ == "__main__":
    unittest.main()
