from __future__ import annotations

from statistics import mean
from typing import Any

from equipment_deep_research.domain.models import (
    AgentRecommendation,
    BaselineFindingPacket,
    CapabilityImageItem,
    RecallRequest,
    TraceEvent,
    WinningMechanismStageOutput,
    to_plain,
)
from equipment_deep_research.domain.store import DomainStore, TraceStore


class WinningMechanismEngine:
    def __init__(self, *, min_confidence: float = 0.7, min_l2_feasibility: int = 3) -> None:
        self.min_confidence = min_confidence
        self.min_l2_feasibility = min_l2_feasibility

    def run(
        self,
        *,
        topic: str,
        route: str,
        store: DomainStore,
        trace: TraceStore,
        coverage: dict[str, Any],
    ) -> tuple[list[WinningMechanismStageOutput], list[CapabilityImageItem], list[AgentRecommendation]]:
        packets = list(store.baseline_packets.values())
        evidence_ids = sorted({evidence_id for packet in packets for evidence_id in packet.evidence_ids})
        recommendations = self._recommend_missing_agents(coverage)
        l1 = self._l1(topic=topic, route=route, packets=packets, evidence_ids=evidence_ids, coverage=coverage)
        store.add_stage_output(l1)
        trace.append(
            TraceEvent(
                event_id="trace-winning-l1",
                event_type="winning_stage_completed",
                actor="winning_mechanism",
                summary=f"L1 completed: gate={l1.gate_passed}",
                output_refs=[l1.stage_id],
            )
        )
        for recall in l1.recall_requests:
            trace.append(
                TraceEvent(
                    event_id=f"trace-{recall.recall_id}",
                    event_type="recall_requested",
                    actor="winning_mechanism",
                    summary=recall.reason,
                    input_refs=[l1.stage_id],
                    output_refs=[recall.recall_id],
                    payload=to_plain(recall),
                )
            )
        l2 = self._l2(topic=topic, route=route, l1=l1, evidence_ids=evidence_ids, coverage=coverage)
        store.add_stage_output(l2)
        trace.append(
            TraceEvent(
                event_id="trace-winning-l2",
                event_type="winning_stage_completed",
                actor="winning_mechanism",
                summary=f"L2 completed: gate={l2.gate_passed}",
                output_refs=[l2.stage_id],
            )
        )
        l3 = self._l3(topic=topic, route=route, l1=l1, l2=l2, evidence_ids=evidence_ids, coverage=coverage)
        store.add_stage_output(l3)
        trace.append(
            TraceEvent(
                event_id="trace-winning-l3",
                event_type="winning_stage_completed",
                actor="winning_mechanism",
                summary=f"L3 completed: gate={l3.gate_passed}",
                output_refs=[l3.stage_id],
            )
        )
        images = self._capability_images(topic=topic, route=route, l3=l3, evidence_ids=evidence_ids, coverage=coverage)
        for image in images:
            store.add_capability_image(image)
            trace.append(
                TraceEvent(
                    event_id=f"trace-capability-{image.capability_id}",
                    event_type="capability_image_created",
                    actor="winning_mechanism",
                    summary=image.name,
                    input_refs=[l3.stage_id, *image.evidence_ids],
                    output_refs=[image.capability_id],
                )
            )
        return [l1, l2, l3], images, recommendations

    def _l1(
        self,
        *,
        topic: str,
        route: str,
        packets: list[BaselineFindingPacket],
        evidence_ids: list[str],
        coverage: dict[str, Any],
    ) -> WinningMechanismStageOutput:
        confidence = _avg_confidence(packets)
        recalls = [
            RecallRequest(
                recall_id=f"recall-L1-{tag}",
                source_layer="L1",
                target_agent_id=None,
                target_capability_tag=tag,
                reason=f"缺少{tag}能力覆盖，影响防御解构与制胜路径判断。",
                required_data=[f"补充{topic}相关{tag}证据和判断"],
                return_node="L1",
                urgency="high",
            )
            for tag in coverage.get("missing_required_tags", [])
        ]
        gate_passed = confidence >= self.min_confidence and not recalls
        return WinningMechanismStageOutput(
            stage_id="stage-L1",
            layer="L1",
            title="制胜逻辑分析",
            outputs={
                "weakness_map": [
                    "围绕敌体系感知、决策、拦截、冗余进行分层解构。",
                    f"{topic}的关键弱点需由场景、装备和运用证据共同支撑。",
                ],
                "winning_paths": [
                    _route_winning_path(route),
                    "以战例和公开证据校验制胜路径假设。",
                ],
                "effect_chain": "行动 -> 直接效果 -> 间接效果 -> 最终能力收益。",
                "key_capabilities": ["感知发现", "快速决策", "精确打击/拦截", "体系协同"],
                "assumptions": ["公开资料足以支撑初步画像，不替代专家论证。"],
            },
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=[] if gate_passed else ["置信度或能力覆盖未达L1门控"],
            recall_requests=recalls,
        )

    def _l2(
        self,
        *,
        topic: str,
        route: str,
        l1: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
    ) -> WinningMechanismStageOutput:
        feasibility = 4 if l1.gate_passed else 2
        confidence = min(0.86, max(0.55, l1.confidence - (0 if l1.gate_passed else 0.08)))
        gate_passed = feasibility >= self.min_l2_feasibility and l1.gate_passed
        return WinningMechanismStageOutput(
            stage_id="stage-L2",
            layer="L2",
            title="概念创新评估",
            outputs={
                "concept_scan": [
                    "扫描高超、模块化、低成本、AI自主、诱饵、巡飞弹等前沿样式。",
                    f"结合{topic}判断可迁移的新能力空间。",
                ],
                "analogy_innovation": "七维分解并进行跨域移植评估。",
                "screened_directions": [
                    "新能力方向：体系化感知-决策-火力闭环。",
                    "改进方向：现有装备在复杂场景下的探测、协同和抗干扰能力提升。",
                ],
                "feasibility_score": feasibility,
                "route": route,
            },
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=[] if gate_passed else ["L2可行性或L1前置门控不足"],
        )

    def _l3(
        self,
        *,
        topic: str,
        route: str,
        l1: WinningMechanismStageOutput,
        l2: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
    ) -> WinningMechanismStageOutput:
        confidence = min(l1.confidence, l2.confidence)
        gate_passed = l2.gate_passed
        return WinningMechanismStageOutput(
            stage_id="stage-L3",
            layer="L3",
            title="能力图像生成",
            outputs={
                "dedup_grouping": "合并L1关键能力与L2创新方向，形成能力条目组。",
                "category_mapping": "按平台、任务、射程、速度、载荷和保障约束映射。",
                "gap_quantification": "按空白、关键差距、部分差距、满足、超出五档评估。",
                "priority_method": "关键性 x 紧迫性 x 可行性。",
                "coverage_limits": coverage.get("missing_required_tags", []),
            },
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=[] if gate_passed else ["L3为受限画像，需补齐缺失能力覆盖"],
        )

    def _capability_images(
        self,
        *,
        topic: str,
        route: str,
        l3: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
    ) -> list[CapabilityImageItem]:
        limit_suffix = ""
        if coverage.get("missing_required_tags"):
            limit_suffix = f"（受限：缺少{','.join(coverage['missing_required_tags'])}覆盖）"
        new_name = "体系化快速感知-决策-处置能力"
        upgrade_name = "现有装备复杂场景适应性升级能力"
        if route == "war_case_learning":
            new_name = "战例牵引的新型协同作战能力"
        if route == "traditional_gap":
            new_name = "传统战法缺口牵引的新能力补位"
        return [
            CapabilityImageItem(
                capability_id="cap-new-001",
                name=new_name,
                equipment_category="导弹/火箭及配套感知、指控、载荷体系",
                capability_type="new_capability",
                source_winning_logic="基于L1制胜路径与L2概念创新形成新作战能力方向",
                related_scenario=topic,
                priority="高：关键性高、紧迫性高、可行性中高",
                capability_gap="现有能力难以在复杂对抗场景下快速闭合感知-决策-处置链路",
                capability_image=f"发展具备多源感知、快速判读、弹性协同、低成本饱和应对和任务载荷适配能力的产品{limit_suffix}",
                evidence_ids=evidence_ids,
                confidence=l3.confidence,
            ),
            CapabilityImageItem(
                capability_id="cap-upgrade-001",
                name=upgrade_name,
                equipment_category="现有导弹/火箭装备与保障系统",
                capability_type="upgrade",
                source_winning_logic="基于传统能力缺口和L3差距量化形成升级需求",
                related_scenario=topic,
                priority="中高：紧迫性高、工程可行性高",
                capability_gap="现有装备在探测、抗干扰、协同、快速任务重构方面存在部分差距",
                capability_image=f"提升现有产品在复杂环境识别、协同接入、任务重构、抗干扰和持续保障方面的功能{limit_suffix}",
                evidence_ids=evidence_ids,
                confidence=l3.confidence,
            ),
        ]

    def _recommend_missing_agents(self, coverage: dict[str, Any]) -> list[AgentRecommendation]:
        return [
            AgentRecommendation(
                recommendation_id=f"agent-rec-{tag}",
                missing_capability_tag=tag,
                reason=f"当前启用agent未覆盖{tag}，会限制制胜机理研判。",
                suggested_agent_description=f"建议启用或新增具备{tag}能力标签的agent。",
            )
            for tag in coverage.get("missing_required_tags", [])
        ]


def _avg_confidence(packets: list[BaselineFindingPacket]) -> float:
    if not packets:
        return 0.0
    return round(mean(packet.confidence for packet in packets), 3)


def _route_winning_path(route: str) -> str:
    if route == "traditional_gap":
        return "传统打法能力缺口 -> 当前装备对比 -> 残余差距 -> 升级需求。"
    if route == "war_case_learning":
        return "局部战争案例 -> 新打法/新能力/不足 -> 未来布局方向。"
    return "新制胜机制/新体系组合/新作战样式 -> 新装备能力增长点。"
