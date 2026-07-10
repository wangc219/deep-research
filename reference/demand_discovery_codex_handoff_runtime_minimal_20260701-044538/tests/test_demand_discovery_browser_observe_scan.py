from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SourceRegistry,
    WhitelistEntry,
)
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_actions import (  # noqa: E402
    BrowserActionState,
    BrowserPageSnapshot,
    BrowserUrlScope,
    create_browser_observe_tool,
)
from knowledgegraph.demand_discovery.tools.documents import create_read_document_tool  # noqa: E402


class BrowserObserveScanTests(unittest.TestCase):
    def test_observe_returns_compact_scan_targets_and_api_candidates(self) -> None:
        browser = _StaticBrowser(
            """
<html>
  <head>
    <title>研究检索页</title>
    <script>
      async function search(q) {
        return fetch('/api/search?keyword=' + encodeURIComponent(q) + '&page=1')
          .then(r => r.json());
      }
    </script>
  </head>
  <body>
    <main>
      <form action="/search" method="get">
        <input type="search" name="keyword" aria-label="输入关键词" />
        <button type="submit">检索</button>
      </form>
      <section class="result-list">
        <a href="/article/1.html">远海保障能力分析</a>
        <a href="/article/2.html">无人平台维护报告</a>
      </section>
      <a href="/reports/report.pdf">下载报告 PDF</a>
      <a href="/search?page=2" rel="next">下一页</a>
    </main>
  </body>
</html>
"""
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=BrowserActionState(),
                browser_session=browser,
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "browser_observe",
                        {
                            "url": "https://example.test/search",
                            "topic": "远海无人平台维护保障能力缺口",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        details = result.details
        self.assertIn("observation_ref", details)
        self.assertEqual(details["url"], "https://example.test/search")
        self.assertEqual(details["title"], "研究检索页")
        self.assertIn("远海保障能力分析", details["visible_text_digest"])
        self.assertTrue(details["article_candidates"])
        self.assertTrue(details["listing_candidates"])
        self.assertTrue(details["forms"])
        self.assertTrue(details["download_targets"])
        self.assertTrue(details["pagination_targets"])
        self.assertTrue(details["top_targets"])
        self.assertIn("target_action", details["suggested_interaction_modes"])
        self.assertIn("javascript", details["suggested_interaction_modes"])
        api = details["network_api_candidates"][0]
        self.assertEqual(api["method"], "GET")
        self.assertEqual(api["host"], "example.test")
        self.assertEqual(api["path"], "/api/search")
        self.assertEqual(api["query_keys"], ["keyword", "page"])
        self.assertEqual(api["purpose_guess"], "search_results")
        self.assertNotIn("cookie", str(api).lower())
        self.assertNotIn("authorization", str(api).lower())

    def test_observe_allows_approved_open_source_scope_and_rejects_other_urls(self) -> None:
        browser = _StaticBrowser(
            "<html><head><title>开放来源文章</title></head><body><article>公开正文</article></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=BrowserActionState(),
                browser_session=browser,
                allowed_scopes=[
                    BrowserUrlScope(
                        scope_type="open_search_plan",
                        source_name="Open web usable fixture",
                        plan_id="osp-1",
                        lead_id="osl-1",
                        url_prefixes=["https://open.example.org/article"],
                        hosts=["open.example.org"],
                    )
                ],
            )
            allowed = asyncio.run(
                tool.execute(
                    ToolCall(
                        "allowed",
                        "browser_observe",
                        {"url": "https://open.example.org/article", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            same_host_other_path = asyncio.run(
                tool.execute(
                    ToolCall(
                        "same-host-other-path",
                        "browser_observe",
                        {"url": "https://open.example.org/other", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            blocked = asyncio.run(
                tool.execute(
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
        self.assertTrue(same_host_other_path.is_error)
        self.assertIn("outside browser URL scope", same_host_other_path.content)
        self.assertTrue(blocked.is_error)
        self.assertIn("outside browser URL scope", blocked.content)

    def test_observe_sanitizes_sensitive_form_fields_and_disables_sensitive_actions(self) -> None:
        browser = _StaticBrowser(
            """
<html>
  <head><title>登录页</title></head>
  <body>
    <form action="/login" method="post">
      <input type="hidden" name="csrf_token" value="secret-token" />
      <input type="password" name="password" value="secret-pwd" />
      <input type="text" name="username" />
      <input type="submit" value="登录" />
    </form>
  </body>
</html>
"""
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=BrowserActionState(),
                browser_session=browser,
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "sensitive",
                        "browser_observe",
                        {"url": "https://example.test/login", "topic": "公开资料"},
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        serialized = str(result.details)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("secret-pwd", serialized)
        self.assertNotIn("'input_type': 'hidden'", serialized)
        self.assertNotIn("'input_type': 'password'", serialized)
        self.assertIn("sensitive_form_fields", result.details["page_risk_flags"])
        self.assertNotIn("javascript", result.details["suggested_interaction_modes"])
        form_targets = [
            target for target in result.details["targets"] if target.get("kind") == "form"
        ]
        self.assertEqual(form_targets[0]["allowed_actions"], [])
        current_document_targets = [
            target
            for target in result.details["targets"]
            if target.get("kind") == "current_document"
        ]
        self.assertEqual(current_document_targets[0]["allowed_actions"], [])

    def test_sensitive_observe_artifact_cannot_leak_secrets_through_read_document(self) -> None:
        browser = _StaticBrowser(
            """
<html>
  <head><title>登录页</title></head>
  <body>
    <form action="/login" method="post">
      <input type="hidden" name="csrf_token" value="secret-token" />
      <input type="password" name="password" value="secret-pwd" />
      <input type="text" name="username" value="public-user" />
      <input type="submit" value="登录" />
    </form>
  </body>
</html>
"""
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            observe_tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=BrowserActionState(),
                browser_session=browser,
            )
            read_tool = create_read_document_tool(artifacts)
            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "sensitive",
                        "browser_observe",
                        {"url": "https://example.test/login", "topic": "公开资料"},
                    ),
                    _ctx(),
                )
            )
            artifact_ref = observe.details["artifact_ref"]
            stored_text = artifacts.get_text(artifact_ref)
            read = asyncio.run(
                read_tool.execute(
                    ToolCall(
                        "read",
                        "read_document",
                        {"artifact_ref": artifact_ref, "limit": 20},
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(observe.is_error)
        self.assertFalse(read.is_error)
        self.assertNotIn("secret-token", stored_text)
        self.assertNotIn("secret-pwd", stored_text)
        self.assertNotIn("secret-token", read.content)
        self.assertNotIn("secret-pwd", read.content)
        self.assertIn("public-user", read.content)


class _StaticBrowser:
    def __init__(self, html: str) -> None:
        self.html = html

    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(url=url, html=self.html)


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
