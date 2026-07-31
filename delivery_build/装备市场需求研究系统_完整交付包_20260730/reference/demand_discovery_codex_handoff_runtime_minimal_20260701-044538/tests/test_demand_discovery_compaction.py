from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.compaction import (  # noqa: E402
    CompactionSettings,
    find_cut_point,
    should_compact,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.session_store import (  # noqa: E402
    JsonlSessionStore,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AgentMessage,
    UserMessage,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402


NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


class RecordingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_messages: list[list[AgentMessage]] = []

    def stream(self, context, tools, options):
        self.request_messages.append(list(context.messages))
        return super().stream(context, tools, options)


class DemandDiscoveryCompactionTests(unittest.IsolatedAsyncioTestCase):
    def test_default_compaction_window_matches_gpt55_context(self) -> None:
        settings = CompactionSettings()

        self.assertEqual(settings.context_window, 256_000)
        self.assertGreaterEqual(settings.keep_recent_tokens, 40_000)
        self.assertFalse(should_compact(context_tokens=200_000, settings=settings))

    def test_should_compact_and_cut_point_avoids_tool_result(self) -> None:
        self.assertFalse(
            should_compact(
                context_tokens=10,
                settings=CompactionSettings(context_window=20, reserve_tokens=5),
            )
        )
        self.assertTrue(
            should_compact(
                context_tokens=16,
                settings=CompactionSettings(context_window=20, reserve_tokens=5),
            )
        )
        messages = [
            UserMessage("old user", 0),
            AgentMessage("assistant", "old assistant", 0),
            AgentMessage("tool_result", "orphan result", 0),
            UserMessage("recent user", 0),
            AgentMessage("assistant", "recent assistant", 0),
        ]

        cut = find_cut_point(messages, keep_recent_tokens=4)

        self.assertEqual(messages[cut.index].role, "user")
        self.assertFalse(cut.split_turn)

    async def test_compaction_projects_summary_into_next_prompt(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(text="first answer with enough content"),
                FakeResponse(text="compact narrative"),
                FakeResponse(text="second answer"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            harness = DiscoveryHarness(
                provider=provider,
                session_store=JsonlSessionStore(session_path, run_id="run-compact"),
                run_id="run-compact",
                compaction_settings=CompactionSettings(
                    context_window=1,
                    reserve_tokens=0,
                    keep_recent_tokens=1,
                ),
            )

            await harness.prompt("first prompt")
            await harness.prompt("second prompt")

            second_prompt_messages = provider.request_messages[2]
            self.assertIn("compact narrative", str(second_prompt_messages[0].content))
            rows = session_path.read_text(encoding="utf-8")
            self.assertIn('"type": "compaction"', rows)
            self.assertIn("first prompt", rows)

    async def test_compaction_summary_appends_programmatic_domain_index(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(text="first answer with enough content"),
                FakeResponse(text="compact narrative"),
            ]
        )
        store = _seed_store()
        harness = DiscoveryHarness(
            provider=provider,
            domain_store=store,
            compaction_settings=CompactionSettings(
                context_window=1,
                reserve_tokens=0,
                keep_recent_tokens=1,
            ),
        )

        await harness.prompt("first prompt")

        projected = harness.messages
        self.assertTrue(projected)
        compacted_context = provider.request_messages[1]
        self.assertGreaterEqual(len(compacted_context), 1)
        summary = harness._compaction.summary  # noqa: SLF001 - state projection contract
        self.assertIn("compact narrative", summary)
        self.assertIn("ev-1", summary)
        self.assertIn("cand-1", summary)

    async def test_compaction_failure_is_non_fatal(self) -> None:
        def fail_summary(context, state) -> AssistantMessage:
            raise RuntimeError("summary failed")

        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(text="first answer with enough content"),
                FakeResponse(factory=fail_summary),
            ]
        )
        events: list[AgentEvent] = []
        harness = DiscoveryHarness(
            provider=provider,
            compaction_settings=CompactionSettings(
                context_window=1,
                reserve_tokens=0,
                keep_recent_tokens=1,
            ),
        )
        harness.subscribe(events.append)

        message = await harness.prompt("first prompt")

        self.assertEqual(message.role, "assistant")
        self.assertIn("compaction_failed", [event.type for event in events])

    async def test_from_session_restores_compaction_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "session.jsonl"
            store = JsonlSessionStore(session_path, run_id="run-restore")
            store.append(
                "message",
                {"role": "user", "content": "old prompt", "timestamp": 0},
                run_id="run-restore",
            )
            store.append("save_point", {}, run_id="run-restore")
            store.append(
                "compaction",
                {
                    "summary": "restored compact summary",
                    "cut_index": 1,
                    "split_turn": False,
                },
                run_id="run-restore",
            )
            provider = RecordingProvider()
            provider.set_responses([FakeResponse(text="after restore")])

            harness = DiscoveryHarness.from_session(
                session_path,
                provider=provider,
                tools=[],
                domain_store=DomainStore(),
            )
            await harness.prompt("new prompt")

            self.assertIn(
                "restored compact summary",
                str(provider.request_messages[0][0].content),
            )


def _seed_store() -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source title",
            source_name="Source",
            source_tier="A",
            source_type="journal",
            publish_time=NOW,
            url_or_path="https://example.test/source",
            summary_text="summary",
            summary_source="structured",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="claim",
            evidence_summary="summary",
            excerpt="excerpt",
            source_location="p1",
            evidence_assessment="strong",
            created_by="tester",
            created_at=NOW,
        )
    )
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="Need capability.",
            status="candidate_demand",
            evidence_ids=["ev-1"],
            open_questions=["open question"],
            solution_signals=[],
            created_by="tester",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


if __name__ == "__main__":
    unittest.main()
