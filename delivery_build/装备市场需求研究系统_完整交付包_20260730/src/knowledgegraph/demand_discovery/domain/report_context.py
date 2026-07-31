"""Report context bundle for autonomous demand-discovery reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


REPORT_USE_VALUES = {
    "core",
    "support",
    "background",
    "limitation",
    "open_question",
    "exclude",
}
MATERIAL_TYPES = {
    "evidence",
    "source",
    "lead",
    "artifact_window",
    "worker_report",
    "judgement",
    "audit",
    "trace_event",
}
REVIEW_STATUSES = {
    "draft",
    "review_ready",
    "needs_revision",
    "approved",
    "rejected",
    "watchlist",
}


@dataclass
class ReportContextMaterial(SerializableDataclass):
    material_id: str
    material_type: str
    title: str
    summary: str
    refs: dict[str, list[str]]
    window_text: str
    source_location: str
    allowed_report_uses: list[str]
    risk_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.material_type not in MATERIAL_TYPES:
            raise ValueError(f"unknown material_type: {self.material_type}")
        for value in self.allowed_report_uses:
            if value not in REPORT_USE_VALUES:
                raise ValueError(f"unknown allowed_report_use: {value}")
        _reject_raw_html(self.window_text)


@dataclass
class CuratedReportItem(SerializableDataclass):
    item_id: str
    material_ids: list[str]
    report_use: str
    claim_summary: str
    curation_reason: str
    required_caveat: str = ""
    excluded_reason: str = ""

    def __post_init__(self) -> None:
        if self.report_use not in REPORT_USE_VALUES:
            raise ValueError(f"unknown report_use: {self.report_use}")
        if not self.material_ids:
            raise ValueError("CuratedReportItem requires material_ids")
        if not self.curation_reason.strip():
            raise ValueError("CuratedReportItem requires curation_reason")
        if self.report_use == "exclude" and not self.excluded_reason.strip():
            raise ValueError("excluded item requires excluded_reason")


@dataclass
class ReportContextBundle(SerializableDataclass):
    bundle_id: str
    run_id: str
    topic: str
    candidate_id: str
    judgement_id: str
    audit_id: str
    review_status: str
    control_brief: dict[str, Any]
    lineage_trace: list[dict[str, Any]]
    materials: list[ReportContextMaterial]
    curated_items: list[CuratedReportItem]
    verifier_warnings: list[str]
    allowed_evidence_ids: list[str]
    blocked_claims: list[str]
    required_caveats: list[str]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"unknown report context review_status: {self.review_status}")
        material_ids = {item.material_id for item in self.materials}
        for item in self.curated_items:
            missing = [
                material_id
                for material_id in item.material_ids
                if material_id not in material_ids
            ]
            if missing:
                raise ValueError(
                    f"curated item references unknown material_ids: {missing}"
                )


def report_context_bundle_from_dict(data: dict[str, Any]) -> ReportContextBundle:
    return ReportContextBundle(
        bundle_id=str(data["bundle_id"]),
        run_id=str(data.get("run_id", "")),
        topic=str(data.get("topic", "")),
        candidate_id=str(data.get("candidate_id", "")),
        judgement_id=str(data.get("judgement_id", "")),
        audit_id=str(data.get("audit_id", "")),
        review_status=str(data.get("review_status", "needs_revision")),
        control_brief=dict(data.get("control_brief", {})),
        lineage_trace=[dict(item) for item in data.get("lineage_trace", [])],
        materials=[
            report_context_material_from_dict(item)
            for item in data.get("materials", [])
        ],
        curated_items=[
            curated_report_item_from_dict(item)
            for item in data.get("curated_items", [])
        ],
        verifier_warnings=[
            str(item) for item in data.get("verifier_warnings", [])
        ],
        allowed_evidence_ids=[
            str(item) for item in data.get("allowed_evidence_ids", [])
        ],
        blocked_claims=[str(item) for item in data.get("blocked_claims", [])],
        required_caveats=[str(item) for item in data.get("required_caveats", [])],
        created_at=_parse_datetime(data.get("created_at")),
    )


def report_context_material_from_dict(
    data: dict[str, Any],
) -> ReportContextMaterial:
    return ReportContextMaterial(
        material_id=str(data["material_id"]),
        material_type=str(data.get("material_type", "")),
        title=str(data.get("title", "")),
        summary=str(data.get("summary", "")),
        refs={
            str(key): [str(item) for item in value]
            for key, value in dict(data.get("refs", {})).items()
        },
        window_text=str(data.get("window_text", "")),
        source_location=str(data.get("source_location", "")),
        allowed_report_uses=[
            str(item) for item in data.get("allowed_report_uses", [])
        ],
        risk_flags=[str(item) for item in data.get("risk_flags", [])],
    )


def curated_report_item_from_dict(data: dict[str, Any]) -> CuratedReportItem:
    return CuratedReportItem(
        item_id=str(data["item_id"]),
        material_ids=[str(item) for item in data.get("material_ids", [])],
        report_use=str(data.get("report_use", "")),
        claim_summary=str(data.get("claim_summary", "")),
        curation_reason=str(data.get("curation_reason", "")),
        required_caveat=str(data.get("required_caveat", "")),
        excluded_reason=str(data.get("excluded_reason", "")),
    )


def _reject_raw_html(text: str) -> None:
    lower = text.lower()
    if "<html" in lower or "<body" in lower or "</html" in lower or "</body" in lower:
        raise ValueError("ReportContextMaterial window_text must not contain raw HTML")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
