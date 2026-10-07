from unittest.mock import MagicMock, patch

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import StructuredTool

import platform_core.agents.toolkits.buildin.tools as search_module
from platform_core.agents.toolkits.buildin.tools import (
    _all_tool_instances,
    _create_doubao_search,
    _create_open_websearch,
    _create_public_search,
    _extra_registry,
    _invoke_search_provider,
    _parse_public_search_response,
    _parse_crossref_search_response,
    _register_web_search_tool,
    _reset_web_search_runtime_state,
    _resilient_web_search,
    _resolve_web_search_provider,
)


def test_provider_failover_calls_raw_function_without_nested_tool_lifecycle(monkeypatch):
    """内部 provider 不是模型工具调用，不能再发出一个无声明 call id。"""
    invoke = MagicMock(side_effect=AssertionError("nested BaseTool.invoke must not be used"))
    raw_function = MagicMock(return_value={"results": [{"title": "paper"}]})
    provider_tool = MagicMock(invoke=invoke, func=raw_function)
    monkeypatch.setitem(
        search_module._WEB_SEARCH_PROVIDERS,
        "test-provider",
        (None, lambda: provider_tool, "Test Provider"),
    )

    result = _invoke_search_provider("test-provider", {"query": "high Q resonator", "count": 4})

    invoke.assert_not_called()
    raw_function.assert_called_once_with(query="high Q resonator", count=4)
    assert result == {
        "query": "high Q resonator",
        "results": [{"title": "paper"}],
        "provider": "test-provider",
    }


def test_resilient_web_search_emits_only_the_model_declared_tool_lifecycle(monkeypatch):
    """回归真实故障：provider 调用不能再产生第二个随机 tool_call_id。"""

    class LifecycleRecorder(BaseCallbackHandler):
        def __init__(self):
            self.starts = []

        def on_tool_start(self, serialized, _input_str, **_kwargs):
            self.starts.append((serialized or {}).get("name"))

    provider_tool = StructuredTool.from_function(
        name="web_search",
        description="test provider",
        func=lambda query, count=10, **_kwargs: {"query": query, "results": [{"title": "paper"}][:count]},
    )
    monkeypatch.setitem(
        search_module._WEB_SEARCH_PROVIDERS,
        "test-provider",
        (None, lambda: provider_tool, "Test Provider"),
    )
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _primary: ["test-provider"])
    _reset_web_search_runtime_state()
    recorder = LifecycleRecorder()

    result = search_module._create_resilient_web_search("test-provider").invoke(
        {"query": "high Q resonator", "count": 1},
        config={"callbacks": [recorder]},
    )

    assert result["status"] == "ok"
    assert recorder.starts == ["web_search"]


def test_tavily_provider_adapter_calls_implementation_without_nested_invoke(monkeypatch):
    invoke = MagicMock(side_effect=AssertionError("nested BaseTool.invoke must not be used"))
    run = MagicMock(
        return_value={
            "query": "metamaterial",
            "results": [{"title": str(index)} for index in range(5)],
        }
    )
    provider_tool = MagicMock(invoke=invoke, spec=["invoke", "_run"])
    provider_tool._run = run
    monkeypatch.setitem(
        search_module._WEB_SEARCH_PROVIDERS,
        "tavily",
        ("TAVILY_API_KEY", lambda: provider_tool, "Tavily"),
    )

    result = _invoke_search_provider(
        "tavily",
        {
            "query": "metamaterial",
            "count": 2,
            "sites": ["ieee.org"],
            "block_hosts": ["example.invalid"],
            "time_range": "month",
        },
    )

    invoke.assert_not_called()
    run.assert_called_once_with(
        query="metamaterial",
        include_domains=["ieee.org"],
        exclude_domains=["example.invalid"],
        time_range="month",
        run_manager=None,
    )
    assert [item["title"] for item in result["results"]] == ["0", "1"]


def test_doubao_search_missing_key(monkeypatch):
    monkeypatch.delenv("DOUBAO_SEARCH_API_KEY", raising=False)
    doubao = _create_doubao_search()
    res = doubao.invoke({"query": "python"})
    assert res["error"] == "DOUBAO_SEARCH_API_KEY 未配置"
    assert res["results"] == []


