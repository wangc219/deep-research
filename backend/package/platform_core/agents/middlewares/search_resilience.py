"""Bound web-search loops so research agents always reach a stop condition."""

from __future__ import annotations

import json
import os
import threading
import time
from urllib.parse import urlparse
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware import hook_config
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from platform_core.research_policy import (
    RESEARCH_BUDGET_ADAPTIVE_LONG_RUNNING,
    normalize_research_budget_mode,
)
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

_PLANNING_ONLY_PROMPT = """# 既有材料规划任务
用户要求只把已经提供的任务书或材料转成计划，且明确不启动真实研究。本轮不调用 AMiner，也不把“证据门、算法、
材料、研究”等规划章节名解释成外部论文取证请求。直接忠实提取既有材料，明确工程估算属于规划假设；只有用户明确
要求补充外部论文依据时，后续轮次才进行学术检索。"""

_RESEARCH_DELIVERY_PROMPT = """# 调研探索员运行边界
只处理调用方交给你的一个明确证据问题。先判断什么发现会改变主智能体结论，再自主选择网页、AMiner 与
已授权知识库；来源职责和调用顺序由问题决定，不按固定地区、数量或渠道配额机械检索。

用户未限制渠道且工具可用时，首轮使用 parallel_research_search，同时启动 Open WebSearch、SearXNG 与 AMiner，
按 URL、DOI 和题名融合去重；首轮只建立候选证据面，不要求各渠道凑数量。评估融合结果后，再用单路工具针对
仍会改变判断的缺口深挖。

web_search 已自适应融合 Open WebSearch 与 SearXNG，不要为两个网页后端重复同一查询。融合网页检索和 AMiner
没有固定内容分工：根据证据缺口、预期信息增益、时效、命中质量与调用成本选择单路、互补并发或首轮后补查。
两路都可发现技术、机构、案例和论文线索；只有预计来源、证据层级或交叉核验价值不同才并发。首路证据已经直接、
权威且边界充分时不为覆盖渠道而补查；命中不足、只有聚合线索、缺摘要/DOI/原始出处或存在冲突时再定向补缺。
只对真正影响判断的论文读取详情。

每次查询解决一个证据缺口。容易同名或漂移时使用 required_terms 或 required_term_groups 保留核心身份，
不要把待证明结论或多个独立问题设为锚点。互补调用可小批并发，同义查询不要并发或重复。

优先直接相关的一手或高权威来源，核对对象、时间、条件、反例和适用边界。同 DOI、转载和跨渠道重复命中
只算一项证据。技术问题可用 AMiner 发现论文并按需读取拟引用论文完整摘要；渠道为空或降级时继续其他来源，
披露覆盖缺口，不把缺失解释为事实不存在。

新增检索不再改变判断、补齐因果链或降低关键不确定性时立即停止。运行时预算只用于防止失控，不是最低用量。
交付紧凑证据包：高价值发现、对主研究判断的影响、真实引用、冲突、边界和仍影响结论的缺口。区分公开事实、
论文结论、本地材料、跨域类比、工程推断和创新假设；不要输出检索过程或继续尝试的承诺，也不要调用 write_todos。"""

_TOOL_PROTOCOL_CORRECTION_PROMPT = """# 工具协议纠错
上一响应把工具调用写成了可见的 DSML/XML 文本，因此没有被执行。禁止输出、解释或复述任何工具协议标记。
如果仍存在明确证据缺口，每次响应只通过原生 tool_calls 调用最多 2 个互补工具；如果证据已经足够，立即输出最终调研交付。"""

_TOOL_PROTOCOL_FINAL_PROMPT = """# 工具协议最终收敛
工具协议连续异常。本轮不再调用任何工具；立即根据已经取得的真实结果完成调研交付，缺失部分明确标为证据缺口。
最终文本不得包含 DSML、XML、tool_calls、invoke 或参数序列化内容。"""

