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


class DemandDiscoveryJudgeAgentTests(unittest.TestCase):
    def test_judge_agent_records_consumable_judgement_with_tool_call(self) -> None:
        store = DomainStore()
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "judge-tool",
                            "name": "record_judgement",
                            "arguments": _judgement_payload(),
                        }
                    ]
                ),
                FakeResponse(text="judgement recorded"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            judgement = asyncio.run(
                run_judge_agent_for_round(
                    round_id="round-1",
                    worker_reports=_worker_reports(),
                    domain_store=store,
                    provider_factory=lambda: provider,
                    run_id="run-judge",
                    sessions_dir=Path(tmp),
                )
            )

        self.assertEqual(judgement.judgement_id, "judge-agent-1")
        self.assertEqual(judgement.next_round_plan["plan_version"], 1)
        self.assertTrue(judgement.next_round_plan["controller_tasks"])
        self.assertIn(
            "judge-agent-1",
            store.judgement_reports,
        )
        self.assertIn(
            "judgement_recorded",
            [event.event_type for event in store.trace_events],
        )

    def test_judge_agent_has_no_programmatic_fallback_when_model_does_not_write(self) -> None:
        provider = FakeProvider()
        provider.set_responses([FakeResponse(text="I think more work is needed.")])

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "judge agent did not write JudgementReport"):
                asyncio.run(
                    run_judge_agent_for_round(
                        round_id="round-1",
                        worker_reports=_worker_reports(),
                        domain_store=DomainStore(),
                        provider_factory=lambda: provider,
                        run_id="run-judge",
                        sessions_dir=Path(tmp),
                    )
                )

    def test_programmatic_judge_synthesis_is_removed(self) -> None:
        import knowledgegraph.demand_discovery.domain.judgement as judgement_module
        import knowledgegraph.demand_discovery.harness.scheduler as scheduler_module

        self.assertFalse(hasattr(judgement_module, "synthesize_judgement_from_worker_reports"))
        self.assertFalse(hasattr(scheduler_module, "run_judge_for_round"))


def _worker_reports() -> list[WorkerReport]:
    return [
        WorkerReport(
            agent_run_id="agent-1",
            report_id="agent-1",
            role="reader",
            status="completed",
            partial_findings=["白名单材料显示远海保障存在持续维护缺口"],
            evidence_refs=["ev-1"],
            lead_refs=["lead-1"],
            open_questions=["缺少独立公开正文交叉验证"],
            need_more_sources=True,
        )
    ]


def _judgement_payload() -> dict[str, object]:
    return {
        "judgement_id": "judge-agent-1",
        "round_id": "round-1",
        "consensus_points": [
            {
                "text": "白名单材料显示远海保障存在持续维护缺口",
                "worker_report_ids": ["agent-1"],
                "evidence_ids": ["ev-1"],
                "lead_ids": ["lead-1"],
            }
        ],
        "contradictions": [],
        "partial_coverage": [],
        "unique_insights": [],
        "blind_spots": [
            {
                "text": "缺少独立公开正文交叉验证",
                "worker_report_ids": ["agent-1"],
                "evidence_ids": [],
                "lead_ids": ["lead-1"],
            }
        ],
        "evidence_strength_map": {"ev-1": "partial"},
        "next_round_plan": {
            "plan_version": 1,
            "round_id": "round-1",
            "summary": "下一轮补充独立公开正文交叉验证",
            "controller_tasks": [
                {
                    "task_id": "task-1",
                    "objective": "补充远海保障能力缺口的独立公开正文证据",
                    "gap_type": "missing_direct_evidence",
                    "routing_hint": "open_search_candidate",
                    "source_scope": "open_web_after_whitelist_exhausted",
                    "input_refs": {
                        "worker_report_ids": ["agent-1"],
                        "evidence_ids": ["ev-1"],
                        "lead_ids": ["lead-1"],
                    },
                    "query_revisions": [
                        {"language": "zh", "query": "远海保障 能力缺口 持续维护"}
                    ],
                    "completion_check": "找到独立公开正文证据，或说明只能得到 partial/adjacent evidence",
                }
            ],
            "worker_briefs": {
                "task-1": "上一轮 ev-1 只有 partial，本轮使用给定 query 补充独立公开正文。"
            },
            "remaining_open_questions": ["缺少独立公开正文交叉验证"],
            "stop_candidate_reason": "",
        },
        "stop_or_continue": "continue",
        "rationale": "证据不足，需要开放补证",
    }


if __name__ == "__main__":
    unittest.main()
