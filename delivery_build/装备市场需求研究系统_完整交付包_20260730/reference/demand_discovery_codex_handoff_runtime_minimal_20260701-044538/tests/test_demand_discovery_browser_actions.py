from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_bridge import (  # noqa: E402
    resolve_controlled_action_url,
)
from knowledgegraph.demand_discovery.tools.browser_actions import (  # noqa: E402
    BrowserActionState,
    BrowserPageSnapshot,
    create_browser_action_tool,
    create_browser_observe_tool,
)


class DemandDiscoveryBrowserActionTests(unittest.TestCase):
    def test_browser_bridge_resolves_controlled_action_targets_without_js_or_selectors(self) -> None:
        self.assertEqual(
            resolve_controlled_action_url(
                "next_page",
                {
                    "kind": "next_page",
                    "url": "https://example.test/page2",
                    "page_url": "https://example.test/search",
                },
                "",
            ),
            "https://example.test/page2",
        )
        self.assertEqual(
            resolve_controlled_action_url(
                "submit_form",
                {
                    "kind": "form",
                    "action_url": "https://example.test/search",
                    "filled_values": {"q": "低空无人机"},
                },
                "",
            ),
            "https://example.test/search?q=%E4%BD%8E%E7%A9%BA%E6%97%A0%E4%BA%BA%E6%9C%BA",
        )
        with self.assertRaisesRegex(ValueError, "unsupported controlled browser action"):
            resolve_controlled_action_url(
                "execute_js",
                {"kind": "script", "selector": "body"},
                "alert(1)",
            )

    def test_observe_and_action_cover_search_next_page_and_download_targets(self) -> None:
        browser = FakeBrowserSession(
            {
                "https://example.test/search": """
<html>
  <head><title>搜索入口</title></head>
  <body>
    <form action="/search/results" method="get">
      <input type="search" name="q" value="" />
      <button type="submit">搜索</button>
    </form>
    <a href="/search?page=2" rel="next">下一页</a>
    <a href="/paper.pdf" class="download">下载PDF</a>
  </body>
</html>
""",
                "https://example.test/search?page=2": """
<html>
  <head><title>第二页</title></head>
  <body><main><a href="/article.html">低空无人机探测预警文章</a></main></body>
</html>
""",
                "https://example.test/search/results?q=%E4%BD%8E%E7%A9%BA%E6%97%A0%E4%BA%BA%E6%9C%BA": """
<html><head><title>搜索结果</title></head><body>低空无人机结果</body></html>
""",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            state = BrowserActionState()
            artifacts = ArtifactStore(Path(tmp))
            registry = SourceRegistry([_entry()])
            observe_tool = create_browser_observe_tool(
                registry,
                artifacts,
                state=state,
                browser_session=browser,
            )
            action_tool = create_browser_action_tool(
                registry,
                artifacts,
                state=state,
                browser_session=browser,
            )

            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "observe-1",
                        "browser_observe",
                        {"url": "https://example.test/search", "topic": "低空无人机"},
                    ),
                    _ctx(),
                )
            )
            self.assertFalse(observe.is_error)
            targets = observe.details["targets"]
            input_target = _target_id(targets, "input", "q")
            form_target = _target_id(targets, "form", "搜索")
            next_target = _target_id(targets, "next_page", "下一页")
            download_target = _target_id(targets, "download_link", "下载PDF")

            fill = asyncio.run(
                action_tool.execute(
                    ToolCall(
                        "action-fill",
                        "browser_action",
                        {
                            "observation_id": observe.details["observation_id"],
                            "target_id": input_target,
                            "action": "fill_input",
                            "value": "低空无人机",
                        },
                    ),
                    _ctx(),
                )
            )
            self.assertFalse(fill.is_error)
            self.assertEqual(fill.details["action"], "fill_input")

            submit = asyncio.run(
                action_tool.execute(
                    ToolCall(
                        "action-submit",
                        "browser_action",
                        {
                            "observation_id": observe.details["observation_id"],
                            "target_id": form_target,
                            "action": "submit_form",
                        },
                    ),
                    _ctx(),
                )
            )
            self.assertFalse(submit.is_error)
            self.assertTrue(submit.details["url_changed"])
            self.assertEqual(submit.details["title_after"], "搜索结果")

            next_page = asyncio.run(
                action_tool.execute(
                    ToolCall(
                        "action-next",
                        "browser_action",
                        {
                            "observation_id": observe.details["observation_id"],
                            "target_id": next_target,
                            "action": "next_page",
                        },
                    ),
                    _ctx(),
                )
            )
            self.assertFalse(next_page.is_error)
            self.assertEqual(next_page.details["final_url"], "https://example.test/search?page=2")
            self.assertIn("低空无人机探测预警文章", next_page.details["new_text"])

            download = asyncio.run(
                action_tool.execute(
                    ToolCall(
                        "action-download",
                        "browser_action",
                        {
                            "observation_id": observe.details["observation_id"],
                            "target_id": download_target,
                            "action": "download_link",
                        },
                    ),
                    _ctx(),
                )
            )
            self.assertFalse(download.is_error)
            self.assertEqual(download.details["download_url"], "https://example.test/paper.pdf")

    def test_action_rejects_target_not_returned_by_observe(self) -> None:
        browser = FakeBrowserSession(
            {
                "https://example.test/search": "<html><title>入口</title><body></body></html>",
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            state = BrowserActionState()
            artifacts = ArtifactStore(Path(tmp))
            registry = SourceRegistry([_entry()])
            observe_tool = create_browser_observe_tool(
                registry,
                artifacts,
                state=state,
                browser_session=browser,
            )
            action_tool = create_browser_action_tool(
                registry,
                artifacts,
                state=state,
                browser_session=browser,
            )
            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "observe-1",
                        "browser_observe",
                        {"url": "https://example.test/search", "topic": "低空无人机"},
                    ),
                    _ctx(),
                )
            )

            result = asyncio.run(
                action_tool.execute(
                    ToolCall(
                        "action-bad",
                        "browser_action",
                        {
                            "observation_id": observe.details["observation_id"],
                            "target_id": "target-from-model-selector",
                            "action": "click_link",
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("unknown browser target_id", result.content)


class FakeBrowserSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = dict(pages)
        self.filled: dict[str, str] = {}

    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            url=url,
            html=self.pages[url],
        )

    async def action(
        self,
        *,
        action: str,
        target: dict[str, object],
        value: str,
        timeout_ms: int,
    ) -> BrowserPageSnapshot:
        if action == "fill_input":
            self.filled[str(target["name"])] = value
            return BrowserPageSnapshot(url=str(target["page_url"]), html=self.pages[str(target["page_url"])])
        if action == "submit_form":
            action_url = str(target["action_url"])
            query = "&".join(f"{key}={_quote(text)}" for key, text in self.filled.items())
            url = f"{action_url}?{query}" if query else action_url
            return BrowserPageSnapshot(url=url, html=self.pages[url])
        if action in {"click_link", "next_page"}:
            url = str(target["url"])
            return BrowserPageSnapshot(url=url, html=self.pages[url])
        if action == "download_link":
            return BrowserPageSnapshot(
                url=str(target["page_url"]),
                html=self.pages[str(target["page_url"])],
                download_url=str(target["url"]),
            )
        raise AssertionError(action)


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value)


def _target_id(targets: list[dict[str, object]], kind: str, text: str) -> str:
    for target in targets:
        if target.get("kind") != kind:
            continue
        haystack = " ".join(str(value) for value in target.values())
        if text in haystack:
            return str(target["target_id"])
    raise AssertionError(f"target not found: {kind} {text}")


def _entry() -> WhitelistEntry:
    return WhitelistEntry(
        source_name="Fixture Source",
        source_tier="A",
        source_type="official",
        hosts=["example.test"],
        fetch_transport="browser_session",
        rate_limit_ms=0,
    )


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
