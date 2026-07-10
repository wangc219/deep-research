from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.report_context import ReportContextMaterial  # noqa: E402
from knowledgegraph.demand_discovery.harness.report_context import ReportContextCandidatePool  # noqa: E402
from knowledgegraph.demand_discovery.harness.report_context_curator import (  # noqa: E402
    run_report_context_curator_agent,
)
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402


class ReportContextCuratorTests(unittest.TestCase):
    def test_context_curator_records_curated_items_via_tool(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "call-curate",
                            "name": "record_report_context_curation",
                            "arguments": {
                                "bundle_id": "rcb-1",
                                "curated_items": [
                                    {
                                        "item_id": "cur-1",
                                        "material_ids": ["mat-evidence-1"],
                                        "report_use": "core",
                                        "claim_summary": "存在远海保障能力缺口",
                                        "curation_reason": "审计允许作为核心证据",
                                        "required_caveat": "样本有限",
                                    }
                                ],
                            },
                        }
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            items = asyncio.run(
                run_report_context_curator_agent(
                    provider=provider,
                    pool=_pool(),
                    session_path=Path(tmp) / "curator.jsonl",
                    system_prompt="context curator",
                )
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].report_use, "core")
        self.assertEqual(items[0].required_caveat, "样本有限")
        self.assertEqual(provider.pending_count(), 0)

    def test_context_curator_prompt_exposes_candidate_pool(self) -> None:
        provider = FakeProvider()

        def assert_pool_visible(context, state):
            del state
            prompt_text = "\n\n".join(str(message.content) for message in context.messages)
            if (
                "report_context_candidate_pool" not in prompt_text
                or "mat-evidence-1" not in prompt_text
            ):
                raise AssertionError("ReportContextCandidatePool was not visible")
            return AssistantMessage(
                content=[
                    AssistantContentBlock(
                        type="tool_call",
                        id="call-curate",
                        name="record_report_context_curation",
                        arguments={
                            "bundle_id": "rcb-1",
                            "curated_items": [
                                {
                                    "item_id": "cur-1",
                                    "material_ids": ["mat-evidence-1"],
                                    "report_use": "core",
                                    "claim_summary": "存在远海保障能力缺口",
                                    "curation_reason": "审计允许作为核心证据",
                                }
                            ],
                        },
                    )
                ]
            )

        provider.set_responses(
            [FakeResponse(factory=assert_pool_visible), FakeResponse(text="done")]
        )

        with tempfile.TemporaryDirectory() as tmp:
            items = asyncio.run(
                run_report_context_curator_agent(
                    provider=provider,
                    pool=_pool(),
                    session_path=Path(tmp) / "curator.jsonl",
                    system_prompt="context curator",
                )
            )

        self.assertEqual(len(items), 1)


def _pool() -> ReportContextCandidatePool:
    return ReportContextCandidatePool(
        bundle_id="rcb-1",
        run_id="run-1",
        topic="远海保障能力缺口",
        candidate_id="cand-1",
        judgement_id="judge-1",
        audit_id="audit-1",
        review_status="needs_revision",
        control_brief={"topic": "远海保障能力缺口"},
        lineage_trace=[
            {"domain_trace_id": "dt-candidate", "event_type": "candidate_synthesized"},
            {"domain_trace_id": "dt-audit", "event_type": "audit_completed"},
        ],
        materials=[
            ReportContextMaterial(
                material_id="mat-evidence-1",
                material_type="evidence",
                title="远海保障",
                summary="公开材料显示存在远海保障缺口",
                refs={"evidence_ids": ["ev-1"]},
                window_text="远海保障需要持续维护能力。",
                source_location="text:fixture#para:0",
                allowed_report_uses=["core", "support"],
                risk_flags=[],
            )
        ],
        allowed_evidence_ids=["ev-1"],
        blocked_claims=[],
        required_caveats=["样本有限"],
    )


if __name__ == "__main__":
    unittest.main()
