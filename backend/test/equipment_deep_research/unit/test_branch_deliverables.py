from dataclasses import replace

from equipment_deep_research.domain.models import (
    AuditResult,
    BaselineFindingPacket,
    CapabilityImageItem,
    EvidenceCard,
    WinningMechanismStageOutput,
    WinningReasoningNode,
)
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.delivery.branch_validator import (
    BranchDeliverableValidator,
)
from equipment_deep_research.orchestration.deliverables import (
    BRANCH_DELIVERABLE_PROFILES,
    BRANCH_REPORT_CONTRACTS,
    BRANCH_WRITER_OUTLINES,
    branch_report_lines,
    branch_writer_brief,
    build_delivery_artifacts,
    _weapon_equipment_card_name,
)
from equipment_deep_research.orchestration.reporting import (
    render_formal_evidence_reference,
    render_report,
)
from equipment_deep_research.orchestration.runner import (
    _clean_report_capability_portrait,
    _compact_report_branch_output,
    _report_decision_brief,
    _report_synthesis_seed,
)


def _store() -> DomainStore:
    store = DomainStore()
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-operation",
            agent_id="operational_employment",
            capability_tags=["operation"],
            topic_focus="无人集群作战运用",
            findings=["集中式指挥在强干扰和节点损失条件下形成单点脆弱性"],
            evidence_ids=["ev-1"],
            confidence=0.82,
            coverage_notes=[],
            open_questions=["低带宽条件下的协同上限是多少"],
            handoff_summary="应发展去中心协同、动态重组和抗干扰自主决策能力。",
            checkpoint="complete",
            limitations=["公开资料不能替代实装压力测试"],
            analysis_sections={
                "mission_chain": ["发现", "决策", "协同", "任务重组"],
                "failure_modes": ["链路压制", "关键节点损失"],
            },
        )
    )
    store.add_reasoning_node(
        WinningReasoningNode(
            object_id="node-s4",
            step=4,
            title="能力映射",
            summary="将任务韧性要求映射为边缘自主决策、低带宽协同和异构接口能力。",
            input_refs=["node-s3"],
            evidence_ids=["ev-1"],
            claim_ids=[],
            confidence=0.8,
            assumptions=["公开资料初步支撑"],
            route="new_winning_mechanism",
            next_action={"action": "continue"},
        )
    )
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L3",
            layer="L3",
            title="能力画像",
            outputs={
                "branch_products": {
                    "tactic_concepts": ["去中心蜂群自主决策", "动态马赛克任务重组", "诱骗-饱和-精打递进"],
                    "tactic_combinations": [f"组合{i}" for i in range(1, 6)],
                    "capability_domains": [f"能力域{i}" for i in range(1, 9)],
                    "capability_indicators": [f"指标{i}" for i in range(1, 31)],
                    "equipment_forms": ["智能蜂群母舰", "异构协同网关"],
                }
            },
            confidence=0.8,
            evidence_ids=["ev-1"],
            gate_passed=True,
            gate_reasons=[],
        )
    )
    store.add_capability_image(
        CapabilityImageItem(
            capability_id="cap-1",
            name="低带宽异构无人作战集群",
            equipment_category="无人作战平台",
            capability_type="new_capability",
            source_winning_logic="以分布式自治降低单点失效影响",
            related_scenario="强电磁压制下的无人集群任务",
            priority="高",
            capability_gap="现有平台跨型接口和自主重组不足",
            capability_image="形成边缘决策、任务动态重组和断链自治的一体化能力。",
            evidence_ids=["ev-1"],
            confidence=0.81,
            mission_effect="保持任务链连续",
            equipment_form="低特征无人机、巡飞弹与边缘任务控制终端",
            baseline_system="公开型号锚点为Switchblade 600 Block 2巡飞弹族谱。",
            development_path="通过弱网协同、节点损耗和任务重构试验验证装备效能。",
            deep_capability_portrait=(
                "该装备面向强电磁压制下的侦察、诱骗和精确打击任务。"
                "可证伪指标包括断链任务完成率、节点损耗后重构时间、目标分配闭合率。"
            ),
            system_dependencies=["统一任务语义", "可信身份与时钟"],
            risk_boundaries=["自主权限必须受任务规则约束"],
        )
    )
    return store


