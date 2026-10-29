from unittest.mock import MagicMock, patch

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import StructuredTool

import pytest

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


@pytest.fixture(autouse=True)
def isolate_provider_adapters_from_distributed_scheduler(monkeypatch):
    """适配器单测隔离 Redis；真实共享调度在独立进程集成测试中验证。"""
    # 生产容器会注入该地址；旧路径单测必须从无 SearXNG 的确定性基线开始，
    # 融合用例再在各自测试内显式启用，避免测试结果依赖执行机环境。
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.setattr(search_module, "coordinated_search", lambda provider, arguments, call: call())


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
        func=lambda query, count=10, **_kwargs: {
            "query": query,
            "results": [{"title": "High Q resonator paper", "url": "https://example.edu/paper"}][:count],
        },
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
            "limit": 20,
            "engines": ["bing", "startpage"],
        },
    )
    assert result["provider"] == "open-websearch"
    for item in result["results"]:
        assert len(item.pop("source_id")) == 16
        assert item.pop("citation").startswith('<cite source="https://ieee.org/paper"')
    assert result["results"] == [
        {
            "title": "IEEE radar paper",
            "url": "https://ieee.org/paper",
            "content": "citable abstract",
            "site_name": "ieee.org",
            "search_engine": "bing",
            "source_tier": "authoritative",
        }
    ]
    assert result["source_quality"] == {"authoritative": 1, "other": 0}
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


def test_open_websearch_distinguishes_no_hits_from_all_engine_failures():
    """成功引擎无命中不能被当成网络故障。"""
    empty = search_module._parse_open_websearch_response(
        "specific query", {"engines": ["bing", "duckduckgo"], "results": [], "partialFailures": []}, count=5
    )
    assert empty["status"] == "empty"
    assert "error" not in empty
    partial = search_module._parse_open_websearch_response(
        "specific query",
        {"engines": ["bing", "duckduckgo"], "partialFailures": [{"engine": "bing", "code": "engine_error"}]},
        count=5,
    )
    assert partial["status"] == "empty"
    failed = search_module._parse_open_websearch_response(
        "specific query", {"engines": ["bing"], "partialFailures": [{"engine": "bing"}]}, count=5
    )
    assert failed["error"]


def test_open_websearch_challenges_are_not_empty_results():
    result = search_module._parse_open_websearch_response(
        "radar",
        {
            "engines": ["bing", "duckduckgo"],
            "results": [],
            "partialFailures": [
                {"engine": "bing", "message": "CAPTCHA required"},
                {"engine": "duckduckgo", "message": "403 anti-spider"},
            ],
        },
        count=5,
    )
    assert result["status"] == "blocked"
    assert result["retry_after_seconds"] == 300


@pytest.mark.parametrize("status_code", [200, 403])
def test_daemon_http_challenge_cools_engines_even_without_json(monkeypatch, status_code):
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://search.test")
    monkeypatch.setenv("OPEN_WEBSEARCH_ENGINES", "bing,duckduckgo")
    coordinator = MagicMock()
    coordinator.engine_remaining.return_value = 0
    monkeypatch.setattr(search_module, "get_active_search_coordinator", lambda: coordinator)
    response = MagicMock(status_code=status_code, text="<html><title>CAPTCHA required</title></html>")
    response.json.side_effect = ValueError("not JSON")
    with patch("httpx.Client.post", return_value=response):
        result = search_module._open_websearch.func(query="radar signal lookup")
    assert result["status"] == "blocked"
    assert result["retry_after_seconds"] == 300
    if status_code == 200:
        assert coordinator.cool_engine.call_count == 2
    else:
        assert [item["engine"] for item in result["partial_failures"]] == ["bing", "duckduckgo"]


def test_partial_challenge_does_not_hide_healthy_engine_empty_result():
    result = search_module._parse_open_websearch_response(
        "radar",
        {
            "engines": ["bing", "duckduckgo"],
            "results": [],
            "partialFailures": [{"engine": "bing", "message": "CAPTCHA required"}],
        },
        count=5,
    )
    assert result["status"] == "empty"
    assert "error" not in result


