"""Search tools and small adapters for whitelisted demand-discovery sources."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from knowledgegraph.demand_discovery.domain.open_search import OpenSourceLead
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.tools import ToolDefinition, ToolExecutionContext
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.bm25 import BM25Index
from knowledgegraph.demand_discovery.tools.keyword_gate import KeywordGate
from knowledgegraph.demand_discovery.tools.network import DEFAULT_HTTP_HEADERS


_REQUEST_PARAM_OBJECT_NAMES = {
    "args",
    "body",
    "data",
    "param",
    "params",
    "payload",
    "query",
    "queryparams",
    "request",
    "requestparams",
    "searchparams",
}
_SEARCH_API_TOKENS = (
    "docsearch",
    "search",
    "query",
    "/es/",
    "/api-surface/",
    "/api/search",
)
_NON_SEARCH_API_TOKENS = (
    "api-traffic",
    "/traffic/",
    "/analytics",
    "/collect",
    "/counter",
    "/metrics",
    "/poll",
    "/share",
    "/stat",
    "/tongji",
    "beacon",
)
_SOURCE_NOISE_TOKENS = {
    "81.cn",
    "csis",
    "defense",
    "defensenews",
    "news",
    "rand",
    "www.81.cn",
}


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source_name: str = ""
    source_tier: str = ""
    published: str | None = None
    source_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "published": self.published,
            "source_id": self.source_id,
        }


class SearchAdapter(Protocol):
    async def search(self, query: str, page: int) -> list[SearchHit]:
        ...


@dataclass(frozen=True)
class OpenSearchHit:
    title: str
    url: str
    snippet: str
    source_domain: str
    search_provider: str
    query_used: str

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source_domain": self.source_domain,
            "search_provider": self.search_provider,
            "query_used": self.query_used,
        }


class OpenSearchAdapter(Protocol):
    async def search(self, query: str, page: int) -> list[OpenSearchHit]:
        ...


class StaticOpenSearchAdapter:
    def __init__(self, hits: list[OpenSearchHit]) -> None:
        self._hits = list(hits)

    async def search(self, query: str, page: int) -> list[OpenSearchHit]:
        hits = list(self._hits)
        if query:
            query_bound_hits = [hit for hit in hits if hit.query_used.strip() == query.strip()]
            if query_bound_hits:
                hits = query_bound_hits
        if not query:
            return hits
        index = BM25Index([f"{hit.title} {hit.snippet}" for hit in hits])
        ranked = index.rank(query, top_k=len(self._hits))
        if ranked:
            return [hits[index] for index, _score in ranked]
        return hits


class StaticSearchAdapter:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = list(hits)

    async def search(self, query: str, page: int) -> list[SearchHit]:
        if not query:
            return list(self._hits)
        index = BM25Index([f"{hit.title} {hit.snippet}" for hit in self._hits])
        return [self._hits[index] for index, _score in index.rank(query, top_k=len(self._hits))]


class LocalCorpusAdapter:
    """Search text artifacts with BM25 and return artifact-backed hits."""

    def __init__(self, artifacts: ArtifactStore) -> None:
        self._artifacts = artifacts

    async def search(self, query: str, page: int) -> list[SearchHit]:
        records = self._artifacts.iter_records("text")
        texts = [record.path.read_text(encoding="utf-8", errors="replace") for record in records]
        if not texts:
            return []
        ranked = BM25Index(texts).rank(query, top_k=len(texts))
        hits: list[SearchHit] = []
        for index, score in ranked:
            if score <= 0:
                continue
            record = records[index]
            meta = record.meta
            title = str(meta.get("title") or record.ref)
            url = str(meta.get("url") or meta.get("final_url") or record.ref)
            snippet = f"{record.ref}: {texts[index][:180]}"
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=str(meta.get("source_name", "")),
                    source_tier=str(meta.get("source_tier", "")),
                    source_id=str(meta.get("source_id", "")) or None,
                )
            )
        return hits


class UrlTemplateAdapter:
    """Render a source search URL and parse obvious result links.

    This is intentionally conservative; site-specific parsers can replace it
    without changing the tool contract.
    """

    def __init__(
        self,
        *,
        source_name: str,
        source_tier: str,
        template: str,
        fetch_text,
    ) -> None:
        self.source_name = source_name
        self.source_tier = source_tier
        self.template = template
        self._fetch_text = fetch_text

    async def search(self, query: str, page: int) -> list[SearchHit]:
        url = self.template.format(query=quote(query), page=page)
        html = await self._fetch_text(url)
        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        for link in soup.find_all("a", href=True):
            title = " ".join(link.get_text(" ", strip=True).split())
            if not title:
                continue
            snippet = _nearby_snippet(link)
            hits.append(
                SearchHit(
                    title=title,
                    url=urljoin(url, str(link.get("href", ""))),
                    snippet=snippet,
                    source_name=self.source_name,
                    source_tier=self.source_tier,
                )
            )
        return hits


class DynamicApiSearchAdapter:
    """Discover same-site JSON search APIs from search pages and scripts.

    The adapter is intentionally heuristic and source-agnostic: it follows a
    configured search page, inspects inline/external JavaScript for GET search
    endpoints, carries over literal/variable defaults from request parameter
    objects, then tries common query parameter names. It never executes page JS.
    """

    def __init__(
        self,
        *,
        source_name: str,
        source_tier: str,
        template: str,
        allowed_hosts: list[str],
        default_queries: list[str] | None = None,
        fetch_text,
        fetch_json=None,
    ) -> None:
        self.source_name = source_name
        self.source_tier = source_tier
        self.template = template
        self.allowed_hosts = [host.lower() for host in allowed_hosts]
        self.default_queries = [item for item in (default_queries or []) if item.strip()]
        self._fetch_text = fetch_text
        self._fetch_json = fetch_json or _default_fetch_json

    async def search(self, query: str, page: int) -> list[SearchHit]:
        if _site_directives_target_other_hosts(query, self.allowed_hosts):
            return []
        fallback_hits: list[SearchHit] = []
        for search_query in _dynamic_query_variants(query):
            search_url = self.template.format(query=quote(search_query), page=page)
            html = await self._fetch_text(search_url)
            fallback_hits.extend(
                _parse_result_links(
                    html,
                    search_url,
                    source_name=self.source_name,
                    source_tier=self.source_tier,
                )
            )
            specs = await _discover_dynamic_api_specs(
                html,
                search_url,
                allowed_hosts=self.allowed_hosts,
                fetch_text=self._fetch_text,
            )
            query_keys = _query_key_order(search_url, specs)
            hits: list[SearchHit] = []
            for spec in specs:
                for query_key in query_keys:
                    params = dict(spec.params)
                    params["pageNumber"] = page
                    params.setdefault("pageSize", 10)
                    params[query_key] = search_query
                    try:
                        payload = await self._fetch_json(spec.url, params)
                    except Exception:
                        continue
                    hits.extend(
                        _hits_from_json(
                            payload,
                            source_name=self.source_name,
                            source_tier=self.source_tier,
                        )
                    )
                    ranked_hits = _rank_hits_for_query(search_query, hits)
                    if ranked_hits:
                        return ranked_hits
            ranked_hits = _rank_hits_for_query(search_query, hits)
            if ranked_hits:
                return ranked_hits
        return _rank_hits_for_query(query, fallback_hits)


def build_default_search_adapters(
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    fetch_text=None,
) -> list[SearchAdapter]:
    adapters: list[SearchAdapter] = [LocalCorpusAdapter(artifacts)]
    for entry in registry.search_entries():
        if entry.search.type == "url_template" and entry.search.template:
            adapters.append(
                UrlTemplateAdapter(
                    source_name=entry.source_name,
                    source_tier=entry.source_tier,
                    template=entry.search.template,
                    fetch_text=fetch_text or _default_fetch_text,
                )
            )
        if entry.search.type == "dynamic_api" and entry.search.template:
            adapters.append(
                DynamicApiSearchAdapter(
                    source_name=entry.source_name,
                    source_tier=entry.source_tier,
                    template=entry.search.template,
                    allowed_hosts=entry.hosts,
                    fetch_text=fetch_text or _default_fetch_text,
                )
            )
    return adapters


def create_search_sources_tool(
    registry: SourceRegistry,
    keyword_gate: KeywordGate,
    *,
    adapters: list[SearchAdapter] | None = None,
) -> ToolDefinition:
    adapter_list = list(adapters or [])

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        query = str(call.arguments["query"])
        page = max(1, int(call.arguments.get("page", 1)))
        top_k = max(1, int(call.arguments.get("top_k", 10)))
        all_hits: list[dict[str, object]] = []
        for adapter in adapter_list:
            for hit in await adapter.search(query, page):
                entry = registry.match(hit.url)
                if entry is None:
                    continue
                gate = keyword_gate.score(f"{hit.title} {hit.snippet}")
                query_score = _query_relevance_score(query, f"{hit.title} {hit.snippet}")
                if _query_requires_relevance(query) and query_score <= 0:
                    continue
                row = hit.to_dict()
                row["source_name"] = hit.source_name or entry.source_name
                row["source_tier"] = hit.source_tier or entry.source_tier
                row["keyword_score"] = gate["score"]
                row["keyword_hits"] = gate["hits"]
                row["query_score"] = query_score
                all_hits.append(row)
        all_hits.sort(
            key=lambda item: (
                int(item.get("query_score", 0)),
                int(item.get("keyword_score", 0)),
                _tier_weight(str(item.get("source_tier", ""))),
            ),
            reverse=True,
        )
        selected = all_hits[:top_k]
        lines = [
            (
                f"{index + 1}. {hit['title']} | tier={hit['source_tier']} | "
                f"score={hit['keyword_score']} | {hit['url']}"
            )
            for index, hit in enumerate(selected)
        ]
        return ToolResult(
            call.id,
            call.name,
            "\n".join(lines) if lines else "no whitelisted search hits",
            {"query": query, "page": page, "hits": selected, "total_hits": len(all_hits)},
        )

    return ToolDefinition(
        name="search_sources",
        description="Search configured whitelisted sources and rank hits with keyword signals.",
        parameters_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "page": {"type": "integer"},
                "top_k": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
    )


def create_open_search_sources_tool(
    domain_store: DomainStore | None,
    registry: SourceRegistry,
    *,
    adapters: list[OpenSearchAdapter] | None = None,
) -> ToolDefinition:
    adapter_list = list(adapters or [])

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        plan_id = str(args.get("open_search_plan_id", "")).strip()
        if not plan_id:
            return ToolResult(
                call.id,
                call.name,
                "open_search_plan_id is required",
                {},
                is_error=True,
            )
        if domain_store is None or plan_id not in domain_store.open_search_plans:
            return ToolResult(
                call.id,
                call.name,
                f"unknown open_search_plan_id: {plan_id}",
                {"open_search_plan_id": plan_id},
                is_error=True,
            )
        plan = domain_store.open_search_plans[plan_id]
        if plan.status not in {"planned", "running"}:
            return ToolResult(
                call.id,
                call.name,
                f"open search plan is not active: {plan.status}",
                {"open_search_plan_id": plan_id, "status": plan.status},
                is_error=True,
            )
        query = str(args.get("query", "")).strip()
        allowed_queries = {item.strip() for item in plan.queries if item.strip()}
        if query not in allowed_queries:
            return ToolResult(
                call.id,
                call.name,
                "query is outside OpenSearchPlan.queries",
                {
                    "open_search_plan_id": plan_id,
                    "query": query,
                    "allowed_queries": sorted(allowed_queries),
                },
                is_error=True,
            )
        used_result_count = sum(
            1
            for lead in domain_store.open_source_leads.values()
            if lead.plan_id == plan_id
        )
        remaining_budget = plan.allowed_result_count - used_result_count
        if remaining_budget <= 0:
            return ToolResult(
                call.id,
                call.name,
                "open search result budget exhausted",
                {
                    "open_search_plan_id": plan_id,
                    "allowed_result_count": plan.allowed_result_count,
                    "used_result_count": used_result_count,
                },
                is_error=True,
            )
        page = max(1, int(args.get("page", 1)))
        top_k = max(1, int(args.get("top_k", plan.allowed_result_count)))
        rows: list[dict[str, object]] = []
        proposals: list[DomainWriteProposal] = []
        lead_ids: list[str] = []
        known_lead_ids = {
            lead.lead_id
            for lead in domain_store.open_source_leads.values()
            if lead.plan_id == plan_id
        }
        for adapter in adapter_list:
            for hit in await adapter.search(query, page):
                scope, excluded_reason = _open_search_scope(registry, hit.url)
                row = hit.to_dict()
                row["source_scope"] = scope
                row["excluded_reason"] = excluded_reason
                if scope == "open_web":
                    lead_id = _open_source_lead_id(plan_id, hit.url)
                    row["open_source_lead_id"] = lead_id
                    if lead_id in known_lead_ids:
                        row["budget_status"] = "duplicate_existing"
                        rows.append(row)
                        continue
                    if len(lead_ids) >= remaining_budget:
                        row["budget_status"] = "skipped_budget_exhausted"
                        rows.append(row)
                        continue
                    lead = OpenSourceLead(
                        lead_id=lead_id,
                        plan_id=plan_id,
                        run_id=plan.run_id,
                        round_id=plan.round_id,
                        topic=plan.topic,
                        url=hit.url,
                        domain=hit.source_domain or (urlparse(hit.url).hostname or ""),
                        title=hit.title,
                        snippet=hit.snippet,
                        source_name_guess=hit.source_domain,
                        search_query=hit.query_used or query,
                        source_scope="open_web",
                        quality_status="pending",
                        created_at=_now_dt(),
                        updated_at=_now_dt(),
                    )
                    lead_ids.append(lead.lead_id)
                    known_lead_ids.add(lead.lead_id)
                    proposals.append(
                        DomainWriteProposal(
                            "upsert",
                            "OpenSourceLead",
                            lead.to_dict(),
                        )
                    )
                rows.append(row)
        selected = rows[:top_k]
        selected_lead_ids = [
            str(row["open_source_lead_id"])
            for row in selected
            if row.get("source_scope") == "open_web"
            and row.get("open_source_lead_id")
            and not row.get("budget_status")
        ]
        selected_proposals = [
            proposal
            for proposal in proposals
            if str(proposal.payload.get("lead_id")) in selected_lead_ids
        ]
        lead_trace_proposals = [
            DomainTraceProposal(
                event_type="open_source_lead_recorded",
                target_type="OpenSourceLead",
                target_id=str(proposal.payload.get("lead_id", "")),
                payload_summary=(
                    "recorded open source lead "
                    f"{proposal.payload.get('lead_id', '')}"
                ),
                input_refs=[plan_id],
                output_refs=[str(proposal.payload.get("lead_id", ""))],
                payload={
                    "open_search_plan_id": plan_id,
                    "url": str(proposal.payload.get("url", "")),
                    "title": str(proposal.payload.get("title", "")),
                    "search_query": str(proposal.payload.get("search_query", "")),
                    "source_scope": "open_web",
                },
            )
            for proposal in selected_proposals
            if proposal.object_type == "OpenSourceLead"
        ]
        lines = [
            _open_search_result_line(index + 1, row)
            for index, row in enumerate(selected)
        ]
        return ToolResult(
            call.id,
            call.name,
            "\n".join(lines) if lines else "no open search hits",
            {
                "open_search_plan_id": plan_id,
                "query": query,
                "page": page,
                "hits": selected,
                "total_hits": len(rows),
                "open_source_lead_ids": selected_lead_ids,
                "allowed_result_count": plan.allowed_result_count,
                "used_result_count": used_result_count,
                "remaining_budget_before": remaining_budget,
                "remaining_budget_after": remaining_budget - len(selected_lead_ids),
            },
            domain_proposals=selected_proposals,
            trace_proposals=[
                *lead_trace_proposals,
                DomainTraceProposal(
                    event_type="open_search_completed",
                    target_type="OpenSearchPlan",
                    target_id=plan_id,
                    payload_summary=f"open search completed for {plan_id}",
                    input_refs=[plan_id],
                    output_refs=selected_lead_ids,
                    payload={
                        "query": query,
                        "hit_count": len(selected),
                        "open_source_lead_ids": selected_lead_ids,
                        "allowed_result_count": plan.allowed_result_count,
                        "used_result_count": used_result_count + len(selected_lead_ids),
                    },
                )
            ],
        )

    return ToolDefinition(
        name="open_search_sources",
        description=(
            "Search open web candidates only after an OpenSearchPlan exists; "
            "records OpenSourceLead for open_web hits."
        ),
        parameters_schema={
            "type": "object",
            "required": ["open_search_plan_id", "query"],
            "properties": {
                "open_search_plan_id": {"type": "string"},
                "query": {"type": "string"},
                "page": {"type": "integer"},
                "top_k": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
    )


def create_open_search_sources_batch_tool(
    domain_store: DomainStore | None,
    registry: SourceRegistry,
    *,
    adapters: list[OpenSearchAdapter] | None = None,
) -> ToolDefinition:
    adapter_list = list(adapters or [])

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        plan_id = str(args.get("open_search_plan_id", "")).strip()
        if not plan_id:
            return ToolResult(
                call.id,
                call.name,
                "open_search_plan_id is required",
                {},
                is_error=True,
            )
        if domain_store is None or plan_id not in domain_store.open_search_plans:
            return ToolResult(
                call.id,
                call.name,
                f"unknown open_search_plan_id: {plan_id}",
                {"open_search_plan_id": plan_id},
                is_error=True,
            )
        plan = domain_store.open_search_plans[plan_id]
        if plan.status not in {"planned", "running"}:
            return ToolResult(
                call.id,
                call.name,
                f"open search plan is not active: {plan.status}",
                {"open_search_plan_id": plan_id, "status": plan.status},
                is_error=True,
            )
        queries = _dedupe_strings(
            [str(item).strip() for item in args.get("queries", []) if str(item).strip()]
        )
        if not queries:
            return ToolResult(
                call.id,
                call.name,
                "queries is required",
                {"open_search_plan_id": plan_id},
                is_error=True,
            )
        allowed_queries = {item.strip() for item in plan.queries if item.strip()}
        outside_queries = [query for query in queries if query not in allowed_queries]
        if outside_queries:
            return ToolResult(
                call.id,
                call.name,
                "query is outside OpenSearchPlan.queries",
                {
                    "open_search_plan_id": plan_id,
                    "queries": outside_queries,
                    "allowed_queries": sorted(allowed_queries),
                },
                is_error=True,
            )
        used_result_count = sum(
            1
            for lead in domain_store.open_source_leads.values()
            if lead.plan_id == plan_id
        )
        remaining_budget = plan.allowed_result_count - used_result_count
        if remaining_budget <= 0:
            return ToolResult(
                call.id,
                call.name,
                "open search result budget exhausted",
                {
                    "open_search_plan_id": plan_id,
                    "allowed_result_count": plan.allowed_result_count,
                    "used_result_count": used_result_count,
                },
                is_error=True,
            )
        page = max(1, int(args.get("page", 1)))
        top_k_per_query = max(1, int(args.get("top_k_per_query", 3)))
        hits_by_query = await _open_search_hits_by_query(
            adapter_list,
            queries=queries,
            page=page,
        )
        selected: list[dict[str, object]] = []
        total_hits = 0
        for query in queries:
            rows_for_query: list[dict[str, object]] = []
            for hit in hits_by_query.get(query, []):
                scope, excluded_reason = _open_search_scope(registry, hit.url)
                row = hit.to_dict()
                row["query"] = query
                row["source_scope"] = scope
                row["excluded_reason"] = excluded_reason
                if scope == "open_web":
                    row["open_source_lead_id"] = _open_source_lead_id(plan_id, hit.url)
                rows_for_query.append(row)
            total_hits += len(rows_for_query)
            selected.extend(rows_for_query[:top_k_per_query])

        existing_lead_ids = {
            lead.lead_id
            for lead in domain_store.open_source_leads.values()
            if lead.plan_id == plan_id
        }
        new_lead_ids: list[str] = []
        proposals: list[DomainWriteProposal] = []
        for row in selected:
            if row.get("source_scope") != "open_web" or not row.get("open_source_lead_id"):
                continue
            lead_id = str(row["open_source_lead_id"])
            if lead_id in existing_lead_ids:
                row["budget_status"] = "duplicate_existing"
                continue
            if lead_id in new_lead_ids:
                row["budget_status"] = "duplicate_selected"
                continue
            if len(new_lead_ids) >= remaining_budget:
                row["budget_status"] = "skipped_budget_exhausted"
                continue
            lead = OpenSourceLead(
                lead_id=lead_id,
                plan_id=plan_id,
                run_id=plan.run_id,
                round_id=plan.round_id,
                topic=plan.topic,
                url=str(row.get("url", "")),
                domain=str(row.get("source_domain") or (urlparse(str(row.get("url", ""))).hostname or "")),
                title=str(row.get("title", "")),
                snippet=str(row.get("snippet", "")),
                source_name_guess=str(row.get("source_domain", "")),
                search_query=str(row.get("query_used") or row.get("query") or ""),
                source_scope="open_web",
                quality_status="pending",
                created_at=_now_dt(),
                updated_at=_now_dt(),
            )
            new_lead_ids.append(lead.lead_id)
            proposals.append(
                DomainWriteProposal(
                    "upsert",
                    "OpenSourceLead",
                    lead.to_dict(),
                )
            )

        lead_trace_proposals = [
            DomainTraceProposal(
                event_type="open_source_lead_recorded",
                target_type="OpenSourceLead",
                target_id=str(proposal.payload.get("lead_id", "")),
                payload_summary=(
                    "recorded open source lead "
                    f"{proposal.payload.get('lead_id', '')}"
                ),
                input_refs=[plan_id],
                output_refs=[str(proposal.payload.get("lead_id", ""))],
                payload={
                    "open_search_plan_id": plan_id,
                    "url": str(proposal.payload.get("url", "")),
                    "title": str(proposal.payload.get("title", "")),
                    "search_query": str(proposal.payload.get("search_query", "")),
                    "source_scope": "open_web",
                },
            )
            for proposal in proposals
            if proposal.object_type == "OpenSourceLead"
        ]
        lines = [
            _open_search_result_line(index + 1, row)
            for index, row in enumerate(selected)
        ]
        return ToolResult(
            call.id,
            call.name,
            "\n".join(lines) if lines else "no open search hits",
            {
                "open_search_plan_id": plan_id,
                "queries": queries,
                "query_count": len(queries),
                "page": page,
                "top_k_per_query": top_k_per_query,
                "hits": selected,
                "total_hits": total_hits,
                "open_source_lead_ids": new_lead_ids,
                "allowed_result_count": plan.allowed_result_count,
                "used_result_count": used_result_count,
                "remaining_budget_before": remaining_budget,
                "remaining_budget_after": remaining_budget - len(new_lead_ids),
            },
            domain_proposals=proposals,
            trace_proposals=[
                *lead_trace_proposals,
                DomainTraceProposal(
                    event_type="open_search_completed",
                    target_type="OpenSearchPlan",
                    target_id=plan_id,
                    payload_summary=f"open search batch completed for {plan_id}",
                    input_refs=[plan_id],
                    output_refs=new_lead_ids,
                    payload={
                        "queries": queries,
                        "query_count": len(queries),
                        "hit_count": len(selected),
                        "open_source_lead_ids": new_lead_ids,
                        "allowed_result_count": plan.allowed_result_count,
                        "used_result_count": used_result_count + len(new_lead_ids),
                    },
                ),
            ],
        )

    return ToolDefinition(
        name="open_search_sources_batch",
        description=(
            "Search multiple OpenSearchPlan queries in one provider-backed batch; "
            "records deduplicated OpenSourceLead rows for open_web hits."
        ),
        parameters_schema={
            "type": "object",
            "required": ["open_search_plan_id", "queries"],
            "properties": {
                "open_search_plan_id": {"type": "string"},
                "queries": {"type": "array", "items": {"type": "string"}},
                "page": {"type": "integer"},
                "top_k_per_query": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
    )


async def _open_search_hits_by_query(
    adapter_list: list[OpenSearchAdapter],
    *,
    queries: list[str],
    page: int,
) -> dict[str, list[OpenSearchHit]]:
    results: dict[str, list[OpenSearchHit]] = {query: [] for query in queries}
    tasks = [
        _search_open_query(adapter, query, page)
        for query in queries
        for adapter in adapter_list
    ]
    if not tasks:
        return results
    for query, hits in await asyncio.gather(*tasks):
        results.setdefault(query, []).extend(hits)
    return results


async def _search_open_query(
    adapter: OpenSearchAdapter,
    query: str,
    page: int,
) -> tuple[str, list[OpenSearchHit]]:
    return query, await adapter.search(query, page)


def _open_search_scope(registry: SourceRegistry, url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return "excluded", "unsupported_url_scheme"
    entry = registry.match(url)
    if entry is not None:
        return "whitelisted", ""
    host = (parsed.hostname or "").lower()
    for excluded in registry.excluded:
        if any(_host_matches_allowed(host, [item.lower()]) for item in excluded.hosts):
            return "excluded", excluded.reason
    return "open_web", ""


def _open_source_lead_id(plan_id: str, url: str) -> str:
    digest = hashlib.sha256(f"{plan_id}:{url}".encode("utf-8")).hexdigest()[:12]
    return f"osl-{digest}"


def _open_search_result_line(index: int, row: dict[str, object]) -> str:
    lead_text = (
        f" | open_source_lead_id={row['open_source_lead_id']}"
        if row.get("source_scope") == "open_web" and row.get("open_source_lead_id")
        else ""
    )
    query_text = f" | query={row['query']}" if row.get("query") else ""
    return (
        f"{index}. {row['title']} | scope={row['source_scope']}"
        f"{lead_text}{query_text} | {row['url']}"
    )


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _tier_weight(tier: str) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(tier.upper(), 0)


def _dynamic_query_variants(query: str) -> list[str]:
    stripped = _strip_site_directives(query).strip()
    return _dedupe_strings([stripped])


def _strip_site_directives(query: str) -> str:
    return " ".join(re.sub(r"\bsite:\S+", " ", query, flags=re.I).split())


def _site_directive_hosts(query: str) -> list[str]:
    return [
        match.group(1).strip().lower()
        for match in re.finditer(r"\bsite:([^\s]+)", query, flags=re.I)
        if match.group(1).strip()
    ]


def _site_directives_target_other_hosts(query: str, allowed_hosts: list[str]) -> bool:
    hosts = _site_directive_hosts(query)
    if not hosts:
        return False
    return not any(_host_matches_allowed(host, allowed_hosts) for host in hosts)


def _host_matches_allowed(host: str, allowed_hosts: list[str]) -> bool:
    normalized = host.strip().lower()
    return any(
        normalized == allowed or normalized.endswith(f".{allowed}")
        for allowed in allowed_hosts
    )


def _rank_hits_for_query(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    deduped = _dedupe_hits(hits)
    if not _query_requires_relevance(query):
        return deduped
    scored = [
        (_query_relevance_score(query, f"{hit.title} {hit.snippet}"), index, hit)
        for index, hit in enumerate(deduped)
    ]
    relevant = [row for row in scored if row[0] > 0]
    relevant.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    return [hit for _score, _index, hit in relevant]


def _query_requires_relevance(query: str) -> bool:
    return bool(_site_directive_hosts(query)) or '"' in query or len(_query_tokens(query)) >= 2


def _query_relevance_score(query: str, text: str) -> int:
    haystack = _normalize_query_text(text)
    score = 0
    for phrase in re.findall(r'"([^"]+)"', query):
        normalized = _normalize_query_text(phrase)
        if normalized and normalized in haystack:
            score += max(3, len(normalized) // 2)
    for token in _query_tokens(_strip_site_directives(query)):
        normalized = _normalize_query_text(token)
        if not normalized or normalized in _SOURCE_NOISE_TOKENS:
            continue
        if normalized in haystack:
            score += 1
    return score


def _query_tokens(query: str) -> list[str]:
    text = _strip_site_directives(query)
    return [
        token
        for token in re.split(r"""[\s,，;；|()（）\[\]{}"'“”‘’]+""", text)
        if len(token.strip()) >= 2
    ]


