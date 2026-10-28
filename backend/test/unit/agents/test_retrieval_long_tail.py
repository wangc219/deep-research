"""长尾科研检索回归：真实别名、标点变体、跨域锚点与来源独立性。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from platform_core.agents.middlewares.search_resilience import SearchResilienceMiddleware
from platform_core.agents.toolkits.buildin import tools as web
from platform_core.services.academic_retrieval_service import AcademicRetrievalService
from platform_core.services.aminer_client import AMinerClient


def record(title, url="https://example.edu/paper", content=""):
    """构造公开科研题录，不依赖真实供应商。"""
    return {"title": title, "url": url, "content": content}


def test_bilingual_aliases_do_not_require_both_languages_and_keep_other_identity_constraints():
    arguments = dict(required_term_groups=[["交错磁性", "altermagnetism"], ["自旋分裂", "spin splitting"]])
    output = web._filter_search_results(
        {
            "results": [
                record("Altermagnetism and spin splitting"),
                record("Magnetism and spin splitting", "https://other.edu/a"),
                record("Altermagnetism", "https://third.edu/a"),
            ]
        },
        "交错磁性 自旋分裂 近期实验",
        **arguments,
    )
    assert [item["title"] for item in output["results"]] == ["Altermagnetism and spin splitting"]
    assert output["filtered_irrelevant_count"] == 2


def test_new_name_unicode_hyphen_and_single_rare_anchor_survive_generic_context_words():
    result = web._filter_search_results(
        {
            "results": [
                record("Twisted‑bilayer excitons"),
                record("Generic semiconductor review", "https://other.edu/x"),
            ]
        },
        "twisted-bilayer latest experimental review",
        required_terms=["twisted-bilayer"],
    )
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Twisted‑bilayer excitons"


def test_result_diversity_deduplicates_tracking_without_rewriting_citations():
    original = "https://lab.edu/a?utm_source=search&id=1#abstract"
    output = web._filter_search_results(
        {
            "results": [
                record("Altermagnetism first", original),
                record("Altermagnetism second", "https://lab.edu/b"),
                record("Altermagnetism third", "https://lab.edu/c"),
                record("Altermagnetism independent", "https://journal.org/d"),
                record("Altermagnetism duplicate", "https://lab.edu/a?id=1&utm_source=other"),
            ]
        },
        "altermagnetism",
        count=3,
    )
    assert [item["title"] for item in output["results"]] == [
        "Altermagnetism first",
        "Altermagnetism second",
        "Altermagnetism independent",
    ]
    assert output["distinct_domains"] == 2
    assert output["results"][0]["url"] == original
    assert "utm_source=search&amp;id=1#abstract" in output["results"][0]["citation"]


def test_quoted_identity_is_mandatory_and_unverified_host_or_path_is_not_authority():
    result = web._filter_search_results(
        {
            "results": [
                record("phonon polariton measurements"),
                record("phonon experiment", "https://spoof.example/newsroom/releases/a"),
                record("phonon propagation and surface polariton", "https://other.edu/fragment"),
            ]
        },
        '"phonon polariton" experiment',
    )
    assert len(result["results"]) == 1
    assert (
        web._search_source_tier({"url": "https://spoof.example/newsroom/releases/a", "source_host": "nature.com"})
        == "other"
    )


def test_alias_constraints_are_in_cache_key_and_validated_at_tool_boundary():
    assert web._web_search_cache_key(
        ["public"], {"query": "spin", "required_term_groups": [["one"]]}
    ) != web._web_search_cache_key(["public"], {"query": "spin", "required_term_groups": [["two"]]})
    with pytest.raises(ValidationError):
        web.DoubaoSearchInput(query="spin", required_term_groups=[[]])
    with pytest.raises(ValidationError):
        web.DoubaoSearchInput(query="x" * 501)


def test_explorer_related_queries_charge_each_search_and_alias_only_search_is_allowed():
    explorer = SearchResilienceMiddleware(research_mode=True)
    explorer.research_academic_topic_calls = 6
    request = SimpleNamespace(
        tool_call={
            "id": "academic",
            "name": "academic_search",
            "args": {"query": "altermagnetism", "related_queries": ["spin splitting", "crystal symmetry"]},
        }
    )
    result = explorer.wrap_tool_call(request, lambda _: pytest.fail("must not overrun atomic budget"))
    assert "超出剩余" in result.content
    assert explorer.research_academic_topic_calls == 6
    request = SimpleNamespace(
        tool_call={
            "id": "alias",
            "name": "web_search",
            "args": {"query": "交错磁性", "required_term_groups": [["交错磁性", "altermagnetism"]]},
        }
    )
    assert explorer.wrap_tool_call(request, lambda _: {"results": []}) == {"results": []}
    assert explorer.research_web_calls == 1
    assert SearchResilienceMiddleware().max_calls == 8


@pytest.mark.asyncio
async def test_semantic_protocol_accepts_items_without_legacy_code_and_preserves_cursor():
    cursor = "next-page-token-0123456"

    def handler(request):
        assert request.method == "POST" and request.url.path.endswith("/paper/qa/searchPro")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [{"paper_id": "p", "title": "Altermagnetism"}],
                    "next_cursor": cursor,
                    "total": {"value": 40, "relation": "gte"},
                    "warnings": [],
                },
            },
        )

    client = AMinerClient(
        {"user_id": "u", "api_key": "test-key-with-at-least-32-characters"}, transport=httpx.MockTransport(handler)
    )
    found = await client.request("semantic_search", {"query": "altermagnetism"})
    assert found["data"][0]["paper_id"] == "p"
    assert found["next_cursor"] == cursor
    assert found["total"] == 40 and found["total_relation"] == "gte"


@pytest.mark.asyncio
async def test_semantic_discovery_keeps_rare_suffix_and_pages_with_only_supplier_cursor():
    service = AcademicRetrievalService(SimpleNamespace())
    query = (
        "Find experiments on electron transport in confined low temperature fluids "
        "with compensated collinear altermagnetism"
    )
    cursor = "next-page-token-0123456"
    service._request = AsyncMock(
        side_effect=[
            {
                "status": "ok",
                "data": [{"paper_id": "p", "title": "Altermagnetism"}],
                "next_cursor": cursor,
                "total": 100,
                "total_relation": "gte",
            },
            {"status": "ok", "data": [{"id": "p", "abstract_slice": "partial evidence"}]},
            {"status": "ok", "data": []},
        ]
    )
    result = await service.search(query, mode="semantic", any_terms=["altermagnetism"])
    assert service._request.call_args_list[0].args == (
        "semantic_search",
        {"query": query, "query_type": "auto", "sort": "relevance", "any_terms": ["altermagnetism"]},
    )
    assert result["results"][0]["id"] == "p"
    assert result["query_coverage"][0]["next_cursor"] == cursor
    await service.search(query, mode="semantic", cursor=cursor)
    assert service._request.call_args_list[-1].args == ("semantic_search", {"cursor": cursor})
    invalid = await service.search(query, mode="semantic", page=2)
    assert invalid["status"] == "invalid_request"


def test_single_alias_cannot_drop_cross_disciplinary_context_into_dictionary_hits():
    """名称命中不等于命中整个问题，普通词释义不得占据科研结果。"""
    result = web._filter_search_results(
        {
            "results": [
                record("Hydrodynamic definition and meaning", "https://dictionary.example/hydrodynamic"),
                record("Moiré pattern in photography", "https://dictionary.example/moire"),
                record("Viscous electron transport in graphene", "https://journal.edu/paper"),
            ]
        },
        "Hydrodynamic electron flow in graphene",
        required_term_groups=[["hydrodynamic", "viscous"]],
    )
    assert [item["url"] for item in result["results"]] == ["https://journal.edu/paper"]


def test_long_query_does_not_silently_lose_rare_identifying_suffix(monkeypatch):
    """回归旧的 100 字符切割，罕见名称位于后半段时仍传给供应商。"""
    query = (
        "experimental evidence in a confined low temperature electronic material with an unusual symmetry "
        + "altermagnetism"
    )
    observed = []
    monkeypatch.setattr(web, "_web_search_provider_order", lambda _: ["test"])
    monkeypatch.setattr(
        web,
        "_invoke_search_provider",
        lambda provider, args: (
            observed.append(args["query"]) or {"results": [record("Altermagnetism in confined material")]}
        ),
    )
    web._reset_web_search_runtime_state()
    result = web._resilient_web_search("test", {"query": query, "required_terms": ["altermagnetism"]})
    assert observed == [query]
    assert result["results"]
