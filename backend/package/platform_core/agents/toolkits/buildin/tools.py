import asyncio
import copy
import os
import re
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Annotated
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool as langchain_tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from platform_core.agents.backends.paths import (
    VIRTUAL_PATH_PREFIX,
    VIRTUAL_SKILLS_PATH,
)
from platform_core.agents.backends.sandbox import ProvisionerSandboxBackend
from platform_core.agents.toolkits.registry import ToolExtraMetadata, _all_tool_instances, _extra_registry, tool
from platform_core.config.options import system_options
from platform_core.services.web_search_coordinator import (
    coordinated_search,
    get_active_search_coordinator,
    rate_limit_delay,
    search_failure,
)
from platform_core.utils import logger
from platform_core.utils.question_utils import normalize_questions

_OCR_OUTPUT_DIR_NAME = "ocr"
_OCR_PREVIEW_LIMIT = 1200
_SAFE_OUTPUT_STEM_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


_DOUBAO_SEARCH_URL = "https://open.feedcoopapi.com/search_api/web_search"
_SOGOU_SEARCH_URL = "https://www.sogou.com/web"
_PUBLIC_SEARCH_URL = "https://html.duckduckgo.com/html/"
_BING_SEARCH_URL = "https://www.bing.com/search"
_CROSSREF_SEARCH_URL = "https://api.crossref.org/works"
_OPEN_WEBSEARCH_SUPPORTED_ENGINES = {
    "baidu",
    "bing",
    "brave",
    "csdn",
    "duckduckgo",
    "exa",
    "hackernews",
    "juejin",
    "linuxdo",
    "sogou",
    "startpage",
}

# Search runs are shared by the main agent and all of its worker processes in a
# Python worker.  Keeping provider health here prevents ten parallel research
# subagents from hammering the same unhealthy endpoint and then each asking the
# model to invent another spelling of the same query.
_WEB_SEARCH_STATE_LOCK = threading.Lock()
_WEB_SEARCH_PROVIDER_HEALTH: dict[str, dict[str, float | int]] = {}
_WEB_SEARCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_WEB_SEARCH_CACHE_MAX_ENTRIES = 256

DOUBAO_SEARCH_DESCRIPTION = """执行网络网页搜索，通过豆包联网搜索获取实时高质量互联网网页内容、新闻和站点资料。

适用场景：
1. 获取最新的时事新闻、即时信息或最新科技动态
2. 检索特定网站的内容（通过 sites 参数指定）
3. 查找指定时间范围内发布的新闻或文章（通过 time_range 参数过滤）

参数使用建议：
- query: 输入简短清晰的搜索关键词或简短提问
- count: 默认 10 条，深度调研可适当调大（最多 50 条）
- time_range: 需要最新消息或时效性强的资讯时建议传入 'OneDay'、'OneWeek' 或 'OneMonth'
- sites: 仅需特定站点（如官媒、平台）时传入站点域名
"""

PUBLIC_SEARCH_DESCRIPTION = """执行公网网页搜索，返回可核验的网页标题、摘要和原始 URL。

适用场景：
1. 为深研对话补充公开论文、专利、标准、政府/军队公开材料和行业资料
2. 核验时效性事实、技术路线、工程瓶颈和公开试验结果
3. 为能力画像中的事实性结论保留可追溯来源

检索要求：每次围绕一个明确证据缺口，用实体名 + 技术/指标的 2-5 个关键词；不要把整个任务写成查询。
每次保留核心对象/实体名，不要只查询“数据、发展、效率”等泛词；中文命中差时可用对应英文术语做一次定向查询。
结果经过关键词相关性过滤，仍需核验是否回答当前子问题；只出现泛词的页面不能作为证据。
重要结论至少交叉核验两个独立来源，优先原始资料和权威机构。结果摘要不等于阅读全文。
status=empty 表示本次查询无有效命中，可针对具体缺口调整一次；status=degraded 表示服务故障，停止网页重试。
"""


class DoubaoSearchInput(BaseModel):
    query: str = Field(description="搜索查询词，1-100字符，必须精准描述检索需求")
    count: int = Field(default=10, ge=1, le=50, description="返回搜索结果数量，支持 1-50 条，默认 10 条")
    time_range: str | None = Field(
        default=None,
        description=(
            "按发文时间筛选结果。可选枚举值:\n"
            "- 'OneDay': 近24小时内\n"
            "- 'OneWeek': 近1周内\n"
            "- 'OneMonth': 近1个月内\n"
            "- 'OneYear': 近1年内\n"
            "- 'YYYY-MM-DD..YYYY-MM-DD': 自定义日期范围区间 (如 '2025-01-01..2025-12-31')"
        ),
    )
    sites: list[str] | None = Field(
        default=None, description="指定限定搜索的完整域名列表 (如 ['sohu.com', '163.com'])，最多支持 20 个站点"
    )
    block_hosts: list[str] | None = Field(
        default=None, description="指定屏蔽的搜索域名列表 (如 ['example.com'])，最多支持 5 个站点"
    )
    content_format: str = Field(
        default="text", description="正文返回格式，支持 'text' (纯文本) 或 'markdown' (Markdown 格式)，默认 'text'"
    )


def _build_doubao_search_payload(
    query: str,
    count: int,
    time_range: str | None,
    sites: list[str] | None,
    block_hosts: list[str] | None,
    content_format: str,
) -> dict:
    filter_obj: dict[str, str | bool] = {"NeedUrl": True}
    if sites:
        filter_obj["Sites"] = "|".join(sites[:20])
    if block_hosts:
        filter_obj["BlockHosts"] = "|".join(block_hosts[:5])

    payload = {
        "Query": query[:100],
        "SearchType": "web",
        "Count": min(max(1, count), 50),
        "Filter": filter_obj,
        "ContentFormats": "markdown" if content_format.lower() == "markdown" else "text",
    }
    if time_range:
        payload["TimeRange"] = time_range
    return payload


def _parse_doubao_search_response(query: str, data: dict) -> dict:
    error_info = data.get("ResponseMetadata", {}).get("Error")
    if error_info:
        logger.error(f"Doubao search API returned error: {error_info}")
        return {
            "query": query,
            "results": [],
            "error": error_info.get("Message", "Unknown error"),
            "code": error_info.get("Code"),
        }

    result_data = data.get("Result") or {}
    results = []
    for item in result_data.get("WebResults") or []:
        res_item = {
            "title": item.get("Title") or "",
            "url": item.get("Url") or "",
            "content": item.get("Summary") or item.get("Snippet") or item.get("Content") or "",
            "score": item.get("RankScore"),
        }
        if item.get("SiteName"):
            res_item["site_name"] = item["SiteName"]
        if item.get("PublishTime"):
            res_item["publish_time"] = item["PublishTime"]
        results.append(res_item)

    return {
        "query": query,
        "results": results,
        "response_time": result_data.get("TimeCost", 0) / 1000.0,
    }


