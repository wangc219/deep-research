from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


class SchedulerWorkerStopPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_records_self_check_trace_for_worker(self) -> None:
        store = DomainStore()

        def provider_factory(_spec: WorkerSpec) -> FakeProvider:
            provider = FakeProvider()
            provider.set_responses(
                [
                    FakeResponse(text="findings:\n- 初步判断没有证据引用"),
                    FakeResponse(
                        text="open_questions:\n- 补证后仍缺少直接证据\nneed_more_sources: true"
                    ),
                ]
            )
            return provider

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = DiscoveryScheduler(
                "run-1",
                provider_factory=provider_factory,
                tool_registry_factory=lambda _spec: [],
                domain_store=store,
                sessions_dir=Path(tmp),
                max_worker_follow_ups_per_assignment=1,
            )
            reports = await scheduler.run_workers(
                [
                    WorkerSpec(
                        role="reader",
                        task_brief="研究极地通信保障能力缺口",
                        tools=[],
                        budget=RunBudget(max_tool_calls=4, max_tokens=4000),
                        context_pack=ContextPack(
                            agent_role="reader",
                            task_brief="研究极地通信保障能力缺口",
                            sections={},
                            token_budget=800,
                        ),
                        assignment_id="assignment-1",
                        source_id="source-a",
                        source_guidance={
                            "round_id": "round-1",
                            "planned_queries": ["极地通信保障 能力缺口"],
                            "route_hints": ["站内搜索"],
                        },
                    )
                ]
            )

        self.assertEqual(len(reports), 1)
        self.assertIsNotNone(reports[0].self_check)
        self.assertEqual(reports[0].follow_up_attempt_count, 1)
        self.assertIn(
            "worker_self_check_recorded",
            [event.event_type for event in store.trace_events],
        )
        self.assertIn(
            "worker_report_finalized",
            [event.event_type for event in store.trace_events],
        )

    async def test_fake_tool_follow_up_reads_body_and_allows_worker_to_finish(self) -> None:
        store = DomainStore()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def provider_factory(_spec: WorkerSpec) -> FakeProvider:
            provider = FakeProvider()
            provider.set_responses(
                [
                    FakeResponse(
                        text=(
                            "findings:\n"
                            "- 只从检索页看到极地通信保障相关条目，尚未读取正文"
                        )
                    ),
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "call-read-body",
                                "name": "fake_read_document",
                                "arguments": {"artifact_ref": "artifact:article-1"},
                            }
                        ]
                    ),
                    FakeResponse(
                        text=(
                            "findings:\n"
                            "- 极地通信保障能力缺口由 ev-1 的正文段落直接支撑\n"
                            "open_questions:\n"
                            "- 仍需第二来源交叉验证\n"
                            "need_more_sources: false"
                        )
                    ),
                ]
            )
            return provider

        async def fake_read_document(
            call: ToolCall,
            ctx: ToolExecutionContext,
        ) -> ToolResult:
            session = next(iter(store.web_research_sessions.values()))
            artifact_ref = str(call.arguments["artifact_ref"])
            updated_session = {
                **session.to_dict(),
                "recent_refs": [
                    *session.recent_refs,
                    {
                        "type": "artifact",
                        "id": artifact_ref,
                        "location_ref": f"{artifact_ref}#p1",
                        "summary": "正文直接讨论极地通信保障链路不稳定导致预警和指挥协同能力缺口。",
                    },
                    {"type": "EvidenceCard", "id": "ev-1"},
                ],
                "attempted_routes": [
                    *session.attempted_routes,
                    {
                        "route": "read_document",
                        "query": "极地通信保障 能力缺口",
                        "outcome": "body_artifact_read",
                        "output_refs": [artifact_ref, "ev-1"],
                    },
                ],
            }
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=(
                    "read body artifact: artifact:article-1#p1; "
                    "created EvidenceCard ev-1"
                ),
                details={"artifact_ref": artifact_ref, "evidence_id": "ev-1"},
                domain_proposals=[
                    DomainWriteProposal(
                        "upsert",
                        "SourceRecord",
                        {
                            "source_id": "source-a",
                            "title": "极地通信保障训练报道",
                            "source_name": "Source A",
                            "source_tier": "B",
                            "source_type": "article",
                            "publish_time": now.isoformat(),
                            "url_or_path": "https://example.test/article-1.html",
                            "summary_text": "正文讨论极地通信保障链路不稳定问题。",
                            "summary_source": "read_document",
                            "collection_decision": "selected",
                            "author_or_org": "Example",
                            "is_repost": False,
                            "original_source": None,
                            "institutional_stance": None,
                            "created_at": now.isoformat(),
                            "updated_at": now.isoformat(),
                        },
                    ),
                    DomainWriteProposal(
                        "upsert",
                        "EvidenceCard",
                        {
                            "evidence_id": "ev-1",
                            "source_id": "source-a",
                            "claim": "极地通信保障存在链路稳定性能力缺口",
                            "evidence_summary": "正文直接说明极地环境下通信链路不稳定影响预警和协同。",
                            "excerpt": "极地环境下通信链路不稳定，影响预警和指挥协同。",
                            "source_location": "artifact:article-1#p1",
                            "evidence_assessment": "direct",
                            "created_by": "reader",
                            "created_at": now.isoformat(),
                        },
                    ),
                    DomainWriteProposal(
                        "upsert",
                        "WebResearchSession",
                        updated_session,
                    ),
                ],
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="source_seen",
                        target_type="SourceRecord",
                        target_id="source-a",
                        payload_summary="read source-a body",
                        output_refs=["source-a"],
                    ),
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-1",
                        payload_summary="created ev-1 from body artifact",
                        input_refs=["source-a", artifact_ref],
                        output_refs=["ev-1"],
                    ),
                    DomainTraceProposal(
                        event_type="web_research_session_updated",
                        target_type="WebResearchSession",
                        target_id=session.session_id,
                        payload_summary="session recorded body artifact read",
                        input_refs=[session.session_id],
                        output_refs=[session.session_id, artifact_ref, "ev-1"],
                    ),
                    DomainTraceProposal(
                        event_type="read_document_completed",
                        target_type="Artifact",
                        target_id=artifact_ref,
                        payload_summary="fake body artifact read",
                        output_refs=[artifact_ref],
                    ),
                ],
            )

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = DiscoveryScheduler(
                "run-1",
                provider_factory=provider_factory,
                tool_registry_factory=lambda _spec: [
                    ToolDefinition(
                        name="fake_read_document",
                        description="Fake body reader for scheduler E2E tests.",
                        parameters_schema={
                            "type": "object",
                            "required": ["artifact_ref"],
                            "properties": {"artifact_ref": {"type": "string"}},
                        },
                        execute=fake_read_document,
                    )
                ],
                domain_store=store,
                sessions_dir=Path(tmp),
                max_worker_follow_ups_per_assignment=2,
            )
            reports = await scheduler.run_workers(
                [
                    WorkerSpec(
                        role="reader",
                        task_brief="研究极地通信保障能力缺口",
                        tools=["fake_read_document"],
                        budget=RunBudget(max_tool_calls=4, max_tokens=4000),
                        context_pack=ContextPack(
                            agent_role="reader",
                            task_brief="研究极地通信保障能力缺口",
                            sections={},
                            token_budget=800,
                        ),
                        assignment_id="assignment-1",
                        source_id="source-a",
                        source_guidance={
                            "round_id": "round-1",
                            "planned_queries": ["极地通信保障 能力缺口"],
                            "route_hints": ["站内搜索"],
                        },
                    )
                ]
            )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].status, "completed")
        self.assertIn("ev-1", reports[0].evidence_refs)
        self.assertIsNotNone(reports[0].self_check)
        self.assertTrue(reports[0].self_check.allowed_to_finish)
        self.assertEqual(reports[0].follow_up_attempt_count, 1)
        self.assertIn("ev-1", store.evidence)
        self.assertIn(
            "body_artifact_read",
            {
                str(route.get("outcome", ""))
                for session in store.web_research_sessions.values()
                for route in session.attempted_routes
            },
        )
        event_types = [event.event_type for event in store.trace_events]
        self.assertIn("worker_follow_up_planned", event_types)
        self.assertIn("read_document_completed", event_types)
        self.assertIn("worker_report_finalized", event_types)


if __name__ == "__main__":
    unittest.main()
