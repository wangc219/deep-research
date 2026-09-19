"""Query-derived coverage matrix for dynamic winning-swarm divergence.

This module is a pure strategy layer.  It does not call providers, mutate the
mission graph, or own ledger writes.  Controllers feed it candidate snapshots
and receive a deterministic coverage report that Gap Analyzer / recruitment
can act on.

Axes are derived from Query-facing candidate fields, not from a fixed
equipment catalogue.  A candidate without the required structured fields can
remain in the ledger as a draft, but it does not count as covering an axis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.domain.models import WinningHypothesis


COVERAGE_AXES: tuple[str, ...] = (
    "battlefield_breakpoint",
    "mechanism",
    "carrier_form",
    "engagement_geometry",
    "resource_exchange",
    "counter_adaptation",
)

BATTLEFIELD_BREAKPOINTS: tuple[str, ...] = (
    "sense",
    "decide",
    "deploy",
    "engage",
    "sustain",
    "recover",
)

MECHANISMS: tuple[str, ...] = (
    "physical_damage",
    "structural_failure",
    "area_denial",
    "time_offset",
    "resource_exchange",
    "behavior_induction",
)

CARRIER_FORMS: tuple[str, ...] = (
    "munition",
    "unmanned",
    "material",
    "infrastructure",
    "swarm_network",
)

ENGAGEMENT_GEOMETRIES: tuple[str, ...] = (
    "point",
    "corridor",
    "area",
    "boundary",
)

TIME_SCALES: tuple[str, ...] = (
    "instant",
    "persistent",
    "staged",
)

_AXIS_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "battlefield_breakpoint": {
        "sense": ("感知", "侦察", "探测", "预警", "监视", "传感器", "探测网"),
        "decide": ("决策", "指挥", "认知", "判断", "授权", "识别"),
        "deploy": ("部署", "投送", "前出", "进入", "预置", "展开"),
        "engage": ("接敌", "交战", "拦截", "打击", "毁伤", "杀伤", "命中"),
        "sustain": ("持续", "压制", "消耗", "饱和", "驻留", "反复"),
        "recover": ("恢复", "再生", "修复", "补充", "再装填"),
    },
    "mechanism": {
        "physical_damage": ("毁伤", "杀伤", "爆破", "动能", "侵彻", "爆炸"),
        "structural_failure": ("结构", "失效", "脆断", "共振", "解体", "疲劳"),
        "area_denial": ("拒止", "封锁", "障碍", "布雷", "封控", "阻隔"),
        "time_offset": ("时间", "窗口", "节奏", "延迟", "抢先", "错位"),
        "resource_exchange": ("成本", "交换比", "消耗", "廉价", "可消耗"),
        "behavior_induction": ("诱导", "欺骗", "诱饵", "误判", "行为", "认知战"),
    },
    "carrier_form": {
        "munition": ("弹", "弹药", "导弹", "火箭", "鱼雷"),
        "unmanned": ("无人", "无人机", "uuv", "usv", "自主平台"),
        "material": ("材料", "介质", "涂层", "气溶胶", "雾剂"),
        "infrastructure": ("预置", "坐底", "基础设施", "阵地", "岸基"),
        "swarm_network": ("蜂群", "网络", "集群", "分布式", "编队"),
    },
    "engagement_geometry": {
        "point": ("点目标", "单点", "点杀伤", "精确点"),
        "corridor": ("通道", "航线", "走廊", "海峡", "水道"),
        "area": ("区域", "海域", "空域", "面状", "广域"),
        "boundary": ("边界", "迁移", "前沿", "接触线"),
    },
}


@dataclass(frozen=True)
class CandidateCoverage:
    """Structured coverage claim extracted from one ledger candidate."""

    candidate_id: str
    title: str
    battlefield_breakpoints: tuple[str, ...] = ()
    mechanisms: tuple[str, ...] = ()
    carrier_forms: tuple[str, ...] = ()
    engagement_geometries: tuple[str, ...] = ()
    time_scales: tuple[str, ...] = ()
    resource_exchange: str = ""
    counter_adaptation: str = ""
    falsification_condition: str = ""
    source_domains: tuple[str, ...] = ()
    cluster_key: str = ""
    counts_toward_coverage: bool = False


@dataclass(frozen=True)
class CoverageSnapshot:
    """Aggregated coverage used by Gap Analyzer and adaptive stop rules."""

    topic: str
    candidate_count: int
    covered_candidate_count: int
    coverage_ratio: float
    duplicate_ratio: float
    contradiction_coverage: float
    marginal_novelty: float
    covered_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    missing_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    cluster_counts: dict[str, int] = field(default_factory=dict)
    candidates: tuple[CandidateCoverage, ...] = ()
    source_domain_entropy: float = 0.0

    @property
    def primary_gaps(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for axis in COVERAGE_AXES:
            if self.missing_values.get(axis):
                ordered.append(axis)
        return tuple(ordered)

    def to_event(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "candidate_count": self.candidate_count,
            "covered_candidate_count": self.covered_candidate_count,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "duplicate_ratio": round(self.duplicate_ratio, 4),
            "contradiction_coverage": round(self.contradiction_coverage, 4),
            "marginal_novelty": round(self.marginal_novelty, 4),
            "primary_gaps": list(self.primary_gaps),
            "cluster_counts": dict(self.cluster_counts),
            "source_domain_entropy": round(self.source_domain_entropy, 4),
        }


def _text_blob(hypothesis: WinningHypothesis) -> str:
    parts = [
        hypothesis.title,
        hypothesis.combat_dimension,
        hypothesis.changed_confrontation_variable,
        hypothesis.original_paradigm,
        hypothesis.disruptive_shift,
        hypothesis.independence_thesis,
        hypothesis.project_function,
        hypothesis.novelty_delta,
        " ".join(hypothesis.mechanism_chain),
        " ".join(hypothesis.equipment_forms),
        " ".join(hypothesis.direct_military_effects),
        " ".join(hypothesis.adversary_adaptations),
        " ".join(hypothesis.counterevidence),
        " ".join(hypothesis.failure_boundaries),
        " ".join(hypothesis.validation_plan),
        " ".join(hypothesis.cost_constraints),
    ]
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _match_tags(text: str, catalog: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    lowered = text.lower()
    matched: list[str] = []
    for tag, keywords in catalog.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            matched.append(tag)
    return tuple(dict.fromkeys(matched))


def _time_scales(text: str) -> tuple[str, ...]:
    tags: list[str] = []
    if any(token in text for token in ("瞬时", "一次性", "单次交战")):
        tags.append("instant")
    if any(token in text for token in ("持续", "驻留", "长期", "反复")):
        tags.append("persistent")
    if any(token in text for token in ("分阶段", "多波次", "分步", "梯次")):
        tags.append("staged")
    return tuple(dict.fromkeys(tags))


def extract_query_axis_hits(topic: str) -> dict[str, tuple[str, ...]]:
    """Tag the Query itself so scouts can be steered off its most salient axis."""

    text = str(topic or "")
    return {
        "battlefield_breakpoint": _match_tags(
            text, _AXIS_KEYWORDS["battlefield_breakpoint"]
        ),
        "mechanism": _match_tags(text, _AXIS_KEYWORDS["mechanism"]),
        "carrier_form": _match_tags(text, _AXIS_KEYWORDS["carrier_form"]),
        "engagement_geometry": _match_tags(
            text, _AXIS_KEYWORDS["engagement_geometry"]
        ),
        "resource_exchange": _match_tags(
            text, {"cost": ("成本",), "expendable": ("消耗", "廉价"), "exposure": ("暴露",)}
        ),
        "counter_adaptation": _match_tags(
            text, {"counter": ("反制", "适应"), "falsification": ("证伪", "失败边界")}
        ),
    }


def classify_candidate(hypothesis: WinningHypothesis) -> CandidateCoverage:
    """Extract coverage tags without a model call."""

    text = _text_blob(hypothesis)
    battlefield = _match_tags(text, _AXIS_KEYWORDS["battlefield_breakpoint"])
    mechanisms = _match_tags(text, _AXIS_KEYWORDS["mechanism"])
    carriers = _match_tags(text, _AXIS_KEYWORDS["carrier_form"])
    geometries = _match_tags(text, _AXIS_KEYWORDS["engagement_geometry"])
    time_scales = _time_scales(text)
    resource_exchange = " ".join(hypothesis.cost_constraints).strip()
    if not resource_exchange and "resource_exchange" in mechanisms:
        resource_exchange = hypothesis.novelty_delta or hypothesis.changed_confrontation_variable
    counter_adaptation = " ".join(hypothesis.adversary_adaptations).strip()
    falsification = " ".join(
        [*hypothesis.counterevidence, *hypothesis.failure_boundaries, *hypothesis.validation_plan]
    ).strip()
    source_domains = tuple(
        dict.fromkeys(
            item.strip()
            for item in (
                hypothesis.combat_dimension,
                hypothesis.original_paradigm,
                *hypothesis.equipment_forms[:2],
            )
            if str(item).strip()
        )
    )
    cluster_key = "|".join(
        (
            mechanisms[0] if mechanisms else "mechanism_unknown",
            carriers[0] if carriers else "carrier_unknown",
            geometries[0] if geometries else "geometry_unknown",
        )
    )
    counts = bool(
        battlefield
        and mechanisms
        and carriers
        and (counter_adaptation or falsification)
    )
    return CandidateCoverage(
        candidate_id=hypothesis.hypothesis_id,
        title=hypothesis.title,
        battlefield_breakpoints=battlefield,
        mechanisms=mechanisms,
        carrier_forms=carriers,
        engagement_geometries=geometries,
        time_scales=time_scales,
        resource_exchange=resource_exchange[:240],
        counter_adaptation=counter_adaptation[:240],
        falsification_condition=falsification[:240],
        source_domains=source_domains,
        cluster_key=cluster_key,
        counts_toward_coverage=counts,
    )


def _entropy(counts: Sequence[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    from math import log

    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * log(probability)
    maximum = log(max(2, len(counts)))
    return entropy / maximum if maximum else 0.0


def build_coverage_snapshot(
    hypotheses: Sequence[WinningHypothesis],
    *,
    topic: str = "",
    previous_cluster_keys: Sequence[str] = (),
) -> CoverageSnapshot:
    """Compute coverage, duplicate rate, contradiction coverage and novelty."""

    classified = tuple(classify_candidate(item) for item in hypotheses)
    covered = [item for item in classified if item.counts_toward_coverage]
    axis_values: dict[str, set[str]] = {axis: set() for axis in COVERAGE_AXES}
    catalogs: dict[str, tuple[str, ...]] = {
        "battlefield_breakpoint": BATTLEFIELD_BREAKPOINTS,
        "mechanism": MECHANISMS,
        "carrier_form": CARRIER_FORMS,
        "engagement_geometry": ENGAGEMENT_GEOMETRIES,
        "resource_exchange": ("cost", "expendable", "exposure"),
        "counter_adaptation": ("counter", "falsification"),
    }
    for item in covered:
        axis_values["battlefield_breakpoint"].update(item.battlefield_breakpoints)
        axis_values["mechanism"].update(item.mechanisms)
        axis_values["carrier_form"].update(item.carrier_forms)
        axis_values["engagement_geometry"].update(item.engagement_geometries)
        if item.resource_exchange:
            axis_values["resource_exchange"].add("cost")
        if item.counter_adaptation:
            axis_values["counter_adaptation"].add("counter")
        if item.falsification_condition:
            axis_values["counter_adaptation"].add("falsification")

    covered_values = {
        axis: tuple(value for value in catalogs[axis] if value in axis_values[axis])
        for axis in COVERAGE_AXES
    }
    missing_values = {
        axis: tuple(value for value in catalogs[axis] if value not in axis_values[axis])
        for axis in COVERAGE_AXES
    }
    covered_axis_count = sum(1 for axis in COVERAGE_AXES if covered_values[axis])
    coverage_ratio = covered_axis_count / max(1, len(COVERAGE_AXES))

    cluster_counts = Counter(item.cluster_key for item in classified if item.cluster_key)
    duplicate_candidates = sum(count - 1 for count in cluster_counts.values() if count > 1)
    duplicate_ratio = duplicate_candidates / max(1, len(classified))

    contradiction_hits = sum(
        1
        for item in classified
        if item.counter_adaptation or item.falsification_condition
    )
    contradiction_coverage = contradiction_hits / max(1, len(classified))

    previous = set(previous_cluster_keys)
    new_clusters = [
        item.cluster_key
        for item in classified
        if item.cluster_key and item.cluster_key not in previous
    ]
    marginal_novelty = len(set(new_clusters)) / max(1, len(classified))

    domain_counts = Counter(
        domain for item in classified for domain in item.source_domains
    )
    return CoverageSnapshot(
        topic=str(topic or ""),
        candidate_count=len(classified),
        covered_candidate_count=len(covered),
        coverage_ratio=round(coverage_ratio, 4),
        duplicate_ratio=round(duplicate_ratio, 4),
        contradiction_coverage=round(contradiction_coverage, 4),
        marginal_novelty=round(marginal_novelty, 4),
        covered_values=covered_values,
        missing_values=missing_values,
        cluster_counts=dict(sorted(cluster_counts.items())),
        candidates=classified,
        source_domain_entropy=round(_entropy(list(domain_counts.values())), 4),
    )


__all__ = [
    "BATTLEFIELD_BREAKPOINTS",
    "CARRIER_FORMS",
    "COVERAGE_AXES",
    "CandidateCoverage",
    "CoverageSnapshot",
    "ENGAGEMENT_GEOMETRIES",
    "MECHANISMS",
    "TIME_SCALES",
    "build_coverage_snapshot",
    "classify_candidate",
    "extract_query_axis_hits",
]