def test_doubao_search_success_with_detailed_params(monkeypatch):
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "test_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ResponseMetadata": {},
        "Result": {
            "TimeCost": 150,
            "WebResults": [
                {
                    "Title": "Python 官网",
                    "Url": "https://www.python.org",
                    "Summary": "Python 编程语言官方网站",
                    "RankScore": 0.98,
                    "SiteName": "Python Org",
                    "PublishTime": "2026-01-01T00:00:00+08:00",
                }
            ],
        },
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        doubao = _create_doubao_search()
        res = doubao.invoke(
            {
                "query": "python 3.13",
                "count": 5,
                "time_range": "OneWeek",
                "sites": ["python.org", "github.com"],
                "block_hosts": ["badsite.com"],
                "content_format": "markdown",
            }
        )

        assert res["query"] == "python 3.13"
        assert len(res["results"]) == 1
        item = res["results"][0]
        assert item["title"] == "Python 官网"
        assert item["url"] == "https://www.python.org"
        assert item["content"] == "Python 编程语言官方网站"
        assert item["score"] == 0.98
        assert item["site_name"] == "Python Org"
        assert item["publish_time"] == "2026-01-01T00:00:00+08:00"

        # Verify payload mapping
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["Query"] == "python 3.13"
        assert payload["Count"] == 5
        assert payload["TimeRange"] == "OneWeek"
        assert payload["Filter"]["Sites"] == "python.org|github.com"
        assert payload["Filter"]["BlockHosts"] == "badsite.com"
        assert payload["ContentFormats"] == "markdown"


def test_register_web_search_tool_provider_selection(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "key1")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    instances_before = len(_all_tool_instances)

    _register_web_search_tool()

    assert _extra_registry["web_search"].display_name == "豆包 网页搜索"
    assert len(_all_tool_instances) == instances_before + 1
    assert _all_tool_instances[-1].name == "web_search"


