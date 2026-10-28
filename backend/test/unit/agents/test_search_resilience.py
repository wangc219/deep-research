import json
from types import SimpleNamespace

import pytest

from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool

from platform_core.agents.middlewares.search_resilience import SearchResilienceMiddleware


def test_explicit_paper_evidence_request_requires_first_search_once():
    """论文取证请求先调用检索；已有结果后允许正常分析和交付。"""
    middleware = SearchResilienceMiddleware()
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[HumanMessage(content="请基于论文摘要比较 RAG 与长上下文，给出来源链接。")],
    )
    assert middleware._prepare_model_request(request).tool_choice == "academic_search"
    assert middleware._prepare_model_request(request).tool_choice is None
    with_evidence = request.override(
        messages=[*request.messages, ToolMessage(content="evidence", name="academic_search", tool_call_id="s")]
    )
    assert SearchResilienceMiddleware()._prepare_model_request(with_evidence).tool_choice is None


@pytest.mark.parametrize(
    "query",
    [
        "请解释 RAG",
        "无需检索论文，分析已给摘要",
        "请检索论文，本轮仅使用网页",
        "请检索论文，不使用 AMiner 或 academic 工具",
    ],
)
def test_first_search_guard_respects_scope_and_opt_out(query):
    request = ModelRequest(
        model=SimpleNamespace(), tools=[SimpleNamespace(name="academic_search")], messages=[HumanMessage(content=query)]
    )
    assert SearchResilienceMiddleware()._prepare_model_request(request).tool_choice is None


def test_first_search_guard_does_not_restore_blocked_academic_tool():
    middleware = SearchResilienceMiddleware()
    middleware.blocked_academic_tools.add("academic_search")
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[HumanMessage(content="请检索论文摘要并给出来源链接")],
    )
    prepared = middleware._prepare_model_request(request)
    assert prepared.tools == [] and prepared.tool_choice is None


def test_research_explorer_technical_subproblem_uses_aminer_first():
    middleware = SearchResilienceMiddleware(research_mode=True)
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="web_search"), SimpleNamespace(name="academic_search")],
        messages=[HumanMessage(content="核验稀疏阵列雷达的作用机理与工程可行性，为主智能体判断提供证据。")],
    )
    assert middleware._prepare_model_request(request).tool_choice == "academic_search"
    assert middleware._prepare_model_request(request).tool_choice is None


def test_research_explorer_technical_subproblem_respects_aminer_opt_out():
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[HumanMessage(content="仅使用网页核验雷达技术路线，不使用 AMiner。")],
    )
    assert SearchResilienceMiddleware(research_mode=True)._prepare_model_request(request).tool_choice is None


def test_ordinary_chat_technical_question_does_not_force_aminer():
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[HumanMessage(content="解释雷达技术原理。")],
    )
    assert SearchResilienceMiddleware()._prepare_model_request(request).tool_choice is None


def _search_request(query):
    """构建一次可区分的搜索调用。"""
    return SimpleNamespace(
        tool_call={"id": query, "name": "web_search", "args": {"query": query, "required_terms": ["drone"]}}
    )


