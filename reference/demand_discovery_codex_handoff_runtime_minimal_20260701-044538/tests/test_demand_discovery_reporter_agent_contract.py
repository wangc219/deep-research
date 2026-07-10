from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReporterAgentContractTests(unittest.TestCase):
    def test_reporter_agent_has_only_report_tools(self) -> None:
        text = (
            PROJECT_ROOT
            / "src"
            / "knowledgegraph"
            / "demand_discovery"
            / "workers"
            / "agents"
            / "reporter.md"
        ).read_text(encoding="utf-8")

        self.assertIn("tools: generate_demand_report, expand_report_context", text)
        self.assertIn("不得搜索", text)
        self.assertIn("不得新增未在 ReportContextBundle 中出现的核心事实", text)
        self.assertNotIn("fetch_page", text)
        self.assertNotIn("browser_execute", text)
        self.assertNotIn("create_evidence_card", text)


if __name__ == "__main__":
    unittest.main()
