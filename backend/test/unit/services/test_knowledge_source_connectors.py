"""统一来源连接器的只读、安全和规范化边界。"""

import pytest

from platform_core.services import knowledge_source_connectors as connectors


def test_canonical_url_removes_tracking_and_sorts_query() -> None:
    value = "HTTPS://Example.COM/report/?utm_source=x&b=2&a=1&fbclid=secret#section"

    assert connectors._canonical_url(value) == "https://example.com/report?a=1&b=2"


def test_web_search_query_plan_expands_languages_and_combinations() -> None:
    rows = connectors._web_search_queries(
        {
            "topics": ["无人系统"],
            "query_combinations": [{"terms": ["反制", "定向能"]}],
            "languages": ["zh-CN", "en"],
        }
    )

    assert rows == [
        ("无人系统", "zh-CN"),
        ("无人系统", "en"),
        ("反制 定向能", "zh-CN"),
        ("反制 定向能", "en"),
    ]


@pytest.mark.asyncio
async def test_web_search_passes_language_and_trust_rules(monkeypatch) -> None:
    calls = []

    def search(query, **kwargs):
        calls.append((query, kwargs))
        return {
            "results": [
                {
                    "url": "https://example.gov/report?utm_campaign=x",
                    "title": "官方试验",
                    "content": "证据摘要",
                    "published_at": "2026-10-31",
                }
            ]
        }

    monkeypatch.setattr(connectors, "execute_public_web_search", search)

    items = await connectors._collect_web_search(
        {
            "queries": ["无人集群"],
            "languages": ["en"],
            "trusted_sites": ["example.gov"],
            "required_terms": ["试验"],
            "time_range": "month",
        }
    )

    assert calls[0][0] == "无人集群 language:en"
    assert calls[0][1]["sites"] == ["example.gov"]
    assert calls[0][1]["required_terms"] == ["试验"]
    assert items[0]["canonical_url"] == "https://example.gov/report"
    assert items[0]["metadata"]["language"] == "en"
    assert items[0]["metadata"]["search_snapshot"]["title"] == "官方试验"


@pytest.mark.asyncio
async def test_sitemap_index_recurses_into_urlset(monkeypatch) -> None:
    documents = {
        "https://example.com/sitemap.xml": b"""
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://example.com/posts.xml</loc></sitemap>
            </sitemapindex>
        """,
        "https://example.com/posts.xml": b"""
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/a</loc></url>
              <url><loc>https://example.com/b</loc></url>
            </urlset>
        """,
    }

    async def fetch(url, **_kwargs):
        return documents[url], url, "application/xml"

    monkeypatch.setattr(connectors, "_safe_fetch", fetch)

    assert await connectors._sitemap_links("https://example.com/sitemap.xml") == [
        "https://example.com/a",
        "https://example.com/b",
    ]


@pytest.mark.asyncio
async def test_website_stays_on_seed_domain_and_respects_depth(monkeypatch) -> None:
    pages = {
        "https://example.com/": b'<html><title>Root</title><body><a href="/a">A</a><a href="https://other.test/x">X</a></body></html>',
        "https://example.com/a": b"<html><title>A</title><body>Article</body></html>",
    }
    fetched = []

    async def robots(_url):
        return True

    async def fetch(url, **_kwargs):
        fetched.append(url)
        return pages[url], url, "text/html"

    monkeypatch.setattr(connectors, "_robots_allowed", robots)
    monkeypatch.setattr(connectors, "_safe_fetch", fetch)

    items = await connectors._collect_website(
        {
            "urls": ["https://example.com"],
            "max_depth": 1,
            "max_pages": 10,
            "request_interval_seconds": 0,
        }
    )

    assert fetched == ["https://example.com/", "https://example.com/a"]
    assert [item["title"] for item in items] == ["Root", "A"]


@pytest.mark.asyncio
async def test_safe_fetch_rejects_private_network_before_request(monkeypatch) -> None:
    async def private(_hostname):
        return True

    monkeypatch.setattr(connectors, "is_private_ip", private)

    with pytest.raises(ValueError, match="禁止访问内网地址"):
        await connectors._safe_fetch("http://127.0.0.1/private")


def test_public_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="不允许嵌入登录凭据"):
        connectors._validate_public_url("https://user:password@example.com/page")
