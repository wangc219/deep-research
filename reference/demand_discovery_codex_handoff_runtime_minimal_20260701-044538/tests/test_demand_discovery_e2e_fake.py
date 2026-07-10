from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.audit_rubric import (  # noqa: E402
    load_default_rubric,
)
from knowledgegraph.demand_discovery.domain.orchestration_tools import (  # noqa: E402
    spawn_worker_tool,
)
from knowledgegraph.demand_discovery.domain.report import REQUIRED_SECTIONS  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.context_pack import (  # noqa: E402
    ContextPackBuilder,
)
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.session_store import (  # noqa: E402
    JsonlSessionStore,
)
from knowledgegraph.demand_discovery.harness.trace_store import (  # noqa: E402
    DomainTraceStore,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.workers.agent_defs import (  # noqa: E402
    default_agent_dir,
)


class DemandDiscoveryPhase2FakeE2ETests(unittest.TestCase):
    def test_orchestrator_spawns_readers_auditor_and_generates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            trace_store = DomainTraceStore()
            rubric = load_default_rubric()

            def worker_provider(spec: WorkerSpec) -> FakeProvider:
                provider = FakeProvider()
                if spec.role == "reader":
                    suffix = "a" if "A" in spec.task_brief else "b"
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
                            FakeResponse(text=f"findings:\n- reader {suffix} done"),
                        ]
                    )
                    return provider
                provider.set_responses(
                    [
                        FakeResponse(
                            tool_calls=[
                                {
                                    "id": "audit-1",
                                    "name": "run_audit",
                                    "arguments": {
                                        "audit_id": "audit-1",
                                        "candidate_id": "cand-1",
                                        "conclusion": "approved",
                                        "scorecard": _passing_scorecard(rubric.item_ids),
                                    },
                                }
                            ]
                        ),
                        FakeResponse(text="findings:\n- audit approved"),
                    ]
                )
                return provider

            scheduler = DiscoveryScheduler(
                "run-e2e",
                provider_factory=worker_provider,
                tool_registry_factory=lambda spec: _tools_for_spec(spec, store, rubric),
                domain_store=store,
                trace_store=trace_store,
                sessions_dir=Path(tmp) / "workers",
                max_concurrency=2,
            )
            parent_provider = FakeProvider()
            parent_provider.set_responses(
                [
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "spawn-readers",
                                "name": "spawn_worker",
                                "arguments": {
                                    "tasks": [
                                        {"agent": "reader", "task": "Read A"},
                                        {"agent": "reader", "task": "Read B"},
                                    ]
                                },
                            }
                        ]
                    ),
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "candidate",
                                "name": "create_or_update_candidate",
                                "arguments": {
                                    "candidate_id": "cand-1",
                                    "title": "Candidate demand",
                                    "demand_statement": "Need a validated capability gap.",
                                    "status": "candidate_demand",
                                    "evidence_ids": ["ev-a", "ev-b"],
                                },
                            }
                        ]
                    ),
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "spawn-auditor",
                                "name": "spawn_worker",
                                "arguments": {"agent": "auditor", "task": "Audit cand-1"},
                            }
                        ]
                    ),
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "report",
                                "name": "generate_demand_report",
                                "arguments": {
                                    "report_id": "report-1",
                                    "candidate_id": "cand-1",
                                    "audit_id": "audit-1",
                                    "title": "Report",
                                    "evidence_ids": ["ev-a", "ev-b"],
                                    "demand_type": "inferred",
                                    "sections": {
                                        key: f"{key} content"
                                        for key in REQUIRED_SECTIONS
                                    },
                                },
                            }
                        ]
                    ),
                    FakeResponse(text="done"),
                ]
            )
            tools = [
                *build_domain_tools(store, rubric=rubric),
                spawn_worker_tool(
                    scheduler=scheduler,
                    agent_dir=default_agent_dir(),
                    available_tool_names={
                        tool.name for tool in build_domain_tools(store, rubric=rubric)
                    },
                ),
            ]
            harness = DiscoveryHarness(
                provider=parent_provider,
                tools=tools,
                session_store=JsonlSessionStore(Path(tmp) / "parent.jsonl", run_id="run-e2e"),
                domain_store=store,
                trace_store=trace_store,
                context_builder=ContextPackBuilder(),
                run_id="run-e2e",
                agent_run_id="orchestrator",
                worker_id="orchestrator",
            )

            asyncio.run(harness.prompt("Discover demand"))

            self.assertEqual(set(store.evidence), {"ev-a", "ev-b"})
            self.assertEqual(store.candidates["cand-1"].status, "demand_report")
            self.assertIn("audit-1", store.audit_reports)
            self.assertIn("report-1", store.demand_reports)
            self.assertGreaterEqual(len(scheduler.list_worker_states()), 3)


def _tools_for_spec(spec: WorkerSpec, store: DomainStore, rubric):
    tools = build_domain_tools(store, rubric=rubric)
    active = set(spec.tools)
    return [tool for tool in tools if tool.name in active]


def _passing_scorecard(item_ids: list[str]) -> dict[str, object]:
    scorecard: dict[str, object] = {
        item_id: {"verdict": "pass", "reason": "ok"} for item_id in item_ids
    }
    scorecard["evidence_support"] = {
        "verdict": "pass",
        "reason": "fake e2e evidence directly supports the core conclusion",
        "evidence_reviews": {
            evidence_id: {
                "evidence_id": evidence_id,
                "support_level": "direct",
                "support_type": "inferred_gap",
                "used_for_core": True,
                "reason": "fixture body evidence supports the candidate",
                "missing_link": "",
            }
            for evidence_id in ["ev-a", "ev-b"]
        },
    }
    return scorecard


if __name__ == "__main__":
    unittest.main()
