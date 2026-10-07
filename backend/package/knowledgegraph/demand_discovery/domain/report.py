"""Demand report skeleton validation and markdown rendering."""

from __future__ import annotations

from typing import Any

from knowledgegraph.demand_discovery.domain.evidence_support import (
    core_conclusion_support_status,
    core_evidence_review_levels,
    evidence_reviews_from_scorecard,
    recommended_report_status_from_scorecard,
    review_ready_scorecard_errors,
    watchlist_scorecard_errors,
    validate_evidence_support_scorecard,
)
from knowledgegraph.demand_discovery.domain.evidence_quality import (
    evidence_has_strong_or_direct_support,
)
from knowledgegraph.demand_discovery.domain.models import AuditReport, DemandReport
from knowledgegraph.demand_discovery.domain.judgement import JudgementReport


REQUIRED_SECTIONS = [
    "core_conclusion",
    "task_scenario",
    "threat_or_environment",
    "capability_gap",
    "existing_solutions_and_residual_gaps",
    "counter_evidence_and_limits",
    "risks_and_constraints",
    "open_questions",
    "next_steps",
]

VALID_DEMAND_TYPES = {"explicit", "inferred"}


def validate_report_sections(sections: dict[str, Any], demand_type: str) -> None:
    for section in REQUIRED_SECTIONS:
        value = sections.get(section)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing required report section: {section}")
    if demand_type not in VALID_DEMAND_TYPES:
        raise ValueError(f"invalid demand_type: {demand_type}")


def render_report_sections(
    store: Any,
    *,
    title: str,
    sections: dict[str, Any],
    demand_type: str,
    evidence_ids: list[str],
    related_technical_directions: list[str] | None = None,
    solution_clues: list[str] | None = None,
) -> str:
    validate_report_sections(sections, demand_type)
    lines = [f"# {title}".strip(), "", f"Demand type: {demand_type}", ""]
    for section in REQUIRED_SECTIONS:
        lines.extend([f"## {section}", str(sections[section]).strip(), ""])
    if related_technical_directions:
        lines.extend(
            [
                "## related_technical_directions",
                _bullet_lines(related_technical_directions),
                "",
            ]
        )
    if solution_clues:
        lines.extend(["## solution_clues", _bullet_lines(solution_clues), ""])
    lines.extend(_supporting_evidence_lines(store, evidence_ids))
    lines.extend(_source_audit_lines(store, evidence_ids))
    return "\n".join(lines).strip()


def render_demand_report(store: Any, report: DemandReport) -> str:
    lines = [report.body.strip()]
    lines.extend(["", *_supporting_evidence_lines(store, report.evidence_ids)])
    lines.extend(_source_audit_lines(store, report.evidence_ids))
    return "\n".join(line for line in lines if line is not None).strip()


def validate_autonomous_report_gate(
    store: Any,
    *,
    candidate_id: str,
    audit_id: str,
    evidence_ids: list[str],
    judgement_id: str,
    review_status: str = "review_ready",
) -> None:
    judgements = getattr(store, "judgement_reports", {})
    judgement = judgements.get(judgement_id)
    if judgement is None:
        raise ValueError(f"JudgementReport is required before autonomous report: {judgement_id}")
    if judgement.stop_or_continue != "stop":
        raise ValueError("stopped JudgementReport is required before autonomous report")
    store.validate_demand_report_reference_gate(
        candidate_id,
        audit_id,
        evidence_ids,
        require_minimum_supported_evidence=review_status == "review_ready",
    )
    audit = getattr(store, "audit_reports", {}).get(audit_id)
    if audit is None:
        raise ValueError(f"AuditReport is required before autonomous report: {audit_id}")
    if review_status == "review_ready":
        semantic_errors = review_ready_scorecard_errors(
            audit.scorecard,
            evidence_ids=list(evidence_ids),
            evidence_map=_evidence_map(store, evidence_ids),
        )
    elif review_status == "watchlist":
        semantic_errors = watchlist_scorecard_errors(
            audit.scorecard,
            evidence_ids=list(evidence_ids),
        )
        if audit.conclusion.strip().lower() not in {"approved", "pass", "通过"}:
            semantic_errors.append("watchlist requires approved audit conclusion")
    else:
        semantic_errors = validate_evidence_support_scorecard(
            audit.scorecard,
            evidence_ids=list(evidence_ids),
        )
    if semantic_errors:
        if review_status == "review_ready":
            raise ValueError(
                "review_ready audit requires evidence_support semantic review: "
                + "; ".join(semantic_errors)
            )
        if review_status == "watchlist":
            raise ValueError(
                "watchlist audit requires structured evidence_support disposition: "
                + "; ".join(semantic_errors)
            )
        if not audit.comments and not audit.required_rework:
            raise ValueError(
                "downgraded report requires audit comments or required_rework: "
                + "; ".join(semantic_errors)
            )
    if review_status == "review_ready":
        store.validate_demand_report_gate(candidate_id, audit_id, evidence_ids)


