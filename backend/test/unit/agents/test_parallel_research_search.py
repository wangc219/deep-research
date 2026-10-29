import asyncio
import time
from types import SimpleNamespace

import pytest

from platform_core.agents.toolkits.buildin import academic
from platform_core.agents.toolkits.buildin import tools as web_tools


def test_three_channel_merge_deduplicates_doi_and_preserves_high_value_metadata():
    web = {
        "status": "ok",
        "provider": "fusion",
        "completed_providers": ["open-websearch", "searxng"],
        "attempted_providers": ["open-websearch", "searxng"],
        "results": [
            {
                "title": "Sparse array radar field experiment",
                "url": "https://doi.org/10.1000/radar?utm_source=search",
                "content": "Sparse array radar field experiment evidence",
                "providers": ["open-websearch", "searxng"],
                "search_engines": ["bing", "brave"],
                "source_tier": "authoritative",
            },
            {
                "title": "Radar programme announcement",
                "url": "https://example.gov/radar",
                "content": "Radar programme announcement and test schedule",
                "providers": ["searxng"],
                "source_tier": "authoritative",
            },
        ],
    }
    aminer = {
        "status": "ok",
        "results": [
            {
                "id": "paper-1",
                "doi": "10.1000/radar",
                "title": "Sparse array radar field experiment",
                "url": "https://doi.org/10.1000/radar",
                "content": "Full abstract with experiment conditions and limitations.",
                "content_level": "abstract",
            },
            {
                "id": "paper-2",
                "title": "Sparse radar calibration method",
                "url": "https://www.aminer.cn/pub/paper-2",
                "content": "Partial abstract about sparse radar calibration.",
                "content_level": "partial_abstract",
            },
        ],
    }

    result = academic._merge_parallel_research_results("sparse radar experiment", web, aminer, count=10)

    assert result["status"] == "ok"
    assert result["search_mode"] == "three_channel_parallel"
    assert result["completed_providers"] == ["open-websearch", "searxng", "aminer"]
    assert result["channel_summary"] == {
        "web_candidates": 2,
        "academic_candidates": 2,
        "unique_candidates": 3,
        "cross_channel_matches": 1,
    }
    hybrid = next(item for item in result["results"] if item["evidence_type"] == "hybrid")
    assert hybrid["providers"] == ["open-websearch", "searxng", "aminer"]
    assert hybrid["content_level"] == "abstract"
    assert hybrid["cross_channel_match"] is True
    assert hybrid["citation"].startswith('<cite source="https://doi.org/10.1000/radar')


@pytest.mark.asyncio
async def test_parallel_research_tool_runs_web_fusion_and_aminer_concurrently(monkeypatch):
    calls = {}

    def web_search(query, **kwargs):
        calls["web"] = (query, kwargs)
        time.sleep(0.1)
        return {
            "status": "ok",
            "provider": "fusion",
            "completed_providers": ["open-websearch", "searxng"],
            "results": [
                {
                    "title": "Radar test evidence",
                    "url": "https://example.org/radar",
                    "content": "Radar test evidence",
                    "providers": ["open-websearch", "searxng"],
                }
            ],
        }

    async def academic_search(self, query, **kwargs):  # noqa: ARG001
        calls["aminer"] = (query, kwargs)
        await asyncio.sleep(0.1)
        return {"status": "ok", "results": []}

    monkeypatch.setattr(web_tools, "execute_public_web_search", web_search)
    monkeypatch.setattr(academic.AcademicRetrievalService, "search", academic_search)
    started = time.monotonic()
    result = await academic.parallel_research_search.coroutine(
        "radar test",
        runtime=SimpleNamespace(context=SimpleNamespace()),
        count=5,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.18
    assert calls["web"][1]["fusion_strategy"] == "parallel"
    assert calls["aminer"][1]["limit"] == 5
    assert calls["aminer"][1]["mode"] == "precision"
    assert result["completed_providers"] == ["open-websearch", "searxng", "aminer"]
