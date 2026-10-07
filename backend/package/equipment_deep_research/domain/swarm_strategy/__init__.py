"""Dynamic-v2 research strategy: coverage, first-wave composition, gap decisions.

This package is the collaboration boundary between Query-derived divergence
control and the existing mission-graph / runtime execution loop.  It has no
provider, ledger or prompt-rendering dependencies.
"""

from equipment_deep_research.domain.swarm_strategy.briefs import (
    ARCHETYPE_AXIS,
    AXIS_LABELS_ZH,
    ScoutMission,
    VALUE_LABELS_ZH,
    assign_scout_mission,
    compact_coverage_for_review,
    gap_axis_from_residuals,
)
from equipment_deep_research.domain.swarm_strategy.composition import (
    DYNAMIC_V2_REVIEWER_ARCHETYPE,
    DYNAMIC_V2_SCOUT_PRIORITY,
    DynamicV2InstanceBounds,
    FirstWavePlan,
    FirstWaveSeat,
    GAP_RECRUIT_ARCHETYPES,
    compose_dynamic_v2_first_wave,
    recruit_archetype_for_gap,
    resolve_dynamic_v2_instance_bounds,
    reviewer_count_for_target,
)
from equipment_deep_research.domain.swarm_strategy.coverage import (
    COVERAGE_AXES,
    CandidateCoverage,
    CoverageSnapshot,
    build_coverage_snapshot,
    classify_candidate,
    extract_query_axis_hits,
)
from equipment_deep_research.domain.swarm_strategy.decisions import (
    AdaptiveSwarmDecision,
    SwarmAction,
    decide_adaptive_action,
)
from equipment_deep_research.domain.swarm_strategy.state import SwarmState

__all__ = [
    "ARCHETYPE_AXIS",
    "AXIS_LABELS_ZH",
    "AdaptiveSwarmDecision",
    "COVERAGE_AXES",
    "CandidateCoverage",
    "CoverageSnapshot",
    "DYNAMIC_V2_REVIEWER_ARCHETYPE",
    "DYNAMIC_V2_SCOUT_PRIORITY",
    "DynamicV2InstanceBounds",
    "FirstWavePlan",
    "FirstWaveSeat",
    "GAP_RECRUIT_ARCHETYPES",
    "ScoutMission",
    "SwarmState",
    "SwarmAction",
    "VALUE_LABELS_ZH",
    "assign_scout_mission",
    "build_coverage_snapshot",
    "classify_candidate",
    "compact_coverage_for_review",
    "compose_dynamic_v2_first_wave",
    "decide_adaptive_action",
    "extract_query_axis_hits",
    "gap_axis_from_residuals",
    "recruit_archetype_for_gap",
    "resolve_dynamic_v2_instance_bounds",
    "reviewer_count_for_target",
]