def _normalize_query_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text).strip().lower())


def _nearby_snippet(link) -> str:
    parent = link.parent
    text = " ".join(parent.get_text(" ", strip=True).split()) if parent else ""
    if text and text != link.get_text(" ", strip=True):
        return text[:240]
    next_p = link.find_next("p")
    if next_p is not None:
        return " ".join(next_p.get_text(" ", strip=True).split())[:240]
    return ""


async def _default_fetch_text(url: str) -> str:
    return await asyncio.to_thread(_requests_text, url)


async def _default_fetch_json(url: str, params: dict[str, object]) -> object:
    return await asyncio.to_thread(_requests_json, url, params)


def _requests_text(url: str) -> str:
    import requests

    response = requests.get(
        url,
        timeout=30,
        headers=DEFAULT_HTTP_HEADERS,
    )
    response.raise_for_status()
    if not response.encoding:
        response.encoding = response.apparent_encoding
    return response.text


def _requests_json(url: str, params: dict[str, object]) -> object:
    import requests

    response = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            **DEFAULT_HTTP_HEADERS,
            "Accept": "application/json,text/plain,*/*",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    response.raise_for_status()
    return response.json()


@dataclass(frozen=True)
class _DynamicApiSpec:
    url: str
    params: dict[str, object]
    query_keys: list[str]


