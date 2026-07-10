"""Domain tool definitions for demand discovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from knowledgegraph.demand_discovery.domain.audit_rubric import (
    AuditRubric,
    load_default_rubric,
    validate_scorecard,
)
from knowledgegraph.demand_discovery.domain.dedup import check_candidate
from knowledgegraph.demand_discovery.domain.evidence_support import (
    evidence_reviews_from_scorecard,
    normalize_support_level,
    validate_semantic_audit_scorecard,
)
from knowledgegraph.demand_discovery.domain.judgement import (
    JudgementReport,
    judgement_report_from_dict,
)
from knowledgegraph.demand_discovery.domain.judgement_plan import (
    GAP_TYPES,
    ROUTING_HINTS,
    SOURCE_SCOPES,
    assess_next_round_plan,
    build_repaired_next_round_plan,
)
from knowledgegraph.demand_discovery.domain.models import EvidenceCard
from knowledgegraph.demand_discovery.domain.open_search import (
    SOURCE_QUALITY_LEVELS,
    SourceQualityAssessment,
)
from knowledgegraph.demand_discovery.domain.report import (
    REQUIRED_SECTIONS,
    VALID_DEMAND_TYPES,
    render_report_sections,
    validate_report_sections,
)
from knowledgegraph.demand_discovery.domain.report_consistency import (
    validate_report_consistency,
)
from knowledgegraph.demand_discovery.domain.state_machine import STATUSES
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
from knowledgegraph.demand_discovery.tools.browser_actions import (
    BrowserActionState,
    BrowserSession,
    BrowserUrlScope,
    create_browser_execute_tool,
    create_browser_observe_tool,
)
from knowledgegraph.demand_discovery.tools.documents import (
    create_extract_summary_tool,
    create_read_document_tool,
)
from knowledgegraph.demand_discovery.tools.discovery import (
    create_classify_source_page_tool,
    create_discover_articles_tool,
    create_download_document_tool,
)
from knowledgegraph.demand_discovery.tools.keyword_gate import (
    KeywordGate,
    load_default_keyword_gate,
)
from knowledgegraph.demand_discovery.tools.network import (
    HttpTransport,
    create_fetch_page_tool,
)
from knowledgegraph.demand_discovery.tools.open_fetch import create_fetch_open_source_page_tool
from knowledgegraph.demand_discovery.tools.search import (
    OpenSearchAdapter,
    SearchAdapter,
    build_default_search_adapters,
    create_open_search_sources_batch_tool,
    create_open_search_sources_tool,
    create_search_sources_tool,
)


_DEFAULT_RUBRIC = object()


def build_domain_tools(
    domain_store: DomainStore | None = None,
    rubric: AuditRubric | None | object = _DEFAULT_RUBRIC,
    source_registry: SourceRegistry | None = None,
) -> list[ToolDefinition]:
    resolved_rubric = load_default_rubric() if rubric is _DEFAULT_RUBRIC else rubric
    return [
        create_source_record_tool(domain_store, source_registry),
        create_assess_source_quality_tool(domain_store),
        create_evidence_card_tool(domain_store),
        create_or_update_candidate_tool(domain_store),
        merge_candidate_tool(domain_store),
        record_judgement_tool(domain_store),
        run_audit_tool(domain_store, rubric=resolved_rubric),
        generate_demand_report_tool(domain_store),
    ]


def build_all_tools(
    domain_store: DomainStore | None,
    source_registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    rubric: AuditRubric | None | object = _DEFAULT_RUBRIC,
    keyword_gate: KeywordGate | None = None,
    search_adapters: list[SearchAdapter] | None = None,
    fetch_http_transport: HttpTransport | None = None,
    enable_browser_tools: bool = False,
    browser_session: BrowserSession | None = None,
    enable_open_search_tools: bool = False,
    open_search_adapters: list[OpenSearchAdapter] | None = None,
) -> list[ToolDefinition]:
    """Build the Phase 3 worker tool surface.

    Domain tools remain separate for existing fake/manual flows; this helper is
    the network-enabled reader/debater surface.
    """

    gate = keyword_gate or load_default_keyword_gate()
    resolved_search_adapters = (
        list(search_adapters)
        if search_adapters is not None
        else build_default_search_adapters(source_registry, artifacts)
    )
    browser_tools: list[ToolDefinition] = []
    if enable_browser_tools:
        browser_state = BrowserActionState()
        allowed_browser_scopes = _allowed_browser_scopes_from_domain_store(domain_store)
        browser_tools = [
            create_browser_observe_tool(
                source_registry,
                artifacts,
                state=browser_state,
                browser_session=browser_session,
                allowed_scopes=allowed_browser_scopes,
            ),
            create_browser_execute_tool(
                source_registry,
                artifacts,
                state=browser_state,
                browser_session=browser_session,
                allowed_scopes=allowed_browser_scopes,
                domain_store=domain_store,
            ),
        ]
    open_search_tools: list[ToolDefinition] = []
    if enable_open_search_tools:
        open_search_tools = [
            create_open_search_sources_tool(
                domain_store,
                source_registry,
                adapters=open_search_adapters,
            ),
            create_open_search_sources_batch_tool(
                domain_store,
                source_registry,
                adapters=open_search_adapters,
            ),
            create_fetch_open_source_page_tool(
                domain_store,
                artifacts,
                http_transport=fetch_http_transport,
            ),
        ]
    return [
        create_search_sources_tool(
            source_registry,
            gate,
            adapters=resolved_search_adapters,
        ),
        *open_search_tools,
        create_fetch_page_tool(
            source_registry,
            artifacts,
            http_transport=fetch_http_transport,
        ),
        create_classify_source_page_tool(artifacts),
        create_discover_articles_tool(
            domain_store,
            source_registry,
            artifacts,
            http_transport=fetch_http_transport,
        ),
        create_download_document_tool(
            domain_store,
            source_registry,
            artifacts,
            http_transport=fetch_http_transport,
        ),
        create_read_document_tool(artifacts),
        create_extract_summary_tool(artifacts),
        *browser_tools,
        *build_domain_tools(
            domain_store,
            rubric=rubric,
            source_registry=source_registry,
        ),
    ]


def _allowed_browser_scopes_from_domain_store(
    domain_store: DomainStore | None,
) -> list[BrowserUrlScope]:
    if domain_store is None:
        return []
    scopes: list[BrowserUrlScope] = []
    for lead in domain_store.open_source_leads.values():
        plan = domain_store.open_search_plans.get(lead.plan_id)
        if plan is None or plan.status not in {"planned", "running"}:
            continue
        parsed = urlparse(lead.url)
        host = parsed.hostname or lead.domain
        scopes.append(
            BrowserUrlScope(
                scope_type="open_search_plan",
                source_name=lead.source_name_guess or lead.domain or "open_web",
                plan_id=lead.plan_id,
                lead_id=lead.lead_id,
                url_prefixes=[lead.url],
                hosts=[host] if host else [],
                scope_granularity="url_prefix",
            )
        )
    return scopes


def create_source_record_tool(
    domain_store: DomainStore | None = None,
    source_registry: SourceRegistry | None = None,
) -> ToolDefinition:
    if isinstance(domain_store, SourceRegistry) and source_registry is None:
        source_registry = domain_store
        domain_store = None

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        source_id = str(args["source_id"])
        payload = {
            "source_id": source_id,
            "title": args.get("title", ""),
            "source_name": args.get("source_name", ""),
            "source_tier": args.get("source_tier", "C"),
            "source_type": args.get("source_type", "document"),
            "publish_time": args.get("publish_time"),
            "url_or_path": args.get("url_or_path", ""),
            "summary_text": args.get("summary_text"),
            "summary_source": args.get("summary_source", "model_generated"),
            "collection_decision": args.get(
                "collection_decision", "use_as_signal_only"
            ),
            "author_or_org": args.get("author_or_org"),
            "is_repost": args.get("is_repost"),
            "original_source": args.get("original_source"),
            "institutional_stance": args.get("institutional_stance"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        if source_registry is not None:
            entry = source_registry.match(str(payload.get("url_or_path", "")))
            if entry is not None:
                payload["source_name"] = entry.source_name
                payload["source_tier"] = entry.source_tier
                payload["source_type"] = entry.source_type
        open_source_lead_id = str(args.get("open_source_lead_id", "")).strip()
        if open_source_lead_id:
            if domain_store is None or open_source_lead_id not in domain_store.open_source_leads:
                return ToolResult(
                    call.id,
                    call.name,
                    f"unknown open_source_lead_id: {open_source_lead_id}",
                    {"open_source_lead_id": open_source_lead_id},
                    is_error=True,
                )
            latest = _latest_quality_assessment_for_lead(domain_store, open_source_lead_id)
            payload["open_source_lead_id"] = open_source_lead_id
            payload["source_tier"] = "B"
            payload["source_type"] = "open_web"
            if payload["collection_decision"] == "use_as_evidence":
                if latest is None:
                    return ToolResult(
                        call.id,
                        call.name,
                        "open source quality assessment is required",
                        {"open_source_lead_id": open_source_lead_id},
                        is_error=True,
                    )
                if latest.quality_level not in {"trusted", "usable"}:
                    return ToolResult(
                        call.id,
                        call.name,
                        f"open source quality is not accepted: {latest.quality_level}",
                        {
                            "open_source_lead_id": open_source_lead_id,
                            "quality_level": latest.quality_level,
                        },
                        is_error=True,
                    )
        return ToolResult(
            call.id,
            call.name,
            f"recorded source {source_id}",
            {"source_id": source_id},
            domain_proposals=[
                DomainWriteProposal("upsert", "SourceRecord", payload)
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="source_seen",
                    target_type="SourceRecord",
                    target_id=source_id,
                    payload_summary=f"source seen {source_id}",
                    output_refs=[source_id],
                )
            ],
        )

    return ToolDefinition(
        "create_source_record",
        "Create or update a source record.",
        _object_schema(
            required=["source_id"],
            properties={
                "source_id": _string("Stable source id."),
                "title": _string("Short source title."),
                "source_name": _string("Publication, site, or source name."),
                "source_tier": _string("Source quality tier such as A/B/C."),
                "source_type": _string("Source type, for example demo or document."),
                "publish_time": _string("ISO publish time when available."),
                "url_or_path": _string("URL, file path, or stable source locator."),
                "summary_text": _string("Concise source summary."),
                "summary_source": _string("How the summary was produced."),
                "collection_decision": _string("Evidence collection decision."),
                "author_or_org": _string("Author or organization when available."),
                "is_repost": {"type": "boolean"},
                "original_source": _string("Original source if this is a repost."),
                "institutional_stance": _string("Source stance or affiliation signal."),
                "open_source_lead_id": _string("OpenSourceLead id when this source came from open search."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def create_evidence_card_tool(
    domain_store: DomainStore | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        evidence_id = str(args["evidence_id"])
        source_id = str(args.get("source_id", ""))
        payload = {
            "evidence_id": evidence_id,
            "source_id": source_id,
            "claim": args.get("claim", ""),
            "evidence_summary": args.get("evidence_summary", ""),
            "excerpt": args.get("excerpt"),
            "source_location": args.get("source_location", ""),
            "evidence_assessment": args.get("evidence_assessment", "unreviewed"),
            "created_by": ctx.worker_id,
            "created_at": _now(),
            "source_quality_assessment_id": args.get("source_quality_assessment_id"),
        }
        if domain_store is not None and (not source_id or source_id in domain_store.sources):
            try:
                staged = domain_store.clone()
                accepted = staged.upsert_evidence(
                    EvidenceCard(
                        evidence_id=evidence_id,
                        source_id=source_id,
                        claim=str(payload.get("claim", "")),
                        evidence_summary=str(payload.get("evidence_summary", "")),
                        excerpt=payload.get("excerpt"),
                        source_location=str(payload.get("source_location", "")),
                        evidence_assessment=str(payload.get("evidence_assessment", "")),
                        created_by=str(payload.get("created_by", "")),
                        created_at=payload["created_at"],
                        source_quality_assessment_id=payload.get("source_quality_assessment_id"),
                    )
                )
                payload = accepted.to_dict()
            except ValueError as exc:
                return ToolResult(
                    call.id,
                    call.name,
                    str(exc),
                    {"evidence_id": evidence_id, "source_id": source_id},
                    is_error=True,
                )
        return ToolResult(
            call.id,
            call.name,
            f"created evidence card {evidence_id}",
            {"evidence_id": evidence_id, "source_id": source_id},
            domain_proposals=[
                DomainWriteProposal("upsert", "EvidenceCard", payload)
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="evidence_created",
                    target_type="EvidenceCard",
                    target_id=evidence_id,
                    payload_summary=f"created evidence {evidence_id}",
                    input_refs=[source_id] if source_id else [],
                    output_refs=[evidence_id],
                )
            ],
        )

    return ToolDefinition(
        "create_evidence_card",
        "Create an evidence card proposal.",
        _object_schema(
            required=["evidence_id"],
            properties={
                "evidence_id": _string("Stable evidence id."),
                "source_id": _string("SourceRecord id supporting the evidence."),
                "claim": _string("Atomic claim supported by the source."),
                "evidence_summary": _string("Short evidence summary."),
                "excerpt": _string("Short quoted or paraphrased excerpt."),
                "source_location": _string(
                    "For fetched pages, use the exact '<simplified_ref>#para:<index>' "
                    "location shown by read_document."
                ),
                "evidence_assessment": _string("Assessment such as strong or weak."),
                "source_quality_assessment_id": _string("SourceQualityAssessment id for open sources."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def create_assess_source_quality_tool(
    domain_store: DomainStore | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        lead_id = str(args["lead_id"])
        if domain_store is None or lead_id not in domain_store.open_source_leads:
            return ToolResult(
                call.id,
                call.name,
                f"unknown open_source_lead_id: {lead_id}",
                {"lead_id": lead_id},
                is_error=True,
            )
        lead = domain_store.open_source_leads[lead_id]
        quality_level = str(args["quality_level"])
        if quality_level not in SOURCE_QUALITY_LEVELS:
            return ToolResult(
                call.id,
                call.name,
                f"unknown SourceQualityAssessment quality_level: {quality_level}",
                {"quality_level": quality_level},
                is_error=True,
            )
        if quality_level == "trusted":
            return ToolResult(
                call.id,
                call.name,
                "trusted quality requires human-reviewed whitelist or manual source approval",
                {"quality_level": quality_level},
                is_error=True,
            )
        basis_artifact_refs = [
            str(item).strip()
            for item in args.get("basis_artifact_refs", [])
            if str(item).strip()
        ]
        body_location_refs = [
            str(item).strip()
            for item in args.get("body_location_refs", [])
            if str(item).strip()
        ]
        assessment = SourceQualityAssessment(
            assessment_id=str(args["assessment_id"]),
            lead_id=lead_id,
            url=lead.url,
            domain=lead.domain,
            basis_artifact_refs=basis_artifact_refs,
            body_location_refs=body_location_refs,
            read_document_ref=str(args.get("read_document_ref", basis_artifact_refs[0] if basis_artifact_refs else "")),
            source_identity=str(args.get("source_identity", "")),
            publisher_or_org=str(args.get("publisher_or_org", "")),
            author=str(args.get("author", "")),
            publish_time=str(args.get("publish_time", "")),
            is_original_source=args.get("is_original_source")
            if isinstance(args.get("is_original_source"), bool)
            else None,
            citation_or_reference_signal=str(args.get("citation_or_reference_signal", "")),
            content_type=str(args.get("content_type", "")),
            quality_level=quality_level,
            risk_flags=[str(item) for item in args.get("risk_flags", [])],
            reason=str(args.get("reason", "")),
            created_by=ctx.worker_id,
            created_at=_now(),
        )
        try:
            staged = domain_store.clone()
            staged.upsert_source_quality_assessment(assessment)
        except ValueError as exc:
            return ToolResult(
                call.id,
                call.name,
                str(exc),
                {"lead_id": lead_id, "assessment_id": assessment.assessment_id},
                is_error=True,
            )
        payload = assessment.to_dict()
        return ToolResult(
            call.id,
            call.name,
            f"assessed source quality {assessment.assessment_id}: {quality_level}",
            {"assessment_id": assessment.assessment_id, "lead_id": lead_id},
            domain_proposals=[
                DomainWriteProposal("upsert", "SourceQualityAssessment", payload)
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="source_quality_assessed",
                    target_type="SourceQualityAssessment",
                    target_id=assessment.assessment_id,
                    payload_summary=f"source quality assessed {assessment.assessment_id}",
                    input_refs=[lead_id, *basis_artifact_refs],
                    output_refs=[assessment.assessment_id],
                    payload={
                        "quality_level": quality_level,
                        "risk_flags": list(assessment.risk_flags),
                    },
                )
            ],
        )

    return ToolDefinition(
        "assess_source_quality",
        "Record source quality assessment for an OpenSourceLead before evidence use.",
        _object_schema(
            required=[
                "assessment_id",
                "lead_id",
                "basis_artifact_refs",
                "body_location_refs",
                "quality_level",
                "reason",
            ],
            properties={
                "assessment_id": _string("Stable assessment id."),
                "lead_id": _string("OpenSourceLead id."),
                "basis_artifact_refs": _string_array("Artifact refs for fetched/read public body."),
                "body_location_refs": _string_array("Paragraph/source_location refs from read_document."),
                "read_document_ref": _string("Primary artifact_ref read before assessment."),
                "source_identity": _string("Source identity shown by the page."),
                "publisher_or_org": _string("Publisher or organization."),
                "author": _string("Author if present."),
                "publish_time": _string("Publish date or time if present."),
                "is_original_source": {"type": "boolean"},
                "citation_or_reference_signal": _string("Citation or source-chain signal."),
                "content_type": _string("article/report/blog/forum/page."),
                "quality_level": {"type": "string", "enum": sorted(SOURCE_QUALITY_LEVELS)},
                "risk_flags": _string_array("Risk flags."),
                "reason": _string("Quality assessment rationale."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def create_or_update_candidate_tool(
    domain_store: DomainStore | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        evidence_ids = list(args.get("evidence_ids", []))
        if domain_store is not None:
            missing = [item for item in evidence_ids if item not in domain_store.evidence]
            if missing:
                return ToolResult(
                    call.id,
                    call.name,
                    f"unknown evidence_id: {missing[0]}",
                    {"missing_evidence_id": missing[0]},
                    is_error=True,
                )
        candidate_id = str(args["candidate_id"])
        exists = domain_store is not None and candidate_id in domain_store.candidates
        status, status_error = _normalize_candidate_status(args.get("status"))
        if status_error is not None:
            return ToolResult(
                call.id,
                call.name,
                status_error,
                {
                    "status": args.get("status"),
                    "allowed_statuses": sorted(STATUSES),
                    "aliases": sorted(_CANDIDATE_STATUS_ALIASES),
                },
                is_error=True,
            )
        event_type = "candidate_updated" if exists else "candidate_created"
        if exists and domain_store is not None:
            current = domain_store.candidates[candidate_id]
            if current.status == "demand_report" and status == "candidate_demand":
                event_type = "candidate_status_rolled_back"
        dedup_result = (
            check_candidate(
                domain_store,
                str(args.get("title", "")),
                str(args.get("demand_statement", "")),
            )
            if domain_store is not None
            else None
        )
        payload = {
            "candidate_id": candidate_id,
            "title": args.get("title", ""),
            "demand_statement": args.get("demand_statement", ""),
            "status": status,
            "evidence_ids": evidence_ids,
            "open_questions": list(args.get("open_questions", [])),
            "solution_signals": list(args.get("solution_signals", [])),
            "created_by": ctx.worker_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        trace_proposals: list[DomainTraceProposal] = []
        details: dict[str, Any] = {"candidate_id": candidate_id}
        content = f"proposed candidate {candidate_id}"
        if dedup_result is not None:
            details["similar_candidates"] = dedup_result.to_dict()
            near = dedup_result.to_dict()["near_duplicates"]
            if near:
                trace_proposals.append(
                    DomainTraceProposal(
                        event_type="duplicate_checked",
                        target_type="CandidateDemand",
                        target_id=candidate_id,
                        payload_summary=f"duplicate checked {candidate_id}",
                        input_refs=[
                            item["candidate_id"]
                            for item in near
                        ],
                        output_refs=[candidate_id],
                        payload=dedup_result.to_dict(),
                    )
                )
            if near:
                near_ids = ", ".join(str(item["candidate_id"]) for item in near)
                content = (
                    f"proposed candidate {candidate_id}; 存在高度相似候选 "
                    f"{near_ids}，请先 read 后决定合并（merge_candidate）或差异化改写"
                )
        trace_proposals.append(
            DomainTraceProposal(
                event_type=event_type,
                target_type="CandidateDemand",
                target_id=candidate_id,
                payload_summary=f"{event_type} {candidate_id}",
                input_refs=evidence_ids,
                output_refs=[candidate_id],
                payload={
                    "open_questions": list(args.get("open_questions", [])),
                },
            )
        )
        return ToolResult(
            call.id,
            call.name,
            content,
            details,
            domain_proposals=[
                DomainWriteProposal("upsert", "CandidateDemand", payload)
            ],
            trace_proposals=trace_proposals,
        )

    return ToolDefinition(
        "create_or_update_candidate",
        "Create or update a candidate demand proposal.",
        _object_schema(
            required=["candidate_id"],
            properties={
                "candidate_id": _string("Stable candidate demand id."),
                "title": _string("Short candidate title."),
                "demand_statement": _string("Demand statement."),
                "status": _string(
                    "Candidate lifecycle status. Omit for candidate_demand; "
                    "proposed is treated as candidate_demand."
                )
                | {"enum": sorted(STATUSES)},
                "evidence_ids": _string_array("Evidence ids supporting the candidate."),
                "open_questions": _string_array("Open questions for follow-up."),
                "solution_signals": _string_array("Potential solution signals."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


_CANDIDATE_STATUS_ALIASES = {
    "candidate": "candidate_demand",
    "candidate_proposal": "candidate_demand",
    "proposal": "candidate_demand",
    "proposed": "candidate_demand",
}


def _normalize_candidate_status(value: Any) -> tuple[str, str | None]:
    if value is None:
        return "candidate_demand", None
    raw = str(value).strip()
    if not raw:
        return "candidate_demand", None
    status = raw.lower().replace("-", "_").replace(" ", "_")
    status = _CANDIDATE_STATUS_ALIASES.get(status, status)
    if status not in STATUSES:
        return "", f"unknown candidate status: {raw}"
    return status, None


def merge_candidate_tool(domain_store: DomainStore | None = None) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        candidate_id = str(args["candidate_id"])
        surviving = str(args["surviving_candidate_id"])
        if domain_store is not None and surviving not in domain_store.candidates:
            return ToolResult(
                call.id,
                call.name,
                f"unknown surviving_candidate_id: {surviving}",
                {"surviving_candidate_id": surviving},
                is_error=True,
            )
        return ToolResult(
            call.id,
            call.name,
            f"merged candidate {candidate_id} into {surviving}",
            {"candidate_id": candidate_id, "surviving_candidate_id": surviving},
            domain_proposals=[
                DomainWriteProposal(
                    "merge",
                    "CandidateDemand",
                    {
                        "candidate_id": candidate_id,
                        "surviving_candidate_id": surviving,
                    },
                )
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="candidate_merged",
                    target_type="CandidateDemand",
                    target_id=surviving,
                    payload_summary=f"merged {candidate_id} into {surviving}",
                    input_refs=[candidate_id],
                    output_refs=[surviving],
                )
            ],
        )

    return ToolDefinition(
        "merge_candidate",
        "Merge one candidate into another.",
        _object_schema(
            required=["candidate_id", "surviving_candidate_id"],
            properties={
                "candidate_id": _string("Candidate id to supersede."),
                "surviving_candidate_id": _string("Candidate id that remains active."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def record_judgement_tool(
    domain_store: DomainStore | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        payload = {
            **dict(call.arguments),
            "created_at": _now(),
        }
        plan = dict(payload.get("next_round_plan", {}))
        if not assess_next_round_plan(plan).is_valid:
            payload["next_round_plan"] = build_repaired_next_round_plan(
                plan,
                round_id=str(payload.get("round_id", "")),
            )
        try:
            report = judgement_report_from_dict(payload)
        except ValueError as exc:
            return ToolResult(
                call.id,
                call.name,
                str(exc),
                {"judgement_id": payload.get("judgement_id")},
                is_error=True,
            )
        return ToolResult(
            call.id,
            call.name,
            f"recorded judgement {report.judgement_id}",
            {"judgement_id": report.judgement_id, "round_id": report.round_id},
            domain_proposals=[
                DomainWriteProposal("upsert", "JudgementReport", report.to_dict())
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="judgement_recorded",
                    target_type="JudgementReport",
                    target_id=report.judgement_id,
                    payload_summary=f"judgement recorded {report.judgement_id}",
                    input_refs=[
                        worker_id
                        for item in [
                            *report.consensus_points,
                            *report.contradictions,
                            *report.partial_coverage,
                            *report.unique_insights,
                            *report.blind_spots,
                        ]
                        for worker_id in item.worker_report_ids
                    ],
                    output_refs=[report.judgement_id],
                    payload={"decision": report.stop_or_continue},
                )
            ],
        )

    judgement_item_schema = {
        "type": "object",
        "required": ["text", "worker_report_ids"],
        "properties": {
            "text": _string(
                "One judgement item statement. Do not use point, issue, "
                "blind_spot, area, insight, details, impact, or limitation."
            ),
            "worker_report_ids": _string_array(
                "Worker report ids that support or produced this item."
            ),
            "evidence_ids": _string_array("Evidence ids supporting this item."),
            "lead_ids": _string_array("Lead ids supporting this item."),
        },
        "additionalProperties": False,
    }
    item_schema = {
        "type": "array",
        "items": judgement_item_schema,
    }
    return ToolDefinition(
        "record_judgement",
        "Record a structured judge/synthesis report for one research round.",
        _object_schema(
            required=["judgement_id", "round_id", "stop_or_continue"],
            properties={
                "judgement_id": _string("Stable judgement id."),
                "round_id": _string("ResearchRound id."),
                "consensus_points": item_schema,
                "contradictions": item_schema,
                "partial_coverage": item_schema,
                "unique_insights": item_schema,
                "blind_spots": item_schema,
                "evidence_strength_map": {"type": "object"},
                "next_round_plan": _next_round_plan_schema(),
                "stop_or_continue": {
                    "type": "string",
                    "enum": ["stop", "continue", "needs_human_steer"],
                },
                "rationale": _string("Judge rationale."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def _next_round_plan_schema() -> dict[str, Any]:
    query_revision_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "language": _string("Query language such as zh, en, or auto."),
            "query": _string("Concrete search query authorized for controller use."),
        },
        "additionalProperties": False,
    }
    controller_task_schema = {
        "type": "object",
        "required": [
            "task_id",
            "objective",
            "gap_type",
            "routing_hint",
            "source_scope",
            "input_refs",
            "query_revisions",
            "completion_check",
        ],
        "properties": {
            "task_id": _string("Stable task id, for example task-1."),
            "objective": _string("Natural-language objective combining question and action intent."),
            "gap_type": {
                "type": "string",
                "enum": sorted(GAP_TYPES),
                "description": "Controlled evidence gap type.",
            },
            "routing_hint": {
                "type": "string",
                "enum": sorted(ROUTING_HINTS),
                "description": "Controlled controller routing hint.",
            },
            "source_scope": {
                "type": "string",
                "enum": sorted(SOURCE_SCOPES),
                "description": "Controlled source scope for this task.",
            },
            "input_refs": {
                "type": "object",
                "properties": {
                    "worker_report_ids": _string_array("Worker report ids."),
                    "evidence_ids": _string_array("Evidence ids."),
                    "lead_ids": _string_array("Lead ids."),
                },
                "additionalProperties": False,
            },
            "query_revisions": {
                "type": "array",
                "items": query_revision_schema,
                "description": "Controller-consumed search query revisions.",
            },
            "completion_check": _string("Concrete condition for ending this task."),
        },
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "required": [
            "plan_version",
            "controller_tasks",
            "worker_briefs",
        ],
        "properties": {
            "plan_version": {"type": "integer", "enum": [1]},
            "round_id": _string("Research round id."),
            "summary": _string("Short plan summary."),
            "controller_tasks": {
                "type": "array",
                "items": controller_task_schema,
            },
            "worker_briefs": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Map keyed by task_id; natural-language brief for the worker.",
            },
            "remaining_open_questions": _string_array("Remaining open questions."),
            "stop_candidate_reason": _string("Reason when the judge believes stopping is acceptable."),
        },
        "additionalProperties": False,
    }


def run_audit_tool(
    domain_store: DomainStore | None = None,
    rubric: AuditRubric | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        candidate_id = str(args["candidate_id"])
        if domain_store is not None and candidate_id not in domain_store.candidates:
            return ToolResult(
                call.id,
                call.name,
                f"unknown candidate_id: {candidate_id}",
                {"candidate_id": candidate_id},
                is_error=True,
            )
        audit_id = str(args["audit_id"])
        conclusion = str(args.get("conclusion", "needs_revision"))
        if domain_store is not None and audit_id in domain_store.audit_reports:
            existing = domain_store.audit_reports[audit_id]
            conflict_message = _audit_conflict_message(
                audit_id,
                existing_candidate_id=existing.candidate_id,
                existing_conclusion=existing.conclusion,
                candidate_id=candidate_id,
                conclusion=conclusion,
            )
            if conflict_message is not None:
                return ToolResult(
                    call.id,
                    call.name,
                    conflict_message,
                    {
                        "audit_id": audit_id,
                        "candidate_id": candidate_id,
                        "existing_candidate_id": existing.candidate_id,
                        "existing_conclusion": existing.conclusion,
                    },
                    is_error=True,
                )
            return ToolResult(
                call.id,
                call.name,
                f"audit {audit_id} already exists: {existing.conclusion}",
                {"audit_id": audit_id, "candidate_id": candidate_id},
            )
        scorecard = dict(args.get("scorecard", {}))
        if rubric is not None:
            try:
                conclusion = validate_scorecard(rubric, scorecard, conclusion)
            except ValueError as exc:
                return ToolResult(
                    call.id,
                    call.name,
                    str(exc),
                    {
                        "audit_id": audit_id,
                        "candidate_id": candidate_id,
                        "required_item_ids": rubric.item_ids,
                    },
                    is_error=True,
                )
        if domain_store is not None:
            candidate = domain_store.candidates[candidate_id]
            conclusion, semantic_rework = validate_semantic_audit_scorecard(
                scorecard=scorecard,
                conclusion=conclusion,
                evidence_ids=list(candidate.evidence_ids),
            )
            if semantic_rework:
                rework = list(args.get("required_rework", []))
                rework.extend(item for item in semantic_rework if item not in rework)
                args = {**args, "required_rework": rework}
                if conclusion.strip().lower() in {"approved", "pass", "通过"}:
                    return ToolResult(
                        call.id,
                        call.name,
                        "; ".join(semantic_rework),
                        {
                            "audit_id": audit_id,
                            "candidate_id": candidate_id,
                            "semantic_rework": semantic_rework,
                        },
                        is_error=True,
                    )
        payload = {
            "audit_id": audit_id,
            "candidate_id": candidate_id,
            "conclusion": conclusion,
            "scorecard": scorecard,
            "comments": args.get("comments", ""),
            "required_rework": list(args.get("required_rework", [])),
            "created_by": ctx.worker_id,
            "created_at": _now(),
        }
        evidence_update_proposals: list[DomainWriteProposal] = []
        evidence_update_traces: list[DomainTraceProposal] = []
        if domain_store is not None:
            evidence_update_proposals, evidence_update_traces = (
                _reviewed_evidence_update_proposals(
                    domain_store,
                    candidate_id=candidate_id,
                    audit_id=audit_id,
                    scorecard=scorecard,
                )
            )
        return ToolResult(
            call.id,
            call.name,
            f"audit {audit_id}: {payload['conclusion']}",
            {"audit_id": audit_id, "candidate_id": candidate_id},
            domain_proposals=[
                DomainWriteProposal("append", "AuditReport", payload),
                *evidence_update_proposals,
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="audit_completed",
                    target_type="AuditReport",
                    target_id=audit_id,
                    payload_summary=f"audit completed {audit_id}",
                    input_refs=_audit_input_refs(domain_store, candidate_id),
                    output_refs=[audit_id],
                    payload={
                        "decision": payload["conclusion"],
                        "evidence_support": scorecard.get("evidence_support", {}),
                        "required_rework": list(payload["required_rework"]),
                    },
                ),
                *evidence_update_traces,
            ],
        )

    return ToolDefinition(
        "run_audit",
        _audit_tool_description(rubric),
        _object_schema(
            required=["audit_id", "candidate_id"],
            properties={
                "audit_id": _string("Stable audit report id."),
                "candidate_id": _string("Candidate id being audited."),
                "conclusion": _string("Audit conclusion."),
                "scorecard": _scorecard_schema(rubric),
                "comments": _string("Audit comments."),
                "required_rework": _string_array("Required rework items."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def generate_demand_report_tool(
    domain_store: DomainStore | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        args = call.arguments
        candidate_id = str(args["candidate_id"])
        audit_id = str(args.get("audit_id", ""))
        report_id = str(args["report_id"])
        evidence_ids = list(args.get("evidence_ids", []))
        report_context_bundle_id = str(args.get("report_context_bundle_id", ""))
        review_status = str(args.get("review_status", "review_ready"))
        domain_trace_ids = list(args.get("domain_trace_ids", []))
        bundle = None
        if domain_store is not None:
            if candidate_id not in domain_store.candidates:
                return ToolResult(
                    call.id,
                    call.name,
                    f"unknown candidate_id: {candidate_id}",
                    {"candidate_id": candidate_id},
                    is_error=True,
                )
            if report_context_bundle_id:
                bundle = domain_store.report_context_bundles.get(
                    report_context_bundle_id
                )
                if bundle is None:
                    return ToolResult(
                        call.id,
                        call.name,
                        f"unknown report_context_bundle_id: {report_context_bundle_id}",
                        {"report_context_bundle_id": report_context_bundle_id},
                        is_error=True,
                    )
                review_status = bundle.review_status
            try:
                if review_status in {"draft", "review_ready"}:
                    domain_store.validate_demand_report_gate(
                        candidate_id,
                        audit_id,
                        evidence_ids,
                    )
                else:
                    domain_store.validate_demand_report_reference_gate(
                        candidate_id,
                        audit_id,
                        evidence_ids,
                        require_minimum_supported_evidence=False,
                    )
            except ValueError as exc:
                return ToolResult(
                    call.id,
                    call.name,
                    str(exc),
                    {
                        "candidate_id": candidate_id,
                        "audit_id": audit_id,
                        "evidence_ids": evidence_ids,
                    },
                    is_error=True,
                )
        body = str(args.get("body", ""))
        sections = args.get("sections")
        if isinstance(sections, dict):
            demand_type = str(args.get("demand_type", ""))
            try:
                validate_report_sections(sections, demand_type)
                body = render_report_sections(
                    domain_store,
                    title=str(args.get("title", "")),
                    sections=sections,
                    demand_type=demand_type,
                    evidence_ids=evidence_ids,
                    related_technical_directions=list(
                        args.get("related_technical_directions", [])
                    ),
                    solution_clues=list(args.get("solution_clues", [])),
                )
            except ValueError as exc:
                return ToolResult(
                    call.id,
                    call.name,
                    str(exc),
                    {},
                    is_error=True,
                )
        if bundle is not None:
            consistency_errors = validate_report_consistency(
                bundle,
                report_body=body,
                evidence_ids=evidence_ids,
                domain_trace_ids=domain_trace_ids,
            )
            if consistency_errors:
                return ToolResult(
                    call.id,
                    call.name,
                    "; ".join(consistency_errors),
                    {
                        "report_context_bundle_id": report_context_bundle_id,
                        "consistency_errors": consistency_errors,
                    },
                    is_error=True,
                )
        payload = {
            "report_id": report_id,
            "candidate_id": candidate_id,
            "title": args.get("title", ""),
            "body": body,
            "evidence_ids": evidence_ids,
            "audit_id": audit_id,
            "domain_trace_ids": domain_trace_ids,
            "created_at": _now(),
            "review_status": review_status,
        }
        lineage_refs = (
            _open_source_lineage_refs(domain_store, evidence_ids)
            if domain_store is not None
            else []
        )
        domain_proposals: list[DomainWriteProposal] = []
        trace_proposals: list[DomainTraceProposal] = []
        if domain_store is not None:
            candidate = domain_store.candidates[candidate_id]
            candidate_payload = candidate.to_dict()
            candidate_payload["status"] = "demand_report"
            candidate_payload["updated_at"] = _now()
            domain_proposals.append(
                DomainWriteProposal("upsert", "CandidateDemand", candidate_payload)
            )
            trace_proposals.append(
                DomainTraceProposal(
                    event_type="candidate_updated",
                    target_type="CandidateDemand",
                    target_id=candidate_id,
                    payload_summary=f"candidate promoted to demand_report {candidate_id}",
                    input_refs=evidence_ids,
                    output_refs=[candidate_id],
                    payload={"decision": "demand_report"},
                )
            )
        domain_proposals.append(DomainWriteProposal("append", "DemandReport", payload))
        trace_proposals.append(
            DomainTraceProposal(
                event_type="report_consistency_checked",
                target_type="DemandReport",
                target_id=report_id,
                payload_summary=f"report consistency checked {report_id}",
                input_refs=[
                    candidate_id,
                    audit_id,
                    *evidence_ids,
                    *lineage_refs,
                    *([report_context_bundle_id] if report_context_bundle_id else []),
                ],
                output_refs=[report_id],
                payload={
                    "report_context_bundle_id": report_context_bundle_id,
                    "review_status": review_status,
                    "result": "passed",
                },
            )
        )
        trace_proposals.append(
            DomainTraceProposal(
                event_type="report_generated",
                target_type="DemandReport",
                target_id=report_id,
                payload_summary=f"report generated {report_id}",
                input_refs=_dedupe_refs([candidate_id, audit_id, *evidence_ids, *lineage_refs]),
                output_refs=[report_id],
            )
        )
        return ToolResult(
            call.id,
            call.name,
            f"generated demand report {report_id}",
            {"report_id": report_id, "candidate_id": candidate_id},
            domain_proposals=domain_proposals,
            trace_proposals=trace_proposals,
        )

    return ToolDefinition(
        "generate_demand_report",
        "Generate a demand report.",
        _object_schema(
            required=["report_id", "candidate_id", "audit_id", "evidence_ids"],
            properties={
                "report_id": _string("Stable demand report id."),
                "candidate_id": _string("Candidate id covered by the report."),
                "title": _string("Report title."),
                "body": _string("Report body."),
                "sections": _report_sections_schema(),
                "demand_type": {
                    "type": "string",
                    "enum": sorted(VALID_DEMAND_TYPES),
                    "description": (
                        "Use explicit only when a source directly states the "
                        "same demand; otherwise use inferred."
                    ),
                },
                "related_technical_directions": _string_array(
                    "Related technical directions."
                ),
                "solution_clues": _string_array("Solution clues."),
                "evidence_ids": _string_array("Evidence ids cited by the report."),
                "audit_id": _string("Audit report id."),
                "domain_trace_ids": _string_array("Domain trace ids to cite."),
                "report_context_bundle_id": _string(
                    "Verified ReportContextBundle id used by the reporter."
                ),
                "review_status": _string("Review status from ReportContextBundle."),
            },
        ),
        execute,
        execution_mode="sequential",
    )


def _open_source_lineage_refs(store: DomainStore, evidence_ids: list[str]) -> list[str]:
    refs: list[str] = []
    for evidence_id in evidence_ids:
        evidence = store.evidence.get(evidence_id)
        if evidence is None:
            continue
        source = store.sources.get(evidence.source_id)
        if source is None or not source.open_source_lead_id:
            continue
        refs.append(source.open_source_lead_id)
        lead = store.open_source_leads.get(source.open_source_lead_id)
        if lead is not None:
            refs.append(lead.plan_id)
        if evidence.source_quality_assessment_id:
            refs.append(evidence.source_quality_assessment_id)
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        text = str(ref).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_quality_assessment_for_lead(
    domain_store: DomainStore,
    lead_id: str,
) -> SourceQualityAssessment | None:
    assessments = [
        item
        for item in domain_store.source_quality_assessments.values()
        if item.lead_id == lead_id
    ]
    if not assessments:
        return None
    return max(assessments, key=lambda item: item.created_at)


def _report_sections_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(REQUIRED_SECTIONS),
        "properties": {
            section: _string(f"Required report section: {section}.")
            for section in REQUIRED_SECTIONS
        },
        "additionalProperties": False,
        "description": "Structured report sections with exact snake_case keys.",
    }


def _object_schema(
    required: list[str],
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required),
        "properties": dict(properties),
        "additionalProperties": False,
    }


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _string_array(description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": description,
    }


def _audit_tool_description(rubric: AuditRubric | None) -> str:
    if rubric is None:
        return "Run an audit and append an audit report."
    return (
        "Run an audit and append an audit report. The scorecard object must "
        "include every rubric item id: "
        f"{', '.join(rubric.item_ids)}."
    )


def _scorecard_schema(rubric: AuditRubric | None) -> dict[str, Any]:
    if rubric is None:
        return {"type": "object", "additionalProperties": True}
    row_schema = {
        "type": "object",
        "required": ["verdict", "reason"],
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["pass", "doubt", "fail"],
                "description": "Rubric item verdict.",
            },
            "reason": _string("Brief reason grounded in traceable evidence."),
        },
        "additionalProperties": False,
    }
    evidence_review_schema = {
        "type": "object",
        "required": [
            "support_level",
            "support_type",
            "used_for_core",
            "reason",
            "missing_link",
        ],
        "properties": {
            "evidence_id": _string(
                "Optional evidence id; the evidence_reviews object key is authoritative."
            ),
            "support_level": {
                "type": "string",
                "enum": [
                    "direct",
                    "partial",
                    "adjacent",
                    "weak",
                    "irrelevant",
                    "unassessed",
                ],
                "description": "Semantic support strength for this EvidenceCard.",
            },
            "support_type": {
                "type": "string",
                "enum": [
                    "explicit_demand",
                    "inferred_gap",
                    "context_only",
                    "counter_evidence",
                    "irrelevant",
                ],
                "description": "How this EvidenceCard is used in the audit.",
            },
            "used_for_core": {
                "type": "boolean",
                "description": "True only when the evidence supports the core conclusion.",
            },
            "reason": _string("One sentence grounded in the excerpt/source location."),
            "missing_link": _string(
                "Empty when no link is missing; otherwise name the missing inference or evidence."
            ),
        },
        "additionalProperties": False,
    }
    evidence_support_schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["pass", "doubt", "fail"]},
            "reason": {"type": "string"},
            "evidence_reviews": {
                "type": "object",
                "additionalProperties": evidence_review_schema,
                "description": (
                    "Object map keyed by evidence_id. Do not use an array; "
                    "each value must be an evidence review object."
                ),
            },
            "recommended_report_status": {
                "type": "string",
                "enum": ["review_ready", "needs_revision", "watchlist", "rejected"],
                "description": "Auditor recommendation for downstream report gate status.",
            },
            "status_reason": _string(
                "Reason for the recommended downstream report status."
            ),
            "recheck_conditions": _string_array(
                "Concrete conditions that would justify rechecking a watchlist report."
            ),
        },
        "required": [
            "verdict",
            "reason",
            "evidence_reviews",
            "recommended_report_status",
            "status_reason",
            "recheck_conditions",
        ],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "required": list(rubric.item_ids),
        "properties": {
            **{item_id: row_schema for item_id in rubric.item_ids},
            "evidence_support": evidence_support_schema,
        },
        "additionalProperties": True,
        "description": "Structured audit rubric scorecard.",
    }


def _audit_input_refs(domain_store: DomainStore | None, candidate_id: str) -> list[str]:
    if domain_store is None:
        return [candidate_id]
    refs = [candidate_id]
    candidate = domain_store.candidates[candidate_id]
    for evidence_id in candidate.evidence_ids:
        refs.append(evidence_id)
        evidence = domain_store.evidence.get(evidence_id)
        if evidence is not None and evidence.source_quality_assessment_id:
            refs.append(evidence.source_quality_assessment_id)
    return refs


def _reviewed_evidence_update_proposals(
    domain_store: DomainStore,
    *,
    candidate_id: str,
    audit_id: str,
    scorecard: dict[str, Any],
) -> tuple[list[DomainWriteProposal], list[DomainTraceProposal]]:
    candidate = domain_store.candidates[candidate_id]
    reviews = evidence_reviews_from_scorecard(scorecard)
    proposals: list[DomainWriteProposal] = []
    traces: list[DomainTraceProposal] = []
    for evidence_id in candidate.evidence_ids:
        evidence = domain_store.evidence.get(evidence_id)
        review = reviews.get(evidence_id)
        if evidence is None or review is None:
            continue
        reviewed_level = normalize_support_level(review.get("support_level"))
        if evidence.evidence_assessment == reviewed_level:
            continue
        payload = evidence.to_dict()
        payload["evidence_assessment"] = reviewed_level
        proposals.append(DomainWriteProposal("upsert", "EvidenceCard", payload))
        traces.append(
            DomainTraceProposal(
                event_type="evidence_updated",
                target_type="EvidenceCard",
                target_id=evidence_id,
                payload_summary=f"audit {audit_id} reviewed evidence {evidence_id}",
                input_refs=[audit_id, evidence_id],
                output_refs=[evidence_id],
                payload={
                    "audit_id": audit_id,
                    "support_level": reviewed_level,
                    "support_type": str(review.get("support_type", "")),
                },
            )
        )
    return proposals, traces


def _audit_conflict_message(
    audit_id: str,
    *,
    existing_candidate_id: str,
    existing_conclusion: str,
    candidate_id: str,
    conclusion: str,
) -> str | None:
    if existing_candidate_id != candidate_id:
        return (
            f"audit_id {audit_id} already exists for candidate "
            f"{existing_candidate_id}; create a new audit_id for revised audits"
        )
    if existing_conclusion.strip().lower() != conclusion.strip().lower():
        return (
            f"audit_id {audit_id} already exists with conclusion "
            f"{existing_conclusion}; create a new audit_id for revised audits"
        )
    return None
