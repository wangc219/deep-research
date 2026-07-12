"""Evidence acceptance, deduplication, corroboration and conflict retention."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from urllib.parse import urlsplit, urlunsplit

from equipment_deep_research.domain.models import EvidenceCard


@dataclass(frozen=True)
class EvidenceAssessment:
    evidence_id: str
    score: float
    decision: str
    reasons: list[str]
    normalized_url: str
    conflict_group: str | None = None


class EvidenceGovernor:
    def __init__(self, *, minimum_score: float = 0.62, weights: dict[str, float] | None = None) -> None:
        self.minimum_score = minimum_score
        self.weights = weights or {"relevance": .30, "transparency": .15, "freshness": .15, "direct_support": .25, "extraction_quality": .15}

    def assess(self, evidence: EvidenceCard, dimensions: dict[str, float], *, existing: list[EvidenceCard] = ()) -> EvidenceAssessment:
        score = round(sum(self.weights.get(key, 0) * max(0, min(1, value)) for key, value in dimensions.items()), 3)
        normalized = normalize_url(evidence.source_url)
        duplicate = next((item for item in existing if normalize_url(item.source_url) == normalized), None)
        reasons = []
        decision = "accepted" if score >= self.minimum_score else "rejected"
        if duplicate:
            decision = "duplicate"
            reasons.append(f"与 {duplicate.evidence_id} URL 重复")
        if score < self.minimum_score:
            reasons.append(f"质量评分 {score:.2f} 低于阈值 {self.minimum_score:.2f}")
        conflict_group = self._conflict_group(evidence, existing)
        if conflict_group:
            reasons.append("保留为冲突/反证材料")
        return EvidenceAssessment(evidence.evidence_id, score, decision, reasons, normalized, conflict_group)

    @staticmethod
    def _conflict_group(evidence: EvidenceCard, existing: list[EvidenceCard]) -> str | None:
        keywords = set(_terms(evidence.claim))
        for item in existing:
            overlap = keywords & set(_terms(item.claim))
            opposite = any(word in evidence.claim for word in ("不足", "失败", "受限", "不支持")) != any(word in item.claim for word in ("不足", "失败", "受限", "不支持"))
            shared = _shared_phrase(evidence.claim, item.claim)
            if (len(overlap) >= 2 or len(shared) >= 3) and opposite:
                basis = "|".join(sorted(overlap)) or shared
                return "conflict-" + sha256(basis.encode()).hexdigest()[:10]
        return None


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


def _terms(text: str) -> list[str]:
    return [term for term in re.split(r"\W+", text.lower()) if len(term) > 1]


def _shared_phrase(left: str, right: str) -> str:
    """Longest common contiguous phrase, sufficient for concise Chinese claims."""
    best = ""
    for start in range(len(left)):
        for end in range(start + 1, len(left) + 1):
            candidate = left[start:end]
            if len(candidate) > len(best) and candidate in right:
                best = candidate
    return best
