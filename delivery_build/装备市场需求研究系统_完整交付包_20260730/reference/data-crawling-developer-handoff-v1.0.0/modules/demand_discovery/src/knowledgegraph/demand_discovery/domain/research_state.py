"""Round-level research state for autonomous demand discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


RESEARCH_LEAD_STATUSES = {
    "discovered",
    "selected",
    "fetched",
    "read",
    "downloaded",
    "skipped",
    "failed",
}
RESEARCH_ROUND_STATUSES = {"planned", "running", "judged", "stopped", "failed"}
PAGE_TYPES = {
    "article",
    "listing",
    "site_home",
    "search_page",
    "download_document",
    "unknown",
}
DOWNLOAD_KINDS = {"none", "pdf", "doc", "docx", "txt", "html_attachment", "unknown"}


@dataclass
class ResearchLead(SerializableDataclass):
    lead_id: str
    round_id: str
    source_name: str
    source_tier: str
    url: str
    title: str
    snippet: str
    page_type: str
    download_kind: str
    relevance_score: float
    importance_score: float
    credibility_score: float
    status: str
    selection_reason: str
    skip_reason: str
    artifact_refs: list[str]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.status not in RESEARCH_LEAD_STATUSES:
            raise ValueError(f"unknown ResearchLead status: {self.status}")
        if self.page_type not in PAGE_TYPES:
            raise ValueError(f"unknown ResearchLead page_type: {self.page_type}")
        if self.download_kind not in DOWNLOAD_KINDS:
            raise ValueError(f"unknown ResearchLead download_kind: {self.download_kind}")


@dataclass
class ReadingQueue(SerializableDataclass):
    queue_id: str
    round_id: str
    topic: str
    lead_ids: list[str]
    selected_lead_ids: list[str]
    skipped_lead_ids: list[str]
    failed_lead_ids: list[str]
    budget_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class ResearchRound(SerializableDataclass):
    round_id: str
    run_id: str
    index: int
    topic: str
    hypothesis: str
    source_strategy_id: str
    worker_report_ids: list[str]
    judgement_id: str | None
    next_round_plan: dict[str, Any]
    stop_reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.status not in RESEARCH_ROUND_STATUSES:
            raise ValueError(f"unknown ResearchRound status: {self.status}")


def research_lead_from_dict(data: dict[str, Any]) -> ResearchLead:
    return ResearchLead(
        lead_id=str(data["lead_id"]),
        round_id=str(data.get("round_id", "")),
        source_name=str(data.get("source_name", "")),
        source_tier=str(data.get("source_tier", "")),
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        snippet=str(data.get("snippet", "")),
        page_type=str(data.get("page_type", "unknown")),
        download_kind=str(data.get("download_kind", "none")),
        relevance_score=float(data.get("relevance_score", 0.0)),
        importance_score=float(data.get("importance_score", 0.0)),
        credibility_score=float(data.get("credibility_score", 0.0)),
        status=str(data.get("status", "discovered")),
        selection_reason=str(data.get("selection_reason", "")),
        skip_reason=str(data.get("skip_reason", "")),
        artifact_refs=list(data.get("artifact_refs", [])),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def reading_queue_from_dict(data: dict[str, Any]) -> ReadingQueue:
    return ReadingQueue(
        queue_id=str(data["queue_id"]),
        round_id=str(data.get("round_id", "")),
        topic=str(data.get("topic", "")),
        lead_ids=list(data.get("lead_ids", [])),
        selected_lead_ids=list(data.get("selected_lead_ids", [])),
        skipped_lead_ids=list(data.get("skipped_lead_ids", [])),
        failed_lead_ids=list(data.get("failed_lead_ids", [])),
        budget_snapshot=dict(data.get("budget_snapshot", {})),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def research_round_from_dict(data: dict[str, Any]) -> ResearchRound:
    return ResearchRound(
        round_id=str(data["round_id"]),
        run_id=str(data.get("run_id", "")),
        index=int(data.get("index", 0)),
        topic=str(data.get("topic", "")),
        hypothesis=str(data.get("hypothesis", "")),
        source_strategy_id=str(data.get("source_strategy_id", "")),
        worker_report_ids=list(data.get("worker_report_ids", [])),
        judgement_id=data.get("judgement_id"),
        next_round_plan=dict(data.get("next_round_plan", {})),
        stop_reason=data.get("stop_reason"),
        status=str(data.get("status", "planned")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
