from __future__ import annotations
# ruff: noqa: E402, F401

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from contextlib import suppress
from hashlib import sha256
import json
from dataclasses import replace
import os
import re
from threading import RLock
from time import monotonic
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.execution_contracts import (
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSelectionRequest,
    AgentSelectionResult,
)
from equipment_deep_research.agents.designs import (
    AgentDesignRegistry,
    AgentDesignSpec,
)
from equipment_deep_research.agents.workflows.baseline import BaselineAgentService
from equipment_deep_research.harness.profiles import HarnessProfile
from equipment_deep_research.domain.models import (
    BASELINE_OPTIONAL_PAYLOAD_FIELDS,
    BASELINE_PAYLOAD_TYPES,
    BaselineFindingPacket,
    EvidenceCard,
    HypothesisLedgerVersion,
    MergeReceipt,
    PortfolioDecision,
    SpecialistContribution,
    SpecialistTask,
    WinningAgentInstance,
    WinningContribution,
    WinningExpertAssessment,
    WinningHypothesis,
    to_plain,
)
from equipment_deep_research.domain.research_focus import (
    disruptive_relationship_groups,
    disruptive_seed_context,
    disruptive_seed_pool_context,
)
from equipment_deep_research.providers.base import ModelMessage, ModelProvider
from equipment_deep_research.providers.responses import ProviderRequestError
from equipment_deep_research.agents.prompts import BaselinePromptBuilder
from equipment_deep_research.agents.orchestrator_prompt import (
    AGENT_SELECTION_OUTPUT_SCHEMA,
    BLUEPRINT_OUTPUT_SCHEMA,
    META_REPLAN_OUTPUT_SCHEMA,
    orchestrator_system_prompt,
)
from equipment_deep_research.agents.runtime_profiles import (
    build_codex_runtime_profile,
    is_aggressive_optimized_v2_payload,
    is_optimized_v2_payload,
)
from equipment_deep_research.agents.performance import AdaptiveCallGate
from equipment_deep_research.orchestration.blueprints import winning_step_modes
from equipment_deep_research.orchestration.execution_contracts import (
    is_quality_execution_profile_id,
)
from equipment_deep_research.orchestration.winning_swarm import (
    QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION,
    SWARM_SPECIALIST_ARCHETYPES,
    WinningSwarmController,
    normalize_weapon_candidate_title,
)
from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.capability_portrait import (
    build_agent_led_capability_portrait,
    build_capability_portrait,
)
from equipment_deep_research.delivery.quality_gate import (
    _normalized_reuse_unit,
    _report_military_information_metrics,
)
from equipment_deep_research.agents.provider_optimizations import (
    get_optimized_search_context_size,
)


