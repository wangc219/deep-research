from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.network_research import _worker_round_brief  # noqa: E402


class NetworkResearchWorkerLoopTests(unittest.TestCase):
    def test_worker_round_brief_requires_self_check_and_follow_up(self) -> None:
        brief = _worker_round_brief(
            topic="极地通信保障能力缺口",
            seed_urls=["https://example.test/search"],
            round_id="round-1",
            source_guidance=[
                {
                    "source_id": "example",
                    "source_name": "Example",
                    "content_languages": ["zh"],
                    "planned_queries": ["极地通信保障 能力缺口"],
                    "route_hints": ["站内搜索", "专题栏目"],
                }
            ],
            allow_browser=True,
        )

        self.assertIn("Worker self-check", brief)
        self.assertIn("follow-up", brief)
        self.assertIn("discarded_findings", brief)
        self.assertIn("remaining blind spots", brief)
        self.assertIn("Do not output strong findings without evidence refs", brief)


if __name__ == "__main__":
    unittest.main()
