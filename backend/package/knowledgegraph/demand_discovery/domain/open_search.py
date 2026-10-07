"""Open-search domain state for demand discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


OPEN_SEARCH_PLAN_STATUSES = {"planned", "running", "completed", "cancelled"}
OPEN_SOURCE_SCOPES = {"open_web"}
OPEN_SOURCE_QUALITY_STATUSES = {"pending", "accepted", "provisional", "background_only", "rejected"}
SOURCE_QUALITY_LEVELS = {"trusted", "usable", "provisional", "background_only", "low_quality", "rejected"}


@dataclass
class OpenSearchPlan(SerializableDataclass):
    plan_id: str
    run_id: str
    round_id: str
    topic: str
    trigger_judgement_id: str
    trigger_reason: str
    queries: list[str]
    allowed_result_count: int
    status: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.status not in OPEN_SEARCH_PLAN_STATUSES:
            raise ValueError(f"unknown OpenSearchPlan status: {self.status}")
        if self.allowed_result_count < 1:
            raise ValueError("OpenSearchPlan allowed_result_count must be positive")


@dataclass
class OpenSourceLead(SerializableDataclass):
    lead_id: str
    plan_id: str
    run_id: str
    round_id: str
    topic: str
    url: str
    domain: str
    title: str
    snippet: str
    source_name_guess: str
    search_query: str
    source_scope: str
    quality_status: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.source_scope not in OPEN_SOURCE_SCOPES:
            raise ValueError(f"unknown OpenSourceLead source_scope: {self.source_scope}")
        if self.quality_status not in OPEN_SOURCE_QUALITY_STATUSES:
            raise ValueError(f"unknown OpenSourceLead quality_status: {self.quality_status}")


@dataclass
class OpenSourceBodyArtifact(SerializableDataclass):
    body_id: str
    lead_id: str
    plan_id: str
    url: str
    final_url: str
    content_type: str
    artifact_ref: str
    simplified_ref: str
    body_location_prefix: str
    fetched_by: str
    created_at: datetime


@dataclass
class SourceQualityAssessment(SerializableDataclass):
    assessment_id: str
    lead_id: str
    url: str
    domain: str
    basis_artifact_refs: list[str]
    body_location_refs: list[str]
    read_document_ref: str
    source_identity: str
    publisher_or_org: str
    author: str
    publish_time: str
    is_original_source: bool | None
    citation_or_reference_signal: str
    content_type: str
    quality_level: str
    risk_flags: list[str]
    reason: str
    created_by: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.quality_level not in SOURCE_QUALITY_LEVELS:
            raise ValueError(f"unknown SourceQualityAssessment quality_level: {self.quality_level}")
        if not self.basis_artifact_refs:
            raise ValueError("SourceQualityAssessment basis_artifact_refs is required")
        if not self.body_location_refs:
            raise ValueError("SourceQualityAssessment body_location_refs is required")


def open_search_plan_from_dict(data: dict[str, Any]) -> OpenSearchPlan:
    return OpenSearchPlan(
        plan_id=str(data["plan_id"]),
        run_id=str(data.get("run_id", "")),
        round_id=str(data.get("round_id", "")),
        topic=str(data.get("topic", "")),
        trigger_judgement_id=str(data.get("trigger_judgement_id", "")),
        trigger_reason=str(data.get("trigger_reason", "")),
        queries=[str(item) for item in data.get("queries", [])],
        allowed_result_count=int(data.get("allowed_result_count", 1)),
        status=str(data.get("status", "planned")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def open_source_lead_from_dict(data: dict[str, Any]) -> OpenSourceLead:
    return OpenSourceLead(
        lead_id=str(data["lead_id"]),
        plan_id=str(data.get("plan_id", "")),
        run_id=str(data.get("run_id", "")),
        round_id=str(data.get("round_id", "")),
        topic=str(data.get("topic", "")),
        url=str(data.get("url", "")),
        domain=str(data.get("domain", "")),
        title=str(data.get("title", "")),
        snippet=str(data.get("snippet", "")),
        source_name_guess=str(data.get("source_name_guess", "")),
        search_query=str(data.get("search_query", "")),
        source_scope=str(data.get("source_scope", "open_web")),
        quality_status=str(data.get("quality_status", "pending")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def open_source_body_artifact_from_dict(data: dict[str, Any]) -> OpenSourceBodyArtifact:
    return OpenSourceBodyArtifact(
        body_id=str(data["body_id"]),
        lead_id=str(data.get("lead_id", "")),
        plan_id=str(data.get("plan_id", "")),
        url=str(data.get("url", "")),
        final_url=str(data.get("final_url", "")),
        content_type=str(data.get("content_type", "")),
        artifact_ref=str(data.get("artifact_ref", "")),
        simplified_ref=str(data.get("simplified_ref", "")),
        body_location_prefix=str(data.get("body_location_prefix", "")),
        fetched_by=str(data.get("fetched_by", "")),
        created_at=_parse_datetime(data.get("created_at")),
    )


def source_quality_assessment_from_dict(data: dict[str, Any]) -> SourceQualityAssessment:
    return SourceQualityAssessment(
        assessment_id=str(data["assessment_id"]),
        lead_id=str(data.get("lead_id", "")),
        url=str(data.get("url", "")),
        domain=str(data.get("domain", "")),
        basis_artifact_refs=[str(item) for item in data.get("basis_artifact_refs", [])],
        body_location_refs=[str(item) for item in data.get("body_location_refs", [])],
        read_document_ref=str(data.get("read_document_ref", "")),
        source_identity=str(data.get("source_identity", "")),
        publisher_or_org=str(data.get("publisher_or_org", "")),
        author=str(data.get("author", "")),
        publish_time=str(data.get("publish_time", "")),
        is_original_source=data.get("is_original_source") if isinstance(data.get("is_original_source"), bool) else None,
        citation_or_reference_signal=str(data.get("citation_or_reference_signal", "")),
        content_type=str(data.get("content_type", "")),
        quality_level=str(data.get("quality_level", "")),
        risk_flags=[str(item) for item in data.get("risk_flags", [])],
        reason=str(data.get("reason", "")),
        created_by=str(data.get("created_by", "")),
        created_at=_parse_datetime(data.get("created_at")),
    )


def quality_level_to_lead_status(quality_level: str) -> str:
    if quality_level in {"trusted", "usable"}:
        return "accepted"
    if quality_level == "provisional":
        return "provisional"
    if quality_level == "background_only":
        return "background_only"
    return "rejected"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
