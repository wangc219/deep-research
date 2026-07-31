from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    WorkerSpec,
    _worker_prompt,
)


class WorkerRequestReadabilityTests(unittest.TestCase):
    def test_scheduler_worker_prompt_uses_model_prompt_sections(self) -> None:
        spec = WorkerSpec(
            role="reading_worker",
            task_brief="查找公开正文证据",
            tools=[],
            budget=RunBudget(max_tool_calls=4, max_tokens=4000),
            context_pack=ContextPack(
                agent_role="reading_worker",
                task_brief="查找公开正文证据",
                sections={
                    "research_state": {
                        "web_research_sessions": [
                            {
                                "session_id": "wrs-1",
                                "active_acceptance_criteria": ["至少读取一篇正文"],
                            }
                        ]
                    }
                },
                token_budget=4000,
            ),
        )

        prompt = _worker_prompt(spec)

        self.assertIn("# Objective", prompt)
        self.assertIn("# Working Memory", prompt)
        self.assertIn("# Constraints", prompt)
        self.assertIn("# Recent Observations", prompt)
        self.assertNotIn("Context pack:\n{", prompt)
        self.assertNotIn("Recommended Next Actions", prompt)
        self.assertIn("wrs-1", prompt)


if __name__ == "__main__":
    unittest.main()
