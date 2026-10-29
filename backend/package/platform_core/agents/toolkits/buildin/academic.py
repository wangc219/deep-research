"""智能对话与研究子智能体共用的论文检索工具。"""

import asyncio
import re
from html import escape
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field, StringConstraints

from platform_core.agents.toolkits.registry import tool
from platform_core.services.academic_retrieval_service import AcademicRetrievalService


class AcademicSearchInput(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] = Field(
        description="简短公开科研关键词；禁止发送完整会话或内部文档"
    )
    related_queries: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]] = (
        Field(
            default_factory=list,
            max_length=2,
            description="可选的英文术语、同义术语或互补技术角度，最多两个；每个检索词单独占用搜索额度，结果合并去重",
        )
    )
    mode: Literal["precision", "topic", "title", "semantic"] = Field(
        default="precision",
        description=(
            "自然语言技术问题默认用 precision（官方问答检索自动提词/受控联合搜索）；"
            "topic 用于单一标准术语，title 用于准确标题，semantic 用于 precision 不足后的 Pro 深语义翻页"
        ),
    )
    cursor: Annotated[str, StringConstraints(min_length=16, max_length=256)] | None = Field(
        default=None, description="仅语义模式：上一页实际返回的 next_cursor；不可自行构造"
    )
    any_terms: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]] | None = (
        Field(default=None, max_length=10, description="仅语义模式：经来源确认的术语或别名，至少匹配其中一个")
    )
    required_term_groups: list[list[str]] | None = Field(
        default=None,
        max_length=6,
        description="仅 precision：真实核心词组，组内 OR、组间 AND；适合中英文别名与多概念联合约束",
    )
    boost_terms: list[str] | None = Field(
        default=None, max_length=12, description="仅 precision：相关性加权词，不作为硬过滤条件"
    )
    years: list[int] | None = Field(default=None, max_length=50, description="可选的精确年份集合")
    sci_only: bool | None = Field(default=None, description="仅 precision：是否限定 SCI 论文")
    citation_boost: bool = Field(default=False, description="仅 precision：提升高被引论文，但不完全按引用量排序")
    author_terms: list[str] | None = Field(
        default=None, max_length=20, description="仅 precision：作者名变体，数组内 OR"
    )
    org_terms: list[str] | None = Field(default=None, max_length=20, description="仅 precision：机构名变体，数组内 OR")
    venue_ids: list[str] | None = Field(default=None, max_length=20, description="仅 precision：期刊或会议 ID 过滤")
    limit: int = Field(default=10, ge=1, le=20, description="每个检索词的候选上限，也是最终合并结果上限")
    page: int = Field(default=1, ge=1, le=10, description="从 1 开始的结果页码；标题搜索最多 10 页")
    order: Literal["relevance", "recent", "cited"] = Field(
        default="relevance", description="相关性优先，或按年份/被引数量排序"
    )


class AcademicPapersInput(BaseModel):
    paper_ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$")]] = Field(
        min_length=1, max_length=10, description="实际检索返回的 AMiner id；不能填写 arXiv 编号、DOI 或 URL"
    )
    full_abstract: bool = Field(default=True, description="仅对拟引用论文读取完整摘要；false 使用免费部分摘要")


class AcademicReferencesInput(BaseModel):
    paper_id: str = Field(min_length=1, max_length=128, description="需要追溯的核心论文 AMiner id，非 arXiv 编号或 DOI")
    limit: int = Field(default=20, ge=1, le=50)


