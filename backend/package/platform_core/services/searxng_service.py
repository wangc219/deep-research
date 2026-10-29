"""SearXNG 管理端连接测试。"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx


def _searxng_url() -> str:
    url = str(os.getenv("SEARXNG_URL") or "").strip().rstrip("/")
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def normalize_unresponsive_engines(value: object) -> list[dict[str, str]]:
    """把 SearXNG 的多种失败结构统一为平台 partial failure。"""
    failures: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            engine = str(item.get("engine") or item.get("name") or "unknown")
            error = str(item.get("error") or item.get("exception") or item.get("message") or "unresponsive")
        elif isinstance(item, (list, tuple)) and item:
            engine = str(item[0])
            error = str(item[1] if len(item) > 1 else "unresponsive")
        else:
            engine, error = str(item or "unknown"), "unresponsive"
        failures.append({"provider": "searxng", "engine": engine, "error": error[:300]})
    return failures


async def test_searxng_connection(config: dict[str, Any]) -> dict[str, Any]:
    """分别确认容器健康和真实 JSON 检索能力。"""
    url = _searxng_url()
    if not url:
        return {
            "status": "not_configured",
            "container_status": "unavailable",
            "search_status": "not_run",
            "message": "SEARXNG_URL 未配置或不是有效的 HTTP(S) 地址",
        }

    timeout = min(10.0, max(3.0, float(config.get("searxng_timeout_seconds") or 8)))
    engines = list(config.get("general_engines") or ["brave"])[:8]
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            health = await client.get(f"{url}/healthz")
            health.raise_for_status()
            if health.text.strip().casefold() != "ok":
                raise ValueError("/healthz 未返回 OK")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "unavailable",
                "container_status": "unavailable",
                "search_status": "not_run",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "engines": engines,
                "message": f"SearXNG 容器健康检查失败：{type(exc).__name__}: {str(exc)[:240]}",
            }

        try:
            response = await client.post(
                f"{url}/search",
                data={
                    "q": "SearXNG metasearch",
                    "format": "json",
                    "engines": ",".join(engines),
                    "language": "en",
                    "safesearch": "0",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "degraded",
                "container_status": "ok",
                "search_status": "failed",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "engines": engines,
                "message": f"SearXNG 容器正常，但外网检索失败：{type(exc).__name__}: {str(exc)[:240]}",
            }

    results = payload.get("results") if isinstance(payload, dict) else []
    failures = normalize_unresponsive_engines(
        payload.get("unresponsive_engines") if isinstance(payload, dict) else None
    )
    result_count = len(results) if isinstance(results, list) else 0
    status = "ok" if result_count else "degraded"
    return {
        "status": status,
        "container_status": "ok",
        "search_status": "ok" if result_count else "empty",
        "latency_ms": round((time.monotonic() - started) * 1000),
        "result_count": result_count,
        "engines": engines,
        "partial_failures": failures,
        "message": "SearXNG 容器与外网检索正常" if result_count else "容器正常，但本次外网检索没有返回结果",
    }
