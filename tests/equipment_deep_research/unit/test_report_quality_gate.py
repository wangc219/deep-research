import pytest

from equipment_deep_research.delivery.quality_gate import (
    CANONICAL_REPORT_H3,
    ReportQualityGate,
    _has_dangling_report_fragment,
)


def _governed_capability_portrait(name: str) -> str:
    body = "\n".join(
        [
            f"概述：面向岛链外缘强对抗、通信受限和导航受扰的远程火力交战阶段，针对敌方机动目标短时暴露且外部航迹易中断的问题，{name}采用箱式发射远程精确制导巡飞弹药构型，利用弹上有限搜索与证据门控原理，配置组合导航和末段复核技术，通过分散发射、目标复核与受控交战，形成断链条件下直接打击能力，实现压缩敌方转移与重组时间的作战效果。",
            "- 装备与技术实现：型号落点为具体武器平台，采用任务载荷、组合导航、末段复核与安全中止软件，明确发射、火控和保障接口；公开基线对照为现役箱式发射巡飞弹药。",
            "- 关键作战流程：1.任务准备：装订目标与规则；2.平台进入：分散部署并更新目标；3.交战处置：完成发射、突防与受控交战；4.持续续接：实施毁伤评估、补击或中止，并在弱网条件下降级运行。",
            "- 形成能力与作战效果：形成远程精确毁伤、持续压制和战损续接能力，直接压缩发现至交战闭环时间并改善单位有效毁伤成本；以任务完成率、闭环时间、正确拒打率和单位成本验收。",
            "- 制胜逻辑机理：传统远程火力依赖持续目标更新并在发现后集中发射，该装备以分散预置、低信息依赖和受控自治改写交战节奏，迫使对手在持续隐蔽与暴露节点功能之间选择，并使其分层拦截资源过载。",
            "- 发展与验证路径：先开展数字仿真和半实物闭环，再围绕强干扰、目标欺骗和节点损耗开展对抗验证，以授权成功率、异常拒打率、闭环时间和单位成本作为转段门槛；失效边界独立记录。",
        ]
    )
    if len(body) < 500:
        body += "公开事实、分析推断和待核验指标分别记录，避免把概念方案写成已经形成的实装能力。" * 4
    return f"**{name}｜装备能力画像**\n\n{body}"


def test_complete_target_seeker_term_is_not_a_dangling_fragment() -> None:
    assert not _has_dangling_report_fragment(
        "核心技术集中在远程飞行、发射平台兼容、任务规划和后续移动目标寻的；"
        "证据边界是公开资料不能证明其具备强拒止环境下的弹群自治。"
    )
    assert not _has_dangling_report_fragment(
        "| 末段再捕获能力 | 导弹进入预置搜索区后，对机动水面目标重新发现、确认和拒打的能力。 |"
    )
    assert not _has_dangling_report_fragment(
        "| 诱压事件捕获 | 诱饵弹记录敌雷达开机、拦截、机动和电子战反应的能力。 |"
    )
    assert _has_dangling_report_fragment("该方向仍缺少可公开验证的。")


def test_current_prefix_is_not_misread_as_a_dangling_conditional() -> None:
    assert not _has_dangling_report_fragment(
        "当前置微波和电子压制装备完成首轮拦截后，"
        "激光复合防空车转入漏网目标精确毁伤。"
    )
    assert _has_dangling_report_fragment("当导航欺骗识别晚于航路偏差形成。")


def _content_contract_report(names: list[str], portraits: str = "") -> str:
    rows = "\n".join(
        f"| {name} | 无人武器平台 | 组合导航与末段复核 | 远程精确毁伤 | 分散编组、发射、突防、交战与毁伤评估 |"
        for name in names
    )
    return f"""## 二、项目画像
### （一）装备图像概述
| 装备系统方向 | 装备平台与方案 | 核心技术 | 形成能力 | 作战概念与主要效果 |
|---|---|---|---|---|
{rows}

{portraits}

### （二）作战运用模式
关键作战流程包括任务准备、分散编组、发射、交战、毁伤评估与再组织，形成链路闭环。
### （三）体系贡献率分析
{'、'.join(names)}逐项形成补链、强链和开链贡献，改善突防、毁伤和任务成功率。
### （四）主要战技指标
核心战技指标包括射程、响应、精度、成本和规模，具体阈值待验证。
## 三、总体方案
### （一）总体架构
总体架构由无人平台、任务载荷、发射单元和软件系统构成。
### （二）子系统方案
子系统落实到硬件、软件和接口方案。
## 四、关键技术
### （一）关键技术清单与攻关途径
核心技术包括组合导航、末段复核和低成本制造。
"""


