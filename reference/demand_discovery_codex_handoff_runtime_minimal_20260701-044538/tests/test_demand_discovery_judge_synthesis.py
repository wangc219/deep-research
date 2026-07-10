from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.judge_agent import (  # noqa: E402
    run_judge_agent_for_round,
)
from knowledgegraph.demand_discovery.harness.worker_report import WorkerReport  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


class DemandDiscoveryJudgeAgentSynthesisTests(unittest.TestCase):
    def test_model_judge_tool_output_produces_consumable_next_round_plan(self) -> None:
        reports = [
            WorkerReport(
                agent_run_id="agent-1",
                report_id="agent-1",
                role="reader",
                status="completed",
                partial_findings=[
                    "低空无人机威胁压缩预警时间",
                    "需要多源探测和快速告警",
                ],
                new_evidence_cards=["ev-1"],
                lead_refs=["lead-1"],
                open_questions=["缺少处置链路材料"],
                risk_or_conflict=["雷达覆盖在城市遮蔽下不足"],
            ),
            WorkerReport(
                agent_run_id="agent-2",
                report_id="agent-2",
                role="reader",
                status="completed",
                partial_findings=[
                    "需要多源探测和快速告警",
                    "光电识别对低慢小目标有补充价值",
                ],
                new_evidence_cards=["ev-2"],
                lead_refs=["lead-2"],
                open_questions=["缺少处置链路材料"],
                risk_or_conflict=["光电识别受天气影响，与雷达覆盖结论需对照"],
            ),
        ]
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "judge-call",
                            "name": "record_judgement",
                            "arguments": _judgement_payload(),
                        }
                    ]
                ),
                FakeResponse(text="judgement recorded"),
            ]
        )
        store = DomainStore()

        with tempfile.TemporaryDirectory() as tmp:
            judgement = asyncio.run(
                run_judge_agent_for_round(
                    round_id="round-1",
                    worker_reports=reports,
                    domain_store=store,
                    provider_factory=lambda: provider,
                    run_id="run-judge-agent",
                    sessions_dir=Path(tmp),
                )
            )

        self.assertEqual(judgement.round_id, "round-1")
        self.assertEqual(judgement.stop_or_continue, "continue")
        self.assertIn("需要多源探测和快速告警", judgement.consensus_points[0].text)
        self.assertGreaterEqual(len(judgement.contradictions), 1)
        self.assertGreaterEqual(len(judgement.blind_spots), 1)
        next_round_plan = judgement.next_round_plan
        self.assertEqual(next_round_plan["plan_version"], 1)
        self.assertNotIn("tasks", next_round_plan)
        self.assertIsInstance(next_round_plan["controller_tasks"], list)
        self.assertTrue(next_round_plan["controller_tasks"])
        self.assertIsInstance(next_round_plan["worker_briefs"], dict)
        first_task = next_round_plan["controller_tasks"][0]
        self.assertEqual(first_task["routing_hint"], "open_search_candidate")
        self.assertEqual(first_task["gap_type"], "missing_direct_evidence")
        self.assertEqual(first_task["source_scope"], "open_web_after_whitelist_exhausted")
        self.assertIsInstance(first_task["input_refs"], dict)
        self.assertIn("worker_report_ids", first_task["input_refs"])
        self.assertIn("evidence_ids", first_task["input_refs"])
        self.assertIn("lead_ids", first_task["input_refs"])
        self.assertIn(first_task["task_id"], next_round_plan["worker_briefs"])
        self.assertIn(judgement.judgement_id, store.judgement_reports)
        for item in [
            *judgement.consensus_points,
            *judgement.contradictions,
            *judgement.blind_spots,
        ]:
            self.assertTrue(item.worker_report_ids)


def _judgement_payload() -> dict[str, object]:
    return {
        "judgement_id": "judge-agent-synthesis",
        "round_id": "round-1",
        "consensus_points": [
            {
                "text": "需要多源探测和快速告警",
                "worker_report_ids": ["agent-1", "agent-2"],
                "evidence_ids": ["ev-1", "ev-2"],
                "lead_ids": ["lead-1", "lead-2"],
            }
        ],
        "contradictions": [
            {
                "text": "光电识别受天气影响，与雷达覆盖结论需对照",
                "worker_report_ids": ["agent-2"],
                "evidence_ids": ["ev-2"],
                "lead_ids": ["lead-2"],
            }
        ],
        "partial_coverage": [],
        "unique_insights": [
            {
                "text": "低空无人机威胁压缩预警时间",
                "worker_report_ids": ["agent-1"],
                "evidence_ids": ["ev-1"],
                "lead_ids": ["lead-1"],
            }
        ],
        "blind_spots": [
            {
                "text": "缺少处置链路材料",
                "worker_report_ids": ["agent-1", "agent-2"],
                "evidence_ids": [],
                "lead_ids": ["lead-1", "lead-2"],
            }
        ],
        "evidence_strength_map": {"ev-1": "partial", "ev-2": "partial"},
        "next_round_plan": {
            "plan_version": 1,
            "round_id": "round-1",
            "summary": "继续围绕处置链路补充开放正文证据",
            "controller_tasks": [
                {
                    "task_id": "task-1",
                    "objective": "寻找反无人机处置链路公开正文材料",
                    "gap_type": "missing_direct_evidence",
                    "routing_hint": "open_search_candidate",
                    "source_scope": "open_web_after_whitelist_exhausted",
                    "input_refs": {
                        "worker_report_ids": ["agent-1", "agent-2"],
                        "evidence_ids": ["ev-1", "ev-2"],
                        "lead_ids": ["lead-1", "lead-2"],
                    },
                    "query_revisions": [
                        {"language": "zh", "query": "低空无人机 处置链路 能力缺口"}
                    ],
                    "completion_check": "找到可读取正文的开放来源并创建 EvidenceCard",
                }
            ],
            "worker_briefs": {
                "task-1": "补充反无人机处置链路的公开正文证据。"
            },
            "remaining_open_questions": ["缺少处置链路材料"],
            "stop_candidate_reason": "",
        },
        "stop_or_continue": "continue",
        "rationale": "证据覆盖不足，需要继续补证",
    }


if __name__ == "__main__":
    unittest.main()
