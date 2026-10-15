"""Bound web-search loops so research agents always reach a stop condition."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from platform_core.services.aminer_client import ACADEMIC_TOOL_NAMES


_SEARCH_STOP_PROMPT = """# 公网检索熔断（本轮运行）
公网检索在本轮已经达到调用预算，或所有后端均已返回持续故障。`web_search` 已被运行时移除。
你必须立即停止重试 web_search 和同义改写，也不要向用户输出“继续尝试/course”等过程性话语。
学术工具可用时仍可使用 AMiner 补充论文证据；其配置、健康和预算独立于网页搜索。
仅本轮用户显式 @知识库且 `query_kbs` 可用、尚未检索时，最多调用一次做跨库检索；
否则直接基于已获得来源和任务上下文完成当前子任务。
如证据仍不足，在结果中简洁标注具体证据缺口后结束；不得因检索故障阻止交付。"""

_ACADEMIC_STOP_PROMPT = """# AMiner 检索降级（本轮运行）
已不可用或达到调用上限的学术工具已从本轮移除。停止对这些工具的重试、同义改写和等待。
继续使用仍可用的网页搜索、授权知识库或已有来源完成当前任务，必要时注明具体证据缺口。"""

_RESEARCH_DELIVERY_PROMPT = """# 调研探索员检索与交付规则
只围绕调用方的单个子问题检索，先明确最多三个需要证据的要点。每次查询使用实体名和技术/指标等少量关键词。
每轮先判断已有来源是否覆盖要点；已能回答就立即交付，不必用满预算。摘要只支持摘要中实际出现的论断。
只有明确证据缺口才继续检索，禁止重复相同查询或无目的更换同义词。
运行时按独立来源、无增量次数、工具调用与耗时控制检索。资料整理阈值不代表事实已证实。
停止后必须返回：关键发现及就近引用、来源列表、冲突与具体证据缺口；不要输出继续尝试的承诺。
每个分领域必须交付结构化报告，即使部分检索限流也不能只返回限流说明；按要点区分已核实发现与待核验缺口。
暂时限流已由工具内部共享排队和冷却恢复，不能推断本轮检索永久不可用；不得通过不断改写查询制造重试风暴。"""


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

    def __init__(self, max_calls: int | None = None, *, research_mode: bool = False) -> None:
        self.max_calls = max_calls if max_calls is not None else _max_web_search_calls()
        self.web_search_calls = 0
        self.search_degraded = False
        self.academic_calls = 0
        self.blocked_academic_tools: set[str] = set()
        self.research_mode = research_mode
        self.research_calls = 0
        self.research_started_at: float | None = None
        self.research_queue_wait_seconds = 0.0
        self.research_queries: set[str] = set()
        self.research_sources: set[str] = set()
        self.research_no_progress = 0
        self.research_stop_reason = ""
        self._research_lock = threading.Lock()

    @property
    def search_blocked(self) -> bool:
        return self.search_degraded or self.web_search_calls >= self.max_calls

    def _prepare_model_request(self, request: ModelRequest) -> ModelRequest:
        if self.research_mode:
            with self._research_lock:
                self._check_research_deadline()
                reason = self.research_stop_reason
            prompt = _RESEARCH_DELIVERY_PROMPT
            if reason:
                prompt += f"\n本轮停止条件已触发：{reason}。所有工具已移除；立即整理现有证据并交付子任务结果。"
            request = request.override(
                tools=[] if reason else request.tools,
                system_message=append_to_system_message(request.system_message, prompt),
            )
        if not self.search_blocked and not self.blocked_academic_tools:
            return request
        blocked = self.blocked_academic_tools | ({"web_search"} if self.search_blocked else set())
        tools = [item for item in (request.tools or []) if _tool_name(item) not in blocked]
        prompt = _SEARCH_STOP_PROMPT if self.search_blocked else ""
        if self.blocked_academic_tools:
            prompt += "\n" + _ACADEMIC_STOP_PROMPT
        system_message = append_to_system_message(request.system_message, prompt)
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
                "web_search 已在本轮熔断。不要重试或改写查询；仅显式 @知识库时可用 query_kbs，"
                "否则使用已有来源完成任务，并标注证据缺口。"
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            name="web_search",
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]) -> Any:
        denial = self._research_denial(request)
        if denial is not None:
            return denial
        if _tool_name(request.tool_call) in ACADEMIC_TOOL_NAMES:
            denial = self._academic_denial(request)
            if denial:
                return denial
            self.academic_calls += 1
            result = handler(request)
            self._record_academic_result(_tool_name(request.tool_call), result)
            self._record_research_result(request, result)
            return result
        if _tool_name(request.tool_call) != "web_search":
            result = handler(request)
            self._record_research_result(request, result)
            return result
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = handler(request)
        if _is_degraded_search_result(result):
            self.search_degraded = True
        self._record_research_result(request, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        denial = self._research_denial(request)
        if denial is not None:
            return denial
        if _tool_name(request.tool_call) in ACADEMIC_TOOL_NAMES:
            denial = self._academic_denial(request)
            if denial:
                return denial
            self.academic_calls += 1
            result = await handler(request)
            self._record_academic_result(_tool_name(request.tool_call), result)
            self._record_research_result(request, result)
            return result
        if _tool_name(request.tool_call) != "web_search":
            result = await handler(request)
            self._record_research_result(request, result)
            return result
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = await handler(request)
        if _is_degraded_search_result(result):
            self.search_degraded = True
        self._record_research_result(request, result)
        return result

    def _check_research_deadline(self) -> None:
        """在下一轮模型或工具调用前检查检索耗时。"""
        if self.research_calls >= 12:
            self.research_stop_reason = self.research_stop_reason or "工具调用达到 12 次"
        if self.research_started_at is not None:
            elapsed = time.monotonic() - self.research_started_at
            if elapsed >= 240:
                self.research_stop_reason = self.research_stop_reason or "检索总耗时达到 240 秒"
            elif elapsed - self.research_queue_wait_seconds >= 120:
                self.research_stop_reason = self.research_stop_reason or "检索时间达到 120 秒"

    def _research_denial(self, request: ToolCallRequest) -> ToolMessage | None:
        """为探索员预占预算并拦截重复查询，保持普通聊天策略不变。"""
        if not self.research_mode:
            return None
        name = _tool_name(request.tool_call)
        with self._research_lock:
            if self.research_started_at is None:
                self.research_started_at = time.monotonic()
            self._check_research_deadline()
            reason = self.research_stop_reason
            if not reason:
                self.research_calls += 1
                if name in {"web_search", "academic_search", "query_kb", "query_kbs"}:
                    arguments = dict(request.tool_call.get("args") or {})
                    arguments.pop("count", None)
                    arguments.pop("content_format", None)
                    if isinstance(arguments.get("query"), str):
                        arguments["query"] = " ".join(arguments["query"].casefold().split())
                    key = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
                    if key in self.research_queries:
                        self.research_no_progress += 1
                        if self.research_no_progress >= 2:
                            self.research_stop_reason = "连续重复查询，无新增证据"
                        reason = "重复查询已拦截，使用已有结果；仅针对具体证据缺口继续"
                    else:
                        self.research_queries.add(key)
            if not reason:
                return None
        return ToolMessage(
            content=json.dumps(
                {"status": "delivery_required" if self.research_stop_reason else "duplicate_query", "message": reason},
                ensure_ascii=False,
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            name=name,
        )

    def _record_research_result(self, request: ToolCallRequest, result: Any) -> None:
        """累计带摘要的去重网页来源，连续无增量时结束网页发现。"""
        if not self.research_mode or _tool_name(request.tool_call) != "web_search":
            return
        text = _result_text(result)
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                payload = json.loads("".join(item.get("text", "") for item in payload if isinstance(item, dict)))
        except (TypeError, ValueError):
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return
        queue_wait = payload.get("queue_wait_seconds", 0)
        if isinstance(queue_wait, (int, float)):
            with self._research_lock:
                self.research_queue_wait_seconds += min(90.0, max(0.0, queue_wait))
        sources = {
            str(item["url"]).split("#", 1)[0].rstrip("/")
            for item in payload["results"]
            if isinstance(item, dict)
            and str(item.get("url") or "").startswith(("https://", "http://"))
            and item.get("title")
            and item.get("content")
        }
        with self._research_lock:
            added = sources - self.research_sources
            self.research_sources.update(sources)
            self.research_no_progress = 0 if added else self.research_no_progress + 1
            if len(self.research_sources) >= 8 and self.web_search_calls >= 2:
                self.research_stop_reason = "已获取至少 8 条带摘要的去重来源，达到资料整理阈值"
            elif self.research_no_progress >= 2:
                self.research_stop_reason = "连续两次网页检索无新增可用来源"

    def _academic_denial(self, request: ToolCallRequest) -> ToolMessage | None:
        """阻止模型显式重复调用已移除的学术工具。"""
        name = _tool_name(request.tool_call)
        if self.academic_calls >= 20:
            self.blocked_academic_tools.update(ACADEMIC_TOOL_NAMES)
        if name not in self.blocked_academic_tools:
            return None
        return ToolMessage(
            content=(
                '{"status":"budget_exhausted","results":[],'
                '"message":"停止 AMiner 重试，使用网页、知识库和已有证据完成回答"}'
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            name=name,
        )

    def _record_academic_result(self, name: str, result: Any) -> None:
        """学术服务故障不熔断网页；接口限额只移除相应工具。"""
        try:
            payload = json.loads(_result_text(result))
        except (TypeError, ValueError):
            payload = {}
        status = (payload.get("aminer_status") or payload.get("status")) if isinstance(payload, dict) else None
        if status in {"disabled", "denied", "auth_failed", "rate_limited", "unavailable", "budget_exhausted"}:
            self.blocked_academic_tools.update(ACADEMIC_TOOL_NAMES)
        elif status in {"limit_reached", "configuration_changed", "in_progress"}:
            self.blocked_academic_tools.add(name)
        if self.academic_calls >= 20:
            self.blocked_academic_tools.update(ACADEMIC_TOOL_NAMES)
