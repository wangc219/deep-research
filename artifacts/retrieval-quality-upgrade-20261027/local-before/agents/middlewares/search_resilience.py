"""Bound web-search loops so research agents always reach a stop condition."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware import hook_config
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
当子问题服务新质武器装备研究时，三源共同支撑创新启发，按互补性、新颖性和对装备构想的启发价值筛选信息。
其他问题保持调用方范围，按其研究目标综合三源，不引入装备创作要求。
网页提供新进展、案例与反常现象，AMiner 提供新原理、方法和实验发现，本地知识库提供研究积累、领域联系与未解问题；
各源都可提出启发和反例。已授权启用知识库时应实际用 query_kbs 取得其独立视角，不必等待网页故障。
围绕同一子问题综合各源不同认识、互补发现和矛盾，探索相关的跨领域联系与新的可能性。
不要求每个启发都已有现成装备对应，也不强求三源得出同样结论；已有文献和成熟案例不能成为创新方向的上限。
明确什么新发现带来何种启发，将创新联想、跨域类比和待验证假设与实际取得的事实分开，说明适用条件与证据缺口。
知识库片段核对对象、方法、条件和出处；关键数字和事实按需用 open_kb_document / find_kb_document 查看上下文。
保留 kb_id、file_id、文件名和定位；低相关片段只算线索。内部原文和项目名称不得发到外部服务。
同一论文跨渠道只算一项原始研究，重复命中不增加新颖性；冲突核对时间、对象和实验条件，不以渠道投票决定事实。
只围绕调用方的单个子问题检索，先明确最多三个需要证据的要点，并为每个要点建立“核心对象/实体 + 作用或指标 +
场景/约束”的主题检索式。
每次 web_search 只查一个明确证据缺口，使用 2-5 个有区分度的词；容易同名或漂移时用 required_terms 固定 1-2
个核心实体/技术身份锚点。
不要把待证明的结论或三个不同子问题同时塞进 required_terms；只有三者确实必须同页共现时才使用 3 个锚点。
每次模型响应最多发起 2 个互补检索工具调用，以受控小批减少模型往返；同一批不得发起两个同渠道同义查询，
也不得为了凑满 2 个调用而搜索。
运行时会拒绝同一响应中的第 3 个检索调用，并继续原子控制各渠道总次数。禁止把 DSML、XML 或其他工具协议写进可见文本。
不要把整段任务、空泛问题或“技术/研究/发展/数据”单独作为查询。每个子任务至少争取 2
个直接相关的一手或高权威网页来源，
优先原始试验、标准、政府/军队、论文出版页和厂商一手资料；已有原始来源时不得用聚合媒体、转载页或 ResearchGate
页面代替。
工具返回的 source_tier=authoritative 可辅助识别权威入口，但仍需根据标题与摘要核验它是否直接回答证据点。
子问题涉及技术原理、材料/器件、算法、工程可行性、性能边界或成熟度时，除非已有充分论文证据或用户明确禁用，先用
AMiner 做一次主题发现，
首次仅用 2-6 个标准学术术语发起一个查询，不携带 related_queries；同一批若还调用网页检索，
必须解决不同且互补的证据缺口。首次主题检索为空时，先从网页命中中提取一篇相关论文的准确标题，
再用 academic_search(mode="title") 定位，不连续堆叠同义词消耗额度。筛选 1-3 篇直接研究当前对象的候选，必须再用
academic_get_papers(full_abstract=True) 补证；
论文题录或宽泛关键词重合不算技术证据。
单个子任务由运行时控制为：最多 8 次精确网页检索、最多 2 次互补论文主题发现，
主题为空时可再做 1 次准确标题校正；完整摘要集中在 1 次
academic_get_papers 调用中读取 1-3 篇。达到某一渠道边界后使用另一渠道或已有证据交付，不得继续同义改写撞限。
每轮先判断已有三源证据是否覆盖要点；关键判断已有直接证据即可交付，网页只补时效和公开事实缺口，不必用满预算。
若确实找不到 2 个，应明确写成来源质量缺口而不是拿低质量页面凑数。摘要只支持摘要中实际出现的论断。
只有明确证据缺口才继续检索，禁止重复相同查询或无目的更换同义词。
运行时按独立来源、无增量次数、工具调用与耗时控制检索。资料整理阈值不代表事实已证实。
停止后必须返回：能直接回答子问题、改变主智能体判断或暴露关键风险的高价值发现及就近引用，
并说明每项发现对主研究为何有用；
同时列出来源、冲突和仍影响判断的具体证据缺口。默认只交付 4-6 条发现，正文不得超过 2500 个中文字符；不要写检索过程、
堆砌通用背景、重复文献清单或低相关事实，也不要输出继续尝试的承诺。
每个约定证据点都要给出可供主智能体合并的结果；即使部分检索限流也不能只返回限流说明，
按要点区分已核实发现与待核验缺口。
暂时限流已由工具内部共享排队和冷却恢复，不能推断本轮检索永久不可用；不得通过不断改写查询制造重试风暴。
本子任务不创建或更新待办，工具调用本身就是执行过程；不要调用 write_todos。"""