def test_quality_gate_recognizes_project_report_semantics() -> None:
    report = """
    证据与推理链：证据ev-system-001；推理S3-S6综合判断。
    级联失效场景1：0-6小时通信受限，任务重分配时延增加30%。
    本质不是继续扩容单一链路，而是从连续全量回传转向最低有效协同，
    通过跨域融合重构任务链并形成新增机制。优先现役改装，提升任务完成率与体系韧性。
    2027-2030年进入中期演进，触发条件是多平台接口成熟；风险是证据仍存在不确定性。
    """

    result = ReportQualityGate().validate(report)

    assert result.depth.indicators["has_evidence_support"] is True
    assert result.military_value.indicators["has_scenarios"] is True
    assert result.novelty.indicators["has_comparison"] is True
    assert result.novelty.indicators["has_breakthrough"] is True


def test_capability_image_parser_ignores_english_direction_header() -> None:
    report = """
### ⑦ 装备能力图像

| direction | 能力域 | 指标画像 |
|---|---|---|
| 抗干扰远程精确制导弹药 | 远程打击 | 抗干扰制导 |
| 可消耗无人搜索打击平台 | 无人打击 | 低信息依赖 |

### ⑧ 效能贡献评估
形成补链、强链和开链贡献。
"""

    assert ReportQualityGate._capability_image_table_directions(report) == [
        "抗干扰远程精确制导弹药",
        "可消耗无人搜索打击平台",
    ]


def test_domain_fitness_recognizes_unmanned_weapon_platform_wording() -> None:
    metadata = {
        "topic": "无人远程精确火力打击装备研究",
        "expected_capability_records": [
            {
                "name": "批量可消耗低空无人携弹平台族",
                "equipment_form": "固定构型低空无人携弹平台",
                "mission_effect": "低空进入并直接猎歼和毁伤机动目标",
            }
        ],
    }

    result = ReportQualityGate()._check_domain_fitness("无人远程火力", metadata)

    assert result.indicators["has_unmanned_combat_equipment"] is True


def test_direct_weapon_focus_recognizes_undersea_interceptors_and_motherships() -> None:
    records = [
        {
            "name": "封装释放式反UUV近程硬杀拦截器",
            "equipment_form": "水下拦截器",
            "mission_effect": "近程拦截并直接毁伤敌UUV",
        },
        {
            "name": "水下无人母艇-效应器再投送艇",
            "equipment_form": "水下无人母平台与水下效应器",
            "mission_effect": "再投送效应器完成猎歼与拒止",
        },
        {
            "name": "低成本反UUV自主拦截鱼雷",
            "equipment_form": "自主鱼雷",
            "mission_effect": "拦截并杀伤敌UUV",
        },
        {
            "name": "坐底封装反潜拒止武器",
            "equipment_form": "UUV投送水下武器",
            "mission_effect": "对潜艇实施拒止和毁伤",
        },
    ]
    result = ReportQualityGate()._check_domain_fitness(
        "真实远海反潜交战场景",
        {
            "topic": "远海反潜武器装备",
            "expected_capability_records": records,
            "require_direct_combat_weapon_focus": True,
        },
    )

    assert result.indicators["has_at_least_4_direct_combat_weapons"] is True
    assert result.indicators["direct_combat_weapons_are_portfolio_majority"] is True
    assert result.passed is True


def test_scenario_first_content_gate_accepts_editorial_equipment_names() -> None:
    source_names = [f"前置画像装备{index}" for index in range(4)]
    editorial_names = [f"战场化命名武器{index}" for index in range(4)]
    report = _content_contract_report(editorial_names)
    result = ReportQualityGate()._check_report_content_contract(
        report,
        {
            "report_template_mode": "project_argument_v1",
            "military_scenario_first_gate": True,
            "require_detailed_capability_portraits": True,
            "require_high_value_military_information": True,
            "expected_capability_directions": source_names,
            "expected_capability_records": [
                {
                    "name": name,
                    "equipment_form": "直接杀伤无人武器平台",
                    "mission_effect": "拦截并毁伤敌方目标",
                }
                for name in source_names
            ],
        },
    )

    assert result.indicators["capability_projection_complete"] is True
    assert result.passed is True


def test_domain_fitness_recognizes_intervening_unmanned_platform_wording() -> None:
    metadata = {
        "topic": "无人远程精确火力打击装备研究",
        "expected_capability_records": [
            {
                "name": "任务区前置的可消耗低空察打一体无人突击平台",
                "equipment_form": "低空察打一体飞行器与直接毁伤载荷",
                "mission_effect": "持续猎歼和毁伤短时暴露目标",
            }
        ],
    }

    result = ReportQualityGate()._check_domain_fitness("无人远程火力", metadata)

    assert result.indicators["has_unmanned_combat_equipment"] is True


