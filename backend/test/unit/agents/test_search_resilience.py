import json
from types import SimpleNamespace

import pytest

from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool

from platform_core.agents.middlewares.search_resilience import SearchResilienceMiddleware


def _search_request(query):
    """构建一次可区分的搜索调用。"""
    return SimpleNamespace(tool_call={"id": query, "name": "web_search", "args": {"query": query}})


def _sources(*indexes):
    """模拟带标题、摘要和原始链接的检索协议。"""
    return {
        "status": "ok",
        "results": [
            {"url": f"https://source{index}.org/paper", "title": f"paper {index}", "content": "abstract"}
            for index in indexes
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_explorer_reaches_source_threshold_and_blocks_further_tools(use_async):
    """达到整理阈值后进入成稿，同步与异步执行规则一致。"""
    middleware = SearchResilienceMiddleware(research_mode=True)

    async def async_handler(request):
        return ToolMessage(
            content=json.dumps(_sources(*range(4 if request.tool_call["id"] == "first" else 8))),
            tool_call_id=request.tool_call["id"],
        )

    def handler(request):
        return ToolMessage(
            content=json.dumps(_sources(*range(4 if request.tool_call["id"] == "first" else 8))),
            tool_call_id=request.tool_call["id"],
        )

    for query in ["first", "second"]:
        if use_async:
            await middleware.awrap_tool_call(_search_request(query), async_handler)
        else:
            middleware.wrap_tool_call(_search_request(query), handler)
    assert len(middleware.research_sources) == 8
    request = ModelRequest(model=SimpleNamespace(), messages=[], tools=[SimpleNamespace(name="web_search")])
    prepared = middleware._prepare_model_request(request)
    assert prepared.tools == []
    assert "资料整理阈值" in str(prepared.system_message.content)
    assert "不代表事实已证实" in str(prepared.system_message.content)
    executed = []
    denial = middleware.wrap_tool_call(_search_request("third"), lambda _: executed.append(True))
    assert "delivery_required" in denial.content
    assert executed == []


def test_explorer_counts_deduplicated_sources_and_stops_on_no_progress():
    middleware = SearchResilienceMiddleware(research_mode=True)
    for query in ["first", "second", "third"]:
        middleware.wrap_tool_call(_search_request(query), lambda _: _sources(1, 1))
    assert len(middleware.research_sources) == 1
    assert "无新增" in middleware.research_stop_reason


def test_explorer_intercepts_repeated_query_without_searching_again():
    middleware = SearchResilienceMiddleware(research_mode=True)
    executed = []

    def handler(_):
        executed.append(True)
        return _sources(1)

    middleware.wrap_tool_call(_search_request("RADAR   drone"), handler)
    for _ in range(2):
        denial = middleware.wrap_tool_call(_search_request("radar drone"), handler)
        assert "重复查询" in denial.content
    assert executed == [True]
    assert middleware.research_stop_reason


def test_explorer_total_budget_prevents_switching_to_another_tool_forever():
    middleware = SearchResilienceMiddleware(research_mode=True)
    request = SimpleNamespace(tool_call={"id": "kb", "name": "query_kbs", "args": {}})
    for index in range(12):
        request.tool_call["args"] = {"query": str(index)}
        middleware.wrap_tool_call(request, lambda _: "knowledge")
    prepared = middleware._prepare_model_request(ModelRequest(model=SimpleNamespace(), messages=[], tools=[]))
    assert "12 次" in str(prepared.system_message.content)
    assert "delivery_required" in middleware.wrap_tool_call(request, lambda _: pytest.fail("budget bypass")).content


def test_explorer_deadline_stops_before_next_tool(monkeypatch):
    middleware = SearchResilienceMiddleware(research_mode=True)
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 10)
    middleware.wrap_tool_call(_search_request("first"), lambda _: _sources(1))
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 131)
    denial = middleware.wrap_tool_call(_search_request("second"), lambda _: pytest.fail("deadline bypass"))
    assert "120 秒" in denial.content


def test_ordinary_chat_does_not_use_explorer_source_threshold():
    middleware = SearchResilienceMiddleware()
    for query in ["first", "second"]:
        middleware.wrap_tool_call(_search_request(query), lambda _: _sources(*range(10)))
    assert not middleware.research_stop_reason
    assert not middleware.search_blocked


def test_temporary_rate_limit_does_not_permanently_disable_web_search():
    middleware = SearchResilienceMiddleware(research_mode=True)
    middleware.wrap_tool_call(_search_request("first"), lambda _: {"status": "rate_limited", "results": []})
    assert not middleware.search_blocked
    middleware.wrap_tool_call(_search_request("second"), lambda _: _sources(1, 2, 3, 4))
    assert len(middleware.research_sources) == 4
    assert not middleware.search_blocked


