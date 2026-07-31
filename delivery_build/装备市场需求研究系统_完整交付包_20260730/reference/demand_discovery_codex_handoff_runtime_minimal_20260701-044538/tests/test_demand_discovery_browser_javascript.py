from __future__ import annotations

import asyncio
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry, WhitelistEntry  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_bridge import _guarded_javascript  # noqa: E402
from knowledgegraph.demand_discovery.tools.browser_actions import (  # noqa: E402
    BrowserActionState,
    BrowserPageSnapshot,
    create_browser_execute_tool,
    create_browser_observe_tool,
)


class BrowserJavaScriptTests(unittest.TestCase):
    def test_javascript_requires_observation_intent_and_expected_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = create_browser_execute_tool(
                _registry(),
                ArtifactStore(Path(tmp)),
                state=BrowserActionState(),
                browser_session=FakeJsBrowser(),
            )
            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": "missing",
                            "intent": "验证动态搜索结果",
                            "mode": "javascript",
                            "javascript": {"script": "return []"},
                        },
                    ),
                    _ctx(),
                )
            )
        self.assertTrue(result.is_error)
        self.assertIn("expected_result is required", result.content)

    def test_javascript_requires_auditable_decision_context_without_use_case_enum(self) -> None:
        browser = FakeJsBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, browser)
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "调用同源公开搜索接口并提取文章候选",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回包含 title 和 url 的公开文章候选",
                                "allow_network_probe": True,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("why_standard_actions_are_insufficient is required", result.content)
        self.assertEqual(browser.javascript_calls, 0)

    def test_javascript_preflight_blocks_credentials_storage_and_mutating_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, FakeJsBrowser())
            observe = _observe(observe_tool)
            blocked = []
            for script in [
                "return document.cookie",
                "return document['cookie']",
                "return window['localStorage'].getItem('token')",
                "return localStorage.getItem('token')",
                "return sessionStorage.getItem('token')",
                "return indexedDB.databases()",
                "return new XMLHttpRequest()",
                "return fetch('/api/update', {method: 'POST', body: JSON.stringify({x: 1})})",
                "return fetch('/api/delete', {method: 'DELETE'})",
            ]:
                result = asyncio.run(
                    execute_tool.execute(
                        ToolCall(
                            "js",
                            "browser_execute",
                            {
                                "observation_ref": observe.details["observation_ref"],
                                "intent": "安全策略测试",
                                "mode": "javascript",
                                "javascript": {
                                "script": script,
                                "expected_result": "返回公开页面候选",
                                **_js_audit_context(),
                                "allow_network_probe": True,
                            },
                            },
                        ),
                        _ctx(),
                    )
                )
                blocked.append(result)
        self.assertTrue(all(item.is_error for item in blocked))
        self.assertTrue(
            all(
                "blocked by browser javascript safety policy" in item.content
                for item in blocked
            )
        )

    def test_javascript_preflight_does_not_block_general_js_constructs(self) -> None:
        browser = FakeJsBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, browser)
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "验证构造器逃逸不能触发真实浏览器执行",
                            "mode": "javascript",
                            "javascript": {
                                "script": (
                                    "return ({}).constructor.constructor("
                                    "\"return 9\")()"
                                ),
                                "expected_result": "返回公开页面诊断结果",
                                **_js_audit_context(),
                                "allow_network_probe": False,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(browser.javascript_calls, 1)

    def test_real_bridge_uses_minimal_guard_not_constructor_or_dom_sandbox(self) -> None:
        guarded = _guarded_javascript(
            script="return document.querySelector('a')?.href || ''",
            max_return_chars=200,
            allow_network_probe=False,
            safety_policy={
                "allowed_origin": "https://example.test",
                "allowed_methods": ["GET", "HEAD"],
                "force_credentials": "omit",
                "max_requests": 0,
            },
        )

        self.assertNotIn("guardPrototype", guarded)
        self.assertNotIn("__installConstructorGuards", guarded)
        self.assertNotIn("__readonlyNode", guarded)
        self.assertNotIn("read-only DOM", guarded)
        self.assertNotIn("__blockedScriptPatterns", guarded)
        self.assertIn("__safeFetch", guarded)
        self.assertIn("credentials: 'omit'", guarded)

    def test_real_bridge_allows_general_js_runtime(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(
            script="return ({}).constructor.constructor(\"return 9\")()",
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"], 9)
        self.assertEqual(payload["url_after"], "https://example.test/search")
        self.assertEqual(payload["global_url"], "https://example.test/search")

    def test_real_bridge_guard_allows_simple_return_runtime(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(script="return 1")

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"], 1)
        self.assertEqual(payload["url_after"], "https://example.test/search")
        self.assertEqual(payload["global_url"], "https://example.test/search")

    def test_real_bridge_guard_allows_same_origin_fetch_runtime(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(
            script=(
                "return await fetch('/api/search?keyword=远海&page=1')"
                ".then(r => r.json())"
            ),
            allow_network_probe=True,
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(
            payload["result"],
            [{"title": "公开结果", "url": "https://example.test/article.html"}],
        )
        self.assertEqual(payload["fetch_args"]["credentials"], "omit")
        self.assertEqual(payload["fetch_args"]["method"], "GET")
        self.assertEqual(
            payload["fetch_args"]["url"],
            "https://example.test/api/search?keyword=%E8%BF%9C%E6%B5%B7&page=1",
        )
        self.assertEqual(payload["network_delta"][0]["path"], "/api/search")

    def test_real_bridge_does_not_treat_dom_mutation_as_evidence_boundary(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(
            script=(
                "document.documentElement.outerHTML = '<html><body>tampered</body></html>'; "
                "return document.documentElement.outerHTML"
            ),
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"], "<html><body>tampered</body></html>")
        self.assertEqual(payload["url_after"], "https://example.test/search")
        self.assertEqual(payload["global_url"], "https://example.test/search")
        self.assertEqual(payload["html_after"], "<html><body>tampered</body></html>")
        self.assertEqual(payload["global_html"], "<html><body>tampered</body></html>")

    def test_real_bridge_guard_allows_read_only_dom_queries_runtime(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(
            script=(
                "const link = document.querySelector('a'); "
                "return {"
                "title: document.title, "
                "bodyText: document.body.innerText, "
                "href: link.href, "
                "outerHTML: document.documentElement.outerHTML"
                "}"
            ),
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["title"], "动态页")
        self.assertEqual(payload["result"]["bodyText"], "正文")
        self.assertEqual(payload["result"]["href"], "https://example.test/article.html")
        self.assertEqual(
            payload["result"]["outerHTML"],
            "<html><body><a href='/article.html'>正文</a></body></html>",
        )
        self.assertEqual(payload["global_html"], "<html><body><a href='/article.html'>正文</a></body></html>")

    def test_same_origin_get_probe_forces_credentials_omit_in_runtime_policy(self) -> None:
        browser = FakeJsBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, browser)
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "调用同源公开搜索接口并确认不携带凭证",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回公开文章候选",
                                **_js_audit_context(),
                                "allow_network_probe": True,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(browser.last_safety_policy["force_credentials"], "omit")
        self.assertEqual(browser.last_safety_policy["allowed_methods"], ["GET", "HEAD"])

    def test_real_bridge_keeps_post_execution_url_visible_for_scope_gate(self) -> None:
        guarded = _guarded_javascript(
            script=(
                "location.href = 'https://outside.example.org'; "
                "window.location = 'https://outside.example.org'; "
                "document.location = 'https://outside.example.org'; "
                "return 1"
            ),
            max_return_chars=200,
            allow_network_probe=False,
            safety_policy={
                "allowed_origin": "https://example.test",
                "allowed_methods": ["GET", "HEAD"],
                "force_credentials": "omit",
                "max_requests": 0,
            },
        )

        self.assertIn("with (__sandbox)", guarded)
        self.assertIn("url_after", guarded)
        self.assertIn("__actualLocation.href", guarded)
        self.assertIn(".call(__sandboxWindow)", guarded)
        self.assertNotIn("new Function('return (async () =>", guarded)

    def test_same_origin_absolute_get_url_is_not_blocked_by_preflight(self) -> None:
        browser = FakeJsBrowser()
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, browser)
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "调用同源绝对 URL 公开搜索接口",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('https://example.test/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回公开文章候选",
                                **_js_audit_context(),
                                "allow_network_probe": True,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(browser.last_safety_policy["force_credentials"], "omit")
        self.assertEqual(result.details["network_delta"][0]["host"], "example.test")

    def test_javascript_rejects_out_of_scope_url_after_even_without_network_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(
                tmp,
                FakeJsBrowser(
                    url_after="https://outside.example.org/changed",
                    network_delta=[],
                ),
            )
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "执行脚本后确认页面仍在允许范围",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return [{title: '外部跳转'}]",
                                "expected_result": "返回页面变化结果",
                                **_js_audit_context(),
                                "allow_network_probe": False,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertIn("outside browser URL scope", result.content)
        self.assertEqual(result.details["blocked_by"], "browser_url_scope")

    def test_javascript_runtime_error_returns_error_class_and_page_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, FakeJsBrowser(error="ReferenceError"))
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "读取动态结果",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return missingVariable",
                                "expected_result": "返回文章链接数组",
                                **_js_audit_context(),
                                "allow_network_probe": False,
                            },
                        },
                    ),
                    _ctx(),
                )
            )
        self.assertTrue(result.is_error)
        self.assertEqual(result.details["status"], "failed")
        self.assertEqual(result.details["error"]["name"], "ReferenceError")
        self.assertEqual(result.details["delta_summary"], "页面无明显文本变化")

    def test_javascript_success_returns_preview_artifact_and_network_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, FakeJsBrowser())
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "调用同源公开搜索接口并提取文章候选",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回包含 title 和 url 的公开文章候选",
                                "why_standard_actions_are_insufficient": "browser_observe 只看到前端容器，target_action 无法得到结果列表",
                                "result_sink": "只生成候选 lead、诊断和 recipe draft，不直接生成 EvidenceCard",
                                "fallback": "如果接口为空或失败，回到页面搜索框并换中文关键词",
                                "allow_network_probe": True,
                            },
                            "max_return_chars": 80,
                        },
                    ),
                    _ctx(),
                )
            )
        self.assertFalse(result.is_error)
        self.assertEqual(result.details["status"], "success")
        self.assertEqual(result.details["execution_mode"], "javascript")
        self.assertTrue(result.details["script_hash"].startswith("sha256:"))
        self.assertLessEqual(len(result.details["return_preview"]), 80)
        self.assertTrue(result.details["return_artifact_ref"])
        self.assertEqual(result.details["network_delta"][0]["path"], "/api/search")
        self.assertEqual(
            result.details["document_candidate_refs"],
            ["https://example.test/article.html"],
        )

    def test_javascript_success_records_audit_context_in_artifacts_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            state = BrowserActionState()
            browser = FakeJsBrowser()
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
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "调用同源公开搜索接口并提取文章候选",
                            "mode": "javascript",
                            "javascript": {
                                "script": "return await fetch('/api/search?keyword=远海&page=1').then(r => r.json())",
                                "expected_result": "返回包含 title 和 url 的公开文章候选",
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
            script_meta = artifacts.get_meta(result.details["script_ref"])
            return_meta = artifacts.get_meta(result.details["return_artifact_ref"])
            proposal = result.trace_proposals[0]

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.details["why_standard_actions_are_insufficient"],
            "browser_observe 只看到前端容器，target_action 无法得到结果列表",
        )
        self.assertEqual(
            result.details["result_sink"],
            "只生成候选 lead、诊断和 recipe draft，不直接生成 EvidenceCard",
        )
        self.assertEqual(
            result.details["fallback"],
            "如果接口为空或失败，回到页面搜索框并换中文关键词",
        )
        self.assertEqual(
            script_meta["why_standard_actions_are_insufficient"],
            result.details["why_standard_actions_are_insufficient"],
        )
        self.assertEqual(return_meta["result_sink"], result.details["result_sink"])
        self.assertEqual(
            proposal.payload["why_standard_actions_are_insufficient"],
            result.details["why_standard_actions_are_insufficient"],
        )
        self.assertEqual(proposal.payload["result_sink"], result.details["result_sink"])
        self.assertEqual(proposal.payload["fallback"], result.details["fallback"])

    def test_javascript_html_after_does_not_replace_capturable_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            state = BrowserActionState()
            browser = FakeJsBrowser(
                html_after="<html><head><title>动态页</title></head><body>tampered</body></html>",
                network_delta=[],
            )
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
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "验证页面脚本是否只作为诊断结果而不是正文来源",
                            "mode": "javascript",
                            "javascript": {
                                "script": (
                                    "document.documentElement.outerHTML = "
                                    "\"<html><body>tampered</body></html>\"; "
                                    "return {changed: true}"
                                ),
                                "expected_result": "返回页面变化诊断",
                                **_js_audit_context(),
                                "allow_network_probe": False,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

            html_records = artifacts.iter_records("html")
            original_html = artifacts.get_text(observe.details["artifact_ref"])

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.details["next_observation_ref"],
            observe.details["observation_ref"],
        )
        self.assertEqual(len(html_records), 1)
        self.assertEqual(html_records[0].ref, observe.details["artifact_ref"])
        self.assertNotIn("tampered", original_html)

    def test_javascript_is_blocked_on_observation_with_sensitive_form_fields(self) -> None:
        browser = FakeJsBrowser(
            observe_html="""
<html><head><title>登录页</title></head><body>
  <form action="/login" method="post">
    <input type="hidden" name="csrf_token" value="secret-token" />
    <input type="password" name="password" value="secret-pwd" />
  </form>
</body></html>
"""
        )
        with tempfile.TemporaryDirectory() as tmp:
            observe_tool, execute_tool = _tools(tmp, browser)
            observe = _observe(observe_tool)
            result = asyncio.run(
                execute_tool.execute(
                    ToolCall(
                        "js",
                        "browser_execute",
                        {
                            "observation_ref": observe.details["observation_ref"],
                            "intent": "读取公开页面状态",
                            "mode": "javascript",
                            "javascript": {
                                "script": (
                                    "return {"
                                    "pwd: document.querySelector('input[type=password]').value, "
                                    "hidden: document.querySelector('input[type=hidden]').value"
                                    "}"
                                ),
                                "expected_result": "返回公开页面状态",
                                **_js_audit_context(),
                                "allow_network_probe": False,
                            },
                        },
                    ),
                    _ctx(),
                )
            )

        self.assertTrue(result.is_error)
        self.assertEqual(result.details["blocked_by"], "sensitive_page")
        self.assertEqual(browser.javascript_calls, 0)

    def test_real_bridge_blocks_sensitive_input_value_reads_runtime(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for guarded JavaScript runtime probe")
        payload = _run_guarded_script_in_node(
            script=(
                "return {"
                "pwd: document.querySelector('input[type=password]').value, "
                "hidden: document.querySelector('input[type=hidden]').value"
                "}"
            ),
            include_sensitive_inputs=True,
        )

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["name"], "SecurityError")
        self.assertIn("sensitive", payload["error"]["message"])


