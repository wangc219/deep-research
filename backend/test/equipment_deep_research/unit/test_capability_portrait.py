from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.capability_portrait import (
    CAPABILITY_PORTRAIT_MODULES,
    assemble_capability_portrait_modules,
    build_agent_led_capability_portrait,
    build_capability_portrait,
    build_capability_title,
    capability_portrait_quality_issues,
    capability_portrait_repair_issues,
    complete_operational_process,
    is_launch_mode_generic_weapon_title,
    normalize_operational_process,
    normalize_capability_classification,
    normalize_verification_plan,
    primary_equipment_form_title,
    parse_capability_portrait_modules,
    resolve_capability_portrait,
    strip_schema_placeholders,
)


def test_portrait_quality_gate_flags_mechanical_overview_slogan() -> None:
    modules = {
        "overview": (
            "传统防空依赖逐目标拦截，敌方以蜂群压缩窗口；测试拦截弹进入航路后形成直接拦截。"
            "把原本依赖固定节奏的处置过程前移到装备本体或编组内，"
            "对目标、火力节点或防御节奏形成可验证的直接约束；"
            "在敌方保持原有突防方式时形成直接杀伤或削峰，迫使其改变航路、编组或投入节奏。"
        ),
        "technology_implementation": "弹载导引头、任务计算机和战斗部接口联锁形成近距拦截闭环。" * 8,
        "operational_process": "发射单元完成航路授权后投放，弹体进入拦截区自主接敌并在作用后退出。" * 8,
        "capability_effects": "形成不依赖逐目标火控通道的并行拦截能力，直接阻断蜂群穿越。" * 8,
        "winning_logic": "把高价单发对廉价数量的旧交换改为按航路拦阻，迫使对手分散编组。" * 8,
    }

    assert any(
        "概述含跨装备通用机械句式" in issue
        for issue in capability_portrait_quality_issues(modules)
    )


def test_portrait_quality_gate_keeps_length_advisory_and_rejects_cross_module_reuse() -> None:
    repeated = "该装备进入受扰空域后持续复核授权目标并在满足证据门槛时实施直接毁伤"
    modules = {
            key: (repeated + "；" + label * 160)
        for key, label in (
            ("overview", "场景"),
            ("technology_implementation", "接口"),
            ("operational_process", "流程"),
            ("capability_effects", "战果"),
            ("winning_logic", "交换"),
        )
    }

    issues = capability_portrait_quality_issues(modules)

    assert not any("总长度超限" in issue for issue in issues)
    assert any("跨栏重复" in issue for issue in issues)


def test_portrait_repair_gate_keeps_editorial_advisories_out_of_model_wave() -> None:
    shared = "敌方持续机动，装备通过受控搜索形成直接毁伤并迫使其改变部署。"
    modules = {
        "overview": ("传统拦截依赖逐目标射击，敌方以数量压缩窗口；本装备改写交换关系，形成直接拦截战果并迫使其改变部署。" + shared) * 3,
        "technology_implementation": ("导弹弹体内置任务计算机、导引头和战斗部接口，通过受控授权把搜索原理落到装备本体。" + shared) * 3,
        "operational_process": ("发射单元装订区域后，弹体自主复核目标，满足授权即实施作用，否则退出并保留复击条件。" + shared) * 3,
        "capability_effects": ("形成断链条件下的受控拦截能力，直接压缩目标脱离窗口并增加对手机动成本。" + shared) * 3,
        "winning_logic": ("传统火力交换依赖连续链路，敌方可借断链脱离；本装备把断链转化为受控搜索问题，迫使对手暴露。" + shared) * 3,
    }

    issues = capability_portrait_quality_issues(modules)
    repair_issues = capability_portrait_repair_issues(modules)
    assert any("跨栏重复" in issue for issue in issues)
    assert any("跨栏重复" in issue for issue in repair_issues)


def test_portrait_repair_gate_keeps_hard_semantic_defects() -> None:
    modules = {key: "完整装备论证。" * 25 for key, _ in CAPABILITY_PORTRAIT_MODULES}
    modules["overview"] = "传统优势与敌方行动方式需要重新审视。" * 12

    repair_issues = capability_portrait_repair_issues(modules)
    assert any("未聚焦颠覆作战关系" in issue for issue in repair_issues)