def test_unmanned_remote_fire_domain_requires_five_delivery_attributes() -> None:
    metadata = {
        "topic": "无人远程精确火力打击装备研究",
        "evidence_count": 3,
        "expected_capability_directions": ["远程无人巡飞打击平台"],
    }
    report = """
### ⑦ 装备能力图像
| 装备系统方向 | 能力域 | 指标画像 | 作战运用概念 |
|---|---|---|---|
| 远程无人巡飞打击平台 | 战役纵深精确打击 | 航程、载荷、成本与自主等级 | 编组待机、波次发射、低空突防与交战 |
| 抗扰远程精确制导弹药 | 战役纵深毁伤 | 射程、突防与末制导 | 多点发射、低空突防与末段交战 |
| 低空诱饵压制巡飞弹 | 防空压制 | 成本、滞空与压制窗口 | 前出待机、波次诱骗与伴随突防 |
| 反辐射无人猎歼车 | 干扰源猎杀 | 测向精度、响应与毁伤载荷 | 静默机动、被动搜索与近程交战 |
| 机动制导火箭炮 | 持续远程火力 | 响应、齐射与再打击周期 | 分散编组、射后转移与补打交战 |

### ⑧ 效能贡献评估
现役效能跃升体现为存量火力断链可战；传统赛道跨代优势体现为成本交换和突防毁伤提升；
新概念赛道开辟体现为无人平台先于目标存在并持续拒止。该创新改变平台绑定火力关系，
对手可能以诱饵和干扰反适应。技术成熟度为样机验证阶段，瓶颈是抗干扰制导；公开证据
仅支持类别级判断，关键结论待验证。近期开展演示验证，设置验证指标、通过条件和失败条件。
来源：https://example.test/evidence
"""

    gate = ReportQualityGate()
    military = gate._check_military_value(report, metadata)
    depth = gate._check_depth(report, metadata)
    novelty = gate._check_novelty(report, metadata)
    foresight = gate._check_foresight(report, metadata)

    assert military.indicators["has_unmanned_remote_fire_domain_alignment"] is True
    assert military.indicators["has_capability_and_operational_concept"] is True
    assert military.indicators["has_three_track_winning_effect"] is True
    assert depth.indicators["has_evidence_bounded_feasibility"] is True
    assert novelty.indicators["has_cross_generation_or_new_track"] is True
    assert novelty.indicators["has_evidence_grounded_novelty"] is True
    assert foresight.indicators["has_maturity_assessment"] is True


def test_domain_novelty_rejects_empty_innovation_labels() -> None:
    metadata = {"topic": "无人远程精确火力打击装备研究"}
    report = "创新新研装备可形成跨代优势并开辟新概念赛道。"

    novelty = ReportQualityGate()._check_novelty(report, metadata)

    assert novelty.indicators["has_evidence_grounded_novelty"] is False
    assert novelty.passed is False


def test_domain_capability_image_rejects_fewer_than_five_directions() -> None:
    metadata = {"topic": "无人远程精确火力打击装备研究"}
    report = """
### ⑦ 装备能力图像
| 装备系统方向 | 能力域 | 指标画像 | 作战运用概念 |
|---|---|---|---|
| 远程无人巡飞打击平台 | 远程打击 | 航程与载荷 | 编组待机、波次发射、低空突防与交战 |
| 抗扰远程精确制导弹药 | 精确毁伤 | 射程与制导 | 多点发射、末段交战 |
| 低空诱饵压制巡飞弹 | 防空压制 | 成本与滞空 | 前出待机、伴随突防 |
| 反辐射无人猎歼车 | 干扰源猎杀 | 测向与载荷 | 静默机动、搜索交战 |

### ⑧ 效能贡献评估
"""

    military = ReportQualityGate()._check_military_value(report, metadata)

    assert military.indicators["has_capability_and_operational_concept"] is False


def test_quality_gate_recognizes_military_forecast_equivalent_language() -> None:
    report = """
    未来十年能力将分阶段形成。近期三年内完成现役改装，中期三至六年形成
    分层中继，远期六至十年开展自治节点预研。若训练数据不足，则该方向应
    降级；一旦对手形成稳定反制，体系将转向人工辅助。当前判断置信度中等，
    失效边界包括接口约束、维护负担和保障风险。
    """

    result = ReportQualityGate().validate(report)

    assert result.foresight.indicators["has_future_prediction"] is True
    assert result.foresight.indicators["has_trigger_conditions"] is True
    assert result.foresight.indicators["has_uncertainty"] is True
    assert result.foresight.indicators["has_evolution_path"] is True


def test_quality_gate_treats_disruptive_relationship_diversity_as_advisory() -> None:
    gate = ReportQualityGate()
    common = (
        "相对传统方式，该新研装备从单项性能竞争转向任务机制重构，形成跨域融合和创新突破。"
    )
    shallow = common + "以低成本规模消耗改善成本交换，并用长航时持续存在改变平台关系。"
    shallow_result = gate._check_novelty(
        shallow,
        {"require_disruptive_lens_diversity": True},
    )

    assert shallow_result.indicators["has_disruptive_relationship_diversity"] is False
    assert shallow_result.passed is True
    assert any("低优先级增强" in item for item in shallow_result.suggestions)

    rich = shallow + "毁伤评估和再打击用于压缩决策周期。"
    rich_result = gate._check_novelty(
        rich,
        {"require_disruptive_lens_diversity": True},
    )
    assert rich_result.indicators["has_disruptive_relationship_diversity"] is True
    assert rich_result.passed is True


