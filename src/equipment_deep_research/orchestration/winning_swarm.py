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
    WinningHypothesis,
    WinningMissionGraph,
    WinningRoleContract,
    to_plain,
)


MERGE_TARGETS = frozenset({"S1", "S2", "S3", "S4", "S5", "S6", "convergence"})

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
        "purpose": "从公开项目、试验和装备族中寻找可改变任务链关系的具体装备形态。",
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
        "purpose": "贯通任务效果、功能、性能约束、体系接口、装备形态和实现路径。",
        "merge_target": "S4",
        "residuals": ["equipment_not_concrete", "engineering_feasibility_insufficient"],
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
}

MISSION_GRAPH_SEED_ARCHETYPES: dict[str, tuple[str, ...]] = {
    "S1": ("opponent_system_modeler", "adversary_adaptation_analyst", "weak_signal_scout"),
    "S2": ("operational_baseline_analyst", "competitive_coa_designer", "baseline_delta_analyst"),
    "S3": ("disruptive_mechanism_generator", "adversary_counter_adaptation_red_team", "cross_scenario_stress_tester"),
    "S4": ("frontier_equipment_miner", "equipment_realization_architect"),
    "S5": ("evidence_verifier", "trl_cost_industrial_auditor"),
    "S6": ("validation_experiment_designer", "independent_portfolio_reviewer"),
}

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
    return {
        "policy_id": policy_id,
        "enabled": enabled,
        "max_dynamic_instances": 16 if dynamic_v2 else 12,
        "max_concurrency": 6,
        "max_waves": 3,
        "mission_graph_min_instances": 8 if dynamic_v2 else 4,
        "mission_graph_target_instances": 12 if dynamic_v2 else 4,
        "mission_graph_max_instances": 16 if dynamic_v2 else 12,
        "minimum_expected_gain": 0.03,
        "breadth_hypothesis_minimum": 4,
        "breadth_hypothesis_maximum": 8,
        "finalist_minimum": 5 if dynamic_v2 else 2,
        "finalist_maximum": 7 if dynamic_v2 else 4,
        "recursive_recruitment_allowed": False,
        "raw_session_sharing_allowed": False,
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
    base = default_winning_swarm_policy(
        enabled=bool(raw.get("enabled", False) if enabled is None else enabled),
        policy_id=policy_id,
    )
    maximum_instances = 16 if dynamic_v2 else 12
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
                raw.get("breadth_hypothesis_minimum"), 1, 8, 4
            ),
            "breadth_hypothesis_maximum": _bounded_int(
                raw.get("breadth_hypothesis_maximum"), 1, 8, 8
            ),
            "finalist_minimum": _bounded_int(
                raw.get("finalist_minimum"), 1, 7,
                5 if dynamic_v2 else 2,
            ),
            "finalist_maximum": _bounded_int(
                raw.get("finalist_maximum"), 1, 7,
                7 if dynamic_v2 else 4,
            ),
            "recursive_recruitment_allowed": False,
            "raw_session_sharing_allowed": False,
        }
    )
    if base["breadth_hypothesis_minimum"] > base["breadth_hypothesis_maximum"]:
        base["breadth_hypothesis_minimum"] = base["breadth_hypothesis_maximum"]
    if base["finalist_minimum"] > base["finalist_maximum"]:
        base["finalist_minimum"] = base["finalist_maximum"]
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
        """Build an 8-16 instance S1-S6 seed graph with safe parallel waves."""

        minimum = 8
        maximum = min(16, max(minimum, int(self.policy.get("mission_graph_max_instances", 16))))
        target = _bounded_int(
            target_instances if target_instances is not None else self.policy.get("mission_graph_target_instances"),
            minimum,
            maximum,
            min(12, maximum),
        )
        selected: list[tuple[str, str]] = []
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
            contract = self.govern_role_contract(
                {"archetype": archetype, **spec}, mission_node=node
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
        core_waves = self.core_execution_waves(range(1, 7))
        wave_by_node = {
            f"S{step}": wave_index
            for wave_index, wave in enumerate(core_waves, start=1)
            for step in wave
        }
        dependencies: dict[str, list[str]] = {}
        resolved_instances: list[WinningAgentInstance] = []
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
            elif step == 4:
                upstream = node_instances["S3"]
                depends_on = [upstream[ordinal % len(upstream)]] if upstream else []
            elif step == 5:
                upstream = node_instances["S4"]
                depends_on = [upstream[ordinal % len(upstream)]] if upstream else []
            elif step == 6:
                depends_on = [*node_instances["S4"], *node_instances["S5"]]
            else:
                depends_on = []
            dependencies[instance.instance_id] = depends_on
            resolved_instances.append(
                replace(
                    instance,
                    wave=wave_by_node[instance.mission_node],
                    depends_on=depends_on,
                )
            )
        waves = [
            [
                instance.instance_id
                for instance in resolved_instances
                if instance.wave == wave_index
            ]
            for wave_index in range(1, len(core_waves) + 1)
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
        if hypothesis is None or contribution.merge_target not in MERGE_TARGETS or not contribution.accepted:
            return ledger, MergeReceipt(
                **receipt_base, resulting_ledger_version=ledger.version,
                status="rejected", conflicts=["invalid_merge_scope_or_contribution"],
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
            novelty_delta=str(patch.get("novelty_delta", ""))[:900],
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
        candidate_ids = [
            item.hypothesis_id
            for item in ledger.hypotheses
            if final_gates[item.hypothesis_id].passed
        ]

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
        front.sort(key=lambda item: (-sum(scores[item].values()), item))
        maximum = int(self.policy.get("finalist_maximum", 4))
        minimum = min(
            maximum,
            int(self.policy.get("finalist_minimum", 2)),
            len(candidate_ids),
        )
        selected = front[:maximum]
        # A sparse first Pareto front must not collapse the dynamic-v2
        # deliverable below its 5-direction business contract.  Fill from the
        # next-best Pareto layers while preserving the first-front ordering and
        # recording dominance reasons for audit.
        if len(selected) < minimum:
            ranked_remainder = sorted(
                (item for item in candidate_ids if item not in selected),
                key=lambda item: (-sum(scores[item].values()), item),
            )
            selected.extend(ranked_remainder[: minimum - len(selected)])
        hypothesis_by_id = {
            item.hypothesis_id: item for item in ledger.hypotheses
        }
        direct_pool = sorted(
            (
                item
                for item in candidate_ids
                if _is_direct_combat_equipment(hypothesis_by_id[item])
            ),
            key=lambda item: (-sum(scores[item].values()), item),
        )
        if len(direct_pool) >= 4 and sum(
            item in direct_pool for item in selected
        ) < 4:
            required_direct = direct_pool[:4]
            ranked_all = sorted(
                candidate_ids,
                key=lambda item: (-sum(scores[item].values()), item),
            )
            selected = list(dict.fromkeys([
                *required_direct,
                *selected,
                *ranked_all,
            ]))[:maximum]
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
        )

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
        for hypothesis in finalists[: min(2, remaining)]:
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
        title = str(value.get("title") or value.get("name") or "候选制胜假设").strip()[:180]
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
            novelty_delta=str(value.get("novelty_delta") or value.get("novelty") or "").strip()[:900],
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
        return replace(hypothesis, residuals=gate.residuals, score=gate.score)

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
        accepted = (
            quality >= float(self.policy["minimum_expected_gain"])
            and bool(_text_list(value.get("findings", []), limit=8))
            and recommendation != "reject"
        )
        return SpecialistContribution(
            contribution_id=_stable_id("contribution", task.task_id, task.hypothesis_id),
            task_id=task.task_id,
            agent_instance_id=task.agent_instance_id,
            hypothesis_id=task.hypothesis_id,
            merge_target=task.merge_target,
            findings=_text_list(value.get("findings", []), limit=8),
            mechanism_chain_updates=_text_list(value.get("mechanism_chain_updates", []), limit=8),
            direct_military_effects=_text_list(value.get("direct_military_effects", []), limit=6),
            equipment_forms=_text_list(value.get("equipment_forms", []), limit=6),
            novelty_delta=str(value.get("novelty_delta", "")).strip()[:900],
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
            novelty_delta=contribution.novelty_delta or hypothesis.novelty_delta,
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
        if not hypothesis.nearest_public_baseline.strip():
            residuals.append("baseline_missing")
        if not hypothesis.changed_confrontation_variable.strip() or not hypothesis.mechanism_chain:
            residuals.append("causal_chain_broken")
        if not hypothesis.direct_military_effects:
            residuals.append("military_effect_missing")
        if not hypothesis.novelty_delta.strip():
            residuals.append("novelty_insufficient")
        if not hypothesis.equipment_forms:
            residuals.append("equipment_not_concrete")
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
            "novelty_insufficient": 0.10,
            "equipment_not_concrete": 0.12,
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
    def is_direct_combat_equipment(hypothesis: WinningHypothesis) -> bool:
        return _is_direct_combat_equipment(hypothesis)

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
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _is_direct_combat_equipment(hypothesis: WinningHypothesis) -> bool:
    """Reject support-only cards from satisfying the combat-equipment quota."""

    text = " ".join([hypothesis.title, *hypothesis.equipment_forms]).lower()
    direct_terms = (
        "无人",
        "平台",
        "飞行器",
        "导弹",
        "弹药",
        "拦截",
        "武器",
        "战斗",
        "载具",
        "机器人",
        "舰",
        "艇",
        "车辆",
        "火力",
        "counter-uas",
        "munition",
        "interceptor",
        "combat vehicle",
        "weapon",
    )
    return any(term in text for term in direct_terms)


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
    "normalize_winning_swarm_policy",
]
