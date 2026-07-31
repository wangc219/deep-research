from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SearchConfig,
    SourceRegistry,
    WhitelistEntry,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.keyword_gate import KeywordGate  # noqa: E402
from knowledgegraph.demand_discovery.tools.search import (  # noqa: E402
    DynamicApiSearchAdapter,
    LocalCorpusAdapter,
    SearchHit,
    StaticSearchAdapter,
    UrlTemplateAdapter,
    build_default_search_adapters,
    create_search_sources_tool,
    _discover_dynamic_api_specs,
    _looks_like_json_search_endpoint,
    _requests_json,
    _requests_text,
    _script_defaults,
)


class DemandDiscoverySearchToolTests(unittest.TestCase):
    def test_search_sources_merges_and_ranks_hits_with_keyword_gate(self) -> None:
        adapter = StaticSearchAdapter(
            [
                SearchHit(
                    title="generic logistics",
                    url="https://example.test/logistics",
                    snippet="后勤保障动态",
                    source_name="Fixture",
                    source_tier="B",
                ),
                SearchHit(
                    title="low altitude gap",
                    url="https://example.test/uas",
                    snippet="复杂环境下低空探测能力需求和短板",
                    source_name="Fixture",
                    source_tier="B",
                ),
            ]
        )
        tool = create_search_sources_tool(
            SourceRegistry([_entry()]),
            KeywordGate({"demand": ["需求"], "gap": ["短板"], "scenario": ["复杂环境"]}),
            adapters=[adapter],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "call-1",
                    "search_sources",
                    {"query": "低空探测需求", "top_k": 2},
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["hits"][0]["title"], "low altitude gap")
        self.assertGreater(result.details["hits"][0]["keyword_score"], 0)
        self.assertIn("low altitude gap", result.content)

    def test_build_all_tools_includes_network_and_domain_tools(self) -> None:
        names = {
            tool.name
            for tool in build_all_tools(
                DomainStore(),
                SourceRegistry([_entry()]),
                ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
                search_adapters=[],
            )
        }

        for name in [
            "search_sources",
            "fetch_page",
            "read_document",
            "extract_summary",
            "create_evidence_card",
            "generate_demand_report",
        ]:
            self.assertIn(name, names)

    def test_build_all_tools_default_search_uses_local_artifact_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            artifacts.put(
                "复杂环境下低空探测能力需求仍有短板",
                kind="text",
                meta={
                    "title": "stored seed source",
                    "url": "https://example.test/stored",
                    "source_name": "Fixture",
                    "source_tier": "B",
                },
            )
            search_tool = next(
                tool
                for tool in build_all_tools(
                    DomainStore(),
                    SourceRegistry([_entry()]),
                    artifacts,
                )
                if tool.name == "search_sources"
            )

            result = asyncio.run(
                search_tool.execute(
                    ToolCall(
                        "call-1",
                        "search_sources",
                        {"query": "低空探测需求", "top_k": 3},
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["hits"][0]["title"], "stored seed source")

    def test_default_search_adapters_do_not_import_whitelist_topic_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = WhitelistEntry(
                source_name="Fixture",
                source_tier="A",
                source_type="official",
                hosts=["example.test"],
                search=SearchConfig(
                    type="dynamic_api",
                    template="https://example.test/search?keyword={query}",
                ),
                default_queries=["反无人机"],
            )

            adapters = build_default_search_adapters(
                SourceRegistry([entry]),
                ArtifactStore(Path(tmp)),
                fetch_text=lambda url: "",
            )

        dynamic = next(
            adapter
            for adapter in adapters
            if isinstance(adapter, DynamicApiSearchAdapter)
        )
        self.assertEqual(dynamic.default_queries, [])

    def test_build_all_tools_source_record_uses_registry_tier_for_matching_url(self) -> None:
        source_tool = next(
            tool
            for tool in build_all_tools(
                DomainStore(),
                SourceRegistry([_entry(source_tier="A", source_type="official")]),
                ArtifactStore(PROJECT_ROOT / "outputs" / "test-artifacts"),
                search_adapters=[],
            )
            if tool.name == "create_source_record"
        )

        result = asyncio.run(
            source_tool.execute(
                ToolCall(
                    "call-1",
                    "create_source_record",
                    {
                        "source_id": "src-model",
                        "title": "Model source",
                        "source_name": "model supplied name",
                        "source_tier": "B",
                        "source_type": "document",
                        "url_or_path": "https://example.test/report",
                    },
                ),
                _ctx(),
            )
        )

        self.assertFalse(result.is_error)
        payload = result.domain_proposals[0].payload
        self.assertEqual(payload["source_name"], "Fixture")
        self.assertEqual(payload["source_tier"], "A")
        self.assertEqual(payload["source_type"], "official")

    def test_local_corpus_adapter_searches_artifact_texts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            ref = artifacts.put(
                "低空无人机探测预警能力需求\n\n复杂环境下存在短板",
                kind="text",
                meta={
                    "title": "artifact low altitude",
                    "url": "https://example.test/artifact",
                    "source_name": "Fixture",
                    "source_tier": "B",
                },
            )
            adapter = LocalCorpusAdapter(artifacts)

            hits = asyncio.run(adapter.search("低空探测需求", 1))

        self.assertEqual(hits[0].title, "artifact low altitude")
        self.assertEqual(hits[0].url, "https://example.test/artifact")
        self.assertIn(ref, hits[0].snippet)

    def test_url_template_adapter_parses_links_from_mock_result_page(self) -> None:
        async def fetch(url: str) -> str:
            self.assertIn("q=%E4%BD%8E%E7%A9%BA", url)
            return """
            <html><body>
              <a href="/a">低空探测需求</a>
              <p>复杂环境下存在预警短板</p>
            </body></html>
            """

        adapter = UrlTemplateAdapter(
            source_name="Fixture",
            source_tier="B",
            template="https://example.test/search?q={query}&page={page}",
            fetch_text=fetch,
        )

        hits = asyncio.run(adapter.search("低空", 1))

        self.assertEqual(hits[0].title, "低空探测需求")
        self.assertEqual(hits[0].url, "https://example.test/a")
        self.assertIn("复杂环境", hits[0].snippet)

    def test_dynamic_api_adapter_discovers_same_site_json_search_from_scripts(self) -> None:
        fetched_urls: list[str] = []
        requested_params: list[dict[str, object]] = []

        async def fetch_text(url: str) -> str:
            fetched_urls.append(url)
            if url.endswith("/search?keyword=%E4%BD%8E%E7%A9%BA&page=1"):
                return """
                <html><body>
                  <script src="/assets/search.js"></script>
                </body></html>
                """
            if url.endswith("/assets/search.js"):
                return """
                var pageNumber = 1;
                var pageSize = 10;
                var channelId = 636;
                var params = {
                  "pageNumber": pageNumber,
                  "pageSize": pageSize,
                  "indexNames": "manuscript",
                  "highlightType": 2,
                  "content": keyword,
                  "searchType": 2,
                  "accessToken": "token-for-fixture",
                  "channelId": channelId
                };
                $.ajax({
                  type: "GET",
                  url: document.location.protocol + "//api.example.test/api-surface/es/docSearchEasy",
                  data: params
                });
                """
            raise AssertionError(f"unexpected fetch_text URL: {url}")

        async def fetch_json(url: str, params: dict[str, object]) -> object:
            requested_params.append(dict(params))
            self.assertEqual(url, "https://api.example.test/api-surface/es/docSearchEasy")
            if params.get("content") != "低空":
                return {"code": 200, "data": {"total": 0, "resultList": []}}
            return {
                "code": 200,
                "data": {
                    "total": 1,
                    "resultList": [
                        {
                            "title": "低空无人机防御训练",
                            "desc": "低空预警与反无人机防护短板",
                            "issueTime": 1773875953,
                            "manuscriptData": {
                                "url": "https://example.test/articles/uas",
                                "classify_name": "训练",
                            },
                        }
                    ],
                },
            }

        adapter = DynamicApiSearchAdapter(
            source_name="Fixture",
            source_tier="A",
            template="https://example.test/search?keyword={query}&page={page}",
            allowed_hosts=["example.test"],
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )

        hits = asyncio.run(adapter.search("低空", 1))

        self.assertIn("https://example.test/assets/search.js", fetched_urls)
        self.assertEqual(hits[0].title, "低空无人机防御训练")
        self.assertEqual(hits[0].url, "https://example.test/articles/uas")
        self.assertEqual(hits[0].source_tier, "A")
        self.assertTrue(
            any(params.get("accessToken") == "token-for-fixture" for params in requested_params)
        )

    def test_dynamic_api_defaults_resolve_fallback_query_parameters(self) -> None:
        script = """
        var keyword = getQueryString("keyword");
        var indexsearch = Number(getQueryString("indexsearch"));
        var channelId = getQueryString('channelId') ? getQueryString('channelId') : 636;
        var pageSize = 10;
        var pageNumber = 1;
        if (!indexsearch) {
          indexsearch = 2;
        }
        params = {
          "pageNumber": pageNumber,
          "pageSize": pageSize,
          "indexNames": "manuscript",
          "highlightType": 2,
          "content": keyword,
          "searchType": indexsearch,
          "accessToken": "token-for-fixture",
          "channelId": channelId
        };
        """

        defaults = _script_defaults(script)

        self.assertEqual(defaults["pageNumber"], 1)
        self.assertEqual(defaults["pageSize"], 10)
        self.assertEqual(defaults["indexNames"], "manuscript")
        self.assertEqual(defaults["highlightType"], 2)
        self.assertEqual(defaults["searchType"], 2)
        self.assertEqual(defaults["accessToken"], "token-for-fixture")
        self.assertEqual(defaults["channelId"], 636)

    def test_dynamic_api_discovery_ignores_tracking_endpoints(self) -> None:
        html = """
        <html><body>
          <script>
            $.ajax({type: "GET", url: "https://metrics.example.test/api-traffic/web/poll?u="});
          </script>
          <script src="/assets/search.js"></script>
        </body></html>
        """

        async def fetch_text(url: str) -> str:
            self.assertEqual(url, "https://example.test/assets/search.js")
            return """
            var keyword = getQueryString("keyword");
            var pageNumber = 1;
            var pageSize = 10;
            var params = {
              pageNumber: pageNumber,
              pageSize: pageSize,
              content: keyword
            };
            $.ajax({
              type: "GET",
              url: document.location.protocol + "//api.example.test/api-surface/es/docSearchEasy",
              data: params
            });
            """

        specs = asyncio.run(
            _discover_dynamic_api_specs(
                html,
                "https://example.test/search?keyword=low",
                allowed_hosts=["example.test"],
                fetch_text=fetch_text,
            )
        )

        self.assertEqual([spec.url for spec in specs], ["https://api.example.test/api-surface/es/docSearchEasy"])
        self.assertFalse(_looks_like_json_search_endpoint("https://metrics.example.test/api-traffic/web/poll?u="))

    def test_dynamic_api_adapter_prefers_json_search_over_static_navigation(self) -> None:
        requested_urls: list[str] = []

        async def fetch_text(url: str) -> str:
            if url.endswith("/search?keyword=%E4%BD%8E%E7%A9%BA&page=1"):
                return """
                <html><body>
                  <nav><a href="/">首页</a><a href="/news">要闻</a></nav>
                  <script src="/assets/search.js"></script>
                </body></html>
                """
            if url.endswith("/assets/search.js"):
                return """
                var keyword = getQueryString("keyword");
                var indexsearch = Number(getQueryString("indexsearch"));
                if (!indexsearch) { indexsearch = 2; }
                var channelId = getQueryString('channelId') ? getQueryString('channelId') : 636;
                var pageNumber = 1;
                var pageSize = 10;
                var params = {
                  "pageNumber": pageNumber,
                  "pageSize": pageSize,
                  "indexNames": "manuscript",
                  "highlightType": 2,
                  "content": keyword,
                  "searchType": indexsearch,
                  "accessToken": "token-for-fixture",
                  "channelId": channelId
                };
                $.ajax({
                  type: "GET",
                  url: document.location.protocol + "//api.example.test/api-surface/es/docSearchEasy",
                  data: params
                });
                """
            raise AssertionError(f"unexpected fetch_text URL: {url}")

        async def fetch_json(url: str, params: dict[str, object]) -> object:
            requested_urls.append(url)
            self.assertNotIn("api-traffic", url)
            self.assertEqual(params["searchType"], 2)
            self.assertEqual(params["channelId"], 636)
            return {
                "code": 200,
                "data": {
                    "resultList": [
                        {
                            "title": "低空无人机防御训练",
                            "desc": "低空预警与反无人机防护短板",
                            "manuscriptData": {"url": "https://example.test/articles/uas"},
                        }
                    ]
                },
            }

        adapter = DynamicApiSearchAdapter(
            source_name="Fixture",
            source_tier="A",
            template="https://example.test/search?keyword={query}&page={page}",
            allowed_hosts=["example.test"],
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )

        hits = asyncio.run(adapter.search("低空", 1))

        self.assertEqual(requested_urls, ["https://api.example.test/api-surface/es/docSearchEasy"])
        self.assertEqual([hit.title for hit in hits], ["低空无人机防御训练"])

    def test_dynamic_api_adapter_skips_site_directives_for_other_hosts(self) -> None:
        async def fetch_text(url: str) -> str:
            raise AssertionError(f"adapter should skip unrelated site: query, got {url}")

        adapter = DynamicApiSearchAdapter(
            source_name="Fixture",
            source_tier="A",
            template="https://example.test/search?keyword={query}&page={page}",
            allowed_hosts=["example.test"],
            fetch_text=fetch_text,
            fetch_json=lambda url, params: {},
        )

        hits = asyncio.run(adapter.search("site:outside.test 反无人机", 1))

        self.assertEqual(hits, [])

    def test_dynamic_api_adapter_does_not_retry_source_default_queries(self) -> None:
        searched_terms: list[str] = []

        async def fetch_text(url: str) -> str:
            if url.startswith("https://example.test/search?"):
                return """
                <html><body>
                  <script src="/assets/search.js"></script>
                </body></html>
                """
            if url.endswith("/assets/search.js"):
                return """
                var keyword = getQueryString("keyword");
                var pageNumber = 1;
                var pageSize = 10;
                var params = {pageNumber: pageNumber, pageSize: pageSize, title: keyword};
                $.ajax({
                  type: "GET",
                  url: document.location.protocol + "//api.example.test/api-surface/es/docSearchEasy",
                  data: params
                });
                """
            raise AssertionError(f"unexpected fetch_text URL: {url}")

        async def fetch_json(url: str, params: dict[str, object]) -> object:
            searched_terms.append(str(params.get("title", "")))
            if params.get("title") == "反无人机":
                return {
                    "data": {
                        "resultList": [
                            {
                                "title": "反无人机方队：软杀伤硬摧毁",
                                "desc": "无人机威胁下的防护能力",
                                "manuscriptData": {"url": "https://example.test/articles/cuas"},
                            }
                        ]
                    }
                }
            return {
                "data": {
                    "resultList": [
                        {
                            "title": "普通新闻",
                            "desc": "与主题无关",
                            "manuscriptData": {"url": "https://example.test/articles/general"},
                        }
                    ]
                }
            }

        adapter = DynamicApiSearchAdapter(
            source_name="Fixture",
            source_tier="A",
            template="https://example.test/search?keyword={query}&page={page}",
            allowed_hosts=["example.test"],
            default_queries=["反无人机"],
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )

        hits = asyncio.run(
            adapter.search("低空 小型 无人机 威胁 探测 预警 防护 能力缺口 RAND Defense News 81.cn", 1)
        )

        non_empty_terms = [term for term in searched_terms if term]
        self.assertEqual(
            non_empty_terms,
            ["低空 小型 无人机 威胁 探测 预警 防护 能力缺口 RAND Defense News 81.cn"],
        )
        self.assertEqual(hits, [])

    def test_dynamic_api_adapter_tries_topic_query_before_source_defaults_for_broad_query(self) -> None:
        searched_terms: list[str] = []

        async def fetch_text(url: str) -> str:
            if url.startswith("https://example.test/search?"):
                return """
                <html><body>
                  <script src="/assets/search.js"></script>
                </body></html>
                """
            if url.endswith("/assets/search.js"):
                return """
                var keyword = getQueryString("keyword");
                var pageNumber = 1;
                var pageSize = 10;
                var params = {pageNumber: pageNumber, pageSize: pageSize, title: keyword};
                $.ajax({
                  type: "GET",
                  url: document.location.protocol + "//api.example.test/api-surface/es/docSearchEasy",
                  data: params
                });
                """
            raise AssertionError(f"unexpected fetch_text URL: {url}")

        async def fetch_json(url: str, params: dict[str, object]) -> object:
            searched_terms.append(str(params.get("title", "")))
            if "战术通信" in str(params.get("title", "")):
                return {
                    "data": {
                        "resultList": [
                            {
                                "title": "战术通信保障能力建设",
                                "desc": "远程补给链受扰条件下的通信保障能力缺口",
                                "manuscriptData": {"url": "https://example.test/articles/comms"},
                            }
                        ]
                    }
                }
            if params.get("title") == "反无人机":
                return {
                    "data": {
                        "resultList": [
                            {
                                "title": "反无人机方队",
                                "desc": "无人机防护",
                                "manuscriptData": {"url": "https://example.test/articles/uav"},
                            }
                        ]
                    }
                }
            return {"data": {"resultList": []}}

        adapter = DynamicApiSearchAdapter(
            source_name="Fixture",
            source_tier="A",
            template="https://example.test/search?keyword={query}&page={page}",
            allowed_hosts=["example.test"],
            default_queries=["反无人机"],
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )

        hits = asyncio.run(
            adapter.search("远程 补给链 受扰 战术通信 保障 能力 缺口 RAND Defense News", 1)
        )

        self.assertEqual(searched_terms[0], "远程 补给链 受扰 战术通信 保障 能力 缺口 RAND Defense News")
        self.assertNotIn("反无人机", searched_terms)
        self.assertEqual(hits[0].title, "战术通信保障能力建设")

    def test_search_sources_ranks_topic_relevance_ahead_of_generic_keyword_hints(self) -> None:
        adapter = StaticSearchAdapter(
            [
                SearchHit(
                    title="体系建设新闻",
                    url="https://example.test/generic",
                    snippet="体系建设动态",
                    source_name="Fixture",
                    source_tier="A",
                ),
                SearchHit(
                    title="反无人机方队",
                    url="https://example.test/cuas",
                    snippet="低空无人机防护能力",
                    source_name="Fixture",
                    source_tier="A",
                ),
            ]
        )
        tool = create_search_sources_tool(
            SourceRegistry([_entry(source_tier="A")]),
            KeywordGate({"equipment": ["体系建设"]}),
            adapters=[adapter],
        )

        result = asyncio.run(
            tool.execute(
                ToolCall("call-1", "search_sources", {"query": "反无人机 低空 防护", "top_k": 2}),
                _ctx(),
            )
        )

        self.assertEqual(result.details["hits"][0]["title"], "反无人机方队")
        self.assertGreater(result.details["hits"][0]["query_score"], 0)

    def test_default_search_http_helpers_use_browser_like_headers(self) -> None:
        calls: list[dict[str, object]] = []

        class TextResponse:
            url = "https://example.test/search"
            status_code = 200
            headers = {"content-type": "text/html"}
            encoding = "utf-8"
            apparent_encoding = "utf-8"
            text = "<html><body>ok</body></html>"

            def raise_for_status(self) -> None:
                return None

        class JsonResponse(TextResponse):
            def json(self) -> object:
                return {"data": {"resultList": []}}

        def fake_get(url: str, **kwargs: object) -> object:
            calls.append({"url": url, **kwargs})
            if "api" in url:
                return JsonResponse()
            return TextResponse()

        with patch("requests.get", side_effect=fake_get):
            text = _requests_text("https://example.test/search")
            payload = _requests_json("https://api.example.test/api-surface/es/docSearchEasy", {"title": "低空"})

        self.assertIn("ok", text)
        self.assertEqual(payload, {"data": {"resultList": []}})
        text_headers = calls[0]["headers"]
        json_headers = calls[1]["headers"]
        self.assertIsInstance(text_headers, dict)
        self.assertIsInstance(json_headers, dict)
        self.assertIn("Mozilla/5.0", str(text_headers.get("User-Agent")))
        self.assertIn("text/html", str(text_headers.get("Accept")))
        self.assertIn("Mozilla/5.0", str(json_headers.get("User-Agent")))
        self.assertIn("application/json", str(json_headers.get("Accept")))
        self.assertIn("en-US", str(json_headers.get("Accept-Language")))


def _entry(source_tier: str = "B", source_type: str = "defense_media") -> WhitelistEntry:
    return WhitelistEntry(
        source_name="Fixture",
        source_tier=source_tier,
        source_type=source_type,
        hosts=["example.test"],
        rate_limit_ms=0,
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "worker-1", {})


if __name__ == "__main__":
    unittest.main()