def test_public_http_200_challenge_is_blocked_and_cooled(monkeypatch):
    coordinator = MagicMock()
    coordinator.engine_remaining.return_value = 0
    monkeypatch.setattr(search_module, "get_active_search_coordinator", lambda: coordinator)
    response = MagicMock(status_code=200, text="<html><title>Verify you are human</title></html>")
    with patch("httpx.Client.get", return_value=response) as get:
        result = search_module._public_search.func(query="radar signal lookup")
    assert get.call_count == 3
    assert result["status"] == "blocked"
    assert coordinator.cool_engine.call_count == 3


def test_challenge_fails_over_once_and_finishes_with_other_evidence(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["open-websearch", "public"])
    invoke = MagicMock(return_value={"status": "blocked", "results": [], "error": "CAPTCHA"})
    monkeypatch.setattr(search_module, "_invoke_search_provider", invoke)
    result = _resilient_web_search("open-websearch", {"query": "radar signal lookup"})
    assert invoke.call_count == 2
    assert result["status"] == "degraded"
    assert result["reason"] == "antibot_challenge"
    assert "AMiner" in result["next_action"]


def test_open_websearch_filters_unrelated_bing_results_and_ranks_relevant_sources(monkeypatch):
    """复现真实中文检索：微信、微博不能作为微多普勒证据。"""
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["open-websearch"])
    monkeypatch.setattr(
        search_module,
        "_invoke_search_provider",
        lambda *_: {
            "results": [
                {"title": "微信，是一个生活方式", "url": "https://weixin.qq.com/", "content": "微信官网"},
                {"title": "微博", "url": "https://weibo.com/", "content": "随时发现新鲜事"},
                {
                    "title": "基于双雷达微动特征融合的无人机分类识别",
                    "url": "https://radars.ac.cn/paper",
                    "content": "微多普勒特征",
                },
            ]
        },
    )
    result = _resilient_web_search("open-websearch", {"query": "微多普勒 雷达 无人机 识别"})
    assert result["status"] == "ok"
    assert result["filtered_irrelevant_count"] == 2
    assert [item["url"] for item in result["results"]] == ["https://radars.ac.cn/paper"]


