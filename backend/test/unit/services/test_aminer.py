"""AMiner 协议、证据和检索策略测试，不发送真实供应商请求。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

from platform_core.services.aminer_client import AMinerClient, AMinerError, deduplicate_papers, normalize_paper
from platform_core.services.academic_retrieval_service import AcademicRetrievalService
from platform_core.agents.middlewares.summary import _structured_search_preview


@pytest.mark.asyncio
async def test_jwt_and_bulk_post_are_official_rest_protocol():
    """鉴权使用短期 JWT 原文，批量题录用 POST JSON。"""

    def handler(request):
        token = request.headers["Authorization"]
        assert not token.startswith("Bearer ")
        claims = jwt.decode(token, "test-key-with-at-least-32-characters", algorithms=["HS256"])
        assert claims["user_id"] == "test-user"
        assert claims["exp"] - claims["timestamp"] == 600
        assert jwt.get_unverified_header(token)["sign_type"] == "SIGN"
        assert request.method == "POST"
        assert request.content == b'{"ids":["paper-1"]}'
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    client = AMinerClient(
        {"user_id": "test-user", "api_key": "test-key-with-at-least-32-characters"},
        transport=httpx.MockTransport(handler),
    )
    assert (await client.request("info", {"ids": ["paper-1"]}))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["search", "title_search", "info", "detail", "references"])
async def test_success_with_null_data_is_an_empty_result(endpoint):
    """真实供应商的成功空响应不能误触发故障降级。"""
    client = AMinerClient(
        {"user_id": "u", "api_key": "test-key-with-at-least-32-characters"},
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 200, "success": True, "data": None})),
    )
    assert (await client.request(endpoint, {}))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "Bearer "])
async def test_official_console_token_is_sent_without_resigning(prefix):
    """控制台 JWT 可直接接入，兼容粘贴 Bearer 前缀且不二次签名。"""
    token = jwt.encode(
        {"user_id": "test-user", "exp": 2_000_000_000}, "test-key-with-at-least-32-characters", algorithm="HS256"
    )

    def handler(request):
        assert request.headers["Authorization"] == token
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    client = AMinerClient(
        {"user_id": "test-user", "api_key": prefix + token},
        transport=httpx.MockTransport(handler),
    )
    assert (await client.request("title_search", {"title": "public paper"}))["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [200, 500])
@pytest.mark.parametrize(
    "code,status,retryable",
    [
        (40301, "auth_failed", False),
        (40302, "auth_failed", False),
        (40307, "auth_failed", False),
        (40308, "auth_failed", False),
        (40306, "rate_limited", False),
        (40001, "invalid_request", False),
        (50001, "unavailable", True),
    ],
)
async def test_business_error_does_not_leak_response(code, status, retryable, http_status):
    """稳定业务状态控制重试，不透出供应商原始错误。"""
    client = AMinerClient(
        {"user_id": "u", "api_key": "test-key-with-at-least-32-characters"},
        transport=httpx.MockTransport(
            lambda request: httpx.Response(http_status, json={"code": code, "message": "secret-response"})
        ),
    )
    with pytest.raises(AMinerError) as error:
        await client.request("search", {"keyword": "public research"})
    assert error.value.status == status
    assert error.value.retryable is retryable
    assert "secret-response" not in str(error.value)


def test_evidence_deduplicates_doi_and_retains_complete_abstract():
    """同一论文只算一个来源，详情不丢失既有 DOI。"""
    records = [
        normalize_paper({"id": "a", "doi": "https://doi.org/10.1/Test", "title": "Paper"}),
        normalize_paper({"id": "b", "doi": "10.1/test", "abstract_slice": "partial"}),
        normalize_paper({"id": "b", "abstract": "complete"}),
    ]
    papers = deduplicate_papers(records)
    assert len(papers) == 1
    assert papers[0]["content_level"] == "abstract"
    assert papers[0]["content"] == "complete"
    assert papers[0]["title"] == "Paper"
    assert papers[0]["url"].startswith("https://doi.org/")
    assert normalize_paper({"id": "empty"})["content_level"] == "metadata"


@pytest.mark.asyncio
async def test_pagination_evidence_tiers_and_empty_references():
    """统一页码映射到不同接口；空参考文献不是后续引用者。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "p", "title": "Paper"}]},
            {"status": "ok", "data": [{"id": "p", "abstract_slice": "partial"}]},
            {"status": "ok", "data": []},
            {"status": "ok", "data": [{"id": "p", "cited": None}]},
        ]
    )
    result = await service.search("topic", page=2)
    assert service._request.call_args_list[0].args == ("search", {"page": 1, "size": 10, "keyword": "topic"})
    assert result["results"][0]["content_level"] == "partial_abstract"
    await service.search("known title", mode="title", page=2)
    assert service._request.call_args_list[2].args == ("title_search", {"page": 2, "size": 10, "title": "known title"})
    references = await service.get_references("p")
    assert references["results"] == []
    assert references["relation"] == "references"