def determine_autonomous_report_review_status(
    judgement: JudgementReport,
    *,
    audit: AuditReport | None = None,
    store: Any | None = None,
    evidence_ids: list[str] | None = None,
) -> str:
    status = "review_ready"
    if judgement.contradictions:
        resolved = {
            str(item)
            for item in judgement.next_round_plan.get("resolved_contradictions", [])
        }
        unresolved = [
            item
            for item in judgement.contradictions
            if item.text not in resolved
        ]
        if unresolved:
            status = "needs_revision"
    if audit is None:
        return status
    conclusion = audit.conclusion.strip().lower()
    if conclusion not in {"approved", "pass", "通过"}:
        return "rejected" if conclusion == "rejected" else "needs_revision"
    checked_evidence_ids = list(evidence_ids or [])
    recommended_status = recommended_report_status_from_scorecard(audit.scorecard)
    if recommended_status == "rejected":
        return "rejected"
    if recommended_status == "needs_revision":
        return "needs_revision"
    if recommended_status == "watchlist":
        watchlist_errors = watchlist_scorecard_errors(
            audit.scorecard,
            evidence_ids=checked_evidence_ids,
        )
        core_levels = core_evidence_review_levels(
            audit.scorecard,
            evidence_ids=checked_evidence_ids,
        )
        if any(level == "irrelevant" for level in core_levels.values()):
            return "rejected"
        if watchlist_errors:
            return "needs_revision"
        return "watchlist"
    errors = validate_evidence_support_scorecard(
        audit.scorecard,
        evidence_ids=checked_evidence_ids,
    )
    if errors:
        return "needs_revision"
    ready_errors = review_ready_scorecard_errors(
        audit.scorecard,
        evidence_ids=checked_evidence_ids,
        evidence_map=_evidence_map(store, checked_evidence_ids),
    )
    if ready_errors:
        return "needs_revision"
    reviews = evidence_reviews_from_scorecard(audit.scorecard)
    support_status = core_conclusion_support_status(
        [
            {**reviews[evidence_id], "evidence_id": evidence_id}
            for evidence_id in checked_evidence_ids
            if evidence_id in reviews
        ],
        evidence_map=_evidence_map(store, checked_evidence_ids),
    )
    if support_status in {"unsupported", "unassessed"}:
        return "needs_revision"
    return status


def _legacy_validate_autonomous_report_gate(
    store: Any,
    *,
    candidate_id: str,
    audit_id: str,
    evidence_ids: list[str],
    judgement: JudgementReport,
) -> None:
    if not any(
        _evidence_from_body(store, evidence_id)
        for evidence_id in evidence_ids
    ):
        raise ValueError(
            "autonomous report requires at least one EvidenceCard from an "
            "article body or downloaded document body"
        )
    if not any(
        evidence_has_strong_or_direct_support(
            store,
            evidence_id,
            evidence_strength_map=judgement.evidence_strength_map,
        )
        for evidence_id in evidence_ids
    ):
        raise ValueError(
            "autonomous report requires at least one strong or direct "
            "EvidenceCard support"
        )


def _supporting_evidence_lines(store: Any, evidence_ids: list[str]) -> list[str]:
    lines = ["## Supporting Evidence"]
    for evidence_id in evidence_ids:
        evidence = getattr(store, "evidence", {}).get(evidence_id)
        if evidence is None:
            lines.append(f"- {evidence_id}: <missing evidence>")
            continue
        excerpt = f" Excerpt: {evidence.excerpt}" if evidence.excerpt else ""
        location = f" Location: {evidence.source_location}" if evidence.source_location else ""
        lines.append(
            f"- {evidence.evidence_id}: {evidence.claim} "
            f"({evidence.evidence_assessment}).{excerpt}{location}"
        )
    lines.append("")
    return lines


def _evidence_map(store: Any | None, evidence_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if store is None:
        return rows
    for evidence_id in evidence_ids:
        evidence = getattr(store, "evidence", {}).get(evidence_id)
        if evidence is not None:
            rows[evidence_id] = {
                "source_id": evidence.source_id,
                "source_location": evidence.source_location,
            }
    return rows


def _source_audit_lines(store: Any, evidence_ids: list[str]) -> list[str]:
    lines = ["## Source Audit"]
    seen_source_ids: set[str] = set()
    for evidence_id in evidence_ids:
        evidence = getattr(store, "evidence", {}).get(evidence_id)
        if evidence is None or evidence.source_id in seen_source_ids:
            continue
        seen_source_ids.add(evidence.source_id)
        source = getattr(store, "sources", {}).get(evidence.source_id)
        if source is None:
            lines.append(f"- {evidence.source_id}: <missing source>")
            continue
        published = source.publish_time.isoformat() if source.publish_time else ""
        lines.append(
            f"- {source.source_id}: {source.source_name} | {source.title} | "
            f"tier={source.source_tier} | time={published} | {source.url_or_path}"
        )
    lines.append("")
    return lines


def _evidence_from_body(store: Any, evidence_id: str) -> bool:
    evidence = getattr(store, "evidence", {}).get(evidence_id)
    if evidence is None:
        return False
    source = getattr(store, "sources", {}).get(evidence.source_id)
    if source is None:
        return False
    if source.collection_decision == "use_as_background":
        return False
    location = str(evidence.source_location or "")
    return "#para:" in location or location.startswith("pdf:") or location.startswith("text:")


def _bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)
