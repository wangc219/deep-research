"""First-wave mission-graph composition for dynamic-v2.

``target_instances`` selects a heterogeneous scout set.  Remaining capacity
up to ``maximum_instances`` is reserved for Gap Analyzer recruitment instead
of cloning the same creative archetype.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class FirstWaveSeat:
    mission_node: str
    archetype: str


@dataclass(frozen=True)
class DynamicV2InstanceBounds:
    """Resolved instance limits shared by planning and execution.

    ``maximum_instances`` is the configured graph ceiling.  ``target_instances``
    is the number available to the first wave after reserving capacity for
    later recruitment or repair.  Keeping this calculation in the strategy
    layer prevents workflow code from silently falling back to a different
    default than the policy normalizer.
    """

    minimum_instances: int
    target_instances: int
    maximum_instances: int


@dataclass(frozen=True)
class FirstWavePlan:
    seats: tuple[FirstWaveSeat, ...]
    reviewer_count: int
    creative_count: int
    scout_count: int
    reserved_recruit_slots: int
    target_instances: int
    maximum_instances: int

    @property
    def instance_count(self) -> int:
        return len(self.seats)


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def resolve_dynamic_v2_instance_bounds(
    *,
    minimum_instances: int = 8,
    target_instances: int | None = 10,
    maximum_instances: int = 21,
    hard_maximum_instances: int | None = None,
    reserved_instances: int = 0,
) -> DynamicV2InstanceBounds:
    """Resolve one bounded target for both graph construction and execution.

    ``hard_maximum_instances`` is an optional profile-wide cap (for example
    ``max_dynamic_instances``).  A reserve can reduce the first-wave target,
    but never below the minimum needed to preserve complementary S1/S2 and
    creative coverage.
    """

    minimum = max(1, _coerce_int(minimum_instances, 8))
    maximum = max(minimum, _coerce_int(maximum_instances, 21))
    if hard_maximum_instances is not None:
        hard_maximum = max(minimum, _coerce_int(hard_maximum_instances, maximum))
        maximum = min(maximum, hard_maximum)
    available_maximum = max(
        minimum,
        maximum - max(0, _coerce_int(reserved_instances, 0)),
    )
    requested = minimum if target_instances is None else _coerce_int(
        target_instances, minimum
    )
    target = max(minimum, min(available_maximum, requested))
    return DynamicV2InstanceBounds(
        minimum_instances=minimum,
        target_instances=target,
        maximum_instances=maximum,
    )


# Indispensable complementary perspectives, then unique creative scouts.
# Order is the fill priority when ``target_instances`` is small.
DYNAMIC_V2_SCOUT_PRIORITY: tuple[FirstWaveSeat, ...] = (
    FirstWaveSeat("S1", "opponent_system_modeler"),
    FirstWaveSeat("S2", "operational_baseline_analyst"),
    FirstWaveSeat("S3", "disruptive_mechanism_generator"),
    FirstWaveSeat("S4", "innovative_equipment_dimension_generator"),
    FirstWaveSeat("S3", "weak_signal_scout"),
    FirstWaveSeat("S1", "adversary_adaptation_analyst"),
    FirstWaveSeat("S2", "competitive_coa_designer"),
    FirstWaveSeat("S3", "cross_scenario_stress_tester"),
)

DYNAMIC_V2_REVIEWER_ARCHETYPE = "independent_portfolio_reviewer"

# Archetypes the Gap Analyzer may recruit.  First-wave scouts are reused only
# when the missing axis still needs another independent pass.
GAP_RECRUIT_ARCHETYPES: dict[str, tuple[str, str]] = {
    "battlefield_breakpoint": ("S3", "weak_signal_scout"),
    "mechanism": ("S3", "disruptive_mechanism_generator"),
    "carrier_form": ("S4", "innovative_equipment_dimension_generator"),
    "engagement_geometry": ("S3", "cross_scenario_stress_tester"),
    "resource_exchange": ("S3", "cross_scenario_stress_tester"),
    "counter_adaptation": ("S3", "adversary_counter_adaptation_red_team"),
}


def reviewer_count_for_target(target_instances: int) -> int:
    """Two cross-pool reviewers below 11 seats, three otherwise."""

    return 2 if int(target_instances) <= 10 else 3


def compose_dynamic_v2_first_wave(
    *,
    target_instances: int,
    maximum_instances: int,
) -> FirstWavePlan:
    """Build a heterogeneous first wave that leaves room for recruitment.

    The first wave never clones ``innovative_equipment_dimension_generator``
    into six identical creative seats.  S5 reviewers are cross-pool and are
    appended after scouts so graph construction can depend them on every
    S3/S4 producer.
    """

    bounds = resolve_dynamic_v2_instance_bounds(
        target_instances=target_instances,
        maximum_instances=maximum_instances,
    )
    target = bounds.target_instances
    maximum = bounds.maximum_instances
    reviewers = reviewer_count_for_target(target)
    scout_budget = max(3, min(len(DYNAMIC_V2_SCOUT_PRIORITY), target - reviewers))
    scouts = DYNAMIC_V2_SCOUT_PRIORITY[:scout_budget]
    seats = (
        *scouts,
        *(
            FirstWaveSeat("S5", DYNAMIC_V2_REVIEWER_ARCHETYPE)
            for _ in range(reviewers)
        ),
    )
    creative_count = sum(seat.mission_node in {"S3", "S4"} for seat in seats)
    reserved = max(0, maximum - len(seats))
    return FirstWavePlan(
        seats=seats,
        reviewer_count=reviewers,
        creative_count=creative_count,
        scout_count=len(scouts),
        reserved_recruit_slots=reserved,
        target_instances=target,
        maximum_instances=maximum,
    )


def recruit_archetype_for_gap(
    gap_axis: str,
    *,
    already_used: Sequence[str] = (),
) -> tuple[str, str]:
    """Return ``(mission_node, archetype)`` for one high-value coverage gap."""

    node, archetype = GAP_RECRUIT_ARCHETYPES.get(
        str(gap_axis),
        ("S3", "disruptive_mechanism_generator"),
    )
    used = {str(item) for item in already_used}
    if archetype in used and gap_axis == "counter_adaptation":
        return "S3", "cross_scenario_stress_tester"
    if archetype in used:
        fallback = GAP_RECRUIT_ARCHETYPES.get(
            "counter_adaptation",
            ("S3", "adversary_counter_adaptation_red_team"),
        )
        if fallback[1] not in used:
            return fallback
    return node, archetype


__all__ = [
    "DYNAMIC_V2_REVIEWER_ARCHETYPE",
    "DYNAMIC_V2_SCOUT_PRIORITY",
    "DynamicV2InstanceBounds",
    "FirstWavePlan",
    "FirstWaveSeat",
    "GAP_RECRUIT_ARCHETYPES",
    "compose_dynamic_v2_first_wave",
    "recruit_archetype_for_gap",
    "resolve_dynamic_v2_instance_bounds",
    "reviewer_count_for_target",
]
