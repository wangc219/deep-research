from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from platform_core.agents.middlewares.search_resilience import SearchResilienceMiddleware


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