async def _discover_dynamic_api_specs(
    html: str,
    page_url: str,
    *,
    allowed_hosts: list[str],
    fetch_text,
) -> list[_DynamicApiSpec]:
    scripts = await _script_texts(html, page_url, allowed_hosts, fetch_text)
    specs: list[_DynamicApiSpec] = []
    for script in scripts:
        defaults = _script_defaults(script)
        endpoints = _script_endpoint_urls(script, page_url, allowed_hosts)
        query_keys = _script_query_keys(script)
        if not endpoints:
            continue
        for endpoint in endpoints:
            specs.append(
                _DynamicApiSpec(
                    url=endpoint,
                    params=defaults,
                    query_keys=query_keys,
                )
            )
    return _dedupe_specs(specs)


async def _script_texts(
    html: str,
    page_url: str,
    allowed_hosts: list[str],
    fetch_text,
) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[str] = []
    for script in soup.find_all("script"):
        if not isinstance(script, Tag):
            continue
        src = str(script.get("src", "") or "").strip()
        if src:
            script_url = urljoin(page_url, src)
            if _host_allowed(script_url, allowed_hosts):
                try:
                    rows.append(await fetch_text(script_url))
                except Exception:
                    pass
            continue
        text = script.string or script.get_text(" ", strip=False)
        if text:
            rows.append(text)
    return rows


