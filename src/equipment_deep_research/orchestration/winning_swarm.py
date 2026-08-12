"""Bounded elastic specialist swarm for winning-mechanism research.

The controller is deliberately provider-agnostic.  It plans logical specialist
tasks, validates their isolated contributions and manages the candidate ledger;
the Agent provider remains responsible for executing each task in its own
governed session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
import re
from typing import Any

from equipment_deep_research.domain.models import (
    AgentPromotionRecord,
    HypothesisLedgerVersion,
    MergeReceipt,
    PortfolioDecision,
    SpecialistContribution,
    SpecialistTask,
    SwarmGateResult,
    SwarmPlan,
    WinningAgentInstance,
    WinningContribution,
    WinningExpertAssessment,
    WinningHypothesis,
    WinningMissionGraph,
    WinningRoleContract,
    to_plain,
)


MERGE_TARGETS = frozenset({"S1", "S2", "S3", "S4", "S5", "S6", "convergence"})

_INTERNAL_WORKFLOW_COMMENTARY_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:S[1-6]|L[1-4])(?![A-Za-z0-9])|"
    r"Codex|Harness|Packet|Claim|Agent|智能体|候选账本|专家盲评|非支配候选|"
    r"组合评审|质量门|角色合同|执行流程|补写|交接状态|退回S[1-6]|回到S[1-6]"
)


def _user_facing_text_list(value: Any, *, limit: int) -> list[str]:
    """Keep military content while preventing audit commentary from entering S6.

    Internal rows remain available through ``findings`` and event/audit records;
    they are simply not merged into fields later rendered as operational prose.
    """

    return [
        item
        for item in _text_list(value, limit=limit)
        if not _INTERNAL_WORKFLOW_COMMENTARY_RE.search(item)
    ]


def _user_facing_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()[:limit]
    return "" if _INTERNAL_WORKFLOW_COMMENTARY_RE.search(text) else text


# Proposal names are communication aids, never claims that a named programme
# exists.  Keeping this rule next to swarm planning makes it available before
# S6, where names otherwise arrive already template-shaped.
QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION = (
    "把命名交给Codex基于完整Query和已经闭合的整装语义作最后一次整体编辑，而不是字段拼装任务。"
    "名称在装备身份和制胜机理闭合后整体创作，应像未来装备体系中真实存在、作战人员会自然使用的真实装备名。"
    "命名前先闭合frontier_principle、technology_discontinuity和disruptive_shift。"
    "命名时可在内部比较构型意象型、原理突破型和装备专名型等自然思路。"
    "只突出一个最有辨识度的构型、原理或战场存在方式（如核心物理意象＋装备身份、自然现象或生物意象＋新型装备、代号＋装备类别、原理突破＋装备身份），同时让人看得出主装备是什么；"
    "不默认两字代号、统一后缀或固定字符区间。"
    "不使用统一系列标记。"
    "名称不是候选摘要；以上只是开放思路，不是模板、配额或分类覆盖任务。"
    "不要把字段压缩成标题，不用功能/动作短语＋装备类别尾词，"
    "不套‘智能/增强型/下一代/多功能XX系统’模板，不复制真实项目名。"
    "临时去掉引号或代号后仍是机械底名时，不能靠加意象挽救，应回到装备形态和原理重新命名。"
    "自由角度形成后才允许由模型吸收外部启发。"
    "不建立意象词库、后缀表、字符串评分或本地命名硬门；不得复制共享示例。"
    "不输出备选名、逐词解释或检查过程。"
)


# These are open combat-effect lenses for the Query-level controller, not a
# fixed taxonomy, production quota, keyword gate, or weapon-family catalogue.
# The controller may activate any subset and may add a Query-specific OTHER
# lens when the battlefield relationship does not fit this vocabulary.
COMBAT_EQUIPMENT_DIVERGENCE_DIMENSIONS: tuple[dict[str, str], ...] = (
    {"dimension": "毁伤", "meaning": "直接破坏目标，或削弱目标功能与结构能力"},
    {"dimension": "打击", "meaning": "对指定目标实施远程或近程攻击并施加效果"},
    {"dimension": "突防", "meaning": "突破防御体系并生存进入目标作用区域"},
    {"dimension": "拦截", "meaning": "发现、跟踪并阻断敌方目标行动"},
    {"dimension": "压制", "meaning": "降低敌方感知、通信、火力或行动能力"},
    {"dimension": "拒止", "meaning": "阻止敌方进入、行动或持续作战"},
    {"dimension": "侦察感知", "meaning": "发现、识别、定位目标和环境"},
    {"dimension": "预警", "meaning": "提前发现威胁并形成响应窗口"},
    {"dimension": "电子对抗", "meaning": "影响敌方电子信息系统"},
    {"dimension": "威慑", "meaning": "通过可信能力改变敌方决策"},
    {"dimension": "生存抗毁", "meaning": "提高装备自身持续作战能力"},
    {"dimension": "战场控制", "meaning": "改变区域、空间或时间上的作战主动权"},
)

CORE_STEP_DEPENDENCIES: dict[int, tuple[int, ...]] = {
    1: (),
    2: (),
    3: (1, 2),
    4: (3,),
    5: (4,),
    6: (4, 5),
}

SWARM_SPECIALIST_ARCHETYPES: dict[str, dict[str, Any]] = {
    "frontier_equipment_miner": {
        "display_name": "前沿装备矿工",
        "purpose": (
            "以Query为先，从与任务对象、威胁形态、作战阶段、地域约束和制胜矛盾直接匹配的"
            "公开项目、试验和装备族中寻找具体战斗武器；无人、远程、低空、精确打击等方向"
            "只有被Query语义触发时才进入观察，不得作为跨Query默认目录。"
        ),
        "merge_target": "S5",
        "residuals": ["equipment_not_concrete", "novelty_insufficient"],
    },
    "weak_signal_scout": {
        "display_name": "技术弱信号侦察",
        "purpose": "识别早期技术、试验里程碑和跨行业弱信号，并严格区分潜力与成熟能力。",
        "merge_target": "S3",
        "residuals": ["novelty_insufficient", "evidence_insufficient"],
    },
    "disruptive_mechanism_generator": {
        "display_name": "颠覆机理生成",
        "purpose": "构造机制真正不同的竞争假设，说明改变的对抗变量、军事效果和失败条件。",
        "merge_target": "S3",
        "residuals": ["causal_chain_broken", "novelty_insufficient"],
    },
    "direct_combat_equipment_generator": {
        "display_name": "Query直接杀伤装备机理生成",
        "purpose": (
            "从直接军事效果反推可独立立项的主战或无人作战装备候选；候选主体必须是"
            "具备侦察、压制、拦截、打击或毁伤效应的具体平台、弹药或任务载荷，"
            "通信、算法、任务胶囊、网关和保障只能作为其体系接口。始终按Query筛选，"
            "必须从Query的任务对象、威胁形态、作战阶段和制胜矛盾开放推演；无人、低空、"
            "远程与精确打击只作为优先观察镜头，不得机械套用或框定最终装备。"
        ),
        "merge_target": "S3",
        "residuals": [
            "direct_combat_equipment_insufficient",
            "equipment_not_concrete",
            "novelty_insufficient",
        ],
    },
    "remote_precision_munition_generator": {
        "display_name": "Query主效武器架构生成",
        "purpose": (
            "依据Query语义形成可独立立项的主效打击、歼灭或反杀伤武器架构，开放比较发射域、"
            "平台、目标包线、感知导引、突防/拦截方式和毁伤机理；候选必须是与Query直接相关的"
            "具体武器装备。远程精打、巡飞弹、无人平台或模块化弹药仅是非穷尽观察镜头；"
            "不输出制造参数、目标坐标或可执行攻击步骤。"
        ),
        "merge_target": "S3",
        "residuals": [
            "direct_combat_equipment_insufficient",
            "equipment_not_concrete",
            "military_effect_missing",
        ],
    },
    "mass_scalable_combat_family_generator": {
        "display_name": "Query非对称新质装备机理生成",
        "purpose": (
            "从Query的制胜矛盾探索改变成本、平台、时间、毁伤、体系或博弈关系的新质武器，"
            "并落实为具体直接作战装备。低成本、系列化、规模化、柔性生产和战损补充仅在"
            "Query因果需要时进入构型，不是强制主题；不能为覆盖镜头强造无关类别，也不能把"
            "供应链或软件平台单列为主体装备。"
        ),
        "merge_target": "S3",
        "residuals": [
            "direct_combat_equipment_insufficient",
            "engineering_feasibility_insufficient",
            "novelty_insufficient",
        ],
    },
    "baseline_delta_analyst": {
        "display_name": "现有方案差异比较",
        "purpose": "建立最近公开基线，识别候选相对现有方案的实质差异而非技术词堆叠。",
        "merge_target": "S2",
        "residuals": ["baseline_missing", "novelty_insufficient"],
    },
    "adversary_counter_adaptation_red_team": {
        "display_name": "对手反适应红队",
        "purpose": "检验对手适应后候选机理是否仍成立，并寻找可证伪失效边界。",
        "merge_target": "S3",
        "residuals": ["counter_adaptation_unresolved", "causal_chain_broken"],
    },
    "equipment_realization_architect": {
        "display_name": "装备实现架构",
        "purpose": (
            "贯通任务效果、功能、性能约束、体系接口、装备形态和实现路径；对命名不完整的"
            "候选，先按主装备本体、投送方式、目标、直接作用与机理重新作语义命名判断，"
            "不得用词表拼接或以内部载荷、火力、平台、弹药代替主装备。"
        ),
        "merge_target": "S5",
        "residuals": ["equipment_not_concrete", "engineering_feasibility_insufficient"],
    },
    "innovative_equipment_dimension_generator": {
        "display_name": "创新装备维度生成",
        "purpose": (
            "依据主控形成的Query装备语义蓝图，在被激活的作战维度内开放推演多个物理原理、"
            "战场存在方式和制胜关系真正不同的武器方向；独立完成整装身份、自然命名和一句制胜说明。"
            "本角色只创造候选，不承担装备物化、接口收敛、证据核验或工程验证。"
        ),
        "merge_target": "S4",
        "residuals": ["novelty_insufficient", "portfolio_direction_shortfall"],
    },
    "equipment_capability_image_repairer": {
        "display_name": "装备能力画像定向修复",
        "purpose": (
            "依据专家残差重写单一候选的装备能力闭环，贯通任务效果、作战运用、功能约束、"
            "体系接口、具体装备、公开基线、失效边界和验证指标；通信、算法、网关和治理"
            "只能作为接口。若证据不足，必须删除或收窄无法证明的构型、效能、成本与产能"
            "主张，改为证据边界内的固定构型和阶段目标，不能只追加验证要求。"
        ),
        "merge_target": "S5",
        "residuals": [
            "equipment_not_concrete",
            "capability_portrait_incomplete",
            "direct_combat_equipment_insufficient",
        ],
    },
    "trl_cost_industrial_auditor": {
        "display_name": "成熟度成本产能审查",
        "purpose": "审查TRL、成本、产能、工业依赖和规模化补充约束，拒绝无依据精确判断。",
        "merge_target": "S5",
        "residuals": ["engineering_feasibility_insufficient"],
    },
    "cross_scenario_stress_tester": {
        "display_name": "跨场景压力测试",
        "purpose": "在不同环境、任务阶段和降级条件下检验候选稳健性及适用边界。",
        "merge_target": "S3",
        "residuals": ["cross_scenario_unstable"],
    },
    "evidence_verifier": {
        "display_name": "证据与工程边界核验",
        "purpose": (
            "面向完整候选账本一次性核验公开基线、事实引用、反证与不确定性，并同步审查"
            "TRL、成本、产能、工业依赖和规模化补充边界；为每项候选检查可证伪指标、"
            "对照方案与判退条件，清除无效证据编号和无依据精确判断。"
        ),
        "merge_target": "S5",
        "residuals": [
            "evidence_insufficient",
            "unsupported_precision",
            "engineering_feasibility_insufficient",
            "validation_route_missing",
        ],
    },
    "validation_experiment_designer": {
        "display_name": "验证试验设计",
        "purpose": "在最终写卡前形成可证伪的指标、对照、试验步骤和淘汰条件，不虚构效能比例。",
        "merge_target": "S5",
        "residuals": ["validation_route_missing"],
    },
    "independent_portfolio_reviewer": {
        "display_name": "独立组合评审",
        "purpose": (
            "候选一旦完成即增量审查其组合独立性、互补性与直接装备属性，"
            "只作retain、merge或reject，不补写、改写或重新命名候选。"
        ),
        "merge_target": "S5",
        "residuals": [],
    },
}

# Dynamic-v2 only exposes lightweight creative roles plus incremental S5.
# Legacy archetypes remain available to the compatibility scheduler, but are
# excluded from the dynamic role catalogue and cannot be recruited there.
_DYNAMIC_V2_ARCHETYPE_IDS = frozenset(
    {
        "weak_signal_scout",
        "disruptive_mechanism_generator",
        "innovative_equipment_dimension_generator",
        "independent_portfolio_reviewer",
    }
)

MISSION_GRAPH_SEED_ARCHETYPES: dict[str, tuple[str, ...]] = {
    "S1": (
        "opponent_system_modeler",
        "adversary_adaptation_analyst",
        "weak_signal_scout",
    ),
    "S2": (
        "operational_baseline_analyst",
        "competitive_coa_designer",
        "baseline_delta_analyst",
    ),
    "S3": (
        "disruptive_mechanism_generator",
        "adversary_counter_adaptation_red_team",
        "cross_scenario_stress_tester",
    ),
    "S4": ("innovative_equipment_dimension_generator",),
    "S5": ("independent_portfolio_reviewer",),
}

MISSION_GRAPH_CORE_ARCHETYPES: dict[str, dict[str, Any]] = {
    "opponent_system_modeler": {
        "display_name": "对手体系建模",
        "purpose": "解释对手当前为何能赢，找出最值得改变的体系依赖和战场关系。",
        "merge_target": "S1",
        "residuals": ["causal_chain_broken", "counter_adaptation_unresolved"],
    },
    "adversary_adaptation_analyst": {
        "display_name": "对手优势反向建模",
        "purpose": "从对手最难被剥夺的优势出发，寻找另一组可被新装备改写的制胜矛盾。",
        "merge_target": "S1",
        "residuals": ["counter_adaptation_unresolved"],
    },
    "operational_baseline_analyst": {
        "display_name": "作战运用基线",
        "purpose": "从我方任务链、行动节奏和效应窗口中寻找值得新装备介入的矛盾。",
        "merge_target": "S2",
        "residuals": ["baseline_missing"],
    },
    "competitive_coa_designer": {
        "display_name": "任务关系重构",
        "purpose": "跳出现行流程，寻找能重新组织接敌、效应释放或战果积累关系的开放问题。",
        "merge_target": "S2",
        "residuals": ["novelty_insufficient", "military_effect_missing"],
    },
}


def _all_role_archetypes() -> dict[str, dict[str, Any]]:
    return {**SWARM_SPECIALIST_ARCHETYPES, **MISSION_GRAPH_CORE_ARCHETYPES}


def _frontloaded_role_governance(
    mission_node: str,
) -> tuple[list[str], list[str], list[str]]:
    """Return query-agnostic mutation and identity rules for one graph node."""

    common_methods = [
        "先读取角色合同、依赖快照和允许的hypothesis_id，再开始分析",
        "只提交本节点新增的信息；已完成的上游字段原样复用，不重复生成",
        "发现越权的新方向时写入portfolio_review，不直接改写候选账本",
    ]
    common_gates = [
        "候选身份主干在各节点间可追踪，禁止用同义改名掩盖装备替换",
        "同族候选是否独立由S5结合完整军事语义整体判断，不设差异轴数量、关键词或字符串阈值",
        "角色输出必须由完整Query决定，不得依赖固定装备类型清单",
    ]
    if mission_node in {"S1", "S2"}:
        return (
            [
                "只形成对手或任务矛盾种子，不创建最终装备卡",
                "从Query开放寻找值得新装备改变的关系，不从热门技术倒推问题",
            ],
            [
                "种子必须足以打开后续独立创造，但不能预定装备答案",
            ],
            ["reasoning_seeds", "quality_residuals", "stop_reason"],
        )
    if mission_node in {"S3", "S4"}:
        return (
            [
                "S3与S4都是创新武器候选创建入口；从Query与开放挑战独立创造，提交前锁定单一主装备身份",
                "只提交最小候选卡；不读取或补写证据、TRL、验证和反适应材料",
            ],
            [
                "候选自然闭合主装备、核心创新、制胜关系和直接战果",
            ],
            [
                "title", "equipment_form", "primary_equipment_identity",
                "target_and_direct_effect", "unique_operational_role",
                "changed_confrontation_variable", "frontier_principle",
                "disruptive_shift", "mechanism_chain", "direct_military_effects",
            ],
        )
    if mission_node == "S5":
        return (
            [
                "每批新增候选完成后立即审查其与已有组合的独立性、互补性和直接装备属性",
                "只能输出retain、merge或reject；不得生成、改写、补强、补证、估算成熟度、设计验证或重新命名候选",
            ],
            [
                "审查结论必须明确retain、merge或reject及其组合理由",
                "S3/S4冻结的名称、装备身份、机理和直接战果不得被S5修改",
            ],
            ["decisions", "portfolio_order", "portfolio_summary", "stop_reason"],
        )
    if mission_node == "S6":
        return (
            [
                *common_methods,
                "只为S5冻结组合并发撰写精简能力画像；不得新增、删除、换名或重排主装备",
                "恢复时复用已完成装备卡，不重跑完整组合",
            ],
            [
                *common_gates,
                "每张卡保持一个主装备、一个专属战场问题和一个清晰制胜逻辑",
                "五栏画像精简、互不复述，并使用一线设计人员可直接理解的语言",
            ],
            ["contributions", "portfolio_review", "stop_reason"],
        )
    return (
        [
            *common_methods,
            "组合评审只读候选身份，对同族差异和跨卡一致性作裁决，不生成替代候选",
        ],
        [
            *common_gates,
            "组合入选必须保留可审计的入选、同族合并、参考或淘汰理由",
        ],
        ["assessments", "portfolio_findings", "stop_reason"],
    )


def default_winning_swarm_policy(
    *, enabled: bool = False, policy_id: str = "winning_swarm_quality_v1"
) -> dict[str, Any]:
    dynamic_v2 = policy_id == "winning_swarm_dynamic_v2"
    quality_cluster = policy_id in {
        "winning_swarm_dynamic_v2",
        "swarm_quality_v1",
        "winning_swarm_quality_v1",
    }
    return {
        "policy_id": policy_id,
        "enabled": enabled,
        "max_dynamic_instances": 21 if dynamic_v2 else 12,
        "max_concurrency": 6,
        "max_waves": 3,
        "mission_graph_min_instances": 8 if dynamic_v2 else 4,
        "mission_graph_target_instances": 15 if dynamic_v2 else 4,
        "mission_graph_max_instances": 21 if dynamic_v2 else 12,
        "minimum_expected_gain": 0.03,
        "breadth_hypothesis_minimum": 1,
        "breadth_hypothesis_maximum": 12,
        # Capacity is not a quota. The Query controller may activate any
        # smaller number of relevant S3/S4 dimension Agents.
        "s3_winning_thesis_capacity": 8 if dynamic_v2 else 0,
        # A branch may reject both its initial thesis and the first reserve.
        # Keep additional precomputed reserve handoffs so the dynamically
        # activated S3 set does not collapse after a sound semantic rejection. Every retry
        # still uses a thesis selected before S3; no local family filling.
        "s3_empty_reallocation_max": 2 if dynamic_v2 else 0,
        # The lower bound is a delivery safety floor, not a generation quota.
        # Dynamic v2 may stop with two independently valuable directions when
        # additional candidates add no new winning relationship; the bounded
        # upper limit still prevents an unreviewable card wall.
        "finalist_minimum": 2 if dynamic_v2 else 5 if quality_cluster else 2,
        "finalist_maximum": 7 if quality_cluster else 4,
        "minimum_direct_combat_equipment": 2
        if dynamic_v2
        else 3
        if quality_cluster
        else 0,
        "preferred_distinct_direct_equipment": (
            3 if dynamic_v2 else 5 if quality_cluster else 0
        ),
        "recursive_recruitment_allowed": False,
        "raw_session_sharing_allowed": False,
        "expert_judge_enabled": False if dynamic_v2 else quality_cluster,
        "expert_judge_required": False if dynamic_v2 else quality_cluster,
        "expert_candidate_pool_maximum": 0 if dynamic_v2 else 10 if quality_cluster else 8,
        "foresight_first_enabled": quality_cluster,
        "frontier_evidence_relaxation": quality_cluster,
        "frontier_final_gate_minimum_score": 0.62,
        "frontier_expert_judge_minimum_score": 0.66,
        "frontier_critical_dimension_minimum": 0.50,
        "expert_judge_minimum_score": 0.68 if quality_cluster else 0.72,
        "expert_judge_critical_dimension_minimum": 0.52 if quality_cluster else 0.60,
        "pending_verification_backfill_enabled": quality_cluster,
        "pending_verification_minimum_score": 0.54,
        "pending_verification_critical_dimension_minimum": 0.42,
        "expert_repair_enabled": False if dynamic_v2 else quality_cluster,
        "expert_repair_max_candidates": 0 if dynamic_v2 else 4,
        "expert_repair_minimum_score": 0.64 if quality_cluster else 0.70,
        "expert_repair_reserved_instances": 0 if dynamic_v2 else 4,
        "same_family_minimum_independent_axes": 2,
        "promotion": {
            "minimum_eligible_runs": 10,
            "minimum_positive_increment_rate": 0.70,
            "maximum_evidence_hard_failures": 0,
            "maximum_permission_hard_failures": 0,
            "offline_evaluation_required": True,
            "human_approval_required": True,
        },
        "archetypes": list(SWARM_SPECIALIST_ARCHETYPES),
    }


def normalize_winning_swarm_policy(
    value: Mapping[str, Any] | None,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    raw = dict(value or {})
    policy_id = str(raw.get("policy_id") or "winning_swarm_quality_v1")[:120]
    dynamic_v2 = policy_id == "winning_swarm_dynamic_v2"
    quality_cluster = policy_id in {
        "winning_swarm_dynamic_v2",
        "swarm_quality_v1",
        "winning_swarm_quality_v1",
    }
    base = default_winning_swarm_policy(
        enabled=bool(raw.get("enabled", False) if enabled is None else enabled),
        policy_id=policy_id,
    )
    # Dynamic v2 starts with 15 capacity slots, then may replace the single
    # S4 placeholder with up to seven candidate-bound realization sessions:
    # 4 S1/S2 + 8 S3 + 7 S4 + 2 S5 = 21 governed instances.
    maximum_instances = 21 if dynamic_v2 else 12
    maximum_concurrency = 6
    minimum_instances = 8 if dynamic_v2 else 1
    base.update(
        {
            "policy_id": policy_id,
            "enabled": bool(base["enabled"] if enabled is None else enabled),
            "max_dynamic_instances": _bounded_int(
                raw.get("max_dynamic_instances"),
                minimum_instances,
                maximum_instances,
                int(base["max_dynamic_instances"]),
            ),
            "max_concurrency": _bounded_int(
                raw.get("max_concurrency"),
                1,
                maximum_concurrency,
                int(base["max_concurrency"]),
            ),
            "max_waves": _bounded_int(raw.get("max_waves"), 1, 3, 3),
            "mission_graph_min_instances": _bounded_int(
                raw.get("mission_graph_min_instances"),
                minimum_instances,
                maximum_instances,
                int(base["mission_graph_min_instances"]),
            ),
            "mission_graph_target_instances": _bounded_int(
                raw.get("mission_graph_target_instances"),
                minimum_instances,
                maximum_instances,
                int(base["mission_graph_target_instances"]),
            ),
            "mission_graph_max_instances": _bounded_int(
                raw.get("mission_graph_max_instances"),
                minimum_instances,
                maximum_instances,
                int(base["mission_graph_max_instances"]),
            ),
            "minimum_expected_gain": _bounded_float(
                raw.get("minimum_expected_gain"), 0.0, 1.0, 0.03
            ),
            "breadth_hypothesis_minimum": _bounded_int(
                raw.get("breadth_hypothesis_minimum"), 1, 12, 1
            ),
            "breadth_hypothesis_maximum": _bounded_int(
                raw.get("breadth_hypothesis_maximum"), 1, 12, 12
            ),
            "s3_winning_thesis_capacity": _bounded_int(
                raw.get("s3_winning_thesis_capacity"),
                1 if dynamic_v2 else 0,
                8 if dynamic_v2 else 0,
                int(base["s3_winning_thesis_capacity"]),
            ),
            "s3_empty_reallocation_max": _bounded_int(
                raw.get("s3_empty_reallocation_max"),
                0,
                2,
                int(base["s3_empty_reallocation_max"]),
            ),
            "finalist_minimum": _bounded_int(
                raw.get("finalist_minimum"),
                1,
                7 if quality_cluster else 7,
                int(base["finalist_minimum"]),
            ),
            "finalist_maximum": _bounded_int(
                raw.get("finalist_maximum"),
                1,
                7 if quality_cluster else 7,
                7 if quality_cluster else 4,
            ),
            "minimum_direct_combat_equipment": _bounded_int(
                raw.get("minimum_direct_combat_equipment"),
                0,
                7 if quality_cluster else 7,
                int(base["minimum_direct_combat_equipment"]),
            ),
            "preferred_distinct_direct_equipment": _bounded_int(
                raw.get("preferred_distinct_direct_equipment"),
                0,
                7 if quality_cluster else 7,
                int(base["preferred_distinct_direct_equipment"]),
            ),
            "recursive_recruitment_allowed": False,
            "raw_session_sharing_allowed": False,
            "expert_judge_enabled": False if dynamic_v2 else bool(
                raw.get("expert_judge_enabled", quality_cluster)
            ),
            "expert_judge_required": False if dynamic_v2 else bool(
                raw.get("expert_judge_required", quality_cluster)
            ),
            "foresight_first_enabled": bool(
                raw.get("foresight_first_enabled", quality_cluster)
            ),
            "frontier_evidence_relaxation": bool(
                raw.get("frontier_evidence_relaxation", quality_cluster)
            ),
            "frontier_final_gate_minimum_score": _bounded_float(
                raw.get("frontier_final_gate_minimum_score"), 0.0, 1.0, 0.62
            ),
            "frontier_expert_judge_minimum_score": _bounded_float(
                raw.get("frontier_expert_judge_minimum_score"), 0.0, 1.0, 0.66
            ),
            "frontier_critical_dimension_minimum": _bounded_float(
                raw.get("frontier_critical_dimension_minimum"), 0.0, 1.0, 0.50
            ),
            "expert_candidate_pool_maximum": 0 if dynamic_v2 else _bounded_int(
                raw.get("expert_candidate_pool_maximum"),
                5,
                12,
                10 if quality_cluster else 8,
            ),
            "expert_judge_minimum_score": _bounded_float(
                raw.get("expert_judge_minimum_score"),
                0.0,
                1.0,
                0.68 if quality_cluster else 0.72,
            ),
            "expert_judge_critical_dimension_minimum": _bounded_float(
                raw.get("expert_judge_critical_dimension_minimum"),
                0.0,
                1.0,
                0.52 if quality_cluster else 0.60,
            ),
            "pending_verification_backfill_enabled": bool(
                raw.get("pending_verification_backfill_enabled", quality_cluster)
            ),
            "pending_verification_minimum_score": _bounded_float(
                raw.get("pending_verification_minimum_score"), 0.0, 1.0, 0.54
            ),
            "pending_verification_critical_dimension_minimum": _bounded_float(
                raw.get("pending_verification_critical_dimension_minimum"),
                0.0,
                1.0,
                0.42,
            ),
            "expert_repair_enabled": False if dynamic_v2 else bool(
                raw.get("expert_repair_enabled", quality_cluster)
            ),
            "expert_repair_max_candidates": 0 if dynamic_v2 else _bounded_int(
                raw.get("expert_repair_max_candidates"),
                0,
                6,
                int(base["expert_repair_max_candidates"]),
            ),
            "expert_repair_minimum_score": _bounded_float(
                raw.get("expert_repair_minimum_score"),
                0.0,
                1.0,
                0.64 if quality_cluster else 0.70,
            ),
            "expert_repair_reserved_instances": 0 if dynamic_v2 else _bounded_int(
                raw.get("expert_repair_reserved_instances"),
                0,
                6,
                int(base["expert_repair_reserved_instances"]),
            ),
            "same_family_minimum_independent_axes": _bounded_int(
                raw.get("same_family_minimum_independent_axes"), 1, 5, 2
            ),
        }
    )
    if base["breadth_hypothesis_minimum"] > base["breadth_hypothesis_maximum"]:
        base["breadth_hypothesis_minimum"] = base["breadth_hypothesis_maximum"]
    if base["finalist_minimum"] > base["finalist_maximum"]:
        base["finalist_minimum"] = base["finalist_maximum"]
    base["minimum_direct_combat_equipment"] = min(
        int(base["finalist_maximum"]),
        int(base["minimum_direct_combat_equipment"]),
    )
    base["preferred_distinct_direct_equipment"] = min(
        int(base["finalist_maximum"]),
        max(
            int(base["minimum_direct_combat_equipment"]),
            int(base["preferred_distinct_direct_equipment"]),
        ),
    )
    if base["mission_graph_min_instances"] > base["mission_graph_max_instances"]:
        base["mission_graph_min_instances"] = base["mission_graph_max_instances"]
    base["mission_graph_target_instances"] = max(
        int(base["mission_graph_min_instances"]),
        min(
            int(base["mission_graph_max_instances"]),
            int(base["mission_graph_target_instances"]),
        ),
    )
    requested_archetypes = _text_list(raw.get("archetypes", []), limit=16)
    allowed_archetypes = (
        _DYNAMIC_V2_ARCHETYPE_IDS if dynamic_v2 else SWARM_SPECIALIST_ARCHETYPES.keys()
    )
    base["archetypes"] = [
        item for item in requested_archetypes if item in allowed_archetypes
    ] or sorted(allowed_archetypes)
    promotion = dict(base["promotion"])
    if isinstance(raw.get("promotion"), Mapping):
        promotion.update(dict(raw["promotion"]))
    promotion.update(
        {
            "minimum_eligible_runs": max(
                10, _bounded_int(promotion.get("minimum_eligible_runs"), 1, 1000, 10)
            ),
            "minimum_positive_increment_rate": max(
                0.70,
                _bounded_float(
                    promotion.get("minimum_positive_increment_rate"), 0.0, 1.0, 0.70
                ),
            ),
            "maximum_evidence_hard_failures": 0,
            "maximum_permission_hard_failures": 0,
            "offline_evaluation_required": True,
            "human_approval_required": True,
        }
    )
    base["promotion"] = promotion
    return base


class WinningSwarmController:
    """Plan, gate and merge a bounded non-recursive specialist swarm."""

    def __init__(self, policy: Mapping[str, Any] | None = None) -> None:
        self.policy = normalize_winning_swarm_policy(policy)

    @property
    def enabled(self) -> bool:
        return bool(self.policy.get("enabled"))

    def plan_initial(self, *, topic: str, execution_profile_id: str) -> SwarmPlan:
        if not self.enabled:
            return SwarmPlan(
                plan_id=_stable_id("swarm-plan", execution_profile_id, topic),
                execution_profile_id=execution_profile_id,
                policy=dict(self.policy),
                tasks=[],
                waves=[],
                stop_reason="policy_disabled",
            )
        archetypes = [
            "frontier_equipment_miner",
            "weak_signal_scout",
            "disruptive_mechanism_generator",
        ]
        tasks = [
            self._task(
                archetype,
                wave=1,
                ordinal=index,
                expected_gain=0.08,
                topic=topic,
            )
            for index, archetype in enumerate(archetypes, start=1)
            if archetype in self.policy["archetypes"]
        ]
        tasks = tasks[: int(self.policy["max_dynamic_instances"])]
        return SwarmPlan(
            plan_id=_stable_id("swarm-plan", execution_profile_id, topic),
            execution_profile_id=execution_profile_id,
            policy=dict(self.policy),
            tasks=tasks,
            waves=[[task.task_id for task in tasks]] if tasks else [],
        )

    def govern_role_contract(
        self,
        value: Mapping[str, Any],
        *,
        mission_node: str,
        allowed_skill_ids: Sequence[str] = (
            "js-equipment-agent-runtime",
            "js-winning-shared-layer",
        ),
        allowed_tool_ids: Sequence[str] = (),
    ) -> WinningRoleContract:
        """Normalize an autonomously proposed role without expanding authority."""

        if mission_node not in MERGE_TARGETS:
            raise ValueError("dynamic role requires a valid S1-S6 merge target")
        if bool(value.get("allow_child_spawn")):
            raise ValueError("dynamic role contracts may not recruit child agents")
        archetype = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(value.get("archetype") or "dynamic_specialist").lower(),
        ).strip("_")[:80]
        if not archetype:
            raise ValueError("dynamic role requires an archetype")
        catalog = _all_role_archetypes()
        spec = catalog.get(archetype, {})
        display_name = str(
            value.get("display_name") or spec.get("display_name") or archetype
        ).strip()[:120]
        purpose = str(value.get("purpose") or spec.get("purpose") or "").strip()[:600]
        if not purpose:
            raise ValueError("dynamic role requires a bounded purpose")
        permitted_skills = set(str(item) for item in allowed_skill_ids)
        requested_skills = _text_list(
            value.get("skill_ids", allowed_skill_ids), limit=8
        )
        skill_ids = [item for item in requested_skills if item in permitted_skills]
        permitted_tools = set(str(item) for item in allowed_tool_ids)
        tool_ids = [
            item
            for item in _text_list(value.get("tool_ids", []), limit=12)
            if item in permitted_tools
        ]
        residuals = _text_list(
            value.get("trigger_residuals", spec.get("residuals", [])), limit=8
        )
        methodology = _text_list(
            value.get(
                "methodology",
                [
                    "只处理声明的质量残差",
                    "依据公开证据形成结构化增量",
                    "只写入声明的合并节点",
                ],
            ),
            limit=8,
        )
        quality_gates = _text_list(
            value.get(
                "quality_gates",
                [
                    "事实推断与假设分离",
                    "证据边界和失效条件明确",
                    "不得产生无依据精确判断",
                ],
            ),
            limit=10,
        )
        output_fields = _text_list(
            value.get(
                "output_fields",
                [
                    "findings",
                    "evidence_ids",
                    "evidence_boundary",
                    "failure_boundaries",
                    "incremental_quality",
                ],
            ),
            limit=12,
        )
        node_methods, node_gates, node_fields = _frontloaded_role_governance(
            mission_node
        )
        methodology = list(dict.fromkeys([*methodology, *node_methods]))
        quality_gates = list(dict.fromkeys([*quality_gates, *node_gates]))
        output_fields = list(dict.fromkeys([*output_fields, *node_fields]))
        contract_id = _stable_id(
            "role-contract", archetype, mission_node, purpose, "|".join(quality_gates)
        )
        return WinningRoleContract(
            role_contract_id=contract_id,
            archetype=archetype,
            display_name=display_name,
            purpose=purpose,
            mission_node=mission_node,
            merge_targets=[mission_node],
            trigger_residuals=residuals,
            methodology=methodology,
            quality_gates=quality_gates,
            output_fields=output_fields,
            skill_ids=skill_ids,
            tool_ids=tool_ids,
            max_instances=_bounded_int(value.get("max_instances"), 1, 2, 1),
            allow_child_spawn=False,
        )

    def build_mission_graph(
        self,
        *,
        topic: str,
        execution_profile_id: str = "winning_swarm_dynamic_v2",
        target_instances: int | None = None,
        query_theses: Sequence[Mapping[str, Any]] = (),
    ) -> WinningMissionGraph:
        """Build an 8-21 instance graph with parallel S3/S4 creators."""

        minimum = 8
        maximum = min(
            21,
            max(minimum, int(self.policy.get("mission_graph_max_instances", 21))),
        )
        target = _bounded_int(
            target_instances
            if target_instances is not None
            else self.policy.get("mission_graph_target_instances"),
            minimum,
            maximum,
            min(12, maximum),
        )
        # Blueprint equipment hypotheses are evidence-free reasoning inputs,
        # not S3 role identities.  Feeding them into role names and purposes
        # before S1/S2 free divergence anchors every producer to the
        # orchestrator's first familiar equipment catalogue.  Keep all S3
        # contracts open; the isolated pre-generation selector later reviews
        # blueprint theses together with fresh S1/S2 reasoning and may reject
        # or replace every one of them before any candidate is authored.
        del query_theses
        if self.policy.get("policy_id") == "winning_swarm_dynamic_v2":
            # ``target`` is a capacity decision, not a quota.  Keep two
            # independent S1 and S2 perspectives plus one incremental S5
            # portfolio role, and let the remaining capacity determine how many
            # isolated S3/S4 creators may be activated.  The later semantic
            # scout may use fewer slots when expected information gain is low.
            creative_capacity = min(8, max(3, target - 5))
            s3_capacity = (creative_capacity + 1) // 2
            s4_capacity = creative_capacity - s3_capacity
            selected = [
                ("S1", "opponent_system_modeler"),
                ("S2", "operational_baseline_analyst"),
                ("S1", "adversary_adaptation_analyst"),
                ("S2", "competitive_coa_designer"),
                *[
                    ("S3", "disruptive_mechanism_generator")
                    for _ in range(s3_capacity)
                ],
                *[
                    ("S4", "innovative_equipment_dimension_generator")
                    for _ in range(s4_capacity)
                ],
                ("S5", "independent_portfolio_reviewer"),
            ]
        else:
            selected = []
            for node in MISSION_GRAPH_SEED_ARCHETYPES:
                selected.append((node, MISSION_GRAPH_SEED_ARCHETYPES[node][0]))
            depth = 1
            while len(selected) < target:
                added = False
                for node, archetypes in MISSION_GRAPH_SEED_ARCHETYPES.items():
                    if depth < len(archetypes) and len(selected) < target:
                        selected.append((node, archetypes[depth]))
                        added = True
                if not added:
                    break
                depth += 1

        contracts: list[WinningRoleContract] = []
        instances: list[WinningAgentInstance] = []
        node_instances: dict[str, list[str]] = {f"S{step}": [] for step in range(1, 7)}
        for ordinal, (node, archetype) in enumerate(selected, start=1):
            spec = _all_role_archetypes()[archetype]
            dynamic_contract = execution_profile_id == "winning_swarm_dynamic_v2"
            query_first_clause = (
                f"当前唯一任务主题为“{topic}”。围绕当前Query自主判断；不要从固定装备类别或示例反推答案。"
                "最终装备应能直接承担打击、歼灭、毁伤、杀伤、压制、拦截或拒止任务。"
                if dynamic_contract
                else (
                    f"当前唯一任务主题为“{topic}”。先从完整Query提取任务对象、威胁形态、作战阶段、"
                    "地域环境、敌方反制和制胜矛盾，再执行本角色工作；不得先选择固定武器类别、公开"
                    "型号或共享示例后反向拼接Query。产出的候选若替换成其他Query仍基本成立，必须判为"
                    "模板化并重新发散。最终收敛对象必须是自身直接承担打击、歼灭、毁伤、杀伤、压制、"
                    "突防、物理拦截或拒止任务的具体新质军事战斗武器；通信、算法、网络与保障只能作为"
                    "内部接口或约束。具体命名由S3/S4 Codex会话基于完整装备语义整体创作。"
                )
            )
            contract = self.govern_role_contract(
                {
                    "archetype": archetype,
                    **spec,
                    "display_name": spec.get("display_name", ""),
                    "purpose": f"{spec.get('purpose', '')}{query_first_clause}",
                    "methodology": (
                        [
                            "从Query语义开放发散候选；保持轻型创造会话",
                            "执行跨Query替换自检，避免通用模板",
                            "只交接当前节点的最小语义",
                        ]
                        if dynamic_contract
                        else [
                            "先形成Query任务对象—威胁—阶段—制胜矛盾语义图",
                            "从Query语义开放发散候选，不从装备目录或公开型号起步",
                            "只处理声明的质量残差并写入声明节点",
                            "执行跨Query替换自检，淘汰换题后仍成立的模板候选",
                        ]
                    ),
                    "quality_gates": (
                        ["输出服务当前Query，保持主装备和直接战果可理解"]
                        if dynamic_contract
                        else [
                            "候选主装备、目标、发射域、毁伤机理与Query形成直接因果闭环",
                            "事实、推断与拟议假设分离，证据边界和失效条件明确",
                            "不得复用共享示例名称或以固定装备族覆盖主题",
                            "新研候选由Codex动态选择描述名、专名或可解释代号，不预设统一格式；名称须呈现具体主装备身份及其创新制胜特征",
                        ]
                    ),
                },
                mission_node=node,
            )
            contracts.append(contract)
            instance_id = _stable_id(
                "winning-agent",
                execution_profile_id,
                topic,
                node,
                archetype,
                str(ordinal),
            )
            node_instances[node].append(instance_id)
            instances.append(
                WinningAgentInstance(
                    instance_id=instance_id,
                    role_contract_id=contract.role_contract_id,
                    archetype=archetype,
                    display_name=contract.display_name,
                    mission_node=node,
                    wave=0,
                    merge_target=node,
                    trigger_residuals=list(contract.trigger_residuals),
                    expected_quality_gain=0.06,
                    allow_child_spawn=False,
                )
            )
        dependencies: dict[str, list[str]] = {}
        dependency_instances: list[WinningAgentInstance] = []
        node_ordinals: dict[str, int] = {f"S{step}": 0 for step in range(1, 7)}
        for instance in instances:
            step = int(instance.mission_node[1:])
            ordinal = node_ordinals[instance.mission_node]
            node_ordinals[instance.mission_node] += 1
            if step in {3, 4} and not instance.hypothesis_id:
                depends_on = [
                    node_instances[node][ordinal % len(node_instances[node])]
                    for node in ("S1", "S2")
                    if node_instances[node]
                ]
            elif step == 5 and instance.archetype == "evidence_verifier":
                # Legacy/restricted fallback only. Dynamic-v2 does not seed
                # this role into its normal successful production path.
                depends_on = [*node_instances["S3"], *node_instances["S4"]]
            elif step == 5 and instance.archetype == "validation_experiment_designer":
                depends_on = [
                    upstream[ordinal % len(upstream)]
                    for upstream in (node_instances["S3"], node_instances["S4"])
                    if upstream
                ]
            elif step == 5 and instance.archetype == "independent_portfolio_reviewer":
                # The runtime feeds this reviewer completed candidates
                # incrementally. Static producer dependencies would recreate
                # the same-wave barrier and let the slowest creator block S5.
                depends_on = []
            elif step == 5:
                upstream = node_instances["S4"]
                depends_on = [upstream[ordinal % len(upstream)]] if upstream else []
            elif step == 6 and instance.archetype == "validation_experiment_designer":
                depends_on = [
                    upstream[ordinal % len(upstream)]
                    for upstream in (node_instances["S3"], node_instances["S4"])
                    if upstream
                ]
            elif step == 6:
                validation_ids = [
                    item.instance_id
                    for item in instances
                    if item.mission_node == "S6"
                    and item.archetype == "validation_experiment_designer"
                ]
                depends_on = [
                    *node_instances["S4"],
                    *node_instances["S5"],
                    *validation_ids,
                ]
            else:
                depends_on = []
            dependencies[instance.instance_id] = depends_on
            dependency_instances.append(
                replace(
                    instance,
                    depends_on=depends_on,
                )
            )
        wave_by_instance: dict[str, int] = {}
        resolved_instances: list[WinningAgentInstance] = []
        for instance in dependency_instances:
            wave = 1 + max(
                (wave_by_instance.get(item, 0) for item in instance.depends_on),
                default=0,
            )
            wave_by_instance[instance.instance_id] = wave
            resolved_instances.append(replace(instance, wave=wave))
        maximum_wave = max(wave_by_instance.values(), default=0)
        waves = [
            [
                instance.instance_id
                for instance in resolved_instances
                if instance.wave == wave_index
            ]
            for wave_index in range(1, maximum_wave + 1)
        ]
        return WinningMissionGraph(
            graph_id=_stable_id("winning-mission-graph", execution_profile_id, topic),
            execution_profile_id=execution_profile_id,
            mission_objective=topic,
            role_contracts=contracts,
            agent_instances=resolved_instances,
            dependencies=dependencies,
            waves=waves,
            s_node_seeds=node_instances,
            minimum_instances=minimum,
            maximum_instances=maximum,
            maximum_concurrency=min(6, int(self.policy.get("max_concurrency", 6))),
            merge_strategy="artifact_ready_speculative_parallel_then_versioned_rebase",
        )

    def recruit_into_mission_graph(
        self,
        graph: WinningMissionGraph,
        contract: WinningRoleContract,
        *,
        hypothesis_id: str = "",
        expected_quality_gain: float = 0.03,
        depends_on: Sequence[str] | None = None,
    ) -> WinningMissionGraph:
        if contract.allow_child_spawn or contract.mission_node not in MERGE_TARGETS:
            raise ValueError("ungoverned role contract cannot enter mission graph")
        if len(graph.agent_instances) >= graph.maximum_instances:
            raise ValueError("mission graph instance budget exhausted")
        # ``expected_quality_gain`` is retained as planning metadata only.
        # A local numeric threshold cannot know whether an unusual military
        # idea is worth an independent Codex review, so it must not veto a
        # governed role before S5 sees the contribution.
        instance_id = _stable_id(
            "winning-agent",
            graph.graph_id,
            contract.role_contract_id,
            hypothesis_id,
            str(len(graph.agent_instances) + 1),
        )
        node = contract.mission_node
        dependency_nodes = (
            CORE_STEP_DEPENDENCIES.get(int(node[1:]), ())
            if node.startswith("S")
            else ()
        )
        resolved_dependencies = (
            list(dict.fromkeys(str(item) for item in depends_on if str(item)))
            if depends_on is not None
            else [
                item.instance_id
                for item in graph.agent_instances
                if item.mission_node in {f"S{step}" for step in dependency_nodes}
            ]
        )
        wave = max(
            (item.wave for item in graph.agent_instances if item.mission_node == node),
            default=len(graph.waves),
        )
        instance = WinningAgentInstance(
            instance_id=instance_id,
            role_contract_id=contract.role_contract_id,
            archetype=contract.archetype,
            display_name=contract.display_name,
            mission_node=node,
            wave=wave,
            merge_target=node,
            hypothesis_id=hypothesis_id,
            depends_on=resolved_dependencies,
            trigger_residuals=list(contract.trigger_residuals),
            expected_quality_gain=round(expected_quality_gain, 4),
        )
        waves = [list(row) for row in graph.waves]
        while len(waves) < wave:
            waves.append([])
        waves[wave - 1].append(instance_id)
        seeds = {key: list(value) for key, value in graph.s_node_seeds.items()}
        seeds.setdefault(node, []).append(instance_id)
        return replace(
            graph,
            role_contracts=[*graph.role_contracts, contract],
            agent_instances=[*graph.agent_instances, instance],
            dependencies={**graph.dependencies, instance_id: resolved_dependencies},
            waves=waves,
            s_node_seeds=seeds,
        )

    def create_ledger(
        self,
        hypotheses: Sequence[WinningHypothesis],
        *,
        created_by: str = "winning_swarm_controller",
    ) -> HypothesisLedgerVersion:
        ordered = sorted(hypotheses, key=lambda item: item.hypothesis_id)
        return HypothesisLedgerVersion(
            ledger_id=_stable_id(
                "hypothesis-ledger", *(item.hypothesis_id for item in ordered)
            ),
            version=1,
            hypotheses=ordered,
            change_summary="initial_candidate_ledger",
            created_by=created_by,
        )

    def merge_contribution(
        self,
        ledger: HypothesisLedgerVersion,
        contribution: WinningContribution,
    ) -> tuple[HypothesisLedgerVersion, MergeReceipt]:
        receipt_base = {
            "receipt_id": _stable_id(
                "merge-receipt", contribution.contribution_id, str(ledger.version)
            ),
            "contribution_id": contribution.contribution_id,
            "hypothesis_id": contribution.hypothesis_id,
            "merge_target": contribution.merge_target,
            "base_ledger_version": contribution.base_ledger_version,
        }
        if contribution.base_ledger_version != ledger.version:
            return ledger, MergeReceipt(
                **receipt_base,
                resulting_ledger_version=ledger.version,
                status="rebase_required",
                conflicts=["stale_ledger_version"],
                rebase_required=True,
            )
        hypothesis = next(
            (
                item
                for item in ledger.hypotheses
                if item.hypothesis_id == contribution.hypothesis_id
            ),
            None,
        )
        conflicts: list[str] = []
        if hypothesis is None:
            conflicts.append("missing_hypothesis")
        if contribution.merge_target not in MERGE_TARGETS:
            conflicts.append("invalid_merge_target")
        if not contribution.accepted:
            conflicts.append("contribution_not_accepted")
        if conflicts:
            return ledger, MergeReceipt(
                **receipt_base,
                resulting_ledger_version=ledger.version,
                status="rejected",
                conflicts=conflicts,
            )
        patch = contribution.hypothesis_patch
        specialist = SpecialistContribution(
            contribution_id=contribution.contribution_id,
            task_id=contribution.contribution_id,
            agent_instance_id=contribution.agent_instance_id,
            hypothesis_id=contribution.hypothesis_id,
            merge_target=contribution.merge_target,
            findings=_text_list(patch.get("findings", []), limit=8),
            mechanism_chain_updates=_user_facing_text_list(
                patch.get("mechanism_chain_updates", []), limit=8
            ),
            direct_military_effects=_user_facing_text_list(
                patch.get("direct_military_effects", []), limit=6
            ),
            equipment_forms=_user_facing_text_list(
                patch.get("equipment_forms", []), limit=6
            ),
            project_function=_user_facing_text(
                patch.get("project_function", ""), limit=700
            ),
            system_interfaces=_user_facing_text_list(
                patch.get("system_interfaces", []), limit=8
            ),
            novelty_delta=_user_facing_text(patch.get("novelty_delta", ""), limit=900),
            frontier_principle=_user_facing_text(
                patch.get("frontier_principle", ""), limit=320
            ),
            technology_discontinuity=_user_facing_text(
                patch.get("technology_discontinuity", ""), limit=420
            ),
            technology_horizon=_user_facing_text(
                patch.get("technology_horizon", ""), limit=120
            ),
            engineering_bottleneck=_user_facing_text(
                patch.get("engineering_bottleneck", ""), limit=360
            ),
            original_paradigm=_user_facing_text(
                patch.get("original_paradigm", ""), limit=900
            ),
            disruptive_shift=_user_facing_text(
                patch.get("disruptive_shift", ""), limit=900
            ),
            independence_thesis=_user_facing_text(
                patch.get("independence_thesis", ""), limit=900
            ),
            naming_rationale=_user_facing_text(
                patch.get("naming_rationale", ""), limit=900
            ),
            decisive_advantage_thesis=_user_facing_text(
                patch.get("decisive_advantage_thesis", ""), limit=900
            ),
            cross_query_distinction=_user_facing_text(
                patch.get("cross_query_distinction", ""), limit=900
            ),
            evidence_boundary=_user_facing_text(
                patch.get("evidence_boundary", ""), limit=800
            ),
            implementation_path=_user_facing_text(
                patch.get("implementation_path", ""), limit=800
            ),
            evidence_ids=list(contribution.evidence_ids),
            counterevidence=_user_facing_text_list(
                patch.get("counterevidence", []), limit=8
            ),
            adversary_adaptations=_user_facing_text_list(
                patch.get("adversary_adaptations", []), limit=8
            ),
            failure_boundaries=_user_facing_text_list(
                patch.get("failure_boundaries", []), limit=8
            ),
            trl_constraints=_user_facing_text_list(
                patch.get("trl_constraints", []), limit=6
            ),
            cost_constraints=_user_facing_text_list(
                patch.get("cost_constraints", []), limit=6
            ),
            industrial_constraints=_user_facing_text_list(
                patch.get("industrial_constraints", []), limit=6
            ),
            cross_scenario_results=_user_facing_text_list(
                patch.get("cross_scenario_results", []), limit=8
            ),
            validation_plan=_user_facing_text_list(
                patch.get("validation_plan", []), limit=8
            ),
            residuals_resolved=list(contribution.residuals_resolved),
            incremental_quality=contribution.incremental_quality,
            recommendation=contribution.recommendation,
            accepted=True,
        )
        updated = self.apply_contribution(hypothesis, specialist)
        # Expert repair must be able to *remove* an unsupported claim.  The
        # normal specialist path is intentionally additive, but an additive
        # evidence-verification pass cannot repair a candidate whose original
        # equipment form or mechanism is itself too speculative.  Keep the
        # replacement surface narrow, explicit and exclusive to governed
        # expert-repair contributions.
        if (
            contribution.contribution_id.startswith("winning-expert-repair-")
            and str(patch.get("patch_mode", "")) == "replace_bounded_claims"
        ):
            requested = set(_text_list(patch.get("replace_fields", []), limit=16))
            list_limits = {
                "mechanism_chain": 10,
                "direct_military_effects": 8,
                "equipment_forms": 8,
                "system_interfaces": 10,
                "counterevidence": 12,
                "adversary_adaptations": 12,
                "failure_boundaries": 12,
                "trl_constraints": 10,
                "cost_constraints": 10,
                "industrial_constraints": 10,
                "cross_scenario_results": 12,
                "validation_plan": 12,
                "evidence_ids": 24,
            }
            string_limits = {
                "title": 240,
                "nearest_public_baseline": 1200,
                "changed_confrontation_variable": 1000,
                "project_function": 700,
                "novelty_delta": 900,
                "original_paradigm": 900,
                "disruptive_shift": 900,
                "independence_thesis": 900,
                "naming_rationale": 900,
                "decisive_advantage_thesis": 900,
                "cross_query_distinction": 900,
                "evidence_boundary": 800,
                "implementation_path": 800,
            }
            replacement_fields: dict[str, Any] = {}
            for name, limit in list_limits.items():
                if name in requested and name in patch:
                    replacement_fields[name] = _text_list(
                        patch.get(name, []), limit=limit
                    )
            for name, limit in string_limits.items():
                if name in requested and name in patch:
                    replacement_fields[name] = str(patch.get(name, "")).strip()[:limit]
            if "title" in replacement_fields:
                replacement_fields["title"] = normalize_weapon_candidate_title(
                    replacement_fields["title"],
                    replacement_fields.get("equipment_forms", updated.equipment_forms),
                )
            if replacement_fields:
                updated = replace(updated, **replacement_fields)
                gate = self.evaluate_gate(updated, stage="targeted")
                updated = replace(updated, residuals=gate.residuals, score=gate.score)
        next_version = ledger.version + 1
        receipt = MergeReceipt(
            **receipt_base,
            resulting_ledger_version=next_version,
            status="merged",
            changed_fields=sorted(str(key) for key in patch),
            quality_delta=round(contribution.incremental_quality, 4),
        )
        hypotheses = [
            updated if item.hypothesis_id == updated.hypothesis_id else item
            for item in ledger.hypotheses
        ]
        return HypothesisLedgerVersion(
            ledger_id=ledger.ledger_id,
            version=next_version,
            parent_version=ledger.version,
            hypotheses=hypotheses,
            merge_receipts=[*ledger.merge_receipts, receipt],
            change_summary=f"merged:{contribution.contribution_id}",
            created_by=contribution.agent_instance_id,
        ), receipt

    @staticmethod
    def rebase_contribution(
        contribution: WinningContribution,
        ledger: HypothesisLedgerVersion,
    ) -> WinningContribution:
        if not any(
            item.hypothesis_id == contribution.hypothesis_id
            for item in ledger.hypotheses
        ):
            raise ValueError("cannot rebase contribution onto a missing hypothesis")
        return replace(
            contribution,
            base_ledger_version=ledger.version,
            rebase_count=contribution.rebase_count + 1,
        )

    def portfolio_decision(
        self,
        ledger: HypothesisLedgerVersion,
        *,
        objective_scores: Mapping[str, Mapping[str, float]] | None = None,
        expert_assessments: Mapping[str, WinningExpertAssessment] | None = None,
    ) -> PortfolioDecision:
        scores: dict[str, dict[str, float]] = {}
        final_gates: dict[str, SwarmGateResult] = {}
        for hypothesis in ledger.hypotheses:
            supplied = dict((objective_scores or {}).get(hypothesis.hypothesis_id, {}))
            gate = self.evaluate_gate(hypothesis, stage="final")
            final_gates[hypothesis.hypothesis_id] = gate
            scores[hypothesis.hypothesis_id] = supplied or {
                "quality": gate.score,
                "evidence": min(1.0, len(hypothesis.evidence_ids) / 3),
                # Without an independent expert score, novelty cannot be
                # inferred from prose presence alone. Reuse the complete
                # semantic gate score only after the discontinuity contract
                # has passed.
                "novelty": gate.score if gate.passed else 0.0,
                "robustness": min(
                    1.0,
                    (
                        len(hypothesis.adversary_adaptations)
                        + len(hypothesis.cross_scenario_results)
                    )
                    / 4,
                ),
                "feasibility": 1.0
                if hypothesis.trl_constraints
                and hypothesis.cost_constraints
                and hypothesis.industrial_constraints
                else 0.0,
            }
        hypothesis_ids = [item.hypothesis_id for item in ledger.hypotheses]
        hypothesis_by_id = {item.hypothesis_id: item for item in ledger.hypotheses}
        strictly_passed_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if final_gates[item.hypothesis_id].passed
            and (
                not self.policy.get("expert_judge_required")
                or expert_assessments is None
                or (
                    item.hypothesis_id in (expert_assessments or {})
                    and (expert_assessments or {})[item.hypothesis_id].passed
                )
            )
        ]
        pending_verification_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if item.hypothesis_id not in strictly_passed_ids
            and final_gates[item.hypothesis_id].passed
            and self.assessment_allows_pending_verification(
                item,
                (expert_assessments or {}).get(item.hypothesis_id),
            )
        ]
        candidate_ids = list(
            dict.fromkeys([*strictly_passed_ids, *pending_verification_ids])
        )

        def dominates(left: str, right: str) -> bool:
            dimensions = set(scores[left]) | set(scores[right])
            left_values = [float(scores[left].get(key, 0.0)) for key in dimensions]
            right_values = [float(scores[right].get(key, 0.0)) for key in dimensions]
            return all(a >= b for a, b in zip(left_values, right_values)) and any(
                a > b for a, b in zip(left_values, right_values)
            )

        front = [
            candidate
            for candidate in candidate_ids
            if not any(
                other != candidate and dominates(other, candidate)
                for other in candidate_ids
            )
        ]
        front = _diverse_portfolio_order(
            front,
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
        )
        maximum = int(self.policy.get("finalist_maximum", 4))
        # Pareto ranking is a prioritisation signal, not a licence to discard
        # a separately evidenced and independently useful weapon direction.
        # Retain the complete passing pool (within the audited S6 capacity),
        # then use the front to order it.  This is what allows a query with
        # seven or more reliable new weapon concepts to reach S6 intact.
        selected = _diverse_portfolio_order(
            [*front, *[item for item in candidate_ids if item not in front]],
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
        )[:maximum]
        # Candidate identity and independence have already been decided by
        # the isolated five-axis Codex clustering pass.  A local equipment
        # family label must not replace a passed same-family weapon merely to
        # make the portfolio look broader.
        direct_pool = _diverse_portfolio_order(
            [
                item
                for item in candidate_ids
                if _is_direct_combat_equipment(
                    hypothesis_by_id[item],
                    (expert_assessments or {}).get(item),
                )
            ],
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
        )
        # When the assessed pool already contains enough direct combat
        # weapons to fill the available S6 card capacity, keep the portfolio
        # focused on those effects instead of letting a high-scoring support
        # link displace a weapon card. Support still remains in the ledger as
        # a cross-card constraint and can be selected when the query calls for
        # it or the direct pool is smaller than capacity.
        if len(direct_pool) >= maximum:
            selected = list(direct_pool[:maximum])
        selected = _diverse_portfolio_order(
            selected,
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
        )[:maximum]
        rejected = [item for item in hypothesis_ids if item not in selected]
        reasons = {
            item: [
                other
                for other in hypothesis_ids
                if other != item and dominates(other, item)
            ]
            for item in rejected
        }
        return PortfolioDecision(
            decision_id=_stable_id(
                "portfolio-decision", ledger.ledger_id, str(ledger.version), *selected
            ),
            ledger_id=ledger.ledger_id,
            ledger_version=ledger.version,
            pareto_front=front,
            selected_hypothesis_ids=selected,
            rejected_hypothesis_ids=rejected,
            objective_scores=scores,
            dominance_reasons=reasons,
            expert_assessment_ids=[
                (expert_assessments or {})[item].assessment_id
                for item in selected
                if item in (expert_assessments or {})
            ],
            quality_judge_passed=(
                expert_assessments is not None
                and bool(selected)
                and all(
                    item in (expert_assessments or {})
                    and (
                        (expert_assessments or {})[item].passed
                        or self.assessment_allows_pending_verification(
                            hypothesis_by_id[item],
                            (expert_assessments or {})[item],
                        )
                    )
                    for item in selected
                )
            ),
        )

    def assessment_allows_pending_verification(
        self,
        hypothesis: WinningHypothesis,
        assessment: WinningExpertAssessment | None,
    ) -> bool:
        """Honor an S5 semantic ``revise`` verdict without numeric cutoffs.

        ``revise`` means the model found a potentially useful candidate whose
        uncertainty must stay visible.  It must not be converted into reject by
        local weighted-score, field-presence, suffix, or equipment-family rules.
        """

        del hypothesis
        return bool(
            self.policy.get("pending_verification_backfill_enabled")
            and assessment is not None
            and assessment.verdict == "revise"
        )

    @staticmethod
    def equipment_family_signature(hypothesis: WinningHypothesis) -> str:
        """Compatibility alias for an exact five-axis semantic identity.

        Equipment-family classification is a model judgement.  This local
        controller deliberately exposes only an opaque exact-identity key and
        never infers a family from model names or Chinese vocabulary.
        """

        return _semantic_identity_signature(hypothesis)

    @staticmethod
    def equipment_family_counts(
        hypotheses: Sequence[WinningHypothesis],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in hypotheses:
            signature = _semantic_identity_signature(item)
            counts[signature] = counts.get(signature, 0) + 1
        return counts

    def passed_portfolio_coverage(
        self,
        ledger: HypothesisLedgerVersion,
        expert_assessments: Mapping[str, WinningExpertAssessment],
    ) -> dict[str, Any]:
        """Report S5 semantic-review coverage without enforcing quotas."""

        passed = [
            item
            for item in ledger.hypotheses
            if item.hypothesis_id in expert_assessments
            and expert_assessments[item.hypothesis_id].passed
        ]
        direct = [
            item
            for item in passed
            if _is_direct_combat_equipment(
                item,
                expert_assessments.get(item.hypothesis_id),
            )
        ]
        direct_identity_counts = self.equipment_family_counts(direct)
        revisable = [
            item
            for item in ledger.hypotheses
            if item.hypothesis_id in expert_assessments
            and expert_assessments[item.hypothesis_id].verdict == "revise"
        ]
        passed_count = len(passed)
        direct_count = len(direct)
        distinct_direct_identity_count = len(direct_identity_counts)
        assessed_count = sum(
            item.hypothesis_id in expert_assessments for item in ledger.hypotheses
        )
        # The five-axis Codex clustering pass is the authority for semantic
        # independence.  Compatibility counters expose opaque identities,
        # never inferred equipment families, and never block readiness.
        independence_conflicts: list[dict[str, Any]] = []
        return {
            "ready": bool(passed or revisable)
            and assessed_count >= len(ledger.hypotheses),
            "assessed_count": assessed_count,
            "passed_count": passed_count,
            "revise_count": len(revisable),
            "direct_combat_equipment_count": direct_count,
            # Retain the legacy keys for API compatibility.  Their values now
            # describe model-governed five-axis identities, not lexical
            # equipment families.
            "distinct_direct_equipment_family_count": distinct_direct_identity_count,
            "direct_equipment_family_counts": direct_identity_counts,
            "distinct_direct_semantic_identity_count": distinct_direct_identity_count,
            "direct_semantic_identity_counts": direct_identity_counts,
            "finalist_minimum": 0,
            "minimum_direct_combat_equipment": 0,
            "preferred_distinct_direct_equipment": 0,
            "same_family_independence_conflicts": independence_conflicts,
            "family_breadth_is_preference": False,
            "semantic_independence_authority": (
                "independent_codex_five_axis_clustering"
            ),
        }

    def select_unassessed_portfolio_candidates(
        self,
        ledger: HypothesisLedgerVersion,
        expert_assessments: Mapping[str, WinningExpertAssessment],
        *,
        maximum: int | None = None,
    ) -> list[str]:
        """Select the next unassessed ledger rows for S5 semantic review."""

        limit = max(
            0,
            int(
                maximum
                if maximum is not None
                else self.policy.get("expert_candidate_pool_maximum", 8)
            ),
        )
        if not limit:
            return []
        assessed_ids = set(expert_assessments)
        candidate_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if item.hypothesis_id not in assessed_ids
        ]
        # Preserve ledger order.  The next S5 Codex call, not a local score or
        # inferred equipment family, decides which candidates are valuable.
        return candidate_ids[:limit]

    def expert_assessment_from_mapping(
        self,
        value: Mapping[str, Any],
        *,
        hypothesis: WinningHypothesis,
        blind_label: str,
        valid_evidence_ids: set[str],
        session_ref: str,
    ) -> WinningExpertAssessment:
        """Validate and normalize one independent expert judgement."""

        dimension_names = (
            "domain_relevance",
            "equipment_capability_fit",
            "innovation",
            "military_value",
            "decisive_advantage",
            "query_specificity",
            "causal_coherence",
            "credibility",
            "engineering_feasibility",
            "robustness",
        )
        raw_scores = value.get("dimension_scores", {})
        raw_scores = raw_scores if isinstance(raw_scores, Mapping) else {}
        scores: dict[str, float] = {}
        for name in dimension_names:
            try:
                score = float(raw_scores.get(name, 0.0))
            except (TypeError, ValueError):
                score = 0.0
            scores[name] = round(max(0.0, min(1.0, score)), 4)
        weights = {
            "domain_relevance": 0.08,
            "equipment_capability_fit": 0.12,
            "innovation": 0.20,
            "military_value": 0.20,
            "decisive_advantage": 0.16,
            "query_specificity": 0.12,
            "causal_coherence": 0.08,
            # Evidence remains visible in the assessment and routes S5
            # verification, but it must not drown out a high-value frontier
            # concept before its public trail is mature.
            "credibility": 0.02,
            "engineering_feasibility": 0.01,
            "robustness": 0.01,
        }
        weighted_score = round(
            sum(scores[name] * weights[name] for name in dimension_names), 4
        )
        verdict = str(value.get("verdict", "revise")).strip().lower()
        if verdict not in {"pass", "revise", "reject"}:
            verdict = "revise"
        # The independent Codex verdict is the semantic decision. Numeric
        # dimensions remain useful diagnostics, but must not mechanically
        # overturn the model judgement because one rubric cell fell below a
        # fixed threshold.
        passed = verdict == "pass"
        model_residuals = _text_list(value.get("residuals", []), limit=10)
        rejection_reasons = _text_list(value.get("rejection_reasons", []), limit=8)
        if not passed and not rejection_reasons:
            rejection_reasons = ["独立Codex语义评审建议继续修改或暂不入选"]
        evidence_ids = self.sanitize_evidence_ids(
            value.get("evidence_ids", []), valid_evidence_ids
        )
        return WinningExpertAssessment(
            assessment_id=_stable_id(
                "winning-expert-assessment",
                hypothesis.hypothesis_id,
                session_ref,
            ),
            hypothesis_id=hypothesis.hypothesis_id,
            blind_label=blind_label,
            verdict=verdict,
            passed=passed,
            weighted_score=weighted_score,
            dimension_scores=scores,
            strengths=_text_list(value.get("strengths", []), limit=8),
            weaknesses=_text_list(value.get("weaknesses", []), limit=8),
            rejection_reasons=rejection_reasons,
            residuals=model_residuals,
            equipment_classification=str(
                value.get("equipment_classification", "")
            ).strip()[:120],
            innovation_type=str(value.get("innovation_type", "")).strip()[:120],
            confidence=_bounded_float(value.get("confidence"), 0.0, 1.0, 0.0),
            evidence_ids=evidence_ids,
            session_ref=session_ref,
        )

    @staticmethod
    def expert_objective_scores(
        assessment: WinningExpertAssessment,
    ) -> dict[str, float]:
        scores = assessment.dimension_scores
        return {
            "quality": assessment.weighted_score,
            "evidence": scores.get("credibility", 0.0),
            "novelty": scores.get("innovation", 0.0),
            "robustness": scores.get("robustness", 0.0),
            "feasibility": scores.get("engineering_feasibility", 0.0),
            "military_value": scores.get("military_value", 0.0),
            "equipment_fit": scores.get("equipment_capability_fit", 0.0),
            "causal_coherence": scores.get("causal_coherence", 0.0),
        }

    @staticmethod
    def repair_archetype_for_assessment(
        assessment: WinningExpertAssessment,
    ) -> str:
        """Route an expert residual to the narrowest governed repair role."""

        scores = assessment.dimension_scores
        if scores.get(
            "equipment_capability_fit", 0.0
        ) < 0.82 or assessment.equipment_classification in {
            "system_link",
            "support",
            "non_materiel",
        }:
            return "equipment_capability_image_repairer"
        evidence_hardening_terms = (
            "公开证据",
            "缺少直接证据",
            "未经证明",
            "实弹",
            "鉴定",
            "全寿命成本",
            "产线",
            "良率",
        )
        residual_text = " ".join(
            [
                *assessment.residuals,
                *assessment.rejection_reasons,
                *assessment.weaknesses,
            ]
        )
        if (
            assessment.equipment_classification
            in {"direct_combat", "unmanned_combat", "upgrade"}
            and scores.get("credibility", 0.0) < 0.70
            and any(term in residual_text for term in evidence_hardening_terms)
        ):
            return "equipment_capability_image_repairer"
        if scores.get("credibility", 0.0) < 0.70:
            return "evidence_verifier"
        if scores.get("engineering_feasibility", 0.0) < 0.68:
            return "trl_cost_industrial_auditor"
        if (
            scores.get("innovation", 0.0) < 0.72
            or scores.get("causal_coherence", 0.0) < 0.72
        ):
            return "disruptive_mechanism_generator"
        if scores.get("robustness", 0.0) < 0.72:
            return "adversary_counter_adaptation_red_team"
        return "baseline_delta_analyst"

    @staticmethod
    def retain_diverse_candidates(
        hypotheses: Sequence[WinningHypothesis],
        *,
        maximum: int = 8,
        priority_source_groups: Sequence[set[str]] = (),
        quota_per_priority_group: int = 2,
    ) -> list[WinningHypothesis]:
        """Retain bounded candidates without starving specialist equipment lanes.

        Dynamic branches often have identical deterministic gate scores.  A
        plain score/id slice can therefore discard both outputs of a dedicated
        remote-munition or scalable-equipment role while retaining generic S1
        and S2 branches.  Reserve a small quota for each declared specialist
        source group, then fill the remaining slots by score.
        """

        limit = max(0, int(maximum))
        if not limit:
            return []
        ranked = sorted(
            hypotheses,
            key=lambda item: (-item.score, item.hypothesis_id),
        )
        selected: list[WinningHypothesis] = []
        selected_ids: set[str] = set()
        for source_group in priority_source_groups:
            if len(selected) >= limit:
                break
            group_rows = [
                item
                for item in ranked
                if item.hypothesis_id not in selected_ids
                and set(item.source_task_ids) & set(source_group)
            ]
            for item in group_rows[: max(0, int(quota_per_priority_group))]:
                selected.append(item)
                selected_ids.add(item.hypothesis_id)
                if len(selected) >= limit:
                    break
        for item in ranked:
            if len(selected) >= limit:
                break
            if item.hypothesis_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item.hypothesis_id)
        return selected

    def core_execution_waves(
        self,
        active_steps: Sequence[int],
        *,
        dependency_map: Mapping[int, Sequence[int]] | None = None,
    ) -> list[tuple[int, ...]]:
        """Return dependency-safe logical S1-S6 waves for the active branch.

        Skipped or reused nodes are treated as already satisfied. Independent
        nodes share a wave; every downstream node starts only after all of its
        declared inputs have been committed.
        """

        dependencies = {
            step: tuple(
                int(item)
                for item in (dependency_map or CORE_STEP_DEPENDENCIES).get(step, ())
                if int(item) in CORE_STEP_DEPENDENCIES
            )
            for step in CORE_STEP_DEPENDENCIES
        }
        selected = {
            int(step)
            for step in active_steps
            if str(step).isdigit() and int(step) in CORE_STEP_DEPENDENCIES
        }
        pending = set(selected)
        satisfied = set(dependencies) - selected
        waves: list[tuple[int, ...]] = []
        while pending:
            ready = tuple(
                step
                for step in sorted(pending)
                if all(dependency in satisfied for dependency in dependencies[step])
            )
            if not ready:
                raise ValueError("S1-S6 dependency graph cannot be scheduled")
            waves.append(ready)
            pending.difference_update(ready)
            satisfied.update(ready)
        return waves

    @staticmethod
    def core_dependencies_from_dag(
        logical_agent_dag: Mapping[str, Sequence[str]] | None,
    ) -> dict[int, tuple[int, ...]]:
        """Project a branch contract DAG onto the S1-S6 logical nodes."""

        dependencies = dict(CORE_STEP_DEPENDENCIES)
        if not isinstance(logical_agent_dag, Mapping):
            return dependencies
        for step in CORE_STEP_DEPENDENCIES:
            node = f"S{step}"
            if node not in logical_agent_dag:
                continue
            raw_dependencies = logical_agent_dag.get(node, ())
            if not isinstance(raw_dependencies, Sequence) or isinstance(
                raw_dependencies,
                (str, bytes),
            ):
                continue
            projected: list[int] = []
            for item in raw_dependencies:
                match = re.fullmatch(r"S([1-6])", str(item).strip(), re.IGNORECASE)
                if match:
                    projected.append(int(match.group(1)))
            dependencies[step] = tuple(dict.fromkeys(projected))
        return dependencies

    def plan_core_schedule(
        self,
        *,
        active_steps: Sequence[int],
        step_modes: Mapping[int, str] | None = None,
        physical_cohorts: Sequence[Sequence[int]] = (),
        dependency_map: Mapping[int, Sequence[int]] | None = None,
    ) -> dict[str, Any]:
        """Build an auditable logical/physical schedule for the six core Agents."""

        modes = {
            step: str((step_modes or {}).get(step, "standard"))
            for step in CORE_STEP_DEPENDENCIES
        }
        dependencies = {
            step: tuple(
                int(item)
                for item in (dependency_map or CORE_STEP_DEPENDENCIES).get(step, ())
                if int(item) in CORE_STEP_DEPENDENCIES
            )
            for step in CORE_STEP_DEPENDENCIES
        }
        waves = self.core_execution_waves(
            active_steps,
            dependency_map=dependencies,
        )
        active = {step for wave in waves for step in wave}
        normalized_cohorts = [
            [f"S{int(step)}" for step in cohort if int(step) in active]
            for cohort in physical_cohorts
            if cohort
        ]
        normalized_cohorts = [row for row in normalized_cohorts if row]
        return {
            "dependencies": {
                f"S{step}": [f"S{dependency}" for dependency in dependencies]
                for step, dependencies in dependencies.items()
            },
            "active_steps": [f"S{step}" for step in sorted(active)],
            "skipped_or_reused_steps": [
                f"S{step}" for step in CORE_STEP_DEPENDENCIES if step not in active
            ],
            "step_modes": {f"S{step}": mode for step, mode in modes.items()},
            "logical_waves": [
                {
                    "wave": index,
                    "core_agents": [f"S{step}" for step in wave],
                    "parallel": len(wave) > 1,
                }
                for index, wave in enumerate(waves, start=1)
            ],
            "physical_cohorts": normalized_cohorts,
            "maximum_parallel_core_agents": max(
                (len(wave) for wave in waves),
                default=0,
            ),
            "merge_strategy": "isolated_result_then_topological_commit",
            "conflict_policy": (
                "one core writer per S node; dynamic writes require exact "
                "hypothesis_id + merge_target"
            ),
            "status": "planned",
        }

    def conflict_free_batches(
        self,
        tasks: Sequence[SpecialistTask],
    ) -> list[list[SpecialistTask]]:
        """Partition ready specialists into bounded, non-conflicting batches.

        Two tasks that update the same candidate and merge target never execute
        concurrently. Tasks that create independent candidates use their task
        ID as the isolation key and may run in parallel.
        """

        maximum = max(1, int(self.policy["max_concurrency"]))
        remaining = list(tasks)
        batches: list[list[SpecialistTask]] = []
        while remaining:
            batch: list[SpecialistTask] = []
            deferred: list[SpecialistTask] = []
            conflict_keys: set[tuple[str, str]] = set()
            for task in remaining:
                owner = task.hypothesis_id or task.task_id
                conflict_key = (owner, task.merge_target)
                if len(batch) >= maximum or conflict_key in conflict_keys:
                    deferred.append(task)
                    continue
                batch.append(task)
                conflict_keys.add(conflict_key)
            batches.append(batch)
            remaining = deferred
        return batches

    def plan_targeted(
        self,
        hypotheses: Sequence[WinningHypothesis],
        gates: Sequence[SwarmGateResult],
        *,
        topic: str,
        used_instances: int,
    ) -> list[SpecialistTask]:
        remaining = max(0, int(self.policy["max_dynamic_instances"]) - used_instances)
        if remaining == 0 or int(self.policy["max_waves"]) < 2:
            return []
        gates_by_id = {item.hypothesis_id: item for item in gates}
        candidates = sorted(
            hypotheses, key=lambda item: (-item.score, item.hypothesis_id)
        )
        tasks: list[SpecialistTask] = []
        seen_pairs: set[tuple[str, str]] = set()
        for hypothesis in candidates:
            gate = gates_by_id.get(hypothesis.hypothesis_id)
            residuals = list(gate.residuals if gate else hypothesis.residuals)
            for residual in residuals:
                archetype = self.archetype_for_residual(residual)
                pair = (hypothesis.hypothesis_id, archetype)
                if archetype not in self.policy["archetypes"] or pair in seen_pairs:
                    continue
                task = self._task(
                    archetype,
                    wave=2,
                    ordinal=len(tasks) + 1,
                    expected_gain=max(0.03, 0.07 - 0.01 * len(tasks)),
                    topic=topic,
                    hypothesis=hypothesis,
                    trigger_residuals=[residual],
                )
                tasks.append(task)
                seen_pairs.add(pair)
                break
            if len(tasks) >= min(4, remaining):
                break
        return tasks

    def plan_convergence(
        self,
        finalists: Sequence[WinningHypothesis],
        *,
        topic: str,
        used_instances: int,
    ) -> list[SpecialistTask]:
        remaining = max(0, int(self.policy["max_dynamic_instances"]) - used_instances)
        if remaining == 0 or int(self.policy["max_waves"]) < 3:
            return []
        tasks: list[SpecialistTask] = []
        for hypothesis in finalists[:remaining]:
            tasks.append(
                self._task(
                    "independent_portfolio_reviewer",
                    wave=3,
                    ordinal=len(tasks) + 1,
                    expected_gain=0.04,
                    topic=topic,
                    hypothesis=hypothesis,
                    trigger_residuals=list(hypothesis.residuals),
                )
            )
        return tasks

    def _task(
        self,
        archetype: str,
        *,
        wave: int,
        ordinal: int,
        expected_gain: float,
        topic: str,
        hypothesis: WinningHypothesis | None = None,
        trigger_residuals: Sequence[str] = (),
    ) -> SpecialistTask:
        spec = SWARM_SPECIALIST_ARCHETYPES[archetype]
        hypothesis_id = hypothesis.hypothesis_id if hypothesis else ""
        task_id = _stable_id(
            "specialist-task",
            str(wave),
            archetype,
            hypothesis_id,
            topic,
            str(ordinal),
        )
        return SpecialistTask(
            task_id=task_id,
            agent_instance_id=task_id.replace("specialist-task", "specialist", 1),
            archetype=archetype,
            display_name=str(spec["display_name"]),
            wave=wave,
            purpose=str(spec["purpose"]),
            merge_target=str(spec["merge_target"]),
            hypothesis_id=hypothesis_id,
            trigger_residuals=_text_list(trigger_residuals, limit=8),
            depends_on=list(hypothesis.source_task_ids[-2:]) if hypothesis else [],
            expected_quality_gain=round(expected_gain, 4),
            max_output_tokens=2000 if wave == 1 else 1600,
            allow_child_spawn=False,
        )

    @staticmethod
    def archetype_for_residual(residual: str) -> str:
        priority = {
            "evidence_insufficient": "evidence_verifier",
            "unsupported_precision": "evidence_verifier",
            "baseline_missing": "baseline_delta_analyst",
            "novelty_insufficient": "baseline_delta_analyst",
            "paradigm_shift_unproven": "disruptive_mechanism_generator",
            "frontier_discontinuity_unproven": "disruptive_mechanism_generator",
            "causal_chain_broken": "adversary_counter_adaptation_red_team",
            "military_effect_missing": "disruptive_mechanism_generator",
            "equipment_not_concrete": "equipment_realization_architect",
            "weapon_name_not_concrete": "equipment_realization_architect",
            "system_interfaces_missing": "equipment_realization_architect",
            "engineering_feasibility_insufficient": "trl_cost_industrial_auditor",
            "counter_adaptation_unresolved": "adversary_counter_adaptation_red_team",
            "cross_scenario_unstable": "cross_scenario_stress_tester",
            "validation_route_missing": "validation_experiment_designer",
        }
        # Model-authored quality notes may contain prose such as
        # ``causal_chain_broken已补强``.  They are useful audit commentary but
        # are not unresolved residual codes.  Falling back to an evidence
        # verifier turned every unknown/narrative note into a post-hoc repair
        # session, defeating front-loaded S3 thesis competition.  Recruit only
        # for an exact governed residual; unknown text remains on the ledger.
        return priority.get(str(residual).strip(), "")

    @staticmethod
    def ready_tasks(
        tasks: Sequence[SpecialistTask],
        *,
        completed_task_ids: set[str],
        failed_task_ids: set[str] | None = None,
    ) -> tuple[list[SpecialistTask], list[SpecialistTask]]:
        failed = failed_task_ids or set()
        ready: list[SpecialistTask] = []
        pruned: list[SpecialistTask] = []
        for task in tasks:
            if task.allow_child_spawn:
                pruned.append(task)
            elif any(dependency in failed for dependency in task.depends_on):
                pruned.append(task)
            elif all(
                dependency in completed_task_ids for dependency in task.depends_on
            ):
                ready.append(task)
        return ready, pruned

    def hypothesis_from_mapping(
        self,
        value: Mapping[str, Any],
        *,
        task: SpecialistTask,
        valid_evidence_ids: set[str],
        ordinal: int,
    ) -> WinningHypothesis:
        evidence_ids = self.sanitize_evidence_ids(
            value.get("evidence_ids", value.get("evidence_refs", [])),
            valid_evidence_ids,
        )
        changed_variable = _user_facing_text(
            value.get("changed_confrontation_variable")
            or value.get("changed_variable")
            or "",
            limit=600,
        )
        mechanism_chain = _user_facing_text_list(
            value.get("mechanism_chain", value.get("winning_mechanism_chain", [])),
            limit=8,
        )
        direct_effects = _user_facing_text_list(
            value.get(
                "direct_military_effects", value.get("direct_military_effect", [])
            ),
            limit=6,
        )
        equipment_forms = _user_facing_text_list(
            value.get("equipment_forms", value.get("equipment_form", [])),
            limit=6,
        )
        # Candidate titles are a delivery surface, not an internal reasoning
        # label. Normalize them before they enter the ledger so the same
        # concrete weapon identity flows to reference cards, portfolio review
        # and S6 instead of leaking S3/S4 labels or a mechanism sentence.
        title = normalize_weapon_candidate_title(
            value.get("title") or value.get("name"),
            equipment_forms,
        )
        project_function = _user_facing_text(
            value.get("project_function")
            or value.get("target_and_direct_effect")
            or value.get("primary_equipment_identity")
            or "",
            limit=700,
        )
        if not project_function and direct_effects:
            project_function = direct_effects[0][:700]
        reference_overview = _user_facing_text(
            value.get("reference_overview") or value.get("weapon_overview") or "",
            limit=1800,
        )
        frontier_principle = _user_facing_text(
            value.get("frontier_principle", ""), limit=320
        )
        technology_discontinuity = _user_facing_text(
            value.get("technology_discontinuity", ""), limit=420
        )
        technology_horizon = _user_facing_text(
            value.get("technology_horizon", ""), limit=120
        )
        engineering_bottleneck = _user_facing_text(
            value.get("engineering_bottleneck", ""), limit=360
        )
        novelty_parts = [
            _user_facing_text(
                value.get("novelty_delta") or value.get("novelty") or "",
                limit=900,
            )
        ]
        if frontier_principle:
            novelty_parts.append(f"前沿原理：{frontier_principle}")
        if technology_discontinuity:
            novelty_parts.append(f"不可由常规升级吸收：{technology_discontinuity}")
        novelty_delta = _user_facing_text(
            "；".join(filter(None, novelty_parts)), limit=900
        )
        trl_constraints = _user_facing_text_list(
            value.get("trl_constraints", []), limit=6
        )
        if technology_horizon:
            trl_constraints = _dedupe(
                [f"前瞻窗口：{technology_horizon}", *trl_constraints], 6
            )
        if engineering_bottleneck:
            trl_constraints = _dedupe(
                [f"关键工程瓶颈：{engineering_bottleneck}", *trl_constraints], 6
            )
        hypothesis_id = _stable_id(
            "hypothesis",
            title,
            changed_variable,
            "|".join(mechanism_chain),
            task.task_id,
            str(ordinal),
        )
        hypothesis = WinningHypothesis(
            hypothesis_id=hypothesis_id,
            title=title,
            nearest_public_baseline=_user_facing_text(
                value.get("nearest_public_baseline")
                or value.get("current_baseline")
                or value.get("baseline")
                or "",
                limit=900,
            ),
            changed_confrontation_variable=changed_variable,
            mechanism_chain=mechanism_chain,
            direct_military_effects=direct_effects,
            equipment_forms=equipment_forms,
            frontier_principle=frontier_principle,
            technology_discontinuity=technology_discontinuity,
            technology_horizon=technology_horizon,
            engineering_bottleneck=engineering_bottleneck,
            winning_angle_id=str(value.get("winning_angle_id", "")).strip()[:160],
            combat_dimension=_user_facing_text(
                value.get("combat_dimension", ""), limit=80
            ),
            dimension_winning_logic=_user_facing_text(
                value.get("dimension_winning_logic", ""), limit=500
            ),
            original_paradigm=_user_facing_text(
                value.get("original_paradigm", ""), limit=900
            ),
            disruptive_shift=_user_facing_text(
                value.get("disruptive_shift", ""), limit=900
            ),
            independence_thesis=_user_facing_text(
                value.get("independence_thesis")
                or value.get("unique_operational_role")
                or "",
                limit=900,
            ),
            project_function=project_function,
            reference_overview=reference_overview,
            novelty_delta=novelty_delta,
            naming_rationale=_user_facing_text(
                value.get("naming_rationale", ""), limit=900
            ),
            decisive_advantage_thesis=_user_facing_text(
                value.get("decisive_advantage_thesis", ""), limit=900
            ),
            cross_query_distinction=_user_facing_text(
                value.get("cross_query_distinction", ""), limit=900
            ),
            system_interfaces=_user_facing_text_list(
                value.get("system_interfaces", []), limit=8
            ),
            evidence_ids=evidence_ids,
            counterevidence=_user_facing_text_list(
                value.get("counterevidence", []), limit=8
            ),
            adversary_adaptations=_user_facing_text_list(
                value.get("adversary_adaptations", []), limit=8
            ),
            failure_boundaries=_user_facing_text_list(
                value.get("failure_boundaries", []), limit=8
            ),
            trl_constraints=trl_constraints,
            cost_constraints=_user_facing_text_list(
                value.get("cost_constraints", []), limit=6
            ),
            industrial_constraints=_user_facing_text_list(
                value.get("industrial_constraints", []), limit=6
            ),
            cross_scenario_results=_user_facing_text_list(
                value.get("cross_scenario_results", []), limit=8
            ),
            validation_plan=_user_facing_text_list(
                value.get("validation_plan", []), limit=8
            ),
            evidence_boundary=_user_facing_text(
                value.get("evidence_boundary", ""), limit=800
            ),
            implementation_path=_user_facing_text(
                value.get("implementation_path", ""), limit=800
            ),
            merge_targets=[task.merge_target],
            source_task_ids=[task.task_id],
        )
        gate = self.evaluate_gate(hypothesis, stage="breadth")
        preflight_residuals = list(gate.residuals)
        return replace(
            hypothesis,
            residuals=_dedupe(preflight_residuals, 24),
            score=gate.score,
        )

    def contribution_from_mapping(
        self,
        value: Mapping[str, Any],
        *,
        task: SpecialistTask,
        valid_evidence_ids: set[str],
    ) -> SpecialistContribution:
        if task.allow_child_spawn:
            raise ValueError("dynamic specialists may not recruit child agents")
        if not task.hypothesis_id or task.merge_target not in MERGE_TARGETS:
            raise ValueError(
                "specialist contribution requires hypothesis_id + merge_target"
            )
        reported_hypothesis = str(value.get("hypothesis_id") or task.hypothesis_id)
        reported_target = str(value.get("merge_target") or task.merge_target)
        if (
            reported_hypothesis != task.hypothesis_id
            or reported_target != task.merge_target
        ):
            raise ValueError(
                "specialist contribution crossed its declared merge boundary"
            )
        evidence_ids = self.sanitize_evidence_ids(
            value.get("evidence_ids", value.get("evidence_refs", [])),
            valid_evidence_ids,
        )
        quality = _bounded_float(
            value.get("incremental_quality", value.get("quality_delta")), 0.0, 1.0, 0.0
        )
        recommendation = str(value.get("recommendation", "retain"))[:80]
        retention = self.contribution_retention_assessment(
            value,
            evidence_ids=evidence_ids,
            reported_quality=quality,
            mission_node=task.merge_target,
        )
        quality = float(retention["effective_quality"])
        accepted = bool(retention["accepted"])
        direct_effects = _user_facing_text_list(
            value.get("direct_military_effects", []), limit=6
        )
        project_function = _user_facing_text(
            value.get("project_function", ""), limit=700
        )
        if not project_function and direct_effects:
            project_function = direct_effects[0][:700]
        return SpecialistContribution(
            contribution_id=_stable_id(
                "contribution", task.task_id, task.hypothesis_id
            ),
            task_id=task.task_id,
            agent_instance_id=task.agent_instance_id,
            hypothesis_id=task.hypothesis_id,
            merge_target=task.merge_target,
            findings=_text_list(value.get("findings", []), limit=8),
            replacement_title=normalize_weapon_candidate_title(
                value.get("replacement_title", ""),
                value.get("equipment_forms", []),
            ),
            mechanism_chain_updates=_user_facing_text_list(
                value.get("mechanism_chain_updates", []), limit=8
            ),
            direct_military_effects=direct_effects,
            equipment_forms=_user_facing_text_list(
                value.get("equipment_forms", []), limit=6
            ),
            project_function=project_function,
            system_interfaces=_user_facing_text_list(
                value.get("system_interfaces", []), limit=8
            ),
            novelty_delta=_user_facing_text(value.get("novelty_delta", ""), limit=900),
            frontier_principle=_user_facing_text(
                value.get("frontier_principle", ""), limit=320
            ),
            technology_discontinuity=_user_facing_text(
                value.get("technology_discontinuity", ""), limit=420
            ),
            technology_horizon=_user_facing_text(
                value.get("technology_horizon", ""), limit=120
            ),
            engineering_bottleneck=_user_facing_text(
                value.get("engineering_bottleneck", ""), limit=360
            ),
            original_paradigm=_user_facing_text(
                value.get("original_paradigm", ""), limit=900
            ),
            disruptive_shift=_user_facing_text(
                value.get("disruptive_shift", ""), limit=900
            ),
            independence_thesis=_user_facing_text(
                value.get("independence_thesis", ""), limit=900
            ),
            naming_rationale=_user_facing_text(
                value.get("naming_rationale", ""), limit=900
            ),
            decisive_advantage_thesis=_user_facing_text(
                value.get("decisive_advantage_thesis", ""), limit=900
            ),
            cross_query_distinction=_user_facing_text(
                value.get("cross_query_distinction", ""), limit=900
            ),
            evidence_boundary=_user_facing_text(
                value.get("evidence_boundary", ""), limit=800
            ),
            implementation_path=_user_facing_text(
                value.get("implementation_path", ""), limit=800
            ),
            evidence_ids=evidence_ids,
            counterevidence=_user_facing_text_list(
                value.get("counterevidence", []), limit=8
            ),
            adversary_adaptations=_user_facing_text_list(
                value.get("adversary_adaptations", []), limit=8
            ),
            failure_boundaries=_user_facing_text_list(
                value.get("failure_boundaries", []), limit=8
            ),
            trl_constraints=_user_facing_text_list(
                value.get("trl_constraints", []), limit=6
            ),
            cost_constraints=_user_facing_text_list(
                value.get("cost_constraints", []), limit=6
            ),
            industrial_constraints=_user_facing_text_list(
                value.get("industrial_constraints", []), limit=6
            ),
            cross_scenario_results=_user_facing_text_list(
                value.get("cross_scenario_results", []), limit=8
            ),
            validation_plan=_user_facing_text_list(
                value.get("validation_plan", []), limit=8
            ),
            residuals_resolved=_text_list(value.get("residuals_resolved", []), limit=8),
            incremental_quality=quality,
            recommendation=recommendation,
            accepted=accepted,
        )

    def contribution_retention_assessment(
        self,
        value: Mapping[str, Any],
        *,
        evidence_ids: Sequence[str],
        reported_quality: float,
        mission_node: str = "",
    ) -> dict[str, Any]:
        """Retain structured W2/S3-S5 value even when self-rating is conservative.

        Specialists sometimes leave ``findings`` empty because their useful
        delta is represented in structured equipment, effect, mechanism and
        evidence fields.  Treat that complete combination as high-quality
        contribution instead of discarding it on formatting or self-scoring.
        """

        recommendation = str(value.get("recommendation", "retain"))[:80]
        findings = _text_list(value.get("findings", []), limit=8)
        equipment_forms = _text_list(value.get("equipment_forms", []), limit=6)
        direct_effects = _text_list(value.get("direct_military_effects", []), limit=6)
        project_function = str(value.get("project_function", "")).strip()
        if not project_function and direct_effects:
            project_function = direct_effects[0]
        mechanism_updates = _text_list(
            value.get("mechanism_chain_updates", value.get("mechanism_chain", [])),
            limit=8,
        )
        novelty = str(value.get("novelty_delta", "")).strip()
        evidence_boundary = str(value.get("evidence_boundary", "")).strip()
        failure_boundaries = _text_list(value.get("failure_boundaries", []), limit=8)
        validation_plan = _text_list(value.get("validation_plan", []), limit=8)
        cross_scenario = _text_list(value.get("cross_scenario_results", []), limit=8)
        # Concrete identity is a structured-contract question here.  Whether
        # an unfamiliar form is genuinely a weapon is decided by the S3
        # admission and independent expert Codex, never by a Chinese suffix
        # catalogue embedded in local retention code.
        concrete_equipment = bool(equipment_forms)
        mechanism_difference = bool(mechanism_updates or novelty)
        structured_weapon_delta = bool(
            concrete_equipment
            and direct_effects
            and project_function
            and mechanism_difference
        )
        generic_substantive = bool(
            structured_weapon_delta
            or findings
            or validation_plan
            or failure_boundaries
            or cross_scenario
            or evidence_boundary
        )
        s6_validation_delta = mission_node == "S6" and bool(
            validation_plan and (failure_boundaries or evidence_boundary)
        )
        accepted = bool(recommendation != "reject" and generic_substantive)
        effective_quality = reported_quality
        return {
            "accepted": accepted,
            "effective_quality": effective_quality,
            "reported_quality": reported_quality,
            "structured_weapon_delta": structured_weapon_delta,
            "s6_validation_delta": s6_validation_delta,
            "retention_reason": (
                "structured_query_weapon_delta"
                if structured_weapon_delta
                else "s6_validation_delta"
                if s6_validation_delta
                else "model_retained_substantive_delta"
                if accepted
                else "insufficient_substantive_gain"
            ),
        }

    def apply_contribution(
        self,
        hypothesis: WinningHypothesis,
        contribution: SpecialistContribution,
    ) -> WinningHypothesis:
        if not contribution.accepted:
            return hypothesis
        if contribution.hypothesis_id != hypothesis.hypothesis_id:
            raise ValueError(
                "contribution hypothesis_id does not match ledger candidate"
            )
        if contribution.merge_target not in MERGE_TARGETS:
            raise ValueError("invalid contribution merge_target")
        residuals = [
            item
            for item in hypothesis.residuals
            if item not in set(contribution.residuals_resolved)
        ]
        replacement_title = contribution.replacement_title.strip()
        # S4/S5 renaming is a whole-candidate semantic decision authored by an
        # isolated Codex session.  Local suffix, length and keyword heuristics
        # must not veto a more natural frontier-equipment name or force the
        # model back to an abstract "function + munition" label.
        naming_repair_allowed = bool(
            contribution.merge_target in {"S4", "S5"}
            and replacement_title
            and replacement_title != hypothesis.title
            and contribution.naming_rationale.strip()
        )
        updated = replace(
            hypothesis,
            title=replacement_title if naming_repair_allowed else hypothesis.title,
            mechanism_chain=_dedupe(
                [
                    *hypothesis.mechanism_chain,
                    *contribution.mechanism_chain_updates,
                ],
                10,
            ),
            direct_military_effects=_dedupe(
                [
                    *hypothesis.direct_military_effects,
                    *contribution.direct_military_effects,
                ],
                8,
            ),
            equipment_forms=_dedupe(
                [
                    *hypothesis.equipment_forms,
                    *contribution.equipment_forms,
                ],
                8,
            ),
            project_function=(
                contribution.project_function or hypothesis.project_function
            ),
            system_interfaces=_dedupe(
                [
                    *hypothesis.system_interfaces,
                    *contribution.system_interfaces,
                ],
                10,
            ),
            novelty_delta=contribution.novelty_delta or hypothesis.novelty_delta,
            frontier_principle=(
                contribution.frontier_principle or hypothesis.frontier_principle
            ),
            technology_discontinuity=(
                contribution.technology_discontinuity
                or hypothesis.technology_discontinuity
            ),
            technology_horizon=(
                contribution.technology_horizon or hypothesis.technology_horizon
            ),
            engineering_bottleneck=(
                contribution.engineering_bottleneck
                or hypothesis.engineering_bottleneck
            ),
            # Ordinary S4/S5 work may complete a missing thesis but cannot
            # silently rewrite the S3 identity. Explicit expert repair uses
            # replace_bounded_claims below when a full correction is needed.
            original_paradigm=(
                hypothesis.original_paradigm or contribution.original_paradigm
            ),
            disruptive_shift=(
                hypothesis.disruptive_shift or contribution.disruptive_shift
            ),
            independence_thesis=(
                hypothesis.independence_thesis or contribution.independence_thesis
            ),
            naming_rationale=(
                contribution.naming_rationale or hypothesis.naming_rationale
            ),
            decisive_advantage_thesis=(
                contribution.decisive_advantage_thesis
                or hypothesis.decisive_advantage_thesis
            ),
            cross_query_distinction=(
                contribution.cross_query_distinction
                or hypothesis.cross_query_distinction
            ),
            evidence_boundary=contribution.evidence_boundary
            or hypothesis.evidence_boundary,
            implementation_path=contribution.implementation_path
            or hypothesis.implementation_path,
            evidence_ids=_dedupe(
                [*hypothesis.evidence_ids, *contribution.evidence_ids], 24
            ),
            counterevidence=_dedupe(
                [*hypothesis.counterevidence, *contribution.counterevidence], 12
            ),
            adversary_adaptations=_dedupe(
                [
                    *hypothesis.adversary_adaptations,
                    *contribution.adversary_adaptations,
                ],
                12,
            ),
            failure_boundaries=_dedupe(
                [*hypothesis.failure_boundaries, *contribution.failure_boundaries], 12
            ),
            trl_constraints=_dedupe(
                [*hypothesis.trl_constraints, *contribution.trl_constraints], 10
            ),
            cost_constraints=_dedupe(
                [*hypothesis.cost_constraints, *contribution.cost_constraints], 10
            ),
            industrial_constraints=_dedupe(
                [
                    *hypothesis.industrial_constraints,
                    *contribution.industrial_constraints,
                ],
                10,
            ),
            cross_scenario_results=_dedupe(
                [
                    *hypothesis.cross_scenario_results,
                    *contribution.cross_scenario_results,
                ],
                12,
            ),
            validation_plan=_dedupe(
                [*hypothesis.validation_plan, *contribution.validation_plan], 12
            ),
            merge_targets=_dedupe(
                [*hypothesis.merge_targets, contribution.merge_target], 7
            ),
            source_task_ids=_dedupe(
                [*hypothesis.source_task_ids, contribution.task_id], 12
            ),
            residuals=residuals,
            status="challenging",
        )
        gate = self.evaluate_gate(updated, stage="targeted")
        return replace(updated, residuals=gate.residuals, score=gate.score)

    def qualifies_for_frontier_evidence_allowance(
        self,
        hypothesis: WinningHypothesis,
    ) -> bool:
        """Allow bounded evidence uncertainty for falsifiable new weapon concepts."""

        return bool(
            self.policy.get("frontier_evidence_relaxation")
            and hypothesis.implementation_path == "new"
            and hypothesis.nearest_public_baseline.strip()
            and hypothesis.changed_confrontation_variable.strip()
            and hypothesis.mechanism_chain
            and hypothesis.direct_military_effects
            and hypothesis.equipment_forms
            and hypothesis.project_function.strip()
            and hypothesis.novelty_delta.strip()
            and hypothesis.original_paradigm.strip()
            and hypothesis.disruptive_shift.strip()
            and hypothesis.independence_thesis.strip()
            and hypothesis.frontier_principle.strip()
            and hypothesis.technology_discontinuity.strip()
            and hypothesis.technology_horizon.strip()
            and hypothesis.engineering_bottleneck.strip()
            and hypothesis.decisive_advantage_thesis.strip()
            and hypothesis.naming_rationale.strip()
            and hypothesis.cross_query_distinction.strip()
            and not self._contains_unsupported_precision(hypothesis)
        )

    def evaluate_gate(
        self, hypothesis: WinningHypothesis, *, stage: str
    ) -> SwarmGateResult:
        residuals: list[str] = []
        rejection_reasons: list[str] = []
        frontloaded_quality = self.policy.get("policy_id") in {
            "winning_swarm_dynamic_v2",
            "swarm_quality_v1",
            "winning_swarm_quality_v1",
        }
        frontier_allowance = bool(
            frontloaded_quality
            and self.qualifies_for_frontier_evidence_allowance(hypothesis)
        )
        if not hypothesis.nearest_public_baseline.strip():
            residuals.append("baseline_missing")
        if (
            not hypothesis.changed_confrontation_variable.strip()
            or not hypothesis.mechanism_chain
        ):
            residuals.append("causal_chain_broken")
        if not hypothesis.direct_military_effects:
            residuals.append("military_effect_missing")
        if not hypothesis.novelty_delta.strip():
            residuals.append("novelty_insufficient")
        if frontloaded_quality:
            if not (
                hypothesis.original_paradigm.strip()
                and hypothesis.disruptive_shift.strip()
                and hypothesis.independence_thesis.strip()
            ):
                residuals.append("paradigm_shift_unproven")
            if not (
                hypothesis.frontier_principle.strip()
                and hypothesis.technology_discontinuity.strip()
                and hypothesis.technology_horizon.strip()
                and hypothesis.engineering_bottleneck.strip()
            ):
                residuals.append("frontier_discontinuity_unproven")
            if not hypothesis.decisive_advantage_thesis.strip():
                residuals.append("decisive_advantage_missing")
            if not hypothesis.naming_rationale.strip():
                residuals.append("weapon_naming_unjustified")
            if not hypothesis.cross_query_distinction.strip():
                residuals.append("template_substitution_unresolved")
        if not hypothesis.equipment_forms:
            residuals.append("equipment_not_concrete")
        if not hypothesis.project_function.strip():
            residuals.append("project_function_missing")
        if frontloaded_quality and not hypothesis.system_interfaces:
            residuals.append("system_interfaces_missing")
        if frontloaded_quality:
            # A concrete weapon may be a forward-looking concept whose public
            # evidence is only analogous or absent.  Object-level evidence is
            # retained when available for audit routing, but it is never a
            # delivery blocker.
            if (
                hypothesis.implementation_path == "upgrade"
                and any(
                    "-web-" in str(evidence_id)
                    for evidence_id in hypothesis.evidence_ids
                )
                and not any(
                    str(evidence_id).startswith("ev-weapon_equipment-")
                    for evidence_id in hypothesis.evidence_ids
                )
            ):
                residuals.append("equipment_object_evidence_missing")
        if not hypothesis.evidence_ids or not hypothesis.evidence_boundary.strip():
            residuals.append("evidence_insufficient")
        if not hypothesis.adversary_adaptations or not hypothesis.failure_boundaries:
            residuals.append("counter_adaptation_unresolved")
        if not (
            hypothesis.trl_constraints
            and hypothesis.cost_constraints
            and hypothesis.industrial_constraints
        ):
            residuals.append("engineering_feasibility_insufficient")
        if not hypothesis.cross_scenario_results:
            residuals.append("cross_scenario_unstable")
        if not hypothesis.validation_plan:
            residuals.append("validation_route_missing")
        if self._contains_unsupported_precision(hypothesis):
            residuals.append("unsupported_precision")
            rejection_reasons.append("无公开证据支撑的精确指标、效能比例或成熟度判断")

        dimension_weights = {
            "baseline_missing": 0.10,
            "causal_chain_broken": 0.16,
            "military_effect_missing": 0.14,
            "direct_combat_effect_unproven": 0.14,
            "novelty_insufficient": 0.10,
            "paradigm_shift_unproven": 0.16,
            "frontier_discontinuity_unproven": 0.12,
            "decisive_advantage_missing": 0.14,
            "weapon_naming_unjustified": 0.05,
            "template_substitution_unresolved": 0.10,
            "equipment_not_concrete": 0.08,
            "project_function_missing": 0.08,
            "system_interfaces_missing": 0.04,
            "mixed_primary_equipment_families": 0.12,
            # Evidence traceability is recommended context, not a hard gate.
            # Keep the residual for routing/diagnostics while assigning no
            # score penalty so sparse public evidence cannot kill inspiration.
            "equipment_object_evidence_missing": 0.0,
            "evidence_insufficient": 0.0,
            "counter_adaptation_unresolved": 0.08,
            "engineering_feasibility_insufficient": 0.06,
            "cross_scenario_unstable": 0.05,
            "validation_route_missing": 0.05,
        }
        if frontier_allowance:
            dimension_weights.update(
                {
                    "equipment_object_evidence_missing": 0.0,
                    "evidence_insufficient": 0.0,
                    "counter_adaptation_unresolved": 0.03,
                    "engineering_feasibility_insufficient": 0.03,
                    "cross_scenario_unstable": 0.03,
                    "validation_route_missing": 0.03,
                }
            )
        score = 1.0 - sum(
            weight
            for residual, weight in dimension_weights.items()
            if residual in residuals
        )
        if "unsupported_precision" in residuals:
            score -= 0.20
        score = round(max(0.0, min(1.0, score)), 4)
        # Residuals route review and remain auditable; they never delete a
        # candidate. Independent Codex semantic review owns final admission.
        passed = True
        return SwarmGateResult(
            gate_id=_stable_id("swarm-gate", hypothesis.hypothesis_id, stage),
            hypothesis_id=hypothesis.hypothesis_id,
            stage=stage,
            passed=passed,
            score=score,
            residuals=list(dict.fromkeys(residuals)),
            rejection_reasons=rejection_reasons,
            evidence_ids=list(hypothesis.evidence_ids),
        )

    @staticmethod
    def _contains_unsupported_precision(hypothesis: WinningHypothesis) -> bool:
        if hypothesis.evidence_ids:
            return False
        text = " ".join(
            [
                *hypothesis.mechanism_chain,
                *hypothesis.direct_military_effects,
                *hypothesis.trl_constraints,
                *hypothesis.validation_plan,
            ]
        )
        return bool(
            re.search(
                r"(?:\bTRL\s*[1-9]\b|\b\d+(?:\.\d+)?\s*%|提升\s*\d+|降低\s*\d+|"
                r"\b\d+(?:\.\d+)?\s*(?:公里|千米|米|秒|分钟|小时|枚|架|套)\b)",
                text,
                flags=re.IGNORECASE,
            )
        )

    def deduplicate_hypotheses(
        self,
        hypotheses: Sequence[WinningHypothesis],
    ) -> tuple[list[WinningHypothesis], list[dict[str, str]]]:
        """Collapse only exact five-axis identity duplicates.

        Semantic similarity is intentionally not decided with Chinese bigram
        overlap.  Near-duplicate and same-thesis variants are now adjudicated
        by an isolated Codex pairwise-clustering pass in the provider.
        """

        kept: list[WinningHypothesis] = []
        merged: list[dict[str, str]] = []
        fingerprint_owner: dict[tuple[str, ...], WinningHypothesis] = {}
        for candidate in sorted(
            hypotheses,
            key=lambda item: (-item.score, -len(item.evidence_ids), item.hypothesis_id),
        ):
            fingerprint = _semantic_identity_fingerprint(candidate)
            duplicate = fingerprint_owner.get(fingerprint)
            if duplicate is None:
                kept.append(candidate)
                fingerprint_owner[fingerprint] = candidate
                continue
            merged.append(
                {
                    "source_hypothesis_id": candidate.hypothesis_id,
                    "target_hypothesis_id": duplicate.hypothesis_id,
                    "reason": "exact_five_axis_identity_duplicate",
                }
            )
        return kept, merged

    @staticmethod
    def operational_independence_axes(
        left: WinningHypothesis,
        right: WinningHypothesis,
    ) -> list[str]:
        """Return exact differing axes without attempting semantic judgement."""

        left_axes = _semantic_identity_fingerprint(left)
        right_axes = _semantic_identity_fingerprint(right)
        names = (
            "target",
            "task_chain_breakpoint",
            "changed_variable",
            "core_mechanism",
            "direct_result",
        )
        return [
            name
            for name, left_value, right_value in zip(names, left_axes, right_axes)
            if left_value != right_value
        ]

    def same_family_independence_conflicts(
        self,
        hypotheses: Sequence[WinningHypothesis],
    ) -> list[dict[str, Any]]:
        """Do not infer semantic conflicts from local family/token rules.

        Candidate merging is completed earlier by an isolated Codex pairwise
        comparison over target, task-chain break, changed variable, core
        mechanism and direct result.  This compatibility method intentionally
        returns no hard conflicts because it has no access to that judgement.
        """

        del hypotheses
        return []

    @staticmethod
    def semantic_hypothesis_match(
        candidate: WinningHypothesis,
        governed_candidates: Sequence[WinningHypothesis],
        *,
        minimum_similarity: float = 0.72,
    ) -> str:
        """Resolve only an exact five-axis identity after model clustering.

        ``minimum_similarity`` is retained for call compatibility.  Fuzzy
        lexical remapping used to attach a specialist contribution to a
        merely similar weapon; aliases produced by the Codex clustering pass
        are handled by the workflow before this exact fallback is reached.
        """

        del minimum_similarity
        fingerprint = _semantic_identity_fingerprint(candidate)
        matches = [
            governed
            for governed in governed_candidates
            if _semantic_identity_fingerprint(governed) == fingerprint
        ]
        if len(matches) != 1:
            return ""
        return matches[0].hypothesis_id

    def select_finalists(
        self,
        hypotheses: Sequence[WinningHypothesis],
    ) -> tuple[list[WinningHypothesis], list[WinningHypothesis], list[SwarmGateResult]]:
        gates = [self.evaluate_gate(item, stage="final") for item in hypotheses]
        gate_by_id = {item.hypothesis_id: item for item in gates}
        ranked = sorted(
            hypotheses,
            key=lambda item: (
                not gate_by_id[item.hypothesis_id].passed,
                -gate_by_id[item.hypothesis_id].score,
                -len(item.evidence_ids),
                item.hypothesis_id,
            ),
        )
        maximum = int(self.policy["finalist_maximum"])
        passing = [item for item in ranked if gate_by_id[item.hypothesis_id].passed]
        non_dominated = [
            candidate
            for candidate in passing
            if not any(
                other.hypothesis_id != candidate.hypothesis_id
                and _dominates(other, candidate, gate_by_id)
                for other in passing
            )
        ]
        selected = non_dominated[:maximum]
        selected_ids = {item.hypothesis_id for item in selected}
        selection_reasons: dict[str, list[str]] = {}
        for candidate in ranked:
            if candidate.hypothesis_id in selected_ids:
                continue
            gate = gate_by_id[candidate.hypothesis_id]
            if not gate.passed:
                selection_reasons[candidate.hypothesis_id] = (
                    list(gate.rejection_reasons)
                    or list(gate.residuals)
                    or ["独立Codex语义评审未将其纳入本轮组合"]
                )
                continue
            dominators = [
                other.hypothesis_id
                for other in passing
                if other.hypothesis_id != candidate.hypothesis_id
                and _dominates(other, candidate, gate_by_id)
            ]
            if dominators:
                selection_reasons[candidate.hypothesis_id] = [
                    "经独立Codex语义评审保留，但被更强候选在质量得分、证据覆盖、"
                    "反适应/跨场景稳健性或工程约束完整性上支配："
                    + "、".join(dominators[:3])
                ]
            else:
                selection_reasons[candidate.hypothesis_id] = [
                    "经独立Codex语义评审保留，但受候选组合容量上限"
                    f"（finalist_maximum={maximum}）约束，按质量得分、证据覆盖和稳定性排序未入选"
                ]
        gates = [
            replace(
                gate,
                rejection_reasons=selection_reasons.get(
                    gate.hypothesis_id,
                    gate.rejection_reasons,
                ),
            )
            for gate in gates
        ]
        gate_by_id = {item.hypothesis_id: item for item in gates}
        finalists = [
            replace(
                item,
                status=(
                    "finalist" if item.hypothesis_id in selected_ids else "rejected"
                ),
                score=gate_by_id[item.hypothesis_id].score,
                residuals=gate_by_id[item.hypothesis_id].residuals,
            )
            for item in ranked
            if item.hypothesis_id in selected_ids
        ]
        rejected = [
            replace(
                item,
                status="rejected",
                score=gate_by_id[item.hypothesis_id].score,
                residuals=gate_by_id[item.hypothesis_id].residuals,
            )
            for item in ranked
            if item.hypothesis_id not in selected_ids
        ]
        return finalists, rejected, gates

    @staticmethod
    def sanitize_evidence_ids(
        values: Any,
        valid_evidence_ids: set[str],
    ) -> list[str]:
        return [
            item for item in _text_list(values, limit=32) if item in valid_evidence_ids
        ]

    @staticmethod
    def is_direct_combat_equipment(
        hypothesis: WinningHypothesis,
        assessment: WinningExpertAssessment | None = None,
    ) -> bool:
        return _is_direct_combat_equipment(hypothesis, assessment)

    def select_expert_repair_assessments(
        self,
        assessments: Mapping[str, WinningExpertAssessment],
        *,
        hypotheses: Mapping[str, WinningHypothesis] | None = None,
    ) -> list[WinningExpertAssessment]:
        """Prioritize failed direct-equipment images before quota conversions.

        Passing system-link candidates are useful for portfolio breadth but
        rewriting them can turn a pass into a reject. Repair already-direct
        ``revise`` candidates first so scarce repair capacity improves actual
        combat equipment rather than converting support concepts merely to
        satisfy a portfolio count. Repair capacity is a runtime bound, not a
        required number of equipment directions.
        """

        maximum_candidates = int(self.policy["expert_repair_max_candidates"])
        direct_categories = {"direct_combat", "unmanned_combat"}

        def is_non_repairable_duplicate(
            item: WinningExpertAssessment,
        ) -> bool:
            decision_text = " ".join(
                [
                    *item.rejection_reasons,
                    *item.residuals,
                    *item.weaknesses,
                ]
            ).casefold()
            return "semantic_duplicate" in decision_text

        concrete_gap = sorted(
            (
                item
                for item in assessments.values()
                if item.passed
                and item.equipment_classification not in direct_categories
            ),
            key=lambda item: (-item.weighted_score, item.hypothesis_id),
        )
        revisions = sorted(
            (
                item
                for item in assessments.values()
                if item.verdict == "revise"
                and not is_non_repairable_duplicate(item)
            ),
            key=lambda item: (-item.weighted_score, item.hypothesis_id),
        )
        direct_revisions = [
            item
            for item in revisions
            if item.equipment_classification in direct_categories
        ]
        other_revisions = [
            item
            for item in revisions
            if item.equipment_classification not in direct_categories
        ]
        # ``hypotheses`` is retained for API compatibility.  Repair priority
        # comes from the independent expert verdict, classification and score;
        # local code must not reshuffle it through an inferred weapon family.
        del hypotheses

        selected: list[WinningExpertAssessment] = []
        seen: set[str] = set()
        for item in [*direct_revisions, *concrete_gap, *other_revisions]:
            if item.hypothesis_id in seen:
                continue
            selected.append(item)
            seen.add(item.hypothesis_id)
            if len(selected) >= maximum_candidates:
                break
        return selected

    @staticmethod
    def contribution_projection(
        contribution: SpecialistContribution,
        *,
        hypothesis_id: str,
        merge_target: str,
    ) -> dict[str, Any] | None:
        if not contribution.accepted:
            return None
        if (
            contribution.hypothesis_id != hypothesis_id
            or contribution.merge_target != merge_target
        ):
            return None
        return to_plain(contribution)

    def promotion_candidate(
        self,
        *,
        archetype: str,
        eligible_runs: int,
        positive_increment_runs: int,
        evidence_hard_failures: int,
        permission_hard_failures: int,
        offline_evaluation_passed: bool = False,
        human_approved: bool = False,
    ) -> AgentPromotionRecord | None:
        promotion = self.policy["promotion"]
        rate = positive_increment_runs / eligible_runs if eligible_runs else 0.0
        if (
            eligible_runs < int(promotion["minimum_eligible_runs"])
            or rate < float(promotion["minimum_positive_increment_rate"])
            or evidence_hard_failures > 0
            or permission_hard_failures > 0
        ):
            return None
        status = (
            "approved"
            if offline_evaluation_passed and human_approved
            else "human_review_pending"
            if offline_evaluation_passed
            else "offline_evaluation_pending"
        )
        return AgentPromotionRecord(
            promotion_id=_stable_id("promotion", archetype, str(eligible_runs)),
            archetype=archetype,
            eligible_runs=eligible_runs,
            positive_increment_runs=positive_increment_runs,
            evidence_hard_failures=evidence_hard_failures,
            permission_hard_failures=permission_hard_failures,
            positive_increment_rate=round(rate, 4),
            offline_evaluation_passed=offline_evaluation_passed,
            human_approved=human_approved,
            status=status,
            rollback_ref=f"{archetype}:ephemeral",
        )


def _normalize_semantic_identity_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value).lower())


def _semantic_identity_fingerprint(
    hypothesis: WinningHypothesis,
) -> tuple[str, ...]:
    """Return the exact target/breakpoint/variable/mechanism/effect identity."""

    target = " ".join([hypothesis.project_function, *hypothesis.equipment_forms[:1]])
    task_breakpoint = hypothesis.project_function
    changed_variable = hypothesis.changed_confrontation_variable
    mechanism = " ".join(hypothesis.mechanism_chain)
    direct_result = " ".join(hypothesis.direct_military_effects)
    return tuple(
        _normalize_semantic_identity_text(item)
        for item in (
            target,
            task_breakpoint,
            changed_variable,
            mechanism,
            direct_result,
        )
    )


def _semantic_identity_signature(hypothesis: WinningHypothesis) -> str:
    """Return an opaque key for an exact, already model-governed identity."""

    payload = "\x1f".join(_semantic_identity_fingerprint(hypothesis))
    return "semantic:" + sha256(payload.encode("utf-8")).hexdigest()[:16]


def _diverse_portfolio_order(
    candidate_ids: Sequence[str],
    *,
    hypothesis_by_id: Mapping[str, WinningHypothesis],
    scores: Mapping[str, Mapping[str, float]],
    prior_ids: Sequence[str] = (),
    family_by_id: Mapping[str, str] | None = None,
) -> list[str]:
    """Rank governed candidates by expert objectives, not family vocabulary.

    ``prior_ids`` and ``family_by_id`` are retained for API compatibility.
    Semantic duplicate removal is owned by the independent five-axis Codex
    pass, so a lexical family round-robin cannot suppress a distinct weapon.
    """

    del hypothesis_by_id, prior_ids, family_by_id
    return sorted(
        dict.fromkeys(candidate_ids),
        key=lambda item: (-sum(scores[item].values()), item),
    )


def _is_direct_combat_equipment(
    hypothesis: WinningHypothesis,
    assessment: WinningExpertAssessment | None = None,
) -> bool:
    """Reject support-only cards from satisfying the combat-equipment quota."""

    classification = (
        assessment.equipment_classification.strip().lower()
        if assessment is not None
        else ""
    )
    if classification in {"direct_combat", "unmanned_combat"}:
        return True
    if classification in {"system_link", "support", "support_only", "non_equipment"}:
        return False

    # No local title/equipment keyword fallback: unfamiliar disruptive forms
    # were previously rejected simply because their nouns were absent from a
    # fixed catalogue.  Real portfolio decisions always carry the independent
    # expert classification.  Without it, preserve the candidate as
    # unclassified rather than claiming it satisfies a combat-equipment quota.
    return False


def _dominates(
    left: WinningHypothesis,
    right: WinningHypothesis,
    gates: Mapping[str, SwarmGateResult],
) -> bool:
    def vector(item: WinningHypothesis) -> tuple[float, float, float, float]:
        return (
            gates[item.hypothesis_id].score,
            min(1.0, len(item.evidence_ids) / 3),
            min(
                1.0,
                (len(item.adversary_adaptations) + len(item.cross_scenario_results))
                / 4,
            ),
            1.0
            if item.trl_constraints
            and item.cost_constraints
            and item.industrial_constraints
            else 0.0,
        )

    left_vector = vector(left)
    right_vector = vector(right)
    return all(a >= b for a, b in zip(left_vector, right_vector)) and any(
        a > b for a, b in zip(left_vector, right_vector)
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _text_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        rows = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = list(value)
    else:
        rows = []
    return _dedupe(
        [str(item).strip()[:1200] for item in rows if str(item).strip()], limit
    )


def _clean_weapon_candidate_text(value: Any) -> str:
    """Strip swarm-stage labels and explanation prose from a visible title."""

    title = " ".join(str(value or "").replace("_", " ").split()).strip()
    title = re.sub(
        r"^(?:(?:[A-H]\s*[-/]?\s*)?S[1-6](?:\s*[-/]?\s*(?:候选)?[A-Z一二三四五六\d]+)?|"
        r"(?:竞争分支|候选)(?:[A-Z一二三四五六\d-]+)?|[A-H])\s*[：:—–/-]*\s*",
        "",
        title,
        count=1,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\bS[1-6]\b\s*[-_/：:]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^(?:红队保留|红队|保留参考|参考武器)\s*[：:—–/-]*\s*", "", title)
    title = re.sub(
        r"^(?:竞争分支|颠覆分支|候选分支)\s*[：:—–/-]*\s*",
        "",
        title,
    )
    # A candidate ledger title must never absorb a following form/interface
    # field.  This is metadata cleanup, not a rule-based weapon renaming.
    title = re.split(
        r"\s*(?:·|\||；|;)\s*(?:主装备)?(?:装备)?(?:形态|接口形态|接口|任务接口)\s*[：:]",
        title,
        maxsplit=1,
    )[0]
    title = re.sub(
        r"^(?:(?:主装备)?(?:装备)?形态|接口形态|接口|任务接口|(?:[Qq]uery)(?:相关|专属)?(?:型号|装备)?|相关型号)\s*[：:]\s*",
        "",
        title,
    )
    # Proposal codenames conventionally use paired Chinese quotation marks;
    # stripping only the opening mark corrupts the visible equipment name.
    return title.strip(" ：:—–/-\"'")


def _preflight_query_weapon_title(value: str) -> str:
    """Preserve the model's semantic name; only remove presentation noise.

    Candidate naming belongs to the query-aware Codex reasoning pass, not a
    catalogue of string substitutions.  Structural validation may still send
    an obviously non-weapon label to an early specialist for a fresh decision.
    """

    return str(value or "").strip()


def normalize_weapon_candidate_title(
    value: Any,
    equipment_forms: Sequence[Any] = (),
) -> str:
    """Preserve the Agent-authored name after internal metadata cleanup.

    Naming is a semantic S3/S5 Agent decision. Local code may remove stage
    labels or following metadata, but must never substitute an equipment form
    or assemble a title from weapon, payload or effect keywords.
    """

    del equipment_forms
    cleaned = _clean_weapon_candidate_text(value)
    head = re.split(r"[：:；;。]", cleaned, maxsplit=1)[0].strip()
    return _preflight_query_weapon_title(head or cleaned)


def _dedupe(values: Sequence[str], limit: int) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item).strip()))[
        :limit
    ]


def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _bounded_float(
    value: Any, minimum: float, maximum: float, fallback: float
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


__all__ = [
    "CORE_STEP_DEPENDENCIES",
    "MERGE_TARGETS",
    "MISSION_GRAPH_CORE_ARCHETYPES",
    "MISSION_GRAPH_SEED_ARCHETYPES",
    "SWARM_SPECIALIST_ARCHETYPES",
    "WinningSwarmController",
    "default_winning_swarm_policy",
    "normalize_weapon_candidate_title",
    "normalize_winning_swarm_policy",
]
