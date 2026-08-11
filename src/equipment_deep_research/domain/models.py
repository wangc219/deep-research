from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal
from uuid import uuid4


ResearchRoute = Literal[
    "auto",
    "new_winning_mechanism",
    "traditional_gap",
    "war_case_learning",
]
InteractionMode = Literal["expert", "autonomous"]
DiscoveryBranch = Literal["auto", "A", "B", "C", "D", "E", "F", "G", "H"]

CapabilityImageType = Literal["new_capability", "upgrade"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_stable_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        # ``dataclasses.asdict`` performs a deepcopy and therefore attempts to
        # pickle immutable provider containers such as MappingProxyType.
        # Reading fields directly keeps conversion deterministic without
        # copying opaque runtime container implementations.
        return {
            item.name: to_plain(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ResearchProblem:
    topic: str
    research_route: ResearchRoute = "auto"
    selected_agent_ids: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    problem_id: str = field(default_factory=lambda: new_stable_id("problem"))
    schema_version: str = "1.0"
    as_of_date: str = ""
    interaction_mode: InteractionMode = "expert"
    discovery_branch: DiscoveryBranch = "auto"
    max_rounds_hint: int = 2
    supplemental_information: str = ""

    def analysis_text(self) -> str:
        """Return the complete user input used for routing and task analysis."""

        supplement = self.supplemental_information.strip()
        return self.topic if not supplement else f"{self.topic}\n{supplement}"

    def structured_query_brief(self) -> dict[str, Any]:
        """Compress optional user context into a bounded downstream handoff.

        The original supplement remains stored on the ResearchProblem for audit,
        while worker Agents receive this short structure instead of a long raw
        paragraph.  Model-generated blueprint fields may refine this baseline.
        """

        supplement = re.sub(r"\s+", " ", self.supplemental_information).strip()
        if not supplement:
            return {
                "core_query": self.topic.strip(),
                "supplement_present": False,
                "focus_questions": [],
                "expansion_dimensions": [],
                "constraints_and_assumptions": [],
                "combat_problem_frame": "",
                "enemy_target_profile": [],
                "battle_phase_and_constraints": [],
                "required_direct_military_effects": [],
                "weapon_design_variables": [],
                "query_specific_weapon_architectures": [],
                "equipment_project_hypotheses": [],
                "rejected_template_anchors": [],
            }

        clauses = [
            item.strip(" ；;。")
            for item in re.split(r"(?<=[？?。；;])\s*", supplement)
            if item.strip(" ；;。")
        ]
        focus_questions = [
            item for item in clauses if "？" in item or "?" in item
        ][:6]
        if not focus_questions:
            focus_questions = clauses[:4]

        # Offline fallback stays intentionally generic.  In real runs the
        # orchestrator derives Query-specific dimensions and equipment
        # hypotheses from the complete input instead of matching a local list.
        expansion_dimensions = [
            "任务对象与直接效果",
            "对手适应与失效边界",
            "装备形态与工程约束",
            "证据问题与淘汰条件",
        ]
        # Keep the offline handoff useful before a model has designed a
        # query-specific blueprint.  These are transparent lexical signals in
        # the user's own supplement, not conclusions about the topic.
        if any(
            signal in supplement
            for signal in ("成本", "效费", "交换比", "单发", "拦截弹")
        ):
            expansion_dimensions.append("成本交换与效费比")
        if any(
            signal in supplement
            for signal in ("量产", "万枚", "规模化", "弹药基数", "产能", "后勤")
        ):
            expansion_dimensions.append("规模化生产与工业动员")

        constraints_and_assumptions = [
            item
            for item in clauses
            if any(
                signal in item
                for signal in ("如果", "假设", "前提", "约束", "以下", "达到", "降至")
            )
        ][:4]
        dimension_summary = "、".join(expansion_dimensions[:4])
        if len(expansion_dimensions) > 4:
            dimension_summary += "等"
        supplement_summary = (
            f"补充研究聚焦{dimension_summary}；已提取{len(focus_questions)}个焦点问题"
            f"和{len(constraints_and_assumptions)}项待验证约束/假设。"
        )

        return {
            "core_query": self.topic.strip(),
            "supplement_present": True,
            "supplement_summary": supplement_summary[:1200],
            "focus_questions": focus_questions,
            "expansion_dimensions": expansion_dimensions,
            "constraints_and_assumptions": constraints_and_assumptions,
            "combat_problem_frame": "",
            "enemy_target_profile": [],
            "battle_phase_and_constraints": [],
            "required_direct_military_effects": [],
            "weapon_design_variables": [],
            "query_specific_weapon_architectures": [],
            "equipment_project_hypotheses": [],
            "rejected_template_anchors": [],
            "handoff_rule": "补充信息用于拓展分析方向；其中假设需验证，不视为既成事实。",
        }

    def resolved_route(self) -> str:
        if self.research_route != "auto":
            return self.research_route
        branch = self.resolved_discovery_branch()["primary"]
        if branch == "B" or branch == "F":
            return "traditional_gap"
        if branch == "C":
            return "war_case_learning"
        return "new_winning_mechanism"

    def resolved_discovery_branch(self) -> dict[str, Any]:
        """Return the target A-H discovery branch without changing runtime routes.

        The field is intentionally additive: existing callers continue to use the
        three executable research routes, while audit and reporting consumers can
        inspect the finer target-architecture classification.
        """
        labels = {
            "A": "新战法发现",
            "B": "传统能力缺口发现",
            "C": "局部战争案例经验",
            "D": "技术驱动发现",
            "E": "对手动向牵引发现",
            "F": "体系对抗博弈发现",
            "G": "跨域融合发现",
            "H": "非传统安全牵引",
        }
        if self.discovery_branch != "auto":
            label = labels[self.discovery_branch]
            return {
                "primary": self.discovery_branch,
                "secondary": [],
                "confidence": 1.0,
                "rationale": f"专家显式指定{label}分支。",
                "label": label,
            }
        route_fallbacks = {
            "new_winning_mechanism": ("A", "新战法发现"),
            "traditional_gap": ("B", "传统能力缺口发现"),
            "war_case_learning": ("C", "局部战争案例经验"),
        }
        if self.research_route in route_fallbacks:
            code, label = route_fallbacks[self.research_route]
            return {
                "primary": code,
                "secondary": [],
                "confidence": 0.9,
                "rationale": f"继承专家显式指定的{self.research_route}研究路线。",
                "label": label,
            }
        return {
            "primary": "A",
            "secondary": [],
            "confidence": 0.35,
            "rationale": "自动模式不从Query字符串猜测分支；等待智能体discovery blueprint完成语义判定，A仅作为离线运行基座。",
            "label": "新战法发现",
        }


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    source_title: str
    source_url: str
    source_tier: str
    claim: str
    excerpt: str
    source_location: str
    quality_assessment: str
    created_by: str
    artifact_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class BaselineFindingPacket:
    packet_id: str
    agent_id: str
    capability_tags: list[str]
    topic_focus: str
    findings: list[str]
    evidence_ids: list[str]
    confidence: float
    coverage_notes: list[str]
    open_questions: list[str]
    handoff_summary: str
    checkpoint: str
    created_at: str = field(default_factory=now_iso)
    claim_ids: list[str] = field(default_factory=list)
    search_log: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    schema_version: str = "1.0"
    analysis_sections: dict[str, Any] = field(default_factory=dict)
    payload_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    claim_bundle_ref: str = ""
    admission_status: Literal["", "accepted", "limited", "rejected"] = ""

    def validate_for_submit(self) -> None:
        if not self.schema_version.startswith("2"):
            return
        expected = BASELINE_PAYLOAD_TYPES.get(self.agent_id)
        if expected is None:
            raise ValueError(f"v2 packet has unsupported agent role: {self.agent_id}")
        payload_type, required_fields = expected
        if self.payload_type != payload_type:
            raise ValueError(
                f"v2 packet for {self.agent_id} requires payload_type={payload_type}"
            )
        missing = [
            name
            for name in required_fields
            if name not in self.payload or self.payload[name] in (None, "", [], {})
        ]
        if missing:
            raise ValueError(f"v2 packet payload missing required fields: {missing}")


BASELINE_PAYLOAD_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "international_situation": (
        "strategic_assessment_v1",
        (
            "situation_assessment",
            "threat_assessment",
            "strategic_pattern",
            "opponent_moves",
            "warning_indicators",
            "alternative_hypotheses",
            "scenario_drivers",
        ),
    ),
    "combat_scenario": (
        "scenario_model_v1",
        (
            "scenario_framework",
            "enemy_coa",
            "critical_timeline",
            "environment_constraints",
            "scenario_branches",
            "capability_pressure_points",
            "assumptions",
        ),
    ),
    "weapon_equipment": (
        "equipment_observation_v1",
        (
            "equipment_profiles",
            "current_parameters",
            "parameter_observations",
            "parameter_conflicts",
            "development_models",
            "technology_readiness",
            "capability_constraints",
            "scenario_fit",
            "capability_gaps",
        ),
    ),
    "operational_employment": (
        "operational_synthesis_v1",
        (
            "operational_constraints",
            "mission_chain",
            "force_coordination",
            "coa",
            "sustainment_resilience",
            "failure_modes",
            "lessons",
            "equipment_function_requirements",
        ),
    ),
    "opponent_monitoring": (
        "opponent_change_assessment_v1",
        (
            "change_baseline",
            "observed_moves",
            "formation_timeline",
            "threat_effects",
            "system_dependencies",
            "counter_requirements",
            "warning_indicators",
        ),
    ),
    "system_confrontation": (
        "system_confrontation_model_v1",
        (
            "system_boundaries",
            "red_blue_models",
            "dependency_graph",
            "cascading_failures",
            "critical_vulnerabilities",
            "alternative_configs",
            "reinforcement_directions",
        ),
    ),
}

BASELINE_OPTIONAL_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "weapon_equipment": (
        "foreign_equipment_landscape",
        "domestic_equipment_landscape",
        "foreign_equipment_cases",
        "domestic_equipment_cases",
        "comparative_findings",
        "system_dependencies",
        "long_range_precision_missile_evidence",
        "long_range_unmanned_strike_evidence",
        "standoff_suppression_evidence",
        "expendable_decoy_electronic_attack_evidence",
        "counter_uas_interceptor_evidence",
        "defensive_countermeasure_options",
        "upgrade_requirements",
        "new_equipment_requirements",
        "verification_plan",
    ),
}


@dataclass(frozen=True)
class StrategicAssessment:
    assessment_id: str
    packet_id: str
    situation_assessment: Any
    threat_assessment: Any
    strategic_pattern: Any
    opponent_moves: Any
    warning_indicators: Any
    alternative_hypotheses: Any
    scenario_drivers: Any
    evidence_ids: list[str]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class ScenarioModel:
    scenario_id: str
    packet_id: str
    scenario_framework: Any
    enemy_coa: Any
    critical_timeline: Any
    environment_constraints: Any
    scenario_branches: Any
    capability_pressure_points: Any
    assumptions: Any
    evidence_ids: list[str]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class EquipmentObservation:
    observation_id: str
    packet_id: str
    equipment_profiles: Any
    current_parameters: Any
    parameter_observations: Any
    parameter_conflicts: Any
    development_models: Any
    technology_readiness: Any
    capability_constraints: Any
    scenario_fit: Any
    capability_gaps: Any
    evidence_ids: list[str]
    foreign_equipment_landscape: Any = field(default_factory=list)
    domestic_equipment_landscape: Any = field(default_factory=list)
    foreign_equipment_cases: Any = field(default_factory=list)
    domestic_equipment_cases: Any = field(default_factory=list)
    comparative_findings: Any = field(default_factory=list)
    system_dependencies: Any = field(default_factory=list)
    long_range_precision_missile_evidence: Any = field(default_factory=list)
    long_range_unmanned_strike_evidence: Any = field(default_factory=list)
    standoff_suppression_evidence: Any = field(default_factory=list)
    expendable_decoy_electronic_attack_evidence: Any = field(default_factory=list)
    counter_uas_interceptor_evidence: Any = field(default_factory=list)
    defensive_countermeasure_options: Any = field(default_factory=list)
    upgrade_requirements: Any = field(default_factory=list)
    new_equipment_requirements: Any = field(default_factory=list)
    verification_plan: Any = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class OperationalSynthesis:
    synthesis_id: str
    packet_id: str
    operational_constraints: Any
    mission_chain: Any
    force_coordination: Any
    coa: Any
    sustainment_resilience: Any
    failure_modes: Any
    lessons: Any
    equipment_function_requirements: Any
    evidence_ids: list[str]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


def typed_domain_object_from_packet(
    packet: BaselineFindingPacket,
) -> (
    StrategicAssessment
    | ScenarioModel
    | EquipmentObservation
    | OperationalSynthesis
    | None
):
    if not packet.schema_version.startswith("2"):
        return None
    packet.validate_for_submit()
    common = {"packet_id": packet.packet_id, "evidence_ids": list(packet.evidence_ids)}
    if packet.agent_id == "international_situation":
        return StrategicAssessment(
            assessment_id=f"strategic-{packet.packet_id}",
            **common,
            **{
                name: packet.payload[name]
                for name in BASELINE_PAYLOAD_TYPES[packet.agent_id][1]
            },
        )
    if packet.agent_id == "combat_scenario":
        return ScenarioModel(
            scenario_id=f"scenario-{packet.packet_id}",
            **common,
            **{
                name: packet.payload[name]
                for name in BASELINE_PAYLOAD_TYPES[packet.agent_id][1]
            },
        )
    if packet.agent_id == "weapon_equipment":
        return EquipmentObservation(
            observation_id=f"equipment-{packet.packet_id}",
            **common,
            **{
                name: packet.payload[name]
                for name in BASELINE_PAYLOAD_TYPES[packet.agent_id][1]
            },
            **{
                name: packet.payload.get(name, [])
                for name in BASELINE_OPTIONAL_PAYLOAD_FIELDS.get(packet.agent_id, ())
            },
        )
    if packet.agent_id == "operational_employment":
        return OperationalSynthesis(
            synthesis_id=f"operational-{packet.packet_id}",
            **common,
            **{
                name: packet.payload[name]
                for name in BASELINE_PAYLOAD_TYPES[packet.agent_id][1]
            },
        )
    return None


@dataclass(frozen=True)
class WorkingCheckpoint:
    """Compact durable state supplied only to the owning research agent."""

    checkpoint_id: str
    agent_id: str
    round_index: int
    completed_steps: list[str] = field(default_factory=list)
    accepted_evidence_ids: list[str] = field(default_factory=list)
    rejected_lead_ids: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    return_node: str = "baseline"
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkingCheckpoint":
        return cls(**value)


@dataclass(frozen=True)
class RecallRequest:
    recall_id: str
    source_layer: str
    target_agent_id: str | None
    target_capability_tag: str | None
    reason: str
    required_data: list[str]
    return_node: str
    urgency: str
    status: str = "pending"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def target_key(self) -> str:
        return self.target_agent_id or self.target_capability_tag or "unroutable"


@dataclass(frozen=True)
class AgentRecommendation:
    recommendation_id: str
    missing_capability_tag: str
    reason: str
    suggested_agent_description: str
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


WinningHypothesisStatus = Literal[
    "draft",
    "challenging",
    "finalist",
    "accepted",
    "merged",
    "rejected",
]


@dataclass(frozen=True)
class WinningHypothesis:
    """Auditable candidate ledger for one mechanism-distinct winning thesis."""

    hypothesis_id: str
    title: str
    nearest_public_baseline: str
    changed_confrontation_variable: str
    mechanism_chain: list[str]
    direct_military_effects: list[str]
    equipment_forms: list[str]
    novelty_delta: str
    frontier_principle: str = ""
    technology_discontinuity: str = ""
    technology_horizon: str = ""
    engineering_bottleneck: str = ""
    winning_angle_id: str = ""
    combat_dimension: str = ""
    dimension_winning_logic: str = ""
    original_paradigm: str = ""
    disruptive_shift: str = ""
    independence_thesis: str = ""
    project_function: str = ""
    reference_overview: str = ""
    naming_rationale: str = ""
    decisive_advantage_thesis: str = ""
    cross_query_distinction: str = ""
    system_interfaces: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    adversary_adaptations: list[str] = field(default_factory=list)
    failure_boundaries: list[str] = field(default_factory=list)
    trl_constraints: list[str] = field(default_factory=list)
    cost_constraints: list[str] = field(default_factory=list)
    industrial_constraints: list[str] = field(default_factory=list)
    cross_scenario_results: list[str] = field(default_factory=list)
    validation_plan: list[str] = field(default_factory=list)
    evidence_boundary: str = ""
    implementation_path: str = ""
    merge_targets: list[str] = field(default_factory=list)
    source_task_ids: list[str] = field(default_factory=list)
    residuals: list[str] = field(default_factory=list)
    score: float = 0.0
    status: WinningHypothesisStatus = "draft"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class SpecialistTask:
    task_id: str
    agent_instance_id: str
    archetype: str
    display_name: str
    wave: int
    purpose: str
    merge_target: str
    hypothesis_id: str = ""
    trigger_residuals: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    expected_quality_gain: float = 0.0
    max_output_tokens: int = 1800
    allow_child_spawn: bool = False
    status: str = "planned"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class SwarmPlan:
    plan_id: str
    execution_profile_id: str
    policy: dict[str, Any]
    tasks: list[SpecialistTask]
    waves: list[list[str]]
    stop_reason: str = ""
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class SpecialistContribution:
    contribution_id: str
    task_id: str
    agent_instance_id: str
    hypothesis_id: str
    merge_target: str
    findings: list[str]
    replacement_title: str = ""
    mechanism_chain_updates: list[str] = field(default_factory=list)
    direct_military_effects: list[str] = field(default_factory=list)
    equipment_forms: list[str] = field(default_factory=list)
    project_function: str = ""
    system_interfaces: list[str] = field(default_factory=list)
    novelty_delta: str = ""
    frontier_principle: str = ""
    technology_discontinuity: str = ""
    technology_horizon: str = ""
    engineering_bottleneck: str = ""
    original_paradigm: str = ""
    disruptive_shift: str = ""
    independence_thesis: str = ""
    naming_rationale: str = ""
    decisive_advantage_thesis: str = ""
    cross_query_distinction: str = ""
    evidence_boundary: str = ""
    implementation_path: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    adversary_adaptations: list[str] = field(default_factory=list)
    failure_boundaries: list[str] = field(default_factory=list)
    trl_constraints: list[str] = field(default_factory=list)
    cost_constraints: list[str] = field(default_factory=list)
    industrial_constraints: list[str] = field(default_factory=list)
    cross_scenario_results: list[str] = field(default_factory=list)
    validation_plan: list[str] = field(default_factory=list)
    residuals_resolved: list[str] = field(default_factory=list)
    incremental_quality: float = 0.0
    recommendation: str = "retain"
    accepted: bool = False
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class SwarmGateResult:
    gate_id: str
    hypothesis_id: str
    stage: str
    passed: bool
    score: float
    residuals: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class WinningExpertAssessment:
    """Independent Codex-CLI judgement for one winning hypothesis.

    The assessment is intentionally separate from agent contributions: the
    judge may score, reject or request revision, but may not mutate the ledger.
    """

    assessment_id: str
    hypothesis_id: str
    blind_label: str
    verdict: str
    passed: bool
    weighted_score: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    residuals: list[str] = field(default_factory=list)
    equipment_classification: str = ""
    innovation_type: str = ""
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    evaluator_agent_id: str = "winning_quality_expert_judge"
    session_ref: str = ""
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class AgentPromotionRecord:
    promotion_id: str
    archetype: str
    eligible_runs: int
    positive_increment_runs: int
    evidence_hard_failures: int
    permission_hard_failures: int
    positive_increment_rate: float
    offline_evaluation_passed: bool = False
    human_approved: bool = False
    status: str = "candidate"
    version: str = "candidate-v1"
    rollback_ref: str = ""
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class WinningRoleContract:
    """Governed, versioned role definition for one mission-graph specialist."""

    role_contract_id: str
    archetype: str
    display_name: str
    purpose: str
    mission_node: str
    merge_targets: list[str]
    trigger_residuals: list[str] = field(default_factory=list)
    methodology: list[str] = field(default_factory=list)
    quality_gates: list[str] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    max_instances: int = 1
    allow_child_spawn: bool = False
    authority_scope: str = "bounded_analysis_only"
    generated_by: str = "winning_swarm_controller"
    status: str = "governed"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class WinningAgentInstance:
    """One isolated, disposable execution instance bound to a role contract."""

    instance_id: str
    role_contract_id: str
    archetype: str
    display_name: str
    mission_node: str
    wave: int
    merge_target: str
    hypothesis_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    trigger_residuals: list[str] = field(default_factory=list)
    expected_quality_gain: float = 0.0
    execution_backend: str = "independent_codex_cli"
    context_isolation: str = "ephemeral"
    allow_child_spawn: bool = False
    status: str = "planned"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class WinningMissionGraph:
    """Dependency-aware graph joining S1-S6 seed instances and recruited roles."""

    graph_id: str
    execution_profile_id: str
    mission_objective: str
    role_contracts: list[WinningRoleContract]
    agent_instances: list[WinningAgentInstance]
    dependencies: dict[str, list[str]]
    waves: list[list[str]]
    s_node_seeds: dict[str, list[str]]
    minimum_instances: int = 8
    maximum_instances: int = 16
    maximum_concurrency: int = 6
    merge_strategy: str = "versioned_ledger_rebase_then_pareto"
    status: str = "planned"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class WinningContribution:
    """A merge-scoped patch produced against one immutable ledger version."""

    contribution_id: str
    agent_instance_id: str
    role_contract_id: str
    hypothesis_id: str
    merge_target: str
    base_ledger_version: int
    hypothesis_patch: dict[str, Any]
    quality_dimensions: dict[str, float] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    residuals_resolved: list[str] = field(default_factory=list)
    incremental_quality: float = 0.0
    recommendation: str = "retain"
    rebase_count: int = 0
    accepted: bool = True
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class MergeReceipt:
    receipt_id: str
    contribution_id: str
    hypothesis_id: str
    merge_target: str
    base_ledger_version: int
    resulting_ledger_version: int
    status: str
    changed_fields: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    quality_delta: float = 0.0
    rebase_required: bool = False
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class HypothesisLedgerVersion:
    ledger_id: str
    version: int
    hypotheses: list[WinningHypothesis]
    parent_version: int | None = None
    merge_receipts: list[MergeReceipt] = field(default_factory=list)
    change_summary: str = ""
    created_by: str = "winning_swarm_controller"
    status: str = "active"
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class PortfolioDecision:
    decision_id: str
    ledger_id: str
    ledger_version: int
    pareto_front: list[str]
    selected_hypothesis_ids: list[str]
    rejected_hypothesis_ids: list[str]
    objective_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    dominance_reasons: dict[str, list[str]] = field(default_factory=dict)
    expert_assessment_ids: list[str] = field(default_factory=list)
    quality_judge_passed: bool = False
    status: str = "proposed"
    requires_human_review: bool = True
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "2.0"


@dataclass(frozen=True)
class WinningMechanismInput:
    input_id: str
    research_route: str
    problem_frame: dict[str, Any]
    packet_ids: list[str]
    evidence_index: list[dict[str, Any]]
    coverage_map: dict[str, Any]
    conflict_set: list[str]
    open_questions: list[str]
    round_budget: dict[str, int]
    attempt: int = 1
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class WinningKnowledgeProjection:
    projection_id: str
    input_id: str
    theory_tools: list[dict[str, Any]]
    case_resources: list[dict[str, Any]]
    frontier_resources: list[dict[str, Any]]
    question_chain: list[dict[str, Any]]
    evidence_ids: list[str]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class WinningReasoningNode:
    object_id: str
    step: int
    title: str
    summary: str
    input_refs: list[str]
    evidence_ids: list[str]
    claim_ids: list[str]
    confidence: float
    assumptions: list[str]
    route: str
    next_action: dict[str, Any]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class WinningMechanismStageOutput:
    stage_id: str
    layer: Literal["L1", "L2", "L3"]
    title: str
    outputs: dict[str, Any]
    confidence: float
    evidence_ids: list[str]
    gate_passed: bool
    gate_reasons: list[str]
    recall_requests: list[RecallRequest] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class CapabilityImageItem:
    capability_id: str
    name: str
    equipment_category: str
    capability_type: CapabilityImageType
    source_winning_logic: str
    related_scenario: str
    priority: str
    capability_gap: str
    capability_image: str
    evidence_ids: list[str]
    confidence: float
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"
    project_function: str = ""
    mission_effect: str = ""
    system_dependencies: list[str] = field(default_factory=list)
    risk_boundaries: list[str] = field(default_factory=list)
    military_utility: str = ""
    strike_countermeasure_value: str = ""
    novelty: str = ""
    foresight: str = ""
    operational_constraints: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)
    agent_contributions: list[str] = field(default_factory=list)
    reasoning_refs: list[str] = field(default_factory=list)
    deep_capability_portrait: str = ""
    equipment_form: str = ""
    operational_mechanism: str = ""
    development_path: str = ""
    baseline_system: str = ""
    upgrade_package: list[str] = field(default_factory=list)
    combat_effect_uplift: str = ""
    strike_chain_contribution: str = ""
    upgrade_boundary: str = ""
    target_scenario: str = ""
    problem_statement: str = ""
    scientific_principle: str = ""
    enabling_technologies: list[str] = field(default_factory=list)
    operational_concept: str = ""
    operational_process: list[str] = field(default_factory=list)
    capability_outcome: str = ""
    winning_mechanism: str = ""
    verification_plan: list[str] = field(default_factory=list)
    indicator_portrait: str = ""

    def validate(self) -> None:
        required = [
            self.capability_id,
            self.name,
            self.equipment_category,
            self.capability_type,
            self.source_winning_logic,
            self.related_scenario,
            self.priority,
            self.capability_gap,
            self.capability_image,
        ]
        if any(not str(item).strip() for item in required):
            raise ValueError("CapabilityImageItem requires all nine display fields")
        if self.capability_type not in {"new_capability", "upgrade"}:
            raise ValueError(f"invalid capability_type: {self.capability_type}")


@dataclass(frozen=True)
class AuditResult:
    audit_id: str
    status: str
    checks: dict[str, bool]
    comments: list[str]
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class ResearchReport:
    report_id: str
    title: str
    body: str
    capability_ids: list[str]
    evidence_ids: list[str]
    audit_id: str
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    event_type: str
    actor: str
    summary: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"