def test_dynamic_g_branch_projects_accepted_capability_images_into_delivery_slots() -> None:
    store = _store()
    store.stage_outputs.clear()

    output = build_delivery_artifacts(
        topic="强干扰下无人装备跨域任务续接",
        branch="G",
        blueprint={"required_outputs": []},
        store=store,
    )["branch_deliverables"]

    assert output["delivery_status"] == "complete"
    assert all(row["met"] for row in output["completion"].values())
    assert output["products"]["cross_domain_gaps"] == [
        "现有平台跨型接口和自主重组不足"
    ]
    assert output["products"]["tactic_combinations"]
    assert output["products"]["capability_indicators"]
    assert output["products"]["equipment_forms"] == [
        "低特征无人机、巡飞弹与边缘任务控制终端"
    ]


def _three_layer_model_body(extra: str = "") -> str:
    body = """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

对手在濒海地域实施高烈度压制，关键时间窗位于首轮任务链形成前后，约束条件包括弱网与补给受限。

### ② 新战法或新概念技术及制胜机理

现有范式依赖集中链路而存在不足；新战法以分布式无人协同重构推理链，因此形成反制与持续作战制胜优势。

### ③ 装备能力特征清单

能力域覆盖感知、打击、压制和保障，指标方向包括射程、响应时间、自主等级、成本量级和规模量级。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

沿用改进用于现役升级，集成创新用于新装备研发，原理突破保留为远期预研。

### ⑤ 核心技术清单与攻关优先级

核心技术点包括抗干扰制导律、材料体系和协同算法，标注成熟度、瓶颈和P0/P1优先级。

### ⑥ 技术耦合与短板风险

感知、通信和制导存在依赖与耦合，卡脖子短板可能导致级联失效并拖垮能力链。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

能力域、指标画像和装备谱系位置用于说明相对现有装备体系的边界。

### ⑧ 效能贡献评估

该方向通过补链、强链、开链改善任务闭环，量化方向包括突防率、交换比和决策周期改善量级。

### ⑨ 发展优先级与近期抓手

P0启动演示验证项目，设置验收指标、通过条件和失败条件；公开来源和证据依据用于约束判断。
"""
    details = "".join(
        f"- 高价值补充论证{index}：聚焦任务阶段、体系接口、失效边界和验证路径。\n"
        for index in range(1, 81)
    )
    return f"{body}\n{extra}\n{details}"


def test_a_branch_artifacts_enforce_architecture_counts_and_deep_content() -> None:
    artifacts = build_delivery_artifacts(
        topic="无人智能集群新战法",
        branch="A",
        blueprint={"required_outputs": ["战法概念集"]},
        store=_store(),
    )

    completion = artifacts["branch_deliverables"]["completion"]
    assert all(row["met"] for row in completion.values())
    assert len(artifacts["demand_cards"]) == 1
    assert artifacts["capability_panorama"]["actual_counts"]["capability_domains"] == 9
    analysis = artifacts["intermediate_agent_analysis"]
    assert "作用机制和约束关系" in analysis
    assert "装备能力域、功能和指标边界" in analysis
    assert set(artifacts["branch_deliverables"]["report_quality_requirements"]) == {
        "领域属性符合性",
        "装备能力图像",
        "制胜效能",
        "创新性",
        "可实现性（成熟度）",
    }


def test_a_branch_projects_complete_dynamic_portfolio_without_legacy_products() -> None:
    source = _store().capability_images["cap-1"]
    store = DomainStore()
    rows = [
        (
            "cap-a",
            "双模反辐射巡飞猎歼弹药",
            "远程巡飞、辐射活动记忆、末段光电复核和直接毁伤",
        ),
        (
            "cap-b",
            "可消耗低空察打一体无人突击平台",
            "低空任务区驻留、断链自主、猎歼短时目标和安全中止",
        ),
        (
            "cap-c",
            "地面发射战役纵深精确制导导弹",
            "分布式发射、受扰导航、远程纵深覆盖和再打击",
        ),
        (
            "cap-d",
            "固定构型低成本巡航效应器族",
            "低成本批产、供应链替代、多轴规模齐射和库存补库",
        ),
        (
            "cap-e",
            "短窗事件触发高速猎歼弹药",
            "时间敏感目标压制、多联装并发和战斗部毁伤评估",
        ),
    ]
    for capability_id, name, mechanism in rows:
        store.add_capability_image(
            replace(
                source,
                capability_id=capability_id,
                name=name,
                equipment_category=name,
                source_winning_logic=f"以{mechanism}改变目标暴露与火力到达关系",
                operational_mechanism=mechanism,
                strike_chain_contribution=f"{mechanism}形成补链或强链贡献",
                evidence_ids=["ev-1"],
            )
        )

    artifacts = build_delivery_artifacts(
        topic="无人远程火力打击装备",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )

    output = artifacts["branch_deliverables"]
    assert output["delivery_status"] == "complete"
    assert output["completion"] == {
        "tactic_concepts": {"target": 3, "actual": 3, "met": True},
        "tactic_combinations": {"target": 5, "actual": 5, "met": True},
        "capability_domains": {"target": 8, "actual": 8, "met": True},
        "capability_indicators": {"target": 30, "actual": 30, "met": True},
    }


