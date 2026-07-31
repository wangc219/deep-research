from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.model_prompt import (  # noqa: E402
    DemandDiscoveryPromptBuilder,
    ModelPrompt,
)
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    WorkerSpec,
    _model_prompt_for_worker,
)


class DemandDiscoveryModelPromptBuilderTests(unittest.TestCase):
    def test_worker_prompt_has_codex_style_fields_and_readable_input(self) -> None:
        pack = ContextPack(
            agent_role="reading_worker",
            task_brief="调查极地通信保障能力缺口",
            sections={
                "research_state": {
                    "web_research_sessions": [
                        {
                            "session_id": "wrs-1",
                            "active_acceptance_criteria": ["至少读取一篇正文"],
                            "compact_summaries": ["公开正文是否支持缺口仍未解决"],
                        }
                    ]
                },
                "evidence_index": [{"evidence_id": "ev-1", "claim": "相邻证据"}],
                "recent_observations": [
                    {
                        "tool_name": "browser_observe",
                        "observed_affordances": [
                            {"kind": "search_box", "target_id": "target-search"}
                        ],
                    }
                ],
            },
            token_budget=6000,
        )

        prompt = DemandDiscoveryPromptBuilder().build(
            pack,
            turn_objective="查找直接正文证据",
            tools=[],
            authorized_scope={"sources": ["source:example"]},
            hard_prohibitions=["不得从搜索摘要创建 EvidenceCard"],
            output_schema={"type": "object", "required": ["findings"]},
        )

        self.assertIsInstance(prompt, ModelPrompt)
        self.assertIn("reading_worker", prompt.base_instructions)
        self.assertFalse(prompt.parallel_tool_calls)
        self.assertEqual(prompt.output_schema["required"], ["findings"])

        rendered = prompt.render_input()
        positions = [
            rendered.index("# Objective"),
            rendered.index("# Working Memory"),
            rendered.index("# Constraints"),
            rendered.index("# Recent Observations"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("wrs-1", rendered)
        self.assertIn("至少读取一篇正文", rendered)
        self.assertIn("target-search", rendered)
        self.assertNotIn("Recommended Next Actions", rendered)
        self.assertNotIn('"agent_role": "reading_worker"', rendered)

    def test_missing_acceptance_criteria_is_visible(self) -> None:
        pack = ContextPack(
            agent_role="reading_worker",
            task_brief="调查 topic",
            sections={},
            token_budget=6000,
        )

        rendered = DemandDiscoveryPromptBuilder().build(pack, tools=[]).render_input()

        self.assertIn("# Constraints", rendered)
        self.assertIn("[]", rendered)
        self.assertIn("criteria missing", rendered)

    def test_auditor_working_memory_includes_audit_context_section(self) -> None:
        pack = ContextPack(
            agent_role="auditor",
            task_brief="semantic audit",
            sections={"audit_context": {"candidate": {"candidate_id": "cand-1"}}},
            token_budget=12000,
        )

        rendered = DemandDiscoveryPromptBuilder().build(pack, tools=[]).render_input()

        self.assertIn('"audit_context"', rendered)
        self.assertIn('"candidate_id": "cand-1"', rendered)

    def test_auditor_scheduler_prompt_uses_audit_output_schema(self) -> None:
        spec = WorkerSpec(
            role="auditor",
            task_brief="Audit candidate evidence support with run_audit.",
            tools=["run_audit"],
            budget=RunBudget(max_tool_calls=4, max_tokens=40_000),
            context_pack=ContextPack(
                agent_role="auditor",
                task_brief="semantic audit",
                sections={
                    "audit_context": {
                        "candidate": {"candidate_id": "cand-1"},
                        "evidence_cards": [{"evidence_id": "ev-1"}],
                    }
                },
                token_budget=12_000,
            ),
        )

        prompt = _model_prompt_for_worker(spec, tools=[])
        rendered = prompt.render_input()
        schema_text = json.dumps(prompt.output_schema, ensure_ascii=False)

        self.assertIn('"audit_context"', rendered)
        self.assertIn("audit_id", schema_text)
        self.assertIn("candidate_id", schema_text)
        self.assertIn("conclusion", schema_text)
        self.assertIn("scorecard", schema_text)
        self.assertIn("recommended_report_status", schema_text)
        self.assertIn("recheck_conditions", schema_text)
        self.assertNotIn("need_more_sources", schema_text)
        self.assertNotIn("findings", schema_text)

    def test_other_roles_share_model_prompt_shape(self) -> None:
        for role in ["judge", "audit_worker", "reporter"]:
            pack = ContextPack(
                agent_role=role,
                task_brief=f"{role} task",
                sections={"trace_summary": {"evidence_ids": ["ev-1"]}},
                token_budget=4000,
            )
            prompt = DemandDiscoveryPromptBuilder().build(pack, tools=[])
            self.assertIsInstance(prompt.base_instructions, str)
            self.assertIsInstance(prompt.input, list)
            self.assertIn("# Objective", prompt.render_input())
            self.assertFalse(prompt.parallel_tool_calls)


if __name__ == "__main__":
    unittest.main()
