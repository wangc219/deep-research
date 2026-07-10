from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.dedup import (  # noqa: E402
    check_candidate,
    normalize_title,
    similarity,
)
from knowledgegraph.demand_discovery.domain.models import CandidateDemand  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryDedupTests(unittest.TestCase):
    def test_title_normalization_unifies_full_width_punctuation_and_case(self) -> None:
        self.assertEqual(
            normalize_title("  低空-无人机：探测  预警（能力）ABC  "),
            "低空无人机探测预警能力abc",
        )

    def test_similarity_hits_near_duplicate_but_not_different_topics(self) -> None:
        self.assertGreaterEqual(
            similarity("低空无人机探测预警能力需求", "低空无人机探测与预警能力需求"),
            0.85,
        )
        self.assertLess(
            similarity("低空无人机探测预警能力需求", "海上补给保障流程优化需求"),
            0.60,
        )

    def test_check_candidate_returns_near_and_similar_candidates(self) -> None:
        store = DomainStore()
        store.upsert_candidate(
            CandidateDemand(
                candidate_id="cand-near",
                title="低空无人机探测预警能力需求",
                demand_statement="复杂低空环境下需要提升无人机探测预警能力。",
                status="candidate_demand",
                evidence_ids=[],
                open_questions=[],
                solution_signals=[],
                created_by="tester",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        store.upsert_candidate(
            CandidateDemand(
                candidate_id="cand-other",
                title="海上补给保障流程优化需求",
                demand_statement="远海补给需要优化流程。",
                status="candidate_demand",
                evidence_ids=[],
                open_questions=[],
                solution_signals=[],
                created_by="tester",
                created_at=NOW,
                updated_at=NOW,
            )
        )

        result = check_candidate(
            store,
            "低空无人机探测与预警能力需求",
            "复杂低空环境下需要提升无人机预警能力。",
        )

        near_ids = [candidate_id for candidate_id, _score in result.near_duplicates]
        self.assertEqual(near_ids, ["cand-near"])
        self.assertNotIn(
            "cand-other",
            [candidate_id for candidate_id, _score in result.similar],
        )

    def test_create_candidate_tool_surfaces_duplicate_hint_and_trace(self) -> None:
        store = DomainStore()
        store.upsert_candidate(
            CandidateDemand(
                candidate_id="cand-near",
                title="低空无人机探测预警能力需求",
                demand_statement="复杂低空环境下需要提升无人机探测预警能力。",
                status="candidate_demand",
                evidence_ids=[],
                open_questions=[],
                solution_signals=[],
                created_by="tester",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        tool = _get_tool(build_domain_tools(store), "create_or_update_candidate")

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    tool.name,
                    {
                        "candidate_id": "cand-new",
                        "title": "低空无人机探测与预警能力需求",
                        "demand_statement": "复杂低空环境下需要提升无人机预警能力。",
                        "evidence_ids": [],
                    },
                ),
                ToolExecutionContext("run", "agent", "worker"),
            )
        )

        self.assertFalse(result.is_error)
        self.assertIn("高度相似候选", result.content)
        self.assertEqual(
            result.details["similar_candidates"]["near_duplicates"][0]["candidate_id"],
            "cand-near",
        )
        self.assertEqual(result.trace_proposals[0].event_type, "duplicate_checked")
        self.assertEqual(result.trace_proposals[1].event_type, "candidate_created")

    def test_scheduler_uses_similarity_dedup_for_worker_briefs(self) -> None:
        scheduler = DiscoveryScheduler("run-dedup")
        first = asyncio.run(
            scheduler.spawn_worker(_spec("低空无人机探测预警能力需求"))
        )
        second = asyncio.run(
            scheduler.spawn_worker(_spec("低空无人机探测与预警能力需求"))
        )

        self.assertEqual(second, first)
        self.assertIn(
            "worker_dedup_skipped",
            [event.type for event in scheduler.events],
        )


def _spec(brief: str) -> WorkerSpec:
    return WorkerSpec(
        role="reader",
        task_brief=brief,
        tools=[],
        budget=RunBudget(max_tool_calls=1),
        context_pack=ContextPack("reader", brief, {}, 200),
    )


def _get_tool(tools, name: str):
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"missing tool {name}")


if __name__ == "__main__":
    unittest.main()
