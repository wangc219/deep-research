"""Source-page discovery and document download tools."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from knowledgegraph.demand_discovery.domain.research_state import (
    ReadingQueue,
    ResearchLead,
)
from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.network import (
    HttpTransport,
    UNTRUSTED_NOTICE,
    WHITELIST_BLOCK_MESSAGE,
    _default_http_transport,
)
from knowledgegraph.demand_discovery.tools.page_simplify import simplify


DOWNLOAD_EXTENSIONS = {
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".txt": "txt",
}


def create_classify_source_page_tool(artifacts: ArtifactStore) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        url = str(args.get("url", ""))
        artifact_ref = str(args.get("artifact_ref", ""))
        if _download_kind(url) != "none":
            details = {
                "page_type": "download_document",
                "title": "",
                "candidate_link_count": 0,
                "download_link_count": 1,
                "reason": "download file extension",
            }
            return ToolResult(call.id, call.name, "classified as download_document", details)
        try:
            html = artifacts.get_text(artifact_ref) if artifact_ref else ""
        except KeyError:
            return ToolResult(
                call.id,
                call.name,
                f"unknown artifact_ref: {artifact_ref}",
                {},
                is_error=True,
            )
        details = classify_source_page(html, url=url)
        return ToolResult(
            call.id,
            call.name,
            f"classified as {details['page_type']}: {details['reason']}",
            details,
        )

    return ToolDefinition(
        name="classify_source_page",
        description="Classify a source page as article/listing/site_home/search_page/download_document/unknown.",
        parameters_schema={
            "type": "object",
            "required": ["topic"],
            "properties": {
                "url": {"type": "string"},
                "artifact_ref": {"type": "string"},
                "topic": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute,
    )


def create_discover_articles_tool(
    store: DomainStore | None,
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    http_transport: HttpTransport | None = None,
    timeout_ms: int = 30_000,
    max_bytes: int = 2_000_000,
) -> ToolDefinition:
    transport = http_transport or _default_http_transport

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        seed_url = str(args["seed_url"]).strip()
        topic = str(args.get("topic", ""))
        round_id = str(args.get("round_id", ""))
        max_candidates = max(1, int(args.get("max_candidates", 20)))
        seed_entry = registry.match(seed_url)
        if seed_entry is None:
            return ToolResult(
                call.id,
                call.name,
                WHITELIST_BLOCK_MESSAGE,
                {"url": seed_url, "blocked_by": "source_whitelist"},
                is_error=True,
            )
        try:
            response = await transport(seed_url, timeout_ms, max_bytes)
        except Exception as exc:
            return ToolResult(
                call.id,
                call.name,
                f"discover fetch failed: {exc}",
                {"url": seed_url},
                is_error=True,
            )
        html = _decode(response.content, _header(response.headers, "content-type"))
        html_ref = artifacts.put(
            html,
            kind="html",
            meta={
                "url": seed_url,
                "final_url": response.url,
                "content_type": _header(response.headers, "content-type"),
                "tool": "discover_articles",
                "fetched_at": _now(),
            },
        )
        links = _extract_article_links(html, response.url or seed_url)[:max_candidates]
        leads: list[ResearchLead] = []
        selected_ids: list[str] = []
        skipped_ids: list[str] = []
        for link in links:
            entry = registry.match(link["url"])
            relevance_score = _topic_score(topic, f"{link['title']} {link['context']}")
            topic_relevant = _topic_relevance_passes(topic, relevance_score)
            status = "selected" if entry is not None and topic_relevant else "skipped"
            skip_reason = ""
            if entry is None:
                skip_reason = "outside source whitelist"
            elif not topic_relevant:
                skip_reason = "topic relevance below threshold"
            lead = ResearchLead(
                lead_id=_lead_id(round_id, link["url"]),
                round_id=round_id,
                source_name=entry.source_name if entry else "",
                source_tier=entry.source_tier if entry else "",
                url=link["url"],
                title=link["title"],
                snippet=link["context"],
                page_type="download_document"
                if _download_kind(link["url"]) != "none"
                else "article",
                download_kind=_download_kind(link["url"]),
                relevance_score=relevance_score,
                importance_score=0.5,
                credibility_score=_tier_score(entry.source_tier if entry else ""),
                status=status,
                selection_reason="whitelisted topic candidate" if status == "selected" else "",
                skip_reason=skip_reason,
                artifact_refs=[html_ref],
                created_at=_dt_now(),
                updated_at=_dt_now(),
            )
            leads.append(lead)
            if status == "selected":
                selected_ids.append(lead.lead_id)
            else:
                skipped_ids.append(lead.lead_id)
        leads = _sort_leads(leads)
        queue = ReadingQueue(
            queue_id=f"queue-{_hash(f'{round_id}:{seed_url}')}",
            round_id=round_id,
            topic=topic,
            lead_ids=[lead.lead_id for lead in leads],
            selected_lead_ids=[lead.lead_id for lead in leads if lead.status == "selected"],
            skipped_lead_ids=[lead.lead_id for lead in leads if lead.status == "skipped"],
            failed_lead_ids=[],
            budget_snapshot={
                "max_candidates": max_candidates,
                "seed_url": seed_url,
            },
            created_at=_dt_now(),
            updated_at=_dt_now(),
        )
        proposals = [
            DomainWriteProposal("upsert", "ResearchLead", lead.to_dict())
            for lead in leads
        ]
        proposals.append(DomainWriteProposal("upsert", "ReadingQueue", queue.to_dict()))
        selected_summaries = [
            _lead_summary(lead)
            for lead in leads
            if lead.status == "selected"
        ]
        skipped_summaries = [
            _lead_summary(lead)
            for lead in leads
            if lead.status == "skipped"
        ]
        lead_lines = _lead_result_lines(selected_summaries, skipped_summaries)
        return ToolResult(
            call.id,
            call.name,
            (
                f"{UNTRUSTED_NOTICE}\n"
                f"discovered {len(queue.selected_lead_ids)} selected leads and "
                f"{len(queue.skipped_lead_ids)} skipped leads"
                f"{lead_lines}"
            ),
            {
                "seed_url": seed_url,
                "artifact_ref": html_ref,
                "selected_count": len(queue.selected_lead_ids),
                "skipped_count": len(queue.skipped_lead_ids),
                "lead_ids": list(queue.lead_ids),
                "selected_lead_ids": list(queue.selected_lead_ids),
                "skipped_lead_ids": list(queue.skipped_lead_ids),
                "selected_leads": selected_summaries,
                "skipped_leads": skipped_summaries,
            },
            domain_proposals=proposals,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="research_leads_discovered",
                    target_type="ReadingQueue",
                    target_id=queue.queue_id,
                    payload_summary=f"discovered articles from {seed_url}",
                    input_refs=[seed_url],
                    output_refs=list(queue.lead_ids),
                    payload={
                        "selected_lead_ids": list(queue.selected_lead_ids),
                        "skipped_lead_ids": list(queue.skipped_lead_ids),
                    },
                )
            ],
        )

    return ToolDefinition(
        name="discover_articles",
        description="Discover whitelisted article/document leads from a listing page.",
        parameters_schema={
            "type": "object",
            "required": ["seed_url", "topic", "round_id"],
            "properties": {
                "seed_url": {"type": "string"},
                "topic": {"type": "string"},
                "round_id": {"type": "string"},
                "max_candidates": {"type": "integer"},
                "depth": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def create_download_document_tool(
    store: DomainStore | None,
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    http_transport: HttpTransport | None = None,
    timeout_ms: int = 30_000,
    max_bytes: int = 5_000_000,
) -> ToolDefinition:
    transport = http_transport or _default_http_transport

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        lead_id = str(args.get("lead_id", ""))
        url = str(args.get("url", "")).strip()
        if not url and store is not None and lead_id and lead_id in store.research_leads:
            url = store.research_leads[lead_id].url
        if registry.match(url) is None:
            return ToolResult(
                call.id,
                call.name,
                WHITELIST_BLOCK_MESSAGE,
                {"url": url, "blocked_by": "source_whitelist"},
                is_error=True,
            )
        try:
            response = await transport(url, timeout_ms, max_bytes)
        except Exception as exc:
            return ToolResult(
                call.id,
                call.name,
                f"download failed: {exc}",
                {"url": url},
                is_error=True,
            )
        content_type = _header(response.headers, "content-type")
        kind = _document_kind(url, content_type)
        raw_ref = artifacts.put(
            response.content,
            kind=kind if kind in {"pdf", "doc", "docx"} else f"{kind}_raw",
            meta={
                "url": url,
                "final_url": response.url,
                "content_type": content_type,
                "download_kind": kind,
                "downloaded_at": _now(),
            },
        )
        details: dict[str, Any] = {
            "url": url,
            "raw_artifact_ref": raw_ref,
            "download_kind": kind,
            "status": "downloaded",
        }
        text_ref = ""
        if kind == "html":
            page = simplify(_decode(response.content, content_type), artifacts)
            text_ref = page.text_ref
        elif kind == "txt":
            text_ref = artifacts.put(
                _decode(response.content, content_type),
                kind="text",
                meta={"url": url, "content_type": "text/plain", "source_artifact_ref": raw_ref},
            )
        elif kind == "pdf":
            extracted = _extract_pdf_text(response.content)
            if extracted:
                text_ref = artifacts.put(
                    extracted,
                    kind="text",
                    meta={
                        "url": url,
                        "content_type": "text/plain",
                        "source_artifact_ref": raw_ref,
                        "parser": "pypdf_or_fallback",
                    },
                )
        elif kind in {"doc", "docx"}:
            details["status"] = "skipped_pending_parser"
        if text_ref:
            details["text_artifact_ref"] = text_ref
        domain_proposals: list[DomainWriteProposal] = []
        if store is not None and lead_id and lead_id in store.research_leads:
            lead = store.research_leads[lead_id]
            updated = replace(
                lead,
                status="downloaded" if text_ref else "skipped",
                skip_reason="" if text_ref else "skipped_pending_parser",
                artifact_refs=[*lead.artifact_refs, raw_ref, *([text_ref] if text_ref else [])],
                updated_at=_dt_now(),
            )
            domain_proposals.append(
                DomainWriteProposal("upsert", "ResearchLead", updated.to_dict())
            )
        return ToolResult(
            call.id,
            call.name,
            f"{UNTRUSTED_NOTICE}\ndownloaded {kind} document: {details['status']}",
            details,
            domain_proposals=domain_proposals,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="document_downloaded",
                    target_type="ResearchLead" if lead_id else "Artifact",
                    target_id=lead_id or raw_ref,
                    payload_summary=f"downloaded document {url}",
                    input_refs=[lead_id] if lead_id else [],
                    output_refs=[raw_ref, *([text_ref] if text_ref else [])],
                    payload={"download_kind": kind, "status": details["status"]},
                )
            ],
        )

    return ToolDefinition(
        name="download_document",
        description="Download a whitelisted html/txt/pdf document; doc/docx stores raw artifact only.",
        parameters_schema={
            "type": "object",
            "required": [],
            "properties": {
                "url": {"type": "string"},
                "lead_id": {"type": "string"},
                "force_refresh": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def classify_source_page(html: str, *, url: str = "") -> dict[str, Any]:
    if _download_kind(url) != "none":
        return {
            "page_type": "download_document",
            "title": "",
            "candidate_link_count": 0,
            "download_link_count": 1,
            "reason": "download file extension",
        }
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    title = _title(soup)
    links = _content_links(soup, url or "https://example.invalid/")
    paragraphs = [
        _clean_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all("p")
        if isinstance(tag, Tag) and len(_clean_text(tag.get_text(" ", strip=True))) >= 12
    ]
    download_count = sum(1 for link in links if _download_kind(link["url"]) != "none")
    text = _clean_text(soup.get_text(" ", strip=True))
    has_search = bool(soup.find("input", attrs={"type": re.compile("search|text", re.I)}))
    if not text and not links:
        page_type, reason = "unknown", "empty page"
    elif has_search and len(paragraphs) < 2:
        page_type, reason = "search_page", "search input with little article text"
    elif len(paragraphs) >= 3 and (soup.find("article") or soup.find("h1")):
        page_type, reason = "article", "has article body paragraphs"
    elif len(links) >= 3:
        page_type, reason = "listing", "has multiple candidate links"
    elif len(links) >= 1 and len(text) < 400:
        page_type, reason = "site_home", "navigation-style page"
    else:
        page_type, reason = "unknown", "insufficient article or listing signals"
    return {
        "page_type": page_type,
        "title": title,
        "candidate_link_count": len(links),
        "download_link_count": download_count,
        "reason": reason,
    }


def _extract_article_links(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    embedded_links = _embedded_story_links(soup, base_url)
    for tag in soup.find_all(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    return _dedupe_links([*embedded_links, *_content_links(soup, base_url)])


def _embedded_story_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=False)
        if not text or ("canonical_url" not in text and "website_url" not in text):
            continue
        for match in re.finditer(
            r'"(?:canonical_url|website_url|short_url)"\s*:\s*"([^"]+)"',
            text,
        ):
            raw_url = _json_unescape(match.group(1))
            if not raw_url or _skip_embedded_url(raw_url):
                continue
            window = text[max(0, match.start() - 900) : min(len(text), match.end() + 1200)]
            title = _embedded_title(window) or raw_url
            context = _embedded_context(window) or title
            rows.append(
                {
                    "url": urljoin(base_url, raw_url),
                    "title": _clean_text(title),
                    "context": _clean_text(context),
                }
            )
    return _dedupe_links(rows)


def _embedded_title(text: str) -> str:
    patterns = [
        r'"headlines"\s*:\s*\{[^{}]*"basic"\s*:\s*"([^"]+)"',
        r'"title"\s*:\s*"([^"]+)"',
        r'"basic"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _json_unescape(match.group(1))
    return ""


def _embedded_context(text: str) -> str:
    match = re.search(
        r'"description"\s*:\s*\{[^{}]*"basic"\s*:\s*"([^"]+)"',
        text,
    )
    return _json_unescape(match.group(1)) if match else ""


def _json_unescape(value: str) -> str:
    try:
        return str(json.loads(f'"{value}"'))
    except Exception:
        return value.replace("\\/", "/")


def _skip_embedded_url(url: str) -> bool:
    lower = url.lower()
    return (
        not url.startswith("/")
        or lower.startswith("/video/")
        or lower.startswith("/videos/")
        or "/video/" in lower
        or lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js"))
    )


def _content_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    root = soup.find(["main", "article", "section"]) or soup.body or soup
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in root.find_all("a"):
        if not isinstance(tag, Tag):
            continue
        href = str(tag.get("href", "")).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        title = _clean_text(tag.get_text(" ", strip=True))
        context = _link_context(tag, title)
        rows.append({"url": url, "title": title or url, "context": context})
    return rows


def _link_context(tag: Tag, title: str) -> str:
    parent = tag.parent
    if not isinstance(parent, Tag):
        return title
    parent_text = _clean_text(parent.get_text(" ", strip=True))
    if parent.name in {"html", "body", "main"}:
        return title
    if len(parent.find_all("a")) > 1:
        return title
    return parent_text or title


def _dedupe_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        url = str(link.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(link)
    return rows


def _lead_summary(lead: ResearchLead) -> dict[str, Any]:
    return {
        "lead_id": lead.lead_id,
        "url": lead.url,
        "title": lead.title,
        "page_type": lead.page_type,
        "download_kind": lead.download_kind,
        "relevance_score": lead.relevance_score,
        "status": lead.status,
        "reason": lead.selection_reason or lead.skip_reason,
    }


def _lead_result_lines(
    selected: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> str:
    rows: list[str] = []
    if selected:
        rows.append("\nselected_leads:")
        for lead in selected[:limit]:
            rows.append(
                "- "
                f"{lead['lead_id']} | {lead['title']} | {lead['url']} | "
                f"page_type={lead['page_type']} | download_kind={lead['download_kind']}"
            )
    if skipped:
        rows.append("\nskipped_leads:")
        for lead in skipped[:limit]:
            rows.append(
                "- "
                f"{lead['lead_id']} | {lead['title']} | {lead['url']} | "
                f"reason={lead['reason']}"
            )
    return "\n" + "\n".join(rows) if rows else ""


def _sort_leads(leads: list[ResearchLead]) -> list[ResearchLead]:
    return sorted(
        leads,
        key=lambda lead: (
            0 if lead.status == "selected" else 1,
            -lead.relevance_score,
            lead.title,
            lead.url,
        ),
    )


def _download_kind(url: str) -> str:
    suffix = _suffix(url)
    return DOWNLOAD_EXTENSIONS.get(suffix, "none")


def _document_kind(url: str, content_type: str) -> str:
    suffix_kind = _download_kind(url)
    lower = content_type.lower()
    if suffix_kind != "none":
        return suffix_kind
    if "pdf" in lower:
        return "pdf"
    if "wordprocessingml" in lower or "docx" in lower:
        return "docx"
    if "msword" in lower:
        return "doc"
    if "html" in lower:
        return "html"
    if "text/plain" in lower or "text/" in lower:
        return "txt"
    return "unknown"


def _extract_pdf_text(content: bytes) -> str:
    try:
        from io import BytesIO
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            return text.strip()
    except Exception:
        pass
    decoded = content.decode("utf-8", errors="ignore")
    lines = [
        line.strip()
        for line in decoded.splitlines()
        if line.strip()
        and not line.startswith("%PDF")
        and not line.startswith("%%EOF")
    ]
    return "\n\n".join(lines)


def _topic_score(topic: str, text: str) -> float:
    tokens = [token for token in re.split(r"\s+", topic.strip()) if token]
    compact_topic = topic.replace(" ", "")
    compact_text = text.replace(" ", "")
    if not tokens and not compact_topic:
        return 0.0
    hits = sum(1 for token in tokens if token in text)
    if compact_topic and compact_topic in compact_text:
        hits += 2
    if any(token in compact_text for token in ["低空", "无人机", "探测", "预警", "防护"]):
        hits += 1
    return min(1.0, hits / max(1, len(tokens) or 2))


def _topic_relevance_passes(topic: str, score: float) -> bool:
    if not topic.strip():
        return True
    tokens = [token for token in re.split(r"\s+", topic.strip()) if token]
    threshold = 0.25 if len(tokens) >= 4 else 0.2
    return score >= threshold


def _tier_score(tier: str) -> float:
    return {"A": 0.95, "B": 0.8, "C": 0.5, "D": 0.2}.get(tier.upper(), 0.0)


def _lead_id(round_id: str, url: str) -> str:
    return f"lead-{_hash(f'{round_id}:{url}')}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _suffix(url: str) -> str:
    path = re.sub(r"[?#].*$", "", urlparse(url).path).lower()
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _title(soup: BeautifulSoup) -> str:
    for tag in [soup.find("h1"), soup.find("title")]:
        if isinstance(tag, Tag):
            text = _clean_text(tag.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _header(headers: dict[str, str], name: str) -> str:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return str(value)
    return ""


def _decode(content: bytes, content_type: str) -> str:
    encoding = "utf-8"
    if "charset=" in content_type.lower():
        encoding = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
    return content.decode(encoding or "utf-8", errors="replace")


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_now() -> datetime:
    return datetime.now(timezone.utc)
