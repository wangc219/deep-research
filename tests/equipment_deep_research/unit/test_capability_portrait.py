from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.capability_portrait import (
    assemble_capability_portrait_modules,
    build_agent_led_capability_portrait,
    build_capability_portrait,
    build_capability_title,
    complete_operational_process,
    is_launch_mode_generic_weapon_title,
    normalize_operational_process,
    normalize_verification_plan,
    primary_equipment_form_title,
    parse_capability_portrait_modules,
    resolve_capability_portrait,
    strip_schema_placeholders,
)


def test_five_authored_modules_are_assembled_without_cross_field_synthesis() -> None:
    modules = {
        "overview": "敌方机动舰艇利用航迹过期脱离远海补击窗口，我方有限区复获巡航弹依据最后可信区域自主收敛搜索，以受控复核恢复交战机会并毁伤授权目标",
        "technology_implementation": "弹上融合惯性、天文与地形匹配维持导航，射频和成像载荷经任务计算机形成同源目标证据，安全状态机把禁击区、授权门槛与导引头接口联锁",
        "operational_process": "联合战役远海追击阶段，舰载发射单元装订最后可信区域后齐射；弹群在干扰空域分配搜索扇区，复获并交叉复核目标，满足授权即攻击，否则越界弃攻",
        "capability_effects": "形成外部更新中断后的有限区复获与受控毁伤能力，直接压缩敌舰脱离窗口；以复获时间、正确交战率、正确拒打率和剩余能量共同验收",
        "winning_logic": "传统补击依赖连续航迹，对手可用拖延更新换取脱离时间；新构型把航迹过期转化为武器自主收敛的有界搜索问题，迫使其在持续机动暴露与降低航速之间选择",
    }

    portrait = assemble_capability_portrait_modules(modules)

    assert portrait.count("概述：") == 1
    assert portrait.count("形成能力与作战效果：") == 1
    assert "以以" not in portrait
    assert "形成形成" not in portrait
    assert parse_capability_portrait_modules(portrait) == modules


def test_capability_classification_is_displayed_without_changing_five_modules() -> None:
    modules = {
        "capability_classification": {
            "primary_dimension": "毁伤维度",
            "secondary_dimensions": ["突防维度"],
            "classification_basis": "以受拒止环境下直接毁伤目标为主，并依靠有限区自主突防形成作用窗口",
        },
        "overview": "压缩机动目标脱离窗口并恢复断链后的直接毁伤机会",
        "technology_implementation": "把有限区搜索、目标复核与安全拒打落实到弹上任务系统",
        "operational_process": "装订最后可信区域，形成有限搜索区，复核目标后受控毁伤或安全弃攻",
        "capability_effects": "形成断链条件下的有限区复获和受控毁伤能力",
        "winning_logic": "把对手依靠航迹过期换取脱离时间的优势转化为有界搜索问题",
    }

    portrait = assemble_capability_portrait_modules(modules)

    assert portrait.startswith("能力分类：主：毁伤维度；辅：突防维度。")
    assert parse_capability_portrait_modules(portrait) == {
        key: value
        for key, value in modules.items()
        if key != "capability_classification"
    }


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


def test_local_portrait_builder_only_arranges_supplied_s6_semantics() -> None:
    portrait = build_agent_led_capability_portrait(**_fields())

    assert "有限区复获远程反舰巡航弹" in portrait
    assert "关键作战流程：" in portrait
    assert "制胜逻辑机理：" in portrait
    assert "搜索区超过剩余能量包线时必须弃攻" not in portrait


def test_compatibility_builder_arranges_structured_fields_without_family_inference() -> None:
    portrait = build_capability_portrait(**_fields())

    assert portrait == build_agent_led_capability_portrait(**_fields())
    assert "待命名具体武器装备" not in portrait


def test_missing_process_is_not_filled_by_local_code() -> None:
    assert complete_operational_process([], equipment_identity="反舰巡航弹") == []