def _script_endpoint_urls(
    script: str,
    page_url: str,
    allowed_hosts: list[str],
) -> list[str]:
    rows: list[str] = []
    patterns = [
        r"url\s*:\s*([^,\n\r}]+)",
        r"fetch\(\s*([^,\n\r)]+)",
        r"\.open\(\s*['\"]GET['\"]\s*,\s*([^,\n\r)]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, script, flags=re.I):
            url = _resolve_js_url_expression(match.group(1), page_url)
            if _looks_like_json_search_endpoint(url) and _host_allowed(url, allowed_hosts):
                rows.append(url)
    return _dedupe_strings(rows)


def _resolve_js_url_expression(expression: str, page_url: str) -> str:
    fragments = [
        _strip_js_string(match.group(0))
        for match in re.finditer(r"""(?:"[^"]*"|'[^']*')""", expression)
    ]
    if not fragments:
        return ""
    value = "".join(fragments)
    parsed = urlparse(page_url)
    if value.startswith("//"):
        return f"{parsed.scheme}:{value}"
    return urljoin(page_url, value)


def _script_defaults(script: str) -> dict[str, object]:
    variable_defaults: dict[str, object] = {}
    for match in re.finditer(
        r"\b(?:var|let|const)\s+([A-Za-z_][\w$-]*)\s*=\s*("
        r"\"[^\"]*\"|'[^']*'|\d+|true|false)",
        script,
    ):
        variable_defaults[match.group(1)] = _parse_js_value(match.group(2))
    for match in re.finditer(
        r"\b(?:var|let|const)\s+([A-Za-z_][\w$-]*)\s*=\s*[^;\n\r?]+"
        r"\?\s*[^:\n\r;]+:\s*(\"[^\"]*\"|'[^']*'|\d+|true|false)",
        script,
    ):
        variable_defaults[match.group(1)] = _parse_js_value(match.group(2))
    for match in re.finditer(
        r"\bif\s*\(\s*!\s*([A-Za-z_][\w$-]*)\s*\)\s*{\s*\1\s*=\s*("
        r"\"[^\"]*\"|'[^']*'|\d+|true|false)",
        script,
        flags=re.S,
    ):
        variable_defaults[match.group(1)] = _parse_js_value(match.group(2))
    defaults: dict[str, object] = {}
    for body in _request_param_object_bodies(script):
        for match in re.finditer(
            r"""["']?([A-Za-z_][\w$-]*)["']?\s*:\s*("[^"]*"|'[^']*'|\d+|true|false|[A-Za-z_][\w$-]*)""",
            body,
        ):
            key = match.group(1)
            raw = match.group(2)
            if _is_query_key(key):
                continue
            value = variable_defaults.get(raw, _parse_js_value(raw))
            if value is not None and key not in defaults:
                defaults[key] = value
    return defaults


def _request_param_object_bodies(script: str) -> list[str]:
    rows: list[str] = []
    for match in re.finditer(
        r"(?:\b(?:var|let|const)\s+)?([A-Za-z_][\w$-]*)\s*=\s*{",
        script,
    ):
        name = match.group(1).lower()
        if name not in _REQUEST_PARAM_OBJECT_NAMES:
            continue
        body = _balanced_brace_body(script, match.end() - 1)
        if body:
            rows.append(body)
    for match in re.finditer(r"\bdata\s*:\s*{", script):
        body = _balanced_brace_body(script, match.end() - 1)
        if body:
            rows.append(body)
    return rows


def _balanced_brace_body(text: str, open_index: int) -> str:
    depth = 0
    quote_char = ""
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote_char:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote_char:
                quote_char = ""
            continue
        if char in {"'", '"'}:
            quote_char = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index]
    return ""


