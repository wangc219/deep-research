"""按需披露 MCP 工具定义，并在调用时绑定真实执行器。"""

import asyncio
from collections.abc import Callable
from typing import Annotated, NotRequired

from deepagents.middleware._utils import append_to_system_message
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from platform_core.agents.mcp.service import get_enabled_mcp_tools
from platform_core.agents.skills.runtime import resolve_skill_gated_tools
from platform_core.utils.logging_config import logger


async def load_available_mcp_tools(slug: str) -> list:
    """记录可选服务故障，保留其他能力的运行机会。"""
    try:
        return await get_enabled_mcp_tools(slug)
    except Exception as exc:
        logger.warning(f"MCP 按需加载失败: server={slug}, error={type(exc).__name__}")
        return []


def merge_mcp_servers(left: list[str] | None, right: list[str] | None) -> list[str]:
    """合并并行工具调用的服务激活状态。"""
    return list(dict.fromkeys([*(left or []), *(right or [])]))


class McpToolsState(AgentState):
    """记录当前会话已按需激活的 MCP 服务。"""

    activated_mcps: NotRequired[Annotated[list[str], merge_mcp_servers]]


class McpToolsMiddleware(AgentMiddleware):
    """初始仅提供服务索引，激活后才请求远程工具 Schema。"""

    state_schema = McpToolsState

    def __init__(self):
        async def load_mcp_tools(server_slug: str, runtime: ToolRuntime) -> Command:
            """加载当前 Agent 被授权使用的一个 MCP 服务及其工具定义。"""
            context = runtime.context
            if server_slug not in (getattr(context, "mcps", None) or []):
                message = ToolMessage(
                    content="MCP 不在当前授权范围内", tool_call_id=runtime.tool_call_id, status="error"
                )
                return Command(update={"messages": [message]})
            tools = await load_available_mcp_tools(server_slug)
            if not tools:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="MCP 暂不可用或没有已启用工具，请使用其他来源或报告此限制。",
                                tool_call_id=runtime.tool_call_id,
                                status="error",
                            )
                        ]
                    }
                )
            loaded = getattr(context, "_loaded_mcp_servers", {})
            loaded[server_slug] = tools
            context._loaded_mcp_servers = loaded
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="已加载工具：" + ", ".join(tool.name for tool in tools),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                    "activated_mcps": [server_slug],
                }
            )

        self.tools = [
            StructuredTool.from_function(
                coroutine=load_mcp_tools,
                name="load_mcp_tools",
                description=(
                    "按需加载已授权 MCP 服务的工具定义。先查看系统中的服务索引，"
                    "再传入 server_slug；下一轮可以直接调用服务工具。"
                ),
            )
        ]

    async def awrap_model_call(self, request, handler: Callable):
        """只为当前运行有权使用且已经激活的服务展开工具。"""
        context = request.runtime.context
        selected = set(getattr(context, "mcps", None) or [])
        activated = [slug for slug in (request.state.get("activated_mcps") or []) if slug in selected]
        loaded = getattr(context, "_loaded_mcp_servers", {})
        missing = [slug for slug in activated if slug not in loaded]
        if missing:
            results = await asyncio.gather(*(load_available_mcp_tools(slug) for slug in missing))
            loaded.update(zip(missing, results))
        context._loaded_mcp_servers = loaded
        tools = list(request.tools or [])
        by_name = {tool.name: tool for tool in tools}
        local_dependency_names = {tool.name for tool in resolve_skill_gated_tools(context)}
        active_tools = {}
        for slug in activated:
            for tool in loaded.get(slug, []):
                if tool.name in local_dependency_names:
                    raise RuntimeError(f"MCP 工具名冲突：{slug}/{tool.name} 与本地 Skill 工具同名")
                if tool.name in by_name and by_name[tool.name] is not tool:
                    raise RuntimeError(f"MCP 工具名冲突：{slug}/{tool.name}")
                if tool.name not in by_name:
                    tools.append(tool)
                    by_name[tool.name] = tool
                active_tools[tool.name] = tool
        context._active_lazy_mcp_tools = active_tools
        catalog = getattr(context, "_mcp_server_catalog", [])
        index = "\n".join(
            f"- {item['key']}: {item['name']} — {item['description']}" for item in catalog if item["key"] in selected
        )
        prompt = (
            "MCP 服务按需加载：需要外部能力时先调用 load_mcp_tools(server_slug)，随后调用其工具。可用服务：\n" + index
        )
        return await handler(
            request.override(
                tools=tools,
                system_message=append_to_system_message(request.system_message, prompt),
            )
        )

    async def awrap_tool_call(self, request, handler: Callable):
        """将动态工具调用绑定到当前轮已开放的真实执行器。"""
        if request.tool is None:
            tool = getattr(request.runtime.context, "_active_lazy_mcp_tools", {}).get(request.tool_call.get("name"))
            if tool is not None:
                request = request.override(tool=tool)
        return await handler(request)