def test_queue_wait_does_not_consume_active_research_budget_but_wall_time_remains_bounded(monkeypatch):
    middleware = SearchResilienceMiddleware(research_mode=True)
    middleware.research_started_at = 0
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 170)
    middleware._record_research_result(_search_request("one"), {**_sources(1), "queue_wait_seconds": 60})
    middleware._check_research_deadline()
    assert not middleware.research_stop_reason
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 250)
    middleware.research_queue_wait_seconds = 180
    middleware._check_research_deadline()
    assert "240 秒" in middleware.research_stop_reason


class _SearchUntilToolsRemovedModel(BaseChatModel):
    """模拟只要工具可见就持续搜索的模型，验证执行图能进入最终输出。"""

    tools_enabled: bool = False

    @property
    def _llm_type(self):
        return "search-until-delivery"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools_enabled": bool(tools)})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        round_number = sum(isinstance(message, ToolMessage) for message in messages) + 1
        if self.tools_enabled:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "web_search", "args": {"query": str(round_number)}, "id": f"call-{round_number}"}],
            )
        else:
            message = AIMessage(content="已交付已有资料及证据缺口。")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_explorer_graph_exits_search_loop_and_returns_final_result():
    """通过真实 LangGraph 工具循环验证阈值移除工具后正常交付。"""
    executed = []

    def search(query: str):
        executed.append(query)
        return _sources(*range(4 if query == "1" else 8))

    graph = create_agent(
        model=_SearchUntilToolsRemovedModel(),
        tools=[StructuredTool.from_function(name="web_search", description="网页检索", func=search)],
        middleware=[SearchResilienceMiddleware(research_mode=True)],
    )
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "调研子问题"}]}, config={"recursion_limit": 8}
    )
    assert executed == ["1", "2"]
    assert result["messages"][-1].content == "已交付已有资料及证据缺口。"
    assert not result["messages"][-1].tool_calls


def test_degraded_search_removes_tool_and_injects_hard_stop_prompt():
    middleware = SearchResilienceMiddleware(max_calls=8)
    tool_request = SimpleNamespace(tool_call={"id": "search-1", "name": "web_search"})

    result = middleware.wrap_tool_call(
        tool_request,
        lambda _request: ToolMessage(
            content='{"status":"degraded","next_action":"本次子任务不要再次调用 web_search"}',
            tool_call_id="search-1",
            name="web_search",
        ),
    )

    assert result.name == "web_search"
    assert middleware.search_degraded is True
    seen = {}
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[],
        tools=[SimpleNamespace(name="web_search"), SimpleNamespace(name="query_kbs")],
    )

    def handler(prepared):
        seen["request"] = prepared
        return ModelResponse(result=[AIMessage(content="done")])

    response = middleware.wrap_model_call(request, handler)

    assert response.result[0].content == "done"
    assert [tool.name for tool in seen["request"].tools] == ["query_kbs"]
    assert "必须立即停止重试" in str(seen["request"].system_message.content)


def test_search_budget_rejects_extra_tool_execution():
    middleware = SearchResilienceMiddleware(max_calls=1)
    first_request = SimpleNamespace(tool_call={"id": "search-1", "name": "web_search"})
    middleware.wrap_tool_call(
        first_request,
        lambda _request: ToolMessage(
            content='{"status":"ok","results":[{"url":"https://example.org"}]}',
            tool_call_id="search-1",
            name="web_search",
        ),
    )
    called = False

    def must_not_run(_request):
        nonlocal called
        called = True

    blocked = middleware.wrap_tool_call(
        SimpleNamespace(tool_call={"id": "search-2", "name": "web_search"}),
        must_not_run,
    )

    assert called is False
    assert blocked.status == "error"
    assert "已在本轮熔断" in blocked.content


def test_academic_degradation_and_web_degradation_are_independent():
    """任一检索渠道故障时保留另一个渠道。"""
    middleware = SearchResilienceMiddleware()
    request = SimpleNamespace(tool_call={"id": "academic-1", "name": "academic_search"})
    middleware.wrap_tool_call(
        request,
        lambda _: ToolMessage(content='{"status":"partial","aminer_status":"auth_failed"}', tool_call_id="academic-1"),
    )
    assert "academic_get_papers" in middleware.blocked_academic_tools
    assert middleware.search_blocked is False
    other = SearchResilienceMiddleware()
    other.wrap_tool_call(
        SimpleNamespace(tool_call={"id": "web", "name": "web_search"}),
        lambda _: ToolMessage(content='{"status":"degraded"}', tool_call_id="web"),
    )
    assert other.search_blocked
    assert not other.blocked_academic_tools


def test_academic_endpoint_limit_only_blocks_its_tool():
    """详情限额耗尽仍允许发现论文。"""
    middleware = SearchResilienceMiddleware()
    middleware.wrap_tool_call(
        SimpleNamespace(tool_call={"id": "detail", "name": "academic_get_papers"}),
        lambda _: ToolMessage(content='{"status":"partial","aminer_status":"limit_reached"}', tool_call_id="detail"),
    )
    assert middleware.blocked_academic_tools == {"academic_get_papers"}
