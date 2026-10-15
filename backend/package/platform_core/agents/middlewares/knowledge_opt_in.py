"""仅在当前用户输入显式提及知识库时开放检索。"""

import re

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

KNOWLEDGE_TOOL_NAMES = frozenset(
    {
        "list_kbs",
        "query_kb",
        "query_kbs",
        "find_kb_document",
        "open_kb_document",
        "get_mindmap",
        "search_file",
        "download_kb_file",
    }
)


def has_knowledge_mention(text: str) -> bool:
    """识别用户手写标记及输入框生成的知识库引用。"""
    return bool(re.search(r'@\s*知识库|@knowledge:(?:"(?:\\.|[^"\\])+"|[^\s"]+)', text))


def apply_knowledge_retrieval_policy(context, *, enabled: bool) -> None:
    """为本轮准备上下文，清除未显式启用的知识库技能与工具。"""
    context._knowledge_retrieval_enabled = enabled
    if enabled:
        rule = "本轮用户已显式 @知识库，可按需检索本轮授权范围内的知识库。"
    else:
        context.knowledges = []
        for field in ("skills", "preload_skills"):
            values = getattr(context, field, None)
            if isinstance(values, list):
                setattr(context, field, [value for value in values if value != "knowledge-base"])
        context.tools = [name for name in context.tools or [] if name not in KNOWLEDGE_TOOL_NAMES]
        rule = (
            "本轮用户未显式 @知识库，禁止检索、列举或读取知识库；"
            "公网或学术检索失败也不得自动转查知识库。使用已有来源完成任务并标注证据缺口。"
        )
    context.system_prompt = f"{context.system_prompt}\n\n# 本轮知识库检索规则\n{rule}"


class KnowledgeOptInMiddleware(AgentMiddleware):
    """同时过滤模型工具列表与实际调用，避免历史技能激活绕过本轮规则。"""

    def __init__(self, *, enabled: bool):
        self.enabled = enabled

    def _filter_request(self, request):
        """保留本轮允许模型使用的工具。"""
        if self.enabled:
            return request
        tools = [
            tool
            for tool in request.tools or []
            if (tool.get("name") if isinstance(tool, dict) else tool.name) not in KNOWLEDGE_TOOL_NAMES
        ]
        return request.override(tools=tools)

    def wrap_model_call(self, request, handler):
        return handler(self._filter_request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._filter_request(request))

    def _denial(self, request):
        """阻止未启用知识库时的显式工具调用。"""
        name = request.tool_call["name"]
        if self.enabled or name not in KNOWLEDGE_TOOL_NAMES:
            return None
        return ToolMessage(
            content="本轮用户未显式 @知识库，知识库工具不可用。请使用已有来源交付结果并标注证据缺口。",
            name=name,
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        denial = self._denial(request)
        return denial if denial is not None else handler(request)

    async def awrap_tool_call(self, request, handler):
        denial = self._denial(request)
        return denial if denial is not None else await handler(request)
