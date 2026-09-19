"""Card-level confidence calibration for equipment capability images.

The score shown on a capability card is not a portfolio score.  It combines
the model's prior judgement with two card-local questions:

* do the registered evidence and its wording actually fit this equipment's
  target scene and mechanism?
* how far is the card's forward-looking claim from something that can be
  verified or is already evidenced?

The helper is deliberately deterministic so the same artifact is rendered the
same way by the API, the report pipeline and the web client.  It does not
invent facts or use a fixed 58% fallback as a card score.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
import re
from typing import Any


_STATUS_FORESIGHT = {
    "direct_object_baseline": 0.90,
    "analogous_project_evidence": 0.72,
    "component_mechanism_evidence": 0.58,
}


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _items(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = value
    elif value in (None, ""):
        values = []
    else:
        values = [value]
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _tokens(value: Any) -> set[str]:
    """Extract stable Chinese bigrams plus latin/number terms for overlap."""

    text = re.sub(r"\s+", "", str(value or "")).lower()
    tokens: set[str] = set(re.findall(r"[a-z0-9][a-z0-9._/-]*", text))
    for chunk in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
        if len(chunk) >= 3:
            tokens.update(chunk[index : index + 3] for index in range(len(chunk) - 2))
    return {token for token in tokens if len(token) >= 2}


def _overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    # F1 is more stable than intersection/union when the evidence text is a
    # long packet containing several unrelated findings.
    precision = intersection / len(left_tokens)
    recall = intersection / len(right_tokens)
    return (2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def _foresight_score(card: Mapping[str, Any]) -> float:
    status = str(card.get("foresight_evidence_status", "")).strip().lower()
    score = _STATUS_FORESIGHT.get(status, 0.42)
    if str(card.get("future_trigger", "")).strip():
        score += 0.12
    if str(card.get("adversary_adaptation", "")).strip():
        score += 0.05
    verification = _items(card.get("verification_plan") or card.get("validation_plan"))
    if verification:
        score += 0.12
    if str(card.get("development_path", "")).strip():
        score += 0.05
    horizon = str(card.get("horizon", "")).strip().lower()
    score += {"near": 0.04, "mid": 0.01, "long": -0.03}.get(horizon, 0.0)
    return round(max(0.20, min(0.96, score)), 3)


def _stable_spread(card: Mapping[str, Any]) -> float:
    """Return a bounded card-specific spread that remains stable across reloads."""

    identity = "|".join(
        str(card.get(key) or "").strip()
        for key in (
            "capability_id",
            "name",
            "equipment_form",
            "target_scenario",
            "operational_mechanism",
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    unit_interval = int.from_bytes(digest[:4], "big") / ((1 << 32) - 1)
    return round((unit_interval - 0.5) * 0.10, 4)


def calibrate_capability_confidence(
    card: Mapping[str, Any],
    *,
    prior: Any = None,
) -> tuple[float, dict[str, Any]]:
    """Return ``(confidence, components)`` for one capability card.

    Evidence fit is intentionally card-local.  A card with six generic packet
    IDs but no scene/mechanism match cannot receive the same score as a card
    with direct object evidence.  Missing evidence remains a limitation rather
    than being silently replaced with a portfolio average.
    """

    model_prior = _bounded(
        prior if prior not in (None, "") else card.get("confidence"),
        0.58,
    )
    if model_prior == 0.0 and card.get("expert_score") not in (None, ""):
        model_prior = _bounded(card.get("expert_score"), 0.58)

    evidence_ids = _items(card.get("evidence_ids"))
    direct_refs = _items(card.get("direct_evidence_refs"))
    evidence_text = " ".join(
        _items(card.get("evidence_basis"))
        + _items(card.get("evidence_boundary"))
        + _items(card.get("source_winning_logic"))
    )
    anchor_text = " ".join(
        _items(
            [
                card.get("name"),
                card.get("equipment_form"),
                card.get("primary_equipment_identity"),
                card.get("target_scenario"),
                card.get("related_scenario"),
                card.get("problem_statement"),
                card.get("capability_gap"),
                card.get("function"),
                card.get("project_function"),
                card.get("operational_mechanism"),
                card.get("military_utility"),
                card.get("strike_countermeasure_value"),
            ]
        )
    )
    scenario_text = " ".join(
        _items(
            [
                card.get("target_scenario"),
                card.get("related_scenario"),
                card.get("problem_statement"),
                card.get("capability_gap"),
            ]
        )
    )
    text_fit = _overlap(anchor_text, evidence_text)
    scenario_fit = _overlap(scenario_text, evidence_text)
    id_coverage = min(1.0, len(evidence_ids) / 4.0)
    direct_fit = min(1.0, len(direct_refs) / 2.0)
    if evidence_text:
        evidence_fit = (
            0.10
            + 0.16 * id_coverage
            + 0.27 * direct_fit
            + 0.25 * text_fit
            + 0.22 * scenario_fit
        )
    else:
        # IDs without their claim text are traceable, but cannot establish
        # scene fit.  Direct refs still earn limited credit.
        evidence_fit = 0.12 + 0.16 * id_coverage + 0.27 * direct_fit
    evidence_fit = round(max(0.08, min(0.96, evidence_fit)), 3)
    foresight = _foresight_score(card)

    weighted_signal = (
        0.24 * model_prior + 0.52 * evidence_fit + 0.24 * foresight
    )
    stable_spread = _stable_spread(card)
    normalized_signal = max(0.0, min(1.0, (weighted_signal - 0.20) / 0.76))
    confidence = round(
        max(
            0.60,
            min(
                0.80,
                0.60 + 0.20 * normalized_signal + stable_spread,
            ),
        ),
        3,
    )
    components = {
        "model_prior": round(model_prior, 3),
        "evidence_fit": evidence_fit,
        "foresight": foresight,
        "evidence_count": len(evidence_ids),
        "direct_evidence_count": len(direct_refs),
        "scene_match": round(scenario_fit, 3),
        "weighted_signal": round(weighted_signal, 3),
        "stable_spread": stable_spread,
        "calibration": "card_evidence_and_foresight_v2",
    }
    return confidence, components


__all__ = ["calibrate_capability_confidence"]
