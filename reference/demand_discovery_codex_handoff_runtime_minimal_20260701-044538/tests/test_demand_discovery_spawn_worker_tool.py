from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.orchestration_tools import (  # noqa: E402
    spawn_worker_tool,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack  # noqa: E402
from knowledgegraph.demand_discovery.harness.scheduler import (  # noqa: E402
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.trace_store import (  # noqa: E402
    DomainTraceStore,
)
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


def _agent_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "reader.md").write_text(
        """---
name: reader
description: Read sources
tools: missing_tool, create_evidence_card
model: default
budget: {"max_tool_calls": 5}
---
Reader prompt.
""",
        encoding="utf-8",
    )
    return root


class DemandDiscoverySpawnWorkerToolTests(unittest.TestCase):
    def test_single_parallel_and_chain_modes_return_digest_and_full_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            briefs_seen: list[str] = []

            def provider_factory(spec: WorkerSpec) -> FakeProvider:
                briefs_seen.append(spec.task_brief)
                provider = FakeProvider()
                provider.set_responses(
                    [FakeResponse(text=f"findings:\n- handled {spec.task_brief}")]
                )
                return provider

            scheduler = DiscoveryScheduler(
                "run-spawn",
                provider_factory=provider_factory,
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp) / "sessions",
                max_concurrency=2,
            )
            tool = spawn_worker_tool(
                scheduler=scheduler,
                agent_dir=_agent_dir(Path(tmp) / "agents"),
                available_tool_names={"create_evidence_card"},
            )
            ctx = ToolExecutionContext(
                run_id="run-spawn",
                agent_run_id="parent",
                worker_id="orchestrator",
            )

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "spawn_worker",
                        {
                            "tasks": [
                                {"agent": "reader", "task": "first"},
                                {"agent": "reader", "task": "second"},
                            ]
                        },
                    ),
                    ctx,
                )
            )

            self.assertFalse(result.is_error)
            self.assertIn("handled first", result.content)
            self.assertEqual(len(result.details["reports"]), 2)
            self.assertEqual(result.domain_proposals, [])
            self.assertEqual(result.trace_proposals, [])
            self.assertEqual(
                result.details["missing_tools_by_agent"]["reader"], ["missing_tool"]
            )

            chain = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-2",
                        "spawn_worker",
                        {
                            "chain": [
                                {"agent": "reader", "task": "alpha"},
                                {"agent": "reader", "task": "beta after {previous}"},
                            ]
                        },
                    ),
                    ctx,
                )
            )

            self.assertFalse(chain.is_error)
            self.assertIn("beta after", briefs_seen[-1])
            self.assertIn("handled alpha", briefs_seen[-1])

    def test_rejects_ambiguous_or_too_large_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = DiscoveryScheduler(
                "run-spawn",
                provider_factory=lambda spec: FakeProvider(),
                tool_registry_factory=lambda spec: [],
                domain_store=DomainStore(),
                trace_store=DomainTraceStore(),
                sessions_dir=Path(tmp) / "sessions",
            )
            tool = spawn_worker_tool(
                scheduler=scheduler,
                agent_dir=_agent_dir(Path(tmp) / "agents"),
                available_tool_names=set(),
            )
            ctx = ToolExecutionContext("run-spawn", "parent", "orchestrator")

            ambiguous = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-ambiguous",
                        "spawn_worker",
                        {
                            "agent": "reader",
                            "task": "one",
                            "tasks": [{"agent": "reader", "task": "two"}],
                        },
                    ),
                    ctx,
                )
            )
            too_many = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-many",
                        "spawn_worker",
                        {
                            "tasks": [
                                {"agent": "reader", "task": str(index)}
                                for index in range(9)
                            ]
                        },
                    ),
                    ctx,
                )
            )

            self.assertTrue(ambiguous.is_error)
            self.assertTrue(too_many.is_error)


if __name__ == "__main__":
    unittest.main()
