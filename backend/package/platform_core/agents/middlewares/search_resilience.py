"""Bound web-search loops so research agents always reach a stop condition."""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage


_SEARCH_STOP_PROMPT = """# 公网检索熔断（本轮运行）
公网检索在本轮已经达到调用预算，或所有后端均已返回持续故障。`web_search` 已被运行时移除。
你必须立即停止重试、停止改写同义查询，也不要向用户输出“继续尝试/course”等过程性话语。
若 `query_kbs` 可用且尚未检索，最多调用一次做跨库检索；否则直接基于已获得来源、知识库结果和任务上下文完成当前子任务。
如证据仍不足，在结果中简洁标注具体证据缺口后结束；不得因检索故障阻止交付。"""


def _tool_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(getattr(value, "name", "") or "")


def _max_web_search_calls() -> int:
    try:
        value = int(os.getenv("WEB_SEARCH_MAX_CALLS_PER_RUN", "8"))
    except (TypeError, ValueError):
        value = 8
    return min(20, max(1, value))


def _result_text(result: Any) -> str:
    if isinstance(result, ToolMessage):
        content = result.content
    else:
        content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(content)


def _is_degraded_search_result(result: Any) -> bool:
    text = _result_text(result).casefold()
    return any(
        marker in text
        for marker in (
            '"status": "degraded"',
            '"status":"degraded"',
            "所有可用公网检索后端均暂不可用",
            "本次子任务不要再次调用 web_search",
        )
    )


class SearchResilienceMiddleware(AgentMiddleware[Any, Any, Any]):
    """Disable web search after terminal degradation or a bounded call budget.

    One middleware instance belongs to one graph/run, so counters do not leak
    into a later user turn while all subagents still receive the same policy.
    Provider retries/failover happen inside the web_search tool; this class
    prevents an LLM from turning a terminal degraded result into an unbounded
    LangGraph model/tool recursion.
    """

    def __init__(self, max_calls: int | None = None) -> None:
        self.max_calls = max_calls if max_calls is not None else _max_web_search_calls()
        self.web_search_calls = 0
        self.search_degraded = False

    @property
    def search_blocked(self) -> bool:
        return self.search_degraded or self.web_search_calls >= self.max_calls

    def _prepare_model_request(self, request: ModelRequest) -> ModelRequest:
        if not self.search_blocked:
            return request
        tools = [item for item in (request.tools or []) if _tool_name(item) != "web_search"]
        system_message = append_to_system_message(request.system_message, _SEARCH_STOP_PROMPT)
        return request.override(tools=tools, system_message=system_message)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._prepare_model_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._prepare_model_request(request))

    def _blocked_message(self, request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                "web_search 已在本轮熔断。不要重试或改写查询；请改用 query_kbs/已有来源完成任务，"
                "并标注证据缺口。"
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            name="web_search",
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]) -> Any:
        if _tool_name(request.tool_call) != "web_search":
            return handler(request)
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = handler(request)
        if _is_degraded_search_result(result):
            self.search_degraded = True
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        if _tool_name(request.tool_call) != "web_search":
            return await handler(request)
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = await handler(request)
        if _is_degraded_search_result(result):
            self.search_degraded = True
        return result