def _script_query_keys(script: str) -> list[str]:
    keys = []
    for match in re.finditer(
        r"""["']?([A-Za-z_][\w$-]*)["']?\s*:\s*(?:keyword|query|searchTerm|searchText)\b""",
        script,
    ):
        key = match.group(1)
        if _is_query_key(key):
            keys.append(key)
    return _dedupe_strings(keys)


def _query_key_order(
    search_url: str,
    specs: list[_DynamicApiSpec],
) -> list[str]:
    query = parse_qs(urlparse(search_url).query)
    preferred: list[str] = []
    field = " ".join(str(item) for values in query.values() for item in values).upper()
    if "CONTENT" in field:
        preferred.append("content")
    if "TITLE" in field:
        preferred.append("title")
    for spec in specs:
        preferred.extend(spec.query_keys)
    preferred.extend(["content", "title", "keyword", "q", "query", "search", "searchText"])
    return _dedupe_strings(preferred)


def _hits_from_json(
    payload: object,
    *,
    source_name: str,
    source_tier: str,
) -> list[SearchHit]:
    rows: list[SearchHit] = []
    for item in _iter_dicts(payload):
        url = _first_text_field(item, ["url", "link", "href", "pageUrl", "sourceUrl"])
        if not url:
            nested = item.get("manuscriptData")
            if isinstance(nested, dict):
                url = _first_text_field(nested, ["url", "link", "href", "pageUrl"])
        if not url or not urlparse(url).scheme:
            continue
        title = _clean_html(_first_text_field(item, ["title", "name", "headline"]) or url)
        snippet = _clean_html(
            _first_text_field(
                item,
                ["desc", "description", "summary", "snippet", "contentText", "content"],
            )
        )
        published = _first_text_field(item, ["published", "publishTime", "issueTime", "date"])
        rows.append(
            SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                source_name=source_name,
                source_tier=source_tier,
                published=published or None,
            )
        )
    return _dedupe_hits(rows)