def test_quality_gate_rejects_invented_support_row_in_capability_image_table() -> None:
    names = [f"直接战斗装备{index}" for index in range(1, 6)]
    h3_bodies = {
        "① 典型作战场景": "对手、地域、烈度、时间窗和约束条件明确。",
        "② 新战法或新概念技术及制胜机理": "现有范式不足，新战法形成制胜优势。",
        "③ 装备能力特征清单": "射程、响应时间、自主等级和成本量级明确。",
        "④ 能力实现途径": "沿用改进、集成创新和原理突破分类实施。",
        "⑤ 核心技术清单与攻关优先级": "制导律成熟度、瓶颈和P0优先级明确。",
        "⑥ 技术耦合与短板风险": "技术耦合、卡脖子短板和级联风险明确。",
        "⑧ 效能贡献评估": "按补链、强链、开链评估突防率和决策周期。",
        "⑨ 发展优先级与近期抓手": "P0演示验证项目设置通过条件和失败条件。",
    }
    parts = ["## 第一层：需求挖掘层——场景·战法/技术·装备能力特征"]
    for title in CANONICAL_REPORT_H3[:3]:
        parts.append(f"### {title}\n{h3_bodies[title]}")
    parts.append("## 第二层：技术攻关层——能力实现途径与核心技术")
    for title in CANONICAL_REPORT_H3[3:6]:
        parts.append(f"### {title}\n{h3_bodies[title]}")
    parts.append("## 第三层：能力图像与效能贡献层")
    rows = "\n".join(
        f"| {name} | 打击毁伤 | 指标 | 边界 | 关系 | 谱系 |"
        for name in names
    )
    parts.append(
        "### ⑦ 装备能力图像\n"
        "| 装备系统方向 | 能力域 | 指标画像 | 使用边界 | 颠覆的传统关系 | 谱系位置 |\n"
        "|---|---|---|---|---|---|\n"
        + rows
    )
    for title in CANONICAL_REPORT_H3[7:]:
        parts.append(f"### {title}\n{h3_bodies[title]}")
    valid = "\n\n".join(parts)
    gate = ReportQualityGate()
    valid_check = gate._check_format_integrity(
        valid,
        {"expected_capability_directions": names},
    )
    assert valid_check.indicators["has_exact_capability_direction_set"] is True

    wrapped = "# 平台统一报告标题\n\n" + valid
    unmarked_wrapper = gate._check_format_integrity(
        wrapped,
        {"expected_capability_directions": names},
    )
    marked_wrapper = gate._check_format_integrity(
        wrapped,
        {
            "expected_capability_directions": names,
            "delivery_owned_h1": True,
        },
    )
    assert unmarked_wrapper.indicators["has_no_report_owned_h1"] is False
    assert marked_wrapper.indicators["has_no_report_owned_h1"] is True

    invalid = valid.replace(names[-1], "弱网联合杀伤网装备包")
    invalid_check = gate._check_format_integrity(
        invalid,
        {"expected_capability_directions": names},
    )
    assert invalid_check.indicators["has_exact_capability_direction_set"] is False
    assert invalid_check.passed is False


def test_quality_gate_has_no_report_length_requirement() -> None:
    report = "\n\n".join(
        [
            "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            "### ① 典型作战场景\n形成对手、地域、烈度、时间窗和约束判断。",
            "### ② 新战法或新概念技术及制胜机理\n由于压制导致任务失败，因此需要新战法形成制胜机制。",
            "### ③ 装备能力特征清单\n形成能力域及射程、响应时间和自主等级方向。",
            "## 第二层：技术攻关层——能力实现途径与核心技术",
            "### ④ 能力实现途径\n优先沿用改进并验证任务完成率。",
            "### ⑤ 核心技术清单与攻关优先级\n标注成熟度、瓶颈与P0优先级。",
            "### ⑥ 技术耦合与短板风险\n保留耦合风险和卡脖子短板。",
            "## 第三层：能力图像与效能贡献层",
            "### ⑦ 装备能力图像\n形成能力域、指标画像和谱系位置。",
            "### ⑧ 效能贡献评估\n按补链、强链、开链评估决策周期改善量级。",
            "### ⑨ 发展优先级与近期抓手\n未来三年启动P0演示验证并设置通过条件。",
        ]
    )
    oversized = report + ("完整段落。" * 100)

    result = ReportQualityGate().validate(
        oversized,
        {"evidence_count": 1, "report_hard_max_chars": len(report)},
    )

    assert "has_bounded_report_length" not in result.format_integrity.indicators
    assert result.format_integrity.passed is True


def test_information_density_gate_rejects_long_generic_repeated_report() -> None:
    names = [f"具体反舰武器{index}" for index in range(1, 6)]
    repeated = (
        "总体来看，国际军事竞争复杂多变，相关能力建设具有重要意义，"
        "迫切需要全面提升体系化、实战化和智能化水平，为新质战斗力提供有力支撑。"
    )
    report = "\n\n".join([repeated] * 18) + "\n\n" + "、".join(names)

    check = ReportQualityGate()._check_report_information_density(
        report,
        {
            "require_high_value_military_information": True,
            "expected_capability_directions": names,
        },
    )

    assert check.indicators["decision_dense_paragraphs"] is False
    assert check.indicators["generic_filler_bounded"] is False
    assert check.indicators["long_sentence_reuse_bounded"] is False
    assert check.indicators["equipment_decision_bundles_complete"] is False
    assert check.passed is False


