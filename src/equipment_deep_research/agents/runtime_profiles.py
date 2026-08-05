"""Codex-facing runtime profiles for every research-agent scene.

The local harness remains the authority that executes and validates tools.
These profiles tell each isolated Codex session which governed tools and
skills are relevant, which method to follow, and what quality gates apply.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from equipment_deep_research.agents.performance import role_card_id
from equipment_deep_research.domain.research_focus import (
    baseline_agent_expansion_lenses,
    branch_reference_focus,
    disruptive_seed_context,
)
from equipment_deep_research.orchestration.execution_contracts import (
    is_quality_execution_profile_id,
)


SAFETY_BOUNDARY = (
    "仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、"
    "具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。"
)


QUERY_DOMINANT_BUSINESS_AGENT_IDS = {
    "international_situation",
    "combat_scenario",
    "weapon_equipment",
    "operational_employment",
    "case_research",
    "technology_radar",
    "opponent_monitoring",
    "system_confrontation",
    "cross_domain_fusion",
    "nontraditional_security",
}


SWARM_RUNTIME_SKILL_IDS = [
    "js-equipment-agent-runtime",
    "js-winning-shared-layer",
]


MILITARY_MISSION_LENSES: dict[str, str] = {
    "orchestrator": "所有蓝图和Agent选择都要落到可验证的打击、歼灭、反制、拒止、威慑、抗毁或持续作战效果，避免只优化流程覆盖。",
    "international_situation": "把联盟、部署、采购和安全态势变化转换为预警窗口、任务压力及拒止/威慑可信度影响。",
    "combat_scenario": "用任务阶段、对手体系和失败条件检验发现—决策—协同—打击—评估—再组织链能否闭合。",
    "weapon_equipment": "说明装备能力如何增强目标发现、火力协同、打击毁伤、反制抗扰、区域拒止、抗毁恢复或持续保障。",
    "operational_employment": "比较战法与力量协同时，以任务闭环、打击/歼灭效果、反制能力、战损续接和持续作战为判据。",
    "scenario_divergence": "候选方向只有在能够改变未来战争中的打击、反制、拒止、威慑或体系生存机制时才进入下游。",
    "case_research": "从战例中提炼改变打击链、成本交换、反制窗口、体系抗毁和持续作战的因果规律及迁移边界。",
    "technology_radar": "判断技术能否带来探测、决策、火力、毁伤、反制、抗扰、机动或保障环节的任务级跃迁。",
    "opponent_monitoring": "研判对手能力形成将如何压缩己方预警与反应窗口，并牵引削弱、延迟、拒止或制衡能力。",
    "system_confrontation": "围绕体系节点失效、替代链路和级联效应，评估打击/反制闭环与战损后任务续接能力。",
    "cross_domain_fusion": "检验跨域数据、权限、时序和接口是否真正缩短火力闭环并提高拒止、反制与抗毁能力。",
    "nontraditional_security": "以保护关键任务和基础设施、限制威胁扩散、恢复行动能力及实施可控反制为军事价值边界。",
    "convergence_fusion": "按军事任务后果和增量价值聚合结论，优先保留能改变打击、反制、拒止、威慑或持续作战机制的Claim。",
    "winning_mechanism": "建立对手体系—任务链断点—打击/反制效果—装备能力—差距—能力画像的军事因果闭环。",
    "winning_s1_opponent": "以Query为锚提出竞争性对手体系与反适应假设，定位可被削弱、延迟、欺骗、拒止或制衡的任务级环节；上游只作证据约束。",
    "winning_s2_operations": "以Query为锚发散机制不同的战法与运用路径，比较其打击/歼灭闭环、反制效率、拒止强度、抗毁恢复和持续作战增益。",
    "winning_s3_breakthrough": "以Query核心矛盾发散竞争性突破机制，解释其如何产生可验证的打击、反制、拒止、威慑或体系生存效果。",
    "winning_s4_capability": "从Query要求的作战效果反推装备功能、性能约束和体系接口，确保直接打击/反制能力主导，支撑层不得反客为主。",
    "winning_s5_gap": "以Query的作战后果评估差距，比较升级、新研和非装备缓解，按可恢复的打击、反制、拒止、抗毁效果排序。",
    "winning_s6_image": "能力画像只保留能够形成显著打击/反制价值、未来对抗优势和可证伪建设路径的装备方向。",
    "winning_step_critic": "拒绝缺少军事任务效果、作用机理、证据依据或失效边界的步骤结果，并只要求最小修复。",
    "winning_round_critic": "检查S1–S6是否形成连续打击/反制军事因果链，避免技术名词、流程完整或证据数量替代真实作战价值。",
    "winning_dynamic_specialist": "专用补强必须改变指定S节点的打击/反制判断或证据强度，不能只增加背景材料。",
    "auditor": "审计关键军事任务结论的证据匹配、因果跨度、失效边界和公开来源安全边界。",
    "reporter": "以打击、歼灭、反制、拒止、威慑、抗毁和持续作战价值统摄证据与S1–S6，形成面向未来战争的装备决策报告。",
}


def military_mission_lens(agent_id: str) -> str:
    return MILITARY_MISSION_LENSES.get(
        agent_id,
        "核心判断必须落到可验证的军事任务效果、作用机理和失效边界。",
    )


CODEX_BRANCH_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "A": {
        "name": "新战法发现",
        "methodology": [
            "审查现有战法与任务链",
            "构造竞争性新战法",
            "用反事实检验突破口",
            "映射S2-S4与验证路径",
        ],
        "quality_gates": [
            "新战法说明适用条件和失败模式",
            "效果链可追溯到证据或显式假设",
        ],
        "output_focus": [
            "现有战法基线",
            "新战法",
            "效果链",
            "装备能力映射",
            "验证路径",
        ],
    },
    "B": {
        "name": "传统能力缺口发现",
        "methodology": [
            "建立传统任务和装备基线",
            "形成能力-任务矩阵",
            "执行S4-S6五档差距评估",
            "比较升级与新研",
        ],
        "quality_gates": ["差距等级具备比较依据", "升级与新研方向说明边界和优先级"],
        "output_focus": ["装备基线", "能力要求", "五档差距", "升级方向", "优先级"],
    },
    "C": {
        "name": "局部战争案例经验",
        "methodology": [
            "多语言案例检索",
            "事实与时间线还原",
            "构建因果链",
            "跨案例比较",
            "检验未来迁移边界",
        ],
        "quality_gates": ["事实、推断和争议分离", "经验迁移说明背景差异与不可迁移项"],
        "output_focus": [
            "事实时间线",
            "关键决策点",
            "因果链",
            "跨案例模式",
            "未来场景映射",
        ],
    },
    "D": {
        "name": "技术驱动发现",
        "methodology": [
            "扫描技术信号",
            "评估TRL与工程节点",
            "识别限制条件",
            "反向构造颠覆场景",
            "映射S3/S4/S6",
        ],
        "quality_gates": ["成熟度有试验或项目节点依据", "技术潜力不等同于已形成能力"],
        "output_focus": ["技术雷达", "成熟度", "能力潜力", "颠覆场景", "阶段验证"],
    },
    "E": {
        "name": "对手动向牵引发现",
        "methodology": [
            "建立装备/演习/条令变化基线",
            "识别异常动向",
            "估计能力形成节奏",
            "映射S1与S3-S6",
        ],
        "quality_gates": ["变化必须相对基线成立", "意图判断包含替代假设和预警指标"],
        "output_focus": [
            "变化基线",
            "能力形成节奏",
            "威胁效应",
            "体系依赖",
            "对冲能力",
        ],
    },
    "F": {
        "name": "体系对抗博弈发现",
        "methodology": [
            "建立红蓝体系边界",
            "绘制任务与接口依赖",
            "识别单点和级联脆弱性",
            "比较替代链路",
            "映射S3-S6",
        ],
        "quality_gates": ["脆弱性说明前置条件和级联边界", "建议保持任务级和防御性"],
        "output_focus": [
            "体系边界",
            "任务依赖图",
            "脆弱点",
            "替代方案",
            "补链强链需求",
        ],
    },
    "G": {
        "name": "跨域融合发现",
        "methodology": [
            "建立陆海空天电网智认知深海矩阵",
            "识别域间接口",
            "定位协同缝隙",
            "构建跨域效果链",
            "映射S3/S4/S6",
        ],
        "quality_gates": [
            "接口含数据、指挥、时序和保障条件",
            "融合收益与耦合风险同时评估",
        ],
        "output_focus": ["跨域边界", "域间接口", "协同缝隙", "跨域效果链", "融合能力"],
    },
    "H": {
        "name": "非传统安全牵引",
        "methodology": [
            "扫描新型威胁",
            "构造非传统场景",
            "分析跨部门边界",
            "强化S1/S3/S4/S6并弱化不适用步骤",
        ],
        "quality_gates": ["法律伦理与民用影响显式列出", "优先韧性、非致命和跨部门能力"],
        "output_focus": [
            "新型威胁画像",
            "触发条件",
            "跨部门边界",
            "非致命与韧性能力",
            "法律伦理限制",
        ],
    },
}


def _profile(
    scenario: str,
    *,
    skills: Sequence[str],
    tools: Sequence[str],
    methodology: Sequence[str],
    quality_gates: Sequence[str],
    output_focus: Sequence[str],
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "skills": list(skills),
        "tools": list(tools),
        "methodology": list(methodology),
        "quality_gates": list(quality_gates),
        "output_focus": list(output_focus),
        "safety_boundary": SAFETY_BOUNDARY,
    }


CODEX_AGENT_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "orchestrator": _profile(
        "资深JS专家人格下的需求语义解析、A-H/OTHER驱动识别、S1-S6蓝图、Agent DAG和四级循环控制",
        skills=[
            "requirement_semantics_analysis",
            "discovery_driver_recognition",
            "discovery_blueprint_generation",
            "dag_loop_orchestration",
        ],
        tools=[
            "analyze_research_request",
            "classify_discovery_drivers",
            "build_discovery_blueprint",
            "plan_execution_waves",
            "evaluate_loop_transition",
        ],
        methodology=[
            "形成任务语义卡和问题树",
            "逐项评估A-H并记录OTHER未覆盖驱动源",
            "组合S1-S6强度与回溯点",
            "按能力覆盖选择最小充分Agent集合",
            "构建DAG波次并设置内中外L4循环预算",
        ],
        quality_gates=[
            "专家显式边界不被覆盖",
            "主次驱动源有任务依据",
            "能力标签无关键遗漏",
            "并发与结构化交接关系明确",
            "无信息增益循环停止",
        ],
        output_focus=[
            "任务语义卡",
            "驱动源评分",
            "发现蓝图",
            "能力覆盖矩阵",
            "Agent DAG与执行波次",
            "循环预算回溯点与停止条件",
        ],
    ),
    "international_situation": _profile(
        "国际安全态势、威胁预警、联盟与力量建设研判",
        skills=["strategic_osint", "threat_forecasting", "force_posture_tracking"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "register_event_timeline",
            "compare_actor_positions",
            "register_warning_indicator",
            "test_competing_hypothesis",
        ],
        methodology=[
            "建立事件时间线",
            "执行行为体-意图-能力三角验证",
            "识别预警指标",
            "比较竞争假设",
        ],
        quality_gates=[
            "主要判断双源支撑",
            "时间尺度明确",
            "高影响低置信判断进入开放问题",
        ],
        output_focus=["态势判断", "威胁评估", "战略格局", "对手动向", "场景驱动因素"],
    ),
    "combat_scenario": _profile(
        "现代多域作战场景、敌方行动方案和环境压力建模",
        skills=[
            "scenario_engineering",
            "modern_battlespace_analysis",
            "adversary_coa_analysis",
        ],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "build_scenario_graph",
            "branch_scenario",
            "map_critical_window",
            "map_environment_constraint",
            "stress_test_scenario",
        ],
        methodology=[
            "构建背景-力量-目标-阶段-触发器",
            "生成最可能/最危险/替代COA",
            "执行环境压力测试",
            "映射能力压力点",
        ],
        quality_gates=[
            "至少两个场景分支",
            "关键节点有证据或显式假设",
            "环境约束映射到装备功能",
        ],
        output_focus=["场景框架", "敌方COA", "关键时间窗", "环境约束", "能力压力点"],
    ),
    "weapon_equipment": _profile(
        "国外与中国国内装备现状、案例、技术路线对比及研发需求形成",
        skills=[
            "equipment_osint",
            "capability_comparison",
            "technology_readiness_analysis",
            "defensive_countermeasure_analysis",
        ],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "extract_parameter_observation",
            "normalize_equipment_variant",
            "reconcile_parameter_conflict",
            "assess_technology_readiness",
            "compare_equipment_capability",
            "map_defensive_countermeasure",
            "formulate_equipment_requirement",
        ],
        methodology=[
            "分别建立国外与中国国内装备谱系",
            "按问题难点解决与核心技术路线两条主线整理案例",
            "核验型号批次与参数条件",
            "分析体系接口和能力边界",
            "映射主题场景压力",
            "按需调用颠覆种子并形成做优/拓新双轨装备族",
            "比较防御性反制、现役升级和新研路径",
            "定义验证计划",
        ],
        quality_gates=[
            "关键型号双源核验",
            "冲突参数不覆盖",
            "国内外案例、技术路线和指标均可追溯到公开证据",
            "种子只作假设且经过对手反制、降级和成熟度校核",
            "不凭空给出精确指标",
        ],
        output_focus=[
            "国外装备全景",
            "中国国内装备现状",
            "国内外具体案例",
            "问题解决与核心技术对比",
            "重点型号档案",
            "体系依赖",
            "能力边界",
            "防御性反制",
            "升级与新研需求",
            "验证计划",
        ],
    ),
    "operational_employment": _profile(
        "任务链、力量协同、COA比较、保障韧性与经验迁移",
        skills=[
            "operational_synthesis",
            "coa_comparison",
            "joint_force_coordination",
            "lessons_transfer",
        ],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "map_task_capability",
            "build_coordination_dependency",
            "compare_coa",
            "assess_sustainment_resilience",
            "transfer_case_lesson",
        ],
        methodology=[
            "消费上游结构化交接",
            "建立任务链和能力-任务矩阵",
            "比较基线/弹性分布/资源受限COA",
            "检查保障与失败模式",
        ],
        quality_gates=["三类COA完整", "协同与保障约束可追溯", "经验迁移说明适用边界"],
        output_focus=["任务链", "协同依赖", "COA比较", "保障韧性", "装备功能需求"],
    ),
    "scenario_divergence": _profile(
        "智能模式下的开放式需求与场景发散",
        skills=["问题重构", "竞争假设", "场景发散", "分支推荐"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "build_scenario_graph",
            "branch_scenario",
            "test_competing_hypothesis",
        ],
        methodology=[
            "扫描弱信号",
            "重构候选问题",
            "形成竞争假设",
            "生成候选场景",
            "推荐A-H分支",
        ],
        quality_gates=["候选方向彼此有区分度", "边界假设显式", "不得把想象当事实"],
        output_focus=["候选主题", "候选场景", "竞争假设", "推荐分支", "边界假设"],
    ),
    "case_research": _profile(
        "多语言战例检索、事实还原、因果链和跨案例迁移",
        skills=["多语言深度搜索", "时序事件重建", "因果链分析", "类比与反事实推理"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "register_event_timeline",
            "transfer_case_lesson",
            "test_competing_hypothesis",
        ],
        methodology=[
            "界定案例",
            "重建事实时间线",
            "标记关键决策点",
            "构建因果链",
            "跨案例比较",
            "映射未来场景",
        ],
        quality_gates=["事实与事后推断分离", "关键因果至少有证据链", "迁移边界完整"],
        output_focus=[
            "事实时间线",
            "参与方与装备",
            "关键决策",
            "因果链",
            "跨案例模式",
            "未来映射",
        ],
    ),
    "technology_radar": _profile(
        "前沿技术信号、成熟度、能力潜力和颠覆场景",
        skills=[
            "技术雷达",
            "technology_readiness_analysis",
            "技术潜力评估",
            "场景反推",
        ],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "assess_technology_readiness",
            "compare_equipment_capability",
            "test_competing_hypothesis",
        ],
        methodology=[
            "扫描论文专利项目与试验",
            "评估TRL和工程节点",
            "识别工业与成本约束",
            "反向构造颠覆场景",
            "设计阶段验证",
        ],
        quality_gates=["技术信号多源核验", "成熟度和能力潜力分开", "限制条件完整"],
        output_focus=[
            "技术信号",
            "成熟度",
            "能力潜力",
            "限制条件",
            "颠覆场景",
            "验证路线",
        ],
    ),
    "opponent_monitoring": _profile(
        "国外装备、演习、条令、采购和能力形成节奏监测",
        skills=["持续OSINT监测", "变化检测", "能力形成节奏评估", "竞争假设"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "register_event_timeline",
            "register_warning_indicator",
            "test_competing_hypothesis",
        ],
        methodology=[
            "建立历史基线",
            "登记新事件",
            "识别异常变化",
            "比较装备-演习-条令一致性",
            "形成预警指标",
        ],
        quality_gates=[
            "变化相对基线可验证",
            "能力形成时间包含不确定性",
            "意图判断有替代假设",
        ],
        output_focus=["变化基线", "异常动向", "能力形成节奏", "体系影响", "预警指标"],
    ),
    "system_confrontation": _profile(
        "红蓝体系模型、任务依赖、级联脆弱性与替代链路",
        skills=["体系建模", "依赖图分析", "脆弱性分析", "简化推演"],
        tools=[
            "build_scenario_graph",
            "map_task_capability",
            "build_coordination_dependency",
            "stress_test_scenario",
            "test_competing_hypothesis",
        ],
        methodology=[
            "定义体系边界",
            "绘制感知-决策-行动-保障链",
            "识别单点与级联失效",
            "压力测试替代链路",
            "形成补链强链需求",
        ],
        quality_gates=[
            "脆弱点有依赖路径依据",
            "区分模型假设与事实",
            "建议保持防御性和任务级",
        ],
        output_focus=["体系边界", "任务依赖", "关键脆弱点", "替代链路", "补链强链需求"],
    ),
    "cross_domain_fusion": _profile(
        "多域能力矩阵、接口依赖、协同缝隙与融合效果链",
        skills=["跨域矩阵", "接口分析", "协同缝隙识别", "融合效果链"],
        tools=[
            "build_scenario_graph",
            "map_task_capability",
            "build_coordination_dependency",
            "stress_test_scenario",
        ],
        methodology=[
            "建立域-任务-能力矩阵",
            "分析数据/指挥/时序/保障接口",
            "定位协同缝隙",
            "比较融合收益和耦合风险",
        ],
        quality_gates=["覆盖相关作战域", "接口条件可验证", "融合建议包含降级运行方式"],
        output_focus=["跨域矩阵", "域间接口", "协同缝隙", "融合效果链", "融合能力需求"],
    ),
    "nontraditional_security": _profile(
        "非传统安全威胁、新型场景、跨部门协同和韧性需求",
        skills=["新威胁扫描", "非传统场景工程", "跨部门边界分析", "法律伦理审查"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "build_scenario_graph",
            "map_environment_constraint",
            "test_competing_hypothesis",
        ],
        methodology=[
            "扫描威胁与触发条件",
            "构造新场景",
            "识别跨部门责任和资源",
            "优先形成非致命与韧性能力",
            "审查法律伦理边界",
        ],
        quality_gates=["民用影响和法律边界明确", "跨部门接口完整", "场景不过度军事化"],
        output_focus=["威胁画像", "触发条件", "跨部门边界", "韧性能力", "法律伦理限制"],
    ),
    "convergence_fusion": _profile(
        "跨Agent、跨背景、跨场景和跨分支的发现收敛",
        skills=["语义聚类", "冲突保留", "优先级排序", "跨分支关联"],
        tools=["prepare_winning_input", "project_winning_resources"],
        methodology=[
            "按共同任务需求聚类",
            "去重但保留冲突",
            "建立跨分支因果关联",
            "形成优先级与回传问题",
        ],
        quality_gates=[
            "不得用多数意见覆盖冲突",
            "每个优先项可追溯到输入Packet",
            "开放问题被保留",
        ],
        output_focus=["需求簇", "冲突", "优先序", "跨分支关联", "开放问题"],
    ),
    "winning_mechanism": _profile(
        "Tree-of-Warfare制胜机理总分析与L1-L3门控",
        skills=[
            "defense_decomposition",
            "winning_path_analysis",
            "effect_chain_analysis",
            "capability_mapping",
            "gap_quantification",
            "capability_image_generation",
        ],
        tools=[
            "prepare_winning_input",
            "project_winning_resources",
            "write_reasoning_node",
            "write_stage_output",
            "create_recall_request",
            "create_capability_image",
        ],
        methodology=[
            "S1防御解构",
            "S2运用审查",
            "S3突破口与效果链",
            "S4能力映射",
            "S5差距量化",
            "S6能力图像综合",
        ],
        quality_gates=[
            "每节点包含认识、证据、置信度和下一步建议",
            "L1-L3门控通过",
            "失败从最早不完整节点回溯",
        ],
        output_focus=[
            "防御解构",
            "制胜路径",
            "效果链",
            "能力映射",
            "五档差距",
            "能力画像",
        ],
    ),
    "winning_s1_opponent": _profile(
        "S1 对手装备、OODA环和体系脆弱性分析",
        skills=["对手装备检索", "OODA环分析", "体系脆弱性", "竞争假设"],
        tools=["write_reasoning_node", "create_recall_request"],
        methodology=[
            "从Query提出至少三个竞争性对手体系与反适应假设",
            "解构感知-判断-决策-行动-保障-恢复",
            "识别关键依赖和替代路径",
            "比较最可能与替代假设",
        ],
        quality_gates=[
            "上游仅作证据与约束，不替代Query主导的军事发散",
            "薄弱环节有依赖依据",
            "事实推断假设分离",
            "不输出可执行攻击指令",
        ],
        output_focus=[
            "对手装备与体系",
            "OODA破绽",
            "体系脆弱性",
            "替代假设",
            "召回问题",
        ],
    ),
    "winning_s2_operations": _profile(
        "S2 条令、演习、战法本体和作战运用审查",
        skills=["条令分析", "演习复盘", "战法本体", "任务链审查"],
        tools=["write_reasoning_node", "create_recall_request"],
        methodology=[
            "从Query发散至少三条机制不同的作战运用路径",
            "建立条令和战法基线",
            "还原任务链与协同",
            "比较演习和实战偏差",
            "识别失败模式和制胜路径",
        ],
        quality_gates=[
            "路径差异落在决策权、力量组织或效应机理而非同义改名",
            "战法要素与场景条件对应",
            "路径包含保障和失败边界",
            "证据不足触发召回",
        ],
        output_focus=["作战运用基线", "战法本体", "协同关系", "失败模式", "制胜路径"],
    ),
    "winning_s3_breakthrough": _profile(
        "S3 反事实、TRIZ和效果链驱动的突破口生成",
        skills=["反事实推理", "TRIZ矛盾分析", "效果链分析", "简化推演"],
        tools=["write_reasoning_node", "create_recall_request"],
        methodology=[
            "从Query核心矛盾生成竞争性突破机制",
            "提取核心矛盾",
            "从选中种子跨至少两个逻辑维度扫描并允许OTHER",
            "改变关键前提做反事实",
            "生成多条防御性突破方向",
            "构建直接/间接效果链",
            "检验替代解释",
        ],
        quality_gates=[
            "至少覆盖两类直接军事作战效果",
            "种子不作为事实且不得强行覆盖全部方向",
            "突破口不等同于口号",
            "效果链节点可追溯",
            "至少保留一个替代方向",
        ],
        output_focus=["核心矛盾", "反事实", "突破方向", "效果链", "验证建议"],
    ),
    "winning_s4_capability": _profile(
        "S4 能力-任务矩阵与DOTMLPF装备需求映射",
        skills=["能力任务矩阵", "DOTMLPF分析", "效果-功能-性能映射", "体系接口分析"],
        tools=["write_reasoning_node", "write_stage_output", "create_recall_request"],
        methodology=[
            "从Query要求的直接作战效果反推能力组合",
            "把效果链映射到任务",
            "把任务映射到能力和功能",
            "把高价值颠覆方向拆成做优接口与拓新装备族",
            "区分装备与非装备DOTMLPF措施",
            "定义性能约束和体系接口",
        ],
        quality_gates=[
            "至少两项能力直接改变火力、突防、拦截、毁伤、拒止或威慑效果",
            "颠覆方向说明改变的传统体系关系",
            "能力需求不直接跳成型号",
            "装备措施与非装备措施分离",
            "接口和适用边界完整",
        ],
        output_focus=["能力-任务矩阵", "DOTMLPF", "装备功能", "性能约束", "体系接口"],
    ),
    "winning_s5_gap": _profile(
        "S5 现役/在研装备、参数、成熟度和体系效能差距评估",
        skills=["装备基线", "参数比较", "成熟度分析", "体系效能评估", "五档差距"],
        tools=["write_reasoning_node", "write_stage_output", "create_recall_request"],
        methodology=[
            "按Query作战后果比较升级、新研和非装备缓解路径",
            "建立现役和在研基线",
            "比较参数与条件",
            "评估成熟度和保障约束",
            "检查成本、反制、降级运行和试验淘汰条件",
            "按空白/关键/部分/满足/超出分级",
        ],
        quality_gates=[
            "差距排序以可恢复的军事效果为依据而非技术标签",
            "每个差距有比较基准",
            "冲突参数被保留",
            "型号能力不脱离体系接口",
        ],
        output_focus=["装备基线", "参数证据", "成熟度", "体系效能", "五档差距"],
    ),
    "winning_s6_image": _profile(
        "S6 融合、排序、需求卡片与能力图像生成",
        skills=["融合去重", "多准则排序", "需求卡片", "能力图像生成"],
        tools=[
            "write_reasoning_node",
            "write_stage_output",
            "create_capability_image",
            "create_recall_request",
        ],
        methodology=[
            "归并前五步结果",
            "保留冲突和依赖",
            "按价值/紧迫/可行/证据排序",
            "检查组合是否超越单纯渐进补齐且仍与Query因果契合",
            "生成升级和新能力需求卡片",
        ],
        quality_gates=[
            "每项追溯到证据与前序节点",
            "升级和新研理由明确",
            "至少一项高潜力方向明确改变成本、平台、时间、效应、体系或自主可控关系",
            "需求卡片以与query匹配的具体无人、导弹、弹药或其他战斗装备为主对象",
            "通信、算法、接口和保障只作为具体战斗装备内部配套",
            "具体武器装备、指标、场景和装备构型形成全景关联",
        ],
        output_focus=["优先级", "升级需求", "新能力需求", "验证路线", "需求卡片", "能力全景图", "深度能力画像"],
    ),
    "winning_step_critic": _profile(
        "S1-S6单步骤证据、因果、覆盖与安全批判",
        skills=["证据审查", "因果审查", "完整性审查", "安全边界审查"],
        tools=["create_recall_request"],
        methodology=[
            "核对输入覆盖",
            "检查证据越界",
            "识别跨步跳跃",
            "检查分支侧重",
            "给出最小重试指引",
        ],
        quality_gates=[
            "问题具体可修复",
            "不代替被审查Agent重写结论",
            "必要时指定补搜/召回",
        ],
        output_focus=["是否通过", "问题", "重试指引", "召回建议"],
    ),
    "winning_round_critic": _profile(
        "S1-S6中循环因果连续性、覆盖和回溯点批判",
        skills=["跨步骤一致性", "因果链审查", "分支覆盖审查", "回溯决策"],
        tools=["create_recall_request"],
        methodology=[
            "检查S1至S6输入输出连接",
            "核对A-H分支侧重",
            "识别最早失败节点",
            "给出后续重跑范围",
        ],
        quality_gates=[
            "回溯到最早不完整步骤",
            "不隐藏剩余不确定性",
            "达到循环上限时明确限制",
        ],
        output_focus=["是否通过", "最早回溯步骤", "跨步问题", "重跑指引"],
    ),
    "winning_dynamic_specialist": _profile(
        "由主控按能力缺口即时生成的有界制胜辅助专用Agent",
        skills=["共享DeepSearch", "共享DeepResearch", "证据治理", "结构化交接"],
        tools=[
            "search_sources",
            "fetch_page",
            "create_evidence_card",
            "create_recall_request",
        ],
        methodology=[
            "读取动态角色契约",
            "只处理可分离的专业缺口",
            "消费指定知识包与证据索引",
            "输出可并入指定S节点的结构化结果",
        ],
        quality_gates=[
            "不得扩展动态契约权限",
            "证据引用必须来自输入索引",
            "结果包含合并节点与停止理由",
        ],
        output_focus=[
            "专业发现",
            "证据引用",
            "对S1-S6的贡献",
            "假设与开放问题",
            "合并目标",
        ],
    ),
    "auditor": _profile(
        "独立证据、覆盖、门控、追溯和发布风险审计",
        skills=["证据审计", "一致性审计", "门控复核", "发布风险评估"],
        tools=["write_audit"],
        methodology=[
            "核对证据链",
            "检查覆盖与冲突",
            "复核用户确认和循环门控",
            "评估报告发布边界",
        ],
        quality_gates=[
            "不得修改事实或放宽门控",
            "风险与具体对象关联",
            "限制发布条件明确",
        ],
        output_focus=["风险摘要", "审计发现", "发布建议", "限制条件"],
    ),
    "reporter": _profile(
        "以Query为主、精简高价值前置研判为辅，深研军事武器装备并按需求挖掘、技术攻关、能力图像与效能贡献三层九项交付",
        skills=["Query主题发散", "证据化写作", "场景战法推演", "核心技术分解", "能力图像表达", "效能贡献评估", "限制披露"],
        tools=["write_report"],
        methodology=[
            "以审计通过内容为边界",
            "从原始Query发散对手地域烈度时间窗约束和行动反行动关系",
            "将前置Agent产物压缩为少量事实锚点、反证和能力线索，不沿其字段顺序写作",
            "优先深研无人化、低空无人机、远程精确打击及强打击歼灭压制毁伤武器装备",
            "按场景与战法、能力特征、实现途径、核心技术、能力图像、效能贡献和验证抓手建立闭环",
            "把深度性、创新性、前瞻性和军事价值性写入三层九项连续因果论证",
            "正文不描述Agent执行过程，回溯关系仅进入附录索引",
            "保留关键反证、适用边界和不确定性",
        ],
        quality_gates=["不新增数字和来源", "结论可回溯到公开证据与前置研判", "固定三层九项且分支产物只作素材", "每项能力特征映射实现途径核心技术耦合风险和效能贡献", "每项关键结论体现深度创新前瞻军事价值", "预测和事实明确分层", "不是字段罗列能力卡片改写或过程描述", "能力与限制同等清晰"],
        output_focus=["典型作战场景", "新战法与制胜机理", "装备能力特征", "核心技术与成熟度", "技术耦合短板", "能力图像", "补链强链开链效能", "发展优先级", "演示验证抓手"],
    ),
}


def build_codex_runtime_profile(
    agent_id: str,
    *,
    payload: Mapping[str, Any] | None = None,
    agent: Any | None = None,
    harness_profile: Any | None = None,
    phase: str = "analysis",
    compact: bool = False,
) -> dict[str, Any]:
    """Merge the static scene profile with registry and A-H task context."""
    static = CODEX_AGENT_RUNTIME_PROFILES.get(agent_id, {})
    profile: dict[str, Any] = {
        "agent_id": agent_id,
        "phase": phase,
        "scenario": str(
            static.get("scenario") or getattr(agent, "description", "通用结构化研究")
        ),
        "skills": list(static.get("skills", ["深度搜索", "证据治理", "结构化研究"])),
        "tools": list(
            static.get(
                "tools", ["search_sources", "fetch_page", "create_evidence_card"]
            )
        ),
        "methodology": list(
            static.get(
                "methodology", ["界定问题", "收集证据", "分析反证", "结构化输出"]
            )
        ),
        "quality_gates": list(
            static.get("quality_gates", ["事实、推断和假设分离", "结论可追溯"])
        ),
        "output_focus": list(static.get("output_focus", [])),
        "military_mission_lens": military_mission_lens(agent_id),
        "safety_boundary": str(static.get("safety_boundary", SAFETY_BOUNDARY)),
        "tool_execution_rule": "这些是本场景允许或相关的受治理工具；由本地Harness执行和校验。Codex只按其语义规划、分析和输出，不得自行修改工作区或系统状态。",
    }
    expansion_lenses = baseline_agent_expansion_lenses(agent_id)
    if expansion_lenses:
        profile["reference_expansion_lenses"] = expansion_lenses
    if agent is not None:
        registered_skills = getattr(agent, "skills", [])
        shared_skills = getattr(agent, "shared_skills", [])
        registered_tools = getattr(agent, "tools", [])
        research_policy = getattr(agent, "research_policy", {})
        output_contract = getattr(agent, "output_contract", {})
        if registered_skills or shared_skills:
            profile["skills"] = [
                _compact_skill(item)
                for item in [*list(registered_skills), *list(shared_skills)]
            ]
        knowledge_packs = getattr(agent, "knowledge_packs", [])
        if knowledge_packs:
            profile["knowledge_packs"] = [
                _compact_knowledge_pack(item) for item in knowledge_packs
            ]
        if registered_tools:
            profile["tools"] = list(registered_tools)
        if isinstance(research_policy, Mapping):
            profile["research_policy"] = dict(research_policy)
            profile["quality_gates"] = _unique(
                [
                    *profile["quality_gates"],
                    *research_policy.get("stopping_conditions", []),
                ]
            )
            profile["output_focus"] = _unique(
                [*profile["output_focus"], *research_policy.get("required_outputs", [])]
            )
        if isinstance(output_contract, Mapping):
            profile["output_contract"] = dict(output_contract)
    if harness_profile is not None:
        phase_tools = getattr(harness_profile, "phase_tools", {})
        phase_key = (
            "winning"
            if phase.startswith("winning")
            else "baseline"
            if phase in {"web_discovery", "evidence_analysis"}
            else phase
        )
        current_phase_tools = list(phase_tools.get(phase_key, []))
        skill_tools = {
            str(tool)
            for skill in profile.get("skills", [])
            if isinstance(skill, Mapping)
            for tool in skill.get("allowed_tools", [])
        }
        harness_tools = {str(tool) for tool in current_phase_tools}
        active_tools = [
            tool
            for tool in profile["tools"]
            if (not skill_tools or tool in skill_tools)
            and (not harness_tools or tool in harness_tools)
        ]
        profile["tools"] = active_tools or list(profile["tools"])
        profile["harness"] = {
            "profile_id": str(getattr(harness_profile, "profile_id", "")),
            "budget": dict(getattr(harness_profile, "budget", {})),
            "evidence_policy": dict(getattr(harness_profile, "evidence_policy", {})),
            "checkpoint_policy": dict(
                getattr(harness_profile, "checkpoint_policy", {})
            ),
            "stop_conditions": list(getattr(harness_profile, "stop_conditions", [])),
            "recovery_policy": dict(getattr(harness_profile, "recovery_policy", {})),
            "active_phase_tools": current_phase_tools,
        }
        profile["quality_gates"] = _unique(
            [
                *profile["quality_gates"],
                *profile["harness"]["stop_conditions"],
            ]
        )
    branch_codes, blueprint = _find_branch_context(payload or {})
    if branch_codes:
        profile["discovery_branches"] = [
            {
                "code": code,
                **CODEX_BRANCH_RUNTIME_PROFILES[code],
                "reference_focus": branch_reference_focus(code),
            }
            for code in branch_codes
            if code in CODEX_BRANCH_RUNTIME_PROFILES
        ]
        # Winning-step payloads already carry their selected seed cards in
        # ``task_input``.  Recomputing the same cards in ``agent_runtime``
        # duplicated context and over-emphasized the framework.  Baseline
        # agents that do not receive an explicit seed block still get one
        # compact, deterministically selected context here.
        explicit_seed_context = (payload or {}).get("disruptive_seed_context")
        if not isinstance(explicit_seed_context, Mapping) or not explicit_seed_context:
            seed_context = disruptive_seed_context(
                _find_query_text(payload or {}),
                branch=branch_codes[0],
                agent_id=agent_id,
            )
            if seed_context:
                profile["disruptive_seed_context"] = seed_context
    if blueprint:
        profile["blueprint_context"] = {
            key: blueprint.get(key)
            for key in (
                "runtime_route",
                "emphasis",
                "required_outputs",
                "loop_policy",
                "reference_focus",
            )
            if blueprint.get(key) not in (None, "", [], {})
        }
    swarm_contract = _find_swarm_specialist_contract(agent_id, payload or {})
    if swarm_contract:
        role = dict(swarm_contract["role_contract"])
        assignment = dict(swarm_contract["assignment"])
        profile["runtime_profile_id"] = str(role["runtime_profile_id"])
        profile["role_contract_version"] = str(role["version"])
        profile["swarm_role_contract"] = role
        profile["swarm_assignment"] = assignment
        profile["scenario"] = str(role["purpose"])
        profile["skills"] = [
            f"{role['display_name']}专用分析",
            "制胜机理共享层",
        ]
        profile["active_dynamic_skill_ids"] = list(SWARM_RUNTIME_SKILL_IDS)
        profile["methodology"] = [
            f"围绕当前声明的候选执行{role['display_name']}任务",
            str(role["purpose"]),
            "只向声明的 hypothesis_id 与 merge_target 提交结构化增量",
            "显式记录证据边界、反证、失败条件和仍未解决的质量残差",
        ]
        profile["quality_gates"] = _unique(
            [
                "不得读取或复述其他 Agent 原始会话",
                "不得招募子 Agent、扩大权限或修改生产角色与 Skill",
                "不得虚构精确指标、效能比例、TRL、成本或产能判断",
                "结果必须保持 hypothesis_id 与 merge_target 的合并边界",
                *role.get("quality_gates", []),
            ]
        )
        profile["output_focus"] = _unique(
            [
                str(role["display_name"]),
                f"对 {role['merge_target']} 的增量贡献",
                "证据与反证边界",
                "失效条件与验证建议",
            ]
        )
        profile["military_mission_lens"] = MILITARY_MISSION_LENSES[
            "winning_dynamic_specialist"
        ]
    dynamic_spec = _find_dynamic_agent_spec(payload or {})
    if dynamic_spec:
        profile["dynamic_agent_contract"] = dynamic_spec
        profile["scenario"] = str(
            dynamic_spec.get("purpose")
            or dynamic_spec.get("display_name")
            or profile["scenario"]
        )
        selected_skill_ids = [
            str(item) for item in dynamic_spec.get("skill_ids", []) if str(item)
        ]
        if selected_skill_ids:
            profile["active_dynamic_skill_ids"] = selected_skill_ids
        selected_pack_ids = [
            str(item)
            for item in dynamic_spec.get("knowledge_pack_ids", [])
            if str(item)
        ]
        if selected_pack_ids:
            profile["active_dynamic_knowledge_pack_ids"] = selected_pack_ids
        profile["methodology"] = _unique(
            [*profile["methodology"], *dynamic_spec.get("methodology", [])]
        )
        profile["quality_gates"] = _unique(
            [*profile["quality_gates"], *dynamic_spec.get("quality_gates", [])]
        )
        profile["output_focus"] = _unique(
            [*profile["output_focus"], *dynamic_spec.get("output_fields", [])]
        )
    if compact:
        full_profile = dict(profile)
        profile["role_card_id"] = role_card_id(agent_id, phase, full_profile)
        profile["role_card_version"] = "2.0"
        profile.pop("research_policy", None)
        profile.pop("output_contract", None)
        harness = profile.get("harness")
        if isinstance(harness, Mapping):
            profile["harness"] = {
                key: harness.get(key)
                for key in (
                    "profile_id",
                    "budget",
                    "evidence_policy",
                    "stop_conditions",
                    "active_phase_tools",
                )
                if harness.get(key) not in (None, "", [], {})
            }
        if phase == "web_discovery":
            profile["skills"] = [
                {
                    key: item.get(key)
                    for key in ("name", "allowed_tools", "quality_gates")
                    if item.get(key) not in (None, "", [], {})
                }
                if isinstance(item, Mapping)
                else item
                for item in profile.get("skills", [])
            ]
        if is_optimized_v2_payload(payload or {}):
            profile = _minimal_business_runtime_profile(
                profile,
                agent_id=agent_id,
                phase=phase,
                blueprint=blueprint,
            )
    return profile


def is_optimized_v2_payload(value: Mapping[str, Any]) -> bool:
    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint",
        "visible_context",
        "context",
        "input",
        "task_input",
        "winning_mechanism_input",
        "assignment",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("discovery_blueprint")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    return any(
        is_quality_execution_profile_id(candidate.get("execution_profile_id", ""))
        for candidate in candidates
    )


def _minimal_business_runtime_profile(
    profile: Mapping[str, Any],
    *,
    agent_id: str,
    phase: str,
    blueprint: Mapping[str, Any],
) -> dict[str, Any]:
    skills = list(profile.get("skills", []))
    chosen_skill = _choose_single_skill(skills, phase=phase)
    tools = _minimal_phase_tools(
        agent_id=agent_id,
        phase=phase,
        tools=[str(item) for item in profile.get("tools", [])],
    )
    branch = str(
        blueprint.get("primary_branch", "")
        or blueprint.get("discovery_branch", "")
    )
    result = {
        "agent_id": agent_id,
        "phase": phase,
        "role": str(profile.get("scenario", "结构化业务研究"))[:180],
        "skill": chosen_skill,
        "tools": tools,
        "method": [
            str(item)[:120]
            for item in list(profile.get("methodology", []))[:2]
        ],
        "output_focus": [
            str(item)[:80]
            for item in list(profile.get("output_focus", []))[:5]
        ],
        "reference_expansion_lenses": [
            str(item)[:100]
            for item in list(profile.get("reference_expansion_lenses", []))[:3]
        ],
        "disruptive_seed_context": profile.get("disruptive_seed_context", {}),
        "quality_gates": [
            *[
                str(item)[:120]
                for item in list(profile.get("quality_gates", []))[:2]
            ],
            "军事任务效果、作用机理和失效边界不可缺失",
        ],
        "military_mission_lens": military_mission_lens(agent_id),
        "branch_focus": {
            "branch": branch,
            "emphasis": list(blueprint.get("emphasis", []))[:4],
            "required_outputs": list(blueprint.get("required_outputs", []))[:6],
            "reference_focus": blueprint.get("reference_focus", {}),
        }
        if branch
        else {},
        "handoff_contract": "只输出当前schema要求的业务结论、证据引用、置信度、限制和下一步建议；不复述流程。",
        "safety_boundary": "只做公开来源下的任务级能力研究，不输出目标坐标、攻击步骤或可直接执行参数。",
        "role_card_id": str(profile.get("role_card_id", "")),
    }
    if profile.get("runtime_profile_id"):
        result.update(
            {
                "runtime_profile_id": str(profile["runtime_profile_id"]),
                "role_contract_version": str(
                    profile.get("role_contract_version", "1.0")
                ),
                "swarm_role_contract": dict(
                    profile.get("swarm_role_contract", {})
                ),
                "swarm_assignment": dict(profile.get("swarm_assignment", {})),
                "active_dynamic_skill_ids": list(
                    profile.get("active_dynamic_skill_ids", [])
                ),
            }
        )
        result["military_mission_lens"] = str(
            profile.get("military_mission_lens")
            or result["military_mission_lens"]
        )
    if agent_id in QUERY_DOMINANT_BUSINESS_AGENT_IDS:
        result["analysis_anchor"] = "query_dominant_military_divergence"
        result["query_dominance_rule"] = (
            "分析优先级固定为：本Agent专业角色与方法第一，Query核心军事矛盾第二，"
            "打击、歼灭、压制、反制、拒止、威慑等直接军事价值第三；三者共同主导独立发散。"
            "跨Agent精简交接只能用于事实证据、约束和反证校验，不得决定议题、分析结构、"
            "方案命名、优先级或最终结论。"
        )
    if not result.get("reference_expansion_lenses"):
        result.pop("reference_expansion_lenses", None)
    if not result.get("disruptive_seed_context"):
        result.pop("disruptive_seed_context", None)
    return result


def _choose_single_skill(skills: Sequence[Any], *, phase: str) -> str:
    if not skills:
        return "结构化业务判断"
    if phase.startswith("web_discovery"):
        for item in skills:
            if isinstance(item, Mapping) and "search_sources" in item.get(
                "allowed_tools", []
            ):
                return str(item.get("name", "公开来源检索"))
    first = skills[0]
    if isinstance(first, Mapping):
        return str(first.get("name", "结构化业务判断"))
    return str(first)


def _minimal_phase_tools(
    *,
    agent_id: str,
    phase: str,
    tools: Sequence[str],
) -> list[str]:
    if agent_id == "reporter" or phase.startswith("report_generation"):
        return ["write_report"]
    if agent_id == "auditor" or "audit" in phase:
        return ["write_audit"]
    if phase.startswith("web_discovery"):
        return [item for item in ("search_sources",) if item in tools]
    if phase == "evidence_analysis":
        preferred = (
            "create_evidence_card",
            "test_competing_hypothesis",
            "stress_test_scenario",
            "compare_coa",
            "compare_equipment_capability",
        )
        selected = [item for item in preferred if item in tools]
        return selected[:2]
    if phase.startswith("winning"):
        preferred = (
            "write_reasoning_node",
            "write_stage_output",
            "create_capability_image",
            "create_recall_request",
        )
        return [item for item in preferred if item in tools][:2]
    return list(tools)[:2]


def _compact_skill(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {
        key: value.get(key)
        for key in (
            "name",
            "steps",
            "allowed_tools",
            "quality_gates",
            "stop_conditions",
            "required_artifacts",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _compact_knowledge_pack(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {
        key: value.get(key)
        for key in (
            "knowledge_pack_id",
            "description",
            "retrieval_policy",
            "quality_gates",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _find_branch_context(
    value: Mapping[str, Any],
) -> tuple[list[str], Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint",
        "visible_context",
        "context",
        "input",
        "winning_mechanism_input",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("discovery_blueprint")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    for candidate in candidates:
        blueprint = candidate.get("discovery_blueprint")
        if isinstance(blueprint, Mapping):
            candidate = blueprint
        primary = str(
            candidate.get("primary_branch") or candidate.get("discovery_branch") or ""
        )
        secondary = candidate.get("secondary_branches", [])
        codes = (
            [primary, *secondary]
            if isinstance(secondary, Sequence)
            and not isinstance(secondary, (str, bytes))
            else [primary]
        )
        resolved = _unique(
            code for code in codes if str(code) in CODEX_BRANCH_RUNTIME_PROFILES
        )
        if resolved:
            return [str(code) for code in resolved], candidate
    return [], {}


def _find_query_text(value: Mapping[str, Any]) -> str:
    """Read a bounded query from known task containers without flattening payloads."""

    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "task",
        "task_input",
        "input",
        "context",
        "visible_context",
        "winning_mechanism_input",
        "structured_query_brief",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("structured_query_brief")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    rows: list[str] = []
    for candidate in candidates:
        for key in ("query", "topic", "core_query"):
            text = str(candidate.get(key, "")).strip()
            if text and text not in rows:
                rows.append(text)
    return "\n".join(rows)[:1600]


def _find_dynamic_agent_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = [value]
    for key in ("input", "task_input", "winning_mechanism_input"):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
    for candidate in candidates:
        spec = candidate.get("dynamic_agent_spec")
        if isinstance(spec, Mapping):
            return {str(key): item for key, item in spec.items()}
    return {}


def _find_swarm_specialist_contract(
    agent_id: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    prefix = "winning_swarm_"
    if not str(agent_id).startswith(prefix):
        return {}
    archetype = str(agent_id)[len(prefix) :]
    # Local import keeps the role catalog authoritative without making the
    # general runtime-profile module initialize the orchestration layer early.
    from equipment_deep_research.orchestration.winning_swarm import (
        MISSION_GRAPH_CORE_ARCHETYPES,
        SWARM_SPECIALIST_ARCHETYPES,
    )

    role_catalog = {
        **SWARM_SPECIALIST_ARCHETYPES,
        **MISSION_GRAPH_CORE_ARCHETYPES,
    }
    if archetype not in role_catalog:
        raise ValueError(f"unknown winning swarm specialist archetype: {archetype}")
    candidates: list[Mapping[str, Any]] = [value]
    for key in ("input", "task_input", "winning_mechanism_input"):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("input")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    task: Mapping[str, Any] = {}
    for candidate in candidates:
        raw_task = candidate.get("specialist_task")
        if isinstance(raw_task, Mapping):
            task = raw_task
            break
    task_archetype = str(task.get("archetype", archetype))
    if task and task_archetype != archetype:
        raise ValueError(
            "winning swarm runtime archetype does not match specialist_task"
        )
    catalog = role_catalog[archetype]
    catalog_target = str(catalog["merge_target"])
    assigned_target = str(task.get("merge_target", catalog_target))
    dynamic_mission_graph = any(
        str(candidate.get("execution_profile_id", ""))
        == "winning_swarm_dynamic_v2"
        for candidate in candidates
    )
    expected_target = (
        assigned_target
        if dynamic_mission_graph
        and assigned_target in {"S1", "S2", "S3", "S4", "S5", "S6"}
        else catalog_target
    )
    if assigned_target != expected_target:
        raise ValueError(
            "winning swarm specialist_task crossed its catalog merge boundary"
        )
    allow_child_spawn = bool(task.get("allow_child_spawn", False))
    if allow_child_spawn:
        raise ValueError("dynamic specialists may not recruit child agents")
    role_contract = {
        "runtime_profile_id": f"winning_swarm_{archetype}",
        "version": "1.0",
        "archetype": archetype,
        "display_name": str(catalog["display_name"]),
        "purpose": str(catalog["purpose"]),
        "merge_target": expected_target,
        "quality_residuals": list(catalog.get("residuals", [])),
        "quality_gates": [
            f"必须实质改善 {residual}"
            for residual in catalog.get("residuals", [])
        ],
        "skill_ids": list(SWARM_RUNTIME_SKILL_IDS),
        "allow_child_spawn": False,
    }
    assignment = {
        "task_id": str(task.get("task_id", "")),
        "agent_instance_id": str(task.get("agent_instance_id", "")),
        "hypothesis_id": str(task.get("hypothesis_id", "")),
        "wave": task.get("wave", 0),
        "merge_target": assigned_target,
        "trigger_residuals": [
            str(item) for item in task.get("trigger_residuals", []) if str(item)
        ][:8],
        "expected_quality_gain": task.get("expected_quality_gain", 0),
        "allow_child_spawn": False,
    }
    return {"role_contract": role_contract, "assignment": assignment}


def _unique(values: Sequence[Any] | Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in (None, "", [], {}) and value not in result:
            result.append(value)
    return result


__all__ = [
    "CODEX_AGENT_RUNTIME_PROFILES",
    "CODEX_BRANCH_RUNTIME_PROFILES",
    "SAFETY_BOUNDARY",
    "MILITARY_MISSION_LENSES",
    "build_codex_runtime_profile",
    "is_optimized_v2_payload",
    "military_mission_lens",
]
