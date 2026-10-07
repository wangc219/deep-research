"""Report context indexing, curation verification, and pipeline helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.models import EvidenceCard
from knowledgegraph.demand_discovery.domain.report_context import (
    CuratedReportItem,
    ReportContextBundle,
    ReportContextMaterial,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore


class ArtifactResolver:
    def __init__(self, stores: list[ArtifactStore]) -> None:
        self.stores = list(stores)

    def exists(self, ref: str) -> bool:
        return any(store.exists(ref) for store in self.stores)

    def get_text(self, ref: str) -> str:
        for store in self.stores:
            if store.exists(ref):
                return store.get_text(ref)
        raise KeyError(ref)


@dataclass
class ReportContextCandidatePool:
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
    allowed_evidence_ids: list[str]
    blocked_claims: list[str]
    required_caveats: list[str]


@dataclass(frozen=True)
class ContextVerificationResult:
    ok: bool
    bundle: ReportContextBundle | None
    errors: list[str]
    warnings: list[str]


class ContextIndexer:
    def __init__(
        self,
        store: DomainStore,
        artifacts: ArtifactStore | ArtifactResolver | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts

    def build_candidate_pool(
        self,
        *,
        run_id: str,
        topic: str,
        candidate_id: str,
        judgement_id: str,
        audit_id: str,
        review_status: str,
    ) -> ReportContextCandidatePool:
        candidate = self.store.candidates[candidate_id]
        audit = self.store.audit_reports[audit_id]
        allowed_evidence_ids = _allowed_evidence_ids(audit.scorecard, candidate.evidence_ids)
        blocked_claims = _scorecard_strings(audit.scorecard, "blocked_claims")
        required_caveats = _scorecard_strings(audit.scorecard, "required_caveats")
        required_caveats.extend(str(item) for item in audit.required_rework)
        required_caveats = _dedupe(required_caveats)

        materials: list[ReportContextMaterial] = []
        for evidence_id in candidate.evidence_ids:
            evidence = self.store.evidence.get(evidence_id)
            if evidence is None:
                continue
            materials.append(self._evidence_material(evidence, allowed_evidence_ids))
            source = self.store.sources.get(evidence.source_id)
            if source is not None:
                materials.append(
                    ReportContextMaterial(
                        material_id=f"mat-source-{source.source_id}",
                        material_type="source",
                        title=source.title,
                        summary=source.summary_text or "",
                        refs={"source_ids": [source.source_id]},
                        window_text=source.summary_text or "",
                        source_location=source.url_or_path,
                        allowed_report_uses=["background", "support"],
                        risk_flags=[f"tier:{source.source_tier}"],
                    )
                )

        if judgement_id in self.store.judgement_reports:
            judgement = self.store.judgement_reports[judgement_id]
            materials.append(
                ReportContextMaterial(
                    material_id=f"mat-judgement-{judgement_id}",
                    material_type="judgement",
                    title=f"Judgement {judgement_id}",
                    summary=judgement.rationale,
                    refs={"judgement_ids": [judgement_id]},
                    window_text=judgement.rationale,
                    source_location=f"judgement:{judgement_id}",
                    allowed_report_uses=["support", "limitation"],
                    risk_flags=[],
                )
            )
        materials.append(
            ReportContextMaterial(
                material_id=f"mat-audit-{audit_id}",
                material_type="audit",
                title=f"Audit {audit_id}",
                summary=audit.comments,
                refs={"audit_ids": [audit_id]},
                window_text=audit.comments,
                source_location=f"audit:{audit_id}",
                allowed_report_uses=["support", "limitation"],
                risk_flags=[],
            )
        )

        lineage_trace = [
            event.to_dict()
            for event in self.store.trace_events
            if event.target_id in {candidate_id, judgement_id, audit_id}
            or candidate_id in event.output_refs
            or audit_id in event.output_refs
        ]
        return ReportContextCandidatePool(
            bundle_id=f"rcb-{uuid4().hex[:12]}",
            run_id=run_id,
            topic=topic,
            candidate_id=candidate_id,
            judgement_id=judgement_id,
            audit_id=audit_id,
            review_status=review_status,
            control_brief={
                "topic": topic,
                "candidate_id": candidate_id,
                "judgement_id": judgement_id,
                "audit_id": audit_id,
                "review_status": review_status,
                "required_rework": list(audit.required_rework),
                "audit_comments": audit.comments,
            },
            lineage_trace=lineage_trace,
            materials=materials,
            allowed_evidence_ids=allowed_evidence_ids,
            blocked_claims=blocked_claims,
            required_caveats=required_caveats,
        )

    def _evidence_material(
        self,
        evidence: EvidenceCard,
        allowed_evidence_ids: list[str],
    ) -> ReportContextMaterial:
        return ReportContextMaterial(
            material_id=f"mat-evidence-{evidence.evidence_id}",
            material_type="evidence",
            title=evidence.claim,
            summary=evidence.evidence_summary,
            refs={
                "evidence_ids": [evidence.evidence_id],
                "source_ids": [evidence.source_id],
            },
            window_text=_window_for_evidence(
                self.artifacts,
                evidence.source_location,
                evidence.excerpt or evidence.evidence_summary,
            ),
            source_location=evidence.source_location,
            allowed_report_uses=(
                ["core", "support"]
                if evidence.evidence_id in allowed_evidence_ids
                else ["background", "limitation"]
            ),
            risk_flags=[],
        )


class ContextVerifier:
    def verify(
        self,
        pool: ReportContextCandidatePool,
        *,
        curated_items: list[CuratedReportItem],
    ) -> ContextVerificationResult:
        errors: list[str] = []
        warnings: list[str] = []
        material_map = {item.material_id: item for item in pool.materials}
        for curated in curated_items:
            for material_id in curated.material_ids:
                material = material_map.get(material_id)
                if material is None:
                    errors.append(f"unknown material_id: {material_id}")
                    continue
                if (
                    curated.report_use != "exclude"
                    and curated.report_use not in material.allowed_report_uses
                ):
                    errors.append(
                        f"report_use {curated.report_use} is not allowed for {material_id}"
                    )
                if curated.report_use in {"core", "support"}:
                    evidence_ids = material.refs.get("evidence_ids", [])
                    for evidence_id in evidence_ids:
                        if evidence_id not in pool.allowed_evidence_ids:
                            errors.append(
                                f"evidence_id not allowed for core/support: {evidence_id}"
                            )
        if errors:
            return ContextVerificationResult(False, None, errors, warnings)
        bundle = ReportContextBundle(
            bundle_id=pool.bundle_id,
            run_id=pool.run_id,
            topic=pool.topic,
            candidate_id=pool.candidate_id,
            judgement_id=pool.judgement_id,
            audit_id=pool.audit_id,
            review_status=pool.review_status,
            control_brief=dict(pool.control_brief),
            lineage_trace=list(pool.lineage_trace),
            materials=list(pool.materials),
            curated_items=list(curated_items),
            verifier_warnings=warnings,
            allowed_evidence_ids=list(pool.allowed_evidence_ids),
            blocked_claims=list(pool.blocked_claims),
            required_caveats=list(pool.required_caveats),
            created_at=datetime.now(timezone.utc),
        )
        return ContextVerificationResult(True, bundle, [], warnings)


def _window_for_evidence(
    artifacts: ArtifactStore | ArtifactResolver | None,
    source_location: str,
    fallback: str,
) -> str:
    ref = source_location.split("#", 1)[0]
    if artifacts is not None and ref and artifacts.exists(ref):
        try:
            text = artifacts.get_text(ref)
        except KeyError:
            return fallback
        if "#para:" in source_location:
            try:
                index = int(source_location.rsplit("#para:", 1)[1])
            except ValueError:
                index = -1
            paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
            if 0 <= index < len(paragraphs):
                start = max(index - 1, 0)
                end = min(index + 2, len(paragraphs))
                return "\n\n".join(paragraphs[start:end])
        return text[:4000]
    return fallback


def _allowed_evidence_ids(
    scorecard: dict[str, Any],
    candidate_evidence_ids: list[str],
) -> list[str]:
    evidence_support = scorecard.get("evidence_support")
    if not isinstance(evidence_support, dict):
        return list(candidate_evidence_ids)
    reviews = evidence_support.get("evidence_reviews")
    if not isinstance(reviews, dict):
        return list(candidate_evidence_ids)
    allowed: list[str] = []
    for evidence_id in candidate_evidence_ids:
        review = reviews.get(evidence_id)
        if not isinstance(review, dict):
            continue
        support_level = str(review.get("support_level", "")).lower()
        if support_level in {"direct", "partial", "strong", "moderate"}:
            allowed.append(evidence_id)
    return allowed or list(candidate_evidence_ids)


def _scorecard_strings(scorecard: dict[str, Any], key: str) -> list[str]:
    result: list[str] = []
    for value in scorecard.values():
        if isinstance(value, dict):
            raw = value.get(key)
            if isinstance(raw, list):
                result.extend(str(item) for item in raw)
            elif isinstance(raw, str) and raw:
                result.append(raw)
    return _dedupe(result)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