def test_all_branches_define_substantive_final_sections() -> None:
    assert list(BRANCH_DELIVERABLE_PROFILES) == list("ABCDEFGH")
    assert all(profile["required_sections"] for profile in BRANCH_DELIVERABLE_PROFILES.values())
    assert list(BRANCH_REPORT_CONTRACTS) == list("ABCDEFGH")
    assert len({row["thesis"] for row in BRANCH_REPORT_CONTRACTS.values()}) == 8
    assert list(BRANCH_WRITER_OUTLINES) == list("ABCDEFGH")
    assert all(
        len(outline["sections"]) == 5
        for outline in BRANCH_WRITER_OUTLINES.values()
    )
    assert all(
        not any(
            label in section
            for label in ("深度性", "军事价值性", "前瞻性", "新颖性")
            for section in outline["sections"]
        )
        for outline in BRANCH_WRITER_OUTLINES.values()
    )


def test_core_branch_writer_briefs_enforce_requested_outputs() -> None:
    branch_a = branch_writer_brief("A")
    assert branch_a["target_counts"] == {
        "tactic_concepts": 3,
        "tactic_combinations": 5,
        "capability_domains": 8,
        "capability_indicators": 30,
    }
    assert "战法概念集：3种新战法" in branch_a["required_sections"]
    assert any("30项能力指标" in item for item in branch_a["mandatory_content"])

    branch_b = branch_writer_brief("B")
    assert "武器装备能力需求卡片" in branch_b["required_sections"]
    assert any("能力全景图" in item for item in branch_b["mandatory_content"])
    assert any("六步效果链" in item for item in branch_b["mandatory_content"])

    branch_c = branch_writer_brief("C")
    assert branch_c["target_counts"] == {
        "case_patterns": 6,
        "future_scenarios": 3,
        "emerging_equipment_categories": 4,
    }
    assert "案例规律报告：6条核心规律" in branch_c["required_sections"]
    assert any("4大新兴装备类别" in item for item in branch_c["mandatory_content"])

    branch_f = branch_writer_brief("F")
    assert branch_f["branch_name"] == "体系对抗博弈发现"
    assert "体系脆弱性规律与级联失效场景" in branch_f["required_sections"]
    assert any("动态重构" in item for item in branch_f["mandatory_content"])
    assert branch_writer_brief("A")["hard_max_chars"] == 0


def test_adaptive_branch_writer_briefs_have_distinct_mission_focus() -> None:
    expected = {
        "D": ("技术机会谱系", "成熟窗口"),
        "E": ("对手能力形成链", "预警信号"),
        "F": ("级联失效场景", "替代链"),
        "G": ("决定性协同缝隙", "跨密域"),
        "H": ("新型威胁画像", "非致命反制"),
    }
    for branch, (section_marker, content_marker) in expected.items():
        brief = branch_writer_brief(branch)
        assert any(section_marker in item for item in brief["required_sections"])
        assert any(content_marker in item for item in brief["mandatory_content"])
        assert brief["target_chars"] == "4200-6500"
        assert brief["hard_max_chars"] == 0


def test_a_branch_completion_counts_declared_products_not_panorama_union() -> None:
    store = _store()
    stage = store.stage_outputs["stage-L3"]
    branch_products = dict(stage.outputs["branch_products"])
    branch_products["capability_domains"] = [f"能力域{i}" for i in range(1, 8)]
    branch_products["capability_indicators"] = [
        f"指标{i}" for i in range(1, 30)
    ]
    store.stage_outputs["stage-L3"] = replace(
        stage,
        outputs={"branch_products": branch_products},
    )

    artifacts = build_delivery_artifacts(
        topic="数量门槛验证",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )
    completion = artifacts["branch_deliverables"]["completion"]
    assert completion["capability_domains"] == {
        "target": 8,
        "actual": 7,
        "met": False,
    }
    assert completion["capability_indicators"] == {
        "target": 30,
        "actual": 29,
        "met": False,
    }


