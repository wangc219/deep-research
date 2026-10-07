from __future__ import annotations

from collections import Counter

import pytest

from equipment_deep_research.agents.workflows.winning_flows.naming import (
    NAMING_EXPRESSION_FAMILY_BY_CODE,
    S3_S4_WEAPON_NAMING_TYPES,
    allocate_s3_s4_naming_assignments,
    assign_s3_s4_naming_types,
    build_s3_s4_naming_plan,
)


SEAT_KEYS = (
    "agent-s3-1",
    "agent-s3-2",
    "agent-s3-3",
    "agent-s4-1",
    "agent-s4-2",
    "agent-s4-3",
)


def _codes(assignments: dict[str, dict[str, object]]) -> dict[str, list[str]]:
    return {
        seat: [str(item["code"]) for item in assignment["candidate_order"]]  # type: ignore[index]
        for seat, assignment in assignments.items()
    }


def test_six_seat_three_candidate_plan_is_balanced() -> None:
    plan = build_s3_s4_naming_plan("run-42|graph-7", SEAT_KEYS)
    stats = plan["portfolio_stats"]
    assignments = plan["assignments"]

    assert len(S3_S4_WEAPON_NAMING_TYPES) == 15
    assert stats["slot_count"] == 18
    assert stats["styles_covered"] == list("ABCDEFGHIJKLMNO")
    assert stats["max_style_frequency"] == 2
    assert len(set(stats["first_candidate_codes"])) == 6
    assert stats["first_candidate_family_count"] == 6

    frequencies = Counter(
        str(row["code"])
        for assignment in assignments.values()
        for row in assignment["candidate_order"]
    )
    assert set(frequencies) == set("ABCDEFGHIJKLMNO")
    assert max(frequencies.values()) == 2
    for assignment in assignments.values():
        rows = assignment["candidate_order"]
        assert [int(row["candidate_position"]) for row in rows] == [1, 2, 3]
        assert len({str(row["code"]) for row in rows}) == 3


def test_first_candidates_span_six_expression_families() -> None:
    assignments = allocate_s3_s4_naming_assignments("stable-seed", SEAT_KEYS)
    first_rows = [
        assignment["candidate_order"][0] for assignment in assignments.values()
    ]

    assert len({str(row["code"]) for row in first_rows}) == 6
    families = {
        NAMING_EXPRESSION_FAMILY_BY_CODE[str(row["code"])] for row in first_rows
    }
    assert len(families) == 6
    assert families == {str(row["expression_family"]) for row in first_rows}


def test_plan_is_independent_of_seat_input_order_and_replayable() -> None:
    seed = "run-42|topic-x|graph-7"
    first = build_s3_s4_naming_plan(seed, SEAT_KEYS)
    reversed_plan = build_s3_s4_naming_plan(seed, tuple(reversed(SEAT_KEYS)))

    assert first == reversed_plan
    assert _codes(first["assignments"]) == _codes(reversed_plan["assignments"])

    # The same stable run/graph seed reconstructs a checkpoint exactly.
    replay = build_s3_s4_naming_plan(seed, SEAT_KEYS)
    assert replay == first


def test_single_seat_wrapper_preserves_legacy_records() -> None:
    rows = assign_s3_s4_naming_types("legacy-run|agent-s3-1", count=6)

    assert len(rows) == 6
    assert len({row["code"] for row in rows}) == 6
    assert all(set(row) == {"code", "label", "focus"} for row in rows)


def test_invalid_or_oversized_portfolios_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="seat_keys must be unique"):
        allocate_s3_s4_naming_assignments("seed", ["s3", "s3"])
    with pytest.raises(ValueError, match="at least one"):
        allocate_s3_s4_naming_assignments("seed", [])
    with pytest.raises(ValueError, match="at most six"):
        allocate_s3_s4_naming_assignments("seed", [f"seat-{i}" for i in range(7)])
    with pytest.raises(ValueError, match="at most 30"):
        allocate_s3_s4_naming_assignments("seed", SEAT_KEYS, candidates_per_seat=6)
