"""共享论文检索用例：配置热更新、有界重试、预算预占与证据投影。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from platform_core.config.options import aminer_api_opts
from platform_core.repositories.academic_retrieval_repository import AcademicRetrievalRepository
from platform_core.services.aminer_client import (
    AMinerClient,
    AMinerError,
    aminer_credential_scope,
    deduplicate_papers,
    normalize_paper,
)
from platform_core.storage.postgres.manager import pg_manager
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now_naive


ACADEMIC_RETRIEVAL_PROMPT = """# 学术检索与论文证据
科研技术问题、论文、研究进展、技术路线比较优先调用 academic_search，提取简短科研关键词，必要时分别使用中英文检索词。
用户要求论文证据或研究依据时，必须实际检索后再回答，不得只凭模型记忆直接生成带论文依据的结论；简短回答也适用。
仅发送公开科研概念；不要把完整会话、内部文档、客户或项目名称、能力画像原文发送给 AMiner。
已知论文标题使用 mode=title；主题发现使用 mode=topic。
先筛选候选；凡准备引用论文支持技术结论，必须先用 academic_get_papers(full_abstract=True) 获取拟引用论文的完整摘要。
若详情被预算或故障阻止，明确说明仅取得题录或部分摘要，收窄结论并标注证据缺口。仅列题录或参考文献关系时无需读取完整摘要。
深研围绕子问题补证，核心论文确需溯源时才调用 academic_get_references，最多扩展一层参考文献，不递归抓取文献树。
metadata 是题录，partial_abstract 是部分摘要，abstract 是完整摘要；都不是全文。
不能从标题推断实验证据，也不能声称已阅读全文。
实验数值、硬件型号、性能倍数和精确参数只能引用本轮实际取得内容明确支持的部分。
模型记忆与常识不算本轮取得的论文证据；未取到对应实验内容时应说明尚未核实，不得把它写成已查证事实。
技术路线的工程外推应标注为判断或待验证假设，不能借论文引用包装成论文已验证的结论。
参考文献是该论文引用的研究，不是后续引用者。被引档位只是辅助信息，不证明论断成立。
网页与 AMiner 找到的同一 DOI/论文 ID 只算一个独立来源。关键结论用不同原始研究或权威来源交叉核验。
结论紧邻引用使用 <cite source="$URL" type="url">$INDEX</cite>，只使用工具实际返回的来源；
模板中的 $URL 和 $INDEX 必须替换为实际来源 URL 和数字，不得输出占位符。没有对应来源的句子不添加虚假引用。
上下文压缩后仍保留论文 ID、DOI、来源和证据层级。
一般问题无需学术检索，非学术公开事实继续使用 web_search，内部事实使用授权知识库。
AMiner 返回 disabled/auth_failed/rate_limited/unavailable/budget_exhausted 时停止对此服务的重试或同义改写。
转用网页、知识库和已有证据完成回答。
limit_reached 表示当前接口额度用尽；不要反复调用该接口。配置更改或相同请求执行中时使用已有证据，不等待或循环尝试。
"""


async def test_aminer_connection(db, *, user_id: str | None = None, api_key: str | None = None) -> dict[str, Any]:
    """测试草稿或已保存凭证，使用免费标题搜索且不持久化输入。"""
    config = await aminer_api_opts.get(db)
    credentials = {
        "user_id": config["user_id"] if user_id is None else user_id.strip(),
        "api_key": api_key.strip() if api_key and api_key.strip() else config["api_key"],
    }
    if not credentials["user_id"] or not credentials["api_key"]:
        return {"status": "not_configured", "message": "请填写 AMiner 用户 ID 和 API Key"}
    try:
        await AMinerClient(credentials).request(
            "title_search", {"title": "Attention Is All You Need", "page": 1, "size": 1}
        )
    except AMinerError as exc:
        return {"status": exc.status, "message": str(exc)}
    return {"status": "ok", "message": "连接正常，免费标题搜索鉴权成功；付费接口权限以实际调用结果为准"}


class AcademicRetrievalService:
    """由可信运行上下文发起检索，不允许模型指定用户、根 Run 或凭证。"""

    def __init__(self, context, *, session_factory=None, transport=None):
        self.context = context
        self.session_factory = session_factory or pg_manager.get_async_session_context
        self.transport = transport

    async def search(
        self, query: str, *, mode: str = "topic", limit: int = 10, order: str = "relevance", page: int = 1
    ) -> dict:
        """发现论文并批量补充部分摘要，按需留给后续详情工具取证。"""
        payload = {"page": min(page, 10) if mode == "title" else page - 1, "size": limit}
        payload["title" if mode == "title" else "keyword"] = query.strip()
        if mode != "title" and order != "relevance":
            payload["order"] = "year" if order == "recent" else "n_citation"
        found = await self._request("title_search" if mode == "title" else "search", payload)
        if found["status"] != "ok":
            return self._result(found, query=query)
        candidates = [item for item in found["data"] if isinstance(item, dict) and item.get("id")][:limit]
        if not candidates:
            return self._result(found, query=query)
        info = await self._request("info", {"ids": list(dict.fromkeys(str(item["id"]) for item in candidates))})
        summaries = {str(item.get("id")): item for item in info.get("data", []) if isinstance(item, dict)}
        papers = []
        for candidate in candidates:
            item = {**candidate, **summaries.get(str(candidate["id"]), {})}
            papers.append(normalize_paper(item, retrieved_at=info.get("retrieved_at") or found.get("retrieved_at")))
        result = self._result(found, query=query, papers=papers)
        if any(paper["content_level"] != "abstract" for paper in result["results"]):
            result["retrieval_guidance"] = (
                "这是论文发现结果，含题录或部分摘要。先筛选相关候选，引用论文支持技术结论前调用 "
                "academic_get_papers(paper_ids=[拟引用的实际 ID], full_abstract=True) 读取完整摘要；"
                "若详情不可用，明确证据层级与缺口，只能依据已取得内容给出有限结论。"
            )
        if info["status"] != "ok":
            result.update(
                status="partial", aminer_status=info["status"], message=f"已找到论文，摘要补充未完成：{info['message']}"
            )
        return result

    async def get_papers(self, paper_ids: list[str], *, full_abstract: bool = True) -> dict:
        """先批量获取题录，再仅为选定论文读取完整摘要。"""
        ids = list(dict.fromkeys(paper_ids))
        info = await self._request("info", {"ids": ids})
        if info["status"] != "ok":
            return self._result(info)
        papers_by_id = {str(item.get("id")): item for item in info["data"] if isinstance(item, dict)}
        errors = []
        retrieved_times = {}
        if full_abstract:
            for paper_id in ids:
                detail = await self._request("detail", {"id": paper_id})
                if detail["status"] != "ok":
                    errors.append(detail)
                    break
                for item in detail["data"]:
                    if isinstance(item, dict) and str(item.get("id")) == paper_id:
                        retrieved_times[paper_id] = detail.get("retrieved_at")
                        papers_by_id[paper_id] = {**papers_by_id.get(paper_id, {}), **item}
        papers = [
            normalize_paper(
                papers_by_id[paper_id], retrieved_at=retrieved_times.get(paper_id) or info.get("retrieved_at")
            )
            for paper_id in ids
            if paper_id in papers_by_id
        ]
        result = self._result(info, papers=papers)
        if errors:
            result.update(
                status="partial",
                aminer_status=errors[0]["status"],
                message=f"保留已有题录或摘要，详情补充未完成：{errors[0]['message']}",
            )
        return result

    async def get_references(self, paper_id: str, *, limit: int = 20) -> dict:
        """只返回核心论文的参考文献，不展开后续引用者或递归文献树。"""
        response = await self._request("references", {"id": paper_id})
        references = []
        for item in response.get("data", []):
            if isinstance(item, dict) and isinstance(item.get("cited"), list):
                references.extend(value for value in item["cited"] if isinstance(value, dict))
        papers = [normalize_paper(item, retrieved_at=response.get("retrieved_at")) for item in references[:limit]]
        return {
            **self._result(response, papers=papers),
            "paper_id": paper_id,
            "relation": "references",
            "one_hop": True,
        }

    async def _request(self, endpoint: str, payload: dict) -> dict:
        """每次发送前重新检查配置并预占；成功缓存与已执行请求幂等复用。"""
        uid = str(getattr(self.context, "uid", "") or "")
        run_id = str(getattr(self.context, "run_id", "") or "")
        if not uid or not run_id:
            return {"status": "denied", "message": "学术检索缺少可信运行上下文"}
        for attempt_no in (1, 2):
            async with self.session_factory() as db:
                config = await aminer_api_opts.get(db)
                if not config["enabled"]:
                    return {"status": "disabled", "message": "AMiner 学术检索已停用"}
                scope = aminer_credential_scope(config)
                request_key = hashlib.sha256(
                    json.dumps([scope, endpoint, payload], sort_keys=True).encode()
                ).hexdigest()
                repo = AcademicRetrievalRepository(db)
                try:
                    root = await repo.resolve_root(
                        run_id=run_id,
                        uid=uid,
                        worker_id=getattr(self.context, "worker_id", None),
                    )
                except ValueError as exc:
                    return {"status": "denied", "message": str(exc)}
                reservation = await repo.reserve(
                    root_run_id=root.id,
                    run_id=run_id,
                    uid=uid,
                    endpoint=endpoint,
                    request_key=request_key,
                    attempt_no=attempt_no,
                    credential_scope=scope,
                )
                await db.commit()
            if reservation.result is not None:
                result = {**reservation.result, "cached": reservation.cached}
            else:
                try:
                    data = await AMinerClient(reservation.credentials, transport=self.transport).request(
                        endpoint, payload
                    )
                    result = {
                        "status": "ok",
                        "data": data["data"],
                        "total": data.get("total"),
                        "retrieved_at": format_utc_datetime(utc_now_naive()),
                        "log_id": data.get("log_id"),
                        "cached": False,
                    }
                except AMinerError as exc:
                    result = {"status": exc.status, "message": str(exc), "retryable": exc.retryable}
                async with self.session_factory() as db:
                    await AcademicRetrievalRepository(db).finish(reservation.call_id, result)
                    await db.commit()
            if not result.get("retryable") or attempt_no == 2:
                return result
            await asyncio.sleep(0.25)
        raise AssertionError("有界重试未返回结果")

    @staticmethod
    def _result(response: dict, *, query: str = "", papers: list[dict] | None = None) -> dict:
        """把供应商结构投影为工具与前端共用的论文证据格式。"""
        if papers is None:
            papers = [
                normalize_paper(item, retrieved_at=response.get("retrieved_at"))
                for item in response.get("data", [])
                if isinstance(item, dict)
            ]
        return {
            "status": response["status"],
            "aminer_status": response["status"],
            "query": query,
            "source": "aminer",
            "results": deduplicate_papers(papers),
            "evidence_notice": (
                "只依据本次返回的 content 支持结论。题录、部分摘要、完整摘要均不是论文全文或实验表格。"
                "没有出现在 content 中的实验数值、硬件型号和测评细节不得作为已核实事实引用，"
                "即使你从模型记忆中知道它们；需要这些信息时另取原始证据，否则说明本轮未核实。"
            ),
            "cached": response.get("cached", False),
            "message": response.get("message", ""),
            "total": response.get("total"),
        }