_RESEARCH_WEB_LIMIT = 24
_RESEARCH_ACADEMIC_TOPIC_LIMIT = 8
_RESEARCH_ACADEMIC_TITLE_LIMIT = 3
_RESEARCH_ACADEMIC_DETAIL_LIMIT = 3
_RESEARCH_BATCH_TOOL_LIMIT = 4
_RESEARCH_ACTIVE_TOOL_LIMIT_SECONDS = 480
_RESEARCH_WALL_LIMIT_SECONDS = 1800
_RESEARCH_EVIDENCE_TOOLS = frozenset(
    {"web_search", "academic_search", "academic_get_papers", "query_kb", "query_kbs"}
) | frozenset(ACADEMIC_TOOL_NAMES)


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


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or block.get("content") or "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")


def _has_serialized_tool_markup(response: Any) -> bool:
    """识别被模型写进正文、未形成原生 tool_calls 的工具协议。"""
    messages = getattr(response, "result", None)
    if not isinstance(messages, list):
        messages = [response]
    for message in messages:
        if getattr(message, "tool_calls", None):
            continue
        text = _message_text(message).casefold()
        if "dsml" in text and ("tool_calls" in text or "invoke name" in text):
            return True
    return False


def _academic_search_mode(arguments: dict[str, Any]) -> str:
    return "title" if str(arguments.get("mode") or "").casefold() == "title" else "topic"


