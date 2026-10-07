"""Consistency gate for reporter-generated autonomous demand reports."""

from __future__ import annotations

from typing import Any


def validate_report_consistency(
    bundle: Any,
    *,
    report_body: str,
    evidence_ids: list[str],
    domain_trace_ids: list[str],
) -> list[str]:
    errors: list[str] = []
    allowed = set(getattr(bundle, "allowed_evidence_ids", []))
    for evidence_id in evidence_ids:
        if evidence_id not in allowed:
            errors.append(f"evidence_id not allowed by ReportContextBundle: {evidence_id}")
    for claim in list(getattr(bundle, "blocked_claims", []) or []):
        if claim and claim in report_body:
            errors.append(f"blocked claim appears in report body: {claim}")
    for caveat in list(getattr(bundle, "required_caveats", []) or []):
        if caveat and caveat not in report_body:
            errors.append(f"required caveat missing from report body: {caveat}")

    lineage_types = {
        str(row.get("event_type", ""))
        for row in list(getattr(bundle, "lineage_trace", []) or [])
        if isinstance(row, dict)
    }
    if {"candidate_synthesized", "audit_completed"} - lineage_types:
        errors.append(
            "ReportContextBundle lineage missing candidate_synthesized or audit_completed"
        )
    required_trace_ids = {
        str(row.get("domain_trace_id", ""))
        for row in list(getattr(bundle, "lineage_trace", []) or [])
        if isinstance(row, dict)
        and row.get("event_type") in {"candidate_synthesized", "audit_completed"}
        and row.get("domain_trace_id")
    }
    if required_trace_ids and not required_trace_ids.issubset(set(domain_trace_ids)):
        errors.append("domain_trace_ids must include candidate_synthesis and audit lineage")
    return errors
