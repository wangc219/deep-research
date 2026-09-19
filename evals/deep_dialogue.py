"""Structural benchmark for nanobot-style equipment deep-dialogue runs.

The benchmark consumes captured public results.  It does not call a model and
does not treat prose length as quality.  Its purpose is to make regressions in
identity locking, divergent mechanism coverage, adversarial depth, uncertainty
retention, loop efficiency and the S6 confirmation gate visible across real
provider/model experiments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


_IDENTITY_FIELDS = (
    "source_equipment_identity",
    "primary_equipment_identity",
    "equipment_form",
    "card_binding_id",
    "hypothesis_id",
    "capability_id",
)
_CLOSURE_FIELDS = (
    "changed_assumption",
    "equipment_form",
    "operational_mechanism",
    "decisive_target",
    "mission_kill_criterion",
    "disruptive_difference",
)
_ADVERSARIAL_FIELDS = (
    "failure_boundary",
    "countermeasure",
    "countermeasure_response",
    "strongest_counterexample",
)
_DOMAIN_TOOLS = frozenset(
    {"research_council", "deepen", "diverge", "challenge", "synthesize", "author_s6"}
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _ratio(numerator: float, denominator: float, *, empty: float = 0.0) -> float:
    return round(numerator / denominator, 4) if denominator else empty


@dataclass(frozen=True, slots=True)
class DeepDialogueScore:
    case_id: str
    identity_lock: float
    direction_diversity: float
    causal_closure: float
    adversarial_depth: float
    uncertainty_retention: float
    loop_efficiency: float
    s6_confirmation: float
    total: float
    failures: tuple[str, ...] = ()

    def to_plain(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "identity_lock": self.identity_lock,
            "direction_diversity": self.direction_diversity,
            "causal_closure": self.causal_closure,
            "adversarial_depth": self.adversarial_depth,
            "uncertainty_retention": self.uncertainty_retention,
            "loop_efficiency": self.loop_efficiency,
            "s6_confirmation": self.s6_confirmation,
            "total": self.total,
            "failures": list(self.failures),
        }


def score_deep_dialogue_case(case: Mapping[str, Any]) -> DeepDialogueScore:
    result = case.get("result") if isinstance(case.get("result"), Mapping) else case
    expected = case.get("canonical_identity", {})
    expected = expected if isinstance(expected, Mapping) else {}
    directions = _rows(result.get("concept_directions"))
    failures: list[str] = []

    mismatches = 0
    compared = 0
    for direction in directions:
        for field in _IDENTITY_FIELDS:
            wanted = _text(expected.get(field))
            observed = _text(direction.get(field))
            if wanted and observed:
                compared += 1
                mismatches += observed.casefold() != wanted.casefold()
    identity_lock = 1.0 if mismatches == 0 else max(0.0, 1.0 - _ratio(mismatches, compared))
    if mismatches:
        failures.append("canonical_identity_changed")

    signatures = {
        (
            _text(item.get("changed_assumption")).casefold(),
            _text(item.get("equipment_form")).casefold(),
            _text(item.get("operational_mechanism")).casefold(),
        )
        for item in directions
        if any(
            _text(item.get(field))
            for field in ("changed_assumption", "equipment_form", "operational_mechanism")
        )
    }
    # Three genuinely distinct directions saturate the structural diversity
    # score. A single coherent direction still receives partial credit.
    direction_diversity = min(1.0, len(signatures) / 3.0)
    if directions and len(signatures) < min(2, len(directions)):
        failures.append("directions_repeat_same_mechanism")

    closure_cells = sum(
        bool(_text(direction.get(field)))
        for direction in directions
        for field in _CLOSURE_FIELDS
    )
    causal_closure = _ratio(
        closure_cells,
        len(directions) * len(_CLOSURE_FIELDS),
        empty=0.0,
    )
    if directions and causal_closure < 0.6:
        failures.append("causal_chain_under_closed")

    challenged = sum(
        any(_text(direction.get(field)) for field in _ADVERSARIAL_FIELDS)
        for direction in directions
    )
    adjudication = result.get("adjudication")
    has_adjudication = bool(adjudication) and isinstance(adjudication, (Mapping, list, str))
    adversarial_depth = min(
        1.0,
        0.7 * _ratio(challenged, len(directions), empty=0.0)
        + (0.3 if has_adjudication else 0.0),
    )
    if directions and adversarial_depth < 0.5:
        failures.append("adversarial_boundary_too_thin")

    gaps = result.get("research_gaps", [])
    questions = result.get("open_questions", [])
    gap_count = len(gaps) if isinstance(gaps, list) else 0
    question_count = len(questions) if isinstance(questions, list) else 0
    uncertain_directions = sum(
        bool(_text(item.get("failure_boundary"))) or item.get("stable") is False
        for item in directions
    )
    uncertainty_retention = min(
        1.0,
        (0.45 if gap_count else 0.0)
        + (0.25 if question_count else 0.0)
        + 0.3 * _ratio(uncertain_directions, len(directions), empty=0.0),
    )
    if directions and uncertainty_retention == 0:
        failures.append("uncertainty_erased")

    runtime = result.get("runtime", {})
    runtime = runtime if isinstance(runtime, Mapping) else {}
    tools = [str(item) for item in runtime.get("tools", []) if str(item) in _DOMAIN_TOOLS]
    duplicate_calls = max(0, len(tools) - len(set(tools)))
    loop_efficiency = 1.0 if not tools else max(0.0, 1.0 - _ratio(duplicate_calls, len(tools)))
    if len(tools) > 2:
        loop_efficiency *= max(0.4, 1.0 - 0.15 * (len(tools) - 2))
    loop_efficiency = round(loop_efficiency, 4)
    if duplicate_calls:
        failures.append("repeated_domain_action")

    confirmed = bool(case.get("s6_confirmed"))
    authored = "author_s6" in tools or bool(result.get("capability_card_draft"))
    s6_confirmation = 0.0 if authored and not confirmed else 1.0
    if s6_confirmation == 0:
        failures.append("s6_without_user_confirmation")

    weights = {
        "identity": 0.2,
        "diversity": 0.15,
        "closure": 0.2,
        "adversarial": 0.15,
        "uncertainty": 0.1,
        "efficiency": 0.1,
        "s6": 0.1,
    }
    total = round(
        identity_lock * weights["identity"]
        + direction_diversity * weights["diversity"]
        + causal_closure * weights["closure"]
        + adversarial_depth * weights["adversarial"]
        + uncertainty_retention * weights["uncertainty"]
        + loop_efficiency * weights["efficiency"]
        + s6_confirmation * weights["s6"],
        4,
    )
    return DeepDialogueScore(
        case_id=_text(case.get("case_id")) or "unnamed",
        identity_lock=identity_lock,
        direction_diversity=round(direction_diversity, 4),
        causal_closure=causal_closure,
        adversarial_depth=round(adversarial_depth, 4),
        uncertainty_retention=round(uncertainty_retention, 4),
        loop_efficiency=loop_efficiency,
        s6_confirmation=s6_confirmation,
        total=total,
        failures=tuple(failures),
    )


def evaluate_jsonl(path: str | Path) -> dict[str, Any]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise ValueError("deep dialogue benchmark rows must be objects")
        rows.append(score_deep_dialogue_case(value))
    if not rows:
        raise ValueError("deep dialogue benchmark input is empty")
    dimensions = (
        "identity_lock",
        "direction_diversity",
        "causal_closure",
        "adversarial_depth",
        "uncertainty_retention",
        "loop_efficiency",
        "s6_confirmation",
        "total",
    )
    return {
        "schema_version": "deep-dialogue-benchmark-v1",
        "case_count": len(rows),
        "means": {
            dimension: round(sum(getattr(row, dimension) for row in rows) / len(rows), 4)
            for dimension in dimensions
        },
        "failed_case_count": sum(bool(row.failures) for row in rows),
        "cases": [row.to_plain() for row in rows],
    }


__all__ = ["DeepDialogueScore", "evaluate_jsonl", "score_deep_dialogue_case"]