def _is_planning_only_request(query: str) -> bool:
    """识别只转换既有材料的规划任务，避免把“证据门”等章节名误判为取证请求。"""
    explicit_external_evidence = any(
        marker in query
        for marker in (
            "请检索论文",
            "请搜索论文",
            "检索外部证据",
            "搜索外部证据",
            "补充论文依据",
            "补充学术依据",
            "引用论文",
            "查找论文",
        )
    )
    if explicit_external_evidence:
        return False
    return any(
        marker in query
        for marker in (
            "只做规划",
            "仅做规划",
            "只需规划",
            "不得启动真实研究",
            "不要启动真实研究",
            "不启动真实研究",
            "不得执行真实研究",
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

    def __init__(
        self,
        max_calls: int | None = None,
        *,
        research_mode: bool = False,
        research_budget_mode: str = "standard",
    ) -> None:
        self.research_budget_mode = normalize_research_budget_mode(research_budget_mode)
        self.adaptive_long_running = (
            research_mode and self.research_budget_mode == RESEARCH_BUDGET_ADAPTIVE_LONG_RUNNING
        )
        self.max_calls = (
            max_calls
            if max_calls is not None
            else None
            if self.adaptive_long_running
            else (_RESEARCH_WEB_LIMIT if research_mode else _max_web_search_calls())
        )
        self.web_search_calls = 0
        self.search_degraded = False
        self.academic_calls = 0
        self.blocked_academic_tools: set[str] = set()
        self.research_mode = research_mode
        self.research_calls = 0
        self.research_started_at: float | None = None
        self.research_tool_seconds = 0.0
        self.research_queries: set[str] = set()
        self.research_sources: set[str] = set()
        self.research_source_domains: set[str] = set()
        self.research_academic_papers: set[str] = set()
        self.research_academic_abstracts: set[str] = set()
        self.research_no_progress = 0
        self.research_stop_reason = ""
        self._research_lock = threading.Lock()
        self.requested_academic_search_started = False
        self.requested_knowledge_search_started = False
        self.parallel_discovery_started = False
        self.research_web_stop_reason = ""
        self.research_web_calls = 0
        self.research_academic_topic_calls = 0
        self.research_academic_title_calls = 0
        self.research_academic_detail_calls = 0
        self.tool_markup_recoveries = 0
        self.force_protocol_final = False

    @property
    def search_blocked(self) -> bool:
        return self.search_degraded or (self.max_calls is not None and self.web_search_calls >= self.max_calls)

    def _prepare_model_request(self, request: ModelRequest) -> ModelRequest:
        if self.research_mode:
            with self._research_lock:
                self._check_research_deadline()
                reason = self.research_stop_reason
                limited_tools, limit_note = self._research_limited_tools()
            prompt = _RESEARCH_DELIVERY_PROMPT
            if self.adaptive_long_running:
                prompt += (
                    "\n本轮为长程自适应研究：不设置网页、论文主题/语义、标题、摘要批次或总工具调用的固定次数上限。"
                    "由覆盖缺口、证据冲突和边际信息增益决定是否继续；完全重复、连续无新增、外部限流、运行取消和"
                    "平台并发/执行边界仍然有效。不要为了消耗预算而检索，也不要因普通短任务额度主动收敛。"
                )
            prompt += (
                f"\n本轮已取得 {len(self.research_sources)} 条去重网页来源、"
                f"{len(self.research_source_domains)} 个站点、{len(self.research_academic_papers)} 篇去重论文候选，"
                f"其中 {len(self.research_academic_abstracts)} 篇达到摘要级；渠道计数不等于独立证据数。"
            )
            if reason:
                prompt += f"\n本轮停止条件已触发：{reason}。所有工具已移除；立即整理现有证据并交付子任务结果。"
            elif limit_note:
                prompt += "\n本轮渠道边界：" + limit_note
            request = request.override(
                tools=[]
                if reason or self.force_protocol_final
                else [
                    tool
                    for tool in (request.tools or [])
                    if _tool_name(tool) not in limited_tools and _tool_name(tool) != "write_todos"
                ],
                system_message=append_to_system_message(request.system_message, prompt),
            )
            if not self.search_blocked and not self.blocked_academic_tools:
                return self._require_parallel_discovery(request)
            blocked = self.blocked_academic_tools | ({"web_search"} if self.search_blocked else set())
            tools = [item for item in (request.tools or []) if _tool_name(item) not in blocked]
            stop_prompt = _SEARCH_STOP_PROMPT if self.search_blocked else ""
            if self.blocked_academic_tools:
                stop_prompt += "\n" + _ACADEMIC_STOP_PROMPT
            return self._require_parallel_discovery(
                request.override(
                    tools=tools,
                    system_message=append_to_system_message(request.system_message, stop_prompt),
                )
            )
        request = self._scope_planning_only_tools(request)
        if not self.search_blocked and not self.blocked_academic_tools:
            return self._require_requested_academic_search(self._require_knowledge_search(request))
        blocked = self.blocked_academic_tools | ({"web_search"} if self.search_blocked else set())
        tools = [item for item in (request.tools or []) if _tool_name(item) not in blocked]
        prompt = _SEARCH_STOP_PROMPT if self.search_blocked else ""
        if self.blocked_academic_tools:
            prompt += "\n" + _ACADEMIC_STOP_PROMPT
        system_message = append_to_system_message(request.system_message, prompt)
        return self._require_requested_academic_search(
            self._require_knowledge_search(request.override(tools=tools, system_message=system_message))
        )

    def _scope_planning_only_tools(self, request: ModelRequest) -> ModelRequest:
        """在模型选择工具前移除未被请求的 AMiner，根治规划任务误检索。"""
        messages = request.messages or []
        latest_user = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
        if latest_user is None or not _is_planning_only_request(_message_text(latest_user).casefold()):
            return request
        return request.override(
            tools=[tool for tool in (request.tools or []) if _tool_name(tool) not in ACADEMIC_TOOL_NAMES],
            system_message=append_to_system_message(request.system_message, _PLANNING_ONLY_PROMPT),
        )

    def _require_parallel_discovery(self, request: ModelRequest) -> ModelRequest:
        """探索员首轮强制一次三渠道并发发现，并尊重用户显式渠道限制。"""
        if self.parallel_discovery_started or request.tool_choice is not None:
            return request
        if "parallel_research_search" not in {_tool_name(tool) for tool in request.tools or []}:
            return request
        messages = request.messages or []
        latest_user = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
        if latest_user is None:
            return request
        query = _message_text(messages[latest_user]).casefold()
        if any(
            marker in query
            for marker in (
                "不要检索",
                "无需检索",
                "不检索",
                "仅分析已有",
                "只分析已有",
                "仅使用网页",
                "只用网页",
                "不使用 aminer",
                "不使用aminer",
                "不要使用 aminer",
                "不要使用aminer",
                "仅使用 aminer",
                "仅使用aminer",
                "只用 aminer",
                "只用aminer",
                "不使用网页",
                "不要使用网页",
            )
        ):
            return request
        if any(
            isinstance(message, ToolMessage) and message.name in _RESEARCH_EVIDENCE_TOOLS
            for message in messages[latest_user + 1 :]
        ):
            self.parallel_discovery_started = True
            return request
        self.parallel_discovery_started = True
        return request.override(tool_choice="parallel_research_search")

    def _require_knowledge_search(self, request: ModelRequest) -> ModelRequest:
        """确保启用的本地来源贡献独立视角；工具授权仍由上下文权限层维护。"""
        if not self.research_mode or self.requested_knowledge_search_started or request.tool_choice is not None:
            return request
        if "query_kbs" not in {_tool_name(tool) for tool in request.tools or []}:
            return request
        messages = request.messages or []
        latest_user = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
        if latest_user is None:
            return request
        query = _message_text(messages[latest_user]).casefold()
        if any(
            marker in query
            for marker in (
                "不要检索",
                "无需检索",
                "不检索",
                "禁止检索",
                "不得检索",
                "仅分析已有",
                "只分析已有",
                "不使用知识库",
                "不要使用知识库",
                "仅使用网页",
                "只用网页",
            )
        ):
            return request
        if any(
            isinstance(message, ToolMessage) and message.name in {"query_kb", "query_kbs"}
            for message in messages[latest_user + 1 :]
        ):
            return request
        self.requested_knowledge_search_started = True
        return request.override(tool_choice="query_kbs")

    def _require_requested_academic_search(self, request: ModelRequest) -> ModelRequest:
        """论文请求及探索员技术子问题先取证，避免凭模型记忆补技术证据。"""
        if self.requested_academic_search_started or request.tool_choice is not None:
            return request
        if "academic_search" not in {_tool_name(t) for t in request.tools or []}:
            return request
        messages = request.messages or []
        latest_user = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
        if latest_user is None or not isinstance(messages[latest_user].content, str):
            return request
        query = messages[latest_user].content.casefold()
        if _is_planning_only_request(query):
            return request
        if any(
            x in query
            for x in (
                "不要检索",
                "无需检索",
                "不检索",
                "禁止检索",
                "不得检索",
                "不要搜索",
                "不使用 aminer",
                "不使用aminer",
                "不要使用 aminer",
                "不要使用aminer",
                "不使用学术检索",
                "无需论文",
                "不需要论文",
                "不要论文",
                "不检索论文",
                "不搜索论文",
                "no academic search",
                "do not search papers",
                "不使用 academic",
                "仅使用网页",
                "只用网页",
                "仅分析已有",
                "只分析已有",
                "基于已给摘要",
                "已有论文证据充分",
            )
        ):
            return request
        explicit_request = "论文" in query and (
            any(x in query for x in ("请检索", "请搜索", "检索论文", "查找论文", "搜索论文"))
            or ("论文摘要" in query and ("来源链接" in query or "doi" in query))
            or any(x in query for x in ("证据", "依据"))
        )
        evidence_requested = any(marker in query for marker in ("证据", "研究依据", "evidence"))
        technical_research = (self.research_mode or evidence_requested) and any(
            marker in query
            for marker in (
                "技术原理",
                "新原理",
                "新方法",
                "跨领域",
                "创新启发",
                "装备启发",
                "作用机理",
                "关键技术",
                "技术路线",
                "技术实现",
                "工程可行",
                "工程瓶颈",
                "瓶颈",
                "性能边界",
                "成熟度",
                "材料",
                "器件",
                "芯片",
                "算法",
                "自主协同",
                "technical feasibility",
                "mechanism",
                "algorithm",
                "material",
                "sensor",
            )
        )
        requested = explicit_request or technical_research
        if not requested:
            return request
        evidence_tools = (
            ACADEMIC_TOOL_NAMES
            if technical_research
            else (ACADEMIC_TOOL_NAMES | {"web_search", "subagent_start", "subagent_await"})
        )
        if any(isinstance(m, ToolMessage) and m.name in evidence_tools for m in messages[latest_user + 1 :]):
            return request
        self.requested_academic_search_started = True
        return request.override(tool_choice="academic_search")

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

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):  # noqa: ARG002
        return self._recover_serialized_tool_markup(state)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):  # noqa: ARG002
        return self._recover_serialized_tool_markup(state)

    def _recover_serialized_tool_markup(self, state) -> dict[str, Any] | None:
        """把协议泄漏留在可审计 state 中，以纠错消息驱动下一次正常模型轮次。"""
        if not self.research_mode:
            return None
        messages = state.get("messages") if isinstance(state, dict) else None
        if not messages or not _has_serialized_tool_markup(messages[-1]):
            return None
        if self.research_calls == 0:
            self.parallel_discovery_started = False
        self.tool_markup_recoveries += 1
        if self.tool_markup_recoveries >= 2:
            self.force_protocol_final = True
            correction = _TOOL_PROTOCOL_FINAL_PROMPT
        else:
            correction = _TOOL_PROTOCOL_CORRECTION_PROMPT
        if self.tool_markup_recoveries > 3:
            raise RuntimeError("调研探索员连续输出未执行的 DSML/XML 工具协议，无法形成可靠交付")
        return {"messages": [HumanMessage(content=correction)], "jump_to": "model"}

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
            result = self._call_research_tool(request, handler)
            self._record_academic_result(_tool_name(request.tool_call), result)
            self._record_research_result(request, result)
            return result
        if _tool_name(request.tool_call) != "web_search":
            result = self._call_research_tool(request, handler)
            self._record_research_result(request, result)
            return result
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = self._call_research_tool(request, handler)
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
            result = await self._acall_research_tool(request, handler)
            self._record_academic_result(_tool_name(request.tool_call), result)
            self._record_research_result(request, result)
            return result
        if _tool_name(request.tool_call) != "web_search":
            result = await self._acall_research_tool(request, handler)
            self._record_research_result(request, result)
            return result
        if self.search_blocked:
            return self._blocked_message(request)
        self.web_search_calls += 1
        result = await self._acall_research_tool(request, handler)
        if _is_degraded_search_result(result):
            self.search_degraded = True
        self._record_research_result(request, result)
        return result

    def _check_research_deadline(self) -> None:
        """只用真实工具执行时间计算活跃预算，模型推理仅受宽松墙钟兜底约束。"""
        if self.adaptive_long_running:
            # 长程模式不在探索员中间件内按次数或局部墙钟截断；总体运行仍由
            # AgentRun 取消/租约、LangGraph recursion_limit 和外部服务限流控制。
            return
        if self.research_calls >= 48:
            self.research_stop_reason = self.research_stop_reason or "工具调用达到 48 次"
        if self.research_tool_seconds >= _RESEARCH_ACTIVE_TOOL_LIMIT_SECONDS:
            self.research_stop_reason = self.research_stop_reason or "检索工具累计执行达到 480 秒"
        if self.research_started_at is not None:
            elapsed = time.monotonic() - self.research_started_at
            if elapsed >= _RESEARCH_WALL_LIMIT_SECONDS:
                self.research_stop_reason = self.research_stop_reason or "调研总墙钟达到 1800 秒"

    def _call_research_tool(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]) -> Any:
        """执行工具并累计真实工具耗时；普通聊天不承担额外计时。"""
        if not self.research_mode or _tool_name(request.tool_call) not in _RESEARCH_EVIDENCE_TOOLS:
            return handler(request)
        started = time.monotonic()
        result: Any = None
        try:
            result = handler(request)
            return result
        finally:
            self._record_research_tool_duration(started, result)

    async def _acall_research_tool(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        """异步工具执行使用与同步路径一致的活跃耗时核算。"""
        if not self.research_mode or _tool_name(request.tool_call) not in _RESEARCH_EVIDENCE_TOOLS:
            return await handler(request)
        started = time.monotonic()
        result: Any = None
        try:
            result = await handler(request)
            return result
        finally:
            self._record_research_tool_duration(started, result)

    def _record_research_tool_duration(self, started: float, result: Any) -> None:
        elapsed = max(0.0, time.monotonic() - started)
        queue_wait = 0.0
        try:
            payload = json.loads(_result_text(result))
            if isinstance(payload, dict) and isinstance(payload.get("queue_wait_seconds"), int | float):
                queue_wait = min(elapsed, max(0.0, float(payload["queue_wait_seconds"])))
        except (TypeError, ValueError):
            pass
        with self._research_lock:
            self.research_tool_seconds += max(0.0, elapsed - queue_wait)

    def _batch_tool_limit_reason(self, request: ToolCallRequest) -> str:
        """限制单个模型响应的检索扇出，保留有界并发与中途重规划能力。"""
        name = _tool_name(request.tool_call)
        if name not in _RESEARCH_EVIDENCE_TOOLS:
            return ""
        state = getattr(request, "state", None)
        messages = state.get("messages") if isinstance(state, Mapping) else None
        if not isinstance(messages, list):
            return ""
        latest = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
        tool_calls = getattr(latest, "tool_calls", None) if latest is not None else None
        if not isinstance(tool_calls, list):
            return ""
        evidence_calls = [call for call in tool_calls if _tool_name(call) in _RESEARCH_EVIDENCE_TOOLS]
        call_id = str(request.tool_call.get("id") or "")
        position = next(
            (index for index, call in enumerate(evidence_calls) if str(call.get("id") or "") == call_id),
            None,
        )
        if position is not None and position >= _RESEARCH_BATCH_TOOL_LIMIT:
            return "同一模型响应最多执行 4 个互补检索调用；后续调用已拒绝，请先评估本批结果再决定是否继续"
        return ""

    def _research_limited_tools(self) -> tuple[set[str], str]:
        """返回已完成本子任务配额的渠道，额度只约束探索员编排而非 AMiner 账户。"""
        blocked: set[str] = set()
        notes: list[str] = []
        if self.research_web_stop_reason:
            blocked.update({"web_search", "parallel_research_search"})
            notes.append(self.research_web_stop_reason + "；继续使用授权知识库、论文摘要和已有来源")
        if self.adaptive_long_running:
            return blocked, "；".join(notes)
        if self.research_web_calls >= _RESEARCH_WEB_LIMIT:
            blocked.update({"web_search", "parallel_research_search"})
            notes.append("网页精确检索已完成 24 次，停止新增网页查询")
        if self.research_academic_detail_calls >= _RESEARCH_ACADEMIC_DETAIL_LIMIT:
            blocked.add("academic_get_papers")
            notes.append("完整摘要已完成 3 批读取，不再重复拉取详情")
        topic_done = self.research_academic_topic_calls >= _RESEARCH_ACADEMIC_TOPIC_LIMIT
        title_done = self.research_academic_title_calls >= _RESEARCH_ACADEMIC_TITLE_LIMIT
        if topic_done and title_done:
            blocked.update({"academic_search", "parallel_research_search"})
            notes.append("论文主题发现已完成，停止同义改写；使用已取得题录/摘要")
        elif topic_done:
            notes.append("论文主题/语义发现已达 8 次；academic_search 仍可在标题额度内准确定位")
        return blocked, "；".join(notes)

    def _reserve_research_tool_budget(self, name: str, arguments: dict[str, Any]) -> str:
        """在执行前原子预占渠道次数，阻止一个模型批次并行冲过建议边界。"""
        if name == "parallel_research_search":
            if self.research_web_stop_reason:
                return "三渠道并发发现已完成网页阶段：" + self.research_web_stop_reason
            if not self.adaptive_long_running and self.research_web_calls >= _RESEARCH_WEB_LIMIT:
                return "网页精确检索额度已完成，不能再次执行三渠道首轮发现"
            if not self.adaptive_long_running and self.research_academic_topic_calls >= _RESEARCH_ACADEMIC_TOPIC_LIMIT:
                return "论文主题发现额度已完成，不能再次执行三渠道首轮发现"
            self.research_web_calls += 1
            self.research_academic_topic_calls += 1
        elif name == "web_search":
            if self.research_web_stop_reason:
                return "web_search 已完成本轮网页发现：" + self.research_web_stop_reason
            if not self.adaptive_long_running and self.research_web_calls >= _RESEARCH_WEB_LIMIT:
                return "web_search 已完成本子任务最多 24 次精确主题检索；停止新增网页查询并整理已有证据"
            self.research_web_calls += 1
        elif name == "academic_search":
            if _academic_search_mode(arguments) == "title":
                if (
                    not self.adaptive_long_running
                    and self.research_academic_title_calls >= _RESEARCH_ACADEMIC_TITLE_LIMIT
                ):
                    return "academic_search 标题校正已完成 3 次；停止再次改写标题"
                requested = 1 + min(2, len(arguments.get("related_queries") or []))
                if (
                    not self.adaptive_long_running
                    and self.research_academic_title_calls + requested > _RESEARCH_ACADEMIC_TITLE_LIMIT
                ):
                    return "academic_search 补充查询超出剩余标题额度；请缩减 related_queries"
                self.research_academic_title_calls += requested
            else:
                if (
                    not self.adaptive_long_running
                    and self.research_academic_topic_calls >= _RESEARCH_ACADEMIC_TOPIC_LIMIT
                ):
                    return "academic_search 主题/语义发现已完成 8 次；使用准确标题定位或整理已有论文"
                requested = 1 + min(2, len(arguments.get("related_queries") or []))
                if (
                    not self.adaptive_long_running
                    and self.research_academic_topic_calls + requested > _RESEARCH_ACADEMIC_TOPIC_LIMIT
                ):
                    return "academic_search 补充查询超出剩余主题额度；请缩减 related_queries"
                self.research_academic_topic_calls += requested
        elif name == "academic_get_papers":
            if (
                not self.adaptive_long_running
                and self.research_academic_detail_calls >= _RESEARCH_ACADEMIC_DETAIL_LIMIT
            ):
                return "academic_get_papers 已完成 3 批摘要读取；停止重复拉取并使用已有完整摘要"
            self.research_academic_detail_calls += 1
        return ""

    def _research_denial(self, request: ToolCallRequest) -> ToolMessage | None:
        """为探索员预占预算并拦截重复查询，保持普通聊天策略不变。"""
        if not self.research_mode:
            return None
        name = _tool_name(request.tool_call)
        batch_reason = self._batch_tool_limit_reason(request)
        if batch_reason:
            return ToolMessage(
                content=json.dumps({"status": "tool_batch_limit", "message": batch_reason}, ensure_ascii=False),
                tool_call_id=str(request.tool_call.get("id") or ""),
                name=name,
            )
        arguments = dict(request.tool_call.get("args") or {})
        with self._research_lock:
            if self.research_started_at is None:
                self.research_started_at = time.monotonic()
            self._check_research_deadline()
            reason = self.research_stop_reason
            if not reason:
                if name in {"web_search", "academic_search", "query_kb", "query_kbs"}:
                    normalized_arguments = dict(arguments)
                    normalized_arguments.pop("count", None)
                    normalized_arguments.pop("content_format", None)
                    if isinstance(normalized_arguments.get("query"), str):
                        normalized_arguments["query"] = " ".join(normalized_arguments["query"].casefold().split())
                    key = name + json.dumps(normalized_arguments, sort_keys=True, ensure_ascii=False, default=str)
                    if key in self.research_queries:
                        self.research_no_progress += 1
                        if self.research_no_progress >= 2:
                            self.research_stop_reason = "连续重复查询，无新增证据"
                        reason = "重复查询已拦截，使用已有结果；仅针对具体证据缺口继续"
                    else:
                        self.research_queries.add(key)
                if not reason:
                    reason = self._reserve_research_tool_budget(name, arguments)
                if not reason:
                    self.research_calls += 1
            if not reason:
                return None
        return ToolMessage(
            content=json.dumps(
                {
                    "status": (
                        "delivery_required"
                        if self.research_stop_reason
                        else "tool_budget_reached"
                        if "已完成" in reason
                        else "duplicate_query"
                    ),
                    "message": reason,
                },
                ensure_ascii=False,
            ),
            tool_call_id=str(request.tool_call.get("id") or ""),
            name=name,
        )

    def _record_research_result(self, request: ToolCallRequest, result: Any) -> None:
        """累计带摘要的去重网页来源，连续无增量时结束网页发现。"""
        name = _tool_name(request.tool_call)
        if not self.research_mode or name not in {"web_search", "parallel_research_search"}:
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
        sources = {
            str(item["url"]).split("#", 1)[0].rstrip("/")
            for item in payload["results"]
            if isinstance(item, dict)
            and (name == "web_search" or item.get("evidence_type") in {"web", "hybrid"})
            and str(item.get("url") or "").startswith(("https://", "http://"))
            and item.get("title")
            and item.get("content")
        }
        with self._research_lock:
            added = sources - self.research_sources
            self.research_sources.update(sources)
            self.research_no_progress = 0 if added else self.research_no_progress + 1
            self.research_source_domains.update(str(urlparse(source).hostname or "") for source in sources)
            if self.research_no_progress >= 3:
                self.research_web_stop_reason = "连续三次网页检索无新增可用来源"

    def _academic_denial(self, request: ToolCallRequest) -> ToolMessage | None:
        """阻止模型显式重复调用已移除的学术工具。"""
        name = _tool_name(request.tool_call)
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
        papers: set[str] = set()
        abstracts: set[str] = set()
        if isinstance(payload, dict):
            for item in payload.get("results") or []:
                if not isinstance(item, dict):
                    continue
                identity = str(item.get("doi") or item.get("id") or "")
                identity = " ".join(identity.casefold().split())
                if not identity:
                    continue
                papers.add(identity)
                if item.get("content_level") == "abstract":
                    abstracts.add(identity)
        if papers:
            with self._research_lock:
                self.research_academic_papers.update(papers)
                self.research_academic_abstracts.update(abstracts)
        if status in {"disabled", "denied", "auth_failed", "rate_limited", "unavailable", "budget_exhausted"}:
            self.blocked_academic_tools.update(ACADEMIC_TOOL_NAMES)
        elif status in {"limit_reached", "configuration_changed", "in_progress"}:
            endpoint = payload.get("failed_endpoint")
            limited_tool = {
                "search": "academic_search",
                "question_search": "academic_search",
                "semantic_search": "academic_search",
                "title_search": "academic_search",
                "detail": "academic_get_papers",
                "references": "academic_get_references",
            }.get(endpoint, name)
            # 免费题录额度不控制 Pro 搜索和付费详情；服务仍可返回已有证据。
            if status != "limit_reached" or endpoint != "info":
                self.blocked_academic_tools.add(limited_tool)
