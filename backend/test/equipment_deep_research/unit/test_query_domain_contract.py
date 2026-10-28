from __future__ import annotations

import json
from types import SimpleNamespace

from equipment_deep_research.agents.provider import AgentRunRequest
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.workflows import baseline_execution
from equipment_deep_research.agents.workflows.shared_context import (
    query_domain_contract,
    query_domain_narrative_instruction,
    reconcile_discovery_blueprint_domain,
    requested_candidate_count_contract,
    sanitize_mission_artifact,
    sanitize_mission_narrative_text,
)
from equipment_deep_research.agents.workflows.reporting_support import (
    _report_writer_system_prompt,
)
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


def test_empty_default_blueprint_does_not_override_explicit_rescue_query() -> None:
    contract = query_domain_contract(
        "山地灾害导致公网中断时，用便携式无人中继恢复救援通信",
        structured_query_brief={
            "query_equipment_mode": "direct_combat",
            "combat_problem_frame": "",
            "enemy_target_profile": [],
            "required_direct_military_effects": [],
            "equipment_semantic_boundary": "",
            "winning_problem_propositions": [],
        },
    )

    assert contract["mode"] == "mission_equipment"
    assert contract["requires_direct_combat_weapon"] is False
    assert "空中/地面通信中继平台" in contract["allowed_equipment_forms"]


def test_negated_combat_vocabulary_does_not_turn_rescue_query_into_combat() -> None:
    contract = query_domain_contract(
        "山地灾害公网中断时恢复救援通信；不使用敌方、击落、毁伤等作战叙事。",
        structured_query_brief={
            "query_equipment_mode": "direct_combat",
            "combat_problem_frame": "",
            "enemy_target_profile": [],
            "required_direct_military_effects": [],
            "equipment_semantic_boundary": "",
            "winning_problem_propositions": [],
        },
    )

    assert contract["mode"] == "mission_equipment"
    assert contract["requires_direct_combat_weapon"] is False


def test_mission_narrative_instruction_forbids_environment_personification() -> None:
    instruction = query_domain_narrative_instruction(
        "山地灾害导致公网中断时，用便携式无人中继恢复救援通信",
        structured_query_brief={"query_equipment_mode": "mission_equipment"},
    )

    assert "不存在敌我对抗" in instruction
    assert "不要把自然环境、地形、天气、故障、拥塞或灾害拟人化" in instruction
    assert "环境压力、失效模式、缓解措施及其新增工程代价" in instruction


def test_report_prompt_inherits_mission_narrative_boundary() -> None:
    prompt = _report_writer_system_prompt(
        {
            "topic": "山地灾害公网中断时恢复救援通信",
            "discovery_blueprint": {"structured_query_brief": {"query_equipment_mode": "mission_equipment"}},
        }
    )

    assert "【非战斗任务叙事引导】" in prompt
    assert "不要把自然环境、地形、天气、故障、拥塞或灾害拟人化" in prompt
    assert "不得据此删除有价值候选、缩减发散空间或把整项研究判为失败" in prompt


def test_rescue_query_reconciles_populated_combat_template_blueprint() -> None:
    blueprint = reconcile_discovery_blueprint_domain(
        "山地灾害公网中断时恢复救援通信；不使用敌方、击落、毁伤等作战叙事。",
        {
            "structured_query_brief": {
                "query_equipment_mode": "direct_combat",
                "combat_problem_frame": "打击对手节点",
                "enemy_target_profile": ["敌方通信节点"],
                "required_direct_military_effects": ["毁伤"],
                "equipment_semantic_boundary": "武器本体",
            },
            "required_outputs": [
                "现有战法基线",
                "战法概念集（3种新战法+5种战法组合）",
                "深度研究主报告（深度性、创新性、前瞻性、军事价值性）",
            ],
        },
    )

    brief = blueprint["structured_query_brief"]
    assert brief["query_equipment_mode"] == "mission_equipment"
    assert brief["enemy_target_profile"] == []
    assert brief["required_direct_military_effects"] == []
    assert "现有任务流程与系统基线" in blueprint["required_outputs"]
    assert all("战法" not in item for item in blueprint["required_outputs"])
    assert all("军事价值" not in item for item in blueprint["required_outputs"])


def test_long_prohibited_combat_vocabulary_stays_inside_negation_scope() -> None:
    topic = (
        "山地灾害造成公网中断时恢复救援通信；保持灾害救援语义，"
        "不使用敌方、我方、对手、击落、摧毁、毁伤、杀伤、弹药、战果、交战、"
        "作战反制等叙事。"
    )

    contract = query_domain_contract(
        topic,
        structured_query_brief={"query_equipment_mode": "direct_combat"},
    )

    assert contract["mode"] == "mission_equipment"