class FakeJsBrowser:
    def __init__(
        self,
        error: str = "",
        url_after: str = "https://example.test/search",
        network_delta: list[dict[str, object]] | None = None,
        html_after: str = "<html><head><title>动态页</title></head><body><a href='/article.html'>远海保障文章</a></body></html>",
        observe_html: str = "<html><head><title>动态页</title></head><body><div id='app'></div></body></html>",
    ) -> None:
        self.error = error
        self.url_after = url_after
        self.network_delta = network_delta
        self.html_after = html_after
        self.observe_html = observe_html
        self.last_safety_policy: dict[str, object] = {}
        self.javascript_calls = 0

    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            url=url,
            html=self.observe_html,
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
        self.javascript_calls += 1
        if "api/search" in script:
            self.last_safety_policy = dict(safety_policy)
        if self.error:
            return {
                "status": "failed",
                "error": {
                    "name": self.error,
                    "message": "missingVariable is not defined",
                    "line": 1,
                    "column": 8,
                },
                "result": None,
                "url_after": self.url_after,
                "title_after": "动态页",
                "html_after": "<html><head><title>动态页</title></head><body><div id='app'></div></body></html>",
                "network_delta": [],
            }
        return {
            "status": "success",
            "result": [
                {"title": "远海保障文章", "url": "https://example.test/article.html"}
            ],
            "url_after": self.url_after,
            "title_after": "动态页",
            "html_after": self.html_after,
            "network_delta": self.network_delta if self.network_delta is not None else [
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


def _tools(tmp: str, browser: FakeJsBrowser):
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
    return observe_tool, execute_tool


def _observe(observe_tool):
    return asyncio.run(
        observe_tool.execute(
            ToolCall(
                "observe",
                "browser_observe",
                {"url": "https://example.test/search", "topic": "远海"},
            ),
            _ctx(),
        )
    )


def _run_guarded_script_in_node(
    *,
    script: str,
    allow_network_probe: bool = False,
    include_sensitive_inputs: bool = False,
) -> dict[str, object]:
    guarded = _guarded_javascript(
        script=script,
        max_return_chars=200,
        allow_network_probe=allow_network_probe,
        safety_policy={
            "allowed_origin": "https://example.test",
            "allowed_methods": ["GET", "HEAD"],
            "force_credentials": "omit",
            "max_requests": 5 if allow_network_probe else 0,
        },
    )
    node_code = """
let fetchArgs = null;
const pageLocation = {
  href: 'https://example.test/search',
  origin: 'https://example.test',
  protocol: 'https:',
  host: 'example.test',
  hostname: 'example.test',
  port: '',
  pathname: '/search',
  search: '',
  hash: '',
  assign: (url) => {
    pageLocation.href = String(url);
  }
};
const pageWindow = {
  location: pageLocation,
  history: {},
  fetch: async (url, init) => {
    fetchArgs = {
      url: String(url),
      method: init && init.method,
      credentials: init && init.credentials,
      body: init && init.body
    };
    return {
      status: 200,
      headers: new Headers({'content-type': 'application/json'}),
      json: async () => [{title: '公开结果', url: 'https://example.test/article.html'}],
      text: async () => 'ok'
    };
  },
  Function,
  eval,
  setTimeout,
  clearTimeout
};
const anchorElement = {
  href: 'https://example.test/article.html',
  textContent: '正文',
  innerText: '正文',
  innerHTML: '正文',
  outerHTML: "<a href='/article.html'>正文</a>"
};
const passwordElement = {
  tagName: 'INPUT',
  nodeName: 'INPUT',
  type: 'password',
  name: 'password',
  value: 'secret-pwd',
  defaultValue: 'secret-pwd',
  textContent: '',
  innerText: '',
  innerHTML: '',
  outerHTML: "<input type='password' name='password' value='secret-pwd'>",
  getAttribute: (name) => {
    const lowered = String(name).toLowerCase();
    if (lowered === 'type') return 'password';
    if (lowered === 'value') return 'secret-pwd';
    if (lowered === 'name') return 'password';
    return null;
  }
};
const hiddenElement = {
  tagName: 'INPUT',
  nodeName: 'INPUT',
  type: 'hidden',
  name: 'csrf_token',
  value: 'secret-token',
  defaultValue: 'secret-token',
  textContent: '',
  innerText: '',
  innerHTML: '',
  outerHTML: "<input type='hidden' name='csrf_token' value='secret-token'>",
  getAttribute: (name) => {
    const lowered = String(name).toLowerCase();
    if (lowered === 'type') return 'hidden';
    if (lowered === 'value') return 'secret-token';
    if (lowered === 'name') return 'csrf_token';
    return null;
  }
};
const bodyElement = {
  textContent: '正文',
  innerText: '正文',
  innerHTML: "<a href='/article.html'>正文</a>",
  outerHTML: "<body><a href='/article.html'>正文</a></body>",
  querySelector: (selector) => {
    if (selector === 'a') return anchorElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return passwordElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return hiddenElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return passwordElement;
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === 'a') return [anchorElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return [passwordElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return [hiddenElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return [passwordElement, hiddenElement];
    return [];
  }
};
const htmlElement = {
  innerText: '正文',
  innerHTML: "<body><a href='/article.html'>正文</a></body>",
  outerHTML: "<html><body><a href='/article.html'>正文</a></body></html>",
  querySelector: (selector) => {
    if (selector === 'body') return bodyElement;
    if (selector === 'a') return anchorElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return passwordElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return hiddenElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return passwordElement;
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === 'body') return [bodyElement];
    if (selector === 'a') return [anchorElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return [passwordElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return [hiddenElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return [passwordElement, hiddenElement];
    return [];
  }
};
const pageDocument = {
  title: '动态页',
  cookie: 'session=secret',
  location: pageLocation,
  documentElement: htmlElement,
  body: bodyElement,
  querySelector: (selector) => {
    if (selector === 'html') return htmlElement;
    if (selector === 'body') return bodyElement;
    if (selector === 'a') return anchorElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return passwordElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return hiddenElement;
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return passwordElement;
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === 'html') return [htmlElement];
    if (selector === 'body') return [bodyElement];
    if (selector === 'a') return [anchorElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=password]') return [passwordElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type=hidden]') return [hiddenElement];
    if (INCLUDE_SENSITIVE && selector === 'input[type="password"], input[type="hidden"]') return [passwordElement, hiddenElement];
    return [];
  },
  getElementById: () => null,
  getElementsByTagName: (tagName) => {
    if (tagName === 'a') return [anchorElement];
    if (INCLUDE_SENSITIVE && String(tagName).toLowerCase() === 'input') return [passwordElement, hiddenElement];
    return [];
  }
};
anchorElement.ownerDocument = pageDocument;
passwordElement.ownerDocument = pageDocument;
hiddenElement.ownerDocument = pageDocument;
bodyElement.ownerDocument = pageDocument;
htmlElement.ownerDocument = pageDocument;
pageDocument.defaultView = pageWindow;
globalThis.location = pageLocation;
const guarded = CODE;
const fn = new Function('window', 'document', 'location', 'history', guarded);
Promise.resolve(fn(pageWindow, pageDocument, pageLocation, pageWindow.history)).then((result) => {
  console.log(JSON.stringify({
    status: result.status,
    result: result.result,
    error: result.error,
    url_after: result.url_after,
    global_url: globalThis.location.href,
    html_after: result.html_after,
    global_html: pageDocument.documentElement.outerHTML,
    network_delta: result.network_delta,
    fetch_args: fetchArgs
  }));
}).catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
""".replace("CODE", json.dumps(guarded)).replace(
        "INCLUDE_SENSITIVE",
        "true" if include_sensitive_inputs else "false",
    )
    completed = subprocess.run(
        ["node", "-e", node_code],
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return json.loads(completed.stdout)


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


def _js_audit_context() -> dict[str, str]:
    return {
        "why_standard_actions_are_insufficient": (
            "browser_observe 只看到前端容器，target_action 无法得到结果列表"
        ),
        "result_sink": "只生成候选 lead、诊断和 recipe draft，不直接生成 EvidenceCard",
        "fallback": "如果接口为空或失败，回到页面搜索框并换中文关键词",
    }


if __name__ == "__main__":
    unittest.main()
