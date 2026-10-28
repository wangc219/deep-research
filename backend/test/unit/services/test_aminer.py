"""AMiner 协议、证据和检索策略测试，不发送真实供应商请求。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

from platform_core.services.aminer_client import AMinerClient, AMinerError, deduplicate_papers, normalize_paper
from platform_core.services.academic_retrieval_service import ACADEMIC_RETRIEVAL_PROMPT, AcademicRetrievalService
from platform_core.agents.middlewares.summary import _structured_search_preview


def test_equipment_evidence_prompt_preserves_autonomy_and_uncertainty():
    """检索按需辅助研究，不将技术解释固定成推演链条。"""
    for requirement in (
        "以用户目标为主线",
        "不规定对话步骤、章节或固定推演链条",
        "不要求先有现成装备或已知技术瓶颈",
        "涉及技术实现且需要新证据、原理启发或可行性核实时",
        "不为每个构想强行匹配论文",
        "不要求逐项展开部件、迁移差距或验证方案",
        "取得或引用摘要不等于研究完成",
        "论文结论、类比迁移、工程推断和待验证假设分开表达",
        "不将论文级结果等同于装备级可用性",
        "不改变纯论文查询的回答范围",
    ):
        assert requirement in ACADEMIC_RETRIEVAL_PROMPT
    assert "论文已支持的机制—当前瓶颈—应用部件或分系统" not in ACADEMIC_RETRIEVAL_PROMPT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier",
    [
        "2407.16833",
        "arXiv:2307.03172v2",
        "10.18653/v1/2024.emnlp-industry.66",
        "https://arxiv.org/abs/2407.16833",
        "cs/9901001",
    ],
)
async def test_external_identifiers_are_recoverable_without_provider_or_budget_request(identifier):
    """错误编号不会向供应商发送或误触发服务熔断，并给出重新定位路径。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(side_effect=AssertionError("must not spend a provider request"))
    papers = await service.get_papers([identifier])
    references = await service.get_references(identifier)
    assert papers["status"] == references["status"] == "invalid_paper_id"
    assert papers["invalid_paper_ids"] == [identifier]
    assert "academic_search" in papers["message"]
    assert papers["results"] == []
    service._request.assert_not_awaited()


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
    assert "需要论文发现、新证据或事实核实时，优先使用 academic_search" in enabled
    assert "分析已有充分材料时不重复检索" in enabled
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


@pytest.mark.asyncio
async def test_joint_search_deduplicates_queries_and_papers_and_preserves_each_angle():
    """重复术语不占额度，不同角度交错保留，摘要补全不能降级已有证据。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {
                "status": "ok",
                "total": 8,
                "data": [
                    {"id": "a", "doi": "10.1/shared", "title": "Shared", "abstract": "full evidence"},
                    {"id": "b", "title": "First angle"},
                ],
            },
            {
                "status": "ok",
                "total": 2,
                "data": [
                    {"_id": "a", "doi": "10.1/SHARED", "title": "Shared"},
                    {"_id": "c", "title": "Second angle"},
                ],
            },
            {
                "status": "ok",
                "data": [
                    {"id": "a", "abstract": None, "abstract_slice": "shorter", "authors": [{"name": "Researcher"}]},
                    {"id": "b", "abstract_slice": "first summary"},
                    {"id": "c", "abstract_slice": "second summary"},
                    {"id": "unrequested", "abstract": "must not leak into candidates"},
                ],
            },
        ]
    )
    result = await service.search("  雷达  识别 ", related_queries=["雷达 识别", "SAR ATR"], limit=3)
    assert service._request.await_count == 3
    assert service._request.call_args_list[0].args[1]["keyword"] == "雷达 识别"
    assert service._request.call_args_list[1].args[1]["keyword"] == "SAR ATR"
    assert [paper["id"] for paper in result["results"]] == ["a", "b", "c"]
    shared = result["results"][0]
    assert shared["content"] == "full evidence"
    assert shared["authors"] == ["Researcher"]
    assert shared["matched_queries"] == ["雷达 识别", "SAR ATR"]
    assert result["total"] is None
    assert result["query_coverage"][0]["next_page"] == 2
    assert result["query_coverage"][1]["next_page"] is None
    assert result["evidence_gaps"]["partial_abstract_ids"] == ["b", "c"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_calls", [("limit_reached", 3), ("auth_failed", 2)])
async def test_joint_search_stops_on_failure_and_reports_unsearched_queries(status, expected_calls):
    """中途失败保留首个查询的证据，明确哪些角度没有执行。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "a", "title": "Paper", "abstract_slice": "evidence"}]},
            {"status": status, "message": "blocked"},
            {"status": "ok", "data": []},
        ]
    )
    result = await service.search("first", related_queries=["second", "third"])
    assert result["status"] == "partial" and result["aminer_status"] == status
    assert result["failed_endpoint"] == "search"
    assert result["unsearched_queries"] == ["third"]
    assert result["results"][0]["content"] == "evidence"
    assert service._request.await_count == expected_calls