def _iter_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _parse_result_links(
    html: str,
    base_url: str,
    *,
    source_name: str,
    source_tier: str,
) -> list[SearchHit]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[SearchHit] = []
    for link in soup.find_all("a", href=True):
        title = " ".join(link.get_text(" ", strip=True).split())
        if not title:
            continue
        rows.append(
            SearchHit(
                title=title,
                url=urljoin(base_url, str(link.get("href", ""))),
                snippet=_nearby_snippet(link),
                source_name=source_name,
                source_tier=source_tier,
            )
        )
    return _dedupe_hits(rows)


def _first_text_field(item: dict[str, object], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _parse_js_value(raw: str) -> object:
    text = str(raw).strip()
    if text in {"true", "false"}:
        return text == "true"
    if text.isdigit():
        return int(text)
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return _strip_js_string(text)
    return None


def _strip_js_string(value: str) -> str:
    try:
        return str(json.loads(value.replace("'", '"')))
    except Exception:
        return value[1:-1]


def _is_query_key(key: str) -> bool:
    return key in {"content", "title", "keyword", "q", "query", "search", "searchText"}


def _looks_like_json_search_endpoint(url: str) -> bool:
    lower = url.lower()
    if not url:
        return False
    if any(token in lower for token in _NON_SEARCH_API_TOKENS):
        return False
    return any(token in lower for token in _SEARCH_API_TOKENS)


def _host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def _dedupe_specs(specs: list[_DynamicApiSpec]) -> list[_DynamicApiSpec]:
    rows: list[_DynamicApiSpec] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.url in seen:
            continue
        seen.add(spec.url)
        rows.append(spec)
    return rows


def _dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    rows: list[SearchHit] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.url in seen:
            continue
        seen.add(hit.url)
        rows.append(hit)
    return rows


def _dedupe_strings(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows


def _clean_html(value: str) -> str:
    if re.match(r"^https?://", value or ""):
        return value
    soup = BeautifulSoup(value or "", "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())
