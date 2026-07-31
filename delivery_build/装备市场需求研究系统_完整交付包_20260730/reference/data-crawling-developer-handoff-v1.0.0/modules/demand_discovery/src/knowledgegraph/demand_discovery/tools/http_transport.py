"""Shared HTTP request helpers for demand-discovery acquisition tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any

import requests

from knowledgegraph.runtime.retry import call_with_retries


DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "text/plain;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass(frozen=True)
class HttpFetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    truncated: bool = False


HttpTransport = Callable[[str, int, int], Awaitable[HttpFetchResponse]]


def request_bytes(
    method: str,
    url: str,
    *,
    timeout_seconds: float = 30.0,
    max_bytes: int = 2_000_000,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, object] | None = None,
    data: object | None = None,
    json_body: object | None = None,
    max_retries: int = 2,
    retry_sleep_seconds: float = 0.5,
    request_sender: Callable[..., Any] | None = None,
) -> HttpFetchResponse:
    request_headers = {**DEFAULT_HTTP_HEADERS, **dict(headers or {})}

    def send() -> HttpFetchResponse:
        request_kwargs = {
            "timeout": max(timeout_seconds, 0.001),
            "headers": request_headers,
            "params": params,
            "data": data,
            "json": json_body,
        }
        if request_sender is None:
            response = requests.request(method.upper(), url, **request_kwargs)
        else:
            response = request_sender(url, **request_kwargs)
        content = response.content[:max_bytes]
        return HttpFetchResponse(
            url=str(response.url),
            status_code=int(response.status_code),
            headers={str(key): str(value) for key, value in response.headers.items()},
            content=content,
            truncated=len(response.content) > max_bytes,
        )

    return call_with_retries(
        send,
        label=f"{method.upper()} {url}",
        max_retries=max_retries,
        sleep_seconds=retry_sleep_seconds,
    )


async def default_http_transport(
    url: str,
    timeout_ms: int,
    max_bytes: int,
) -> HttpFetchResponse:
    return await asyncio.to_thread(
        request_bytes,
        "GET",
        url,
        timeout_seconds=max(timeout_ms / 1000, 0.001),
        max_bytes=max_bytes,
    )


def header_value(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return ""


def decode_response(response: HttpFetchResponse) -> str:
    content_type = header_value(response.headers, "content-type")
    encoding = "utf-8"
    if "charset=" in content_type.lower():
        encoding = (
            content_type.lower()
            .split("charset=", 1)[1]
            .split(";", 1)[0]
            .strip()
        )
    return response.content.decode(encoding or "utf-8", errors="replace")


def request_json(
    method: str,
    url: str,
    **kwargs: Any,
) -> object:
    response = request_bytes(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code} for {url}")
    return json.loads(decode_response(response))
