from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.research_state import (  # noqa: E402
    ReadingQueue,
    ResearchLead,
    ResearchRound,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryContextPackResearchStateTests(unittest.TestCase):
    def test_context_pack_renders_compact_research_state_without_raw_html(self) -> None:
        store = DomainStore()
        store.upsert_research_lead(
            _lead(
                "lead-selected",
                status="selected",
                snippet="<html><body>RAW_HTML_SHOULD_NOT_RENDER</body></html>",
            )
        )
        store.upsert_research_lead(
            _lead("lead-skipped", status="skipped", snippet="白名单外链接", skip_reason="outside whitelist")
        )
        store.upsert_research_lead(
            _lead("lead-failed", status="failed", snippet="下载失败", skip_reason="fetch failed")
        )
        store.upsert_reading_queue(
            ReadingQueue(
                queue_id="queue-1",
                round_id="round-1",
                topic="低空无人机",
                lead_ids=["lead-selected", "lead-skipped", "lead-failed"],
                selected_lead_ids=["lead-selected"],
                skipped_lead_ids=["lead-skipped"],
                failed_lead_ids=["lead-failed"],
                budget_snapshot={"remaining_rounds": 1},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        store.upsert_research_round(
            ResearchRound(
                round_id="round-1",
                run_id="run-1",
                index=1,
                topic="低空无人机",
                hypothesis="探测预警能力缺口",
                source_strategy_id="strategy-1",
                worker_report_ids=["agent-reader"],
                judgement_id="judge-1",
                next_round_plan={"queries": ["反无人机 防护"], "need_more_sources": True},
                stop_reason=None,
                status="judged",
                created_at=NOW,
                updated_at=NOW,
            )
        )

        pack = ContextPackBuilder().build(
            "reading_worker",
            "继续调研低空无人机",
            store.to_run_state(),
            token_budget=4000,
        )
        rendered = pack.render()

        self.assertIn("research_state", pack.sections)
        self.assertIn("lead-selected", rendered)
        self.assertIn("lead-skipped", rendered)
        self.assertIn("lead-failed", rendered)
        self.assertIn("next_round_plan", rendered)
        self.assertNotIn("RAW_HTML_SHOULD_NOT_RENDER", rendered)


def _lead(
    lead_id: str,
    *,
    status: str,
    snippet: str,
    skip_reason: str = "",
) -> ResearchLead:
    return ResearchLead(
        lead_id=lead_id,
        round_id="round-1",
        source_name="中国军网",
        source_tier="A",
        url=f"http://www.81.cn/{lead_id}.html",
        title=lead_id,
        snippet=snippet,
        page_type="article",
        download_kind="none",
        relevance_score=0.8,
        importance_score=0.7,
        credibility_score=0.9,
        status=status,
        selection_reason="topic match" if status == "selected" else "",
        skip_reason=skip_reason,
        artifact_refs=[],
        created_at=NOW,
        updated_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
