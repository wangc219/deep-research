from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.research_state import (  # noqa: E402
    ReadingQueue,
    ResearchLead,
    ResearchRound,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryResearchStateTests(unittest.TestCase):
    def test_research_state_rejects_unknown_status(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown ResearchLead status"):
            _lead("lead-bad", status="maybe")
        with self.assertRaisesRegex(ValueError, "unknown ResearchRound status"):
            _round(status="maybe")

    def test_domain_store_exports_and_loads_research_state_jsonl(self) -> None:
        store = DomainStore()
        store.upsert_research_lead(_lead("lead-selected", status="selected"))
        store.upsert_research_lead(_lead("lead-skipped", status="skipped"))
        store.upsert_reading_queue(
            ReadingQueue(
                queue_id="queue-1",
                round_id="round-1",
                topic="低空无人机",
                lead_ids=["lead-selected", "lead-skipped"],
                selected_lead_ids=["lead-selected"],
                skipped_lead_ids=["lead-skipped"],
                failed_lead_ids=[],
                budget_snapshot={"round": 1},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        store.upsert_research_round(
            _round(
                status="judged",
                next_round_plan={"focus": ["补充雷达探测材料"]},
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.jsonl"
            store.export_jsonl(path)
            loaded = DomainStore.load_jsonl(path)

        self.assertEqual(
            loaded.research_leads["lead-selected"].to_dict(),
            store.research_leads["lead-selected"].to_dict(),
        )
        self.assertEqual(
            loaded.reading_queues["queue-1"].selected_lead_ids,
            ["lead-selected"],
        )
        self.assertEqual(
            loaded.research_rounds["round-1"].next_round_plan,
            {"focus": ["补充雷达探测材料"]},
        )


def _lead(lead_id: str, *, status: str) -> ResearchLead:
    return ResearchLead(
        lead_id=lead_id,
        round_id="round-1",
        source_name="中国军网",
        source_tier="A",
        url=f"http://www.81.cn/{lead_id}.html",
        title=f"Lead {lead_id}",
        snippet="低空无人机探测预警材料",
        page_type="article",
        download_kind="none",
        relevance_score=0.8,
        importance_score=0.7,
        credibility_score=0.9,
        status=status,
        selection_reason="topic match",
        skip_reason="",
        artifact_refs=[],
        created_at=NOW,
        updated_at=NOW,
    )


def _round(
    *,
    status: str,
    next_round_plan: dict[str, object] | None = None,
) -> ResearchRound:
    return ResearchRound(
        round_id="round-1",
        run_id="run-1",
        index=1,
        topic="低空无人机",
        hypothesis="低空无人机探测预警存在能力缺口",
        source_strategy_id="strategy-1",
        worker_report_ids=["agent-1"],
        judgement_id="judge-1",
        next_round_plan=next_round_plan or {},
        stop_reason=None,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