@langchain_tool("web_search", args_schema=DoubaoSearchInput, description=DOUBAO_SEARCH_DESCRIPTION)
def _doubao_search(
    query: str,
    count: int = 10,
    time_range: str | None = None,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
    content_format: str = "text",
) -> dict:
    api_key = os.getenv("DOUBAO_SEARCH_API_KEY")
    if not api_key:
        return {"query": query, "results": [], "error": "DOUBAO_SEARCH_API_KEY 未配置"}

    payload = _build_doubao_search_payload(query, count, time_range, sites, block_hosts, content_format)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(_DOUBAO_SEARCH_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error(f"Doubao search failed: {exc}")
        return {"query": query, **search_failure(exc)}

    return _parse_doubao_search_response(query, data)


def _create_doubao_search():
    """Create the Doubao web search tool instance."""
    return _doubao_search


def _create_tavily_search():
    """Create the Tavily web search tool instance with tool name web_search."""
    from langchain_tavily import TavilySearch

    return TavilySearch(name="web_search")


def _open_websearch_engines() -> list[str]:
    """解析 daemon 多引擎列表，忽略迁移后残留的无效值。"""

    configured = os.getenv("OPEN_WEBSEARCH_ENGINES", "bing,duckduckgo")
    engines = []
    for value in configured.split(","):
        engine = value.strip().lower()
        if engine in _OPEN_WEBSEARCH_SUPPORTED_ENGINES and engine not in engines:
            engines.append(engine)
    return engines or ["bing"]


def _parse_open_websearch_response(
    query: str,
    data: dict,
    *,
    count: int,
    block_hosts: list[str] | None = None,
    sites: list[str] | None = None,
) -> dict:
    """把 open-websearch daemon 响应规范为平台统一检索协议。"""

    blocked = {_normalize_search_host(host) for host in (block_hosts or [])}
    blocked.discard("")
    allowed = {_normalize_search_host(host) for host in (sites or [])} - {""}
    results = []
    seen_urls: set[str] = set()
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen_urls:
            continue
        hostname = _normalize_search_host(url)
        if allowed and not any(hostname == host or hostname.endswith(f".{host}") for host in allowed):
            continue
        if any(hostname == host or hostname.endswith(f".{host}") for host in blocked):
            continue
        title = " ".join(str(item.get("title") or "").split())
        if not title:
            continue
        seen_urls.add(url)
        result = {
            "title": title[:500],
            "url": url[:2000],
            "content": " ".join(
                BeautifulSoup(str(item.get("description") or ""), "html.parser").get_text(" ", strip=True).split()
            )[:4000],
            "site_name": hostname,
        }
        if item.get("engine"):
            result["search_engine"] = str(item["engine"])
        results.append(result)

    output = {
        "query": query,
        "results": results,
        "provider": "open-websearch",
        "search_endpoint": "open-websearch",
    }
    partial_failures = data.get("partialFailures")
    if isinstance(partial_failures, list) and partial_failures:
        output["partial_failures"] = partial_failures
    engines = data.get("engines") or []
    failed_engines = {item.get("engine") for item in (partial_failures or []) if isinstance(item, dict)}
    if not results and engines and set(engines).issubset(failed_engines):
        output["error"] = "open-websearch 所有请求引擎均失败"
    elif not results:
        output["status"] = "empty"
    return _filter_search_results(output, query, count=count, sites=sites, block_hosts=block_hosts)


@langchain_tool("web_search", args_schema=DoubaoSearchInput, description=PUBLIC_SEARCH_DESCRIPTION)
def _open_websearch(
    query: str,
    count: int = 10,
    time_range: str | None = None,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
    content_format: str = "text",
) -> dict:
    """通过随项目部署的 open-websearch daemon 执行多引擎检索。"""

    del time_range, content_format
    normalized_query = " ".join(str(query or "").split())[:100]
    site_hosts = [_normalize_search_host(site) for site in (sites or [])[:20]]
    site_hosts = [host for host in site_hosts if host]
    search_query = normalized_query
    if site_hosts:
        search_query = f"{search_query} ({' OR '.join(f'site:{host}' for host in site_hosts)})"

    base_url = str(os.getenv("OPEN_WEBSEARCH_URL") or "").strip().rstrip("/")
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        return {
            "query": normalized_query,
            "results": [],
            "provider": "open-websearch",
            "error": "OPEN_WEBSEARCH_URL 未配置或不是有效的 HTTP(S) 地址",
        }

    timeout = _web_search_float_env("OPEN_WEBSEARCH_TIMEOUT_SECONDS", 15.0, minimum=3.0, maximum=60.0)
    coordinator = get_active_search_coordinator()
    delays = {
        engine: coordinator.engine_remaining(engine) if coordinator else 0 for engine in _open_websearch_engines()
    }
    engines = [engine for engine, delay in delays.items() if delay == 0]
    if not engines:
        return {
            "query": normalized_query,
            "results": [],
            "status": "rate_limited",
            "retry_after_seconds": min(delays.values()),
            "error": "搜索引擎正在按限流响应冷却",
        }
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.post(
            f"{base_url}/search",
            json={
                "query": search_query,
                "limit": max(1, min(int(count), 50)),
                "engines": engines,
            },
        )
        response.raise_for_status()
        envelope = response.json()

    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        error = envelope.get("error") if isinstance(envelope, dict) else None
        message = error.get("message") if isinstance(error, dict) else "daemon 返回无效响应"
        return {
            "query": normalized_query,
            "results": [],
            "provider": "open-websearch",
            "error": str(message)[:300],
        }
    data = envelope.get("data")
    if not isinstance(data, dict):
        return {
            "query": normalized_query,
            "results": [],
            "provider": "open-websearch",
            "error": "daemon 成功响应缺少 data",
        }
    return _parse_open_websearch_response(
        normalized_query,
        data,
        count=count,
        block_hosts=block_hosts,
        sites=sites,
    )


def _create_open_websearch():
    """创建 open-websearch daemon 工具适配器。"""

    return _open_websearch


def _decode_public_result_url(value: str) -> str:
    """还原 DuckDuckGo 跳转链接为可审计的原始来源 URL。"""

    url = str(value or "").strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = (parse_qs(parsed.query).get("uddg") or [""])[0]
        if target:
            url = target
            parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _normalize_search_host(value: str) -> str:
    """把站点过滤条件规范为不含路径和端口的域名。"""

    raw = str(value or "").strip().lower()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return str(parsed.hostname or "").strip(".")


def _parse_public_search_response(
    query: str,
    body: str,
    *,
    count: int,
    block_hosts: list[str] | None = None,
    sites: list[str] | None = None,
) -> dict:
    """解析公开搜索页，只输出标题、摘要和原始 URL。"""

    blocked = {_normalize_search_host(host) for host in (block_hosts or [])}
    blocked.discard("")
    results = []
    seen_urls: set[str] = set()
    soup = BeautifulSoup(body, "html.parser")
    for row in soup.select(".result, .vrwrap, li.b_algo"):
        link = row.select_one("a.result__a, h3 a, h2 a")
        if link is None:
            continue
        raw_url = str(link.get("href") or "")
        if raw_url.startswith("/") and not raw_url.startswith("//"):
            source = row.select_one("[data-url^='http://'], [data-url^='https://']")
            raw_url = str(source.get("data-url") or "") if source is not None else ""
        url = _decode_public_result_url(raw_url)
        if not url or url in seen_urls:
            continue
        hostname = _normalize_search_host(url)
        if any(hostname == host or hostname.endswith(f".{host}") for host in blocked):
            continue
        title = " ".join(link.get_text(" ", strip=True).split())
        snippet_node = row.select_one(".result__snippet, .text-layout, .space-txt, .b_caption p")
        content = " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node is not None else ""
        if not title:
            continue
        seen_urls.add(url)
        results.append(
            {
                "title": title[:500],
                "url": url[:2000],
                "content": content[:4000],
                "site_name": hostname,
            }
        )
    return _filter_search_results(
        {"query": query, "results": results, "provider": "public"},
        query,
        count=count,
        sites=sites,
        block_hosts=block_hosts,
    )


def _looks_academic_query(query: str, sites: list[str] | None = None) -> bool:
    detail = f"{query} {' '.join(sites or [])}".casefold()
    return any(
        marker in detail
        for marker in (
            " ieee",
            "iet ",
            "paper",
            "journal",
            "survey",
            "doi",
            "academic",
            "deep learning",
            "classification",
            "detection",
            "micro-doppler",
            "micro doppler",
            "论文",
            "期刊",
            "学术",
            "综述",
        )
    )


def _parse_crossref_search_response(query: str, data: dict, *, count: int) -> dict:
    results = []
    for item in (data.get("message") or {}).get("items") or []:
        titles = item.get("title") or []
        title = " ".join(str(titles[0] if titles else "").split())
        url = str(item.get("URL") or "").strip()
        if not title or not url:
            continue
        abstract = str(item.get("abstract") or "")
        content = " ".join(BeautifulSoup(abstract, "html.parser").get_text(" ", strip=True).split())
        publisher = " ".join(str(item.get("publisher") or "").split())
        date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
        publish_time = "-".join(str(value) for value in date_parts if value is not None)
        if not content:
            content = " · ".join(value for value in (publisher, publish_time) if value)
        result = {
            "title": title[:500],
            "url": url[:2000],
            "content": content[:4000],
            "site_name": publisher or "Crossref",
        }
        if publish_time:
            result["publish_time"] = publish_time
        if item.get("DOI"):
            result["doi"] = str(item["DOI"])
        results.append(result)
        if len(results) >= max(1, min(int(count), 50)):
            break
    return {"query": query, "results": results, "provider": "public", "search_endpoint": "crossref"}


def _search_crossref(query: str, *, count: int, timeout: float, headers: dict[str, str]) -> dict:
    crossref_headers = dict(headers)
    contact = str(os.getenv("CROSSREF_MAILTO") or "").strip()
    crossref_headers["User-Agent"] = "equipment-deep-research/1.0" + (f" (mailto:{contact})" if contact else "")
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=crossref_headers) as client:
        response = client.get(
            _CROSSREF_SEARCH_URL,
            params={
                "query.bibliographic": query,
                "rows": max(1, min(int(count), 50)),
                "select": "DOI,title,URL,abstract,publisher,published",
            },
        )
        response.raise_for_status()
    return _parse_crossref_search_response(query, response.json(), count=count)