def test_portrait_quality_gate_accepts_concise_distinct_modules() -> None:
    modules = {
        "overview": "敌舰利用航迹过期脱离补击窗口，有限区复获巡航弹把最后可信区域转化为可控搜索空间，以弹上复核恢复交战机会并直接毁伤授权目标。" * 4,
        "technology_implementation": "弹上组合导航维持位置基准，射频与成像载荷形成同源目标证据，任务计算机联锁禁击区、授权门槛和导引头；样机以搜索包线和剩余能量不闭合为判退条件。" * 4,
        "operational_process": "舰载单元装订最后可信区域后齐射，弹群在干扰空域分配扇区；复获目标后交叉复核，满足授权即攻击，否则越界弃攻，余弹依据毁伤确认转入补击。" * 4,
        "capability_effects": "形成外部更新中断后的有限区复获、正确拒打与受控毁伤能力，直接压缩敌舰脱离窗口；以复获时间、正确交战率、剩余能量和单位有效毁伤成本验收。" * 4,
        "winning_logic": "传统补击依赖连续航迹，对手可用拖延更新换取脱离时间；新构型迫使其在高速机动暴露与降低航速之间选择，并增加诱饵管理、分层拦截和电磁静默成本。" * 4,
    }

    assert capability_portrait_quality_issues(modules) == []


def test_portrait_quality_gate_flags_each_visibly_thin_module() -> None:
    modules = {
        "overview": "传统补击依赖连续航迹，敌方可借断链换取脱离时间；本装备把航迹过期改写为有界搜索与受控复核，恢复断链后的直接打击机会，压缩目标转移窗口，并迫使对手在持续机动暴露和降低行动节奏之间选择，打开失联条件下的持续猎歼任务。",
        "technology_implementation": "弹载任务计算机把目标证据、禁击边界和末制导授权联锁，避免失联后误击。",
        "operational_process": "装订任务边界后发射，弹体复核目标，满足授权则攻击，否则退出。",
        "capability_effects": "形成断链条件下的受控精确打击能力。",
        "winning_logic": "迫使对手同时压制导航、感知和任务判断，不能只靠断链解除威胁。",
    }

    issues = capability_portrait_quality_issues(modules)

    for label in (
        "概述",
        "装备与技术实现",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑机理",
    ):
        assert any(
            f"{label}明显过短，低于约180字告警线" in issue
            for issue in issues
        )


def test_portrait_quality_gate_requires_overview_to_center_disruptive_effect() -> None:
    modules = {
        "overview": "面向复杂背景，装备具备多模感知、边缘处理和自主打击能力，提升目标识别效率。",
        "technology_implementation": "弹载任务计算机把目标证据、禁击边界和末制导授权联锁，避免失联后误击。",
        "operational_process": "装订任务边界后发射，弹体复核目标，满足授权则攻击，否则退出。",
        "capability_effects": "形成断链条件下的受控精确打击能力。",
        "winning_logic": "迫使对手同时压制导航、感知和任务判断，不能只靠断链解除威胁。",
    }

    issues = capability_portrait_quality_issues(modules)
    assert any("概述明显过短，低于约180字告警线" in issue for issue in issues)
    assert any("概述未说明传统能力" in issue for issue in issues)
    assert any("概述未聚焦颠覆作战关系" in issue for issue in issues)


def test_portrait_quality_gate_rejects_generic_technology_paragraph() -> None:
    modules = {
        "overview": "断链后仍能受控打击授权目标。",
        "technology_implementation": "采用人工智能、分布式协同和智能化决策提升体系效能。",
        "operational_process": "装订任务边界后发射，弹体复核目标，满足授权则攻击，否则退出。",
        "capability_effects": "形成断链条件下的受控精确打击能力。",
        "winning_logic": "迫使对手同时压制导航、感知和任务判断，不能只靠断链解除威胁。",
    }

    assert any(
        "未绑定具体武器本体或工程模块" in issue
        for issue in capability_portrait_quality_issues(modules)
    )


def test_portrait_quality_gate_accepts_explicit_component_placement_language() -> None:
    modules = {
        "overview": "传统拦截按架次消耗，敌方数量优势会压穿火力通道；本装备改变交换关系并形成直接拒止战果。" * 3,
        "technology_implementation": (
            "导引头装在弹头前视窗，任务计算机搭载于弹体中段并与飞控、战斗部接口联锁，"
            "使目标发现、授权判断和末段作用在装备本体内闭合。"
        ) * 3,
        "operational_process": "发射单元完成授权与空域装订，弹体进入拦阻区后自主认领目标并在作用后退出。" * 3,
        "capability_effects": "形成不依赖逐目标火控通道的并行拦截能力，使后续波次无法利用再装填空窗突防。" * 3,
        "winning_logic": "把高价单发对廉价数量的旧交换改为低成本并行拦阻，迫使对手分散编组并延长暴露时间。" * 3,
    }

    issues = capability_portrait_quality_issues(modules)

    assert "装备与技术实现未说明关键原理如何落到装备本体" not in issues


