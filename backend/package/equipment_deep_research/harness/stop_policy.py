from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard


@dataclass(frozen=True)
class StopDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceSufficiencyDecision:
    allowed: bool
    reasons: tuple[str, ...]
    accepted_count: int
    distinct_domains: int
    target_count: int


def evaluate_baseline_stop(
    packet: BaselineFindingPacket,
    *,
    enforce_evidence_counts: bool,
    minimum_evidence_count: int = 2,
    evidence_sufficiency: EvidenceSufficiencyDecision | None = None,
) -> StopDecision:
    packet.validate_for_submit()
    # Packet v1 remains a supported runtime/recovery format.  Its free-form
    # analysis_sections cannot satisfy the role-specific v2 payload gates, so
    # only v2 packets are evaluated against those structural stop conditions.
    if not packet.schema_version.startswith("2"):
        return StopDecision(True, ())
    payload = packet.payload
    reasons: list[str] = []
    if enforce_evidence_counts:
        if evidence_sufficiency is not None:
            reasons.extend(evidence_sufficiency.reasons)
        elif len(packet.evidence_ids) < minimum_evidence_count:
            reasons.append(f"正式证据少于{minimum_evidence_count}条")
    if packet.agent_id == "international_situation":
        if not _nonempty(payload.get("alternative_hypotheses")):
            reasons.append("缺少替代假设")
        if not _nonempty(payload.get("warning_indicators")):
            reasons.append("缺少预警指标")
        if not _nonempty(payload.get("scenario_drivers")):
            reasons.append("缺少时间尺度或场景牵引")
    elif packet.agent_id == "combat_scenario":
        branches = payload.get("scenario_branches")
        if not isinstance(branches, list) or len(branches) < 2:
            reasons.append("场景分支少于两个")
        if not _nonempty(payload.get("assumptions")) and not packet.evidence_ids:
            reasons.append("关键节点既无证据也无显式假设")
    elif packet.agent_id == "weapon_equipment":
        observations = payload.get("parameter_observations")
        if not isinstance(observations, list) or not observations:
            reasons.append("缺少参数观测")
        elif any(not _complete_parameter(item) for item in observations):
            reasons.append("参数观测缺少单位、批次、条件或置信度")
        if not _nonempty(payload.get("parameter_conflicts")):
            reasons.append("未显式保留冲突参数")
        if not _nonempty(payload.get("foreign_equipment_landscape")):
            reasons.append("缺少国外装备全景与型号谱系")
        if not _nonempty(payload.get("system_dependencies")):
            reasons.append("缺少国外装备体系依赖与适用边界")
        if not _nonempty(payload.get("defensive_countermeasure_options")):
            reasons.append("缺少可追溯的防御性反制选项")
        if not _nonempty(payload.get("upgrade_requirements")) and not _nonempty(
            payload.get("new_equipment_requirements")
        ):
            reasons.append("缺少现役升级或新装备研发需求")
        if not _nonempty(payload.get("verification_plan")):
            reasons.append("缺少反制与装备需求验证计划")
    elif packet.agent_id == "operational_employment":
        coa = payload.get("coa")
        if not isinstance(coa, dict) or not {
            "baseline",
            "distributed",
            "resource_constrained",
        } <= set(coa):
            reasons.append("未完成基线、弹性分布和资源受限三类COA比较")
        if not _nonempty(payload.get("operational_constraints")):
            reasons.append("作战约束不可追溯")
    elif packet.agent_id == "opponent_monitoring":
        if not _nonempty(payload.get("change_baseline")):
            reasons.append("缺少可比较的对手变化基线")
        if not _nonempty(payload.get("observed_moves")):
            reasons.append("缺少可观测动向")
        if not _nonempty(payload.get("formation_timeline")):
            reasons.append("缺少能力形成时间线")
        if not _nonempty(payload.get("warning_indicators")):
            reasons.append("缺少预警指标")
    elif packet.agent_id == "system_confrontation":
        if not _nonempty(payload.get("dependency_graph")):
            reasons.append("缺少体系依赖图")
        if not _nonempty(payload.get("cascading_failures")):
            reasons.append("缺少级联失效分析")
        if not _nonempty(payload.get("critical_vulnerabilities")):
            reasons.append("缺少关键脆弱点")
        if not _nonempty(payload.get("alternative_configs")):
            reasons.append("缺少替代体系构型")
    return StopDecision(not reasons, tuple(reasons))


def evaluate_evidence_sufficiency(
    packet: BaselineFindingPacket,
    evidence: list[EvidenceCard],
    *,
    minimum_count: int,
    target_count: int,
    minimum_domains: int = 2,
    require_counterevidence: bool = True,
) -> EvidenceSufficiencyDecision:
    accepted_count = len(evidence)
    domains = {
        (urlsplit(item.source_url).hostname or "").lower()
        for item in evidence
        if item.source_url
    }
    domains.discard("")
    reasons: list[str] = []
    if accepted_count < minimum_count:
        reasons.append(f"正式证据少于{minimum_count}条")
    if len(domains) < minimum_domains:
        reasons.append(f"独立来源域少于{minimum_domains}类")
    if require_counterevidence and not any(
        str(item).strip() for item in packet.limitations
    ):
        reasons.append("缺少反证、冲突或适用边界")
    return EvidenceSufficiencyDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        accepted_count=accepted_count,
        distinct_domains=len(domains),
        target_count=target_count,
    )


def _complete_parameter(value: Any) -> bool:
    return isinstance(value, dict) and all(
        value.get(key) not in (None, "", [], {})
        for key in ("unit", "variant", "condition", "confidence")
    )


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


__all__ = [
    "EvidenceSufficiencyDecision",
    "StopDecision",
    "evaluate_baseline_stop",
    "evaluate_evidence_sufficiency",
]
