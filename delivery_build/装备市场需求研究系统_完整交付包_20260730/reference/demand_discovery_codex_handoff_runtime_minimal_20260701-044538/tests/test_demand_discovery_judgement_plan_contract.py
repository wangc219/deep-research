from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.judgement_plan import (  # noqa: E402
    assess_next_round_plan,
    build_repaired_next_round_plan,
    compile_worker_brief,
)


class DemandDiscoveryJudgementPlanContractTests(unittest.TestCase):
    def test_valid_plan_uses_minimal_controller_tasks_and_worker_briefs(self) -> None:
        plan = {
            "plan_version": 1,
            "round_id": "round-1",
            "summary": "补齐直接证据",
            "controller_tasks": [
                {
                    "task_id": "task-1",
                    "objective": "补充跨区域应急通信资源调度的 direct/partial 正文证据",
                    "gap_type": "missing_direct_evidence",
                    "routing_hint": "open_search_candidate",
                    "source_scope": "open_web_after_whitelist_exhausted",
                    "input_refs": {
                        "worker_report_ids": ["agent-1"],
                        "evidence_ids": ["ev-1"],
                        "lead_ids": ["lead-1"],
                    },
                    "query_revisions": [
                        {
                            "language": "zh",
                            "query": "跨区域 应急通信 资源 调度 运营商 报告",
                        }
                    ],
                    "completion_check": "找到官方/运营商正文证据，或说明只能得到 partial/adjacent evidence",
                }
            ],
            "worker_briefs": {
                "task-1": "本轮目标是补充跨区域应急通信资源调度的直接证据。优先使用给定中文 query。"
            },
            "remaining_open_questions": [],
            "stop_candidate_reason": "",
        }

        assessment = assess_next_round_plan(plan)

        self.assertTrue(assessment.is_valid)
        self.assertFalse(assessment.repaired)
        self.assertEqual(assessment.controller_tasks[0]["task_id"], "task-1")
        self.assertEqual(assessment.worker_briefs["task-1"], plan["worker_briefs"]["task-1"])

    def test_repair_converts_legacy_tasks_without_preserving_old_tasks_field(self) -> None:
        repaired = build_repaired_next_round_plan(
            {
                "plan_version": 1,
                "round_id": "round-1",
                "summary": "旧计划",
                "tasks": [
                    {
                        "task_id": "task-open",
                        "gap_type": "open_search_candidate",
                        "question": "寻找远海保障能力缺口公开正文",
                        "routing_decision_hint": "open_search_candidate",
                        "source_constraints": {
                            "source_scope": "open_web",
                            "whitelist_exhausted": True,
                        },
                        "input_refs": {
                            "worker_report_ids": ["worker-1"],
                            "evidence_ids": ["ev-1"],
                            "lead_ids": ["lead-1"],
                        },
                        "query_revisions": [{"language": "zh", "query": "远海保障 能力缺口"}],
                        "done_criteria": ["白名单 route/query 已耗尽或无新增"],
                    }
                ],
            },
            topic="远海保障能力缺口",
        )

        self.assertNotIn("tasks", repaired)
        task = repaired["controller_tasks"][0]
        self.assertEqual(task["task_id"], "task-open")
        self.assertEqual(task["routing_hint"], "open_search_candidate")
        self.assertEqual(task["source_scope"], "open_web_after_whitelist_exhausted")
        self.assertEqual(task["query_revisions"][0]["query"], "远海保障 能力缺口")
        self.assertIn("task-open", repaired["worker_briefs"])
        self.assertTrue(assess_next_round_plan(repaired).is_valid)

    def test_repair_rewrites_generic_query_with_topic_context(self) -> None:
        repaired = build_repaired_next_round_plan(
            {
                "plan_version": 1,
                "round_id": "round-1",
                "controller_tasks": [
                    {
                        "task_id": "task-1",
                        "objective": "补充独立来源交叉验证",
                        "gap_type": "missing_direct_evidence",
                        "routing_hint": "open_search_candidate",
                        "source_scope": "open_web_after_whitelist_exhausted",
                        "input_refs": {"worker_report_ids": ["agent-1"]},
                        "query_revisions": [{"language": "zh", "query": "继续补充材料"}],
                        "completion_check": "找到正文证据",
                    }
                ],
                "worker_briefs": {},
            },
            topic="极端天气灾害城市应急通信保障能力缺口",
        )

        query = repaired["controller_tasks"][0]["query_revisions"][0]["query"]
        self.assertIn("极端天气灾害城市应急通信保障能力缺口", query)
        self.assertNotEqual(query, "继续补充材料")

    def test_assessment_rejects_unknown_enums_and_missing_worker_refs(self) -> None:
        plan = {
            "plan_version": 1,
            "round_id": "round-1",
            "summary": "补证",
            "controller_tasks": [
                {
                    "task_id": "task-bad",
                    "objective": "补充远海保障直接证据",
                    "gap_type": "bad_gap",
                    "routing_hint": "bad_route",
                    "source_scope": "bad_scope",
                    "input_refs": {
                        "worker_report_ids": [],
                        "evidence_ids": [],
                        "lead_ids": [],
                    },
                    "query_revisions": [{"language": "zh", "query": "远海保障 能力缺口"}],
                    "completion_check": "找到正文证据",
                }
            ],
            "worker_briefs": {"task-bad": "补充远海保障直接证据。"},
        }

        assessment = assess_next_round_plan(plan)

        self.assertFalse(assessment.is_valid)
        self.assertIn("task-bad unknown gap_type: bad_gap", assessment.errors)
        self.assertIn("task-bad unknown routing_hint: bad_route", assessment.errors)
        self.assertIn("task-bad unknown source_scope: bad_scope", assessment.errors)
        self.assertIn(
            "task-bad input_refs.worker_report_ids is required",
            assessment.errors,
        )

    def test_compile_worker_brief_is_natural_language_but_cites_controller_fields(self) -> None:
        brief = compile_worker_brief(
            {
                "task_id": "task-1",
                "objective": "补充运营商原始材料",
                "gap_type": "missing_direct_evidence",
                "routing_hint": "open_search_candidate",
                "source_scope": "open_web_after_whitelist_exhausted",
                "input_refs": {
                    "worker_report_ids": ["agent-1"],
                    "evidence_ids": ["ev-1"],
                    "lead_ids": ["lead-1"],
                },
                "query_revisions": [{"language": "zh", "query": "应急通信 运营商 调度"}],
                "completion_check": "新增 EvidenceCard 或说明只能得到 partial evidence",
            }
        )

        self.assertIn("补充运营商原始材料", brief)
        self.assertIn("应急通信 运营商 调度", brief)
        self.assertIn("ev-1", brief)
        self.assertIn("新增 EvidenceCard", brief)


if __name__ == "__main__":
    unittest.main()
