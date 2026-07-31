"""Judge/synthesis domain schema for autonomous research rounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


STOP_OR_CONTINUE = {"stop", "continue", "needs_human_steer"}


@dataclass
class JudgementItem(SerializableDataclass):
    text: str
    worker_report_ids: list[str]
    evidence_ids: list[str] = field(default_factory=list)
    lead_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.worker_report_ids:
            raise ValueError("JudgementItem requires worker_report_ids")


@dataclass
class JudgementReport(SerializableDataclass):
    judgement_id: str
    round_id: str
    consensus_points: list[JudgementItem]
    contradictions: list[JudgementItem]
    partial_coverage: list[JudgementItem]
    unique_insights: list[JudgementItem]
    blind_spots: list[JudgementItem]
    evidence_strength_map: dict[str, str]
    next_round_plan: dict[str, Any]
    stop_or_continue: str
    rationale: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.stop_or_continue not in STOP_OR_CONTINUE:
            raise ValueError(f"unknown stop_or_continue: {self.stop_or_continue}")
        for item in self.consensus_points:
            if not item.evidence_ids and not item.lead_ids:
                raise ValueError("consensus_points require evidence_ids or lead_ids")


def judgement_report_from_dict(data: dict[str, Any]) -> JudgementReport:
    return JudgementReport(
        judgement_id=str(data["judgement_id"]),
        round_id=str(data.get("round_id", "")),
        consensus_points=_items(data.get("consensus_points", [])),
        contradictions=_items(data.get("contradictions", [])),
        partial_coverage=_items(data.get("partial_coverage", [])),
        unique_insights=_items(data.get("unique_insights", [])),
        blind_spots=_items(data.get("blind_spots", [])),
        evidence_strength_map=dict(data.get("evidence_strength_map", {})),
        next_round_plan=dict(data.get("next_round_plan", {})),
        stop_or_continue=str(data.get("stop_or_continue", "continue")),
        rationale=str(data.get("rationale", "")),
        created_at=_parse_datetime(data.get("created_at")),
    )


def _items(values: list[dict[str, Any]]) -> list[JudgementItem]:
    return [
        JudgementItem(
            text=str(item.get("text", "")),
            worker_report_ids=list(item.get("worker_report_ids", [])),
            evidence_ids=list(item.get("evidence_ids", [])),
            lead_ids=list(item.get("lead_ids", [])),
        )
        for item in values
    ]


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
