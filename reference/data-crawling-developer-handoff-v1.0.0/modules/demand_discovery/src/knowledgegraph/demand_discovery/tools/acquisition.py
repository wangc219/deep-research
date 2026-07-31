"""High-level source acquisition tools.

The acquisition layer hides site-specific search/fetch choreography from the
model. It returns compact document previews and per-source status records; deep
reading happens through document_id based read_acquired_document calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Protocol

from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    WhitelistEntry,
)
from knowledgegraph.demand_discovery.domain.source_health import (
    SourceHealthSnapshot,
    SourceHealthStatus,
)
from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.discovery import (
    _extract_article_links,
    _topic_score,
    classify_source_page,
)
from knowledgegraph.demand_discovery.tools.http_transport import (
    HttpTransport,
    decode_response,
    default_http_transport,
    header_value,
)
from knowledgegraph.demand_discovery.tools.network import UNTRUSTED_NOTICE
from knowledgegraph.demand_discovery.tools.page_simplify import simplify


ACQUISITION_STATUSES = {"ok", "partial", "exhausted", "needs_auth", "failed"}


@dataclass(frozen=True)
class AcquiredDocument:
    document_id: str
    source_name: str
    source_tier: str
    scope: str
    route_used: str
    title: str
    url: str
    published_at: str | None
    body_artifact_ref: str
    evidence_preview: list[dict[str, str]]
    evidence_allowed: bool
    evidence_policy: str
    rank_score: float = 0.0
    why_ranked: str = ""

    def to_internal_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "scope": self.scope,
            "route_used": self.route_used,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "body_artifact_ref": self.body_artifact_ref,
            "evidence_preview": [dict(item) for item in self.evidence_preview],
            "evidence_allowed": self.evidence_allowed,
            "evidence_policy": self.evidence_policy,
            "rank_score": self.rank_score,
            "why_ranked": self.why_ranked,
        }

    def to_model_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_name": self.source_name,
            "source_credibility": _source_credibility_label(self.source_tier),
            "published_at": self.published_at,
            "url": self.url,
            "content_preview": [
                {
                    "text": str(item.get("text", "")),
                    "why_relevant": str(
                        item.get("why_relevant")
                        or item.get("reason")
                        or self.why_ranked
                        or "与检索问题存在文本相关性"
                    ),
                }
                for item in self.evidence_preview
            ],
            "can_support_evidence": self.evidence_allowed,
            "evidence_use": _evidence_use_label(self.evidence_policy),
            "next_action": "可阅读全文" if self.body_artifact_ref else "仅可查看预览",
        }


@dataclass(frozen=True)
class AcquisitionAdapterResult:
    status: str
    documents: list[AcquiredDocument] = field(default_factory=list)
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    interrupt: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in ACQUISITION_STATUSES:
            raise ValueError(f"unknown acquisition status: {self.status}")


@dataclass(frozen=True)
class SourceAcquisitionRequest:
    entry: WhitelistEntry
    round_id: str
    research_direction_id: str
    queries: list[dict[str, str]]
    max_candidates: int

    def primary_query(self) -> str:
        if not self.queries:
            return ""
        return str(self.queries[0].get("text", "")).strip()


class SourceAcquisitionAdapter(Protocol):
    def supports(self, entry: WhitelistEntry) -> bool:
        ...

    async def acquire(
        self,
        *,
        request: SourceAcquisitionRequest,
        artifacts: ArtifactStore,
    ) -> AcquisitionAdapterResult:
        ...


class AcquiredDocumentStore:
    """Process-local lookup from model-visible document_id to stored artifact."""

    def __init__(self) -> None:
        self._records: dict[str, AcquiredDocument] = {}

    def upsert_many(self, documents: list[AcquiredDocument]) -> None:
        for document in documents:
            self._records[document.document_id] = document

    def get(self, document_id: str) -> AcquiredDocument:
        if document_id not in self._records:
            raise KeyError(document_id)
        return self._records[document_id]


class EntryUrlProbeAdapter:
    """Fetch configured entry URLs and return compact source previews.

    This adapter deliberately does not claim evidence. It exists to prove that a
    source route is reachable and to expose candidate links/preview text for the
    next acquisition iteration.
    """

    def __init__(
        self,
        http_transport: HttpTransport | None = None,
        *,
        timeout_ms: int = 30_000,
        max_bytes: int = 2_000_000,
    ) -> None:
        self._transport = http_transport or default_http_transport
        self._timeout_ms = timeout_ms
        self._max_bytes = max_bytes

    def supports(self, entry: WhitelistEntry) -> bool:
        return bool(entry.entry_urls)

    async def acquire(
        self,
        *,
        request: SourceAcquisitionRequest,
        artifacts: ArtifactStore,
    ) -> AcquisitionAdapterResult:
        entry = request.entry
        query = request.primary_query()
        if not entry.entry_urls:
            return AcquisitionAdapterResult(
                status="exhausted",
                reason="no_entry_urls",
                diagnostics={"route_used": "entry_url_probe"},
            )
        errors: list[str] = []
        for url in entry.entry_urls:
            try:
                response = await self._transport(
                    url,
                    self._timeout_ms,
                    self._max_bytes,
                )
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            if response.status_code >= 400:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            content_type = header_value(response.headers, "content-type")
            html = decode_response(response)
            page = simplify(html, artifacts)
            page_type = classify_source_page(html, url=response.url).get("page_type", "unknown")
            links = _extract_article_links(html, response.url or url)[
                : request.max_candidates
            ]
            preview_text = _preview_text(query, [item.text for item in page.paragraphs])
            title = page.title or entry.source_name
            document = AcquiredDocument(
                document_id=f"doc-{_hash(f'{request.round_id}|{entry.source_name}|{response.url or url}')}",
                source_name=entry.source_name,
                source_tier=entry.source_tier,
                scope="whitelist",
                route_used="entry_url_probe",
                title=title,
                url=response.url or url,
                published_at=page.publish_time,
                body_artifact_ref=page.text_ref,
                evidence_preview=[
                    {
                        "text": preview_text,
                        "location_ref": f"{page.text_ref}#para:0",
                    }
                ]
                if preview_text
                else [],
                evidence_allowed=False,
                evidence_policy="entry_page_preview_only",
                rank_score=_entry_probe_score(query, title, preview_text, entry),
                why_ranked=(
                    "entry page preview; use as route/candidate signal, not evidence"
                ),
            )
            return AcquisitionAdapterResult(
                status="ok",
                documents=[document],
                diagnostics={
                    "route_used": "entry_url_probe",
                    "entry_url": url,
                    "final_url": response.url,
                    "page_type": page_type,
                    "candidate_links": links,
                    "candidate_count": len(links),
                },
            )
        return AcquisitionAdapterResult(
            status="failed" if errors else "exhausted",
            reason="; ".join(errors) if errors else "no_entry_url_result",
            diagnostics={"route_used": "entry_url_probe", "errors": errors},
        )


def create_acquire_whitelist_documents_tool(
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    adapters: list[SourceAcquisitionAdapter] | None = None,
    document_store: AcquiredDocumentStore | None = None,
    source_health_snapshot: SourceHealthSnapshot | None = None,
) -> ToolDefinition:
    resolved_adapters = list(adapters or [])
    resolved_document_store = document_store or AcquiredDocumentStore()

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        queries = _queries_from_arguments(call.arguments)
        if not queries:
            return ToolResult(
                call.id,
                call.name,
                "query_bundle is required",
                {
                    "error_type": "missing_query",
                    "accepted_arguments": ["query_bundle"],
                },
                is_error=True,
            )
        query = queries[0]["text"]
        query_texts = [item["text"] for item in queries]
        query_signature = "|".join(query_texts)
        round_id = str(call.arguments.get("round_id", "") or ctx.run_id).strip()
        research_direction_id = str(
            call.arguments.get("research_direction_id", "")
        ).strip()
        requested_sources = [
            str(item).strip()
            for item in call.arguments.get("source_names", [])
            if str(item).strip()
        ]
        max_candidates = max(1, int(call.arguments.get("max_candidates", 50)))
        max_documents = max(1, int(call.arguments.get("max_documents", 20)))
        entries = _selected_entries(registry, requested_sources)

        documents: list[AcquiredDocument] = []
        source_statuses: list[dict[str, Any]] = []
        interrupt: dict[str, Any] | None = None

        for entry in entries:
            health_status = (
                source_health_snapshot.status_for(entry.source_name)
                if source_health_snapshot is not None
                else None
            )
            if _should_short_circuit_health_status(health_status):
                source_statuses.append(
                    _source_status_from_health(entry, health_status)
                )
                if health_status.status == "needs_auth" and interrupt is None:
                    interrupt = _interrupt_from_health(entry, health_status)
                continue
            adapter = _adapter_for(entry, resolved_adapters)
            if adapter is None:
                source_statuses.append(
                    _source_status(
                        entry,
                        status="exhausted",
                        reason="no_supported_adapter",
                        route_used="none",
                    )
                )
                continue
            request = SourceAcquisitionRequest(
                entry=entry,
                round_id=round_id,
                research_direction_id=research_direction_id,
                queries=queries,
                max_candidates=max_candidates,
            )
            result = await adapter.acquire(
                request=request,
                artifacts=artifacts,
            )
            documents.extend(result.documents)
            route_used = (
                result.documents[0].route_used
                if result.documents
                else str(result.diagnostics.get("route_used", ""))
            )
            source_statuses.append(
                _source_status(
                    entry,
                    status=result.status,
                    reason=result.reason,
                    route_used=route_used,
                    documents=len(result.documents),
                    diagnostics=result.diagnostics,
                )
            )
            if result.status == "needs_auth" and interrupt is None:
                interrupt = dict(result.interrupt or {})

        ranked_documents = _rank_documents(documents)[:max_documents]
        resolved_document_store.upsert_many(ranked_documents)
        status = _overall_status(source_statuses, ranked_documents, interrupt)
        acquisition_id = f"acq-{_hash(f'{round_id}|{query_signature}|{len(source_statuses)}')}"
        debug_payload = {
            "acquisition_id": acquisition_id,
            "round_id": round_id,
            "research_direction_id": research_direction_id,
            "scope": "whitelist",
            "query_used": query,
            "queries": queries,
            "documents": [
                document.to_internal_dict() for document in ranked_documents
            ],
            "source_statuses": source_statuses,
            "diagnostics": {
                "sources_requested": len(entries),
                "sources_attempted": len(source_statuses),
                "documents_returned": len(ranked_documents),
                "documents_seen": len(documents),
                "query_count": len(queries),
            },
        }
        diagnostics_ref = artifacts.put(
            _json_dumps(debug_payload),
            kind="json",
            meta={
                "tool": "acquire_whitelist_documents",
                "acquisition_id": acquisition_id,
                "content_type": "application/json",
            },
        )
        details = {
            "model_payload": {
                "documents": [
                    document.to_model_dict() for document in ranked_documents
                ],
            },
            "control": {
                "overall_status": status,
                "source_statuses": [
                    _control_source_status(item) for item in source_statuses
                ],
                "interrupt": interrupt,
            },
            "debug": {
                "diagnostics_ref": diagnostics_ref,
                "diagnostics": {
                    "query_count": len(queries),
                    "queries": queries,
                    "research_direction_id": research_direction_id,
                },
            },
        }
        return ToolResult(
            call.id,
            call.name,
            _content_summary(status, ranked_documents, source_statuses, interrupt),
            details,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="whitelist_acquisition_completed",
                    target_type="AcquisitionResult",
                    target_id=acquisition_id,
                    payload_summary=f"acquired {len(ranked_documents)} whitelist documents",
                    input_refs=query_texts,
                    output_refs=[doc.document_id for doc in ranked_documents],
                    payload={
                        "status": status,
                        "source_statuses": source_statuses,
                        "query_count": len(queries),
                    },
                )
            ],
        )

    return ToolDefinition(
        name="acquire_whitelist_documents",
        description=(
            "Search all whitelisted sources by default and return compact document "
            "previews plus per-source acquisition status."
        ),
        parameters_schema={
            "type": "object",
            "required": [],
            "properties": {
                "query_bundle": {"type": "object"},
                "research_direction_id": {"type": "string"},
                "round_id": {"type": "string"},
                "source_names": {"type": "array"},
                "max_candidates": {"type": "integer"},
                "max_documents": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=120_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def create_read_acquired_document_tool(
    document_store: AcquiredDocumentStore,
    artifacts: ArtifactStore,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        del ctx
        document_id = str(call.arguments["document_id"]).strip()
        offset = max(0, int(call.arguments.get("offset", 0)))
        limit = max(1, int(call.arguments.get("limit", 8)))
        focus = str(call.arguments.get("focus", "")).strip()
        try:
            document = document_store.get(document_id)
        except KeyError:
            return ToolResult(
                call.id,
                call.name,
                f"unknown acquired document_id: {document_id}",
                {"document_id": document_id},
                is_error=True,
            )
        if not document.body_artifact_ref:
            return ToolResult(
                call.id,
                call.name,
                f"document has no readable body: {document_id}",
                {
                    "document_id": document_id,
                    "title": document.title,
                    "source_name": document.source_name,
                    "evidence_policy": document.evidence_policy,
                },
                is_error=True,
            )
        paragraphs = _paragraphs(artifacts.get_text(document.body_artifact_ref))
        end = min(offset + limit, len(paragraphs))
        rows = [
            {
                "paragraph_id": f"p{index}",
                "text": paragraphs[index],
                "can_quote": True,
            }
            for index in range(offset, end)
        ]
        has_more = end < len(paragraphs)
        focus_text = f"; focus={focus}" if focus else ""
        content = (
            f"{UNTRUSTED_NOTICE}\n"
            f"read acquired document {document_id}{focus_text}; "
            f"returned paragraphs {offset}-{end} of {len(paragraphs)}"
        )
        return ToolResult(
            call.id,
            call.name,
            content,
            {
                "document_id": document_id,
                "title": document.title,
                "source_name": document.source_name,
                "content": rows,
                "has_more": has_more,
                "next_offset": end if has_more else None,
            },
        )

    return ToolDefinition(
        name="read_acquired_document",
        description=(
            "Read paragraphs from a document returned by acquire_whitelist_documents "
            "using document_id, without exposing artifact refs to the model."
        ),
        parameters_schema={
            "type": "object",
            "required": ["document_id"],
            "properties": {
                "document_id": {"type": "string"},
                "focus": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=30_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def _queries_from_arguments(arguments: dict[str, Any]) -> list[dict[str, str]]:
    bundle = arguments.get("query_bundle")
    rows: list[dict[str, str]] = []
    if isinstance(bundle, dict):
        bundle_queries = bundle.get("queries", [])
        if isinstance(bundle_queries, list):
            for item in bundle_queries:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                rows.append(
                    {
                        "text": text,
                        "language": str(
                            item.get("language", "auto") or "auto"
                        ).strip()
                        or "auto",
                        "intent": str(
                            item.get("intent", "evidence_discovery")
                            or "evidence_discovery"
                        ).strip()
                        or "evidence_discovery",
                    }
                )

    return _dedupe_query_rows(rows)


def _dedupe_query_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        key = " ".join(text.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "text": text,
                "language": str(row.get("language", "auto") or "auto"),
                "intent": str(
                    row.get("intent", "evidence_discovery")
                    or "evidence_discovery"
                ),
            }
        )
    return deduped


def _selected_entries(
    registry: SourceRegistry,
    source_names: list[str],
) -> list[WhitelistEntry]:
    if not source_names:
        return list(registry.sources)
    wanted = set(source_names)
    return [entry for entry in registry.sources if entry.source_name in wanted]


def _adapter_for(
    entry: WhitelistEntry,
    adapters: list[SourceAcquisitionAdapter],
) -> SourceAcquisitionAdapter | None:
    for adapter in adapters:
        if adapter.supports(entry):
            return adapter
    return None


def _source_status(
    entry: WhitelistEntry,
    *,
    status: str,
    reason: str,
    route_used: str,
    documents: int = 0,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_name": entry.source_name,
        "source_tier": entry.source_tier,
        "source_type": entry.source_type,
        "status": status,
        "reason": reason,
        "route_used": route_used,
        "documents": documents,
        "diagnostics": dict(diagnostics or {}),
    }


def _source_status_from_health(
    entry: WhitelistEntry,
    health_status: SourceHealthStatus,
) -> dict[str, Any]:
    return _source_status(
        entry,
        status=health_status.status,
        reason=health_status.reason,
        route_used="source_health",
        diagnostics={
            "provider": health_status.provider,
            "action": health_status.action,
            "checked_at": (
                health_status.checked_at.isoformat()
                if health_status.checked_at is not None
                else ""
            ),
            "ttl_seconds": health_status.ttl_seconds,
        },
    )


def _should_short_circuit_health_status(
    health_status: SourceHealthStatus | None,
) -> bool:
    return (
        health_status is not None
        and health_status.status
        in {"needs_auth", "unreachable", "not_configured", "disabled"}
    )


def _interrupt_from_health(
    entry: WhitelistEntry,
    health_status: SourceHealthStatus,
) -> dict[str, Any]:
    provider = health_status.provider or entry.fetch_transport or "source"
    reason = health_status.reason or "authorization_required"
    return {
        "interrupt_type": "auth_required",
        "provider": provider,
        "source_name": entry.source_name,
        "reason": reason,
        "resume_token": f"source-health:{entry.source_name}",
        "user_message": "source authorization is required before acquisition can continue",
    }


def _control_source_status(status: dict[str, Any]) -> dict[str, Any]:
    raw_status = str(status.get("status", ""))
    return {
        "source_name": str(status.get("source_name", "")),
        "status": raw_status,
        "reason": _readable_reason(str(status.get("reason", "")), raw_status),
        "action": _source_action(raw_status),
    }


def _overall_status(
    source_statuses: list[dict[str, Any]],
    documents: list[AcquiredDocument],
    interrupt: dict[str, Any] | None,
) -> str:
    if interrupt is not None:
        return "needs_auth"
    if documents and all(item["status"] == "ok" for item in source_statuses):
        return "ok"
    if documents:
        return "partial"
    if any(item["status"] == "failed" for item in source_statuses):
        return "failed"
    return "exhausted"


def _rank_documents(documents: list[AcquiredDocument]) -> list[AcquiredDocument]:
    return sorted(
        documents,
        key=lambda item: (item.rank_score, _tier_weight(item.source_tier), item.title),
        reverse=True,
    )


def _tier_weight(tier: str) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(tier).upper(), 0)


def _content_summary(
    status: str,
    documents: list[AcquiredDocument],
    source_statuses: list[dict[str, Any]],
    interrupt: dict[str, Any] | None,
) -> str:
    if status == "needs_auth":
        provider = str((interrupt or {}).get("provider", "source"))
        message = str((interrupt or {}).get("user_message", "authorization required"))
        return f"{UNTRUSTED_NOTICE}\nneeds authorization for {provider}: {message}"
    status_counts: dict[str, int] = {}
    for item in source_statuses:
        key = str(item.get("status", "unknown"))
        status_counts[key] = status_counts.get(key, 0) + 1
    top_lines = [
        f"- {doc.document_id} | {doc.source_name} | {doc.title} | score={doc.rank_score:.2f}"
        for doc in documents[:8]
    ]
    suffix = "\n" + "\n".join(top_lines) if top_lines else ""
    return (
        f"{UNTRUSTED_NOTICE}\n"
        f"acquired {len(documents)} documents from whitelist; "
        f"status={status}; source_status_counts={status_counts}"
        f"{suffix}"
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _source_credibility_label(tier: str) -> str:
    normalized = str(tier).upper()
    if normalized == "A":
        return "高可信来源"
    if normalized == "B":
        return "专业来源"
    if normalized == "C":
        return "线索来源"
    if normalized == "D":
        return "低可信来源"
    return "未分级来源"


def _evidence_use_label(policy: str) -> str:
    if policy in {"article_body_allowed", "pdf_body_allowed", "document_body_allowed"}:
        return "正文可作证据"
    if policy == "entry_page_preview_only":
        return "仅作线索"
    if policy == "metadata_only":
        return "仅作背景"
    return "需进一步核验"


def _source_action(status: str) -> str:
    if status == "needs_auth":
        return "pause_for_user_auth"
    if status in {"unreachable", "not_configured"}:
        return "skip_source_for_this_round"
    if status == "disabled":
        return "skip_disabled_source"
    if status == "degraded":
        return "continue_with_caution"
    if status == "failed":
        return "controller_retry_or_skip"
    if status == "exhausted":
        return "skip_source_for_this_round"
    return "continue"


def _readable_reason(reason: str, status: str) -> str:
    if reason == "wechat_session_invalid":
        return "微信公众平台登录已失效"
    if reason == "no_supported_adapter":
        return "当前来源尚无可用采集适配器"
    if reason == "no_entry_urls":
        return "当前来源缺少入口地址"
    if reason == "entry_url_probe_failed":
        return "entry_url_probe_failed"
    if reason == "source_disabled_for_run":
        return "source disabled for this run"
    if reason == "browser_session_not_enabled":
        return "browser session is not configured"
    if reason == "wechat_session_missing":
        return "wechat session authorization is missing"
    if reason == "no_entry_route_configured":
        return "no entry route is configured"
    if reason == "no_matching_candidates":
        return "未发现匹配候选"
    if reason:
        return reason
    if status == "ok":
        return "已返回候选材料"
    if status == "partial":
        return "部分返回候选材料"
    if status == "exhausted":
        return "本轮未发现可用材料"
    if status == "failed":
        return "采集失败"
    if status == "needs_auth":
        return "需要用户授权"
    return ""


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _paragraphs(text: str) -> list[str]:
    return [item.strip() for item in text.split("\n\n") if item.strip()]


def _preview_text(query: str, paragraphs: list[str]) -> str:
    if not paragraphs:
        return ""
    ranked = sorted(
        (item.strip() for item in paragraphs if item.strip()),
        key=lambda item: _topic_score(query, item),
        reverse=True,
    )
    text = ranked[0] if ranked else paragraphs[0]
    return text[:360]


def _entry_probe_score(
    query: str,
    title: str,
    preview: str,
    entry: WhitelistEntry,
) -> float:
    tier = {"A": 2.0, "B": 1.5, "C": 1.0, "D": 0.5}.get(entry.source_tier, 0.0)
    return tier + _topic_score(query, f"{title} {preview}")