def test_combat_signal_after_contrast_is_not_hidden_by_earlier_negation() -> None:
    contract = query_domain_contract(
        "不使用敌方拟人化叙事，但是研究新型武器打击装备。",
        structured_query_brief={"query_equipment_mode": "direct_combat"},
    )

    assert contract["mode"] == "direct_combat"


def test_explicit_candidate_count_is_preserved_as_query_contract() -> None:
    exact = requested_candidate_count_contract("请收敛为3个可工程化装备候选")
    exact_natural = requested_candidate_count_contract("请收敛为正好3个可工程化装备候选")
    exact_project = requested_candidate_count_contract("请收敛为正好3个可独立立项、部署和试验验收的实体装备候选")
    ranged = requested_candidate_count_contract("形成三至五个装备候选并比较")
    absent = requested_candidate_count_contract("形成高质量装备方向")

    assert exact == {
        "explicit": True,
        "minimum": 3,
        "target": 3,
        "maximum": 3,
        "source": "user_query",
    }
    assert exact_natural == exact
    assert exact_project == exact
    assert ranged["minimum"] == 3
    assert ranged["target"] == 5
    assert ranged["maximum"] == 5
    assert absent["explicit"] is False


def test_mission_publication_sanitizer_removes_legacy_combat_template_language() -> None:
    payload = {
        "report_contract": {
            "military_test": "检验敌方适应后的毁伤与交战战果",
        },
        "cards": [
            {
                "foresight": "跟踪对手体系与作战方式",
                "scenario": (
                    "保持灾害救援语义，不使用敌方、我方、对手、击落、摧毁、"
                    "毁伤、杀伤、弹药、战果、交战、作战反制等叙事。"
                ),
            }
        ],
    }

    sanitized = sanitize_mission_artifact(payload)
    rendered = json.dumps(sanitized, ensure_ascii=False)

    for forbidden in (
        "敌方",
        "我方",
        "对手",
        "击落",
        "摧毁",
        "毁伤",
        "杀伤",
        "弹药",
        "战果",
        "交战",
        "作战反制",
    ):
        assert forbidden not in rendered
    assert "坚持灾害救援任务叙事" in rendered
    assert sanitize_mission_narrative_text("灾害摧毁公网基站") == "灾害破坏公网基站"


def test_mission_publication_sanitizer_preserves_governed_s6_headings() -> None:
    portrait = "\n".join(
        (
            "概述：面向灾害救援的背景与思路。",
            "- 装备与技术实现：形成可用构型。",
            "- 关键作战流程：装备进入作战现场后切换状态。",
            "- 形成能力与作战效果：新增可观察任务效果。",
            "- 制胜逻辑机理：改变原有任务关系。",
        )
    )

    sanitized = sanitize_mission_narrative_text(portrait)

    for heading in (
        "概述：",
        "装备与技术实现：",
        "关键作战流程：",
        "形成能力与作战效果：",
        "制胜逻辑机理：",
    ):
        assert heading in sanitized
    assert "装备进入任务现场后切换状态" in sanitized


def test_mission_query_uses_relevant_public_search_instead_of_combat_anchors(
    monkeypatch,
) -> None:
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "status": "ok",
            "data": {
                "results": [
                    {
                        "title": "UAV-Based Mesh Networks for Emergency Communication",
                        "url": "https://example.org/emergency-uav-mesh",
                        "description": "A disaster rescue communication relay network study.",
                    },
                    {
                        "title": "Precision strike missile",
                        "url": "https://example.org/missile",
                        "description": "A weapon system page.",
                    },
                ]
            },
        },
    )
    monkeypatch.setenv("OPEN_WEBSEARCH_URL", "http://open-websearch:3210")
    monkeypatch.setattr(baseline_execution.httpx, "post", lambda *args, **kwargs: response)
    request = AgentRunRequest(
        "run-mission-search",
        AgentDef("equipment", "装备", "", ["equipment"], [], {}),
        "山地灾害公网中断时使用无人中继恢复救援通信",
        "new_winning_mechanism",
        {"structured_query_brief": {"query_equipment_mode": "mission_equipment"}},
    )

    rows = baseline_execution._provider_neutral_live_search_rows(request, limit=4)

    assert [item["url"] for item in rows] == ["https://example.org/emergency-uav-mesh"]
    assert rows[0]["retrieval_lane"] == "provider_neutral_live_search"


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
    assert (
        _should_run_model_blueprint(
            mode="real",
            provider_kind="codex_cli",
            execution_profile_id="winning_swarm_dynamic_v2",
            callable_designer=True,
        )
        is True
    )
    monkeypatch.setenv("EQUIPMENT_DR_DISABLE_MODEL_BLUEPRINT", "1")
    assert (
        _should_run_model_blueprint(
            mode="real",
            provider_kind="codex_cli",
            execution_profile_id="winning_swarm_dynamic_v2",
            callable_designer=True,
        )
        is False
    )
