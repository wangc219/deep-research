from __future__ import annotations

import asyncio

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools.evidence import EvidenceGovernor, normalize_url
from equipment_deep_research.tools.search import SearchAggregator, SearchHit, StaticSearchProvider


def _evidence(identifier: str, url: str, claim: str) -> EvidenceCard:
    return EvidenceCard(identifier, "source", url, "B", claim, "excerpt", "p:1", "raw", "agent")


def test_evidence_scoring_rejects_low_quality_and_retains_conflicts() -> None:
    governor = EvidenceGovernor()
    accepted = _evidence("ev-1", "https://a.example/item", "系统支持复杂环境探测能力")
    weak = governor.assess(_evidence("ev-2", "https://b.example/item", "系统不支持复杂环境探测能力"), {"relevance": .9, "transparency": .1, "freshness": .1, "direct_support": .1, "extraction_quality": .1}, existing=[accepted])
    assert weak.decision == "rejected"
    assert weak.conflict_group


def test_search_aggregates_public_providers_without_domain_allowlist() -> None:
    hit = SearchHit("A", "https://research.example.org/a", "lead", .7, [])
    rows = asyncio.run(SearchAggregator([StaticSearchProvider("a", [hit]), StaticSearchProvider("b", [hit])]).search("test"))
    assert len(rows) == 1
    assert rows[0].provider_names == ["a", "b"]


def test_search_aggregation_caches_and_deduplicates_concurrent_queries() -> None:
    calls = 0

    class _Provider:
        name = "slow"

        async def search(self, query, limit):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return [SearchHit(query, "https://example.org/result", "", 1, [self.name])]

    async def run():
        aggregator = SearchAggregator([_Provider()])
        first, second = await asyncio.gather(
            aggregator.search("Full-width Ｑｕｅｒｙ"),
            aggregator.search("full-width query"),
        )
        cached = await aggregator.search("full-width query")
        return first, second, cached

    first, second, cached = asyncio.run(run())
    assert calls == 1
    assert first == second == cached


def test_malformed_url_is_stable_governance_input() -> None:
    assert normalize_url("http://[2001:db8::1/").startswith("invalid:")


def test_search_provider_capacity_is_shared_across_queries_and_reusable_loops():
    active = peak = 0

    class Provider:
        name = 'bounded'

        async def search(self, query, limit):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
            return [SearchHit(query, 'https://example.org/' + query, '', 1, [])]

    aggregator = SearchAggregator([Provider(), Provider()], max_concurrency=2, cache_size=0)
    for _ in range(2):
        rows = asyncio.run(aggregator.search_many(['a', 'b', 'c'], max_concurrency=3))
        assert set(rows) == {'a', 'b', 'c'}
    assert peak == 2
    assert active == 0


def test_search_failure_does_not_poison_cache_and_operators_remain_distinct():
    calls = []

    class Provider:
        name = 'recovering'

        async def search(self, query, limit):
            calls.append(query)
            if len(calls) == 1:
                raise TimeoutError('transient provider failure')
            return [SearchHit(query, 'https://example.org/result', '', 1, [])]

    async def run():
        aggregator = SearchAggregator([Provider()])
        assert await aggregator.search('alpha -beta') == []
        assert await aggregator.search('alpha -beta')
        assert await aggregator.search('alpha beta')
        assert await aggregator.search('alpha -beta')

    asyncio.run(run())
    assert calls == ['alpha -beta', 'alpha -beta', 'alpha beta']