def test_information_density_gate_accepts_short_equipment_decision_bundles() -> None:
    names = [f"具体反舰武器{index}" for index in range(1, 6)]
    paragraphs = []
    for index, name in enumerate(names, start=1):
        paragraphs.append(
            f"{name}用于岛链外缘交战第{index}阶段，针对敌方机动舰艇、诱饵和电子干扰，"
            f"由岸基第{index}火力单元分散部署并发射，完成搜索复核、受控交战、毁伤评估和补击；"
            f"直接战果是阻断目标转移并恢复第{index}路反舰火力，以再捕获率、正确拒打率、"
            f"闭环时间和第{index}阶段通过条件开展半实物验证。"
        )
    report = "\n\n".join(paragraphs)

    check = ReportQualityGate()._check_report_information_density(
        report,
        {
            "require_high_value_military_information": True,
            "expected_capability_directions": names,
        },
    )

    assert check.indicators == {
        "decision_dense_paragraphs": True,
        "section_density_bounded": True,
        "generic_filler_bounded": True,
        "long_sentence_reuse_bounded": True,
        "equipment_decision_bundles_complete": True,
    }
    assert check.passed is True


def test_information_density_gate_allows_low_density_development_foundation() -> None:
    names = [f"具体反舰武器{index}" for index in range(1, 6)]
    dense_paragraphs = []
    for index, name in enumerate(names, start=1):
        dense_paragraphs.append(
            f"{name}在岛链外缘对敌方机动舰艇实施第{index}波反舰交战，完成发射、"
            f"搜索复核、受控毁伤和补击；以再捕获率、拒打率与闭环时间作为第{index}项验证门槛。"
        )
    dense_paragraphs.append(
        "建设决策优先完成多模导引头半实物试验；若诱饵条件下身份复核率不能达到通过条件，"
        "则停止转段并保留现役基线。"
    )
    generic = (
        "总体来看，国际军事竞争复杂多变，相关能力建设具有重要意义，"
        "迫切需要全面提升体系化、实战化和智能化水平。"
    )
    report = (
        "## 二、项目画像\n\n"
        + "\n\n".join(dense_paragraphs)
        + "\n\n## 五、研制基础\n\n"
        + generic
        + "\n\n"
        + generic.replace("国际", "地区")
    )

    check = ReportQualityGate()._check_report_information_density(
        report,
        {
            "require_high_value_military_information": True,
            "expected_capability_directions": names,
        },
    )

    assert check.indicators["decision_dense_paragraphs"] is True
    assert check.indicators["generic_filler_bounded"] is True
    assert check.indicators["section_density_bounded"] is True
    assert check.passed is True
    assert not any("五、研制基础" in suggestion for suggestion in check.suggestions)


def test_information_density_gate_still_rejects_low_value_preceding_section() -> None:
    names = [f"具体反舰武器{index}" for index in range(1, 6)]
    dense = "\n\n".join(
        f"{name}针对敌机动舰艇和电子干扰，由岸基火力单元完成发射、复核、毁伤和补击，"
        f"以第{index}项再捕获率、拒打率和闭环时间作为验证门槛。"
        for index, name in enumerate(names, start=1)
    )
    generic = (
        "总体来看，国际军事竞争复杂多变，相关能力建设具有重要意义，"
        "迫切需要全面提升体系化、实战化和智能化水平。"
    )
    report = (
        "## 二、项目画像\n\n"
        + dense
        + "\n\n## 三、总体方案\n\n"
        + generic
        + "\n\n"
        + generic.replace("国际", "地区")
        + "\n\n## 五、研制基础\n\n参与单位与技术基础待核验。"
    )

    check = ReportQualityGate()._check_report_information_density(
        report,
        {
            "require_high_value_military_information": True,
            "expected_capability_directions": names,
        },
    )

    assert check.indicators["section_density_bounded"] is False
    assert check.passed is False
    assert any("三、总体方案" in suggestion for suggestion in check.suggestions)


def test_quality_content_gate_requires_all_full_governed_portraits_when_enabled() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    portraits = "\n\n".join(
        _governed_capability_portrait(name) for name in names
    )
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "require_detailed_capability_portraits": True,
    }

    check = ReportQualityGate()._check_report_content_contract(
        _content_contract_report(names, portraits),
        metadata,
    )

    assert check.indicators["detailed_capability_portraits_complete"] is True
    assert check.passed is True


@pytest.mark.parametrize("direction_count", [4, 8])
def test_quality_content_gate_projects_exact_selected_portfolio_size(
    direction_count: int,
) -> None:
    names = [
        f"前瞻无人远程打击装备{index}"
        for index in range(1, direction_count + 1)
    ]
    portraits = "\n\n".join(
        _governed_capability_portrait(name) for name in names
    )
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "expected_capability_records": [{"name": name} for name in names],
        "require_detailed_capability_portraits": True,
    }

    check = ReportQualityGate()._check_report_content_contract(
        _content_contract_report(names, portraits),
        metadata,
    )

    assert check.indicators["capability_projection_complete"] is True
    assert check.indicators["detailed_capability_portraits_complete"] is True
    assert check.passed is True