def test_branch_products_use_latest_valid_l3_after_backtrack() -> None:
    store = _store()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L3-repair",
            layer="L3",
            title="回溯修订后的分支产物",
            outputs={
                "branch_products": {
                    "tactic_concepts": ["修订后的新战法"],
                    "tactic_combinations": ["修订组合"],
                    "capability_domains": ["修订能力域"],
                    "capability_indicators": ["修订指标"],
                    "equipment_forms": ["修订装备形态"],
                }
            },
            confidence=0.85,
            evidence_ids=["ev-1"],
            gate_passed=True,
            gate_reasons=[],
            created_at="9999-12-31T23:59:59+00:00",
        )
    )

    products = build_delivery_artifacts(
        topic="回溯产物验证",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )["branch_deliverables"]["products"]

    assert products["tactic_concepts"] == ["修订后的新战法"]
    assert "去中心蜂群自主决策" not in products["tactic_concepts"]


def test_c_branch_accepts_case_aliases_and_explicit_convergence_products() -> None:
    store = _store()
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-case",
            agent_id="case_research",
            capability_tags=["case_reconstruction"],
            topic_focus="单案例复盘",
            findings=["主案例结论"],
            evidence_ids=["ev-1"],
            confidence=0.82,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="单案例主线",
            checkpoint="complete",
            limitations=[],
            analysis_sections={
                "cross_case_patterns": [f"规律{i}" for i in range(1, 7)],
                "future_scenario_mapping": [f"场景{i}" for i in range(1, 4)],
            },
        )
    )
    convergence = {
        "cross_branch_links": [
            "四大新兴装备类别收敛：可消耗无人装备包；分层反无人系统；抗扰任务网络；节点抢修保障装备"
        ]
    }

    artifacts = build_delivery_artifacts(
        topic="单案例复盘",
        branch="C",
        blueprint={"required_outputs": []},
        store=store,
        convergence=convergence,
    )

    completion = artifacts["branch_deliverables"]["completion"]
    assert completion == {
        "case_patterns": {"target": 6, "actual": 6, "met": True},
        "future_scenarios": {"target": 3, "actual": 3, "met": True},
        "emerging_equipment_categories": {"target": 4, "actual": 4, "met": True},
    }
    assert artifacts["branch_deliverables"]["delivery_status"] == "complete"


def test_report_decision_brief_is_bounded_public_and_preserves_core_counts() -> None:
    store = _store()
    store.add_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_title="公开联合任务网络研究",
            source_url="https://example.test/joint-mission-network",
            source_tier="A",
            claim="强干扰条件下需要分布式协同与任务重组。",
            excerpt="公开试验表明单点链路和集中节点会放大任务中断风险。",
            source_location="公开网页",
            quality_assessment="权威公开来源，结论仍需场景验证。",
            created_by="test",
        )
    )
    artifacts = build_delivery_artifacts(
        topic="无人智能集群新战法",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )
    brief = _report_decision_brief(
        store=store,
        branch_output=artifacts["branch_deliverables"],
        convergence={
            "clusters": [
                {
                    "name": "任务链韧性",
                    "packet_ids": ["packet-operation"],
                    "shared_need": "S1-S6判断：强干扰下必须闭合ev-1对应的任务重组能力。",
                }
            ],
            "conflicts": ["packet-operation提示公开资料不能替代实装验证。"],
            "priorities": ["优先形成cap-1对应的断链自治能力。"],
        },
    )
    serialized = str(brief)
    assert "packet-operation" not in serialized
    assert "ev-1" not in serialized
    assert "cap-1" not in serialized
    assert "S1-S6" not in serialized
    assert brief["capability_decisions"][0]["public_sources"] == [
        {
            "title": "公开联合任务网络研究",
            "url": "https://example.test/joint-mission-network",
        }
    ]
    decision = brief["capability_decisions"][0]
    assert decision["operational_process"] == []
    assert decision["verification_plan"] == []
    assert "关键作战流程" in decision["capability_portrait"]
    synchronized_image = next(iter(store.capability_images.values()))
    assert synchronized_image.capability_image == (
        synchronized_image.deep_capability_portrait
    )
    assert _clean_report_capability_portrait(
        synchronized_image.capability_image
    ) == decision["capability_portrait"]
    products = brief["branch_products"]
    assert len(products["tactic_concepts"]) == 3
    assert len(products["tactic_combinations"]) == 5
    assert len(products["capability_domains"]) == 8
    assert len(products["capability_indicators"]) == 30


