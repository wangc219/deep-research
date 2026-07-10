from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "demand_discovery_pages"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness  # noqa: E402
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.discovery import create_discover_articles_tool  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402


class DemandDiscoveryDiscoverArticlesToolTests(unittest.TestCase):
    def test_discovers_whitelisted_links_and_records_skipped_outside_links(self) -> None:
        html = (FIXTURE_ROOT / "listing_with_articles.html").read_bytes()

        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
            )

        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            registry = SourceRegistry([_entry()])
            artifacts = ArtifactStore(Path(tmp))
            tool = create_discover_articles_tool(
                store,
                registry,
                artifacts,
                http_transport=transport,
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "discover_articles",
                        {
                            "seed_url": "https://example.test/listing.html",
                            "topic": "低空无人机探测预警",
                            "round_id": "round-1",
                            "max_candidates": 10,
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["selected_count"], 3)
        self.assertEqual(result.details["skipped_count"], 1)
        self.assertIn("https://example.test/articles/radar-warning.html", result.content)
        self.assertIn("selected_leads", result.details)
        self.assertTrue(
            any(
                lead["url"] == "https://example.test/articles/radar-warning.html"
                for lead in result.details["selected_leads"]
            )
        )
        self.assertEqual(
            [proposal.object_type for proposal in result.domain_proposals],
            ["ResearchLead", "ResearchLead", "ResearchLead", "ResearchLead", "ReadingQueue"],
        )
        self.assertNotIn("EvidenceCard", {proposal.object_type for proposal in result.domain_proposals})
        statuses = [proposal.payload["status"] for proposal in result.domain_proposals if proposal.object_type == "ResearchLead"]
        self.assertEqual(statuses.count("selected"), 3)
        self.assertEqual(statuses.count("skipped"), 1)

    def test_harness_flushes_discovered_research_leads_at_save_point(self) -> None:
        html = (FIXTURE_ROOT / "listing_with_articles.html").read_bytes()

        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
            )

        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            registry = SourceRegistry([_entry()])
            artifacts = ArtifactStore(Path(tmp) / "artifacts")
            provider = FakeProvider()
            provider.set_responses(
                [
                    FakeResponse(
                        tool_calls=[
                            {
                                "id": "discover",
                                "name": "discover_articles",
                                "arguments": {
                                    "seed_url": "https://example.test/listing.html",
                                    "topic": "低空无人机探测预警",
                                    "round_id": "round-1",
                                    "max_candidates": 10,
                                },
                            }
                        ]
                    ),
                    FakeResponse(text="done"),
                ]
            )
            harness = DiscoveryHarness(
                provider=provider,
                tools=[
                    create_discover_articles_tool(
                        store,
                        registry,
                        artifacts,
                        http_transport=transport,
                    )
                ],
                trace_store=DomainTraceStore(),
                domain_store=store,
                run_id="run-1",
                agent_run_id="agent-1",
                worker_id="reader",
            )

            assistant = asyncio.run(harness.prompt("discover listing leads"))

        self.assertFalse(assistant.is_error)
        self.assertEqual(len(store.research_leads), 4)
        self.assertEqual(len(store.reading_queues), 1)
        self.assertEqual(
            [event.event_type for event in store.trace_events],
            ["research_leads_discovered"],
        )

    def test_discovers_article_links_from_embedded_story_json(self) -> None:
        html = b"""
<html><body>
<script>
Fusion.globalContent={
  "content_elements":[{
    "canonical_url":"/global/europe/2026/06/03/at-a-nato-range-in-latvia-hits-and-misses-mark-europes-counter-drone-journey/",
    "headlines":{"basic":"At a NATO range in Latvia, hits and misses mark Europe's counter-drone journey"},
    "description":{"basic":"Counter-drone interceptors must work every time."},
    "type":"story"
  }]
};
</script>
</body></html>
"""

        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
            )

        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="Defense News",
                        source_tier="B",
                        source_type="defense_media",
                        hosts=["defensenews.com"],
                        fetch_transport="http",
                        rate_limit_ms=0,
                    )
                ]
            )
            artifacts = ArtifactStore(Path(tmp))
            tool = create_discover_articles_tool(
                store,
                registry,
                artifacts,
                http_transport=transport,
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "discover_articles",
                        {
                            "seed_url": "https://www.defensenews.com/unmanned/",
                            "topic": "counter-drone detection warning",
                            "round_id": "round-1",
                            "max_candidates": 5,
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["selected_count"], 1)
        self.assertIn("https://www.defensenews.com/global/europe/2026/06/03/", result.content)
        self.assertEqual(
            result.details["selected_leads"][0]["url"],
            "https://www.defensenews.com/global/europe/2026/06/03/at-a-nato-range-in-latvia-hits-and-misses-mark-europes-counter-drone-journey/",
        )
        self.assertIn(
            "counter-drone",
            result.details["selected_leads"][0]["title"],
        )

    def test_skips_whitelisted_listing_links_with_low_topic_relevance(self) -> None:
        html = b"""
<html><body><main>
  <a href="/defence/arctic-rescue-sustainment.html">Arctic rescue sustainment exercise exposes logistics gap</a>
  <a href="/weapons/munition-forging.html">Australia's new forging capability to support ADF allies</a>
  <a href="/air/uav-expansion.html">South Korea plans rapid expansion of UAV capabilities</a>
</main></body></html>
"""

        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
            )

        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            registry = SourceRegistry(
                [
                    WhitelistEntry(
                        source_name="Janes",
                        source_tier="B",
                        source_type="defense_media",
                        hosts=["janes.example.test"],
                        fetch_transport="http",
                        rate_limit_ms=0,
                    )
                ]
            )
            artifacts = ArtifactStore(Path(tmp))
            tool = create_discover_articles_tool(
                store,
                registry,
                artifacts,
                http_transport=transport,
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "discover_articles",
                        {
                            "seed_url": "https://janes.example.test/defence-news",
                            "topic": "arctic rescue sustainment logistics capability gap",
                            "round_id": "round-1",
                            "max_candidates": 10,
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["selected_count"], 1)
        self.assertEqual(result.details["skipped_count"], 2)
        self.assertEqual(
            result.details["selected_leads"][0]["url"],
            "https://janes.example.test/defence/arctic-rescue-sustainment.html",
        )
        self.assertIn(
            "topic relevance below threshold",
            {lead["reason"] for lead in result.details["skipped_leads"]},
        )


def _entry() -> WhitelistEntry:
    return WhitelistEntry(
        source_name="Fixture Source",
        source_tier="A",
        source_type="official",
        hosts=["example.test"],
        fetch_transport="http",
        rate_limit_ms=0,
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
