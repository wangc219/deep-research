from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_actions import (  # noqa: E402
    BrowserActionState,
    BrowserPageSnapshot,
    create_browser_execute_tool,
    create_browser_observe_tool,
)


class BrowserExecuteTests(unittest.TestCase):
    def test_browser_execute_target_action_returns_delta_and_next_observation(self) -> None:
        browser = FakeBrowserSession(
            {
                "https://example.test/search": """
<html><head><title>入口</title></head><body>
  <form action="/search/results" method="get">
    <input type="search" name="q" />
    <button type="submit">搜索</button>
  </form>
</body></html>
""",
                "https://example.test/search/results?q=%E8%BF%9C%E6%B5%B7": """
<html><head><title>搜索结果</title></head><body>
  <main><a href="/article.html">远海保障文章</a></main>
</body></html>
""",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = BrowserActionState()
            artifacts = ArtifactStore(Path(tmp))
            observe_tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            execute_tool = create_browser_execute_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "observe",
                        "browser_observe",
                        {"url": "https://example.test/search", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            input_id = _target_id(observe.details["targets"], "input", "q")
            form_id = _target_id(observe.details["targets"], "form", "搜索")
            fill = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "fill",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "填写中文检索词",
                            "mode": "target_action",
                            "target_action": {
                                "action": "fill_input",
                                "target_id": input_id,
                                "value": "远海",
                            },
                        },
                    ),
                    _ctx(),
                )
            )
            submit = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "submit",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "提交检索并观察结果页",
                            "mode": "target_action",
                            "target_action": {
                                "action": "submit_form",
                                "target_id": form_id,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(fill.is_error)
        self.assertEqual(fill.details["status"], "success")
        self.assertEqual(fill.details["execution_mode"], "target_action")
        self.assertFalse(submit.is_error)
        self.assertTrue(submit.details["url_changed"])
        self.assertEqual(submit.details["title_after"], "搜索结果")
        self.assertIn("远海保障文章", submit.details["delta_summary"])
        self.assertIn("next_observation_ref", submit.details)
        self.assertEqual(submit.details["suggested_next_actions"], ["capture_current_document"])

    def test_browser_execute_capture_current_document_creates_artifact_not_evidence(self) -> None:
        browser = FakeBrowserSession(
            {
                "https://example.test/article.html": """
<html><head><title>文章</title></head><body><article>远海保障正文</article></body></html>
""",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = BrowserActionState()
            artifacts = ArtifactStore(Path(tmp))
            observe_tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            execute_tool = create_browser_execute_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "observe",
                        "browser_observe",
                        {"url": "https://example.test/article.html", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            current_document_id = _target_id(
                observe.details["targets"],
                "current_document",
                "当前页面",
            )
            capture = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "capture",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "保存当前文章正文",
                            "mode": "target_action",
                            "target_action": {
                                "action": "capture_current_document",
                                "target_id": current_document_id,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(capture.is_error)
        self.assertTrue(capture.details["document_candidate_refs"])
        self.assertEqual(capture.domain_proposals, [])

    def test_browser_execute_rejects_out_of_scope_target_before_session_action(self) -> None:
        browser = RecordingBrowserSession(
            {
                "https://example.test/search": """
<html><head><title>入口</title></head><body>
  <a href="https://outside.example.org/article.html">外部文章</a>
</body></html>
""",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = BrowserActionState()
            artifacts = ArtifactStore(Path(tmp))
            observe_tool = create_browser_observe_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            execute_tool = create_browser_execute_tool(
                _registry(),
                artifacts,
                state=state,
                browser_session=browser,
            )
            observe = asyncio.run(
                observe_tool.execute(
                    ToolCall(
                        "observe",
                        "browser_observe",
                        {"url": "https://example.test/search", "topic": "远海"},
                    ),
                    _ctx(),
                )
            )
            outside_target_id = _target_id(
                observe.details["targets"],
                "link",
                "外部文章",
            )
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "outside",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "点击外部文章",
                            "mode": "target_action",
                            "target_action": {
                                "action": "click_link",
                                "target_id": outside_target_id,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertEqual(result.details["blocked_by"], "browser_url_scope")
        self.assertEqual(browser.actions, [])

    def test_build_all_tools_exposes_browser_execute_not_browser_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_all_tools(
                DomainStore(),
                _registry(),
                ArtifactStore(Path(tmp)),
                enable_browser_tools=True,
                browser_session=FakeBrowserSession({}),
            )
        names = [tool.name for tool in tools]
        self.assertIn("browser_observe", names)
        self.assertIn("browser_execute", names)
        self.assertNotIn("browser_action", names)


class FakeBrowserSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = dict(pages)
        self.filled: dict[str, str] = {}

    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(url=url, html=self.pages[url])

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
            from urllib.parse import quote

            action_url = str(target["action_url"])
            query = "&".join(f"{key}={quote(text)}" for key, text in self.filled.items())
            url = f"{action_url}?{query}" if query else action_url
            return BrowserPageSnapshot(url=url, html=self.pages[url])
        if action == "capture_current_document":
            return BrowserPageSnapshot(url=str(target["page_url"]), html=self.pages[str(target["page_url"])])
        raise AssertionError(action)


class RecordingBrowserSession(FakeBrowserSession):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(pages)
        self.actions: list[tuple[str, str]] = []

    async def action(
        self,
        *,
        action: str,
        target: dict[str, object],
        value: str,
        timeout_ms: int,
    ) -> BrowserPageSnapshot:
        self.actions.append((action, str(target.get("url", ""))))
        if action in {"click_link", "next_page"}:
            url = str(target["url"])
            return BrowserPageSnapshot(url=url, html=self.pages.get(url, ""))
        return await super().action(
            action=action,
            target=target,
            value=value,
            timeout_ms=timeout_ms,
        )


def _target_id(targets: list[dict[str, object]], kind: str, text: str) -> str:
    for target in targets:
        if target.get("kind") != kind:
            continue
        if text in " ".join(str(value) for value in target.values()):
            return str(target["target_id"])
    raise AssertionError(f"missing target {kind} {text}")


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
