"""Multi-provider public search aggregation. Search hits remain leads, not evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import re
import time
import unicodedata
from collections.abc import Sequence
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
    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        max_concurrency: int = 8,
        cache_size: int = 128,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.providers = providers
        self.max_concurrency = max(1, min(64, int(max_concurrency)))
        self.cache_size = max(0, min(4096, int(cache_size)))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache: dict[tuple[str, int], tuple[float, list[SearchHit]]] = {}
        self._in_flight: dict[tuple[str, int], asyncio.Task[list[SearchHit]]] = {}
        self._provider_loop: asyncio.AbstractEventLoop | None = None
        self._provider_semaphore: asyncio.Semaphore | None = None

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        normalized_query = _query_key(query)
        if not normalized_query or not self.providers:
            return []
        normalized_limit = max(1, min(100, int(limit)))
        key = (normalized_query, normalized_limit)
        cached = self._cache_get(key)
        if cached is not None:
            return list(cached)
        existing = self._in_flight.get(key)
        if existing is not None:
            return list(await asyncio.shield(existing))
        task = asyncio.create_task(
            self._search_uncached(query=str(query).strip(), limit=normalized_limit)
        )
        self._in_flight[key] = task
        task.add_done_callback(lambda completed: self._finish_in_flight(key, completed))
        # The task is shielded so cancellation of one caller does not cancel
        # a shared provider request used by another caller.
        rows = await asyncio.shield(task)
        return list(rows)

    def _finish_in_flight(
        self,
        key: tuple[str, int],
        task: asyncio.Task[list[SearchHit]],
    ) -> None:
        self._in_flight.pop(key, None)
        if task.cancelled():
            return
        try:
            rows = task.result()
        except BaseException:
            return
        # An empty response may mean every provider temporarily failed. Let
        # the next caller retry instead of caching a false evidence gap.
        if rows:
            self._cache_put(key, rows)

    async def search_many(
        self,
        queries: Sequence[str],
        *,
        limit: int = 10,
        max_concurrency: int | None = None,
    ) -> dict[str, list[SearchHit]]:
        """Run a deduplicated query batch with bounded fan-out.

        Dynamic research often discovers several gaps at once.  This method
        collapses exact/formatting duplicates and lets the aggregator share
        its provider cache, while the semaphore prevents a large Query from
        opening one task per provider per gap.
        """

        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw in queries:
            original = str(raw or "").strip()
            key = _query_key(original)
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append((key, original))
        if not ordered:
            return {}
        semaphore = asyncio.Semaphore(
            self.max_concurrency if max_concurrency is None
            else max(1, min(64, int(max_concurrency)))
        )

        async def run(item: tuple[str, str]) -> tuple[str, list[SearchHit]]:
            key, original = item
            async with semaphore:
                return key, await self.search(original, limit=limit)

        rows = await asyncio.gather(*(run(item) for item in ordered))
        return dict(rows)

    async def _search_uncached(self, *, query: str, limit: int) -> list[SearchHit]:
        # All concurrent queries share the same provider capacity. Recreate
        # the gate when a CLI caller reuses the aggregator in a new loop.
        loop = asyncio.get_running_loop()
        if self._provider_loop is not loop:
            self._provider_loop = loop
            self._provider_semaphore = asyncio.Semaphore(self.max_concurrency)
        provider_semaphore = self._provider_semaphore
        assert provider_semaphore is not None

        async def call(provider: SearchProvider) -> list[SearchHit]:
            async with provider_semaphore:
                return await provider.search(query, limit)

        results = await asyncio.gather(
            *(call(provider) for provider in self.providers),
            return_exceptions=True,
        )
        merged: dict[str, SearchHit] = {}
        for provider, rows in zip(self.providers, results):
            if isinstance(rows, BaseException):
                if isinstance(rows, asyncio.CancelledError):
                    raise rows
                continue
            for row in rows:
                key = normalize_url(row.url)
                previous = merged.get(key)
                provider_names = sorted(set((previous.provider_names if previous else []) + row.provider_names + [provider.name]))
                merged[key] = replace(row, provider_names=provider_names, rank=max(row.rank, previous.rank if previous else 0))
        return sorted(
            merged.values(),
            key=lambda row: (-row.rank, -len(row.provider_names), row.url),
        )[:limit]

    def _cache_get(self, key: tuple[str, int]) -> list[SearchHit] | None:
        if not self.cache_ttl_seconds:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        timestamp, rows = entry
        if time.monotonic() - timestamp >= self.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return rows

    def _cache_put(self, key: tuple[str, int], rows: list[SearchHit]) -> None:
        if self.cache_size <= 0:
            return
        if len(self._cache) >= self.cache_size and key not in self._cache:
            oldest = min(self._cache, key=lambda item: self._cache[item][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (time.monotonic(), list(rows))


def _query_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    # Quotes, minus signs and other search operators change query meaning.
    # Keep them so different evidence requests never share a cache entry.
    return re.sub(r"\s+", " ", text).strip()
