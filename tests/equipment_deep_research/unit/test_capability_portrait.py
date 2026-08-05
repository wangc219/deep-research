from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_portrait,
    build_capability_title,
    normalize_capability_problem,
    normalize_operational_process,
    normalize_verification_plan,
    resolve_capability_portrait,
)
from equipment_deep_research.orchestration.winning import _normalize_direction_name


def test_capability_portrait_uses_governed_causal_structure() -> None:
    portrait = build_capability_portrait(
        scenario="强扰条件下的战役纵深火力窗口",
        problem="目标暴露时间短且传统火力响应链过长",
        principle="前置火力存在与任务闭环压缩原理",
        technologies=["受扰导航", "末段目标复核", "低带宽协同"],
        operational_concept="巡飞火力前置待机并由人在回路实施交战授权",
        operational_steps=["任务装订", "分散发射", "巡飞搜索", "授权交战", "毁伤评估"],
        capability="短时敏感目标持续猎歼",
        effect="压缩发现至毁伤时间并提高再打击组织效率",
        winning_mechanism="以时间前置换取决策优势并反转高价值平台依赖",
    )

    for marker in (
        "现役或类别级装备基线",
        "利用前置火力存在与任务闭环压缩原理",
        "采用受扰导航",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑机理",
    ):
        assert marker in portrait
    assert len(portrait) >= 500
    assert portrait.startswith("概述：")
    assert "- 装备与技术实现：" in portrait
    assert "- 发展与验证路径：" not in portrait


def test_deadline_fallback_exports_structured_capability_portrait_fields() -> None:
    rows = build_deadline_weapon_directions(topic="无人远程精确火力打击装备")

    assert len(rows) == 6
    for row in rows:
        assert row["target_scenario"]
        assert row["problem_statement"]
        assert row["scientific_principle"]
        assert row["enabling_technologies"]
        assert row["operational_concept"]
        assert row["operational_process"]
        assert row["capability_outcome"]
        assert row["winning_mechanism"]
        assert "制胜逻辑机理" in row["capability_portrait"]
        assert "\n- 装备与技术实现：" in row["capability_portrait"]
        assert not any(
            fragment in row["capability_portrait"]
            for fragment in (
                "任务的。",
                "效应器及。",
                "为JASSM-ER。",
                "不与JASSM-ER的空射平台，",
            )
        )

    by_name = {row["name"]: row["capability_portrait"] for row in rows}
    harop = by_name["失辐射等待反辐射巡飞弹"]
    assert harop.startswith("概述：面向")
    assert all(marker in harop.split("\n", 1)[0] for marker in ("针对", "利用", "采用", "通过", "形成", "实现"))
    assert "MALD-J类公开基线" not in harop
    assert "关机目标再捕获率、诱饵误接受率、安全拒打率" in harop
    assert "关机窗口、诱饵排除和真实节点续接" in harop

    barracuda = by_name["低成本批量巡航效应器"]
    assert barracuda.startswith("概述：面向")
    assert "PrSM类公开基线" not in barracuda
    assert "保持固定构型和明确任务边界" in barracuda
    assert "批次合格率、任务完成率、单位有效毁伤成本和补充周期" in barracuda
    assert "高价拦截弹与巡航效应器的成本交换" in barracuda


def test_capability_title_prefers_concrete_weapon_form_over_abstract_chain() -> None:
    title = build_capability_title(
        name="低空可消耗察打一体无人突击平台续接目标证据链",
        equipment_form="车载箱式、舰载箱式或空投式发射的固定翼小型无人平台",
        effect="对时敏目标实施侦察确认和精确打击",
    )

    assert title == "箱式发射低空可消耗察打一体无人机"
    assert "证据链" not in title


def test_capability_title_removes_upgrade_suffix_and_collapses_process_sentence() -> None:
    assert build_capability_title(
        name="Harop类间歇链路目标证据缓存与复核升级",
        equipment_form="固定构型长航时巡飞猎歼弹药",
        effect="链路恢复后快速完成授权猎歼",
    ) == "间歇链路证据缓存巡飞猎歼弹药"
    assert build_capability_title(
        name="分布式巡飞弹药续接首击后目标再确认与补射",
        equipment_form="箱式发射长航时巡飞弹药；察打一体小型无人攻击平台",
        effect="对首击漏毁目标实施补射",
    ) == "箱式发射长航时巡飞补射弹药"


def test_capability_title_preserves_unmanned_arsenal_carrier_identity() -> None:
    assert build_capability_title(
        name="岛链外长航时无人载弹母机",
        equipment_form="长航时低特征无人作战飞机，挂载防区外精确打击弹药",
        effect="机场受毁后接替空基防区外释能",
    ) == "岛链外长航时无人载弹母机"


def test_primary_equipment_anchor_beats_baseline_and_negative_comparison_mentions() -> None:
    evidence_cache = build_capability_portrait(
        scenario="强电磁压制下短时目标暴露与链路间歇阶段",
        problem="目标证据、时间戳和授权状态在断链后脱节",
        principle="固定弹载证据缓存与链路恢复后重新授权，不引入失联自主攻击",
        technologies=["弹载计算与存储", "低带宽证据摘要"],
        operational_concept="缓存目标证据，链路恢复后由人在回路复核并重新授权",
        operational_steps=[],
        capability="保留短时暴露机动目标的可复核证据",
        effect="减少重新搜索和重新关联时间",
        winning_mechanism="以证据缓存和重新授权闭合间歇链路任务",
        equipment_form="固定构型长航时巡飞猎歼弹药",
        baseline="公开IAI Harop长航时巡飞弹药基线",
        failure_boundary="弹上传感器不能可靠区分授权目标类别与诱饵时",
    )
    assert evidence_cache.startswith("概述：面向联合火力追击机动发射车、雷达和指挥节点时")
    assert "以固定构型长航时巡飞猎歼弹药为主装备" in evidence_cache
    assert "目标轨迹保持率、重新授权时延、正确拒打率" in evidence_cache
    assert "现有反辐射武器" not in evidence_cache

    low_altitude = build_capability_portrait(
        scenario="强电磁压制下首击后的短时补射窗口",
        problem="首击后外部毁伤评估和补射授权链难以及时闭合",
        principle="以批量固定构型降低战损补充成本",
        technologies=["预装目标包", "低速率授权与中止链路", "本机光电确认"],
        operational_concept="目标区外缘待机、本地再确认、受控补射和毁伤评估",
        operational_steps=[],
        capability="对首击漏毁和临机转移目标实施直接补射",
        effect="保留目标邻近空域的目视确认、局部BDA和补射能力",
        winning_mechanism="相较串行补射链，把目标再确认和补射嵌入可消耗作战装备",
        equipment_form="箱式发射长航时巡飞弹药",
        baseline="Harop类长航时巡飞弹药是最接近公开基线",
        failure_boundary="目标区持续强防空覆盖且无低空进入廊道时",
    )
    assert low_altitude.startswith("概述：面向强电磁压制下首击后的短时补射窗口")
    assert "目标再发现率、补射时延、单位有效毁伤成本和平台损耗率" in low_altitude
    assert "现有反辐射武器" not in low_altitude
    assert "批次合格率" not in low_altitude


def test_legacy_evidence_cache_gap_drops_old_mechanism_and_cross_card_problem() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem=(
            "现有基线“公开Harop长航时巡飞弹药基线”尚不能在“把链路中断后丢失候选目标轨迹，"
            "改为由弹载组件缓存目标证据并在链路恢复后重新授权”变化后稳定形成："
            "在通信间歇条件下保留短时暴露目标的可复核证据"
        ),
        principle="弹载证据缓存、链路恢复复核与人在回路重新授权",
        technologies=["弹上传感处理", "低带宽证据摘要"],
        operational_concept="前沿在位搜索、断链保持、恢复复核和受控交战",
        operational_steps=[],
        capability="保留短时暴露机动目标的可复核证据",
        effect="减少重新搜索和重新关联时间",
        winning_mechanism="把断链目标丢失转化为可审计任务状态",
        equipment_form="固定构型长航时巡飞猎歼弹药",
        baseline="公开Harop长航时巡飞弹药基线",
    )

    overview = portrait.split("\n", 1)[0]
    assert "针对短时暴露目标的候选轨迹、时间戳、传感摘要和授权状态会在断链中丢失" in overview
    assert "针对现役反辐射弹药" not in overview
    assert "重构任务闭环，利用" not in overview
    assert overview.count("利用") == 1


def test_low_altitude_portrait_rejects_inherited_anti_radiation_gap() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下首击后的短时补射窗口",
        problem=(
            "现役反辐射弹药难以跨越关机窗口、排除诱饵辐射源并续接压制真实节点，"
            "利用首击后目标区附近在位火力重构任务闭环"
        ),
        principle="以目标区附近在位察打压缩首击后再确认与补射时间",
        technologies=["低空组合导航", "本机光电确认", "低速率授权链路"],
        operational_concept="目标区外缘待机、本地复核、受控补射和毁伤评估",
        operational_steps=[],
        capability="对首击漏毁和临机转移目标实施直接补射",
        effect="保留局部毁伤评估和补射能力",
        winning_mechanism="压缩对手转移、修复和伪装时间",
        equipment_form="箱式发射低空可消耗察打一体无人携弹平台",
    )

    overview = portrait.split("\n", 1)[0]
    assert "针对首击漏毁、临机转移目标的外部毁伤评估与再确认链" in overview
    assert "反辐射" not in overview
    assert "关机窗口" not in overview
    assert "重构任务闭环，利用" not in overview