@langchain_tool("web_search", args_schema=DoubaoSearchInput, description=PUBLIC_SEARCH_DESCRIPTION)
def _public_search(
    query: str,
    count: int = 10,
    time_range: str | None = None,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
    content_format: str = "text",
) -> dict:
    """无需专用 API Key 的公网检索兜底，确保深研始终可访问公开资料。"""

    normalized_query = " ".join(str(query or "").split())[:100]
    site_hosts = [_normalize_search_host(site) for site in (sites or [])[:20]]
    site_hosts = [host for host in site_hosts if host]
    search_query = normalized_query
    if site_hosts:
        search_query = f"{search_query} ({' OR '.join(f'site:{host}' for host in site_hosts)})"
    time_filter = {
        "OneDay": "d",
        "OneWeek": "w",
        "OneMonth": "m",
        "OneYear": "y",
    }.get(str(time_range or ""))
    params = {"query": search_query}
    if time_filter:
        params["df"] = time_filter
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        )
    }
    timeout = _web_search_float_env("PUBLIC_SEARCH_TIMEOUT_SECONDS", 12.0, minimum=3.0, maximum=30.0)
    # Search engines frequently return an anti-bot page (sometimes HTTP 200 or
    # 202) to server-side traffic. Every endpoint is therefore both a transport
    # and parse fallback. In particular, never return from the first exception:
    # that bug used to make DuckDuckGo/Bing unreachable whenever Sogou returned
    # its common 403 anti-spider response.
    endpoints = (
        ("sogou", _SOGOU_SEARCH_URL, params),
        ("duckduckgo", _PUBLIC_SEARCH_URL, {"q": search_query, **({"df": time_filter} if time_filter else {})}),
        ("bing", _BING_SEARCH_URL, {"q": search_query}),
    )
    failures: list[dict[str, str | int]] = []
    coordinator = get_active_search_coordinator()
    retry_after = 0.0
    academic_query = _looks_academic_query(normalized_query, sites)
    crossref_delay = coordinator.engine_remaining("crossref") if academic_query and coordinator else 0
    retry_after = max(retry_after, crossref_delay)
    if academic_query and not crossref_delay:
        try:
            academic = _search_crossref(
                normalized_query,
                count=count,
                timeout=timeout,
                headers=headers,
            )
            academic = _filter_search_results(
                academic, normalized_query, count=count, sites=sites, block_hosts=block_hosts
            )
            if academic["results"]:
                return academic
            failures.append({"endpoint": "crossref", "error": "empty_response"})
        except Exception as exc:
            delay = rate_limit_delay(search_failure(exc))
            if delay:
                retry_after = max(retry_after, delay)
                if coordinator:
                    coordinator.cool_engine("crossref", delay)
            failures.append({"endpoint": "crossref", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            logger.warning(f"Public search endpoint 'crossref' failed: {exc}")
    for endpoint, url, endpoint_params in endpoints:
        remaining = coordinator.engine_remaining(endpoint) if coordinator else 0
        if remaining:
            retry_after = max(retry_after, remaining)
            failures.append({"endpoint": endpoint, "error": "rate_limit_cooldown"})
            continue
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                response = client.get(url, params=endpoint_params)
                response.raise_for_status()
            result = _parse_public_search_response(
                normalized_query,
                response.text,
                count=count,
                block_hosts=block_hosts,
                sites=sites,
            )
            if result["results"]:
                result["search_endpoint"] = endpoint
                return result
            failures.append(
                {
                    "endpoint": endpoint,
                    "status_code": response.status_code,
                    "error": (
                        "irrelevant_results" if result.get("filtered_irrelevant_count") else "empty_or_antibot_response"
                    ),
                }
            )
        except Exception as exc:
            delay = rate_limit_delay(search_failure(exc))
            if delay:
                retry_after = max(retry_after, delay)
                if coordinator:
                    coordinator.cool_engine(endpoint, delay)
            failures.append({"endpoint": endpoint, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            logger.warning(f"Public search endpoint '{endpoint}' failed: {exc}")
    return {
        "query": normalized_query,
        "results": [],
        "provider": "public",
        "failures": failures,
        **(
            {"status": "empty"}
            if any(item["error"] in {"irrelevant_results", "empty_response"} for item in failures)
            else (
                {"status": "rate_limited", "retry_after_seconds": retry_after, "error": "公网后端临时限流"}
                if retry_after
                else {"error": "公网检索入口均未返回可解析结果"}
            )
        ),
    }


def _create_public_search():
    """创建无需专用密钥的公网搜索工具。"""

    return _public_search


# provider -> (required env var, factory, display name)
_WEB_SEARCH_PROVIDERS = {
    "open-websearch": ("OPEN_WEBSEARCH_URL", _create_open_websearch, "Open WebSearch 多引擎搜索"),
    "public": (None, _create_public_search, "公网网页搜索"),
    "doubao": ("DOUBAO_SEARCH_API_KEY", _create_doubao_search, "豆包 网页搜索"),
    "tavily": ("TAVILY_API_KEY", _create_tavily_search, "Tavily 网页搜索"),
}


def _resolve_web_search_provider() -> str | None:
    """优先解析已配置搜索服务，缺省时使用无需密钥的公网检索。"""

    configured = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
    if configured:
        if configured not in _WEB_SEARCH_PROVIDERS:
            logger.warning(f"Unknown WEB_SEARCH_PROVIDER '{configured}', falling back to public search.")
            return "public"
        env_key, _, _ = _WEB_SEARCH_PROVIDERS[configured]
        if env_key and not os.getenv(env_key):
            logger.warning(
                f"WEB_SEARCH_PROVIDER is set to '{configured}', but {env_key} is not configured; "
                "falling back to public search."
            )
            return "public"
        return configured

    for provider in ("open-websearch", "doubao", "tavily"):
        env_key, _, _ = _WEB_SEARCH_PROVIDERS[provider]
        if env_key and os.getenv(env_key):
            return provider
    return "public"


def _web_search_provider_order(primary: str) -> list[str]:
    """Return configured providers in failover order, always ending in public."""

    ordered = [primary]
    for provider in ("open-websearch", "doubao", "tavily"):
        env_key, _, _ = _WEB_SEARCH_PROVIDERS[provider]
        if provider != primary and env_key and os.getenv(env_key):
            ordered.append(provider)
    if "public" not in ordered:
        ordered.append("public")
    return ordered


def _web_search_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _web_search_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _web_search_cache_key(provider_order: list[str], arguments: dict) -> tuple:
    return (
        tuple(provider_order),
        str(arguments.get("query") or "").strip().casefold(),
        int(arguments.get("count") or 10),
        str(arguments.get("time_range") or ""),
        tuple(str(item).casefold() for item in (arguments.get("sites") or [])),
        tuple(str(item).casefold() for item in (arguments.get("block_hosts") or [])),
        str(arguments.get("content_format") or "text").casefold(),
        os.getenv("OPEN_WEBSEARCH_ENGINES", "bing,duckduckgo").casefold(),
    )


def _web_search_cached(key: tuple, now: float) -> dict | None:
    with _WEB_SEARCH_STATE_LOCK:
        cached = _WEB_SEARCH_CACHE.get(key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _WEB_SEARCH_CACHE.pop(key, None)
            return None
        result = copy.deepcopy(value)
    result["cache_hit"] = True
    result["queue_wait_seconds"] = 0.0
    return result


def _cache_web_search_result(key: tuple, result: dict, now: float) -> None:
    ttl = _web_search_float_env("WEB_SEARCH_CACHE_TTL_SECONDS", 300.0, minimum=0.0, maximum=3600.0)
    if ttl <= 0:
        return
    with _WEB_SEARCH_STATE_LOCK:
        if len(_WEB_SEARCH_CACHE) >= _WEB_SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(_WEB_SEARCH_CACHE, key=lambda item: _WEB_SEARCH_CACHE[item][0])
            _WEB_SEARCH_CACHE.pop(oldest_key, None)
        _WEB_SEARCH_CACHE[key] = (now + ttl, copy.deepcopy(result))


def _provider_circuit_open(provider: str, now: float) -> tuple[bool, float]:
    with _WEB_SEARCH_STATE_LOCK:
        health = _WEB_SEARCH_PROVIDER_HEALTH.get(provider) or {}
        open_until = float(health.get("open_until") or 0.0)
    return open_until > now, max(0.0, open_until - now)


def _record_provider_success(provider: str) -> None:
    with _WEB_SEARCH_STATE_LOCK:
        _WEB_SEARCH_PROVIDER_HEALTH[provider] = {"failures": 0, "open_until": 0.0}


def _record_provider_failure(provider: str, now: float) -> float:
    threshold = _web_search_int_env("WEB_SEARCH_CIRCUIT_FAILURE_THRESHOLD", 2, minimum=1, maximum=10)
    cooldown = _web_search_float_env("WEB_SEARCH_CIRCUIT_COOLDOWN_SECONDS", 45.0, minimum=1.0, maximum=600.0)
    with _WEB_SEARCH_STATE_LOCK:
        health = _WEB_SEARCH_PROVIDER_HEALTH.setdefault(provider, {"failures": 0, "open_until": 0.0})
        failures = int(health.get("failures") or 0) + 1
        health["failures"] = failures
        if failures >= threshold:
            health["open_until"] = now + cooldown
            return cooldown
    return 0.0


def _reset_web_search_runtime_state() -> None:
    """Test/admin hook; provider health otherwise deliberately spans subagent runs."""

    with _WEB_SEARCH_STATE_LOCK:
        _WEB_SEARCH_PROVIDER_HEALTH.clear()
        _WEB_SEARCH_CACHE.clear()


def _normalize_provider_search_result(provider: str, query: str, raw: object) -> dict:
    if isinstance(raw, list):
        result = {"query": query, "results": raw}
    elif isinstance(raw, dict):
        result = dict(raw)
    else:
        result = {"query": query, "results": [], "error": f"unexpected {type(raw).__name__} response"}
    result.setdefault("query", query)
    result.setdefault("results", [])
    result["provider"] = provider
    return result


def _search_query_terms(query: str) -> set[str]:
    """提取主题词，排除站点操作符、年份和不提供主题信息的泛词。"""
    ignored = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "what",
        "how",
        "of",
        "in",
        "on",
        "to",
        "a",
        "an",
        "site",
        "https",
        "www",
        "research",
        "study",
        "analysis",
        "data",
        "development",
        "资料",
        "相关",
        "研究",
        "分析",
        "发展",
        "数据",
        "型号",
        "代表",
        "介绍",
        "技术",
        "计划",
    }
    detail = re.sub(r"\bsite:\S+|(?<!\S)-\S+", " ", query.casefold())
    terms = set(re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*|[\u4e00-\u9fff]+", detail)) - ignored
    return {term for term in terms if len(term) >= 2 and not re.fullmatch(r"(?:19|20)\d{2}", term)}


def _rank_search_results(query: str, results: list[dict]) -> list[dict]:
    """按独立主题词覆盖排序，避免一个长词的零散双字片段凑成相关命中。"""
    terms = _search_query_terms(query)
    if not terms:
        return []
    scored = []
    for item in results:
        if not isinstance(item, dict):
            continue
        text = (
            BeautifulSoup(f"{item.get('title', '')} {item.get('content', '')}", "html.parser")
            .get_text(" ", strip=True)
            .casefold()
        )
        score = 0
        for term in terms:
            if re.fullmatch(r"[\u4e00-\u9fff]+", term):
                # 长中文复合词允许词序/部分修饰变化，但必须覆盖大部分，且只计一个主题词。
                pairs = {term[index : index + 2] for index in range(len(term) - 1)}
                covered = sum(pair in text for pair in pairs)
                matched = term in text or (len(term) >= 4 and covered >= 2 and covered / len(pairs) >= 0.6)
            else:
                matched = bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
            score += matched
        scored.append((score, item))
    minimum_coverage = min(2, len(terms))
    return [item for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True) if score >= minimum_coverage]


def _filter_search_results(
    result: dict,
    query: str,
    *,
    count: int = 10,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
) -> dict:
    """统一执行相关性、域名和数量约束，先筛选再截断。"""
    original = result.get("results") or []
    allowed = {_normalize_search_host(host) for host in sites or []} - {""}
    blocked = {_normalize_search_host(host) for host in block_hosts or []} - {""}
    scoped = []
    for item in original:
        if not isinstance(item, dict):
            continue
        host = _normalize_search_host(item.get("url") or "")
        if allowed and not any(host == domain or host.endswith(f".{domain}") for domain in allowed):
            continue
        if any(host == domain or host.endswith(f".{domain}") for domain in blocked):
            continue
        scoped.append(item)
    relevant = _rank_search_results(query, scoped)
    filtered = int(result.get("filtered_irrelevant_count") or 0) + len(original) - len(relevant)
    output = {**result, "query": query, "results": relevant[: max(1, min(int(count), 50))]}
    if filtered:
        output["filtered_irrelevant_count"] = filtered
    if (
        not relevant
        and not output.get("error")
        and output.get("status")
        not in {
            "rate_limited",
            "unavailable",
            "degraded",
        }
    ):
        output["status"] = "empty"
    return output


def _invoke_search_provider(provider: str, arguments: dict) -> dict:
    """跨 worker 协调原始供应商调用，避免子智能体并发造成限流。"""
    return coordinated_search(provider, arguments, lambda: _invoke_raw_search_provider(provider, arguments))


def _invoke_raw_search_provider(provider: str, arguments: dict) -> dict:
    """执行供应商原始实现，避免嵌套工具事件生成无声明的调用 ID。"""

    _, factory, _ = _WEB_SEARCH_PROVIDERS[provider]
    tool = factory()
    raw_function = getattr(tool, "func", None)
    if callable(raw_function):
        raw = raw_function(**arguments)
    elif provider == "tavily":
        # Tavily exposes a BaseTool rather than a StructuredTool.  Calling its
        # implementation directly avoids nested lifecycle callbacks while
        # preserving the public web_search argument contract.
        tavily_time_range = {
            "oneday": "day",
            "oneweek": "week",
            "onemonth": "month",
            "oneyear": "year",
        }.get(str(arguments.get("time_range") or "").casefold(), arguments.get("time_range"))
        raw = tool._run(  # noqa: SLF001 - intentional provider adapter boundary
            query=str(arguments.get("query") or ""),
            include_domains=arguments.get("sites"),
            exclude_domains=arguments.get("block_hosts"),
            time_range=tavily_time_range,
            run_manager=None,
        )
        if isinstance(raw, dict) and isinstance(raw.get("results"), list):
            raw = {**raw, "results": raw["results"][: max(1, min(int(arguments.get("count") or 10), 50))]}
    else:
        raise TypeError(f"Search provider {provider!r} does not expose a raw callable")
    return _normalize_provider_search_result(provider, str(arguments.get("query") or ""), raw)


def _resilient_web_search(primary: str, arguments: dict) -> dict:
    """Retry and fail over inside the tool, before the model sees a failure.

    The returned degraded payload is terminal for the current subtask.  It tells
    the agent to switch evidence channels instead of recursively reformulating
    a query and generating the repeated failure narration seen in deep research.
    """

    query = " ".join(str(arguments.get("query") or "").split())[:100]
    arguments = {**arguments, "query": query}
    if not _search_query_terms(query):
        return {
            "query": query,
            "results": [],
            "status": "empty",
            "next_action": "查询缺少明确主题词；请使用核心对象/实体名和具体技术/指标，禁止只查询单字或泛词。",
        }
    providers = _web_search_provider_order(primary)
    now = time.monotonic()
    cache_key = _web_search_cache_key(providers, arguments)
    cached = _web_search_cached(cache_key, now)
    if cached is not None:
        return cached

    attempts_per_provider = _web_search_int_env("WEB_SEARCH_PROVIDER_ATTEMPTS", 2, minimum=1, maximum=3)
    retry_delay = _web_search_float_env("WEB_SEARCH_RETRY_INITIAL_DELAY_SECONDS", 0.25, minimum=0.0, maximum=5.0)
    failures: list[dict[str, object]] = []
    attempted_providers: list[str] = []
    retry_after = 0.0
    empty_result = None
    limited_result = None

    for provider in providers:
        circuit_open, remaining = _provider_circuit_open(provider, time.monotonic())
        if circuit_open:
            retry_after = max(retry_after, remaining)
            failures.append({"provider": provider, "error": "circuit_open"})
            continue
        attempted_providers.append(provider)
        # The public provider already fans out across Sogou, DuckDuckGo and
        # Bing. Repeating that entire chain immediately adds load without new
        # coverage, so only API-backed providers get same-call retries.
        provider_attempts = 1 if provider in {"open-websearch", "public"} else attempts_per_provider
        for attempt in range(1, provider_attempts + 1):
            try:
                result = _invoke_search_provider(provider, arguments)
            except Exception as exc:  # provider SDKs do not share one exception hierarchy
                result = {"query": query, "provider": provider, **search_failure(exc)}
            # 每个供应商（包括公网兜底）都执行同一规则，HTTP 成功不代表命中相关。
            result = _filter_search_results(
                result,
                query,
                count=arguments.get("count", 10),
                sites=arguments.get("sites"),
                block_hosts=arguments.get("block_hosts"),
            )
            if result.get("results"):
                _record_provider_success(provider)
                result.update(
                    {
                        "status": "ok",
                        "attempted_providers": attempted_providers,
                        "provider_attempt": attempt,
                    }
                )
                _cache_web_search_result(cache_key, result, time.monotonic())
                return result

            if result.get("status") == "rate_limited" or rate_limit_delay(result):
                # 短暂限流由共享调度器恢复；等待预算用完后切换后端，不即时重试或永久熔断本轮。
                limited_result = result
                retry_after = max(retry_after, rate_limit_delay(result))
                failures.append({"provider": provider, "error": "rate_limited"})
                break

            if result.get("status") == "empty" or not result.get("error"):
                # 无命中属于查询结果，不能污染跨子任务共享的服务健康状态。
                _record_provider_success(provider)
                empty_result = {**result, "status": "empty", "results": []}
                break

            failures.append(
                {
                    "provider": provider,
                    "attempt": attempt,
                    "error": str(result.get("error") or "empty_result")[:300],
                }
            )
            retry_after = max(retry_after, _record_provider_failure(provider, time.monotonic()))
            if attempt < provider_attempts and retry_delay > 0:
                time.sleep(retry_delay * attempt)
            circuit_open, remaining = _provider_circuit_open(provider, time.monotonic())
            if circuit_open:
                retry_after = max(retry_after, remaining)
                break

    if empty_result is not None:
        return {
            **empty_result,
            "attempted_providers": attempted_providers,
            "next_action": "本次查询未找到有效命中；只针对尚未覆盖的证据缺口调整一次，再无增量则交付已有发现。",
        }

    if limited_result is not None:
        return {
            "query": query,
            "results": [],
            "status": "rate_limited",
            "retryable": True,
            "retry_after_seconds": max(1, int(retry_after + 0.999)),
            "attempted_providers": attempted_providers,
            "failures": failures[-6:],
            "next_action": (
                "共享调度已完成有界排队、冷却恢复和后端切换；暂时限流不代表整轮检索永久不可用。"
                "不要反复改写同一查询；使用其他可用证据完成分领域报告，逐项标注缺口，不能只返回限流说明。"
            ),
        }

    return {
        "query": query,
        "results": [],
        "status": "degraded",
        "retryable": False,
        "retry_after_seconds": max(1, int(retry_after or 45)),
        "attempted_providers": attempted_providers,
        "failures": failures[-6:],
        "error": "所有可用公网检索后端均暂不可用",
        "next_action": (
            "本次子任务不要再次调用 web_search 或改写同义查询；仅本轮用户显式 @知识库且工具可用时，"
            "可用 query_kbs 跨库检索；否则使用已获得来源和任务上下文继续，并标注仍缺少的公网证据。"
        ),
    }


def _create_resilient_web_search(primary: str):
    @langchain_tool("web_search", args_schema=DoubaoSearchInput, description=PUBLIC_SEARCH_DESCRIPTION)
    def resilient_web_search(
        query: str,
        count: int = 10,
        time_range: str | None = None,
        sites: list[str] | None = None,
        block_hosts: list[str] | None = None,
        content_format: str = "text",
    ) -> dict:
        return _resilient_web_search(
            primary,
            {
                "query": query,
                "count": count,
                "time_range": time_range,
                "sites": sites,
                "block_hosts": block_hosts,
                "content_format": content_format,
            },
        )

    return resilient_web_search


def _register_web_search_tool() -> None:
    """Register a resilient search router with the selected provider as primary."""
    provider = _resolve_web_search_provider()
    if provider is None:
        return

    _, _, display_name = _WEB_SEARCH_PROVIDERS[provider]
    _extra_registry["web_search"] = ToolExtraMetadata(category="buildin", tags=["搜索"], display_name=display_name)
    _all_tool_instances.append(_create_resilient_web_search(provider))


# 模块加载时注册网络搜索工具
try:
    _register_web_search_tool()
except Exception as e:
    logger.warning(f"Failed to register web search tool: {e}")


class PresentArtifactsInput(BaseModel):
    """Expose artifact files to the frontend after the agent finishes."""

    filepaths: list[str] = Field(description="需要展示给用户的文件绝对路径列表；建议把交付物放在 Project outputs/ 下")


def _normalize_presented_artifact_path(filepath: str, runtime: ToolRuntime) -> str:
    from platform_core.agents.backends.sandbox.backend import ProvisionerSandboxBackend

    runtime_context = runtime.context
    runtime_scope_id, uid, workdir_relative_path = _resolve_runtime_sandbox_scope(runtime)

    normalized_input = str(filepath or "").strip()
    if not normalized_input:
        raise ValueError("文件路径不能为空")

    normalized_path = str(
        PurePosixPath(normalized_input if normalized_input.startswith("/") else f"/{normalized_input}")
    )
    workdir_path = str(getattr(runtime_context, "workdir_path", "") or "").rstrip("/")
    allowed = normalized_path.startswith(f"{workdir_path}/") or normalized_path.startswith(
        f"{VIRTUAL_PATH_PREFIX.rstrip('/')}/"
    )
    allowed = allowed or normalized_path.startswith(f"{VIRTUAL_SKILLS_PATH}/")
    if not workdir_path or not allowed:
        raise ValueError(f"文件不在当前用户可见范围内: {normalized_input}")
    backend = ProvisionerSandboxBackend(
        thread_id=runtime_scope_id,
        uid=str(uid),
        workdir_path=workdir_relative_path,
        create_if_missing=True,
    )
    if not backend.regular_file_exists(normalized_path):
        raise ValueError(f"文件不存在或不是普通文件: {normalized_input}")
    return normalized_path


PRESENT_ARTIFACTS_DESCRIPTION = """
将已经生成好的结果文件展示给用户。

使用场景：
1. 你已经写好了最终结果文件；建议放在当前 Project Workdir 的 `outputs/` 下
2. 你希望前端在对话结束后显示这些结果文件卡片
3. 这些文件需要支持下载或预览

注意事项：
1. 可以传入当前 Project Workdir、User Data 或已授权 Skills 中的普通文件
2. 不要传入中间过程文件，只有真正需要给用户看的结果文件才调用
3. 可以一次传多个文件
"""


@tool(
    category="buildin",
    tags=["文件", "交付物"],
    display_name="展示交付物",
    description=PRESENT_ARTIFACTS_DESCRIPTION,
    args_schema=PresentArtifactsInput,
)
def present_artifacts(
    filepaths: list[str],
    runtime: ToolRuntime,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """登记当前用户可见的普通文件，使前端展示给用户。"""
    try:
        normalized_paths = [_normalize_presented_artifact_path(filepath, runtime) for filepath in filepaths]
    except ValueError as exc:
        return Command(update={"messages": [ToolMessage(content=f"Error: {exc}", tool_call_id=tool_call_id)]})

    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [ToolMessage(content="已将交付物展示给用户", tool_call_id=tool_call_id)],
        }
    )


class OcrParseFileInput(BaseModel):
    """Parse a sandbox file with OCR and save the Markdown result."""

    file_path: str = Field(description="需要 OCR 解析的 Project、User Data 或已授权 Skill 文件绝对路径")
    ocr_engine: str | None = Field(default=None, description="可选 OCR 引擎；省略时使用系统默认 OCR 引擎")


OCR_PARSE_FILE_DESCRIPTION = """
将沙盒中的 PDF、Office 文档或图片文件解析为 Markdown 文本，并把结果保存为文件。

使用场景：
1. 用户上传了 PDF、Office 文档或图片附件，需要提取其中的文字内容
2. Project Workdir、User Data 或 Skills 下已有文件，需要转成可读取的 Markdown
3. 解析结果较长，后续应使用 read_file 读取保存后的 Markdown 文件

注意事项：
1. file_path 必须位于当前用户可见范围
2. 解析结果会写入当前 Project Workdir 的 outputs/ocr/ 下
4. 工具只返回结果文件路径和短预览，不直接返回完整 OCR 文本
5. 如需在前端展示结果文件，请再调用 present_artifacts
"""


@tool(
    category="buildin",
    tags=["文件", "OCR"],
    display_name="OCR 解析文件",
    description=OCR_PARSE_FILE_DESCRIPTION,
    args_schema=OcrParseFileInput,
)
async def ocr_parse_file(file_path: str, runtime: ToolRuntime, ocr_engine: str | None = None) -> dict:
    """Parse a sandbox file with OCR, persist Markdown output, and return only a short result summary."""
    from platform_core.services.ocr_service import parse_document

    runtime_scope_id, uid, workdir_relative_path = _resolve_runtime_sandbox_scope(runtime)
    source_virtual_path = _resolve_ocr_source_path(file_path, runtime)
    backend = ProvisionerSandboxBackend(
        thread_id=runtime_scope_id,
        uid=uid,
        workdir_path=workdir_relative_path,
        create_if_missing=True,
    )
    from platform_core.services.ocr_service import resolve_ocr_engine_id

    engine = resolve_ocr_engine_id(ocr_engine, (await system_options.get())["default_ocr_engine"])
    source_temp = ""
    output_temp = ""
    try:
        suffix = PurePosixPath(source_virtual_path).suffix
        with tempfile.NamedTemporaryFile(prefix="deep-research-ocr-source-", suffix=suffix, delete=False) as temp_file:
            source_temp = temp_file.name
        try:
            await asyncio.to_thread(
                backend.download_authorized_file_to_path,
                source_virtual_path,
                source_temp,
                100 * 1024 * 1024,
            )
        except ValueError as exc:
            raise ValueError(f"文件不存在或不是普通文件: {source_virtual_path}") from exc
        markdown = await parse_document(source_temp, params={"ocr_engine": engine})
        workdir_path = str(_runtime_scope_value(runtime, "workdir_path") or "").rstrip("/")
        parsed_path = _next_ocr_output_path(backend, workdir_path, PurePosixPath(source_virtual_path))
        with tempfile.NamedTemporaryFile(prefix="deep-research-ocr-output-", delete=False) as temp_file:
            output_temp = temp_file.name
            temp_file.write(markdown.encode("utf-8"))
        await asyncio.to_thread(backend.upload_authorized_file_from_path, parsed_path, output_temp)
    finally:
        for temp_path in (source_temp, output_temp):
            if temp_path:
                with suppress(FileNotFoundError):
                    await asyncio.to_thread(os.unlink, temp_path)
    preview, truncated = _ocr_preview(markdown)

    return {
        "source_path": source_virtual_path,
        "parsed_path": parsed_path,
        "ocr_engine": engine,
        "char_count": len(markdown),
        "preview": preview,
        "truncated": truncated,
    }


def _resolve_ocr_source_path(file_path: str, runtime: ToolRuntime) -> str:
    """校验 OCR 输入位于当前用户可见文件范围。"""
    _resolve_runtime_sandbox_scope(runtime)

    normalized_input = str(file_path or "").strip()
    if not normalized_input:
        raise ValueError("文件路径不能为空")
    if ".." in PurePosixPath(normalized_input).parts:
        raise ValueError("只允许解析当前用户可见范围内的文件")

    clean_virtual_path = "/" + normalized_input.lstrip("/")
    workdir_path = str(_runtime_scope_value(runtime, "workdir_path") or "").rstrip("/")
    allowed = clean_virtual_path.startswith(f"{workdir_path}/") or clean_virtual_path.startswith(
        f"{VIRTUAL_PATH_PREFIX.rstrip('/')}/"
    )
    allowed = allowed or clean_virtual_path.startswith(f"{VIRTUAL_SKILLS_PATH}/")
    if not workdir_path or not allowed:
        raise ValueError("只允许解析当前用户可见范围内的文件")

    return clean_virtual_path


def _resolve_runtime_sandbox_scope(runtime: ToolRuntime) -> tuple[str, str, str]:
    """读取 execution runtime、用户与 Workdir 路径。"""
    runtime_thread_id = _runtime_scope_value(runtime, "runtime_scope_id") or _runtime_scope_value(runtime, "thread_id")
    uid = _runtime_scope_value(runtime, "uid")
    workdir_path = _runtime_scope_value(runtime, "workdir_relative_path")
    if not runtime_thread_id:
        raise ValueError("当前运行时缺少 thread_id")
    if not uid:
        raise ValueError("当前运行时缺少 uid")
    if not workdir_path:
        raise ValueError("当前运行时缺少 workdir_relative_path")
    return runtime_thread_id, uid, workdir_path


def _runtime_scope_value(runtime: ToolRuntime, key: str) -> str | None:
    """Look up a runtime scope value from LangGraph config, context, or state."""
    config = getattr(runtime, "config", None)
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    sources = (
        configurable if isinstance(configurable, dict) else {},
        getattr(runtime, "context", None),
        getattr(runtime, "state", None) if isinstance(getattr(runtime, "state", None), dict) else {},
    )
    for source in sources:
        value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _next_ocr_output_path(backend, workdir_path: str, source_path: PurePosixPath) -> str:
    """在当前 Project outputs 中选择不冲突的 Markdown 路径。"""
    base_name = _safe_ocr_output_stem(source_path)
    candidate = f"{workdir_path}/outputs/{_OCR_OUTPUT_DIR_NAME}/{base_name}.md"
    index = 1
    while backend.regular_file_exists(candidate):
        candidate = f"{workdir_path}/outputs/{_OCR_OUTPUT_DIR_NAME}/{base_name}-{index}.md"
        index += 1
    return candidate


def _safe_ocr_output_stem(source_path: Path) -> str:
    """Build a filesystem-friendly output filename stem from the source file name."""
    stem = source_path.stem.strip() or "ocr_result"
    safe_stem = _SAFE_OUTPUT_STEM_RE.sub("_", stem).strip("._-")
    return safe_stem or "ocr_result"


def _ocr_preview(markdown: str) -> tuple[str, bool]:
    """Return the short preview included in the tool result and whether it was truncated."""
    if len(markdown) <= _OCR_PREVIEW_LIMIT:
        return markdown, False
    return markdown[:_OCR_PREVIEW_LIMIT].rstrip(), True


ASK_USER_QUESTION_DESCRIPTION = """
在执行过程中，当你需要用户做决定或补充需求时，使用这个工具向用户提问。

适用场景：
1. 收集用户偏好或需求（例如风格、范围、优先级）
2. 澄清模糊指令（存在多种合理解释时）
3. 在实现过程中让用户选择方案方向
4. 在有明显权衡时让用户做取舍

使用规范：
1. questions 提供 1-5 个问题，每项包含 question，并可包含 options、multi_select、allow_other
2. 纯问答不提供 options（或传空列表），用户将直接填写文本
3. 选择题的 options 提供 2-5 个有区分度的选项，每项包含 label、value 和 description。
   label 写简短选项名称；description 用一句话解释该选项的范围、产出或取舍，推荐项说明推荐理由。
   description 会以小字显示在选项下方，不要只在聊天正文里提供说明，也不要重复选项名称。
4. 需求澄清应提供一个基于上下文的推荐项：放在第一位，并在 label 末尾加“（推荐）”（兼容 "(Recommended)"）
5. 若需要多选：将该问题的 multi_select 设为 true
6. allow_other 只用于选择题，通常保持 true，让用户可自行填写答案
7. 智能对话、深研对话的范围澄清必须调用本工具，不要只在正文列出澄清点。
   每题都有推荐项时，页面两分钟未作答会采用推荐项并继续；用户开始选择或填写后停止自动选择。
   没有推荐项或需要用户提供真实事实的纯问答不会自动回答；操作授权走专门审批机制。

注意事项：
1. 不要用这个工具询问“是否继续执行”“计划是否准备好”这类流程控制问题
2. 不要在信息已充分、无需用户决策时滥用该工具
3. 先基于现有上下文自行决策，只有关键不确定性时才提问

返回结果：
answer 为 object，格式为 {question_id: answer}。
跳过的问题不会出现在 answer 中。answer 的值可能是 string（纯问答或单选）、list（多选）
或 object（选择题的自行填写文本）。
"""


@tool(
    category="buildin",
    tags=["交互"],
    display_name="向用户提问",
    description=ASK_USER_QUESTION_DESCRIPTION,
)
def ask_user_question(
    questions: Annotated[
        list[dict] | str | None,
        "问题列表；纯问答格式 {question}，选择题格式 "
        "{question, options:[{label,value,description}], multi_select, allow_other, question_id(optional)}",
    ] = None,
) -> dict:
    """向用户发起问题并等待回答。"""
    # 解析 questions 参数：如果是字符串，尝试解析为 JSON
    if isinstance(questions, str):
        try:
            import json

            questions = json.loads(questions)
            logger.debug(f"Parsed string questions to list: {questions}")
        except Exception as e:
            logger.error(f"Failed to parse questions string: {e}, using None")
            questions = None

    normalized_questions = normalize_questions(questions or [])

    if not normalized_questions:
        raise ValueError("questions 至少需要包含一个有效问题")

    interrupt_payload = {
        "questions": normalized_questions,
        "source": "ask_user_question",
    }
    answer = interrupt(interrupt_payload)

    return {
        "questions": normalized_questions,
        "answer": answer,
    }
