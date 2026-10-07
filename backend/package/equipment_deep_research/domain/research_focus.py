"""Compact reference-focus kernels for A-H branches and baseline agents.

The source requirements are intentionally stored as short, unique-owner
kernels.  Runtime prompts consume only the selected branch kernel and the
current agent's lenses instead of repeating the full reference text.
"""

from __future__ import annotations

from typing import Any


# Each reference item has exactly one primary owner.  Items that are strategic
# context rather than an A-H discovery driver belong to a baseline agent.
REFERENCE_REQUIREMENT_OWNERS: dict[int, str] = {
    1: "C",
    2: "international_situation",
    3: "F",
    4: "D",
    5: "E",
    6: "F",
    7: "G",
    8: "G",
    9: "E",
    10: "A",
    11: "B",
    12: "D",
}


BRANCH_REFERENCE_FOCUS: dict[str, dict[str, Any]] = {
    "A": {
        "source_items": [10],
        "task_kernel": (
            "智能化大规模全域联合作战场景→提炼任务组织、决策节奏和无人远火新运用机理"
            "→交付竞争性新战法、装备族和验证命题。"
        ),
    },
    "B": {
        "source_items": [11],
        "task_kernel": (
            "周边控制、远海前出、远程快打和远域任务→按对陆海空任务链检查现役短板与失效边界"
            "→交付做优清单、拓新接口和建设优先级。"
        ),
    },
    "C": {
        "source_items": [1],
        "task_kernel": (
            "近期局部冲突中的无人系统和远程火力运用→区分有效机制、失效条件和迁移边界"
            "→交付证据矩阵、装备启示和待验证假设。"
        ),
    },
    "D": {
        "source_items": [4, 12],
        "task_kernel": (
            "人工智能、量子、无人、太空、电磁及新质效应证据→推演组合跃迁和工程约束"
            "→交付跨代装备概念、存量做优路径和成熟度路线。"
        ),
    },
    "E": {
        "source_items": [5, 9],
        "task_kernel": (
            "强敌全球部署、合作支援和多层防御建设→识别能力增量、体系依赖和形成信号"
            "→交付威胁图谱、预警指标及装备对冲需求。"
        ),
    },
    "F": {
        "source_items": [3, 6],
        "task_kernel": (
            "穿透性制空、隐身水下平台及马赛克/决策中心体系→拆解制胜机理和关键依赖"
            "→交付反穿透/反体系装备族、韧性方案和压力测试。"
        ),
    },
    "G": {
        "source_items": [7, 8],
        "task_kernel": (
            "空天、深海、电磁和网络能力扩展→研究信息、指挥、效应与保障接口"
            "→交付跨域装备组合、失联降级模式和联合验证方案。"
        ),
    },
    "H": {
        "source_items": [],
        "task_kernel": (
            "无人扩散、商业基础设施和灰色风险→分析军民交织、冲突外溢与规则边界"
            "→交付预警、防护、保障及可控非致命装备需求；本轮不强行吸收其他条目。"
        ),
    },
}


BASELINE_AGENT_EXPANSION_LENSES: dict[str, tuple[str, ...]] = {
    "international_situation": (
        "美西方、台海、南海、日印朝及海外通道风险耦合",
        "联盟部署、危机升级与战略误判控制",
        "把形势变化转换为无人远火场景和任务压力",
    ),
    "combat_scenario": (
        "多方向并发与危机阶段转换",
        "拒止环境、战损条件和持续任务场景",
        "周边控制、远海前出、远程快打与远域任务边界",
    ),
    "weapon_equipment": (
        "无人/远火具体装备族及角色完整性",
        "现役做优、新研拓新和通用载荷复用边界",
        "全寿命成本、补充能力、成熟度和验证",
    ),
    "operational_employment": (
        "对陆、对海、对空任务链和关键窗口",
        "分层控制、拒止与反制任务效果",
        "战损续接、保障约束和失败模式",
    ),
    "case_research": (
        "俄乌及中东等战例中的无人远火运用",
        "成功/失效对照、成本交换和反制周期",
        "战例证据校核与经验迁移边界",
    ),
    "technology_radar": (
        "人工智能、量子、无人、太空、电磁网络和新质效应",
        "跨技术非线性组合与工程集成瓶颈",
        "成熟度、供应链依赖和反制敏感性",
    ),
    "opponent_monitoring": (
        "穿透性制空、马赛克/决策中心和低成本集群演进",
        "多层预警拦截及空天深海网电部署信号",
        "盟友基地、工业产能和组织编制同步变化",
    ),
    "system_confrontation": (
        "A2/AD穿透—反穿透与分布式杀伤体系依赖",
        "感知—指挥—效应器解耦及级联失效",
        "战损重构、成本交换反转和对手适应后剩余价值",
    ),
    "cross_domain_fusion": (
        "空天深海电磁网络的授权、数据和时序接口",
        "在轨快速部署、水下无人组网和频谱网电协同",
        "跨域故障级联与失联降级协同",
    ),
    "nontraditional_security": (
        "商业无人技术扩散和民用设施军事化风险",
        "海外节点、灰色行动与非国家行为体",
        "法律伦理、升级控制和军地韧性",
    ),
    "scenario_divergence": (
        "扫描现有分支未覆盖的新对手、新空间、新任务和新效应",
        "最多保留两个能改变体系关系的高价值新增方向",
    ),
}


