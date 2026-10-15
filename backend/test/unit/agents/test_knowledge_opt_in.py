from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.agents.buildin.subagent.context import SubAgentContext
from platform_core.agents.middlewares.knowledge_opt_in import (
    KNOWLEDGE_TOOL_NAMES,
    KnowledgeOptInMiddleware,
    apply_knowledge_retrieval_policy,
    has_knowledge_mention,
)
from platform_core.services.agent_run_manifest_service import resolve_run_knowledge_opt_in
from platform_core.storage.postgres.models_business import AgentRun, Message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("调研光电技术", False),
        ("参考知识库内容", False),
        ("@file:知识库资料.pdf", False),
        ("@skill:knowledge-base 调研", False),
        ("@知识库 调研光电技术", True),
        ("@ 知识库 调研", True),
        ("@knowledge:kb-123 调研", True),
        ('@knowledge:"技术 资料库" 调研', True),
        ("@knowledge:", False),
        ('@knowledge:""', False),
    ],
)
def test_knowledge_mention(text, expected):
    assert has_knowledge_mention(text) is expected


def test_policy_removes_preloads_and_explicit_tools_but_preserves_other_sources():
    context = SubAgentContext(
        knowledges=["kb"],
        skills=["knowledge-base", "deep-research"],
        preload_skills=["knowledge-base"],
        tools=["web_search", "query_kbs", "academic_search"],
    )
    apply_knowledge_retrieval_policy(context, enabled=False)
    assert context.knowledges == []
    assert context.skills == ["deep-research"]
    assert context.preload_skills == []
    assert context.tools == ["web_search", "academic_search"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
async def test_gate_hides_and_blocks_all_kb_tools(enabled, use_async):
    middleware = KnowledgeOptInMiddleware(enabled=enabled)
    tools = [SimpleNamespace(name=name) for name in ["web_search", *KNOWLEDGE_TOOL_NAMES]]
    request = SimpleNamespace(tools=tools, override=lambda **kwargs: SimpleNamespace(**kwargs))
    seen = []

    def handler(req):
        seen.append(req)
        return "ok"

    async def async_handler(req):
        return handler(req)

    if use_async:
        await middleware.awrap_model_call(request, async_handler)
    else:
        middleware.wrap_model_call(request, handler)
    assert {tool.name for tool in seen.pop().tools} == ({tool.name for tool in tools} if enabled else {"web_search"})
    for name in KNOWLEDGE_TOOL_NAMES:
        call = SimpleNamespace(tool_call={"name": name, "id": name, "args": {}})
        result = (
            await middleware.awrap_tool_call(call, async_handler)
            if use_async
            else middleware.wrap_tool_call(call, handler)
        )
        if enabled:
            assert result == "ok"
            assert seen.pop() is call
        else:
            assert result.status == "error"
            assert result.tool_call_id == name
            assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected", [("调研", False), ("@知识库 调研", True)])
async def test_child_and_resume_follow_current_original_user_input(text, expected):
    root = SimpleNamespace(run_type="chat", uid="u", input_message_id=1)
    resumed = SimpleNamespace(run_type="resume", uid="u", created_by_run_id="root")
    child = SimpleNamespace(run_type="subagent", uid="u", created_by_run_id="resume", input_message_id=2)
    records = {
        (AgentRun, "root"): root,
        (AgentRun, "resume"): resumed,
        (Message, 1): SimpleNamespace(content=text),
        # 子任务描述不能自行开启本轮原始用户未开启的知识库。
        (Message, 2): SimpleNamespace(content="@知识库 搜索"),
    }
    db = SimpleNamespace(get=AsyncMock(side_effect=lambda model, key: records[(model, key)]))
    assert await resolve_run_knowledge_opt_in(child, db) is expected
    assert await resolve_run_knowledge_opt_in(resumed, db) is expected
    assert await resolve_run_knowledge_opt_in(root, db) is expected
    records[(Message, 1)].content = "继续调研"
    assert await resolve_run_knowledge_opt_in(root, db) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_agent_graph_tool_node_obeys_opt_in_even_if_model_emits_hidden_call(enabled):
    """真实 Agent 图中，模型发出隐藏调用时也不能执行检索。"""
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool

    executed = []

    @tool
    def query_kbs(query: str) -> str:
        """查询知识库。"""
        executed.append(query)
        return "found"

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = ToolModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "query_kbs", "id": "kb", "args": {"query": "技术"}}]),
            AIMessage(content="已完成"),
        ]
    )
    graph = create_agent(model=model, tools=[query_kbs], middleware=[KnowledgeOptInMiddleware(enabled=enabled)])
    result = await graph.ainvoke({"messages": [{"role": "user", "content": "调研技术"}]})
    assert executed == (["技术"] if enabled else [])
    assert result["messages"][-1].content == "已完成"