class ParallelResearchSearchInput(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] = Field(
        description="一个明确证据缺口的公开检索词；首轮同时查询 Open WebSearch、SearXNG 与 AMiner"
    )
    count: int = Field(default=10, ge=1, le=20, description="每个发现通道的候选上限")
    academic_mode: Literal["precision", "topic", "title", "semantic"] = Field(
        default="precision", description="AMiner 默认使用官方问答精确检索；必要时可选主题、准确标题或 Pro 语义模式"
    )
    order: Literal["relevance", "recent", "cited"] = Field(default="relevance")
    time_range: str | None = Field(default=None, description="网页时间范围，与 web_search 一致")
    sites: list[str] | None = Field(default=None, max_length=20, description="可选的严格站点范围")
    block_hosts: list[str] | None = Field(default=None, max_length=5, description="需要排除的网页域名")
    required_terms: list[str] | None = Field(default=None, max_length=3, description="网页结果必须保留的身份锚点")
    required_term_groups: list[list[str]] | None = Field(
        default=None, max_length=3, description="网页结果真实别名组：组内 OR、组间 AND"
    )


def _parallel_result_keys(item: dict) -> set[str]:
    """为跨网页与论文候选生成保守的去重身份。"""
    keys = set()
    doi = str(item.get("doi") or "").strip().casefold()
    if doi:
        keys.add("doi:" + re.sub(r"^(?:https?://doi\.org/|doi:)", "", doi))
    raw_url = str(item.get("url") or "").strip()
    try:
        parsed = urlsplit(raw_url)
        if parsed.scheme.casefold() in {"http", "https"} and parsed.hostname:
            query = [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid", "msclkid"}
            ]
            canonical = urlunsplit(
                (
                    "https",
                    parsed.netloc.casefold(),
                    parsed.path.rstrip("/") or "/",
                    urlencode(sorted(query)),
                    "",
                )
            )
            keys.add("url:" + canonical)
            if parsed.hostname.casefold() in {"doi.org", "dx.doi.org"}:
                keys.add("doi:" + parsed.path.strip("/").casefold())
    except ValueError:
        pass
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(item.get("title") or "").casefold())
    if len(title) >= 12:
        keys.add("title:" + title)
    return keys