def _sources(*indexes):
    """模拟带标题、摘要和原始链接的检索协议。"""
    return {
        "status": "ok",
        "results": [
            {
                "url": f"https://source{index}.org/paper",
                "title": f"paper {index}",
                "content": "abstract",
                "source_tier": "authoritative" if index < 2 else "other",
            }
            for index in indexes
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_explorer_does_not_stop_on_twelve_sources(use_async):
    """网页资料充足时停止网页，仍允许其他渠道补证，同步与异步一致。"""
    middleware = SearchResilienceMiddleware(research_mode=True)

    async def async_handler(request):
        index = int(request.tool_call["id"].rsplit("-", 1)[-1])
        return ToolMessage(
            content=json.dumps(_sources(index * 2, index * 2 + 1)),
            tool_call_id=request.tool_call["id"],
        )

    def handler(request):
        index = int(request.tool_call["id"].rsplit("-", 1)[-1])
        return ToolMessage(
            content=json.dumps(_sources(index * 2, index * 2 + 1)),
            tool_call_id=request.tool_call["id"],
        )

    for query in [f"search-{index}" for index in range(6)]:
        if use_async:
            await middleware.awrap_tool_call(_search_request(query), async_handler)
        else:
            middleware.wrap_tool_call(_search_request(query), handler)
    assert len(middleware.research_sources) == 12
    request = ModelRequest(model=SimpleNamespace(), messages=[], tools=[SimpleNamespace(name="web_search")])
    prepared = middleware._prepare_model_request(request)
    assert [tool.name for tool in prepared.tools] == ["web_search"]
    assert "不因来源总数达到 12 条就自动停止" in str(prepared.system_message.content)
    assert not middleware.research_web_stop_reason


def test_explorer_counts_deduplicated_sources_and_stops_on_no_progress():
    middleware = SearchResilienceMiddleware(research_mode=True)
    for query in ["first", "second", "third", "fourth"]:
        middleware.wrap_tool_call(_search_request(query), lambda _: _sources(1, 1))
    assert len(middleware.research_sources) == 1
    assert "无新增" in middleware.research_web_stop_reason
    assert not middleware.research_stop_reason
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[],
        tools=[
            SimpleNamespace(name=name)
            for name in ("web_search", "academic_get_papers", "query_kbs", "open_kb_document")
        ],
    )
    assert [tool.name for tool in middleware._prepare_model_request(request).tools] == [
        "academic_get_papers",
        "query_kbs",
        "open_kb_document",
    ]
    kb_request = SimpleNamespace(tool_call={"id": "kb", "name": "query_kbs", "args": {"query_text": "具体缺口"}})
    assert middleware.wrap_tool_call(kb_request, lambda _: "local evidence") == "local evidence"


def test_explorer_keeps_search_available_until_authoritative_source_floor_is_met():
    middleware = SearchResilienceMiddleware(research_mode=True)
    for query in ["first", "second"]:
        payload = _sources(*range(8))
        for item in payload["results"]:
            item["source_tier"] = "other"
        middleware.wrap_tool_call(_search_request(query), lambda _, payload=payload: payload)
    prepared = middleware._prepare_model_request(
        ModelRequest(model=SimpleNamespace(), messages=[], tools=[SimpleNamespace(name="web_search")])
    )
    assert [tool.name for tool in prepared.tools] == ["web_search"]


def test_explorer_removes_todo_tool_from_research_loop():
    middleware = SearchResilienceMiddleware(research_mode=True)
    prepared = middleware._prepare_model_request(
        ModelRequest(
            model=SimpleNamespace(),
            messages=[],
            tools=[SimpleNamespace(name="web_search"), SimpleNamespace(name="write_todos")],
        )
    )
    assert [tool.name for tool in prepared.tools] == ["web_search"]


def test_explorer_rejects_unanchored_web_search_without_charging_budget():
    middleware = SearchResilienceMiddleware(research_mode=True)
    request = SimpleNamespace(tool_call={"id": "search", "name": "web_search", "args": {"query": "drone swarm"}})
    executed = []
    result = middleware.wrap_tool_call(request, lambda _: executed.append(True))
    assert "missing_required_terms" in result.content
    assert middleware.research_web_calls == 0
    assert executed == []


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
    for index in range(48):
        request.tool_call["args"] = {"query": str(index)}
        middleware.wrap_tool_call(request, lambda _: "knowledge")
    prepared = middleware._prepare_model_request(ModelRequest(model=SimpleNamespace(), messages=[], tools=[]))
    assert "48 次" in str(prepared.system_message.content)
    assert "delivery_required" in middleware.wrap_tool_call(request, lambda _: pytest.fail("budget bypass")).content


def test_explorer_channel_budgets_stop_parallel_batches_before_execution():
    """渠道次数在工具执行前预占，单批并行也不能冲过受控检索边界。"""
    web = SearchResilienceMiddleware(research_mode=True)
    executed_web = []
    for index in range(24):
        web.wrap_tool_call(
            _search_request(f"web-{index}"),
            lambda request: executed_web.append(request.tool_call["id"]) or "unparsed result",
        )
    denied_web = web.wrap_tool_call(_search_request("web-24"), lambda _: pytest.fail("web budget bypass"))
    assert len(executed_web) == 24
    assert "tool_budget_reached" in denied_web.content

    academic = SearchResilienceMiddleware(research_mode=True)
    executed_academic = []

    def academic_request(call_id, name="academic_search", **args):
        return SimpleNamespace(tool_call={"id": call_id, "name": name, "args": args})

    for index in range(8):
        academic.wrap_tool_call(
            academic_request(f"topic-{index}", query=f"topic {index}", mode="semantic"),
            lambda request: executed_academic.append(request.tool_call["id"]) or '{"status":"ok","results":[]}',
        )
    denied_topic = academic.wrap_tool_call(
        academic_request("topic-8", query="topic 8"), lambda _: pytest.fail("topic budget bypass")
    )
    for index in range(3):
        academic.wrap_tool_call(
            academic_request(f"title-{index}", query=f"Exact Paper Title {index}", mode="title"),
            lambda request: executed_academic.append(request.tool_call["id"]) or '{"status":"ok","results":[]}',
        )
        academic.wrap_tool_call(
            academic_request(f"detail-{index}", "academic_get_papers", paper_ids=[f"p{index}"]),
            lambda request: executed_academic.append(request.tool_call["id"]) or '{"status":"ok"}',
        )
    denied_title = academic.wrap_tool_call(
        academic_request("title-4", query="Another Title", mode="title"), lambda _: pytest.fail("title budget bypass")
    )
    denied_detail = academic.wrap_tool_call(
        academic_request("detail-4", "academic_get_papers", paper_ids=["p4"]),
        lambda _: pytest.fail("detail budget bypass"),
    )
    assert len(executed_academic) == 14
    assert all("tool_budget_reached" in item.content for item in (denied_topic, denied_title, denied_detail))


def test_explorer_allows_two_evidence_tools_per_model_batch_and_rejects_third():
    middleware = SearchResilienceMiddleware(research_mode=True)
    calls = [
        {"id": "one", "name": "web_search", "args": {"query": "one", "required_terms": ["one"]}},
        {"id": "two", "name": "academic_search", "args": {"query": "two"}},
        {"id": "three", "name": "web_search", "args": {"query": "three", "required_terms": ["three"]}},
    ]
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}
    executed = []

    def request(call):
        return SimpleNamespace(tool_call=call, state=state)

    for call in calls[:2]:
        middleware.wrap_tool_call(
            request(call),
            lambda item: executed.append(item.tool_call["id"]) or '{"status":"ok","results":[]}',
        )
    denied = middleware.wrap_tool_call(request(calls[2]), lambda _: pytest.fail("batch limit bypass"))

    assert executed == ["one", "two"]
    assert "tool_batch_limit" in denied.content


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_explorer_recovers_serialized_dsml_tool_markup(use_async):
    """模型把工具协议写进正文时通过可审计 state 纠错，而不在 wrapper 内隐藏重试。"""
    middleware = SearchResilienceMiddleware(research_mode=True)
    state = {"messages": [AIMessage(content='<｜DSML｜tool_calls><｜DSML｜invoke name="web_search">')]}
    result = (
        await middleware.aafter_model(state, SimpleNamespace())
        if use_async
        else middleware.after_model(state, SimpleNamespace())
    )
    assert result["jump_to"] == "model"
    assert "工具协议纠错" in result["messages"][0].content

    second = middleware.after_model(state, SimpleNamespace())
    assert "最终收敛" in second["messages"][0].content
    prepared = middleware._prepare_model_request(
        ModelRequest(model=SimpleNamespace(), messages=[], tools=[SimpleNamespace(name="web_search")])
    )
    assert prepared.tools == []