class S6QualityError(RuntimeError):
    """Raised when S6 cannot satisfy its quality gate without a fallback image."""

    def __init__(
        self,
        message: str,
        *,
        partial_result: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.partial_result = (
            dict(partial_result) if isinstance(partial_result, Mapping) else {}
        )


def _query_led_combat_equipment_theme_contract() -> dict[str, Any]:
    """Return the shared query-first theme anchors for combat equipment work."""

    return {
        "query_precedence": (
            "当前query的任务对象、威胁、作战阶段和直接军事效果始终优先；"
            "下列主题与示例仅用于发散，不是必选目录、固定命名或覆盖率要求。"
            "与query没有直接因果关系的类别必须舍弃，不得为了凑齐主题机械生成。"
        ),
        "divergence_mode": (
            "每个Agent先独立复述Query中的任务对象、威胁形态、作战阶段、地域/环境约束和"
            "制胜矛盾，再围绕这些语义做跨域与机制级发散，最后从直接战果、公开基线和工程"
            "边界收敛到具体装备项目；不得先选装备族再反向拼接Query。"
        ),
        "mandatory_query_semantic_pass": [
            "任务对象与敌方目标/威胁",
            "作战阶段、交战窗口与地域环境",
            "对手主要反制与我方当前断点",
            "必须形成的直接打击、歼灭、压制、拦截或拒止效果",
            "决定胜负的成本、时间、平台、生存、毁伤或体系矛盾",
        ],
        "cross_query_template_guard": (
            "候选名称、主装备形态、目标、发射/释放域、毁伤机理和作战流程必须由本Query共同决定；"
            "若替换成另一Query后仍基本成立，说明候选模板化，必须退回重新发散。公开型号只能在"
            "Query专属构型形成之后用于核验最近基线，不能充当生成起点。"
        ),
        "examples_are_non_exhaustive": True,
        "illustrative_names_are_not_facts": True,
        "naming_style_references": [],
        "naming_reference_rule": (
            "不提供固定装备名称、装备族、技术词表或句式范例。由Codex CLI从当前Query的完整军事语义"
            "独立形成装备身份、作战概念、制胜机理和自然名称。"
        ),
        "model_creative_reference": (
            "仅供自由制胜角度形成后的Codex理解创新跨度、装备具体度和自然命名表达：例如，高功率微波"
            "巡飞弹体现以新质电磁效应直接压制无人蜂群与电子设备、改变逐目标拦截的交换关系；仿生扑翼"
            "微型侦察打击弹体现以低慢小、低可探测构型进入城市巷战等新场景并实施隐蔽精确毁伤；高超音速"
            "滑翔增程精确打击远程火箭弹体现以跨代射程、速度、生存与精度压制传统火力；隐身无人僚机伴随"
            "火力支援系统体现有人平台与低可探测无人战斗节点重构平台关系和毁伤半径；量子雷达或其他非GPS"
            "依赖的新型探测制导微型精确弹只作为更长期的前瞻概念表达示例，相关探测、抗干扰和精确定位能力"
            "必须按证据、物理边界与工程成熟度写成待验证假设，绝不能把‘无视干扰’等示意效果写成既成事实。"
            "模块化巡飞弹—通用弹药系列体现的也不是给普通弹药增加接口，而是让武器架构、认证边界和"
            "柔性制造共同改变战时补充速度与成本交换关系；只有这种关系确由Query牵引时才值得借鉴。"
            "‘蜂鸟’仿生扑翼微型作战弹只用于示意自然/生物意象如何承载真实运动构型并保留装备身份；"
            "‘蚁群’分布式微型效应弹只用于示意群体组织意象如何表达分布式作战存在方式。引号、两字意象"
            "和上述装备类别均非必选格式，不能复制为默认系列。"
            "这里的名称、目标、"
            "装备族、技术组合和示意性能均不是事实、答案、目录或配额，只用于理解‘真实高技术构型或新效应"
            "机理+具体主装备身份+颠覆交战关系与直接战果’的表达密度。Codex可借鉴思考方式、重构或全部"
            "舍弃，不得复制名称、数字与句式；最终内容必须由当前Query、自由制胜角度和证据边界独立推导。"
        ),
        "combat_subject_requirement": (
            "候选主体必须是可独立立项、研制、改装和试验的具体战斗/打击型武器装备："
            "平台、弹药、拦截器、定向能或电子攻击效应器、武装无人平台等，直接承担"
            "打击、歼灭、毁伤、杀伤、突防、压制、物理拦截、拒止或续接火力任务。"
            "仅有侦察、感知、通信或决策能力而没有直接战斗效应的对象不得作为最终候选。"
        ),
        "theme_lanes": [],
        "innovation_lenses": [],
        "foresight_first_rule": (
            "质量集群和动态蜂群的前置阶段必须先形成若干机制互异、由Query语义独立推导的"
            "前瞻新质竞争假设，优先检验其是否改变成本、平台、时间、毁伤、体系、伦理与博弈逻辑，"
            "是否在传统能力红海形成跨代优势，或在新质能力蓝海形成高维优速优势；随后再按"
            "Query相关性、具体武器身份、直接军事效果、证据边界和可证伪性收敛。优先发散不等于"
            "固定覆盖、分类配额或新颖词汇竞赛；与Query无关、没有直接战果或不能落实为具体武器的"
            "方向必须舍弃。"
        ),
        "frontier_discontinuity_reference": (
            "前瞻性不是在常规装备上追加智能化标签，而是检验是否形成前沿、创新、颠覆或新质的"
            "战斗能力：既可以由新原理、新构型或新效应改变射程、速度、生存、发现、毁伤与成本"
            "交换关系，也可以由新的作战运用、跨域组合或体系架构改变能力需求维度和制胜方式。"
            "以上只规定创新跨度，不是装备目录、技术配额或默认答案；Codex必须依据当前Query"
            "自行选择、改写或全部舍弃，并落实到具体直接战斗装备和直接军事效果。组合Judge先"
            "判断创新价值与颠覆增量，不以已经明确可落实的物理/工程断层、成熟度、工程瓶颈或"
            "试验方案作为前置条件；这些内容留给后续装备化和工程论证深化。"
        ),
        "frontier_evidence_policy": (
            "前瞻新研装备公开对象证据不足时，不得因尚无同名型号或完整系统公开材料而直接淘汰。"
            "可使用相邻项目、组成技术、效应机理或类比装备证据支撑可行边界；若有证据应保留可追溯"
            "引用并明确公开证据支持什么、不支持什么、哪些属于研究假设。证据引用和证据边界是推荐项，"
            "不是前瞻灵感方向的强制门槛。反证、失效边界和"
            "可证伪验证/淘汰条件应尽量在前置阶段形成；暂缺时作为低优先级补全项，不因其单独淘汰"
            "具有高价值的新质装备灵感。不得把未来性能、TRL、成本、产能或列装状态写成既成事实。"
            "现役升级或声称具名公开型号既有能力时，有与对象或装备族直接匹配的证据应优先引用；"
            "没有该证据时不得虚构既有属性，但不得仅因证据缺失而让前瞻灵感方向失败。"
        ),
        "project_function_requirement": (
            "每个收敛候选必须显式给出项目功能：谁在何种场景/约束下，依靠哪一种具体装备，"
            "完成何种侦察、压制、突防、拦截、打击、毁伤、拒止或火力续接动作，并解决Query中的"
            "哪一个任务链断点。项目功能不得只写智能化、体系化、低成本或规模化。"
        ),
        "convergence_gate": [
            "装备项目暂定名与概念/公开项目身份",
            "单一主装备形态",
            "项目功能",
            "Query因果关系与目标/阶段",
            "直接军事效果",
            "公开基线差异与证据问题",
            "体系接口、成本产能和失效边界",
            "可证伪验证与淘汰条件",
        ],
        "support_only_exclusion": (
            "通信、C2、算法、网关、供应链、产线、后勤、软件和治理不能独立占用最终武器方向；"
            "它们只能作为具体战斗装备的接口、工程约束、规模化条件或横向支撑层。"
        ),
        "direct_weapon_convergence_test": [
            "能够指出单一、具体、可研制和可试验的主武器装备对象",
            "该装备自身携带或投送直接效应器，而非仅为其他武器提供信息或通信",
            "能够明确敌方目标及打击、歼灭、毁伤、杀伤、压制或物理拦截结果",
            "装备构型、发射/释放域、毁伤机理与Query任务阶段直接匹配",
            "新质性体现为改变Query中的关键对抗关系，而非堆叠智能化、无人化等标签",
        ],
        "safety_boundary": (
            "保持任务级和装备论证级抽象，不输出制造参数、攻击坐标、实时目标信息或可直接执行的交战指令。"
        ),
    }


def _query_led_combat_equipment_theme_instruction() -> str:
    contract = _query_led_combat_equipment_theme_contract()
    return (
        "装备主题共同约束："
        + str(contract["query_precedence"])
        + str(contract["divergence_mode"])
        + str(contract["combat_subject_requirement"])
        + str(contract["naming_reference_rule"])
        + str(contract["model_creative_reference"])
        + str(contract["foresight_first_rule"])
        + str(contract["frontier_discontinuity_reference"])
        + str(contract["frontier_evidence_policy"])
        + str(contract["project_function_requirement"])
        + str(contract["support_only_exclusion"])
        + str(contract["safety_boundary"])
    )


def _conditional_priority_observation_lenses(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """No keyword-driven equipment lens is allowed to preselect a direction."""

    del topic, structured_query_brief
    return []


def _query_combat_equipment_divergence_brief(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose the Codex-authored semantic divergence brief to downstream Agents."""

    brief = dict(structured_query_brief or {})
    # Blueprint names are disposable planning labels.  Passing them into S3
    # anchors otherwise isolated Codex sessions to the same codename grammar
    # (for example, every candidate inheriting one acronym suffix).  Preserve
    # the military thesis and equipment constraints while withholding the
    # provisional title so S3 authors the actual equipment identity naturally.
    equipment_hypotheses = [
        {key: item for key, item in row.items() if key != "project_name"}
        for row in brief.get("equipment_project_hypotheses", [])
        if isinstance(row, Mapping)
    ]
    frontier_hypotheses = [
        {
            key: item
            for key, item in row.items()
            if key
            in {
                "enabling_principle",
                "innovation_mode",
                "equipment_implication",
                "query_causal_link",
                "direct_military_effect",
                "disruptive_delta",
                "conventional_absorption_limit",
                "technology_horizon",
                "engineering_bottleneck",
                "disconfirming_condition",
            }
        }
        for row in brief.get("frontier_technology_hypotheses", [])
        if isinstance(row, Mapping)
    ]
    return {
        "query": _clean_capability_handoff_text(topic, limit=600),
        "combat_problem_frame": str(brief.get("combat_problem_frame", ""))[:900]
        or "由前置Codex Agent依据完整query语义建立任务对象、对手、作战阶段和关键矛盾，不做关键词枚举匹配。",
        "enemy_target_profile": _compact_prompt_value(
            brief.get("enemy_target_profile", []),
            max_string_chars=260,
            max_list_items=6,
        ),
        "battle_phase_and_constraints": _compact_prompt_value(
            brief.get("battle_phase_and_constraints", []),
            max_string_chars=260,
            max_list_items=8,
        ),
        "required_direct_military_effects": _compact_prompt_value(
            brief.get("required_direct_military_effects", []),
            max_string_chars=260,
            max_list_items=6,
        ),
        "equipment_semantic_boundary": str(
            brief.get("equipment_semantic_boundary", "")
        )[:700],
        "winning_problem_propositions": _compact_prompt_value(
            brief.get("winning_problem_propositions", []),
            max_string_chars=360,
            max_list_items=6,
        ),
        "weapon_design_variables": _compact_prompt_value(
            brief.get("weapon_design_variables", []),
            max_string_chars=260,
            max_list_items=8,
        ),
        "query_specific_weapon_architectures": _compact_prompt_value(
            brief.get("query_specific_weapon_architectures", []),
            max_string_chars=360,
            max_list_items=6,
        ),
        "frontier_technology_hypotheses": _compact_prompt_value(
            frontier_hypotheses,
            max_string_chars=420,
            max_list_items=6,
        ),
        "equipment_project_hypotheses": _compact_prompt_value(
            equipment_hypotheses,
            max_string_chars=420,
            max_list_items=6,
        ),
        "rejected_template_anchors": _compact_prompt_value(
            brief.get("rejected_template_anchors", []),
            max_string_chars=260,
            max_list_items=6,
        ),
        "conditional_priority_observation_lenses": (
            _conditional_priority_observation_lenses(
                topic,
                structured_query_brief=brief,
            )
        ),
        "generation_rules": [
            "以Codex对完整query的语义推演为主，不按提示词表或固定装备目录匹配",
            "先开放推演多种query专属武器架构，再用对象证据、直接军事价值和机制差异收敛",
            "每个收敛项目必须明确具体装备形态、项目功能、Query因果链、证据问题与淘汰条件",
            "蓝图暂定名不向S3传递；S3必须根据完整军事语义重新形成最终候选名称",
            "共享Prompt示例只作为反事实启发，不能决定装备类别、配额或命名",
            "执行跨Query替换自检：若更换任务对象、威胁和作战阶段后候选仍无需实质修改，则判为模板化并重做",
            "主动探索不复述共享示例、且由本Query制胜矛盾自然推导的新质打击杀伤装备架构；没有成立者时不得凑数",
            "同时执行前沿新质机会扫描：开放探索新原理、新构型、新效应、新作战运用和跨域组合，重点判断前沿性、创新性、颠覆性与新质战斗价值；工程断层、成熟度和瓶颈不是Judge前置条件",
            "W2若形成高质量具体装备、直接战果、差异机理和证据边界，应合并保留",
            "不得用预置装备类别、技术关键词或固定创新维度限制Codex CLI的发散空间",
        ],
    }


class FakeAgentProvider:
    enforce_profile_stops = False

    def design_discovery_blueprint(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {}

    def converge_discovery_outputs(self, payload: dict[str, Any]) -> dict[str, Any]:
        packets = payload.get("packets", [])
        return {
            "clusters": [
                {
                    "name": str(item.get("agent_id", "baseline")),
                    "packet_ids": [str(item.get("packet_id", ""))],
                    "shared_need": str(item.get("handoff_summary", "")),
                }
                for item in packets
            ],
            "conflicts": [],
            "priorities": [
                str(item.get("handoff_summary", "")) for item in packets[:6]
            ],
            "cross_branch_links": [],
            "open_questions": [
                str(question)
                for item in packets
                for question in item.get("open_questions", [])[:2]
            ][:8],
        }

    def review_discovery_meta_loop(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {}

    def select_agents(self, request: AgentSelectionRequest) -> AgentSelectionResult:
        remaining = set(request.required_capability_tags)
        selected: list[str] = []
        candidates = list(request.candidates)
        while candidates and remaining:
            candidate = max(
                candidates,
                key=lambda item: len(set(item.get("capability_tags", [])) & remaining),
            )
            covered = set(candidate.get("capability_tags", [])) & remaining
            if not covered:
                break
            selected.append(str(candidate["agent_id"]))
            remaining -= covered
            candidates.remove(candidate)
        return AgentSelectionResult(
            selected_agent_ids=selected,
            rationale="离线模式按任务所需 capability 计算最小覆盖 Agent 集。",
            task_analysis=[
                f"研究路线={request.research_route}",
                f"必需能力={','.join(request.required_capability_tags)}",
            ],
            dependency_notes=["依赖关系由 Agent Registry 在选择完成后生成执行波次。"],
            model_used=False,
        )

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        agent = request.agent
        prefix = agent.display_name
        topic = request.topic
        suffix = "-1" if request.round_index == 1 else f"-r{request.round_index}"
        evidence = EvidenceCard(
            evidence_id=f"ev-{agent.agent_id}{suffix}",
            source_title=f"{prefix}离线验证材料",
            source_url=f"https://fixture.local/{agent.agent_id}",
            source_tier="A",
            claim=f"{prefix}发现与“{topic}”相关的关键能力信号。",
            excerpt=f"围绕{topic}的公开资料显示，{prefix}维度存在可用于能力画像研判的信号。",
            source_location="fixture:1",
            quality_assessment="offline_fixture",
            created_by=agent.agent_id,
        )
        findings = _findings_for_agent(agent.agent_id, topic, request.research_route)
        upstream = request.context.get("upstream_handoffs", [])
        if upstream:
            findings.append(
                "已综合上游结构化交接："
                + "、".join(str(item.get("agent_id", "")) for item in upstream)
                + "；仅消费摘要、证据索引和开放问题。"
            )
        analysis_sections = _analysis_sections_for_agent(
            agent.agent_id, topic, request.research_route
        )
        payload_type, typed_payload, packet_version = _typed_packet_payload(
            agent.agent_id, analysis_sections
        )
        if upstream:
            analysis_sections["upstream_synthesis"] = {
                "consumed_agents": [item.get("agent_id") for item in upstream],
                "handoff_summaries": [item.get("handoff_summary") for item in upstream],
                "open_questions": [
                    question
                    for item in upstream
                    for question in item.get("open_questions", [])
                ],
            }
        packet = BaselineFindingPacket(
            packet_id=(
                f"packet-{agent.agent_id}"
                if request.round_index == 1
                else f"packet-{agent.agent_id}-r{request.round_index}"
            ),
            agent_id=agent.agent_id,
            capability_tags=list(agent.capability_tags),
            topic_focus=topic,
            findings=findings,
            evidence_ids=[evidence.evidence_id],
            confidence=0.78,
            coverage_notes=[
                f"{prefix}维度已形成离线可审计初步发现。",
                "该结果用于验证多agent闭环，真实运行需替换为联网证据。",
            ],
            open_questions=[
                f"{prefix}维度仍需进一步联网补充高置信资料。",
            ],
            handoff_summary=f"{prefix}围绕{topic}形成{len(findings)}条基线发现，并按交接策略输出给下游。",
            checkpoint=f"{agent.agent_id}: baseline round {request.round_index} complete",
            claim_ids=[
                "claim-" + sha256(f"{agent.agent_id}:{item}".encode()).hexdigest()[:12]
                for item in findings
            ],
            analysis_sections=analysis_sections,
            payload_type=payload_type,
            payload=typed_payload,
            schema_version=packet_version,
        )
        return AgentRunResult(
            packet=packet, evidence=[evidence], raw_message=packet.handoff_summary
        )


class RealAgentProvider(FakeAgentProvider):
    """Initial real-mode provider.

    This first deliverable keeps the model-facing runtime pluggable while still
    producing auditable artifacts. It records that public web evidence should be
    materialized through tools; model API integration can replace this provider
    without changing orchestration contracts.
    """

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        result = super().run_baseline_agent(request)
        public_url = _public_smoke_url_for_agent(request.agent.agent_id)
        evidence = [
            EvidenceCard(
                evidence_id=item.evidence_id.replace("-1", "-real-smoke"),
                source_title=item.source_title.replace(
                    "离线验证材料", "真实模式待材料化线索"
                ),
                source_url=public_url,
                source_tier=item.source_tier,
                claim=item.claim,
                excerpt=item.excerpt + " real模式首版保留联网工具接入点。",
                source_location="real-smoke:public-url",
                quality_assessment="real_smoke_public_source",
                created_by=item.created_by,
            )
            for item in result.evidence
        ]
        packet = BaselineFindingPacket(
            **{
                **result.packet.__dict__,
                "evidence_ids": [item.evidence_id for item in evidence],
                "coverage_notes": [
                    *result.packet.coverage_notes,
                    "real模式首版验证运行链路和证据治理边界，后续可接入真实搜索provider。",
                ],
            }
        )
        return AgentRunResult(
            packet=packet, evidence=evidence, raw_message=packet.handoff_summary
        )

    def draft_report(self, payload: dict[str, Any]) -> str:
        """Return a bounded report fixture for the explicit ``smoke`` provider.

        This provider is used only by offline materialization/acceptance tests;
        production real-mode profiles still require the isolated Codex Reporter.
        """

        if _report_template_mode(payload) == "project_argument_v1":
            return _build_limited_report(payload)
        topic = str(payload.get("topic", "真实模式冒烟验证")).strip()
        return f"""## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

{topic}仅验证真实模式证据材料化、任务恢复和交付接口，不形成正式军事结论；对手、地域、烈度、时间窗与约束均待正式研究。

### ② 新战法或新概念技术及制胜机理

公开线索经过材料化、证据门控和任务链映射后，才能进入能力需求判断；失败来源不得作为事实依据。

### ③ 装备能力特征清单

本冒烟报告不生成射程、响应时间、自主等级、成本或规模等能力指标，仅确认三层九项数据结构能够交付。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

后续正式运行应判断各项能力属于沿用改进、集成创新或原理突破；本冒烟报告不作工程结论。

### ⑤ 核心技术清单与攻关优先级

核心技术点、成熟度、瓶颈与优先级均需在正式研究中依据公开证据形成。

### ⑥ 技术耦合与短板风险

本次不判断技术依赖与卡脖子环节，所有耦合关系均待验证。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

本次不外推具体装备谱系位置，仅验证能力图像章节能够交付。

### ⑧ 效能贡献评估

本次不评估补链、强链或开链效能，不形成突防率、交换比或决策周期改善结论。

### ⑨ 发展优先级与近期抓手

所有事实边界以材料化状态和公开来源为准；真实研究需重新执行联网检索、反证和专家复核。
"""


class ResponsesAgentProvider:
    """Turns a Responses-compatible model result into a constrained handoff.

    This adapter deliberately does not turn model-claimed URLs into evidence.
    Evidence must still be produced by the network tool/materialization chain.
    """

    uses_hosted_web_search = True
    enforce_profile_stops = True

    def __init__(
        self,
        provider: ModelProvider,
        *,
        agent_providers: Mapping[str, ModelProvider] | None = None,
        agent_definitions: Mapping[str, AgentDef] | None = None,
        harness_profiles: Mapping[str, HarnessProfile] | None = None,
        model_options: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.agent_providers = dict(agent_providers or {})
        snapshot = getattr(provider, "snapshot", lambda: {})()
        self.provider_kind = str(snapshot.get("type", "responses"))
        self.discovery_provider = self._build_discovery_provider()
        self.discovery_backend = (
            "responses_http"
            if self.discovery_provider is not None
            else self.provider_kind
        )
        self.agent_definitions = (
            dict(agent_definitions or {}) if self.provider_kind == "codex_cli" else {}
        )
        self.agent_designs = AgentDesignRegistry.load_default()
        self.baseline_workflow = BaselineAgentService(self.agent_designs)
        self.harness_profiles = (
            dict(harness_profiles or {}) if self.provider_kind == "codex_cli" else {}
        )
        self.model_options = model_options or {
            "reasoning_effort": "high",
            "max_output_tokens": 5000,
            "web_search": {
                "search_context_size": "high",
                "external_web_access": True,
            },
            "include_web_sources": True,
            "require_web_search": True,
        }
        self._winning_progress_callback: Callable[[dict[str, Any]], None] | None = None
        self._reporter_progress_callback: Callable[[dict[str, Any]], None] | None = None
        self._baseline_progress_callback: Callable[[dict[str, Any]], None] | None = None
        self._call_metrics: list[dict[str, Any]] = []
        self._call_metrics_lock = RLock()
        self._isolated_agent_providers: dict[str, ModelProvider] = {}
        self._isolated_agent_providers_lock = RLock()
        self._call_gate = AdaptiveCallGate()
        self._discovery_cache: dict[
            tuple[str, str, int], tuple[str, dict[str, Any]]
        ] = {}
        self._discovery_inflight: dict[
            tuple[str, str, int], Future[tuple[str, dict[str, Any]]]
        ] = {}
        self._discovery_lock = RLock()
        self._shared_discovery_sources: dict[str, dict[str, dict[str, Any]]] = {}
        self._runtime_budgets: dict[str, int | float] = {}
        self._run_started_at = monotonic()
        self._budget_started_calls = 0
        self._budget_started_delivery_calls = 0
        self._budget_started_swarm_calls = 0
        self._budget_started_quality_judge_calls = 0
        self._search_batches_started = 0
        self._last_report_quality_issues: list[str] = []
        self._latest_report_draft = ""
        self._s6_card_result_cache: dict[
            tuple[str, str], tuple[dict[str, Any], str]
        ] = {}
        self._budget_lock = RLock()
        self._closed = False

    def close(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import close

        return close(self, *args, **kwargs)

    def configure_run_budget(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            configure_run_budget,
        )

        return configure_run_budget(self, *args, **kwargs)

    def _deadline_state(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import deadline_state

        return deadline_state(self, *args, **kwargs)

    def _deadline_adjusted_options(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            deadline_adjusted_options,
        )

        return deadline_adjusted_options(self, *args, **kwargs)

    def _optional_work_allowed(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            optional_work_allowed,
        )

        return optional_work_allowed(self, *args, **kwargs)

    def _reserve_model_call(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import reserve_model_call

        return reserve_model_call(self, *args, **kwargs)

    def _reserve_search_batches(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            reserve_search_batches,
        )

        return reserve_search_batches(self, *args, **kwargs)

    def set_winning_progress_callback(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            set_winning_progress_callback,
        )

        return set_winning_progress_callback(self, *args, **kwargs)

    def set_baseline_progress_callback(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            set_baseline_progress_callback,
        )

        return set_baseline_progress_callback(self, *args, **kwargs)

    def set_reporter_progress_callback(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            set_reporter_progress_callback,
        )

        return set_reporter_progress_callback(self, *args, **kwargs)

    def _emit_baseline_progress(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            emit_baseline_progress,
        )

        return emit_baseline_progress(self, *args, **kwargs)

    def _emit_winning_progress(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            emit_winning_progress,
        )

        return emit_winning_progress(self, *args, **kwargs)

    def _emit_reporter_progress(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            emit_reporter_progress,
        )

        return emit_reporter_progress(self, *args, **kwargs)

    def _emit_model_progress(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import emit_model_progress

        return emit_model_progress(self, *args, **kwargs)

    def _record_call_metric(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import record_call_metric

        return record_call_metric(self, *args, **kwargs)

    def _call_metric_count(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import call_metric_count

        return call_metric_count(self, *args, **kwargs)

    def _call_metrics_since(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import call_metrics_since

        return call_metrics_since(self, *args, **kwargs)

    def run_baseline_agent(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import (
            run_baseline_agent,
        )

        return run_baseline_agent(self, *args, **kwargs)

    def prefetch_baseline_agent(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import (
            prefetch_baseline_agent,
        )

        return prefetch_baseline_agent(self, *args, **kwargs)

    def select_agents(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import select_agents

        return select_agents(self, *args, **kwargs)

    def analyze_winning_mechanism(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            analyze_winning_mechanism,
        )

        return analyze_winning_mechanism(self, *args, **kwargs)

    def design_discovery_blueprint(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            design_discovery_blueprint,
        )

        return design_discovery_blueprint(self, *args, **kwargs)

    def converge_discovery_outputs(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            converge_discovery_outputs,
        )

        return converge_discovery_outputs(self, *args, **kwargs)

    def review_discovery_meta_loop(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            review_discovery_meta_loop,
        )

        return review_discovery_meta_loop(self, *args, **kwargs)

    def review_audit(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import review_audit

        return review_audit(self, *args, **kwargs)

    def draft_report(self, payload: dict[str, Any]) -> str:
        from equipment_deep_research.agents.workflows.reporter import draft_report

        return draft_report(self, payload)

    def _draft_parallel_report(self, *args: Any, **kwargs: Any) -> str:
        from equipment_deep_research.agents.workflows.reporter import (
            draft_parallel_report,
        )

        return draft_parallel_report(self, *args, **kwargs)

    def _limited_report_delivery(self, *args: Any, **kwargs: Any) -> str:
        from equipment_deep_research.agents.workflows.reporter import (
            limited_report_delivery,
        )

        return limited_report_delivery(self, *args, **kwargs)

    def _draft_report_attempt(self, *args: Any, **kwargs: Any) -> str:
        from equipment_deep_research.agents.workflows.reporter import (
            draft_report_attempt,
        )

        return draft_report_attempt(self, *args, **kwargs)

    async def _run_reporter_text(self, *args: Any, **kwargs: Any) -> str:
        from equipment_deep_research.agents.workflows.reporter import run_reporter_text

        return await run_reporter_text(self, *args, **kwargs)

    def consume_report_quality_issues(self) -> list[str]:
        from equipment_deep_research.agents.workflows.reporter import (
            consume_report_quality_issues,
        )

        return consume_report_quality_issues(self)

    async def _select_agents(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            select_agents_async,
        )

        return await select_agents_async(self, *args, **kwargs)

    async def _run(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import run

        return await run(self, *args, **kwargs)

    async def _discovery_for_request(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import (
            discovery_for_request,
        )

        return await discovery_for_request(self, *args, **kwargs)

    async def _discover(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import discover

        return await discover(self, *args, **kwargs)

    async def _repair_baseline_output(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.baseline_execution import (
            repair_baseline_output,
        )

        return await repair_baseline_output(self, *args, **kwargs)

    async def _collect_stream(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import collect_stream

        return await collect_stream(self, *args, **kwargs)

    async def _analyze_winning_mechanism(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.orchestrator import (
            analyze_winning_mechanism_async,
        )

        return await analyze_winning_mechanism_async(self, *args, **kwargs)

    async def _analyze_winning_subagents(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from equipment_deep_research.agents.workflows.winning import (
            analyze_winning_subagents,
        )

        return await analyze_winning_subagents(self, payload)

    def _provider_for(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import provider_for

        return provider_for(self, *args, **kwargs)

    def _build_discovery_provider(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            build_discovery_provider,
        )

        return build_discovery_provider(self, *args, **kwargs)

    def _discovery_provider_for(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import (
            discovery_provider_for,
        )

        return discovery_provider_for(self, *args, **kwargs)

    def _model_call_metric(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import model_call_metric

        return model_call_metric(self, *args, **kwargs)

    async def _run_core_json(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import run_core_json

        return await run_core_json(self, *args, **kwargs)

    async def _run_core_text(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import run_core_text

        return await run_core_text(self, *args, **kwargs)

    def _runtime_messages(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import runtime_messages

        return runtime_messages(self, *args, **kwargs)

    def _harness_for(self, *args: Any, **kwargs: Any) -> Any:
        from equipment_deep_research.agents.workflows.runtime import harness_for

        return harness_for(self, *args, **kwargs)


def _winning_step_modes(payload: Mapping[str, Any]) -> dict[int, str]:
    blueprint = payload.get("discovery_blueprint", {})
    branch = (
        str(blueprint.get("primary_branch", ""))
        if isinstance(blueprint, Mapping)
        else ""
    )
    branch = branch or str(payload.get("discovery_branch", ""))
    adaptive = (
        blueprint.get("adaptive_winning_step_modes", {})
        if isinstance(blueprint, Mapping)
        else {}
    )
    return winning_step_modes(
        branch,
        research_route=str(payload.get("research_route", "")),
        adaptive_modes=adaptive if isinstance(adaptive, Mapping) else None,
    )


def _winning_military_divergence_contract(step: int) -> dict[str, Any]:
    step_rules: dict[int, dict[str, Any]] = {
        1: {
            "minimum_competing_mechanisms": 3,
            "diverge_on": ["对手体系构型", "反适应方式", "任务链薄弱环节"],
            "converge_by": "对我方打击/反制窗口、对手替代链和证据强度",
        },
        2: {
            "minimum_competing_mechanisms": 3,
            "diverge_on": ["决策权分配", "力量组织", "效应递进与协同方式"],
            "converge_by": "打击/歼灭闭环、拒止强度、战损续接和失败代价",
        },
        3: {
            "minimum_competing_mechanisms": 3,
            "diverge_on": ["关键前提", "突破机理", "直接与间接效果链"],
            "converge_by": "作战效果增量、对手反适应、跨场景稳健性和可证伪性",
        },
        4: {
            "minimum_competing_mechanisms": 3,
            "diverge_on": ["装备功能组合", "体系接口", "现役升级与新研边界"],
            "converge_by": "至少2项直接作战效应、工程约束、成熟度和验证路径",
        },
        5: {
            "minimum_competing_mechanisms": 3,
            "diverge_on": ["现役升级", "中长期新研", "非装备缓解"],
            "converge_by": "可恢复的打击/拦截/反制/拒止效果、证据强度和时间成本",
        },
    }
    return {
        "step": int(step),
        "primary_anchor": "query_military_problem",
        "upstream_role": "evidence_constraints_counterevidence_only",
        "anti_anchor_rule": "不得继承上游议程、结构、术语或结论；不得以通信、接口、治理或保障改善替代直接作战价值",
        "required_effect_families": [
            "目标发现与持续跟踪",
            "火力分配与打击毁伤",
            "突防拦截与反制压制",
            "区域拒止与威慑",
            "抗毁恢复与任务续接",
        ],
        **step_rules.get(int(step), step_rules[3]),
    }


def _compact_prompt_value(
    value: Any,
    *,
    max_string_chars: int = 900,
    max_list_items: int = 8,
) -> Any:
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        # Prompt compaction must never manufacture a fragment that downstream
        # specialists can mistake for a complete mechanism or evidence claim.
        # Prefer a complete clause; if the source has no safe boundary, retain
        # it intact instead of replacing missing semantics with an ellipsis.
        return _clip_complete_report_phrase(value, max_string_chars)
    if isinstance(value, Mapping):
        return {
            str(key): _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
    return value


def _bounded_unique_texts(
    values: Sequence[Any],
    *,
    limit: int,
    max_chars: int,
) -> list[str]:
    """Keep a small, non-redundant first/last projection of an evolving list."""

    unique: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = re.sub(r"\s+", " ", str(raw)).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    if len(unique) > limit:
        first_count = (limit + 1) // 2
        last_count = limit - first_count
        unique = (
            [*unique[:first_count], *unique[-last_count:]]
            if last_count
            else unique[:limit]
        )
    return [
        _compact_prompt_value(item, max_string_chars=max_chars, max_list_items=limit)
        for item in unique
    ]


def _compact_swarm_candidate_handoff(
    item: WinningHypothesis,
    *,
    blind_label: str = "",
    portfolio_summary: bool = False,
) -> dict[str, Any]:
    """Project one candidate into a decision-complete, role-neutral handoff.

    Winning hypotheses accumulate S3-S6 patches over time. Passing every
    historical list entry to later roles made the portfolio reviewer and
    quality judge reread repeated context instead of comparing the candidates.
    Keep the causal spine, equipment landing point, evidence boundary and
    falsification fields while preserving both the original basis and the most
    recent repair additions.
    """

    payload: dict[str, Any] = {
        "hypothesis_id": item.hypothesis_id,
        "title": _compact_prompt_value(item.title, max_string_chars=120),
        "nearest_public_baseline": _compact_prompt_value(
            item.nearest_public_baseline,
            max_string_chars=220,
        ),
        "changed_confrontation_variable": _compact_prompt_value(
            item.changed_confrontation_variable,
            max_string_chars=180,
        ),
        "winning_angle_id": _compact_prompt_value(
            item.winning_angle_id,
            max_string_chars=160,
        ),
        "combat_dimension": _compact_prompt_value(
            item.combat_dimension,
            max_string_chars=80,
        ),
        "dimension_winning_logic": _compact_prompt_value(
            item.dimension_winning_logic,
            max_string_chars=220,
        ),
        "original_paradigm": _compact_prompt_value(
            item.original_paradigm,
            max_string_chars=220,
        ),
        "disruptive_shift": _compact_prompt_value(
            item.disruptive_shift,
            max_string_chars=220,
        ),
        "independence_thesis": _compact_prompt_value(
            item.independence_thesis,
            max_string_chars=220,
        ),
        "mechanism_chain": _bounded_unique_texts(
            item.mechanism_chain,
            limit=4,
            max_chars=150,
        ),
        "direct_military_effects": _bounded_unique_texts(
            item.direct_military_effects,
            limit=4,
            max_chars=130,
        ),
        "equipment_forms": _bounded_unique_texts(
            item.equipment_forms,
            limit=3,
            max_chars=170,
        ),
        "project_function": _compact_prompt_value(
            item.project_function,
            max_string_chars=220,
        ),
        "reference_overview": _compact_prompt_value(
            item.reference_overview,
            max_string_chars=900,
        ),
        "naming_rationale": _compact_prompt_value(
            item.naming_rationale,
            max_string_chars=220,
        ),
        "decisive_advantage_thesis": _compact_prompt_value(
            item.decisive_advantage_thesis,
            max_string_chars=240,
        ),
        "cross_query_distinction": _compact_prompt_value(
            item.cross_query_distinction,
            max_string_chars=220,
        ),
        "system_interfaces": _bounded_unique_texts(
            item.system_interfaces,
            limit=4,
            max_chars=100,
        ),
        "novelty_delta": _compact_prompt_value(
            item.novelty_delta,
            max_string_chars=180,
        ),
        "evidence_ids": _bounded_unique_texts(
            item.evidence_ids,
            limit=8,
            max_chars=90,
        ),
        "evidence_boundary": _compact_prompt_value(
            item.evidence_boundary,
            max_string_chars=240,
        ),
        "counterevidence": _bounded_unique_texts(
            item.counterevidence,
            limit=3,
            max_chars=130,
        ),
        "adversary_adaptations": _bounded_unique_texts(
            item.adversary_adaptations,
            limit=3,
            max_chars=120,
        ),
        "failure_boundaries": _bounded_unique_texts(
            item.failure_boundaries,
            limit=4,
            max_chars=130,
        ),
        "trl_constraints": _bounded_unique_texts(
            item.trl_constraints,
            limit=3,
            max_chars=110,
        ),
        "cost_constraints": _bounded_unique_texts(
            item.cost_constraints,
            limit=3,
            max_chars=110,
        ),
        "industrial_constraints": _bounded_unique_texts(
            item.industrial_constraints,
            limit=3,
            max_chars=110,
        ),
        "cross_scenario_results": _bounded_unique_texts(
            item.cross_scenario_results,
            limit=3,
            max_chars=120,
        ),
        "validation_plan": _bounded_unique_texts(
            item.validation_plan,
            limit=4,
            max_chars=130,
        ),
        "implementation_path": item.implementation_path,
        "score": round(float(item.score), 3),
    }
    if portfolio_summary:
        # A portfolio reviewer compares the whole ledger.  Preserve the
        # decision spine for every candidate while removing engineering-detail
        # lists that are already checked by targeted S4/S5/S6 contributors and
        # the final quality judge.  This keeps global comparison auditable
        # without multiplying the full candidate record by 8-20 branches.
        payload = {
            "hypothesis_id": payload["hypothesis_id"],
            "title": payload["title"],
            "nearest_public_baseline": _compact_prompt_value(
                item.nearest_public_baseline,
                max_string_chars=140,
            ),
            "changed_confrontation_variable": _compact_prompt_value(
                item.changed_confrontation_variable,
                max_string_chars=120,
            ),
            "winning_angle_id": _compact_prompt_value(
                item.winning_angle_id,
                max_string_chars=100,
            ),
            "original_paradigm": _compact_prompt_value(
                item.original_paradigm,
                max_string_chars=140,
            ),
            "disruptive_shift": _compact_prompt_value(
                item.disruptive_shift,
                max_string_chars=140,
            ),
            "independence_thesis": _compact_prompt_value(
                item.independence_thesis,
                max_string_chars=140,
            ),
            "mechanism_chain": _bounded_unique_texts(
                item.mechanism_chain,
                limit=2,
                max_chars=110,
            ),
            "direct_military_effects": _bounded_unique_texts(
                item.direct_military_effects,
                limit=2,
                max_chars=100,
            ),
            "equipment_forms": _bounded_unique_texts(
                item.equipment_forms,
                limit=2,
                max_chars=120,
            ),
            "project_function": _compact_prompt_value(
                item.project_function,
                max_string_chars=150,
            ),
            "novelty_delta": _compact_prompt_value(
                item.novelty_delta,
                max_string_chars=120,
            ),
            "evidence_ids": _bounded_unique_texts(
                item.evidence_ids,
                limit=4,
                max_chars=80,
            ),
            "evidence_boundary": _compact_prompt_value(
                item.evidence_boundary,
                max_string_chars=140,
            ),
            "failure_boundaries": _bounded_unique_texts(
                item.failure_boundaries,
                limit=2,
                max_chars=100,
            ),
            "validation_plan": _bounded_unique_texts(
                item.validation_plan,
                limit=2,
                max_chars=100,
            ),
            "implementation_path": item.implementation_path,
            "score": round(float(item.score), 3),
        }
    if blind_label:
        payload["blind_label"] = blind_label
        payload.pop("hypothesis_id", None)
    return payload


def _compact_swarm_event_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep UI/audit projections without copying the complete ledger twice."""

    raw_ledger = value.get("hypothesis_ledger", {})
    raw_hypotheses = (
        raw_ledger.get("hypotheses", []) if isinstance(raw_ledger, Mapping) else []
    )
    hypotheses = []
    for item in raw_hypotheses[:20]:
        if not isinstance(item, Mapping):
            continue
        hypotheses.append(
            {
                "hypothesis_id": str(item.get("hypothesis_id", "")),
                "title": _compact_prompt_value(
                    str(item.get("title", "")),
                    max_string_chars=140,
                ),
                "status": str(item.get("status", "")),
                "score": item.get("score"),
                "equipment_forms": _bounded_unique_texts(
                    item.get("equipment_forms", []),
                    limit=2,
                    max_chars=120,
                ),
                "changed_confrontation_variable": _compact_prompt_value(
                    str(item.get("changed_confrontation_variable", "")),
                    max_string_chars=180,
                ),
                "mechanism_chain": _bounded_unique_texts(
                    item.get("mechanism_chain", []),
                    limit=4,
                    max_chars=130,
                ),
                "direct_military_effects": _bounded_unique_texts(
                    item.get("direct_military_effects", []),
                    limit=3,
                    max_chars=130,
                ),
                "project_function": _compact_prompt_value(
                    str(item.get("project_function", "")),
                    max_string_chars=180,
                ),
                "reference_overview": _compact_prompt_value(
                    str(item.get("reference_overview", "")),
                    max_string_chars=900,
                ),
                "novelty_delta": _compact_prompt_value(
                    str(item.get("novelty_delta", "")),
                    max_string_chars=180,
                ),
                "decisive_advantage_thesis": _compact_prompt_value(
                    str(item.get("decisive_advantage_thesis", "")),
                    max_string_chars=180,
                ),
                "evidence_ids": _bounded_unique_texts(
                    item.get("evidence_ids", []),
                    limit=6,
                    max_chars=90,
                ),
                "failure_boundaries": _bounded_unique_texts(
                    item.get("failure_boundaries", []),
                    limit=2,
                    max_chars=120,
                ),
                "validation_plan": _bounded_unique_texts(
                    item.get("validation_plan", []),
                    limit=2,
                    max_chars=120,
                ),
            }
        )
    receipts = []
    for item in value.get("merge_receipts", [])[:40]:
        if not isinstance(item, Mapping):
            continue
        receipts.append(
            {
                key: item.get(key)
                for key in (
                    "receipt_id",
                    "contribution_id",
                    "hypothesis_id",
                    "merge_target",
                    "base_ledger_version",
                    "resulting_ledger_version",
                    "status",
                    "changed_fields",
                    "conflicts",
                    "quality_delta",
                    "rebase_required",
                )
            }
        )
    raw_policy = value.get("policy", {})
    policy = raw_policy if isinstance(raw_policy, Mapping) else {}
    return {
        "policy": {
            key: policy.get(key)
            for key in (
                "policy_id",
                "max_concurrency",
                "finalist_minimum",
                "finalist_maximum",
                "expert_judge_required",
            )
        },
        "hypothesis_ledger": {
            "ledger_id": str(raw_ledger.get("ledger_id", ""))
            if isinstance(raw_ledger, Mapping)
            else "",
            "version": raw_ledger.get("version", 0)
            if isinstance(raw_ledger, Mapping)
            else 0,
            "status": str(raw_ledger.get("status", "active"))
            if isinstance(raw_ledger, Mapping)
            else "active",
            "hypotheses": hypotheses,
        },
        "merge_receipts": receipts,
        "portfolio_quality_gate": dict(value.get("portfolio_quality_gate", {}))
        if isinstance(value.get("portfolio_quality_gate"), Mapping)
        else {},
        "budget": dict(value.get("budget", {}))
        if isinstance(value.get("budget"), Mapping)
        else {},
        "final_merge": dict(value.get("final_merge", {}))
        if isinstance(value.get("final_merge"), Mapping)
        else {},
        "stop_reason": str(value.get("stop_reason", "")),
    }


def _compact_equipment_portfolio_event(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project final directions once for interaction views, without S6 bulk."""

    keep = (
        "hypothesis_id",
        "name",
        "priority",
        "type",
        "function",
        "feasibility",
        "horizon",
        "direct_evidence_refs",
        "military_value",
        "concise_winning_summary",
        "equipment_form",
        "operational_mechanism",
        "development_path",
        "failure_boundary",
        "confidence",
        "expert_score",
        "direct_combat_equipment",
        "verification_status",
        "confidence_limited",
        "selection_quality_status",
        "s6_eligible",
    )
    return [
        {
            key: _compact_prompt_value(
                item.get(key),
                max_string_chars=260,
                max_list_items=6,
            )
            for key in keep
            if item.get(key) not in (None, "", [], {})
        }
        for item in rows[:12]
        if isinstance(item, Mapping)
    ]


def _quality_judge_output_token_budget(candidate_count: int) -> int:
    """Scale review output to the actual blind-review set.

    The first portfolio review commonly carries ten candidates and still gets
    the full budget.  A repair review usually contains only one or two changed
    candidates; retaining the same 4,600-token ceiling increases latency and
    cost without adding independent coverage of unchanged candidates.
    """

    return min(4600, max(2600, 1800 + max(0, int(candidate_count)) * 800))


def _effective_expert_judge_status(
    rounds: Sequence[Mapping[str, Any]],
    *,
    assessed_count: int,
    expected_count: int,
) -> str:
    """Retain a complete earlier blind review if a bounded rejudge fails."""

    latest = str(rounds[-1].get("status", "limited")) if rounds else "failed"
    if latest == "completed":
        return "completed"
    complete_prior_round = any(
        str(item.get("status", "")) == "completed" for item in rounds[:-1]
    )
    if (
        complete_prior_round
        and int(expected_count) > 0
        and int(assessed_count) >= int(expected_count)
    ):
        return "completed"
    return latest


def _quality_judge_candidate_payload(
    item: WinningHypothesis,
    *,
    blind_label: str,
) -> dict[str, Any]:
    """Create a bounded, decision-complete record for S5 semantic review.

    Local residual calculators are intentionally not included.  They remain
    available in the audit ledger, but exposing them here anchored Codex to a
    mechanical verdict before it had read the candidate as a whole.
    """

    return _compact_swarm_candidate_handoff(
        item,
        blind_label=blind_label,
    )


def _quality_judge_scoped_evidence_index(
    evidence_index: Any,
    candidate_evidence_ids: set[str],
) -> list[dict[str, Any]]:
    """Keep only evidence cards referenced by the candidates under review."""

    rows = (
        [dict(item) for item in evidence_index if isinstance(item, Mapping)]
        if isinstance(evidence_index, Sequence)
        and not isinstance(evidence_index, (str, bytes))
        else []
    )
    scoped = [
        item
        for item in rows
        if str(item.get("evidence_id", "")) in candidate_evidence_ids
    ]
    return scoped or rows


def _branch_product_output_schema(branch: str) -> dict[str, Any]:
    """Expose only the current branch's narrative products to S6.

    The former all-branch schema encouraged the model to draft thirteen product
    families on every run. Besides wasting tokens, it diluted the branch-specific
    conclusions the delivery validator actually consumes.
    """
    schemas: dict[str, dict[str, Any]] = {
        "A": {
            "tactic_concepts": ["深度研判正文"],
            "tactic_combinations": ["深度研判正文"],
            "capability_domains": ["深度研判正文"],
            "capability_indicators": ["带任务口径和验证边界的指标正文"],
            "equipment_forms": ["深度研判正文"],
        },
        "B": {},
        "C": {
            "case_patterns": ["深度研判正文"],
            "future_scenarios": ["深度研判正文"],
            "emerging_equipment_categories": ["深度研判正文"],
        },
        "D": {
            "technology_opportunities": ["深度研判正文"],
            "future_scenarios": ["深度研判正文"],
            "equipment_forms": ["深度研判正文"],
        },
        "E": {
            "threat_patterns": ["深度研判正文"],
            "future_scenarios": ["深度研判正文"],
            "capability_domains": ["深度研判正文"],
            "equipment_forms": ["深度研判正文"],
        },
        "F": {
            "system_vulnerabilities": ["深度研判正文"],
            "future_scenarios": ["深度研判正文"],
            "capability_domains": ["深度研判正文"],
            "equipment_forms": ["深度研判正文"],
        },
        "G": {
            "cross_domain_gaps": ["深度研判正文"],
            "tactic_combinations": ["深度研判正文"],
            "capability_indicators": ["带任务口径和验证边界的指标正文"],
            "equipment_forms": ["深度研判正文"],
        },
        "H": {
            "emerging_threat_profiles": ["深度研判正文"],
            "future_scenarios": ["深度研判正文"],
            "capability_domains": ["深度研判正文"],
            "equipment_forms": ["深度研判正文"],
        },
    }
    return dict(schemas.get(str(branch), schemas["B"]))


_COMBAT_EFFECT_TERMS = (
    "作战",
    "打击",
    "火力",
    "反制",
    "突防",
    "毁伤",
    "目标",
    "杀伤链",
    "任务闭环",
    "抗毁",
    "持续保障",
)

_HIGH_ORDER_COMBAT_EFFECT_TERMS = (
    "目标发现",
    "目标识别",
    "目标捕获",
    "目标再捕获",
    "再捕获",
    "目标指示",
    "目标跟踪",
    "持续跟踪",
    "火力",
    "火力分配",
    "火力引导",
    "火力协同",
    "打击",
    "猎歼",
    "歼灭",
    "杀伤",
    "毁伤",
    "摧毁",
    "再打击",
    "补击",
    "补射",
    "突防",
    "拦截",
    "截击",
    "压制",
    "反制",
    "拒止",
    "威慑",
    "防空",
    "反导",
    "反舰",
    "制空",
    "制海",
    "夺控",
    "封控",
    "破袭",
    "瘫痪",
    "抗饱和",
)

_ORDINARY_SUPPORT_LAYER_TERMS = (
    "通信",
    "链路",
    "数据链",
    "网关",
    "接口",
    "同步",
    "治理",
    "审计",
    "保障",
    "恢复",
    "维修",
    "补给",
    "回收",
    "数据读取",
    "数据下载",
    "BDA",
)

_PRIMARY_SUPPORT_MISSION_TERMS = (
    "数据读取",
    "数据下载",
    "BDA",
    "回收/",
    "回收接口",
    "回收终端",
)

_STRONG_DIRECT_COMBAT_EFFECT_TERMS = (
    "打击",
    "猎歼",
    "歼灭",
    "杀伤",
    "毁伤",
    "摧毁",
    "再打击",
    "突防",
    "拦截",
    "截击",
    "压制",
    "反制",
    "拒止",
    "威慑",
    "破袭",
    "瘫痪",
)

_ANCILLARY_SUPPORT_EQUIPMENT_TERMS = (
    "伪装",
    "假目标",
    "假阵地",
    "诱饵阵地",
    "工程构设",
    "构设器",
    "效果评估终端",
    "维修",
    "补给",
    "运输",
    "保障",
)

_SUPPORT_FOCUSED_QUERY_TERMS = (
    "伪装装备",
    "假目标装备",
    "诱饵装备",
    "工程保障装备",
    "维修保障装备",
    "补给装备",
    "通信装备",
    "数据链装备",
    "后勤保障",
)

_FORBIDDEN_UPGRADE_NAME_TERMS = (
    "包",
    "套件",
    "保障",
    "通信",
    "链路",
    "数据链",
    "网关",
    "接口",
    "中间件",
    "治理",
    "审计",
    "恢复",
    "韧性",
)

_DIRECT_COMBAT_EQUIPMENT_NAME_TERMS = (
    "C2",
    "ISR",
    "指挥系统",
    "火控",
    "雷达",
    "预警机",
    "战斗机",
    "轰炸机",
    "破障车",
    "扫雷车",
    "防空车",
    "防空分队",
    "发射车",
    "战车",
    "炮车",
    "拦截车",
    "压制车",
    "截击器车",
    "装甲车",
    "车辆",
    "舰",
    "艇",
    "潜艇",
    "无人机",
    "无人僚机",
    "无人艇",
    "无人潜航器",
    "巡航弹",
    "打击弹",
    "导弹",
    "弹药",
    "拦截弹",
    "发射单元",
    "武器站",
    "火力车",
    "拦截阵",
    "拦截器",
    "截击器",
    "定向能",
    "激光武器",
    "高功率微波",
    "电子战",
    "任务载荷",
    "传感器",
    "制导",
)

_UNMANNED_COMBAT_EQUIPMENT_TERMS = (
    "无人机",
    "察打一体无人平台",
    "无人携弹平台",
    "无人艇",
    "无人潜航器",
    "无人车",
    "无人僚机",
    "无人集群",
    "蜂群",
    "UUV",
    "USV",
    "巡飞弹",
    "无人弹",
    "可消耗无人",
)

_LETHAL_WEAPON_EQUIPMENT_TERMS = (
    "巡航弹",
    "导弹",
    "巡飞弹",
    "反辐射弹",
    "电子压制弹",
    "诱饵弹",
    "无人弹",
    "弹药",
    "拦截弹",
    "火箭弹",
    "鱼雷",
    "深弹",
    "火炮",
    "舰炮",
    "武器站",
    "发射单元",
    "战斗部",
    "定向能",
    "激光武器",
    "高功率微波",
    "电子压制器",
    "反无人效应器",
)

_MISSILE_PRECISION_MUNITION_TERMS = (
    "巡航弹",
    "导弹",
    "巡飞弹",
    "反辐射弹",
    "电子压制弹",
    "诱饵弹",
    "无人弹",
    "精确制导弹药",
    "制导弹药",
    "智能弹药",
    "拦截弹",
    "火箭弹",
    "制导火箭弹",
    "鱼雷",
    "深弹",
    "制导炸弹",
    "炮射导弹",
    "战斗部",
)

_MISSILE_PRECISION_MUNITION_NAME_CONCEPTS = (
    "远程精确火力",
    "远域精确火力",
    "精确打击弹药",
    "低成本精确打击",
    "低成本拦截",
    "末端精确打击",
)

_GENERIC_NEW_WEAPON_TITLES = {
    "无人机",
    "无人作战平台",
    "巡飞弹",
    "反辐射巡飞弹",
    "远程导弹",
    "精确制导弹药",
    "拦截弹",
    "电子压制效应器",
}

_WEAPON_SUPPORT_CONTEXT_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:导弹|弹药|鱼雷|火箭弹|炮弹)(?:补给|运输|装填|保障|维修|储运|检测|仓储)(?:车|车辆|系统|平台|装备|分队|能力)?",
        r"(?:补给|运输|装填|保障|维修|储运|检测|仓储)(?:导弹|弹药|鱼雷|火箭弹|炮弹)(?:车|车辆|系统|平台|装备|分队|能力)?",
    )
)

_COMBAT_MUNITION_COMPOUND_PATTERN = re.compile(
    r"(?:电子|反辐射|诱骗|干扰|压制|制导|拦截|巡飞|无人)"
    r"[\u3400-\u9fffA-Za-z0-9/-]{0,8}弹"
)

_CAPABILITY_TITLE_REPEAT_TERMS = tuple(
    sorted(
        {
            *_HIGH_ORDER_COMBAT_EFFECT_TERMS,
            "能力",
            "系统",
            "装备",
            "平台",
            "任务",
            "目标",
            "火力",
        },
        key=len,
        reverse=True,
    )
)


from equipment_deep_research.agents.workflows.s6_quality import (
    _has_combat_effect_signal,
    _has_high_order_combat_value,
    _is_ordinary_support_direction,
    _has_combat_munition_compound,
    _has_specific_model_designator,
    _direction_name_has_equipment_object,
    _is_ancillary_support_equipment_direction,
    _query_explicitly_requests_support_equipment,
    _weapon_equipment_identity,
    _strip_weapon_support_context,
    _equipment_direction_categories,
    _is_unmanned_combat_equipment_direction,
    _is_lethal_weapon_equipment_direction,
    _is_missile_precision_munition_direction,
    _dedupe_capability_title,
    _s6_title_requires_structural_repair,
    _capability_title_equipment_anchor,
    _capability_upgrade_effect_anchor,
    _compact_capability_direction_title,
    _uniquify_compacted_capability_titles,
    _capability_portrait_alignment_issues,
    _capability_language_issues,
    _collect_reference_ids,
    _normalize_effect_chain_references,
    _normalize_concept_direction_priorities,
    _normalize_priority_references,
    _prioritized_evidence_index,
    _compact_s6_prior_outputs,
    _evidence_boundary_is_public_semantic,
    _query_relevance_issues,
    _truncate_complete_text,
    _clean_capability_handoff_text,
    _capability_handoff_statement,
    _capability_synthesis_handoff,
    _s6_card_is_reusable,
    _s6_first_pass_quality_contract,
    _capability_text_similarity,
    _capability_primary_equipment_family,
    _s6_primary_equipment_object_kind,
    _s6_primary_equipment_identity_mismatch,
    _build_direction_capability_portrait,
    _normalize_s6_deterministic_format,
    _equipment_form_identity_text,
    _direction_is_defensive_only,
    _s6_frontier_evidence_allowance,
    _indicator_portrait_is_specific,
    _query_relevance_is_specific,
    _prepare_pre_s6_card_contract,
    _capability_direction_quality_issues,
    _s6_delivery_blocking_issues,
    _s6_portrait_repair_issues,
    _s6_release_gate_state,
    _recover_invalid_s6_result,
    _requires_s6_combat_value_rewrite,
    _s6_repair_targets,
    _s6_portrait_module_repair_targets,
    _s6_can_use_lightweight_card_repair,
    _merge_s6_direction_repairs,
    _merge_s6_portrait_module_repairs,
    _s6_portfolio_confidence,
    _s6_weapon_title_is_descriptive_sentence,
    _merge_dynamic_portfolio_with_s6_authored_cards,
)


def _latest_inner_loop_failures(
    loop_trace: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return only unresolved final inner-loop outcomes for each S step.

    A planned repair and its first failed review remain useful trace history,
    but must not make the middle loop `limited` after a later iteration passes.
    Processing trace order makes the last authoritative evaluation for a step
    replace stale findings from earlier iterations.
    """

    latest_by_step: dict[int, dict[str, Any]] = {}
    for item in loop_trace:
        if item.get("loop") != "inner":
            continue
        try:
            step = int(item.get("step", 0) or 0)
        except (TypeError, ValueError):
            continue
        if step not in range(1, 7):
            continue
        latest_by_step[step] = dict(item)
    return [
        latest_by_step[step]
        for step in sorted(latest_by_step)
        if latest_by_step[step].get("passed") is not True
    ]


def _partition_tracks(tracks: Sequence[str], slots: int) -> list[list[str]]:
    clean = [str(item) for item in tracks if str(item).strip()]
    if not clean:
        return [[]]
    count = max(1, min(len(clean), slots))
    result: list[list[str]] = [[] for _ in range(count)]
    for index, track in enumerate(clean):
        result[index % count].append(track)
    return [item for item in result if item]


def _compact_discovery_text(text: str, *, max_chars: int = 9000) -> str:
    """Keep evidence-bearing discovery content, not search narration."""
    selected: list[str] = []
    seen: set[str] = set()
    used = 0
    for raw in str(text).splitlines():
        line = " ".join(raw.split())
        if not line or line in seen:
            continue
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "searching for",
                "search completed",
                "i will search",
                "我将检索",
                "检索过程",
            )
        ):
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        clipped = line[:remaining]
        selected.append(clipped)
        seen.add(line)
        used += len(clipped) + 1
    return "\n".join(selected)


def _compact_discovered_sources(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in rows:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        result.append(
            {
                "title": " ".join(str(item.get("title", "")).split())[:140],
                "url": url,
                "evidence_hint": " ".join(
                    str(item.get("snippet") or item.get("claim") or "").split()
                )[:240],
            }
        )
        if len(result) >= limit:
            break
    return result


def _merge_required_source_anchors(
    rows: Sequence[Mapping[str, Any]],
    anchor_urls: Sequence[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Reserve discovery slots for object-level equipment source anchors."""

    normalized_rows: list[dict[str, Any]] = []
    rows_by_url: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        url = _without_tracking_parameters(str(row.get("url", "")).strip())
        if not url or url in rows_by_url:
            continue
        row["url"] = url
        normalized_rows.append(row)
        rows_by_url[url] = row

    anchored: list[dict[str, Any]] = []
    anchor_set: set[str] = set()
    for anchor_index, raw_url in enumerate(anchor_urls):
        url = _without_tracking_parameters(str(raw_url).strip())
        if not url or url in anchor_set:
            continue
        anchor_set.add(url)
        anchored_row = dict(
            rows_by_url.get(
                url,
                {
                    "title": _normalized_source_title("", url),
                    "url": url,
                    "snippet": "",
                },
            )
        )
        # Keep the reservation explicit even when the hosted search already
        # returned this URL.  Downstream evidence diversification otherwise
        # loses the information and can move a second source from the same
        # domain (for example Barracuda after Roadrunner) behind the acceptance
        # cut-off.
        anchored_row["retrieval_lane"] = "required_source_anchor"
        anchored_row["required_source_anchor"] = True
        anchored_row["required_source_anchor_index"] = anchor_index
        anchored.append(anchored_row)

    remaining = [
        item for item in normalized_rows if str(item.get("url", "")) not in anchor_set
    ]
    return [*anchored, *remaining][: max(0, limit)]


def _prioritize_specialized_anchor_urls(
    channels: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Reserve one object anchor per equipment lane before secondary sources.

    The accepted-evidence target can be smaller than the total number of
    mandatory and corroborating URLs.  Flattening one channel at a time used
    to spend several early slots on PrSM/AARGM corroboration while starving
    the later Barracuda lane.  Interleave the first anchor from every channel,
    then append secondary anchors, so each distinct equipment family receives
    an identity source before any family receives extra confirmation.
    """

    anchor_groups = [
        [
            str(url)
            for url in item.get("source_anchors", [])
            if str(url).startswith("https://")
        ]
        for item in channels
        if isinstance(item, Mapping)
    ]
    primary = [group[0] for group in anchor_groups if group]
    secondary = [url for group in anchor_groups for url in group[1:]]
    return list(dict.fromkeys([*primary, *secondary]))


def _query_specific_weapon_evidence_channels(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build evidence lanes from Query semantics instead of a weapon catalogue."""

    brief = dict(structured_query_brief or {})

    def compact(value: Any, fallback: str) -> str:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            text = "；".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value or "").strip()
        return text[:900] or fallback

    targets = compact(
        brief.get("enemy_target_profile"),
        "由Codex依据完整Query识别敌方目标、威胁形态及关键反制",
    )
    phases = compact(
        brief.get("battle_phase_and_constraints"),
        "由Codex依据完整Query识别作战阶段、交战窗口、地域环境与约束",
    )
    effects = compact(
        brief.get("required_direct_military_effects"),
        "由Codex依据完整Query识别必须形成的打击、歼灭、毁伤、杀伤、压制或拦截效果",
    )
    architectures = compact(
        brief.get("winning_problem_propositions")
        or brief.get("query_specific_weapon_architectures"),
        "围绕Query任务断点与待改变变量检索最近公开能力边界，不预设装备族或型号",
    )
    return [
        {
            "channel_id": "query_target_threat_combat_effect",
            "name": "Query任务对象与直接战果证据",
            "query_anchor": topic,
            "focus": f"目标/威胁：{targets}；阶段/约束：{phases}；直接战果：{effects}",
            "preferred_sources": ["军方与政府", "作战条令与演训", "权威战例复盘"],
            "source_anchors": [],
            "required_result": "任务对象、威胁反制、作战阶段、直接战果与证据边界",
        },
        {
            "channel_id": "query_specific_weapon_architecture_baseline",
            "name": "Query制胜问题与公开装备边界证据",
            "query_anchor": topic,
            "focus": (
                f"开放制胜问题：{architectures}；只核验最近常规实现、公开能力边界和关键失效证据，"
                "不得据此替S3预选平台、弹药、载荷或技术路线，也不按固定型号目录补齐。"
            ),
            "preferred_sources": [
                "项目办公室",
                "军方试验与采购",
                "型号制造商",
                "权威技术评估",
            ],
            "source_anchors": [],
            "required_result": "单一主装备身份、既有任务属性、拟议增量、直接战斗效果与对象证据",
        },
        {
            "channel_id": "query_countermeasure_failure_boundary",
            "name": "Query对抗适应与失效边界证据",
            "query_anchor": topic,
            "focus": (
                f"围绕{targets}在{phases}中的对手反适应，核验候选武器的进入、生存、导引、效应、"
                "毁伤评估、补击与拒打边界。"
            ),
            "preferred_sources": ["军方试验机构", "审计与技术评估", "演训与战例复盘"],
            "source_anchors": [],
            "required_result": "对手反制、候选失效条件、反证、验证指标与淘汰条件",
        },
        {
            "channel_id": "query_weapon_engineering_acquisition",
            "name": "Query战斗武器工程与规模化证据",
            "query_anchor": topic,
            "focus": (
                "仅对已经由Query语义收敛出的直接战斗武器核验试验、采购、成熟度、成本、产能、"
                "供应链和批次一致性；不得从现成采购项目反向决定候选装备。"
            ),
            "preferred_sources": [
                "政府预算与合同",
                "审计机构",
                "军方试验",
                "项目办公室与制造商",
            ],
            "source_anchors": [],
            "required_result": "试验采购状态、工程边界、成本产能口径、时间边界与未知项",
        },
    ]


def _agent_plan_mode(context: Mapping[str, Any]) -> str:
    value = str(context.get("_agent_plan_mode", "required")).strip().lower()
    return value if value in {"required", "reference", "callback"} else "required"


def _compact_discovery_blueprint(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: value.get(key)
        for key in (
            "primary_branch",
            "branch_name",
            "emphasis",
            "required_outputs",
            "execution_profile_id",
            "structured_query_brief",
            "adaptive_winning_step_modes",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _weapon_specialized_evidence_channels(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return only the equipment lanes activated by this Query's semantics.

    The former implementation returned every familiar unmanned, long-range,
    anti-radiation, decoy and counter-UAS lane for every topic.  Even when the
    downstream prompt said "Query first", those retrieval anchors biased the
    whole swarm toward the same weapon catalogue.  Keep the object-neutral
    Query lanes for every run and append a specialist lane only when the
    structured semantic brief activates it.
    """

    lenses = {
        str(item.get("id", ""))
        for item in _conditional_priority_observation_lenses(
            topic,
            structured_query_brief=structured_query_brief,
        )
    }
    optional_channels = [
        {
            "channel_id": "long_range_precision_missile",
            "name": "远打精打导弹专项证据",
            "query_anchor": topic,
            "focus": (
                "战役纵深精确打击导弹、远程巡飞弹与精确制导弹药；重点核验目标类型、"
                "射程/突防/制导/毁伤/成本口径、火控与侦察依赖、库存产能和公开运用边界"
            ),
            "preferred_sources": [
                "军方与政府",
                "预算采购",
                "型号制造商",
                "权威试验与战例复盘",
            ],
            "source_anchors": [
                "https://files.gao.gov/reports/GAO-25-107263/index.html",
                "https://www.army.mil/article/272301/army_announces_first_precision_strike_missiles_delivery",
                "https://www.lockheedmartin.com/en-us/products/precision-strike-missile.html",
                "https://www.lockheedmartin.com/en-us/products/jassm.html",
            ],
            "required_result": "型号或类别锚点、直接作战效果、关键指标方向、证据边界与反证",
        },
        {
            "channel_id": "low_altitude_expendable_unmanned_strike",
            "name": "低空可消耗无人突击专项证据",
            "query_anchor": topic,
            "focus": (
                "低空/超低空单程攻击无人机、可消耗察打一体平台与远程无人突击装备；"
                "重点核验具体项目、任务载荷、作战半径口径、受扰导航、链路受限自治、"
                "有人监督、消耗/回收方式和公开实装运用"
            ),
            "preferred_sources": [
                "军方项目",
                "预算与试验",
                "制造商",
                "权威战例与演训复盘",
            ],
            "required_result": "具体平台或装备族、任务载荷、作用阶段、体系依赖、失效边界与反证",
        },
        {
            "channel_id": "loitering_antiradiation_suppression",
            "name": "巡飞猎歼与反辐射压制专项证据",
            "query_anchor": topic,
            "focus": (
                "巡飞弹药、Harpy/Harop类反辐射巡飞弹药、AARGM-ER类反防空效应器、"
                "防空压制弹药、可消耗诱饵与直接毁伤载荷；"
                "重点核验单一主装备对象、导引/搜索公开边界、压制对象、试验或采购状态、"
                "协同依赖、对手反适应和物理相容性"
            ),
            "preferred_sources": [
                "军方与政府",
                "作战条令与演训",
                "型号制造商",
                "权威技术评估",
            ],
            "source_anchors": [
                "https://www.navair.navy.mil/news/Navys-AARGM-ER-enter-production/Wed-08252021-1544",
                "https://www.navair.navy.mil/product/Advanced-Anti-Radiation-Guided-Missile-Extended-Range-AARGM-ER",
                "https://www.iai.co.il/p/harop",
            ],
            "required_result": "具体效应平台或弹药、压制对象、作战链贡献、指标方向、边界与反证",
        },
        {
            "channel_id": "expendable_decoy_electronic_attack",
            "name": "可消耗诱饵与电子攻击效应器专项证据",
            "query_anchor": topic,
            "focus": (
                "MALD/MALD-J类空射可消耗诱饵与电子攻击效应器；重点核验具体型号、模拟或干扰对象、"
                "对防空探测与火控链的直接压制/欺骗效果、载机与任务规划依赖、采购试验状态、"
                "对手识别反适应和公开性能边界。该方向必须区别于反辐射巡飞弹药与巡航毁伤弹药"
            ),
            "preferred_sources": ["军方与政府", "预算采购", "项目办公室", "型号制造商"],
            "source_anchors": [
                "https://www.rtx.com/raytheon/what-we-do/air/mald-decoy",
            ],
            "required_result": "具体诱饵/电子攻击效应器、直接压制或欺骗效果、任务依赖、状态、边界与反证",
        },
        {
            "channel_id": "counter_uas_interceptor_effector",
            "name": "反无人机拦截效应器专项证据",
            "query_anchor": topic,
            "focus": (
                "Coyote、Roadrunner等可重复或可消耗反无人机拦截效应器；重点核验具体平台、"
                "对无人机或巡飞弹的直接拦截效果、传感器/火控依赖、发射与回收构型、测试部署状态、"
                "成本交换、饱和边界和误识别风险。该方向必须是承担物理拦截的战斗装备"
            ),
            "preferred_sources": ["军方与政府", "预算合同", "试验机构", "型号制造商"],
            "source_anchors": [
                "https://www.rtx.com/raytheon/what-we-do/integrated-air-and-missile-defense/coyote",
                "https://www.anduril.com/roadrunner",
            ],
            "required_result": "具体拦截平台/弹药、直接拦截对象与效果、体系依赖、成本交换、边界与反证",
        },
        {
            "channel_id": "scalable_low_cost_combat_family",
            "name": "低成本规模化装备族与生产专项证据",
            "query_anchor": topic,
            "focus": (
                "低成本可消耗打击装备族、开放式接口、固定构型系列化、多供应链替代、"
                "工厂换产和柔性产线；重点核验合同、批次、成本口径、产能爬坡、质量一致性、"
                "关键瓶颈以及不得外推为战场现场换装的边界"
            ),
            "preferred_sources": [
                "预算采购",
                "政府合同",
                "审计报告",
                "制造商产线与供应链披露",
            ],
            "source_anchors": [
                "https://www.anduril.com/news/anduril-department-of-war-sign-production-agreement-for-surface-launched-barracuda-500m",
            ],
            "required_result": "具体装备族或生产项目、成本与产能证据、通用接口边界、规模化瓶颈与反证",
        },
        {
            "channel_id": "equipment_test_procurement_cost_capacity",
            "name": "装备试验采购成本产能专项证据",
            "query_anchor": topic,
            "focus": (
                "直接作战装备的飞行/实装试验、采购决策、预算审计、单位成本、库存补充、"
                "交付节奏和产能扩充；优先补齐可用于核验成熟度、工程可行性和规模化承诺的"
                "一手项目证据"
            ),
            "preferred_sources": [
                "军方试验机构",
                "政府预算与合同",
                "审计机构",
                "项目办公室与制造商",
            ],
            "required_result": "项目里程碑、采购或试验证据、成本产能口径、时间边界、冲突信息与未知项",
        },
    ]
    channel_lenses = {
        "long_range_precision_missile": {"remote_strike", "precision_strike"},
        "low_altitude_expendable_unmanned_strike": {
            "unmanned_combat",
            "low_altitude_weapon",
        },
        "loitering_antiradiation_suppression": {
            "anti_radiation_or_electromagnetic",
        },
        "expendable_decoy_electronic_attack": {"decoy_or_deception_effector"},
        "counter_uas_interceptor_effector": {"counter_unmanned_interceptor"},
        "scalable_low_cost_combat_family": {"scalable_mass_production"},
        # Engineering evidence is already present in the always-on Query lanes.
        "equipment_test_procurement_cost_capacity": set(),
    }
    selected = [
        {
            **item,
            "activation_rule": (
                "该通道仅因Query信号被优先检索；材料必须先交给Codex CLI与竞争解释、"
                "OTHER替代构型共同消化，不能直接生成同名装备方向。"
            ),
        }
        for item in optional_channels
        if channel_lenses.get(str(item.get("channel_id", "")), set()) & lenses
    ]
    return [
        *_query_specific_weapon_evidence_channels(
            topic,
            structured_query_brief=structured_query_brief,
        ),
        *selected,
    ]


def _direct_combat_generator_diversity_instruction() -> str:
    return (
        "先依据query_combat_equipment_divergence_brief开放形成竞争性Query专属武器架构，"
        "再只输出具有独立因果、直接军事效果和对象证据的方向；不规定内部候选数或最终条数。"
        "保留方向应在敌方目标、作战阶段、发射/释放域、直接效应或制胜关系上存在实质差异，"
        "并落实为自身承担打击、歼灭、毁伤、杀伤、压制或物理拦截的具体新质军事战斗武器。"
        "不得预设无人机、巡飞弹、反辐射弹、远程导弹或反无人拦截器等固定类别，也不得先读取"
        "公开型号名称再反向构造任务。"
    )


def _portfolio_gap_completion_instruction(topic: str = "") -> str:
    del topic
    return (
        "本实例是专家首轮评判后的组合缺口补齐；替代候选数量由未解决任务断点、对象证据、"
        "机制独立性和受治理的剩余候选容量共同决定，不得按固定条数补齐。"
        "先从candidate_ledger中明确区分专家已通过与未通过候选。任何与已通过候选在主装备、"
        "最近公开基线、核心机理或装备族上实质重复的方案都不得输出；未通过候选是负面样本而"
        "不是装备族禁区；必须重新消费Query语义简报，从尚未解决的任务对象、威胁、阶段和"
        "制胜矛盾发散替代架构，逐条解决原问题，不能只改名或润色。候选必须是直接承担"
        "打击、歼灭、毁伤、杀伤、突防、压制、物理拦截或区域拒止的具体新质军事战斗武器。"
        "每条有可追溯证据时优先保留，并把公开事实、装备架构创新、作战运用创新和待验证"
        "假设分层写清；没有证据时不得因此淘汰或阻断，但要收窄事实表述。现役升级或声称公开型号"
        "既有能力时，有ev-weapon_equipment-web-*对象证据应优先使用；没有时不得虚构型号属性。"
        "前瞻新研构型可由相邻项目、组成技术、效应机理或类比装备证据支撑；evidence_boundary有则"
        "明确证据边界，无则作为推荐补全项；反证、失效条件和可证伪淘汰试验暂缺时不因其单独淘汰"
        "高价值灵感。公开型号只能用于核验由Query先行推演出的最近基线，不能"
        "因为证据库存在某型号就强制生成对应装备族。架构增量必须"
        "落实到机体/弹体、动力与回收、载荷、发射补给、共用接口或构型分工，而不能只写"
        "前推部署、火力分配或回收优先等运用办法；不得把通信、算法、产线或供应链单独作为"
        "主体方向。创新"
        "必须明确其改变的是成本交换、突防窗口、毁伤闭环、平台暴露或战损补充中的哪一种对抗"
        "关系，并给出可淘汰该方向的对照试验。执行跨Query替换自检；若换题后候选仍基本成立，"
        "必须重新生成。若证据不足，收窄事实表述并标注待验证，不得凑数或因此直接淘汰与Query高度相关的灵感。"
    )


def _portfolio_frontier_completion_instruction() -> str:
    return (
        "本轮不是为了增加候选数量，而是修复组合创新审计确认的前沿、新质与颠覆性机会缺口。"
        "先读取portfolio_innovation_audit和完整candidate_ledger，保留已通过候选，不改名、不"
        "重写、不把它们当作负面样本；只探索尚未覆盖、且由当前Query直接牵引的前沿创新机会。"
        "必须把创新使能逻辑、具体主装备构型、任务链断点、直接军事效果和相对传统能力/运用/"
        "实现样式的颠覆增量连成一条因果链。可从新原理、新构型、新效应、新作战运用、跨域组合，"
        "以及测量感知、推进机动、材料能源、直接效应毁伤、制造成本、自主群体架构等开放维度思考，"
        "但这些不是固定分类、关键词配额或默认装备族；与Query无直接因果关系时必须舍弃。"
        "授权时序、任务规划、人在回路、战损评估或软件闭环只有在实质改变具体装备构型、接敌"
        "方式、效应方式或制胜关系时才能成为创新，不能仅换名包装；也不得为了显得新颖堆叠热门"
        "技术。Judge阶段不要求方向已经具备可落实的物理/工程断层、成熟工程锚点、工程瓶颈或"
        "完整证伪方案；这些可作为后续深化项。若没有方向同时满足Query因果、具体直接战斗装备、"
        "直接战果和实质颠覆增量，返回空hypotheses。"
    )


def _normalize_portfolio_innovation_audit(value: Any) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    mode = str(raw.get("portfolio_mode", "uncertain")).strip().lower()
    if mode not in {
        "diverse",
        "same_equipment_family",
        "same_mechanism",
        "process_only",
        "uncertain",
    }:
        mode = "uncertain"
    opportunity = raw.get("missing_frontier_opportunity", {})
    opportunity = dict(opportunity) if isinstance(opportunity, Mapping) else {}
    normalized_opportunity = {
        key: str(opportunity.get(key, "")).strip()[:500]
        for key in (
            "query_gap",
            "enabling_principle",
            "innovation_mode",
            "equipment_implication",
            "direct_military_effect",
            "disruptive_delta",
            "conventional_absorption_limit",
            "engineering_bottleneck",
        )
    }
    recommended = raw.get("completion_recommended") is True
    sufficient = raw.get("frontier_breadth_sufficient") is True
    actionable = bool(
        normalized_opportunity["query_gap"]
        and normalized_opportunity["equipment_implication"]
        and normalized_opportunity["direct_military_effect"]
        and (
            normalized_opportunity["disruptive_delta"]
            or normalized_opportunity["enabling_principle"]
            or normalized_opportunity["conventional_absorption_limit"]
        )
    )
    return {
        "frontier_breadth_sufficient": sufficient,
        "portfolio_mode": mode,
        "homogeneity_reason": str(raw.get("homogeneity_reason", "")).strip()[:700],
        "completion_recommended": bool(recommended and not sufficient and actionable),
        "missing_frontier_opportunity": normalized_opportunity,
        "audit_reason": str(raw.get("audit_reason", "")).strip()[:700],
    }


def _portfolio_innovation_completion_requested(value: Any) -> bool:
    return bool(
        _normalize_portfolio_innovation_audit(value).get("completion_recommended")
    )


def _portfolio_remaining_repair_slots(
    *,
    passed_count: int,
    finalist_minimum: int,
    completion_count: int,
) -> int:
    """Use the second expert call for new candidates plus only needed repairs."""

    return max(
        0,
        int(finalist_minimum) - int(passed_count) - int(completion_count),
    )


def _prioritize_winning_evidence_index(
    value: Any,
    *,
    archetype: str = "",
) -> list[dict[str, Any]]:
    """Put direct weapon-equipment cards first in the bounded swarm context."""

    rows = (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    del archetype

    return sorted(
        rows,
        key=lambda item: (
            0
            if str(item.get("created_by", "")) == "weapon_equipment"
            or str(item.get("evidence_id", "")).startswith("ev-weapon_equipment-")
            else 1,
        ),
    )


def _recover_specialized_winning_seed_hypotheses(
    evidence_index: Any,
    *,
    archetype: str,
) -> list[dict[str, Any]]:
    """Never author equipment candidates from a local evidence catalogue."""

    del evidence_index, archetype
    return []


def _prepare_portfolio_gap_completion_rows(
    value: Any,
    evidence_index: Any,
    *,
    topic: str,
    passed_hypotheses: Any = (),
) -> tuple[list[dict[str, Any]], int]:
    """Preserve Codex-authored gap candidates without injecting a fixed weapon."""

    raw_rows = (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    del evidence_index, topic, passed_hypotheses
    return raw_rows, 0


def _substantive_query_seed_row(value: Mapping[str, Any]) -> bool:
    """Recognize a model row worth preserving ahead of deterministic fallback."""

    forms = value.get("equipment_forms", value.get("equipment_form", []))
    effects = value.get(
        "direct_military_effects", value.get("direct_military_effect", [])
    )
    evidence = value.get("evidence_ids", value.get("evidence_refs", []))
    form_text = " ".join(
        str(item)
        for item in (
            forms
            if isinstance(forms, Sequence) and not isinstance(forms, (str, bytes))
            else [forms]
        )
    )
    has_weapon = any(
        marker in form_text
        for marker in (
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
    )
    has_effect = bool(effects)
    has_evidence = bool(evidence)
    has_difference = bool(
        value.get("changed_confrontation_variable")
        or value.get("novelty_delta")
        or value.get("mechanism_chain")
    )
    return has_weapon and has_effect and has_evidence and has_difference


def _ensure_specialized_winning_seed_lanes(
    value: Any,
    evidence_index: Any,
    *,
    archetype: str,
    topic: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Return only Codex-authored, query-led candidate rows.

    Empty or weak output remains observable so the mission graph can recruit a
    new S3 reasoning instance.  This helper never fills a lane, enforces a
    candidate count, or derives a weapon from an evidence/model dictionary.
    """

    del evidence_index, archetype, topic
    raw_rows = (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    substantive_rows = [item for item in raw_rows if _substantive_query_seed_row(item)]
    return substantive_rows or raw_rows, 0


def _discovery_system_prompt(agent_id: str) -> str:
    try:
        design = AgentDesignRegistry.load_default().get(agent_id)
    except KeyError:
        return (
            "你是公开资料检索Agent。发现可核验来源，优先政府、军方、国际组织、"
            "制造商和权威研究机构；只输出最小事实。"
        )
    prompt = design.discovery_instruction() or (
        "你是公开资料检索Agent。发现可核验来源，优先政府、军方、国际组织、"
        "制造商和权威研究机构；只输出最小事实。"
    )
    if design.search_mode == "equipment_deep":
        prompt += _query_led_combat_equipment_theme_instruction()
    return prompt


def _missing_baseline_fields(
    payload: Mapping[str, Any],
    agent: AgentDef,
) -> list[str]:
    missing = [
        field
        for field in (
            "findings",
            "confidence",
            "handoff_summary",
            "source_claims",
        )
        if payload.get(field) in (None, "", [], {})
    ]
    if agent.research_policy.get("require_counter_evidence", False) and payload.get(
        "contradictions"
    ) in (None, "", [], {}):
        missing.append("contradictions")
    sections = payload.get("analysis_sections", {})
    if not isinstance(sections, Mapping):
        sections = {}
    properties = (
        agent.output_contract.get("properties", [])
        if isinstance(agent.output_contract, Mapping)
        else []
    )
    missing.extend(
        f"analysis_sections.{field}"
        for field in properties
        if sections.get(str(field)) in (None, "", [], {})
    )
    return missing


def _repair_schema(
    schema: Mapping[str, Any],
    missing: Sequence[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    section_fields: dict[str, Any] = {}
    schema_sections = schema.get("analysis_sections", {})
    for field_name in missing:
        if field_name.startswith("analysis_sections."):
            name = field_name.split(".", 1)[1]
            if isinstance(schema_sections, Mapping):
                section_fields[name] = schema_sections.get(
                    name, "string | object | array"
                )
        elif field_name in schema:
            result[field_name] = schema[field_name]
    if section_fields:
        result["analysis_sections"] = section_fields
    return result or {"open_questions": ["string"]}


def _merge_missing_payload(
    current: Mapping[str, Any],
    patch: Mapping[str, Any],
    missing: Sequence[str],
) -> dict[str, Any]:
    merged = dict(current)
    for field_name in missing:
        if field_name.startswith("analysis_sections."):
            name = field_name.split(".", 1)[1]
            patch_sections = patch.get("analysis_sections", {})
            if isinstance(patch_sections, Mapping) and patch_sections.get(name) not in (
                None,
                "",
                [],
                {},
            ):
                sections = dict(merged.get("analysis_sections", {}))
                sections[name] = patch_sections[name]
                merged["analysis_sections"] = sections
        elif patch.get(field_name) not in (None, "", [], {}):
            merged[field_name] = patch[field_name]
    return merged


def _is_harness_budget_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    message = str(exc).lower()
    return "harness v2" in message and any(
        marker in message for marker in ("budget", "deadline", "no new model call")
    )


def _is_transient_provider_failure(exc: BaseException) -> bool:
    message = str(exc or "").lower()
    return any(
        marker in message
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "network",
            "temporarily unavailable",
            "timed out",
            "request timeout",
            "read timeout",
            "connect timeout",
            "stream disconnected",
            "upstream",
            "internal server error",
            "response failed",
            "error decoding response body",
        )
    )


def _trim_deadline_partial_text(value: object) -> str:
    """Keep only the last complete sentence from a streamed deadline result."""

    text = str(value or "").strip()
    if not text:
        return ""
    if text.count("```") % 2:
        text = text[: text.rfind("```")].rstrip()
    floor = max(0, int(len(text) * 0.6))
    sentence_end = max(
        text.rfind(marker, floor) for marker in ("。", "！", "？", ".", "!", "?")
    )
    if sentence_end >= floor:
        text = text[: sentence_end + 1]
    return text.strip()


def _minimum_viable_model_report(
    text: str,
    payload: Mapping[str, Any],
) -> bool:
    """Accept a model-written deadline draft only when it is reviewable."""

    normalized = str(text).strip()
    if not normalized or not _report_has_complete_canonical_structure(normalized):
        return False
    if re.search(
        r"(?<![A-Za-z0-9_])(?:ev|packet|cap)-[A-Za-z0-9]",
        normalized,
        flags=re.IGNORECASE,
    ):
        return False
    catalog = payload.get("evidence_catalog", [])
    allowed_urls = {
        str(item.get("url", "")).strip().rstrip("/")
        for item in catalog
        if isinstance(item, Mapping) and str(item.get("url", "")).strip()
    }
    cited_urls = {
        item.rstrip("/)") for item in re.findall(r"https://[^\s)]+", normalized)
    }
    if allowed_urls and any(url.rstrip("/") not in allowed_urls for url in cited_urls):
        return False
    return normalized[-1] not in "，、（([【“‘："


def _merge_partial_report_with_limited_completion(
    candidate: str,
    fallback: str,
    payload: Mapping[str, Any],
) -> str:
    """Keep complete model-written chapters and fill only missing chapters.

    Parallel Reporter calls are independently useful. A single failed section
    must not discard the other completed sections and replace the whole report
    with deterministic prose.
    """

    def h2_blocks(text: str) -> dict[str, str]:
        matches = list(
            re.finditer(r"^##\s+(?P<title>.+?)\s*$", str(text), flags=re.MULTILINE)
        )
        blocks: dict[str, str] = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            blocks[match.group("title").strip()] = text[match.start() : end].strip()
        return blocks

    def required_children(h2: str) -> tuple[list[str], list[str]]:
        if _report_template_mode(payload) == "project_argument_v1":
            h3 = [
                title
                for title, parent in _PROJECT_REPORT_H3_PARENT.items()
                if parent == h2
            ]
            h4 = [
                title
                for title, parent_h3 in _PROJECT_REPORT_H4_PARENT.items()
                if parent_h3 in h3
            ]
            return h3, h4
        index = list(_REPORT_CANONICAL_H2).index(h2)
        return list(_REPORT_CANONICAL_H3[index * 3 : index * 3 + 3]), []

    def complete_model_block(h2: str, block: str) -> bool:
        if len(block) < 240 or block.rstrip()[-1:] in "，、（([【“‘：":
            return False
        h3, h4 = required_children(h2)
        return all(f"### {title}" in block for title in h3) and all(
            f"#### {title}" in block for title in h4
        )

    candidate_blocks = h2_blocks(candidate)
    fallback_blocks = h2_blocks(fallback)
    canonical_h2, _, _ = _report_canonical_headings(payload)
    merged: list[str] = []
    for h2 in canonical_h2:
        model_block = candidate_blocks.get(h2, "")
        fallback_block = fallback_blocks.get(h2, "")
        if model_block and complete_model_block(h2, model_block):
            merged.append(model_block)
        elif fallback_block:
            merged.append(fallback_block)
    return "\n\n".join(merged).strip()


def _build_limited_report(
    payload: Mapping[str, Any],
    *,
    draft: str = "",
) -> str:
    """Build a traceable deadline delivery from accepted handoff data.

    This is the last safety net after the normal xhigh Reporter and its compact
    model retry are both unavailable.  It deliberately does not invent model
    numbers, sources or equipment parameters; missing judgments are marked for
    validation while the run still completes with a reviewable artifact.
    """

    generation = _reporter_generation_payload(payload, None)
    handoff = generation.get("research_handoff", {})
    if not isinstance(handoff, Mapping):
        handoff = {}
    if _report_template_mode(payload) == "project_argument_v1":
        cues = [
            dict(item)
            for item in handoff.get("capability_cues", [])
            if isinstance(item, Mapping)
        ][:12]
        comparative = handoff.get("comparative_status", {})
        comparative = comparative if isinstance(comparative, Mapping) else {}

        def text_rows(key: str, limit: int = 5) -> list[str]:
            values = handoff.get(key, [])
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                return []
            return [
                _clean_reporter_clue_text(item, max_chars=220)
                for item in values[:limit]
                if _clean_reporter_clue_text(item)
            ]

        def cue_values(*keys: str, limit: int = 5) -> list[str]:
            rows: list[str] = []
            for item in cues:
                for key in keys:
                    value = _clean_reporter_clue_text(item.get(key, ""), max_chars=220)
                    if value:
                        rows.append(value)
                        break
                if len(rows) >= limit:
                    break
            return rows

        def prose_list(values: Sequence[str], fallback: str) -> str:
            rows = list(
                dict.fromkeys(str(item).strip() for item in values if str(item).strip())
            )
            return "；".join(rows) if rows else fallback

        def comparative_findings_text() -> str:
            value = comparative.get("comparative_findings")
            if isinstance(value, Mapping):
                rows = [
                    f"{_clean_reporter_clue_text(key, max_chars=40)}："
                    f"{_clean_reporter_clue_text(item, max_chars=240)}"
                    for key, item in list(value.items())[:6]
                    if _clean_reporter_clue_text(item)
                ]
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                rows = [
                    _clean_reporter_clue_text(item, max_chars=240)
                    for item in value[:6]
                    if _clean_reporter_clue_text(item)
                ]
            else:
                rows = (
                    [_clean_reporter_clue_text(value, max_chars=500)] if value else []
                )
            if rows:
                return "；".join(rows)
            return (
                "现有交接尚未形成可核验的国别案例对照，因此本节不以常识补造型号结论；"
                "本项目的差异化暂收敛为：不把抗干扰理解为单链路增强，而是以可消耗前出平台、"
                "反辐射窗口制造和近距毁伤续接共同恢复任务闭环。"
            )

        def case_paragraphs(key: str, fallback: str) -> str:
            rows = comparative.get(key, [])
            if not isinstance(rows, list) or not rows:
                return fallback
            paragraphs = []
            for item in rows[:5]:
                if not isinstance(item, Mapping):
                    continue
                paragraphs.append(
                    f"**{item.get('equipment_or_project', '公开装备案例')}**："
                    f"{item.get('country', '')}{item.get('organization', '')}，状态为{item.get('status', '待核验')}；"
                    f"面向{item.get('problem_addressed', '相关问题难点')}，采用{item.get('technical_route', '公开技术途径待核验')}；"
                    f"核心技术与指标为{item.get('core_technologies', [])}、{item.get('core_indicators', [])}。"
                    f"证据边界：{item.get('evidence_boundary', '公开资料不足，不能外推未披露性能')}。"
                )
            return "\n\n".join(paragraphs) or fallback

        names = [
            str(item.get("direction", "")).strip()
            for item in cues
            if str(item.get("direction", "")).strip()
        ]
        direction_text = "、".join(names) or "具体装备方向待前置研究收敛"
        anchors = text_rows("decisive_anchors", 4)
        breaks = text_rows("mission_chain_breaks", 4)
        limits = text_rows("counterevidence_and_limits", 3)
        priorities = text_rows("priority_signals", 4)
        problems = cue_values("problem_statement", "capability_gap", limit=5)
        effects = cue_values("mission_effect", "capability_outcome", limit=5)
        mechanisms = cue_values("winning_mechanism", "mechanism_hint", limit=5)
        disruptive = cue_values("disruptive_relationship", limit=4)
        portrait_rows = []
        for item in cues:
            name = _clean_reporter_clue_text(item.get("direction", ""), max_chars=90)
            if not name:
                continue
            equipment = _clean_reporter_clue_text(
                item.get("equipment_hint") or item.get("capability_portrait", ""),
                max_chars=180,
            ).replace("|", "/")
            technology = prose_list(
                [
                    *(
                        item.get("enabling_technologies", [])
                        if isinstance(item.get("enabling_technologies", []), list)
                        else []
                    ),
                    item.get("scientific_principle", ""),
                ],
                "关键技术从任务机理和失效边界反推",
            ).replace("|", "/")
            outcome = _clean_reporter_clue_text(
                item.get("capability_outcome") or item.get("mission_effect", ""),
                max_chars=180,
            ).replace("|", "/")
            operation = _clean_reporter_clue_text(
                item.get("operational_concept")
                or item.get("winning_mechanism")
                or item.get("mechanism_hint", ""),
                max_chars=200,
            ).replace("|", "/")
            portrait_rows.append(
                f"| {name} | {equipment or '装备构型按交接边界继续分解'} | "
                f"{technology} | {outcome or '任务效果按代表性场景验证'} | "
                f"{operation or '按任务准备—进入—确认—交战—评估闭合运用'} |"
            )
        if not portrait_rows:
            portrait_rows.append(
                "| 具体装备方向待收敛 | 仅保留Query定义的任务边界 | "
                "按任务断点反推技术 | 以任务成功率验证 | 不补造装备结论 |"
            )

        def table_cell(value: object, fallback: str, *, limit: int = 180) -> str:
            return (
                _clean_reporter_clue_text(value, max_chars=limit)
                .replace("|", "／")
                .strip(" ；。")
                or fallback
            )

        subsystem_rows: list[str] = []
        technology_rows: list[str] = []
        foundation_rows: list[str] = []
        for item in cues:
            name = table_cell(item.get("direction"), "具体装备方向", limit=90)
            equipment = table_cell(
                item.get("equipment_hint"),
                "平台、任务载荷与发射/保障组件按装备方向集成",
            )
            technologies = item.get("enabling_technologies", [])
            technology_list = (
                [str(value) for value in technologies[:5]]
                if isinstance(technologies, list)
                else [str(technologies)]
            )
            technology = table_cell(
                "、".join(value for value in technology_list if value)
                or item.get("scientific_principle"),
                "任务软件、感知导航、火控和安全控制技术",
            )
            operation = table_cell(
                item.get("operational_concept") or item.get("winning_mechanism"),
                "按任务装订、受控交战、效应评估和再组织闭合运行",
            )
            boundary = table_cell(
                item.get("boundary") or item.get("coupling_risk"),
                "接口、授权、导航可信度或目标证据不足时降级",
            )
            development = table_cell(
                item.get("development_path"),
                "先仿真和接口联试，再开展半实物、实装与红蓝对抗验证",
            )
            baseline = table_cell(
                item.get("public_equipment_baseline"),
                "公开资料仅支持类别级基线，成熟度和指标待样机验证",
            )
            indicator = table_cell(
                item.get("indicator_portrait"),
                "按覆盖、响应、自主边界、单位任务成本、规模与生存性校准",
            )
            subsystem_rows.append(
                f"| {name} | {equipment} | {technology} | {operation} | {boundary} | {development} |"
            )
            technology_rows.append(
                f"| {name}关键技术组合 | {technology} | {baseline} | {boundary} | {development} | {indicator} |"
            )
            foundation_rows.append(
                f"- **{name}**：现有基础为{baseline}；工程承接沿{development}推进。"
                f"对{name}的验证只承诺{indicator}，公开证据不足处保留待核验边界。"
            )

        architecture_text = (
            "总体架构采用“任务状态与授权控制层—跨域武器与效应层—感知/PNT与低带宽接口层—"
            "保障试验层”四层闭合。任务状态与授权控制层维护目标包有效期、禁打边界、PNT可信度、"
            "补射申请和超时中止规则；跨域武器与效应层由各具体装备方向承担复核、压制、毁伤、"
            "拦截和拒止；感知/PNT与接口层只传递完成任务所需的最小状态摘要；保障试验层负责批次"
            "软件、弹药补充、训练数据和红蓝对抗复盘。信息流从目标发现与证据分级进入任务状态包，"
            "经授权门限分配给适配射手，交战后以BDA摘要回流并触发补射、等待、改打或中止，形成"
            "可审计闭环。"
        )
        participation_rows = "\n".join(
            (
                "| 总体论证与体系设计单位 | 任务链建模、装备组合、状态包与授权规则 | 总体接口基线、需求分解、验证矩阵 |",
                "| 武器平台与弹药总体单位 | 平台、载荷、战斗部、发射和安全控制集成 | 样机、任务软件适配、平台级试验记录 |",
                "| 感知导航与任务软件单位 | 被动感知、PNT可信评估、目标摘要和受控自治 | 算法基线、数据接口、失效降级策略 |",
                "| 火控与指挥信息接口单位 | 目标包、授权、补射申请、BDA和审计日志闭合 | 低带宽协议、网关适配、互操作联试 |",
                "| 试验鉴定与保障产业单位 | 对抗环境、半实物、综合靶场、产能与补充验证 | 通过/失败条件、成本交换和持续波次数据 |",
            )
        )
        report = f"""## 一、需求分析

### （一）需求概述

#### 1. 背景分析

“{payload.get("topic", "装备研究项目")}”所对应的竞争焦点，不是单件弹药能否在理想链路下命中，而是对手通过压制导航、通信、目标更新和毁伤评估，使远程精确火力在目标短时暴露窗口内失去连续决策依据。前置交接已经形成的决定性判断包括：{prose_list(anchors, "强对抗条件下，任务链的可续接性比单项峰值指标更能决定精确打击结果")}。这意味着装备建设重心需要从“持续保持一条完整链路”转向“主链路受压后仍能以局部感知、预授权规则和近距效应器完成最低有效闭环”。

作战样式演进带来的直接矛盾是：精确打击越来越依赖高质量目标包和快速闭环，而强电磁压制恰好攻击这些依赖。已识别的链路断点为：{prose_list(breaks, "目标确认、火力授权、末段修正和战损评估在受扰条件下难以连续闭合")}。因此，本项目不是泛化建设通信或指挥系统，而是把任务续接能力固化到可消耗前出平台、反辐射压制效应器、携弹无人平台及其任务接口中，使装备在信息不完备时仍能形成受约束、可审计、可验证的直接作战贡献。

#### 2. 需求阐述

需求应从任务失败机理反推，而不能停留在“抗干扰、智能化、低成本”等标签。当前需要解决的具体问题包括：{prose_list(problems, prose_list(breaks, "目标信息过期、远程火力与目标区脱节、压制窗口无法转化为毁伤窗口"))}。对应能力要求是：一要在主链路断续时维持目标区附近的低特征感知与有限确认；二要把对手辐射和压制行为转化为可捕获、可打击的暴露事件；三要以批量可消耗平台覆盖多个时间窗口，降低单个平台损失对任务成功率的影响；四要把授权、取消、目标摘要和战损回传压缩为最小接口闭环。预期任务效果包括：{prose_list(effects, "恢复精确打击窗口、形成近距补打并支撑再攻击决策")}。

上述要求必须转化为可立项、可试验的能力指标：以目标包有效期内交付率衡量续接，以发现至交战时间衡量响应，以失联条件下允许动作集合衡量自主边界，以单位有效毁伤和单位压制小时衡量成本交换，以同时在空数量和持续波次衡量规模能力，并在代表性干扰、诱饵、战损和授权延迟条件下验证失效边界。现有反证与限制为：{prose_list(limits, "公开证据尚不能支持未经试验校准的性能点值，所有指标先定义口径和通过条件")}。

#### 3. 项目画像

项目以{direction_text}为主体装备方向，不把通信、算法或保障节点另行包装为主装备。各方向围绕“前出存在—局部确认—窗口制造—直接毁伤—战损回传/再攻击”形成组合：可消耗低空察打一体平台负责续接目标链和近距确认，反辐射巡飞效应器利用对手压制行为制造短时窗口，批量低空携弹平台以多方向、多波次完成近距毁伤，前沿察打分队承担补打与战损回传。其核心机理为：{prose_list(mechanisms, "以分布式、可消耗、受约束的局部闭环替代对连续远域链路的单点依赖")}；相对传统方案改变的关系包括：{prose_list(disruptive, "从单弹峰值性能竞争转向任务闭环、成本交换和持续波次竞争")}。

### （二）国内外现状

#### 1. 国外情况

{case_paragraphs("foreign_cases", "当前已接受交接未提供足以独立成项的国外型号案例，因此不补造项目状态或指标。现阶段只能以公开装备类别作为基线：防区外精确弹药解决远域投送，反辐射武器解决辐射源压制，巡飞弹药和可消耗无人平台解决目标区持续存在；但这些类别能否在强压制下共同完成任务续接，仍取决于任务包、授权、时间协同和战损回传接口。")}

#### 2. 国内现状（中国）

{case_paragraphs("domestic_cases", "当前已接受交接未提供足以支撑型号级结论的中国国内案例，故不推断未公开状态。可确认的研究边界是：国内若已有远程精确火力、无人平台和反辐射效应器基础，本项目的增量仍不在单项平台存在与否，而在强压制条件下的平台接口闭合、可消耗规模运用、近距续接毁伤和联合验证。")}

#### 3. 对比小结

{comparative_findings_text()}

### （三）建设必要性分析

#### 1. 作战使用角度

项目的作战必要性来自已识别的链路断点：{prose_list(breaks, "目标确认、授权、末段修正与毁伤评估断续")}。若仍只增强远程链路或单弹抗扰，一旦主节点、PNT或目标更新同时受压，火力仍会因信息过期而失效；本项目通过目标区附近的可消耗平台和反辐射效应器，把补链动作直接转化为压制、毁伤、补打和再攻击依据。

#### 2. 装备能力提升角度

装备能力提升不是追求所有指标同步最大化，而是在受扰条件下建立可交换的组合优势：用前出驻留缩短响应，用预授权和安全中止规则界定自主边界，用固定构型与批次生产改善成本和补充，用多方向进入与任务分工提高生存性。建设优先信号为：{prose_list(priorities, "优先验证能否恢复任务闭环，再校准射程、载荷和规模指标")}。

#### 3. 领域占位角度

该方向占位价值在于形成可系列化的低空可消耗平台族、反辐射效应器族和统一任务接口，使后续不同载荷、发射平台和保障方式能够共享任务装订、授权、取消与战果摘要机制。若只形成单一演示样机而没有接口和批量制造基线，则难以转化为装备族，也无法在对手快速反适应后持续迭代。

#### 4. 综合效益

综合效益应以“是否用可承受的成本恢复高价值火力的有效使用”为主线：军事上提高受扰条件下的任务完成概率，体系上减少对单一链路和高价值节点的依赖，经济上比较可消耗平台损失与高端弹药空耗、任务失败的机会成本，工业上检验固定构型、批次一致性和多源替代能力。任何方向若不能同时证明直接作战贡献、可补充性和对手反适应下的有效边界，都不应仅凭概念新颖进入立项。

## 二、项目画像

### （一）装备图像概述

| 装备系统方向 | 装备平台与方案 | 核心技术 | 形成能力 | 作战概念与主要效果 |
|---|---|---|---|---|
{chr(10).join(portrait_rows)}

### （二）作战运用模式

#### 1. 作战运用流程

按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径。

#### 2. 链路闭环分析

围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理。

### （三）体系贡献率分析

体系贡献以原方案为基线，从任务成功率、闭环时间、耗弹量、突防效能、交换比和持续波次建立计算口径；公开数据不足时只给验证方法，不承诺点值。

### （四）主要战技指标

主要指标覆盖射程/覆盖、响应、自主与授权边界、精度、毁伤、抗扰生存、单位任务成本、并发规模和产能补充，均需明确测试条件与证据状态。

## 三、总体方案

### （一）总体架构

{architecture_text}

部署上采用后方高价值节点集中制定授权边界、前沿可消耗节点分散进入、主链路与短报文/本地规则并行的PACE构型。任何跨节点接管都必须携带目标身份、时间窗、证据等级、允许动作和中止条件；节点受损时，系统优先保留安全中止和证据回传，再按任务价值恢复确认与交战，避免把“断链自治”误写成无限自主开火。

### （二）子系统方案

| 子系统/装备方向 | 硬件与产品形态 | 软件与核心技术 | 主要输入输出及运用 | 工程边界 | 集成验证项目 |
|---|---|---|---|---|---|
{chr(10).join(subsystem_rows)}

子系统集成顺序按“接口先闭合、单装再验证、跨域后组网”推进：先冻结目标包、授权、PNT可信度和BDA摘要字段，再分别验证平台级感知、导航、火控与安全中止，最后在节点损耗、通信降级、目标机动和诱饵污染条件下开展跨装备接管。接口字段或安全状态若不能审计，即使单装命中率较高也不得判定任务续接能力形成。

## 四、关键技术

### （一）关键技术清单与攻关途径

| 技术名称 | 技术内涵 | 成熟度/现有基础 | 主要瓶颈 | 攻关途径 | 验证指标与失败条件 |
|---|---|---|---|---|---|
{chr(10).join(technology_rows)}

关键技术不是平行堆叠关系。任务状态包和授权审计是所有装备共享的控制底座，PNT可信评估与目标复核决定能否安全进入交战，低带宽接口决定能否跨节点续接，平台/弹药自身的制导、毁伤和拦截能力决定最终任务效果。任一串联环节在代表性压制条件下失效，均不能以其他分项的高成熟度平均抵消；攻关评审必须同时保留通过条件、失败样本和对手反适应测试。

## 五、研制基础

### （一）参与单位

公开交接不足以指定国内承研单位、总装单位或试验部队，因此不虚构名称，按能力类型形成责任闭环：

| 单位类型 | 主要责任 | 必须交付的接口或证据 |
|---|---|---|
{participation_rows}

组织上由总体单位维护唯一需求和接口基线，各装备总体对自身平台安全、任务边界和实装效果负责，试验鉴定单位独立记录失败条件。国外公开型号、机构和项目仅作为技术与状态对照，不能直接替代国内参与单位论证。

### （二）技术基础

项目技术基础应从现有平台、类别级装备基线、算法/任务软件、试验设施和产业补充能力分别核验，而不能只凭某一公开型号推定全链成熟。逐装备承接关系如下：

{chr(10).join(foundation_rows)}

近期优先使用训练弹、仿真火控、现有无人平台和被动感知载荷验证任务状态字段、接口时序与安全中止；中期形成跨装备样机并进入半实物和综合靶场；后续再用持续波次、补给受阻和节点损耗试验检验产能、维护和战损补充。凡公开资料不能支撑的精确参数、成熟度和参与单位信息，均进入核验清单而不写成既成事实。
"""
        return report.strip()

    def text_rows(key: str, *, limit: int = 5) -> list[str]:
        values = handoff.get(key, [])
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return []
        rows: list[str] = []
        for item in values[:limit]:
            cleaned = _clean_reporter_clue_text(item)
            if cleaned:
                rows.append(_truncate_complete_text(cleaned, limit=220))
        return rows

    cues = [
        dict(item)
        for item in handoff.get("capability_cues", [])
        if isinstance(item, Mapping)
    ][:12]
    anchors = text_rows("decisive_anchors", limit=4)
    breaks = text_rows("mission_chain_breaks", limit=4)
    limits = text_rows("counterevidence_and_limits", limit=4)
    priorities = text_rows("priority_signals", limit=4)
    query = _clean_reporter_clue_text(
        payload.get("topic", "装备需求研究"), max_chars=220
    )

    def bullet_rows(values: Sequence[str], fallback: str) -> str:
        rows = [str(item).strip() for item in values if str(item).strip()]
        if not rows:
            return fallback
        return "\n".join(f"- {item}" for item in rows)

    direction_rows: list[str] = []
    mechanism_rows: list[str] = []
    effect_rows: list[str] = []
    technology_rows: list[str] = []
    capability_table_rows: list[str] = []
    for index, cue in enumerate(cues, start=1):
        name = _clean_reporter_clue_text(
            cue.get("direction") or cue.get("equipment_hint") or f"候选装备方向{index}",
            max_chars=90,
        )
        equipment = _clean_reporter_clue_text(
            cue.get("equipment_hint", ""), max_chars=120
        )
        mission = _clean_reporter_clue_text(
            cue.get("mission_effect", ""), max_chars=180
        )
        mechanism = _clean_reporter_clue_text(
            cue.get("mechanism_hint", ""), max_chars=180
        )
        trigger = _clean_reporter_clue_text(
            cue.get("future_trigger", ""), max_chars=140
        )
        direction_rows.append(
            f"P{index}｜{name}：{equipment or '装备形态以已审计研究交接为准'}；"
            f"任务贡献为{mission or '补齐相关任务链能力，具体指标待演示验证'}。"
        )
        if mechanism:
            mechanism_rows.append(f"{name}：{mechanism}")
        if mission:
            effect_rows.append(f"{name}：{mission}")
        if trigger or mechanism:
            technology_rows.append(
                f"{name}：围绕{mechanism or '任务机理'}开展技术分解；"
                f"触发条件为{trigger or '威胁压力与工程成熟度达到验证门槛'}。"
            )
        lineage = (
            "现役升级"
            if str(cue.get("type", "")).strip() == "upgrade"
            else "新研装备"
        )
        operation = mechanism or mission or "按任务阶段编组运用，具体流程待演示验证"
        capability_table_rows.append(
            f"| {name} | {mission or '直接打击、压制、毁伤或拒止能力'} | "
            "射程/响应时间/自主等级/成本量级/规模量级待证据校准 | "
            f"{operation} | {lineage} |"
        )

    source_rows = [
        f"- [{_clean_reporter_clue_text(item.get('title', '公开来源'), max_chars=80)}]({str(item.get('url', '')).strip()})"
        for item in generation.get("public_sources", [])
        if isinstance(item, Mapping)
        and str(item.get("url", "")).startswith(("http://", "https://"))
    ][:6]
    del draft  # Never splice a potentially truncated model fragment into delivery.
    capability_table = "\n".join(
        [
            "| 装备系统方向 | 能力域 | 指标画像 | 作战运用概念 | 谱系位置 |",
            "|---|---|---|---|---|",
            *capability_table_rows,
        ]
    )

    sections = [
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
        "### ① 典型作战场景",
        f"本报告围绕“{query}”进行限时收敛。典型场景应以对手能力、地域环境、冲突烈度、关键时间窗和电磁/保障/成本约束共同定义，优先检验发现—决策—火力—毁伤评估链条中的决定性断点。\n"
        + bullet_rows(
            [*anchors, *breaks],
            "- 当前交接未保留足够场景锚点，需在演示验证前补齐对手、地域、烈度、时间窗与约束。",
        ),
        "### ② 新战法或新概念技术及制胜机理",
        "创新性不以技术标签判定，而以相对现役基线是否改变传统作战关系判定：从持续链路喂数转向弹上/机上受限闭环，从单一高价平台转向可消耗多点火力，从一次打击转向可续接再打击。上述属于证据约束下的新增机制假设；必须同时验证对手反适应、适用边界和失效边界，不能把概念潜力写成已形成能力。\n"
        + bullet_rows(
            mechanism_rows,
            "- 当前交接未形成可直接发布的逐项机理，保留为后续定向复核项。",
        ),
        "### ③ 装备能力特征清单",
        "能力特征按任务效果、射程/覆盖、响应时间、自主等级、抗扰与生存、成本量级、规模量级和体系接口八类组织；定量值仅在公开证据和试验条件明确时给出区间。\n"
        + bullet_rows(
            direction_rows,
            "- 当前仅能确认应形成多个互异的具体武器装备方向，不能以通信、算法或保障主题替代最终装备画像。",
        ),
        "## 第二层：技术攻关层——能力实现途径与核心技术",
        "### ④ 能力实现途径",
        "每个方向分别判定为沿用改进、集成创新或原理突破：已有平台和弹药可通过传感、火控、载荷与软件升级恢复战斗效能时优先沿用改进；跨平台闭环和有人—无人协同时采用集成创新；只有现有物理边界无法满足射程、成本交换或生存要求时进入原理突破。限时版不对缺乏成熟度证据的方向强行定级。",
        "### ⑤ 核心技术清单与攻关优先级",
        "核心技术必须精确到制导、感知、推进/能源、载荷、材料、任务自主、集群协同、抗干扰和低成本制造等技术点，并逐项标注定性成熟度、工程瓶颈与优先级。公开证据不足的TRL统一标为待验证；每项设置试验验证、演示验证、验证指标、通过条件和失败条件，禁止把推断写成既成能力。\n"
        + bullet_rows(
            technology_rows,
            "- 技术点、成熟度和瓶颈需从已确定装备方向逐项反推，避免脱离任务场景罗列通用技术。",
        ),
        "### ⑥ 技术耦合与短板风险",
        "优先识别会拖垮整项能力的单点短板：目标信息质量、末制导与火控闭环、推进/能源、载荷效应、抗干扰链路、批量制造和保障能力必须联合校核。任何一项若无法在代表性干扰、气象和规模条件下通过验证，都应下调系统成熟度而非以其他分项平均。\n"
        + bullet_rows(
            limits,
            "- 当前未形成完整反证集，后续验证必须设置对手反适应、链路失效、弹药消耗和成本上限场景。",
        ),
        "## 第三层：能力图像与效能贡献层",
        "### ⑦ 装备能力图像",
        "能力图像以全部证据闭环、互异且高军事价值的具体武器装备方向横向比较；装备类别由Query的任务对象、威胁形态、作战阶段、地域约束和制胜矛盾决定，不预设无人、低空、远程、导弹或其他目录，并同时标明现役升级与新研谱系位置。\n"
        + capability_table,
        "### ⑧ 效能贡献评估",
        "效能贡献按补链、强链、开链分类，并明确三条制胜赛道：现役效能跃升用于判断存量装备升级后能否恢复断链条件下的毁伤；传统赛道跨代优势用于判断射程、突防、交换比和决策周期是否形成代际差；新概念赛道开辟用于判断无人持续存在、低成本规模火力或新质压制是否形成此前不存在的任务路径。量化方向优先采用突防率提升量级、交换比改善量级、决策周期压缩量级、同时交战目标数和代表性场景任务成功率；无公开校准证据时只给验证方向。\n"
        + bullet_rows(
            effect_rows,
            "- 当前只保留定性贡献，具体提升量级必须经兵棋、半实物和实装对抗验证后发布。",
        ),
        "### ⑨ 发展优先级与近期抓手",
        "近期抓手应选择能够同时验证任务机理、关键短板和成本边界的演示项目：先用数字兵棋和任务级仿真筛除低增益方向，再开展半实物闭环与代表性干扰环境试验，最后以小批量体系对抗验证决定升级、集成或新研立项。\n"
        + bullet_rows(
            priorities,
            "- 优先级按直接作战贡献、卡脖子程度、成熟度、规模成本与三年内可验证性联合排序。",
        ),
    ]
    if source_rows:
        sections.extend(["", "公开来源（限时版保留的代表性目录）：", *source_rows])
    sections.extend(
        [
            "",
            "> 限制说明：正常高深度报告调用未能在运行预算内完成，本版仅使用已接受的研究交接与公开来源形成结构化交付；未核实的定量指标、型号参数和成熟度均未补造。",
        ]
    )
    return "\n\n".join(item for item in sections if item is not None).strip()


def _swarm_provider_isolation_id(
    agent_id: str,
    payload: Mapping[str, Any],
) -> str:
    parallel_s6 = str(agent_id) == "winning_s6_image"
    if not str(agent_id).startswith("winning_swarm_") and not parallel_s6:
        return ""
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("input", "task_input"):
        child = payload.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("input")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    for candidate in candidates:
        if parallel_s6:
            card_id = str(candidate.get("parallel_card_id", "")).strip()
            if card_id:
                return card_id
        task = candidate.get("specialist_task")
        if isinstance(task, Mapping):
            return str(task.get("agent_instance_id", "")).strip()
    return ""


def _swarm_session_ref(task: SpecialistTask) -> str:
    digest = sha256(
        f"{task.task_id}:{task.agent_instance_id}".encode("utf-8")
    ).hexdigest()[:12]
    return f"cli-session-{digest}"


def _swarm_runtime_audit_contract(
    task: SpecialistTask,
    provider_snapshot: Mapping[str, Any],
    *,
    runtime_agent_id: str,
    session_ref: str,
) -> dict[str, Any]:
    provider_type = str(provider_snapshot.get("type", "unknown"))
    session_mode = str(
        provider_snapshot.get("session_mode")
        or ("ephemeral" if provider_type == "codex_cli" else "provider_managed")
    )
    return {
        "task_id": task.task_id,
        "agent_instance_id": task.agent_instance_id,
        "display_name": task.display_name,
        "archetype": task.archetype,
        "role_purpose": task.purpose,
        "trigger_residuals": list(task.trigger_residuals),
        "hypothesis_id": task.hypothesis_id,
        "merge_target": task.merge_target,
        "wave": task.wave,
        "provider_type": provider_type,
        "execution_backend": str(
            provider_snapshot.get("execution_backend")
            or (
                "independent_codex_cli"
                if provider_type == "codex_cli"
                else "isolated_model_turn"
            )
        ),
        "context_isolation": session_mode,
        "provider_isolation_id": str(provider_snapshot.get("context_isolation", "")),
        "process_isolation": str(
            provider_snapshot.get("process_isolation")
            or (
                "new_process_per_turn"
                if provider_type == "codex_cli"
                else "provider_managed"
            )
        ),
        "sandbox_mode": str(provider_snapshot.get("sandbox_mode", "")),
        "model": str(provider_snapshot.get("model", "")),
        "runtime_profile_id": runtime_agent_id,
        "role_contract_version": "1.0",
        "skill_ids": [
            "js-equipment-agent-runtime",
            "js-winning-shared-layer",
        ],
        "allow_child_spawn": False,
        "expected_quality_gain": task.expected_quality_gain,
        "session_ref": session_ref,
    }


def _phase_reasoning_effort(
    agent_id: str,
    phase: str,
    configured: str,
) -> str:
    """Keep quality-critical reasoning high and trim only auxiliary phases."""
    normalized = str(configured).lower()
    configured_effort = (
        normalized if normalized in {"low", "medium", "high", "xhigh"} else "high"
    )
    winning_step_agents = {
        "winning_s1_opponent",
        "winning_s2_operations",
        "winning_s3_breakthrough",
        "winning_s4_capability",
        "winning_s5_gap",
        "winning_s6_image",
    }
    if agent_id in winning_step_agents:
        if agent_id == "winning_s6_image":
            if "card_repair" in phase:
                return "low"
            if phase == "winning_s6_image_deep" and os.environ.get(
                "EQUIPMENT_DR_ENTERPRISE_LATENCY_PROFILE", "1"
            ).strip().lower() not in {"0", "false", "no"}:
                return "medium"
            return "high"
        if agent_id == "winning_s4_capability" and os.environ.get(
            "EQUIPMENT_DR_ENTERPRISE_LATENCY_PROFILE",
            "1",
        ).strip() not in {"0", "false", "no"}:
            return "medium"
        return "low" if phase.endswith("_light") else "high"
    if agent_id == "winning_cohort-s1-s2":
        # S1/S2 consume already-researched scenario and threat packets.  A
        # compact adjudication is sufficient; expensive deep reasoning here
        # mostly repeats the baseline and historically became the longest tail.
        return "low"
    if agent_id == "tactic_validation_cohort":
        return "low"
    if agent_id in {"winning_mechanism", "auditor"}:
        return configured_effort
    if agent_id == "winning_dynamic_specialist":
        return "medium"
    if agent_id == "winning_swarm_independent_portfolio_reviewer":
        if phase == "winning_post_divergence_seed_challenge_mapping":
            # This single pre-generation pass decides whether a free Query
            # angle can cross the conventional ceiling before any S3 weapon
            # exists.  Medium effort improves semantic and technical breadth
            # without adding another serial model call.
            return "medium"
        return "low"
    if agent_id in {"winning_step_critic", "winning_round_critic"}:
        return "medium"
    if agent_id == "reporter":
        return configured_effort
    if phase in {
        "blueprint_design",
        "discovery_meta_replan",
        "winning_step_review",
        "winning_round_review",
        "winning_round_rereview",
        "report_generation",
        "agent_selection",
    }:
        return "medium"
    if phase.endswith("_light"):
        return "low"
    if agent_id == "convergence_fusion":
        return "medium"
    return configured_effort


def _phase_model_verbosity(agent_id: str, phase: str) -> str:
    if phase == "blueprint_design":
        # The blueprint is a compact causal routing artifact.  Low verbosity
        # reduces serialization latency without lowering reasoning effort.
        return "low"
    if agent_id == "winning_swarm_independent_portfolio_reviewer":
        return "low"
    if agent_id in {
        "winning_step_critic",
        "winning_round_critic",
        "auditor",
        "convergence_fusion",
    }:
        return "low"
    if agent_id == "reporter":
        return "medium"
    if agent_id == "winning_s6_image":
        if "card_repair" in phase:
            return "low"
        return "medium"
    if agent_id == "winning_s4_capability" and os.environ.get(
        "EQUIPMENT_DR_ENTERPRISE_LATENCY_PROFILE", "1"
    ).strip().lower() not in {"0", "false", "no"}:
        return "low"
    if phase.endswith("_light") or phase in {"agent_selection", "report_generation"}:
        return "low"
    return "medium"


def _agent_model_options(
    defaults: dict[str, Any],
    agent: AgentDef,
    *,
    provider_kind: str = "responses",
) -> dict[str, Any]:
    profile = agent.model_profile
    options = {**defaults}
    options["reasoning_effort"] = str(
        profile.get("reasoning_effort", options.get("reasoning_effort", "high"))
    )
    options["max_output_tokens"] = int(
        profile.get("max_output_tokens", options.get("max_output_tokens", 5000))
    )
    search = dict(options.get("web_search", {}))
    search["search_context_size"] = str(
        profile.get("search_context_size", search.get("search_context_size", "high"))
    )
    options["web_search"] = search
    return _apply_codex_performance_options(options, provider_kind)


def _apply_codex_performance_options(
    options: Mapping[str, Any],
    provider_kind: str,
    *,
    quality_critical: bool = False,
) -> dict[str, Any]:
    result = dict(options)
    if provider_kind != "codex_cli":
        return result
    profile = (
        os.environ.get(
            "EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE",
            "quality",
        )
        .strip()
        .lower()
    )
    if profile not in {"balanced", "fast"} or quality_critical:
        return result
    if str(result.get("reasoning_effort", "high")).lower() in {"high", "xhigh"}:
        result["reasoning_effort"] = "medium"
    token_cap = 3600 if profile == "balanced" else 2800
    result["max_output_tokens"] = min(
        int(result.get("max_output_tokens", token_cap)),
        token_cap,
    )
    if profile == "fast":
        result["model_verbosity"] = "low"
    search = result.get("web_search")
    if isinstance(search, Mapping):
        search_options = dict(search)
        search_options["search_context_size"] = (
            "medium" if profile == "balanced" else "low"
        )
        result["web_search"] = search_options
    return result


def _evidence_from_web_sources(
    *,
    request: AgentRunRequest,
    payload: dict[str, Any],
    sources: object,
    provider_kind: str = "responses",
) -> list[EvidenceCard]:
    claims = {
        _without_tracking_parameters(str(item.get("url", "")).strip()): str(
            item.get("claim", "")
        ).strip()
        for item in payload.get("source_claims", [])
        if isinstance(item, dict) and str(item.get("url", "")).strip()
    }
    source_rows = (
        list(sources)
        if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes))
        else []
    )
    # Some Responses-compatible gateways omit citation annotations when the
    # model is constrained to strict JSON. These remain discovery leads only:
    # the scheduler must fetch, materialize, score, and accept them before use.
    if not source_rows:
        source_rows = [{"url": url, "title": url, "snippet": ""} for url in claims]
    fallback_claim = next(
        (
            str(item).strip()
            for item in payload.get("findings", [])
            if str(item).strip()
        ),
        f"{request.agent.display_name}关于{request.topic}的公开资料研判。",
    )
    result: list[EvidenceCard] = []
    seen: set[str] = set()
    for source in source_rows:
        if not isinstance(source, Mapping):
            continue
        url = _without_tracking_parameters(str(source.get("url", "")).strip())
        if not url or url in seen:
            continue
        seen.add(url)
        digest = sha256(url.encode("utf-8")).hexdigest()[:12]
        title = str(source.get("title", "")).strip()
        snippet = str(source.get("snippet", "")).strip()
        structured_claim = bool(claims.get(url))
        required_source_anchor = bool(source.get("required_source_anchor")) or (
            str(source.get("retrieval_lane", "")) == "required_source_anchor"
        )
        hosted_source = bool(
            snippet
            or (title and title != url)
            or (provider_kind == "codex_cli" and structured_claim)
        )
        source_prefix = "codex" if provider_kind == "codex_cli" else "responses"
        evidence_markers = [
            f"{source_prefix}_web_search_source"
            if hosted_source
            else f"{source_prefix}_web_search_lead"
        ]
        if not structured_claim:
            evidence_markers.append("finding_fallback")
        if required_source_anchor:
            evidence_markers.append("required_source_anchor")
        result.append(
            EvidenceCard(
                evidence_id=f"ev-{request.agent.agent_id}-web-{digest}",
                source_title=_normalized_source_title(title, url),
                source_url=url,
                source_tier="B",
                claim=claims.get(url) or fallback_claim,
                excerpt=snippet,
                source_location=f"{source_prefix}:web_search",
                quality_assessment="; ".join(evidence_markers),
                created_by=request.agent.agent_id,
            )
        )
    return result


def _normalized_source_title(title: str, url: str) -> str:
    if title and title != url:
        return title
    try:
        parsed = urlsplit(url)
    except ValueError:
        return title or url
    hostname = (parsed.hostname or "公开来源").removeprefix("www.")
    path_name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    readable_name = re.sub(r"[-_]+", " ", path_name).strip()
    if readable_name and readable_name.lower() not in {"article", "release", "report"}:
        return f"{hostname} · {readable_name[:120]}"
    return hostname


def _without_tracking_parameters(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
    )


def _source_rows_from_discovery_text(text: str) -> list[dict[str, str]]:
    """Extract discovery leads only; scheduler materialization remains authoritative."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"https://[^\s<>\"']+", text):
        url = match.group(0).rstrip(").,;:，。；：】]}>")
        if url in seen:
            continue
        seen.add(url)
        rows.append({"url": url, "title": url, "snippet": ""})
        if len(rows) >= 12:
            break
    return rows


_REPORT_CANONICAL_H2 = (
    "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
    "第二层：技术攻关层——能力实现途径与核心技术",
    "第三层：能力图像与效能贡献层",
)

_REPORT_CANONICAL_H3 = (
    "① 典型作战场景",
    "② 新战法或新概念技术及制胜机理",
    "③ 装备能力特征清单",
    "④ 能力实现途径",
    "⑤ 核心技术清单与攻关优先级",
    "⑥ 技术耦合与短板风险",
    "⑦ 装备能力图像",
    "⑧ 效能贡献评估",
    "⑨ 发展优先级与近期抓手",
)

_PROJECT_REPORT_CANONICAL_H2 = (
    "一、需求分析",
    "二、项目画像",
    "三、总体方案",
    "四、关键技术",
    "五、研制基础",
)

_PROJECT_REPORT_CANONICAL_H3 = (
    "（一）需求概述",
    "（二）国内外现状",
    "（三）建设必要性分析",
    "（一）装备图像概述",
    "（二）作战运用模式",
    "（三）体系贡献率分析",
    "（四）主要战技指标",
    "（一）总体架构",
    "（二）子系统方案",
    "（一）关键技术清单与攻关途径",
    "（一）参与单位",
    "（二）技术基础",
)

_PROJECT_REPORT_CANONICAL_H4 = (
    "1. 背景分析",
    "2. 需求阐述",
    "3. 项目画像",
    "1. 国外情况",
    "2. 国内现状（中国）",
    "3. 对比小结",
    "1. 作战使用角度",
    "2. 装备能力提升角度",
    "3. 领域占位角度",
    "4. 综合效益",
    "1. 作战运用流程",
    "2. 链路闭环分析",
)

_PROJECT_REPORT_H3_PARENT = {
    title: parent
    for parent, titles in (
        (_PROJECT_REPORT_CANONICAL_H2[0], _PROJECT_REPORT_CANONICAL_H3[0:3]),
        (_PROJECT_REPORT_CANONICAL_H2[1], _PROJECT_REPORT_CANONICAL_H3[3:7]),
        (_PROJECT_REPORT_CANONICAL_H2[2], _PROJECT_REPORT_CANONICAL_H3[7:9]),
        (_PROJECT_REPORT_CANONICAL_H2[3], _PROJECT_REPORT_CANONICAL_H3[9:10]),
        (_PROJECT_REPORT_CANONICAL_H2[4], _PROJECT_REPORT_CANONICAL_H3[10:12]),
    )
    for title in titles
}

_PROJECT_REPORT_H4_PARENT = {
    title: parent
    for parent, titles in (
        (_PROJECT_REPORT_CANONICAL_H3[0], _PROJECT_REPORT_CANONICAL_H4[0:3]),
        (_PROJECT_REPORT_CANONICAL_H3[1], _PROJECT_REPORT_CANONICAL_H4[3:6]),
        (_PROJECT_REPORT_CANONICAL_H3[2], _PROJECT_REPORT_CANONICAL_H4[6:10]),
        (_PROJECT_REPORT_CANONICAL_H3[4], _PROJECT_REPORT_CANONICAL_H4[10:12]),
    )
    for title in titles
}


from equipment_deep_research.agents.workflows import (
    reporting_support as _reporting_support,
)

_reporting_support._sync_legacy_globals()

from equipment_deep_research.agents.workflows.reporting_support import (
    _report_template_mode,
    _report_canonical_headings,
    _report_has_complete_canonical_structure,
    _canonical_report_h2,
    _canonical_report_h3,
    _canonical_report_h4,
    _normalize_report_structure_deterministically,
    _report_capability_cues,
    _report_capability_portrait_markdown,
    _remove_empty_report_clauses,
    _normalized_report_reuse_text,
    _report_matrix_verification_mechanism,
    _reflow_long_report_paragraphs,
    _stabilize_report_delivery_contract,
    _report_issues_are_deterministic_format_only,
    _project_argument_report_writer_system_prompt,
    _report_writer_system_prompt,
    _report_repair_system_prompt,
    _clean_winning_hypothesis_title,
    _winning_portfolio_title,
    _winning_combat_scene,
    _winning_primary_equipment_form,
    _winning_title_has_concrete_equipment_identity,
    _prioritize_equipment_evidence_refs,
    _is_remote_precision_portfolio_direction,
    _report_branch,
    _report_target_chars,
    _unbounded_quality_report,
    _report_hard_max_chars,
    _clip_complete_report_phrase,
    _compact_report_table_row,
    _normalize_report_line_ending,
    _enforce_report_hard_max,
    _report_writer_max_chars,
    _reporter_output_token_budget,
    _strip_report_internal_markers,
    _clean_reporter_clue_text,
    _mark_reporter_handoff_rewrite_boundaries,
    _sanitize_reporter_output,
    _normalize_branch_report_labels,
    _normalize_numbered_report_title_group,
    _reporter_generation_payload,
    _compact_reporter_branch_products,
    _reporter_repair_payload,
    _reporter_timeout_retry_payload,
    _reporter_agent_contract,
    _reporter_revision_notes,
    _report_issue_code,
    _report_capability_image_table_directions,
    _report_fragment_quality_issues,
    _report_draft_quality_issues,
    _report_project_argument_content_issues,
    _report_three_layer_content_issues,
    _report_domain_attribute_issues,
    _report_markdown_structure_issues,
    _unbalanced_report_markdown,
    _report_table_issues,
    _is_report_seed_copy_issue,
    _report_seed_copy_issues,
    _report_v2_benchmark_issues,
    _report_issues_require_fallback,
    _report_delivery_blocking_issues,
    _report_nonnegotiable_delivery_issues,
    _branch_delivery_is_complete,
    _c_branch_product_semantically_present,
    _report_required_section_present,
    _has_numbered_report_label,
    _report_evidence_ids,
    _normalize_report_summary,
    _limit_report_summary,
)


def _parse_baseline_payload(text: str) -> dict[str, Any]:
    value = _parse_json_object(text)
    if not value:
        return {
            "findings": [text],
            "confidence": 0.45,
            "open_questions": [],
            "handoff_summary": text,
        }
    return value


def _typed_packet_payload(
    agent_id: str,
    analysis_sections: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str]:
    definition = BASELINE_PAYLOAD_TYPES.get(agent_id)
    if definition is None:
        return "", {}, "1.0"
    payload_type, required_fields = definition
    payload_fields = required_fields + BASELINE_OPTIONAL_PAYLOAD_FIELDS.get(
        agent_id, ()
    )
    payload = {name: analysis_sections.get(name, "") for name in payload_fields}
    frontier_inspirations = analysis_sections.get("frontier_inspirations", [])
    if isinstance(frontier_inspirations, list) and frontier_inspirations:
        payload["frontier_inspirations"] = [
            dict(item)
            for item in frontier_inspirations[:3]
            if isinstance(item, Mapping)
        ]
    if agent_id == "weapon_equipment":
        payload["parameter_observations"] = _normalize_parameter_observations(
            payload.get("parameter_observations")
        )
    elif agent_id == "operational_employment":
        payload["coa"] = _normalize_coa(payload.get("coa"))
    return payload_type, payload, "2.0"


def _normalize_parameter_observations(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else [value]
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            item = dict(row)
        elif row not in (None, "", [], {}):
            item = {"parameter": str(row), "value": "未结构化披露"}
        else:
            continue
        item.setdefault("parameter", "公开参数")
        item.setdefault("value", "未披露")
        item.setdefault("unit", "未披露")
        item.setdefault("variant", "公开来源未注明批次")
        item.setdefault("condition", "公开来源条件")
        item.setdefault("confidence", 0.5)
        normalized.append(item)
    return normalized or [
        {
            "parameter": "公开参数",
            "value": "未披露",
            "unit": "未披露",
            "variant": "公开来源未注明批次",
            "condition": "公开来源条件",
            "confidence": 0.5,
        }
    ]


def _normalize_coa(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        normalized = dict(value)
    else:
        normalized = {"baseline": value or "未单列基线方案"}
    normalized.setdefault("baseline", "未单列基线方案")
    normalized.setdefault("distributed", "未单列弹性分布方案")
    normalized.setdefault("resource_constrained", "未单列资源受限方案")
    return normalized


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _findings_for_agent(agent_id: str, topic: str, route: str) -> list[str]:
    if agent_id == "international_situation":
        return [
            f"围绕{topic}，需要先识别潜在威胁力量和对抗压力。",
            "战略格局变化可能推动新型装备能力从单点性能转向体系贡献。",
        ]
    if agent_id == "combat_scenario":
        return [
            f"{topic}应落入明确任务场景，包含敌方方案、关键时间窗和环境约束。",
            "场景约束决定能力画像不能只写技术方向，必须转化为任务功能。",
        ]
    if agent_id == "weapon_equipment":
        return [
            f"需要围绕{topic}建立国外现役、在研和替代装备的型号谱系与能力证据矩阵。",
            "国外装备的体系依赖、任务优势和能力边界应分别映射为防御性反制选项、现役升级需求与新装备研发需求。",
        ]
    if agent_id == "operational_employment":
        return [
            f"{topic}需要结合COA、兵力协同和经验教训判断可用作战样式。",
            "作战运用约束用于校验能力画像是否能进入真实任务链条。",
        ]
    if agent_id == "case_research":
        return [
            f"围绕{topic}形成跨案例事实时序、关键决策点和因果链。",
            "案例结论必须区分可迁移机制、特定战场条件与对手反适应边界。",
            "案例Packet直接进入S3-S6，不由S6重新猜测或压缩生成。",
        ]
    return [f"{agent_id} produced baseline finding for {topic} under {route}."]


def _analysis_sections_for_agent(
    agent_id: str, topic: str, route: str
) -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {
        "international_situation": {
            "situation_assessment": f"围绕{topic}研判国际安全环境、装备竞争态势和外部驱动因素。",
            "threat_assessment": "识别潜在威胁力量、能力增长点、可能意图与对抗压力。",
            "strategic_pattern": "分析战略格局变化对体系对抗和装备需求的牵引。",
            "opponent_moves": "跟踪对手装备部署、技术投入、演训和作战概念动向。",
            "warning_indicators": ["力量部署异常", "采购与演训节奏变化"],
            "alternative_hypotheses": ["能力扩张", "常规轮换或政策信号"],
            "scenario_drivers": ["近期威胁", "中期能力形成", "远期技术扩散"],
        },
        "combat_scenario": {
            "scenario_framework": f"将{topic}映射到任务背景、作战阶段、参与力量和胜负条件。",
            "enemy_coa": "构造敌方可能行动方案、关键节点和可观测行为。",
            "critical_timeline": "标注预警、决策、交战、重构和保障的关键时间窗口。",
            "environment_constraints": "明确地形、气象、电磁、网络和部署空间约束。",
            "scenario_branches": ["最可能分支", "最危险分支"],
            "capability_pressure_points": ["预警时间窗", "断链自治", "持续保障"],
            "assumptions": ["公开来源不足处显式标注假设"],
        },
        "weapon_equipment": {
            "foreign_equipment_landscape": f"围绕{topic}梳理国外现役、在研、预研和替代装备的国家、厂商、型号谱系、任务定位、部署状态与证据覆盖。",
            "domestic_equipment_landscape": f"围绕{topic}梳理中国国内公开可核验的现役、在研、预研装备与技术项目，标注单位、状态、任务定位和证据边界。",
            "foreign_equipment_cases": [
                {
                    "country": "美国/俄罗斯/其他强国",
                    "organization": "军方/研制单位/厂商",
                    "equipment_or_project": "具体型号或项目",
                    "status": "现役|在研|预研|试验",
                    "problem_addressed": "解决的问题或难点",
                    "technical_route": "技术方案途径",
                    "core_technologies": ["核心技术"],
                    "core_indicators": ["带条件、批次与来源的公开指标"],
                    "source_urls": ["公开来源URL"],
                    "image_urls": ["可用实证或图片URL"],
                    "evidence_boundary": "公开证据能与不能证明什么",
                }
            ],
            "domestic_equipment_cases": [
                {
                    "country": "中国",
                    "organization": "公开披露的参与单位",
                    "equipment_or_project": "具体型号或项目",
                    "status": "现役|在研|预研|试验",
                    "problem_addressed": "解决的问题或难点",
                    "technical_route": "技术方案途径",
                    "core_technologies": ["核心技术"],
                    "core_indicators": ["带条件、批次与来源的公开指标"],
                    "source_urls": ["公开来源URL"],
                    "image_urls": ["可用实证或图片URL"],
                    "evidence_boundary": "公开证据能与不能证明什么",
                }
            ],
            "comparative_findings": [
                "按问题解决路径比较国外与中国国内优势和短板",
                "按核心技术、技术途径和工程成熟度比较差异",
                "据此说明本项目的差异化优势和补位价值",
            ],
            "equipment_profiles": [
                {"model": "baseline-model", "variant": "public-baseline"}
            ],
            "current_parameters": f"梳理与{topic}相关的现有装备功能、参数和体系接口。",
            "parameter_observations": [
                {
                    "parameter": "公开参数",
                    "value": "unknown",
                    "unit": "unknown",
                    "variant": "public-baseline",
                    "condition": "公开资料",
                    "confidence": 0.6,
                }
            ],
            "parameter_conflicts": ["冲突参数并列保留，不做无依据覆盖"],
            "development_models": "跟踪在研型号、验证项目、替代路线和潜在迭代方向。",
            "technology_readiness": "按可获得性、验证程度、集成条件和工程风险评估成熟度。",
            "system_dependencies": [
                "指挥控制、数据链、传感器、任务载荷、保障和供应链依赖"
            ],
            "capability_constraints": "识别探测、决策、载荷、协同、保障和成本边界。",
            "scenario_fit": ["按目标场景标注适用与不适用边界"],
            "capability_gaps": ["将装备边界映射为可追溯能力差距"],
            "long_range_precision_missile_evidence": [
                "远打精打导弹专项：按具体导弹/精确弹药对象记录任务效果、指标方向、体系依赖、证据边界和反证"
            ],
            "long_range_unmanned_strike_evidence": [
                "远程无人打击专项：按具体无人平台与载荷记录作用阶段、毁伤效果、自治边界、证据边界和反证"
            ],
            "standoff_suppression_evidence": [
                "远域压制专项：按具体压制平台/弹药记录压制对象、作用距离口径、协同依赖、证据边界和反证"
            ],
            "expendable_decoy_electronic_attack_evidence": [
                "可消耗诱饵/电子攻击专项：按MALD/MALD-J类具体效应器记录压制或欺骗对象、任务依赖、状态、边界和反证"
            ],
            "counter_uas_interceptor_evidence": [
                "反无人机拦截专项：按Coyote/Roadrunner类具体拦截效应器记录目标对象、直接拦截效果、体系依赖、成本交换、边界和反证"
            ],
            "defensive_countermeasure_options": [
                "将国外装备能力与依赖映射为探测、防护、抗干扰、韧性和体系协同等防御功能"
            ],
            "upgrade_requirements": [
                "优先形成可由现役平台、任务系统、软件或保障体系承载的升级需求"
            ],
            "new_equipment_requirements": [
                "当现役平台无法覆盖关键能力边界时形成新装备任务需求、能力目标和技术路线候选"
            ],
            "verification_plan": [
                "通过公开数据复核、仿真、半实物试验、场景演练或工程样机验证需求"
            ],
        },
        "operational_employment": {
            "operational_constraints": f"明确{topic}在任务规则、指挥关系和保障条件下的运用约束。",
            "mission_chain": ["发现", "识别", "决策", "处置", "评估", "恢复"],
            "force_coordination": "分析跨军兵种、有人无人、传感器与火力单元协同关系。",
            "coa": {
                "baseline": "集中式基线",
                "distributed": "弹性分布",
                "resource_constrained": "资源受限",
            },
            "sustainment_resilience": ["补给", "备件", "能源", "软件更新", "战损恢复"],
            "failure_modes": ["断链", "误警饱和", "节点损耗", "保障中断"],
            "lessons": "总结公开战例中的有效做法、失败模式和可迁移经验。",
            "equipment_function_requirements": ["任务链可追溯的装备功能要求"],
        },
        "opponent_monitoring": {
            "change_baseline": f"围绕{topic}建立采购、部署、演训、条令和工业能力变化基线。",
            "observed_moves": ["公开可观测采购与部署动向"],
            "formation_timeline": ["近期项目节点", "中期能力形成窗口"],
            "threat_effects": ["对任务链和装备需求形成的压力"],
            "system_dependencies": ["指挥、数据链、保障和工业依赖"],
            "counter_requirements": ["防御性监测、韧性和验证需求"],
            "warning_indicators": ["采购节奏变化", "部署演训异常", "条令概念更新"],
        },
        "system_confrontation": {
            "system_boundaries": f"围绕{topic}限定红蓝任务链、信息链和保障链边界。",
            "red_blue_models": {"red": "体系压力类别", "blue": "防御性任务体系"},
            "dependency_graph": ["感知→决策→协同→效应→评估→保障"],
            "cascading_failures": ["关键接口降级导致任务链级联失效"],
            "critical_vulnerabilities": ["单点依赖", "接口不兼容", "保障链脆弱"],
            "alternative_configs": ["分布式冗余", "降级运行", "多路径保障"],
            "reinforcement_directions": ["补链强链", "接口标准化", "体系韧性验证"],
        },
        "case_research": {
            "multilingual_sources": ["公开战报", "影像核验", "智库分析", "官方通报"],
            "fact_timeline": ["预警与部署", "首次规模运用", "对手适应", "战法迭代"],
            "decision_points": [
                "商业通信保障",
                "低成本无人系统规模运用",
                "便携防空重塑低空",
                "电子战争夺频谱",
            ],
            "causal_chain": "低成本消耗品、商用技术和快速迭代经体系融合改变战场成本交换与适应速度。",
            "case_patterns": [
                "低成本消耗性平台通过规模与迭代速度对冲高价值平台优势",
                "商业通信与军用指挥融合可提高断链条件下的任务连续性",
                "传感器—火力闭环速度比单个平台峰值参数更决定战场效果",
                "电子战与反电子战构成无人系统运用的首要生存边界",
                "分布式补给、维修和软件更新决定高消耗作战的持续性",
                "对手快速复制与反适应要求装备采用开放接口和持续升级架构",
            ],
            "lessons": ["低成本×大规模", "快迭代×开放接口", "体系融合×韧性保障"],
            "cross_case_patterns": ["规模—成本—适应速度共同改变战场经济学"],
            "future_scenarios": [
                "强电磁压制与弱网条件下的分布式无人任务持续",
                "高消耗远程精确打击与低成本拦截的成本交换对抗",
                "商用智能与军用任务系统快速融合下的迭代竞赛",
            ],
            "emerging_equipment_categories": [
                "低成本精确打击与消耗性弹药",
                "抗扰分布式无人协同节点",
                "全频谱电子战与认知频谱装备",
                "战场快速制造、维修与软件更新系统",
            ],
            "transfer_boundaries": [
                "公开战例的地理、联盟、工业和规则条件不能直接等同于未来任务环境",
                "所有效果只给出定性等级、比较排序、适用条件和置信度",
            ],
        },
    }
    sections = values.get(
        agent_id, {"finding": f"{agent_id}围绕{topic}执行{route}路线研究。"}
    )
    return {**sections, "research_route": route}


def _public_smoke_url_for_agent(agent_id: str) -> str:
    urls = {
        "international_situation": "https://www.gov.cn/",
        "combat_scenario": "http://www.81.cn/",
        "weapon_equipment": "https://www.mod.gov.cn/",
        "operational_employment": "http://www.81.cn/",
    }
    return urls.get(agent_id, "https://www.gov.cn/")
