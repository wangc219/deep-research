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
DISRUPTIVE_EQUIPMENT_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "id": "A1",
        "dimension": "成本",
        "title": "成本强加",
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
        "shift": "后方集中交付→前沿分布式按需制造与快速改型",
        "equipment_pull": "模块化弹药、开放架构、数字设计及制造检测保障单元",
        "checks": "质量一致性、安全认证、材料供应和设计权管控",
        "signals": ("制造", "3d打印", "模块化", "数字孪生", "快速改型", "供应链", "生产"),
    },
    {
        "id": "B1",
        "dimension": "平台",
        "title": "持续火力场",
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
        "shift": "战时部署→平时预置、危机时可信激活",
        "equipment_pull": "深海/地下/轨道预置无人节点、长期能源、自检与授权控制",
        "checks": "可探测性、跨年可靠性、法律升级风险和防误激活",
        "signals": ("预置", "休眠", "唤醒", "深海", "轨道", "地下", "长期潜伏"),
    },
    {
        "id": "C1",
        "dimension": "时间",
        "title": "决策节奏对抗",
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
        "shift": "固定任务策略→批次数据回灌并快速更新后续无人/弹药策略",
        "equipment_pull": "安全数据回灌、模型更新、仿真验证、边缘学习与版本回退",
        "checks": "样本投毒、过拟合、可解释性、人在回路和更新失效",
        "signals": ("学习型", "越打越聪明", "数据回灌", "自主进化", "模型更新", "战役内"),
    },
    {
        "id": "D1",
        "dimension": "效应",
        "title": "功能压制",
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
        "shift": "行动仅追求物理结果→兼具威慑沟通和升级管理功能",
        "equipment_pull": "可控效应、行动可验证、战果评估与授权审计系统",
        "checks": "信号误读、文化差异、升级失控和责任边界",
        "signals": ("认知", "战略沟通", "信号", "威慑", "升级预期", "意志"),
    },
    {
        "id": "E1",
        "dimension": "体系",
        "title": "火力即服务",
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
        "shift": "自主规则全透明/全黑箱→选择性披露、可审计约束和可信接管",
        "equipment_pull": "规则验证、行为日志、权限分层、人工接管与安全停机系统",
        "checks": "被预测利用、威慑误判、责任归属和网络安全",
        "signals": ("算法威慑", "透明困境", "自主交战", "可验证约束", "人在回路", "人工接管"),
    },
    {
        "id": "F2",
        "dimension": "博弈可控",
        "title": "拒止环境自主",
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


# The disruptive lenses are useful only for weapon/effect queries.  This
# deterministic topic gate prevents branch priors from injecting the framework
# into unrelated research such as personnel, generic logistics or governance.
_DISRUPTIVE_EQUIPMENT_DOMAIN_SIGNALS: tuple[str, ...] = (
    "无人",
    "低空",
    "远程",
    "远域",
    "精打",
    "精确打击",
    "精确制导",
    "导弹",
    "弹药",
    "火力",
    "巡飞",
    "拦截",
    "防空",
    "反导",
    "反舰",
    "蜂群",
    "集群",
    "杀伤链",
    "歼灭",
    "毁伤",
    "压制",
    "拒止",
    "新质效应",
    "自主交战",
    "反介入",
    "区域拒止",
    "岛链",
    "a2/ad",
    "a2ad",
)


_BROAD_A2AD_THEME_SIGNALS: tuple[str, ...] = (
    "反介入",
    "区域拒止",
    "岛链",
    "a2/ad",
    "a2ad",
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


_BRANCH_SEED_PRIORS: dict[str, tuple[str, ...]] = {
    "A": ("B1", "C1", "E1", "E2", "F1"),
    "B": ("A1", "A2", "F2", "E1"),
    "C": ("A1", "C2", "E2", "F2"),
    "D": ("A2", "C2", "D1", "E1", "F1", "F2"),
    "E": ("A1", "B1", "E2", "F1", "F2"),
    "F": ("A1", "C1", "E1", "E2", "F2"),
    "G": ("B1", "B2", "D1", "E1", "F2"),
    "H": ("D2", "F1", "F2", "E2"),
}


_AGENT_SEED_PRIORS: dict[str, tuple[str, ...]] = {
    "combat_scenario": ("B1", "B2", "C1", "F2"),
    "weapon_equipment": tuple(item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS),
    "operational_employment": ("A1", "B1", "C1", "E1", "E2"),
    "technology_radar": ("A2", "C2", "D1", "E1", "F1", "F2"),
    "system_confrontation": ("A1", "C1", "E1", "E2", "F2"),
    "cross_domain_fusion": ("B1", "B2", "D1", "E1", "F2"),
    "scenario_divergence": tuple(item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS),
    "winning_s3_breakthrough": tuple(item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS),
    "winning_s4_capability": tuple(item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS),
    "winning_s5_gap": ("A1", "A2", "C2", "F2"),
    "winning_s6_image": tuple(item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS),
}


_AGENT_SEED_LIMITS: dict[str, int] = {
    "combat_scenario": 2,
    "weapon_equipment": 3,
    "operational_employment": 2,
    "technology_radar": 3,
    "system_confrontation": 3,
    "cross_domain_fusion": 3,
    "scenario_divergence": 2,
    "winning_s3_breakthrough": 4,
    "winning_s4_capability": 3,
    "winning_s5_gap": 2,
    "winning_s6_image": 3,
}


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
    """Select a small, diverse seed set without an additional model call."""

    limit = _AGENT_SEED_LIMITS.get(str(agent_id), 0)
    allowed = set(_AGENT_SEED_PRIORS.get(str(agent_id), ()))
    if limit <= 0 or not allowed:
        return []
    normalized_query = str(query).lower()
    broad_a2ad_theme = any(
        signal in normalized_query for signal in _BROAD_A2AD_THEME_SIGNALS
    )
    if not any(
        signal in normalized_query
        for signal in _DISRUPTIVE_EQUIPMENT_DOMAIN_SIGNALS
    ):
        return []
    branch_priors = _BRANCH_SEED_PRIORS.get(str(branch), ())
    agent_priors = _AGENT_SEED_PRIORS.get(str(agent_id), ())
    directly_matched: list[tuple[int, int, int, int, dict[str, Any]]] = []
    exploration_candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for position, item in enumerate(DISRUPTIVE_EQUIPMENT_SEEDS):
        seed_id = str(item["id"])
        if seed_id not in allowed:
            continue
        matched_signals = [
            str(signal)
            for signal in item["signals"]
            if str(signal).lower() in normalized_query
        ]
        branch_rank = (
            len(branch_priors) - branch_priors.index(seed_id)
            if seed_id in branch_priors
            else 0
        )
        agent_rank = (
            len(agent_priors) - agent_priors.index(seed_id)
            if seed_id in agent_priors
            else 0
        )
        if matched_signals:
            # Priors only break ties between query-matched cards; they can no
            # longer make an unrelated card enter the primary selection.
            directly_matched.append(
                (len(matched_signals), branch_rank, agent_rank, -position, item)
            )
        else:
            exploration_candidates.append((branch_rank, agent_rank, -position, item))
    directly_matched.sort(
        key=lambda row: (-row[0], -row[1], -row[2], -row[3])
    )

    selected: list[dict[str, str]] = []
    used_dimensions: set[str] = set()
    # First retain the strongest query-matched card from each distinct lens.
    # Do not immediately consume the small context budget with two variants of
    # the same lens: a broad weapon query needs at least one bounded challenge
    # from another dimension to escape the incremental "capability fill" frame.
    for _, _, _, _, item in directly_matched:
        if len(selected) >= limit:
            break
        dimension = str(item["dimension"])
        if dimension in used_dimensions:
            continue
        selected.append(_public_seed_card(item, selection_basis="query_signal"))
        used_dimensions.add(dimension)

    # When the Query only exposes one explicit disruptive lens, add exactly one
    # clearly marked, branch-relevant challenge card.  This gives S3/S4/S6 a
    # genuine two-lens comparison without flooding every Agent with the full
    # framework or pretending that the second lens is evidence.
    if selected and len(used_dimensions) == 1 and len(selected) < limit:
        exploration_candidates.sort(
            key=lambda row: (-row[0], -row[1], -row[2])
        )
        for _, _, _, item in exploration_candidates:
            dimension = str(item["dimension"])
            if dimension in used_dimensions:
                continue
            selected.append(
                _public_seed_card(
                    item,
                    selection_basis="bounded_exploration",
                )
            )
            used_dimensions.add(dimension)
            break

    # Fill any residual slots only with direct Query matches.  Priors never
    # create a third speculative card.
    for _, _, _, _, item in directly_matched:
        if len(selected) >= limit:
            break
        if any(row["id"] == item["id"] for row in selected):
            continue
        selected.append(_public_seed_card(item, selection_basis="query_signal"))

    # A broad A2/AD or island-chain equipment query names a battlespace rather
    # than a disruptive mechanism. Give it two branch-relevant, dimensionally
    # distinct challenge cards so the reasoning can compare real alternatives,
    # while still avoiding the full framework. Other broad weapon queries keep
    # the previous single-card bound.
    if not selected and exploration_candidates and limit > 0:
        exploration_candidates.sort(
            key=lambda row: (-row[0], -row[1], -row[2])
        )
        exploration_limit = min(limit, 2 if broad_a2ad_theme else 1)
        for _, _, _, item in exploration_candidates:
            dimension = str(item["dimension"])
            if dimension in used_dimensions:
                continue
            selected.append(
                _public_seed_card(
                    item,
                    selection_basis="bounded_exploration",
                )
            )
            used_dimensions.add(dimension)
            if len(selected) >= exploration_limit:
                break
    return selected[:limit]


def disruptive_seed_context(
    query: str,
    *,
    branch: str,
    agent_id: str,
) -> dict[str, Any]:
    """Build the bounded runtime context for disruptive equipment reasoning."""

    cards = select_disruptive_equipment_seeds(
        query,
        branch=branch,
        agent_id=agent_id,
    )
    if not cards:
        return {}
    context: dict[str, Any] = {
        "cards": cards,
        "rule": (
            "种子仅是按Query筛选的内部反事实镜头，不是事实、指标或必选目录；优先比较2至3类，"
            "证据不足不补齐，bounded_exploration最多挑战一个既有前提。实战门：必须贯通"
            "对手/场景—任务链断点—具体装备—打击/歼灭/压制/拦截/毁伤/拒止效果—可量化验证，"
            "并说明对手反制、失效边界与人在回路；不满足即淘汰。允许提出OTHER新方向。"
        ),
    }
    return context


def _public_seed_card(
    item: dict[str, Any],
    *,
    selection_basis: str,
) -> dict[str, str]:
    return {
        "id": str(item["id"]),
        "dimension": str(item["dimension"]),
        "title": str(item["title"]),
        "shift": str(item["shift"]),
        "equipment_pull": str(item["equipment_pull"]),
        "checks": str(item["checks"]),
        "selection_basis": selection_basis,
    }
