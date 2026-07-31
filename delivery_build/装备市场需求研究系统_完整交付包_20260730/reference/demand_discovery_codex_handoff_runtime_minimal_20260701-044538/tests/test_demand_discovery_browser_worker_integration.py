from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.open_search import OpenSearchPlan, OpenSourceLead  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.network_research import _worker_round_brief  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_actions import BrowserPageSnapshot  # noqa: E402


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class BrowserWorkerIntegrationTests(unittest.TestCase):
    def test_browser_tools_are_compact_and_do_not_expose_action_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                DomainStore(),
                _registry(),
                ArtifactStore(Path(tmp)),
                enable_browser_tools=True,
            )
        names = [tool.name for tool in tools]
        self.assertIn("browser_observe", names)
        self.assertIn("browser_execute", names)
        self.assertNotIn("browser_action", names)
        execute_tool = next(tool for tool in tools if tool.name == "browser_execute")
        schema_text = str(execute_tool.parameters_schema)
        self.assertIn("target_action", schema_text)
        self.assertIn("javascript", schema_text)
        javascript_schema = execute_tool.parameters_schema["properties"]["javascript"]
        self.assertEqual(
            javascript_schema["required"],
            [
                "script",
                "expected_result",
                "why_standard_actions_are_insufficient",
                "result_sink",
                "fallback",
            ],
        )
        self.assertNotIn("js_use_case", schema_text)
        self.assertLess(len(schema_text), 2600)

    def test_build_all_tools_derives_open_source_lead_browser_scope(self) -> None:
        store = _store_with_open_source_lead()
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                store,
                _registry(),
                ArtifactStore(Path(tmp)),
                enable_browser_tools=True,
                browser_session=_OpenBrowser(),
            )
            observe_tool = next(tool for tool in tools if tool.name == "browser_observe")
            allowed = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "allowed",
                        "browser_observe",
                        {"url": "https://open.example.org/article", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            blocked_same_host_other_path = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "blocked-same-host",
                        "browser_observe",
                        {"url": "https://open.example.org/other", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            blocked = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "blocked",
                        "browser_observe",
                        {"url": "https://outside.example.org/article", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
        self.assertFalse(allowed.is_error)
        self.assertEqual(allowed.details["source_scope"]["scope_type"], "open_search_plan")
        self.assertEqual(allowed.details["source_scope"]["plan_id"], "osp-1")
        self.assertEqual(allowed.details["source_scope"]["lead_id"], "osl-1")
        self.assertTrue(blocked_same_host_other_path.is_error)
        self.assertIn("outside browser URL scope", blocked_same_host_other_path.content)
        self.assertTrue(blocked.is_error)
        self.assertIn("outside browser URL scope", blocked.content)

    def test_active_open_search_plan_does_not_allow_search_engine_anchor(self) -> None:
        store = _store_with_open_search_plan_only()
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                store,
                _registry(),
                ArtifactStore(Path(tmp)),
                enable_browser_tools=True,
                browser_session=_OpenBrowser(),
            )
            observe_tool = next(tool for tool in tools if tool.name == "browser_observe")
            result = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "google-search",
                        "browser_observe",
                        {
                            "url": "https://www.google.com/search?q=%E8%BF%9C%E6%B5%B7",
                            "topic": "远海",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("outside browser URL scope", result.content)

    def test_search_engine_observation_does_not_record_open_source_leads(self) -> None:
        store = _store_with_open_search_plan_only()
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                store,
                _registry(),
                ArtifactStore(Path(tmp)),
                enable_browser_tools=True,
                browser_session=_GoogleResultsBrowser(),
            )
            observe_tool = next(tool for tool in tools if tool.name == "browser_observe")
            result = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "google-search",
                        "browser_observe",
                        {
                            "url": "https://www.google.com/search?q=%E8%BF%9C%E6%B5%B7",
                            "topic": "远海无人平台维护保障能力缺口",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("outside browser URL scope", result.content)
        self.assertEqual(result.domain_proposals, [])

    def test_worker_brief_exposes_provider_search_and_scoped_browser_fallback_for_open_search_round(self) -> None:
        brief = _worker_round_brief(
            "远海无人平台维护保障能力缺口",
            ["https://example.test/search"],
            "round-2",
            allow_open_search=True,
            open_search_plan_id="osp-1",
            open_search_queries=["远海无人平台 维护保障"],
            allow_browser=True,
        )

        self.assertIn("provider-backed open_search_sources", brief)
        self.assertIn("browser_observe", brief)
        self.assertIn("browser_execute", brief)
        self.assertIn("authorized URL scope", brief)
        self.assertIn("record a blind spot", brief)
        self.assertNotIn("Google Search browser anchor", brief)
        self.assertNotIn("https://www.google.com/search?q=", brief)

    def test_worker_brief_explains_browser_js_evidence_boundaries(self) -> None:
        brief = _worker_round_brief(
            "远海无人平台维护保障能力缺口",
            ["https://example.test/search"],
            "round-1",
            source_guidance=[
                {
                    "url": "https://example.test/search",
                    "source_name": "Example",
                    "content_languages": ["zh"],
                    "planned_queries": ["远海无人平台 维护保障"],
                }
            ],
            allow_browser=True,
        )
        self.assertIn("browser_observe", brief)
        self.assertIn("browser_execute", brief)
        self.assertIn("JavaScript", brief)
        self.assertIn("why_standard_actions_are_insufficient", brief)
        self.assertIn("result_sink", brief)
        self.assertIn("fallback", brief)
        self.assertIn("capture_current_document", brief)
        self.assertIn("read_document", brief)
        self.assertIn("Do not create EvidenceCard from browser observation", brief)


class _OpenBrowser:
    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            url=url,
            html="<html><head><title>开放来源文章</title></head><body><article>公开正文</article></body></html>",
        )


class _GoogleResultsBrowser:
    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            url=url,
            html=(
                "<html><head><title>Google Search</title></head><body>"
                "<a href='https://open.example.org/article'>开放来源文章</a>"
                "<a href='https://www.google.com/preferences'>Google settings</a>"
                "<a href='https://example.test/whitelisted'>白名单文章</a>"
                "</body></html>"
            ),
        )


def _store_with_open_source_lead() -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海无人平台维护保障能力缺口",
            trigger_judgement_id="judge-1",
            trigger_reason="whitelist exhausted",
            queries=["远海无人平台 维护保障"],
            allowed_result_count=5,
            status="running",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_open_source_lead(
        OpenSourceLead(
            lead_id="osl-1",
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-2",
            topic="远海无人平台维护保障能力缺口",
            url="https://open.example.org/article",
            domain="open.example.org",
            title="开放来源文章",
            snippet="公开正文摘要",
            source_name_guess="Open web usable fixture",
            search_query="远海无人平台 维护保障",
            source_scope="open_web",
            quality_status="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _store_with_open_search_plan_only() -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海无人平台维护保障能力缺口",
            trigger_judgement_id="judge-1",
            trigger_reason="whitelist exhausted",
            queries=["远海无人平台 维护保障"],
            allowed_result_count=5,
            status="running",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _registry() -> SourceRegistry:
    return SourceRegistry(
        [
            WhitelistEntry(
                source_name="Example",
                source_tier="A",
                source_type="official",
                hosts=["example.test"],
                fetch_transport="http",
                entry_urls=["https://example.test/search"],
                interaction_profile="browser_search",
            )
        ]
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