def test_title_preserves_novel_agent_name_instead_of_dictionary_renaming() -> None:
    title = build_capability_title(
        name="潮痕-1有限区复获远程反舰巡航弹",
        equipment_form="固定构型远程反舰巡航弹及多模末制导段",
        effect="直接毁伤机动舰艇",
    )

    assert title == "潮痕-1有限区复获远程反舰巡航弹"


def test_title_preserves_codex_name_without_local_generic_classification() -> None:
    title = build_capability_title(
        name="远程导弹",
        equipment_form="岛基机动有限区复获远程反舰导弹",
    )

    assert title == "远程导弹"


def test_public_model_name_is_not_locally_replaced() -> None:
    title = build_capability_title(
        name="Harop类间歇链路任务升级",
        equipment_form="固定构型长航时巡飞猎歼弹药",
    )

    assert title == "Harop类间歇链路任务升级"
    assert "证据缓存" not in title


def test_launch_mode_generic_detection_is_disabled() -> None:
    assert is_launch_mode_generic_weapon_title("地射无人机") is False
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


def test_schema_placeholders_are_removed_from_verification_and_portrait_prose() -> None:
    assert normalize_verification_plan(
        ["string", "与现役基线比较任务完成情况"],
        equipment_identity="任意新质装备",
    ) == ["与现役基线比较任务完成情况"]
    assert strip_schema_placeholders("失效边界；string；对抗验证。") == (
        "失效边界；对抗验证。"
    )
    assert "string" not in resolve_capability_portrait(
        "制胜逻辑机理与对抗边界：失效边界；string；对抗验证。",
        **_fields(),
    )


def test_legacy_winning_logic_label_and_key_are_read_into_the_new_module() -> None:
    legacy = (
        "概述：旧概述。\n"
        "- 装备与技术实现：旧技术。\n"
        "- 关键作战流程：旧流程。\n"
        "- 形成能力与作战效果：旧效果。\n"
        "- 制胜逻辑机理与对抗边界：旧制胜逻辑。"
    )

    modules = parse_capability_portrait_modules(legacy)
    assert modules["winning_logic"] == "旧制胜逻辑"
    rendered = assemble_capability_portrait_modules(
        {**modules, "winning_logic_boundary": "不应优先采用的旧键内容"}
    )
    assert "制胜逻辑机理：旧制胜逻辑。" in rendered
    assert "制胜逻辑机理与对抗边界" not in rendered


def test_resolver_preserves_complete_agent_written_portrait() -> None:
    portrait = (
        "概述：面向远海补击窗口，该巡航弹通过有限区复获压缩目标脱离时间。\n"
        "- 装备与技术实现：采用抗扰导航与射频—成像复核。\n"
        "- 关键作战流程：装订、搜索、复核、交战或弃攻。\n"
        "- 形成能力与作战效果：形成断链复获能力并直接毁伤授权目标。\n"
        "- 制胜逻辑机理：传统补击依赖持续外部更新，有限搜索把等待链路改写为武器自主复获并压缩目标机动收益。"
    )

    assert resolve_capability_portrait(portrait, **_fields()) == portrait


def test_resolver_preserves_incomplete_legacy_text_without_rebuilding() -> None:
    resolved = resolve_capability_portrait("概述：过短。", **_fields())

    assert resolved == "概述：过短。"


def test_forced_compact_does_not_rewrite_legacy_combat_semantics() -> None:
    legacy = (
        "概述：短程反UUV效应器聚焦岛链外缘编队航路的水下拒止交战阶段，"
        "直接回应旧版资料。其核心构想是以预置节点压缩清障时间，"
        "以投送—校准—分类—受控拦截形成局部拒止，"
        "预期取得阻断UUV清障并迫使潜艇绕行。"
    )

    portrait = resolve_capability_portrait(
        legacy,
        force_compact=True,
        **_fields(
            scenario="任务相关作战阶段",
            principle="占位原理",
            operational_concept="占位构想",
            capability="占位能力",
            effect="占位效果",
        ),
    )

    assert portrait == legacy
    assert "投送—校准—分类—受控拦截" in portrait


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
    assert "潮痕-1有限区复获远程反舰巡航弹" in rows[0]["capability_portrait"]
    assert "关键作战流程：" in rows[0]["capability_portrait"]
