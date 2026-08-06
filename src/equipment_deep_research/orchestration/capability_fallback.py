"""Evidence-bounded S6 recovery for deadline finalization.

Recovery is deliberately agent-led: it may normalize only equipment
directions already authored by a query-aware Codex agent.  It never creates a
local fallback portfolio or substitutes a fixed catalogue of weapon families.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from equipment_deep_research.orchestration.capability_portrait import (
    build_agent_led_capability_portrait,
)


def build_deadline_weapon_directions(
    *,
    topic: str,
    evidence_ids: Sequence[str] = (),
    evidence_index: Sequence[Mapping[str, Any]] = (),
    confidence: float = 0.62,
    gap_basis: str = "",
    candidate_directions: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Normalize upstream Codex candidates without inventing a portfolio.

    A deadline or malformed S6 response is not permission to substitute a
    fixed weapon catalogue.  When no query-aware candidate exists, recovery
    returns an empty list so orchestration can re-run reasoning or fail closed.
    """

    query = " ".join(str(topic or "").split())
    evidence = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
    authored_rows = [
        dict(item) for item in candidate_directions if isinstance(item, Mapping)
    ]
    recovered: list[dict[str, Any]] = []
    for position, source in enumerate(authored_rows[:12], start=1):
        name = str(source.get("name") or source.get("title") or "").strip()
        equipment_form = str(
            source.get("equipment_form")
            or source.get("primary_equipment_identity")
            or ""
        ).strip()
        if not name or not equipment_form:
            continue

        row = dict(source)
        row["name"] = name
        row["equipment_form"] = equipment_form
        row["primary_equipment_identity"] = str(
            source.get("primary_equipment_identity") or equipment_form
        ).strip()
        row["priority"] = str(source.get("priority") or f"P{position}")
        row["type"] = str(source.get("type") or "new_capability")
        try:
            source_confidence = float(source.get("confidence", confidence) or confidence)
        except (TypeError, ValueError):
            source_confidence = confidence
        row["confidence"] = max(0.0, min(1.0, source_confidence))

        direct_refs = [
            str(item)
            for item in source.get(
                "direct_evidence_refs", source.get("evidence_ids", [])
            )
            if str(item).strip()
        ]
        row["direct_evidence_refs"] = list(dict.fromkeys(direct_refs))[:3]
        row["evidence_ids"] = list(
            dict.fromkeys([*row["direct_evidence_refs"], *evidence])
        )[:12]

        if not str(row.get("capability_portrait", "")).strip():
            row["capability_portrait"] = build_agent_led_capability_portrait(
                name=name,
                scenario=row.get("target_scenario", query),
                problem=row.get("problem_statement")
                or row.get("capability_gap")
                or gap_basis,
                principle=row.get("scientific_principle")
                or row.get("depth_mechanism")
                or row.get("novelty", ""),
                technologies=row.get("enabling_technologies", []),
                operational_concept=row.get("operational_concept")
                or row.get("operational_mechanism", ""),
                operational_steps=row.get("operational_process")
                or row.get("mechanism_chain", []),
                capability=row.get("capability_outcome") or row.get("function", ""),
                effect=row.get("military_value")
                or row.get("combat_effect_uplift", ""),
                winning_mechanism=row.get("winning_mechanism")
                or row.get("depth_mechanism", ""),
                equipment_form=equipment_form,
                baseline=row.get("baseline_system", ""),
                failure_boundary=row.get("failure_boundary")
                or row.get("failure_boundaries", []),
            )
        recovered.append(row)
    return recovered
