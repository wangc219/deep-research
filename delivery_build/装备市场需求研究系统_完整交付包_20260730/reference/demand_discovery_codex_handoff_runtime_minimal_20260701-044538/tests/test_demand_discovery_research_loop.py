from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import run_autonomous_research_sync  # noqa: E402
from knowledgegraph.demand_discovery.domain.judgement import JudgementItem, JudgementReport  # noqa: E402
from knowledgegraph.demand_discovery.domain.models import EvidenceCard, SourceRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_strategy import (  # noqa: E402
    SelectedSource,
    SourceStrategy,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.research_loop import (  # noqa: E402
    _first_plan_query,
    evaluate_stop_conditions,
    ResearchLoopController,
)


class DemandDiscoveryResearchLoopTests(unittest.TestCase):
    def test_fake_loop_runs_two_rounds_then_synthesizes_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测 防护"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            result = run_autonomous_research_sync(
                mode="fake",
                topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                output_root=root / "runs",
                run_id="fake-loop",
                max_rounds=2,
                source_whitelist_path=whitelist,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))

        self.assertEqual(len(summary["rounds"]), 2)
        self.assertEqual(summary["rounds"][0]["status"], "judged")
        self.assertEqual(summary["rounds"][0]["judgement"]["stop_or_continue"], "continue")
        self.assertEqual(summary["rounds"][1]["status"], "stopped")
        self.assertEqual(summary["rounds"][1]["judgement"]["stop_or_continue"], "stop")
        first_plan = summary["rounds"][0]["judgement"]["next_round_plan"]
        self.assertEqual(first_plan["plan_version"], 1)
        first_plan_queries = [
            item["query"]
            for task in first_plan["controller_tasks"]
            for item in task.get("query_revisions", [])
        ]
        self.assertTrue(first_plan_queries)
        self.assertIn(first_plan_queries[0], summary["rounds"][1]["hypothesis"])
        self.assertIn("judgement", summary["trace"])
        self.assertIn("candidate_synthesis", summary["trace"])
        self.assertLess(summary["trace"].index("judgement"), summary["trace"].index("candidate_synthesis"))

    def test_stop_conditions_are_programmatic(self) -> None:
        judgement = JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(
                    text="需要多源探测",
                    worker_report_ids=["agent-1"],
                    evidence_ids=["ev-1"],
                )
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={"ev-1": "strong"},
            next_round_plan={},
            stop_or_continue="continue",
            rationale="continue",
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        self.assertEqual(
            evaluate_stop_conditions(round_index=2, max_rounds=2, new_strong_evidence_count=1, judgement=judgement).reason,
            "max_rounds",
        )
        self.assertEqual(
            evaluate_stop_conditions(round_index=1, max_rounds=2, new_strong_evidence_count=0, judgement=judgement).reason,
            "no_new_strong_evidence",
        )
        self.assertEqual(
            evaluate_stop_conditions(round_index=1, max_rounds=2, new_strong_evidence_count=1, judgement=judgement, budget_exhausted=True).reason,
            "budget_exhausted",
        )

    def test_stop_conditions_consume_v1_tasks_not_legacy_high_priority(self) -> None:
        v1_judgement = JudgementReport(
            judgement_id="judge-v1",
            round_id="round-1",
            consensus_points=[],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={},
            next_round_plan={
                "plan_version": 1,
                "controller_tasks": [
                    {
                        "task_id": "task-1",
                        "objective": "继续读取另一条白名单正文",
                        "gap_type": "source_gap",
                        "routing_hint": "different_whitelist_source",
                        "source_scope": "whitelist",
                        "input_refs": {"worker_report_ids": ["agent-1"]},
                        "query_revisions": [{"language": "zh", "query": "白名单 正文 补证"}],
                        "completion_check": "至少新增一条白名单正文证据",
                    }
                ],
                "worker_briefs": {"task-1": "继续读取另一条白名单正文"},
            },
            stop_or_continue="continue",
            rationale="continue",
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        legacy_judgement = JudgementReport(
            **{
                **v1_judgement.to_dict(),
                "judgement_id": "judge-legacy",
                "next_round_plan": {"high_priority": ["旧字段不应续命"]},
            }
        )

        self.assertEqual(
            evaluate_stop_conditions(
                round_index=1,
                max_rounds=2,
                new_strong_evidence_count=0,
                judgement=v1_judgement,
            ).reason,
            "continue",
        )
        self.assertEqual(
            evaluate_stop_conditions(
                round_index=1,
                max_rounds=2,
                new_strong_evidence_count=0,
                judgement=legacy_judgement,
            ).reason,
            "no_new_strong_evidence",
        )

    def test_stop_conditions_ignore_untraceable_v1_tasks(self) -> None:
        judgement = JudgementReport(
            judgement_id="judge-untraceable",
            round_id="round-1",
            consensus_points=[],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={},
            next_round_plan={
                "plan_version": 1,
                "controller_tasks": [
                    {
                        "task_id": "task-no-refs",
                        "objective": "继续补充正文证据",
                        "gap_type": "missing_direct_evidence",
                        "routing_hint": "different_whitelist_source",
                        "source_scope": "whitelist_first",
                        "input_refs": {"worker_report_ids": []},
                        "query_revisions": [{"language": "zh", "query": "补证"}],
                        "completion_check": "新增正文证据",
                    }
                ],
                "worker_briefs": {"task-no-refs": "无 worker refs 的任务不能续命。"},
            },
            stop_or_continue="continue",
            rationale="continue",
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        self.assertEqual(
            evaluate_stop_conditions(
                round_index=1,
                max_rounds=2,
                new_strong_evidence_count=0,
                judgement=judgement,
            ).reason,
            "no_new_strong_evidence",
        )

    def test_first_plan_query_ignores_legacy_plan_fields(self) -> None:
        self.assertEqual(
            _first_plan_query({"queries": ["旧查询"], "focus": ["旧焦点"], "high_priority": ["旧高优先级"]}),
            "",
        )
        self.assertEqual(
            _first_plan_query(
                {
                    "plan_version": 1,
                    "controller_tasks": [
                        {
                            "task_id": "task-1",
                            "query_revisions": [{"query": "新任务查询"}],
                        }
                    ],
                    "worker_briefs": {"task-1": "自然语言任务书"},
                }
            ),
            "新任务查询",
        )

    def test_count_new_strong_evidence_accepts_chinese_strength_labels(self) -> None:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        store = DomainStore()
        store.upsert_source(
            SourceRecord(
                source_id="src-cn",
                title="极端场景应急通信能力建设意见",
                source_name="开放政策来源",
                source_tier="B",
                source_type="open_web",
                publish_time=now,
                url_or_path="https://example.test/policy",
                summary_text="政策文件列出通信能力短板。",
                summary_source="worker_read_document",
                collection_decision="collect",
                author_or_org=None,
                is_repost=False,
                original_source=None,
                institutional_stance=None,
                created_at=now,
                updated_at=now,
            )
        )
        store.upsert_evidence(
            EvidenceCard(
                evidence_id="ev-cn",
                source_id="src-cn",
                claim="极端场景下基层保底通信能力仍需建设",
                evidence_summary="政策文件提出网络抗毁和基层保底通信能力建设任务。",
                excerpt="基层保底通信能力基本建立。",
                source_location="text:cn#para:0",
                evidence_assessment="较强：政策原文转载，覆盖能力缺口清单",
                created_by="reader",
                created_at=now,
            )
        )
        controller = ResearchLoopController(
            run_id="run-cn",
            topic="极端天气灾害中的城市应急通信保障能力缺口",
            strategy=_strategy(),
            store=store,
            registry=SourceRegistry([]),
            max_rounds=2,
        )

        self.assertEqual(controller._count_new_strong_evidence(["ev-cn"]), 1)

    def test_network_worker_report_preserves_reader_stop_reason_and_next_routes(self) -> None:
        controller = ResearchLoopController(
            run_id="run-reader-sop",
            topic="远海保障能力缺口",
            strategy=_strategy(),
            store=DomainStore(),
            registry=SourceRegistry([]),
            max_rounds=2,
        )
        worker_result = SimpleNamespace(
            run_id="network-run-1",
            trace_event_count=0,
            run_dir="runs/network-run-1",
            error="",
            final_text=(
                "findings:\n"
                "- 白名单入口未找到足够正文证据\n\n"
                "evidence_ready_for_judge: false\n\n"
                "stop_reason:\n"
                "- whitelist_exhausted\n\n"
                "remaining_gaps:\n"
                "- 缺少公开正文交叉验证\n\n"
                "suggested_next_routes:\n"
                "- open_search_candidate true; query=远海保障 能力缺口\n\n"
                "need_more_sources: true\n\n"
                "risks:\n"
                "- 白名单结果重复"
            ),
        )

        reports = controller._network_worker_reports(
            1,
            "round-1",
            [],
            [],
            worker_result=worker_result,
        )
        reader = reports[0]

        self.assertEqual(reader.stop_reason, "whitelist_exhausted")
        self.assertFalse(reader.evidence_ready_for_judge)
        self.assertEqual(reader.open_questions, ["缺少公开正文交叉验证"])
        self.assertEqual(
            reader.next_round_suggestions,
            ["open_search_candidate true; query=远海保障 能力缺口"],
        )
        self.assertTrue(reader.need_more_sources)

def _strategy() -> SourceStrategy:
    return SourceStrategy(
        strategy_id="strategy-cn",
        topic="极端天气灾害中的城市应急通信保障能力缺口",
        selected_sources=[
            SelectedSource(
                source_name="开放政策来源",
                source_tier="B",
                source_type="open_web",
                fetch_transport="http",
                entry_urls=["https://example.test/"],
                content_languages=["zh"],
                planned_queries=["应急通信 能力缺口"],
                default_queries=[],
                interaction_profile="static_listing",
                rationale="test fixture",
            )
        ],
        held_sources=[],
        seed_urls=["https://example.test/"],
        rationale="test fixture",
    )


if __name__ == "__main__":
    unittest.main()