def _merge_parallel_research_results(query: str, web: dict, academic: dict, *, count: int) -> dict:
    """跨网页融合结果与 AMiner 候选去重、交错排序并保留证据层级。"""
    groups: dict[str, dict] = {}
    identity_map: dict[str, str] = {}
    lane_results = (("web", web.get("results") or []), ("aminer", academic.get("results") or []))
    active_lanes = sum(bool(items) for _, items in lane_results) or 1
    max_rrf = active_lanes / 61

    for lane, items in lane_results:
        for rank, raw_item in enumerate(items, 1):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            keys = _parallel_result_keys(item)
            if not keys:
                continue
            group_id = next((identity_map[key] for key in keys if key in identity_map), "")
            providers = item.get("providers") or (["aminer"] if lane == "aminer" else [web.get("provider") or "web"])
            if isinstance(providers, str):
                providers = [providers]
            if not group_id:
                group_id = sorted(keys)[0]
                candidate = {
                    **item,
                    "providers": list(dict.fromkeys(str(value) for value in providers if value)),
                    "search_engines": list(item.get("search_engines") or []),
                    "_rrf": 0.0,
                }
                groups[group_id] = candidate
            else:
                candidate = groups[group_id]
                candidate["providers"] = list(
                    dict.fromkeys([*candidate.get("providers", []), *(str(value) for value in providers if value)])
                )
                candidate["search_engines"] = list(
                    dict.fromkeys([*candidate.get("search_engines", []), *(item.get("search_engines") or [])])
                )
                if len(str(item.get("title") or "")) > len(str(candidate.get("title") or "")):
                    candidate["title"] = item["title"]
                if len(str(item.get("content") or "")) > len(str(candidate.get("content") or "")):
                    candidate["content"] = item["content"]
                for field in ("id", "doi", "authors", "year", "venue", "content_level", "publish_time"):
                    if not candidate.get(field) and item.get(field):
                        candidate[field] = item[field]
                if item.get("url") and item.get("url") != candidate.get("url"):
                    candidate["alternate_urls"] = list(
                        dict.fromkeys([*candidate.get("alternate_urls", []), str(item["url"])])
                    )
            for key in keys:
                identity_map[key] = group_id
            candidate["_rrf"] += 1 / (60 + rank)

    ranked = []
    for item in groups.values():
        providers = set(item.get("providers") or [])
        cross_channel = "aminer" in providers and bool(providers - {"aminer"})
        item["cross_channel_match"] = cross_channel
        item["evidence_type"] = "hybrid" if cross_channel else "academic" if "aminer" in providers else "web"
        normalized_rrf = min(1.0, float(item.pop("_rrf", 0.0)) / max_rrf)
        value_bonus = 0.15 * (item.get("source_tier") == "authoritative")
        value_bonus += 0.1 * (item.get("content_level") == "abstract")
        value_bonus += 0.15 * cross_channel
        ranked.append((normalized_rrf + value_bonus, item))
    selected = [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)[: max(1, count * 2)]]
    for index, item in enumerate(selected, 1):
        url = str(item.get("url") or "")
        if url:
            item["citation"] = f'<cite source="{escape(url, quote=True)}" type="url">{index}</cite>'

    partial_failures = [failure for failure in web.get("partial_failures") or [] if isinstance(failure, dict)]
    academic_status = str(academic.get("aminer_status") or academic.get("status") or "ok")
    if academic_status not in {"ok", "empty"}:
        partial_failures.append(
            {
                "provider": "aminer",
                "error": str(academic.get("message") or academic.get("error") or academic_status)[:300],
                "status": academic_status,
            }
        )
    completed = list(web.get("completed_providers") or [])
    if not completed and web.get("_completed", True) and web.get("provider"):
        completed.append(str(web["provider"]))
    if academic.get("_completed", True):
        completed.append("aminer")
    completed = list(dict.fromkeys(completed))

    output = {
        "query": query,
        "results": selected,
        "status": "ok"
        if selected
        else "empty"
        if web.get("status") == "empty" and academic_status in {"ok", "empty"}
        else "degraded",
        "search_mode": "three_channel_parallel",
        "provider": "research-fusion",
        "completed_providers": completed,
        "attempted_providers": list(
            dict.fromkeys([*(web.get("attempted_providers") or ["open-websearch", "searxng"]), "aminer"])
        ),
        "query_profile": web.get("query_profile") or {},
        "channel_summary": {
            "web_candidates": len(web.get("results") or []),
            "academic_candidates": len(academic.get("results") or []),
            "unique_candidates": len(selected),
            "cross_channel_matches": sum(item.get("cross_channel_match", False) for item in selected),
        },
        "aminer_status": academic_status,
        "queue_wait_seconds": float(web.get("queue_wait_seconds") or 0.0),
    }
    if partial_failures:
        output["partial_failures"] = partial_failures[-12:]
    if not selected:
        output["next_action"] = "三渠道首轮未取得有效候选；只针对仍影响判断的具体证据缺口调整一次。"
    return output


