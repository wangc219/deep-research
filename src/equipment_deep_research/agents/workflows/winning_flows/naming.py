"""Portfolio-level naming-style allocation for the six S3/S4 seats.

The creative model remains responsible for inventing the actual Chinese
equipment name.  This module only allocates *which naming perspective* should
lead each candidate.  Allocation is deterministic for a run/portfolio seed,
independent of input ordering, and balanced across the six creative seats.

Historically each seat sampled A--O independently.  That made a replay stable
for one seat, but did not prevent all six seats from choosing the same small
set of naming perspectives.  The portfolio allocator below first gives the
first candidate of each seat a different expression family, then fills later
candidate positions from a bounded multiset (all fifteen styles once, plus at
most one repeat of any style).  It is deliberately free of lexical rules: it
does not generate, rewrite, or score names.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from hashlib import sha256
from typing import Any

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
    load_dynamic_winning_prompt,
)


def _load_naming_types() -> tuple[dict[str, str], ...]:
    """Load the reviewed A–O naming catalog from the shared Markdown resource."""

    value = load_dynamic_winning_json("common", section="s3_s4.naming_types")
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ValueError(
            "dynamic resource section must be a JSON object list: s3_s4.naming_types"
        )
    return tuple(
        {str(key): str(item_value) for key, item_value in item.items()}
        for item in value
    )


# Keep the historical public constant and aliases while making common.md the
# single source of model-facing naming guidance.
S3_S4_WEAPON_NAMING_TYPES: tuple[dict[str, str], ...] = _load_naming_types()

# A broad expression-family grouping is used only for the first candidate of
# each seat.  It prevents six first names from all being, for example,
# two-character codenames or generic mission descriptions while still leaving
# the model free to choose the actual words.  The groups are intentionally
# coarse and non-prescriptive; later positions may use any remaining style.
NAMING_EXPRESSION_FAMILY_BY_CODE: dict[str, str] = {
    "A": "physical_form",
    "B": "science_principle",
    "C": "identity_metaphor",
    "D": "mission_capability",
    "E": "mission_capability",
    "F": "combat_mechanism",
    "G": "science_principle",
    "H": "battlespace_time",
    "I": "mission_capability",
    "J": "battlespace_time",
    "K": "combat_mechanism",
    "L": "identity_metaphor",
    "M": "scale_economy",
    "N": "scale_economy",
    "O": "scale_economy",
}

NAMING_EXPRESSION_FAMILIES: tuple[str, ...] = (
    "physical_form",
    "science_principle",
    "identity_metaphor",
    "mission_capability",
    "combat_mechanism",
    "battlespace_time",
    "scale_economy",
)

MAX_S3_S4_SEATS = 6

# Public aliases make the module easy to adopt from code that used either the
# old constant name or a more descriptive one.
NAMING_TYPES = S3_S4_WEAPON_NAMING_TYPES
S3_S4_NAMING_TYPES = S3_S4_WEAPON_NAMING_TYPES

# Stable audit identifier for the portfolio allocation contract.
NAMING_ASSIGNMENT_VERSION = "s3_s4_portfolio_balanced_v1"

_TYPE_BY_CODE = {item["code"]: item for item in S3_S4_WEAPON_NAMING_TYPES}
_GROUPS_FOR_SIX_SEATS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("physical_form", ("A",)),
    ("science_principle", ("B", "G")),
    ("identity_metaphor", ("C", "L")),
    ("mission_capability", ("D", "E", "I")),
    ("combat_mechanism", ("F", "K")),
    ("battlespace_time", ("H", "J")),
    ("scale_economy", ("M", "N", "O")),
)


def _digest(seed: str, *parts: object) -> bytes:
    material = "|".join((str(seed), *(str(part) for part in parts)))
    return sha256(material.encode("utf-8")).digest()


def _ranked(values: Iterable[str], seed: str, *parts: object) -> list[str]:
    """Return a deterministic pseudo-random ordering without Python hash()."""

    return sorted(
        (str(value) for value in values),
        key=lambda value: (_digest(seed, *parts, value), value),
    )


def _normalize_seat_keys(seat_keys: Sequence[str] | Mapping[str, Any]) -> list[str]:
    if isinstance(seat_keys, Mapping):
        raw_keys = list(seat_keys.keys())
    elif isinstance(seat_keys, (str, bytes)):
        raw_keys = [seat_keys.decode() if isinstance(seat_keys, bytes) else seat_keys]
    else:
        raw_keys = list(seat_keys)
    normalized = [str(value).strip() for value in raw_keys]
    if any(not value for value in normalized):
        raise ValueError("seat_keys must not contain empty values")
    if len(set(normalized)) != len(normalized):
        raise ValueError("seat_keys must be unique")
    if not normalized:
        raise ValueError("at least one S3/S4 seat key is required")
    if len(normalized) > MAX_S3_S4_SEATS:
        raise ValueError(
            "portfolio allocator supports at most six S3/S4 seat keys; "
            "use a separate portfolio seed for a larger swarm"
        )
    return normalized


def _bounded_candidate_count(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("candidates_per_seat must be an integer") from exc
    if count < 1:
        raise ValueError("candidates_per_seat must be at least 1")
    return count


def _first_candidate_codes(seed: str, seats: Sequence[str]) -> dict[str, str]:
    """Assign unique expression families/codes to the first seat position.

    For the normal six-seat graph this uses six different broad families.  If
    a caller supplies more than seven seats, families necessarily repeat; the
    code is still rotated deterministically and never repeats within a seat.
    """

    seat_order = _ranked(seats, seed, "seat-order")
    family_order = _ranked(
        (name for name, _codes in _GROUPS_FOR_SIX_SEATS),
        seed,
        "first-candidate-family-order",
    )
    groups = dict(_GROUPS_FOR_SIX_SEATS)
    result: dict[str, str] = {}
    for index, seat in enumerate(seat_order):
        family = family_order[index % len(family_order)]
        code_order = _ranked(groups[family], seed, "first-candidate-code", family)
        result[seat] = code_order[index // len(family_order) % len(code_order)]
    return result


def _target_counts(
    seed: str,
    seats: Sequence[str],
    candidates_per_seat: int,
    primary_codes: Mapping[str, str],
) -> dict[str, int]:
    """Build a balanced style multiset for all candidate slots.

    Every style is used once whenever the portfolio has at least fifteen
    slots.  Additional slots are deterministic repeats, with a hard maximum
    count of two per style.  Smaller portfolios use each selected style once.
    """

    total_slots = len(seats) * candidates_per_seat
    if total_slots > len(S3_S4_WEAPON_NAMING_TYPES) * 2:
        raise ValueError(
            "the balanced allocator supports at most 30 total candidate slots"
        )
    ordered_codes = _ranked(_TYPE_BY_CODE, seed, "portfolio-style-order")
    primary_set = set(primary_codes.values())
    counts = {code: 0 for code in _TYPE_BY_CODE}
    for code in primary_codes.values():
        counts[code] += 1

    if total_slots <= len(S3_S4_WEAPON_NAMING_TYPES):
        needed = total_slots - len(primary_codes)
        for code in ordered_codes:
            if needed <= 0:
                break
            if counts[code] == 0:
                counts[code] = 1
                needed -= 1
        return counts

    # First cover all fifteen styles, then distribute the surplus as repeats.
    for code in ordered_codes:
        if counts[code] == 0:
            counts[code] = 1
    surplus = total_slots - len(S3_S4_WEAPON_NAMING_TYPES)
    repeat_order = _ranked(
        _TYPE_BY_CODE,
        seed,
        "portfolio-repeat-order",
        ",".join(sorted(primary_set)),
    )
    for code in repeat_order:
        if surplus <= 0:
            break
        if counts[code] < 2:
            counts[code] += 1
            surplus -= 1
    if surplus:
        # This can only happen when the caller asks for >30 slots, guarded
        # above, but keep the invariant explicit for future table changes.
        raise ValueError("unable to satisfy the per-style maximum of two")
    return counts


def _assign_remaining_codes(
    seed: str,
    seats: Sequence[str],
    candidates_per_seat: int,
    primary_codes: Mapping[str, str],
    target_counts: Mapping[str, int],
) -> dict[str, list[str]]:
    """Assign positions 2..N with deterministic constraint backtracking."""

    if candidates_per_seat == 1:
        return {seat: [] for seat in seats}

    # Keep the stable seat order for tie-breaking, while returning results in
    # the caller's (possibly different) order.
    stable_seats = _ranked(seats, seed, "seat-order")
    slots = [
        (seat, position)
        for position in range(1, candidates_per_seat)
        for seat in stable_seats
    ]
    # ``target_counts`` describes the complete portfolio, including the
    # already assigned first candidate.  Consume those primary occurrences
    # before filling positions 2..N; otherwise the search would silently
    # overproduce a primary style and leave another style uncovered.
    primary_counts = Counter(primary_codes.values())
    remaining = {
        code: int(count) - int(primary_counts.get(code, 0))
        for code, count in target_counts.items()
    }
    if any(count < 0 for count in remaining.values()):
        raise ValueError("target style counts cannot be lower than primary assignments")
    used_by_seat = {seat: {primary_codes[seat]} for seat in seats}
    assigned: dict[tuple[str, int], str] = {}

    def candidates_for(slot: tuple[str, int]) -> list[str]:
        seat, position = slot
        candidates = [
            code
            for code, count in remaining.items()
            if count > 0 and code not in used_by_seat[seat]
        ]
        return _ranked(candidates, seed, "slot", seat, position)

    def choose_slot(unfilled: Sequence[tuple[str, int]]) -> tuple[tuple[str, int], list[str]]:
        ranked_slots: list[tuple[int, int, tuple[str, int], list[str]]] = []
        for slot in unfilled:
            options = candidates_for(slot)
            seat, position = slot
            ranked_slots.append(
                (
                    len(options),
                    position,
                    slot,
                    options,
                )
            )
        if not ranked_slots:
            raise RuntimeError("no unfilled naming slots")
        ranked_slots.sort(
            key=lambda row: (
                row[0],
                row[1],
                _digest(seed, "slot-tie", row[2][0], row[2][1]),
            )
        )
        _count, _position, slot, options = ranked_slots[0]
        return slot, options

    # Six seats x three candidates yields only twelve non-primary slots, so a
    # small depth-first search is cheap and gives an exact guarantee instead
    # of relying on a greedy repair heuristic.
    def visit(unfilled: list[tuple[str, int]]) -> bool:
        if not unfilled:
            return True
        slot, options = choose_slot(unfilled)
        if not options:
            return False
        seat, _position = slot
        next_unfilled = [item for item in unfilled if item != slot]
        for code in options:
            remaining[code] -= 1
            used_by_seat[seat].add(code)
            assigned[slot] = code
            if visit(next_unfilled):
                return True
            assigned.pop(slot, None)
            used_by_seat[seat].remove(code)
            remaining[code] += 1
        return False

    if not visit(list(slots)):
        raise ValueError(
            "unable to assign balanced naming styles without repeating a style "
            "within one seat"
        )
    return {
        seat: [assigned[(seat, position)] for position in range(1, candidates_per_seat)]
        for seat in seats
    }


def _record(code: str, *, position: int, seat: str, seed_digest: str) -> dict[str, str | int]:
    item = _TYPE_BY_CODE[code]
    record: dict[str, str | int] = {
        "candidate_position": position,
        "code": code,
        "label": item["label"],
        "focus": item["focus"],
        "expression_family": NAMING_EXPRESSION_FAMILY_BY_CODE[code],
        "portfolio_slot": f"{seat}:{position}",
        "assignment_version": "s3_s4_portfolio_balanced_v1",
        "seed_digest": seed_digest,
    }
    for key in (
        "naming_core",
        "keywords",
        "example",
        "naming_question",
        "name_format",
    ):
        value = str(item.get(key, "") or "").strip()
        if value:
            record[key] = value
    return record


def allocate_s3_s4_naming_assignments(
    seed: str,
    seat_keys: Sequence[str] | Mapping[str, Any],
    *,
    candidates_per_seat: int = 3,
) -> dict[str, dict[str, Any]]:
    """Allocate naming styles for a portfolio of S3/S4 creative seats.

    Parameters
    ----------
    seed:
        Stable run/graph seed.  Include the run id and graph id when possible;
        do not use Python's process-randomized ``hash``.
    seat_keys:
        Stable seat identifiers (for example ``agent-s3-1``).  Results are
        keyed by these identifiers and do not depend on their input order.
    candidates_per_seat:
        Number of candidate positions each seat may author.  The dynamic
        swarm normally uses three.

    Returns
    -------
    dict
        One assignment record per seat.  ``candidate_order`` is ordered by
        candidate position and is directly suitable for a prompt handoff.
    """

    normalized_seed = str(seed)
    seats = _normalize_seat_keys(seat_keys)
    count = _bounded_candidate_count(candidates_per_seat)
    primary_codes = _first_candidate_codes(normalized_seed, seats)
    target_counts = _target_counts(normalized_seed, seats, count, primary_codes)
    remaining_codes = _assign_remaining_codes(
        normalized_seed,
        seats,
        count,
        primary_codes,
        target_counts,
    )
    seed_digest = sha256(normalized_seed.encode("utf-8")).hexdigest()[:16]
    assignment_metadata = load_dynamic_winning_json(
        "common", section="s3_s4.naming_assignment_metadata"
    )
    application_rule = load_dynamic_winning_prompt(
        "common", section="s3_s4.naming_assignment_application"
    )
    if not isinstance(assignment_metadata, Mapping):
        assignment_metadata = {}
    assignments: dict[str, dict[str, Any]] = {}
    # Canonical insertion order makes persisted JSON/checkpoints identical
    # even when callers enumerate the same seat set differently.
    for seat in _ranked(seats, normalized_seed, "seat-order"):
        codes = [primary_codes[seat], *remaining_codes[seat]]
        assignments[seat] = {
            "seat_key": seat,
            "assignment_version": "s3_s4_portfolio_balanced_v1",
            # Preserve the legacy field/value consumed by existing prompt and
            # provider tests.  ``allocation_mode`` carries the stronger
            # portfolio-level semantics without breaking old readers.
            "selection_mode": "random_without_replacement",
            "allocation_mode": "portfolio_deterministic_balanced",
            "candidate_order": [
                _record(
                    code,
                    position=position,
                    seat=seat,
                    seed_digest=seed_digest,
                )
                for position, code in enumerate(codes, start=1)
            ],
            "first_candidate_expression_family": NAMING_EXPRESSION_FAMILY_BY_CODE[
                codes[0]
            ],
            "name_length": str(assignment_metadata.get("name_length", "")),
            "application_rule": application_rule,
        }
    return assignments


def build_s3_s4_naming_plan(
    seed: str,
    seat_keys: Sequence[str] | Mapping[str, Any],
    *,
    candidates_per_seat: int = 3,
) -> dict[str, Any]:
    """Return assignments plus auditable portfolio-level balance metadata."""

    normalized_seed = str(seed)
    assignments = allocate_s3_s4_naming_assignments(
        seed,
        seat_keys,
        candidates_per_seat=candidates_per_seat,
    )
    all_rows = [
        row
        for assignment in assignments.values()
        for row in assignment["candidate_order"]
    ]
    counts: dict[str, int] = {}
    for row in all_rows:
        code = str(row["code"])
        counts[code] = counts.get(code, 0) + 1
    # Derive aggregate metadata from the allocator's stable seat order, not
    # mapping insertion order.  This keeps a serialized checkpoint byte-for-
    # byte equivalent when a caller supplies the same seats in another order.
    stable_seat_order = _ranked(assignments.keys(), normalized_seed, "seat-order")
    first_rows = [
        assignments[seat]["candidate_order"][0] for seat in stable_seat_order
    ]
    first_families = [str(row["expression_family"]) for row in first_rows]
    return {
        "assignment_version": "s3_s4_portfolio_balanced_v1",
        "selection_mode": "random_without_replacement",
        "allocation_mode": "portfolio_deterministic_balanced",
        "seed_digest": sha256(normalized_seed.encode("utf-8")).hexdigest()[:16],
        "seat_order": stable_seat_order,
        "candidate_count_per_seat": int(candidates_per_seat),
        "assignments": assignments,
        "portfolio_stats": {
            "seat_count": len(assignments),
            "slot_count": len(all_rows),
            "style_counts": dict(sorted(counts.items())),
            "styles_covered": sorted(counts),
            "max_style_frequency": max(counts.values(), default=0),
            "first_candidate_codes": [str(row["code"]) for row in first_rows],
            "first_candidate_families": first_families,
            "first_candidate_family_count": len(set(first_families)),
        },
    }


def assign_s3_s4_naming_types(seed: str, *, count: int = 3) -> list[dict[str, str]]:
    """Backward-compatible single-seat sampler.

    The old helper returned only a list of style records.  This wrapper keeps
    that shape while using the new deterministic allocator, so callers can
    migrate without changing prompt code.  A single seat can request up to
    all fifteen styles, matching the historical helper; the dynamic six-seat
    path should use :func:`allocate_s3_s4_naming_assignments` instead.
    """

    bounded_count = max(1, min(int(count), len(S3_S4_WEAPON_NAMING_TYPES)))
    assignment = allocate_s3_s4_naming_assignments(
        seed,
        ["single-seat"],
        candidates_per_seat=bounded_count,
    )["single-seat"]
    return [
        {
            key: value
            for key, value in row.items()
            if key in {"code", "label", "focus"}
        }
        for row in assignment["candidate_order"]
    ]


# Compatibility aliases with names likely used by integrations.
portfolio_s3_s4_naming_assignments = allocate_s3_s4_naming_assignments
balanced_s3_s4_naming_plan = build_s3_s4_naming_plan
single_seat_naming_assignment = assign_s3_s4_naming_types


__all__ = [
    "MAX_S3_S4_SEATS",
    "NAMING_ASSIGNMENT_VERSION",
    "NAMING_EXPRESSION_FAMILIES",
    "NAMING_EXPRESSION_FAMILY_BY_CODE",
    "NAMING_TYPES",
    "S3_S4_NAMING_TYPES",
    "S3_S4_WEAPON_NAMING_TYPES",
    "allocate_s3_s4_naming_assignments",
    "assign_s3_s4_naming_types",
    "balanced_s3_s4_naming_plan",
    "build_s3_s4_naming_plan",
    "portfolio_s3_s4_naming_assignments",
    "single_seat_naming_assignment",
]