def test_report_decision_brief_rebuilds_portrait_from_final_subtype_name() -> None:
    store = _store()
    original = next(iter(store.capability_images.values()))
    store.capability_images[original.capability_id] = replace(
        original,
        name="射频复核反舰巡飞猎歼弹药",
        equipment_category="反舰巡飞猎歼弹药",
        equipment_form="长航时可消耗多模反舰巡飞猎歼弹药",
        target_scenario="强电磁压制下远海反舰火力链断裂后的目标复获阶段",
        problem_statement="外部航迹失效后难以发现并确认机动水面舰艇",
        scientific_principle="被动射频候选发现与成像交叉复核",
        enabling_technologies=["被动射频", "成像识别", "安全拒打"],
        operational_concept="控制传感器暴露并完成跨模态复核后受控攻击",
        operational_process=[
            "被动射频候选发现",
            "成像传感器短时开启",
            "跨模态交叉确认",
            "直接攻击或拒打",
        ],
        capability_outcome="断链后确认并直接攻击经授权水面舰艇",
        mission_effect="形成断链后的直接反舰毁伤",
        winning_mechanism="以跨模态互证压缩诱饵误导收益",
    )
    artifacts = build_delivery_artifacts(
        topic="强电磁压制下远海反舰续接",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )

    _report_decision_brief(
        store=store,
        branch_output=artifacts["branch_deliverables"],
        convergence={},
    )

    synchronized = store.capability_images[original.capability_id]
    portrait = synchronized.capability_image
    assert all(
        marker in portrait
        for marker in ("被动射频", "成像", "交叉确认", "直接攻击")
    )


def test_report_synthesis_seed_keeps_only_high_value_editorial_anchors() -> None:
    store = _store()
    artifacts = build_delivery_artifacts(
        topic="无人智能集群新战法",
        branch="A",
        blueprint={"required_outputs": []},
        store=store,
    )
    seed = _report_synthesis_seed(
        store=store,
        branch_output=artifacts["branch_deliverables"],
        convergence={
            "priorities": [f"优先信号{i}" for i in range(8)],
            "conflicts": [f"反证边界{i}" for i in range(6)],
        },
    )

    assert len(seed["decisive_anchors"]) <= 3
    assert len(seed["mission_chain_breaks"]) <= 3
    assert len(seed["capability_cues"]) <= 7
    assert len(seed["counterevidence_and_limits"]) <= 2
    assert len(seed["priority_signals"]) <= 3
    assert (
        "Switchblade 600 Block 2"
        in seed["capability_cues"][0]["public_equipment_baseline"]
    )
    assert {
        "capability_gap",
        "development_path",
        "priority",
        "boundary",
    } <= set(seed["capability_cues"][0])
    serialized = str(seed)
    assert "branch_products" not in serialized
    assert "packet-" not in serialized
    assert "ev-" not in serialized


def test_reporter_seed_preserves_all_six_s6_directions_and_disruptive_relationships() -> None:
    store = _store()
    original = next(iter(store.capability_images.values()))
    store.capability_images.clear()
    relationships = [
        "以低成本规模消耗反转拦截经济学",
        "从发射平台转向长航时持续存在的无人火力",
        "以毁伤评估和再打击压缩决策周期",
        "用电子压制与定向能形成非动能毁伤效应",
        "以弱网任务重构实现传感器—射手解耦",
        "以人在回路、人工授权和安全降级约束自主交战",
    ]
    for index, relationship in enumerate(relationships, start=1):
        store.add_capability_image(
            replace(
                original,
                capability_id=f"cap-{index}",
                name=f"具体武器装备方向{index}",
                priority=f"P{index}",
                novelty=relationship,
            )
        )
    artifacts = build_delivery_artifacts(
        topic="西太反介入装备能力缺口",
        branch="F",
        blueprint={"required_outputs": []},
        store=store,
    )

    seed = _report_synthesis_seed(
        store=store,
        branch_output=artifacts["branch_deliverables"],
        convergence=None,
    )

    assert len(seed["capability_cues"]) == 6
    assert {item["direction"] for item in seed["capability_cues"]} == {
        f"具体武器装备方向{index}" for index in range(1, 7)
    }
    assert all(item["disruptive_relationship"] for item in seed["capability_cues"])