def test_legacy_prsm_gap_keeps_problem_separate_from_governed_principle() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem=(
            "现有基线“PrSM公开基线”尚不能在“把基础弹体扩展为固定多模末制导段”"
            "变化后稳定形成：对战役纵深机动目标实施远程精确毁伤"
        ),
        principle="通过开放架构接口安装固定多模末制导段并完成末段再捕获",
        technologies=["目标包有效期管理", "组合导航可信评估", "多模再捕获"],
        operational_concept="分散接令、机动发射、末段再捕获和安全拒打",
        operational_steps=[],
        capability="战役纵深机动目标远程精确毁伤",
        effect="缩短重新发现目标后的火力闭环",
        winning_mechanism="压缩目标机动与坐标过期收益",
        equipment_form="固定构型地面发射远程精确制导导弹",
        baseline="PrSM公开开放架构基线",
    )

    overview = portrait.split("\n", 1)[0]
    assert "针对目标坐标过期、导航受扰和末端不可确认" in overview
    assert "把基础弹体扩展为固定多模末制导段重构任务闭环" not in overview
    assert "重构任务闭环，利用" not in overview


def test_foreign_model_remains_baseline_not_primary_equipment_subject() -> None:
    portrait = build_capability_portrait(
        scenario=(
            "强电磁压制下精确打击任务续接装备研究中的目标信息稀疏、"
            "链路间歇和导航受扰任务阶段"
        ),
        problem=(
            "公开资料能够证明JASSM-ER防区外打击属性，但不能证明强欺骗条件下的任务闭合质量"
        ),
        principle="导航可信度与末端证据共同门控毁伤释放",
        technologies=["组合导航可信评估", "末段身份复核"],
        operational_concept="防区外释放、低可探测突防、末端复核和受控弃攻",
        operational_steps=[],
        capability="战役纵深固定和准固定节点受控补击",
        effect="降低目标包过期导致的错误消耗",
        winning_mechanism="不把JASSM-ER与地射导弹混成一类",
        equipment_form="JASSM-ER类空射低可探测防区外巡航导弹及任务规划升级组件",
        baseline="JASSM-ER公开空射防区外打击基线",
    )

    overview, modules = portrait.split("\n", 1)
    assert "联合战役首轮纵深突击后" in overview
    assert "针对导航欺骗、目标包过期和末端身份不确定" in overview
    assert "针对公开资料" not in overview
    assert "以空射隐身防区外巡航导弹及其抗扰导航" in overview
    assert "为主装备" in overview
    assert "以JASSM-ER类" not in overview
    assert "形成在一体化防空与导航欺骗叠加条件下" in overview
    assert "压缩敌防空体系恢复" in overview
    assert "JASSM-ER公开空射防区外打击基线为公开对照" in modules
    assert "核心机理是以低可探测防区外投送、抗扰导航和末端复核" in modules
    assert "核心机理是不把JASSM-ER" not in modules


def test_capability_portrait_does_not_destructively_trim_long_modules() -> None:
    repeated = "任务链断点、接口约束、对手反适应与代表性干扰条件需要联合验证，" * 12

    portrait = build_capability_portrait(
        scenario=repeated,
        problem=repeated,
        principle=repeated,
        technologies=[repeated] * 6,
        operational_concept=repeated,
        operational_steps=[repeated] * 6,
        capability=repeated,
        effect=repeated,
        winning_mechanism=repeated,
        baseline=repeated,
        development_path=repeated,
        failure_boundary=[repeated] * 4,
        verification_plan=repeated,
    )

    assert len(portrait) > 800
    assert "任务链断点、接口约束、对手反适应与代表性干扰条件需要联合验证" in portrait
    assert "发展与验证路径" not in portrait
    assert "应降级或重新校准" in portrait
    assert portrait.endswith("。")


def test_resolve_capability_portrait_rebuilds_bloated_non_equipment_overview() -> None:
    detail = "具体装备构型、任务变量、对抗样本、验收指标和停止转段门槛分别展开论证，" * 5
    portrait = "\n".join(
        [
            (
                "概述：面向强对抗任务场景，针对任务链断点，利用任务状态压缩原理，采用受扰导航与"
                f"末段复核技术，通过分散进入、目标确认、受控交战和毁伤评估流程，形成持续精确打击能力，"
                f"实现压缩毁伤闭环作战效果。{detail}。"
            ),
            f"- 装备与技术实现：{detail}。",
            f"- 关键作战流程：{detail}。",
            f"- 形成能力与作战效果：{detail}。",
            f"- 制胜逻辑机理与对抗边界：{detail}。",
            f"- 发展与验证路径：{detail}。",
        ]
    )

    resolved = resolve_capability_portrait(
        portrait,
        scenario="fallback scenario",
        problem="fallback problem",
        principle="fallback principle",
        technologies=["fallback technology"],
        operational_concept="fallback concept",
        operational_steps=["fallback step"],
        capability="fallback capability",
        effect="fallback effect",
        winning_mechanism="fallback mechanism",
    )

    overview = resolved.split("\n", 1)[0]
    assert resolved != portrait
    assert 120 <= len(overview.removeprefix("概述：")) <= 360
    assert "为主装备" in overview
    assert len(resolved) > 900


def test_capability_portrait_overview_is_concise_weapon_specific_and_combat_focused() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下远海反舰齐射后的补击阶段",
        problem="外部目标航迹与中途更新在GNSS拒止下中断",
        principle="弹上有限搜索与多模证据门控交战",
        technologies=["抗欺骗组合导航", "被动射频与光电复核"],
        operational_concept="舰艇发射后进入授权目标活动区搜索复核并受控交战",
        operational_steps=["任务装订", "发射进入", "搜索复核", "交战评估"],
        capability="断链条件下海上机动目标复获与直接毁伤",
        effect="续接反舰火力并压缩敌编队重组时间",
        winning_mechanism="把连续外部更新依赖转为弹上有限闭环",
        equipment_form="舰射长航时反舰巡飞猎歼弹药",
    )

    overview = portrait.split("\n", 1)[0].removeprefix("概述：")
    assert 120 <= len(overview) <= 360
    assert "舰射长航时反舰巡飞猎歼弹药为主装备" in overview
    assert "远海反舰齐射后的补击阶段" in overview
    assert "搜索复核—交战/拒打—毁伤评估与补射接替" in overview
    assert "续接反舰火力" in overview
    assert all(
        overview.count(marker) == 1
        for marker in ("面向", "针对", "利用", "采用", "通过", "形成", "实现")
    )


def test_resolve_rebuilds_research_framed_overview_into_combat_scene() -> None:
    detail = "装备构型、任务流程、对抗边界、验收指标和停止转段条件均已展开，" * 8
    existing = "\n".join(
        [
            (
                "概述：面向强电磁压制下精确打击任务续接装备研究中的导航受扰任务阶段，"
                "针对公开基线不能证明强欺骗条件下的任务闭合质量，利用任务门控原理，"
                "采用组合导航与末段复核技术，通过防区外释放和受控交战流程，形成纵深补击能力，"
                f"实现持续毁伤效果。{detail}"
            ),
            f"- 装备与技术实现：{detail}",
            f"- 关键作战流程：{detail}",
            f"- 形成能力与作战效果：{detail}",
            f"- 制胜逻辑机理与对抗边界：{detail}",
            f"- 发展与验证路径：{detail}。",
        ]
    )

    resolved = resolve_capability_portrait(
        existing,
        scenario="强电磁压制下精确打击任务续接装备研究中的导航受扰任务阶段",
        problem="公开基线不能证明强欺骗条件下的任务闭合质量",
        principle="导航可信度与末端目标证据共同约束毁伤释放",
        technologies=["组合导航可信评估", "末段身份复核"],
        operational_concept="防区外多轴释放、低可探测突防和末段复核",
        operational_steps=[],
        capability="战役纵深高价值节点受控补击",
        effect="保持联合战役纵深破击节奏",
        winning_mechanism="压缩对手预警拦截和修复时间",
        equipment_form="JASSM-ER类空射低可探测防区外巡航导弹",
        baseline="JASSM-ER公开基线",
    )

    overview = resolved.split("\n", 1)[0]
    assert "联合战役首轮纵深突击后" in overview
    assert "针对公开基线" not in overview


