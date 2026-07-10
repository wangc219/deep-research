from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.open_search import OpenSearchPlan  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    ExcludedSource,
    SourceRegistry,
    WhitelistEntry,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.search import (  # noqa: E402
    OpenSearchHit,
    StaticOpenSearchAdapter,
    create_open_search_sources_batch_tool,
    create_open_search_sources_tool,
)


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class DemandDiscoveryOpenSearchToolTests(unittest.TestCase):
    def test_open_search_rejects_query_outside_plan_queries(self) -> None:
        tool = create_open_search_sources_tool(_store(), _registry(), adapters=[_adapter()])

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "arbitrary unplanned query",
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("query is outside OpenSearchPlan.queries", result.content)

    def test_open_search_respects_plan_budget_across_calls(self) -> None:
        store = _store(allowed_result_count=1)
        tool = create_open_search_sources_tool(store, _registry(), adapters=[_adapter()])

        first = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "远海保障 缺口",
                        "top_k": 5,
                    },
                ),
                _ctx(),
            )
        )
        self.assertFalse(first.is_error)
        staged = store.clone()
        for proposal in first.domain_proposals:
            staged.apply_domain_proposal(proposal)

        second = asyncio.run(
            create_open_search_sources_tool(staged, _registry(), adapters=[_adapter()]).execute(
                ToolCall(
                    "call-2",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "远海保障 缺口",
                        "top_k": 5,
                    },
                ),
                _ctx(),
            )
        )

        self.assertTrue(second.is_error)
        self.assertIn("open search result budget exhausted", second.content)

    def test_open_search_scopes_whitelist_open_excluded_and_bad_scheme(self) -> None:
        tool = create_open_search_sources_tool(_store(), _registry(), adapters=[_adapter()])

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "远海保障 缺口",
                        "top_k": 5,
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        hits = result.details["hits"]
        self.assertEqual(
            [item["source_scope"] for item in hits],
            ["whitelisted", "open_web", "excluded", "excluded"],
        )
        self.assertEqual(len(result.domain_proposals), 1)
        self.assertEqual(result.domain_proposals[0].object_type, "OpenSourceLead")
        self.assertEqual(result.details["used_result_count"], 0)
        self.assertEqual(result.details["remaining_budget_after"], 2)

    def test_open_source_lead_proposals_have_matching_trace_proposals(self) -> None:
        tool = create_open_search_sources_tool(_store(), _registry(), adapters=[_adapter()])

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "远海保障 缺口",
                        "top_k": 5,
                    },
                ),
                _ctx(),
            )
        )

        lead_ids = [
            str(proposal.payload["lead_id"])
            for proposal in result.domain_proposals
            if proposal.object_type == "OpenSourceLead"
        ]
        trace_targets = {
            proposal.target_id
            for proposal in result.trace_proposals
            if proposal.target_type == "OpenSourceLead"
        }

        self.assertEqual(lead_ids, ["osl-7e2a169c1a9f"])
        self.assertTrue(set(lead_ids).issubset(trace_targets))

    def test_open_search_content_prints_open_source_lead_id_for_model_use(self) -> None:
        tool = create_open_search_sources_tool(_store(), _registry(), adapters=[_adapter()])

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "open_search_sources",
                    {
                        "open_search_plan_id": "osp-1",
                        "query": "远海保障 缺口",
                        "top_k": 5,
                    },
                ),
                _ctx(),
            )
        )

        self.assertIn("open_source_lead_id=osl-7e2a169c1a9f", result.content)
        self.assertIn("https://open.example.test/report", result.content)

    def test_open_search_batch_searches_multiple_plan_queries_in_one_call(self) -> None:
        tool = create_open_search_sources_batch_tool(
            _store(allowed_result_count=3),
            _registry(),
            adapters=[_adapter()],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-batch",
                    "open_search_sources_batch",
                    {
                        "open_search_plan_id": "osp-1",
                        "queries": ["远海保障 缺口", "应急通信 交叉验证"],
                        "top_k_per_query": 2,
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertIn("query=远海保障 缺口", result.content)
        self.assertIn("query=应急通信 交叉验证", result.content)
        lead_ids = [
            str(proposal.payload["lead_id"])
            for proposal in result.domain_proposals
            if proposal.object_type == "OpenSourceLead"
        ]
        self.assertEqual(len(lead_ids), len(set(lead_ids)))
        self.assertGreaterEqual(len(lead_ids), 2)
        self.assertEqual(result.details["query_count"], 2)

    def test_build_all_tools_exposes_open_search_only_when_enabled(self) -> None:
        names_without = {
            tool.name
            for tool in build_all_tools(
                _store(),
                _registry(),
                ArtifactStore(PROJECT_ROOT / "outputs" / "test-open-search-off"),
                search_adapters=[],
            )
        }
        names_with = {
            tool.name
            for tool in build_all_tools(
                _store(),
                _registry(),
                ArtifactStore(PROJECT_ROOT / "outputs" / "test-open-search-on"),
                search_adapters=[],
                enable_open_search_tools=True,
                open_search_adapters=[_adapter()],
            )
        }

        self.assertNotIn("open_search_sources", names_without)
        self.assertNotIn("fetch_open_source_page", names_without)
        self.assertIn("open_search_sources", names_with)
        self.assertIn("open_search_sources_batch", names_with)
        self.assertIn("fetch_open_source_page", names_with)


def _store(*, allowed_result_count: int = 3) -> DomainStore:
    store = DomainStore()
    store.upsert_open_search_plan(
        OpenSearchPlan(
            plan_id="osp-1",
            run_id="run-1",
            round_id="round-1",
            topic="远海保障",
            trigger_judgement_id="judge-1",
            trigger_reason="白名单耗尽后补证",
            queries=["远海保障 缺口", "应急通信 交叉验证"],
            allowed_result_count=allowed_result_count,
            status="planned",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return store


def _registry() -> SourceRegistry:
    return SourceRegistry(
        sources=[
            WhitelistEntry(
                source_name="Official",
                source_tier="A",
                source_type="official",
                hosts=["official.example.test"],
                entry_urls=["https://official.example.test/"],
            )
        ],
        excluded=[
            ExcludedSource(
                source_name="Excluded Forum",
                reason="forum rumor",
                hosts=["forum.example.test"],
            )
        ],
    )


def _adapter() -> StaticOpenSearchAdapter:
    return StaticOpenSearchAdapter(
        [
            OpenSearchHit(
                title="白名单结果",
                url="https://official.example.test/article",
                snippet="官方正文线索",
                source_domain="official.example.test",
                search_provider="fixture",
                query_used="远海保障 缺口",
            ),
            OpenSearchHit(
                title="开放网页结果",
                url="https://open.example.test/report",
                snippet="公开机构报告线索",
                source_domain="open.example.test",
                search_provider="fixture",
                query_used="远海保障 缺口",
            ),
            OpenSearchHit(
                title="应急通信交叉验证",
                url="https://agency.example.test/emergency-comms",
                snippet="极端天气 应急通信 交叉验证 正文",
                source_domain="agency.example.test",
                search_provider="fixture",
                query_used="应急通信 交叉验证",
            ),
            OpenSearchHit(
                title="论坛传闻",
                url="https://forum.example.test/thread",
                snippet="低质量论坛线索",
                source_domain="forum.example.test",
                search_provider="fixture",
                query_used="远海保障 缺口",
            ),
            OpenSearchHit(
                title="脚本 URL",
                url="javascript:alert(1)",
                snippet="bad scheme",
                source_domain="",
                search_provider="fixture",
                query_used="远海保障 缺口",
            ),
        ]
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