def test_adaptive_branch_report_products_are_bounded_for_editorial_use() -> None:
    compact = _compact_report_branch_output(
        {
            "branch": "G",
            "branch_name": "跨域融合发现",
            "required_sections": ["跨域缝隙图谱"],
            "completion": {},
            "products": {
                "cross_domain_gaps": [f"跨域缝隙{i}" for i in range(12)],
                "capability_indicators": [f"指标{i}" for i in range(30)],
            },
            "report_contract": {},
        }
    )
    assert len(compact["products"]["cross_domain_gaps"]) == 6
    assert len(compact["products"]["capability_indicators"]) == 6


def test_similar_branches_deliver_structured_demand_cards() -> None:
    for branch in "DEFGH":
        profile = BRANCH_DELIVERABLE_PROFILES[branch]
        assert "装备能力需求图像（需求卡片）" in profile["required_sections"]
        assert "demand_cards" in profile["product_keys"]
        artifacts = build_delivery_artifacts(
            topic="测试主题",
            branch=branch,
            blueprint={"required_outputs": []},
            store=_store(),
        )
        cards = artifacts["branch_deliverables"]["products"]["demand_cards"]
        assert cards and isinstance(cards[0], dict), branch
        assert cards[0]["weapon_equipment"] == "低带宽异构无人作战集群"
        assert cards[0]["equipment_configuration"].startswith("低特征无人机")
        assert cards[0]["development_mode"] == "新研武器装备"
        assert cards[0]["key_indicators"] == [
            "断链任务完成率",
            "节点损耗后重构时间",
            "目标分配闭合率",
        ]
        assert "capability_domain" not in cards[0]


def test_demand_card_prefers_valid_project_name_over_configuration_component() -> None:
    original = next(iter(_store().capability_images.values()))
    cases = (
        (
            "多模复核反辐射巡飞猎歼弹",
            "中程巡飞弹体、被动射频导引头、光电复核载荷组成",
        ),
        (
            "短距起降低特征无人火力母机",
            "短距起降低特征无人机体、模块化载架、诱饵与巡飞弹挂载组成",
        ),
        (
            "节点护卫反无人机拦截车",
            "机动防护车、搜索雷达、Coyote类可消耗拦截弹和本地火控组成",
        ),
        (
            "半潜预置远程导弹火力舱",
            "低特征半潜无人艇体、密封化弹药舱和条件授权火控组成",
        ),
    )

    for name, equipment_form in cases:
        image = replace(original, name=name, equipment_form=equipment_form)
        assert _weapon_equipment_card_name(image) == name


def test_g_branch_projects_authoritative_indicator_portrait() -> None:
    store = _store()
    image = next(iter(store.capability_images.values()))
    store.capability_images[image.capability_id] = replace(
        image,
        indicator_portrait=(
            "以断链任务完成率、重构时延和目标分配闭合率形成联合验证口径。"
        ),
    )
    stage = next(iter(store.stage_outputs.values()))
    store.stage_outputs[stage.stage_id] = replace(
        stage,
        outputs={"branch_products": {}},
    )

    artifacts = build_delivery_artifacts(
        topic="强干扰条件下无人集群任务",
        branch="G",
        blueprint={"required_outputs": []},
        store=store,
    )

    assert artifacts["branch_deliverables"]["products"]["capability_indicators"] == [
        "以断链任务完成率、重构时延和目标分配闭合率形成联合验证口径。"
    ]


def test_branch_b_validator_rejects_abstract_capability_domain_as_card_subject() -> None:
    artifacts = build_delivery_artifacts(
        topic="测试主题",
        branch="B",
        blueprint={"required_outputs": []},
        store=_store(),
    )
    deliverables = {
        "demand_cards": artifacts["demand_cards"],
        "capability_panorama": artifacts["capability_panorama"],
        "reasoning_traceability": {"trace_chain": []},
    }
    validator = BranchDeliverableValidator()

    assert validator.validate_branch_b(deliverables).passed is True

    abstract = dict(artifacts["demand_cards"][0])
    abstract["weapon_equipment"] = "智能协同能力域"
    rejected = validator.validate_branch_b(
        {**deliverables, "demand_cards": [abstract]}
    )

    assert rejected.passed is False
    assert "card_0_weapon_equipment" in rejected.gaps