def test_empty_search_does_not_open_shared_provider_circuit(monkeypatch):
    """连续冷门查询不会熔断其他研究员的正常查询。"""
    _reset_web_search_runtime_state()
    monkeypatch.setenv("WEB_SEARCH_CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["open-websearch"])
    invoke = MagicMock(return_value={"status": "empty", "results": []})
    monkeypatch.setattr(search_module, "_invoke_search_provider", invoke)
    for query in ["first narrow query", "second narrow query"]:
        assert _resilient_web_search("open-websearch", {"query": query})["status"] == "empty"
    assert invoke.call_count == 2
    assert search_module._WEB_SEARCH_PROVIDER_HEALTH["open-websearch"]["failures"] == 0


def test_open_websearch_enforces_site_filter_when_engine_ignores_operator():
    """限定站点必须在结果边界再次过滤。"""
    result = search_module._parse_open_websearch_response(
        "radar",
        {"results": [{"title": "Unrelated", "url": "https://weixin.qq.com/"}]},
        count=5,
        sites=["ieee.org"],
    )
    assert result["results"] == []
    assert result["status"] == "empty"


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
        "公开论文",
        html,
        count=10,
        block_hosts=["blocked.example"],
    )

    assert result["distinct_domains"] == 1
    assert result["results"][0]["citation"] == '<cite source="https://example.edu/paper" type="url">1</cite>'
    result.pop("distinct_domains")
    for item in result["results"]:
        assert len(item.pop("source_id")) == 16
        item.pop("citation")
    assert result == {
        "query": "公开论文",
        "provider": "public",
        "results": [
            {
                "title": "论文",
                "url": "https://example.edu/paper",
                "content": "公开论文摘要",
                "site_name": "example.edu",
                "source_tier": "authoritative",
            }
        ],
        "source_quality": {"authoritative": 1, "other": 0},
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
      <a class="result__a" href="https://example.org/standard">雷达标准</a>
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
        <div class="b_caption"><p>Micro-Doppler radar signal classification evidence.</p></div></li></html>
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
    for item in result["results"]:
        assert len(item.pop("source_id")) == 16
        assert item.pop("citation").startswith('<cite source="https://ieee.example/paper"')
    assert result["results"] == [
        {
            "title": "IEEE paper",
            "url": "https://ieee.example/paper",
            "content": "Micro-Doppler radar signal classification evidence.",
            "site_name": "ieee.example",
            "source_tier": "other",
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
            "results": [{"title": "IEEE micro Doppler radar paper", "url": "https://example.org/paper"}],
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


@pytest.mark.parametrize("provider", ["open-websearch", "public", "doubao", "tavily"])
def test_every_provider_rejects_screenshot_noise_and_keeps_uav_evidence(monkeypatch, provider):
    """截图中的单字释义和游戏结果不能从任一后端进入证据列表。"""
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: [provider])
    results = [
        {
            "title": "VALORANT《无畏契约》官方网站-腾讯游戏",
            "content": "2026无畏契约全球冠军赛",
            "url": "https://val.qq.com",
        },
        {
            "title": "无（汉语文字）_百度百科",
            "content": "无是汉语文字，甲骨文始见",
            "url": "https://baike.baidu.com/word",
        },
        {"title": "无（哲学概念）", "content": "存在的否定状态", "url": "https://example.org/philosophy"},
        {"title": "无怎么读_无的拼音", "content": "2026年汉语字典", "url": "https://example.org/dictionary"},
        {
            "title": "俄乌战场上FPV无人机作战效能浅析",
            "content": "无人机打击效率与战果数据",
            "url": "https://example.org/uav",
        },
    ]
    monkeypatch.setattr(search_module, "_invoke_search_provider", lambda *_: {"results": results})
    result = _resilient_web_search(provider, {"query": "无人机 俄乌 战场 战果 数据 FPV无人机 巡飞弹 打击 效率"})
    assert result["status"] == "ok"
    assert result["filtered_irrelevant_count"] == 4
    assert [item["url"] for item in result["results"]] == ["https://example.org/uav"]


@pytest.mark.parametrize(
    "query,title,content",
    [
        ("无人机蜂群 自主协同", "无人系统资料", "自主学习的发展计划"),
        ("无人机 技术 发展 数据", "游戏技术发展趋势", "用户数据分析"),
        ("micro radar", "Microsoft radio service", "microservices for radiology"),
        ("无人机 2026", "2026无畏契约全球冠军赛", "无字拼音"),
    ],
)
def test_generic_words_years_and_term_fragments_do_not_establish_topic_relevance(query, title, content):
    assert search_module._rank_search_results(query, [{"title": title, "content": content}]) == []


def test_chinese_compound_word_reordering_keeps_relevant_paper():
    result = {"title": "蜂群无人机自主协同技术", "content": "集群规划"}
    assert search_module._rank_search_results("无人机蜂群 自主协同", [result]) == [result]


def test_required_terms_keep_results_on_the_parent_topic():
    """核心锚点阻止同一技术词把检索带到错误对象。"""
    radar = {
        "title": "复杂电磁环境下雷达目标识别",
        "content": "稀疏注意力降低识别计算量",
        "url": "https://example.org/radar",
    }
    language_model = {
        "title": "稀疏注意力语言模型",
        "content": "降低长文本计算量并提高推理效率",
        "url": "https://example.org/llm",
    }
    assert search_module._rank_search_results(
        "稀疏注意力 计算量",
        [language_model, radar],
        required_terms=["雷达"],
    ) == [radar]


def test_hyphenated_required_terms_match_space_separated_source_text():
    result = {
        "title": "High Power Microwave Counter UAS Test",
        "content": "A counter-UAS field demonstration against a drone swarm.",
        "url": "https://example.org/hpm",
    }
    assert search_module._rank_search_results(
        "high-power microwave counter-UAS",
        [result],
        required_terms=["high-power microwave", "counter-UAS"],
    ) == [result]


def test_title_matches_rank_ahead_of_summary_only_matches():
    title_match = {"title": "无人机蜂群自主协同试验", "content": "公开报告"}
    summary_match = {"title": "自主系统试验", "content": "无人机蜂群采用自主协同"}
    assert search_module._rank_search_results("无人机蜂群 自主协同", [summary_match, title_match]) == [
        title_match,
        summary_match,
    ]


def test_authoritative_publication_page_ranks_ahead_of_matching_aggregator():
    aggregator = {
        "title": "High-power Microwave Damage Assessment Method for UAV",
        "content": "high power microwave UAV damage assessment",
        "url": "https://www.researchgate.net/publication/123",
    }
    publisher = {
        "title": "High-power Microwave Damage Assessment Method for UAV",
        "content": "high power microwave UAV damage assessment",
        "url": "https://iopscience.iop.org/article/10.1088/example",
    }
    ranked = search_module._rank_search_results("high power microwave UAV damage", [aggregator, publisher])
    assert ranked == [publisher]


def test_filtered_results_expose_source_quality_summary():
    result = search_module._filter_search_results(
        {
            "results": [
                {
                    "title": "DARPA counter UAV program",
                    "content": "counter UAV field test",
                    "url": "https://www.darpa.mil/program/example",
                },
                {
                    "title": "Counter UAV overview",
                    "content": "counter UAV field test",
                    "url": "https://news.example/overview",
                },
            ]
        },
        "counter UAV field test",
    )
    assert result["source_quality"] == {"authoritative": 1, "other": 1}
    assert [item["source_tier"] for item in result["results"]] == ["authoritative", "other"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.81.cn/wj_208604/16449511.html",
        "https://www.mod.gov.cn/gfbw/qwfb/16302036.html",
        "https://www.gov.cn/zhengce/example.htm",
        "https://www.cas.cn/syky/202501/example.html",
        "https://www.cetc.com.cn/zgdk/example/index.html",
        "https://www.engineering.org.cn/sscae/CN/example.html",
        "https://www.avic.com/cn/xwzx/example.html",
        "https://www.norinco.com/GB/example/index.html",
        "https://www.spacechina.com/n25/n2014789/example.html",
    ],
)
def test_domestic_official_and_original_manufacturer_sources_are_authoritative(url):
    """国内政府、军队、科研机构和军工原厂原文属于权威来源。"""
    assert search_module._search_source_tier({"url": url}) == "authoritative"


def test_open_websearch_does_not_trust_baidu_display_host_as_verified_authority():
    result = search_module._parse_open_websearch_response(
        "counter UAV field test",
        {
            "results": [
                {
                    "title": "Army counter UAV field test",
                    "description": "counter UAV field test results",
                    "url": "http://www.baidu.com/link?url=opaque",
                    "source": "www.army.mil/article/...",
                    "engine": "baidu",
                }
            ]
        },
        count=5,
    )
    assert result["results"][0]["source_host"] == "www.army.mil"
    assert result["results"][0]["source_tier"] == "other"
    assert result["source_quality"] == {"authoritative": 0, "other": 1}


@pytest.mark.parametrize("query", ["无", "资料 数据 发展", "2026 site:example.org"])
def test_queries_without_topic_do_not_call_search_backends(monkeypatch, query):
    invoke = MagicMock(side_effect=AssertionError("no topic to search"))
    monkeypatch.setattr(search_module, "_invoke_search_provider", invoke)
    assert _resilient_web_search("public", {"query": query})["status"] == "empty"
    invoke.assert_not_called()


def _fusion_config(**overrides):
    config = {
        "adaptive_fusion_enabled": True,
        "searxng_enabled": True,
        "general_engines": ["brave"],
        "chinese_engines": ["baidu", "sogou", "sogou wechat"],
        "academic_engines": ["arxiv", "semantic scholar", "pubmed"],
        "news_engines": ["brave.news", "reuters"],
        "official_engines": ["brave"],
        "min_relevant_results": 6,
        "min_distinct_domains": 4,
        "max_filtered_ratio_percent": 60,
        "total_timeout_seconds": 1,
        "searxng_timeout_seconds": 1,
        "hedge_delay_seconds": 0.1,
        "rrf_k": 60,
    }
    return {**config, **overrides}


@pytest.mark.parametrize(
    "query,expected_language,expected_categories,immediate",
    [
        ("无人机蜂群", "zh-CN", {"chinese"}, True),
        ("无人机 swarm autonomy", "all", {"mixed"}, True),
        ("latest radar news", "en", {"news"}, True),
        ("radar official standard", "en", {"official"}, True),
        ("radar signal processing", "en", {"general"}, False),
        (
            "photonic time crystal nonreciprocal microwave amplification",
            "en",
            {"academic"},
            True,
        ),
        ("Moiré excitons in semiconductor heterobilayers", "en", {"academic"}, True),
        ("Hydrodynamic electron flow in graphene", "en", {"academic"}, True),
        ("roton-like phonon polariton dispersion in twisted alpha-MoO3", "en", {"academic"}, True),
        ("magneto-ionic protonation control of exchange bias", "en", {"academic"}, True),
        ("nonreciprocal magnon polarons in antiferromagnets", "en", {"academic"}, True),
    ],
)
def test_fusion_query_classification_is_deterministic(query, expected_language, expected_categories, immediate):
    profile = search_module._classify_fusion_query({"query": query}, _fusion_config())

    assert profile["language"] == expected_language
    assert expected_categories.issubset(profile["categories"])
    assert profile["immediate_fusion"] is immediate
    assert len(profile["engines"]) <= 8


def test_searxng_response_normalizes_dates_failures_and_strict_custom_range():
    payload = {
        "results": [
            {
                "title": "<b>Radar drone field test</b>",
                "url": "https://ieee.org/paper",
                "content": "Radar drone field test evidence",
                "publishedDate": "2025-06-15T12:00:00Z",
                "engines": ["semantic scholar", "brave"],
            },
            {
                "title": "Radar drone old field test",
                "url": "https://ieee.org/old",
                "content": "Radar drone field test evidence",
                "publishedDate": "2024-12-31",
                "engine": "brave",
            },
            {
                "title": "Radar drone undated field test",
                "url": "https://ieee.org/undated",
                "content": "Radar drone field test evidence",
                "engine": "brave",
            },
        ],
        "unresponsive_engines": [["pubmed", "timeout"]],
    }

    result = search_module._parse_searxng_response(
        "radar drone field test",
        payload,
        count=10,
        engines=["brave", "pubmed"],
        time_range="2025-01-01..2025-12-31",
        sites=["ieee.org"],
    )

    assert [item["url"] for item in result["results"]] == ["https://ieee.org/paper"]
    assert result["results"][0]["title"] == "Radar drone field test"
    assert result["results"][0]["publish_time"].startswith("2025-06-15")
    assert result["partial_failures"] == [{"provider": "searxng", "engine": "pubmed", "error": "timeout"}]


def test_searxng_posts_form_with_profiles_and_search_operators(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080/")
    monkeypatch.setattr(search_module, "get_active_search_coordinator", lambda: None)
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "title": "Radar drone field test",
                "url": "https://ieee.org/paper",
                "content": "Radar drone field test evidence",
                "engine": "brave",
            }
        ]
    }

    with patch("httpx.Client.post", return_value=response) as post:
        result = search_module._searxng_search(
            "radar drone field test",
            count=5,
            time_range="OneWeek",
            sites=["ieee.org"],
            block_hosts=["spam.example"],
            engines=["brave", "semantic scholar"],
            language="all",
        )

    _, kwargs = post.call_args
    assert kwargs["data"] == {
        "q": "radar drone field test (site:ieee.org) -site:spam.example",
        "format": "json",
        "engines": "brave,semantic scholar",
        "language": "all",
        "safesearch": "0",
        "time_range": "week",
    }
    assert result["provider"] == "searxng"


