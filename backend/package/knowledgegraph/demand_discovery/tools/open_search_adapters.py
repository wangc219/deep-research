"""Configurable open-web search adapters for demand discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Awaitable, Callable, Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
import yaml

from knowledgegraph.demand_discovery.tools.network import DEFAULT_HTTP_HEADERS
from knowledgegraph.demand_discovery.tools.search import OpenSearchHit, OpenSearchAdapter


FetchText = Callable[[str], Awaitable[str]]
JsonTransport = Callable[
    [str, dict[str, str], dict[str, object]], Awaitable[dict[str, object]]
]


@dataclass(frozen=True)
class HtmlUrlTemplateOpenSearchAdapter:
    name: str
    search_provider: str
    template: str
    result_selector: str
    fetch_text: FetchText

    async def search(self, query: str, page: int) -> list[OpenSearchHit]:
        url = self.template.format(
            query=quote(query),
            page=page,
            offset=max(page - 1, 0) * 10,
        )
        html = await self.fetch_text(url)
        soup = BeautifulSoup(html or "", "html.parser")
        anchors = (
            soup.select(self.result_selector)
            if self.result_selector
            else soup.find_all("a", href=True)
        )
        hits: list[OpenSearchHit] = []
        for anchor in anchors:
            href = str(anchor.get("href", "")).strip()
            if not href:
                continue
            final_url = _normalize_result_url(urljoin(url, href))
            if not final_url:
                continue
            parsed = urlparse(final_url)
            if parsed.scheme.lower() not in {"http", "https"}:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())
            if not title:
                title = final_url
            hits.append(
                OpenSearchHit(
                    title=title,
                    url=final_url,
                    snippet=_nearby_text(anchor),
                    source_domain=(parsed.hostname or "").lower(),
                    search_provider=self.search_provider or self.name,
                    query_used=query,
                )
            )
        return _dedupe_hits(hits)


@dataclass(frozen=True)
class TavilyOpenSearchAdapter:
    name: str
    search_provider: str
    endpoint_url: str
    api_key: str
    max_results: int = 5
    search_depth: str = "basic"
    json_transport: JsonTransport | None = None

    async def search(self, query: str, page: int) -> list[OpenSearchHit]:
        if page > 1:
            return []
        payload: dict[str, object] = {
            "query": query,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        transport = self.json_transport or _default_json_transport
        data = await transport(self.endpoint_url, headers, payload)
        query_used = str(data.get("query") or query)
        hits: list[OpenSearchHit] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme.lower() not in {"http", "https"}:
                continue
            title = str(item.get("title") or url).strip()
            snippet = str(item.get("content") or item.get("snippet") or "").strip()
            hits.append(
                OpenSearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_domain=(parsed.hostname or "").lower(),
                    search_provider=self.search_provider or self.name,
                    query_used=query_used,
                )
            )
        return _dedupe_hits(hits)


def load_open_search_adapters(
    path: str | Path | None = None,
    *,
    fetch_text: FetchText | None = None,
    json_transport: JsonTransport | None = None,
    env: Mapping[str, str] | None = None,
) -> list[OpenSearchAdapter]:
    config_path = Path(path) if path is not None else default_open_search_adapters_path()
    if not config_path.exists():
        return []
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    resolved_env = _load_env(config_path, env)
    adapters: list[OpenSearchAdapter] = []
    for index, item in enumerate(data.get("adapters", [])):
        if not isinstance(item, dict):
            continue
        if item.get("enabled", True) is False:
            continue
        adapter_type = str(item.get("type", "")).strip()
        if adapter_type == "tavily_search":
            api_key = _resolve_env_key(item, resolved_env)
            if not api_key:
                continue
            adapters.append(
                TavilyOpenSearchAdapter(
                    name=str(item.get("name", f"adapter-{index}")),
                    search_provider=str(
                        item.get("search_provider", item.get("name", "tavily"))
                    ),
                    endpoint_url=str(
                        item.get("endpoint_url", "https://api.tavily.com/search")
                    ),
                    api_key=api_key,
                    max_results=int(item.get("max_results", 5)),
                    search_depth=str(item.get("search_depth", "basic")),
                    json_transport=json_transport,
                )
            )
            continue
        if adapter_type != "html_url_template":
            raise ValueError(
                f"unsupported open search adapter type at adapters[{index}]: "
                f"{adapter_type}"
            )
        template = str(item.get("template", "")).strip()
        if not template:
            raise ValueError(f"open search adapters[{index}].template is required")
        adapters.append(
            HtmlUrlTemplateOpenSearchAdapter(
                name=str(item.get("name", f"adapter-{index}")),
                search_provider=str(item.get("search_provider", item.get("name", ""))),
                template=template,
                result_selector=str(item.get("result_selector", "a")),
                fetch_text=fetch_text or _default_fetch_text,
            )
        )
    return adapters


def default_open_search_adapters_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "demand_discovery"
        / "open_search_adapters.yaml"
    )


async def _default_fetch_text(url: str) -> str:
    return await asyncio.to_thread(_requests_text, url)


async def _default_json_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    return await asyncio.to_thread(_requests_json, url, headers, payload)


def _requests_text(url: str) -> str:
    import requests

    response = requests.get(url, timeout=30, headers=DEFAULT_HTTP_HEADERS)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = response.apparent_encoding
    return response.text


def _requests_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    import requests

    response = requests.post(url, timeout=30, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("open search provider returned non-object JSON")
    return data


def _load_env(config_path: Path, env: Mapping[str, str] | None) -> dict[str, str]:
    if env is not None:
        return {str(key): str(value) for key, value in env.items()}
    values = {str(key): str(value) for key, value in os.environ.items()}
    env_path = _project_root_for_config(config_path) / ".env"
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values.setdefault(key, value)
    return values


def _project_root_for_config(config_path: Path) -> Path:
    resolved = config_path.resolve()
    if resolved.name == "open_search_adapters.yaml":
        for parent in resolved.parents:
            if (parent / "src").exists() and (parent / "tests").exists():
                return parent
    return Path(__file__).resolve().parents[4]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if key.startswith("$env:"):
        key = key[len("$env:") :]
    key = key.strip()
    if not key:
        return None
    value = value.strip().strip('"').strip("'")
    return key, value


def _resolve_env_key(item: dict[str, Any], env: Mapping[str, str]) -> str:
    env_key = str(item.get("env_key", "")).strip()
    if not env_key:
        return ""
    return str(env.get(env_key, "")).strip()


def _normalize_result_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _is_google_search_host(host):
        if parsed.path == "/url":
            query = parse_qs(parsed.query)
            for key in ("q", "url"):
                values = query.get(key, [])
                if values:
                    target = unquote(values[0]).strip()
                    if urlparse(target).scheme.lower() in {"http", "https"}:
                        return target
            return ""
        return ""
    return url


def _is_google_search_host(host: str) -> bool:
    return host == "google.com" or host.endswith(".google.com")


def _nearby_text(anchor: Any) -> str:
    parent = getattr(anchor, "parent", None)
    text = " ".join(parent.get_text(" ", strip=True).split()) if parent else ""
    if text:
        return text[:300]
    return ""


def _dedupe_hits(hits: list[OpenSearchHit]) -> list[OpenSearchHit]:
    rows: list[OpenSearchHit] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.url in seen:
            continue
        seen.add(hit.url)
        rows.append(hit)
    return rows