def test_branch_sections_render_own_products_without_duplication() -> None:
    artifacts = build_delivery_artifacts(
        topic="测试主题",
        branch="D",
        blueprint={"required_outputs": []},
        store=_store(),
    )
    lines = branch_report_lines(artifacts["branch_deliverables"])
    text = "\n".join(lines)
    assert "### 装备能力需求图像（需求卡片）" in text
    # 需求卡片条目只出现在自己的章节，不再因 fallback 在每个章节重复
    card_lines = [line for line in lines if "低带宽异构无人作战集群" in line]
    assert len(card_lines) == 1
    assert "### 分支论证主线" in text
    assert "关键节点受压、通信降级或保障中断" not in text
    assert "技术如何改变任务机制与体系关系" in text
    assert "### 深度研判尺度" not in text
    assert "- 深度性：" not in text


def _render_branch_report(branch: str, store: DomainStore) -> str:
    route = {
        "A": "new_winning_mechanism",
        "B": "traditional_gap",
        "C": "war_case_learning",
    }[branch]
    artifacts = build_delivery_artifacts(
        topic="分支精简报告验证",
        branch=branch,
        blueprint={"required_outputs": []},
        store=store,
    )
    return render_report(
        topic="分支精简报告验证",
        route=route,
        store=store,
        coverage={"coverage_passed": True, "missing_required_tags": []},
        audit=AuditResult(
            audit_id="audit-test",
            status="approved",
            checks={"coverage": True},
            comments=[],
        ),
        executive_summary="关键判断应聚焦任务链断点、作战效果、创新机制和未来边界。" * 100,
        discovery_branch=branch,
        delivery_artifacts=artifacts,
    ).body


def test_a_branch_report_is_compact_and_preserves_required_counts() -> None:
    report = _render_branch_report("A", _store())

    assert "战法概念集：3种新战法" in report
    assert "战法组合：5种组合" in report
    assert "装备能力需求图像：8大能力域" in report
    assert "30项能力指标" in report
    assert "关联装备形态建议" in report
    assert "智能蜂群母舰" in report
    assert len(report) < 14_000


def test_complete_codex_branch_body_is_not_repeated_by_deterministic_section() -> None:
    model_body = _three_layer_model_body(
        "A分支的新战法、战法组合和能力指标已压缩融入三层九项。"
    )
    artifacts = build_delivery_artifacts(
        topic="新战法报告去重",
        branch="A",
        blueprint={"required_outputs": []},
        store=_store(),
    )
    report = render_report(
        topic="新战法报告去重",
        route="new_winning_mechanism",
        store=_store(),
        coverage={"coverage_passed": True, "missing_required_tags": []},
        audit=AuditResult(
            audit_id="audit-test",
            status="approved",
            checks={"coverage": True},
            comments=[],
        ),
        executive_summary=model_body,
        discovery_branch="A",
        delivery_artifacts=artifacts,
    ).body

    assert "公开来源索引" not in report
    assert "Codex" not in report
    assert "Agent" not in report
    assert "## 1. 核心结论" not in report
    assert "## 2. 分支深度综合研判与军事运用价值" not in report
    assert "### 3.1 战法概念集：3种新战法" not in report
    assert report.count("### ② 新战法或新概念技术及制胜机理") == 1
    assert sum(line.startswith("# ") for line in report.splitlines()) == 1