def test_quality_content_gate_rejects_table_only_and_duplicate_title_portraits() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "require_detailed_capability_portraits": True,
    }
    gate = ReportQualityGate()

    table_only = gate._check_report_content_contract(
        _content_contract_report(names),
        metadata,
    )
    portraits = "\n\n".join(
        _governed_capability_portrait(name) for name in names
    )
    duplicated = gate._check_report_content_contract(
        _content_contract_report(
            names,
            portraits + "\n\n" + _governed_capability_portrait(names[0]),
        ),
        metadata,
    )

    assert table_only.indicators["detailed_capability_portraits_complete"] is False
    assert table_only.passed is False
    assert duplicated.indicators["detailed_capability_portraits_complete"] is False
    assert duplicated.passed is False


def test_quality_content_gate_rejects_portrait_missing_governed_label() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    portraits = "\n\n".join(
        _governed_capability_portrait(name) for name in names
    ).replace("- 关键作战流程：", "- 战斗步骤：", 1)
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "require_detailed_capability_portraits": True,
    }

    check = ReportQualityGate()._check_report_content_contract(
        _content_contract_report(names, portraits),
        metadata,
    )

    assert check.indicators["detailed_capability_portraits_complete"] is False
    assert check.passed is False


def test_quality_content_gate_rejects_two_step_portrait_without_comparison_gate() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    portraits = "\n\n".join(
        _governed_capability_portrait(name) for name in names
    )
    portraits = portraits.replace(
        "1.任务准备：装订目标与规则；2.平台进入：分散部署并更新目标；3.交战处置：完成发射、突防与受控交战；4.持续续接：实施毁伤评估、补击或中止",
        "1.平台进入：分散部署；2.目标复核：更新目标",
        1,
    ).replace("开展对抗验证", "开展一般验证", 1)
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "require_detailed_capability_portraits": True,
    }

    check = ReportQualityGate()._check_report_content_contract(
        _content_contract_report(names, portraits),
        metadata,
    )

    assert check.indicators["detailed_capability_portraits_complete"] is False
    assert check.passed is False


def test_legacy_content_gate_remains_compatible_without_strict_portrait_flag() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
    }

    check = ReportQualityGate()._check_report_content_contract(
        _content_contract_report(names),
        metadata,
    )

    assert check.indicators["detailed_capability_portraits_complete"] is True
    assert check.passed is True


def test_feasibility_gate_accepts_specific_equivalent_engineering_terms() -> None:
    report = """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征
### ① 典型作战场景
场景正文。
### ② 新战法或新概念技术及制胜机理
机理正文。
### ③ 装备能力特征清单
能力正文。
## 第二层：技术攻关层——能力实现途径与核心技术
### ④ 能力实现途径
沿用改进、集成创新和原理突破分别推进。
### ⑤ 核心技术清单与攻关优先级
P0攻关多源PNT与抗欺骗导航、末段复核与拒打逻辑、预装订任务包与断链降级软件；
P1攻关低带宽协同、宽带被动侦收与关机续踪；P2验证多弹型任务规划和半实物闭环。
成熟度按现役改装、样机和工程化分级，公开证据不足处待验证。
### ⑥ 技术耦合与短板风险
导航与末段复核串联耦合；拒打逻辑是单点短板，一旦失效会级联拖垮任务闭环。
## 第三层：能力图像与效能贡献层
### ⑦ 装备能力图像
能力图像正文。
### ⑧ 效能贡献评估
效能正文。
### ⑨ 发展优先级与近期抓手
开展半实物和演示验证，设置验收指标、通过条件与失败条件。
"""

    check = ReportQualityGate()._check_feasibility_fitness(report, None)

    assert check.indicators["has_specific_core_technologies"] is True


def test_feasibility_gate_accepts_real_report_engineering_vocabulary() -> None:
    report = """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征
### ① 典型作战场景
场景正文。
### ② 新战法或新概念技术及制胜机理
机理正文。
### ③ 装备能力特征清单
能力正文。
## 第二层：技术攻关层——能力实现途径与核心技术
### ④ 能力实现途径
现役改装和集成创新并行。
### ⑤ 核心技术清单与攻关优先级
P0验证抗GNSS组合导航与欺骗隔离、辐射活动记忆、光电末端复核与拒击算法；
P1验证多弹并发任务分配、末段安全中止和模块化载荷接口。成熟度按样机和工程化分级，公开证据不足处待验证。
### ⑥ 技术耦合与短板风险
组合导航、复核与安全中止串联耦合，任一单点短板会级联拖垮闭环。
## 第三层：能力图像与效能贡献层
### ⑦ 装备能力图像
能力图像正文。
### ⑧ 效能贡献评估
效能正文。
### ⑨ 发展优先级与近期抓手
开展半实物演示验证，设置验收指标、通过条件和失败条件。
"""

    check = ReportQualityGate()._check_feasibility_fitness(report, None)

    assert check.indicators["has_specific_core_technologies"] is True


