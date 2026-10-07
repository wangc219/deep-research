"""Publish gated demand reports into human and machine-facing artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from knowledgegraph.demand_discovery.domain.models import DemandReport
from knowledgegraph.demand_discovery.domain.store import DomainStore


@dataclass(frozen=True)
class PublishedReport:
    report_md_path: Path
    manifest_path: Path


def publish_report(
    store: DomainStore,
    *,
    report_id: str,
    output_dir: Path,
    report_context_bundle_id: str = "",
) -> PublishedReport:
    report = store.demand_reports[report_id]
    output_dir.mkdir(parents=True, exist_ok=True)
    report_md_path = output_dir / "report.md"
    manifest_path = output_dir / "report_manifest.json"
    report_md_path.write_text(_human_report_markdown(report), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            _manifest(report, report_context_bundle_id),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return PublishedReport(report_md_path=report_md_path, manifest_path=manifest_path)


def _human_report_markdown(report: DemandReport) -> str:
    body = report.body.strip()
    if body.startswith("#"):
        return body + "\n"
    title = report.title.strip()
    if title:
        return f"# {title}\n\n{body}\n"
    return body + "\n"


def _manifest(
    report: DemandReport,
    report_context_bundle_id: str,
) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "candidate_id": report.candidate_id,
        "audit_id": report.audit_id,
        "report_context_bundle_id": report_context_bundle_id,
        "review_status": report.review_status,
        "evidence_ids": list(report.evidence_ids),
        "domain_trace_ids": list(report.domain_trace_ids),
        "created_at": report.created_at.isoformat(),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "sensitive_review_required": report.sensitive_review_required,
    }
