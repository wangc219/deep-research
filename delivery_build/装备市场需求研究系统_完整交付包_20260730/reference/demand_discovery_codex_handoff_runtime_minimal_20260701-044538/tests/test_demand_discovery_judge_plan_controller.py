from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_strategy import SelectedSource, SourceStrategy  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.judge_plan_routing import (  # noqa: E402
    human_profile_requests_from_judgement,
    open_search_queries_from_judgement,
    worker_assignments_from_judgement,
)
from knowledgegraph.demand_discovery.harness.research_loop import (  # noqa: E402
    ResearchLoopController,
    _first_plan_query,
)


NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)


class DemandDiscoveryJudgePlanControllerTests(unittest.TestCase):
    def test_open_search_queries_use_controller_tasks_not_worker_brief_text(self) -> None:
        judgement = _judgement(
            {
                "plan_version": 1,
                "round_id": "round-1",
                "summary": "补证",
                "controller_tasks": [
                    {
                        "task_id": "task-open",
                        "objective": "补充远海保障公开正文",
                        "gap_type": "missing_direct_evidence",
                        "routing_hint": "open_search_candidate",
                        "source_scope": "open_web_after_whitelist_exhausted",
                        "input_refs": {"worker_report_ids": ["worker-1"]},
                        "query_revisions": [{"language": "zh", "query": "远海保障 能力缺口"}],
                        "completion_check": "找到正文证据",
                    }
                ],
                "worker_briefs": {
                    "task-open": "请不要把这个自然语言 brief 当 query：错误 query 不应被 controller 使用"
                },
                "remaining_open_questions": [],
                "stop_candidate_reason": "",
            }
        )

        queries = open_search_queries_from_judgement(judgement, fallback_topic="远海保障")

        self.assertEqual(queries[0], "远海保障 能力缺口")
        self.assertNotIn("错误 query 不应被 controller 使用", queries)

    def test_worker_assignments_join_controller_task_with_natural_language_brief(self) -> None:
        judgement = _judgement(_new_plan())

        assignments = worker_assignments_from_judgement(judgement)

        self.assertEqual(assignments[0]["task_id"], "task-open")
        self.assertEqual(assignments[0]["objective"], "补充远海保障公开正文")
        self.assertIn("上一轮 evidence 只有 partial", assignments[0]["worker_brief"])
        self.assertEqual(assignments[0]["query_revisions"][0]["query"], "远海保障 能力缺口")

    def test_worker_assignments_skip_tasks_without_worker_report_refs(self) -> None:
        plan = _new_plan()
        task = dict(plan["controller_tasks"][0])  # type: ignore[index]
        task["task_id"] = "task-no-refs"
        task["input_refs"] = {
            "worker_report_ids": [],
            "evidence_ids": [],
            "lead_ids": [],
        }
        plan["controller_tasks"] = [task]
        plan["worker_briefs"] = {"task-no-refs": "无上一轮 worker refs 的任务不能下发。"}
        judgement = _judgement(plan)

        assignments = worker_assignments_from_judgement(judgement)

        self.assertEqual(assignments, [])

    def test_human_profile_needed_routes_to_human_profile_requests(self) -> None:
        plan = _new_plan()
        task = dict(plan["controller_tasks"][0])  # type: ignore[index]
        task["task_id"] = "task-human"
        task["gap_type"] = "human_profile_needed"
        task["routing_hint"] = "human_profile_needed"
        task["source_scope"] = "human_profile_required"
        plan["controller_tasks"] = [task]
        plan["worker_briefs"] = {"task-human": "需要人工审计 source profile。"}
        judgement = _judgement(plan)

        requests = human_profile_requests_from_judgement(judgement)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["task_id"], "task-human")

    def test_research_loop_open_search_trigger_consumes_controller_tasks(self) -> None:
        controller = _controller()
        judgement = _judgement(_new_plan())

        decision = controller._should_trigger_open_search(
            round_index=2,
            judgement=judgement,
            new_strong_evidence_count=0,
            consecutive_no_new_sources=1,
        )

        self.assertTrue(decision.should_trigger)
        self.assertEqual(
            controller._open_search_queries_from_judgement(judgement)[0],
            "远海保障 能力缺口",
        )

    def test_first_plan_query_reads_controller_objective_when_query_is_missing(self) -> None:
        self.assertEqual(
            _first_plan_query(
                {
                    "plan_version": 1,
                    "controller_tasks": [
                        {
                            "task_id": "task-1",
                            "objective": "补充运营商原始材料",
                            "query_revisions": [],
                        }
                    ],
                    "worker_briefs": {"task-1": "自然语言任务书"},
                }
            ),
            "补充运营商原始材料",
        )


def _new_plan() -> dict[str, object]:
    return {
        "plan_version": 1,
        "round_id": "round-1",
        "summary": "补证",
        "controller_tasks": [
            {
                "task_id": "task-open",
                "objective": "补充远海保障公开正文",
                "gap_type": "missing_direct_evidence",
                "routing_hint": "open_search_candidate",
                "source_scope": "open_web_after_whitelist_exhausted",
                "input_refs": {
                    "worker_report_ids": ["worker-1"],
                    "evidence_ids": ["ev-1"],
                    "lead_ids": ["lead-1"],
                },
                "query_revisions": [{"language": "zh", "query": "远海保障 能力缺口"}],
                "completion_check": "找到正文证据",
            }
        ],
        "worker_briefs": {
            "task-open": "上一轮 evidence 只有 partial，本轮用给定 query 补充公开正文。"
        },
        "remaining_open_questions": [],
        "stop_candidate_reason": "",
    }


def _judgement(next_round_plan: dict[str, object]) -> JudgementReport:
    return JudgementReport(
        judgement_id="judge-1",
        round_id="round-1",
        consensus_points=[
            JudgementItem(text="远海保障存在能力缺口", worker_report_ids=["worker-1"], evidence_ids=["ev-1"])
        ],
        contradictions=[],
        partial_coverage=[],
        unique_insights=[],
        blind_spots=[],
        evidence_strength_map={"ev-1": "partial"},
        next_round_plan=next_round_plan,
        stop_or_continue="continue",
        rationale="needs more evidence",
        created_at=NOW,
    )


def _controller() -> ResearchLoopController:
    source = SelectedSource(
        source_name="Official",
        source_tier="A",
        source_type="official",
        fetch_transport="http",
        entry_urls=["https://official.example.test/"],
        content_languages=["zh"],
        planned_queries=["远海保障"],
        default_queries=["远海保障"],
        interaction_profile="static_listing",
        rationale="test",
    )
    strategy = SourceStrategy(
        strategy_id="strategy-1",
        topic="远海保障能力缺口",
        selected_sources=[source],
        seed_urls=["https://official.example.test/"],
    )
    return ResearchLoopController(
        run_id="run-1",
        topic=strategy.topic,
        strategy=strategy,
        store=DomainStore(),
        registry=SourceRegistry(sources=[]),
        max_rounds=3,
    )


if __name__ == "__main__":
    unittest.main()