def test_three_track_effect_accepts_open_chain_semantics_for_new_track() -> None:
    section = (
        "现役效能跃升用于恢复断链条件下的毁伤，传统赛道形成跨代优势；"
        "开链贡献由无人低成本火力重构此前的平台绑定任务路径。"
    )

    assert ReportQualityGate._has_three_track_winning_effect(section) is True


def test_feasibility_gate_accepts_concrete_demonstration_project_conditions() -> None:
    report = """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征
### ① 典型作战场景
场景正文。
### ② 新战法或新概念技术及制胜机理
机理正文。
### ③ 装备能力特征清单
能力正文。
## 第二层：技术攻关层——能力实现途径与核心技术
### ④ 能力实现途径
现役改装与集成创新并行。
### ⑤ 核心技术清单与攻关优先级
P0攻关多源PNT、末段复核、拒打逻辑和低带宽协同；成熟度按样机与工程化分级，公开证据不足处待验证。
### ⑥ 技术耦合与短板风险
导航和末段复核串联耦合；拒打逻辑是单点短板，失效会级联拖垮闭环。
## 第三层：能力图像与效能贡献层
### ⑦ 装备能力图像
能力图像正文。
### ⑧ 效能贡献评估
效能正文。
### ⑨ 发展优先级与近期抓手
近期演示项目设置强干扰综合靶场。通过条件是授权内打击和异常拒打均可审计；失败条件是规则冲突不可发现。
"""

    check = ReportQualityGate()._check_feasibility_fitness(report, None)

    assert check.indicators["has_validation_and_failure_conditions"] is True


def test_quality_gate_rejects_legacy_six_section_report_template() -> None:
    legacy_report = """## 核心判断
形成任务判断。

## 因果机理与任务链
说明任务链。

## 分支规定成果
形成分支成果。

## 能力需求与装备发展
形成装备方向。

## 跨场景适用性
说明场景边界。

## 不确定性、验证与证据边界
说明验证风险。
"""

    result = ReportQualityGate().validate(legacy_report)

    assert result.format_integrity.indicators["has_canonical_sections"] is False
    assert result.format_integrity.indicators["has_canonical_items"] is False
    assert result.format_integrity.passed is False


