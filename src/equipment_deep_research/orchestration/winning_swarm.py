"""Bounded elastic specialist swarm for winning-mechanism research.

The controller is deliberately provider-agnostic.  It plans logical specialist
tasks, validates their isolated contributions and manages the candidate ledger;
the Agent provider remains responsible for executing each task in its own
governed session.
"""

from __future__ import annotations

from collections import Counter
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

# Proposal names are communication aids, never claims that a named programme
# exists.  Keeping this rule next to swarm planning makes it available before
# S6, where names otherwise arrive already template-shaped.
QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION = (
    "命名先由独立Codex会话基于完整Query与已确定的主装备构型作语义判断：逐一核对主装备本体、"
    "投送/发射方式、目标、直接作战作用与关键机理，再自然命名；不得按词表、正则、共享示例或"
    "固定代号模板拼接名称。新研候选可在确有表达价值时采用‘可辨识的中文代号（可选）+Query专属"
    "构型/任务特征+单一具体武器对象’；没有自然且可解释的代号时，直接使用准确的装备描述名称。"
    "代号必须从本Query的任务对象、交战环境、关键机理或直接战果中原创推导；其语义必须能对应说明"
    "该武器的主要作战作用、目标或制胜机理，不能只是无关的修辞。不得复用共享示例、真实项目名"
    "或把代号当作已列装事实。"
    "名称中不得出现‘Query相关型号’、‘Query专属型号’、‘相关型号’等研究元话语，也不得从"
    "Query反推出虚构型号；公开型号只能作为证据基线，不是新研候选名称。"
    "代号后必须保留完整的弹、机、车、艇、发射舱、拦截器或效应器等主装备身份，不能只写代号、"
    "‘系统’、‘火力’、‘平台’、‘弹药’、‘弹群’或泛化武器类别；必须收敛为巡飞弹、导弹、"
    "无人僚机/攻击无人机、拦截器、鱼雷、发射车、发射舱或定向能效应器等可单独研制和试验的"
    "具体武器装备。现役升级项不强制添加代号。"
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
        "merge_target": "S4",
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
        "merge_target": "S4",
        "residuals": ["equipment_not_concrete", "engineering_feasibility_insufficient"],
    },
    "equipment_capability_image_repairer": {
        "display_name": "装备能力画像定向修复",
        "purpose": (
            "依据专家残差重写单一候选的装备能力闭环，贯通任务效果、作战运用、功能约束、"
            "体系接口、具体装备、公开基线、失效边界和验证指标；通信、算法、网关和治理"
            "只能作为接口。若证据不足，必须删除或收窄无法证明的构型、效能、成本与产能"
            "主张，改为证据边界内的固定构型和阶段目标，不能只追加验证要求。"
        ),
        "merge_target": "S4",
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
        "display_name": "证据核验",
        "purpose": "核验公开基线、事实引用、反证和不确定性，清除无效证据编号。",
        "merge_target": "S5",
        "residuals": ["evidence_insufficient", "unsupported_precision"],
    },
    "validation_experiment_designer": {
        "display_name": "验证试验设计",
        "purpose": "形成可证伪的指标、对照、试验步骤和淘汰条件，不虚构效能比例。",
        "merge_target": "S6",
        "residuals": ["validation_route_missing"],
    },
    "independent_portfolio_reviewer": {
        "display_name": "独立组合评审",
        "purpose": "独立审查候选组合的非支配性、证据边界、反适应韧性和装备落点。",
        "merge_target": "S6",
        "residuals": [],
    },
    "quality_expert_judge": {
        "display_name": "制胜机理质量专家评判",
        "purpose": "只读盲评候选的领域契合、装备能力落点、创新性、军事价值、因果可信度、证据质量和工程可行性，并给出可审计淘汰理由。",
        "merge_target": "convergence",
        "residuals": [],
    },
}

MISSION_GRAPH_SEED_ARCHETYPES: dict[str, tuple[str, ...]] = {
    "S1": ("opponent_system_modeler", "adversary_adaptation_analyst", "weak_signal_scout"),
    "S2": ("operational_baseline_analyst", "competitive_coa_designer", "baseline_delta_analyst"),
    "S3": (
        "disruptive_mechanism_generator",
        "adversary_counter_adaptation_red_team",
        "direct_combat_equipment_generator",
        "remote_precision_munition_generator",
        "mass_scalable_combat_family_generator",
        "cross_scenario_stress_tester",
    ),
    "S4": ("frontier_equipment_miner", "equipment_realization_architect"),
    "S5": ("evidence_verifier", "trl_cost_industrial_auditor"),
    "S6": ("validation_experiment_designer", "independent_portfolio_reviewer"),
}

DYNAMIC_V2_MISSION_GRAPH_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("S1", "opponent_system_modeler"),
    ("S2", "operational_baseline_analyst"),
    ("S1", "adversary_adaptation_analyst"),
    ("S2", "competitive_coa_designer"),
    ("S3", "disruptive_mechanism_generator"),
    ("S4", "frontier_equipment_miner"),
    ("S5", "evidence_verifier"),
    ("S6", "validation_experiment_designer"),
    ("S3", "adversary_counter_adaptation_red_team"),
    ("S3", "direct_combat_equipment_generator"),
    ("S3", "remote_precision_munition_generator"),
    ("S3", "mass_scalable_combat_family_generator"),
    ("S4", "equipment_realization_architect"),
    ("S5", "trl_cost_industrial_auditor"),
    ("S6", "independent_portfolio_reviewer"),
    ("S3", "cross_scenario_stress_tester"),
)

MISSION_GRAPH_CORE_ARCHETYPES: dict[str, dict[str, Any]] = {
    "opponent_system_modeler": {
        "display_name": "对手体系建模", "purpose": "建立对手体系、任务链、关键依赖和可验证断点，形成S1竞争性底图。",
        "merge_target": "S1", "residuals": ["causal_chain_broken", "counter_adaptation_unresolved"],
    },
    "adversary_adaptation_analyst": {
        "display_name": "对手适应研判", "purpose": "独立构造对手适应路径，识别我方假设最早失效节点和预警信号。",
        "merge_target": "S1", "residuals": ["counter_adaptation_unresolved"],
    },
    "operational_baseline_analyst": {
        "display_name": "作战运用基线", "purpose": "建立现行任务链与战法基线，定位S2可改变的行动、资源和时序变量。",
        "merge_target": "S2", "residuals": ["baseline_missing"],
    },
    "competitive_coa_designer": {
        "display_name": "竞争战法设计", "purpose": "并行构造机理不同的行动方案，比较直接军事效果、代价与失效边界。",
        "merge_target": "S2", "residuals": ["novelty_insufficient", "military_effect_missing"],
    },
}