def test_overview_normalizes_leading_equipment_connector_and_incomplete_transition() -> None:
    portrait = build_capability_portrait(
        scenario="西太平洋岛礁海上拒止阶段",
        problem="目标航迹停更后岸基火力只能等待上级火控更新",
        principle="任务包自治与目标质量门控",
        technologies=["抗拒止定位授时", "齐射规划"],
        operational_concept="预授权任务包约束下的断链续射",
        operational_steps=[],
        capability="岸基反舰发射车断链目标续接与安全拒打",
        effect="把前沿岸基反舰单元从等待上级火控更新的发射节点",
        winning_mechanism="压缩目标再暴露后的补射决策时间",
        equipment_form="以NMESIS类岸基反舰发射系统为公开对照的改进型反舰发射车",
        baseline="NMESIS类岸基反舰发射系统",
    )

    overview = portrait.split("\n", 1)[0]
    assert "以以" not in overview
    assert "短停释放反舰导弹并射后快速转移" in overview
    assert "压缩其岛链通道机动自由" in overview


def test_capability_title_adds_supported_novelty_to_generic_weapon_class() -> None:
    title = build_capability_title(
        name="反辐射巡飞弹",
        equipment_form="车载可消耗巡飞弹药，配置被动射频寻的与末端光电确认传感器",
        effect="对间歇开机雷达实施持续搜索和压制毁伤",
    )

    assert title == "多模复核反辐射巡飞猎歼弹"


def test_capability_title_removes_numbered_prefix_and_names_expendable_weapon_family() -> None:
    title = build_capability_title(
        name="1：反适应后转向先消耗低空拦截屏障的可消耗诱打-毁伤弹药族",
        equipment_form="低成本可消耗攻击载荷族、中远程巡飞弹药和无人火力打击平台",
        effect="诱导并消耗低空拦截资源后实施末端毁伤",
    )

    assert title == "可消耗诱打毁伤弹药族"
    assert not title.startswith("1")


def test_capability_names_remove_internal_lettered_candidate_prefixes() -> None:
    source = "A. 批量可消耗低空无人携弹平台族：首击后本地再确认与补射"

    assert _normalize_direction_name(source) == "批量可消耗低空无人携弹平台族：首击后本地再确认与补射"
    assert build_capability_title(
        name=source,
        equipment_form="箱式发射低空可消耗察打一体无人携弹平台",
        effect="首击后本地再确认与直接补射",
    ) == "箱式发射低空可消耗察打一体无人机"


def test_capability_problem_keeps_one_complete_equipment_local_gap() -> None:
    problem = (
        "公开基线能够证明远程空射精确打击对象存在，但不能证明强欺骗条件下的任务闭合质量；"
        "基线导弹可执行反辐射压制，但缺少关机目标复核；"
        "现有平台多强调侦察或打击单一任务，缺少携带毁伤载荷并"
    )

    normalized = normalize_capability_problem(
        problem,
        fallback="空射巡航导弹任务闭环存在断点",
    )

    assert normalized == "公开基线能够证明远程空射精确打击对象存在，但不能证明强欺骗条件下的任务闭合质量"
    assert not normalized.endswith("并")
    assert "反辐射" not in normalized


def test_operational_process_keeps_short_model_flow_visible_for_upstream_repair() -> None:
    steps = normalize_operational_process(
        ["保留空射防区外投送和低可探测突防基线", "验证导航可信评估"],
        equipment_identity="JASSM-ER空射低可探测防区外巡航导弹",
    )

    assert steps == ["保留空射防区外投送和低可探测突防基线", "验证导航可信评估"]


def test_operational_process_does_not_select_flow_from_public_model_name() -> None:
    steps = normalize_operational_process(
        ["装订任务", "释放效应器"],
        equipment_identity=(
            "MALD-J空射可消耗诱饵与电子攻击效应器；"
            "为远程精确制导弹药创造突防窗口"
        ),
    )

    assert steps == ["装订任务", "释放效应器"]


def test_operational_process_preserves_unfamiliar_codex_authored_equipment_flow() -> None:
    authored = [
        "任务前将主装备分散配置到许可区域并完成安全自检",
        "按方案限定的运动方式进入责任区并保持低特征待机",
        "由本装备传感与授权逻辑确认目标类别和交战条件",
        "满足门槛时实施直接效应，不满足时拒打或退出",
        "形成任务摘要并由同类节点接替下一轮行动",
    ]

    assert normalize_operational_process(
        authored,
        equipment_identity="玄羽-7跨介质任务载体；首次出现且不在任何本地装备词表中",
    ) == authored


def test_cruise_mother_munition_preserves_codex_authored_heterogeneous_flow() -> None:
    identity = (
        "异构子效应器巡航母弹；远程巡航母弹，内置诱饵、被动侦察、"
        "短时电子压制和小型毁伤子弹药舱"
    )

    authored_steps = [
        "装订母弹目标区、子效应器释放规则和安全边界",
        "母弹以抗扰导航进入岛链外缘",
        "按目标证据分时释放诱饵、侦察、电子压制或有限毁伤子效应器",
        "汇总窗口摘要并把剩余任务转交后续精打火力",
    ]
    steps = normalize_operational_process(
        authored_steps,
        equipment_identity=identity,
    )
    plan = normalize_verification_plan(
        [],
        equipment_identity=identity,
        failure_boundary="子弹药释放安全不可控或母弹被远距拦截导致载荷集中损失不可接受",
    )

    assert steps == authored_steps
    assert "母弹中途被拦截" in plan[0]
    assert "子效应器安全分离率" in plan[1]


def test_resolver_does_not_guess_cross_card_leakage_from_weapon_keywords() -> None:
    portrait = resolve_capability_portrait(
        (
            "概述：面向西太首轮突防阶段，针对敌防空火控链，利用诱饵塑造威胁响应，"
            "采用平台特征模拟与电子攻击载荷，通过诱导雷达响应和受控干扰，"
            "以远程巡航母弹为主装备，形成诱骗压制能力，实现主攻波次开窗。\n"
            "- 装备与技术实现：以MALD式诱饵和电子攻击为主。\n"
            "- 关键作战流程：模拟平台特征并诱导雷达开机。\n"
            "- 形成能力与作战效果：形成电子压制窗口。\n"
            "- 制胜逻辑机理与对抗边界：迫使雷达开机或静默。"
        ),
        name="异构子效应器巡航母弹",
        scenario="前沿机场和固定阵地受毁后的首轮续击阶段",
        problem="单功能弹药需要多次独立起射和连续链路协同",
        principle="远程母载运输与分时异构释能",
        technologies=["模块化子舱", "安全分离", "抗扰组合导航"],
        operational_concept="一次起射后分时释放诱饵、侦察、压制和有限毁伤子效应器",
        operational_steps=["装订任务", "母弹进入", "分时释放", "窗口通报"],
        capability="跨岛链分时多效应释能",
        effect="为后续精打火力制造时间方位窗口",
        winning_mechanism="把多平台多次起射压入一枚远程母弹",
        equipment_form=(
            "远程巡航母弹，内置诱饵、被动侦察、短时电子压制和小型毁伤子弹药舱"
        ),
        baseline="JASSM与MALD等分立公开基线",
        failure_boundary="子效应器不能安全分离或母弹集中损失不可接受",
    )

    assert "MALD式诱饵和电子攻击为主" in portrait
    assert "模拟平台特征并诱导雷达开机" in portrait


def test_verification_plan_has_environment_comparator_metrics_and_stop_gate() -> None:
    plan = normalize_verification_plan(
        ["开展接口联试"],
        equipment_identity="关机目标再捕获反辐射弹药",
        failure_boundary="末段证据不能区分真实雷达与诱饵",
    )

    assert len(plan) == 3
    assert "关机机动" in plan[0] and "诱饵辐射" in plan[0]
    assert "未改装" in plan[1] and "再捕获率" in plan[1]
    assert "停止转段" in plan[2] and "拒打" in plan[2]


def test_verification_plan_reorders_complete_model_rows_by_decision_sequence() -> None:
    plan = normalize_verification_plan(
        [
            "预注册通过与淘汰门槛，证据不闭合时停止转段",
            "与串行任务链基线比较任务完成率和尾部时延",
            "在弱网、PNT受扰和目标机动条件下开展多波次对抗",
        ],
        equipment_identity="箱式发射低空可消耗察打一体无人机",
    )

    assert "条件" in plan[0]
    assert "基线" in plan[1]
    assert "门槛" in plan[2]


def test_verification_plan_prefers_labeled_failure_boundary_over_future_trigger() -> None:
    plan = normalize_verification_plan(
        [],
        equipment_identity="PrSM类开放架构多模末制导导弹",
        failure_boundary=[
            "未来触发：对海上机动目标潜在增益较高",
            "失效边界：目标位移超过末段重捕获能力且无法获得新更新时",
        ],
    )

    assert "目标位移超过末段重捕获能力" in plan[2]
    assert "未来触发" not in plan[2]
    assert "时，则" not in plan[2]


def test_verification_plan_does_not_duplicate_leading_conditional() -> None:
    plan = normalize_verification_plan(
        [],
        equipment_identity="近域反无人拦截弹车",
        failure_boundary="失效边界：若来袭密度超过拦截车弹药容量，必须优先撤收",
    )

    assert "若若" not in plan[2]
    assert "若来袭密度超过拦截车弹药容量" in plan[2]


