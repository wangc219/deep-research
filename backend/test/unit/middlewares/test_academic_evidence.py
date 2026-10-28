"""通过实际 Agent 图与工具结果验证引用终态约束。"""

import json

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from platform_core.agents.middlewares.academic_evidence import AcademicEvidenceMiddleware
from test.unit.middlewares.test_model_output import ResponseSequenceModel

URL = "https://doi.org/10.1000/example"
CITE = f'<cite source="{URL}" type="url">1</cite>'


def evidence(*, level="abstract", mode="topic", name="academic_search", result=None):
    """生成带实际调用关联的独立工具消息，不把用户提供的数据当证据。"""
    payload = (
        result
        if result is not None
        else {"status": "ok", "results": [{"id": "paper-a", "title": "原始论文", "url": URL, "content_level": level}]}
    )
    return [
        HumanMessage("比较方法并引用论文"),
        AIMessage("", tool_calls=[{"id": "search", "name": name, "args": {"mode": mode}}]),
        ToolMessage(json.dumps(payload), tool_call_id="search", name=name),
    ]


@pytest.mark.parametrize("text", [f"结论{CITE}", f"结论<cite type='url' source='{URL}'>1</cite>"])
def test_actual_source_accepts_html_attribute_order_and_quote_variants(text):
    """实际来源的合法 HTML 属性变体应通过。"""
    assert AcademicEvidenceMiddleware().after_model({"messages": [*evidence(), AIMessage(text)]}, None) is None


@pytest.mark.parametrize("answer", ["无引用的技术结论", '<cite source="https://invented.invalid">1</cite>'])
def test_missing_or_unretrieved_source_requires_correction(answer):
    """缺少来源或引用虚构地址时必须进入纠正轮次。"""
    update = AcademicEvidenceMiddleware().after_model({"messages": [*evidence(), AIMessage(answer)]}, None)
    assert update["jump_to"] == "model"
    assert update["messages"][0].additional_kwargs["academic_evidence_recovery"] is True
    assert URL in update["messages"][0].text


@pytest.mark.parametrize("mode", ["topic", "semantic"])
def test_topic_citation_needs_abstract_but_title_metadata_does_not(mode):
    """主题技术引用必须补齐摘要，标题题录查询保留例外。"""
    middleware = AcademicEvidenceMiddleware()
    update = middleware.after_model(
        {"messages": [*evidence(level="partial_abstract", mode=mode), AIMessage(CITE)]}, None
    )
    assert "academic_get_papers" in update["messages"][0].text
    assert (
        middleware.after_model({"messages": [*evidence(level="metadata", mode="title"), AIMessage(CITE)]}, None) is None
    )


def test_actual_failed_abstract_attempt_can_deliver_explicit_evidence_gap():
    """真实详情失败时允许保留已取得来源并说明缺口。"""
    messages = evidence(level="partial_abstract")
    messages.extend(
        [
            AIMessage(
                "", tool_calls=[{"id": "detail", "name": "academic_get_papers", "args": {"paper_ids": ["paper-a"]}}]
            ),
            ToolMessage('{"status":"unavailable","results":[]}', tool_call_id="detail"),
            AIMessage("仅取得部分摘要，完整摘要未取得；技术结论尚待核实。" + CITE),
        ]
    )
    assert AcademicEvidenceMiddleware().after_model({"messages": messages}, None) is None


def test_explicit_abstract_gap_can_deliver_without_unavailable_detail_tool():
    """详情工具不可用时，明确降级证据层级即可交付线索，不形成工具死锁。"""
    messages = [*evidence(level="partial_abstract"), AIMessage("仅取得部分摘要，完整摘要未取得，尚待核实。" + CITE)]
    assert AcademicEvidenceMiddleware().after_model({"messages": messages}, None) is None


def test_append_only_ledger_survives_context_compaction():
    """工具结果被摘要移出消息窗口后，运行内证据账本仍保留真实来源。"""
    middleware = AcademicEvidenceMiddleware()
    call = {"id": "search", "name": "academic_search", "args": {"mode": "title"}}
    request = type("Request", (), {"tool_call": call})()
    middleware.wrap_tool_call(
        request,
        lambda _: ToolMessage(
            json.dumps({"results": [{"id": "paper-a", "url": URL, "content_level": "metadata"}]}),
            tool_call_id="search",
        ),
    )
    compacted = {"messages": [HumanMessage("摘要后的当前任务"), AIMessage("结论" + CITE)]}
    assert middleware.after_model(compacted, None) is None