# Compact disruptive-equipment seeds.  They are hypotheses for divergence,
# never evidence or pre-approved requirements.  Only the few cards selected by
# the deterministic matcher enter a Codex task.
DISRUPTIVE_EQUIPMENT_SEED_LIBRARY_VERSION = "v2"


DISRUPTIVE_EQUIPMENT_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "id": "A1",
        "dimension": "成本",
        "title": "成本强加",
        "original_paradigm": "拦截经济学反转",
        "research_relation": "单件性能竞争→体系交换比竞争",
        "shift": "高性能少量精打→低成本规模精确效应与持续成本强加",
        "equipment_pull": "低成本远程弹药族、规模任务规划、分布式补充保障",
        "checks": "全寿命成本、产能、对手廉价反制及我方抗规模打击",
        "signals": (
            "成本",
            "效费比",
            "拦截",
            "低成本",
            "廉价",
            "量产",
            "弹药",
            "防空",
            "成本交换",
            "规模化",
            "远程精打",
            "远程精确",
        ),
    },
    {
        "id": "A2",
        "dimension": "成本",
        "title": "制造即战力",
        "original_paradigm": "前线弹药工厂",
        "research_relation": "后方库存→分布式按需制造",
        "shift": "后方集中交付→前沿分布式按需制造与快速改型",
        "equipment_pull": "模块化弹药、开放架构、数字设计及制造检测保障单元",
        "checks": "质量一致性、安全认证、材料供应和设计权管控",
        "signals": ("制造", "3d打印", "模块化", "数字孪生", "快速改型", "供应链", "生产"),
    },
    {
        "id": "B1",
        "dimension": "平台",
        "title": "持续火力场",
        "original_paradigm": "徘徊火力云",
        "research_relation": "临时发射→战区持续存在",
        "shift": "临战发射→无人/巡飞节点长期驻留、任务出现即响应",
        "equipment_pull": "长航时低特征平台、能源补给、自主待机接替与集群管理",
        "checks": "暴露累积、误识别、弱网协同、回收维护和安全终止",
        "signals": (
            "徘徊",
            "长航时",
            "持续驻留",
            "火力云",
            "巡飞",
            "待机",
            "水下",
            "无人远程",
            "远程无人",
            "低空无人",
        ),
    },
    {
        "id": "B2",
        "dimension": "平台",
        "title": "预置任务节点",
        "original_paradigm": "和平预置、战时激活",
        "research_relation": "战时部署→预先部署和可信激活",
        "shift": "战时部署→平时预置、危机时可信激活",
        "equipment_pull": "深海/地下/轨道预置无人节点、长期能源、自检与授权控制",
        "checks": "可探测性、跨年可靠性、法律升级风险和防误激活",
        "signals": ("预置", "休眠", "唤醒", "深海", "轨道", "地下", "长期潜伏"),
    },
    {
        "id": "C1",
        "dimension": "时间",
        "title": "决策节奏对抗",
        "original_paradigm": "毁平台转向毁节奏",
        "research_relation": "物理摧毁→压缩或扰乱决策周期",
        "shift": "只追求己方更快→削弱对手感知、判断和资源调度节奏",
        "equipment_pull": "时敏感知、节奏建模、任务编排与效果评估系统",
        "checks": "误判、升级外溢、对手自动化适应和效果可测性",
        "signals": (
            "决策节奏",
            "ooda",
            "时敏",
            "时间窗",
            "节奏",
            "疲劳",
            "多波次",
            "决策周期",
        ),
    },
    {
        "id": "C2",
        "dimension": "时间",
        "title": "战役内学习",
        "original_paradigm": "越打越聪明",
        "research_relation": "固定策略→批次间快速学习",
        "shift": "固定任务策略→批次数据回灌并快速更新后续无人/弹药策略",
        "equipment_pull": "安全数据回灌、模型更新、仿真验证、边缘学习与版本回退",
        "checks": "样本投毒、过拟合、可解释性、人在回路和更新失效",
        "signals": ("学习型", "越打越聪明", "数据回灌", "自主进化", "模型更新", "战役内"),
    },
    {
        "id": "D1",
        "dimension": "效应",
        "title": "功能压制",
        "original_paradigm": "非动能点穴瘫痪",
        "research_relation": "结构毁伤→关键功能失效",
        "shift": "单一爆炸毁伤→可控非动能、可逆或低附带效应",
        "equipment_pull": "电磁/电子压制等非动能效应器及效果识别评估载荷",
        "checks": "效果可测性、环境影响、对手屏蔽恢复和法律边界",
        "signals": (
            "非动能",
            "功能瘫痪",
            "功能毁伤",
            "电磁注入",
            "电子压制",
            "可逆效应",
            "新质毁伤",
            "定向能",
            "高功率微波",
        ),
    },
    {
        "id": "D2",
        "dimension": "效应",
        "title": "战略信号",
        "original_paradigm": "打击作为战略信号",
        "research_relation": "单纯毁伤→打击与认知效应结合",
        "shift": "行动仅追求物理结果→兼具威慑沟通和升级管理功能",
        "equipment_pull": "可控效应、行动可验证、战果评估与授权审计系统",
        "checks": "信号误读、文化差异、升级失控和责任边界",
        "signals": ("认知", "战略沟通", "信号", "威慑", "升级预期", "意志"),
    },
    {
        "id": "E1",
        "dimension": "体系",
        "title": "火力即服务",
        "original_paradigm": "任意传感器匹配最优射手",
        "research_relation": "平台绑定→传感器与射手解耦",
        "shift": "传感器与射手平台绑定→跨域感知、指挥和效应器动态匹配",
        "equipment_pull": "开放任务接口、可信融合、火力资源池和分布式任务分配",
        "checks": "数据污染、权限冲突、链路中断和单点算法依赖",
        "signals": (
            "传感器-射手",
            "传感器射手",
            "火力即服务",
            "任意传感器",
            "弹药池",
            "动态匹配",
            "火力资源池",
            "杀伤链",
        ),
    },
    {
        "id": "E2",
        "dimension": "体系",
        "title": "集群对抗生态",
        "original_paradigm": "蜂群对蜂群",
        "research_relation": "单平台对抗→算法和种群对抗",
        "shift": "单群单任务→异构无人种群与反集群体系持续适应",
        "equipment_pull": "异构集群、反集群节点、群体态势、资源调度和快速补充",
        "checks": "失控涌现、敌我识别、频谱拥塞和成本交换反转",
        "signals": (
            "蜂群",
            "集群对抗",
            "算法对算法",
            "种群",
            "反集群",
            "异构集群",
            "无人集群",
        ),
    },
    {
        "id": "F1",
        "dimension": "博弈可控",
        "title": "可验证自主",
        "original_paradigm": "算法威慑、选择性透明",
        "research_relation": "黑箱自主→可约束、可验证自主",
        "shift": "自主规则全透明/全黑箱→选择性披露、可审计约束和可信接管",
        "equipment_pull": "规则验证、行为日志、权限分层、人工接管与安全停机系统",
        "checks": "被预测利用、威慑误判、责任归属和网络安全",
        "signals": ("算法威慑", "透明困境", "自主交战", "可验证约束", "人在回路", "人工接管"),
    },
    {
        "id": "F2",
        "dimension": "博弈可控",
        "title": "拒止环境自主",
        "original_paradigm": "越降级越自主",
        "research_relation": "网络依赖→断链条件下任务自治",
        "shift": "依赖卫星/链路/单一导航→受限时分级自治、任务重构和安全降级",
        "equipment_pull": "多源导航、离线规划、低带宽协同、失联安全与替代链",
        "checks": "自主边界、态势过期、误伤风险和任务中止条件",
        "signals": (
            "卫星致盲",
            "数据链切断",
            "gps不可用",
            "导航拒止",
            "降级可用",
            "失联",
            "弱网",
            "拒止环境",
            "断链",
        ),
    },
)