def test_verification_plan_does_not_append_a_second_then_clause() -> None:
    plan = normalize_verification_plan(
        [],
        equipment_identity="短距起降低特征无人火力母机",
        failure_boundary="若载荷过小或生存性不足，则仅作为有人确认弹药释放平台使用",
    )

    assert plan[2].count("则") == 1
    assert "则仅作为有人确认弹药释放平台使用，并停止转段" in plan[2]


def test_short_takeoff_unmanned_fire_carrier_uses_platform_process_and_metrics() -> None:
    identity = (
        "短距起降低特征无人火力母机；短距起降低特征无人机体、模块化载架、"
        "诱饵与小型巡航/巡飞弹挂载和人在回路释放组件"
    )

    authored_steps = [
        "从滑行道或简易场地短距起飞",
        "沿低特征航路进入授权释放区",
        "人在回路确认后先投诱饵再释放小型打击弹",
        "保留未用载荷并转场退出或由下一架接替",
    ]
    steps = normalize_operational_process(authored_steps, equipment_identity=identity)
    plan = normalize_verification_plan(
        [],
        equipment_identity=identity,
        failure_boundary="载荷过小、生存性不足或混载分离不可控",
    )
    portrait = build_capability_portrait(
        name="短距起降低特征无人火力母机",
        scenario="主跑道受毁但滑行道和简易场地仍可使用",
        problem="有人载机无法维持诱骗与轻型打击架次",
        principle="利用短距起降、低特征航迹和模块化混载降低机场依赖",
        technologies=["短距起降", "模块化载架", "抗扰导航", "人在回路释放"],
        operational_concept="进入授权释放区后先投诱饵再释放小型打击弹药",
        operational_steps=steps,
        capability="跑道受损后的无人空中诱骗与轻型打击",
        effect="维持空中释能并迟滞敌防空重组",
        winning_mechanism="把完整跑道和有人载机从必要条件降为可替代条件",
        equipment_form=identity.split("；", 1)[1],
        failure_boundary="载荷过小、生存性不足或混载分离不可控",
    )

    assert steps == authored_steps
    assert "混载分离异常" in plan[0]
    assert "简易场地出动成功率" in plan[1]
    assert "利用利用" not in portrait
    assert "利用以" not in portrait
    assert "无人火力母机" in portrait
    assert "批次合格率" not in portrait


def test_r13_potentially_submerged_launcher_uses_sea_launch_process_and_metrics() -> None:
    identity = (
        "无人潜浮远射巡飞弹舱；无人半潜或浮潜弹舱，集成封存、自检、"
        "授权保险和多枚远射巡飞弹发射单元"
    )

    authored_steps = [
        "危机期在岛链海域分散布放潜浮弹舱",
        "以低特征航位保持和被动警戒持续待机",
        "收到认证任务包后复核授权与弹舱状态",
        "条件满足时受控发射远射巡飞弹，否则拒打",
        "发射后转移沉默并由邻近弹舱接替补射",
    ]
    steps = normalize_operational_process(authored_steps, equipment_identity=identity)
    plan = normalize_verification_plan(
        [],
        equipment_identity=identity,
        failure_boundary="海况超限、授权无法认证或封存失效率过高",
    )

    joined_steps = "；".join(steps)
    joined_plan = "；".join(plan)
    assert all(marker in joined_steps for marker in ("海域", "待机", "弹舱", "发射", "转移"))
    assert "多路径低空进入目标区" not in joined_steps
    assert all(marker in joined_plan for marker in ("海况", "弹舱状态", "受控发射", "连续补击"))
    assert "目标再发现率" not in joined_plan
    assert steps == authored_steps


def test_r13_counter_swarm_escort_uses_interception_process_and_metrics() -> None:
    identity = (
        "护射低空反蜂群拦截弹；车载或可快速架设的小型低空拦截弹发射单元，"
        "配套近程探测和有限非动能变体"
    )

    authored_steps = [
        "伴随被护火力节点部署并建立近程告警",
        "发现低空小目标后完成威胁分类与交战排序",
        "按有人监督或预授权规则实施分层拦截",
        "确认拦截效果并掩护被护节点发射、撤收或补弹",
    ]
    steps = normalize_operational_process(authored_steps, equipment_identity=identity)
    plan = normalize_verification_plan(
        [],
        equipment_identity=identity,
        failure_boundary="若探测漏警高、拦截弹交换比不利或己方电磁压制造成互扰",
    )

    joined_steps = "；".join(steps)
    joined_plan = "；".join(plan)
    assert all(marker in joined_steps for marker in ("被护节点", "发现低空", "拦截", "撤收"))
    assert "受控补射" not in joined_steps
    assert all(marker in joined_plan for marker in ("低空", "拦截", "节点", "单位有效拦截成本"))
    assert "目标再发现率" not in joined_plan
    assert steps == authored_steps


def test_capability_portrait_preserves_specific_gap_and_complete_transition_clause() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem=(
            "现役反辐射武器对短时开机、关机转移和假辐射源的持续猎杀与目标复核能力不足；"
            "现有公开基线仅支持类别级判断，后续字段为跨方向共享限制。"
        ),
        principle=(
            "从规避或硬抗敌方电磁压制后继续打击转为利用敌方压制开机窗口实施"
            "被动探测、巡飞待机和反辐射毁伤"
        ),
        technologies=["被动辐射探测", "末端光电确认", "任务约束接口"],
        operational_concept="巡飞待机后按目标真实性实施受控交战",
        operational_steps=["进入搜索空域", "复核辐射源", "授权交战", "效果评估"],
        capability="真实辐射节点持续压制",
        effect="降低被诱饵吸引并制造后续精确打击窗口",
        winning_mechanism="把敌方持续压制所需的电磁辐射转化为可攻击暴露",
    )

    assert "现役反辐射武器对短时开机、关机转移和假辐射源" in portrait
    assert "利用对手辐射暴露换取被动定位" in portrait
    assert "宽带被动射频侦测、辐射源记忆区、失辐射等待" in portrait
    assert "巡飞待机和反。" not in portrait


def test_capability_portrait_does_not_repeat_scenario_relation_prefix() -> None:
    portrait = build_capability_portrait(
        scenario="面向2030年前后强对抗、通信受限和导航受扰环境中的短时火力窗口",
        problem="现役装备难以在弱网条件下持续闭合任务链",
        principle="任务状态压缩与边缘受控授权",
        technologies=["组合导航", "低带宽任务更新"],
        operational_concept="分散部署、目标复核、受控交战和毁伤评估",
        operational_steps=["任务装订", "平台进入", "目标复核", "授权交战"],
        capability="弱网条件下持续精确打击",
        effect="压缩短时目标发现至毁伤闭环",
        winning_mechanism="改变对手的时间和拦截成本交换关系",
    )

    assert "2030年前后强对抗、通信受限和导航受扰环境" in portrait
    assert "面向面向" not in portrait


def test_capability_portrait_normalizes_governed_verb_prefixes() -> None:
    portrait = build_capability_portrait(
        scenario="强压制环境下的补射窗口",
        problem="首轮打击后目标包过期且补射授权中断",
        principle="任务状态压缩与受控授权",
        technologies=["PNT可信评估", "低带宽BDA摘要"],
        operational_concept="发射单元按授权门限生成补射或等待建议",
        operational_steps=["装订任务状态", "复核目标", "申请补射", "回传毁伤摘要"],
        capability="形成断链条件下可审计补射能力",
        effect="使现役远火转向有条件再分配火力",
        winning_mechanism="把任务断裂转化为受控火力延迟",
        failure_boundary=["当目标身份无法确认时，只能等待或中止"],
    )

    assert "形成形成" not in portrait
    assert "实现使" not in portrait
    assert "时，只能等待或中止时应" not in portrait


def test_capability_portrait_merges_landing_gap_mechanism_effect_and_evolution() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem=(
            "现有Harop与AARGM公开基线尚不能跨越关机窗口、排除诱饵发射源，"
            "并续接压制真实电磁节点"
        ),
        principle="把敌方持续压制所需的辐射转化为可攻击暴露",
        technologies=["被动射频侦测", "末端EO确认", "低带宽授权接口"],
        operational_concept="巡飞待机、本地复核和受控交战",
        operational_steps=[
            "反辐射巡飞弹在压制区外缘分散待机",
            "当辐射源暴露时，弹药本地完成候选排序和目标确认",
            "直接效果是制造开机遭猎歼、关机失压制的两难",
        ],
        capability="真实辐射节点持续压制与猎歼",
        effect="为后续远程精确火力恢复短时目标更新和授权窗口",
        winning_mechanism=(
            "公开基线对比与工程增量说明较长；通过分散待机、被动侦测、末端复核和受控交战，"
            "制造开机遭猎歼、关机失压制的两难并改变暴露与拦截成本交换关系"
        ),
        equipment_form=(
            "主装备对象：反压制反辐射巡飞猎歼弹药；"
            "装备形态：车载、舰载或前沿箱式发射的可消耗巡飞弹药；"
            "作战运用：在压制区外缘分散待机"
        ),
        baseline="以IAI Harop与AARGM公开能力为对照",
        development_path=(
            "开展工程样机、体系接口和对抗试验；"
            "通过条件为构建含真实压制源、诱饵、友邻辐射源和间歇开机目标的试验场；"
            "测量误击、拒打和弹药消耗率"
        ),
        failure_boundary=["失效边界：友邻电磁源密集且白名单不完整时，误判风险不可接受"],
    )

    assert len(portrait) >= 500
    assert "型号落点为长航时多模复核反辐射巡飞猎歼弹" in portrait
    assert "围绕“关机窗口、诱饵排除和真实节点续接”闭合任务链" in portrait
    assert "直接实现为后续远程精确火力恢复短时目标更新和授权窗口" in portrait
    assert "开机维持空情与火控、关机失去探测射击机会" in portrait
    assert "发展与验证路径" not in portrait
    assert "预警雷达、火控雷达和电子战车辆" in portrait
    assert "误判风险不可接受，应降级或重新校准" in portrait


