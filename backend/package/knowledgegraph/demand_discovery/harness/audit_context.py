"""Build compact model-facing context for semantic audit workers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from knowledgegraph.demand_discovery.domain.evidence_support import normalize_support_level


@dataclass
class AuditContextBundle:
    candidate: dict[str, Any]
    judgement: dict[str, Any]
    evidence_bundle: list[dict[str, Any]]
    worker_research_summary: list[dict[str, Any]]
    report_core_conclusion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "judgement": self.judgement,
            "evidence_bundle": list(self.evidence_bundle),
            "worker_research_summary": list(self.worker_research_summary),
            "report_core_conclusion": self.report_core_conclusion,
        }

    def render(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def build_audit_context_bundle(
    store: Any,
    *,
    candidate_id: str,
    judgement_id: str,
    report_core_conclusion: str,
    artifact_windows: dict[str, str] | None = None,
) -> AuditContextBundle:
    candidate = store.candidates[candidate_id]
    judgement = store.judgement_reports[judgement_id]
    windows = artifact_windows or {}
    evidence_bundle: list[dict[str, Any]] = []
    for evidence_id in candidate.evidence_ids:
        evidence = store.evidence[evidence_id]
        source = store.sources.get(evidence.source_id)
        source_payload = {}
        if source is not None:
            source_payload = {
                "source_id": source.source_id,
                "source_name": source.source_name,
                "source_tier": source.source_tier,
                "source_type": source.source_type,
                "collection_decision": source.collection_decision,
                "url_or_path": source.url_or_path,
                "open_source_lead_id": source.open_source_lead_id,
            }
        assessment = None
        if evidence.source_quality_assessment_id:
            assessment = getattr(store, "source_quality_assessments", {}).get(
                evidence.source_quality_assessment_id
            )
        open_source_lead_id = getattr(source, "open_source_lead_id", "") or ""
        source_quality_payload = {
            "source_quality_assessment_id": evidence.source_quality_assessment_id or "",
            "quality_level": "missing" if open_source_lead_id else "",
            "reason": (
                "open source evidence lacks SourceQualityAssessment"
                if open_source_lead_id and not evidence.source_quality_assessment_id
                else ""
            ),
            "basis_artifact_refs": [],
            "body_location_refs": [],
            "open_source_lead_id": open_source_lead_id,
        }
        if assessment is not None:
            source_quality_payload = {
                "source_quality_assessment_id": assessment.assessment_id,
                "quality_level": assessment.quality_level,
                "reason": assessment.reason,
                "basis_artifact_refs": list(assessment.basis_artifact_refs),
                "body_location_refs": list(assessment.body_location_refs),
                "open_source_lead_id": assessment.lead_id,
            }
        evidence_bundle.append(
            {
                "evidence_id": evidence.evidence_id,
                "claim": evidence.claim,
                "evidence_summary": evidence.evidence_summary,
                "excerpt": evidence.excerpt,
                "source_location": evidence.source_location,
                "normalized_support_level": normalize_support_level(evidence.evidence_assessment),
                "source": source_payload,
                "source_quality": source_quality_payload,
                "material_window_refs": [
                    key for key in windows if key in evidence.source_location
                ],
            }
        )
    worker_summary = []
    for check in list(getattr(store, "worker_self_checks", {}).values())[-5:]:
        worker_summary.append(
            {
                "assignment_id": check.assignment_id,
                "topic_alignment": check.topic_alignment,
                "follow_up_reason": check.follow_up_reason,
                "discarded_findings": list(check.discarded_findings)[:5],
                "remaining_blind_spots": list(check.remaining_blind_spots)[:5],
            }
        )
    return AuditContextBundle(
        candidate={
            "candidate_id": candidate.candidate_id,
            "title": candidate.title,
            "demand_statement": candidate.demand_statement,
            "evidence_ids": list(candidate.evidence_ids),
            "open_questions": list(candidate.open_questions),
        },
        judgement=judgement.to_dict(),
        evidence_bundle=evidence_bundle,
        worker_research_summary=worker_summary,
        report_core_conclusion=report_core_conclusion,
    )
