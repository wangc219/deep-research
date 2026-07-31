from equipment_deep_research.delivery.quality_gate import (
    CANONICAL_REPORT_H3,
    ReportQualityGate,
)


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


def test_quality_gate_can_require_three_natural_disruptive_relationships() -> None:
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
    assert shallow_result.passed is False

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


def test_quality_gate_treats_final_report_max_as_advisory() -> None:
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

    assert result.format_integrity.indicators["has_bounded_report_length"] is False
    assert result.format_integrity.passed is True


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
