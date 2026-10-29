from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from platform_core.services import searxng_service


class _AsyncClient:
    def __init__(self, *, health, search):
        self.get = AsyncMock(return_value=health)
        self.post = AsyncMock(return_value=search)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def _response(*, text="", payload=None, error=None):
    response = MagicMock(text=text)
    response.raise_for_status.side_effect = error
    response.json.return_value = payload
    return response


def test_unresponsive_engine_formats_are_normalized_without_losing_engine_identity():
    assert searxng_service.normalize_unresponsive_engines(
        [["brave", "timeout"], {"engine": "pubmed", "exception": "rate limited"}]
    ) == [
        {"provider": "searxng", "engine": "brave", "error": "timeout"},
        {"provider": "searxng", "engine": "pubmed", "error": "rate limited"},
    ]


@pytest.mark.asyncio
async def test_connection_test_reports_healthy_container_and_real_search(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    client = _AsyncClient(
        health=_response(text="OK\n"),
        search=_response(
            payload={
                "results": [{"title": "SearXNG", "url": "https://example.org"}],
                "unresponsive_engines": [["brave", "timeout"]],
            }
        ),
    )
    monkeypatch.setattr(searxng_service.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await searxng_service.test_searxng_connection({"general_engines": ["brave"], "searxng_timeout_seconds": 8})

    assert result["status"] == "ok"
    assert result["container_status"] == "ok"
    assert result["result_count"] == 1
    assert result["partial_failures"][0]["engine"] == "brave"
    assert client.post.await_args.kwargs["data"]["format"] == "json"


@pytest.mark.asyncio
async def test_connection_test_distinguishes_container_failure_from_outbound_failure(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    request = httpx.Request("GET", "http://searxng:8080/healthz")
    health_error = httpx.ConnectError("connection refused", request=request)
    failed_health = _AsyncClient(health=_response(error=health_error), search=_response(payload={}))
    monkeypatch.setattr(searxng_service.httpx, "AsyncClient", lambda **_kwargs: failed_health)

    unavailable = await searxng_service.test_searxng_connection({"general_engines": ["brave"]})

    assert unavailable["status"] == "unavailable"
    assert unavailable["container_status"] == "unavailable"
    assert unavailable["search_status"] == "not_run"

    search_request = httpx.Request("POST", "http://searxng:8080/search")
    search_error = httpx.ReadTimeout("upstream timed out", request=search_request)
    failed_search = _AsyncClient(health=_response(text="OK"), search=_response(error=search_error))
    monkeypatch.setattr(searxng_service.httpx, "AsyncClient", lambda **_kwargs: failed_search)

    degraded = await searxng_service.test_searxng_connection({"general_engines": ["brave"]})

    assert degraded["status"] == "degraded"
    assert degraded["container_status"] == "ok"
    assert degraded["search_status"] == "failed"
    assert "容器正常" in degraded["message"]
