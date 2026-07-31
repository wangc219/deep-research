from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.judgement import (  # noqa: E402
    JudgementItem,
    JudgementReport,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryJudgementTests(unittest.TestCase):
    def test_judgement_items_require_worker_refs_and_consensus_support_refs(self) -> None:
        with self.assertRaisesRegex(ValueError, "worker_report_ids"):
            JudgementItem(text="unreferenced", worker_report_ids=[])
        with self.assertRaisesRegex(ValueError, "consensus_points"):
            _report(
                consensus_points=[
                    JudgementItem(text="consensus", worker_report_ids=["agent-1"])
                ]
            )

    def test_domain_store_exports_and_loads_judgement_report(self) -> None:
        store = DomainStore()
        report = _report(
            consensus_points=[
                JudgementItem(
                    text="需要多源探测和快速告警",
                    worker_report_ids=["agent-1", "agent-2"],
                    evidence_ids=["ev-1"],
                    lead_ids=["lead-1"],
                )
            ],
            contradictions=[
                JudgementItem(
                    text="雷达与光电覆盖边界存在冲突",
                    worker_report_ids=["agent-1", "agent-2"],
                    lead_ids=["lead-2"],
                )
            ],
        )
        store.upsert_judgement_report(report)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.jsonl"
            store.export_jsonl(path)
            loaded = DomainStore.load_jsonl(path)

        self.assertEqual(
            loaded.judgement_reports["judge-1"].to_dict(),
            report.to_dict(),
        )

    def test_record_judgement_tool_emits_judgement_report_proposal(self) -> None:
        tool = next(tool for tool in build_domain_tools(DomainStore(), rubric=None) if tool.name == "record_judgement")

        result = __import__("asyncio").run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "record_judgement",
                    {
                        "judgement_id": "judge-tool",
                        "round_id": "round-1",
                        "consensus_points": [
                            {
                                "text": "需要多源探测",
                                "worker_report_ids": ["agent-1"],
                                "evidence_ids": ["ev-1"],
                                "lead_ids": [],
                            }
                        ],
                        "contradictions": [],
                        "partial_coverage": [],
                        "unique_insights": [],
                        "blind_spots": [
                            {
                                "text": "缺少处置链路",
                                "worker_report_ids": ["agent-1"],
                                "evidence_ids": [],
                                "lead_ids": ["lead-1"],
                            }
                        ],
                        "evidence_strength_map": {"ev-1": "strong"},
                        "next_round_plan": {"queries": ["处置链路"]},
                        "stop_or_continue": "continue",
                        "rationale": "继续补证",
                    },
                ),
                ToolExecutionContext("run-1", "agent-1", "judge", {}),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.domain_proposals[0].object_type, "JudgementReport")
        self.assertEqual(result.trace_proposals[0].event_type, "judgement_recorded")

    def test_record_judgement_tool_schema_requires_traceable_judgement_items(self) -> None:
        tool = next(tool for tool in build_domain_tools(DomainStore(), rubric=None) if tool.name == "record_judgement")

        consensus_schema = tool.parameters_schema["properties"]["consensus_points"]["items"]

        self.assertEqual(consensus_schema["required"], ["text", "worker_report_ids"])
        self.assertFalse(consensus_schema["additionalProperties"])
        self.assertIn("evidence_ids", consensus_schema["properties"])
        self.assertIn("lead_ids", consensus_schema["properties"])


def _report(
    *,
    consensus_points: list[JudgementItem],
    contradictions: list[JudgementItem] | None = None,
) -> JudgementReport:
    return JudgementReport(
        judgement_id="judge-1",
        round_id="round-1",
        consensus_points=consensus_points,
        contradictions=contradictions or [],
        partial_coverage=[
            JudgementItem(text="只覆盖探测，缺处置", worker_report_ids=["agent-1"], lead_ids=["lead-1"])
        ],
        unique_insights=[
            JudgementItem(text="城市遮蔽影响连续跟踪", worker_report_ids=["agent-2"], evidence_ids=["ev-2"])
        ],
        blind_spots=[
            JudgementItem(text="缺少实装部署材料", worker_report_ids=["agent-1"], lead_ids=["lead-3"])
        ],
        evidence_strength_map={"ev-1": "strong"},
        next_round_plan={"queries": ["反无人机 防护"], "need_more_sources": True},
        stop_or_continue="continue",
        rationale="需要补证",
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