def test_web_search_defaults_to_public_provider_without_api_keys(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("OPEN_WEBSEARCH_URL", raising=False)
    monkeypatch.delenv("DOUBAO_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert _resolve_web_search_provider() == "public"


def test_web_search_prefers_open_websearch_when_daemon_is_configured(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://open-websearch:3210")
    monkeypatch.setenv("DOUBAO_SEARCH_API_KEY", "paid-provider-key")

    assert _resolve_web_search_provider() == "open-websearch"


def test_open_websearch_normalizes_daemon_results(monkeypatch):
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://open-websearch:3210/")
    monkeypatch.setenv("OPEN_WEBSEARCH_ENGINES", "bing,startpage,invalid,bing")
    response = MagicMock()
    response.json.return_value = {
        "status": "ok",
        "data": {
            "query": "radar site:ieee.org",
            "results": [
                {
                    "title": " IEEE radar paper ",
                    "url": "https://ieee.org/paper",
                    "description": "  citable   abstract ",
                    "source": "IEEE",
                    "engine": "bing",
                },
                {
                    "title": "blocked",
                    "url": "https://ads.example/page",
                    "description": "ignore",
                    "engine": "startpage",
                },
            ],
            "partialFailures": [{"engine": "startpage", "code": "engine_error", "message": "token unavailable"}],
        },
        "error": None,
    }

    with patch("httpx.Client.post", return_value=response) as mock_post:
        result = _create_open_websearch().invoke(
            {
                "query": "radar",
                "count": 5,
                "sites": ["ieee.org"],
                "block_hosts": ["ads.example"],
            }
        )

    response.raise_for_status.assert_called_once()
    mock_post.assert_called_once_with(
        "http://open-websearch:3210/search",
        json={
            "query": "radar (site:ieee.org)",
            "limit": 5,
            "engines": ["bing", "startpage"],
            "searchMode": "request",
        },
    )
    assert result["provider"] == "open-websearch"
    assert result["results"] == [
        {
            "title": "IEEE radar paper",
            "url": "https://ieee.org/paper",
            "content": "citable abstract",
            "site_name": "ieee.org",
            "search_engine": "bing",
        }
    ]
    assert result["partial_failures"][0]["engine"] == "startpage"


def test_open_websearch_surfaces_daemon_error(monkeypatch):
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://open-websearch:3210")
    response = MagicMock()
    response.json.return_value = {
        "status": "error",
        "data": None,
        "error": {"code": "engine_error", "message": "all configured engines failed"},
    }

    with patch("httpx.Client.post", return_value=response):
        result = _create_open_websearch().invoke({"query": "radar"})

    assert result["results"] == []
    assert result["error"] == "all configured engines failed"


def test_public_search_parses_original_urls_and_blocks_hosts():
    html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.edu%2Fpaper">论文</a>
      <div class="result__snippet">公开论文摘要</div>
    </div>
    <div class="result">
      <a class="result__a" href="https://blocked.example/report">应屏蔽</a>
      <div class="result__snippet">不可用来源</div>
    </div>
    """

    result = _parse_public_search_response(
        "测试检索",
        html,
        count=10,
        block_hosts=["blocked.example"],
    )

    assert result == {
        "query": "测试检索",
        "provider": "public",
        "results": [
            {
                "title": "论文",
                "url": "https://example.edu/paper",
                "content": "公开论文摘要",
                "site_name": "example.edu",
            }
        ],
    }


def test_crossref_parser_returns_citable_academic_sources():
    result = _parse_crossref_search_response(
        "radar UAV IEEE paper",
        {
            "message": {
                "items": [
                    {
                        "DOI": "10.1109/example",
                        "title": ["Radar-Based UAV Classification"],
                        "URL": "https://doi.org/10.1109/example",
                        "abstract": "<jats:p>Micro-Doppler evidence.</jats:p>",
                        "publisher": "IEEE",
                        "published": {"date-parts": [[2025, 7]]},
                    }
                ]
            }
        },
        count=5,
    )

    assert result["search_endpoint"] == "crossref"
    assert result["results"][0] == {
        "title": "Radar-Based UAV Classification",
        "url": "https://doi.org/10.1109/example",
        "content": "Micro-Doppler evidence.",
        "site_name": "IEEE",
        "publish_time": "2025-7",
        "doi": "10.1109/example",
    }


def test_public_search_returns_citable_results(monkeypatch):
    html = """
    <div class="result">
      <a class="result__a" href="https://example.org/standard">公开标准</a>
      <div class="result__snippet">标准正文摘要</div>
    </div>
    """
    response = MagicMock()
    response.text = html

    with patch("httpx.Client.get", return_value=response) as mock_get:
        result = _create_public_search().invoke(
            {
                "query": "雷达 标准",
                "count": 5,
                "sites": ["example.org"],
                "time_range": "OneYear",
            }
        )

    response.raise_for_status.assert_called_once()
    assert result["results"][0]["url"] == "https://example.org/standard"
    _, kwargs = mock_get.call_args
    assert "site:example.org" in kwargs["params"]["query"]
    assert kwargs["params"]["df"] == "y"


def test_public_search_reaches_bing_when_sogou_and_duckduckgo_are_blocked():
    challenge = MagicMock(status_code=202, text="<html><body>bot challenge</body></html>")
    challenge.raise_for_status.return_value = None
    bing = MagicMock(
        status_code=200,
        text="""
        <html><li class="b_algo"><h2><a href="https://ieee.example/paper">IEEE paper</a></h2>
        <div class="b_caption"><p>Micro-Doppler classification evidence.</p></div></li></html>
        """,
    )
    bing.raise_for_status.return_value = None

    with patch(
        "httpx.Client.get",
        side_effect=[
            __import__("httpx").HTTPStatusError(
                "403 anti-spider",
                request=__import__("httpx").Request("GET", "https://www.sogou.com/web"),
                response=__import__("httpx").Response(
                    403,
                    request=__import__("httpx").Request("GET", "https://www.sogou.com/web"),
                ),
            ),
            challenge,
            bing,
        ],
    ) as mock_get:
        result = _create_public_search().invoke({"query": "radar signal lookup", "count": 5})

    assert mock_get.call_count == 3
    assert result["search_endpoint"] == "bing"
    assert result["results"] == [
        {
            "title": "IEEE paper",
            "url": "https://ieee.example/paper",
            "content": "Micro-Doppler classification evidence.",
            "site_name": "ieee.example",
        }
    ]


def test_resilient_search_fails_over_before_model_sees_error(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ATTEMPTS", "1")
    monkeypatch.setenv("WEB_SEARCH_RETRY_INITIAL_DELAY_SECONDS", "0")
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _primary: ["doubao", "tavily"])
    calls = []

    def fake_invoke(provider, arguments):
        calls.append(provider)
        if provider == "doubao":
            return {"query": arguments["query"], "results": [], "provider": provider, "error": "503"}
        return {
            "query": arguments["query"],
            "results": [{"title": "IEEE paper", "url": "https://example.org/paper"}],
            "provider": provider,
        }

    monkeypatch.setattr(search_module, "_invoke_search_provider", fake_invoke)

    result = _resilient_web_search("doubao", {"query": "micro Doppler radar", "count": 5})

    assert result["status"] == "ok"
    assert result["provider"] == "tavily"
    assert result["attempted_providers"] == ["doubao", "tavily"]
    assert calls == ["doubao", "tavily"]


def test_resilient_search_opens_shared_circuit_and_returns_terminal_degradation(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ATTEMPTS", "1")
    monkeypatch.setenv("WEB_SEARCH_CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("WEB_SEARCH_CIRCUIT_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("WEB_SEARCH_RETRY_INITIAL_DELAY_SECONDS", "0")
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _primary: ["public"])
    calls = []

    def always_fail(provider, arguments):
        calls.append((provider, arguments["query"]))
        return {"query": arguments["query"], "results": [], "provider": provider, "error": "timeout"}

    monkeypatch.setattr(search_module, "_invoke_search_provider", always_fail)

    first = _resilient_web_search("public", {"query": "first query", "count": 5})
    second = _resilient_web_search("public", {"query": "synonym query", "count": 5})

    assert first["status"] == second["status"] == "degraded"
    assert first["retryable"] is False
    assert "不要再次调用 web_search" in first["next_action"]
    assert second["failures"] == [{"provider": "public", "error": "circuit_open"}]
    assert calls == [("public", "first query")]
