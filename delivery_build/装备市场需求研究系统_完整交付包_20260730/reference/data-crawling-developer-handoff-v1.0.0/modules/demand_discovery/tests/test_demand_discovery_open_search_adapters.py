from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.tools.open_search_adapters import (  # noqa: E402
    default_open_search_adapters_path,
    load_open_search_adapters,
)


class DemandDiscoveryOpenSearchAdapterTests(unittest.TestCase):
    def test_default_config_uses_tavily_search_when_key_is_available(self) -> None:
        adapters = load_open_search_adapters(
            default_open_search_adapters_path(),
            env={"TAVILY_API_KEY": "tvly-test"},
        )

        self.assertEqual(len(adapters), 1)
        adapter = adapters[0]
        self.assertEqual(getattr(adapter, "name"), "tavily_search")
        self.assertEqual(getattr(adapter, "search_provider"), "tavily")
        self.assertEqual(getattr(adapter, "max_results"), 5)

    def test_default_config_skips_tavily_when_key_is_missing(self) -> None:
        adapters = load_open_search_adapters(
            default_open_search_adapters_path(),
            env={},
        )

        self.assertEqual(adapters, [])

    def test_loader_reads_powershell_style_env_file_for_tavily_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / ".env").write_text(
                '$env:TAVILY_API_KEY="tvly-from-env-file"\n',
                encoding="utf-8",
            )
            config_dir = root / "configs" / "demand_discovery"
            config_dir.mkdir(parents=True)
            config = config_dir / "open_search_adapters.yaml"
            config.write_text(
                """
version: 1
adapters:
  - name: tavily_search
    type: tavily_search
    enabled: true
    env_key: TAVILY_API_KEY
""",
                encoding="utf-8",
            )

            adapters = load_open_search_adapters(config)

        self.assertEqual(len(adapters), 1)
        self.assertEqual(getattr(adapters[0], "api_key"), "tvly-from-env-file")

    def test_tavily_adapter_maps_json_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "open_search_adapters.yaml"
            config.write_text(
                """
version: 1
adapters:
  - name: tavily_search
    type: tavily_search
    enabled: true
    search_provider: tavily
    env_key: TAVILY_API_KEY
    endpoint_url: https://api.tavily.com/search
    max_results: 2
    search_depth: basic
""",
                encoding="utf-8",
            )
            requests: list[dict[str, object]] = []

            async def json_transport(
                url: str,
                headers: dict[str, str],
                payload: dict[str, object],
            ) -> dict[str, object]:
                requests.append({"url": url, "headers": headers, "payload": payload})
                return {
                    "query": "远海保障 缺口",
                    "results": [
                        {
                            "title": "远海保障能力建设报告",
                            "url": "https://open.example.test/report",
                            "content": "报告讨论远海保障能力缺口和补强方向。",
                            "score": 0.91,
                        },
                        {
                            "title": "重复结果",
                            "url": "https://open.example.test/report",
                            "content": "同一 URL 应去重。",
                            "score": 0.88,
                        },
                    ],
                }

            adapters = load_open_search_adapters(
                config,
                env={"TAVILY_API_KEY": "tvly-test"},
                json_transport=json_transport,
            )
            hits = asyncio.run(adapters[0].search("远海保障 缺口", 1))

        self.assertEqual(len(adapters), 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["url"], "https://api.tavily.com/search")
        headers = requests[0]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer tvly-test")
        payload = requests[0]["payload"]
        self.assertEqual(payload["query"], "远海保障 缺口")
        self.assertEqual(payload["max_results"], 2)
        self.assertEqual(payload["search_depth"], "basic")
        self.assertEqual(payload["include_answer"], False)
        self.assertEqual(payload["include_raw_content"], False)
        self.assertEqual(
            [hit.url for hit in hits],
            ["https://open.example.test/report"],
        )
        self.assertEqual(hits[0].title, "远海保障能力建设报告")
        self.assertEqual(hits[0].snippet, "报告讨论远海保障能力缺口和补强方向。")
        self.assertEqual(hits[0].source_domain, "open.example.test")
        self.assertEqual(hits[0].search_provider, "tavily")
        self.assertEqual(hits[0].query_used, "远海保障 缺口")

    def test_google_redirect_results_are_normalized_and_internal_links_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "open_search_adapters.yaml"
            config.write_text(
                """
version: 1
adapters:
  - name: google_search
    type: html_url_template
    enabled: true
    search_provider: google
    template: "https://www.google.com/search?q={query}&start={offset}"
    result_selector: "a"
""",
                encoding="utf-8",
            )

            async def fetch_text(url: str) -> str:
                return (
                    "<html><body>"
                    "<a href='/url?q=https%3A%2F%2Fopen.example.test%2Freport&sa=U'>"
                    "高寒救援保障报告</a>"
                    "<a href='/search?q=related'>Google internal navigation</a>"
                    "</body></html>"
                )

            adapters = load_open_search_adapters(config, fetch_text=fetch_text)
            hits = asyncio.run(adapters[0].search("高寒救援 保障缺口", 1))

        self.assertEqual([hit.url for hit in hits], ["https://open.example.test/report"])
        self.assertEqual(hits[0].source_domain, "open.example.test")
        self.assertEqual(hits[0].search_provider, "google")

    def test_loader_builds_html_url_template_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "open_search_adapters.yaml"
            config.write_text(
                """
version: 1
adapters:
  - name: fixture_html
    type: html_url_template
    enabled: true
    search_provider: fixture-search
    template: "https://search.example.test/?q={query}&page={page}"
    result_selector: "a.result"
""",
                encoding="utf-8",
            )
            fetched_urls: list[str] = []

            async def fetch_text(url: str) -> str:
                fetched_urls.append(url)
                return (
                    "<html><body>"
                    "<a class='result' href='https://open.example.test/report'>"
                    "远海保障缺口报告</a>"
                    "<p>公开机构正文线索</p>"
                    "</body></html>"
                )

            adapters = load_open_search_adapters(config, fetch_text=fetch_text)
            hits = asyncio.run(adapters[0].search("远海保障 缺口", 2))

        self.assertEqual(len(adapters), 1)
        self.assertEqual(len(hits), 1)
        self.assertIn("%E8%BF%9C%E6%B5%B7", fetched_urls[0])
        self.assertEqual(hits[0].url, "https://open.example.test/report")
        self.assertEqual(hits[0].source_domain, "open.example.test")
        self.assertEqual(hits[0].search_provider, "fixture-search")

    def test_loader_ignores_disabled_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "open_search_adapters.yaml"
            config.write_text(
                """
version: 1
adapters:
  - name: disabled
    type: html_url_template
    enabled: false
    template: "https://search.example.test/?q={query}"
""",
                encoding="utf-8",
            )

            adapters = load_open_search_adapters(config)

        self.assertEqual(adapters, [])


if __name__ == "__main__":
    unittest.main()