def test_portrait_quality_gate_accepts_non_missile_weapon_body_components() -> None:
    modules = {
        "overview": "传统低空防空依赖逐目标射击，低慢小蜂群会耗尽火力通道；本装备把低空走廊变成持续物理拒止面并形成直接拦截战果。" * 3,
        "technology_implementation": (
            "伞骨装在浮体下方并撑开网幕，系留绞车与锚定结构吸收撞击动量后自动复位，"
            "网衣、伞骨和浮体共同把几何覆盖原理落到拦阻飞艇本体。"
        ) * 3,
        "operational_process": "班组完成走廊授权后展开浮体，网幕持续拦阻贴地目标，受损后补位或收网转移。" * 3,
        "capability_effects": "形成不占火控通道的持续低空物理拦截能力，迫使对手抬升或投入扫障兵力。" * 3,
        "winning_logic": "把逐目标射击交换改为预置障碍交换，敌方数量优势转化为碰撞风险与清障成本。" * 3,
    }

    issues = capability_portrait_quality_issues(modules)

    assert "装备与技术实现未绑定具体武器本体或工程模块" not in issues


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


def test_capability_classification_deduplicates_and_drops_equipment_forms() -> None:
    classification = normalize_capability_classification(
        {
            "primary_dimension": "失联自主精确打击",
            "secondary_dimensions": [
                "离线协同巡飞弹群",
                "打击维度",
                "目标识别能力",
            ],
            "classification_basis": "以直接打击为主，并依靠目标识别形成授权条件。",
        }
    )

    assert classification == {
        "primary_dimension": "打击维度",
        "secondary_dimensions": ["侦察感知维度"],
        "classification_basis": "以直接打击为主，并依靠目标识别形成授权条件。",
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


def test_nested_module_object_is_rejected_for_authoring_but_salvaged_for_display() -> None:
    from equipment_deep_research.agents.workflows.winning_flows.s6_authoring import (
        _extract_s6_module_content,
    )
    from equipment_deep_research.orchestration.capability_portrait import (
        coerce_portrait_module_prose,
        normalize_capability_portrait_text,
        portrait_module_looks_structured,
    )

    nested = {
        "key_technologies": [
            "边缘在线强化学习与神经形态芯片",
            "机间动态网状自组网与经验压缩编码",
            "低成本抗干扰弹道末制导与多模导引头",
        ],
        "system_architecture": (
            "三层架构：指控层负责任务规划；边缘计算层运行在线学习；"
            "通信层采用动态网状自组网。"
        ),
        "implementation_path": "分三阶段：实验室验证、对抗试验、实战集成验证。",
        "key_bottlenecks": {
            "intelligence_requirement": "机间通信量随规模上升，需特征压缩。",
            "latency_requirement": "在线学习需毫秒级反馈，机载算力有限。",
        },
        "keyword_context": "在线学习指机载实时辨识并调整攻击参数。",
    }
    dump = str(nested)

    assert portrait_module_looks_structured(nested)
    assert portrait_module_looks_structured(dump)
    assert (
        coerce_portrait_module_prose(
            nested,
            module_key="technology_implementation",
            allow_structured_salvage=False,
        )
        == ""
    )
    assert _extract_s6_module_content({"module_content": nested}, "technology_implementation") == ""
    assert _extract_s6_module_content({"module_content": dump}, "technology_implementation") == ""

    salvaged = coerce_portrait_module_prose(
        nested,
        module_key="technology_implementation",
        allow_structured_salvage=True,
    )
    assert salvaged
    assert "key_technologies" not in salvaged
    assert "system_architecture" not in salvaged
    assert "边缘在线强化学习与神经形态芯片" in salvaged
    assert "三层架构" in salvaged

    modules = {
        "overview": "敌方依托固定防御节奏消耗首波突防，本装备以代际经验继承改写蜂群交战窗口并恢复持续压制。",
        "technology_implementation": dump,
        "operational_process": "装订任务后投放，机群在线学习并动态组网，经验压缩后交接后续波次继续突防。",
        "capability_effects": "形成多波次经验继承下的持续突防与末端精确打击能力，压缩敌方拦截窗口。",
        "winning_logic": "传统蜂群依赖地面重规划，新构型把经验继承内化到机间交换，迫使对手同时应对学习与组网。",
    }
    issues = capability_portrait_quality_issues(modules)
    assert any("一次性写成中文正文" in issue or "结构化对象" in issue for issue in issues)
    assert assemble_capability_portrait_modules(modules) == ""

    portrait = (
        "概述：敌方依托固定防御节奏消耗首波突防，本装备以代际经验继承改写蜂群交战窗口。\n"
        f"- 装备与技术实现：{dump}\n"
        "- 关键作战流程：装订任务后投放，机群在线学习并动态组网。\n"
        "- 形成能力与作战效果：形成多波次经验继承下的持续突防能力。\n"
        "- 制胜逻辑机理：传统蜂群依赖地面重规划，新构型把经验继承内化到机间交换。"
    )
    normalized = normalize_capability_portrait_text(portrait)
    assert "key_technologies" not in normalized
    assert "system_architecture" not in normalized
    assert "边缘在线强化学习与神经形态芯片" in normalized
    assert "装备与技术实现：" in normalized


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
