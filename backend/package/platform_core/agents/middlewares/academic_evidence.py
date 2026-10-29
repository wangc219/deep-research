"""把学术引用约束落实到终态校验，失败时有界重写而不伪造来源。"""

import json
import re
import threading
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from platform_core.services.aminer_client import ACADEMIC_TOOL_NAMES


class _Citations(HTMLParser):
    """读取引用属性，兼容单双引号、属性次序与 HTML 转义。"""

    def __init__(self):
        """初始化本轮引用地址列表。"""
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        """只读取引用来源属性，文件引用保持原有处理方式。"""
        if tag != "cite":
            return
        attributes = dict(attrs)
        source = (attributes.get("source") or "").strip()
        if attributes.get("type") != "file" or source.startswith(("http://", "https://")):
            if not source.startswith(("http://", "https://")) and "url" in source.casefold():
                return
            self.urls.append(source)


def _canonical_url(value: str) -> str:
    """归一化同一公开来源的安全 URL 变体，不跨域合并。"""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return value.strip()
    host = parsed.hostname.casefold()
    if host == "dx.doi.org":
        host = "doi.org"
    port = f":{parsed.port}" if parsed.port else ""
    path = unquote(parsed.path).rstrip("/") or "/"
    if host == "doi.org":
        path = path.casefold()
    return urlunsplit(("https", host + port, path, parsed.query, ""))


def _result_payload(result: Any) -> dict[str, Any] | None:
    """读取工具返回的 JSON 对象。"""
    content = result.content if isinstance(result, ToolMessage) else getattr(result, "content", result)
    if not isinstance(content, str):
        return content if isinstance(content, dict) else None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _subagent_result_text(payload: dict[str, Any]) -> str:
    """读取 subagent_await 的平面或嵌套完成输出，不把整个字典字符串化。"""
    value: Any = payload.get("result")
    for _ in range(4):
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""
        output = value.get("output")
        if isinstance(output, str):
            return output
        value = value.get("result")
    return ""


def _discloses_abstract_gap(text: str) -> bool:
    """识别模型已明确降级证据层级的交付。"""
    normalized = text.casefold()
    return any(
        marker in normalized
        for marker in (
            "未取得完整摘要",
            "仅取得题录",
            "部分摘要",
            "完整摘要未取得",
            "尚待核实",
            "证据缺口",
            "full abstract was not available",
            "metadata only",
            "partial abstract",
        )
    )


def _strip_unknown_citations(text: str, sources: dict[str, str]) -> str:
    """降级交付时只移除未登记的 cite 标签，保留原正文。"""

    def replace(match: re.Match[str]) -> str:
        source = re.search(r"\bsource\s*=\s*(['\"])(.*?)\1", match.group("attrs"), flags=re.I)
        if source and _canonical_url(source.group(2)) in sources:
            return match.group(0)
        return ""

    return re.sub(
        r"<cite\b(?P<attrs>[^>]*)>.*?</cite\s*>",
        replace,
        text,
        flags=re.I | re.S,
    )


