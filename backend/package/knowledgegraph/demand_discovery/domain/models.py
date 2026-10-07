"""Demand discovery domain dataclasses.

These objects are the durable domain layer used by the demo and future
review/report workflows. Runtime events and provider streams stay in the
harness; these records describe source, evidence, candidate, audit, and report
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class SerializableDataclass:
    """Mixin for stable ``to_dict`` serialization."""

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: _serialize(getattr(self, field.name))
            for field in fields(self)
        }


@dataclass
class SourceRecord(SerializableDataclass):
    source_id: str
    title: str
    source_name: str
    source_tier: str
    source_type: str
    publish_time: datetime | None
    url_or_path: str
    summary_text: str | None
    summary_source: str
    collection_decision: str
    author_or_org: str | None
    is_repost: bool | None
    original_source: str | None
    institutional_stance: str | None
    created_at: datetime
    updated_at: datetime
    open_source_lead_id: str | None = None


@dataclass
class EvidenceCard(SerializableDataclass):
    evidence_id: str
    source_id: str
    claim: str
    evidence_summary: str
    excerpt: str | None
    source_location: str
    evidence_assessment: str
    created_by: str
    created_at: datetime
    source_quality_assessment_id: str | None = None


@dataclass
class CandidateDemand(SerializableDataclass):
    candidate_id: str
    title: str
    demand_statement: str
    status: str
    evidence_ids: list[str]
    open_questions: list[str]
    solution_signals: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    superseded_by: str | None = None
    superseded_reason: str | None = None


@dataclass
class DomainTraceEvent(SerializableDataclass):
    domain_trace_id: str
    trace_id: str
    event_type: str
    actor: str
    target_type: str
    target_id: str
    input_refs: list[str]
    output_refs: list[str]
    summary: str
    decision: str | None
    rationale: str | None
    model: str | None
    prompt_id: str | None
    tool_refs: list[str]
    runtime_event_id: str | None
    created_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport(SerializableDataclass):
    audit_id: str
    candidate_id: str
    conclusion: str
    scorecard: dict[str, Any]
    comments: str
    required_rework: list[str]
    created_by: str
    created_at: datetime


@dataclass
class DemandReport(SerializableDataclass):
    report_id: str
    candidate_id: str
    title: str
    body: str
    evidence_ids: list[str]
    audit_id: str
    domain_trace_ids: list[str]
    created_at: datetime
    review_status: str = "draft"
    sensitive_review_required: bool = False


@dataclass
class HumanReviewRecord(SerializableDataclass):
    review_id: str
    report_id: str
    reviewer: str
    review_time: datetime
    decision: str
    decision_reason: str
    accepted_claims: list[str]
    rejected_claims: list[str]
    requested_changes: list[str]
    notes: str