# These compact groups are an acceptance vocabulary, not a prompt checklist.
# They let S6 and Reporter prove that several genuinely different causal
# relationships reached the final equipment portfolio without injecting the
# full disruptive framework into every runtime context.
DISRUPTIVE_RELATIONSHIP_SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "cost_industrial": (
        "低成本",
        "成本交换",
        "交换比",
        "边际成本",
        "单位拦截成本",
        "库存消耗",
        "规模量产",
        "批量生产",
        "工业补充",
        "战损再生",
        "快速再装填",
    ),
    "platform_presence": (
        "可消耗",
        "长航时",
        "持续值班",
        "持续存在",
        "预置",
        "分布式机动",
        "多点发射",
        "低暴露",
        "无人僚机",
        "无人集群",
        "火力云",
    ),
    "time_learning": (
        "决策周期",
        "决策节奏",
        "时间窗",
        "多波次",
        "再打击",
        "毁伤评估",
        "任务重规划",
        "战役内进化",
        "越打越",
        "响应时间",
    ),
    "effects": (
        "电子压制",
        "反辐射",
        "定向能",
        "高能激光",
        "高功率微波",
        "非动能",
        "功能瘫痪",
        "软杀伤",
        "电磁注入",
    ),
    "system_ecology": (
        "传感器—射手",
        "传感器-射手",
        "火力池",
        "资源池",
        "任务闭环",
        "弱网",
        "断链",
        "任务重构",
        "分布式协同",
        "跨域火控",
        "杀伤生态",
    ),
    "controlled_escalation": (
        "人在回路",
        "人工授权",
        "人工批准",
        "选择性披露",
        "可验证约束",
        "任务取消",
        "人工接管",
        "安全降级",
        "失联安全",
        "交战边界",
    ),
}


