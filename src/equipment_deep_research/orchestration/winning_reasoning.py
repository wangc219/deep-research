"""Traceable six-step winning-mechanism reasoning, independent of agent names."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard


@dataclass(frozen=True)
class ReasoningNode:
    object_id: str
    title: str
    summary: str
    input_refs: list[str]
    evidence_ids: list[str]
    confidence: float
    assumptions: list[str]


@dataclass(frozen=True)
class SixStepResult:
    defense_decomposition: ReasoningNode
    winning_paths: ReasoningNode
    effect_chain: ReasoningNode
    capability_mapping: ReasoningNode
    gap_matrix: ReasoningNode
    image_drafts: list[ReasoningNode]

    def critical_nodes(self) -> list[ReasoningNode]:
        return [self.defense_decomposition, self.winning_paths, self.effect_chain, self.capability_mapping, self.gap_matrix, *self.image_drafts]


class SixStepReasoner:
    def run(self, *, topic: str, route: str, packets: list[BaselineFindingPacket], evidence: list[EvidenceCard]) -> SixStepResult:
        evidence_ids = [item.evidence_id for item in evidence] or [item for packet in packets for item in packet.evidence_ids]
        confidence = round(sum(packet.confidence for packet in packets) / len(packets), 3) if packets else 0.0
        base = lambda name, summary, refs=[]: ReasoningNode(self._id(name, topic), name, summary, refs, evidence_ids, confidence, ["仅基于已接纳公开证据", f"路线：{route}"])
        defense = base("防御解构", "按感知、决策、拦截、冗余四层识别对手防御薄弱环节。")
        paths = base("制胜路径", self._path(route), [defense.object_id])
        effect = base("效果链", "任务行动 -> 直接效果 -> 体系扰动 -> 作战收益。", [paths.object_id])
        mapping = base("能力映射", "将效果链映射为感知、决策、协同、载荷与保障功能。", [effect.object_id])
        gaps = base("差距量化", "按空白、关键差距、部分差距、满足、超出五档评估。", [mapping.object_id])
        draft = base("能力画像草案", "形成具备多源感知、快速判读、协同处置和任务重构能力的装备功能需求。", [gaps.object_id])
        return SixStepResult(defense, paths, effect, mapping, gaps, [draft])

    @staticmethod
    def _id(name: str, topic: str) -> str:
        return "reason-" + sha256(f"{name}:{topic}".encode()).hexdigest()[:12]

    @staticmethod
    def _path(route: str) -> str:
        return {"traditional_gap": "传统场景/战法与现有装备对比，识别能力缺口并提出升级功能。", "war_case_learning": "从局部战争战例提取新能力、新打法与经验不足，研判可迁移方向。"}.get(route, "新制胜机制、新作战打法和新体系组合牵引新装备能力增长点。")
