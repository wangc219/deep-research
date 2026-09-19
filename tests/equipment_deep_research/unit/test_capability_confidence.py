from equipment_deep_research.orchestration.capability_confidence import (
    calibrate_capability_confidence,
)


def _card(**overrides: object) -> dict[str, object]:
    card: dict[str, object] = {
        "name": "断链地形匹配巡飞弹",
        "equipment_form": "地形匹配末制导巡飞弹",
        "target_scenario": "卫星导航受压制、数据链中断时沿山谷低空逼近雷达车",
        "problem_statement": "强干扰使连续制导和目标更新失效",
        "operational_mechanism": "惯导结合地形轮廓匹配维持航迹，末段复核雷达车并直接毁伤",
        "evidence_ids": ["ev-1", "ev-2"],
        "evidence_basis": [
            "公开材料支持强干扰条件下组合导航、地形匹配和末段自主复核用于低空精确打击雷达车。"
        ],
        "confidence": 0.58,
    }
    card.update(overrides)
    return card


def test_confidence_rewards_evidence_that_matches_equipment_and_scene() -> None:
    matched, matched_components = calibrate_capability_confidence(_card())
    generic, generic_components = calibrate_capability_confidence(
        _card(
            evidence_basis=["公开材料讨论分布式保障、后勤韧性与人才培养。"]
        )
    )

    assert matched > generic
    assert matched_components["evidence_fit"] > generic_components["evidence_fit"]


def test_confidence_rewards_forward_looking_falsifiability() -> None:
    bounded, bounded_components = calibrate_capability_confidence(
        _card(
            foresight_evidence_status="analogous_project_evidence",
            future_trigger="敌方导航欺骗与低空补盲雷达规模部署",
            adversary_adaptation="对手增加地貌伪装和近程拦截",
            validation_plan=["在强干扰山谷航线中对照基线考核复获率和正确拒打率"],
        )
    )
    unbounded, unbounded_components = calibrate_capability_confidence(_card())

    assert bounded > unbounded
    assert bounded_components["foresight"] > unbounded_components["foresight"]


def test_same_prior_does_not_force_identical_card_scores() -> None:
    direct, _ = calibrate_capability_confidence(
        _card(direct_evidence_refs=["ev-weapon-equipment-1", "ev-scene-2"])
    )
    generic, _ = calibrate_capability_confidence(
        _card(
            evidence_ids=["ev-generic-1"],
            evidence_basis=["公开材料仅支持一般方向，未覆盖该装备或使用场景。"],
        )
    )

    assert direct != generic


def test_confidence_uses_stable_sixty_to_eighty_percent_band() -> None:
    card = _card()

    first, first_components = calibrate_capability_confidence(card)
    second, second_components = calibrate_capability_confidence(card)

    assert 0.60 <= first <= 0.80
    assert first == second
    assert first_components["stable_spread"] == second_components["stable_spread"]
    assert first_components["calibration"] == "card_evidence_and_foresight_v2"