def disruptive_relationship_groups(text: Any) -> tuple[str, ...]:
    """Return naturally evidenced disruptive relationship groups in text."""

    normalized = str(text).lower()
    return tuple(
        name
        for name, signals in DISRUPTIVE_RELATIONSHIP_SIGNAL_GROUPS.items()
        if any(str(signal).lower() in normalized for signal in signals)
    )


REFERENCE_DEDUP_RULES: tuple[str, ...] = (
    "E只研究对手部署与能力形成，F只研究体系制胜机理和反制。",
    "D合并技术跃迁与新质效应，共用成熟度、风险和验证框架。",
    "G合并空天深海与电磁网络，共用跨域接口和降级模型。",
    "A只形成未来战法，不重复研究形势、技术、对手装备和体系基线。",
    "B统一归并现役缺口；其他分支只提交候选需求和证据。",
    "同一装备族以主需求加跨分支接口表达，禁止重复立项。",
)


def branch_reference_focus(branch: str) -> dict[str, Any]:
    """Return a copy-safe compact focus block for one branch."""

    value = BRANCH_REFERENCE_FOCUS.get(str(branch), {})
    return {
        "source_items": list(value.get("source_items", [])),
        "task_kernel": str(value.get("task_kernel", "")),
    }


def baseline_agent_expansion_lenses(agent_id: str) -> list[str]:
    """Return only the current agent's short reference lenses."""

    return list(BASELINE_AGENT_EXPANSION_LENSES.get(str(agent_id), ()))


