from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.tools.bm25 import BM25Index  # noqa: E402
from knowledgegraph.demand_discovery.tools.keyword_gate import (  # noqa: E402
    KeywordGate,
    load_default_keyword_gate,
)


class DemandDiscoveryKeywordGateTests(unittest.TestCase):
    def test_keyword_gate_reports_category_hits_without_filtering(self) -> None:
        gate = KeywordGate(
            {
                "demand": ["需求", "迫切"],
                "gap": ["短板", "不足"],
                "scenario": ["复杂环境"],
            }
        )

        result = gate.score("复杂环境下的低空探测能力需求仍有短板")

        self.assertGreater(result["score"], 0)
        self.assertEqual(result["hits"]["demand"], ["需求"])
        self.assertEqual(result["hits"]["gap"], ["短板"])
        self.assertEqual(result["hits"]["scenario"], ["复杂环境"])

    def test_default_keyword_gate_loads_config(self) -> None:
        gate = load_default_keyword_gate()

        self.assertIn("demand", gate.categories)
        self.assertGreater(gate.score("能力需求和瓶颈")["score"], 0)

    def test_bm25_ranks_more_relevant_document_first(self) -> None:
        index = BM25Index(
            [
                "低空无人机探测预警能力需求",
                "后勤运输保障流程",
                "电子对抗训练总结",
            ]
        )

        ranked = index.rank("低空探测需求", top_k=2)

        self.assertEqual(ranked[0][0], 0)
        self.assertGreater(ranked[0][1], ranked[1][1])


if __name__ == "__main__":
    unittest.main()
