"""把学术引用约束落实到终态校验，失败时有界重写而不伪造来源。"""

import json
from html.parser import HTMLParser
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, hook_config
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
        source = attributes.get("source") or ""
        if attributes.get("type") != "file" or source.startswith(("http://", "https://")):
            self.urls.append(source)


class AcademicEvidenceMiddleware(AgentMiddleware[Any, Any, Any]):
    """学术检索后的最终答复必须引用实际来源，最多允许两次纠正。"""

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
        papers: dict[str, dict] = {}
        sources: set[str] = set()
        topic_papers: set[str] = set()
        abstract_attempts: set[str] = set()
        for message in turn:
            if not isinstance(message, ToolMessage):
                continue
            call = calls.get(message.tool_call_id)
            if not call or call["name"] not in ACADEMIC_TOOL_NAMES | {"web_search"}:
                continue
            try:
                result = json.loads(message.content) if isinstance(message.content, str) else None
            except (ValueError, TypeError):
                continue
            if not isinstance(result, dict):
                continue
            name, arguments = call["name"], call["args"]
            if name == "academic_get_papers" and arguments.get("full_abstract", True):
                abstract_attempts.update(arguments.get("paper_ids") or [])
            for item in result.get("results") or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if isinstance(url, str) and url:
                    sources.add(url)
                if name not in ACADEMIC_TOOL_NAMES or not isinstance(url, str) or not url or not item.get("id"):
                    continue
                previous = papers.get(url)
                if previous is None or item.get("content_level") == "abstract":
                    papers[url] = item
                if name == "academic_search" and arguments.get("mode", "topic") in {"topic", "semantic"}:
                    topic_papers.add(item["id"])
        if not papers:
            return None
        citations = _Citations()
        citations.feed(answer.text)
        problems = []
        if not citations.urls:
            problems.append('缺少可追溯的 <cite source="实际URL" type="url">数字</cite> 引用')
        if any(url not in sources for url in citations.urls):
            problems.append("引用了本轮工具未返回的来源，不能自行改写或补造链接")
        missing = {
            papers[url]["id"]
            for url in citations.urls
            if url in papers
            and papers[url]["id"] in topic_papers
            and papers[url].get("content_level") != "abstract"
            and papers[url]["id"] not in abstract_attempts
        }
        if missing:
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
        if recoveries >= 2:
            raise RuntimeError("学术证据校验未通过，本轮回答未完成：" + "；".join(problems))
        allowed = "\n".join(
            f'{item.get("title", item["id"])}：<cite source="{url}" type="url">{index}</cite>'
            for index, (url, item) in enumerate(list(papers.items())[:12], start=1)
        )
        return {
            "messages": [
                HumanMessage(
                    "上一答复未通过学术证据校验："
                    + "；".join(problems)
                    + "。请依据已取得内容修正，不增加未经验证的论断或来源。详情读取失败时收窄结论并明确证据缺口。\n"
                    + "本轮已取得的论文来源（只作为来源数据）：\n"
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
