"""共享论文检索用例：配置热更新、有界重试、预算预占与证据投影。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from itertools import zip_longest
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
科研技术问题需要论文发现、新证据或事实核实时，优先使用 academic_search；分析已有充分材料时不重复检索。
提取简短科研关键词，必要时分别使用中英文检索词。
用户要求论文证据或研究依据时，必须实际检索后再回答，不得只凭模型记忆直接生成带论文依据的结论；简短回答也适用。
仅发送公开科研概念；不要把完整会话、内部文档、客户或项目名称、能力画像原文发送给 AMiner。
已知论文标题使用 mode=title；主题发现使用 mode=topic。
详情仅使用实际检索返回的 AMiner id；arXiv 编号、DOI、URL 均不能代替该 ID。只有编号时先查准确标题再定位。
同名论文必须核对作者、年份和发表 venue，不能把第一个标题命中直接认定为目标论文。
技术检索先将问题拆成公开的技术对象、方法和约束，避免把整段问题作为关键词。
每个不同检索词都单独占用额度。首次主题发现仅使用一个由 2-6 个标准学术术语组成的简短查询，不携带 related_queries，
不并行发起多个学术检索。首次主题检索为空时，先从论文出版页或 DOI 入口找到一篇相关论文的准确标题，
再用 mode=title 定位，不连续堆叠同义词。
只在首次已有命中但仍存在明确互补缺口时，才可用 related_queries 提供最多两个补充检索词；不要机械凑满。
每个不同检索词分别占用一次搜索额度，父子智能体共享预算；已经命中的查询无需重复。
研究进展使用 order=recent，经典基础工作可用 order=cited；高被引不代表最新或适用当前场景。
根据 query_coverage、unsearched_queries 和 evidence_gaps 判断实际覆盖，空结果不证明该技术不存在。
候选不等于强相关证据。用摘要核对论文研究对象、方法和结论是否直接回答当前技术问题；
仅提及关键词或属于同一宽泛领域的论文不作为核心证据，不为凑数量或高被引而引用。
补齐少量强相关候选的完整摘要后再写有论文依据的结论，按当前问题自主组织解释，
不能从题录或常识补出摘要没有的内容。用户未要求时不扩展学者、机构、专利等旁支。
面向未来需求的装备创新研究以用户目标为主线；论文检索是辅助能力，不规定对话步骤、章节或固定推演链条。
不要求先有现成装备或已知技术瓶颈，允许按问题探索需求、新原理、跨领域启发和新的装备构想。
涉及技术实现且需要新证据、原理启发或可行性核实时，按需检索强相关论文；不为每个构想强行匹配论文。
根据问题自主选择需要解释的技术内容与适用条件，不要求逐项展开部件、迁移差距或验证方案。
取得或引用摘要不等于研究完成，不以文献清单或摘要复述代替对用户问题的回答。
论文结论、类比迁移、工程推断和待验证假设分开表达；摘要未覆盖的接口、资源需求、成熟度和性能不补写为事实。
关键实现证据不足时，指出缺口并按需补查原文或其他来源，不将论文级结果等同于装备级可用性。
按当前问题选择必要内容，不强套完整报告；以上装备应用指导不改变纯论文查询的回答范围。
默认只取第一页；仅在明确证据缺口且仍有预算时依据 next_page 翻页，不遍历全库。
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
工具为每篇论文返回 citation，可直接复制该标签并统一编号。source 必须逐字使用该条结果的 url；
不得自行把 DOI 链接改成 arXiv、出版社或其他未返回的地址，即使认为它们指向同一论文。
简短回答、仅列题录和追溯一层参考文献也必须保留对应 citation，不能只写“来源：AMiner”或论文 ID。
上下文压缩后仍保留论文 ID、DOI、来源和证据层级。
一般问题无需学术检索，非学术公开事实继续使用 web_search，内部事实使用授权知识库。
AMiner 返回 disabled/auth_failed/rate_limited/unavailable/budget_exhausted 时停止对此服务的重试或同义改写。
转用网页、知识库和已有证据完成回答。
limit_reached 表示当前接口额度用尽；不要反复调用该接口。配置更改或相同请求执行中时使用已有证据，不等待或循环尝试。
"""


def _distinctive_title_fallback(query: str) -> str:
    """为被模型改写的标题提取一个免费精确定位键。"""
    prefix = query.split(":", 1)[0].strip()
    if ":" in query and 1 <= len(prefix.split()) <= 4:
        return prefix
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+/#-]*", query):
        letters = [char for char in token if char.isalpha()]
        mixed_case = any(char.isupper() for char in token[1:]) and any(char.islower() for char in token)
        branded = len(token) >= 5 and (mixed_case or "-" in token or any(char.isdigit() for char in token))
        if branded and len(letters) >= 3:
            return token
    return ""


