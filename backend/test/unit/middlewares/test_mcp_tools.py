"""MCP 工具按需披露的真实 Agent 图测试。"""

from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from platform_core.agents.context import BaseContext
from platform_core.agents.middlewares.mcp_tools import McpToolsMiddleware
from platform_core.agents.middlewares.skills import SkillsMiddleware
from platform_core.agents.toolkits.service import resolve_configured_runtime_tools


class ToolModel(FakeMessagesListChatModel):
    """记录每轮模型实际收到的工具定义。"""

    visible_tools: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        """仅记录 Schema，不改变测试响应。"""
        self.visible_tools.append([item.name for item in tools])
        return self


@pytest.mark.asyncio
async def test_remote_schema_is_lazy_and_dynamic_tool_reaches_executor(monkeypatch):
    """首轮无远程 Schema，激活后工具实际执行，且不会重复请求定义。"""

    @tool
    async def remote_echo(value: str) -> str:
        """返回远程标记。"""
        return "REMOTE:" + value

    loader = AsyncMock(return_value=[remote_echo])
    monkeypatch.setattr("platform_core.agents.middlewares.mcp_tools.get_enabled_mcp_tools", loader)
    model = ToolModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"id": "load", "name": "load_mcp_tools", "args": {"server_slug": "papers"}}]
            ),
            AIMessage(content="", tool_calls=[{"id": "call", "name": "remote_echo", "args": {"value": "verified"}}]),
            AIMessage(content="done"),
        ]
    )
    context = BaseContext(mcps=["papers"], tools=[], skills=[])
    context._mcp_server_catalog = [{"key": "papers", "name": "论文", "description": "论文查询"}]
    graph = create_agent(model, middleware=[McpToolsMiddleware()], context_schema=BaseContext)
    loader.assert_not_awaited()
    result = await graph.ainvoke({"messages": [HumanMessage(content="verify")]}, context=context)
    assert model.visible_tools[0] == ["load_mcp_tools"]
    assert "remote_echo" in model.visible_tools[1]
    assert any(
        isinstance(message, ToolMessage) and message.content == "REMOTE:verified" for message in result["messages"]
    )
    assert result["activated_mcps"] == ["papers"]
    loader.assert_awaited_once_with("papers")


@pytest.mark.asyncio
async def test_unauthorized_service_never_connects(monkeypatch):
    """显式越权调用也不得连接服务或持久化激活状态。"""
    loader = AsyncMock()
    monkeypatch.setattr("platform_core.agents.middlewares.mcp_tools.get_enabled_mcp_tools", loader)
    model = ToolModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"id": "load", "name": "load_mcp_tools", "args": {"server_slug": "private"}}]
            ),
            AIMessage(content="denied"),
        ]
    )
    graph = create_agent(model, middleware=[McpToolsMiddleware()], context_schema=BaseContext)
    result = await graph.ainvoke({"messages": [HumanMessage(content="verify")]}, context=BaseContext(mcps=["papers"]))
    loader.assert_not_awaited()
    assert not result.get("activated_mcps")
    assert any(isinstance(message, ToolMessage) and message.status == "error" for message in result["messages"])


@pytest.mark.asyncio
async def test_graph_configuration_does_not_eagerly_fetch_mcp_tools(monkeypatch):
    """通用工具装配必须保留按需语义。"""
    loader = AsyncMock()
    monkeypatch.setattr("platform_core.agents.mcp.service.get_enabled_mcp_tools", loader)
    await resolve_configured_runtime_tools(BaseContext(mcps=["papers"], tools=[], skills=[]))
    loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_preloaded_skill_can_use_an_explicitly_selected_lazy_mcp(monkeypatch):
    """Skill 预加载不能因服务同时出现在 MCP 配置中而丢失依赖。"""

    @tool
    async def remote_echo() -> str:
        """返回预加载依赖的执行结果。"""
        return "PRELOADED_REMOTE"

    loader = AsyncMock(return_value=[remote_echo])
    monkeypatch.setattr("platform_core.agents.middlewares.skills.get_enabled_mcp_tools", loader)
    model = ToolModel(
        responses=[
            AIMessage(content="", tool_calls=[{"id": "call", "name": "remote_echo", "args": {}}]),
            AIMessage(content="done"),
        ]
    )
    context = BaseContext(mcps=["papers"], skills=["research"], preload_skills=["research"], tools=[])
    context._skill_runtime_snapshot = {
        "effective_skills": ["research"],
        "preloaded_skills": ["research"],
        "preloaded_skill_contents": {"research": "Call the remote research tool."},
        "runtime_skills": {"research": {"name": "research", "tools": [], "mcps": ["papers"], "skills": []}},
    }
    graph = create_agent(model, middleware=[SkillsMiddleware(), McpToolsMiddleware()], context_schema=BaseContext)
    result = await graph.ainvoke({"messages": [HumanMessage(content="verify")]}, context=context)
    assert "remote_echo" in model.visible_tools[0]
    assert any(
        isinstance(message, ToolMessage) and message.content == "PRELOADED_REMOTE" for message in result["messages"]
    )


@pytest.mark.asyncio
async def test_lazy_mcp_cannot_shadow_an_unactivated_local_skill_tool():
    """隐藏工具仍在本地执行表中，必须在披露远程同名工具前拒绝冲突。"""
    context = BaseContext(mcps=["papers"], tools=[], skills=["kb"])
    context._loaded_mcp_servers = {"papers": [SimpleNamespace(name="query_kb")]}
    context._skill_runtime_snapshot = {
        "effective_skills": ["kb"],
        "runtime_skills": {"kb": {"tools": ["query_kb"]}},
    }
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tools=[], state={"activated_mcps": ["papers"]})
    with pytest.raises(RuntimeError, match="工具名冲突"):
        await McpToolsMiddleware().awrap_model_call(request, AsyncMock())