def test_project_argument_template_structure_and_compact_gate_payload() -> None:
    names = [f"无人远程打击装备{index}" for index in range(1, 6)]
    rows = "\n".join(
        f"| {name} | 无人平台与精确载荷 | 组合导航与末段复核 | 远程精确毁伤 | 分散编组、发射、突防、交战与毁伤评估 |"
        for name in names
    )
    report = f"""## 一、需求分析
### （一）需求概述
#### 1. 背景分析
国际军事竞争加速无人化远程精确火力发展。
#### 2. 需求阐述
针对强扰和短时目标，需要压缩火力闭环。
#### 3. 项目画像
项目形成体系化、实战化和智能化装备方案。
### （二）国内外现状
#### 1. 国外情况
国外案例基于公开证据说明技术路线与指标边界。
#### 2. 国内现状（中国）
国内案例基于公开证据说明平台和核心技术基础。
#### 3. 对比小结
对比结论区分事实、推断和待核验假设。
### （三）建设必要性分析
#### 1. 作战使用角度
作战需求迫切并贡献现有装备体系。
#### 2. 装备能力提升角度
需要提升性能、产能和供应链韧性。
#### 3. 领域占位角度
需要形成新平台和系列装备布局。
#### 4. 综合效益
兼顾军事平衡、成本交换和规模效益。
## 二、项目画像
### （一）装备图像概述
| 装备系统方向 | 装备平台与方案 | 核心技术 | 形成能力 | 作战概念与主要效果 |
|---|---|---|---|---|
{rows}
### （二）作战运用模式
#### 1. 作战运用流程
关键作战流程包括任务准备、分散部署、发射、交战、毁伤评估与再组织。
#### 2. 链路闭环分析
链路闭环压缩目标发现至毁伤评估的决策周期。
### （三）体系贡献率分析
逐项形成补链、强链和开链贡献：{'、'.join(names)}改善突防、毁伤和任务成功率。
### （四）主要战技指标
核心战技指标包括射程、响应、精度、成本和规模，具体阈值待验证。
## 三、总体方案
### （一）总体架构
总体架构由无人平台、任务载荷、发射单元和软件系统构成。
### （二）子系统方案
子系统落实到硬件、软件和接口方案。
## 四、关键技术
### （一）关键技术清单与攻关途径
核心技术包括组合导航、末段复核和低成本制造，并设置试验验证、通过条件和失败条件。
## 五、研制基础
### （一）参与单位
参与单位信息待项目组织确认。
### （二）技术基础
公开证据支持类别级技术基础，成熟度和指标仍需样机验证。
"""
    metadata = {
        "report_template_mode": "project_argument_v1",
        "expected_capability_directions": names,
        "expected_capability_records": [
            {
                "name": name,
                "equipment_form": "无人远程精确打击平台",
                "mission_effect": "远程精确毁伤",
            }
            for name in names
        ],
        "evidence_count": 2,
    }

    result = ReportQualityGate().validate(report, metadata)
    compact = result.compact()

    assert result.format_integrity.passed is True
    assert result.fitness["内容闭环"].passed is True
    assert result.fitness["证据与验证边界"].passed is True
    assert result.passed is True
    assert set(compact) == {
        "passed",
        "overall_score",
        "core_gates",
        "blockers",
        "diagnostics",
    }
    assert "has_bounded_report_length" not in compact["core_gates"]["模板结构"]["failed"]

    rewrite_marker_result = ReportQualityGate().validate(
        report.replace(
            "无人平台与精确载荷",
            "无人平台〔改写断点：保留事实但不得照录〕与精确载荷",
            1,
        ),
        metadata,
    )
    assert rewrite_marker_result.format_integrity.indicators[
        "has_no_internal_rewrite_boundary"
    ] is False
    assert rewrite_marker_result.passed is False

    candidate_prefix_report = report.replace(
        f"| {names[0]} |",
        f"| A. {names[0]} |",
        1,
    )
    candidate_prefix_result = ReportQualityGate().validate(
        candidate_prefix_report,
        {
            **metadata,
            "expected_capability_directions": [f"A. {names[0]}", *names[1:]],
            "expected_capability_records": [
                {
                    **metadata["expected_capability_records"][0],
                    "name": f"A. {names[0]}",
                },
                *metadata["expected_capability_records"][1:],
            ],
        },
    )
    assert candidate_prefix_result.format_integrity.indicators[
        "has_no_internal_candidate_prefix"
    ] is False
    assert candidate_prefix_result.passed is False

    fragmented = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "国际军事竞争加速无人化远程精确火力发展。在高强度对抗中。",
    )
    fragmented_result = ReportQualityGate().validate(fragmented, metadata)
    assert fragmented_result.format_integrity.indicators["has_complete_paragraphs"] is False
    assert fragmented_result.passed is False

    complete_target_sentence = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "该方向不追求让弹药脱离人类授权自主选择目标。",
    )
    complete_target_result = ReportQualityGate().validate(
        complete_target_sentence,
        metadata,
    )
    assert complete_target_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    complete_stage_sentence = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "从领域占位看，无人远程火力装备正处于从单型产品竞争向作战生态竞争转变的阶段。",
    )
    complete_stage_result = ReportQualityGate().validate(
        complete_stage_sentence,
        metadata,
    )
    assert complete_stage_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    complete_mission_sentence = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "该拦截效应器可承担对无人机威胁的硬杀伤或非动能反蜂群任务。",
    )
    complete_mission_result = ReportQualityGate().validate(
        complete_mission_sentence,
        metadata,
    )
    assert complete_mission_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    complete_support_sentence = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "公开对象页支撑该效应器与火控体系配合应对单机到蜂群目标。",
    )
    complete_support_result = ReportQualityGate().validate(
        complete_support_sentence,
        metadata,
    )
    assert complete_support_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    complete_division_sentence = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "从作战阶段看，需求可分为破门、压制、猎歼、补击和防护五个阶段。",
    )
    complete_division_result = ReportQualityGate().validate(
        complete_division_sentence,
        metadata,
    )
    assert complete_division_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    clipped_table = report.replace(
        "分散编组、发射、突防、交战与毁伤评估 |",
        "通信降级、GNSS受扰、目标。 |",
        1,
    )
    clipped_result = ReportQualityGate().validate(clipped_table, metadata)
    assert clipped_result.format_integrity.indicators["has_complete_paragraphs"] is False
    assert clipped_result.passed is False

    equipment_list_table = report.replace(
        "分散编组、发射、突防、交战与毁伤评估 |",
        "JASSM-ER类、PrSM类、低空无人携弹平台 |",
        1,
    )
    equipment_list_result = ReportQualityGate().validate(
        equipment_list_table,
        metadata,
    )
    assert equipment_list_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is True

    dangling_conditional = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "若导航欺骗识别晚于航路偏差形成。",
    )
    dangling_result = ReportQualityGate().validate(
        dangling_conditional,
        metadata,
    )
    assert dangling_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is False

    semantic_clipping = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "相对公开基线，增量机理延伸到任务区自主搜索…。",
    )
    semantic_clipping_result = ReportQualityGate().validate(
        semantic_clipping,
        metadata,
    )
    assert semantic_clipping_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is False

    hard_stem_clipping = report.replace(
        "国际军事竞争加速无人化远程精确火力发展。",
        "开展传感器—授权—发射闭环试验，确。",
    )
    hard_stem_result = ReportQualityGate().validate(
        hard_stem_clipping,
        metadata,
    )
    assert hard_stem_result.format_integrity.indicators[
        "has_complete_paragraphs"
    ] is False