def _all_role_archetypes() -> dict[str, dict[str, Any]]:
    return {**SWARM_SPECIALIST_ARCHETYPES, **MISSION_GRAPH_CORE_ARCHETYPES}


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
        "max_dynamic_instances": 18 if dynamic_v2 else 12,
        "max_concurrency": 6,
        "max_waves": 3,
        "mission_graph_min_instances": 8 if dynamic_v2 else 4,
        "mission_graph_target_instances": 12 if dynamic_v2 else 4,
        "mission_graph_max_instances": 18 if dynamic_v2 else 12,
        "minimum_expected_gain": 0.03,
        "breadth_hypothesis_minimum": 1,
        "breadth_hypothesis_maximum": 12,
        # Direction count is an output of evidence and independent combat
        # utility, not a five-card production quota.  Dynamic v2 can retain
        # every separately evidenced weapon direction up to a bounded review
        # capacity; the lower bound only prevents an empty deliverable.
        "finalist_minimum": 1 if quality_cluster else 2,
        "finalist_maximum": 12 if quality_cluster else 4,
        "minimum_direct_combat_equipment": 1 if quality_cluster else 0,
        "preferred_distinct_direct_equipment": 1 if quality_cluster else 0,
        "recursive_recruitment_allowed": False,
        "raw_session_sharing_allowed": False,
        "expert_judge_enabled": quality_cluster,
        "expert_judge_required": quality_cluster,
        "expert_candidate_pool_maximum": 10 if quality_cluster else 8,
        "expert_judge_minimum_score": 0.72,
        "expert_judge_critical_dimension_minimum": 0.60,
        "expert_repair_enabled": quality_cluster,
        "expert_repair_max_candidates": 6 if dynamic_v2 else 4,
        "expert_repair_minimum_score": 0.70,
        "expert_repair_reserved_instances": 6 if dynamic_v2 else 4,
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
    maximum_instances = 18 if dynamic_v2 else 12
    maximum_concurrency = 6
    minimum_instances = 8 if dynamic_v2 else 1
    base.update(
        {
            "policy_id": policy_id,
            "enabled": bool(base["enabled"] if enabled is None else enabled),
            "max_dynamic_instances": _bounded_int(
                raw.get("max_dynamic_instances"), minimum_instances, maximum_instances,
                int(base["max_dynamic_instances"]),
            ),
            "max_concurrency": _bounded_int(
                raw.get("max_concurrency"), 1, maximum_concurrency,
                int(base["max_concurrency"]),
            ),
            "max_waves": _bounded_int(raw.get("max_waves"), 1, 3, 3),
            "mission_graph_min_instances": _bounded_int(
                raw.get("mission_graph_min_instances"), minimum_instances,
                maximum_instances, int(base["mission_graph_min_instances"]),
            ),
            "mission_graph_target_instances": _bounded_int(
                raw.get("mission_graph_target_instances"), minimum_instances,
                maximum_instances, int(base["mission_graph_target_instances"]),
            ),
            "mission_graph_max_instances": _bounded_int(
                raw.get("mission_graph_max_instances"), minimum_instances,
                maximum_instances, int(base["mission_graph_max_instances"]),
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
            "finalist_minimum": _bounded_int(
                raw.get("finalist_minimum"), 1, 12 if quality_cluster else 7,
                1 if quality_cluster else 2,
            ),
            "finalist_maximum": _bounded_int(
                raw.get("finalist_maximum"), 1, 12 if quality_cluster else 7,
                12 if quality_cluster else 4,
            ),
            "minimum_direct_combat_equipment": _bounded_int(
                raw.get("minimum_direct_combat_equipment"),
                0,
                12 if quality_cluster else 7,
                1 if quality_cluster else 0,
            ),
            "preferred_distinct_direct_equipment": _bounded_int(
                raw.get("preferred_distinct_direct_equipment"),
                0,
                12 if quality_cluster else 7,
                1 if quality_cluster else 0,
            ),
            "recursive_recruitment_allowed": False,
            "raw_session_sharing_allowed": False,
            "expert_judge_enabled": bool(
                raw.get("expert_judge_enabled", quality_cluster)
            ),
            "expert_judge_required": bool(
                raw.get("expert_judge_required", quality_cluster)
            ),
            "expert_candidate_pool_maximum": _bounded_int(
                raw.get("expert_candidate_pool_maximum"),
                5,
                12,
                10 if quality_cluster else 8,
            ),
            "expert_judge_minimum_score": _bounded_float(
                raw.get("expert_judge_minimum_score"), 0.0, 1.0, 0.72
            ),
            "expert_judge_critical_dimension_minimum": _bounded_float(
                raw.get("expert_judge_critical_dimension_minimum"),
                0.0,
                1.0,
                0.60,
            ),
            "expert_repair_enabled": bool(
                raw.get("expert_repair_enabled", quality_cluster)
            ),
            "expert_repair_max_candidates": _bounded_int(
                raw.get("expert_repair_max_candidates"), 0, 6,
                6 if dynamic_v2 else 4,
            ),
            "expert_repair_minimum_score": _bounded_float(
                raw.get("expert_repair_minimum_score"), 0.0, 1.0, 0.70
            ),
            "expert_repair_reserved_instances": _bounded_int(
                raw.get("expert_repair_reserved_instances"), 0, 6,
                6 if dynamic_v2 else 4,
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
        min(int(base["mission_graph_max_instances"]), int(base["mission_graph_target_instances"])),
    )
    requested_archetypes = _text_list(raw.get("archetypes", []), limit=16)
    base["archetypes"] = [
        item for item in requested_archetypes if item in SWARM_SPECIALIST_ARCHETYPES
    ] or list(SWARM_SPECIALIST_ARCHETYPES)
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
            "baseline_delta_analyst",
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
            r"[^a-z0-9_]+", "_", str(value.get("archetype") or "dynamic_specialist").lower()
        ).strip("_")[:80]
        if not archetype:
            raise ValueError("dynamic role requires an archetype")
        catalog = _all_role_archetypes()
        spec = catalog.get(archetype, {})
        display_name = str(value.get("display_name") or spec.get("display_name") or archetype).strip()[:120]
        purpose = str(value.get("purpose") or spec.get("purpose") or "").strip()[:600]
        if not purpose:
            raise ValueError("dynamic role requires a bounded purpose")
        permitted_skills = set(str(item) for item in allowed_skill_ids)
        requested_skills = _text_list(value.get("skill_ids", allowed_skill_ids), limit=8)
        skill_ids = [item for item in requested_skills if item in permitted_skills]
        permitted_tools = set(str(item) for item in allowed_tool_ids)
        tool_ids = [
            item for item in _text_list(value.get("tool_ids", []), limit=12)
            if item in permitted_tools
        ]
        residuals = _text_list(
            value.get("trigger_residuals", spec.get("residuals", [])), limit=8
        )
        methodology = _text_list(
            value.get(
                "methodology",
                ["只处理声明的质量残差", "依据公开证据形成结构化增量", "只写入声明的合并节点"],
            ),
            limit=8,
        )
        quality_gates = _text_list(
            value.get(
                "quality_gates",
                ["事实推断与假设分离", "证据边界和失效条件明确", "不得产生无依据精确判断"],
            ),
            limit=10,
        )
        output_fields = _text_list(
            value.get(
                "output_fields",
                ["findings", "evidence_ids", "evidence_boundary", "failure_boundaries", "incremental_quality"],
            ),
            limit=12,
        )
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
    ) -> WinningMissionGraph:
        """Build an 8-18 instance S1-S6 graph with reserved repair capacity."""

        minimum = 8
        maximum = min(
            18,
            max(minimum, int(self.policy.get("mission_graph_max_instances", 18))),
        )
        target = _bounded_int(
            target_instances if target_instances is not None else self.policy.get("mission_graph_target_instances"),
            minimum,
            maximum,
            min(12, maximum),
        )
        if self.policy.get("policy_id") == "winning_swarm_dynamic_v2":
            selected = list(DYNAMIC_V2_MISSION_GRAPH_SEQUENCE[:target])
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
            query_first_clause = (
                f"当前唯一任务主题为“{topic}”。先从完整Query提取任务对象、威胁形态、作战阶段、"
                "地域环境、敌方反制和制胜矛盾，再执行本角色工作；不得先选择固定武器类别、公开"
                "型号或共享示例后反向拼接Query。产出的候选若替换成其他Query仍基本成立，必须判为"
                "模板化并重新发散。最终收敛对象必须是自身直接承担打击、歼灭、毁伤、杀伤、压制、"
                "突防、物理拦截或拒止任务的具体新质军事战斗武器；通信、算法、网络与保障只能作为"
                f"内部接口或约束。{QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION}"
            )
            contract = self.govern_role_contract(
                {
                    "archetype": archetype,
                    **spec,
                    "purpose": f"{spec.get('purpose', '')}{query_first_clause}",
                    "methodology": [
                        "先形成Query任务对象—威胁—阶段—制胜矛盾语义图",
                        "从Query语义开放发散候选，不从装备目录或公开型号起步",
                        "只处理声明的质量残差并写入声明节点",
                        "执行跨Query替换自检，淘汰换题后仍成立的模板候选",
                    ],
                    "quality_gates": [
                        "候选主装备、目标、发射域、毁伤机理与Query形成直接因果闭环",
                        "事实、推断与拟议假设分离，证据边界和失效条件明确",
                        "不得复用共享示例名称或以固定装备族覆盖主题",
                        "新研候选名称遵循Query专属代号（可选）+具体主装备身份；代号语义须对应武器作用、目标或制胜机理，且不把拟议代号写成事实",
                    ],
                },
                mission_node=node,
            )
            contracts.append(contract)
            instance_id = _stable_id(
                "winning-agent", execution_profile_id, topic, node, archetype, str(ordinal)
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
            if step == 3:
                depends_on = [
                    node_instances[node][ordinal % len(node_instances[node])]
                    for node in ("S1", "S2")
                    if node_instances[node]
                ]
            elif step == 4 and instance.archetype == "frontier_equipment_miner":
                depends_on = [
                    node_instances[node][ordinal % len(node_instances[node])]
                    for node in ("S1", "S2")
                    if node_instances[node]
                ]
            elif step == 4:
                upstream = node_instances["S3"]
                depends_on = [upstream[ordinal % len(upstream)]] if upstream else []
            elif step == 5 and instance.archetype == "evidence_verifier":
                upstream = node_instances["S3"]
                depends_on = [upstream[ordinal % len(upstream)]] if upstream else []
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
        if expected_quality_gain < float(self.policy["minimum_expected_gain"]):
            raise ValueError("expected quality gain is below recruitment threshold")
        instance_id = _stable_id(
            "winning-agent", graph.graph_id, contract.role_contract_id,
            hypothesis_id, str(len(graph.agent_instances) + 1),
        )
        node = contract.mission_node
        dependency_nodes = CORE_STEP_DEPENDENCIES.get(int(node[1:]), ()) if node.startswith("S") else ()
        resolved_dependencies = (
            list(dict.fromkeys(str(item) for item in depends_on if str(item)))
            if depends_on is not None
            else [
                item.instance_id
                for item in graph.agent_instances
                if item.mission_node in {f"S{step}" for step in dependency_nodes}
            ]
        )
        wave = max((item.wave for item in graph.agent_instances if item.mission_node == node), default=len(graph.waves))
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
            ledger_id=_stable_id("hypothesis-ledger", *(item.hypothesis_id for item in ordered)),
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
            "receipt_id": _stable_id("merge-receipt", contribution.contribution_id, str(ledger.version)),
            "contribution_id": contribution.contribution_id,
            "hypothesis_id": contribution.hypothesis_id,
            "merge_target": contribution.merge_target,
            "base_ledger_version": contribution.base_ledger_version,
        }
        if contribution.base_ledger_version != ledger.version:
            return ledger, MergeReceipt(
                **receipt_base, resulting_ledger_version=ledger.version,
                status="rebase_required", conflicts=["stale_ledger_version"], rebase_required=True,
            )
        hypothesis = next(
            (item for item in ledger.hypotheses if item.hypothesis_id == contribution.hypothesis_id),
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
                **receipt_base, resulting_ledger_version=ledger.version,
                status="rejected", conflicts=conflicts,
            )
        patch = contribution.hypothesis_patch
        specialist = SpecialistContribution(
            contribution_id=contribution.contribution_id,
            task_id=contribution.contribution_id,
            agent_instance_id=contribution.agent_instance_id,
            hypothesis_id=contribution.hypothesis_id,
            merge_target=contribution.merge_target,
            findings=_text_list(patch.get("findings", []), limit=8),
            mechanism_chain_updates=_text_list(patch.get("mechanism_chain_updates", []), limit=8),
            direct_military_effects=_text_list(patch.get("direct_military_effects", []), limit=6),
            equipment_forms=_text_list(patch.get("equipment_forms", []), limit=6),
            project_function=str(patch.get("project_function", "")).strip()[:700],
            system_interfaces=_text_list(patch.get("system_interfaces", []), limit=8),
            novelty_delta=str(patch.get("novelty_delta", ""))[:900],
            naming_rationale=str(patch.get("naming_rationale", ""))[:900],
            decisive_advantage_thesis=str(
                patch.get("decisive_advantage_thesis", "")
            )[:900],
            cross_query_distinction=str(
                patch.get("cross_query_distinction", "")
            )[:900],
            evidence_boundary=str(patch.get("evidence_boundary", ""))[:800],
            implementation_path=str(patch.get("implementation_path", ""))[:800],
            evidence_ids=list(contribution.evidence_ids),
            counterevidence=_text_list(patch.get("counterevidence", []), limit=8),
            adversary_adaptations=_text_list(patch.get("adversary_adaptations", []), limit=8),
            failure_boundaries=_text_list(patch.get("failure_boundaries", []), limit=8),
            trl_constraints=_text_list(patch.get("trl_constraints", []), limit=6),
            cost_constraints=_text_list(patch.get("cost_constraints", []), limit=6),
            industrial_constraints=_text_list(patch.get("industrial_constraints", []), limit=6),
            cross_scenario_results=_text_list(patch.get("cross_scenario_results", []), limit=8),
            validation_plan=_text_list(patch.get("validation_plan", []), limit=8),
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
        hypotheses = [updated if item.hypothesis_id == updated.hypothesis_id else item for item in ledger.hypotheses]
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
        if not any(item.hypothesis_id == contribution.hypothesis_id for item in ledger.hypotheses):
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
                "novelty": 1.0 if hypothesis.novelty_delta else 0.0,
                "robustness": min(1.0, (len(hypothesis.adversary_adaptations) + len(hypothesis.cross_scenario_results)) / 4),
                "feasibility": 1.0 if hypothesis.trl_constraints and hypothesis.cost_constraints and hypothesis.industrial_constraints else 0.0,
            }
        hypothesis_ids = [item.hypothesis_id for item in ledger.hypotheses]
        hypothesis_by_id = {
            item.hypothesis_id: item for item in ledger.hypotheses
        }
        candidate_ids = [
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
        portfolio_family_by_id = {
            item: (
                "expert:"
                + (expert_assessments or {})[item].equipment_classification.strip().lower()
                if item in (expert_assessments or {})
                and (expert_assessments or {})[item].equipment_classification.strip().lower()
                in {"system_link", "support", "support_only", "non_equipment"}
                else _equipment_family_signature(hypothesis_by_id[item])
            )
            for item in candidate_ids
        }

        def dominates(left: str, right: str) -> bool:
            dimensions = set(scores[left]) | set(scores[right])
            left_values = [float(scores[left].get(key, 0.0)) for key in dimensions]
            right_values = [float(scores[right].get(key, 0.0)) for key in dimensions]
            return all(a >= b for a, b in zip(left_values, right_values)) and any(a > b for a, b in zip(left_values, right_values))

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
            family_by_id=portfolio_family_by_id,
        )
        maximum = int(self.policy.get("finalist_maximum", 4))
        minimum = min(
            maximum,
            int(self.policy.get("finalist_minimum", 2)),
            len(candidate_ids),
        )
        # Pareto ranking is a prioritisation signal, not a licence to discard
        # a separately evidenced and independently useful weapon direction.
        # Retain the complete passing pool (within the audited S6 capacity),
        # then use the front to order it.  This is what allows a query with
        # seven or more reliable new weapon concepts to reach S6 intact.
        selected = _diverse_portfolio_order(
            [*front, *[item for item in candidate_ids if item not in front]],
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
            family_by_id=portfolio_family_by_id,
        )[:maximum]
        if len(selected) < minimum:
            ranked_remainder = _diverse_portfolio_order(
                [item for item in candidate_ids if item not in selected],
                hypothesis_by_id=hypothesis_by_id,
                scores=scores,
                prior_ids=selected,
                family_by_id=portfolio_family_by_id,
            )
            selected.extend(ranked_remainder[: minimum - len(selected)])
        # Pareto selection can still fill the portfolio with two wording or
        # operating-concept variants of the same concrete equipment family.
        # Keep the strongest selected member per family, then backfill from
        # already-passed candidates in other families. Only reuse a family
        # when the passing pool lacks enough distinct equipment directions.
        selected_target = len(selected)
        distinct_selected: list[str] = []
        selected_families: set[str] = set()
        for item in selected:
            family = portfolio_family_by_id[item]
            if family in selected_families:
                continue
            distinct_selected.append(item)
            selected_families.add(family)
        ranked_replacements = _diverse_portfolio_order(
            [item for item in candidate_ids if item not in distinct_selected],
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
            prior_ids=distinct_selected,
            family_by_id=portfolio_family_by_id,
        )
        for item in ranked_replacements:
            family = portfolio_family_by_id[item]
            if family in selected_families:
                continue
            distinct_selected.append(item)
            selected_families.add(family)
            if len(distinct_selected) >= selected_target:
                break
        if len(distinct_selected) < selected_target:
            distinct_selected.extend(
                item
                for item in ranked_replacements
                if item not in distinct_selected
            )
        selected = distinct_selected[:selected_target]
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
            family_by_id=portfolio_family_by_id,
        )
        distinct_direct_pool: list[str] = []
        distinct_direct_families: set[str] = set()
        for item in direct_pool:
            family = portfolio_family_by_id[item]
            if family in distinct_direct_families:
                continue
            distinct_direct_pool.append(item)
            distinct_direct_families.add(family)
        # When the assessed pool already contains enough direct combat
        # weapons to fill the available S6 card capacity, keep the portfolio
        # focused on those effects instead of letting a high-scoring support
        # link displace a weapon card. Support still remains in the ledger as
        # a cross-card constraint and can be selected when the query calls for
        # it or the direct pool is smaller than capacity.
        if len(direct_pool) >= maximum:
            selected = list(direct_pool[:maximum])
        minimum_direct = min(
            maximum,
            int(self.policy.get("minimum_direct_combat_equipment", 4)),
        )
        preferred_distinct_direct = min(
            maximum,
            int(
                self.policy.get(
                    "preferred_distinct_direct_equipment",
                    minimum_direct,
                )
            ),
        )
        direct_target = (
            preferred_distinct_direct
            if len(distinct_direct_pool) >= preferred_distinct_direct
            else minimum_direct
        )
        selected_direct_families = {
            portfolio_family_by_id[item]
            for item in selected
            if item in direct_pool
        }
        if (
            len(direct_pool) >= direct_target
            and len(selected_direct_families) < direct_target
        ):
            required_direct = (
                distinct_direct_pool[:direct_target]
                if len(distinct_direct_pool) >= direct_target
                else direct_pool[:direct_target]
            )
            ranked_all = sorted(
                candidate_ids,
                key=lambda item: (-sum(scores[item].values()), item),
            )
            selected = list(dict.fromkeys([
                *required_direct,
                *selected,
                *ranked_all,
            ]))[:maximum]
        selected = _diverse_portfolio_order(
            selected,
            hypothesis_by_id=hypothesis_by_id,
            scores=scores,
            family_by_id=portfolio_family_by_id,
        )[:maximum]
        if selected and not any(
            hypothesis_by_id[item].implementation_path == "upgrade"
            for item in selected
        ):
            upgrade_pool = _diverse_portfolio_order(
                [
                    item
                    for item in candidate_ids
                    if item not in selected
                    and hypothesis_by_id[item].implementation_path == "upgrade"
                ],
                hypothesis_by_id=hypothesis_by_id,
                scores=scores,
                prior_ids=selected,
                family_by_id=portfolio_family_by_id,
            )
            if upgrade_pool:
                selected[-1] = upgrade_pool[0]
                selected = _diverse_portfolio_order(
                    list(dict.fromkeys(selected)),
                    hypothesis_by_id=hypothesis_by_id,
                    scores=scores,
                    family_by_id=portfolio_family_by_id,
                )[:maximum]
        rejected = [item for item in hypothesis_ids if item not in selected]
        reasons = {
            item: [other for other in hypothesis_ids if other != item and dominates(other, item)]
            for item in rejected
        }
        return PortfolioDecision(
            decision_id=_stable_id("portfolio-decision", ledger.ledger_id, str(ledger.version), *selected),
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
                    and (expert_assessments or {})[item].passed
                    for item in selected
                )
            ),
        )

    @staticmethod
    def equipment_family_signature(hypothesis: WinningHypothesis) -> str:
        return _equipment_family_signature(hypothesis)

    @staticmethod
    def equipment_family_counts(
        hypotheses: Sequence[WinningHypothesis],
    ) -> dict[str, int]:
        return dict(
            Counter(_equipment_family_signature(item) for item in hypotheses)
        )

    def passed_portfolio_coverage(
        self,
        ledger: HypothesisLedgerVersion,
        expert_assessments: Mapping[str, WinningExpertAssessment],
    ) -> dict[str, Any]:
        """Describe whether passed candidates can form the intended portfolio.

        Counting expert passes alone is insufficient: several accepted wording
        variants may still represent the same weapon family, while a system
        link can occupy the fifth slot without adding a concrete weapon.  The
        dynamic quality profile therefore keeps the bounded completion lane
        open until both the direction count and direct-family breadth are met.
        """

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
        direct_family_counts = self.equipment_family_counts(direct)
        finalist_minimum = int(self.policy.get("finalist_minimum", 2))
        minimum_direct = min(
            finalist_minimum,
            int(self.policy.get("minimum_direct_combat_equipment", 0)),
        )
        preferred_distinct_direct = min(
            finalist_minimum,
            int(
                self.policy.get(
                    "preferred_distinct_direct_equipment",
                    minimum_direct,
                )
            ),
        )
        passed_count = len(passed)
        direct_count = len(direct)
        distinct_direct_family_count = len(direct_family_counts)
        return {
            "ready": (
                passed_count >= finalist_minimum
                and direct_count >= minimum_direct
                and distinct_direct_family_count >= preferred_distinct_direct
            ),
            "passed_count": passed_count,
            "direct_combat_equipment_count": direct_count,
            "distinct_direct_equipment_family_count": (
                distinct_direct_family_count
            ),
            "direct_equipment_family_counts": direct_family_counts,
            "finalist_minimum": finalist_minimum,
            "minimum_direct_combat_equipment": minimum_direct,
            "preferred_distinct_direct_equipment": (
                preferred_distinct_direct
            ),
        }

    def select_unassessed_portfolio_candidates(
        self,
        ledger: HypothesisLedgerVersion,
        expert_assessments: Mapping[str, WinningExpertAssessment],
        *,
        maximum: int | None = None,
    ) -> list[str]:
        """Select diverse, gate-passing ledger rows for the bounded re-review.

        The first blind review intentionally receives a compact candidate pool.
        When that pool yields too few finalists, the second review should first
        use strong candidates already produced by the mission graph instead of
        spending another generator call on replacement prose.  The expert gate
        remains authoritative: this method only chooses what to review and
        never promotes an unassessed or failed candidate.
        """

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
        hypotheses_by_id = {
            item.hypothesis_id: item for item in ledger.hypotheses
        }
        gate_by_id = {
            item.hypothesis_id: self.evaluate_gate(item, stage="final")
            for item in ledger.hypotheses
            if item.hypothesis_id not in assessed_ids
        }
        candidate_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if item.hypothesis_id not in assessed_ids
            and gate_by_id[item.hypothesis_id].passed
        ]
        if not candidate_ids:
            return []
        scores = {
            hypothesis_id: {
                "quality": gate_by_id[hypothesis_id].score,
                "evidence": min(
                    1.0,
                    len(hypotheses_by_id[hypothesis_id].evidence_ids) / 3,
                ),
                "robustness": min(
                    1.0,
                    (
                        len(
                            hypotheses_by_id[
                                hypothesis_id
                            ].adversary_adaptations
                        )
                        + len(
                            hypotheses_by_id[
                                hypothesis_id
                            ].cross_scenario_results
                        )
                    )
                    / 4,
                ),
            }
            for hypothesis_id in candidate_ids
        }
        family_by_id = {
            hypothesis_id: _equipment_family_signature(
                hypotheses_by_id[hypothesis_id]
            )
            for hypothesis_id in candidate_ids
        }
        passed_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if item.hypothesis_id in expert_assessments
            and expert_assessments[item.hypothesis_id].passed
        ]
        ordered = _diverse_portfolio_order(
            candidate_ids,
            hypothesis_by_id=hypotheses_by_id,
            scores=scores,
            prior_ids=passed_ids,
            family_by_id=family_by_id,
        )
        selected: list[str] = []
        passed_has_upgrade = any(
            hypotheses_by_id[item].implementation_path == "upgrade"
            for item in passed_ids
            if item in hypotheses_by_id
        )
        if not passed_has_upgrade:
            upgrade = next(
                (
                    item
                    for item in ordered
                    if hypotheses_by_id[item].implementation_path == "upgrade"
                ),
                None,
            )
            if upgrade is not None:
                selected.append(upgrade)
        selected.extend(
            item
            for item in ordered
            if _is_direct_combat_equipment(hypotheses_by_id[item])
        )
        selected.extend(ordered)
        return list(dict.fromkeys(selected))[:limit]

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
            "equipment_capability_fit": 0.14,
            "innovation": 0.15,
            "military_value": 0.16,
            "decisive_advantage": 0.13,
            "query_specificity": 0.10,
            "causal_coherence": 0.09,
            "credibility": 0.08,
            "engineering_feasibility": 0.04,
            "robustness": 0.03,
        }
        weighted_score = round(
            sum(scores[name] * weights[name] for name in dimension_names), 4
        )
        verdict = str(value.get("verdict", "revise")).strip().lower()
        if verdict not in {"pass", "revise", "reject"}:
            verdict = "revise"
        critical_minimum = float(
            self.policy["expert_judge_critical_dimension_minimum"]
        )
        critical_dimensions = (
            "domain_relevance",
            "equipment_capability_fit",
            "military_value",
            "decisive_advantage",
            "query_specificity",
            "credibility",
        )
        passed = (
            verdict == "pass"
            and weighted_score >= float(self.policy["expert_judge_minimum_score"])
            and all(scores[name] >= critical_minimum for name in critical_dimensions)
        )
        rejection_reasons = _text_list(value.get("rejection_reasons", []), limit=8)
        if not passed and not rejection_reasons:
            rejection_reasons = ["专家评判未达到综合分或关键维度门槛"]
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
            residuals=_text_list(value.get("residuals", []), limit=10),
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
        if (
            scores.get("equipment_capability_fit", 0.0) < 0.82
            or assessment.equipment_classification
            in {"system_link", "support", "non_materiel"}
        ):
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
                if all(
                    dependency in satisfied
                    for dependency in dependencies[step]
                )
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
        candidates = sorted(hypotheses, key=lambda item: (-item.score, item.hypothesis_id))
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
                if task.expected_quality_gain < float(self.policy["minimum_expected_gain"]):
                    continue
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
        return priority.get(residual, "evidence_verifier")

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
            elif all(dependency in completed_task_ids for dependency in task.depends_on):
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
        changed_variable = str(
            value.get("changed_confrontation_variable")
            or value.get("changed_variable")
            or ""
        ).strip()[:600]
        mechanism_chain = _text_list(
            value.get("mechanism_chain", value.get("winning_mechanism_chain", [])),
            limit=8,
        )
        direct_effects = _text_list(
            value.get("direct_military_effects", value.get("direct_military_effect", [])),
            limit=6,
        )
        equipment_forms = _text_list(
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
        project_function = str(value.get("project_function", "")).strip()[:700]
        if not project_function and direct_effects:
            project_function = direct_effects[0][:700]
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
            nearest_public_baseline=str(
                value.get("nearest_public_baseline")
                or value.get("current_baseline")
                or value.get("baseline")
                or ""
            ).strip()[:900],
            changed_confrontation_variable=changed_variable,
            mechanism_chain=mechanism_chain,
            direct_military_effects=direct_effects,
            equipment_forms=equipment_forms,
            project_function=project_function,
            novelty_delta=str(value.get("novelty_delta") or value.get("novelty") or "").strip()[:900],
            naming_rationale=str(value.get("naming_rationale", "")).strip()[:900],
            decisive_advantage_thesis=str(
                value.get("decisive_advantage_thesis", "")
            ).strip()[:900],
            cross_query_distinction=str(
                value.get("cross_query_distinction", "")
            ).strip()[:900],
            system_interfaces=_text_list(value.get("system_interfaces", []), limit=8),
            evidence_ids=evidence_ids,
            counterevidence=_text_list(value.get("counterevidence", []), limit=8),
            adversary_adaptations=_text_list(value.get("adversary_adaptations", []), limit=8),
            failure_boundaries=_text_list(value.get("failure_boundaries", []), limit=8),
            trl_constraints=_text_list(value.get("trl_constraints", []), limit=6),
            cost_constraints=_text_list(value.get("cost_constraints", []), limit=6),
            industrial_constraints=_text_list(value.get("industrial_constraints", []), limit=6),
            cross_scenario_results=_text_list(value.get("cross_scenario_results", []), limit=8),
            validation_plan=_text_list(value.get("validation_plan", []), limit=8),
            evidence_boundary=str(value.get("evidence_boundary", "")).strip()[:800],
            implementation_path=str(value.get("implementation_path", "")).strip()[:800],
            merge_targets=[task.merge_target],
            source_task_ids=[task.task_id],
        )
        gate = self.evaluate_gate(hypothesis, stage="breadth")
        preflight_residuals = list(gate.residuals)
        if _weapon_title_needs_concretization(title):
            # The final portrait writer must not be the routine naming
            # repairer.  Resolve an ambiguous carrier name in the swarm's
            # equipment-realization wave while target/effect facts are fresh.
            preflight_residuals.append("weapon_name_not_concrete")
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
            raise ValueError("specialist contribution requires hypothesis_id + merge_target")
        reported_hypothesis = str(value.get("hypothesis_id") or task.hypothesis_id)
        reported_target = str(value.get("merge_target") or task.merge_target)
        if reported_hypothesis != task.hypothesis_id or reported_target != task.merge_target:
            raise ValueError("specialist contribution crossed its declared merge boundary")
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
        direct_effects = _text_list(value.get("direct_military_effects", []), limit=6)
        project_function = str(value.get("project_function", "")).strip()[:700]
        if not project_function and direct_effects:
            project_function = direct_effects[0][:700]
        return SpecialistContribution(
            contribution_id=_stable_id("contribution", task.task_id, task.hypothesis_id),
            task_id=task.task_id,
            agent_instance_id=task.agent_instance_id,
            hypothesis_id=task.hypothesis_id,
            merge_target=task.merge_target,
            findings=_text_list(value.get("findings", []), limit=8),
            mechanism_chain_updates=_text_list(value.get("mechanism_chain_updates", []), limit=8),
            direct_military_effects=direct_effects,
            equipment_forms=_text_list(value.get("equipment_forms", []), limit=6),
            project_function=project_function,
            system_interfaces=_text_list(value.get("system_interfaces", []), limit=8),
            novelty_delta=str(value.get("novelty_delta", "")).strip()[:900],
            naming_rationale=str(value.get("naming_rationale", "")).strip()[:900],
            decisive_advantage_thesis=str(
                value.get("decisive_advantage_thesis", "")
            ).strip()[:900],
            cross_query_distinction=str(
                value.get("cross_query_distinction", "")
            ).strip()[:900],
            evidence_boundary=str(value.get("evidence_boundary", "")).strip()[:800],
            implementation_path=str(value.get("implementation_path", "")).strip()[:800],
            evidence_ids=evidence_ids,
            counterevidence=_text_list(value.get("counterevidence", []), limit=8),
            adversary_adaptations=_text_list(value.get("adversary_adaptations", []), limit=8),
            failure_boundaries=_text_list(value.get("failure_boundaries", []), limit=8),
            trl_constraints=_text_list(value.get("trl_constraints", []), limit=6),
            cost_constraints=_text_list(value.get("cost_constraints", []), limit=6),
            industrial_constraints=_text_list(value.get("industrial_constraints", []), limit=6),
            cross_scenario_results=_text_list(value.get("cross_scenario_results", []), limit=8),
            validation_plan=_text_list(value.get("validation_plan", []), limit=8),
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

        minimum = float(self.policy["minimum_expected_gain"])
        recommendation = str(value.get("recommendation", "retain"))[:80]
        findings = _text_list(value.get("findings", []), limit=8)
        equipment_forms = _text_list(value.get("equipment_forms", []), limit=6)
        direct_effects = _text_list(
            value.get("direct_military_effects", []), limit=6
        )
        project_function = str(value.get("project_function", "")).strip()
        if not project_function and direct_effects:
            project_function = direct_effects[0]
        mechanism_updates = _text_list(
            value.get("mechanism_chain_updates", value.get("mechanism_chain", [])),
            limit=8,
        )
        novelty = str(value.get("novelty_delta", "")).strip()
        evidence_boundary = str(value.get("evidence_boundary", "")).strip()
        failure_boundaries = _text_list(
            value.get("failure_boundaries", []), limit=8
        )
        validation_plan = _text_list(value.get("validation_plan", []), limit=8)
        cross_scenario = _text_list(
            value.get("cross_scenario_results", []), limit=8
        )
        weapon_markers = (
            "导弹",
            "巡飞",
            "弹药",
            "战斗部",
            "效应器",
            "无人机",
            "无人平台",
            "拦截弹",
            "鱼雷",
            "水雷",
            "激光武器",
        )
        concrete_equipment = any(
            any(marker in form for marker in weapon_markers)
            and len(form.strip()) >= 6
            for form in equipment_forms
        )
        mechanism_difference = bool(mechanism_updates or novelty)
        evidence_bounded = bool(evidence_ids) and bool(
            evidence_boundary or failure_boundaries
        )
        structured_weapon_delta = bool(
            concrete_equipment
            and direct_effects
            and project_function
            and mechanism_difference
            and evidence_bounded
        )
        generic_substantive = bool(
            findings
            or validation_plan
            or failure_boundaries
            or cross_scenario
            or evidence_boundary
        )
        s6_validation_delta = mission_node == "S6" and bool(
            validation_plan and (failure_boundaries or evidence_boundary)
        )
        accepted = bool(
            recommendation != "reject"
            and generic_substantive
            and (
                reported_quality >= minimum
                or structured_weapon_delta
                or s6_validation_delta
            )
        )
        effective_quality = (
            max(reported_quality, minimum)
            if accepted and (structured_weapon_delta or s6_validation_delta)
            else reported_quality
        )
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
                else "reported_incremental_gain"
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
            raise ValueError("contribution hypothesis_id does not match ledger candidate")
        if contribution.merge_target not in MERGE_TARGETS:
            raise ValueError("invalid contribution merge_target")
        residuals = [
            item
            for item in hypothesis.residuals
            if item not in set(contribution.residuals_resolved)
        ]
        updated = replace(
            hypothesis,
            mechanism_chain=_dedupe([
                *hypothesis.mechanism_chain,
                *contribution.mechanism_chain_updates,
            ], 10),
            direct_military_effects=_dedupe([
                *hypothesis.direct_military_effects,
                *contribution.direct_military_effects,
            ], 8),
            equipment_forms=_dedupe([
                *hypothesis.equipment_forms,
                *contribution.equipment_forms,
            ], 8),
            project_function=(
                contribution.project_function or hypothesis.project_function
            ),
            system_interfaces=_dedupe([
                *hypothesis.system_interfaces,
                *contribution.system_interfaces,
            ], 10),
            novelty_delta=contribution.novelty_delta or hypothesis.novelty_delta,
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
            evidence_boundary=contribution.evidence_boundary or hypothesis.evidence_boundary,
            implementation_path=contribution.implementation_path or hypothesis.implementation_path,
            evidence_ids=_dedupe([*hypothesis.evidence_ids, *contribution.evidence_ids], 24),
            counterevidence=_dedupe([*hypothesis.counterevidence, *contribution.counterevidence], 12),
            adversary_adaptations=_dedupe([*hypothesis.adversary_adaptations, *contribution.adversary_adaptations], 12),
            failure_boundaries=_dedupe([*hypothesis.failure_boundaries, *contribution.failure_boundaries], 12),
            trl_constraints=_dedupe([*hypothesis.trl_constraints, *contribution.trl_constraints], 10),
            cost_constraints=_dedupe([*hypothesis.cost_constraints, *contribution.cost_constraints], 10),
            industrial_constraints=_dedupe([*hypothesis.industrial_constraints, *contribution.industrial_constraints], 10),
            cross_scenario_results=_dedupe([*hypothesis.cross_scenario_results, *contribution.cross_scenario_results], 12),
            validation_plan=_dedupe([*hypothesis.validation_plan, *contribution.validation_plan], 12),
            merge_targets=_dedupe([*hypothesis.merge_targets, contribution.merge_target], 7),
            source_task_ids=_dedupe([*hypothesis.source_task_ids, contribution.task_id], 12),
            residuals=residuals,
            status="challenging",
        )
        gate = self.evaluate_gate(updated, stage="targeted")
        return replace(updated, residuals=gate.residuals, score=gate.score)

    def evaluate_gate(self, hypothesis: WinningHypothesis, *, stage: str) -> SwarmGateResult:
        residuals: list[str] = []
        rejection_reasons: list[str] = []
        frontloaded_quality = self.policy.get("policy_id") in {
            "winning_swarm_dynamic_v2",
            "swarm_quality_v1",
            "winning_swarm_quality_v1",
        }
        if not hypothesis.nearest_public_baseline.strip():
            residuals.append("baseline_missing")
        if not hypothesis.changed_confrontation_variable.strip() or not hypothesis.mechanism_chain:
            residuals.append("causal_chain_broken")
        if not hypothesis.direct_military_effects:
            residuals.append("military_effect_missing")
        if frontloaded_quality:
            combat_effect_text = " ".join(
                [hypothesis.project_function, *hypothesis.direct_military_effects]
            )
            if not any(
                marker in combat_effect_text
                for marker in (
                    "打击",
                    "歼灭",
                    "毁伤",
                    "摧毁",
                    "杀伤",
                    "猎歼",
                    "拦截",
                    "压制",
                    "瘫痪",
                    "破障",
                    "拒止",
                )
            ):
                residuals.append("direct_combat_effect_unproven")
        if not hypothesis.novelty_delta.strip():
            residuals.append("novelty_insufficient")
        if frontloaded_quality:
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
        if (
            frontloaded_quality
            and not hypothesis.system_interfaces
        ):
            residuals.append("system_interfaces_missing")
        if frontloaded_quality:
            if _mixed_named_equipment_families(hypothesis):
                residuals.append("mixed_primary_equipment_families")
            if (
                _is_direct_combat_equipment(hypothesis)
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
            "decisive_advantage_missing": 0.14,
            "weapon_naming_unjustified": 0.05,
            "template_substitution_unresolved": 0.10,
            "equipment_not_concrete": 0.08,
            "project_function_missing": 0.08,
            "system_interfaces_missing": 0.04,
            "mixed_primary_equipment_families": 0.12,
            "equipment_object_evidence_missing": 0.12,
            "evidence_insufficient": 0.14,
            "counter_adaptation_unresolved": 0.08,
            "engineering_feasibility_insufficient": 0.06,
            "cross_scenario_unstable": 0.05,
            "validation_route_missing": 0.05,
        }
        score = 1.0 - sum(
            weight for residual, weight in dimension_weights.items() if residual in residuals
        )
        if "unsupported_precision" in residuals:
            score -= 0.20
        score = round(max(0.0, min(1.0, score)), 4)
        critical = {"baseline_missing", "causal_chain_broken", "military_effect_missing"}
        if frontloaded_quality:
            critical.update(
                {
                    "decisive_advantage_missing",
                    "weapon_naming_unjustified",
                    "template_substitution_unresolved",
                    "direct_combat_effect_unproven",
                }
            )
        if stage == "breadth":
            passed = score >= 0.45 and not critical.intersection(residuals)
        elif stage == "targeted":
            passed = score >= 0.62 and "unsupported_precision" not in residuals
        else:
            passed = score >= 0.70 and not residuals
        if not passed and not rejection_reasons and stage == "final":
            rejection_reasons.append("最终业务质量门仍存在未闭合残差")
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
        kept: list[WinningHypothesis] = []
        merged: list[dict[str, str]] = []
        for candidate in sorted(
            hypotheses,
            key=lambda item: (-item.score, -len(item.evidence_ids), item.hypothesis_id),
        ):
            duplicate = next(
                (
                    existing
                    for existing in kept
                    if _hypothesis_similarity(candidate, existing) >= 0.72
                ),
                None,
            )
            if duplicate is None:
                kept.append(candidate)
                continue
            merged.append(
                {
                    "source_hypothesis_id": candidate.hypothesis_id,
                    "target_hypothesis_id": duplicate.hypothesis_id,
                    "reason": "mechanism_semantic_duplicate",
                }
            )
        return kept, merged

    @staticmethod
    def semantic_hypothesis_match(
        candidate: WinningHypothesis,
        governed_candidates: Sequence[WinningHypothesis],
        *,
        minimum_similarity: float = 0.72,
    ) -> str:
        """Resolve an obsolete candidate id to its governed semantic peer."""

        ranked = sorted(
            (
                (_hypothesis_similarity(candidate, governed), governed)
                for governed in governed_candidates
            ),
            key=lambda row: (-row[0], -row[1].score, row[1].hypothesis_id),
        )
        if not ranked or ranked[0][0] < minimum_similarity:
            return ""
        return ranked[0][1].hypothesis_id

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
        minimum = int(self.policy["finalist_minimum"])
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
        if len(selected) < minimum:
            selected_ids = {item.hypothesis_id for item in selected}
            selected.extend(
                item
                for item in passing
                if item.hypothesis_id not in selected_ids
            )
            selected = selected[: min(maximum, max(minimum, len(selected)))]
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
                    or ["最终业务质量门未通过"]
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
                    "已通过单项质量门，但被更强候选在质量得分、证据覆盖、"
                    "反适应/跨场景稳健性或工程约束完整性上支配："
                    + "、".join(dominators[:3])
                ]
            else:
                selection_reasons[candidate.hypothesis_id] = [
                    "已通过单项质量门，但受候选组合容量上限"
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
                status=("finalist" if item.hypothesis_id in selected_ids else "rejected"),
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
            item
            for item in _text_list(values, limit=32)
            if item in valid_evidence_ids
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
        minimum_score = float(self.policy["expert_repair_minimum_score"])
        direct_categories = {"direct_combat", "unmanned_combat"}
        concrete_gap = sorted(
            (
                item
                for item in assessments.values()
                if item.passed
                and item.equipment_classification not in direct_categories
                and item.weighted_score >= minimum_score
            ),
            key=lambda item: (-item.weighted_score, item.hypothesis_id),
        )
        revisions = sorted(
            (
                item
                for item in assessments.values()
                if item.verdict == "revise"
                and item.weighted_score >= minimum_score
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
        if hypotheses:
            passed_direct_families = {
                _equipment_family_signature(hypotheses[item.hypothesis_id])
                for item in assessments.values()
                if item.passed
                and item.hypothesis_id in hypotheses
                and _is_direct_combat_equipment(
                    hypotheses[item.hypothesis_id],
                    item,
                )
            }

            def family_for(item: WinningExpertAssessment) -> str:
                hypothesis = hypotheses.get(item.hypothesis_id)
                return (
                    _equipment_family_signature(hypothesis)
                    if hypothesis is not None
                    else ""
                )

            def missing_family_diverse(
                rows: Sequence[WinningExpertAssessment],
            ) -> list[WinningExpertAssessment]:
                missing = sorted(
                    (
                        item
                        for item in rows
                        if family_for(item)
                        and family_for(item) not in passed_direct_families
                    ),
                    key=lambda item: (-item.weighted_score, item.hypothesis_id),
                )
                first_per_family: list[WinningExpertAssessment] = []
                seen_families: set[str] = set()
                for item in missing:
                    family = family_for(item)
                    if family in seen_families:
                        continue
                    first_per_family.append(item)
                    seen_families.add(family)
                return [
                    *first_per_family,
                    *(item for item in missing if item not in first_per_family),
                    *(
                        item
                        for item in rows
                        if item not in missing
                    ),
                ]

            direct_revisions = missing_family_diverse(direct_revisions)
            other_revisions = missing_family_diverse(other_revisions)

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


def _hypothesis_similarity(left: WinningHypothesis, right: WinningHypothesis) -> float:
    left_tokens = _tokens(
        " ".join(
            [
                left.title,
                left.changed_confrontation_variable,
                *left.mechanism_chain,
                *left.direct_military_effects,
            ]
        )
    )
    right_tokens = _tokens(
        " ".join(
            [
                right.title,
                right.changed_confrontation_variable,
                *right.mechanism_chain,
                *right.direct_military_effects,
            ]
        )
    )
    if not left_tokens or not right_tokens:
        return 0.0

    def jaccard(left_values: set[str], right_values: set[str]) -> float:
        if not left_values or not right_values:
            return 0.0
        return len(left_values & right_values) / len(left_values | right_values)

    semantic_overlap = jaccard(left_tokens, right_tokens)
    form_overlap = jaccard(
        _tokens(" ".join(left.equipment_forms)),
        _tokens(" ".join(right.equipment_forms)),
    )
    baseline_overlap = jaccard(
        _tokens(left.nearest_public_baseline),
        _tokens(right.nearest_public_baseline),
    )
    same_family = (
        _equipment_family_signature(left) == _equipment_family_signature(right)
    )
    # This is a conservative ledger guard after the Codex semantic pass.  It
    # catches wording variants of the same equipment thesis without using a
    # title-only match: main form, public baseline and complete mechanism/effect
    # semantics must agree.  Independent Codex judgement remains authoritative.
    weighted = (
        0.40 * semantic_overlap
        + 0.25 * form_overlap
        + 0.15 * baseline_overlap
        + (0.20 if same_family else 0.0)
    )
    return max(semantic_overlap, weighted)


def _equipment_family_signature(hypothesis: WinningHypothesis) -> str:
    """Return a broad equipment family for portfolio-level diversity control.

    The family is intentionally coarser than a candidate title. It prevents a
    five-item portfolio from being filled by wording variants of the same
    low-altitude unmanned platform or anti-radiation loitering munition while
    still allowing a second variant when the candidate pool lacks breadth.
    """

    primary_text = " ".join(
        [hypothesis.title, *hypothesis.equipment_forms[:1]]
    ).lower()
    full_text = " ".join(
        [hypothesis.title, *hypothesis.equipment_forms]
    ).lower()

    def classify(text: str) -> str:
        if any(term in text for term in ("barracuda", "famm")):
            return "scalable_low_cost_cruise_effector"
        if any(
            term in text
            for term in ("mald", "adm-160", "诱饵/电子攻击效应器")
        ):
            return "expendable_decoy_electronic_attack_effector"
        if any(term in text for term in ("harop", "harpy", "巡飞猎歼")):
            return "loitering_munition"
        if any(term in text for term in ("prsm", "precision strike missile")):
            return "ground_launched_precision_missile"
        if any(term in text for term in ("反辐射", "抗辐射")):
            return "anti_radiation_loitering_munition"
        if any(term in text for term in ("高功率微波", "定向能", "激光武器")):
            return "directed_energy_weapon"
        if any(term in text for term in ("反无人机", "反无人系统", "无人机拦截")):
            return "counter_unmanned_weapon"
        if any(term in text for term in ("低空", "超低空")) and any(
            term in text for term in ("无人", "察打", "携弹", "巡飞")
        ):
            return "low_altitude_unmanned_strike"
        if any(term in text for term in ("空射", "机载")) and any(
            term in text for term in ("导弹", "巡航弹", "防区外")
        ):
            return "air_launched_standoff_missile"
        if any(term in text for term in ("地射", "地面发射", "车载发射")) and any(
            term in text for term in ("导弹", "火箭弹", "精确制导")
        ):
            return "ground_launched_precision_missile"
        if any(term in text for term in ("舰射", "潜射", "海上发射")) and any(
            term in text for term in ("导弹", "巡航弹", "鱼雷")
        ):
            return "maritime_launched_weapon"
        if "巡航" in text and any(
            term in text for term in ("导弹", "弹药", "效应器")
        ):
            return "cruise_munition"
        if "巡飞" in text and any(
            term in text for term in ("弹", "弹药", "效应器")
        ):
            return "loitering_munition"
        if any(
            term in text for term in ("无人艇", "无人潜航", "无人车", "无人僚机")
        ):
            return "unmanned_combat_platform"
        if any(term in text for term in ("导弹", "火箭弹", "拦截弹", "鱼雷")):
            return "guided_missile_or_munition"
        return ""

    # Classify the visible subject and first authoritative equipment form
    # before scanning subordinate interfaces or companion weapons. Otherwise
    # “反舰导弹与反辐射弹药成组使用” is mislabeled as an anti-radiation card.
    family = classify(primary_text) or classify(full_text)
    if family:
        return family
    normalized = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", hypothesis.title.lower())
    fallback = normalized or hypothesis.hypothesis_id
    return "specific:" + sha256(fallback.encode("utf-8")).hexdigest()[:12]


def _mixed_named_equipment_families(
    hypothesis: WinningHypothesis,
) -> tuple[str, ...]:
    """Detect one card that combines multiple public weapon-family anchors."""

    text = " ".join([hypothesis.title, *hypothesis.equipment_forms]).lower()
    families = {
        family
        for family, anchors in {
            "mald": ("mald", "adm-160"),
            "aargm": ("aargm",),
            "harop": ("harop", "harpy"),
            "prsm": ("prsm", "precision strike missile"),
            "jassm": ("jassm", "agm-158", "lrasm"),
            "barracuda": ("barracuda", "famm"),
        }.items()
        if any(anchor in text for anchor in anchors)
    }
    return tuple(sorted(families)) if len(families) > 1 else ()


def _diverse_portfolio_order(
    candidate_ids: Sequence[str],
    *,
    hypothesis_by_id: Mapping[str, WinningHypothesis],
    scores: Mapping[str, Mapping[str, float]],
    prior_ids: Sequence[str] = (),
    family_by_id: Mapping[str, str] | None = None,
) -> list[str]:
    """Rank by objective score while selecting broad families round-robin."""

    def family(item: str) -> str:
        return str((family_by_id or {}).get(item) or _equipment_family_signature(
            hypothesis_by_id[item]
        ))

    remaining = list(dict.fromkeys(candidate_ids))
    family_counts = Counter(
        family(item)
        for item in prior_ids
        if item in hypothesis_by_id
    )
    ordered: list[str] = []
    while remaining:
        minimum_family_count = min(
            family_counts[family(item)]
            for item in remaining
        )
        eligible = [
            item
            for item in remaining
            if family_counts[family(item)] == minimum_family_count
        ]
        chosen = min(
            eligible,
            key=lambda item: (-sum(scores[item].values()), item),
        )
        ordered.append(chosen)
        remaining.remove(chosen)
        family_counts[family(chosen)] += 1
    return ordered


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

    text = " ".join([hypothesis.title, *hypothesis.equipment_forms]).lower()
    direct_weapon_terms = (
        "导弹",
        "弹药",
        "拦截",
        "武器",
        "战斗",
        "电子攻击效应器",
        "电子压制器",
        "打击载荷",
        "火力节点",
        "舰",
        "艇",
        "火力",
        "counter-uas",
        "munition",
        "interceptor",
        "combat vehicle",
        "weapon",
    )
    if classification == "upgrade":
        return any(term in text for term in direct_weapon_terms)
    return any(term in text for term in direct_weapon_terms)


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


def _tokens(value: str) -> set[str]:
    text = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value.lower())
    latin = {item for item in text.split() if len(item) >= 2}
    chinese = {
        text[index : index + 2]
        for index in range(max(0, len(text) - 1))
        if re.fullmatch(r"[\u3400-\u9fff]{2}", text[index : index + 2])
    }
    return latin | chinese


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
    return _dedupe([str(item).strip()[:1200] for item in rows if str(item).strip()], limit)


_WEAPON_CANDIDATE_MARKERS = (
    "导弹", "巡飞", "弹药", "毁伤弹", "拦截弹", "无人机", "攻击无人机", "无人攻击机", "无人僚机", "无人艇",
    "无人潜航器", "无人平台", "效应器", "火力舱", "发射车", "武器站",
    "火炮", "鱼雷", "水雷", "激光武器", "微波武器",
)
_ABSTRACT_CANDIDATE_MARKERS = (
    "证据链", "任务链", "信息链", "杀伤链", "闭环", "能力", "体系", "方向",
    "红队保留", "竞争分支", "颠覆分支", "候选", "作战模式",
)

_GENERIC_CANDIDATE_WEAPON_TITLES = frozenset(
    {
        "内置效应器",
        "效应器",
        "内置载荷",
        "任务载荷",
        "攻击载荷",
        "火力",
        "平台",
        "弹药",
        "弹群",
    }
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


def _is_concrete_weapon_candidate_title(value: str) -> bool:
    text = str(value or "").strip()
    generic_label = text in _GENERIC_CANDIDATE_WEAPON_TITLES or bool(
        re.match(r"^(?:内置效应器|内置载荷|任务载荷|攻击载荷)\s*[：:]", text)
    )
    return (
        bool(text)
        and not generic_label
        and any(marker in text for marker in _WEAPON_CANDIDATE_MARKERS)
        and not any(marker in text for marker in _ABSTRACT_CANDIDATE_MARKERS)
    )


def _preflight_query_weapon_title(value: str) -> str:
    """Preserve the model's semantic name; only remove presentation noise.

    Candidate naming belongs to the query-aware Codex reasoning pass, not a
    catalogue of string substitutions.  Structural validation may still send
    an obviously non-weapon label to an early specialist for a fresh decision.
    """

    return str(value or "").strip()


def _weapon_title_needs_concretization(value: str) -> bool:
    """Flag a generic carrier before it is admitted to the swarm ledger."""

    return str(value or "").strip().endswith(("火力", "平台", "弹药", "弹群"))


def normalize_weapon_candidate_title(
    value: Any,
    equipment_forms: Sequence[Any] = (),
) -> str:
    """Return a concise, user-facing concrete weapon name for a candidate.

    The dynamic swarm can reason with S-node labels and explanatory titles,
    but those are never a valid equipment identity. Prefer a concise weapon
    noun in the candidate title; otherwise anchor it to the declared equipment
    form. This occurs before the hypothesis enters the ledger and S6.
    """

    cleaned = _clean_weapon_candidate_text(value)
    head = re.split(r"[：:；;。]", cleaned, maxsplit=1)[0].strip()
    if _is_concrete_weapon_candidate_title(head):
        # A selected candidate is already a concrete weapon identity.  Do not
        # turn it into a generic family merely to satisfy a display budget;
        # S6 may only make non-semantic cleanup to this name.
        return _preflight_query_weapon_title(head)
    if _is_concrete_weapon_candidate_title(cleaned):
        return _preflight_query_weapon_title(cleaned)
    for raw_form in equipment_forms:
        form = _clean_weapon_candidate_text(raw_form)
        form = re.sub(
            r"^(?:单一主装备(?:对象)?|主体装备|主装备对象|装备形态)\s*(?:为)?\s*[：:]?\s*",
            "",
            form,
        )
        form = re.sub(
            r"^(?:背负、车载或舰岸箱式发射的|背负、车载、舰岸箱式发射的|"
            r"背负发射的|箱式发射的|车载发射的|舰载发射的|空射的|地射的)",
            "",
            form,
        )
        form = re.split(r"[；;。]", form, maxsplit=1)[0].strip()
        if _is_concrete_weapon_candidate_title(form):
            return _preflight_query_weapon_title(form)
    # A malformed model output must never expose an orchestration stage.
    return _preflight_query_weapon_title(head or cleaned or "待复核具体武器装备")


def _dedupe(values: Sequence[str], limit: int) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item).strip()))[:limit]


def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
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
