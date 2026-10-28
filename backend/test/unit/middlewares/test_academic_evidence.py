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
    update = middleware.after_model({"messages": [*evidence(level="partial_abstract", mode=mode), AIMessage(CITE)]}, None)
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