def test_rrf_fusion_merges_canonical_urls_metadata_and_preserves_hard_constraints():
    open_result = {
        "provider": "open-websearch",
        "results": [
            {
                "title": "Counter UAV test",
                "url": "https://example.org/paper?utm_source=open",
                "content": "counter UAV field test",
                "search_engine": "bing",
            }
        ],
    }
    searx_result = {
        "provider": "searxng",
        "results": [
            {
                "title": "Counter UAV field test and assessment",
                "url": "https://example.org/paper",
                "content": "counter UAV field test with measured assessment results",
                "search_engines": ["brave"],
            },
            {
                "title": "Counter UAV field test program",
                "url": "https://www.darpa.mil/program/counter-uav",
                "content": "counter UAV field test program",
                "search_engines": ["brave"],
            },
        ],
    }

    result = search_module._merge_fused_search_results(
        "counter UAV field test",
        {"count": 10, "block_hosts": ["blocked.example"]},
        {"language": "en", "categories": ["general"], "engines": ["brave"]},
        _fusion_config(),
        [open_result, searx_result],
        searxng_attempted=True,
    )

    assert result["status"] == "ok"
    assert result["provider"] == "fusion"
    assert result["completed_providers"] == ["open-websearch", "searxng"]
    merged = next(item for item in result["results"] if "example.org/paper" in item["url"])
    assert merged["title"] == "Counter UAV field test and assessment"
    assert merged["providers"] == ["open-websearch", "searxng"]
    assert merged["search_engines"] == ["bing", "brave"]
    assert all(not key.startswith("_fusion_") for item in result["results"] for key in item)