def test_dynamic_portrait_filters_internal_reasoning_and_keeps_specific_mechanism() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem=(
            "现有低空续接火力尚不能在首击后完成本地再确认、BDA和补射授权"
        ),
        principle=(
            "把S2的关键变量从后方是否持续更新目标包改为"
            "首击后电磁压制窗口内是否仍有可滞空、可目视再确认、可直接补射的低成本作战主体"
        ),
        technologies=["预装目标包接口", "低速率授权链路", "本机光电确认"],
        operational_concept="分散部署、目标区外缘待机、受控补射和毁伤评估",
        operational_steps=[
            "强电磁压制使外部侦察回传和毁伤评估链路不稳定，传统补射链难以及时闭合",
            "在首轮火力前后释放低空无人携弹平台进入目标区外缘待机",
            "平台以本机传感器完成目标再确认和毁伤观察，并按授权门槛实施补射",
            "S2增量不是增强通信背景，而是把续接火力节点前推到目标邻近空域",
        ],
        capability="对首击漏毁和临机转移目标实施直接补射",
        effect="保留目标邻近空域的目视确认、局部BDA和补射能力",
        winning_mechanism=(
            "相较传统远程导弹首击、外部ISR评估、再次发射的串行链条，"
            "该分支把S2中的目标再确认和补射嵌入可消耗直接作战装备，"
            "先布设可滞空火力再等待证据窗口"
        ),
        equipment_form="箱式发射低空可消耗察打一体无人携弹平台",
        baseline="Harop类长航时巡飞弹药",
        development_path=(
            "围绕低空无人携弹平台开展工程样机和接口试验；"
            "通过条件为比较串行补射链与巡飞续接链的再发现率、补射时延和单位有效毁伤成本；"
            "进行红方假目标、烟尘和近程防空压力测试"
        ),
        failure_boundary=["目标区持续强防空覆盖且无低空进入廊道时"],
    )

    assert "S2" not in portrait
    assert "增量不是" not in portrait
    assert "在首轮火力前后释放低空无人携弹平台进入目标区外缘待机" in portrait
    assert "本机传感器" in portrait
    assert "受控补射" in portrait
    assert "目标再发现率、补射时延、单位有效毁伤成本和平台损耗率" in portrait
    assert "目标区附近在位确认和补射" in portrait
    assert "发展与验证路径" not in portrait
    overview = portrait.split("\n", 1)[0].removeprefix("概述：")
    assert 120 <= len(overview) <= 360
    assert overview.count("箱式发射低空可消耗察打一体无人携弹平台") == 1
    assert "单一主体为" not in overview
    assert "主装备对象为" not in overview
    assert "具备察打一体能力的" not in overview


def test_oversized_portrait_never_trims_acceptance_or_verification_contract() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制、导航受扰和低空拦截叠加条件下的短时火力窗口",
        problem="首击后目标转移、外部毁伤评估中断且补射授权链难以及时闭合",
        principle="把目标区附近预置的可消耗火力节点作为本地再确认和补射主体",
        technologies=[
            "预装目标包与禁击区任务接口",
            "低带宽授权、中止和毁伤摘要接口",
            "多模末端目标复核传感器",
        ],
        operational_concept="分散部署、目标区外缘待机、本地复核、受控补射和多波次接替",
        operational_steps=[
            "箱式发射单元装订目标包、禁击区、授权边界和失联规则后分批释放",
            "平台沿多路径低空进入目标区外缘并以本机传感器完成局部搜索和目标再确认",
            "发现漏毁、转移或短时暴露目标后回传证据摘要并按授权门槛实施受控补射",
            "完成局部毁伤评估、剩余平台重组和下一波次接替，链路失效时安全中止",
        ],
        capability="对首击漏毁和临机转移目标实施本地再确认与直接补射",
        effect="在主数据链不稳定时保留目视确认、局部毁伤评估和补射能力",
        winning_mechanism=(
            "把侦察、确认、毁伤评估和补射压缩进同一可消耗作战主体，"
            "以目标区附近的在位火力压缩对手转移、修复和伪装时间"
        ),
        equipment_form="箱式发射长航时低空可消耗察打一体无人携弹平台",
        baseline="远程精确弹药首击、外部ISR评估和后方再次发射的串行补射链",
        development_path=(
            "先完成预装目标包、低速率抗扰授权与中止链路工程样机和接口联试，"
            "再开展多波次半实物和实装对抗"
        ),
        failure_boundary="目标区低空通道被连续近程防空覆盖且平台无法进入或待机",
        verification_plan=[
            "在弱网、PNT受扰、低空拦截、平台损耗和目标机动条件下开展多波次对抗",
            "与串行补射链基线比较再发现率、补射时延和单位有效毁伤成本",
            "预注册通过与淘汰门槛，证据不能闭合时停止转段",
        ],
    )

    assert "以目标再发现率、补射时延、单位有效毁伤成本和平台损耗率验收" in portrait
    assert "发展与验证路径" not in portrait
    assert "目标区低空通道被连续近程防空覆盖" in portrait
    assert "应降级或重新校准" in portrait


def test_electronic_attack_portrait_uses_suppression_specific_metrics() -> None:
    portrait = build_capability_portrait(
        scenario="远程精确打击突防窗口",
        problem="防空探测与火控链压缩主攻武器突防窗口",
        principle="以多轴诱饵和电子攻击迫使威胁雷达响应并错配火控资源",
        technologies=["威胁库", "任务规划接口", "既有干扰载荷"],
        operational_concept="多轴释放、响应诱导、受控压制和窗口评估",
        operational_steps=["任务装订", "多轴释放", "选择干扰响应", "发布压制摘要"],
        capability="主攻武器进入前的防空探测与火控链压制",
        effect="扩大后续武器的安全突防与末端更新窗口",
        winning_mechanism="以可消耗诱饵和电子攻击改变对手火控资源分配",
        equipment_form="MALD-J空射可消耗诱饵与电子攻击效应器",
    )

    assert "威胁雷达响应率、有效压制窗口、后续突防增益和单位诱饵任务成本" in portrait
    assert "持续开机暴露、火控资源错配" in portrait
    assert "对手可用诱饵、强干扰和近程拦截反制" in portrait


def test_capability_portrait_keeps_failure_condition_and_consequence_complete() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem="现役装备难以在弱网条件下持续闭合任务链",
        principle="任务状态压缩与边缘受控授权",
        technologies=["组合导航", "低带宽任务更新"],
        operational_concept="分散部署、目标复核、受控交战和毁伤评估",
        operational_steps=["任务装订", "平台进入", "目标复核", "授权交战"],
        capability="弱网条件下持续精确打击",
        effect="压缩短时目标发现至毁伤闭环",
        winning_mechanism="改变对手的时间和拦截成本交换关系",
        failure_boundary=["对手在长期不辐射条件下仍能维持足够空情和火控时，迫使开机机制失效"],
    )

    assert "当对手在长期不辐射条件下仍能维持足够空情和火控时，迫使开机机制失效，应降级或重新校准" in portrait
    assert "失效时应降级" not in portrait


def test_capability_portrait_preserves_changed_variable_target_without_duplicated_verb() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem="目标坐标过期且末端不可确认",
        principle=(
            "把纵深火力对固定坐标和长准备周期的依赖，转变为地面分布式发射单元"
            "能否利用短暂目标窗口完成快速投送，并由弹上终端确认决定打击或安全中止"
        ),
        technologies=["受扰导航", "终端目标确认"],
        operational_concept="分散部署、快速发射、末段复核和安全中止",
        operational_steps=["任务装订", "快速发射", "末段确认", "安全中止"],
        capability="时间敏感目标快速精确打击",
        effect="压缩目标暴露至毁伤时间",
        winning_mechanism="以高速投送压缩目标转移和防御反应时间",
    )

    assert "利用地面分布式发射单元能否利用短暂目标窗口完成快速投送" in portrait
    assert "利用把纵深火力" not in portrait
    assert "利用将任务变量转为" not in portrait


