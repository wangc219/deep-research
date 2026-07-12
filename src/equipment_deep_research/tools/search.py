"""Multi-provider public search aggregation. Search hits remain leads, not evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol

from equipment_deep_research.tools.evidence import normalize_url


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    rank: float
    provider_names: list[str]


class SearchProvider(Protocol):
    name: str
    async def search(self, query: str, limit: int) -> list[SearchHit]: ...


class StaticSearchProvider:
    def __init__(self, name: str, hits: list[SearchHit]) -> None:
        self.name, self.hits = name, hits

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        del query
        return self.hits[:limit]


class SearchAggregator:
    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        results = await asyncio.gather(*(provider.search(query, limit) for provider in self.providers), return_exceptions=True)
        merged: dict[str, SearchHit] = {}
        for provider, rows in zip(self.providers, results):
            if isinstance(rows, Exception):
                continue
            for row in rows:
                key = normalize_url(row.url)
                previous = merged.get(key)
                provider_names = sorted(set((previous.provider_names if previous else []) + row.provider_names + [provider.name]))
                merged[key] = replace(row, provider_names=provider_names, rank=max(row.rank, previous.rank if previous else 0))
        return sorted(merged.values(), key=lambda row: (-row.rank, -len(row.provider_names), row.url))[:limit]
