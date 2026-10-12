"""可选知识库与独立公网检索的外发、权限和错误边界。"""

import asyncio
import copy
import json

import httpx
import pytest

from document_research.engine import Engine
from document_research.providers import HttpProviders, ProviderError
from document_research.tests.test_engine import CONFIG, LOCAL, TASK, SyntheticProviders


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("mode", ["answer", "research"])
def test_local_only_never_calls_unselected_zhipu(configured, mode):
    config = copy.deepcopy(CONFIG)
    if not configured:
        config.pop("zhipu")
    provider = SyntheticProviders()
    if mode == "answer":
        provider.output = {
            "answer": [
                {"text": "资料提及表格", "source_id": "S1", "quote": LOCAL["text"]}
            ],
            "gaps": [],
            "graph": [],
        }
    result = asyncio.run(
        Engine(lambda: config, provider).run(
            {**TASK, "mode": mode}, [LOCAL], lambda: None
        )
    )
    assert result["sources"]
    assert [call[0] for call in provider.calls] == ["model"]


def test_configured_zhipu_only_receives_selected_library():
    config = copy.deepcopy(CONFIG)
    config["zhipu"]["libraries"]["alice"].append({"id": "kb-b"})
    provider = SyntheticProviders()
    asyncio.run(
        Engine(lambda: config, provider).retrieve(
            {**TASK, "library_ids": ["local-a", "zhipu:kb-b"]}, [LOCAL], lambda: None
        )
    )
    assert provider.calls == [("zhipu", ["kb-b"], TASK["problem"])]


def envelope(**changes):
    return {
        "status": "ok",
        "data": {
            "results": [
                {
                    "title": "Docling docs",
                    "url": "https://docling-project.github.io/docling/",
                    "description": "Docling converts tables.",
                }
            ],
            **changes,
        },
    }


def test_open_websearch_without_zhipu_sends_only_public_keyword():
    requests, checks = [], []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=envelope(
                partialFailures=[
                    {"engine": "duckduckgo", "error": "private diagnostic"}
                ]
            ),
        )

    provider = HttpProviders(httpx.MockTransport(handle))
    sources, warnings = asyncio.run(
        provider.search_public("", "Docling table", lambda: checks.append(1))
    )
    assert len(requests) == 1 and len(checks) == 2
    assert str(requests[0].url) == "http://127.0.0.1:3210/search"
    assert "authorization" not in requests[0].headers
    assert json.loads(requests[0].content) == {
        "query": "Docling table",
        "limit": 10,
        "engines": ["bing", "duckduckgo"],
        "searchMode": "request",
    }
    assert sources[0]["content_kind"] == "search_excerpt"
    assert any("部分搜索引擎失败" in warning for warning in warnings)
    assert "private diagnostic" not in "".join(warnings)


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "error": "private"},
        {"status": "ok"},
        envelope(results=[None]),
        envelope(partialFailures="invalid"),
    ],
)
def test_open_websearch_rejects_failed_or_invalid_responses(response):
    provider = HttpProviders(
        httpx.MockTransport(
            lambda request, response=response: httpx.Response(200, json=response)
        )
    )
    with pytest.raises(ProviderError):
        asyncio.run(provider.search_public("", "Docling table", lambda: None))


@pytest.mark.parametrize(
    "settings",
    [
        {"base_url": "http://external.example"},
        {"base_url": "http://user:secret@localhost:3210"},
        {"base_url": "http://localhost:3210?key=secret"},
        {"engines": [{}]},
        {"provider": "invalid"},
    ],
)
def test_invalid_search_configuration_never_sends_request(settings):
    def unexpected(request):
        pytest.fail("invalid settings reached network")

    provider = HttpProviders(
        httpx.MockTransport(unexpected), lambda: {"web_search": settings}
    )
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.search_public("", "Docling table", lambda: None))
    assert "secret" not in str(error.value)


def test_open_websearch_empty_and_filtered_results_are_distinct_from_failure():
    for response in [
        envelope(results=[]),
        envelope(
            results=[
                {
                    "title": "untrusted",
                    "url": "https://unrelated.example",
                    "description": "unrelated",
                }
            ]
        ),
    ]:
        provider = HttpProviders(
            httpx.MockTransport(
                lambda request, response=response: httpx.Response(200, json=response)
            )
        )
        sources, _ = asyncio.run(
            provider.search_public("", "Docling table", lambda: None)
        )
        assert sources == []


def test_open_websearch_response_cannot_survive_revocation():
    def revoke():
        raise PermissionError("revoked")

    provider = HttpProviders(
        httpx.MockTransport(lambda request: httpx.Response(200, json=envelope()))
    )
    with pytest.raises(PermissionError):
        asyncio.run(provider.search_public("", "Docling table", revoke))
