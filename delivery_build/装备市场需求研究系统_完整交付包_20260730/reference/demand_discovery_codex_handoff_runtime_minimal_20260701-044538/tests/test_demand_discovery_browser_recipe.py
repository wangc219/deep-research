from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.browser_research import (  # noqa: E402
    BrowserApiCandidate,
    BrowserRecipeDraft,
)
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_actions import (  # noqa: E402
    BrowserActionState,
    BrowserPageSnapshot,
    create_browser_execute_tool,
    create_browser_observe_tool,
)


NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


class BrowserRecipeTests(unittest.TestCase):
    def test_browser_recipe_draft_rejects_unknown_status_and_roundtrips_jsonl(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown BrowserRecipeDraft review_status"):
            _recipe(review_status="stable")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domain.jsonl"
            store = DomainStore()
            recipe = _recipe()
            store.upsert_browser_recipe_draft(recipe)
            store.export_jsonl(path)
            loaded = DomainStore.load_jsonl(path)
        self.assertEqual(
            loaded.browser_recipe_drafts[recipe.recipe_id].to_dict(),
            recipe.to_dict(),
        )

    def test_browser_api_candidate_is_read_only_get_or_head(self) -> None:
        self.assertEqual(_api_candidate(method="HEAD").method, "HEAD")
        with self.assertRaisesRegex(ValueError, "unsupported BrowserApiCandidate method"):
            _api_candidate(method="POST")

    def test_successful_javascript_api_candidate_creates_recipe_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DomainStore()
            artifacts = ArtifactStore(Path(tmp))
            state = BrowserActionState()
            browser = RecipeBrowser()
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
                domain_store=store,
                run_id="run-1",
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
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "execute",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "发现同源公开搜索接口",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回文章候选和公开搜索 API pattern",
                                "why_standard_actions_are_insufficient": "browser_observe 只看到前端容器，target_action 无法得到结果列表",
                                "result_sink": "只生成候选 lead、诊断和 recipe draft，不直接生成 EvidenceCard",
                                "fallback": "如果接口为空或失败，回到页面搜索框并换中文关键词",
                                "allow_network_probe": True,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(len(store.browser_recipe_drafts), 1)
        recipe = next(iter(store.browser_recipe_drafts.values()))
        self.assertEqual(recipe.review_status, "draft")
        self.assertEqual(recipe.source_name, "Example")
        self.assertEqual(recipe.output_type, "api_candidate")
        self.assertIsNotNone(recipe.api_candidate)
        self.assertEqual(recipe.api_candidate.path, "/api/search")
        self.assertEqual(recipe.input_names, ["keyword", "page"])
        self.assertIn("same-origin", recipe.safety_notes)


class RecipeBrowser:
    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            url=url,
            html="<html><title>搜索</title><body><div id='app'></div></body></html>",
        )

    async def action(
        self,
        *,
        action: str,
        target: dict[str, object],
        value: str,
        timeout_ms: int,
    ) -> BrowserPageSnapshot:
        raise AssertionError(action)

    async def execute_javascript(
        self,
        *,
        script: str,
        timeout_ms: int,
        max_return_chars: int,
        allow_network_probe: bool,
        safety_policy: dict[str, object],
    ) -> dict[str, object]:
        return {
            "status": "success",
            "result": [
                {"title": "远海保障文章", "url": "https://example.test/article.html"}
            ],
            "url_after": "https://example.test/search",
            "title_after": "搜索",
            "html_after": "<html><title>搜索</title><body><a href='/article.html'>远海保障文章</a></body></html>",
            "network_delta": [
                {
                    "method": "GET",
                    "host": "example.test",
                    "path": "/api/search",
                    "query_keys": ["keyword", "page"],
                    "status": 200,
                    "content_type": "application/json",
                    "purpose_guess": "search_results",
                }
            ],
        }


def _api_candidate(method: str = "GET") -> BrowserApiCandidate:
    return BrowserApiCandidate(
        method=method,
        url="https://example.test/api/search",
        host="example.test",
        path="/api/search",
        query_keys=["keyword", "page"],
        body_keys=[],
        content_type="application/json",
        purpose_guess="search_results",
        same_origin=True,
    )


def _recipe(review_status: str = "draft") -> BrowserRecipeDraft:
    return BrowserRecipeDraft(
        recipe_id="browser-recipe-1",
        run_id="run-1",
        source_name="Example",
        domain="example.test",
        intent="站内搜索并提取结果文章链接",
        trigger_condition="HTTP search route returns empty",
        script_hash="sha256:abc",
        script_ref="artifact:script",
        return_artifact_ref="artifact:return",
        input_names=["keyword", "page"],
        output_type="api_candidate",
        api_candidate=_api_candidate(),
        observed_success_signal="result list contains title and URL",
        safety_notes=["same-origin", "read-only"],
        review_status=review_status,
        created_at=NOW,
        updated_at=NOW,
    )


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
