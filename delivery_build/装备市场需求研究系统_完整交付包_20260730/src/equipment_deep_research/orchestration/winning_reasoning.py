"""Traceable six-step winning-mechanism reasoning, independent of agent names."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from equipment_deep_research.domain.models import (
    BaselineFindingPacket,
    EvidenceCard,
    WinningKnowledgeProjection,
    WinningMechanismInput,
    WinningReasoningNode,
)

@dataclass(frozen=True)
class SixStepResult:
    defense_decomposition: WinningReasoningNode
    winning_paths: WinningReasoningNode
    effect_chain: WinningReasoningNode
    capability_mapping: WinningReasoningNode
    gap_matrix: WinningReasoningNode
    image_drafts: list[WinningReasoningNode]

    def critical_nodes(self) -> list[WinningReasoningNode]:
        return [self.defense_decomposition, self.winning_paths, self.effect_chain, self.capability_mapping, self.gap_matrix, *self.image_drafts]


class WinningResourceProjector:
    def build(
        self,
        *,
        input_pack: WinningMechanismInput,
        packets: list[BaselineFindingPacket],
        evidence: list[EvidenceCard],
    ) -> WinningKnowledgeProjection:
        evidence_ids = [item.evidence_id for item in evidence]
        case_ids = [item.evidence_id for item in evidence if any(key in (item.claim + item.excerpt) for key in ("战例", "战争", "案例", "经验", "教训"))]
        frontier_ids = [item.evidence_id for item in evidence if any(key in (item.claim + item.excerpt) for key in ("新型", "前沿", "趋势", "技术", "自主", "智能", "无人"))]
        if input_pack.research_route == "war_case_learning" and not case_ids:
            case_ids = evidence_ids
        if input_pack.research_route == "new_winning_mechanism" and not frontier_ids:
            frontier_ids = evidence_ids
        questions = [
            "敌方重心与关键体系依赖是什么？",
            "可形成何种制胜逻辑与优选路径？",
            "效果链要求哪些功能与性能能力？",
            "能否通过新机制、新打法或新体系组合创造新能力增长点？",
        ]
        questions.extend(input_pack.open_questions)
        return WinningKnowledgeProjection(
            projection_id=f"winning-resources-r{input_pack.attempt}",
            input_id=input_pack.input_id,
            theory_tools=[
                {"name": "防御分层解析", "dimensions": ["感知", "决策", "拦截", "冗余"], "knowledge_pack_ids": ["public_evidence_index", "military_knowledge_base", "equipment_ontology", "doctrine_library", "case_library", "frontier_technology_library", "short_term_memory", "long_term_memory"]},
                {"name": "重心与击败机制识别", "dimensions": ["重心", "依赖", "时间窗口", "风险"]},
                {"name": "效果链因果建模", "dimensions": ["行动", "直接效果", "间接效果", "最终效果"]},
                {"name": "效果-功能-性能映射", "dimensions": ["效果", "功能", "性能"]},
                {"name": "五档差距评估", "dimensions": ["空白", "关键差距", "部分差距", "满足", "超出"]},
            ],
            case_resources=[{"evidence_id": item, "use": "战例验证、经验教训与跨场景迁移"} for item in case_ids],
            frontier_resources=[{"evidence_id": item, "use": "新概念、新技术、新手段与成熟度研判"} for item in frontier_ids],
            question_chain=[{"order": index + 1, "question": question, "status": "open"} for index, question in enumerate(dict.fromkeys(questions))],
            evidence_ids=evidence_ids,
        )


class SixStepReasoner:
    def run(self, *, topic: str, route: str, packets: list[BaselineFindingPacket], evidence: list[EvidenceCard], input_pack: WinningMechanismInput | None = None, resources: WinningKnowledgeProjection | None = None, model_analysis: dict[str, Any] | None = None) -> SixStepResult:
        evidence_ids = [item.evidence_id for item in evidence] or [item for packet in packets for item in packet.evidence_ids]
        packet_ids = [packet.packet_id for packet in packets]
        valid_model_refs = set(evidence_ids) | set(packet_ids)
        confidence = round(sum(packet.confidence for packet in packets) / len(packets), 3) if packets else 0.0
        claim_ids = sorted({claim_id for packet in packets for claim_id in packet.claim_ids})
        root_refs = [item for item in [input_pack.input_id if input_pack else None, resources.projection_id if resources else None] if item]
        findings = [finding for packet in packets for finding in packet.findings]
        sections = {
            key: value
            for packet in packets
            for key, value in packet.analysis_sections.items()
            if value not in (None, "", [], {})
        }
        open_questions = list(
            dict.fromkeys(question for packet in packets for question in packet.open_questions)
        )
        limitations = list(
            dict.fromkeys(item for packet in packets for item in packet.limitations)
        )
        def base(
            step: int,
            name: str,
            summary: str,
            refs: list[str] | None = None,
        ) -> WinningReasoningNode:
            model_node = _model_reasoning_node(model_analysis, step)
            recognition = str(model_node.get("recognition", "")).strip()
            raw_model_refs = model_node.get("evidence_refs", [])
            if not isinstance(raw_model_refs, list):
                raw_model_refs = []
            model_refs = [
                str(item)
                for item in raw_model_refs
                if str(item) in valid_model_refs
            ]
            return WinningReasoningNode(
                object_id=self._id(name, topic, input_pack.attempt if input_pack else 1),
                step=step,
                title=name,
                summary=recognition or summary,
                input_refs=refs if refs is not None else root_refs,
                evidence_ids=list(dict.fromkeys(model_refs)) or evidence_ids,
                claim_ids=claim_ids,
                confidence=_model_confidence(model_node, confidence),
                assumptions=["仅基于已接纳公开证据", f"路线：{route}", "公开资料结论需由分析师确认"],
                route=route,
                next_action=_model_next_action(
                    model_node,
                    step=step,
                    model_analysis=model_analysis,
                ),
            )
        defense = base(
            1,
            "防御解构",
            _model_summary(model_analysis, "defense_decomposition")
            or self._defense_summary(topic, findings, sections, limitations),
        )
        paths = base(
            2,
            "制胜路径",
            _model_summary(model_analysis, "winning_paths")
            or self._path_summary(route, findings, sections),
            [defense.object_id],
        )
        effect = base(
            3,
            "效果链",
            _model_summary(model_analysis, "effect_chain")
            or self._effect_summary(sections, open_questions),
            [paths.object_id],
        )
        mapping = base(
            4,
            "能力映射",
            _model_summary(model_analysis, "capability_mapping")
            or self._mapping_summary(sections),
            [effect.object_id],
        )
        gaps = base(
            5,
            "差距量化",
            _model_summary(model_analysis, "gap_assessment")
            or self._gap_summary(sections, limitations),
            [mapping.object_id],
        )
        draft = base(
            6,
            "能力画像生成",
            _model_summary(model_analysis, "concept_directions")
            or self._image_summary(route, findings, open_questions),
            [gaps.object_id],
        )
        return SixStepResult(defense, paths, effect, mapping, gaps, [draft])

    @staticmethod
    def _compact(values: list[object], *, limit: int = 3) -> str:
        rendered = [str(value).strip() for value in values if str(value).strip()]
        return "；".join(rendered[:limit]) or "当前结构化材料未给出具体内容"

    def _defense_summary(
        self,
        topic: str,
        findings: list[str],
        sections: dict[str, object],
        limitations: list[str],
    ) -> str:
        pressure = [
            sections[key]
            for key in ("threat_assessment", "enemy_coa", "environment_constraints")
            if key in sections
        ]
        basis = self._compact(pressure or findings)
        caveat = self._compact(limitations, limit=2) if limitations else "无已登记冲突"
        return (
            f"围绕{topic}，按感知、决策、处置、冗余/恢复四层解构。"
            f"主要压力依据：{basis}。证据边界：{caveat}。"
        )

    def _path_summary(
        self,
        route: str,
        findings: list[str],
        sections: dict[str, object],
    ) -> str:
        coa = [sections[key] for key in ("coa", "force_coordination", "scenario_framework") if key in sections]
        return f"{self._path(route)} 候选路径比较依据：{self._compact(coa or findings)}。"

    def _effect_summary(
        self,
        sections: dict[str, object],
        open_questions: list[str],
    ) -> str:
        timeline = [sections[key] for key in ("critical_timeline", "operational_constraints") if key in sections]
        unresolved = self._compact(open_questions, limit=2) if open_questions else "无新增开放问题"
        return (
            "依据关键时间窗和运用约束形成：持续发现 -> 可信识别/态势形成 -> "
            "威胁排序与资源分配 -> 分层处置 -> 任务连续性。"
            f"约束依据：{self._compact(timeline)}；待验证：{unresolved}。"
        )

    def _mapping_summary(self, sections: dict[str, object]) -> str:
        equipment = [
            sections[key]
            for key in (
                "current_parameters",
                "capability_constraints",
                "technology_readiness",
                "force_coordination",
            )
            if key in sections
        ]
        return (
            "将效果链逐项转换为效果 -> 功能 -> 性能/约束，覆盖多源感知、"
            "可信判别、快速决策、协同处置和韧性保障。"
            f"装备与工程依据：{self._compact(equipment)}。"
        )

    def _gap_summary(
        self,
        sections: dict[str, object],
        limitations: list[str],
    ) -> str:
        comparison = [
            sections[key]
            for key in ("current_parameters", "development_models", "capability_constraints")
            if key in sections
        ]
        caveat = self._compact(limitations, limit=2) if limitations else "无已登记冲突"
        return (
            "按空白、关键差距、部分差距、满足、超出五档，将场景所需功能与现有/在研能力比较。"
            f"比较基线：{self._compact(comparison)}；不确定性：{caveat}。"
        )

    def _image_summary(
        self,
        route: str,
        findings: list[str],
        open_questions: list[str],
    ) -> str:
        unresolved = len(open_questions)
        return (
            "依据前五步去重归并，分别形成新作战能力方向和现有装备升级需求，"
            "并写入制胜逻辑、关联场景、优先级、差距、功能画像和证据引用。"
            f"路线={route}，基线发现={len(findings)}条，待闭合问题={unresolved}项。"
        )

    @staticmethod
    def _id(name: str, topic: str, attempt: int) -> str:
        return "reason-" + sha256(f"{name}:{topic}:{attempt}".encode()).hexdigest()[:12]

    @staticmethod
    def _path(route: str) -> str:
        return {"traditional_gap": "传统场景/战法与现有装备对比，识别能力缺口并提出升级功能。", "war_case_learning": "从局部战争战例提取新能力、新打法与经验不足，研判可迁移方向。"}.get(route, "新制胜机制、新作战打法和新体系组合牵引新装备能力增长点。")


def _model_summary(model_analysis: dict[str, Any] | None, key: str) -> str:
    if not model_analysis:
        return ""
    value = model_analysis.get(key)
    if isinstance(value, list):
        rendered = [
            json_value if isinstance(json_value, str) else str(json_value)
            for json_value in value[:6]
        ]
        return "；".join(item for item in rendered if item.strip())
    return str(value).strip() if value not in (None, "") else ""


def _model_reasoning_node(
    model_analysis: dict[str, Any] | None,
    step: int,
) -> dict[str, Any]:
    if not model_analysis:
        return {}
    nodes = model_analysis.get("reasoning_nodes", {})
    if not isinstance(nodes, dict):
        return {}
    value = nodes.get(str(step), nodes.get(step, nodes.get(f"S{step}", {})))
    return dict(value) if isinstance(value, dict) else {}


def _model_confidence(model_node: dict[str, Any], fallback: float) -> float:
    try:
        value = float(model_node.get("confidence", fallback))
    except (TypeError, ValueError):
        return fallback
    return round(min(1.0, max(0.0, value)), 3)


def _model_next_action(
    model_node: dict[str, Any],
    *,
    step: int,
    model_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    next_step = _next_active_step(model_analysis, step)
    default = (
        {
            "action": "continue",
            "target_step": next_step,
            "reason": f"S{step}完成后进入下一有效步骤S{next_step}。",
        }
        if next_step
        else {
            "action": "stop",
            "target_step": 0,
            "reason": "S1-S6推理链已完成，进入L1-L3门控与独立审计。",
        }
    )
    raw = model_node.get("next_action", {})
    if not isinstance(raw, dict):
        return default
    action = str(raw.get("action", "")).strip().lower()
    if action not in {"continue", "parallel", "backtrack", "recall", "stop"}:
        return default
    try:
        target_step = int(raw.get("target_step", default["target_step"]) or 0)
    except (TypeError, ValueError):
        target_step = int(default["target_step"])
    if target_step not in range(0, 7):
        target_step = int(default["target_step"])
    if action == "stop":
        target_step = 0
    reason = str(raw.get("reason", "")).strip() or str(default["reason"])
    return {
        "action": action,
        "target_step": target_step,
        "reason": reason[:500],
    }


def _next_active_step(
    model_analysis: dict[str, Any] | None,
    step: int,
) -> int:
    raw_plan = (model_analysis or {}).get("winning_step_plan", [])
    modes: dict[int, str] = {}
    if isinstance(raw_plan, list):
        for item in raw_plan:
            if not isinstance(item, dict):
                continue
            try:
                item_step = int(item.get("step", 0))
            except (TypeError, ValueError):
                continue
            modes[item_step] = str(
                item.get("execution_mode", item.get("mode", "standard"))
            )
    return next(
        (
            candidate
            for candidate in range(step + 1, 7)
            if modes.get(candidate, "standard") != "skip"
        ),
        0,
    )
