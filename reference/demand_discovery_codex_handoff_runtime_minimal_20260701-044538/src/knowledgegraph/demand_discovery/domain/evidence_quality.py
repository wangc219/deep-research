"""Shared evidence support checks for autonomous synthesis/report gates."""

from __future__ import annotations

from typing import Any

from knowledgegraph.demand_discovery.domain.evidence_support import normalize_support_level


def evidence_has_strong_or_direct_support(
    store: Any,
    evidence_id: str,
    *,
    evidence_strength_map: dict[str, str] | None = None,
) -> bool:
    evidence = getattr(store, "evidence", {}).get(evidence_id)
    if evidence is None:
        return False
    mapped_strength = None
    if evidence_strength_map is not None and evidence_id in evidence_strength_map:
        mapped_strength = evidence_strength_map[evidence_id]
    if mapped_strength is not None and not _is_strong_or_direct_label(mapped_strength):
        return False
    assessment = str(getattr(evidence, "evidence_assessment", "") or "")
    if assessment:
        return _is_strong_or_direct_label(assessment)
    return mapped_strength is not None and _is_strong_or_direct_label(mapped_strength)


def evidence_can_support_candidate_synthesis(
    store: Any,
    evidence_id: str,
    *,
    evidence_strength_map: dict[str, str] | None = None,
) -> bool:
    evidence = getattr(store, "evidence", {}).get(evidence_id)
    if evidence is None:
        return False
    mapped_strength = None
    if evidence_strength_map is not None and evidence_id in evidence_strength_map:
        mapped_strength = evidence_strength_map[evidence_id]
    if mapped_strength is not None:
        mapped_level = normalize_support_level(mapped_strength)
        if mapped_level not in {"direct", "partial"}:
            return False
    assessment = str(getattr(evidence, "evidence_assessment", "") or "")
    if assessment:
        return normalize_support_level(assessment) in {"direct", "partial"}
    return (
        mapped_strength is not None
        and normalize_support_level(mapped_strength) in {"direct", "partial"}
    )


def _is_strong_or_direct_label(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    first = text
    for separator in (":", "：", "；", ";", "，", ",", "。", ".", "（", "("):
        first = first.split(separator, 1)[0]
    first = first.strip()
    if first in {"strong", "direct"}:
        return True
    if first.startswith("strong ") or first.startswith("direct "):
        return True
    return first in {
        "强",
        "强证据",
        "较强",
        "较强证据",
        "中等偏强",
        "偏强",
        "直接",
        "直接证据",
        "直接支持",
    }