_TOOL_PROTOCOL_CORRECTION_PROMPT = """# 工具协议纠错
上一响应把工具调用写成了可见的 DSML/XML 文本，因此没有被执行。禁止输出、解释或复述任何工具协议标记。
如果仍存在明确证据缺口，每次响应只通过原生 tool_calls 调用最多 2 个互补工具；如果证据已经足够，立即输出最终调研交付。"""

_TOOL_PROTOCOL_FINAL_PROMPT = """# 工具协议最终收敛
工具协议连续异常。本轮不再调用任何工具；立即根据已经取得的真实结果完成调研交付，缺失部分明确标为证据缺口。
最终文本不得包含 DSML、XML、tool_calls、invoke 或参数序列化内容。"""

_RESEARCH_WEB_LIMIT = 8
_RESEARCH_ACADEMIC_TOPIC_LIMIT = 2
_RESEARCH_ACADEMIC_TITLE_LIMIT = 1
_RESEARCH_ACADEMIC_DETAIL_LIMIT = 1
_RESEARCH_BATCH_TOOL_LIMIT = 2
_RESEARCH_ACTIVE_TOOL_LIMIT_SECONDS = 180
_RESEARCH_WALL_LIMIT_SECONDS = 900
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
        self.research_tool_seconds = 0.0
        self.research_queries: set[str] = set()
        self.research_sources: set[str] = set()
        self.research_authoritative_sources: set[str] = set()
        self.research_no_progress = 0
        self.research_stop_reason = ""
        self._research_lock = threading.Lock()
        self.requested_academic_search_started = False
        self.requested_knowledge_search_started = False
        self.research_web_stop_reason = ""
        self.research_web_calls = 0
        self.research_academic_topic_calls = 0
        self.research_academic_title_calls = 0
        self.research_academic_detail_calls = 0
        self.research_academic_has_hits = False
        self.tool_markup_recoveries = 0
        self.force_protocol_final = False

    @property
    def search_blocked(self) -> bool:
        return self.search_degraded or self.web_search_calls >= self.max_calls

    def _prepare_model_request(self, request: ModelRequest) -> ModelRequest:
        if self.research_mode:
            with self._research_lock:
                self._check_research_deadline()
                reason = self.research_stop_reason
                limited_tools, limit_note = self._research_limited_tools()
            prompt = _RESEARCH_DELIVERY_PROMPT
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
        if self.research_calls >= 20:
            self.research_stop_reason = self.research_stop_reason or "工具调用达到 20 次"
        if self.research_tool_seconds >= _RESEARCH_ACTIVE_TOOL_LIMIT_SECONDS:
            self.research_stop_reason = self.research_stop_reason or "检索工具累计执行达到 180 秒"
        if self.research_started_at is not None:
            elapsed = time.monotonic() - self.research_started_at
            if elapsed >= _RESEARCH_WALL_LIMIT_SECONDS:
                self.research_stop_reason = self.research_stop_reason or "调研总墙钟达到 900 秒"

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
        """拒绝同一个模型响应里排在第 3 位及之后的证据检索调用。"""
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
            return "同一模型响应最多执行 2 个互补检索调用；第 3 个及后续调用已拒绝，请先评估本批结果再决定是否继续"
        return ""

    def _research_limited_tools(self) -> tuple[set[str], str]:
        """返回已完成本子任务配额的渠道，额度只约束探索员编排而非 AMiner 账户。"""
        blocked: set[str] = set()
        notes: list[str] = []
        if self.research_web_stop_reason:
            blocked.add("web_search")
            notes.append(self.research_web_stop_reason + "；继续使用授权知识库、论文摘要和已有来源")
        if self.research_web_calls >= _RESEARCH_WEB_LIMIT:
            blocked.add("web_search")
            notes.append("网页精确检索已完成 8 次，停止新增网页查询")
        if self.research_academic_detail_calls >= _RESEARCH_ACADEMIC_DETAIL_LIMIT:
            blocked.add("academic_get_papers")
            notes.append("完整摘要已完成一次集中读取，不再重复拉取详情")
        topic_done = self.research_academic_topic_calls >= _RESEARCH_ACADEMIC_TOPIC_LIMIT
        title_done = self.research_academic_title_calls >= _RESEARCH_ACADEMIC_TITLE_LIMIT
        if topic_done and (self.research_academic_has_hits or title_done):
            blocked.add("academic_search")
            notes.append("论文主题发现已完成，停止同义改写；使用已取得题录/摘要")
        elif topic_done:
            notes.append("论文主题发现已达 2 次且仍为空；academic_search 仅允许一次准确标题校正")
        return blocked, "；".join(notes)

    def _reserve_research_tool_budget(self, name: str, arguments: dict[str, Any]) -> str:
        """在执行前原子预占渠道次数，阻止一个模型批次并行冲过建议边界。"""
        if name == "web_search":
            if self.research_web_stop_reason:
                return "web_search 已完成本轮网页发现：" + self.research_web_stop_reason
            if self.research_web_calls >= _RESEARCH_WEB_LIMIT:
                return "web_search 已完成本子任务最多 8 次精确主题检索；停止新增网页查询并整理已有证据"
            self.research_web_calls += 1
        elif name == "academic_search":
            if _academic_search_mode(arguments) == "title":
                if self.research_academic_title_calls >= _RESEARCH_ACADEMIC_TITLE_LIMIT:
                    return "academic_search 标题校正已完成 1 次；停止再次改写标题"
                self.research_academic_title_calls += 1
            else:
                if self.research_academic_topic_calls >= _RESEARCH_ACADEMIC_TOPIC_LIMIT:
                    return "academic_search 主题发现已完成 2 次；如主题为空只允许用准确标题校正，否则整理已有论文"
                self.research_academic_topic_calls += 1
        elif name == "academic_get_papers":
            if self.research_academic_detail_calls >= _RESEARCH_ACADEMIC_DETAIL_LIMIT:
                return "academic_get_papers 已完成一次集中摘要读取；停止重复拉取并使用已有完整摘要"
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
        if name == "web_search":
            required_terms = [
                " ".join(str(term or "").split())
                for term in (arguments.get("required_terms") or [])[:3]
                if len(" ".join(str(term or "").split())) >= 2
            ]
            if not required_terms:
                return ToolMessage(
                    content=json.dumps(
                        {
                            "status": "missing_required_terms",
                            "message": (
                                "本次网页检索未执行。请从查询中选择 1-2 个不可丢失的核心实体或技术身份作为 "
                                "required_terms 后重试；不要把待证明结论或三个不同子问题设为必选锚点。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=str(request.tool_call.get("id") or ""),
                    name=name,
                )
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
        sources = {
            str(item["url"]).split("#", 1)[0].rstrip("/")
            for item in payload["results"]
            if isinstance(item, dict)
            and str(item.get("url") or "").startswith(("https://", "http://"))
            and item.get("title")
            and item.get("content")
        }
        authoritative_sources = {
            str(item["url"]).split("#", 1)[0].rstrip("/")
            for item in payload["results"]
            if isinstance(item, dict)
            and item.get("source_tier") == "authoritative"
            and str(item.get("url") or "").startswith(("https://", "http://"))
            and item.get("title")
            and item.get("content")
        }
        with self._research_lock:
            added = sources - self.research_sources
            self.research_sources.update(sources)
            self.research_authoritative_sources.update(authoritative_sources)
            self.research_no_progress = 0 if added else self.research_no_progress + 1
            if (
                len(self.research_sources) >= 12
                and len(self.research_authoritative_sources) >= 2
                and self.web_search_calls >= 6
            ):
                self.research_web_stop_reason = (
                    "已完成至少 6 次网页检索并取得 12 条带摘要的去重来源，"
                    "其中至少 2 条为一手或高权威来源，达到资料整理阈值"
                )
            elif self.research_no_progress >= 2:
                self.research_web_stop_reason = "连续两次网页检索无新增可用来源"

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
        if (
            self.research_mode
            and name == "academic_search"
            and isinstance(payload, dict)
            and isinstance(payload.get("results"), list)
            and payload["results"]
        ):
            with self._research_lock:
                self.research_academic_has_hits = True
        if status in {"disabled", "denied", "auth_failed", "rate_limited", "unavailable", "budget_exhausted"}:
            self.blocked_academic_tools.update(ACADEMIC_TOOL_NAMES)
        elif status in {"limit_reached", "configuration_changed", "in_progress"}:
            endpoint = payload.get("failed_endpoint")
            limited_tool = {
                "search": "academic_search",
                "title_search": "academic_search",
                "detail": "academic_get_papers",
                "references": "academic_get_references",
            }.get(endpoint, name)
            # 免费题录额度不控制 Pro 搜索和付费详情；服务仍可返回已有证据。
            if status != "limit_reached" or endpoint != "info":
                self.blocked_academic_tools.add(limited_tool)
