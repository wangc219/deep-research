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


def test_malformed_url_is_stable_governance_input() -> None:
    assert normalize_url("http://[2001:db8::1/").startswith("invalid:")
