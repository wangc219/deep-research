from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.workers.agent_defs import (  # noqa: E402
    discover_agents,
    parse_agent_def,
)


class DemandDiscoveryAgentDefTests(unittest.TestCase):
    def test_parse_agent_frontmatter_with_budget_json(self) -> None:
        text = """---
name: reader
description: read sources
tools: search_sources, fetch_page, create_evidence_card
model: default
budget: {"max_tokens": 1000, "max_tool_calls": 12}
---
Reader prompt body.
"""

        agent = parse_agent_def(text, source_path=Path("reader.md"))

        self.assertEqual(agent.name, "reader")
        self.assertEqual(agent.tools, ["search_sources", "fetch_page", "create_evidence_card"])
        self.assertEqual(agent.budget.max_tokens, 1000)
        self.assertEqual(agent.budget.max_tool_calls, 12)
        self.assertIn("Reader prompt body", agent.system_prompt)

    def test_discover_agents_skips_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reader.md").write_text(
                """---
name: reader
description: ok
tools: create_evidence_card
model: default
budget: {"max_tool_calls": 5}
---
Prompt.
""",
                encoding="utf-8",
            )
            (root / "bad.md").write_text(
                """---
name: bad
budget: {not-json}
---
Broken.
""",
                encoding="utf-8",
            )

            agents = discover_agents(root)

            self.assertEqual(set(agents), {"reader"})

    def test_default_agent_budgets_match_gpt55_context_window(self) -> None:
        agents = discover_agents()

        self.assertGreaterEqual(set(agents), {
            "auditor",
            "context_curator",
            "debater",
            "judge",
            "orchestrator",
            "reader",
            "reporter",
        })
        for name, agent in agents.items():
            with self.subTest(agent=name):
                self.assertGreaterEqual(agent.budget.max_tokens or 0, 200_000)


if __name__ == "__main__":
    unittest.main()