def test_compression_retains_paper_identity_and_evidence():
    """长摘要压缩仍可追溯论文和证据层级。"""
    import json

    paper = normalize_paper({"id": "p", "doi": "10.1/test", "title": "Paper", "abstract": "long text " * 1000})
    preview = json.loads(_structured_search_preview("academic_get_papers", {"status": "ok", "results": [paper]}, 1000))
    result = preview["results"][0]
    assert result["id"] == "p"
    assert result["doi"] == "10.1/test"
    assert result["content_level"] == "abstract"
    assert result["url"] == paper["url"]
    assert result["retrieved_at"] == paper["retrieved_at"]


@pytest.mark.asyncio
async def test_registered_tool_receives_runtime_without_exposing_identity(monkeypatch):
    """通过真实 ToolNode 注入可信上下文，模型参数不包含身份和凭证。"""
    from langgraph.graph import MessagesState, StateGraph, START, END
    from langgraph.prebuilt import ToolNode
    from langchain_core.messages import AIMessage
    from platform_core.agents.context import BaseContext
    from platform_core.agents.toolkits.buildin import academic

    expected = BaseContext(uid="trusted-user", run_id="trusted-run")
    seen = []

    class FakeService:
        def __init__(self, context):
            seen.append(context)

        async def search(self, query, **kwargs):
            assert query == "public topic"
            return {"status": "ok", "results": []}

    monkeypatch.setattr(academic, "AcademicRetrievalService", FakeService)
    graph = StateGraph(MessagesState, context_schema=BaseContext)
    graph.add_node("tools", ToolNode([academic.academic_search]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    response = await graph.compile().ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "academic_search",
                            "args": {"query": "public topic"},
                            "id": "call-academic",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
        context=expected,
    )
    assert seen == [expected]
    assert response["messages"][-1].name == "academic_search"
    assert response["messages"][-1].status == "success"
    properties = academic.academic_search.tool_call_schema.model_json_schema()["properties"]
    assert not {"uid", "run_id", "worker_id", "api_key", "runtime"} & properties.keys()


def test_smart_and_subagent_prompt_route_academic_questions_conditionally():
    """共享智能体提示只在学术工具可用时自动引导科研检索。"""
    from platform_core.agents.context import BaseContext
    from platform_core.agents.buildin.chatbot.prompt import build_prompt_with_context

    enabled = build_prompt_with_context(BaseContext(tools=["academic_search"], workdir_path="/projects/test"))
    assert "科研技术问题" in enabled and "优先调用 academic_search" in enabled
    assert "不是后续引用者" in enabled
    disabled = build_prompt_with_context(BaseContext(tools=["web_search"], workdir_path="/projects/test"))
    assert "# 学术检索与论文证据" not in disabled


@pytest.mark.asyncio
async def test_connection_uses_free_title_search_and_does_not_mutate_config(monkeypatch):
    """草稿只参与一次免费鉴权，失败可降级且不会写配置。"""
    from platform_core.services import academic_retrieval_service as module

    saved = {"user_id": "saved-user", "api_key": "saved-key"}
    monkeypatch.setattr(module.aminer_api_opts.__class__, "get", AsyncMock(return_value=saved))
    request = AsyncMock(return_value={"code": 200, "success": True, "data": []})
    monkeypatch.setattr(module.AMinerClient, "request", request)
    result = await module.test_aminer_connection(object(), user_id="draft-user", api_key="draft-key")
    assert result["status"] == "ok"
    request.assert_awaited_once_with("title_search", {"title": "Attention Is All You Need", "page": 1, "size": 1})
    assert saved == {"user_id": "saved-user", "api_key": "saved-key"}
