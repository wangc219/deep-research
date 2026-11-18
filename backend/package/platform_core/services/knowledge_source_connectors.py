"""统一知识来源的只读采集适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import deque
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify
from readability import Document
from sqlalchemy import MetaData, Table, and_, create_engine, inspect, select, text

from platform_core.agents.toolkits.buildin.tools import execute_public_web_search
from platform_core.knowledge.utils.url_fetcher import is_private_ip

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_ROWS = 1000
ALLOWED_FILTER_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
}


async def collect_source_items(source_type: str, config: dict, credential: dict | None) -> list[dict]:
    """执行一种来源的有界只读采集并返回规范化候选。"""
    if source_type in {"postgresql", "mysql"}:
        return await asyncio.to_thread(_collect_database, source_type, config, credential or {})
    if source_type == "website":
        return await _collect_website(config)
    if source_type == "web_search":
        return await _collect_web_search(config)
    if source_type == "upload":
        return []
    raise ValueError("不支持的知识来源类型")


def _collect_database(source_type: str, config: dict, credential: dict) -> list[dict]:
    """仅通过反射后的表/视图和列对象构造 SELECT。"""
    table_name = str(config.get("table") or "").strip()
    if not table_name:
        raise ValueError("数据库来源必须选择表或视图")
    schema = str(config.get("schema") or "").strip() or None
    columns = _string_list(config.get("columns"))
    content_columns = _string_list(config.get("content_columns"))
    metadata_columns = _string_list(config.get("metadata_columns"))
    title_column = str(config.get("title_column") or "").strip()
    primary_key = str(config.get("primary_key") or "").strip()
    cursor_column = str(config.get("cursor_column") or "").strip()
    selected_names = list(
        dict.fromkeys([*columns, *content_columns, *metadata_columns, title_column, primary_key, cursor_column])
    )
    selected_names = [name for name in selected_names if name]
    if not primary_key or not content_columns:
        raise ValueError("数据库来源必须配置主键和正文列")

    engine = create_engine(_database_url(source_type, credential), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if source_type == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            else:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET SESSION MAX_EXECUTION_TIME = 30000"))

            available = set(inspect(connection).get_table_names(schema=schema))
            available.update(inspect(connection).get_view_names(schema=schema))
            if table_name not in available:
                raise ValueError("所选表或视图不存在")
            table = Table(table_name, MetaData(), schema=schema, autoload_with=connection)
            unknown = [name for name in selected_names if name not in table.c]
            if unknown:
                raise ValueError(f"数据库字段不存在: {', '.join(unknown)}")
            projected = [table.c[name] for name in selected_names]
            statement = select(*projected)
            predicates = []
            for raw_filter in config.get("filters") or []:
                if not isinstance(raw_filter, dict):
                    raise ValueError("数据库过滤条件格式无效")
                name = str(raw_filter.get("column") or "")
                operator = str(raw_filter.get("operator") or "eq")
                if name not in table.c or operator not in ALLOWED_FILTER_OPERATORS:
                    raise ValueError("数据库过滤条件包含未授权字段或操作符")
                column = table.c[name]
                value = raw_filter.get("value")
                predicates.append(_database_predicate(column, operator, value))
            cursor_value = config.get("cursor_value")
            if cursor_column and cursor_value not in (None, ""):
                if cursor_column not in table.c:
                    raise ValueError("增量游标字段不存在")
                predicates.append(table.c[cursor_column] > cursor_value)
            if predicates:
                statement = statement.where(and_(*predicates))
            if cursor_column:
                statement = statement.order_by(table.c[cursor_column].asc())
            limit = min(max(int(config.get("max_rows") or 200), 1), MAX_SOURCE_ROWS)
            rows = connection.execute(statement.limit(limit)).mappings().all()
    finally:
        engine.dispose()

    byte_limit = min(max(int(config.get("max_bytes") or MAX_SOURCE_BYTES), 1), MAX_SOURCE_BYTES)
    accumulated_bytes = 0
    items = []
    for row in rows:
        key = str(row[primary_key])
        title = str(row.get(title_column) or key) if title_column else key
        body = "\n\n".join(f"## {name}\n\n{_markdown_value(row.get(name))}" for name in content_columns)
        metadata = {name: _json_value(row.get(name)) for name in metadata_columns}
        if cursor_column:
            metadata["cursor"] = _json_value(row.get(cursor_column))
        markdown = f"# {title}\n\n{body}\n"
        row_bytes = len(markdown.encode("utf-8")) + len(
            json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8")
        )
        if accumulated_bytes + row_bytes > byte_limit:
            break
        accumulated_bytes += row_bytes
        items.append(
            {
                "external_key": key,
                "canonical_url": "",
                "title": title,
                "markdown": markdown,
                "metadata": metadata,
            }
        )
    return items


def _database_url(source_type: str, credential: dict) -> str:
    host = str(credential.get("host") or "").strip()
    database = str(credential.get("database") or "").strip()
    username = str(credential.get("username") or "").strip()
    password = str(credential.get("password") or "")
    if not host or not database or not username:
        raise ValueError("数据库连接缺少 host、database 或 username")
    default_port = 5432 if source_type == "postgresql" else 3306
    port = int(credential.get("port") or default_port)
    driver = "postgresql+psycopg" if source_type == "postgresql" else "mysql+pymysql"
    return f"{driver}://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"


def _database_predicate(column, operator: str, value: Any):
    if operator == "eq":
        return column == value
    if operator == "ne":
        return column != value
    if operator == "gt":
        return column > value
    if operator == "gte":
        return column >= value
    if operator == "lt":
        return column < value
    if operator == "lte":
        return column <= value
    return column.contains(str(value))


async def _collect_website(config: dict) -> list[dict]:
    seeds = _string_list(config.get("urls") or config.get("seed_urls"))
    if config.get("sitemap_url"):
        seeds.extend(await _sitemap_links(str(config["sitemap_url"])))
    if config.get("rss_url"):
        seeds.extend(await _xml_links(str(config["rss_url"]), {"link"}))
    seeds = list(dict.fromkeys(_canonical_url(url) for url in seeds if url))
    if not seeds:
        raise ValueError("网站来源至少需要 URL、sitemap 或 RSS")

    max_pages = min(max(int(config.get("max_pages") or 20), 1), 100)
    max_depth = min(max(int(config.get("max_depth") or 0), 0), 3)
    interval_value = config.get("request_interval_seconds")
    request_interval = min(max(float(1.0 if interval_value is None else interval_value), 0.0), 30.0)
    allowed_hosts = {urlparse(url).hostname for url in seeds}
    queue = deque((url, 0) for url in seeds)
    visited: set[str] = set()
    items = []
    last_fetch_at = 0.0
    while queue and len(items) < max_pages:
        url, depth = queue.popleft()
        if url in visited or urlparse(url).hostname not in allowed_hosts:
            continue
        visited.add(url)
        if not await _robots_allowed(url):
            continue
        delay = request_interval - (asyncio.get_running_loop().time() - last_fetch_at)
        if delay > 0:
            await asyncio.sleep(delay)
        content, final_url, content_type = await _safe_fetch(url)
        last_fetch_at = asyncio.get_running_loop().time()
        if urlparse(final_url).hostname not in allowed_hosts:
            continue
        if "html" not in content_type:
            continue
        html = content.decode("utf-8", errors="replace")
        item = _html_item(final_url, html)
        items.append(item)
        if depth >= max_depth:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.select("a[href]"):
            child = _canonical_url(urljoin(final_url, anchor.get("href", "")))
            if child and urlparse(child).hostname in allowed_hosts and child not in visited:
                queue.append((child, depth + 1))
    return items


async def _collect_web_search(config: dict) -> list[dict]:
    queries = _web_search_queries(config)
    if not queries:
        raise ValueError("WebSearch 来源至少需要一个关注话题或查询")
    count = min(max(int(config.get("count") or 10), 1), 30)
    time_range = str(config.get("time_range") or "").strip() or None
    sites = _string_list(config.get("trusted_sites")) or None
    blocked = _string_list(config.get("blocked_sites")) or None
    items = []
    seen = set()
    required_terms = _string_list(config.get("required_terms")) or None
    required_term_groups = _string_matrix(config.get("required_term_groups")) or None
    for query, language in queries:
        localized_query = f"{query} language:{language}" if language else query
        result = await asyncio.to_thread(
            execute_public_web_search,
            localized_query,
            count=count,
            time_range=time_range,
            sites=sites,
            block_hosts=blocked,
            required_terms=required_terms,
            required_term_groups=required_term_groups,
        )
        for row in result.get("results") or []:
            url = _canonical_url(str(row.get("url") or row.get("link") or ""))
            if not url or url in seen:
                continue
            seen.add(url)
            title = str(row.get("title") or url)
            snippet = str(row.get("content") or row.get("snippet") or row.get("description") or "")
            items.append(
                {
                    "external_key": url,
                    "canonical_url": url,
                    "title": title,
                    "markdown": f"# {title}\n\n{snippet}\n\n来源：{url}\n",
                    "metadata": {
                        "query": query,
                        "language": language,
                        "published_at": row.get("published_at") or row.get("date"),
                        "source": row.get("source") or urlparse(url).hostname,
                        "search_snapshot": _bounded_mapping(row),
                    },
                }
            )
    return items


async def _sitemap_links(url: str, *, depth: int = 0, seen: set[str] | None = None) -> list[str]:
    """递归读取 sitemap index，并限制深度与数量。"""
    seen = seen or set()
    normalized = _canonical_url(url)
    if not normalized or normalized in seen or depth > 3 or len(seen) >= 20:
        return []
    seen.add(normalized)
    content, _, _ = await _safe_fetch(normalized, allow_xml=True)
    root = ElementTree.fromstring(content)
    root_name = root.tag.rsplit("}", 1)[-1].casefold()
    links = [
        element.text.strip() for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "loc" and element.text
    ]
    if root_name != "sitemapindex":
        return links[:1000]
    pages: list[str] = []
    for child_url in links[:20]:
        pages.extend(await _sitemap_links(child_url, depth=depth + 1, seen=seen))
        if len(pages) >= 1000:
            break
    return pages[:1000]


async def _xml_links(url: str, tags: set[str]) -> list[str]:
    content, _, _ = await _safe_fetch(url, allow_xml=True)
    root = ElementTree.fromstring(content)
    links = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in tags and element.text:
            links.append(element.text.strip())
    return links


async def _safe_fetch(
    url: str,
    *,
    allow_xml: bool = False,
    allow_text: bool = False,
) -> tuple[bytes, str, str]:
    _validate_public_url(url)
    current = url
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for _ in range(6):
            parsed = urlparse(current)
            _validate_public_url(current)
            if not parsed.hostname or await is_private_ip(parsed.hostname):
                raise ValueError("网站来源禁止访问内网地址")
            async with client.stream("GET", current, headers={"User-Agent": "KnowledgeCollector/1.0"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    current = urljoin(current, response.headers.get("Location") or "")
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                allowed = (
                    "html" in content_type
                    or (allow_xml and ("xml" in content_type or "rss" in content_type))
                    or (allow_text and ("text/plain" in content_type or not content_type))
                )
                if not allowed:
                    raise ValueError(f"网站来源不支持内容类型: {content_type}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_SOURCE_BYTES:
                        raise ValueError("网站内容超过 10 MB 限制")
                return bytes(data), current, content_type
    raise ValueError("网站重定向次数过多")


async def _robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        content, _, _ = await _safe_fetch(robots_url, allow_text=True)
    except (ValueError, httpx.HTTPError):
        return True
    parser = RobotFileParser()
    parser.parse(content.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch("KnowledgeCollector/1.0", url)


def _html_item(url: str, html: str) -> dict:
    readable = Document(html)
    title = BeautifulSoup(readable.title() or "", "html.parser").get_text(" ", strip=True) or url
    body_html = readable.summary(html_partial=True)
    body = markdownify(body_html, heading_style="ATX").strip()
    return {
        "external_key": url,
        "canonical_url": url,
        "title": title,
        "markdown": f"# {title}\n\n{body}\n\n来源：{url}\n",
        "metadata": {"source": urlparse(url).hostname},
    }


def _canonical_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/") or "/", "", query, ""))


def content_hash(markdown: str) -> str:
    """对规范化 Markdown 生成稳定摘要。"""
    normalized = "\n".join(line.rstrip() for line in markdown.strip().splitlines()) + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_matrix(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [row for item in value if (row := _string_list(item))]


def _web_search_queries(config: dict) -> list[tuple[str, str]]:
    base = _string_list(config.get("queries") or config.get("topics"))
    for item in config.get("query_combinations") or []:
        if isinstance(item, str) and item.strip():
            base.append(item.strip())
        elif isinstance(item, dict):
            terms = _string_list(item.get("terms"))
            if terms:
                base.append(" ".join(terms))
    languages = _string_list(config.get("languages")) or [""]
    return list(dict.fromkeys((query, language) for query in base for language in languages))[:50]


def _validate_public_url(url: str) -> None:
    """只接受显式公开 HTTP(S) URL；网络地址安全由每次 DNS 检查保证。"""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("网站 URL 必须是有效的 HTTP(S) 地址")
    if parsed.username or parsed.password:
        raise ValueError("网站来源 URL 不允许嵌入登录凭据")


def _markdown_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return f"```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"
    return str(value if value is not None else "")


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _bounded_mapping(value: dict) -> dict:
    result = {}
    for key, item in value.items():
        if key.lower() in {"authorization", "cookie", "credentials", "token", "api_key"}:
            continue
        result[str(key)[:80]] = _json_value(item) if not isinstance(item, (dict, list)) else str(item)[:1000]
    return result
