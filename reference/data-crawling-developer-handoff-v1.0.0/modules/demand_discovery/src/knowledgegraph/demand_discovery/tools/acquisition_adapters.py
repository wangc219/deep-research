"""Dedicated acquisition adapters for whitelisted source families."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import math
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from knowledgegraph.demand_discovery.domain.source_registry import WhitelistEntry
from knowledgegraph.demand_discovery.tools.acquisition import (
    AcquiredDocument,
    AcquisitionAdapterResult,
    SourceAcquisitionRequest,
    _hash,
    _preview_text,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.discovery import (
    _extract_pdf_text,
    _topic_score,
)
from knowledgegraph.demand_discovery.tools.http_transport import (
    DEFAULT_HTTP_HEADERS,
    HttpFetchResponse,
    HttpTransport,
    decode_response,
    default_http_transport,
    header_value,
    request_bytes,
)


MLPLA_HOST = "journal.mlpla.mil.cn"
MLPLA_SEARCH_FIELDS = ("titleCn", "abstractinfoCn", "keywordCn")
MLPLA_FIELD_WEIGHTS = {"titleCn": 3.0, "abstractinfoCn": 2.0, "keywordCn": 1.0}
MLPLA_STATIC_JOURNALS = {
    "jskxwz": "e6f87e82-cd19-4a62-b9db-6bbcfa47725f",
    "jsycypg": "8dca4dc0-494e-4c8c-9925-d13434777e79",
}

MlplaSearchTransport = Callable[
    [str, dict[str, str], int, int],
    Awaitable[HttpFetchResponse],
]


@dataclass(frozen=True)
class MlplaJournalProfile:
    source_name: str
    source_tier: str
    journal_path: str
    journal_id: str


@dataclass(frozen=True)
class MlplaSearchRecord:
    article_id: str
    title: str
    abstract: str
    citation: str
    published_at: str | None
    journal_path: str
    article_url: str
    html_url: str
    pdf_url: str
    matched_query: str
    matched_field: str
    pdf_available: bool
    rank_score: float


@dataclass(frozen=True)
class MlplaBody:
    text: str
    raw_ref: str
    text_ref: str
    policy: str
    final_url: str


class MlplaJournalAdapter:
    """Acquire MLPLA journal documents through the platform search API."""

    def __init__(
        self,
        http_transport: HttpTransport | None = None,
        *,
        search_transport: MlplaSearchTransport | None = None,
        timeout_ms: int = 30_000,
        max_bytes: int = 20_000_000,
        maxresult: int = 20,
        max_pages_per_query_field: int = 5,
    ) -> None:
        self._transport = http_transport or default_http_transport
        self._search_transport = search_transport or _default_mlpla_search_transport
        self._timeout_ms = timeout_ms
        self._max_bytes = max_bytes
        self._maxresult = max(1, maxresult)
        self._max_pages_per_query_field = max(1, max_pages_per_query_field)

    def supports(self, entry: WhitelistEntry) -> bool:
        return _profile_from_static_entry(entry) is not None or any(
            _url_host_matches(url, MLPLA_HOST) for url in entry.entry_urls
        )

    async def acquire(
        self,
        *,
        request: SourceAcquisitionRequest,
        artifacts: ArtifactStore,
    ) -> AcquisitionAdapterResult:
        profile = await self._resolve_profile(request.entry)
        if profile is None:
            return AcquisitionAdapterResult(
                status="exhausted",
                reason="not_configured",
                diagnostics={"route_used": "mlpla_search_api"},
            )

        records, errors = await self._search_records(profile, request)
        if not records:
            return AcquisitionAdapterResult(
                status="failed" if errors else "exhausted",
                reason="; ".join(errors) if errors else "no_matching_candidates",
                diagnostics={
                    "route_used": "mlpla_search_api",
                    "journal_path": profile.journal_path,
                    "records_seen": 0,
                    "errors": errors,
                },
            )

        ranked_records = sorted(
            records.values(),
            key=lambda item: (item.rank_score, item.published_at or "", item.title),
            reverse=True,
        )
        fetch_limit = min(
            len(ranked_records),
            max(request.max_candidates, request.max_candidates * 3),
        )
        documents: list[AcquiredDocument] = []
        body_errors: list[str] = []
        for record in ranked_records[:fetch_limit]:
            try:
                documents.append(
                    await self._document_from_record(
                        request=request,
                        artifacts=artifacts,
                        profile=profile,
                        record=record,
                    )
                )
            except Exception as exc:
                body_errors.append(f"{record.article_id}: {exc}")

        if not documents:
            return AcquisitionAdapterResult(
                status="failed",
                reason="; ".join([*errors, *body_errors]) or "body_fetch_failed",
                diagnostics={
                    "route_used": "mlpla_search_api",
                    "journal_path": profile.journal_path,
                    "records_seen": len(records),
                    "errors": [*errors, *body_errors],
                },
            )
        return AcquisitionAdapterResult(
            status="partial" if body_errors else "ok",
            documents=documents,
            reason="; ".join(body_errors),
            diagnostics={
                "route_used": "mlpla_search_api",
                "journal_path": profile.journal_path,
                "records_seen": len(records),
                "documents_returned": len(documents),
                "body_errors": body_errors,
            },
        )

    async def _resolve_profile(
        self,
        entry: WhitelistEntry,
    ) -> MlplaJournalProfile | None:
        static_profile = _profile_from_static_entry(entry)
        if static_profile is not None:
            return static_profile
        path = _journal_path_from_entry(entry)
        if not path:
            return None
        journal_id = await self._fetch_journal_id(path)
        if not journal_id:
            return None
        return MlplaJournalProfile(
            source_name=entry.source_name,
            source_tier=entry.source_tier,
            journal_path=path,
            journal_id=journal_id,
        )

    async def _fetch_journal_id(self, journal_path: str) -> str:
        url = f"https://{MLPLA_HOST}/{journal_path}/cn/to_advance_search"
        try:
            response = await self._transport(url, self._timeout_ms, self._max_bytes)
        except Exception:
            return ""
        if response.status_code >= 400:
            return ""
        html = decode_response(response)
        return _journal_id_from_advanced_search_html(html)

    async def _search_records(
        self,
        profile: MlplaJournalProfile,
        request: SourceAcquisitionRequest,
    ) -> tuple[dict[str, MlplaSearchRecord], list[str]]:
        query_texts = [
            str(row.get("text", "")).strip()
            for row in request.queries
            if str(row.get("text", "")).strip()
        ]
        records: dict[str, MlplaSearchRecord] = {}
        errors: list[str] = []
        for query in query_texts:
            for field in MLPLA_SEARCH_FIELDS:
                page = 1
                total_pages = 1
                while page <= total_pages:
                    try:
                        payload = await self._post_search(profile, query, field, page)
                    except Exception as exc:
                        errors.append(f"{profile.journal_path}:{field}:{page}: {exc}")
                        break
                    page_records = _records_from_payload(payload)
                    total = _total_records_from_payload(payload)
                    total_pages = min(
                        self._max_pages_per_query_field,
                        max(1, math.ceil(total / self._maxresult)),
                    )
                    for raw in page_records:
                        record = _record_from_raw(
                            raw,
                            profile=profile,
                            matched_query=query,
                            matched_field=field,
                        )
                        if record is None:
                            continue
                        existing = records.get(record.article_id)
                        if existing is None or record.rank_score > existing.rank_score:
                            records[record.article_id] = record
                    if page >= total_pages:
                        break
                    page += 1
        return records, errors

    async def _post_search(
        self,
        profile: MlplaJournalProfile,
        query: str,
        field: str,
        page: int,
    ) -> dict[str, Any]:
        url = f"https://{MLPLA_HOST}/{profile.journal_path}/data/search/advancedSearchResult"
        condition = {
            "field": field,
            "value": query,
            "type": "LIKE",
            "relation": "AND",
        }
        form = {
            "searchCondition": json.dumps(
                condition,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "otherConditions": "",
            "language": "cn",
            "maxresult": str(self._maxresult),
            "currentpage": str(page),
            "orderBy": "",
            "journalId": profile.journal_id,
        }
        response = await self._search_transport(
            url,
            form,
            self._timeout_ms,
            self._max_bytes,
        )
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code}")
        text = decode_response(response)
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {}

    async def _document_from_record(
        self,
        *,
        request: SourceAcquisitionRequest,
        artifacts: ArtifactStore,
        profile: MlplaJournalProfile,
        record: MlplaSearchRecord,
    ) -> AcquiredDocument:
        body = await self._fetch_body(record, artifacts)
        query = record.matched_query or request.primary_query()
        if body is not None:
            paragraphs = _paragraphs(body.text)
            preview = _preview_text(query, paragraphs)
            return AcquiredDocument(
                document_id=f"doc-{_hash(f'{request.round_id}|{profile.source_name}|{record.article_id}')}",
                source_name=profile.source_name,
                source_tier=profile.source_tier,
                scope="whitelist",
                route_used=f"mlpla_search_{body.policy}",
                title=record.title,
                url=record.article_url,
                published_at=record.published_at,
                body_artifact_ref=body.text_ref,
                evidence_preview=[
                    {
                        "text": preview,
                        "location_ref": f"{body.text_ref}#para:0",
                    }
                ]
                if preview
                else [],
                evidence_allowed=True,
                evidence_policy=body.policy,
                rank_score=6.0 + record.rank_score + _topic_score(query, body.text),
                why_ranked="MLPLA search result with readable article body",
            )

        preview = _clean_html(record.abstract or record.citation)
        return AcquiredDocument(
            document_id=f"doc-{_hash(f'{request.round_id}|{profile.source_name}|{record.article_id}')}",
            source_name=profile.source_name,
            source_tier=profile.source_tier,
            scope="whitelist",
            route_used="mlpla_search_metadata",
            title=record.title,
            url=record.article_url,
            published_at=record.published_at,
            body_artifact_ref="",
            evidence_preview=[
                {
                    "text": preview[:360],
                    "reason": "MLPLA search metadata matched the query; body was not readable",
                }
            ]
            if preview
            else [],
            evidence_allowed=False,
            evidence_policy="metadata_only",
            rank_score=record.rank_score,
            why_ranked="MLPLA search metadata matched the query",
        )

    async def _fetch_body(
        self,
        record: MlplaSearchRecord,
        artifacts: ArtifactStore,
    ) -> MlplaBody | None:
        pdf_body = await self._fetch_pdf_body(record, artifacts)
        if pdf_body is not None:
            return pdf_body
        return await self._fetch_html_body(record, artifacts)

    async def _fetch_pdf_body(
        self,
        record: MlplaSearchRecord,
        artifacts: ArtifactStore,
    ) -> MlplaBody | None:
        try:
            response = await self._transport(
                record.pdf_url,
                self._timeout_ms,
                self._max_bytes,
            )
        except Exception:
            return None
        content_type = header_value(response.headers, "content-type")
        if (
            response.status_code >= 400
            or response.truncated
            or not _looks_like_pdf(response.content, content_type)
        ):
            return None
        raw_ref = artifacts.put(
            response.content,
            kind="pdf",
            meta={
                "url": record.pdf_url,
                "final_url": response.url,
                "content_type": content_type,
                "article_id": record.article_id,
                "tool": "mlpla_journal_adapter",
            },
        )
        text = _normalize_body_text(_extract_pdf_text_quiet(response.content))
        if not _body_text_is_usable(text):
            return None
        text_ref = artifacts.put(
            text,
            kind="text",
            meta={
                "url": record.pdf_url,
                "final_url": response.url,
                "content_type": "text/plain",
                "source_artifact_ref": raw_ref,
                "article_id": record.article_id,
                "parser": "pypdf_or_fallback",
            },
        )
        return MlplaBody(
            text=text,
            raw_ref=raw_ref,
            text_ref=text_ref,
            policy="pdf_body_allowed",
            final_url=response.url or record.pdf_url,
        )

    async def _fetch_html_body(
        self,
        record: MlplaSearchRecord,
        artifacts: ArtifactStore,
    ) -> MlplaBody | None:
        try:
            response = await self._transport(
                record.html_url,
                self._timeout_ms,
                self._max_bytes,
            )
        except Exception:
            return None
        if response.status_code >= 400:
            return None
        content_type = header_value(response.headers, "content-type")
        html = decode_response(response)
        text = _normalize_body_text(_extract_html_fulltext(html))
        if not _body_text_is_usable(text):
            return None
        raw_ref = artifacts.put(
            html,
            kind="html",
            meta={
                "url": record.html_url,
                "final_url": response.url,
                "content_type": content_type,
                "article_id": record.article_id,
                "tool": "mlpla_journal_adapter",
            },
        )
        text_ref = artifacts.put(
            text,
            kind="text",
            meta={
                "url": record.html_url,
                "final_url": response.url,
                "content_type": "text/plain",
                "source_artifact_ref": raw_ref,
                "article_id": record.article_id,
                "parser": "mlpla_article_fulltext_data",
            },
        )
        return MlplaBody(
            text=text,
            raw_ref=raw_ref,
            text_ref=text_ref,
            policy="article_body_allowed",
            final_url=response.url or record.html_url,
        )


async def _default_mlpla_search_transport(
    url: str,
    form: dict[str, str],
    timeout_ms: int,
    max_bytes: int,
) -> HttpFetchResponse:
    return await asyncio.to_thread(
        _requests_post,
        url,
        form,
        timeout_ms,
        max_bytes,
    )


def _requests_post(
    url: str,
    form: dict[str, str],
    timeout_ms: int,
    max_bytes: int,
) -> HttpFetchResponse:
    headers = {
        **DEFAULT_HTTP_HEADERS,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": f"https://{MLPLA_HOST}",
        "Referer": f"https://{MLPLA_HOST}/",
        "X-Requested-With": "XMLHttpRequest",
    }
    return request_bytes(
        "POST",
        url,
        data=form,
        timeout_seconds=max(timeout_ms / 1000, 0.001),
        max_bytes=max_bytes,
        headers=headers,
    )


def _profile_from_static_entry(entry: WhitelistEntry) -> MlplaJournalProfile | None:
    path = _journal_path_from_entry(entry)
    if not path:
        return None
    journal_id = MLPLA_STATIC_JOURNALS.get(path)
    if not journal_id:
        return None
    return MlplaJournalProfile(
        source_name=entry.source_name,
        source_tier=entry.source_tier,
        journal_path=path,
        journal_id=journal_id,
    )


def _journal_path_from_entry(entry: WhitelistEntry) -> str:
    for url in entry.entry_urls:
        parsed = urlparse(url)
        if not _host_matches(parsed.hostname or "", MLPLA_HOST):
            continue
        path = parsed.path.strip("/")
        first = path.split("/", 1)[0].strip()
        if first and first not in {"cn", "journals", "article", "data"}:
            return first
    for prefix in entry.path_prefixes:
        first = prefix.strip("/").split("/", 1)[0].strip()
        if first:
            return first
    return ""


def _journal_id_from_advanced_search_html(html: str) -> str:
    match = re.search(r"web_common_data\s*=\s*(\{.*?\})\s*;", html or "", re.S)
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    journal = data.get("journal")
    if not isinstance(journal, dict):
        return ""
    return str(journal.get("id", "")).strip()


def _records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pager = _pager_filter(payload)
    rows = pager.get("records", [])
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _total_records_from_payload(payload: dict[str, Any]) -> int:
    pager = _pager_filter(payload)
    try:
        return max(0, int(pager.get("totalrecord", 0)))
    except (TypeError, ValueError):
        return 0


def _pager_filter(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return {}
    pager = data.get("pagerFilter", {})
    return pager if isinstance(pager, dict) else {}


def _record_from_raw(
    raw: dict[str, Any],
    *,
    profile: MlplaJournalProfile,
    matched_query: str,
    matched_field: str,
) -> MlplaSearchRecord | None:
    article_id = str(raw.get("id") or raw.get("articleId") or "").strip()
    if not article_id:
        return None
    title = _clean_html(raw.get("titleCn") or raw.get("title") or "")
    abstract = _clean_html(raw.get("abstractinfoCn") or raw.get("abstract") or "")
    citation = _clean_html(raw.get("citationCn") or raw.get("citation") or "")
    if not title and not abstract:
        return None
    journal = raw.get("journal", {})
    if not isinstance(journal, dict):
        journal = {}
    journal_path = _normalize_journal_path(
        str(journal.get("path") or journal.get("publisherId") or profile.journal_path)
    )
    article_url = f"https://{MLPLA_HOST}/{journal_path}/article/id/{article_id}"
    html_url = f"{article_url}?viewType=HTML"
    pdf_url = f"https://{MLPLA_HOST}/{journal_path}/cn/article/pdf/preview/{article_id}.pdf"
    business = raw.get("articleBusiness", {})
    if not isinstance(business, dict):
        business = {}
    pdf_available = bool(
        business.get("pdfFileName")
        or business.get("pdfFileSizeInt")
        or raw.get("pdfAccess") is True
    )
    published_at = _published_at(raw, citation)
    score_text = f"{title} {abstract} {citation}"
    return MlplaSearchRecord(
        article_id=article_id,
        title=title or article_id,
        abstract=abstract,
        citation=citation,
        published_at=published_at,
        journal_path=journal_path,
        article_url=article_url,
        html_url=html_url,
        pdf_url=pdf_url,
        matched_query=matched_query,
        matched_field=matched_field,
        pdf_available=pdf_available,
        rank_score=_record_rank_score(
            matched_query,
            matched_field=matched_field,
            title=title,
            score_text=score_text,
        ),
    )


def _record_rank_score(
    query: str,
    *,
    matched_field: str,
    title: str,
    score_text: str,
) -> float:
    compact_query = query.replace(" ", "")
    compact_title = title.replace(" ", "")
    title_boost = 0.0
    if compact_query and compact_query in compact_title:
        title_boost += 2.0
    title_boost += sum(
        0.25
        for token in re.split(r"\s+", query.strip())
        if token and token in title
    )
    return (
        MLPLA_FIELD_WEIGHTS.get(matched_field, 0.5)
        + title_boost
        + _topic_score(query, score_text)
    )


def _published_at(raw: dict[str, Any], citation: str) -> str | None:
    for key in ("publishDate", "publishTime", "year", "pubYear"):
        value = str(raw.get(key, "")).strip()
        if value:
            return value
    match = re.search(r"(20\d{2})", citation or "")
    return match.group(1) if match else None


def _normalize_journal_path(value: str) -> str:
    text = value.strip().strip("/")
    if "/" in text:
        text = text.split("/", 1)[0]
    return text


def _looks_like_pdf(content: bytes, content_type: str) -> bool:
    return "pdf" in content_type.lower() or content.lstrip().startswith(b"%PDF")


def _extract_pdf_text_quiet(content: bytes) -> str:
    logger = logging.getLogger("pypdf")
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        return _extract_pdf_text(content)
    finally:
        logger.setLevel(previous_level)


def _extract_html_fulltext(html: str) -> str:
    encoded = _script_variable(html, "article_fulltext_data")
    if not encoded:
        return ""
    decoded = _decode_base64_json(encoded)
    rows = _text_values(decoded)
    return "\n\n".join(row for row in rows if row)


def _script_variable(html: str, name: str) -> str:
    pattern = rf"{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]"
    match = re.search(pattern, html or "", re.S)
    return match.group(1).strip() if match else ""


def _decode_base64_json(value: str) -> Any:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded)
        text = raw.decode("utf-8", errors="replace")
        return json.loads(text)
    except Exception:
        return None


def _text_values(value: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(value, str):
        text = _clean_html(value)
        if len(text) >= 8:
            rows.append(text)
        return rows
    if isinstance(value, list):
        for item in value:
            rows.extend(_text_values(item))
        return rows
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and str(key).lower() in {
                "title",
                "heading",
                "text",
                "content",
                "paragraph",
                "html",
            }:
                rows.extend(_text_values(item))
            elif isinstance(item, (dict, list)):
                rows.extend(_text_values(item))
        return rows
    return rows


def _normalize_body_text(text: str) -> str:
    paragraphs = _paragraphs(text)
    return "\n\n".join(paragraphs)


def _paragraphs(text: str) -> list[str]:
    rows = [
        _clean_html(item)
        for item in re.split(r"\n\s*\n|\r\n\s*\r\n", text or "")
        if _clean_html(item)
    ]
    if len(rows) <= 1:
        rows = [
            _clean_html(item)
            for item in re.split(r"(?<=[。！？.!?])\s*", text or "")
            if _clean_html(item)
        ]
    return [row for row in rows if len(row) >= 6]


def _body_text_is_usable(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 20 or not _paragraphs(stripped):
        return False
    lowered = stripped.lower()
    structural_hits = sum(
        1
        for marker in (" obj", " endobj", "xref", "startxref", "/type/catalog")
        if marker in lowered
    )
    return structural_hits < 2


def _clean_html(value: Any) -> str:
    raw = str(value or "")
    if "<" not in raw or ">" not in raw:
        return re.sub(r"\s+", " ", raw).strip()
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _url_host_matches(url: str, expected_host: str) -> bool:
    host = (urlparse(url).hostname or "").strip().lower()
    return _host_matches(host, expected_host)


def _host_matches(host: str, expected_host: str) -> bool:
    normalized = host.strip().lower()
    expected = expected_host.strip().lower()
    return normalized == expected or normalized.endswith(f".{expected}")