def test_capability_portrait_prefers_real_interface_technologies_over_equipment_descriptor() -> None:
    portrait = build_capability_portrait(
        scenario="导航受扰条件下的纵深火力窗口",
        problem="目标坐标过期且末端不可确认",
        principle="由固定坐标打击转为受约束更新与末段确认",
        technologies=[
            "与HIMARS/M270A2发射箱、火控和武器授权接口",
            "任务规划系统下装目标参考、授权区域、禁打区和中止条件",
            "可选接收多源侦察形成的目标状态更新",
            "单一主装备：PrSM类地面发射远程精确制导导弹；指标方向为战役纵深覆盖",
        ],
        operational_concept="分散部署、快速发射、末段复核和安全中止",
        operational_steps=["任务装订", "快速发射", "末段确认", "安全中止"],
        capability="时间敏感目标快速精确打击",
        effect="压缩目标暴露至毁伤时间",
        winning_mechanism="以高速投送压缩目标转移和防御反应时间",
    )

    assert "HIMARS/M270A2发射箱" in portrait
    assert "任务规划系统" in portrait
    assert "采用单一主装备" not in portrait


def test_capability_portrait_uses_grammatical_relation_for_ba_construction() -> None:
    portrait = build_capability_portrait(
        scenario="强电磁压制下的短时火力窗口",
        problem="目标坐标过期且末端不可确认",
        principle="把PrSM作为独立地射导弹对象论证，不与空射巡航导弹混写",
        technologies=["任务规划", "受扰导航", "末段确认"],
        operational_concept="分散部署、快速发射、末段复核和安全中止",
        operational_steps=["任务装订", "快速发射", "末段确认", "安全中止"],
        capability="时间敏感目标快速精确打击",
        effect="压缩目标暴露至毁伤时间",
        winning_mechanism="以高速投送压缩目标转移和防御反应时间",
    )

    assert "利用目标信息时效约束和末段多模证据门控远程火力释放" in portrait
    assert "利用以" not in portrait
    assert "利用把PrSM" not in portrait


def test_antiship_overview_keeps_adversary_countermeasures_before_clipping() -> None:
    portrait = build_capability_portrait(
        scenario=(
            "强电磁压制与GNSS拒止下，对手水面编队以机动、诱饵、雷达静默和"
            "分层防空反制，岛链外缘或远海反舰齐射后的目标复获与末段交战阶段"
        ),
        problem="外部目标更新中断后难以完成舰艇身份复核和交战",
        principle="以可消耗搜索时间和交叉观测扩大局部再捕获机会",
        technologies=["非GNSS导航", "被动射频与成像复核"],
        operational_concept="分区搜索、身份复核、受控交战和安全拒打",
        operational_steps=["任务装订", "分散进入", "目标复核", "授权交战"],
        capability="失联海区目标再发现与直接打击",
        effect="直接毁伤机动水面目标",
        winning_mechanism="以目标区局部搜索压缩对手机动逃逸时间",
        equipment_form="长航时反舰巡飞猎歼弹药",
    )

    overview = portrait.split("\n", 1)[0]
    assert "远海反舰" in overview
    assert "对手水面编队" in overview
    assert any(marker in overview for marker in ("机动", "诱饵", "分层防空"))


def test_secondary_baseline_models_do_not_override_primary_weapon_portrait() -> None:
    common = {
        "scenario": "远海反舰齐射后，对手水面编队以机动、诱饵和分层防空反制",
        "problem": "外部目标更新中断后需要形成可验证的直接作战闭环",
        "technologies": ["机械与电气接口", "任务管理", "安全授权"],
        "operational_concept": "任务装订、分散进入、受控交战和再组织",
        "operational_steps": ["任务装订", "平台进入", "目标复核", "交战与再组织"],
        "failure_boundary": ["接口或身份门槛无法闭合时停止转段"],
    }
    cruise = build_capability_portrait(
        **common,
        principle="以概率搜索和多模身份门控续接断链反舰齐射",
        capability="断链后目标再捕获、弹间去重和直接反舰毁伤",
        effect="降低机动舰艇利用航迹过期和诱饵获得的逃逸收益",
        winning_mechanism="把航迹陈旧度转化为受约束搜索与安全拒打选择",
        equipment_form="多模导引自主再捕获远程反舰巡航弹药",
        baseline="JASSM/AGM-158与AARGM-ER只作为相邻公开弹药基线",
    )
    common_airframe = build_capability_portrait(
        **common,
        principle="以共同弹体和任务前载荷重配改变库存与齐射生成逻辑",
        capability="共同库存生成任务适配混合齐射",
        effect="降低专用弹药库存错配导致的任务取消",
        winning_mechanism="以任务前重配改变可用弹量和分类资源交换关系",
        equipment_form="采用共同推进、飞控、能源与发射接口的可消耗飞行弹体",
        baseline="MALD、AARGM-ER和Harop只证明相邻装备类别存在",
    )

    for portrait in (cruise, common_airframe):
        assert "关机前目标记忆与末端独立复核" not in portrait
        assert "关机目标再捕获率、诱饵误接受率" not in portrait
        assert "宽带被动射频侦测、辐射源类别判别" not in portrait
    assert "弹间目标摘要与安全弃攻状态机" in cruise
    assert "共同弹体必须冻结机械安装面" in common_airframe


def test_surface_ambush_boat_rebuilds_stale_cruise_effecter_semantics() -> None:
    portrait = build_capability_portrait(
        name="航路伏击自主突击无人艇",
        scenario="远海反舰齐射后的目标复获阶段",
        problem="高端远程弹药数量不足，难以维持多波次纵深毁伤",
        principle="将最后可靠情报转换为航路、海峡和补给通道约束",
        technologies=["非GNSS导航", "被动声学", "光电近距识别"],
        operational_concept="预置待机、近距识别、受控拦截和转移",
        operational_steps=["航路装订", "分散预置", "近距识别", "受控撞击"],
        capability="关键航路近距拦截并毁伤水面目标",
        effect="迫使舰队绕行、降速或清剿伏击区",
        winning_mechanism="以空间占据压缩舰队可选航路",
        equipment_form="低特征自主无人艇",
        baseline="Barracuda只作为相邻低成本效应器锚点",
    )

    overview = portrait.split("\n", 1)[0]
    assert all(marker in overview for marker in ("航路", "待机", "近距", "水面目标"))
    assert any(marker in overview for marker in ("绕行", "降速", "清剿"))
    assert "巡航效应器对纵深固定" not in overview
    assert "多轴多波次突防" not in overview


def test_common_airframe_rebuilds_stale_anti_radiation_gap() -> None:
    portrait = build_capability_portrait(
        name="共架可消耗多任务弹药",
        scenario="强电磁压制下的短时火力窗口",
        problem="现役反辐射弹药难以跨越关机窗口并排除诱饵辐射源",
        principle="共同弹体库存按威胁变化重配诱饵、猎辐射或毁伤载荷",
        technologies=["统一机械电气接口", "质量重心控制", "功率热管理"],
        operational_concept="威胁判读、载荷选配、接口检查和混合齐射生成",
        operational_steps=["威胁判读", "载荷选配", "接口检查", "库存再平衡"],
        capability="共同库存生成任务适配混合齐射",
        effect="降低专用构型库存错配导致的任务取消",
        winning_mechanism="以任务前重配改变可用弹量和分类资源交换关系",
        equipment_form="采用共同推进、飞控、能源与发射接口的可消耗飞行弹体",
    )

    overview = portrait.split("\n", 1)[0]
    assert all(marker in overview for marker in ("库存", "载荷", "接口", "混合齐射"))
    assert "现役反辐射弹药难以跨越关机窗口" not in overview


def test_antiship_cruise_rebuilds_stale_anti_radiation_gap() -> None:
    portrait = build_capability_portrait(
        name="协同去重远程反舰巡航弹药",
        scenario="远海反舰齐射后的目标复获阶段",
        problem="现役反辐射弹药难以跨越关机窗口并排除诱饵辐射源",
        principle="以航迹陈旧度约束概率搜索并按目标摘要去重",
        technologies=["抗扰组合导航", "多模身份复核", "弹间目标摘要"],
        operational_concept="目标包装订、分区搜索、身份复核与去重、受控毁伤",
        operational_steps=["目标包装订", "分区搜索", "身份复核", "去重交战"],
        capability="过时航迹条件下再捕获并直接反舰毁伤",
        effect="减少多弹重复攻击并毁伤机动水面舰艇",
        winning_mechanism="把航迹陈旧转化为可计量搜索负荷",
        equipment_form="多模导引自主再捕获远程反舰巡航弹药",
    )

    overview = portrait.split("\n", 1)[0]
    assert all(marker in overview for marker in ("搜索扇区", "目标摘要", "去重", "独立毁伤"))
    assert "现役反辐射弹药难以跨越关机窗口" not in overview


