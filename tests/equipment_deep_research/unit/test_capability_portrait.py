from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.capability_portrait import (
    build_agent_led_capability_portrait,
    build_capability_portrait,
    build_capability_title,
    complete_operational_process,
    is_launch_mode_generic_weapon_title,
    normalize_operational_process,
    normalize_verification_plan,
    primary_equipment_form_title,
    resolve_capability_portrait,
)


def _fields(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "name": "有限区复获远程反舰巡航弹",
        "scenario": "GNSS拒止下远海目标航迹过期后的补击窗口",
        "problem": "外部目标更新中断后，现役弹药难以安全复获并确认机动舰艇",
        "principle": "把目标最大机动包线、剩余能量和多模证据共同用于有限区复获",
        "technologies": ["抗扰组合导航", "射频—成像复核", "安全拒打状态机"],
        "operational_concept": "按最后可信区域装订，进入有限搜索区后自主复获并受控交战",
        "operational_steps": [
            "装订最后可信目标区域和禁击区",
            "按剩余能量生成有限搜索区",
            "以射频和成像证据复核目标身份",
            "满足授权门槛后直接攻击，否则安全弃攻",
        ],
        "capability": "断链后对机动水面目标实施有限区自主复获与受控毁伤",
        "effect": "压缩目标脱离窗口并减少无效弹药消耗",
        "winning_mechanism": "把对手依靠航迹过期脱离打击的时间收益压缩为可验证搜索包线",
        "equipment_form": "固定构型远程反舰巡航弹及其多模末制导段",
        "baseline": "公开远程反舰巡航弹类别基线",
        "failure_boundary": ["搜索区超过剩余能量包线时必须弃攻"],
        "verification_plan": ["与无有限区复获能力的基线比较目标复获、拒打和剩余能量"],
    }
    values.update(overrides)
    return values


def test_portrait_is_overview_plus_four_agent_led_sections() -> None:
    portrait = build_agent_led_capability_portrait(**_fields())
    rows = portrait.splitlines()

    assert len(rows) == 5
    assert rows[0].startswith("概述：有限区复获远程反舰巡航弹")
    assert [row.split("：", 1)[0] for row in rows[1:]] == [
        "- 装备与技术实现",
        "- 关键作战流程",
        "- 形成能力与作战效果",
        "- 制胜逻辑机理与对抗边界",
    ]
    assert "发展与验证路径" not in portrait


def test_formatter_preserves_agent_semantics_without_family_recipe() -> None:
    portrait = build_capability_portrait(**_fields())

    for authored in (
        "按剩余能量生成有限搜索区",
        "射频—成像复核",
        "满足授权门槛后直接攻击，否则安全弃攻",
        "搜索区超过剩余能量包线时必须弃攻",
    ):
        assert authored in portrait
    for unprovided_stock_phrase in (
        "多轴释放",
        "诱导雷达开机",
        "射后转移",
        "分批释放巡飞弹",
    ):
        assert unprovided_stock_phrase not in portrait


def test_missing_process_remains_visible_instead_of_local_completion() -> None:
    portrait = build_capability_portrait(**_fields(operational_steps=[]))

    assert "须回到S5/S6 Agent补写" in portrait
    assert "任务前装订目标、禁击区" not in portrait
    assert complete_operational_process([], equipment_identity="反舰巡航弹") == []


def test_title_preserves_novel_agent_name_instead_of_dictionary_renaming() -> None:
    title = build_capability_title(
        name="潮痕-1有限区复获远程反舰巡航弹",
        equipment_form="固定构型远程反舰巡航弹及多模末制导段",
        effect="直接毁伤机动舰艇",
    )

    assert title == "潮痕-1有限区复获远程反舰巡航弹"


def test_generic_title_yields_to_agent_authored_concrete_form() -> None:
    title = build_capability_title(
        name="远程导弹",
        equipment_form="岛基机动有限区复获远程反舰导弹",
    )

    assert title == "岛基机动有限区复获远程反舰导弹"


def test_public_model_is_not_automatically_translated_or_promoted() -> None:
    title = build_capability_title(
        name="Harop类间歇链路任务升级",
        equipment_form="固定构型长航时巡飞猎歼弹药",
    )

    assert title == "固定构型长航时巡飞猎歼弹药"
    assert "证据缓存" not in title


def test_launch_mode_generic_detection_is_narrow() -> None:
    assert is_launch_mode_generic_weapon_title("地射无人机") is True
    assert is_launch_mode_generic_weapon_title("地射有限区复获反舰导弹") is False


def test_primary_equipment_form_strips_only_metadata_tail() -> None:
    assert primary_equipment_form_title(
        "固定构型远程反舰巡航弹；任务接口：低带宽目标摘要"
    ) == "固定构型远程反舰巡航弹"


def test_process_normalizer_preserves_order_and_does_not_infer_actor() -> None:
    rows = normalize_operational_process(
        ["任务装订", "目标复核", "授权攻击", "毁伤评估"],
        equipment_identity="任意新质装备",
    )

    assert rows == ["任务装订", "目标复核", "授权攻击", "毁伤评估"]


def test_verification_normalizer_only_uses_agent_authored_rows() -> None:
    rows = normalize_verification_plan(
        ["在强扰和目标航迹过期条件下注入对抗样本", "与现役基线比较任务完成情况"],
        equipment_identity="任意新质装备",
        failure_boundary="误击拒打边界无法闭合时停止转段",
    )

    assert rows == [
        "在强扰和目标航迹过期条件下注入对抗样本",
        "与现役基线比较任务完成情况",
    ]


def test_resolver_preserves_complete_agent_written_portrait() -> None:
    portrait = build_agent_led_capability_portrait(**_fields())

    assert resolve_capability_portrait(portrait, **_fields()) == portrait


def test_resolver_rebuilds_incomplete_legacy_portrait_from_structured_fields() -> None:
    resolved = resolve_capability_portrait("概述：过短。", **_fields())

    assert resolved != "概述：过短。"
    assert "有限区复获远程反舰巡航弹" in resolved
    assert len(resolved.splitlines()) == 5


def test_deadline_recovery_fails_closed_without_agent_candidate() -> None:
    assert build_deadline_weapon_directions(topic="无人远程精确火力打击装备") == []


def test_deadline_recovery_normalizes_only_upstream_agent_candidate() -> None:
    candidate = {
        "name": "潮痕-1有限区复获远程反舰巡航弹",
        "equipment_form": "固定构型远程反舰巡航弹及多模末制导段",
        "target_scenario": _fields()["scenario"],
        "problem_statement": _fields()["problem"],
        "scientific_principle": _fields()["principle"],
        "enabling_technologies": _fields()["technologies"],
        "operational_concept": _fields()["operational_concept"],
        "operational_process": _fields()["operational_steps"],
        "capability_outcome": _fields()["capability"],
        "military_value": _fields()["effect"],
        "winning_mechanism": _fields()["winning_mechanism"],
        "failure_boundary": _fields()["failure_boundary"],
        "direct_evidence_refs": ["ev-weapon-1"],
    }

    rows = build_deadline_weapon_directions(
        topic="远海目标复获",
        evidence_ids=["ev-context-1"],
        candidate_directions=[candidate],
    )

    assert len(rows) == 1
    assert rows[0]["name"] == candidate["name"]
    assert rows[0]["direct_evidence_refs"] == ["ev-weapon-1"]
    assert rows[0]["evidence_ids"] == ["ev-weapon-1", "ev-context-1"]
    assert len(rows[0]["capability_portrait"].splitlines()) == 5