def test_explorer_model_thinking_time_does_not_consume_active_tool_budget(monkeypatch):
    middleware = SearchResilienceMiddleware(research_mode=True)
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 10)
    middleware.wrap_tool_call(_search_request("first"), lambda _: _sources(1))
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 131)
    result = middleware.wrap_tool_call(_search_request("second"), lambda _: _sources(2))
    assert result == _sources(2)
    assert not middleware.research_stop_reason


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


def test_tool_execution_budget_and_wall_time_are_bounded_independently(monkeypatch):
    middleware = SearchResilienceMiddleware(research_mode=True)
    middleware.research_started_at = 0
    middleware.research_tool_seconds = 479
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 800)
    middleware._check_research_deadline()
    assert not middleware.research_stop_reason
    middleware.research_tool_seconds = 480
    middleware._check_research_deadline()
    assert "480 秒" in middleware.research_stop_reason

    wall = SearchResilienceMiddleware(research_mode=True)
    wall.research_started_at = 0
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: 1801)
    wall._check_research_deadline()
    assert "1800 秒" in wall.research_stop_reason


def test_active_budget_counts_retrieval_execution_but_not_queue_or_other_tools(monkeypatch):
    middleware = SearchResilienceMiddleware(research_mode=True)
    now = [10.0]
    monkeypatch.setattr("platform_core.agents.middlewares.search_resilience.time.monotonic", lambda: now[0])

    def search_handler(_):
        now[0] = 15.0
        return {**_sources(1), "queue_wait_seconds": 2}

    middleware.wrap_tool_call(_search_request("timed"), search_handler)
    assert middleware.research_tool_seconds == pytest.approx(3.0)

    other = SimpleNamespace(tool_call={"id": "todo", "name": "write_todos", "args": {}}, state={})

    def other_handler(_):
        now[0] = 25.0
        return "done"

    middleware.wrap_tool_call(other, other_handler)
    assert middleware.research_tool_seconds == pytest.approx(3.0)


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
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": str(round_number), "required_terms": ["drone"]},
                        "id": f"call-{round_number}",
                    }
                ],
            )
        else:
            message = AIMessage(content="已交付已有资料及证据缺口。")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_explorer_graph_exits_search_loop_and_returns_final_result():
    """通过真实 LangGraph 工具循环验证阈值移除工具后正常交付。"""
    executed = []

    def search(query: str, required_terms: list[str] | None = None):
        del required_terms
        executed.append(query)
        index = int(query) - 1
        return _sources(index * 2, index * 2 + 1)

    graph = create_agent(
        model=_SearchUntilToolsRemovedModel(),
        tools=[StructuredTool.from_function(name="web_search", description="网页检索", func=search)],
        middleware=[SearchResilienceMiddleware(research_mode=True)],
    )
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "调研子问题"}]}, config={"recursion_limit": 100}
    )
    assert executed == [str(index) for index in range(1, 25)]
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