def test_antiship_loitering_hunter_excludes_decoy_suppression_main_flow() -> None:
    portrait = build_capability_portrait(
        name="长航时可消耗多模反舰巡飞猎歼弹药",
        scenario="远海反舰齐射后水面编队机动并释放诱饵",
        problem="外部航迹中断后难以持续保管并复核水面目标",
        principle="被动测向、视觉分类和航迹连续性检验",
        technologies=["被动射频", "红外/电视", "目标质量摘要"],
        operational_concept="前沿待机搜索、目标保管、身份复核和受控攻击",
        operational_steps=["进入目标可能区", "持续搜索", "身份复核", "直接攻击"],
        capability="断链目标保管、搜索区更新、局部BDA和有限直接毁伤",
        effect="为反舰弹更新搜索区并由自身战斗部攻击经授权水面目标",
        winning_mechanism="以前沿在位时间压缩舰队脱离接触窗口",
        equipment_form=(
            "折叠翼低空长航时无人机，配置被动射频、红外/电视、"
            "可消耗诱饵和小型压制载荷"
        ),
    )

    overview = portrait.split("\n", 1)[0]
    assert all(marker in overview for marker in ("水面", "搜索", "身份复核", "直接攻击"))
    assert any(marker in overview for marker in ("目标保管", "搜索区"))
    assert "诱导雷达开机" not in overview
    assert "主攻波次开窗" not in overview
    assert 120 <= len(overview.removeprefix("概述：")) <= 360


def test_resolver_rebuilds_existing_loitering_hunter_with_electronic_attack_flow() -> None:
    fields = {
        "name": "长航时可消耗多模反舰巡飞猎歼弹药",
        "scenario": "远海反舰齐射后水面编队机动并释放诱饵",
        "problem": "外部航迹中断后难以持续保管并复核水面目标",
        "principle": "被动测向、视觉分类和航迹连续性检验",
        "technologies": ["被动射频", "红外/电视", "目标质量摘要"],
        "operational_concept": "前沿待机搜索、目标保管、身份复核和受控攻击",
        "operational_steps": ["进入目标可能区", "持续搜索", "身份复核", "直接攻击"],
        "capability": "断链目标保管、搜索区更新、局部BDA和有限直接毁伤",
        "effect": "为反舰弹更新搜索区并由自身战斗部攻击经授权水面目标",
        "winning_mechanism": "以前沿在位时间压缩舰队脱离接触窗口",
        "equipment_form": (
            "折叠翼低空长航时无人机，配置被动射频、红外/电视、"
            "可消耗诱饵和小型压制载荷"
        ),
    }
    stale = build_capability_portrait(
        **{key: value for key, value in fields.items() if key != "name"}
    )
    assert "主攻波次利用" in stale.split("\n", 1)[0]

    rebuilt = resolve_capability_portrait(stale, **fields)
    overview = rebuilt.split("\n", 1)[0]

    assert "目标保管" in overview
    assert "受控直接攻击" in overview
    assert "主攻波次利用" not in overview


def test_resolver_preserves_complete_portrait_for_codex_semantic_review() -> None:
    generic_fields = {
        "scenario": "远海反舰齐射后水面编队机动并释放诱饵",
        "problem": "外部航迹中断后难以持续保管并复核水面目标",
        "principle": "被动测向、视觉分类和航迹连续性检验",
        "technologies": ["被动射频", "红外/电视", "目标质量摘要"],
        "operational_concept": "前沿待机搜索、目标保管、身份复核和受控攻击",
        "operational_steps": ["进入目标可能区", "持续搜索", "身份复核", "直接攻击"],
        "capability": "断链目标保管、搜索区更新、局部BDA和有限直接毁伤",
        "effect": "为反舰弹更新搜索区并由自身战斗部攻击经授权水面目标",
        "winning_mechanism": "以前沿在位时间压缩舰队脱离接触窗口",
        "equipment_form": "长航时可消耗多模反舰巡飞猎歼弹药",
    }
    stale = build_capability_portrait(
        name="长航时多模反舰巡飞猎歼弹药",
        **generic_fields,
    )
    assert "交叉确认" not in stale.split("\n", 1)[0]

    rebuilt = resolve_capability_portrait(
        stale,
        name="射频复核反舰巡飞猎歼弹药",
        **generic_fields,
    )
    overview = rebuilt.split("\n", 1)[0]

    assert rebuilt == stale
    assert "直接攻击" in overview


def test_generic_portraits_keep_project_specific_modules_and_metrics() -> None:
    common = {
        "scenario": "前沿阵地受毁且强电磁压制下的跨岛链补击阶段",
        "problem": "既有火力节点无法在间歇链路下持续形成直接毁伤",
        "technologies": ["抗扰任务规划", "目标复核", "安全授权"],
        "operational_concept": "分散部署、受控进入、目标复核和任务再组织",
        "operational_steps": ["任务装订", "分散部署", "目标复核", "交战与再组织"],
        "capability": "受扰条件下持续执行指定目标任务",
        "effect": "压缩目标反应时间并形成可复核战果",
        "winning_mechanism": "以分散任务节点改变对手搜索与防护资源分配",
    }
    microwave = build_capability_portrait(
        **common,
        name="脉冲封域微波效应器",
        principle="以瞬态电磁能量使暴露电子载荷进入功能失效状态",
        equipment_form="车载高功率微波定向能效应器",
    )
    navigation = build_capability_portrait(
        **common,
        name="无源定向微型制导弹药",
        principle="以无源场特征匹配约束末段航迹和目标身份",
        equipment_form="微型精确制导弹药",
    )

    assert all(marker in microwave for marker in ("高功率脉冲源", "定向辐射", "安全闭锁"))
    assert "功能压制确认率" in microwave
    assert "无源定向微型制导弹药的构型必须围绕其项目功能" in navigation
    assert "无源定向微型制导弹药任务完成率" in navigation
    for stale_clause in (
        "平台、载荷、传感、火控、任务软件与安全授权接口必须围绕同一直接战斗任务完成构型闭合",
        "具体战果表现为在代表性对抗场景中缩短发现、确认、交战、评估与再组织链路",
        "以任务完成率、闭环时间、单位代价和战损保持率验收",
        "在具体对抗中通过压缩对手反应时间提高防护资源投入并降低己方任务重组代价",
    ):
        assert stale_clause not in microwave
        assert stale_clause not in navigation


def test_land_loitering_launcher_and_microwave_portraits_do_not_inherit_antiradiation() -> None:
    common = {
        "scenario": "机场受毁与强电磁压制后的跨岛链补击阶段",
        "technologies": ["抗扰任务规划", "目标复核", "安全授权"],
        "operational_concept": "分散部署、受控进入、目标复核和任务再组织",
        "operational_steps": ["任务装订", "分散部署", "目标复核", "交战与再组织"],
        "capability": "形成受扰条件下的直接作战效果",
        "effect": "压缩目标反应时间并形成可复核战果",
        "winning_mechanism": "改变对手搜索、防护和恢复资源分配",
    }
    launcher = build_capability_portrait(
        **common,
        name="无人值守岛岸巡飞弹发射车",
        problem="机场出动链断裂后缺少可持续的岛岸无人火力释放节点",
        principle="以分散机动发射和在位搜索续接远程火力",
        equipment_form="车载无人巡飞弹药发射车",
    )
    microwave = build_capability_portrait(
        **common,
        name="高功率微波巡飞压制弹",
        problem="敌电子压制和低空反无人节点阻断后续弹药进入",
        principle="以短时功能压制为后续火力制造可测窗口",
        equipment_form="可消耗高功率微波巡飞弹药",
    )

    assert "现役反辐射弹药" not in launcher
    assert "现役反辐射弹药" not in microwave
    assert "车载无人巡飞弹药发射车" in launcher
    assert "高功率微波巡飞压制弹" in microwave
    assert all(marker in launcher for marker in ("短停释放", "射后脱离率", "多阵位"))
    assert all(marker in microwave for marker in ("功能压制", "恢复时间", "附带影响"))


def test_missile_launch_usv_uses_controlled_release_process_and_metrics() -> None:
    portrait = build_capability_portrait(
        name="半潜预置巡航弹无人艇",
        scenario="前沿机场与固定阵地受毁后的岛链间补击阶段",
        problem="空基与固定岸基释能节点被压制后缺少可生存的远火发射域",
        principle="以分布式海上预置和异步发射替代受毁机场与固定阵地",
        technologies=["半潜低特征艇体", "模块化巡航弹舱", "低截获授权"],
        operational_concept="分散布放、低特征待机、受控发射和射后转移",
        operational_steps=["分散布放", "海上待机", "授权复核", "释放巡航弹", "转移补击"],
        capability="不依赖单一机场的海上远程火力释放",
        effect="续接对敌纵深节点的巡航弹补击",
        winning_mechanism="迫使敌方扩大海上小目标搜剿范围",
        equipment_form="半潜无人艇平台与模块化巡航弹舱",
        failure_boundary="授权或弹舱状态不可验证时拒绝发射",
    )

    assert all(
        marker in portrait
        for marker in ("弹舱状态", "受控释放巡航弹", "拒绝发射", "射后脱离率")
    )
    assert "直接撞击" not in portrait


