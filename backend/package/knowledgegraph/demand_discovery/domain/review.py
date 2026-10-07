"""Human review and local push-list helpers for demand reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledgegraph.demand_discovery.domain.models import (
    AuditReport,
    DemandReport,
    HumanReviewRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore


@dataclass(frozen=True)
class PushPlan:
    inbox_path: Path
    watchlist_path: Path


def push_priority(
    report: DemandReport,
    audit: AuditReport | None,
    review: HumanReviewRecord | None,
) -> str:
    if review is None:
        if report.review_status == "review_ready":
            return "hold_for_evidence"
        return "none"
    decision = review.decision.strip().lower()
    if decision == "approved":
        return "immediate"
    if decision == "approved_with_changes":
        return "digest"
    if decision == "needs_revision":
        return "hold_for_evidence"
    if decision == "watchlist":
        return "watch_pool"
    return "none"


def generate_push_lists(store: DomainStore, plan: PushPlan) -> None:
    plan.inbox_path.parent.mkdir(parents=True, exist_ok=True)
    plan.watchlist_path.parent.mkdir(parents=True, exist_ok=True)
    buckets = {
        "immediate": [],
        "digest": [],
        "hold_for_evidence": [],
        "watch_pool": [],
    }
    for report in sorted(store.demand_reports.values(), key=lambda item: item.report_id):
        review = store.latest_human_review(report.report_id)
        audit = store.audit_reports.get(report.audit_id)
        priority = push_priority(report, audit, review)
        if priority in buckets:
            buckets[priority].append(_report_line(report, review))

    plan.inbox_path.write_text(
        "\n".join(
            [
                "# Demand Discovery Push Inbox",
                "",
                "## Immediate",
                *_lines_or_none(buckets["immediate"]),
                "",
                "## Digest",
                *_lines_or_none(buckets["digest"]),
                "",
                "## Hold For Evidence",
                *_lines_or_none(buckets["hold_for_evidence"]),
                "",
            ]
        ),
        encoding="utf-8",
    )
    plan.watchlist_path.write_text(
        "\n".join(
            [
                "# Demand Discovery Watchlist",
                "",
                "## Watch Pool",
                *_lines_or_none(buckets["watch_pool"]),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _report_line(report: DemandReport, review: HumanReviewRecord | None) -> str:
    decision = review.decision if review is not None else "pending"
    sensitive = " sensitive" if report.sensitive_review_required else ""
    return f"- {report.report_id} | {report.title} | {decision}{sensitive}"


def _lines_or_none(lines: list[str]) -> list[str]:
    return lines if lines else ["- none"]
