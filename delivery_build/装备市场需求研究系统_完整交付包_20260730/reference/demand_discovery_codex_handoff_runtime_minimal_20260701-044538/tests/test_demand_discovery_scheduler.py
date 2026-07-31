from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import time
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.cancellation import (  # noqa: E402
    CancelToken,
)
from knowledgegraph.demand_discovery.harness.context_pack import (  # noqa: E402
    ContextPack,
)
from knowledgegraph.demand_discovery.harness.event_bus import EventBus  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.trace_store import (  # noqa: E402
    DomainTraceStore,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


async def _noop(call, ctx):
    return ToolResult(call.id, call.name, "ok", {})


def _pack(role: str, marker: str) -> ContextPack:
    return ContextPack(
        agent_role=role,
        task_brief=marker,
        sections={"marker": marker},
        token_budget=800,
    )


def _spec(role: str, marker: str, tools: list[str] | None = None) -> WorkerSpec:
    return WorkerSpec(
        role=role,
        task_brief=marker,
        tools=tools or ["create_source_record", "create_evidence_card"],
        budget=RunBudget(max_tool_calls=20),
        context_pack=_pack(role, marker),
    )


class RecordingFakeProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.seen_options: list[dict] = []
        self.seen_prompts: list[str] = []

    def stream(self, context, tools, options):
        self.seen_options.append(dict(options))
        messages = list(getattr(context, "messages", []) or [])
        if messages:
            self.seen_prompts.append(str(getattr(messages[-1], "content", "")))
        return super().stream(context, tools, options)


class DemandDiscoverySchedulerTests(unittest.TestCase):
    def test_worker_harnesses_write_isolated_sessions_and_shared_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            trace_store = DomainTraceStore()

            def provider_factory(spec: WorkerSpec) -> FakeProvider:
                suffix = spec.task_brief
                provider = FakeProvider()
                provider.set_responses(
                    [
                        FakeResponse(
                            tool_calls=[
                                {
                                    "id": f"src-{suffix}",
                                    "name": "create_source_record",
                                    "arguments": {
                                        "source_id": f"src-{suffix}",
                                        "title": f"Source {suffix}",
                                        "source_name": "fixture",
                                        "source_tier": "A",
                                        "source_type": "document",
                                        "url_or_path": f"fixture://{suffix}",
                                        "summary_text": "summary",
                                        "summary_source": "manual",
                                        "collection_decision": "use_as_evidence",
                                    },
                                },
                                {
                                    "id": f"ev-{suffix}",
                                    "name": "create_evidence_card",
                                    "arguments": {
                                        "evidence_id": f"ev-{suffix}",
                                        "source_id": f"src-{suffix}",
                                        "claim": f"claim {suffix}",
                                        "evidence_summary": f"summary {suffix}",
                                        "excerpt": f"excerpt {suffix}",
                                        "source_location": "p1",
                                    },
                                },
                            ]
                        ),
                        FakeResponse(
                            text=(
                                "findings:\n"
                                f"- finding {suffix}\n"
                                "open_questions:\n"
                                "- verify one point\n"
                                "need_more_sources: false\n"
                                "risks:\n"
                                "- no conflict"
                            )
                        ),
                    ]
                )
                return provider

            scheduler = DiscoveryScheduler(
                "run-phase2",
                provider_factory=provider_factory,
                tool_registry_factory=lambda spec: build_domain_tools(store),
                domain_store=store,
                trace_store=trace_store,
                sessions_dir=Path(tmp),
                cancel_token=CancelToken(),
                max_concurrency=2,
            )

            reports = asyncio.run(
                scheduler.run_workers(
                    [_spec("reader", "a"), _spec("reader", "b")]
                )
            )

            self.assertEqual([report.status for report in reports], ["completed", "completed"])
            self.assertEqual(set(store.sources), {"src-a", "src-b"})
            self.assertEqual(set(store.evidence), {"ev-a", "ev-b"})
            self.assertEqual(
                {item for report in reports for item in report.new_evidence_cards},
                {"ev-a", "ev-b"},
            )
            self.assertEqual(len(list(Path(tmp).glob("agent-*.jsonl"))), 2)

    def test_max_concurrency_one_runs_workers_serially(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str, float]] = []

            async def slow(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
                calls.append((str(call.arguments["marker"]), "start", time.monotonic()))
                await asyncio.sleep(0.05)
                calls.append((str(call.arguments["marker"]), "end", time.monotonic()))
                return ToolResult(call.id, call.name, "ok", {})

            def provider_factory(spec: WorkerSpec) -> FakeProvider:
                provider = FakeProvider()
                provider.set_responses(
                    [
                        FakeResponse(
                            tool_calls=[
                                {
                                    "id": f"slow-{spec.task_brief}",
                                    "name": "slow",
                                    "arguments": {"marker": spec.task_brief},
                                }
                            ]
                        ),
                        FakeResponse(text=f"findings:\n- {spec.task_brief}"),
                    ]
                )
                return provider

            scheduler = DiscoveryScheduler(
                "run-serial",
                provider_factory=provider_factory,
                tool_registry_factory=lambda spec: [
                    ToolDefinition(
                        "slow",
                        "",
                        {
                            "type": "object",
                            "required": ["marker"],
                            "properties": {"marker": {"type": "string"}},
                        },
                        slow,
                    )
                ],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
                max_concurrency=1,
            )

            asyncio.run(scheduler.run_workers([_spec("reader", "a", ["slow"]), _spec("reader", "b", ["slow"])]))

            first_end = next(t for marker, phase, t in calls if marker == "a" and phase == "end")
            second_start = next(t for marker, phase, t in calls if marker == "b" and phase == "start")
            self.assertLessEqual(first_end, second_start)

    def test_worker_failure_returns_failed_report_without_stopping_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:

            def provider_factory(spec: WorkerSpec) -> FakeProvider:
                if spec.task_brief == "bad":
                    raise RuntimeError("provider setup failed")
                provider = FakeProvider()
                provider.set_responses([FakeResponse(text="findings:\n- ok")])
                return provider

            scheduler = DiscoveryScheduler(
                "run-failure",
                provider_factory=provider_factory,
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
                max_concurrency=2,
            )

            reports = asyncio.run(
                scheduler.run_workers(
                    [_spec("reader", "bad", []), _spec("reader", "good", [])]
                )
            )

            by_task = {report.task_brief: report for report in reports}
            self.assertEqual(by_task["bad"].status, "failed")
            self.assertIn("provider setup failed", by_task["bad"].error)
            self.assertEqual(by_task["good"].status, "completed")

    def test_cancel_worker_marks_only_target_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = DiscoveryScheduler(
                "run-cancel",
                provider_factory=lambda spec: FakeProvider(),
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
                max_concurrency=2,
            )

            first = asyncio.run(scheduler.spawn_worker(_spec("reader", "a", [])))
            second = asyncio.run(scheduler.spawn_worker(_spec("reader", "b", [])))
            asyncio.run(scheduler.cancel_worker(first))

            states = {state.agent_run_id: state.status for state in scheduler.list_worker_states()}
            self.assertEqual(states[first], "cancelled")
            self.assertEqual(states[second], "pending")

    def test_worker_events_include_run_agent_and_parent_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = DiscoveryScheduler(
                "run-events",
                provider_factory=lambda spec: FakeProvider(),
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
            )

            agent_run_id = asyncio.run(
                scheduler.spawn_worker(_spec("reader", "a", []), parent_event_id="parent-1")
            )

            event = scheduler.events[0]
            self.assertEqual(event.run_id, "run-events")
            self.assertEqual(event.agent_run_id, agent_run_id)
            self.assertEqual(event.payload["parent_event_id"], "parent-1")

    def test_event_bus_receives_child_runtime_events_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus()
            seen = []
            bus.subscribe(seen.append, categories={"agent_runtime"})

            provider = FakeProvider()
            provider.set_responses([FakeResponse(text="findings:\n- done")])
            scheduler = DiscoveryScheduler(
                "run-event-bus",
                provider_factory=lambda spec: provider,
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
                event_bus=bus,
            )

            asyncio.run(scheduler.run_workers([_spec("reader", "a", [])]))

            event_types = [event.event_type for event in seen]
            self.assertEqual(event_types.count("agent_start"), 1)
            self.assertEqual(event_types.count("turn_start"), 1)
            self.assertEqual(event_types.count("message_start"), 1)
            self.assertEqual(event_types.count("turn_end"), 1)

    def test_auditor_worker_passes_composer_options_to_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = RecordingFakeProvider()
            provider.set_responses([FakeResponse(text="audit completed")])
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

            scheduler = DiscoveryScheduler(
                "run-auditor-options",
                provider_factory=lambda _spec: provider,
                tool_registry_factory=lambda _spec: [
                    ToolDefinition(
                        "run_audit",
                        "",
                        {"type": "object", "properties": {}},
                        _noop,
                    )
                ],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp),
            )

            asyncio.run(scheduler.run_workers([spec]))

            self.assertTrue(provider.seen_options)
            options = provider.seen_options[0]
            schema_text = str(options.get("output_schema", {}))
            self.assertIn("scorecard", schema_text)
            self.assertIn("recommended_report_status", schema_text)
            self.assertFalse(options["parallel_tool_calls"])
            self.assertIn('"audit_context"', provider.seen_prompts[0])


if __name__ == "__main__":
    unittest.main()
