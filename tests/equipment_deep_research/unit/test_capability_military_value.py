from equipment_deep_research.orchestration.capability_military_value import (
    needs_military_capability_rewrite,
    rewrite_capability_for_military_value,
)


def _row(name: str, capability_type: str = "new_capability") -> dict:
    return {
        "capability_id": "cap-1",
        "name": name,
        "capability_type": capability_type,
        "equipment_category": "旧类别",
        "source_winning_logic": "旧逻辑",
        "related_scenario": "边境村镇态势感知条件下影响分析",
        "priority": "高",
        "capability_gap": "旧差距；本次基线：公开基线有限",
        "capability_image": "旧画像",
        "evidence_ids": ["ev-1"],
        "confidence": 0.78,
        "agent_contributions": ["agent-a"],
    }


def test_generic_border_direction_is_rewritten_as_direct_combat_capability() -> None:
    original = _row("传统战法能力空白补位能力")
    rewritten = rewrite_capability_for_military_value(
        original,
        topic="边境村镇态势感知条件下影响分析",
        route="traditional_gap",
    )

    assert rewritten["name"] == "边境低空渗透目标多源猎获与反无人压制引导能力"
    assert "低空雷达" in rewritten["equipment_form"]
    assert "压制" in rewritten["mission_effect"]
    assert "反无人效应器" in rewritten["strike_countermeasure_value"]
    assert "关键作战流程" in rewritten["deep_capability_portrait"]
    assert "制胜逻辑机理" in rewritten["deep_capability_portrait"]
    assert rewritten["target_scenario"] == "边境村镇态势感知条件下影响分析"
    assert rewritten["operational_process"]
    assert "无人作战平台、导弹/弹药" in rewritten["development_path"]
    assert rewritten["capability_image"] == rewritten["deep_capability_portrait"]
    assert rewritten["evidence_ids"] == ["ev-1"]
    assert rewritten["confidence"] == 0.78
    assert rewritten["priority"] == "高"
    assert rewritten["agent_contributions"] == ["agent-a"]
    assert rewritten["capability_gap"].endswith("本次基线：公开基线有限")


def test_generic_upgrade_names_specific_existing_equipment_and_effect() -> None:
    rewritten = rewrite_capability_for_military_value(
        _row("现有装备传统场景能力提升", "upgrade"),
        topic="边境接触带丛林通信影响能力研究",
        route="traditional_gap",
    )

    assert rewritten["name"] == "现役边防雷达/光电节点低空目标猎获与反制火控升级"
    assert "现役边防雷达" in rewritten["baseline_system"]
    assert rewritten["upgrade_package"]
    assert "压制" in rewritten["combat_effect_uplift"]
    assert "反无人效应器" in rewritten["strike_chain_contribution"]


def test_already_specific_high_value_direction_is_preserved() -> None:
    row = _row("现役近程防空与反无人机分队低空小目标分层拦截升级", "upgrade")

    assert not needs_military_capability_rewrite(row)
    assert rewrite_capability_for_military_value(
        row,
        topic="海峡低空反制研究",
    ) == row


def test_specific_missile_equipment_title_is_not_rewritten_to_domain_slogan() -> None:
    row = _row("岛链远程多模制导弹药")

    assert not needs_military_capability_rewrite(row)
    assert rewrite_capability_for_military_value(
        row,
        topic="挖掘在西太反介入体系下的装备能力缺口",
        route="traditional_gap",
    ) == row


def test_specific_glide_weapon_title_is_not_rewritten_to_c2_capability() -> None:
    row = _row("被动末端制导滑翔弹")

    assert not needs_military_capability_rewrite(row)
    assert rewrite_capability_for_military_value(
        row,
        topic="强干扰、弱通信条件下低信息依赖精确打击装备研究",
        route="traditional_gap",
    ) == row