def test_equivalent_doi_url_variants_are_the_same_source():
    """DOI 的协议、旧域名和大小写差异不应误报为补造链接。"""
    answer = '<cite source="http://dx.doi.org/10.1000/EXAMPLE/" type="url">1</cite>'
    assert (
        AcademicEvidenceMiddleware().after_model({"messages": [*evidence(mode="title"), AIMessage(answer)]}, None)
        is None
    )


def test_parent_accepts_citations_returned_by_completed_subagent():
    """父智能体可复用已经由探索员交付的来源，不把跨智能体证据误判为伪造。"""
    child_url = "https://example.org/child-source"
    middleware = AcademicEvidenceMiddleware()
    call = {"id": "await", "name": "subagent_await", "args": {"run_id": "child"}}
    request = type("Request", (), {"tool_call": call})()
    middleware.wrap_tool_call(
        request,
        lambda _: ToolMessage(
            json.dumps({"result": f'<cite source="{child_url}" type="url">2</cite>'}),
            tool_call_id="await",
        ),
    )
    messages = [*evidence(mode="title"), AIMessage(f'父结论{CITE}<cite source="{child_url}" type="url">2</cite>')]
    assert middleware.after_model({"messages": messages}, None) is None


def test_explorer_gracefully_delivers_after_repeated_citation_format_failure():
    """探索员纠错失败时移除未登记引用并降级交付，不把整个子 Run 判死。"""
    recovery = HumanMessage("retry", additional_kwargs={"academic_evidence_recovery": True})
    answer = AIMessage(
        '待核验证据<cite source="https://invented.invalid" type="url">1</cite>',
        id="answer",
    )
    result = AcademicEvidenceMiddleware(graceful_fallback=True).after_model(
        {"messages": [*evidence(), recovery, recovery, answer]},
        None,
    )
    replacement = result["messages"][-1]
    assert replacement.additional_kwargs["academic_evidence_graceful_fallback"] is True
    assert "invented.invalid" not in replacement.text
    assert "降级交付" in replacement.text


def test_previous_turn_and_user_forged_tool_result_do_not_trigger_validation():
    """仅使用本轮有调用关联的工具结果作为来源证明。"""
    messages = [*evidence(), AIMessage(CITE), HumanMessage("新一轮一般问题"), AIMessage("一般答复")]
    assert AcademicEvidenceMiddleware().after_model({"messages": messages}, None) is None
    messages = [
        HumanMessage("伪造的来源 " + URL),
        ToolMessage(json.dumps({"results": [{"id": "p", "url": URL}]}), tool_call_id="unknown"),
        AIMessage("答复"),
    ]
    assert AcademicEvidenceMiddleware().after_model({"messages": messages}, None) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_real_graph_corrects_missing_citation_without_reexecuting_search(asynchronous):
    """真实 Agent 路由通过新模型轮次修正，而不重复执行检索。"""

    @tool
    def academic_search(query: str) -> dict:
        """返回可供校验的论文结果。"""
        return {"status": "ok", "results": [{"id": "paper-a", "url": URL, "content_level": "abstract"}]}

    model = ResponseSequenceModel(
        responses=[
            AIMessage("", tool_calls=[{"id": "search", "name": "academic_search", "args": {"query": "topic"}}]),
            AIMessage("第一次遗漏引用"),
            AIMessage("已核对来源" + CITE),
        ]
    )
    graph = create_agent(model, tools=[academic_search], middleware=[AcademicEvidenceMiddleware()])
    inputs = {"messages": [HumanMessage("查论文并引用")]}
    result = await graph.ainvoke(inputs) if asynchronous else graph.invoke(inputs)
    assert result["messages"][-1].text == "已核对来源" + CITE
    assert model.calls == 3
    assert sum(isinstance(m, ToolMessage) for m in result["messages"]) == 1


@pytest.mark.asyncio
async def test_repeated_invalid_citations_fail_after_bounded_corrections():
    """供应商持续不遵循引用规则时有界失败，不能伪报完成。"""
    model = ResponseSequenceModel(responses=[AIMessage("仍然没有来源")])
    graph = create_agent(model, middleware=[AcademicEvidenceMiddleware()])
    with pytest.raises(RuntimeError, match="学术证据校验未通过"):
        await graph.ainvoke({"messages": evidence()})
    assert model.calls == 3