@tool(
    category="buildin",
    tags=["搜索", "论文", "融合"],
    display_name="三渠道并行研究检索",
    description=(
        "调研探索员首轮发现工具：并行查询 Open WebSearch、SearXNG 与 AMiner，"
        "按 URL、DOI 和题名去重融合高价值候选；后续再按证据缺口使用单路工具深挖。"
    ),
    args_schema=ParallelResearchSearchInput,
)
async def parallel_research_search(
    query: str,
    runtime: ToolRuntime,
    count: int = 10,
    academic_mode: str = "precision",
    order: str = "relevance",
    time_range: str | None = None,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
    required_terms: list[str] | None = None,
    required_term_groups: list[list[str]] | None = None,
) -> dict:
    """并行执行两类公网后端和 AMiner，返回一次去重融合的发现结果。"""
    from platform_core.agents.toolkits.buildin.tools import execute_public_web_search

    web_task = asyncio.to_thread(
        execute_public_web_search,
        query,
        count=count,
        time_range=time_range,
        sites=sites,
        block_hosts=block_hosts,
        required_terms=required_terms,
        required_term_groups=required_term_groups,
        fusion_strategy="parallel",
    )
    academic_task = AcademicRetrievalService(runtime.context).search(
        query,
        mode=academic_mode,
        limit=count,
        order=order,
        required_term_groups=required_term_groups,
    )
    web_result, academic_result = await asyncio.gather(web_task, academic_task, return_exceptions=True)
    if isinstance(web_result, BaseException):
        web_result = {
            "status": "degraded",
            "results": [],
            "provider": "web",
            "error": f"{type(web_result).__name__}: {str(web_result)[:240]}",
            "_completed": False,
        }
    if isinstance(academic_result, BaseException):
        academic_result = {
            "status": "unavailable",
            "aminer_status": "unavailable",
            "results": [],
            "message": f"{type(academic_result).__name__}: {str(academic_result)[:240]}",
            "_completed": False,
        }
    return _merge_parallel_research_results(query, web_result, academic_result, count=count)


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文搜索",
    description=(
        "通过 AMiner 发现论文并返回题录、DOI、来源和部分摘要。科研技术问题优先使用；"
        "自然语言技术问题、罕见术语和跨学科问题默认用 mode=precision，支持官方自动提词、"
        "AND/OR 联合约束、加权词、年份、SCI、作者、机构和 venue 过滤；precision 不足再用 semantic。"
        "支持 related_queries 中英文互补发现；order=recent 查进展，cited 查经典，semantic 支持游标翻页。"
        "仅发送公开科研关键词，不发送会话或内部文档。"
    ),
    args_schema=AcademicSearchInput,
)
async def academic_search(
    query: str,
    runtime: ToolRuntime,
    mode: str = "precision",
    limit: int = 10,
    order: str = "relevance",
    page: int = 1,
    related_queries: list[str] | None = None,
    cursor: str | None = None,
    any_terms: list[str] | None = None,
    required_term_groups: list[list[str]] | None = None,
    boost_terms: list[str] | None = None,
    years: list[int] | None = None,
    sci_only: bool | None = None,
    citation_boost: bool = False,
    author_terms: list[str] | None = None,
    org_terms: list[str] | None = None,
    venue_ids: list[str] | None = None,
) -> dict:
    """按主题或已知标题检索公开论文。"""
    return await AcademicRetrievalService(runtime.context).search(
        query,
        mode=mode,
        limit=limit,
        order=order,
        page=page,
        related_queries=related_queries,
        cursor=cursor,
        any_terms=any_terms,
        required_term_groups=required_term_groups,
        boost_terms=boost_terms,
        years=years,
        sci_only=sci_only,
        citation_boost=citation_boost,
        author_terms=author_terms,
        org_terms=org_terms,
        venue_ids=venue_ids,
    )


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文摘要与详情",
    description="批量补齐选定论文题录，按需获取完整摘要。请先筛选拟引用论文再调用；摘要不是全文，不能声称已阅读全文。",
    args_schema=AcademicPapersInput,
)
async def academic_get_papers(paper_ids: list[str], runtime: ToolRuntime, full_abstract: bool = True) -> dict:
    """为选定论文补充可追溯摘要证据。"""
    return await AcademicRetrievalService(runtime.context).get_papers(paper_ids, full_abstract=full_abstract)


@tool(
    category="buildin",
    tags=["搜索", "论文"],
    display_name="论文参考文献",
    description="获取核心论文引用的参考文献，按需扩展一层。不是后续引用者列表，不递归抓取文献树；与其他论文工具共享本轮预算。",
    args_schema=AcademicReferencesInput,
)
async def academic_get_references(paper_id: str, runtime: ToolRuntime, limit: int = 20) -> dict:
    """追溯核心论文的原始参考文献。"""
    return await AcademicRetrievalService(runtime.context).get_references(paper_id, limit=limit)
