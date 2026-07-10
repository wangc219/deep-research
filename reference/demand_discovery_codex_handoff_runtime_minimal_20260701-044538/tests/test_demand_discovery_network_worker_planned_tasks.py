from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.network_research import _worker_round_brief  # noqa: E402


class DemandDiscoveryNetworkWorkerPlannedTasksTests(unittest.TestCase):
    def test_worker_round_brief_includes_judge_planned_worker_briefs(self) -> None:
        brief = _worker_round_brief(
            "远海保障能力缺口",
            ["https://example.test/search"],
            "round-2",
            planned_tasks=[
                {
                    "task_id": "task-open",
                    "objective": "补充远海保障公开正文",
                    "routing_hint": "open_search_candidate",
                    "source_scope": "open_web_after_whitelist_exhausted",
                    "query_revisions": [{"language": "zh", "query": "远海保障 能力缺口"}],
                    "worker_brief": "上一轮 evidence 只有 partial，本轮读取公开正文并创建 EvidenceCard。",
                }
            ],
            allow_open_search=True,
            open_search_plan_id="osp-1",
            open_search_queries=["远海保障 能力缺口"],
        )

        self.assertIn("Planned judge follow-up tasks", brief)
        self.assertIn("task-open", brief)
        self.assertIn("上一轮 evidence 只有 partial", brief)
        self.assertIn("远海保障 能力缺口", brief)


if __name__ == "__main__":
    unittest.main()
