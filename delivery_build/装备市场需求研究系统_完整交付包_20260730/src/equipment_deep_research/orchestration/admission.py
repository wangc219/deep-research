"""Claim extraction and packet admission for Harness v2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Literal, Mapping, Sequence

from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard


ClaimKind = Literal["fact", "inference", "hypothesis"]
AdmissionStatus = Literal["accepted", "limited", "rejected"]


@dataclass(frozen=True)
class ClaimBundleItem:
    claim_id: str
    text: str
    claim_type: ClaimKind
    parent_background_ids: tuple[str, ...] = ()
    parent_scenario_ids: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    downstream_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimBundle:
    bundle_id: str
    packet_id: str
    claims: tuple[ClaimBundleItem, ...]
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PacketAdmissionDecision:
    packet_id: str
    status: AdmissionStatus
    scores: dict[str, float]
    reasons: tuple[str, ...]
    accepted_claim_ids: tuple[str, ...]
    rejected_claim_ids: tuple[str, ...]
    incremental_value: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PacketAdmissionGate:
    """Deterministic admission gate; never invents evidence or upgrades claims."""

    def __init__(self, *, accepted_threshold: float = 0.68, limited_threshold: float = 0.48) -> None:
        self.accepted_threshold = accepted_threshold
        self.limited_threshold = limited_threshold

    def extract_claim_bundle(
        self,
        packet: BaselineFindingPacket,
        evidence: Mapping[str, EvidenceCard],
        *,
        downstream_targets: Sequence[str] = (),
    ) -> ClaimBundle:
        urls = tuple(
            dict.fromkeys(
                card.source_url
                for evidence_id in packet.evidence_ids
                if (card := evidence.get(evidence_id)) is not None
                and card.source_url.startswith(("http://", "https://"))
            )
        )
        evidence_ids = tuple(
            evidence_id for evidence_id in packet.evidence_ids if evidence_id in evidence
        )
        claims: list[ClaimBundleItem] = []
        for position, finding in enumerate(packet.findings):
            text = str(finding).strip()
            if not text:
                continue
            claim_id = (
                packet.claim_ids[position]
                if position < len(packet.claim_ids) and packet.claim_ids[position]
                else "claim-" + sha256(f"{packet.packet_id}:{text}".encode()).hexdigest()[:12]
            )
            claims.append(
                ClaimBundleItem(
                    claim_id=claim_id,
                    text=text,
                    claim_type=_infer_claim_type(text),
                    source_urls=urls,
                    evidence_ids=evidence_ids,
                    counter_evidence=tuple(packet.limitations[:3]),
                    confidence=max(0.0, min(1.0, float(packet.confidence))),
                    downstream_targets=tuple(str(item) for item in downstream_targets),
                )
            )
        bundle_id = "claims-" + sha256(packet.packet_id.encode()).hexdigest()[:12]
        return ClaimBundle(bundle_id=bundle_id, packet_id=packet.packet_id, claims=tuple(claims))

    def evaluate(
        self,
        packet: BaselineFindingPacket,
        bundle: ClaimBundle,
        evidence: Mapping[str, EvidenceCard],
        *,
        task_terms: Sequence[str] = (),
        accepted_claim_texts: Sequence[str] = (),
        upstream_required: bool = False,
    ) -> PacketAdmissionDecision:
        normalized_topic = packet.topic_focus.lower()
        relevant_terms = [str(item).lower() for item in task_terms if str(item).strip()]
        relevance = (
            sum(term in normalized_topic or any(term in claim.text.lower() for claim in bundle.claims) for term in relevant_terms)
            / len(relevant_terms)
            if relevant_terms
            else (1.0 if bundle.claims else 0.0)
        )
        evidence_rows = [
            evidence[item]
            for item in packet.evidence_ids
            if item in evidence
        ]
        public_rows = [
            item for item in evidence_rows if item.source_url.startswith(("http://", "https://"))
        ]
        source_quality = (
            sum(_source_quality(item.source_tier) for item in public_rows) / len(public_rows)
            if public_rows
            else 0.0
        )
        claim_evidence_match = (
            sum(
                bool(
                    item.source_urls
                    and item.evidence_ids
                    and all(evidence_id in evidence for evidence_id in item.evidence_ids)
                )
                for item in bundle.claims
            )
            / len(bundle.claims)
            if bundle.claims
            else 0.0
        )
        upstream_acceptance = 1.0
        if upstream_required:
            upstream = packet.analysis_sections.get("upstream_synthesis", {})
            upstream_acceptance = 1.0 if isinstance(upstream, Mapping) and upstream.get("consumed_agents") else 0.0
        prior = {str(item).strip().lower() for item in accepted_claim_texts if str(item).strip()}
        incremental_value = (
            sum(claim.text.strip().lower() not in prior for claim in bundle.claims) / len(bundle.claims)
            if bundle.claims
            else 0.0
        )
        scores = {
            "task_relevance": round(relevance, 4),
            "source_quality": round(source_quality, 4),
            "claim_evidence_match": round(claim_evidence_match, 4),
            "upstream_acceptance": round(upstream_acceptance, 4),
            "incremental_value": round(incremental_value, 4),
        }
        score = (
            0.25 * relevance
            + 0.25 * source_quality
            + 0.25 * claim_evidence_match
            + 0.15 * upstream_acceptance
            + 0.10 * incremental_value
        )
        if score >= self.accepted_threshold and bundle.claims:
            status: AdmissionStatus = "accepted"
        elif score >= self.limited_threshold and bundle.claims:
            status = "limited"
        else:
            status = "rejected"
        reasons: list[str] = []
        if relevance < 0.5:
            reasons.append("task_relevance_low")
        if source_quality < 0.5:
            reasons.append("public_source_quality_low")
        if claim_evidence_match < 0.9:
            reasons.append("claim_evidence_binding_incomplete")
        if upstream_required and upstream_acceptance == 0:
            reasons.append("upstream_handoff_not_consumed")
        if incremental_value < 0.25:
            reasons.append("incremental_value_low")
        accepted_ids = tuple(item.claim_id for item in bundle.claims) if status != "rejected" else ()
        rejected_ids = tuple(item.claim_id for item in bundle.claims) if status == "rejected" else ()
        return PacketAdmissionDecision(
            packet_id=packet.packet_id,
            status=status,
            scores=scores,
            reasons=tuple(reasons),
            accepted_claim_ids=accepted_ids,
            rejected_claim_ids=rejected_ids,
            incremental_value=round(incremental_value, 4),
        )


def _infer_claim_type(text: str) -> ClaimKind:
    lowered = text.lower()
    if any(marker in lowered for marker in ("假设", "可能", "或将", "预计", "若")):
        return "hypothesis"
    if any(marker in lowered for marker in ("推断", "表明", "意味着", "因此", "牵引")):
        return "inference"
    return "fact"


def _source_quality(tier: str) -> float:
    return {"A": 1.0, "B": 0.8, "C": 0.55, "D": 0.3}.get(str(tier).upper(), 0.4)


__all__ = [
    "ClaimBundle",
    "ClaimBundleItem",
    "PacketAdmissionDecision",
    "PacketAdmissionGate",
]
