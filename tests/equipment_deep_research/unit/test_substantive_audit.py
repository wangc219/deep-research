from __future__ import annotations

from equipment_deep_research.domain.models import (
    CapabilityImageItem,
    WinningMechanismStageOutput,
)
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.orchestration.reporting import audit_run


def _card(**overrides: object) -> CapabilityImageItem:
    values: dict[str, object] = {
        "capability_id": "cap-audit",
        "name": "断链自主精确打击弹药系统",
        "equipment_category": "远程精确制导弹药系统",
        "capability_type": "new_capability",
        "source_winning_logic": "在卫星拒止和强干扰条件下保持目标区自主交战闭环",
        "related_scenario": "联合战役纵深打击阶段遭卫星拒止和导航欺骗",
        "priority": "高",
        "capability_gap": "现役弹药在断链条件下缺少目标复核、授权交战和补击续接能力",
        "capability_image": "弹药在目标区自主复核并按授权边界实施毁伤或拒打",
        "evidence_ids": ["ev-1"],
        "confidence": 0.55,
        "target_scenario": "联合战役纵深打击阶段遭卫星拒止和导航欺骗",
        "problem_statement": "导航欺骗与目标更新中断使现役精确打击链断裂",
        "military_utility": "在通信受限时继续压制授权目标并维持远程火力续接",
        "mission_effect": "闭合目标复核、毁伤评估和补击任务链",
        "equipment_form": "弹载多模导引、抗骗导航和任务自治计算单元",
        "operational_mechanism": "飞行中监测导航可信度，末段交叉复核目标，不满足授权边界时拒打",
        "operational_process": ["装订授权边界", "末段复核目标", "实施毁伤或拒打"],
        "capability_outcome": "形成断链条件下可审计的远程精确火力续接能力",
        "winning_mechanism": "从依赖持续链路的单次命中转向断链条件下的任务闭环",
        "novelty": "新增机制把可信源选择、任务裁决和末段复核下沉到弹药本体，改变断链交战关系",
        "operational_concept": "由弹药在目标区自主完成复核和受约束交战",
        "strike_countermeasure_value": "降低导航欺骗和诱饵对远程打击任务链的破坏",
        "risk_boundaries": ["目标特征不可辨或授权边界失效时必须拒打"],
        "verification_plan": ["开展强干扰、诱饵和断链对抗试验"],
    }
    values.update(overrides)
    return CapabilityImageItem(**values)


def _stage() -> WinningMechanismStageOutput:
    return WinningMechanismStageOutput(
        stage_id="stage-L3",
        layer="L3",
        title="能力画像",
        outputs={"effect_chain": ["威胁—缺口—装备作用—直接效果"]},
        confidence=0.55,
        evidence_ids=["ev-1"],
        gate_passed=False,
        gate_reasons=["阶段置信度低于旧阈值"],
    )


def test_substantive_audit_ignores_mechanical_failures_when_business_case_is_closed() -> None:
    store = DomainStore()
    store.add_capability_image(_card())
    store.add_stage_output(_stage())

    audit = audit_run(
        store=store,
        coverage={"route": "new_winning_mechanism", "coverage_passed": False},
        max_rounds=1,
        current_rounds=3,
        analyst_confirmed=False,
        source_materials=[{"status": "fetch_failed"}],
    )

    assert audit.status == "approved"
    assert all(audit.substantive_checks.values())
    assert audit.mechanical_diagnostics["coverage"] is False
    assert audit.mechanical_diagnostics["confidence_ge_70"] is False
    assert audit.mechanical_diagnostics["stage_gates_passed"] is False
    assert not audit.hard_blockers


def test_substantive_audit_limits_only_a_card_without_concrete_equipment_or_causal_chain() -> None:
    store = DomainStore()
    store.add_capability_image(
        _card(
            equipment_form="平台能力",
            primary_equipment_identity="体系能力",
            problem_statement="",
            operational_mechanism="",
            capability_outcome="",
            winning_mechanism="",
            novelty="智能化",
        )
    )
    store.add_stage_output(_stage())

    audit = audit_run(
        store=store,
        coverage={"route": "new_winning_mechanism", "coverage_passed": True},
        max_rounds=2,
    )

    assert audit.status == "limited"
    assert audit.substantive_checks["concrete_equipment"] is False
    assert audit.substantive_checks["causal_coherence"] is False
    assert audit.hard_blockers


def test_substantive_audit_does_not_fail_an_empty_source_materialization_when_evidence_boundary_exists() -> None:
    store = DomainStore()
    store.add_capability_image(_card(evidence_ids=[], risk_boundaries=["仅作假设，需对抗试验验证"]))
    audit = audit_run(
        store=store,
        coverage={"route": "new_winning_mechanism", "coverage_passed": False},
        max_rounds=2,
        source_materials=[{"status": "network_safety_rejected"}],
    )

    assert audit.status == "approved"
    assert audit.checks["source_materialization"] is False
    assert any("材料化" in item for item in audit.advisories)
