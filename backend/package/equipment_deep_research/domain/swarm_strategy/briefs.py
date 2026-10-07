"""Query-derived exclusive scout missions.

Coverage used to be a post-hoc report.  These briefs are the creation-time
steer: each S3/S4 seat owns one coverage axis and is told which values are
already salient in the Query or occupied by siblings.  That is what turns
model divergence into complementary weapon concepts instead of six
interceptor variants.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from equipment_deep_research.domain.swarm_strategy.coverage import (
    BATTLEFIELD_BREAKPOINTS,
    CARRIER_FORMS,
    COVERAGE_AXES,
    CoverageSnapshot,
    ENGAGEMENT_GEOMETRIES,
    MECHANISMS,
    extract_query_axis_hits,
)


ARCHETYPE_AXIS: dict[str, str] = {
    "disruptive_mechanism_generator": "mechanism",
    "innovative_equipment_dimension_generator": "carrier_form",
    "weak_signal_scout": "battlefield_breakpoint",
    "cross_scenario_stress_tester": "engagement_geometry",
    "adversary_counter_adaptation_red_team": "counter_adaptation",
}

AXIS_CATALOGS: dict[str, tuple[str, ...]] = {
    "battlefield_breakpoint": BATTLEFIELD_BREAKPOINTS,
    "mechanism": MECHANISMS,
    "carrier_form": CARRIER_FORMS,
    "engagement_geometry": ENGAGEMENT_GEOMETRIES,
    "resource_exchange": ("cost", "expendable", "exposure"),
    "counter_adaptation": ("counter", "falsification"),
}

AXIS_LABELS_ZH: dict[str, str] = {
    "battlefield_breakpoint": "战场断点",
    "mechanism": "作用机制",
    "carrier_form": "载体形态",
    "engagement_geometry": "接敌几何",
    "resource_exchange": "成本与资源交换",
    "counter_adaptation": "对手反制与证伪",
}

VALUE_LABELS_ZH: dict[str, str] = {
    "sense": "感知/侦察",
    "decide": "决策/授权",
    "deploy": "部署/前出",
    "engage": "接敌/交战",
    "sustain": "持续压制",
    "recover": "恢复/再生",
    "physical_damage": "物理毁伤",
    "structural_failure": "结构失效",
    "area_denial": "空间拒止",
    "time_offset": "时间错位",
    "resource_exchange": "资源交换",
    "behavior_induction": "行为诱导",
    "munition": "弹药弹体",
    "unmanned": "无人平台",
    "material": "材料/介质",
    "infrastructure": "基础设施/预置",
    "swarm_network": "群体/网络",
    "point": "点目标",
    "corridor": "通道/走廊",
    "area": "区域",
    "boundary": "边界迁移",
    "cost": "单次成本",
    "expendable": "可消耗性",
    "exposure": "暴露窗口",
    "counter": "对手反制",
    "falsification": "最小证伪",
}


@dataclass(frozen=True)
class ScoutMission:
    """Exclusive coverage assignment for one creative seat."""

    archetype: str
    axis: str
    focus_values: tuple[str, ...]
    avoid_values: tuple[str, ...]
    occupied_cluster_keys: tuple[str, ...]
    query_salient_values: tuple[str, ...]
    on_query_seat: bool
    forced_gap: str = ""

    @property
    def axis_label(self) -> str:
        return AXIS_LABELS_ZH.get(self.axis, self.axis)

    def labels(self, values: Sequence[str]) -> tuple[str, ...]:
        return tuple(VALUE_LABELS_ZH.get(str(item), str(item)) for item in values)

    def to_payload(self, instruction: str) -> dict[str, object]:
        return {
            "exclusive_axis": self.axis,
            "exclusive_axis_label": self.axis_label,
            "focus_values": list(self.focus_values),
            "focus_labels": list(self.labels(self.focus_values)),
            "avoid_values": list(self.avoid_values),
            "avoid_labels": list(self.labels(self.avoid_values)),
            "occupied_cluster_keys": list(self.occupied_cluster_keys),
            "query_salient_values": list(self.query_salient_values),
            "query_salient_labels": list(self.labels(self.query_salient_values)),
            "on_query_seat": self.on_query_seat,
            "forced_gap": self.forced_gap,
            "instruction": instruction,
        }


def _orthogonal_values(axis: str, salient: Sequence[str], occupied: Sequence[str]) -> tuple[str, ...]:
    catalog = AXIS_CATALOGS.get(axis, ())
    blocked = {str(item) for item in (*salient, *occupied)}
    orthogonal = tuple(item for item in catalog if item not in blocked)
    if orthogonal:
        return orthogonal
    unused_occupied = tuple(item for item in catalog if item not in set(salient))
    return unused_occupied or catalog


def assign_scout_mission(
    *,
    archetype: str,
    topic: str,
    occupied: CoverageSnapshot | None = None,
    forced_gap: str = "",
    on_query_seat: bool = False,
) -> ScoutMission:
    """Assign one exclusive coverage axis and a complementary focus set."""

    axis = str(forced_gap or ARCHETYPE_AXIS.get(str(archetype), "mechanism"))
    if axis not in COVERAGE_AXES:
        axis = "mechanism"
    query_hits = extract_query_axis_hits(topic)
    salient = query_hits.get(axis, ())
    occupied_values = occupied.covered_values.get(axis, ()) if occupied else ()
    occupied_clusters = (
        tuple(occupied.cluster_counts)[:8] if occupied is not None else ()
    )
    orthogonal = _orthogonal_values(axis, salient, occupied_values)
    if on_query_seat and not forced_gap:
        focus = tuple(dict.fromkeys((*salient[:2], *orthogonal[:1])))[:3]
        avoid = occupied_values
    else:
        focus = orthogonal[:3] or salient[:3] or AXIS_CATALOGS.get(axis, ())[:3]
        avoid = tuple(dict.fromkeys((*salient, *occupied_values)))
    return ScoutMission(
        archetype=str(archetype),
        axis=axis,
        focus_values=focus,
        avoid_values=avoid,
        occupied_cluster_keys=occupied_clusters,
        query_salient_values=salient,
        on_query_seat=bool(on_query_seat and not forced_gap),
        forced_gap=str(forced_gap or ""),
    )


def compact_coverage_for_review(
    snapshot: CoverageSnapshot,
) -> dict[str, object]:
    """Small S5-facing view of the coverage matrix."""

    return {
        "coverage_ratio": snapshot.coverage_ratio,
        "duplicate_ratio": snapshot.duplicate_ratio,
        "contradiction_coverage": snapshot.contradiction_coverage,
        "marginal_novelty": snapshot.marginal_novelty,
        "primary_gaps": list(snapshot.primary_gaps),
        "cluster_counts": dict(list(snapshot.cluster_counts.items())[:8]),
        "missing_values": {
            axis: list(values[:4])
            for axis, values in snapshot.missing_values.items()
            if values
        },
    }


def gap_axis_from_residuals(residuals: Sequence[object]) -> str:
    """Read the Gap Analyzer residual written at recruitment time."""

    for raw in residuals:
        text = str(raw or "")
        if text.startswith("coverage_gap:"):
            return text.split(":", 1)[-1].strip()
    return ""


__all__ = [
    "ARCHETYPE_AXIS",
    "AXIS_LABELS_ZH",
    "ScoutMission",
    "VALUE_LABELS_ZH",
    "assign_scout_mission",
    "compact_coverage_for_review",
    "gap_axis_from_residuals",
]