@pytest.mark.asyncio
async def test_joint_search_limits_results_after_diverse_candidate_selection():
    """候选多于交付上限时保留两个角度，并明确截断量。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "a"}, {"id": "b"}]},
            {"status": "ok", "data": [{"id": "c"}, {"id": "d"}]},
            {"status": "ok", "data": []},
        ]
    )
    result = await service.search("first", related_queries=["second"], limit=2)
    assert [paper["id"] for paper in result["results"]] == ["a", "c"]
    assert result["unique_candidates"] == 4 and result["omitted_candidates"] == 2
    assert service._request.call_args_list[-1].args == ("info", {"ids": ["a", "c"]})


@pytest.mark.asyncio
async def test_empty_search_does_not_claim_the_technology_does_not_exist():
    """空命中保持成功状态，提示检索范围局限且不额外请求详情。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(return_value={"status": "ok", "data": []})
    result = await service.search("rare topic")
    assert result["status"] == "ok" and result["results"] == []
    assert "不代表技术不存在" in result["retrieval_guidance"]
    assert service._request.await_count == 2


@pytest.mark.asyncio
async def test_empty_topic_uses_concise_free_title_fallback_before_reporting_no_hit():
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": []},
            {"status": "ok", "data": [{"id": "p", "title": "Altermagnetism"}]},
            {"status": "ok", "data": [{"id": "p", "abstract_slice": "spin splitting"}]},
        ]
    )
    result = await service.search("altermagnetism")
    assert result["results"][0]["id"] == "p"
    assert service._request.call_args_list[1].args == (
        "title_search",
        {"page": 1, "size": 10, "title": "altermagnetism"},
    )
    assert result["query_coverage"][1]["mode"] == "title_fallback"


@pytest.mark.asyncio
async def test_long_topic_is_compacted_before_paid_search_and_reports_original_query():
    """模型把任务整句当关键词时，边界压缩为少量技术术语，避免已知的长式空命中。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "paper", "title": "Microwave source paper"}]},
            {"status": "ok", "data": [{"id": "paper", "abstract_slice": "evidence"}]},
        ]
    )
    original = (
        "solid-state high-power microwave counter-UAV military weapon system "
        "engineering implementation feasibility limitations review"
    )

    result = await service.search(original)

    sent = service._request.call_args_list[0].args[1]["keyword"]
    assert len(sent.split()) <= 6
    assert sent != original
    assert result["query"] == original
    assert result["query_coverage"][0]["requested_query"] == original
    assert result["results"][0]["id"] == "paper"


@pytest.mark.asyncio
async def test_short_topic_removes_generic_research_modifiers_without_losing_identity():
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "paper", "title": "Quantum sensing"}]},
            {"status": "ok", "data": [{"id": "paper", "abstract_slice": "evidence"}]},
        ]
    )

    await service.search("quantum sensing emerging mechanisms")

    assert service._request.call_args_list[0].args[1]["keyword"] == "quantum sensing"


@pytest.mark.asyncio
async def test_title_search_retries_one_distinctive_identifier_before_giving_up():
    """模型对网页标题的轻微改写不应使免费标题定位失效。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": []},
            {"status": "ok", "data": [{"id": "paper", "title": "SwarmFuzz: Discovering GPS Spoofing Attacks"}]},
            {"status": "ok", "data": [{"id": "paper", "abstract_slice": "direct evidence"}]},
        ]
    )

    result = await service.search("SwarmFuzz GPS spoofing attacks drone swarms", mode="title")

    assert result["results"][0]["id"] == "paper"
    assert [call.args[1]["title"] for call in service._request.call_args_list[:2]] == [
        "SwarmFuzz GPS spoofing attacks drone swarms",
        "SwarmFuzz",
    ]
    assert result["query_coverage"][1]["query"] == "SwarmFuzz"