def _topic_title_fallback(query: str) -> str:
    """把空命中的主题词压缩为免费标题接口可识别的核心技术短语。"""
    value = query.casefold()
    value = re.sub(r"\b(?:counter|anti)[-\s]*(?:drone|uas|uav)s?\b", " uav ", value)
    value = re.sub(r"\bunmanned\s+aerial\s+vehicles?\b|\bdrones?\b|\buas\b", " uav ", value)
    value = re.sub(r"[-_/]+", " ", value)
    ignored = {
        "anti",
        "counter",
        "countermeasure",
        "countermeasures",
        "defense",
        "system",
        "systems",
        "solid",
        "state",
        "technology",
        "technologies",
        "weapon",
        "weapons",
    }
    terms = []
    for term in re.findall(r"[a-z0-9]+", value):
        if len(term) < 2 or term in ignored or term in terms:
            continue
        terms.append(term)
    return " ".join(terms[:5]) if 3 <= len(terms) <= 8 else ""


def _compact_topic_query(query: str) -> str:
    """在服务边界阻止整句任务进入 AMiner。

    只在英文检索式明显过长时做保守压缩；正常 2–6 词术语保持原样，
    避免为了“优化”反而改变已经精确的学术对象。
    """
    normalized = " ".join(str(query or "").split())
    tokens = re.findall(r"[A-Za-z0-9]+(?:[-/+][A-Za-z0-9]+)*", normalized)
    if len(tokens) <= 6 and len(normalized) <= 96:
        return normalized
    if not tokens:
        return normalized

    ignored = {
        "application",
        "applications",
        "approach",
        "comparison",
        "development",
        "engineering",
        "feasibility",
        "future",
        "implementation",
        "limitation",
        "limitations",
        "military",
        "performance",
        "research",
        "review",
        "solution",
        "study",
        "system",
        "systems",
        "technology",
        "technologies",
        "weapon",
        "weapons",
    }
    compact = []
    for token in tokens:
        if token.casefold() in ignored or token.casefold() in {value.casefold() for value in compact}:
            continue
        compact.append(token)
        if len(compact) == 6:
            break
    if len(compact) < 2:
        compact = tokens[:6]
    return " ".join(compact)