class AcademicEvidenceMiddleware(AgentMiddleware[Any, Any, Any]):
    """学术检索后的最终答复必须引用实际来源，最多允许两次纠正。"""

    def __init__(self, *, graceful_fallback: bool = False):
        self.graceful_fallback = graceful_fallback
        self._lock = threading.Lock()
        self._sources: dict[str, str] = {}
        self._papers: dict[str, dict[str, Any]] = {}
        self._topic_papers: set[str] = set()
        self._abstract_attempts: set[str] = set()

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Any]) -> Any:
        """工具完成时追加证据谱系，避免长上下文压缩后丢失真实来源。"""
        result = handler(request)
        self._record_tool_result(request.tool_call, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        """异步工具链路使用同一追加式证据账本。"""
        result = await handler(request)
        self._record_tool_result(request.tool_call, result)
        return result

    def _record_tool_result(self, call: dict[str, Any], result: Any) -> None:
        name = str(call.get("name") or "")
        payload = _result_payload(result)
        if payload is None:
            return
        if name == "subagent_await":
            citations = _Citations()
            citations.feed(_subagent_result_text(payload))
            with self._lock:
                for url in citations.urls:
                    self._sources.setdefault(_canonical_url(url), url)
            return
        if name not in ACADEMIC_TOOL_NAMES | {"web_search"}:
            return
        arguments = dict(call.get("args") or {})
        with self._lock:
            if name == "academic_get_papers" and arguments.get("full_abstract", True):
                self._abstract_attempts.update(arguments.get("paper_ids") or [])
            for item in payload.get("results") or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str) or not url:
                    continue
                canonical = _canonical_url(url)
                self._sources.setdefault(canonical, url)
                if name not in ACADEMIC_TOOL_NAMES or not item.get("id"):
                    continue
                previous = self._papers.get(canonical)
                if previous is None or item.get("content_level") == "abstract":
                    self._papers[canonical] = item
                discovery_mode = (
                    arguments.get("academic_mode", "precision")
                    if name == "parallel_research_search"
                    else arguments.get("mode", "precision")
                )
                if name in {"academic_search", "parallel_research_search"} and discovery_mode in {
                    "precision",
                    "topic",
                    "semantic",
                }:
                    self._topic_papers.add(item["id"])

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        """仅检查本轮实际执行过的工具结果，不把用户文本当作来源证明。"""
        messages = state["messages"]
        answer = messages[-1]
        if not isinstance(answer, AIMessage) or answer.tool_calls or not answer.text.strip():
            return None
        start = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if isinstance(messages[i], HumanMessage)
                and not messages[i].additional_kwargs.get("academic_evidence_recovery")
                and not messages[i].additional_kwargs.get("model_output_recovery")
            ),
            0,
        )
        turn = messages[start:]
        calls = {call["id"]: call for message in turn if isinstance(message, AIMessage) for call in message.tool_calls}
        with self._lock:
            papers = dict(self._papers)
            sources = dict(self._sources)
            topic_papers = set(self._topic_papers)
            abstract_attempts = set(self._abstract_attempts)
        for message in turn:
            if not isinstance(message, ToolMessage):
                continue
            call = calls.get(message.tool_call_id)
            if not call:
                continue
            if call["name"] == "subagent_await":
                result = _result_payload(message)
                if result is not None:
                    citations = _Citations()
                    citations.feed(_subagent_result_text(result))
                    for url in citations.urls:
                        sources.setdefault(_canonical_url(url), url)
                continue
            if call["name"] not in ACADEMIC_TOOL_NAMES | {"web_search"}:
                continue
            result = _result_payload(message)
            if result is None:
                continue
            name, arguments = call["name"], call["args"]
            if name == "academic_get_papers" and arguments.get("full_abstract", True):
                abstract_attempts.update(arguments.get("paper_ids") or [])
            for item in result.get("results") or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if isinstance(url, str) and url:
                    canonical = _canonical_url(url)
                    sources.setdefault(canonical, url)
                if name not in ACADEMIC_TOOL_NAMES or not isinstance(url, str) or not url or not item.get("id"):
                    continue
                previous = papers.get(canonical)
                if previous is None or item.get("content_level") == "abstract":
                    papers[canonical] = item
                discovery_mode = (
                    arguments.get("academic_mode", "precision")
                    if name == "parallel_research_search"
                    else arguments.get("mode", "precision")
                )
                if name in {"academic_search", "parallel_research_search"} and discovery_mode in {
                    "precision",
                    "topic",
                    "semantic",
                }:
                    topic_papers.add(item["id"])
        if not papers:
            return None
        citations = _Citations()
        citations.feed(answer.text)
        problems = []
        if not citations.urls:
            problems.append('缺少可追溯的 <cite source="实际URL" type="url">数字</cite> 引用')
        if any(_canonical_url(url) not in sources for url in citations.urls):
            problems.append("引用了本轮工具未返回的来源，不能自行改写或补造链接")
        missing = {
            papers[_canonical_url(url)]["id"]
            for url in citations.urls
            if _canonical_url(url) in papers
            and papers[_canonical_url(url)]["id"] in topic_papers
            and papers[_canonical_url(url)].get("content_level") != "abstract"
            and papers[_canonical_url(url)]["id"] not in abstract_attempts
        }
        if missing and not _discloses_abstract_gap(answer.text):
            problems.append(
                "主题发现的拟引用论文尚未读取完整摘要；先用 academic_get_papers(full_abstract=True) 读取 "
                + ", ".join(sorted(missing))
            )
        if not problems:
            return None
        recoveries = sum(
            isinstance(message, HumanMessage) and bool(message.additional_kwargs.get("academic_evidence_recovery"))
            for message in turn
        )
        if recoveries >= 2 and self.graceful_fallback:
            fallback = _strip_unknown_citations(answer.text, sources).rstrip()
            if missing:
                fallback += "\n\n[证据边界：部分论文仅取得题录或部分摘要，相关结论作为待核验线索，不视为全文证实。]"
            fallback += "\n\n[引用校验已降级交付：未能确认的引用不作为本证据包的事实依据。]"
            # 保留供应商 Model lifecycle 的 message id 与响应元数据。Run 终态持久化
            # 依靠该 id 将最终 State 投影回本次模型调用；生成一个无 id 的新消息会让
            # 已完成的探索员在最后一步被误判为“最终输出无法关联”。
            replacement = answer.model_copy(
                update={
                    "content": fallback,
                    "additional_kwargs": {
                        **dict(answer.additional_kwargs or {}),
                        "academic_evidence_graceful_fallback": True,
                    },
                }
            )
            return {"messages": [replacement]}
        if recoveries >= 2:
            raise RuntimeError("学术证据校验未通过，本轮回答未完成：" + "；".join(problems))
        allowed = "\n".join(
            f'{item.get("title", item["id"])}：<cite source="{sources.get(url, url)}" type="url">{index}</cite>'
            for index, (url, item) in enumerate(list(papers.items())[:24], start=1)
        )
        return {
            "messages": [
                HumanMessage(
                    "上一答复未通过学术证据校验："
                    + "；".join(problems)
                    + "。请依据已取得内容修正，不增加未经验证的论断或来源。详情读取失败时收窄结论并明确证据缺口。\n"
                    + "以下是本轮已取得论文来源的可复制清单（用于纠错，不代表只有这些来源；不得据此缩减已验证范围）：\n"
                    + allowed,
                    additional_kwargs={"academic_evidence_recovery": True},
                )
            ],
            "jump_to": "model",
        }

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        """异步图沿用相同的来源和有界恢复规则。"""
        return self.after_model(state, runtime)