@pytest.mark.asyncio
async def test_free_metadata_limit_does_not_prevent_paid_detail_retrieval():
    """免费接口次数耗尽仍能取得选定论文完整摘要。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "limit_reached", "message": "free limit"},
            {"status": "ok", "data": [{"_id": "a", "title": "Paper", "abstract": "complete evidence"}]},
        ]
    )
    result = await service.get_papers(["a", "a"])
    assert result["results"][0]["content_level"] == "abstract"
    assert result["failed_endpoint"] == "info"
    assert result["missing_paper_ids"] == result["missing_abstract_ids"] == []
    assert service._request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("full_abstract", [True, False])
async def test_missing_papers_and_abstracts_are_not_reported_as_complete(full_abstract):
    """HTTP 成功不代表取得了每篇论文或完整摘要，缺口逐项返回。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "a", "abstract_slice": "partial"}]},
            {"status": "ok", "data": [{"id": "a", "abstract": None}]},
            {"status": "ok", "data": []},
        ]
    )
    result = await service.get_papers(["a", "missing"], full_abstract=full_abstract)
    assert result["status"] == "partial" and result["aminer_status"] == "ok"
    assert result["missing_paper_ids"] == ["missing"]
    assert result["missing_abstract_ids"] == (["a", "missing"] if full_abstract else [])
    assert result["results"][0]["content"] == "partial"


def test_joint_search_schema_rejects_blank_queries_and_unbounded_expansion():
    """模型输入在工具边界限制扩展数量与空白检索词。"""
    from pydantic import ValidationError
    from platform_core.agents.toolkits.buildin.academic import AcademicSearchInput

    for arguments in [
        {"query": "   "},
        {"query": "topic", "related_queries": ["  "]},
        {"query": "topic", "related_queries": ["one", "two", "three"]},
    ]:
        with pytest.raises(ValidationError):
            AcademicSearchInput(**arguments)


@pytest.mark.asyncio
async def test_enrichment_auth_failure_takes_precedence_over_search_limit():
    """发现阶段用尽额度后若补全发生鉴权故障，不能掩盖全局故障。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        side_effect=[
            {"status": "ok", "data": [{"id": "a", "title": "Paper"}]},
            {"status": "limit_reached", "message": "search limit"},
            {"status": "auth_failed", "message": "auth failed"},
        ]
    )
    result = await service.search("topic", related_queries=["second angle"])
    assert result["status"] == "partial" and result["results"][0]["id"] == "a"
    assert result["aminer_status"] == "auth_failed" and result["failed_endpoint"] == "info"


@pytest.mark.asyncio
async def test_references_are_deduplicated_before_limiting_and_report_truncation():
    """重复参考文献不挤占限额，并明确工具只展示了部分文献。"""
    service = AcademicRetrievalService(SimpleNamespace())
    service._request = AsyncMock(
        return_value={
            "status": "ok",
            "data": [
                {
                    "id": "root",
                    "cited": [
                        {"id": "a"},
                        {"id": "a"},
                        {"id": "b"},
                        {"id": "c"},
                    ],
                }
            ],
        }
    )
    result = await service.get_references("root", limit=2)
    assert [paper["id"] for paper in result["results"]] == ["a", "b"]
    assert result["reference_count"] == 3 and result["omitted_references"] == 1
    assert result["one_hop"] and result["relation"] == "references"


def test_joint_search_compression_keeps_paper_identity_before_verbose_coverage():
    """联合检索覆盖说明不能挤掉压缩上下文中的全部论文身份。"""
    import json

    papers = [normalize_paper({"id": f"paper-{index}", "title": f"Paper {index}"}) for index in range(10)]
    result = AcademicRetrievalService._result({"status": "ok"}, query="public topic", papers=papers)
    result["query_coverage"] = [
        {"query": "term " * 40, "status": "ok", "page": 1, "returned": 10, "next_page": 2} for _ in range(3)
    ]
    result["unsearched_queries"] = []
    preview = json.loads(_structured_search_preview("academic_search", result, 1200))
    assert preview["results"][0]["id"] == "paper-0"
    assert preview["results"][0]["content_level"] == "metadata"
    assert len(preview["query_coverage"]) == 3
    assert preview["evidence_gap_counts"]["metadata_only_ids"] == 10
