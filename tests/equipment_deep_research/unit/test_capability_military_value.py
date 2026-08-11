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


def test_generic_direction_is_not_reclassified_from_topic_keywords() -> None:
    original = _row("传统战法能力空白补位能力")
    rewritten = rewrite_capability_for_military_value(
        original,
        topic="边境村镇态势感知条件下影响分析",
        route="traditional_gap",
    )

    assert not needs_military_capability_rewrite(original)
    assert rewritten == original


def test_missing_title_gets_object_neutral_structural_fallback() -> None:
    original = _row("", "upgrade")
    rewritten = rewrite_capability_for_military_value(
        original,
        topic="边境接触带丛林通信影响能力研究",
        route="traditional_gap",
    )

    assert needs_military_capability_rewrite(original)
    assert rewritten["name"] == "待模型复核的现役装备升级方向"
    assert "边防雷达" not in rewritten["equipment_form"]
    assert "反无人" not in rewritten["mission_effect"]
    assert rewritten["target_scenario"] == "边境接触带丛林通信影响能力研究"
    assert "关键作战流程" in rewritten["deep_capability_portrait"]
    assert rewritten["upgrade_package"]
    assert rewritten["evidence_ids"] == ["ev-1"]


def test_forced_enrichment_preserves_model_identity_across_topics() -> None:
    row = _row("模型生成的装备方向")
    row["equipment_form"] = "模型生成的主装备对象"
    row["mission_effect"] = "模型生成的直接军事效果"

    border = rewrite_capability_for_military_value(
        row,
        topic="边境低空研究",
        force=True,
    )
    maritime = rewrite_capability_for_military_value(
        row,
        topic="远海护航研究",
        force=True,
    )

    for rewritten in (border, maritime):
        assert rewritten["name"] == row["name"]
        assert rewritten["equipment_form"] == row["equipment_form"]
        assert rewritten["mission_effect"] == row["mission_effect"]


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
