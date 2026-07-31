"""Shared endpoint matching helpers for Stage 3 candidate evaluation.

These helpers use candidate edge text plus linked candidate slot aliases. They
are evaluation/governance utilities only; they must not be used as route
candidate generation input.
"""

from __future__ import annotations

from typing import Any


def build_slot_index(slots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(slot.get("candidate_id")): slot
        for slot in slots
        if str(slot.get("candidate_id") or "").strip()
    }


def endpoint_terms(
    candidate_edge: dict[str, Any],
    side: str,
    slot_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    if side not in {"source", "target"}:
        raise ValueError(f"Unsupported endpoint side: {side}")
    terms: list[str] = [str(candidate_edge.get(f"{side}_name", "")).strip()]
    slot = linked_slot(candidate_edge, side, slot_by_id)
    if slot is not None:
        terms.append(str(slot.get("name", "")).strip())
        aliases = slot.get("aliases", [])
        if isinstance(aliases, list):
            terms.extend(str(alias).strip() for alias in aliases)
    return _dedupe_nonempty(terms)


def endpoint_layer(
    candidate_edge: dict[str, Any],
    side: str,
    slot_by_id: dict[str, dict[str, Any]],
) -> str:
    if side not in {"source", "target"}:
        raise ValueError(f"Unsupported endpoint side: {side}")
    slot = linked_slot(candidate_edge, side, slot_by_id)
    if slot is not None and str(slot.get("layer", "")).strip():
        return str(slot.get("layer", "")).strip()
    return str(candidate_edge.get(f"{side}_layer", "")).strip()


def linked_slot(
    candidate_edge: dict[str, Any],
    side: str,
    slot_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_id = str(candidate_edge.get(f"{side}_candidate_id") or "").strip()
    return slot_by_id.get(candidate_id)


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