def test_r10_misleading_semisub_name_still_uses_remote_magazine_portrait() -> None:
    portrait = build_capability_portrait(
        name="低特征自主突击无人艇",
        scenario="前沿机场与固定岸基发射点受毁后的岛链补击阶段",
        problem="固定释能节点受毁后缺少海上远火缓存",
        principle="分布式海上预置与异步释能降低单点失效风险",
        technologies=["半潜艇体", "密封远程弹药舱", "低截获授权"],
        operational_concept="低特征待机，接令后释放巡航弹并转移",
        operational_steps=["分散布放", "海上待机", "授权复核", "释放巡航弹"],
        capability="机场外海上远程火力释放",
        effect="续接纵深指挥、保障和远程火力节点补击",
        winning_mechanism="迫使敌方扩大海上小目标搜剿范围",
        equipment_form="低活动半潜无人艇，内置密封远程弹药舱、简化火控终端和被动告警",
        failure_boundary="弹舱状态或授权不可验证时拒绝发射",
    )

    assert all(marker in portrait for marker in ("模块化巡航弹舱", "受控释放巡航弹", "连续补击波次数"))
    assert "航路覆盖率" not in portrait
    assert "直接撞击" not in portrait


def test_sealed_loitering_nest_keeps_prepositioned_launcher_contract() -> None:
    portrait = build_capability_portrait(
        name="岛上密封巡飞弹巢",
        scenario="机场与道路发射链受压后的岛上持续补击阶段",
        problem="车辆和固定阵地受毁后缺少隐蔽巡飞火力缓存",
        principle="长期密封预置与多巢接替降低集中发射节点脆弱性",
        technologies=["长储密封箱体", "弹药健康监测", "远程安全闭锁"],
        operational_concept="低活动待机、授权分批释放和未暴露弹巢接替",
        operational_steps=["分散预置", "健康监测", "授权复核", "分批释放", "节点接替"],
        capability="岛上分散巡飞弹持续释放",
        effect="搜索、复核和补击漏毁或转移目标",
        winning_mechanism="迫使对手持续发现并清除大量伪装密封节点",
        equipment_form="密封箱式巡飞弹发射巢，内含察打一体巡飞弹、健康监测和授权终端",
        failure_boundary="长期封存失效率过高或授权链不能闭合时停止释放",
    )

    assert all(marker in portrait for marker in ("长期封存", "分批释放", "未暴露", "授权释放成功率"))
    assert "无人驾驶或遥控底盘" not in portrait
    assert "发射车立即转移" not in portrait


def test_r10_node_interceptor_form_overrides_old_recon_drone_name() -> None:
    portrait = build_capability_portrait(
        name="低空可消耗察打一体无人机",
        scenario="远火节点遭小型无人机和巡飞弹连续搜索攻击",
        problem="分布式火力节点缺少低特征近域自卫火力",
        principle="近域低成本拦截保护远火射手的下一射击周期",
        technologies=["被动告警", "小型近程火控", "微型拦截弹"],
        operational_concept="威胁分类、有人监督拦截并掩护节点撤收",
        operational_steps=["自防扇区装订", "低空警戒", "威胁分类", "拦截与撤收"],
        capability="远火节点近程反杀伤",
        effect="提高节点生存率与再发射保持率",
        winning_mechanism="以低成本拦截换取高价值射手和剩余弹药",
        equipment_form="节点内置微型拦截弹发射单元，配套被动告警、小型近程火控和可消耗拦截弹",
        failure_boundary="误报率过高或自卫发射暴露节点超过收益时停止硬拦截",
    )

    assert all(marker in portrait for marker in ("侦察无人机", "分层拦截", "被护节点生存率", "再发射保持率"))
    assert "目标邻近空域" not in portrait
    assert "漏毁目标再发现" not in portrait


def test_fresh_quality_weapon_families_keep_equipment_local_combat_contracts() -> None:
    common = {
        "scenario": "前沿机场受毁与强电磁压制后的跨岛链持续释能阶段",
        "problem": "固定机场和集中发射节点受损后持续火力链出现断点",
        "principle": "以分散在位火力和受控任务释放续接作战节奏",
        "technologies": ["低带宽任务接口", "抗扰导航", "人工授权"],
        "operational_concept": "分散部署、短窗接令、受控交战与再组织",
        "operational_steps": ["任务装订", "分散部署", "目标复核", "交战与再组织"],
        "capability": "机场外持续释能",
        "effect": "维持远程火力波次并形成可复核战果",
        "winning_mechanism": "改变对手搜索、拦截和防护资源分配",
    }
    usv = build_capability_portrait(
        **{
            **common,
            "operational_concept": "海上分布弹舱低特征待机、受控发射和接替补射",
        },
        name="低特征自主突击无人艇",
        equipment_form="半潜式无人水面发射艇，搭载密封化远程弹药发射单元",
    )
    airborne = build_capability_portrait(
        **common,
        name="岛链外长航时无人载弹母机",
        equipment_form="长航时低特征无人作战飞机，挂载防区外精确打击弹药",
    )
    decoy = build_capability_portrait(
        **common,
        name="低成本可编程诱骗压制弹",
        equipment_form="小型可消耗空射诱骗压制弹，具备电磁特征模拟和电子压制载荷",
    )
    land = build_capability_portrait(
        **common,
        name="岛基机动精击导弹车",
        equipment_form="轮式远程精确导弹发射车，配套分散补弹车和短停发射控制系统",
    )
    counter = build_capability_portrait(
        **common,
        name="近域反无人拦截弹车",
        equipment_form="机动式反无人拦截弹车，集成小型拦截弹、非动能效应器和低辐射火控终端",
    )

    assert "受控释放巡航弹" in usv and "直接撞击" not in usv
    assert all(
        marker in airborne
        for marker in (
            "后方或幸存机场",
            "岛链外防区外",
            "弹药库存",
            "分批释放防区外弹药",
            "保留未用载荷",
            "战果摘要",
            "重新占位或退出",
        )
    )
    assert not any(
        marker in airborne
        for marker in ("箱式分批释放", "多路径低空进入", "本地搜索", "近区补击")
    )
    assert "诱导防空雷达开机" in decoy and "批次合格率" not in decoy
    assert all(marker in land for marker in ("短停发射", "射后撤收", "相邻车组补射"))
    assert all(marker in counter for marker in ("分层拦截", "被护节点生存率", "再发射保持率"))
    assert "须在代表性对抗场景中直接改变" not in land
    assert "须在代表性对抗场景中直接改变" not in counter


def test_armed_unmanned_wingman_keeps_platform_local_search_and_attack_flow() -> None:
    portrait = build_capability_portrait(
        name="远域反辐射压制无人僚机",
        scenario="前沿机场反复受毁后的持续压制阶段",
        problem="后方火力缺少对机动防空节点的持续再发现和有限补击主体",
        principle="目标区外缘在位被动搜索、跨模态复核和有限自带火力",
        technologies=["被动射频侦察", "光电复核", "小型精确弹", "抗扰导航"],
        operational_concept="岛链外缘低特征待机、复核、受控攻击或引导远火",
        operational_steps=["后方起飞", "外缘待机", "射频发现", "光电复核", "授权攻击"],
        capability="对机动防空与电子战车辆持续察打压制",
        effect="压缩敌节点关机转移和重组时间",
        winning_mechanism="把后方串行再发现与补击前推到目标区外缘",
        equipment_form=(
            "长航时低可探测武装无人僚机，搭载被动射频/光电侦察、"
            "小型精确弹、可消耗诱饵和有限电子压制载荷"
        ),
        failure_boundary="跨模态身份复核不足或近程拦截损耗不可接受",
    )

    assert all(
        marker in portrait
        for marker in (
            "长航时低可探测武装无人僚机",
            "被动射频",
            "光电",
            "后方起飞",
            "外缘待机",
            "射频发现",
            "光电复核",
        )
    )
    assert "长航时多模复核反辐射巡飞猎歼弹" not in portrait
    assert "弹舱库存" not in portrait


def test_missile_launcher_usv_title_overrides_misleading_assault_label() -> None:
    assert build_capability_title(
        name="低特征自主突击无人艇",
        equipment_form="半潜式无人水面发射艇，搭载密封化远程弹药发射单元",
        effect="海上分布弹舱受控发射与接替补射",
    ) == "半潜预置巡航弹无人艇"


def test_expendable_decoy_stays_in_electronic_attack_process() -> None:
    portrait = build_capability_portrait(
        name="诱扰开窗可消耗无人弹",
        scenario="主攻弹药进入敌一体化防空区前的突防开窗阶段",
        problem="敌防空雷达与拦截资源压缩主攻弹药突防窗口",
        principle="以可消耗特征模拟和伴随干扰诱导敌火控资源错配",
        technologies=["可编程特征模拟", "伴随干扰载荷", "被动响应感知"],
        operational_concept="多轴释放、诱导雷达响应、受控干扰和窗口通报",
        operational_steps=["威胁库装订", "多轴释放", "诱导雷达响应", "伴随干扰", "窗口通报"],
        capability="可消耗诱骗、压制开窗和短时更新",
        effect="为巡航弹与反辐射弹药创造突防窗口",
        winning_mechanism="以低成本无人弹换取敌高价值拦截与辐射暴露",
        equipment_form="可消耗喷气无人弹与可编程特征模拟、伴随干扰载荷",
    )

    assert all(
        marker in portrait
        for marker in ("受保护平台特征模拟", "多轴诱导防空雷达开机", "干扰载荷")
    )
    assert "末端光电/红外确认真实雷达车" not in portrait
