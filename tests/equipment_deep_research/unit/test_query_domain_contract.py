from __future__ import annotations

from equipment_deep_research.agents.workflows.shared_context import query_domain_contract
from equipment_deep_research.domain.models import CapabilityImageItem, EvidenceCard
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.orchestration.runner import _bind_capability_evidence
from equipment_deep_research.orchestration.runner import _should_run_model_blueprint


def test_detection_query_does_not_inherit_combat_subject_contract() -> None:
    contract = query_domain_contract(
        "强电磁压制环境下高机动多传感器现场检测装备能力缺口",
        structured_query_brief={
            "query_equipment_mode": "mission_equipment",
            "equipment_semantic_boundary": "装备本体承担检测、定位和跟踪，不承担毁伤",
            "required_direct_military_effects": ["发现并识别目标"],
        },
    )

    assert contract["mode"] == "mission_equipment"
    assert contract["requires_direct_combat_weapon"] is False
    assert "远程精确打击弹药" in contract["forbidden_subjects"]


def test_domain_defaults_to_direct_combat_without_model_decision() -> None:
    contract = query_domain_contract("现场检测装备能力缺口")
    assert contract["mode"] == "direct_combat"
    assert contract["requires_direct_combat_weapon"] is True


def test_combat_query_keeps_direct_effect_requirement() -> None:
    contract = query_domain_contract(
        "复杂电磁环境下远程精确打击装备的突防与毁伤闭环",
        structured_query_brief={
            "equipment_semantic_boundary": "具体弹药本体承担直接毁伤效果",
            "required_direct_military_effects": ["突防和毁伤"],
        },
    )

    assert contract["mode"] == "direct_combat"
    assert contract["requires_direct_combat_weapon"] is True


def test_shared_evidence_is_background_when_it_does_not_entail_card_identity() -> None:
    store = DomainStore()
    store.evidence["ev-common"] = EvidenceCard(
        evidence_id="ev-common",
        source_title="通用传感器综述",
        source_url="https://example.com/common",
        source_tier="government",
        claim="多传感器融合可改善复杂环境下的观测连续性",
        excerpt="融合架构需要独立验证。",
        source_location="body",
        quality_assessment="assessed",
        created_by="test",
    )
    image = CapabilityImageItem(
        capability_id="cap-1",
        name="断链复核检测节点",
        equipment_category="检测装备",
        capability_type="new_capability",
        source_winning_logic="形成现场检测闭环",
        related_scenario="现场检测",
        priority="P1",
        capability_gap="缺少复核节点",
        capability_image="",
        evidence_ids=["ev-common"],
        confidence=0.8,
        equipment_form="机动检测平台",
    )
    bound = _bind_capability_evidence([image], store, query_domain={"mode": "mission_equipment"})[0]

    assert bound.evidence_binding["background"] == ["ev-common"]
    assert bound.evidence_binding["direct"] == []
    assert bound.verification_status == "hypothesis"
    assert bound.confidence_limited is True


def test_quality_swarm_uses_bounded_model_blueprint_by_default(monkeypatch) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_DISABLE_MODEL_BLUEPRINT", raising=False)
    assert _should_run_model_blueprint(
        mode="real",
        provider_kind="codex_cli",
        execution_profile_id="winning_swarm_dynamic_v2",
        callable_designer=True,
    ) is True
    monkeypatch.setenv("EQUIPMENT_DR_DISABLE_MODEL_BLUEPRINT", "1")
    assert _should_run_model_blueprint(
        mode="real",
        provider_kind="codex_cli",
        execution_profile_id="winning_swarm_dynamic_v2",
        callable_designer=True,
    ) is False