def test_complete_model_report_keeps_compact_sources_and_sidecar_has_full_audit_fields() -> None:
    store = _store()
    store.add_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_title="DoD counter-UAS fact sheet",
            source_url=(
                "https://media.defense.gov/2024/Dec/05/"
                "FACT-SHEET-STRATEGY-FOR-COUNTERING-UNMANNED-SYSTEMS.PDF"
            ),
            source_tier="A",
            claim="E1：该事实单直接支持反无人体系需要提升探测与韧性。",
            excerpt="The Department will improve detection and increase force resilience.",
            source_location="text:artifact#p13",
            quality_assessment="reader_fetched",
            created_by="test",
            created_at="2026-07-20T10:00:00+00:00",
        )
    )
    store.add_evidence(
        EvidenceCard(
            evidence_id="ev-background",
            source_title="Background overview",
            source_url="https://example.org/background",
            source_tier="B",
            claim="E2：该材料仅提供相关背景。",
            excerpt="",
            source_location="codex:web_search",
            quality_assessment="hosted_search_citation",
            created_by="test",
            created_at="2026-07-20T10:00:00+00:00",
        )
    )
    artifacts = build_delivery_artifacts(
        topic="证据附录验证",
        branch="B",
        blueprint={"required_outputs": []},
        store=store,
    )

    report = render_report(
        topic="证据附录验证",
        route="traditional_gap",
        store=store,
        coverage={"coverage_passed": True, "missing_required_tags": []},
        audit=AuditResult(
            audit_id="audit-test",
            status="approved",
            checks={"coverage": True},
            comments=[],
        ),
        executive_summary=(
            "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n\n"
            "模型正文。"
        ),
        discovery_branch="B",
        delivery_artifacts=artifacts,
        prefer_model_report=True,
    ).body

    assert report.index("**核心公开来源索引**") > report.index("模型正文")
    assert "## 核心公开来源索引" not in report
    assert "本报告从 2 项正式证据中列示" in report
    assert report.count("**E0") == 2
    assert "## 正式证据引用说明" not in report

    ledger = render_formal_evidence_reference(store)
    assert "本报告登记的 2 项正式证据" in ledger
    assert "### E01｜DoD counter-UAS fact sheet" in ledger
    assert "### E02｜Background overview" in ledger
    assert "2024-12-05" in ledger
    assert "材料化正文第 13 段" in ledger
    assert "能力方向“低带宽异构无人作战集群”" in ledger
    assert "直接支撑（已保存原文摘录及正文定位）" in ledger
    assert "未与正式结论节点绑定，仅作为背景材料" in ledger
    assert "背景/间接支撑（未绑定正式结论，不得单独支撑关键结论）" in ledger
    assert "发布日期未闭环" in ledger
    assert ledger.count("**URL：**") == 2


def test_preferred_b_report_never_reenters_deterministic_template() -> None:
    model_body = _three_layer_model_body(
        "需求卡片与能力全景图共同指向任务链韧性缺口。"
    )
    store = _store()
    artifacts = build_delivery_artifacts(
        topic="传统能力缺口报告去重",
        branch="B",
        blueprint={"required_outputs": []},
        store=store,
    )
    report = render_report(
        topic="传统能力缺口报告去重",
        route="traditional_gap",
        store=store,
        coverage={"coverage_passed": True, "missing_required_tags": []},
        audit=AuditResult(
            audit_id="audit-test",
            status="approved",
            checks={"coverage": True},
            comments=[],
        ),
        executive_summary=model_body,
        discovery_branch="B",
        delivery_artifacts=artifacts,
        prefer_model_report=True,
    ).body

    assert report.count("需求卡片与能力全景图共同指向任务链韧性缺口") == 1
    assert "## 1. 核心结论" not in report
    assert "## 2. 分支深度综合研判与军事运用价值" not in report
    assert "## 3. 传统能力缺口发现分支专用输出" not in report
    assert sum(line.startswith("# ") for line in report.splitlines()) == 1


def test_b_branch_report_keeps_cards_panorama_and_traceability_compact() -> None:
    report = _render_branch_report("B", _store())

    assert "武器装备能力需求卡片" in report
    assert "具体待发展武器装备" in report
    assert "低带宽异构无人作战集群" in report
    assert "能力域/需求" not in report
    assert "能力全景图" in report
    assert "深度研究结论与推理链回溯" in report
    assert "reasoning_traceability.json" not in report
    assert "需求卡片、证据链与可证伪条件的逐项映射" in report
    assert len(report) < 10_000


def test_c_branch_report_keeps_six_three_four_contract_without_full_dump() -> None:
    store = _store()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-C-products",
            layer="L3",
            title="案例分支产物",
            outputs={
                "branch_products": {
                    "case_patterns": [f"核心规律{i}：体系与战法共同改变任务效果" for i in range(1, 7)],
                    "future_scenarios": [f"高置信场景{i}：对手适应与技术扩散触发能力演化" for i in range(1, 4)],
                    "emerging_equipment_categories": [f"新兴装备类别{i}：形成可验证的反制与制衡能力" for i in range(1, 5)],
                }
            },
            confidence=0.8,
            evidence_ids=["ev-1"],
            gate_passed=True,
            gate_reasons=[],
        )
    )
    report = _render_branch_report("C", store)

    assert "案例规律报告：6条核心规律" in report
    assert "未来场景预测：3类高置信场景" in report
    assert "装备需求图像：4大新兴装备类别" in report
    assert "核心规律6" in report
    assert "高置信场景3" in report
    assert "新兴装备类别4" in report
    assert "https://" not in report
    assert len(report) < 10_000
