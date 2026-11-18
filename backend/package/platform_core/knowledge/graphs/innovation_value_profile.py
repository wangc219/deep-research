"""为军事技术创新候选生成可解释的多维价值剖面。"""

from __future__ import annotations

from typing import Any

INNOVATION_VALUE_PROFILE_VERSION = "defense-innovation-value-profile-v1"

_NOVELTY_MARKERS = (
    "新型",
    "新质",
    "前沿",
    "突破",
    "颠覆",
    "原创",
    "跨域",
    "融合",
    "转化",
    "新机理",
    "新原理",
    "emerging",
    "breakthrough",
    "novel",
)


def build_innovation_value_profile(
    path: dict[str, Any],
    *,
    discovery_mode: str,
    relation_type: str,
) -> dict[str, Any]:
    """依据封闭证据路径计算模式相关、不会写成事实的创新价值剖面。"""
    inspiration = path.get("research_inspiration") or {}
    evidence = path.get("evidence") or {}
    nodes = path.get("nodes") or []
    relations = path.get("relations") or []
    roles = {str(node.get("semantic_role") or "") for node in nodes}
    technology_count = sum(str(node.get("semantic_role") or "") == "technology" for node in nodes)
    relation_confidences = [_relation_confidence(relation) for relation in relations]
    average_confidence = sum(relation_confidences) / len(relation_confidences) if relation_confidences else 0.5
    mention_count = max(int(evidence.get("mention_count") or 0), 0)
    file_count = len({str(value) for value in evidence.get("file_ids") or [] if str(value).strip()})
    role_coverage = _probability(path.get("semantic_coverage"))
    gap_count = len(path.get("evidence_gaps") or [])
    value_dimensions = list(inspiration.get("military_value_dimensions") or [])
    capability_gains = list(inspiration.get("expected_capability_gains") or [])
    application_directions = list(inspiration.get("application_directions") or [])
    applicable_conditions = list(inspiration.get("applicable_conditions") or [])
    value_signals = list(inspiration.get("value_signals") or [])

    evidence_strength = _clamp(
        min(mention_count / 6, 1) * 0.3
        + (1.0 if file_count >= 2 else 0.45) * 0.25
        + role_coverage * 0.2
        + average_confidence * 0.25
        - min(gap_count * 0.06, 0.24)
    )
    military_value = _clamp(
        min(len(value_dimensions) / 3, 1) * 0.4
        + min(len(capability_gains), 2) * 0.12
        + min(len(application_directions), 2) * 0.08
        + (0.1 if "capability" in roles else 0.0)
        + (0.1 if "application" in roles else 0.0)
    )
    novelty_signal_count = sum(
        any(marker in _signal_text(signal).casefold() for marker in _NOVELTY_MARKERS) for signal in value_signals
    )
    route_kind = str(path.get("route_kind") or "")
    novelty = _clamp(
        0.12
        + (0.22 if route_kind in {"combined", "same_layer", "predicted"} else 0.0)
        + (0.2 if technology_count >= 2 else 0.0)
        + (0.16 if file_count >= 2 else 0.0)
        + min(novelty_signal_count, 2) * 0.15
    )
    feasibility = _clamp(
        average_confidence * 0.3
        + evidence_strength * 0.35
        + min(len(applicable_conditions), 2) * 0.1
        + min(len(value_signals), 3) * 0.05
        - min(gap_count * 0.05, 0.2)
    )
    transferability = _clamp(
        (0.25 if {"technology", "application"}.issubset(roles) else 0.0)
        + (0.15 if {"principle", "capability"}.issubset(roles) else 0.0)
        + (0.2 if file_count >= 2 else 0.0)
        + min(len(applicable_conditions), 2) * 0.1
        + (0.2 if relation_type in {"TRANSFERABLE_TO", "COMBINES_WITH"} else 0.0)
    )
    evidence_sufficiency = min(mention_count / 3, 1)
    sparse_signal = 1 - min(mention_count / 12, 1)
    bridge_signal = min(max(len(path.get("relation_ids") or []) - 1, 0) / 3, 1)
    weak_signal_potential = _clamp(
        (novelty * 0.35 + (1.0 if file_count >= 2 else 0.25) * 0.25 + bridge_signal * 0.2 + sparse_signal * 0.2)
        * (0.45 + evidence_sufficiency * 0.55)
    )
    dimensions = {
        "military_value": round(military_value, 4),
        "novelty": round(novelty, 4),
        "feasibility": round(feasibility, 4),
        "transferability": round(transferability, 4),
        "evidence_strength": round(evidence_strength, 4),
        "weak_signal_potential": round(weak_signal_potential, 4),
    }
    weights = _mode_weights(discovery_mode)
    strategic_score = sum(dimensions[name] * weight for name, weight in weights.items())
    return {
        "version": INNOVATION_VALUE_PROFILE_VERSION,
        "mode": discovery_mode,
        "dimensions": dimensions,
        "weights": weights,
        "strategic_score": round(_clamp(strategic_score), 4),
        "priority": _priority(strategic_score, weak_signal_potential, evidence_strength),
        "weak_signal": weak_signal_potential >= 0.5 and evidence_strength >= 0.35,
        "signals": {
            "military_value_dimensions": value_dimensions[:12],
            "cross_document": file_count >= 2,
            "source_document_count": file_count,
            "mention_count": mention_count,
            "novelty_signal_count": novelty_signal_count,
        },
        "advisory_only": True,
    }


def _mode_weights(discovery_mode: str) -> dict[str, float]:
    if discovery_mode == "bottom_up":
        return {
            "military_value": 0.2,
            "novelty": 0.2,
            "feasibility": 0.15,
            "transferability": 0.15,
            "evidence_strength": 0.15,
            "weak_signal_potential": 0.15,
        }
    return {
        "military_value": 0.25,
        "novelty": 0.1,
        "feasibility": 0.2,
        "transferability": 0.15,
        "evidence_strength": 0.2,
        "weak_signal_potential": 0.1,
    }


def _priority(strategic_score: float, weak_signal: float, evidence_strength: float) -> str:
    if strategic_score >= 0.68 and evidence_strength >= 0.45:
        return "priority"
    if weak_signal >= 0.55 and evidence_strength >= 0.35:
        return "weak_signal_watch"
    if strategic_score >= 0.48:
        return "promising"
    return "observe"


def _relation_confidence(relation: dict[str, Any]) -> float:
    properties = relation.get("properties") or {}
    return _probability(properties.get("confidence", relation.get("confidence", 0.5)))


def _signal_text(signal: Any) -> str:
    if isinstance(signal, dict):
        return " ".join(str(signal.get(field) or "") for field in ("label", "text", "entity"))
    return str(signal or "")


def _probability(value: Any) -> float:
    try:
        return _clamp(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
