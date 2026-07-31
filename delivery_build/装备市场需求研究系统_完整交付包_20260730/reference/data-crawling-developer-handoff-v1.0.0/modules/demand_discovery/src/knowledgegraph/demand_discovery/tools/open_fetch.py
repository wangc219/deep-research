"""Plan-scoped fetching for open-web leads."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import time
from urllib.parse import urlparse

from knowledgegraph.demand_discovery.domain.open_search import OpenSourceBodyArtifact
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.tools import ToolDefinition, ToolExecutionContext
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.http_transport import (
    DEFAULT_HTTP_HEADERS,
    HttpFetchResponse,
    HttpTransport,
    decode_response,
    default_http_transport,
    header_value,
)
from knowledgegraph.demand_discovery.tools.network import UNTRUSTED_NOTICE
from knowledgegraph.demand_discovery.tools.page_simplify import simplify


def create_fetch_open_source_page_tool(
    domain_store: DomainStore | None,
    artifacts: ArtifactStore,
    *,
    http_transport: HttpTransport | None = None,
    timeout_ms: int = 30_000,
    max_bytes: int = 2_000_000,
) -> ToolDefinition:
    transport = http_transport or _default_transport

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        plan_id = str(call.arguments["open_search_plan_id"]).strip()
        lead_id = str(call.arguments["open_source_lead_id"]).strip()
        url = str(call.arguments["url"]).strip()
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return _error(call, "unsupported URL scheme for fetch_open_source_page", {"url": url})
        if domain_store is None or plan_id not in domain_store.open_search_plans:
            return _error(call, f"unknown open_search_plan_id: {plan_id}", {"open_search_plan_id": plan_id})
        plan = domain_store.open_search_plans[plan_id]
        if plan.status not in {"planned", "running"}:
            return _error(call, f"open search plan is not active: {plan.status}", {"open_search_plan_id": plan_id})
        lead = domain_store.open_source_leads.get(lead_id)
        if lead is None:
            return _error(call, f"unknown open_source_lead_id: {lead_id}", {"open_source_lead_id": lead_id})
        if lead.plan_id != plan_id:
            return _error(call, "OpenSourceLead does not belong to OpenSearchPlan", {"open_search_plan_id": plan_id, "open_source_lead_id": lead_id})
        if url != lead.url:
            return _error(call, "url does not match OpenSourceLead", {"url": url, "lead_url": lead.url})
        started = time.perf_counter()
        try:
            response = await transport(url, timeout_ms, max_bytes)
        except Exception as exc:
            return _error(call, f"fetch failed: {exc}", {"url": url})
        if response.status_code >= 400:
            return _error(call, f"fetch failed with HTTP {response.status_code}", {"url": url, "status_code": response.status_code})
        final_host = (urlparse(response.url).hostname or "").lower()
        if final_host and lead.domain and final_host != lead.domain.lower():
            return _error(call, "redirect target differs from OpenSourceLead domain", {"url": url, "final_url": response.url})
        content_type = header_value(response.headers, "content-type")
        if not _is_html_or_text(content_type):
            return _error(
                call,
                "fetch_open_source_page supports html/txt only; use download_document for PDF",
                {"url": url, "content_type": content_type},
            )
        text = decode_response(response)
        raw_ref = artifacts.put(
            text,
            kind=_artifact_kind(content_type),
            meta={
                "url": url,
                "final_url": response.url,
                "content_type": content_type,
                "open_search_plan_id": plan_id,
                "open_source_lead_id": lead_id,
                "status_code": response.status_code,
                "headers_used": sorted(DEFAULT_HTTP_HEADERS),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        page = simplify(text, artifacts)
        body = OpenSourceBodyArtifact(
            body_id=_body_id(plan_id, lead_id, page.text_ref),
            lead_id=lead_id,
            plan_id=plan_id,
            url=lead.url,
            final_url=response.url,
            content_type=content_type,
            artifact_ref=raw_ref,
            simplified_ref=page.text_ref,
            body_location_prefix=f"{page.text_ref}#",
            fetched_by=ctx.worker_id,
            created_at=datetime.now(timezone.utc),
        )
        details = {
            "open_search_plan_id": plan_id,
            "open_source_lead_id": lead_id,
            "body_id": body.body_id,
            "artifact_ref": raw_ref,
            "simplified_ref": page.text_ref,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": content_type,
            "fetch_ms": int((time.perf_counter() - started) * 1000),
        }
        return ToolResult(
            call.id,
            call.name,
            f"{UNTRUSTED_NOTICE}\nFetched OpenSourceLead {lead_id}; use read_document artifact_ref={page.text_ref}",
            details,
            domain_proposals=[
                DomainWriteProposal("upsert", "OpenSourceBodyArtifact", body.to_dict())
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="open_source_body_fetched",
                    target_type="OpenSourceLead",
                    target_id=lead_id,
                    payload_summary=f"fetched open source body {lead_id}",
                    input_refs=[plan_id, lead_id],
                    output_refs=[body.body_id, raw_ref, page.text_ref],
                    payload=details,
                )
            ],
        )

    return ToolDefinition(
        name="fetch_open_source_page",
        description="Fetch public HTML/TXT body for an OpenSourceLead within an active OpenSearchPlan.",
        parameters_schema={
            "type": "object",
            "required": ["open_search_plan_id", "open_source_lead_id", "url"],
            "properties": {
                "open_search_plan_id": {"type": "string"},
                "open_source_lead_id": {"type": "string"},
                "url": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=timeout_ms + 5_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def _error(call: ToolCall, content: str, details: dict[str, object]) -> ToolResult:
    return ToolResult(call.id, call.name, content, details, is_error=True)


async def _default_transport(
    url: str,
    timeout_ms: int,
    max_bytes: int,
) -> HttpFetchResponse:
    return await default_http_transport(url, timeout_ms, max_bytes)


def _is_html_or_text(content_type: str) -> bool:
    normalized = content_type.lower().split(";", 1)[0].strip()
    return normalized in {"text/html", "application/xhtml+xml", "text/plain"}


def _artifact_kind(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    return "text" if normalized == "text/plain" else "html"


def _body_id(plan_id: str, lead_id: str, simplified_ref: str) -> str:
    digest = hashlib.sha256(
        f"{plan_id}:{lead_id}:{simplified_ref}".encode("utf-8")
    ).hexdigest()[:12]
    return f"osb-{digest}"