def test_plain_english_query_skips_searxng_when_open_quality_is_sufficient(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(search_module, "load_web_search_runtime_options", lambda: _fusion_config())
    open_result = {
        "provider": "open-websearch",
        "status": "ok",
        "results": [
            {
                "title": f"Radar drone field test result {index}",
                "url": f"https://source{index}.example/paper",
                "content": "radar drone field test evidence",
            }
            for index in range(6)
        ],
        "distinct_domains": 6,
        "source_quality": {"authoritative": 0, "other": 6},
    }
    monkeypatch.setattr(search_module, "_legacy_resilient_web_search", MagicMock(return_value=open_result))
    searxng = MagicMock(side_effect=AssertionError("quality gate should stop the second lane"))
    monkeypatch.setattr(search_module, "_invoke_searxng_provider", searxng)

    result = search_module._resilient_web_search("open-websearch", {"query": "radar drone field test", "count": 10})

    assert result["search_mode"] == "open_only"
    assert result["completed_providers"] == ["open-websearch"]
    searxng.assert_not_called()


def test_parallel_strategy_starts_both_web_lanes_for_plain_english_query(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(search_module, "load_web_search_runtime_options", lambda: _fusion_config())
    monkeypatch.setattr(
        search_module,
        "_legacy_resilient_web_search",
        lambda *_: {
            "provider": "open-websearch",
            "results": [
                {
                    "title": "Radar drone field test",
                    "url": "https://open.example/radar",
                    "content": "radar drone field test evidence",
                }
            ],
        },
    )
    searxng = MagicMock(
        return_value={
            "provider": "searxng",
            "results": [
                {
                    "title": "Radar drone field test report",
                    "url": "https://searx.example/radar",
                    "content": "radar drone field test report evidence",
                }
            ],
        }
    )
    monkeypatch.setattr(search_module, "_invoke_searxng_provider", searxng)

    result = search_module._resilient_web_search(
        "open-websearch",
        {"query": "radar drone field test", "count": 10, "_fusion_strategy": "parallel"},
    )

    assert result["search_mode"] == "parallel_fusion"
    assert result["completed_providers"] == ["open-websearch", "searxng"]
    searxng.assert_called_once()


def test_immediate_fusion_keeps_open_results_when_searxng_misses_total_deadline(monkeypatch):
    import time

    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(
        search_module,
        "load_web_search_runtime_options",
        lambda: _fusion_config(total_timeout_seconds=0.05, hedge_delay_seconds=0.01),
    )
    monkeypatch.setattr(
        search_module,
        "_legacy_resilient_web_search",
        lambda *_: {
            "provider": "open-websearch",
            "status": "ok",
            "results": [
                {
                    "title": "无人机雷达试验",
                    "url": "https://example.org/radar",
                    "content": "无人机雷达试验证据",
                }
            ],
        },
    )

    def slow_searxng(*_args):
        time.sleep(0.2)
        return {"provider": "searxng", "results": []}

    monkeypatch.setattr(search_module, "_invoke_searxng_provider", slow_searxng)
    started = time.monotonic()
    result = search_module._resilient_web_search("open-websearch", {"query": "无人机 雷达", "count": 10})

    assert time.monotonic() - started < 0.15
    assert result["status"] == "ok"
    assert result["completed_providers"] == ["open-websearch"]
    assert result["partial_failures"][0]["provider"] == "searxng"


def test_disabling_adaptive_fusion_restores_legacy_path(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    monkeypatch.setattr(
        search_module,
        "load_web_search_runtime_options",
        lambda: _fusion_config(adaptive_fusion_enabled=False),
    )
    legacy = MagicMock(return_value={"status": "empty", "results": [], "marker": "legacy"})
    monkeypatch.setattr(search_module, "_legacy_resilient_web_search", legacy)

    result = search_module._resilient_web_search("open-websearch", {"query": "radar field test"})

    assert result["marker"] == "legacy"
    legacy.assert_called_once()


def test_open_websearch_filters_before_count_limit():
    result = search_module._parse_open_websearch_response(
        "无人机 蜂群",
        {
            "results": [
                {"title": "无的拼音", "url": "https://example.org/noise"},
                {"title": "无人机蜂群", "description": "自主协同", "url": "https://example.org/paper"},
            ]
        },
        count=1,
    )
    assert [item["url"] for item in result["results"]] == ["https://example.org/paper"]


def test_public_endpoint_ignores_noise_and_tries_next_engine():
    noise = MagicMock(
        status_code=200,
        text="""
      <li class="b_algo"><h2><a href="https://val.qq.com">无畏契约</a></h2>
      <div class="b_caption"><p>无的拼音与字典</p></div></li>""",
    )
    relevant = MagicMock(
        status_code=200,
        text="""
      <div class="result"><a class="result__a" href="https://example.org/uav">无人机蜂群研究</a>
      <div class="result__snippet">自主协同试验</div></div>""",
    )
    with patch("httpx.Client.get", side_effect=[noise, relevant]) as get:
        result = _create_public_search().invoke({"query": "无人机 蜂群", "count": 1})
    assert get.call_count == 2
    assert result["search_endpoint"] == "duckduckgo"
    assert [item["url"] for item in result["results"]] == ["https://example.org/uav"]


def test_all_irrelevant_results_are_empty_and_do_not_open_provider_circuit(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["public"])
    noise = MagicMock(
        status_code=200,
        text="""
      <li class="b_algo"><h2><a href="https://val.qq.com">无畏契约</a></h2>
      <div class="b_caption"><p>无的拼音</p></div></li>""",
    )
    with patch("httpx.Client.get", return_value=noise):
        result = _resilient_web_search("public", {"query": "无人机 蜂群"})
    assert result["status"] == "empty"
    assert result["results"] == []
    assert "error" not in result
    assert search_module._WEB_SEARCH_PROVIDER_HEALTH["public"]["failures"] == 0


def test_public_site_restriction_is_enforced_when_engine_ignores_it():
    result = _parse_public_search_response(
        "radar",
        """<div class="result"><a class="result__a" href="https://ads.example/radar">radar</a></div>""",
        count=5,
        sites=["ieee.org"],
    )
    assert result["results"] == []


def test_rate_limit_fails_over_without_immediate_retry_or_permanent_circuit(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["open-websearch", "tavily"])
    invoke = MagicMock(
        side_effect=[
            {"status": "rate_limited", "results": [], "retry_after_seconds": 120},
            {"results": [{"title": "radar drone evidence", "url": "https://example.org/paper"}]},
        ]
    )
    monkeypatch.setattr(search_module, "_invoke_search_provider", invoke)
    result = _resilient_web_search("open-websearch", {"query": "radar drone"})
    assert result["status"] == "ok"
    assert invoke.call_count == 2
    assert "open-websearch" not in search_module._WEB_SEARCH_PROVIDER_HEALTH


def test_all_rate_limited_providers_remain_temporary(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["open-websearch"])
    monkeypatch.setattr(
        search_module,
        "_invoke_search_provider",
        lambda *_: {
            "status": "rate_limited",
            "results": [],
            "retry_after_seconds": 120,
        },
    )
    result = _resilient_web_search("open-websearch", {"query": "radar drone"})
    assert result["status"] == "rate_limited"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 120
    assert "open-websearch" not in search_module._WEB_SEARCH_PROVIDER_HEALTH


def test_local_cache_does_not_charge_original_request_queue_wait(monkeypatch):
    _reset_web_search_runtime_state()
    monkeypatch.setattr(search_module, "_web_search_provider_order", lambda _: ["public"])
    invoke = MagicMock(
        return_value={
            "results": [{"title": "radar drone evidence", "url": "https://example.org/paper"}],
            "queue_wait_seconds": 15.0,
        }
    )
    monkeypatch.setattr(search_module, "_invoke_search_provider", invoke)
    assert _resilient_web_search("public", {"query": "radar drone"})["queue_wait_seconds"] == 15
    cached = _resilient_web_search("public", {"query": "radar drone"})
    assert cached["cache_hit"] is True
    assert cached["queue_wait_seconds"] == 0
    assert invoke.call_count == 1