def select_disruptive_equipment_seeds(
    query: str,
    *,
    branch: str,
    agent_id: str,
) -> list[dict[str, str]]:
    """Recall only Query-linked reference lenses.

    Branch and role priors used to inject cards even when the Query did not
    name the underlying problem.  Codex now performs the open-ended expansion;
    this local function is deliberately a cheap, conservative fallback that
    returns direct semantic hits only.  ``branch`` and ``agent_id`` remain in
    the signature for persisted callers, but no longer constrain exploration.
    """

    del branch, agent_id
    limit = 3
    normalized_query = str(query).lower()
    if not normalized_query.strip():
        return []
    directly_matched: list[tuple[int, int, dict[str, Any]]] = []
    for position, item in enumerate(DISRUPTIVE_EQUIPMENT_SEEDS):
        matched_signals = [
            str(signal)
            for signal in item["signals"]
            if str(signal).lower() in normalized_query
        ]
        if matched_signals:
            directly_matched.append(
                (sum(len(value) for value in matched_signals), -position, item)
            )
    directly_matched.sort(key=lambda row: (-row[0], -row[1]))

    selected: list[dict[str, str]] = []
    used_dimensions: set[str] = set()
    for _, _, item in directly_matched:
        if len(selected) >= limit:
            break
        dimension = str(item["dimension"])
        if dimension in used_dimensions:
            continue
        selected.append(_public_seed_card(item, selection_basis="query_signal"))
        used_dimensions.add(dimension)
    for _, _, item in directly_matched:
        if len(selected) >= limit:
            break
        if any(row["id"] == item["id"] for row in selected):
            continue
        selected.append(_public_seed_card(item, selection_basis="query_signal"))
    return selected[:limit]


def disruptive_seed_context(
    query: str,
    *,
    branch: str,
    agent_id: str,
) -> dict[str, Any]:
    """Build Query-activated seeds for a Codex semantic digestion pass.

    Keyword matching is retained as a cheap recall mechanism.  It only decides
    which evidence/search priors deserve attention; it never decides which
    equipment direction survives.  The receiving Codex session must reinterpret
    every seed against the complete Query and may rewrite or discard all cards.
    """

    cards = select_disruptive_equipment_seeds(
        query,
        branch=branch,
        agent_id=agent_id,
    )
    if not cards:
        return {}
    context: dict[str, Any] = {
        "library_version": DISRUPTIVE_EQUIPMENT_SEED_LIBRARY_VERSION,
        "cards": cards,
        "rule": (
            "种子由Query信号激活，只是检索和反事实思考的起点，不是事实、指标、目录、命名模板或配额。"
            "Codex应从完整Query自行发散竞争解释或OTHER替代方向，逐卡说明因果关系，并可改写或"
            "丢弃全部种子；不得复制种子标题作为装备名，也不得复制equipment_pull或公开型号作为最终装备名。"
            "若把当前Query替换为另一任务后结论仍基本不变，视为未完成语义消化，必须重新发散。"
            "实战门：必须贯通"
            "对手/场景—任务链断点—具体装备—打击/歼灭/压制/拦截/毁伤/拒止效果—可量化验证，"
            "并说明对手反制、失效边界与人在回路；不满足即淘汰。"
        ),
    }
    return context


def disruptive_seed_pool_context() -> dict[str, Any]:
    """Expose the complete seed pool for a post-divergence Codex challenge.

    Unlike ``disruptive_seed_context``, this function performs no keyword or
    branch matching.  It is intentionally used only after a model has already
    formed a free Query-specific angle portfolio, so a second semantic model
    pass can adopt, rewrite, combine or discard seed relations without local
    code deciding which disruptive logic applies.
    """

    return {
        "library_version": DISRUPTIVE_EQUIPMENT_SEED_LIBRARY_VERSION,
        "cards": [
            _public_seed_card(item, selection_basis="post_divergence_model_review")
            for item in DISRUPTIVE_EQUIPMENT_SEEDS
        ],
        "rule": (
            "完整种子池只在自由制胜角度形成后交给独立Codex作反事实挑战。"
            "模型可采用、重写、跨种子重构、形成遗漏角度或全部舍弃；"
            "不得按维度逐项覆盖，不得复制种子标题、equipment_pull或示例装备作为候选名称。"
        ),
    }


def _public_seed_card(
    item: dict[str, Any],
    *,
    selection_basis: str,
) -> dict[str, str]:
    return {
        "id": str(item["id"]),
        "dimension": str(item["dimension"]),
        "title": str(item["title"]),
        "original_paradigm": str(item["original_paradigm"]),
        "research_relation": str(item["research_relation"]),
        "shift": str(item["shift"]),
        "equipment_pull": str(item["equipment_pull"]),
        "checks": str(item["checks"]),
        "selection_basis": selection_basis,
    }