def test_free_metadata_limit_keeps_topic_search_and_details_available():
    """免费题录耗尽不能误伤仍有额度的 Pro 搜索和论文详情。"""
    middleware = SearchResilienceMiddleware()
    middleware.wrap_tool_call(
        SimpleNamespace(tool_call={"id": "search", "name": "academic_search"}),
        lambda _: ToolMessage(
            content='{"status":"partial","aminer_status":"limit_reached","failed_endpoint":"info"}',
            tool_call_id="search",
        ),
    )
    assert not middleware.blocked_academic_tools


def test_explorer_uses_authorized_local_evidence_then_aminer():
    middleware = SearchResilienceMiddleware(research_mode=True)
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name=name) for name in ("query_kbs", "academic_search", "web_search")],
        messages=[HumanMessage(content="核验材料的工程可行性，融合三源证据")],
    )
    assert middleware._prepare_model_request(request).tool_choice == "query_kbs"
    request = request.override(
        messages=[
            *request.messages,
            ToolMessage(content="local constraints and public paper title", name="query_kbs", tool_call_id="kb"),
        ]
    )
    assert middleware._prepare_model_request(request).tool_choice == "academic_search"
    assert middleware._prepare_model_request(request).tool_choice is None


def test_explorer_does_not_skip_aminer_because_web_was_searched():
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[
            HumanMessage(content="核验材料的工程可行性"),
            ToolMessage(content="web evidence", name="web_search", tool_call_id="web"),
        ],
    )
    assert (
        SearchResilienceMiddleware(research_mode=True)._prepare_model_request(request).tool_choice == "academic_search"
    )


@pytest.mark.parametrize(
    "research_mode,query",
    [
        (False, "核验材料的工程可行性"),
        (True, "仅分析已有知识库摘录，无需检索"),
        (True, "本轮仅使用网页"),
        (True, "不要使用知识库"),
    ],
)
def test_local_evidence_guard_respects_scope(research_mode, query):
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="query_kbs")],
        messages=[HumanMessage(content=query)],
    )
    assert SearchResilienceMiddleware(research_mode=research_mode)._prepare_model_request(request).tool_choice is None


def test_restored_local_tool_result_is_not_searched_again():
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="query_kbs")],
        messages=[
            HumanMessage(content="使用已启用知识库补证"),
            ToolMessage(content="local evidence", name="query_kbs", tool_call_id="kb"),
        ],
    )
    assert SearchResilienceMiddleware(research_mode=True)._prepare_model_request(request).tool_choice is None


@pytest.mark.parametrize(
    "question",
    [
        "围绕长序列推理显存瓶颈比较两条解决路径，结合公开证据。",
        "比较两类算法的性能边界，给出研究依据。",
        "技术方案需要论文证据，先核对已有研究。",
    ],
)
def test_technical_evidence_request_cannot_skip_all_retrieval(question):
    """主智能体也必须实际取证，不能把用户要求的证据替换成模型记忆。"""
    request = ModelRequest(
        model=SimpleNamespace(), tools=[SimpleNamespace(name="academic_search")], messages=[HumanMessage(question)]
    )
    prepared = SearchResilienceMiddleware().wrap_model_call(request, lambda value: value)
    assert prepared.tool_choice == "academic_search"


@pytest.mark.parametrize("optout", ["不需要论文", "无需论文", "仅使用网页", "do not search papers"])
def test_explicit_optout_overrides_technical_evidence_request(optout):
    """用户限制检索渠道时不得因证据规则强制调用学术工具。"""
    request = ModelRequest(
        model=SimpleNamespace(),
        tools=[SimpleNamespace(name="academic_search")],
        messages=[HumanMessage("比较算法性能并说明证据，" + optout)],
    )
    prepared = SearchResilienceMiddleware().wrap_model_call(request, lambda value: value)
    assert prepared.tool_choice is None
