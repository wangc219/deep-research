from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    ApparentStopContext,
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)


class WorkerStopPolicyHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_hook_injects_follow_up_on_apparent_stop(self) -> None:
        store = DomainStore()
        injected: list[str] = []

        def policy(ctx: ApparentStopContext) -> list[str]:
            if injected:
                self.assertIn("已按 follow-up", ctx.last_assistant_text)
                return []
            self.assertIn("只有相邻证据", ctx.last_assistant_text)
            self.assertEqual(ctx.follow_up_attempt_count, 0)
            injected.append("continue")
            return ["Self-check failed: current evidence is adjacent-only. Continue."]

        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(text="findings:\n- 只有相邻证据"),
                FakeResponse(text="open_questions:\n- 已按 follow-up 记录盲点"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=[],
            domain_store=store,
            run_id="run-1",
            agent_run_id="agent-1",
            worker_id="reader",
            apparent_stop_follow_up_policy=policy,
        )

        final = await harness.prompt("研究极地通信保障能力缺口")

        self.assertIn("已按 follow-up", final.content[0].text)
        self.assertEqual(injected, ["continue"])

    async def test_hook_does_not_repeat_same_policy_message_without_new_body_delta(self) -> None:
        calls = 0

        def policy(ctx: ApparentStopContext) -> list[str]:
            nonlocal calls
            calls += 1
            return ["repeat follow-up"]

        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(text="findings:\n- 没有正文"),
                FakeResponse(text="findings:\n- 仍没有正文"),
                FakeResponse(text="findings:\n- 不应到第三次"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=[],
            apparent_stop_follow_up_policy=policy,
        )

        final = await harness.prompt("go")

        self.assertIn("仍没有正文", final.content[0].text)
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