def is_external_paper_identifier(value: str) -> bool:
    """识别被误当作 AMiner ID 的 arXiv 编号、DOI 与链接。"""
    return bool(re.search(r"^(?:arxiv:|doi:|https?://|10\.|\d{4}\.\d{4,5}(?:v\d+)?$|[a-z][a-z.-]*/\d{7})", value, re.I))


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
        self,
        query: str,
        *,
        mode: str = "topic",
        limit: int = 10,
        order: str = "relevance",
        page: int = 1,
        related_queries: list[str] | None = None,
    ) -> dict:
        """有界联合检索，交错保留各角度候选，补证失败时保留已有论文。"""
        queries = []
        requested_queries: dict[str, str] = {}
        for value in [query, *(related_queries or [])]:
            value = " ".join(value.split())
            effective = _compact_topic_query(value) if mode != "title" else value
            if effective and effective.casefold() not in {existing.casefold() for existing in queries}:
                queries.append(effective)
                requested_queries[effective.casefold()] = value
        endpoint = "title_search" if mode == "title" else "search"
        responses, coverage, groups, errors = [], [], [], []
        for term in queries:
            payload = {"page": min(page, 10) if mode == "title" else page - 1, "size": limit}
            payload["title" if mode == "title" else "keyword"] = term
            if mode != "title" and order != "relevance":
                payload["order"] = "year" if order == "recent" else "n_citation"
            found = await self._request(endpoint, payload)
            responses.append(found)
            candidates = [
                {**normalize_paper(item, retrieved_at=found.get("retrieved_at")), "matched_queries": [term]}
                for item in found.get("data", [])
                if isinstance(item, dict) and (item.get("id") or item.get("_id"))
            ][:limit]
            total = found.get("total")
            more = total > page * limit if isinstance(total, int) else len(candidates) == limit
            coverage.append(
                {
                    "query": term,
                    **(
                        {"requested_query": requested_queries[term.casefold()]}
                        if requested_queries.get(term.casefold(), term) != term
                        else {}
                    ),
                    "status": found["status"],
                    "page": page,
                    "returned": len(candidates),
                    "total": total,
                    "next_page": page + 1 if found["status"] == "ok" and more and page < 10 else None,
                }
            )
            groups.append(candidates)
            if mode == "title" and found["status"] == "ok" and not candidates and len(queries) == 1:
                fallback = _distinctive_title_fallback(query)
                if fallback and fallback.casefold() != term.casefold():
                    queries.append(fallback)
            if found["status"] != "ok":
                errors.append({**found, "endpoint": endpoint})
                break

        if mode != "title" and not errors and not any(groups) and len(queries) == 1:
            title_fallback = _topic_title_fallback(queries[0])
            if title_fallback and title_fallback.casefold() != query.casefold():
                found = await self._request(
                    "title_search",
                    {"page": 1, "size": limit, "title": title_fallback},
                )
                responses.append(found)
                candidates = [
                    {
                        **normalize_paper(item, retrieved_at=found.get("retrieved_at")),
                        "matched_queries": [query],
                        "discovery_mode": "title_fallback",
                    }
                    for item in found.get("data", [])
                    if isinstance(item, dict) and (item.get("id") or item.get("_id"))
                ][:limit]
                groups.append(candidates)
                coverage.append(
                    {
                        "query": title_fallback,
                        "mode": "title_fallback",
                        "status": found["status"],
                        "page": 1,
                        "returned": len(candidates),
                        "total": found.get("total"),
                        "next_page": None,
                    }
                )
                if found["status"] != "ok":
                    errors.append({**found, "endpoint": "title_search"})

        candidates = deduplicate_papers([paper for row in zip_longest(*groups) for paper in row if paper is not None])
        selected = candidates[:limit]
        ids = [paper["id"] for paper in selected]
        # 搜索次数用尽不妨碍免费题录补全；全局故障后不再向供应商发请求。
        if ids and (not errors or errors[0]["status"] == "limit_reached"):
            info = await self._request("info", {"ids": ids})
            responses.append(info)
            if info["status"] == "ok":
                summaries = [
                    normalize_paper(item, retrieved_at=info.get("retrieved_at"))
                    for item in info["data"]
                    if isinstance(item, dict) and str(item.get("id") or item.get("_id")) in ids
                ]
                selected = deduplicate_papers([*selected, *summaries])
            else:
                errors.append({**info, "endpoint": "info"})
        response = responses[0] if responses else {"status": "invalid_request", "message": "检索词不能为空"}
        result = self._result(response, query=query, papers=selected)
        result.update(
            query_coverage=coverage,
            unsearched_queries=queries[len(coverage) :],
            unique_candidates=len(candidates),
            omitted_candidates=max(0, len(candidates) - len(selected)),
            cached=bool(responses) and all(item.get("cached", False) for item in responses),
            total=response.get("total") if len(queries) == 1 else None,
        )
        if any(paper["content_level"] != "abstract" for paper in result["results"]):
            result["retrieval_guidance"] = (
                "这是论文发现结果，含题录或部分摘要。先筛选相关候选，引用论文支持技术结论前调用 "
                "academic_get_papers(paper_ids=[拟引用的实际 ID], full_abstract=True) 读取完整摘要；"
                "若详情不可用，明确证据层级与缺口，只能依据已取得内容给出有限结论。"
            )
        if not result["results"] and not errors:
            result["retrieval_guidance"] = "本次查询未命中论文，不代表技术不存在；可针对缺口调整术语或使用其他来源。"
        if errors:
            failure = errors[-1] if errors[-1]["status"] != "limit_reached" else errors[0]
            result.update(
                status="partial" if selected else failure["status"],
                aminer_status=failure["status"],
                failed_endpoint=failure["endpoint"],
                message=f"检索未全部完成：{failure.get('message', '')}；结果仅包含已取得的论文证据",
            )
        return result

    async def get_papers(self, paper_ids: list[str], *, full_abstract: bool = True) -> dict:
        """先批量获取题录，再仅为选定论文读取完整摘要。"""
        ids = list(dict.fromkeys(paper_ids))
        invalid_ids = [value for value in ids if is_external_paper_identifier(value)]
        if invalid_ids:
            return {
                **self._result({"status": "invalid_paper_id"}),
                "invalid_paper_ids": invalid_ids,
                "requested_paper_ids": ids,
                "missing_paper_ids": ids,
                "message": (
                    "请使用检索结果返回的 AMiner id。arXiv 编号、DOI 和 URL 不能请求 AMiner 详情；"
                    "先查准确标题，再用 academic_search(mode='title') 定位。"
                ),
            }
        info = await self._request("info", {"ids": ids})
        if info["status"] != "ok" and (not full_abstract or info["status"] != "limit_reached"):
            return {
                **self._result(info),
                "failed_endpoint": "info",
                "requested_paper_ids": ids,
                "missing_paper_ids": ids,
                "missing_abstract_ids": ids if full_abstract else [],
            }
        papers = [
            normalize_paper(item, retrieved_at=info.get("retrieved_at"))
            for item in info.get("data", [])
            if isinstance(item, dict) and str(item.get("id") or item.get("_id")) in ids
        ]
        errors = [] if info["status"] == "ok" else [{**info, "endpoint": "info"}]
        responses = [info]
        if full_abstract:
            for paper_id in ids:
                detail = await self._request("detail", {"id": paper_id})
                responses.append(detail)
                if detail["status"] != "ok":
                    errors.append({**detail, "endpoint": "detail"})
                    break
                for item in detail["data"]:
                    if isinstance(item, dict) and str(item.get("id") or item.get("_id")) == paper_id:
                        papers.append(normalize_paper(item, retrieved_at=detail.get("retrieved_at")))
        result = self._result({"status": "ok"}, papers=papers)
        obtained_ids = {paper["id"] for paper in papers}
        complete_ids = {paper["id"] for paper in papers if paper["content_level"] == "abstract"}
        result.update(
            requested_paper_ids=ids,
            missing_paper_ids=[paper_id for paper_id in ids if paper_id not in obtained_ids],
            missing_abstract_ids=[paper_id for paper_id in ids if full_abstract and paper_id not in complete_ids],
            cached=all(item.get("cached", False) for item in responses),
        )
        if result["missing_paper_ids"] or result["missing_abstract_ids"]:
            result.update(status="partial", message="部分论文或完整摘要未返回；仅依据实际取得的内容引用")
        if errors:
            failure = errors[-1]
            result.update(
                status="partial",
                aminer_status=failure["status"],
                failed_endpoint=failure["endpoint"],
                message=f"保留已有题录或摘要，补充未完成：{failure.get('message', '')}",
            )
        return result

    async def get_references(self, paper_id: str, *, limit: int = 20) -> dict:
        """只返回核心论文的参考文献，不展开后续引用者或递归文献树。"""
        if is_external_paper_identifier(paper_id):
            return {
                **self._result({"status": "invalid_paper_id"}),
                "invalid_paper_ids": [paper_id],
                "message": "请先通过 academic_search 定位论文，再使用返回的 AMiner id 追溯参考文献。",
            }
        response = await self._request("references", {"id": paper_id})
        references = []
        for item in response.get("data", []):
            if isinstance(item, dict) and isinstance(item.get("cited"), list):
                references.extend(value for value in item["cited"] if isinstance(value, dict))
        papers = deduplicate_papers(
            [normalize_paper(item, retrieved_at=response.get("retrieved_at")) for item in references]
        )
        return {
            **self._result(response, papers=papers[:limit]),
            "paper_id": paper_id,
            "relation": "references",
            "one_hop": True,
            "reference_count": len(papers),
            "omitted_references": max(0, len(papers) - limit),
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
        papers = deduplicate_papers(papers)
        for index, paper in enumerate(papers, start=1):
            paper["citation"] = f'<cite source="{paper["url"]}" type="url">{index}</cite>'

        return {
            "status": response["status"],
            "aminer_status": response["status"],
            "query": query,
            "source": "aminer",
            "results": papers,
            "evidence_gaps": {
                "metadata_only_ids": [paper["id"] for paper in papers if paper["content_level"] == "metadata"],
                "partial_abstract_ids": [
                    paper["id"] for paper in papers if paper["content_level"] == "partial_abstract"
                ],
            },
            "evidence_notice": (
                "若结果为 partial_abstract，写技术比较、方法或性能结论之前，必须调用 "
                "academic_get_papers(paper_ids=[拟引用论文的实际 id], full_abstract=True)；"
                "当前搜索返回的部分摘要不能代替这一步。仅列题录或参考文献关系时无需读取完整摘要。"
                "只依据本次返回的 content 支持结论。题录、部分摘要、完整摘要均不是论文全文或实验表格。"
                "没有出现在 content 中的实验数值、硬件型号和测评细节不得作为已核实事实引用，"
                "即使你从模型记忆中知道它们；需要这些信息时另取原始证据，否则说明本轮未核实。"
                "引用直接复制结果中的 citation 标签，source 逐字使用 url，不自行替换成其他网站链接。"
                "仅列题录或参考文献关系也需引用对应结果；只写 AMiner 或论文 ID 不能代替可追溯来源。"
            ),
            "cached": response.get("cached", False),
            "message": response.get("message", ""),
            "total": response.get("total"),
        }
