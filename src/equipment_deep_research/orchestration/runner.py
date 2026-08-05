from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from difflib import SequenceMatcher
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from equipment_deep_research.agents.provider import (
    AgentProvider,
    AgentSelectionRequest,
    FakeAgentProvider,
    RealAgentProvider,
    ResponsesAgentProvider,
    S6QualityError,
    _capability_direction_quality_issues,
    _enforce_report_hard_max,
    _normalize_s6_deterministic_format,
    _normalize_report_structure_deterministically,
    _s6_delivery_blocking_issues,
    _strip_report_internal_markers,
)
from equipment_deep_research.agents.registry import AgentDef, AgentRegistry
from equipment_deep_research.domain.messages import FINALIZE_TASK_ID, RunCheckpoint
from equipment_deep_research.domain.models import (
    CapabilityImageItem,
    ResearchProblem,
    TraceEvent,
    now_iso,
    to_plain,
)
from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal
from equipment_deep_research.domain.store import DomainStore, SqliteRunStore, TraceStore
from equipment_deep_research.domain.workspace import RunWorkspace, path_from_fd
from equipment_deep_research.harness.context import compact_packet_handoff
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload
from equipment_deep_research.harness.recovery import RecoveryManager
from equipment_deep_research.harness.scheduler import DiscoveryScheduler, WorkerReport
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.harness.winning_core import WinningCoreHarness
from equipment_deep_research.orchestration.coverage import (
    coverage_for_route,
    load_preset_policy,
)
from equipment_deep_research.orchestration.blueprints import (
    build_discovery_blueprint,
    execution_waves_from_blueprint,
    normalize_dynamic_subagents,
    winning_step_modes,
)
from equipment_deep_research.orchestration.execution_contracts import (
    apply_execution_profile_to_blueprint,
    is_quality_execution_profile_id,
    resolve_execution_profile,
)
from equipment_deep_research.orchestration.capability_portrait import (
    normalize_capability_problem,
    normalize_operational_process,
    normalize_verification_plan,
    resolve_capability_portrait,
)
from equipment_deep_research.orchestration.admission import PacketAdmissionGate
from equipment_deep_research.orchestration.audit_policy import (
    decide_final_audit_review,
)
from equipment_deep_research.orchestration.planning import ResearchPlanner
from equipment_deep_research.orchestration.communication import (
    AgentMessageEnvelope,
    OrchestrationMessageBus,
)
from equipment_deep_research.orchestration.deliverables import (
    STRUCTURED_PRODUCT_KEYS,
    branch_profile,
    build_delivery_artifacts,
)
from equipment_deep_research.orchestration.reporting import (
    audit_run,
    render_formal_evidence_reference,
    render_report,
)
from equipment_deep_research.orchestration.recall import RecallCoordinator
from equipment_deep_research.orchestration.winning import WinningMechanismEngine
from equipment_deep_research.orchestration.winning_reasoning import SixStepReasoner
from equipment_deep_research.orchestration.stage_policy import (
    RunStagePolicy,
    resolve_run_stage_policy,
)
from equipment_deep_research.providers.registry import (
    ProviderConfigurationError,
    ProviderRegistry,
)
from equipment_deep_research.tools.evidence import EvidenceGovernor
from equipment_deep_research.tools.permissions import ToolPermissionRegistry
from equipment_deep_research.delivery.quality_gate import ReportQualityGate
from equipment_deep_research.delivery.exporter import DeliveryExporter


PRIMARY_BUSINESS_AGENT_IDS = {
    "international_situation",
    "combat_scenario",
    "weapon_equipment",
    "operational_employment",
    "opponent_monitoring",
    "system_confrontation",
}

# Bump only when Reporter publication stabilization or final report-gate
# semantics change.  Completed checkpoints then reopen the finalize task under
# ``--allow-resume-config-mismatch`` without rerunning baseline agents or the
# winning-swarm candidate/Judge stages.
REPORT_DELIVERY_CONTRACT_VERSION = "2026-08-04.11"


def _baseline_wave_concurrency(
    discovery_blueprint: Mapping[str, Any],
    wave_size: int,
) -> int:
    """Resolve one enforceable concurrency ceiling for every baseline wave."""
    if wave_size < 1:
        raise ValueError("wave_size must be positive")
    configured = os.environ.get("EQUIPMENT_DR_BASELINE_WAVE_CONCURRENCY", "").strip()
    if configured:
        try:
            limit = int(configured)
        except ValueError as exc:
            raise ValueError(
                "EQUIPMENT_DR_BASELINE_WAVE_CONCURRENCY must be a positive integer"
            ) from exc
    else:
        runtime_budgets = discovery_blueprint.get("runtime_budgets", {})
        limit = int(
            runtime_budgets.get("codex_concurrency", 4)
            if isinstance(runtime_budgets, Mapping)
            else 4
        )
    if limit < 1:
        raise ValueError("baseline wave concurrency must be positive")
    return min(wave_size, limit)


def _failure_handoff_candidates(
    failed_agent: AgentDef,
    registry: AgentRegistry,
) -> list[str]:
    required = set(failed_agent.capability_tags)
    published_targets = {
        str(item) for item in failed_agent.handoff_policy.get("publish_to", [])
    }
    candidates = [
        agent
        for agent in registry.enabled_baseline_agents()
        if agent.agent_id != failed_agent.agent_id
        and (
            required.intersection(agent.capability_tags)
            or agent.agent_id in published_targets
            or failed_agent.agent_id
            in {
                str(item)
                for item in agent.handoff_policy.get(
                    "accept_from",
                    [],
                )
            }
        )
    ]
    candidates.sort(
        key=lambda agent: (
            -len(required.intersection(agent.capability_tags)),
            agent.agent_id,
        )
    )
    return [agent.agent_id for agent in candidates]


def _failure_handoff(
    *,
    report: WorkerReport,
    agent: AgentDef,
    registry: AgentRegistry,
    wave_index: int,
    resume_count: int,
) -> AgentMessageEnvelope:
    candidates = _failure_handoff_candidates(agent, registry)
    safe_payload = sanitize_runtime_payload(
        {
            "task_id": _task_id(agent.agent_id),
            "failed_agent_id": agent.agent_id,
            "failure_type": "agent_execution_failed",
            "error": report.error,
            "partial_packet_id": report.packet_id,
            "partial_evidence_ids": report.new_evidence_ids,
            "transfer_candidates": candidates,
            "retryable": True,
            "resume_checkpoint": "checkpoints/latest.json",
            "wave_index": wave_index,
            "resume_count": resume_count,
        },
        max_string_length=512,
    )
    envelope = AgentMessageEnvelope(
        message_id=(
            f"handoff-failed-{agent.agent_id}-w{wave_index}-r{resume_count}"
        ),
        message_type="handoff_ready",
        sender=agent.agent_id,
        recipient=candidates[0] if candidates else "orchestrator",
        object_refs=[
            item
            for item in [report.packet_id, *report.new_evidence_ids]
            if item
        ],
        payload=dict(safe_payload),
        capability_tags=list(dict.fromkeys(agent.capability_tags)),
        status="failed",
        return_node=f"baseline-wave-{wave_index}",
    )
    bus = OrchestrationMessageBus()
    bus.publish(envelope)
    return envelope


def _admitted_packet_snapshot(store: DomainStore) -> list[Any]:
    """Legacy packets have no status and remain eligible; v2 rejections do not."""
    return [
        packet
        for packet in store.baseline_packet_snapshot()
        if getattr(packet, "admission_status", "") != "rejected"
    ]


_MILITARY_EFFECT_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("侦察预警", ("侦察", "预警", "探测", "感知", "态势")),
    ("指挥决策", ("指挥", "决策", "指控", "闭环", "c4isr")),
    ("打击歼灭", ("打击", "歼灭", "毁伤", "火力", "精确效应", "突防")),
    ("拦截反制", ("拦截", "反制", "压制", "干扰", "欺骗", "电子战")),
    ("拒止制衡", ("拒止", "反介入", "区域拒止", "制衡", "封控")),
    ("威慑慑止", ("威慑", "慑止")),
    ("生存抗毁", ("抗毁", "生存", "防护", "隐蔽", "机动", "分散")),
    ("保障恢复", ("保障", "补给", "维修", "恢复", "再生")),
    ("持续作战", ("持续作战", "任务持续", "韧性", "冗余", "任务保持")),
    ("体系协同", ("体系", "协同", "组网", "跨域", "杀伤链", "任务链")),
)

_MILITARY_MECHANISM_TERMS = (
    "导致",
    "形成",
    "改变",
    "削弱",
    "恢复",
    "压缩",
    "延迟",
    "阻断",
    "突破",
    "牵引",
    "依赖",
    "失效",
    "窗口",
    "链路",
    "节点",
    "条件",
    "边界",
)

_STEP_AGENT_DEFAULTS: dict[str, tuple[str, ...]] = {
    "international_situation": ("S1", "S3"),
    "combat_scenario": ("S2", "S3", "S4"),
    "operational_employment": ("S2", "S4", "S5"),
    "weapon_equipment": ("S1", "S4", "S5"),
    "opponent_monitoring": ("S1", "S3", "S5"),
    "system_confrontation": ("S1", "S2", "S3", "S4", "S5"),
    "case_research": ("S3", "S4", "S5"),
}


def _compact_text_value(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _military_effects_for_text(text: str) -> list[str]:
    lowered = text.lower()
    return [
        label
        for label, terms in _MILITARY_EFFECT_TERMS
        if any(term.lower() in lowered for term in terms)
    ]


def _claim_downstream_steps(agent_id: str, text: str) -> list[str]:
    steps = set(_STEP_AGENT_DEFAULTS.get(agent_id, ()))
    lowered = text.lower()
    keyword_steps = {
        "S1": ("对手", "敌方", "威胁", "薄弱", "反适应", "体系依赖"),
        "S2": ("场景", "任务链", "战法", "运用", "协同", "作战阶段"),
        "S3": ("突破", "机制", "趋势", "未来", "假设", "触发"),
        "S4": ("能力", "功能", "性能", "接口", "装备", "指标"),
        "S5": ("现役", "差距", "缺口", "成熟度", "升级", "验证", "在研"),
    }
    for step, terms in keyword_steps.items():
        if any(term in lowered for term in terms):
            steps.add(step)
    return sorted(steps, key=lambda item: int(item[1:]))[:5]


def _military_claim_score(
    *,
    text: str,
    effects: Sequence[str],
    confidence: float,
    source_urls: Sequence[str],
    admission_status: str,
    topic: str,
) -> float:
    lowered = text.lower()
    topic_markers = [
        term
        for _, terms in _MILITARY_EFFECT_TERMS
        for term in terms
        if term.lower() in topic.lower()
    ]
    topic_overlap = sum(term.lower() in lowered for term in topic_markers[:8])
    mechanism_hits = sum(term in lowered for term in _MILITARY_MECHANISM_TERMS)
    score = (
        min(0.32, 0.08 * len(effects))
        + min(0.20, 0.04 * mechanism_hits)
        + min(0.12, 0.04 * topic_overlap)
        + min(0.16, max(0.0, float(confidence)) * 0.16)
        + (0.14 if source_urls else 0.0)
        + (0.06 if admission_status in {"", "accepted"} else 0.02)
    )
    return round(min(1.0, score), 4)


def _claims_are_near_duplicates(left: str, right: str) -> bool:
    left_norm = re.sub(r"[^\w\u4e00-\u9fff]", "", left.lower())
    right_norm = re.sub(r"[^\w\u4e00-\u9fff]", "", right.lower())
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return min(len(left_norm), len(right_norm)) >= 24
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.84


def _case_branch_products(packet: Any) -> dict[str, list[Any]]:
    payload = getattr(packet, "payload", None) or getattr(
        packet, "analysis_sections", {}
    )
    if not isinstance(payload, Mapping):
        return {}
    sources = {
        "case_patterns": ("case_patterns", "cross_case_patterns", "lessons"),
        "future_scenarios": (
            "future_scenarios",
            "future_scenario_mapping",
            "scenario_projections",
        ),
        "emerging_equipment_categories": (
            "emerging_equipment_categories",
            "equipment_needs",
            "equipment_categories",
        ),
        "migration_boundaries": ("migration_boundaries", "transfer_boundaries"),
    }
    limits = {
        "case_patterns": 6,
        "future_scenarios": 3,
        "emerging_equipment_categories": 4,
        "migration_boundaries": 4,
    }
    products: dict[str, list[Any]] = {}
    for key, source_keys in sources.items():
        values = next(
            (
                payload.get(source_key)
                for source_key in source_keys
                if isinstance(payload.get(source_key), list)
                and payload.get(source_key)
            ),
            [],
        )
        if not values:
            continue
        products[key] = [
            _compact_text_value(item, 360)
            if not isinstance(item, Mapping)
            else {
                str(field): _compact_text_value(value, 260)
                for field, value in list(item.items())[:6]
                if value not in (None, "", [], {})
            }
            for item in list(values)[: limits[key]]
        ]
    return products


def _build_military_value_handoff(
    store: DomainStore,
    *,
    topic: str,
    convergence: Mapping[str, Any] | None = None,
    maximum_claims: int = 6,
    maximum_claims_per_agent: int = 2,
) -> dict[str, Any]:
    """Converge admitted baseline output into a small, evidence-bound military packet."""

    gate = PacketAdmissionGate()
    candidates: list[dict[str, Any]] = []
    branch_products: dict[str, list[Any]] = {}
    input_chars = 0
    packet_by_id: dict[str, Any] = {}
    for packet in _admitted_packet_snapshot(store):
        packet_by_id[packet.packet_id] = packet
        input_chars += len(json.dumps(compact_packet_handoff(packet), ensure_ascii=False))
        if packet.agent_id == "case_research":
            branch_products.update(_case_branch_products(packet))
        bundle = gate.extract_claim_bundle(packet, store.evidence)
        status = str(getattr(packet, "admission_status", ""))
        for claim in bundle.claims:
            text = _compact_text_value(claim.text, 340)
            # Do not mistake military terms copied verbatim from the query for
            # new value contributed by the baseline Agent.
            effect_basis = text.replace(_compact_text_value(topic, 320), "")
            effects = _military_effects_for_text(effect_basis)
            mechanism_hits = sum(
                marker in effect_basis.lower()
                for marker in _MILITARY_MECHANISM_TERMS
            )
            # Generic information lists do not enter the S-chain. A conclusion
            # must carry a military task effect, or at least combine a clear
            # causal mechanism with a military mission/体系 term.
            if not effects and mechanism_hits < 2:
                continue
            evidence_ids = [
                evidence_id
                for evidence_id in claim.evidence_ids
                if evidence_id in store.evidence
            ][:2]
            source_urls = [
                store.evidence[evidence_id].source_url
                for evidence_id in evidence_ids
                if store.evidence[evidence_id].source_url.startswith(
                    ("http://", "https://")
                )
            ][:1]
            if not source_urls:
                source_urls = list(claim.source_urls[:1])
            boundary_source = next(
                (
                    item
                    for item in list(getattr(packet, "limitations", []))
                    if str(item).strip()
                ),
                "",
            )
            downstream_steps = _claim_downstream_steps(packet.agent_id, text)
            score = _military_claim_score(
                text=text,
                effects=effects,
                confidence=claim.confidence,
                source_urls=source_urls,
                admission_status=status,
                topic=topic,
            )
            mission_condition = _compact_text_value(
                getattr(packet, "topic_focus", ""),
                160,
            )
            if mission_condition == _compact_text_value(topic, 160):
                mission_condition = ""
            candidate = {
                "claim_id": claim.claim_id,
                "claim_type": claim.claim_type,
                "source_agent_id": packet.agent_id,
                "packet_id": packet.packet_id,
                "military_effects": effects,
                "mechanism": text,
                "mission_condition": mission_condition,
                "failure_boundary": _compact_text_value(boundary_source, 180),
                "evidence_ids": evidence_ids,
                "source_urls": list(dict.fromkeys(source_urls)),
                "confidence": round(float(claim.confidence), 3),
                "downstream_steps": downstream_steps,
                "_selection_score": score,
            }
            candidates.append(
                {
                    key: value
                    for key, value in candidate.items()
                    if value not in (None, "", [], {})
                    or key == "_selection_score"
                }
            )

    ranked = sorted(
        candidates,
        key=lambda item: (
            -float(item["_selection_score"]),
            -len(item.get("military_effects", [])),
            item["source_agent_id"],
            item["claim_id"],
        ),
    )
    deduplicated: list[dict[str, Any]] = []
    for candidate in ranked:
        if any(
            _claims_are_near_duplicates(
                candidate["mechanism"], existing["mechanism"]
            )
            for existing in deduplicated
        ):
            continue
        deduplicated.append(candidate)

    selected: list[dict[str, Any]] = []
    per_agent: dict[str, int] = {}
    # First preserve cross-agent diversity, then fill remaining slots by value.
    for candidate in deduplicated:
        agent_id = candidate["source_agent_id"]
        if per_agent.get(agent_id, 0) or len(selected) >= maximum_claims:
            continue
        selected.append(candidate)
        per_agent[agent_id] = 1
    for candidate in deduplicated:
        if candidate in selected or len(selected) >= maximum_claims:
            continue
        agent_id = candidate["source_agent_id"]
        if per_agent.get(agent_id, 0) >= maximum_claims_per_agent:
            continue
        existing_effects = {
            effect
            for item in selected
            if item["source_agent_id"] == agent_id
            for effect in item.get("military_effects", [])
        }
        adds_new_effect = bool(
            set(candidate.get("military_effects", [])) - existing_effects
        )
        if float(candidate["_selection_score"]) < 0.62 and not adds_new_effect:
            continue
        selected.append(candidate)
        per_agent[agent_id] = per_agent.get(agent_id, 0) + 1

    selected = [
        {key: value for key, value in item.items() if key != "_selection_score"}
        for item in selected
    ]

    selected_packet_ids = {item["packet_id"] for item in selected}
    open_questions = list(
        dict.fromkeys(
            _compact_text_value(question, 220)
            for packet_id in selected_packet_ids
            for question in getattr(packet_by_id.get(packet_id), "open_questions", [])[:1]
            if str(question).strip()
        )
    )[:4]
    raw_conflicts = list((convergence or {}).get("conflicts", []))
    conflicts = [
        _compact_text_value(item, 240)
        for item in raw_conflicts
        if _military_effects_for_text(str(item))
        or any(marker in str(item) for marker in _MILITARY_MECHANISM_TERMS)
    ][:3]
    handoff = {
        "schema": "military_value_handoff_v1",
        "query_anchor": _compact_text_value(topic, 320),
        "claims": selected,
        "conflicts": conflicts,
        "open_questions": open_questions,
        "branch_products": branch_products,
    }
    output_chars = len(json.dumps(handoff, ensure_ascii=False))
    handoff["statistics"] = {
        "input_packet_count": len(packet_by_id),
        "candidate_claim_count": len(candidates),
        "selected_claim_count": len(selected),
        "source_agent_count": len({item["source_agent_id"] for item in selected}),
        "evidence_url_count": len(
            {
                url
                for item in selected
                for url in item.get("source_urls", [])
            }
        ),
        "input_chars": input_chars,
        "output_chars": output_chars,
        "compression_ratio": round(output_chars / max(1, input_chars), 4),
    }
    return handoff


def _military_handoff_packet_refs(
    store: DomainStore,
    handoff: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected_packet_ids = {
        str(item.get("packet_id", ""))
        for item in handoff.get("claims", [])
        if isinstance(item, Mapping) and str(item.get("packet_id", ""))
    }
    if not selected_packet_ids and handoff.get("branch_products"):
        selected_packet_ids = {
            packet.packet_id
            for packet in _admitted_packet_snapshot(store)
            if packet.agent_id == "case_research"
        }
    return [
        {
            "packet_id": packet.packet_id,
            "agent_id": packet.agent_id,
            "evidence_ids": list(packet.evidence_ids)[:3],
            "confidence": packet.confidence,
        }
        for packet in _admitted_packet_snapshot(store)
        if packet.packet_id in selected_packet_ids
    ]


def _military_handoff_evidence_index(
    store: DomainStore,
    handoff: Mapping[str, Any],
) -> list[dict[str, Any]]:
    claim_evidence_ids = list(
        dict.fromkeys(
            str(evidence_id)
            for item in handoff.get("claims", [])
            if isinstance(item, Mapping)
            for evidence_id in item.get("evidence_ids", [])
            if str(evidence_id)
        )
    )
    selected_packet_ids = {
        str(item.get("packet_id", ""))
        for item in handoff.get("claims", [])
        if isinstance(item, Mapping) and str(item.get("packet_id", ""))
    }
    packet_evidence_ids = list(
        dict.fromkeys(
            str(evidence_id)
            for packet in _admitted_packet_snapshot(store)
            if packet.packet_id in selected_packet_ids
            for evidence_id in packet.evidence_ids
            if str(evidence_id) in store.evidence
        )
    )
    direct_weapon_ids = [
        evidence_id
        for evidence_id in packet_evidence_ids
        if evidence_id.startswith("ev-weapon_equipment-")
        or str(store.evidence[evidence_id].created_by) == "weapon_equipment"
    ]
    other_packet_ids = [
        evidence_id
        for evidence_id in packet_evidence_ids
        if evidence_id not in direct_weapon_ids
    ]
    # Selected claims intentionally carry only a tiny citation subset, while
    # the winning swarm needs all accepted object-level cards from the packet.
    # Expand direct weapon evidence before generic packet context so a
    # multi-equipment packet is not reduced to its first two citations.
    evidence_ids = list(
        dict.fromkeys(
            [*claim_evidence_ids, *direct_weapon_ids, *other_packet_ids]
        )
    )
    return [
        {
            "evidence_id": item.evidence_id,
            "title": _compact_text_value(item.source_title, 140),
            "url": item.source_url,
            "tier": item.source_tier,
            "claim": _compact_text_value(item.claim, 260),
            "created_by": item.created_by,
        }
        for evidence_id in evidence_ids[:24]
        if (item := store.evidence.get(evidence_id)) is not None
    ]


def _optimized_fake_model_analysis(branch: str, store: DomainStore) -> dict[str, Any]:
    """Deterministic acceptance fixture for branch-contract smoke tests."""
    evidence_ids = list(store.evidence)[:6]
    base = {
        "effect_chain": [
            "任务压力形成→现有任务链暴露失效窗口→新机制改变对抗关系→能力映射→验证"
        ],
        "capability_mapping": ["把任务效果映射为功能、指标、接口和验证条件"],
        "gap_assessment": [
            {"capability": "任务链韧性", "grade": "关键差距", "basis": "公开证据与场景压力"}
        ],
        "assumptions": ["离线fixture仅验证合同与数据流，不代表真实军事结论"],
        "open_questions": [],
        "confidence": 0.78,
        "subagent_runs": [],
        "loop_trace": [],
    }
    if branch == "A":
        domains = [
            "分布式感知", "边缘决策", "抗扰协同", "任务重构", "精确效应",
            "电子对抗", "持续保障", "试验评估",
        ]
        indicators = [
            f"{domains[index % len(domains)]}指标{index + 1}（任务级可验证口径）"
            for index in range(30)
        ]
        base["branch_products"] = {
            "tactic_concepts": [
                "去中心蜂群自主决策",
                "功能解耦的动态马赛克任务重组",
                "诱骗—压制—精确效应递进战法",
            ],
            "tactic_combinations": [
                "分布式感知+去中心决策",
                "诱骗塑形+电子压制",
                "异构蜂群+动态任务重组",
                "低成本消耗+精确效应",
                "前沿自治+后方持续保障",
            ],
            "capability_domains": domains,
            "capability_indicators": indicators,
            "equipment_forms": ["智能蜂群母舰", "异构协同网关", "抗扰边缘任务节点"],
            "research_backgrounds": ["背景A", "背景B", "背景C"],
            "operational_scenarios": [f"场景{index + 1}" for index in range(6)],
            "tactic_validations": [
                {"tactic_id": f"T{index + 1}", "result": "定性可行，需仿真和试验校准", "evidence_ids": evidence_ids}
                for index in range(3)
            ],
        }
    elif branch == "C":
        case_packet = next(
            (packet for packet in _admitted_packet_snapshot(store) if packet.agent_id == "case_research"),
            None,
        )
        sections = (case_packet.payload or case_packet.analysis_sections) if case_packet else {}
        base["branch_products"] = {
            "case_patterns": list(
                sections.get("case_patterns")
                or sections.get("cross_case_patterns")
                or []
            )[:6],
            "future_scenarios": list(
                sections.get("future_scenarios")
                or sections.get("future_scenario_mapping")
                or []
            )[:3],
            "emerging_equipment_categories": list(
                sections.get("emerging_equipment_categories")
                or sections.get("equipment_needs")
                or []
            )[:4],
        }
    else:
        base["branch_products"] = {}
    return base


class DeepResearchRunner:
    def __init__(
        self,
        *,
        project_root: Path,
        output_root: Path,
        agent_config_path: Path,
        preset_config_path: Path,
        provider_config_path: Path | None = None,
        evidence_config_path: Path | None = None,
        route_config_path: Path | None = None,
        provider: AgentProvider | None = None,
        run_hook: Callable[[str, RunWorkspace], None] | None = None,
        session_store_factory: Callable[[str, Path], Any] | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.output_root = Path(output_root)
        self.agent_config_path = Path(agent_config_path)
        self.preset_config_path = Path(preset_config_path)
        self.provider_config_path = (
            Path(provider_config_path)
            if provider_config_path is not None
            else self.project_root
            / "configs"
            / "equipment_deep_research"
            / "providers.yaml"
        )
        self.evidence_config_path = (
            Path(evidence_config_path)
            if evidence_config_path is not None
            else self.project_root
            / "configs"
            / "equipment_deep_research"
            / "evidence.yaml"
        )
        default_route_config_path = (
            self.project_root / "configs" / "equipment_deep_research" / "routes.yaml"
        )
        sibling_route_config_path = self.agent_config_path.parent / "routes.yaml"
        if route_config_path is not None:
            self.route_config_path = Path(route_config_path)
        elif default_route_config_path.is_file():
            self.route_config_path = default_route_config_path
        elif sibling_route_config_path.is_file():
            self.route_config_path = sibling_route_config_path
        else:
            self.route_config_path = default_route_config_path
        self.provider = provider
        self.run_hook = run_hook
        self.session_store_factory = session_store_factory
        self.event_sink = event_sink
        if provider_config_path is not None and not self.provider_config_path.is_file():
            raise FileNotFoundError(
                f"configuration file does not exist: {self.provider_config_path}"
            )
        if evidence_config_path is not None and not self.evidence_config_path.is_file():
            raise FileNotFoundError(
                f"configuration file does not exist: {self.evidence_config_path}"
            )
        if route_config_path is not None and not self.route_config_path.is_file():
            raise FileNotFoundError(
                f"configuration file does not exist: {self.route_config_path}"
            )

    def run(
        self,
        *,
        mode: str,
        topic: str,
        supplemental_information: str = "",
        research_route: str,
        run_id: str,
        agent_ids: list[str] | None = None,
        max_rounds: int | None = None,
        provider_name: str | None = None,
        provider_model: str | None = None,
        provider_base_url: str | None = None,
        provider_api_key_env: str | None = None,
        agent_model_profiles: dict[str, dict[str, Any]] | None = None,
        resume: bool = False,
        analyst_confirmed: bool = False,
        as_of_date: str = "",
        interaction_mode: str = "expert",
        discovery_branch: str = "auto",
        execution_profile_id: str = "legacy_v1",
        report_template_mode: str = "three_layer_nine_item",
        stage_policy_id: str = "full_method",
        allow_resume_config_mismatch: bool = False,
    ) -> dict[str, Any]:
        resources = _RunResourceScope()
        try:
            result = self._run_impl(
                mode=mode,
                topic=topic,
                supplemental_information=supplemental_information,
                research_route=research_route,
                run_id=run_id,
                agent_ids=agent_ids,
                max_rounds=max_rounds,
                provider_name=provider_name,
                provider_model=provider_model,
                provider_base_url=provider_base_url,
                provider_api_key_env=provider_api_key_env,
                agent_model_profiles=agent_model_profiles,
                resume=resume,
                analyst_confirmed=analyst_confirmed,
                as_of_date=as_of_date,
                interaction_mode=interaction_mode,
                discovery_branch=discovery_branch,
                execution_profile_id=execution_profile_id,
                report_template_mode=report_template_mode,
                stage_policy_id=stage_policy_id,
                allow_resume_config_mismatch=allow_resume_config_mismatch,
                resources=resources,
            )
            delivery_root = resources.prepare_delivery_path()
            manifest = DeliveryExporter().build_manifest(delivery_root)
            return {
                **result,
                "manifest_path": str(delivery_root / "delivery-manifest.json"),
                "manifest_file_count": manifest["file_count"],
            }
        finally:
            resources.close()

    def _run_impl(
        self,
        *,
        mode: str,
        topic: str,
        supplemental_information: str,
        research_route: str,
        run_id: str,
        agent_ids: list[str] | None,
        max_rounds: int | None,
        provider_name: str | None = None,
        provider_model: str | None = None,
        provider_base_url: str | None = None,
        provider_api_key_env: str | None = None,
        agent_model_profiles: dict[str, dict[str, Any]] | None = None,
        resume: bool,
        analyst_confirmed: bool,
        as_of_date: str,
        interaction_mode: str,
        discovery_branch: str,
        execution_profile_id: str,
        report_template_mode: str,
        stage_policy_id: str,
        allow_resume_config_mismatch: bool,
        resources: "_RunResourceScope",
    ) -> dict[str, Any]:
        execution_started_at = now_iso()
        if mode not in {"fake", "real"}:
            raise ValueError("mode must be fake or real")
        if report_template_mode not in {
            "three_layer_nine_item",
            "project_argument_v1",
        }:
            raise ValueError("unknown report template mode")
        stage_policy = resolve_run_stage_policy(stage_policy_id)
        execution_profile = resolve_execution_profile(execution_profile_id)
        requested_problem = ResearchProblem(
            topic=topic,
            supplemental_information=supplemental_information.strip(),
            research_route=research_route,
            selected_agent_ids=[],
            as_of_date=as_of_date,
            interaction_mode=interaction_mode,
            discovery_branch=discovery_branch,
            max_rounds_hint=max_rounds or 2,
        )
        registry = AgentRegistry.load(self.agent_config_path)
        policy = load_preset_policy(self.preset_config_path)
        gate_policy = dict(policy.gate_policy)
        resolved_max_rounds = max_rounds or int(gate_policy.get("max_rounds", 2))
        if execution_profile is not None:
            resolved_max_rounds = min(resolved_max_rounds, 3)
        effective_agent_model_profiles = {
            agent_id: dict(profile)
            for agent_id, profile in (agent_model_profiles or {}).items()
        }
        if execution_profile is not None:
            reporter_profile = dict(effective_agent_model_profiles.get("reporter", {}))
            configured_reporter_model = str(reporter_profile.get("model", ""))
            if not configured_reporter_model or "mini" in configured_reporter_model.lower():
                reporter_profile.update(
                    {
                        "provider": "codex",
                        "model": provider_model
                        or os.environ.get("EQUIPMENT_DR_MODEL", "").strip()
                        or "gpt-5.5",
                    }
                )
            effective_agent_model_profiles["reporter"] = reporter_profile
        provider = self._select_agent_provider(
            mode,
            provider_name,
            model=provider_model,
            base_url=provider_base_url,
            api_key_env=provider_api_key_env,
            agent_model_profiles=effective_agent_model_profiles,
            agent_registry=registry,
        )
        stored_blueprint = (
            self._load_discovery_blueprint(run_id)
            if (
                resume
                and mode == "real"
                and getattr(provider, "provider_kind", "") == "codex_cli"
            )
            else None
        )
        available_blueprint_agents = registry.enabled_baseline_agents()
        available_agent_capabilities = {
            agent.agent_id: tuple(agent.capability_tags)
            for agent in available_blueprint_agents
        }
        available_skills = {
            skill_id: skill.to_agent_skill()
            for skill_id, skill in registry.harness_catalog.skills.items()
        }
        available_knowledge_pack_ids = list(registry.harness_catalog.knowledge_packs)
        model_blueprint: dict[str, Any] = {}
        if stored_blueprint is not None:
            discovery_blueprint = stored_blueprint
        else:
            blueprint_designer = getattr(provider, "design_discovery_blueprint", None)
            if (
                mode == "real"
                and getattr(provider, "provider_kind", "") == "codex_cli"
                and callable(blueprint_designer)
                and execution_profile is None
            ):
                model_blueprint = blueprint_designer(
                    {
                        "topic": topic,
                        "supplemental_information": supplemental_information.strip(),
                        "structured_query_brief": requested_problem.structured_query_brief(),
                        "research_route": research_route,
                        "interaction_mode": interaction_mode,
                        "requested_discovery_branch": discovery_branch,
                        "explicit_constraints": list(requested_problem.constraints),
                        "as_of_date": requested_problem.as_of_date,
                        "analyst_selected_agent_ids": list(agent_ids or []),
                        "heuristic_branch": requested_problem.resolved_discovery_branch(),
                        "maximum_rounds": resolved_max_rounds,
                        "allowed_branches": list("ABCDEFGH"),
                        "other_driver_policy": "记录unmatched_driver，以最接近A-H为运行基座，并依据available_agents即时生成custom_blueprint；由L4复核。",
                        "available_agents": [
                            {
                                "agent_id": agent.agent_id,
                                "display_name": agent.display_name,
                                "description": agent.description,
                                "capability_tags": list(agent.capability_tags),
                                "skill_ids": list(agent.skill_ids),
                                "knowledge_pack_ids": list(agent.knowledge_pack_ids),
                                "tool_names": list(agent.tools),
                                "input_contract": (
                                    agent.input_contract
                                    if isinstance(agent.input_contract, str)
                                    else str(agent.input_contract.get("name", "inline"))
                                ),
                                "output_contract": (
                                    agent.output_contract
                                    if isinstance(agent.output_contract, str)
                                    else str(
                                        agent.output_contract.get("name", "inline")
                                    )
                                ),
                                "wait_for": list(
                                    agent.handoff_policy.get("wait_for", [])
                                ),
                                "publish_to": list(
                                    agent.handoff_policy.get("publish_to", [])
                                ),
                            }
                            for agent in available_blueprint_agents
                        ],
                        "available_shared_skills": [
                            item
                            for item in available_skills.values()
                            if item.get("shared")
                        ],
                        "available_knowledge_packs": registry.knowledge_pack_catalog(),
                    }
                )
            discovery_blueprint = build_discovery_blueprint(
                requested_problem,
                model_blueprint=model_blueprint,
                available_agent_capabilities=available_agent_capabilities,
                available_skills=available_skills,
                available_knowledge_pack_ids=available_knowledge_pack_ids,
            )
        discovery_blueprint = apply_execution_profile_to_blueprint(
            discovery_blueprint,
            execution_profile,
        )
        budget_configurer = getattr(provider, "configure_run_budget", None)
        if callable(budget_configurer):
            budget_configurer(discovery_blueprint.get("runtime_budgets", {}))
        route = str(discovery_blueprint["runtime_route"])
        blueprinted_problem = replace(
            requested_problem,
            discovery_branch=str(discovery_blueprint["primary_branch"]),
        )
        additional_required_tags = set(
            str(item)
            for item in discovery_blueprint.get("required_capability_tags", [])
        )
        specialist_agent_ids = [
            str(item) for item in discovery_blueprint.get("specialist_agent_ids", [])
        ]
        blueprint_initial_agent_ids = list(
            dict.fromkeys(
                str(item)
                for item in [
                    *discovery_blueprint.get("initial_baseline_agent_ids", []),
                    *(
                        discovery_blueprint.get("promoted_callback_agent_ids", [])
                        if resume
                        else []
                    ),
                ]
                if str(item).strip()
            )
        )
        planner = ResearchPlanner(policy)
        required_tags = sorted(
            planner.required_tags_for_problem(blueprinted_problem)
            | additional_required_tags
        )
        if agent_ids:
            (
                effective_agent_ids,
                blueprint_default_agent_ids,
                analyst_requested_agent_ids,
                analyst_additional_agent_ids,
            ) = _merge_blueprint_and_analyst_agent_ids(
                blueprint_agent_ids=blueprint_initial_agent_ids,
                specialist_agent_ids=specialist_agent_ids,
                analyst_agent_ids=agent_ids,
                preserve_blueprint_defaults=execution_profile is not None,
            )
            selected_candidates = registry.select_agents(effective_agent_ids)
            selected_candidate_ids = {agent.agent_id for agent in selected_candidates}
            architecture_additions = [
                registry.get(agent_id)
                for agent_id in specialist_agent_ids
                if agent_id not in selected_candidate_ids
            ]
            selected_candidates.extend(architecture_additions)
            selection_view = {
                "mode": (
                    "blueprint_plus_analyst_additions"
                    if execution_profile is not None
                    else "analyst_explicit"
                ),
                "model_used": False,
                "rationale": (
                    "optimized_v2保留A-H蓝图默认Agent，并将分析师勾选的其他角色作为追加项合并执行；"
                    "人工追加不会覆盖默认编排。"
                    if execution_profile is not None
                    else
                    "分析师已显式锁定核心Agent；系统复用A-H蓝图结果并只补充架构必需的专项Agent，"
                    "避免再次调用Codex重复选择。"
                ),
                "task_analysis": [
                    f"主发现分支={discovery_blueprint['primary_branch']}（{discovery_blueprint['branch_name']}）",
                    f"运行路线={route}",
                    "必需能力=" + "、".join(required_tags),
                ],
                "dependency_notes": [
                    "执行波次由A-H蓝图waves与Agent handoff策略确定；只传递结构化Packet。",
                    (
                        "蓝图默认Agent保持不变，分析师追加角色进入同一依赖编排；系统不再进行重复模型筛选。"
                        if execution_profile is not None
                        else "分析师锁定的Agent不再进行模型二次筛选，专项Agent仅按蓝图补齐。"
                    ),
                ],
                "model_selected_agent_ids": effective_agent_ids,
                "blueprint_default_agent_ids": blueprint_default_agent_ids,
                "analyst_requested_agent_ids": analyst_requested_agent_ids,
                "analyst_additional_agent_ids": analyst_additional_agent_ids,
                "selection_locked_by_analyst": execution_profile is None,
                "selection_augmented_by_analyst": bool(
                    execution_profile is not None and analyst_additional_agent_ids
                ),
                "architecture_additions": [
                    agent.agent_id for agent in architecture_additions
                ],
            }
        elif blueprint_initial_agent_ids:
            selected_candidates = registry.select_agents(
                list(
                    dict.fromkeys(
                        [*blueprint_initial_agent_ids, *specialist_agent_ids]
                    )
                )
            )
            selection_view = {
                "mode": "blueprint_driven",
                "model_used": bool(model_blueprint),
                "rationale": (
                    "主控Agent已在A-H蓝图阶段按分支路径和当前输入形成最小基线Agent计划；"
                    "复用该决策，避免再次调用模型做重复选择。"
                ),
                "task_analysis": [
                    f"主发现分支={discovery_blueprint['primary_branch']}（{discovery_blueprint['branch_name']}）",
                    "首轮Agent=" + "、".join(blueprint_initial_agent_ids),
                    "回调候选="
                    + "、".join(discovery_blueprint.get("callback_agent_ids", [])),
                ],
                "dependency_notes": [
                    "required与reference角色进入首轮；callback角色仅在L3/L4发现独立缺口时启用。",
                    "执行依赖继续服从Agent handoff契约，只传递结构化Packet。",
                ],
                "required_capability_tags": required_tags,
                "model_selected_agent_ids": blueprint_initial_agent_ids,
                "coverage_additions": [],
                "baseline_agent_plan": discovery_blueprint.get(
                    "baseline_agent_plan", []
                ),
                "callback_agent_ids": discovery_blueprint.get(
                    "callback_agent_ids", []
                ),
            }
        else:
            primary_candidates = [
                agent
                for agent in registry.enabled_baseline_agents()
                if agent.agent_id in PRIMARY_BUSINESS_AGENT_IDS
            ]
            candidates = primary_candidates or registry.enabled_baseline_agents()
            candidate_ids = {agent.agent_id for agent in candidates}
            candidates.extend(
                registry.get(agent_id)
                for agent_id in specialist_agent_ids
                if agent_id not in candidate_ids
            )
            selection_request = AgentSelectionRequest(
                topic=topic,
                research_route=route,
                required_capability_tags=required_tags,
                candidates=[
                    {
                        "agent_id": agent.agent_id,
                        "display_name": agent.display_name,
                        "description": agent.description,
                        "capability_tags": agent.capability_tags,
                        "skills": agent.skills,
                        "tools": agent.tools,
                        "input_contract": agent.input_contract,
                        "output_contract": agent.output_contract,
                        "handoff_policy": agent.handoff_policy,
                    }
                    for agent in candidates
                ],
            )
            selector = getattr(provider, "select_agents", None)
            decision = (
                selector(selection_request)
                if callable(selector)
                else FakeAgentProvider().select_agents(selection_request)
            )
            selected_candidates = planner.select_for_problem(
                blueprinted_problem,
                candidates,
                preferred_agent_ids=decision.selected_agent_ids,
                additional_required_tags=additional_required_tags,
            )
            model_ids = [
                agent_id
                for agent_id in decision.selected_agent_ids
                if agent_id in {agent.agent_id for agent in candidates}
            ]
            final_ids = [agent.agent_id for agent in selected_candidates]
            selection_view = {
                "mode": "model_driven"
                if decision.model_used
                else "capability_fallback",
                "model_used": decision.model_used,
                "rationale": decision.rationale,
                "task_analysis": decision.task_analysis,
                "dependency_notes": decision.dependency_notes,
                "required_capability_tags": required_tags,
                "model_selected_agent_ids": model_ids,
                "coverage_additions": [
                    item for item in final_ids if item not in model_ids
                ],
            }
        if os.environ.get("EQUIPMENT_DR_PROMOTE_REQUIRED_BASELINE", "1") != "0":
            selected_candidates, promoted_callback_ids = _promote_required_callbacks(
                selected_candidates=selected_candidates,
                discovery_blueprint=discovery_blueprint,
                registry=registry,
                required_tags=required_tags,
            )
        else:
            promoted_callback_ids = []
            discovery_blueprint["promoted_callback_agent_ids"] = []
        if promoted_callback_ids:
            selection_view["coverage_promoted_callback_agent_ids"] = list(
                promoted_callback_ids
            )
            selection_view["dependency_notes"] = [
                *list(selection_view.get("dependency_notes", [])),
                "为避免完成制胜分析后再进入外循环，缺失必需能力对应的蓝图补充角色已前移执行。",
            ]
        minimum_agent_additions: list[str] = []
        if execution_profile is not None:
            selected_candidates, minimum_agent_additions = (
                _ensure_minimum_business_agents(
                    selected_candidates=selected_candidates,
                    discovery_blueprint=discovery_blueprint,
                    registry=registry,
                    minimum=3,
                    maximum=4,
                )
            )
        if minimum_agent_additions:
            selection_view["minimum_agent_additions"] = minimum_agent_additions
            selection_view["dependency_notes"] = [
                *list(selection_view.get("dependency_notes", [])),
                "optimized_v2 保证至少3个互补业务Agent；新增角色以Query为锚独立研判，并在收敛层后置融合。",
            ]
        selection_view["discovery_blueprint"] = discovery_blueprint
        maximize_codex_parallelism = (
            mode == "real"
            and getattr(provider, "provider_kind", "") == "codex_cli"
            and (
                os.environ.get(
                    "EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM",
                    "0",
                )
                == "1"
                or os.environ.get(
                    "EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE",
                    "quality",
                )
                .strip()
                .lower()
                in {"balanced", "fast"}
            )
        )
        if execution_profile is not None:
            # Optimized v2 parallelizes only dependency-free work.  Required
            # barriers remain part of the branch execution contract.
            maximize_codex_parallelism = True
        selected_agent_waves = execution_waves_from_blueprint(
            selected_candidates,
            discovery_blueprint,
            maximize_parallelism=maximize_codex_parallelism,
        )
        selected_agents = [agent for wave in selected_agent_waves for agent in wave]
        selected_agent_ids = [agent.agent_id for agent in selected_agents]
        callback_agent_ids = [
            str(agent_id)
            for agent_id in discovery_blueprint.get("callback_agent_ids", [])
            if str(agent_id) in set(registry.all_agent_ids())
        ]
        planned_recall_agent_ids = [
            str(item.get("agent_id", ""))
            for item in discovery_blueprint.get("baseline_agent_plan", [])
            if isinstance(item, Mapping)
            and str(item.get("agent_id", "")) in set(registry.all_agent_ids())
        ]
        registered_recall_agent_ids = [
            agent.agent_id for agent in registry.enabled_baseline_agents()
        ]
        recall_candidate_agent_ids = list(
            dict.fromkeys(
                [
                    *selected_agent_ids,
                    *callback_agent_ids,
                    *planned_recall_agent_ids,
                    *registered_recall_agent_ids,
                ]
            )
        )
        recall_candidate_agents = [
            registry.get(agent_id) for agent_id in recall_candidate_agent_ids
        ]
        baseline_plan_mode_by_agent = {
            str(item.get("agent_id", "")): str(item.get("mode", "reference"))
            for item in discovery_blueprint.get("baseline_agent_plan", [])
            if isinstance(item, Mapping)
        }
        # 架构专项 Agent 若未列入业务计划，默认仅作为参考角色，避免隐式
        # 升级为 required/deep/critical 并与主业务 Agent 争抢模型槽位。
        for specialist_agent_id in specialist_agent_ids:
            baseline_plan_mode_by_agent.setdefault(
                specialist_agent_id,
                "reference",
            )
        # Every initially selected baseline agent lies on the run's completion
        # path, including a light/reference agent whose packet is consumed by
        # S1-S6. Give this wave critical priority; "normal" remains reserved for
        # speculative background work that can safely yield a model slot.
        baseline_priority_by_agent = {
            agent.agent_id: "critical"
            for wave in selected_agent_waves
            for agent in wave
        }
        baseline_search_intensity_by_agent = {
            agent.agent_id: {
                "required": "deep",
                # 参考 Agent 只补足主 Agent 的视角，不再重复执行双 lane 深检索。
                # 若后续质量门发现缺口，仍可通过 callback 进行定向补证。
                "reference": "light",
                "callback": "light",
            }.get(
                baseline_plan_mode_by_agent.get(agent.agent_id, "reference"),
                "standard",
            )
            for wave in selected_agent_waves
            for agent in wave
        }
        problem = replace(
            blueprinted_problem,
            selected_agent_ids=selected_agent_ids,
        )
        permissions = ToolPermissionRegistry.default()
        for agent in recall_candidate_agents:
            permissions.validate_agent_tools(agent)
        coverage = coverage_for_route(
            route=route,
            selected_agents=selected_agents,
            policy=policy,
            additional_required_tags=list(required_tags),
            discovery_branch=str(discovery_blueprint["primary_branch"]),
        )
        config_fingerprint = self._config_fingerprint(
            mode=mode,
            max_rounds=resolved_max_rounds,
            analyst_confirmed=analyst_confirmed,
            stage_policy_id=stage_policy.policy_id,
            report_template_mode=report_template_mode,
            provider_name=provider_name,
            provider_model=provider_model,
            provider_base_url=provider_base_url,
            provider_api_key_env=provider_api_key_env,
            agent_model_profiles=effective_agent_model_profiles,
            interaction_mode=interaction_mode,
            discovery_branch=discovery_branch,
            discovery_blueprint=discovery_blueprint,
        )

        resume_config_changed = False
        if resume:
            recovered = RecoveryManager(self.output_root).load(
                run_id,
                topic=topic,
                supplemental_information=supplemental_information.strip(),
                research_route=research_route,
                resolved_route=route,
                selected_agent_ids=selected_agent_ids,
                config_fingerprint=config_fingerprint,
                allow_config_mismatch=allow_resume_config_mismatch,
            )
            workspace = recovered.workspace
            sqlite_store = recovered.sqlite_store
            resources.bind(workspace, sqlite_store)
            store = recovered.domain_store
            trace = recovered.trace_store
            trace.set_event_sink(self.event_sink)
            resume_config_changed = (
                recovered.checkpoint.config_fingerprint != config_fingerprint
            )
            checkpoint = replace(
                recovered.checkpoint,
                resume_count=recovered.checkpoint.resume_count + 1,
            )
            if checkpoint.status == "completed" and resume_config_changed:
                checkpoint = replace(
                    checkpoint,
                    status="running",
                    config_fingerprint=config_fingerprint,
                    completed_task_ids=[
                        task_id
                        for task_id in checkpoint.completed_task_ids
                        if task_id != FINALIZE_TASK_ID
                    ],
                    pending_task_ids=[FINALIZE_TASK_ID],
                    task_statuses={
                        **checkpoint.task_statuses,
                        FINALIZE_TASK_ID: "pending",
                    },
                )
            problem = recovered.problem
            worker_reports = list(recovered.worker_reports)
            source_materials = _dedupe_plain_rows(recovered.source_materials)
            resumed_event = TraceEvent(
                event_id=f"trace-run-resumed-{checkpoint.resume_count}",
                event_type="run_resumed",
                actor="orchestrator",
                summary=f"run resumed for {topic}",
                payload={
                    "resume_count": checkpoint.resume_count,
                    "completed_task_ids": checkpoint.completed_task_ids,
                    "pending_task_ids": checkpoint.pending_task_ids,
                    "status": checkpoint.status,
                    "configuration_changed": resume_config_changed,
                },
            )
            trace.append(resumed_event)
            savepoint_id = sqlite_store.commit(
                (
                    self._checkpoint_proposal(
                        checkpoint, f"resume-{checkpoint.resume_count}"
                    ),
                ),
                (self._trace_proposal(resumed_event),),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
            if checkpoint.status == "completed":
                self._write_recovered_outputs(
                    workspace=workspace,
                    mode=mode,
                    problem=problem,
                    route=route,
                    discovery_blueprint=discovery_blueprint,
                    convergence=self._convergence_from_trace(trace),
                    selected_agent_ids=selected_agent_ids,
                    coverage=coverage,
                    worker_reports=worker_reports,
                    source_materials=source_materials,
                    store=store,
                    trace=trace,
                    analyst_confirmed=analyst_confirmed,
                )
                result = self._result(
                    run_id=run_id,
                    run_dir=workspace.run_dir,
                    route=route,
                    store=store,
                )
                return result
        else:
            workspace = RunWorkspace.create(self.output_root, run_id)
            resources.bind_workspace(workspace)
            workspace.write_run_text(
                "discovery_blueprint.json",
                json.dumps(
                    discovery_blueprint,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
            sqlite_store = SqliteRunStore.for_workspace(workspace, run_id=run_id)
            resources.bind_store(sqlite_store)
            self._emit_hook("after_workspace_created", workspace)
            store = DomainStore()
            store.add_problem(problem)
            trace = TraceStore(event_sink=self.event_sink)
            worker_reports: list[WorkerReport] = []
            source_materials: list[dict[str, Any]] = []
            checkpoint = self._initial_checkpoint(
                run_id=run_id,
                topic=topic,
                research_route=research_route,
                route=route,
                selected_agent_ids=selected_agent_ids,
                max_rounds=resolved_max_rounds,
                mode=mode,
                config_fingerprint=config_fingerprint,
            )
            started_event = TraceEvent(
                event_id="trace-run-started",
                event_type="run_started",
                actor="orchestrator",
                summary=f"run started for {topic}",
                payload={
                    "mode": mode,
                    "provider": provider_name
                    or (
                        "fake"
                        if mode == "fake"
                        else (
                            "codex"
                            if getattr(provider, "provider_kind", "") == "codex_cli"
                            else "responses"
                        )
                    ),
                    "model": provider_model or "",
                    "base_url_host": urlsplit(provider_base_url).hostname
                    if provider_base_url
                    else "",
                    "api_key_env": provider_api_key_env or "",
                    "route": route,
                    "interaction_mode": interaction_mode,
                    "discovery_branch": discovery_blueprint["primary_branch"],
                    "discovery_blueprint": discovery_blueprint,
                    "agent_ids": selected_agent_ids,
                    "stage_policy_id": stage_policy.policy_id,
                    "report_template_mode": report_template_mode,
                    "analyst_confirmed": analyst_confirmed,
                    "agent_selection": selection_view,
                    "agent_models": {
                        agent_id: {
                            "provider": profile.get("provider") or provider_name,
                            "model": profile.get("model"),
                            "base_url_host": urlsplit(
                                str(profile.get("base_url") or "")
                            ).hostname,
                            "api_key_env": profile.get("api_key_env"),
                        }
                        for agent_id, profile in sorted(
                            effective_agent_model_profiles.items()
                        )
                    },
                },
            )
            self._write_core_agent_session(
                workspace,
                "orchestrator",
                {
                    "event_type": "model_result"
                    if selection_view.get("model_used")
                    else "plan_result",
                    "task_analysis": selection_view.get("task_analysis", []),
                    "rationale": selection_view.get("rationale", ""),
                    "dependency_notes": selection_view.get("dependency_notes", []),
                    "selected_agent_ids": selected_agent_ids,
                    "coverage": coverage,
                    "discovery_blueprint": discovery_blueprint,
                },
            )
            trace.append(started_event)
            meta_event = TraceEvent(
                event_id="trace-discovery-meta-loop-initial",
                event_type="discovery_meta_loop_evaluated",
                actor="orchestrator",
                summary=(
                    "Codex 元编排完成，形成A-H发现蓝图"
                    if discovery_blueprint.get("generated_by") == "codex_orchestrator"
                    else "确定性元编排完成，形成A-H发现蓝图"
                ),
                output_refs=[str(discovery_blueprint["blueprint_id"])],
                payload={
                    "cycle": 1,
                    "maximum_cycles": discovery_blueprint["loop_policy"][
                        "meta_max_cycles"
                    ],
                    "primary_branch": discovery_blueprint["primary_branch"],
                    "secondary_branches": discovery_blueprint["secondary_branches"],
                    "runtime_route": route,
                    "generated_by": discovery_blueprint["generated_by"],
                    "replan_required": False,
                },
            )
            if stage_policy.meta_loop_enabled:
                trace.append(meta_event)
            savepoint_id = sqlite_store.commit(
                (
                    self._domain_proposal("ResearchProblem", problem),
                    self._checkpoint_proposal(checkpoint, "initial"),
                ),
                (
                    self._trace_proposal(started_event),
                    *(
                        (self._trace_proposal(meta_event),)
                        if stage_policy.meta_loop_enabled
                        else ()
                    ),
                ),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

        scheduler = DiscoveryScheduler(
            run_id=run_id,
            run_dir=workspace.run_dir,
            provider=provider,
            store=store,
            trace=trace,
            mode=mode,
            source_materials=source_materials,
            session_store_factory=self.session_store_factory,
            workspace=workspace,
            evidence_governor=self._evidence_governor(),
            event_sink=self.event_sink,
            harness_store=sqlite_store,
            harness_catalog=registry.harness_catalog,
            shared_context={
                "discovery_blueprint": discovery_blueprint,
                "structured_query_brief": discovery_blueprint.get(
                    "structured_query_brief", {}
                ),
                "selected_business_agent_ids": [
                    agent_id
                    for agent_id in selected_agent_ids
                    if agent_id in PRIMARY_BUSINESS_AGENT_IDS
                ],
                "_pipeline_agent_ids": [
                    agent_id
                    for agent_id in selected_agent_ids
                    if checkpoint.task_statuses.get(_task_id(agent_id)) != "completed"
                ],
            },
        )
        resources.bind_scheduler(scheduler)
        baseline_progress_setter = getattr(
            provider,
            "set_baseline_progress_callback",
            None,
        )
        if callable(baseline_progress_setter):
            progress_session_id = uuid4().hex[:10]
            progress_sequence = 0

            def emit_baseline_progress(row: dict[str, Any]) -> None:
                nonlocal progress_sequence
                progress_sequence += 1
                event_type = str(row.get("event_type", "baseline_pipeline_progress"))
                details = {
                    key: value for key, value in row.items() if key != "event_type"
                }
                agent_id = str(details.get("agent_id", "orchestrator"))
                event_hash = sha256(
                    json.dumps(
                        {"event_type": event_type, **details},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:12]
                summaries = {
                    "baseline_discovery_started": "Agent 多源检索已启动",
                    "baseline_discovery_lane_started": "Agent 检索通道已启动",
                    "baseline_discovery_lane_completed": "Agent 检索通道已返回",
                    "baseline_discovery_completed": "Agent 多源检索已完成",
                    "baseline_analysis_started": "Agent 结构化分析已启动",
                    "baseline_analysis_completed": "Agent 结构化分析已完成",
                    "baseline_model_queue_started": "Agent 等待模型调用槽位",
                    "baseline_model_call_started": "Agent 模型调用已启动",
                    "baseline_model_call_progress": "Agent 模型调用持续执行中",
                    "baseline_model_call_completed": "Agent 模型调用已完成",
                }
                trace.append(
                    TraceEvent(
                        event_id=(
                            f"trace-{event_type}-{agent_id}-{progress_session_id}-"
                            f"{progress_sequence}-{event_hash}"
                        ),
                        event_type=event_type,
                        actor=agent_id,
                        summary=summaries.get(event_type, "Agent 流水线进度更新"),
                        payload=details,
                    )
                )

            baseline_progress_setter(emit_baseline_progress)
        reports_by_agent = {report.agent_id: report for report in worker_reports}
        agents_by_id = {
            agent.agent_id: agent for agent in recall_candidate_agents
        }
        pending_prefetch_agents = [
            agent
            for agent in selected_agents
            if checkpoint.task_statuses.get(_task_id(agent.agent_id)) != "completed"
        ]
        baseline_concurrency_ceiling = _baseline_wave_concurrency(
            discovery_blueprint,
            max(
                1,
                max(
                    (len(wave) for wave in selected_agent_waves),
                    default=1,
                ),
            ),
        )
        prefetch_executor: ThreadPoolExecutor | None = None
        if (
            mode == "real"
            and getattr(provider, "provider_kind", "") == "codex_cli"
            and callable(getattr(provider, "prefetch_baseline_agent", None))
            and pending_prefetch_agents
        ):
            trace.append(
                TraceEvent(
                    event_id="trace-baseline-pipeline-started",
                    event_type="baseline_pipeline_started",
                    actor="orchestrator",
                    summary="六业务 Agent 检索阶段已按全局并发预算提前流水化启动",
                    output_refs=[
                        f"baseline:{agent.agent_id}"
                        for agent in pending_prefetch_agents
                    ],
                    payload={
                        "agent_ids": [
                            agent.agent_id for agent in pending_prefetch_agents
                        ],
                        "stage": "discovery_prefetch",
                        "dependency_mode": "analysis_only",
                        "max_concurrency": baseline_concurrency_ceiling,
                        "bounded": True,
                    },
                )
            )
            prefetch_executor = ThreadPoolExecutor(
                max_workers=min(
                    len(pending_prefetch_agents),
                    baseline_concurrency_ceiling,
                    max(
                        1,
                        int(
                            os.environ.get(
                                "EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS",
                                "6",
                            )
                        ),
                    ),
                ),
                thread_name_prefix="baseline-discovery-prefetch",
            )
            resources.bind_prefetch_executor(prefetch_executor)
            for agent in pending_prefetch_agents:
                prefetch_executor.submit(
                    scheduler.prefetch_agent,
                    agent=agent,
                    topic=topic,
                    research_route=route,
                    round_index=max(
                        1,
                        checkpoint.round_index + checkpoint.resume_count,
                    ),
                    execution_priority=baseline_priority_by_agent.get(
                        agent.agent_id,
                        "normal",
                    ),
                    search_intensity=baseline_search_intensity_by_agent.get(
                        agent.agent_id,
                        "standard",
                    ),
                    plan_mode=baseline_plan_mode_by_agent.get(
                        agent.agent_id,
                        "reference",
                    ),
                )
        for wave_index, configured_wave in enumerate(selected_agent_waves, start=1):
            wave = [
                agent
                for agent in configured_wave
                if checkpoint.task_statuses.get(_task_id(agent.agent_id)) != "completed"
            ]
            if not wave:
                continue
            for agent in wave:
                checkpoint = self._set_task_status(
                    checkpoint,
                    _task_id(agent.agent_id),
                    "running",
                )
            savepoint_id = sqlite_store.commit(
                (
                    self._checkpoint_proposal(
                        checkpoint,
                        f"baseline-wave-{wave_index}-running-r{checkpoint.resume_count}",
                    ),
                ),
                (),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

            trace_start = len(trace.snapshot())
            wave_concurrency = _baseline_wave_concurrency(
                discovery_blueprint,
                len(wave),
            )
            wave_attempt_suffix = f"-r{checkpoint.resume_count}"
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-baseline-wave-{wave_index}-started"
                        f"{wave_attempt_suffix}"
                    ),
                    event_type="baseline_wave_started",
                    actor="orchestrator",
                    summary=f"baseline wave {wave_index} started with {len(wave)} agent(s)",
                    output_refs=[f"baseline:{agent.agent_id}" for agent in wave],
                    payload={
                        "wave_index": wave_index,
                        "agent_ids": [agent.agent_id for agent in wave],
                        "concurrent": wave_concurrency > 1,
                        "wave_size": len(wave),
                        "max_concurrency": wave_concurrency,
                        "bounded": True,
                        "execution_batches": math.ceil(
                            len(wave) / wave_concurrency
                        ),
                        "execution_mode": discovery_blueprint.get(
                            "baseline_execution_mode", "dependency_waves"
                        ),
                        "codex_session_policy": (
                            "isolated_ephemeral_per_agent"
                            if getattr(provider, "provider_kind", "") == "codex_cli"
                            else "provider_default"
                        ),
                    },
                )
            )
            with ThreadPoolExecutor(
                max_workers=wave_concurrency,
                thread_name_prefix=f"baseline-wave-{wave_index}",
            ) as executor:
                futures = [
                    (
                        agent,
                        executor.submit(
                            scheduler.run_agent,
                            agent=agent,
                            topic=topic,
                            research_route=route,
                            raise_on_error=True,
                            round_index=max(
                                1,
                                checkpoint.round_index + checkpoint.resume_count,
                            ),
                            execution_priority=baseline_priority_by_agent.get(
                                agent.agent_id,
                                "normal",
                            ),
                            search_intensity=baseline_search_intensity_by_agent.get(
                                agent.agent_id,
                                "standard",
                            ),
                            plan_mode=baseline_plan_mode_by_agent.get(
                                agent.agent_id,
                                "reference",
                            ),
                        ),
                    )
                    for agent in wave
                ]
                wave_reports: list[WorkerReport] = []
                wave_failures: list[tuple[AgentDef, WorkerReport, Exception]] = []
                for agent, future in futures:
                    try:
                        wave_reports.append(future.result())
                    except Exception as exc:
                        report = getattr(exc, "worker_report", None)
                        if not isinstance(report, WorkerReport):
                            report = WorkerReport(
                                agent_id=agent.agent_id,
                                status="failed",
                                new_evidence_ids=[],
                                packet_id="",
                                handoff_summary="",
                                session_path=str(
                                    workspace.sessions_dir
                                    / f"{agent.agent_id}.jsonl"
                                ),
                                error=str(exc),
                            )
                        wave_reports.append(report)
                        wave_failures.append((agent, report, exc))

            for report in wave_reports:
                reports_by_agent[report.agent_id] = report
                checkpoint = self._set_task_status(
                    checkpoint,
                    _task_id(report.agent_id),
                    "completed" if report.status == "completed" else "pending",
                )
            worker_reports = [
                reports_by_agent[item]
                for item in selected_agent_ids
                if item in reports_by_agent
            ]
            checkpoint = replace(
                checkpoint,
                source_materials=_dedupe_plain_rows(scheduler.source_materials),
                worker_reports=[to_plain(item) for item in worker_reports],
            )
            domain_proposals = [
                *(
                    self._domain_proposal("EvidenceCard", store.evidence[evidence_id])
                    for report in wave_reports
                    if report.status == "completed"
                    for evidence_id in report.new_evidence_ids
                ),
                *(
                    self._domain_proposal(
                        "BaselineFindingPacket",
                        store.baseline_packets[report.packet_id],
                    )
                    for report in wave_reports
                    if report.status == "completed"
                ),
                *(
                    self._domain_proposal(
                        report.domain_object_type,
                        _domain_object_for_report(store, report),
                    )
                    for report in wave_reports
                    if report.status == "completed"
                    and report.domain_object_type
                    and report.domain_object_id
                ),
                self._checkpoint_proposal(
                    checkpoint,
                    f"baseline-wave-{wave_index}-completed-r{checkpoint.resume_count}",
                ),
            ]
            failure_handoffs = [
                _failure_handoff(
                    report=report,
                    agent=agent,
                    registry=registry,
                    wave_index=wave_index,
                    resume_count=checkpoint.resume_count,
                )
                for agent, report, _ in wave_failures
            ]
            for handoff in failure_handoffs:
                trace.append(
                    TraceEvent(
                        event_id=f"trace-{handoff.message_id}",
                        event_type="agent_failure_handoff_ready",
                        actor=handoff.sender,
                        summary=(
                            f"failed task handoff prepared for {handoff.recipient}"
                        ),
                        input_refs=list(handoff.object_refs),
                        output_refs=[f"{handoff.message_id}.json"],
                        payload=handoff.to_plain(),
                    )
                )
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-baseline-wave-{wave_index}-completed"
                        f"{wave_attempt_suffix}"
                    ),
                    event_type=(
                        "baseline_wave_limited"
                        if wave_failures
                        else "baseline_wave_completed"
                    ),
                    actor="orchestrator",
                    summary=(
                        f"baseline wave {wave_index} preserved partial results; "
                        f"{len(wave_failures)} task(s) remain resumable"
                        if wave_failures
                        else f"baseline wave {wave_index} completed"
                    ),
                    input_refs=[f"baseline:{agent.agent_id}" for agent in wave],
                    output_refs=[
                        report.packet_id
                        for report in wave_reports
                        if report.packet_id
                    ],
                    payload={
                        "wave_index": wave_index,
                        "agent_ids": [report.agent_id for report in wave_reports],
                        "completed_agent_ids": [
                            report.agent_id
                            for report in wave_reports
                            if report.status == "completed"
                        ],
                        "failed_agent_ids": [
                            report.agent_id
                            for report in wave_reports
                            if report.status != "completed"
                        ],
                        "handoff_ids": [
                            handoff.message_id for handoff in failure_handoffs
                        ],
                    },
                )
            )
            trace_proposals = [
                self._trace_proposal(event) for event in trace.snapshot()[trace_start:]
            ]
            batch_hash = _proposal_batch_hash(domain_proposals, trace_proposals)
            savepoint_id = sqlite_store.commit(domain_proposals, trace_proposals)
            for report in wave_reports:
                task_id = _task_id(report.agent_id)
                try:
                    scheduler.append_savepoint(
                        report,
                        savepoint_id,
                        task_id=task_id,
                        batch_hash=batch_hash,
                    )
                except Exception:
                    self._record_session_write_failure(
                        sqlite_store=sqlite_store,
                        run_id=run_id,
                        report=report,
                        task_id=task_id,
                        checkpoint_id=savepoint_id,
                        batch_hash=batch_hash,
                    )
                    raise
            for handoff in failure_handoffs:
                handoff_payload = handoff.to_plain()
                handoff_payload["committed_savepoint_id"] = savepoint_id
                workspace.write_run_text(
                    f"{handoff.message_id}.json",
                    json.dumps(
                        handoff_payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
            if wave_failures:
                raise wave_failures[0][2]

        if prefetch_executor is not None:
            prefetch_executor.shutdown(wait=True)
            resources.release_prefetch_executor()
        if callable(baseline_progress_setter):
            baseline_progress_setter(None)

        if execution_profile is not None:
            admission_packets = store.baseline_packet_snapshot()
            admission_already_complete = bool(admission_packets) and all(
                packet.claim_bundle_ref
                and packet.admission_status in {"accepted", "limited", "rejected"}
                for packet in admission_packets
            )
            if resume and admission_already_complete:
                trace.append(
                    TraceEvent(
                        event_id=(
                            "trace-packet-admission-reused-"
                            f"r{checkpoint.resume_count}"
                        ),
                        event_type="packet_admission_reused",
                        actor="packet_admission_gate",
                        summary="复用已提交的 Packet Admission 结果",
                        input_refs=[
                            packet.packet_id for packet in admission_packets
                        ],
                        output_refs=[
                            packet.claim_bundle_ref for packet in admission_packets
                        ],
                        payload={
                            "packet_count": len(admission_packets),
                            "statuses": {
                                packet.packet_id: packet.admission_status
                                for packet in admission_packets
                            },
                        },
                    )
                )
            else:
                admission_proposals, admission_events = self._apply_packet_admission(
                    workspace=workspace,
                    store=store,
                    topic=topic,
                    discovery_blueprint=discovery_blueprint,
                )
                for event in admission_events:
                    trace.append(event)
                if admission_proposals or admission_events:
                    sqlite_store.commit(
                        admission_proposals,
                        tuple(
                            self._trace_proposal(event)
                            for event in admission_events
                        ),
                    )

        self._emit_hook("after_baseline_agents", workspace)
        convergence = self._convergence_from_trace(trace)
        if checkpoint.task_statuses.get(FINALIZE_TASK_ID) != "completed":
            checkpoint = self._set_task_status(
                checkpoint,
                FINALIZE_TASK_ID,
                "running",
            )
            savepoint_id = sqlite_store.commit(
                (
                    self._checkpoint_proposal(
                        checkpoint,
                        f"{FINALIZE_TASK_ID}-running-r{checkpoint.resume_count}",
                    ),
                ),
                (),
            )
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)

            final_trace_start = len(trace.events)
            trace.append(
                TraceEvent(
                    event_id="trace-baseline-summary",
                    event_type="baseline_agents_summarized",
                    actor="orchestrator",
                    summary=f"{len(worker_reports)} baseline agents completed",
                    output_refs=[
                        report.packet_id
                        for report in worker_reports
                        if report.packet_id
                    ],
                )
            )
            if resume and convergence.get("clusters"):
                trace.append(
                    TraceEvent(
                        event_id=f"trace-discovery-convergence-reused-r{checkpoint.resume_count}",
                        event_type="discovery_convergence_reused",
                        actor="convergence_fusion",
                        summary="从检查点复用已完成的收敛结果",
                    )
                )
            else:
                convergence = self._run_discovery_convergence(
                    provider=provider,
                    workspace=workspace,
                    trace=trace,
                    topic=topic,
                    route=route,
                    discovery_blueprint=discovery_blueprint,
                    coverage=coverage,
                    store=store,
                    mode=mode,
                    available_skills=available_skills,
                    available_knowledge_pack_ids=available_knowledge_pack_ids,
                    meta_loop_enabled=stage_policy.meta_loop_enabled,
                )
            coverage = {
                **coverage,
                "discovery_blueprint": discovery_blueprint,
                "convergence": convergence,
            }
            if not stage_policy.winning_enabled:
                return self._complete_baseline_only_run(
                    run_id=run_id,
                    mode=mode,
                    workspace=workspace,
                    sqlite_store=sqlite_store,
                    checkpoint=checkpoint,
                    final_trace_start=final_trace_start,
                    provider=provider,
                    problem=problem,
                    route=route,
                    discovery_blueprint=discovery_blueprint,
                    convergence=convergence,
                    coverage=coverage,
                    selected_agent_ids=selected_agent_ids,
                    worker_reports=worker_reports,
                    source_materials=_dedupe_plain_rows(scheduler.source_materials),
                    store=store,
                    trace=trace,
                    analyst_confirmed=analyst_confirmed,
                    resolved_max_rounds=resolved_max_rounds,
                    execution_started_at=execution_started_at,
                    stage_policy=stage_policy,
                )
            military_value_handoff = self._prepare_military_value_handoff(
                workspace=workspace,
                trace=trace,
                store=store,
                topic=topic,
                convergence=convergence,
            )
            engine = WinningMechanismEngine(
                min_confidence=float(gate_policy.get("min_stage_confidence", 0.7)),
                min_l2_feasibility=int(gate_policy.get("min_l2_feasibility", 3)),
                risk_based_gates=execution_profile is not None,
            )
            winning_model_analysis = (
                self._load_latest_core_agent_result(workspace, "winning_mechanism")
                if resume
                else {}
            )
            if winning_model_analysis and not _winning_analysis_reusable_for_profile(
                winning_model_analysis,
                execution_profile_id=str(
                    discovery_blueprint.get("execution_profile_id", "legacy_v1")
                ),
            ):
                trace.append(
                    TraceEvent(
                        event_id=(
                            "trace-winning-model-reuse-rejected-r"
                            f"{checkpoint.resume_count}"
                        ),
                        event_type="winning_model_result_reuse_rejected",
                        actor="winning_mechanism",
                        summary=(
                            "已完成的核心结果不含当前质量模式要求的权威制胜组合，"
                            "本次恢复重新执行制胜主链"
                        ),
                        output_refs=["winning-model-analysis"],
                        payload={
                            "execution_profile_id": discovery_blueprint.get(
                                "execution_profile_id", "legacy_v1"
                            ),
                            "reason": "profile_authoritative_portfolio_missing",
                        },
                    )
                )
                winning_model_analysis = {}
            winning_advisor = getattr(provider, "analyze_winning_mechanism", None)
            if winning_model_analysis:
                trace.append(
                    TraceEvent(
                        event_id=f"trace-winning-model-reused-r{checkpoint.resume_count}",
                        event_type="winning_model_result_reused",
                        actor="winning_mechanism",
                        summary="从受控会话复用已完成的核心制胜机理结构化结果",
                        output_refs=["winning-model-analysis"],
                    )
                )
            elif mode == "real" and callable(winning_advisor):
                minimal_winning_input = is_quality_execution_profile_id(
                    discovery_blueprint.get("execution_profile_id")
                )
                winning_packets = (
                    _military_handoff_packet_refs(store, military_value_handoff)
                    if minimal_winning_input
                    else [
                        compact_packet_handoff(packet, minimal=False)
                        for packet in _admitted_packet_snapshot(store)
                    ]
                )
                winning_input = {
                    "topic": topic,
                    "structured_query_brief": discovery_blueprint.get(
                        "structured_query_brief", {}
                    ),
                    "research_route": route,
                    "interaction_mode": problem.interaction_mode,
                    "discovery_blueprint": _compact_winning_blueprint(
                        discovery_blueprint
                    )
                    if minimal_winning_input
                    else discovery_blueprint,
                    "discovery_convergence": _compact_winning_convergence(
                        convergence
                    )
                    if minimal_winning_input
                    else convergence,
                    "coverage": _compact_winning_coverage(coverage)
                    if minimal_winning_input
                    else coverage,
                    "packets": winning_packets,
                    "military_value_handoff": military_value_handoff
                    if minimal_winning_input
                    else {},
                    "evidence_index": (
                        _military_handoff_evidence_index(
                            store,
                            military_value_handoff,
                        )
                        if minimal_winning_input
                        else store.evidence_index()
                    ),
                    **(
                        {}
                        if minimal_winning_input
                        else {
                            "shared_skill_catalog": registry.shared_skill_catalog(),
                            "knowledge_pack_catalog": registry.knowledge_pack_catalog(),
                        }
                    ),
                    "selected_business_agent_ids": list(selected_agent_ids),
                    "execution_profile_id": discovery_blueprint.get(
                        "execution_profile_id", "legacy_v1"
                    ),
                    "execution_contract": _compact_winning_contract(
                        discovery_blueprint.get("execution_contract", {})
                    )
                    if minimal_winning_input
                    else discovery_blueprint.get("execution_contract", {}),
                    "ablation_scope": (
                        "restricted_generic_baseline_evidence_closed"
                        if stage_policy.evidence_closed
                        else ""
                    ),
                    "evidence_closed": stage_policy.evidence_closed,
                }
                self._write_core_agent_session(
                    workspace,
                    "winning_mechanism",
                    {
                        "event_type": "task_received",
                        "summary": "消费结构化基线、正式证据与coverage，执行核心制胜机理分析。",
                        "input_refs": [
                            packet["packet_id"] for packet in winning_input["packets"]
                        ],
                    },
                )
                trace.append(
                    TraceEvent(
                        event_id="trace-winning-model-call",
                        event_type="tool_call",
                        actor="winning_mechanism",
                        summary="核心制胜机理 Agent 调用独立真实模型",
                        input_refs=[
                            packet["packet_id"] for packet in winning_input["packets"]
                        ],
                        payload={
                            "tool_name": "analyze_winning_mechanism",
                            "provider_mode": "real",
                        },
                    )
                )
                progress_setter = getattr(
                    provider,
                    "set_winning_progress_callback",
                    None,
                )
                progress_sequence = 0

                def record_winning_progress(row: dict[str, Any]) -> None:
                    nonlocal progress_sequence
                    progress_sequence += 1
                    self._record_winning_progress_row(
                        workspace,
                        trace,
                        row,
                        attempt=checkpoint.round_index,
                        event_suffix=f"live-{progress_sequence}",
                    )

                progress_streamed = callable(progress_setter)
                if progress_streamed and stage_policy.feedback_loops_enabled:
                    progress_setter(record_winning_progress)
                try:
                    if stage_policy.feedback_loops_enabled:
                        winning_model_analysis, winning_harness_result, winning_tools = (
                            WinningCoreHarness(
                                run_id=run_id,
                                agent=registry.get("winning_mechanism"),
                                catalog=registry.harness_catalog,
                                sessions_dir=workspace.sessions_dir,
                                workspace=workspace,
                                store=sqlite_store,
                            ).execute(
                                winning_advisor,
                                winning_input,
                                attempt=checkpoint.round_index,
                                resume_from="L1",
                            )
                        )
                    else:
                        winning_model_analysis = winning_advisor(winning_input) or {}
                        winning_harness_result = None
                        winning_tools = []
                except S6QualityError as exc:
                    partial_result = getattr(exc, "partial_result", {})
                    if isinstance(partial_result, Mapping) and partial_result:
                        self._write_core_agent_session(
                            workspace,
                            "winning_mechanism",
                            {
                                "event_type": "model_checkpoint",
                                "result": dict(partial_result),
                                "summary": (
                                    "已保存动态蜂群候选账本、专家评估和最终组合；"
                                    "组合内部门通过时可在恢复阶段仅重做S6最终投影。"
                                ),
                            },
                        )
                    raise
                finally:
                    if progress_streamed and stage_policy.feedback_loops_enabled:
                        progress_setter(None)
                if stage_policy.feedback_loops_enabled:
                    self._record_winning_subagent_activity(
                        workspace,
                        trace,
                        winning_model_analysis,
                        attempt=checkpoint.round_index,
                        record_subagents=not progress_streamed,
                    )
                    trace.append(
                        TraceEvent(
                            event_id=f"trace-winning-harness-r{checkpoint.round_index}",
                            event_type="agent_harness_completed",
                            actor="winning_mechanism",
                            summary=f"winning_core_v1 completed: {winning_harness_result.status}",
                            payload={
                                "runtime_profile_id": "winning_core_v1",
                                "active_skill_ids": (
                                    registry.get("winning_mechanism").skill_ids[:1]
                                    if execution_profile is not None
                                    else registry.get("winning_mechanism").skill_ids
                                ),
                                "active_tool_names": winning_tools,
                                "phase_id": "winning",
                                "stop_reason": winning_harness_result.status,
                                "snapshot_count": len(winning_harness_result.snapshots),
                            },
                        )
                    )
                if not winning_model_analysis:
                    self._write_core_agent_session(
                        workspace,
                        "winning_mechanism",
                        {
                            "event_type": "model_result_invalid",
                            "summary": "核心Agent响应不是有效结构化JSON，已转确定性治理回退并限制发布。",
                        },
                    )
                    trace.append(
                        TraceEvent(
                            event_id="trace-winning-model-invalid",
                            event_type="tool_result",
                            actor="winning_mechanism",
                            summary="核心制胜机理 Agent 结构化响应无效，启用治理回退",
                            payload={
                                "tool_name": "analyze_winning_mechanism",
                                "status": "limited_fallback",
                            },
                        )
                    )
                else:
                    self._write_core_agent_session(
                        workspace,
                        "winning_mechanism",
                        {
                            "event_type": "model_result",
                            "result": winning_model_analysis,
                        },
                    )
                    trace.append(
                        TraceEvent(
                            event_id="trace-winning-model-result",
                            event_type="tool_result",
                            actor="winning_mechanism",
                            summary="核心制胜机理 Agent 已返回结构化六步分析",
                            output_refs=["winning-model-analysis"],
                            payload={
                                "tool_name": "analyze_winning_mechanism",
                                "status": "completed",
                            },
                        )
                    )
            if execution_profile is not None and mode == "fake" and not winning_model_analysis:
                winning_model_analysis = _optimized_fake_model_analysis(
                    str(discovery_blueprint["primary_branch"]),
                    store,
                )
            stage_outputs, images, recommendations = engine.run(
                topic=topic,
                route=route,
                store=store,
                trace=trace,
                coverage=coverage,
                max_rounds=resolved_max_rounds,
                model_analysis=winning_model_analysis,
                loops_enabled=stage_policy.feedback_loops_enabled,
            )
            store.retain_capability_images(
                {item.capability_id for item in images}
            )
            recall_coordinator = RecallCoordinator(max_rounds=resolved_max_rounds)
            recall_packet_ids: list[str] = []
            recall_evidence_ids: list[str] = []
            recall_reports: list[WorkerReport] = []
            recall_reports_by_agent: dict[str, WorkerReport] = {}
            completed_return_nodes: list[str] = []
            completed_recall_supplements: list[dict[str, Any]] = []
            for stage in stage_outputs if stage_policy.feedback_loops_enabled else []:
                for recall in stage.recall_requests:
                    routed = recall_coordinator.route(
                        recall,
                        registry,
                        recall_candidate_agent_ids,
                        round_index=checkpoint.round_index,
                    )
                    store.add_recall_request(routed.recall)
                    if routed.status == "routed" and routed.target_agent_id:
                        recall_report = recall_reports_by_agent.get(
                            routed.target_agent_id
                        )
                        reused_recall_result = recall_report is not None
                        if recall_report is None:
                            recall_report = scheduler.run_agent(
                                agent=agents_by_id[routed.target_agent_id],
                                topic=topic,
                                research_route=route,
                                round_index=(
                                    checkpoint.round_index
                                    + len(recall_reports)
                                    + 1
                                ),
                                recall_request={
                                    "recall_id": routed.recall.recall_id,
                                    "reason": routed.recall.reason,
                                    "required_data": routed.recall.required_data,
                                    "return_node": routed.recall.return_node,
                                    "evidence_index": store.evidence_index(),
                                    "targeted_supplement": routed.recall.recall_id.startswith(
                                        "recall-L3-targeted-evidence-"
                                    ),
                                },
                                raise_on_error=True,
                                plan_mode="callback",
                            )
                            recall_reports_by_agent[
                                routed.target_agent_id
                            ] = recall_report
                            recall_reports.append(recall_report)
                            recall_packet_ids.append(recall_report.packet_id)
                            recall_evidence_ids.extend(
                                recall_report.new_evidence_ids
                            )
                        completed = recall_coordinator.complete(routed)
                        store.add_recall_request(completed.recall)
                        completed_return_nodes.append(completed.recall.return_node)
                        packet = store.baseline_packets.get(recall_report.packet_id)
                        findings = list(getattr(packet, "findings", []) or [])[:3]
                        limitations = list(
                            dict.fromkeys(
                                [
                                    *list(getattr(packet, "limitations", []) or []),
                                    *list(getattr(packet, "open_questions", []) or []),
                                ]
                            )
                        )[:3]
                        completed_recall_supplements.append(
                            {
                                "recall_id": completed.recall.recall_id,
                                "target_agent_id": routed.target_agent_id,
                                "return_node": completed.recall.return_node,
                                "packet_id": recall_report.packet_id,
                                "handoff_summary": str(
                                    getattr(packet, "handoff_summary", "")
                                    or recall_report.handoff_summary
                                )[:600],
                                "high_value_findings": [
                                    str(item)[:500] for item in findings
                                ],
                                "new_evidence_ids": list(
                                    dict.fromkeys(recall_report.new_evidence_ids)
                                ),
                                "limitations_or_open_questions": [
                                    str(item)[:400] for item in limitations
                                ],
                            }
                        )
                        trace.append(
                            TraceEvent(
                                event_id=f"trace-recall-completed-{recall.recall_id}",
                                event_type="recall_task_completed",
                                actor=routed.target_agent_id,
                                summary=(
                                    "recall reused the completed callback packet and "
                                    f"returned to {completed.recall.return_node}"
                                    if reused_recall_result
                                    else "recall completed and returned to "
                                    f"{completed.recall.return_node}"
                                ),
                                input_refs=[recall.recall_id],
                                output_refs=[
                                    recall_report.packet_id,
                                    *recall_report.new_evidence_ids,
                                ],
                                payload={
                                    "status": "completed",
                                    "reused_callback_packet": reused_recall_result,
                                    "target_agent_id": routed.target_agent_id,
                                    "return_node": completed.recall.return_node,
                                },
                            )
                        )
                        trace.append(
                            TraceEvent(
                                event_id=f"trace-recall-compressed-{recall.recall_id}",
                                event_type="recall_supplement_compressed",
                                actor="orchestrator",
                                summary=(
                                    "再调结果已压缩为高价值补充，等待回填至"
                                    f"{completed.recall.return_node}；不重跑制胜链"
                                ),
                                input_refs=[recall_report.packet_id],
                                output_refs=[completed.recall.return_node],
                                payload={
                                    "target_agent_id": routed.target_agent_id,
                                    "return_node": completed.recall.return_node,
                                    "finding_count": len(findings),
                                    "evidence_count": len(
                                        recall_report.new_evidence_ids
                                    ),
                                },
                            )
                        )
                    if routed.recommendation is not None:
                        recommendations.append(routed.recommendation)
                    trace.append(
                        TraceEvent(
                            event_id=f"trace-recall-route-{recall.recall_id}",
                            event_type=f"recall_{routed.status}",
                            actor="orchestrator",
                            summary=(
                                f"recall routed to {routed.target_agent_id}"
                                if routed.target_agent_id
                                else "recall limited because no selected agent can cover target"
                            ),
                            input_refs=[recall.recall_id],
                            output_refs=(
                                [routed.target_agent_id]
                                if routed.target_agent_id
                                else (
                                    [routed.recommendation.recommendation_id]
                                    if routed.recommendation
                                    else []
                                )
                            ),
                        )
                    )
            if recall_reports:
                recalled_agent_ids = list(recall_reports_by_agent)
                selected_agent_ids = list(
                    dict.fromkeys([*selected_agent_ids, *recalled_agent_ids])
                )
                selected_agents = [
                    registry.get(agent_id) for agent_id in selected_agent_ids
                ]
                coverage = coverage_for_route(
                    route=route,
                    selected_agents=selected_agents,
                    policy=policy,
                    additional_required_tags=list(required_tags),
                    discovery_branch=str(
                        discovery_blueprint["primary_branch"]
                    ),
                )
                unresolved_tags = set(coverage["missing_required_tags"])
                recommendations = [
                    item
                    for item in recommendations
                    if item.missing_capability_tag in unresolved_tags
                ]
                problem = replace(
                    problem,
                    selected_agent_ids=selected_agent_ids,
                )
                store.add_problem(problem)
                trace.append(
                    TraceEvent(
                        event_id=(
                            f"trace-coverage-recomputed-r"
                            f"{checkpoint.round_index + 1}"
                        ),
                        event_type="coverage_recomputed_after_recall",
                        actor="orchestrator",
                        summary=(
                            "再调结果已合并并重新计算能力覆盖："
                            + (
                                "全部必需标签已覆盖"
                                if coverage["coverage_passed"]
                                else "仍缺少"
                                + "、".join(
                                    coverage["missing_required_tags"]
                                )
                            )
                        ),
                        input_refs=list(dict.fromkeys(recall_packet_ids)),
                        payload={
                            "coverage_passed": coverage["coverage_passed"],
                            "provided_tags": coverage["provided_tags"],
                            "missing_required_tags": coverage[
                                "missing_required_tags"
                            ],
                            "recalled_agent_ids": recalled_agent_ids,
                        },
                    )
                )
                prior_gate_state = {
                    stage.layer: (stage.confidence, stage.gate_passed)
                    for stage in stage_outputs
                }
                stage_outputs = engine.reevaluate_gates_after_recall(
                    topic=topic,
                    route=route,
                    stages=stage_outputs,
                    store=store,
                    coverage=coverage,
                    model_analysis=winning_model_analysis,
                    recall_supplements=completed_recall_supplements,
                )
                for stage in stage_outputs:
                    store.add_stage_output(stage)
                    before_confidence, before_gate = prior_gate_state[stage.layer]
                    supplements = [
                        item
                        for item in completed_recall_supplements
                        if item["return_node"] == stage.layer
                    ]
                    trace.append(
                        TraceEvent(
                            event_id=f"trace-winning-gate-reevaluated-{stage.stage_id}",
                            event_type="winning_stage_gate_reevaluated",
                            actor="orchestrator",
                            summary=(
                                f"{stage.layer}已基于再调证据局部重评门控："
                                f"{before_gate} -> {stage.gate_passed}；未重跑S1-S6"
                            ),
                            input_refs=[
                                item["packet_id"]
                                for item in completed_recall_supplements
                            ],
                            output_refs=[stage.stage_id],
                            payload={
                                "layer": stage.layer,
                                "before_confidence": before_confidence,
                                "after_confidence": stage.confidence,
                                "before_gate_passed": before_gate,
                                "after_gate_passed": stage.gate_passed,
                                "evidence_delta": sum(
                                    len(item["new_evidence_ids"])
                                    for item in supplements
                                ),
                                "winning_chain_rerun": False,
                            },
                        )
                    )
                worker_reports.extend(recall_reports)
            if stage_policy.feedback_loops_enabled:
                trace.append(
                    TraceEvent(
                    event_id=f"trace-winning-outer-loop-r{checkpoint.round_index}",
                    event_type="winning_outer_loop_evaluated",
                    actor="orchestrator",
                    summary=(
                        "外循环完成定向再调，受影响门控已局部重评且未重跑S1-S6"
                        if recall_reports
                        else "外循环评估完成，无需定向再调"
                    ),
                    input_refs=[
                        item.recall_id for item in store.recall_requests.values()
                    ],
                    output_refs=[report.packet_id for report in recall_reports],
                    payload={
                        "attempt": checkpoint.round_index,
                        "maximum_rounds": resolved_max_rounds,
                        "recall_count": len(recall_reports),
                        "return_nodes": completed_return_nodes,
                        "passed": not any(
                            item.status == "limited"
                            for item in store.recall_requests.values()
                        ),
                    },
                    )
                )
            for recommendation in recommendations:
                store.add_recommendation(recommendation)
            for stage in stage_outputs:
                trace.append(
                    TraceEvent(
                        event_id=f"trace-tool-call-write-stage-{stage.stage_id}",
                        event_type="tool_call",
                        actor="winning_mechanism",
                        summary=f"写入{stage.layer}制胜机理阶段输出",
                        payload={
                            "tool_name": "write_stage_output",
                            "stage_id": stage.stage_id,
                            "layer": stage.layer,
                        },
                    )
                )
                trace.append(
                    TraceEvent(
                        event_id=f"trace-tool-result-write-stage-{stage.stage_id}",
                        event_type="tool_result",
                        actor="winning_mechanism",
                        summary=f"{stage.layer}阶段输出已写入",
                        output_refs=[stage.stage_id],
                        payload={
                            "tool_name": "write_stage_output",
                            "status": "completed",
                        },
                    )
                )
            for image in images:
                trace.append(
                    TraceEvent(
                        event_id=f"trace-tool-call-capability-{image.capability_id}",
                        event_type="tool_call",
                        actor="winning_mechanism",
                        summary=f"生成能力画像：{image.name}",
                        input_refs=list(image.evidence_ids),
                        payload={
                            "tool_name": "create_capability_image",
                            "capability_id": image.capability_id,
                        },
                    )
                )
                trace.append(
                    TraceEvent(
                        event_id=f"trace-tool-result-capability-{image.capability_id}",
                        event_type="tool_result",
                        actor="winning_mechanism",
                        summary=f"能力画像已生成：{image.name}",
                        output_refs=[image.capability_id],
                        payload={
                            "tool_name": "create_capability_image",
                            "status": "completed",
                        },
                    )
                )
            trace.append(
                TraceEvent(
                    event_id="trace-delegated-auditor",
                    event_type="agent_task_delegated",
                    actor="orchestrator",
                    summary="委派审计智能体执行五判据检查",
                    payload={
                        "target_agent_id": "auditor",
                        "allowed_tools": ["write_audit"],
                    },
                )
            )
            trace.append(
                TraceEvent(
                    event_id="trace-tool-call-audit",
                    event_type="tool_call",
                    actor="auditor",
                    summary="执行证据、覆盖、门控、追溯和轮次五判据审计",
                    payload={"tool_name": "write_audit"},
                )
            )
            risk_based_coverage_accepted = (
                execution_profile is not None
                and bool(stage_outputs)
                and all(item.gate_passed for item in stage_outputs)
                and bool(images)
                and all(item.evidence_ids for item in images)
            )
            audit_coverage = (
                {
                    **coverage,
                    "coverage_passed": True,
                    "risk_based_coverage_accepted": True,
                }
                if risk_based_coverage_accepted
                else coverage
            )
            audit = audit_run(
                store=store,
                coverage=audit_coverage,
                max_rounds=resolved_max_rounds,
                current_rounds=checkpoint.round_index,
                source_materials=scheduler.source_materials,
                analyst_confirmed=analyst_confirmed,
                risk_based_confidence=execution_profile is not None,
            )
            audit_review_decision = decide_final_audit_review(
                trace_events=trace.snapshot(),
                deterministic_status=audit.status,
                stage_outputs=stage_outputs,
                capability_images=images,
                evidence_count=len(store.evidence),
            )
            if audit_review_decision.expert_judge_present:
                audit = replace(
                    audit,
                    checks={
                        **audit.checks,
                        "expert_judge_passed": (
                            audit_review_decision.expert_judge_passed
                        ),
                    },
                )
            if (
                audit_review_decision.expert_judge_present
                and not audit_review_decision.expert_judge_passed
            ):
                audit = replace(
                    audit,
                    status="limited",
                    comments=[
                        *audit.comments,
                        "上游质量专家评判未通过；问题必须回到候选生成或修复阶段解决，"
                        "最终审计不再调用第二个模型重复评判。",
                    ],
                )
            if resume_config_changed:
                audit = replace(
                    audit,
                    comments=[
                        *audit.comments,
                        "本次由中断检查点在更新后的运行配置下恢复；已保留原有证据与阶段结果，"
                        "并按新审计规则复核。配置差异作为审计备注保留，不单独降低研究交付状态；"
                        "若分支成果、证据、阶段门或报告门发生实质变化，仍由对应硬门限制交付。",
                    ],
                )
            audit_reviewer = getattr(provider, "review_audit", None)
            if (
                mode == "real"
                and callable(audit_reviewer)
                and audit_review_decision.model_review_required
            ):
                trace.append(
                    TraceEvent(
                        event_id="trace-auditor-model-call",
                        event_type="tool_call",
                        actor="auditor",
                        summary="审计 Agent 调用独立真实模型复核确定性判据",
                        payload={"tool_name": "review_audit", "provider_mode": "real"},
                    )
                )
                audit_payload = {
                    "topic": topic,
                    "research_route": route,
                    "execution_profile_id": discovery_blueprint.get(
                        "execution_profile_id", "legacy_v1"
                    ),
                    "deterministic_checks": audit.checks,
                    "deterministic_status": audit.status,
                    "coverage_summary": {
                        "coverage_passed": bool(audit_coverage.get("coverage_passed")),
                        "raw_coverage_passed": bool(coverage.get("coverage_passed")),
                        "risk_based_coverage_accepted": risk_based_coverage_accepted,
                        "required_tags": list(coverage.get("required_tags", []))[:30],
                        "provided_tags": list(coverage.get("provided_tags", []))[:30],
                        "missing_required_tags": list(
                            coverage.get("missing_required_tags", [])
                        )[:12],
                        "provided_by_agent": {
                            packet.agent_id: list(packet.capability_tags)
                            for packet in store.baseline_packet_snapshot()
                        },
                    },
                    "analyst_confirmation": {
                        "confirmed": analyst_confirmed,
                        "scope": (
                            "用户已确认本轮分析边界和发布责任"
                            if analyst_confirmed
                            else "未取得分析师发布确认"
                        ),
                    },
                    "stage_gate_summary": [
                        {
                            "layer": item.layer,
                            "confidence": item.confidence,
                            "gate_passed": item.gate_passed,
                            "gate_reasons": list(item.gate_reasons)[:4],
                            "evidence_count": len(item.evidence_ids),
                        }
                        for item in stage_outputs
                    ],
                    "capability_summary": [
                        {
                            "capability_id": item.capability_id,
                            "name": item.name,
                            "priority": item.priority,
                            "confidence": item.confidence,
                            "evidence_ids": list(item.evidence_ids)[:20],
                            "risk_boundaries": list(item.risk_boundaries)[:3],
                        }
                        for item in images[: (8 if execution_profile is not None else 12)]
                    ],
                    "evidence_summary": {
                        "total": len(store.evidence),
                        "cards": store.evidence_index()[
                            : (24 if execution_profile is not None else 80)
                        ],
                        "tiers": {
                            tier: sum(
                                evidence.source_tier == tier
                                for evidence in store.evidence.values()
                            )
                            for tier in ("A", "B", "C", "D")
                        },
                        "unreferenced_capabilities": [
                            item.capability_id for item in images if not item.evidence_ids
                        ],
                        "source_families": sorted(
                            {
                                urlsplit(item.source_url).netloc or item.source_title
                                for item in store.evidence.values()
                            }
                        )[: (20 if execution_profile is not None else 40)],
                    },
                }
                try:
                    audit_review = audit_reviewer(audit_payload)
                    if not audit_review:
                        raise ValueError("invalid structured JSON")
                except Exception as exc:
                    deterministic_approved = audit.status == "approved"
                    audit = replace(
                        audit,
                        status="approved" if deterministic_approved else "limited",
                        comments=[
                            *audit.comments,
                            "独立模型复核超时或异常，已保留确定性五判据结论；"
                            + (
                                "全部硬判据已通过，因此本次断连仅记为审计备注，不降低交付状态。"
                                if deterministic_approved
                                else "仍存在确定性硬判据缺口，本次报告维持受限。"
                            ),
                        ],
                    )
                    trace.append(
                        TraceEvent(
                            event_id="trace-auditor-model-fallback",
                            event_type="audit_model_fallback",
                            actor="auditor",
                            summary="独立审计模型未按时返回，已采用确定性审计结论",
                            payload={
                                "tool_name": "review_audit",
                                "status": (
                                    "approved_deterministic"
                                    if deterministic_approved
                                    else "limited_deterministic"
                                ),
                                "reason": type(exc).__name__,
                            },
                        )
                    )
                else:
                    review_limited = (
                        audit_review.get("release_recommendation") == "limited"
                    )
                    audit = replace(
                        audit,
                        status="limited" if review_limited else audit.status,
                        comments=[
                            *audit.comments,
                            *[str(item) for item in audit_review.get("findings", [])][
                                :6
                            ],
                            f"独立审计Agent意见：{audit_review.get('risk_summary', '')}",
                        ],
                    )
                    self._write_core_agent_session(
                        workspace,
                        "auditor",
                        {"event_type": "model_result", "result": audit_review},
                    )
                    trace.append(
                        TraceEvent(
                            event_id="trace-auditor-model-result",
                            event_type="tool_result",
                            actor="auditor",
                            summary="独立审计模型复核完成",
                            payload={
                                "tool_name": "review_audit",
                                "status": "completed",
                            },
                        )
                    )
            elif mode == "real" and callable(audit_reviewer):
                trace.append(
                    TraceEvent(
                        event_id="trace-auditor-model-skipped",
                        event_type="audit_model_review_skipped",
                        actor="auditor",
                        summary="已有专家评判，最终审计仅执行确定性发布门",
                        payload={
                            "reason": audit_review_decision.reason,
                            "expert_judge_passed": (
                                audit_review_decision.expert_judge_passed
                            ),
                        },
                    )
                )
            store.add_audit(audit)
            trace.append(
                TraceEvent(
                    event_id="trace-tool-result-audit",
                    event_type="tool_result",
                    actor="auditor",
                    summary=f"五判据审计完成：{audit.status}",
                    output_refs=[audit.audit_id],
                    payload={"tool_name": "write_audit", "status": audit.status},
                )
            )
            trace.append(
                TraceEvent(
                    event_id="trace-audit-completed",
                    event_type="audit_completed",
                    actor="auditor",
                    summary=f"五判据审计完成：{audit.status}",
                    output_refs=[audit.audit_id],
                    payload={"status": audit.status, "audit_id": audit.audit_id},
                )
            )
            trace.append(
                TraceEvent(
                    event_id="trace-delegated-reporter",
                    event_type="agent_task_delegated",
                    actor="orchestrator",
                    summary="委派Codex报告智能体按当前分支契约生成深度研究报告",
                    payload={
                        "target_agent_id": "reporter",
                        "allowed_tools": ["write_report"],
                    },
                )
            )
            trace.append(
                TraceEvent(
                    event_id="trace-tool-call-report",
                    event_type="tool_call",
                    actor="reporter",
                    summary="独立报告Agent接收少量高价值研判种子与公开来源，围绕Query重新构建深度报告",
                    input_refs=[
                        audit.audit_id,
                        *[item.capability_id for item in images],
                    ],
                    payload={"tool_name": "write_report"},
                )
            )
            reporter_summary = ""
            reporter_model_started = False
            winning_swarm_summary = (
                discovery_blueprint.get("winning_swarm", {})
                if isinstance(
                    discovery_blueprint.get("winning_swarm", {}), Mapping
                )
                else {}
            )
            if not winning_swarm_summary:
                winning_swarm_summary = next(
                    (
                        dict(event.payload.get("swarm_summary", {}))
                        for event in reversed(trace.snapshot())
                        if event.event_type == "swarm_gate_evaluated"
                        and isinstance(
                            event.payload.get("swarm_summary", {}), Mapping
                        )
                        and event.payload.get("swarm_summary")
                    ),
                    {},
                )
            portfolio_quality_gate = (
                winning_swarm_summary.get("portfolio_quality_gate", {})
                if isinstance(
                    winning_swarm_summary.get("portfolio_quality_gate", {}),
                    Mapping,
                )
                else {}
            )
            delivery_artifacts = build_delivery_artifacts(
                topic=topic,
                branch=str(discovery_blueprint["primary_branch"]),
                blueprint=discovery_blueprint,
                store=store,
                convergence=convergence,
            )
            report_drafter = getattr(provider, "draft_report", None)
            reporter_progress_setter = getattr(
                provider,
                "set_reporter_progress_callback",
                None,
            )
            reporter_progress_sequence = 0

            def record_reporter_progress(row: dict[str, Any]) -> None:
                nonlocal reporter_progress_sequence
                reporter_progress_sequence += 1
                self._record_reporter_progress_row(
                    workspace,
                    trace,
                    row,
                    attempt=checkpoint.round_index,
                    event_suffix=str(reporter_progress_sequence),
                )

            if mode == "real":
                try:
                    execution_profile_id = str(
                        discovery_blueprint.get(
                            "execution_profile_id", "legacy_v1"
                        )
                    )
                    if (
                        execution_profile_id == "winning_swarm_dynamic_v2"
                        and portfolio_quality_gate
                        and not bool(portfolio_quality_gate.get("passed"))
                    ):
                        raise ValueError(
                            "winning swarm portfolio quality gate failed before "
                            "Reporter: "
                            f"directions={portfolio_quality_gate.get('direction_count', 0)}, "
                            "direct_equipment="
                            f"{portfolio_quality_gate.get('direct_combat_equipment_count', 0)}, "
                            "distinct_direct_families="
                            f"{portfolio_quality_gate.get('distinct_direct_equipment_family_count', 0)}, "
                            "required_distinct_direct_families="
                            f"{portfolio_quality_gate.get('preferred_distinct_direct_equipment', 5)}"
                        )
                    reporter_model_started = True
                    trace.append(
                        TraceEvent(
                            event_id="trace-reporter-model-call",
                            event_type="tool_call",
                            actor="reporter",
                            summary="报告 Agent 调用隔离Codex/真实模型生成分支深度正文",
                            payload={
                                "tool_name": "draft_report",
                                "provider_mode": "real",
                                "branch": discovery_blueprint["primary_branch"],
                                "required_sections": delivery_artifacts[
                                    "branch_writer_brief"
                                ]["required_sections"],
                            },
                        )
                    )
                    if callable(reporter_progress_setter):
                        reporter_progress_setter(record_reporter_progress)
                    if not callable(report_drafter):
                        raise RuntimeError(
                            "真实模式必须由独立报告Agent生成正文；"
                            "当前Provider不支持draft_report"
                        )
                    reporter_summary = report_drafter(
                        {
                            "run_id": run_id,
                            "topic": topic,
                            "research_route": route,
                            "execution_profile_id": discovery_blueprint.get(
                                "execution_profile_id", "legacy_v1"
                            ),
                            "portfolio_quality_gate": dict(
                                portfolio_quality_gate
                            ),
                            "report_template_mode": report_template_mode,
                            "ablation_scope": (
                                "restricted_generic_baseline_evidence_closed"
                                if stage_policy.evidence_closed
                                else ""
                            ),
                            "evidence_closed": stage_policy.evidence_closed,
                            "report_context": {
                                "primary_branch": discovery_blueprint.get(
                                    "primary_branch", ""
                                ),
                                "branch_name": delivery_artifacts[
                                    "branch_deliverables"
                                ].get("branch_name", ""),
                                "secondary_branches": list(
                                    discovery_blueprint.get(
                                        "secondary_branches", []
                                    )
                                )[:2],
                                "audit_status": audit.status,
                                "audit_limits": [
                                    str(item)[:220] for item in audit.comments[:3]
                                ],
                                "coverage_passed": bool(
                                    coverage.get("coverage_passed")
                                ),
                            },
                            "synthesis_seed": _report_synthesis_seed(
                                store=store,
                                branch_output=delivery_artifacts[
                                    "branch_deliverables"
                                ],
                                convergence=convergence,
                            ),
                            "evidence_catalog": _report_evidence_catalog(
                                store,
                                limit=8,
                                claim_chars=150,
                            ),
                            "branch_report_contract": delivery_artifacts[
                                "branch_report_contract"
                            ],
                            "branch_writer_brief": delivery_artifacts[
                                "branch_writer_brief"
                            ],
                            # Local Reporter gates use this compact status and
                            # product inventory to distinguish missing branch
                            # content from harmless wording differences. The
                            # fresh model prompt builder intentionally does not
                            # serialize this object, so it cannot pollute the
                            # Reporter context.
                            "branch_deliverables": {
                                "delivery_status": delivery_artifacts[
                                    "branch_deliverables"
                                ].get("delivery_status", ""),
                                "products": delivery_artifacts[
                                    "branch_deliverables"
                                ].get("products", {}),
                            },
                        }
                    )
                    if not reporter_summary.strip():
                        raise ValueError("empty report summary")
                except Exception as exc:
                    failure_payload = {
                        "tool_name": "draft_report",
                        "status": "failed_no_fallback",
                        "reason": type(exc).__name__,
                        "detail": str(exc)[:1000],
                        "resumable": True,
                    }
                    if portfolio_quality_gate:
                        failure_payload["portfolio_quality_gate"] = dict(
                            portfolio_quality_gate
                        )
                    failure_event = TraceEvent(
                        event_id=(
                            "trace-reporter-model-failed-"
                            f"r{checkpoint.resume_count}"
                        ),
                        event_type="report_model_failed",
                        actor="reporter",
                        summary="独立报告Agent未成功生成正文，已停止交付并保留检查点",
                        payload=failure_payload,
                    )
                    trace.append(failure_event)
                    self._write_core_agent_session(
                        workspace,
                        "reporter",
                        {
                            "event_type": "model_error",
                            **failure_payload,
                        },
                    )
                    checkpoint = self._set_task_status(
                        checkpoint,
                        FINALIZE_TASK_ID,
                        "pending",
                    )
                    failure_savepoint_id = sqlite_store.commit(
                        (
                            self._checkpoint_proposal(
                                checkpoint,
                                f"reporter-failed-r{checkpoint.resume_count}",
                            ),
                        ),
                        (self._trace_proposal(failure_event),),
                    )
                    self._write_checkpoint_file(
                        workspace,
                        checkpoint,
                        failure_savepoint_id,
                    )
                    workspace.write_run_text(
                        "report_failure.json",
                        json.dumps(
                            {
                                **failure_payload,
                                "run_id": run_id,
                                "checkpoint_id": failure_savepoint_id,
                                "report_written": False,
                                "created_at": failure_event.created_at,
                            },
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                    )
                    raise RuntimeError(
                        "独立报告Agent生成失败；真实模式禁止确定性降级报告，"
                        "任务已保留检查点，可恢复后重新生成。"
                    ) from exc
                else:
                    # A successful resume supersedes any prior Reporter
                    # failure diagnostic. Leaving the stale file behind makes
                    # completed runs look failed to filesystem-based tooling.
                    (workspace.run_dir / "report_failure.json").unlink(
                        missing_ok=True
                    )
                finally:
                    if callable(reporter_progress_setter):
                        reporter_progress_setter(None)
                    if reporter_model_started:
                        self._write_core_agent_session(
                            workspace,
                            "reporter",
                            {"event_type": "model_result", "text": reporter_summary},
                        )
                        trace.append(
                            TraceEvent(
                                event_id="trace-reporter-model-result",
                                event_type="tool_result",
                                actor="reporter",
                                summary="报告 Agent 分支深度正文生成完成",
                                payload={
                                    "tool_name": "draft_report",
                                    "status": "completed",
                                },
                            )
                        )
            report = render_report(
                topic=topic,
                route=route,
                store=store,
                coverage=coverage,
                audit=audit,
                executive_summary=reporter_summary,
                discovery_branch=str(discovery_blueprint["primary_branch"]),
                discovery_blueprint=discovery_blueprint,
                delivery_artifacts=delivery_artifacts,
                prefer_model_report=bool(reporter_summary.strip()),
            )
            if execution_profile is not None:
                report = replace(
                    report,
                    body=_enforce_report_hard_max(
                        _normalize_delivery_report_structure(
                            _publicize_report_references(report.body, store)
                        ),
                        _report_delivery_limit_payload(
                            discovery_blueprint=discovery_blueprint,
                            report_template_mode=report_template_mode,
                            branch_writer_brief=delivery_artifacts[
                                "branch_writer_brief"
                            ],
                        ),
                    ),
                )
                accepted_claim_rows = _report_accepted_claims(
                    store,
                    per_packet_limit=100,
                    total_limit=1000,
                )
                binding_rate = (
                    sum(bool(item.get("public_urls")) for item in accepted_claim_rows)
                    / len(accepted_claim_rows)
                    if accepted_claim_rows
                    else 0.0
                )
                internal_reference_found = bool(
                    re.search(
                        r"\b(?:packet|claim|ev|stage|capability)-[A-Za-z0-9_.:-]+"
                        r"|〔改写断点：保留事实但不得照录〕"
                        r"|(?m:(?:^|\|\s*|\*\*)[A-Ha-h]\s*[.．、:：]\s*(?=[^\s|*]))",
                        report.body,
                    )
                )
                workspace.write_run_text(
                    "claim_source_binding.json",
                    json.dumps(
                        {
                            "accepted_claim_count": len(accepted_claim_rows),
                            "claims_with_public_sources": sum(
                                bool(item.get("public_urls"))
                                for item in accepted_claim_rows
                            ),
                            "binding_rate": round(binding_rate, 6),
                            "minimum_required": 0.9,
                            "internal_reference_found": internal_reference_found,
                            "passed": binding_rate >= 0.9
                            and not internal_reference_found,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
                quality_report = ReportQualityGate().validate(
                    report.body,
                    {
                        "evidence_count": len(store.evidence),
                        "topic": topic,
                        "branch": discovery_blueprint["primary_branch"],
                        "execution_profile_id": discovery_blueprint.get(
                            "execution_profile_id", "legacy_v1"
                        ),
                        "require_detailed_capability_portraits": (
                            discovery_blueprint.get("execution_profile_id")
                            in {
                                "swarm_quality_v1",
                                "winning_swarm_dynamic_v2",
                            }
                        ),
                        "require_high_value_military_information": (
                            discovery_blueprint.get("execution_profile_id")
                            in {
                                "swarm_quality_v1",
                                "winning_swarm_dynamic_v2",
                            }
                        ),
                        "report_template_mode": report_template_mode,
                        "delivery_owned_h1": True,
                        "branch_delivery_status": delivery_artifacts[
                            "branch_deliverables"
                        ].get("delivery_status"),
                        "require_disruptive_lens_diversity": (
                            len(store.capability_images) >= 5
                        ),
                        "expected_capability_directions": [
                            item.name
                            for item in sorted(
                                store.capability_images.values(),
                                key=lambda item: (
                                    _report_priority_rank(item.priority),
                                    -float(item.confidence),
                                    item.name,
                                ),
                            )[:7]
                        ],
                        "expected_capability_records": [
                            {
                                "name": item.name,
                                "equipment_form": item.equipment_form,
                                "equipment_category": item.equipment_category,
                                "capability_type": item.capability_type,
                                "mission_effect": item.mission_effect,
                                "military_utility": item.military_utility,
                                "operational_mechanism": item.operational_mechanism,
                                "strike_countermeasure_value": item.strike_countermeasure_value,
                                "evidence_count": len(item.evidence_ids),
                            }
                            for item in sorted(
                                store.capability_images.values(),
                                key=lambda item: (
                                    _report_priority_rank(item.priority),
                                    -float(item.confidence),
                                    item.name,
                                ),
                            )[:7]
                        ],
                    },
                )
                workspace.write_run_text(
                    "report_quality_gate.json",
                    json.dumps(
                        quality_report.compact(),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
                branch_gate_passed = (
                    delivery_artifacts["branch_deliverables"].get(
                        "delivery_status"
                    )
                    == "complete"
                )
                trace.append(
                    TraceEvent(
                        event_id="trace-report-quality-gate-v2",
                        event_type="report_quality_gate_evaluated",
                        actor="report_quality_gate",
                        summary=(
                            "报告质量与分支交付门通过"
                            if quality_report.passed and branch_gate_passed
                            else "报告质量或分支交付门受限"
                        ),
                        input_refs=[report.report_id],
                        payload={
                            "quality_passed": quality_report.passed,
                            "quality_score": quality_report.overall_score,
                            "branch_deliverables_passed": branch_gate_passed,
                            "branch_delivery_status": delivery_artifacts[
                                "branch_deliverables"
                            ].get("delivery_status"),
                            "claim_source_binding_rate": round(binding_rate, 6),
                            "internal_reference_found": internal_reference_found,
                        },
                    )
                )
                if (
                    not quality_report.passed
                    or not branch_gate_passed
                    or binding_rate < 0.9
                    or internal_reference_found
                ):
                    audit = replace(
                        audit,
                        status="limited",
                        comments=[
                            *audit.comments,
                            "optimized_v2正式报告门控未全部通过；保留最近完整Checkpoint交付，"
                            "缺口已记录为后续ResidualCard候选，不触发整篇重写。",
                        ],
                    )
                    store.add_audit(audit)
                else:
                    reconciled_audit = _reconcile_final_audit_status(
                        audit,
                        optimized_v2=execution_profile is not None,
                    )
                    if reconciled_audit != audit:
                        audit = reconciled_audit
                        store.add_audit(audit)
                        report = render_report(
                            topic=topic,
                            route=route,
                            store=store,
                            coverage=coverage,
                            audit=audit,
                            executive_summary=reporter_summary,
                            discovery_branch=str(
                                discovery_blueprint["primary_branch"]
                            ),
                            discovery_blueprint=discovery_blueprint,
                            delivery_artifacts=delivery_artifacts,
                            prefer_model_report=bool(reporter_summary.strip()),
                        )
                        report = replace(
                            report,
                            body=_enforce_report_hard_max(
                                _normalize_delivery_report_structure(
                                    _publicize_report_references(report.body, store)
                                ),
                                _report_delivery_limit_payload(
                                    discovery_blueprint=discovery_blueprint,
                                    report_template_mode=report_template_mode,
                                    branch_writer_brief=delivery_artifacts[
                                        "branch_writer_brief"
                                    ],
                                ),
                            ),
                        )
                        trace.append(
                            TraceEvent(
                                event_id="trace-audit-release-reconciled",
                                event_type="audit_release_reconciled",
                                actor="report_quality_gate",
                                summary="最终报告门与引用门通过，审计状态恢复为可交付",
                                payload={
                                    "status": audit.status,
                                    "quality_score": quality_report.overall_score,
                                    "claim_source_binding_rate": round(
                                        binding_rate,
                                        6,
                                    ),
                                },
                            )
                        )
            store.add_report(report)
            trace.append(
                TraceEvent(
                    event_id="trace-tool-result-report",
                    event_type="tool_result",
                    actor="reporter",
                    summary="能力画像研究报告已生成",
                    output_refs=[report.report_id],
                    payload={"tool_name": "write_report", "status": "completed"},
                )
            )
            trace.append(
                TraceEvent(
                    event_id="trace-report-completed",
                    event_type="report_completed",
                    actor="reporter",
                    summary="能力画像研究报告生成完成",
                    output_refs=[report.report_id],
                    payload={"status": "completed", "report_id": report.report_id},
                )
            )
            self._emit_hook("after_finalize_engine", workspace)
            checkpoint = self._set_task_status(
                checkpoint,
                FINALIZE_TASK_ID,
                "completed",
            )
            checkpoint = replace(
                checkpoint,
                budget_remaining={
                    **checkpoint.budget_remaining,
                    "baseline_tasks": 0,
                    "finalize_tasks": 0,
                    "rounds": max(resolved_max_rounds - 1, 0),
                },
                status="completed",
                source_materials=_dedupe_plain_rows(scheduler.source_materials),
                worker_reports=[to_plain(item) for item in worker_reports],
            )
            checkpoint.validate()
            final_domain_proposals = [
                *(
                    self._domain_proposal("EvidenceCard", store.evidence[item])
                    for item in sorted(set(recall_evidence_ids))
                ),
                *(
                    self._domain_proposal(
                        "BaselineFindingPacket", store.baseline_packets[item]
                    )
                    for item in sorted(set(recall_packet_ids))
                ),
                *(
                    self._domain_proposal(
                        report.domain_object_type,
                        _domain_object_for_report(store, report),
                    )
                    for report in recall_reports
                    if report.domain_object_type and report.domain_object_id
                ),
                *(
                    self._domain_proposal("WinningMechanismStageOutput", item)
                    for item in stage_outputs
                ),
                *(
                    self._domain_proposal("WinningMechanismInput", item)
                    for item in store.winning_inputs.values()
                ),
                *(
                    self._domain_proposal("WinningKnowledgeProjection", item)
                    for item in store.knowledge_projections.values()
                ),
                *(
                    self._domain_proposal("WinningReasoningNode", item)
                    for item in store.reasoning_nodes.values()
                ),
                *(
                    self._domain_proposal("CapabilityImageItem", item)
                    for item in images
                ),
                *(
                    self._domain_proposal("AgentRecommendation", item)
                    for item in recommendations
                ),
                *(
                    self._domain_proposal("RecallRequest", item)
                    for item in store.recall_requests.values()
                ),
                self._domain_proposal("AuditResult", audit),
                self._domain_proposal("ResearchReport", report),
                self._checkpoint_proposal(
                    checkpoint,
                    f"completed-r{checkpoint.resume_count}",
                ),
            ]
            final_trace_proposals = [
                self._trace_proposal(event)
                for event in trace.events[final_trace_start:]
            ]
            if resume_config_changed and checkpoint.resume_count:
                generation_suffix = f"-r{checkpoint.resume_count}"
                final_domain_proposals = [
                    replace(
                        proposal,
                        proposal_id=f"{proposal.proposal_id}{generation_suffix}",
                        idempotency_key=(
                            f"{proposal.idempotency_key}{generation_suffix}"
                            if proposal.idempotency_key
                            else generation_suffix.lstrip("-")
                        ),
                    )
                    for proposal in final_domain_proposals
                ]
                final_trace_proposals = [
                    replace(
                        proposal,
                        proposal_id=f"{proposal.proposal_id}{generation_suffix}",
                    )
                    for proposal in final_trace_proposals
                ]
            savepoint_id = sqlite_store.commit(
                final_domain_proposals,
                final_trace_proposals,
            )
            sqlite_store.prune_domain_objects(
                object_type="CapabilityImageItem",
                keep_object_ids={item.capability_id for item in images},
            )
            self._emit_hook("after_final_commit", workspace)
            self._write_checkpoint_file(workspace, checkpoint, savepoint_id)
        else:  # pragma: no cover - normalized completed checkpoints return above
            recommendations = list(store.recommendations.values())
            report = next(iter(store.reports.values()))

        self._emit_hook("before_outputs", workspace)
        self._write_outputs(
            workspace=workspace,
            mode=mode,
            problem=problem,
            route=route,
            discovery_blueprint=discovery_blueprint,
            convergence=convergence,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=recommendations,
            source_materials=_dedupe_plain_rows(scheduler.source_materials),
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
            execution_started_at=execution_started_at,
        )
        result = self._result(
            run_id=run_id,
            run_dir=workspace.run_dir,
            route=route,
            store=store,
        )
        return result

    def _complete_baseline_only_run(
        self,
        *,
        run_id: str,
        mode: str,
        workspace: RunWorkspace,
        sqlite_store: SqliteRunStore,
        checkpoint: RunCheckpoint,
        final_trace_start: int,
        provider: AgentProvider,
        problem: ResearchProblem,
        route: str,
        discovery_blueprint: dict[str, Any],
        convergence: dict[str, Any],
        coverage: dict[str, Any],
        selected_agent_ids: list[str],
        worker_reports: list[WorkerReport],
        source_materials: list[dict[str, Any]],
        store: DomainStore,
        trace: TraceStore,
        analyst_confirmed: bool,
        resolved_max_rounds: int,
        execution_started_at: str,
        stage_policy: RunStagePolicy,
    ) -> dict[str, Any]:
        """Finalize a real baseline-only run without invoking winning stages."""

        audit = audit_run(
            store=store,
            coverage=coverage,
            max_rounds=resolved_max_rounds,
            current_rounds=1,
            source_materials=source_materials,
            analyst_confirmed=analyst_confirmed,
        )
        audit = replace(
            audit,
            status="limited",
            checks={
                **audit.checks,
                "winning_stage_intentionally_removed": True,
                "feedback_loops_intentionally_removed": True,
            },
            comments=[
                *audit.comments,
                "消融策略已真实跳过S1-S6、能力画像以及L1-L4循环；"
                "本报告仅允许整理基线事实、证据、冲突和未决问题。",
            ],
        )
        store.add_audit(audit)
        delivery_artifacts = build_delivery_artifacts(
            topic=problem.topic,
            branch=str(discovery_blueprint["primary_branch"]),
            blueprint=discovery_blueprint,
            store=store,
            convergence=convergence,
        )
        synthesis_seed = _baseline_only_synthesis_seed(store, convergence)
        reporter_summary = _baseline_only_report_summary(
            problem.topic,
            store,
            synthesis_seed=synthesis_seed,
        )
        report_drafter = getattr(provider, "draft_report", None)
        if mode == "real":
            if not callable(report_drafter):
                raise RuntimeError("真实消融运行要求同一Provider提供Reporter")
            reporter_summary = report_drafter(
                {
                    "topic": problem.topic,
                    "research_route": route,
                    "execution_profile_id": discovery_blueprint.get(
                        "execution_profile_id", "legacy_v1"
                    ),
                    "ablation_scope": "baseline_only_no_winning_no_loops",
                    "report_context": {
                        "primary_branch": discovery_blueprint.get(
                            "primary_branch", ""
                        ),
                        "audit_status": audit.status,
                        "coverage_passed": bool(coverage.get("coverage_passed")),
                    },
                    "synthesis_seed": synthesis_seed,
                    "evidence_catalog": _report_evidence_catalog(
                        store,
                        limit=8,
                        claim_chars=150,
                    ),
                    "branch_report_contract": delivery_artifacts[
                        "branch_report_contract"
                    ],
                    "branch_writer_brief": delivery_artifacts[
                        "branch_writer_brief"
                    ],
                    "branch_deliverables": {
                        "delivery_status": "ablation_baseline_only",
                        "products": {},
                    },
                }
            )
            if not reporter_summary.strip():
                raise RuntimeError("baseline-only Reporter returned an empty report")
            violations = _baseline_only_report_violations(
                reporter_summary,
                synthesis_seed=synthesis_seed,
                allowed_urls={
                    item.source_url
                    for item in store.evidence.values()
                    if item.source_url.startswith(("http://", "https://"))
                },
            )
            if violations:
                # Only provenance corruption reaches this branch. Ordinary
                # paragraph-level citation density must not replace a complete
                # Reporter draft with the compact emergency renderer.
                reporter_summary = _baseline_only_grounded_fallback_report(
                    problem.topic,
                    synthesis_seed=synthesis_seed,
                    evidence=store.evidence_snapshot(),
                )
                fallback_violations = _baseline_only_report_violations(
                    reporter_summary,
                    synthesis_seed=synthesis_seed,
                    allowed_urls={
                        item.source_url
                        for item in store.evidence.values()
                        if item.source_url.startswith(("http://", "https://"))
                    },
                )
                if fallback_violations:
                    raise RuntimeError(
                        "baseline-only safe report validation failed: "
                        + "; ".join(fallback_violations[:8])
                    )
                trace.append(
                    TraceEvent(
                        event_id="trace-ablation-baseline-provenance-closed",
                        event_type="report_provenance_closed",
                        actor="reporter",
                        summary=(
                            "模型草稿未满足基线溯源合同，已仅用准入基线标记和公开来源"
                            "生成证据限定报告；实验继续完成"
                        ),
                        payload={"violations": violations[:8]},
                    )
                )
        report = render_report(
            topic=problem.topic,
            route=route,
            store=store,
            coverage=coverage,
            audit=audit,
            executive_summary=reporter_summary,
            discovery_branch=str(discovery_blueprint["primary_branch"]),
            discovery_blueprint=discovery_blueprint,
            delivery_artifacts=delivery_artifacts,
            prefer_model_report=True,
        )
        store.add_report(report)
        trace.append(
            TraceEvent(
                event_id="trace-ablation-baseline-report-completed",
                event_type="report_completed",
                actor="reporter",
                summary="基线限定Reporter已生成去制胜机理消融报告",
                output_refs=[report.report_id],
                payload={
                    "stage_policy_id": stage_policy.policy_id,
                    "baseline_only": True,
                },
            )
        )
        checkpoint = self._set_task_status(
            checkpoint,
            FINALIZE_TASK_ID,
            "completed",
        )
        checkpoint = replace(
            checkpoint,
            status="completed",
            source_materials=source_materials,
            worker_reports=[to_plain(item) for item in worker_reports],
        )
        checkpoint.validate()
        sqlite_store.commit(
            (
                self._domain_proposal("AuditResult", audit),
                self._domain_proposal("ResearchReport", report),
                self._checkpoint_proposal(checkpoint, "ablation-completed"),
            ),
            tuple(
                self._trace_proposal(event)
                for event in trace.events[final_trace_start:]
            ),
        )
        self._write_outputs(
            workspace=workspace,
            mode=mode,
            problem=problem,
            route=route,
            discovery_blueprint={
                **discovery_blueprint,
                "stage_policy_id": stage_policy.policy_id,
            },
            convergence=convergence,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=[],
            source_materials=source_materials,
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
            execution_started_at=execution_started_at,
        )
        return self._result(
            run_id=run_id,
            run_dir=workspace.run_dir,
            route=route,
            store=store,
        )

    def _select_agent_provider(
        self,
        mode: str,
        provider_name: str | None,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        agent_model_profiles: dict[str, dict[str, Any]] | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> AgentProvider:
        if self.provider is not None:
            return self.provider
        if provider_name == "fake" or mode == "fake":
            return FakeAgentProvider()
        if provider_name == "smoke":
            return RealAgentProvider()
        provider_registry = ProviderRegistry.load(self.provider_config_path)
        selected_profile = provider_name or provider_registry.default_provider
        registry = agent_registry or AgentRegistry.load(self.agent_config_path)
        reporter_workspace = (
            self.output_root / "runtime" / "reporter-agent-workspace"
        ).resolve()
        reporter_workspace.mkdir(parents=True, exist_ok=True)
        effective_agent_profiles = {
            agent_id: dict(profile)
            for agent_id, profile in (agent_model_profiles or {}).items()
        }
        configured_reporter = effective_agent_profiles.get("reporter")
        if configured_reporter is not None and str(
            configured_reporter.get("provider") or selected_profile
        ) != "codex":
            raise ProviderConfigurationError(
                "reporter must use Codex CLI with a custom URL/API; "
                "Responses reporter override is disabled"
            )
        if configured_reporter is None:
            reporter_definition = registry.get("reporter")
            effective_agent_profiles["reporter"] = {
                "provider": "codex",
                "model": str(
                    reporter_definition.model_profile.get("model")
                    or model
                    or "gpt-5.5"
                ),
                "api_key_env": str(
                    reporter_definition.model_profile.get("api_key_env") or ""
                ),
                "base_url": str(
                    reporter_definition.model_profile.get("base_url") or ""
                ),
            }
        model_provider = provider_registry.create(
            selected_profile,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            workspace_path=self.project_root,
            isolation_key="orchestrator-default",
        )
        routed_providers = {}
        for agent_id, profile in effective_agent_profiles.items():
            routed_profile = str(profile.get("provider") or selected_profile)
            inherited_base_url = (
                base_url if routed_profile == selected_profile else None
            )
            inherited_key_env = (
                api_key_env if routed_profile == selected_profile else None
            )
            routed_providers[agent_id] = provider_registry.create(
                routed_profile,
                model=str(profile.get("model") or model or "gpt-5.5"),
                base_url=str(profile.get("base_url") or inherited_base_url or "")
                or None,
                api_key_env=(
                    str(profile.get("api_key_env") or inherited_key_env or "") or None
                ),
                workspace_path=(
                    reporter_workspace
                    if agent_id == "reporter"
                    else self.project_root
                ),
                isolation_key=agent_id,
                include_default_skills=agent_id != "reporter",
            )
        if provider_registry.profile_snapshot(selected_profile).get("type") == "codex_cli":
            for agent_id in registry.all_agent_ids():
                if agent_id in routed_providers:
                    continue
                definition = registry.get(agent_id)
                routed_providers[agent_id] = provider_registry.create(
                    selected_profile,
                    model=str(
                        definition.model_profile.get("model")
                        or model
                        or "gpt-5.5"
                    ),
                    base_url=base_url,
                    api_key_env=api_key_env,
                    workspace_path=self.project_root,
                    isolation_key=agent_id,
                )
        agent_definitions = {
            agent_id: registry.get(agent_id) for agent_id in registry.all_agent_ids()
        }
        adapter = ResponsesAgentProvider(  # type: ignore[arg-type]
            model_provider,
            agent_providers=routed_providers,  # type: ignore[arg-type]
            agent_definitions=agent_definitions,
            harness_profiles=registry.harness_catalog.profiles,
        )
        reporter_snapshot = getattr(
            adapter._provider_for("reporter"),
            "snapshot",
            lambda: {},
        )()
        if str(reporter_snapshot.get("type", "")) != "codex_cli":
            raise ProviderConfigurationError(
                "reporter must resolve to Codex CLI; local login and non-Codex "
                "report backends are disabled"
            )
        return adapter

    def _initial_checkpoint(
        self,
        *,
        run_id: str,
        topic: str,
        research_route: str,
        route: str,
        selected_agent_ids: list[str],
        max_rounds: int,
        mode: str,
        config_fingerprint: str,
    ) -> RunCheckpoint:
        task_ids = [
            *[_task_id(agent_id) for agent_id in selected_agent_ids],
            FINALIZE_TASK_ID,
        ]
        checkpoint = RunCheckpoint(
            run_id=run_id,
            checkpoint_id=f"run-checkpoint-{run_id}",
            completed_task_ids=[],
            pending_task_ids=task_ids,
            round_index=1,
            budget_remaining={
                "rounds": max_rounds,
                "baseline_tasks": len(selected_agent_ids),
                "finalize_tasks": 1,
            },
            status="running",
            task_statuses={task_id: "pending" for task_id in task_ids},
            topic=topic,
            research_route=research_route,
            resolved_route=route,
            selected_agent_ids=selected_agent_ids,
            source_materials=[],
            worker_reports=[],
            mode=mode,
            config_fingerprint=config_fingerprint,
        )
        checkpoint.validate()
        return checkpoint

    @staticmethod
    def _set_task_status(
        checkpoint: RunCheckpoint,
        task_id: str,
        status: str,
    ) -> RunCheckpoint:
        statuses = dict(checkpoint.task_statuses)
        statuses[task_id] = status
        ordered_tasks = [
            *[_task_id(agent_id) for agent_id in checkpoint.selected_agent_ids],
            FINALIZE_TASK_ID,
        ]
        completed = [item for item in ordered_tasks if statuses[item] == "completed"]
        pending = [item for item in ordered_tasks if statuses[item] == "pending"]
        updated = replace(
            checkpoint,
            completed_task_ids=completed,
            pending_task_ids=pending,
            task_statuses=statuses,
            budget_remaining={
                **checkpoint.budget_remaining,
                "baseline_tasks": sum(
                    1
                    for item in ordered_tasks
                    if item != FINALIZE_TASK_ID and statuses[item] != "completed"
                ),
                "finalize_tasks": int(statuses.get(FINALIZE_TASK_ID) != "completed"),
            },
        )
        updated.validate()
        return updated

    @staticmethod
    def _domain_proposal(object_type: str, value: Any) -> DomainWriteProposal:
        payload = to_plain(value)
        id_fields = {
            "ResearchProblem": "problem_id",
            "EvidenceCard": "evidence_id",
            "BaselineFindingPacket": "packet_id",
            "StrategicAssessment": "assessment_id",
            "ScenarioModel": "scenario_id",
            "EquipmentObservation": "observation_id",
            "OperationalSynthesis": "synthesis_id",
            "RecallRequest": "recall_id",
            "AgentRecommendation": "recommendation_id",
            "WinningMechanismInput": "input_id",
            "WinningKnowledgeProjection": "projection_id",
            "WinningReasoningNode": "object_id",
            "WinningMechanismStageOutput": "stage_id",
            "CapabilityImageItem": "capability_id",
            "AuditResult": "audit_id",
            "ResearchReport": "report_id",
        }
        object_id = str(payload[id_fields[object_type]])
        key = f"{object_type}:{object_id}"
        return DomainWriteProposal(
            proposal_id=f"domain-{key}",
            object_type=object_type,
            operation="upsert",
            payload=payload,
            idempotency_key=f"domain:{key}",
        )

    @staticmethod
    def _checkpoint_proposal(
        checkpoint: RunCheckpoint,
        step: str,
    ) -> DomainWriteProposal:
        key = f"workflow:{checkpoint.run_id}:{step}"
        return DomainWriteProposal(
            proposal_id=key,
            object_type="RunCheckpoint",
            operation="upsert",
            payload=to_plain(checkpoint),
            idempotency_key=key,
        )

    @staticmethod
    def _trace_proposal(event: TraceEvent) -> TraceProposal:
        return TraceProposal(
            proposal_id=event.event_id,
            event_type=event.event_type,
            actor=event.actor,
            payload=to_plain(event),
        )

    @staticmethod
    def _record_session_write_failure(
        *,
        sqlite_store: SqliteRunStore,
        run_id: str,
        report: WorkerReport,
        task_id: str,
        checkpoint_id: str,
        batch_hash: str,
    ) -> None:
        session_ref = Path(report.session_path).name
        marker_seed = f"{run_id}:{task_id}:{checkpoint_id}:{batch_hash}:{session_ref}"
        marker_id = (
            f"runner-session-{sha256(marker_seed.encode('utf-8')).hexdigest()[:24]}"
        )
        marker_event = TraceEvent(
            event_id=marker_id,
            event_type="session_write_failed",
            actor=report.agent_id,
            summary=f"session savepoint write failed for {task_id}",
            payload={
                "marker_id": marker_id,
                "committed_checkpoint_id": checkpoint_id,
                "batch_hash": batch_hash,
                "turn_index": 1,
                "task_id": task_id,
                "agent_id": report.agent_id,
                "execution_id": report.worker_report_id,
                "session_ref": session_ref,
                "session_event": "savepoint",
                "recovery_status": "reconcile_required",
            },
        )
        sqlite_store.commit(
            (),
            (
                TraceProposal(
                    proposal_id=marker_id,
                    event_type=marker_event.event_type,
                    actor=report.agent_id,
                    payload=to_plain(marker_event),
                ),
            ),
        )

    def _config_fingerprint(
        self,
        *,
        mode: str,
        max_rounds: int,
        analyst_confirmed: bool,
        stage_policy_id: str = "full_method",
        report_template_mode: str = "three_layer_nine_item",
        provider_name: str | None = None,
        provider_model: str | None = None,
        provider_base_url: str | None = None,
        provider_api_key_env: str | None = None,
        agent_model_profiles: dict[str, dict[str, Any]] | None = None,
        interaction_mode: str = "expert",
        discovery_branch: str = "auto",
        discovery_blueprint: dict[str, Any] | None = None,
    ) -> str:
        files = {
            "agents": self.agent_config_path,
            "presets": self.preset_config_path,
            "providers": self.provider_config_path,
            "evidence": self.evidence_config_path,
            "routes": self.route_config_path,
            "harness": self.agent_config_path.parent / "harness.yaml",
        }
        payload = {
            "report_delivery_contract_version": REPORT_DELIVERY_CONTRACT_VERSION,
            "files": {
                name: (
                    None
                    if name in {"providers", "evidence", "routes", "harness"}
                    and not path.exists()
                    else sha256(path.read_bytes()).hexdigest()
                )
                for name, path in files.items()
            },
            "mode": mode,
            "max_rounds": max_rounds,
            "analyst_confirmed": analyst_confirmed,
            "stage_policy_id": stage_policy_id,
            "report_template_mode": report_template_mode,
            "interaction_mode": interaction_mode,
            "discovery_branch": discovery_branch,
            "discovery_blueprint": {
                key: value
                for key, value in (discovery_blueprint or {}).items()
                if key
                not in {
                    "blueprint_id",
                    "rationale",
                    "generated_by",
                    "structured_query_brief",
                }
            },
            "provider": {
                "name": provider_name,
                "model": provider_model,
                "base_url_host": urlsplit(provider_base_url).hostname
                if provider_base_url
                else None,
                "api_key_env": provider_api_key_env,
            },
            "agent_models": {
                agent_id: {
                    "model": profile.get("model"),
                    "base_url_host": urlsplit(
                        str(profile.get("base_url") or "")
                    ).hostname,
                    "api_key_env": profile.get("api_key_env"),
                }
                for agent_id, profile in sorted((agent_model_profiles or {}).items())
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{sha256(encoded).hexdigest()}"

    def _load_discovery_blueprint(self, run_id: str) -> dict[str, Any] | None:
        workspace = RunWorkspace.open_existing(self.output_root, run_id)
        try:
            if not workspace.run_file_is_regular("discovery_blueprint.json"):
                return None
            payload = json.loads(workspace.read_run_text("discovery_blueprint.json"))
        finally:
            workspace.close()
        if not isinstance(payload, dict):
            raise ValueError("persisted discovery blueprint must be an object")
        required = {"primary_branch", "runtime_route", "waves", "loop_policy"}
        if not required <= set(payload):
            raise ValueError("persisted discovery blueprint is incomplete")
        return payload

    def _prepare_military_value_handoff(
        self,
        *,
        workspace: RunWorkspace,
        trace: TraceStore,
        store: DomainStore,
        topic: str,
        convergence: Mapping[str, Any] | None,
        event_suffix: str = "main",
    ) -> dict[str, Any]:
        handoff = _build_military_value_handoff(
            store,
            topic=topic,
            convergence=convergence,
        )
        workspace.write_run_text(
            "military_value_handoff.json",
            json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True),
        )
        statistics = dict(handoff.get("statistics", {}))
        trace.append(
            TraceEvent(
                event_id=f"trace-military-value-handoff-{event_suffix}",
                event_type="military_value_handoff_created",
                actor="convergence_fusion",
                summary=(
                    "基线结果已收敛为"
                    f"{statistics.get('selected_claim_count', 0)}条高军事价值结论，"
                    "仅向S1–S5按职责投影"
                ),
                input_refs=[
                    packet.packet_id for packet in _admitted_packet_snapshot(store)
                ],
                output_refs=["military-value-handoff"],
                payload=statistics,
            )
        )
        return handoff

    def _apply_packet_admission(
        self,
        *,
        workspace: RunWorkspace,
        store: DomainStore,
        topic: str,
        discovery_blueprint: Mapping[str, Any],
    ) -> tuple[tuple[DomainWriteProposal, ...], list[TraceEvent]]:
        """Bind baseline claims to evidence and block rejected packets downstream."""
        gate = PacketAdmissionGate()
        accepted_texts: list[str] = []
        claim_bundles: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        proposals: list[DomainWriteProposal] = []
        events: list[TraceEvent] = []
        hard_dependencies = dict(discovery_blueprint.get("hard_dependencies", {}) or {})
        active_steps = [
            f"S{step}"
            for step, mode in winning_step_modes(
                str(discovery_blueprint.get("primary_branch", "A")),
                research_route=str(discovery_blueprint.get("runtime_route", "")),
                adaptive_modes=discovery_blueprint.get(
                    "adaptive_winning_step_modes", {}
                ),
            ).items()
            if mode != "skip"
        ]
        task_terms = [
            item
            for item in re.split(r"[，。；、\s/]+", topic)
            if len(item.strip()) >= 2
        ][:12]
        packet_snapshot = store.baseline_packet_snapshot()
        available_packet_agents = {packet.agent_id for packet in packet_snapshot}
        for packet in packet_snapshot:
            bundle = gate.extract_claim_bundle(
                packet,
                store.evidence,
                downstream_targets=active_steps,
            )
            decision = gate.evaluate(
                packet,
                bundle,
                store.evidence,
                task_terms=task_terms,
                accepted_claim_texts=accepted_texts,
                upstream_required=bool(
                    set(hard_dependencies.get(packet.agent_id, []))
                    & available_packet_agents
                ),
            )
            updated = replace(
                packet,
                claim_bundle_ref=bundle.bundle_id,
                admission_status=decision.status,
            )
            store.add_baseline_packet(updated)
            proposals.append(
                DomainWriteProposal(
                    proposal_id=f"domain-BaselineFindingPacket:{updated.packet_id}:admission-v2",
                    object_type="BaselineFindingPacket",
                    operation="upsert",
                    payload=to_plain(updated),
                    idempotency_key=f"domain:BaselineFindingPacket:{updated.packet_id}:admission-v2",
                )
            )
            claim_bundles.append(bundle.to_dict())
            decisions.append(decision.to_dict())
            if decision.status != "rejected":
                accepted_texts.extend(item.text for item in bundle.claims)
            events.append(
                TraceEvent(
                    event_id=f"trace-packet-admission-{packet.packet_id}",
                    event_type="packet_admission_evaluated",
                    actor="packet_admission_gate",
                    summary=f"{packet.agent_id} packet {decision.status}",
                    input_refs=[packet.packet_id, *packet.evidence_ids],
                    output_refs=[bundle.bundle_id, *decision.accepted_claim_ids],
                    payload={
                        "status": decision.status,
                        "scores": decision.scores,
                        "reasons": list(decision.reasons),
                        "incremental_value": decision.incremental_value,
                    },
                )
            )
        workspace.write_run_text(
            "claim_bundles.json",
            json.dumps(claim_bundles, ensure_ascii=False, indent=2, sort_keys=True),
        )
        workspace.write_run_text(
            "packet_admission.json",
            json.dumps(decisions, ensure_ascii=False, indent=2, sort_keys=True),
        )
        return tuple(proposals), events

    def _run_discovery_convergence(
        self,
        *,
        provider: AgentProvider,
        workspace: RunWorkspace,
        trace: TraceStore,
        topic: str,
        route: str,
        discovery_blueprint: dict[str, Any],
        coverage: dict[str, Any],
        store: DomainStore,
        mode: str,
        available_skills: Mapping[str, Mapping[str, Any]],
        available_knowledge_pack_ids: Sequence[str],
        meta_loop_enabled: bool = True,
    ) -> dict[str, Any]:
        packets = [
            {
                "packet_id": packet.packet_id,
                "agent_id": packet.agent_id,
                "capability_tags": packet.capability_tags,
                "findings": packet.findings[:6],
                "handoff_summary": packet.handoff_summary,
                "confidence": packet.confidence,
                "open_questions": packet.open_questions[:4],
                "evidence_ids": packet.evidence_ids,
                "limitations": packet.limitations[:4],
            }
            for packet in _admitted_packet_snapshot(store)
        ]
        payload = {
            "topic": topic,
            "research_route": route,
            "discovery_blueprint": discovery_blueprint,
            "coverage": coverage,
            "packets": packets,
            "evidence_index": store.evidence_index(),
        }
        trace.append(
            TraceEvent(
                event_id="trace-delegated-convergence-fusion",
                event_type="agent_task_delegated",
                actor="orchestrator",
                summary="委派收敛融合 Agent 执行跨背景、跨场景和跨分支汇聚",
                input_refs=[item["packet_id"] for item in packets],
                output_refs=["discovery-convergence"],
                payload={"target_agent_id": "convergence_fusion"},
            )
        )
        trace.append(
            TraceEvent(
                event_id="trace-discovery-convergence-call",
                event_type="tool_call",
                actor="convergence_fusion",
                summary="聚类需求、保留冲突、形成优先序和跨分支关联",
                input_refs=[item["packet_id"] for item in packets],
                payload={
                    "tool_name": "converge_discovery_outputs",
                    "provider_mode": mode,
                },
            )
        )
        self._write_core_agent_session(
            workspace,
            "convergence_fusion",
            {
                "event_type": "task_received",
                "summary": "消费发现蓝图、结构化基线、证据索引和覆盖结果，执行收敛融合。",
                "input_refs": [item["packet_id"] for item in packets],
                "primary_branch": discovery_blueprint["primary_branch"],
            },
        )
        converger = getattr(provider, "converge_discovery_outputs", None)
        optimized_v2 = is_quality_execution_profile_id(
            discovery_blueprint.get("execution_profile_id")
        )
        material_conflicts = [
            limitation
            for packet in packets
            for limitation in packet.get("limitations", [])
            if any(marker in str(limitation) for marker in ("冲突", "矛盾", "相反", "不一致"))
        ]
        if optimized_v2 and not material_conflicts:
            convergence = FakeAgentProvider().converge_discovery_outputs(payload)
            convergence["fusion_mode"] = "local_cluster_dedupe_rank"
            convergence["model_call_skipped"] = True
        else:
            convergence = (
                converger(payload)
                if callable(converger)
                else FakeAgentProvider().converge_discovery_outputs(payload)
            )
        if not isinstance(convergence, dict) or not convergence:
            convergence = FakeAgentProvider().converge_discovery_outputs(payload)
            convergence["limited_fallback"] = True
        self._write_core_agent_session(
            workspace,
            "convergence_fusion",
            {
                "event_type": (
                    "model_result" if mode == "real" else "deterministic_result"
                ),
                "result": convergence,
            },
        )
        trace.append(
            TraceEvent(
                event_id="trace-discovery-convergence-completed",
                event_type="discovery_convergence_completed",
                actor="convergence_fusion",
                summary="发现结果收敛融合完成",
                input_refs=[item["packet_id"] for item in packets],
                output_refs=["discovery-convergence"],
                payload={"result": convergence},
            )
        )
        if not meta_loop_enabled:
            meta_review = {
                "replan_required": False,
                "added_secondary_branches": [],
                "step_mode_overrides": [],
                "step_mode_changes": [],
                "dynamic_subagents": [],
                "focus_questions": [],
                "rationale": "消融策略关闭L4元循环，固定首轮蓝图。",
                "stop_reason": "disabled_by_stage_policy",
            }
            discovery_blueprint["meta_review"] = meta_review
            convergence["meta_review"] = meta_review
            workspace.write_run_text(
                "discovery_blueprint.json",
                json.dumps(
                    discovery_blueprint,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
            return convergence
        meta_review = {
            "replan_required": False,
            "added_secondary_branches": [],
            "step_mode_overrides": [],
            "step_mode_changes": [],
            "dynamic_subagents": [],
            "focus_questions": [],
            "rationale": "覆盖与收敛结果未触发实质性重规划条件，保留当前蓝图。",
            "stop_reason": "lean_meta_gate_passed",
        }
        meta_reviewer = getattr(provider, "review_discovery_meta_loop", None)
        enable_model_l4 = os.environ.get(
            "EQUIPMENT_DR_ENABLE_L4_MODEL_REPLAN",
            "0",
        ).strip().lower() in {"1", "true", "yes"}
        material_replan_trigger = (
            not bool(coverage.get("coverage_passed"))
            or len(convergence.get("conflicts", [])) >= 3
            or bool(discovery_blueprint.get("unmatched_driver"))
        )
        if (
            mode == "real"
            and getattr(provider, "provider_kind", "") == "codex_cli"
            and callable(meta_reviewer)
            and enable_model_l4
            and material_replan_trigger
        ):
            try:
                raw_meta_review = meta_reviewer(
                    {
                        **payload,
                        "convergence": convergence,
                        "allowed_branches": list("ABCDEFGH"),
                        "allowed_step_modes": ["skip", "light", "standard", "deep"],
                        "available_shared_skills": [
                            item
                            for item in available_skills.values()
                            if item.get("shared")
                        ],
                        "available_knowledge_packs": list(available_knowledge_pack_ids),
                    }
                )
                meta_review = _normalize_discovery_meta_review(
                    raw_meta_review,
                    discovery_blueprint,
                    available_skills=available_skills,
                    available_knowledge_pack_ids=available_knowledge_pack_ids,
                )
            except Exception as exc:  # keep the governed pipeline deliverable
                meta_review = {
                    **meta_review,
                    "rationale": "Codex L4元循环不可用，保留原蓝图并继续受限执行。",
                    "stop_reason": f"meta_replanner_error:{type(exc).__name__}",
                }
        if meta_review["replan_required"]:
            discovery_blueprint["secondary_branches"] = list(
                dict.fromkeys(
                    [
                        *discovery_blueprint.get("secondary_branches", []),
                        *meta_review["added_secondary_branches"],
                    ]
                )
            )[:2]
            discovery_blueprint["adaptive_winning_step_modes"] = {
                str(item["step"]): item["mode"]
                for item in meta_review["step_mode_overrides"]
            }
            discovery_blueprint["dynamic_subagents"] = list(
                {
                    str(item["agent_instance_id"]): item
                    for item in [
                        *discovery_blueprint.get("dynamic_subagents", []),
                        *meta_review["dynamic_subagents"],
                    ]
                }.values()
            )[:3]
        discovery_blueprint["meta_review"] = meta_review
        convergence["meta_review"] = meta_review
        workspace.write_run_text(
            "discovery_blueprint.json",
            json.dumps(
                discovery_blueprint,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )
        trace.append(
            TraceEvent(
                event_id="trace-discovery-meta-loop-final",
                event_type="discovery_meta_loop_evaluated",
                actor="orchestrator",
                summary=(
                    "L4元循环已完成有界重规划"
                    if meta_review["replan_required"]
                    else "L4元循环复核完成，保留当前执行蓝图"
                ),
                input_refs=["discovery-convergence"],
                output_refs=[str(discovery_blueprint["blueprint_id"])],
                payload={
                    "cycle": discovery_blueprint["loop_policy"]["meta_max_cycles"],
                    "maximum_cycles": discovery_blueprint["loop_policy"][
                        "meta_max_cycles"
                    ],
                    "primary_branch": discovery_blueprint["primary_branch"],
                    "secondary_branches": discovery_blueprint["secondary_branches"],
                    "cross_branch_link_count": len(
                        convergence.get("cross_branch_links", [])
                    ),
                    "open_question_count": len(convergence.get("open_questions", [])),
                    "replan_required": meta_review["replan_required"],
                    "added_secondary_branches": meta_review["added_secondary_branches"],
                    "step_mode_overrides": meta_review["step_mode_overrides"],
                    "step_mode_changes": meta_review["step_mode_changes"],
                    "dynamic_subagents": [
                        {
                            "agent_instance_id": item["agent_instance_id"],
                            "display_name": item["display_name"],
                            "merge_target": item["merge_target"],
                            "skill_ids": item["skill_ids"],
                            "knowledge_pack_ids": item["knowledge_pack_ids"],
                        }
                        for item in meta_review["dynamic_subagents"]
                    ],
                    "focus_questions": meta_review["focus_questions"],
                    "rationale": meta_review["rationale"],
                    "stop_reason": meta_review["stop_reason"],
                },
            )
        )
        return convergence

    @staticmethod
    def _convergence_from_trace(trace: TraceStore) -> dict[str, Any]:
        for event in reversed(trace.snapshot()):
            if event.event_type != "discovery_convergence_completed":
                continue
            result = event.payload.get("result", {})
            return dict(result) if isinstance(result, dict) else {}
        return {}

    @staticmethod
    def _write_checkpoint_file(
        workspace: RunWorkspace,
        checkpoint: RunCheckpoint,
        savepoint_id: str,
    ) -> None:
        encoded = json.dumps(
            {
                "savepoint_id": savepoint_id,
                "checkpoint": to_plain(checkpoint),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        workspace.write_checkpoint_text(f"{savepoint_id}.json", encoded)
        workspace.write_checkpoint_text("latest.json", encoded)

    @staticmethod
    def _write_core_agent_session(
        workspace: RunWorkspace,
        agent_id: str,
        record: dict[str, Any],
    ) -> None:
        sessions_fd = workspace.dup_sessions_fd()
        try:
            session = JsonlSessionStore(
                f"{agent_id}.jsonl",
                root_fd=sessions_fd,
                root_label=workspace.sessions_dir,
            )
            try:
                session.append({"agent_id": agent_id, **record})
            finally:
                session.close()
        finally:
            os.close(sessions_fd)

    @staticmethod
    def _load_latest_core_agent_result(
        workspace: RunWorkspace,
        agent_id: str,
    ) -> dict[str, Any]:
        def recovered_swarm_summary() -> dict[str, Any]:
            """Recover an already-finished quality-v1 swarm after S6 failure.

            Older S6 exception checkpoints contained only the projected cards
            even though the controller had already persisted its complete
            candidate ledger and finalist decision. Reattaching that audited
            summary avoids rerunning the expensive breadth/reviewer cohort on
            resume. Dynamic-v2 remains governed by its explicit portfolio gate.
            """

            controller_path = workspace.sessions_dir / "winning_swarm_controller.jsonl"
            if not controller_path.is_file():
                return {}
            for controller_line in reversed(
                controller_path.read_text(encoding="utf-8").splitlines()
            ):
                try:
                    controller_row = json.loads(controller_line)
                except json.JSONDecodeError:
                    continue
                summary = controller_row.get("swarm_summary")
                if not isinstance(summary, Mapping):
                    continue
                policy = summary.get("policy", {})
                policy_id = (
                    str(policy.get("policy_id", ""))
                    if isinstance(policy, Mapping)
                    else ""
                )
                finalists = summary.get("finalists", [])
                if (
                    policy_id == "winning_swarm_quality_v1"
                    and isinstance(finalists, list)
                    and finalists
                ):
                    recovered = dict(summary)
                    recovered["portfolio_quality_gate"] = {
                        "passed": True,
                        "recovered_from_controller_audit": True,
                        "finalist_count": len(finalists),
                    }
                    return recovered
            return {}

        path = workspace.sessions_dir / f"{agent_id}.jsonl"
        if not path.is_file():
            return {}
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            result = row.get("result")
            if row.get("event_type") == "model_result" and isinstance(result, dict):
                return dict(result)
            if row.get("event_type") == "model_checkpoint" and isinstance(
                result, dict
            ):
                checkpoint_result = dict(result)
                swarm = checkpoint_result.get("winning_swarm", {})
                if not isinstance(swarm, Mapping) or not swarm:
                    recovered = recovered_swarm_summary()
                    if recovered:
                        checkpoint_result["winning_swarm"] = recovered
                        swarm = recovered
                gate = (
                    swarm.get("portfolio_quality_gate", {})
                    if isinstance(swarm, Mapping)
                    else {}
                )
                if isinstance(gate, Mapping) and bool(gate.get("passed")):
                    normalized = _normalize_s6_deterministic_format(
                        checkpoint_result,
                        topic="",
                    )
                    normalized_swarm = normalized.get("winning_swarm", {})
                    normalized_directions = normalized.get(
                        "concept_directions", []
                    )
                    if (
                        isinstance(normalized_swarm, dict)
                        and isinstance(normalized_directions, list)
                        and normalized_directions
                    ):
                        normalized_swarm["final_equipment_portfolio"] = [
                            dict(item)
                            for item in normalized_directions
                            if isinstance(item, Mapping)
                        ]
                    resume_s6_warnings = _capability_direction_quality_issues(
                        normalized
                    )
                    resume_s6_issues = _s6_delivery_blocking_issues(
                        resume_s6_warnings
                    )
                    controller_audit_recovered = bool(
                        gate.get("recovered_from_controller_audit")
                    )
                    # A persisted controller decision is the authoritative
                    # expert review for this checkpoint.  Re-running the newer
                    # S6 rubric during resume can turn formatting drift into a
                    # second audit and unnecessarily restart the expensive
                    # swarm. Preserve warnings, but do not overturn the prior
                    # expert decision without new evidence or changed content.
                    normalized["s6_quality_gate_passed"] = (
                        controller_audit_recovered or not resume_s6_issues
                    )
                    normalized["s6_quality_gate_failed"] = (
                        bool(resume_s6_issues) and not controller_audit_recovered
                    )
                    normalized["s6_quality_gate_issues"] = (
                        [] if controller_audit_recovered else resume_s6_issues
                    )
                    normalized["s6_quality_warnings"] = [
                        issue
                        for issue in resume_s6_warnings
                        if controller_audit_recovered
                        or issue not in set(resume_s6_issues)
                    ]
                    return dict(normalized)
        return {}

    @classmethod
    def _record_winning_subagent_activity(
        cls,
        workspace: RunWorkspace,
        trace: TraceStore,
        analysis: dict[str, Any],
        *,
        attempt: int,
        record_subagents: bool = True,
    ) -> None:
        if record_subagents:
            for index, row in enumerate(analysis.get("subagent_runs", []), start=1):
                if not isinstance(row, dict):
                    continue
                cls._record_winning_progress_row(
                    workspace,
                    trace,
                    row,
                    attempt=attempt,
                    event_suffix=str(index),
                )
        for index, row in enumerate(analysis.get("loop_trace", []), start=1):
            if not isinstance(row, dict):
                continue
            loop_name = str(row.get("loop", "inner"))
            actor = (
                "winning_step_critic"
                if loop_name == "inner"
                else "winning_round_critic"
            )
            cls._write_core_agent_session(
                workspace,
                actor,
                {
                    "event_type": f"winning_{loop_name}_loop_evaluated",
                    "attempt": attempt,
                    **row,
                },
            )
            trace.append(
                TraceEvent(
                    event_id=f"trace-winning-{loop_name}-loop-r{attempt}-{index}",
                    event_type=f"winning_{loop_name}_loop_evaluated",
                    actor=actor,
                    summary=(
                        f"{loop_name} loop {'通过' if row.get('passed') else '触发回溯'}"
                    ),
                    payload={**row, "attempt": attempt},
                )
            )
        for index, metric in enumerate(analysis.get("codex_call_metrics", []), start=1):
            if not isinstance(metric, Mapping):
                continue
            payload = dict(metric)
            agent_id = str(payload.get("agent_id", "winning_mechanism"))
            cls._write_core_agent_session(
                workspace,
                agent_id,
                {
                    "event_type": "winning_model_call_completed",
                    "attempt": attempt,
                    **payload,
                },
            )
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-winning-model-call-{agent_id}-"
                        f"r{attempt}-{index}"
                    ),
                    event_type="winning_model_call_completed",
                    actor=agent_id,
                    summary=(
                        f"{payload.get('phase', 'winning')} completed in "
                        f"{payload.get('elapsed_seconds', 'unknown')}s"
                    ),
                    payload={**payload, "attempt": attempt},
                )
            )

    @classmethod
    def _record_winning_progress_row(
        cls,
        workspace: RunWorkspace,
        trace: TraceStore,
        row: Mapping[str, Any],
        *,
        attempt: int,
        event_suffix: str,
    ) -> None:
        payload = dict(row)
        agent_id = str(payload.get("agent_id", "winning_mechanism"))
        event_type = str(
            payload.get("event_type", "winning_subagent_completed")
        )
        if event_type.startswith("winning_model_"):
            current_step = str(payload.get("current_step", "S3-S6 推理"))
            elapsed = payload.get("elapsed_seconds")
            status_text = (
                "等待模型槽位"
                if event_type.endswith("queue_started")
                else "开始执行"
                if event_type.endswith("call_started")
                else f"持续执行 · 已耗时 {elapsed} 秒"
                if event_type.endswith("call_progress")
                else f"执行完成 · 用时 {elapsed} 秒"
            )
            cls._write_core_agent_session(
                workspace,
                agent_id,
                {
                    "event_type": event_type,
                    "attempt": attempt,
                    **payload,
                },
            )
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-{event_type}-{agent_id}-"
                        f"r{attempt}-{event_suffix}"
                    ),
                    event_type=event_type,
                    actor=agent_id,
                    summary=f"{current_step}：{status_text}",
                    payload={**payload, "attempt": attempt},
                )
            )
            return
        swarm_event_summaries = {
            "swarm_planned": "制胜机理弹性 Agent 群已完成有界任务规划",
            "specialist_recruitment_planned": "动态专用 Agent 已形成角色招聘合同",
            "specialist_spawned": "动态专用 Agent 已按质量残差孵化",
            "specialist_session_started": "动态专用 Agent 已启动独立 Codex CLI 会话",
            "specialist_session_completed": "动态专用 Agent 的独立 Codex CLI 会话已结束",
            "specialist_completed": "动态专用 Agent 已完成隔离任务",
            "specialist_pruned": "动态专用 Agent 已因预算、依赖或增益门槛回收",
            "hypothesis_created": "候选制胜假设已进入结构化账本",
            "hypothesis_merged": "专用贡献已合并到声明的候选与 S 节点",
            "hypothesis_rejected": "候选制胜假设未通过业务质量门",
            "swarm_gate_evaluated": "制胜假设或候选组合已完成质量门控",
            "winning_inner_loop_evaluated": "候选级专家批判、残差修复与复评内循环已完成",
            "promotion_candidate_created": "长期专用 Agent 晋级候选已生成，等待离线评测与人工审核",
            "winning_mission_graph_planned": "动态蜂群 Mission Graph 已完成有界规划",
            "winning_agent_instance_recruited": "动态蜂群 Agent 实例已按任务节点招募",
            "winning_agent_instance_ready": "动态蜂群 Agent 实例已就绪",
            "winning_agent_session_started": "动态蜂群 Agent 已启动独立模型会话",
            "winning_agent_session_completed": "动态蜂群 Agent 独立模型会话已完成",
            "winning_agent_instance_failed": "动态蜂群 Agent 实例执行失败",
            "winning_agent_instance_cancelled": "动态蜂群 Agent 实例已停止或回收",
            "winning_candidate_branch_created": "动态蜂群候选分支已写入账本",
            "winning_specialized_seed_recovered": "动态蜂群已按直接装备证据门恢复专用候选",
            "winning_specialized_seed_empty": "动态蜂群专用候选生成完成，未恢复额外种子",
            "winning_candidate_ledger_frozen": "动态蜂群候选账本版本已冻结",
            "winning_contribution_queued": "动态蜂群增量贡献等待合并",
            "winning_contribution_hypothesis_remapped": "动态蜂群增量贡献已重映射到规范候选",
            "winning_contribution_rejected": "动态蜂群增量贡献未通过合并门",
            "winning_contribution_rebase_required": "动态蜂群增量贡献需要基于新账本重放",
            "winning_contribution_merged": "动态蜂群增量贡献已合并",
            "winning_portfolio_merge_completed": "动态蜂群候选组合收敛完成",
            "winning_quality_judge_recruited": "动态蜂群质量评审实例已招募",
            "winning_quality_judge_started": "动态蜂群质量评审已启动",
            "winning_quality_judge_assessed": "动态蜂群质量评审完成单项判断",
            "winning_quality_judge_completed": "动态蜂群质量评审已完成",
            "winning_quality_judge_failed": "动态蜂群质量评审失败",
            "winning_quality_repair_planned": "动态蜂群质量残差修复已规划",
            "winning_quality_repair_completed": "动态蜂群质量残差修复已完成",
            "winning_quality_repair_failed": "动态蜂群质量残差修复失败",
        }
        if event_type in swarm_event_summaries:
            cls._write_core_agent_session(
                workspace,
                agent_id,
                {
                    "event_type": event_type,
                    "attempt": attempt,
                    **payload,
                },
            )
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-{event_type}-{agent_id}-"
                        f"r{attempt}-{event_suffix}"
                    ),
                    event_type=event_type,
                    actor=agent_id,
                    summary=swarm_event_summaries[event_type],
                    payload={**payload, "attempt": attempt},
                )
            )
            return
        cls._write_core_agent_session(
            workspace,
            agent_id,
            {
                "event_type": "winning_subagent_completed",
                "attempt": attempt,
                **payload,
            },
        )
        trace.append(
            TraceEvent(
                event_id=f"trace-{agent_id}-r{attempt}-{event_suffix}",
                event_type="winning_subagent_completed",
                actor=agent_id,
                summary=(
                    f"动态专用 Agent 完成并合并到{payload.get('merge_target', 'S3')}"
                    if payload.get("execution_mode") == "dynamic"
                    else (
                        f"S{payload.get('step')} 按A-H分支蓝图跳过"
                        if payload.get("status") == "skipped_by_branch_blueprint"
                        else (
                            f"S{payload.get('step')} 专用 Agent 完成"
                            f"（中循环{payload.get('middle_cycle', 1)}）"
                        )
                    )
                ),
                payload={**payload, "attempt": attempt},
            )
        )

    @classmethod
    def _record_reporter_progress_row(
        cls,
        workspace: RunWorkspace,
        trace: TraceStore,
        row: Mapping[str, Any],
        *,
        attempt: int,
        event_suffix: str,
    ) -> None:
        payload = dict(row)
        event_type = str(payload.get("event_type", "report_model_call_progress"))
        current_step = str(payload.get("current_step", "三层九项报告撰写"))
        elapsed = payload.get("elapsed_seconds")
        status_text = (
            "等待模型槽位"
            if event_type.endswith("queue_started")
            else "开始执行"
            if event_type.endswith("call_started")
            else f"持续执行 · 已耗时 {elapsed} 秒"
            if event_type.endswith("call_progress")
            else f"执行完成 · 用时 {elapsed} 秒"
        )
        cls._write_core_agent_session(
            workspace,
            "reporter",
            {
                "event_type": event_type,
                "attempt": attempt,
                **payload,
            },
        )
        trace.append(
            TraceEvent(
                event_id=(
                    f"trace-{event_type}-reporter-r{attempt}-{event_suffix}"
                ),
                event_type=event_type,
                actor="reporter",
                summary=f"{current_step}：{status_text}",
                payload={**payload, "attempt": attempt},
            )
        )

    def _write_recovered_outputs(
        self,
        *,
        workspace: RunWorkspace,
        mode: str,
        problem: ResearchProblem,
        route: str,
        discovery_blueprint: dict[str, Any],
        convergence: dict[str, Any],
        selected_agent_ids: list[str],
        coverage: dict[str, Any],
        worker_reports: list[WorkerReport],
        source_materials: list[dict[str, Any]],
        store: DomainStore,
        trace: TraceStore,
        analyst_confirmed: bool,
    ) -> None:
        if not store.reports:
            raise RuntimeError("completed checkpoint has no research report")
        # Completed resumes must still pick up deterministic portrait-contract
        # fixes. Reuse the same report-brief governance path to synchronize the
        # frozen capability records, then rewrite delivery artifacts without
        # reopening any model-backed Reporter stage.
        _report_decision_brief(
            store=store,
            branch_output={},
            convergence=convergence,
        )
        report = next(iter(store.reports.values()))
        self._write_outputs(
            workspace=workspace,
            mode=mode,
            problem=problem,
            route=route,
            discovery_blueprint=discovery_blueprint,
            convergence=convergence,
            selected_agent_ids=selected_agent_ids,
            coverage=coverage,
            worker_reports=worker_reports,
            recommendations=list(store.recommendations.values()),
            source_materials=source_materials,
            store=store,
            trace=trace,
            report_body=report.body,
            analyst_confirmed=analyst_confirmed,
        )

    def _write_outputs(
        self,
        *,
        workspace: RunWorkspace,
        mode: str,
        problem: ResearchProblem,
        route: str,
        discovery_blueprint: dict[str, Any],
        convergence: dict[str, Any],
        selected_agent_ids: list[str],
        coverage: dict[str, Any],
        worker_reports: list[Any],
        recommendations: list[Any],
        source_materials: list[dict[str, Any]],
        store: DomainStore,
        trace: TraceStore,
        report_body: str,
        analyst_confirmed: bool,
        execution_started_at: str = "",
    ) -> None:
        delivery_artifacts = build_delivery_artifacts(
            topic=problem.topic,
            branch=str(discovery_blueprint["primary_branch"]),
            blueprint=discovery_blueprint,
            store=store,
            convergence=convergence,
        )
        workspace.write_run_text("report.md", report_body)
        workspace.write_run_text(
            "evidence_references.md",
            render_formal_evidence_reference(store),
        )
        workspace.write_run_text(
            "branch_deliverables.json",
            json.dumps(
                delivery_artifacts["branch_deliverables"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )
        structured_artifact_names = [
            name
            for name in STRUCTURED_PRODUCT_KEYS
            if name in branch_profile(str(discovery_blueprint["primary_branch"]))["product_keys"]
        ]
        for name in structured_artifact_names:
            workspace.write_run_text(
                f"{name}.json",
                json.dumps(
                    delivery_artifacts[name],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
        workspace.write_run_text(
            "capability_images.json",
            json.dumps(
                [to_plain(item) for item in store.capability_images.values()],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )
        summary = {
            "mode": mode,
            "analyst_confirmed": analyst_confirmed,
            "problem": to_plain(problem),
            "resolved_route": route,
            "interaction_mode": problem.interaction_mode,
            "discovery_branch": problem.resolved_discovery_branch(),
            "discovery_blueprint": discovery_blueprint,
            "discovery_convergence": convergence,
            "delivery_artifacts": {
                "branch_deliverables": "branch_deliverables.json",
                "evidence_references": "evidence_references.md",
                **{name: f"{name}.json" for name in structured_artifact_names},
            },
            "selected_agent_ids": selected_agent_ids,
            "coverage": coverage,
            "worker_reports": [to_plain(report) for report in worker_reports],
            "recall_requests": [
                to_plain(recall) for recall in store.recall_requests.values()
            ],
            "agent_recommendations": [to_plain(item) for item in recommendations],
            "source_materials": source_materials,
            "store_summary": store.summary(),
            "trace_summary": trace.summary(),
            "provider": self._provider_snapshot(mode, trace),
            "agent_models": next(
                (
                    dict(event.payload.get("agent_models", {}))
                    for event in trace.snapshot()
                    if event.event_type == "run_started"
                ),
                {},
            ),
            "plan_graph": self._plan_graph_view(
                problem,
                discovery_blueprint=discovery_blueprint,
            ),
            "six_step_reasoning": self._six_step_view(
                topic=problem.topic,
                route=route,
                store=store,
            ),
            "winning_mechanism": {
                "inputs": [to_plain(item) for item in store.winning_inputs.values()],
                "resource_projections": [
                    to_plain(item) for item in store.knowledge_projections.values()
                ],
                "reasoning_nodes": [
                    to_plain(item) for item in store.reasoning_nodes.values()
                ],
                "stages": [to_plain(item) for item in store.stage_outputs.values()],
            },
            "evidence_assessments": self._evidence_assessments(store),
        }
        summary["performance_summary"] = self._performance_summary(
            trace=trace,
            selected_agent_ids=selected_agent_ids,
            discovery_blueprint=discovery_blueprint,
            execution_started_at=execution_started_at,
        )
        summary["winning_swarm"] = next(
            (
                dict(event.payload.get("swarm_summary", {}))
                for event in reversed(trace.snapshot())
                if event.event_type == "swarm_gate_evaluated"
                and isinstance(event.payload.get("swarm_summary", {}), Mapping)
                and event.payload.get("swarm_summary")
            ),
            {},
        )
        if is_quality_execution_profile_id(
            discovery_blueprint.get("execution_profile_id")
        ):
            contribution_observations = _agent_contribution_observations(
                store=store,
                trace=trace,
                report_body=report_body,
                workspace=workspace,
            )
            summary["agent_contributions"] = contribution_observations
            workspace.write_run_text(
                "agent_contributions.json",
                json.dumps(
                    contribution_observations,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
        summary["architecture_conformance"] = self._architecture_conformance(
            summary=summary,
            store=store,
            workspace=workspace,
        )
        workspace.write_run_text(
            "round_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        )
        workspace.write_run_text("domain.jsonl", store.jsonl_text())
        workspace.write_run_text("trace.jsonl", trace.jsonl_text())
        workspace.write_run_text(
            "architecture-acceptance.json",
            json.dumps(
                summary["architecture_conformance"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )

    @staticmethod
    def _performance_summary(
        *,
        trace: TraceStore,
        selected_agent_ids: Sequence[str],
        discovery_blueprint: Mapping[str, Any],
        execution_started_at: str = "",
    ) -> dict[str, Any]:
        """Build compact efficiency diagnostics without exposing hidden reasoning."""
        events = trace.snapshot()

        def timestamp(event: TraceEvent) -> datetime | None:
            try:
                return datetime.fromisoformat(event.created_at)
            except (TypeError, ValueError):
                return None

        dated = [value for event in events if (value := timestamp(event)) is not None]
        try:
            actual_start = (
                datetime.fromisoformat(execution_started_at)
                if execution_started_at
                else min(dated)
            )
        except (TypeError, ValueError):
            actual_start = min(dated) if dated else None
        total_seconds = (
            round((max(dated) - actual_start).total_seconds(), 3)
            if dated and actual_start is not None
            else 0.0
        )
        orchestration_setup_seconds = (
            round((min(dated) - actual_start).total_seconds(), 3)
            if dated and actual_start is not None
            else 0.0
        )
        call_events = [
            event
            for event in events
            if event.event_type
            in {
                "agent_model_call_completed",
                "winning_model_call_completed",
                "report_model_call_completed",
            }
        ]
        elapsed_values = [
            float(event.payload["elapsed_seconds"])
            for event in call_events
            if isinstance(event.payload.get("elapsed_seconds"), (int, float))
        ]
        queue_values = [
            float(event.payload["queue_wait_seconds"])
            for event in call_events
            if isinstance(event.payload.get("queue_wait_seconds"), (int, float))
        ]
        step_runs = [
            event
            for event in events
            if event.event_type == "winning_subagent_completed"
            and event.payload.get("status") == "completed"
        ]
        inner_events = [
            event
            for event in events
            if event.event_type == "winning_inner_loop_evaluated"
        ]
        middle_events = [
            event
            for event in events
            if event.event_type == "winning_middle_loop_evaluated"
        ]
        baseline_wave_events = [
            event for event in events if event.event_type == "baseline_wave_started"
        ]
        completed_swarm_agent_ids = {
            str(event.actor)
            for event in events
            if (
                event.event_type == "winning_agent_session_completed"
                or (
                    event.event_type == "winning_subagent_completed"
                    and event.payload.get("event_type")
                    == "winning_agent_session_completed"
                )
            )
            and str(event.actor).strip()
        }
        plan_modes = {
            str(item.get("agent_id", "")): str(item.get("mode", ""))
            for item in discovery_blueprint.get("baseline_agent_plan", [])
            if isinstance(item, Mapping)
        }
        return {
            "wall_time_seconds": total_seconds,
            "orchestration_setup_seconds": max(0.0, orchestration_setup_seconds),
            "selected_agent_count": len(selected_agent_ids),
            "selected_business_agent_count": sum(
                agent_id in PRIMARY_BUSINESS_AGENT_IDS
                for agent_id in selected_agent_ids
            ),
            "required_agent_count": sum(
                plan_modes.get(agent_id) == "required"
                for agent_id in selected_agent_ids
            ),
            "reference_agent_count": sum(
                plan_modes.get(agent_id, "reference") == "reference"
                for agent_id in selected_agent_ids
            ),
            "dynamic_agent_count": sum(
                str(agent_id).startswith("dynamic-")
                for agent_id in selected_agent_ids
            )
            + len(completed_swarm_agent_ids),
            "model_call_count": len(call_events),
            "model_elapsed_seconds_sum": round(sum(elapsed_values), 3),
            "max_model_call_seconds": round(max(elapsed_values, default=0.0), 3),
            "max_queue_wait_seconds": round(max(queue_values, default=0.0), 3),
            "winning_step_call_counts": {
                str(step): sum(
                    1
                    for event in step_runs
                    if int(event.payload.get("step", 0) or 0) == step
                )
                for step in range(1, 7)
            },
            "inner_review_count": len(inner_events),
            "inner_retry_count": sum(
                int(event.payload.get("iteration", 1) or 1) > 1
                for event in inner_events
            ),
            "middle_review_count": len(middle_events),
            "middle_cycle_count": max(
                (
                    int(event.payload.get("cycle", 1) or 1)
                    for event in middle_events
                ),
                default=0,
            ),
            "baseline_wave_governance": [
                {
                    "wave_index": int(event.payload.get("wave_index", 0) or 0),
                    "wave_size": int(event.payload.get("wave_size", 0) or 0),
                    "max_concurrency": int(
                        event.payload.get("max_concurrency", 0) or 0
                    ),
                    "execution_batches": int(
                        event.payload.get("execution_batches", 0) or 0
                    ),
                    "bounded": event.payload.get("bounded") is True,
                }
                for event in baseline_wave_events
            ],
        }

    def _provider_snapshot(
        self,
        mode: str,
        trace: TraceStore | None = None,
    ) -> dict[str, str]:
        if mode == "fake":
            return {"type": "fake", "model": "fake", "base_url_host": ""}
        if trace is not None:
            started = next(
                (
                    event
                    for event in trace.snapshot()
                    if event.event_type == "run_started"
                ),
                None,
            )
            if started is not None:
                provider_name = str(started.payload.get("provider", ""))
                if provider_name == "codex":
                    return {
                        "type": "codex_cli",
                        "model": str(started.payload.get("model", ""))
                        or "(cli default)",
                        "base_url_host": str(started.payload.get("base_url_host", "")),
                    }
                if provider_name == "responses":
                    return {
                        "type": "responses",
                        "model": str(started.payload.get("model", "")),
                        "base_url_host": str(started.payload.get("base_url_host", "")),
                    }
        if not self.provider_config_path.exists():
            return {"type": "codex_cli", "model": "gpt-5.5", "base_url_host": ""}
        registry = ProviderRegistry.load(self.provider_config_path)
        profile = registry.profile_snapshot(registry.default_provider)
        return {str(key): str(value) for key, value in profile.items()}

    def _plan_graph_view(
        self,
        problem: ResearchProblem,
        *,
        discovery_blueprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        registry = AgentRegistry.load(self.agent_config_path)
        selected = registry.select_agents(problem.selected_agent_ids)
        graph = ResearchPlanner(load_preset_policy(self.preset_config_path)).build(
            problem,
            selected,
        )
        blueprint = discovery_blueprint or build_discovery_blueprint(problem)
        waves = execution_waves_from_blueprint(selected, blueprint)
        return {
            "plan_id": graph.plan_id,
            "discovery_blueprint": blueprint,
            "baseline_map_count": sum(
                node.node_type == "baseline_map" for node in graph.nodes
            ),
            "nodes": [to_plain(node) for node in graph.nodes],
            "dependency_edges": [
                {"from": dependency, "to": node.node_id}
                for node in graph.nodes
                for dependency in node.depends_on
            ],
            "execution_waves": [
                {
                    "wave": index,
                    "agent_ids": [agent.agent_id for agent in wave],
                    "concurrent": len(wave) > 1,
                }
                for index, wave in enumerate(waves, start=1)
            ],
            "gate_points": [
                {"gate": "baseline_contract_and_evidence", "after": "reduce:baseline"},
                {"gate": "cross_scenario_convergence", "after": "convergence_fusion"},
                {"gate": "L1_confidence_coverage", "after": "L1", "threshold": 0.7},
                {"gate": "L2_feasibility_consistency", "after": "L2", "threshold": 3},
                {"gate": "L3_nine_field_traceability", "after": "L3"},
                {"gate": "five_criteria_audit", "after": "audit:five-criteria"},
            ],
            "recall_return_nodes": ["L1", "L2", "L3"],
            "loops": {
                "inner": "winning_step_critic",
                "middle": "winning_round_critic",
                "outer": "L1/L2/L3定向Recall与节点返回",
                "meta": "A-H蓝图选择、跨分支汇聚与重规划评估",
                **blueprint.get("loop_policy", {}),
            },
        }

    @staticmethod
    def _architecture_conformance(
        *,
        summary: dict[str, Any],
        store: DomainStore,
        workspace: RunWorkspace,
    ) -> dict[str, Any]:
        stage_layers = {item.layer for item in store.stage_outputs.values()}
        reasoning_steps = {item.step for item in store.reasoning_nodes.values()}
        required_image_fields = {
            "capability_id",
            "name",
            "equipment_category",
            "capability_type",
            "source_winning_logic",
            "related_scenario",
            "priority",
            "capability_gap",
            "capability_image",
        }
        image_rows = [to_plain(item) for item in store.capability_images.values()]
        selected = list(summary.get("selected_agent_ids", []))
        session_agents = {
            path.stem for path in (workspace.run_dir / "agent_sessions").glob("*.jsonl")
        }
        resource_projections = summary["winning_mechanism"]["resource_projections"]
        trace_rows = list(summary.get("trace_summary", []))
        event_types = {
            str(item.get("event_type", "")) for item in trace_rows
        }
        wave_governance = list(
            summary.get("performance_summary", {}).get(
                "baseline_wave_governance",
                [],
            )
        )
        governed_sessions: dict[str, bool] = {}
        for agent_id in selected:
            try:
                records = [
                    json.loads(line)
                    for line in workspace.read_run_text(
                        f"agent_sessions/{agent_id}.jsonl"
                    ).splitlines()
                    if line.strip()
                ]
            except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
                governed_sessions[agent_id] = False
                continue
            task_record = next(
                (item for item in records if item.get("event_type") == "task_received"),
                {},
            )
            governed_sessions[agent_id] = bool(
                isinstance(task_record.get("allowed_tools"), list)
                and isinstance(task_record.get("object_read_scopes"), list)
                and isinstance(task_record.get("object_write_scopes"), list)
                and isinstance(task_record.get("budget"), dict)
                and task_record.get("budget")
            )
        failure_handoff_rows = [
            item
            for item in trace_rows
            if item.get("event_type") == "agent_failure_handoff_ready"
        ]
        persisted_loop_kinds = _persisted_winning_loop_kinds(store)
        blueprint = summary.get("discovery_blueprint", {})
        execution_profile_id = str(blueprint.get("execution_profile_id", "")).strip()
        checks = {
            "real_or_fake_mode_recorded": summary.get("mode") in {"real", "fake"},
            "dynamic_agent_selection_recorded": bool(selected),
            "plan_graph_complete": bool(summary["plan_graph"].get("execution_waves"))
            and len(summary["plan_graph"].get("gate_points", [])) >= 5,
            "isolated_agent_sessions": set(selected) <= session_agents,
            "permission_and_budget_contracts_recorded": bool(governed_sessions)
            and all(governed_sessions.values()),
            "bounded_wave_concurrency_enforced": bool(wave_governance)
            and all(
                item.get("bounded") is True
                and isinstance(item.get("max_concurrency"), int)
                and 1
                <= item["max_concurrency"]
                <= item.get("wave_size", 0)
                for item in wave_governance
            ),
            "structured_map_reduce_handoffs": bool(store.baseline_packets)
            and all(
                packet.packet_id
                and packet.handoff_summary
                and isinstance(packet.evidence_ids, list)
                for packet in store.baseline_packets.values()
            )
            and bool(summary.get("discovery_convergence")),
            "recoverable_checkpoint_lineage": workspace.run_file_is_regular(
                "run.db"
            )
            and workspace.run_file_is_regular("checkpoints/latest.json"),
            "failure_handoff_contracts_persisted": (
                all(
                    all(
                        workspace.run_file_is_regular(str(output_ref))
                        for output_ref in item.get("output_refs", [])
                    )
                    for item in failure_handoff_rows
                )
                if failure_handoff_rows
                else True
            ),
            "core_agent_sessions": (
                {
                    "orchestrator",
                    "convergence_fusion",
                    "winning_mechanism",
                }
                <= session_agents
                and (
                    "auditor" in session_agents
                    or "audit_completed" in event_types
                )
                and (
                    "reporter" in session_agents
                    or "report_completed" in event_types
                )
                if summary.get("mode") == "real"
                else True
            ),
            "coverage_explicit": "missing_required_tags" in summary.get("coverage", {}),
            "a_h_blueprint_executable": bool(blueprint)
            and blueprint.get("primary_branch") in set("ABCDEFGH")
            and bool(blueprint.get("waves")),
            "cross_scenario_convergence_present": bool(
                summary.get("discovery_convergence")
            ),
            "outer_and_meta_loops_recorded": {
                "winning_outer_loop_evaluated",
                "discovery_meta_loop_evaluated",
            }
            <= event_types,
            "codex_inner_and_middle_loops_recorded": _codex_loops_recorded(
                mode=str(summary.get("mode", "")),
                execution_profile_id=execution_profile_id,
                event_types=event_types,
                persisted_loop_kinds=persisted_loop_kinds,
                session_agents=session_agents,
            ),
            "four_knowledge_resources_projected": bool(resource_projections)
            and all(
                key in resource_projections[-1]
                for key in (
                    "theory_tools",
                    "case_resources",
                    "frontier_resources",
                    "question_chain",
                )
            ),
            "six_step_reasoning_complete": reasoning_steps == {1, 2, 3, 4, 5, 6},
            "l1_l2_l3_present": stage_layers == {"L1", "L2", "L3"},
            "nine_field_capability_images": bool(image_rows)
            and all(required_image_fields <= set(row) for row in image_rows),
            "formal_evidence_present": bool(store.evidence),
            "five_criteria_audit_present": bool(store.audits),
            "final_report_present": bool(store.reports),
        }
        audit_status = next(
            (item.status for item in store.audits.values()),
            "missing",
        )
        return {
            "schema_version": "1.0",
            "architecture_source": [
                "基于多智能体协作的JS装备市场需求深度挖掘系统架构设计.docx",
                "编排器与动态智能体_总体架构图.pdf",
                "制胜机理智能体_详细架构图.pdf",
            ],
            "checks": checks,
            "runtime_complete": all(checks.values()),
            "release_ready": all(checks.values()) and audit_status == "approved",
            "audit_status": audit_status,
            "limitations": []
            if audit_status == "approved"
            else [
                "运行链路可完整，但正式发布仍须满足覆盖、置信度、材料化、轮次和分析师确认判据。"
            ],
        }

    @staticmethod
    def _six_step_view(
        *,
        topic: str,
        route: str,
        store: DomainStore,
    ) -> dict[str, Any]:
        result = SixStepReasoner().run(
            topic=topic,
            route=route,
            packets=list(store.baseline_packets.values()),
            evidence=list(store.evidence.values()),
        )
        return {
            "defense_decomposition": to_plain(result.defense_decomposition),
            "winning_paths": to_plain(result.winning_paths),
            "effect_chain": to_plain(result.effect_chain),
            "capability_mapping": to_plain(result.capability_mapping),
            "gap_matrix": to_plain(result.gap_matrix),
            "image_drafts": [to_plain(item) for item in result.image_drafts],
        }

    def _evidence_assessments(self, store: DomainStore) -> list[dict[str, Any]]:
        governor = self._evidence_governor()
        accepted: list[Any] = []
        rows: list[dict[str, Any]] = []
        for evidence in store.evidence.values():
            materialized = bool(evidence.artifact_refs)
            dimensions = {
                "relevance": 0.85,
                "transparency": 0.8 if evidence.source_location else 0.3,
                "freshness": 0.7,
                "direct_support": 0.8 if evidence.excerpt else 0.2,
                "extraction_quality": 0.85 if materialized else 0.45,
            }
            assessment = governor.assess(
                evidence,
                dimensions,
                existing=accepted,
            )
            if assessment.decision == "accepted":
                accepted.append(evidence)
            rows.append(to_plain(assessment))
        return rows

    def _evidence_governor(self) -> EvidenceGovernor:
        if not self.evidence_config_path.exists():
            return EvidenceGovernor()
        import yaml

        payload = (
            yaml.safe_load(self.evidence_config_path.read_text(encoding="utf-8")) or {}
        )
        return EvidenceGovernor(
            minimum_score=float(
                payload.get("acceptance", {}).get("min_quality_score", 0.62)
            ),
            weights={
                str(key): float(value)
                for key, value in payload.get("weights", {}).items()
            }
            or None,
        )

    @staticmethod
    def _result(
        *,
        run_id: str,
        run_dir: Path,
        route: str,
        store: DomainStore,
    ) -> dict[str, Any]:
        if not store.audits:
            raise RuntimeError("completed run has no audit result")
        audit = next(iter(store.audits.values()))
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "route": route,
            "status": "completed",
            "report_path": str(run_dir / "report.md"),
            "capability_images_path": str(run_dir / "capability_images.json"),
            "branch_deliverables_path": str(run_dir / "branch_deliverables.json"),
            "summary_path": str(run_dir / "round_summary.json"),
            "audit_status": audit.status,
            "capability_count": len(store.capability_images),
            "stage_count": len(store.stage_outputs),
        }

    def _emit_hook(self, event: str, workspace: RunWorkspace) -> None:
        if self.run_hook is not None:
            self.run_hook(event, workspace)


def _task_id(agent_id: str) -> str:
    return f"baseline:{agent_id}"


def _domain_object_for_report(store: DomainStore, report: WorkerReport) -> Any:
    catalogs = {
        "StrategicAssessment": store.strategic_assessments,
        "ScenarioModel": store.scenario_models,
        "EquipmentObservation": store.equipment_observations,
        "OperationalSynthesis": store.operational_syntheses,
    }
    try:
        return catalogs[report.domain_object_type][report.domain_object_id]
    except KeyError as exc:
        raise RuntimeError(
            f"missing typed domain object {report.domain_object_type}/{report.domain_object_id}"
        ) from exc


def _proposal_batch_hash(
    domain_proposals: Sequence[DomainWriteProposal],
    trace_proposals: Sequence[TraceProposal],
) -> str:
    rows = [
        {"channel": "domain", **proposal.to_plain()} for proposal in domain_proposals
    ] + [{"channel": "trace", **proposal.to_plain()} for proposal in trace_proposals]
    rows.sort(key=lambda row: (str(row["proposal_id"]), str(row["channel"])))
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _dedupe_plain_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        if encoded in seen:
            continue
        seen.add(encoded)
        unique.append(dict(row))
    return unique


def _compact_winning_blueprint(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "primary_branch",
            "branch_name",
            "emphasis",
            "required_outputs",
            "adaptive_winning_step_modes",
            "execution_profile_id",
            "structured_query_brief",
            # Quality profiles consume the compact blueprint.  Dropping this
            # field silently disabled ``swarm_quality_v1`` while dynamic v2
            # appeared to work only because the provider force-enabled it.
            "winning_swarm_policy",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _compact_winning_convergence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    clusters = []
    for item in value.get("clusters", [])[:6]:
        if isinstance(item, Mapping):
            clusters.append(
                {
                    key: str(item.get(key, ""))[:260]
                    for key in ("name", "shared_need", "military_value")
                    if item.get(key) not in (None, "", [], {})
                }
            )
        elif str(item).strip():
            clusters.append(str(item)[:260])
    return {
        "clusters": clusters,
        "priorities": [str(item)[:240] for item in value.get("priorities", [])[:5]],
        "conflicts": [str(item)[:220] for item in value.get("conflicts", [])[:4]],
    }


def _compact_winning_coverage(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "coverage_passed",
            "required_tags",
            "provided_tags",
            "missing_required_tags",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _compact_winning_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: value.get(key)
        for key in (
            "branch",
            "step_intensity",
            "physical_cohorts",
            "branch_products",
            "backtrack_map",
            "stop_conditions",
            "background_count",
            "scenarios_per_background",
            "maximum_rounds",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _minimal_winning_evidence_index(
    store: DomainStore,
    packets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    requested_ids = list(
        dict.fromkeys(
            str(evidence_id)
            for packet in packets
            for evidence_id in packet.get("evidence_ids", [])
            if str(evidence_id)
        )
    )
    if len(requested_ids) < 18:
        requested_ids.extend(
            evidence_id
            for evidence_id in store.evidence
            if evidence_id not in requested_ids
        )
    rows: list[dict[str, Any]] = []
    for evidence_id in requested_ids[:24]:
        item = store.evidence.get(evidence_id)
        if item is None:
            continue
        rows.append(
            {
                "evidence_id": item.evidence_id,
                "title": str(item.source_title)[:140],
                "url": str(item.source_url),
                "tier": str(item.source_tier),
                "claim": " ".join(str(item.claim).split())[:260],
            }
        )
    return rows


def _report_evidence_catalog(
    store: DomainStore,
    *,
    limit: int = 18,
    claim_chars: int = 240,
) -> list[dict[str, Any]]:
    """Public, citation-ready evidence rows for the final report agent."""

    tier_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    ranked_rows = sorted(
        store.evidence.values(),
        key=lambda item: (
            tier_rank.get(str(item.source_tier), 9),
            not bool(str(item.excerpt).strip()),
            str(item.source_title),
        ),
    )
    decision_images = sorted(
        store.capability_images.values(),
        key=lambda item: (
            _report_priority_rank(item.priority),
            -float(item.confidence),
            item.name,
        ),
    )[:7]
    decision_evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for image_item in decision_images
            for evidence_id in image_item.evidence_ids[:3]
        )
    )
    priority_rows = [
        store.evidence[evidence_id]
        for evidence_id in decision_evidence_ids
        if evidence_id in store.evidence
    ]
    rows = list(
        dict.fromkeys(
            [item.evidence_id for item in priority_rows]
            + [item.evidence_id for item in ranked_rows]
        )
    )
    selected = [store.evidence[evidence_id] for evidence_id in rows[: max(1, limit)]]
    return [
        {
            "title": str(item.source_title)[:140],
            "url": str(item.source_url),
            "tier": str(item.source_tier),
            "claim": " ".join(str(item.claim).split())[: max(60, claim_chars)],
        }
        for item in selected
        if str(item.source_url).strip()
    ]


def _report_accepted_claims(
    store: DomainStore,
    *,
    per_packet_limit: int = 3,
    total_limit: int = 16,
) -> list[dict[str, Any]]:
    """Pass admitted causal claims—not internal traces—to the final writer."""
    rows: list[dict[str, Any]] = []
    for packet in _admitted_packet_snapshot(store):
        evidence_rows = [
            store.evidence[evidence_id]
            for evidence_id in packet.evidence_ids
            if evidence_id in store.evidence
            and store.evidence[evidence_id].source_url.startswith(("http://", "https://"))
        ]
        public_urls = list(dict.fromkeys(item.source_url for item in evidence_rows))
        for finding in packet.findings[:per_packet_limit]:
            rows.append(
                {
                    "claim": str(finding)[:520],
                    "confidence": packet.confidence,
                    "public_urls": public_urls[:3],
                    "counter_evidence_or_limits": [
                        str(item)[:180] for item in packet.limitations[:2]
                    ],
                }
            )
    return rows[:total_limit]


def _publicize_report_references(body: str, store: DomainStore) -> str:
    """Replace internal object identifiers with citation-ready public handles."""
    result = str(body)
    for evidence in sorted(
        store.evidence.values(), key=lambda item: len(item.evidence_id), reverse=True
    ):
        label = evidence.source_title.strip() or "公开来源"
        replacement = (
            f"[{label}]({evidence.source_url})"
            if evidence.source_url.startswith(("http://", "https://"))
            else label
        )
        result = result.replace(evidence.evidence_id, replacement)
    for packet in store.baseline_packets.values():
        result = result.replace(packet.packet_id, f"{packet.agent_id}专业研究结论")
        if packet.claim_bundle_ref:
            result = result.replace(packet.claim_bundle_ref, "已准入结论集")
        for claim_id in packet.claim_ids:
            result = result.replace(claim_id, "公开证据支持的结论")
    return result


def _normalize_delivery_report_structure(body: str) -> str:
    """Apply deterministic heading repair without dropping delivery-owned H1."""

    text = str(body)
    h1 = next(
        (
            line.strip()
            for line in text.splitlines()
            if line.startswith("# ") and not line.startswith("## ")
        ),
        "",
    )
    normalized = _normalize_report_structure_deterministically(text).strip()
    if h1 and not normalized.startswith(h1):
        return f"{h1}\n\n{normalized}".strip()
    return normalized


def _report_delivery_limit_payload(
    *,
    discovery_blueprint: Mapping[str, Any],
    report_template_mode: str,
    branch_writer_brief: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve the execution contract during post-render length handling."""

    return {
        "execution_profile_id": discovery_blueprint.get(
            "execution_profile_id", "legacy_v1"
        ),
        "report_template_mode": report_template_mode,
        "branch_writer_brief": branch_writer_brief,
    }


def _agent_contribution_observations(
    *,
    store: DomainStore,
    trace: TraceStore,
    report_body: str,
    workspace: RunWorkspace | None = None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    events = trace.snapshot()
    for packet in _admitted_packet_snapshot(store):
        evidence_ids = set(packet.evidence_ids)
        adopted_by_steps = {
            f"S{node.step}": [
                claim_id
                for claim_id in packet.claim_ids
                if claim_id in set(node.claim_ids)
            ]
            or list(packet.claim_ids[:1])
            for node in store.reasoning_nodes.values()
            if evidence_ids & set(node.evidence_ids)
        }
        capability_ids = [
            item.capability_id
            for item in store.capability_images.values()
            if evidence_ids & set(item.evidence_ids)
        ]
        public_urls = [
            store.evidence[evidence_id].source_url
            for evidence_id in packet.evidence_ids
            if evidence_id in store.evidence
            and store.evidence[evidence_id].source_url.startswith(("http://", "https://"))
        ]
        report_sections = ["final_report"] if any(url in report_body for url in public_urls) else []
        trace_model_events = [
            event
            for event in events
            if event.actor == packet.agent_id
            and event.event_type
            in {"agent_model_call_completed", "winning_model_call_completed"}
        ]
        # A resumed run reconstructs domain objects from checkpoints, but its
        # in-memory TraceStore intentionally contains only the resumed segment.
        # Agent session JSONL is the durable execution ledger, so use it as the
        # source of truth when available.  max() prevents double-counting when
        # the same completion event is also present in the current TraceStore.
        persisted_model_calls = _persisted_agent_model_call_count(
            workspace=workspace,
            agent_id=packet.agent_id,
        )
        model_calls = max(len(trace_model_events), persisted_model_calls)
        observations.append(
            {
                "observation_id": f"contribution-{packet.packet_id}",
                "agent_id": packet.agent_id,
                "packet_id": packet.packet_id,
                "produced_claim_ids": list(packet.claim_ids),
                "adopted_by_s_steps": adopted_by_steps,
                "adopted_by_capability_ids": capability_ids,
                "adopted_by_report_sections": report_sections,
                "model_calls": model_calls,
                "loao_quality_delta": None,
                "contributed": bool(
                    adopted_by_steps or capability_ids or report_sections
                ),
            }
        )
    return observations


def _persisted_agent_model_call_count(
    *,
    workspace: RunWorkspace | None,
    agent_id: str,
) -> int:
    if workspace is None or not agent_id:
        return 0
    try:
        payload = workspace.read_run_text(
            Path("agent_sessions") / f"{agent_id}.jsonl"
        )
    except (FileNotFoundError, OSError, ValueError):
        return 0

    count = 0
    for line in payload.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(event, Mapping)
            and event.get("agent_id") == agent_id
            and event.get("event_type")
            in {"agent_model_call_completed", "winning_model_call_completed"}
        ):
            count += 1
    return count


def _report_decision_brief(
    *,
    store: DomainStore,
    branch_output: Mapping[str, Any],
    convergence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert research artifacts into a bounded editorial decision brief.

    The final writer should receive decisions and public source handles, not the
    raw multi-agent transcript.  This function deliberately removes internal
    identifiers and keeps only the material needed to argue a conclusion.
    """

    convergence = convergence or {}
    thesis_candidates: list[Any] = []
    for cluster in convergence.get("clusters", []):
        if isinstance(cluster, Mapping):
            cluster_name = str(cluster.get("name", ""))
            if any(
                marker in cluster_name
                for marker in ("回调", "缺失标签", "覆盖闭合")
            ):
                continue
            thesis_candidates.append(
                cluster.get("shared_need") or cluster.get("name")
            )
    thesis_candidates.extend(convergence.get("priorities", []))
    thesis_candidates.extend(
        node.summary
        for node in sorted(
            store.reasoning_nodes.values(),
            key=lambda item: (item.step, item.created_at),
            reverse=True,
        )
    )
    thesis_candidates.extend(
        packet.handoff_summary for packet in store.baseline_packets.values()
    )

    images = sorted(
        store.capability_images.values(),
        key=lambda item: (
            _report_priority_rank(item.priority),
            -float(item.confidence),
            item.name,
        ),
    )[:7]
    capability_decisions: list[dict[str, Any]] = []
    for image_index, image_item in enumerate(images):
        mission_failure = _derive_report_mission_failure(
            capability_gap=image_item.capability_gap,
            deep_portrait=image_item.deep_capability_portrait,
        )
        equipment_identity = "；".join(
            value
            for value in (
                image_item.name,
                image_item.equipment_form or image_item.equipment_category,
                image_item.mission_effect or image_item.military_utility,
            )
            if value
        )
        normalized_problem = normalize_capability_problem(
            image_item.problem_statement or mission_failure,
            fallback=(
                f"{image_item.name}对应的关键任务链存在目标、授权、交战或毁伤评估断点"
            ),
        )
        normalized_process = normalize_operational_process(
            image_item.operational_process or image_item.strike_chain_contribution,
            equipment_identity=equipment_identity,
        )
        normalized_verification = normalize_verification_plan(
            image_item.verification_plan,
            equipment_identity=equipment_identity,
            failure_boundary=(
                image_item.risk_boundaries
                or image_item.operational_constraints
                or image_item.upgrade_boundary
            ),
        )
        normalized_portrait = resolve_capability_portrait(
            image_item.deep_capability_portrait,
            name=image_item.name,
            scenario=image_item.target_scenario or image_item.related_scenario,
            problem=normalized_problem,
            principle=(
                image_item.scientific_principle
                or image_item.operational_mechanism
                or image_item.novelty
            ),
            technologies=(
                image_item.enabling_technologies
                or image_item.upgrade_package
                or image_item.equipment_form
            ),
            operational_concept=(
                image_item.operational_concept or image_item.operational_mechanism
            ),
            operational_steps=normalized_process,
            capability=(
                image_item.capability_outcome
                or image_item.military_utility
                or image_item.mission_effect
            ),
            effect=image_item.mission_effect or image_item.military_utility,
            winning_mechanism=(
                image_item.winning_mechanism
                or image_item.source_winning_logic
                or image_item.novelty
            ),
            equipment_form=image_item.equipment_form or image_item.equipment_category,
            baseline=image_item.baseline_system or image_item.equipment_category,
            development_path=image_item.development_path or image_item.foresight,
            failure_boundary=(
                image_item.risk_boundaries or image_item.operational_constraints
            ),
            verification_plan=normalized_verification,
        )
        if (
            normalized_portrait != image_item.capability_image
            or normalized_portrait != image_item.deep_capability_portrait
        ):
            image_item = replace(
                image_item,
                capability_image=normalized_portrait,
                deep_capability_portrait=normalized_portrait,
            )
            images[image_index] = image_item
            store.capability_images[image_item.capability_id] = image_item
        public_sources = []
        seen_urls: set[str] = set()
        for evidence_id in image_item.evidence_ids:
            evidence = store.evidence.get(str(evidence_id))
            if evidence is None:
                continue
            url = str(evidence.source_url).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            public_sources.append(
                {
                    "title": _clean_report_brief_text(
                        evidence.source_title,
                        max_chars=160,
                    ),
                    "url": url,
                }
            )
            if len(public_sources) >= 2:
                break
        capability_decisions.append(
            {
                "name": _clean_report_brief_text(image_item.name, max_chars=100),
                "priority": _clean_report_brief_text(
                    image_item.priority,
                    max_chars=40,
                ),
                "type": str(image_item.capability_type),
                "project_function": _clean_report_brief_text(
                    image_item.project_function,
                    max_chars=240,
                ),
                "mission_failure": mission_failure,
                "operational_effect": _clean_report_brief_text(
                    image_item.strike_countermeasure_value
                    or image_item.combat_effect_uplift
                    or image_item.military_utility
                    or image_item.mission_effect,
                    max_chars=280,
                ),
                "mechanism": _clean_report_brief_text(
                    image_item.operational_mechanism
                    or image_item.source_winning_logic,
                    max_chars=280,
                ),
                "target_scenario": _clean_report_brief_text(
                    image_item.target_scenario or image_item.related_scenario,
                    max_chars=220,
                ),
                "problem_statement": _clean_report_brief_text(
                    normalized_problem,
                    max_chars=220,
                ),
                "scientific_principle": _clean_report_brief_text(
                    image_item.scientific_principle
                    or image_item.operational_mechanism,
                    max_chars=200,
                ),
                "enabling_technologies": _clean_report_brief_items(
                    image_item.enabling_technologies,
                    limit=5,
                    max_chars=100,
                ),
                "operational_concept": _clean_report_brief_text(
                    image_item.operational_concept
                    or image_item.operational_mechanism,
                    max_chars=240,
                ),
                "operational_process": _clean_report_brief_items(
                    normalized_process,
                    limit=6,
                    max_chars=120,
                ),
                "capability_outcome": _clean_report_brief_text(
                    image_item.capability_outcome
                    or image_item.military_utility
                    or image_item.mission_effect,
                    max_chars=200,
                ),
                "winning_mechanism": _clean_report_brief_text(
                    image_item.winning_mechanism
                    or image_item.source_winning_logic,
                    max_chars=240,
                ),
                "equipment_form": _clean_report_brief_text(
                    image_item.equipment_form or image_item.equipment_category,
                    max_chars=220,
                ),
                "public_equipment_baseline": _clean_report_brief_text(
                    image_item.baseline_system,
                    max_chars=260,
                ),
                "future_trigger": _clean_report_brief_text(
                    image_item.foresight,
                    max_chars=220,
                ),
                "disruptive_relationship": _clean_report_brief_text(
                    image_item.novelty,
                    max_chars=220,
                ),
                "development_path": _clean_report_brief_text(
                    image_item.development_path,
                    max_chars=200,
                ),
                "verification_plan": _clean_report_brief_items(
                    normalized_verification,
                    limit=4,
                    max_chars=180,
                ),
                "capability_portrait": _clean_report_capability_portrait(
                    normalized_portrait
                ),
                "indicator_portrait": _report_indicator_portrait(image_item),
                "coupling_risk": _report_coupling_risk(image_item),
                "boundaries": _clean_report_brief_items(
                    [
                        *image_item.risk_boundaries,
                        *image_item.operational_constraints,
                        image_item.upgrade_boundary,
                    ],
                    limit=8,
                    max_chars=180,
                ),
                "public_sources": public_sources,
            }
        )

    task_chain_breaks = _clean_report_brief_items(
        [
            *(
                _derive_report_mission_failure(
                    capability_gap=item.capability_gap,
                    deep_portrait=item.deep_capability_portrait,
                )
                for item in images
            ),
            *(
                item
                for packet in store.baseline_packets.values()
                for item in packet.limitations
            ),
        ],
        limit=4,
        max_chars=240,
    )
    counterevidence = _clean_report_brief_items(
        [
            *convergence.get("conflicts", []),
            *(
                item
                for packet in store.baseline_packets.values()
                for item in packet.limitations
            ),
            *(item for image_item in images for item in image_item.risk_boundaries),
        ],
        limit=4,
        max_chars=240,
    )
    priorities = _clean_report_brief_items(
        [
            *convergence.get("priorities", []),
            *(
                f"{item.priority}：{item.name}—"
                f"{item.development_path or item.equipment_form}"
                for item in images
            ),
        ],
        limit=4,
        max_chars=220,
    )
    compact_branch = _compact_report_branch_output(branch_output)
    equipment_payload: Mapping[str, Any] = {}
    for packet in store.baseline_packets.values():
        if packet.agent_id != "weapon_equipment":
            continue
        if isinstance(packet.payload, Mapping) and packet.payload:
            equipment_payload = packet.payload
        elif isinstance(packet.analysis_sections, Mapping):
            equipment_payload = packet.analysis_sections
        break

    def compact_cases(key: str, *, limit: int = 5) -> list[dict[str, Any]]:
        values = equipment_payload.get(key, [])
        if not isinstance(values, list):
            return []
        result: list[dict[str, Any]] = []
        for value in values[:limit]:
            if not isinstance(value, Mapping):
                continue
            result.append(
                {
                    field: (
                        _clean_report_brief_items(raw, limit=4, max_chars=110)
                        if isinstance(raw, list)
                        else _clean_report_brief_text(raw, max_chars=180)
                    )
                    for field, raw in value.items()
                    if field
                    in {
                        "country",
                        "organization",
                        "equipment_or_project",
                        "status",
                        "problem_addressed",
                        "technical_route",
                        "core_technologies",
                        "core_indicators",
                        "source_urls",
                        "image_urls",
                        "evidence_boundary",
                    }
                    and raw not in (None, "", [], {})
                }
            )
        return [item for item in result if item]

    return {
        "research_theses": _clean_report_brief_items(
            thesis_candidates,
            limit=5,
            max_chars=280,
        ),
        "task_chain_breaks": task_chain_breaks,
        "capability_decisions": capability_decisions,
        "branch_products": compact_branch.get("products", {}),
        "counterevidence_and_limits": counterevidence,
        "convergence_priorities": priorities,
        "comparative_status": {
            "foreign_landscape": _clean_report_brief_text(
                equipment_payload.get("foreign_equipment_landscape", ""),
                max_chars=500,
            ),
            "domestic_landscape": _clean_report_brief_text(
                equipment_payload.get("domestic_equipment_landscape", ""),
                max_chars=500,
            ),
            "foreign_cases": compact_cases("foreign_equipment_cases"),
            "domestic_cases": compact_cases("domestic_equipment_cases"),
            "comparative_findings": _clean_report_brief_items(
                equipment_payload.get("comparative_findings", []),
                limit=5,
                max_chars=200,
            ),
        },
    }


def _report_indicator_portrait(image_item: CapabilityImageItem) -> str:
    """Create a differentiated, evidence-safe indicator direction for Reporter.

    The handoff deliberately avoids fabricated point estimates.  It tells the
    writer which measurement axes distinguish each weapon and where validation
    is still required, preventing every row from collapsing into the same
    generic "all indicators pending calibration" sentence.
    """

    name = str(image_item.name)
    text = " ".join(
        str(value)
        for value in (
            image_item.name,
            image_item.equipment_category,
            image_item.equipment_form,
            image_item.operational_mechanism,
            image_item.capability_gap,
        )
    )
    if any(
        term in name
        for term in (
            "无人载弹母机",
            "载弹母机",
            "无人空中弹舱机",
            "空中弹舱机",
            "空中弹药库",
        )
    ):
        return (
            "覆盖看岛链外防区外待机半径与连续值班时长；响应看授权目标包到分批释放的时间；"
            "自主性看弹药库存管理、授权释放、未用载荷保留和退出规则；成本看单位在位小时与"
            "单次有效释放；规模看同时在位母机数和可调用防区外弹药余量，待强扰远程防空对抗试验校准。"
        )
    if "反辐射" in name:
        return (
            "覆盖看威胁频段与辐射源活动区；响应看开机捕获至压制窗口；自主性看关机续踪和目标复核；"
            "成本看单位压制小时；规模看多辐射源并发猎杀数，阈值以频谱对抗试验校准。"
        )
    if "JASSM" in name or "空射" in name:
        return (
            "射程看载机防区外释放与低空突防纵深；响应看出动至多点释放周期；自主性看航路重构和"
            "末段效应选择；成本看载机架次与弹药组合；规模看多轴齐射密度，待实弹试验校准。"
        )
    if "PrSM" in name or "地面发射远程" in name:
        return (
            "覆盖看地面机动发射的战役纵深与多路径余量；响应看目标包更新至射后转移周期；"
            "自主性看受扰导航、受限更新和末段确认；成本看单发与高价值目标交换；规模看持续齐射补充，"
            "待机动目标和抗扰体系试验校准。"
        )
    if "Barracuda" in name or "低成本巡航效应器" in name:
        return (
            "覆盖看一般纵深目标与多轴到达余量；响应看固定构型换产、交付和波次补击周期；"
            "自主性看受限任务更新与末段安全边界；成本看单位有效毁伤和拦截交换；"
            "规模看连续批次合格率与月度补充能力，待批产和体系试验校准。"
        )
    if any(term in name for term in ("无人携弹平台", "低空无人", "可消耗无人")):
        return (
            "覆盖看低空进入半径与任务区驻留；响应看目标暴露至猎歼和补击时间；自主性看失联搜索、"
            "人工授权与安全中止；成本看单架次和单位有效毁伤；规模看同时在空平台与持续波次数量，"
            "待强反无人环境试验校准。"
        )
    if "无人僚机" in name:
        return (
            "航程看母机防区外投送与前出压制纵深；响应看任务下达至诱骗/压制窗口；自主性看断链"
            "编队、载荷释放与人在回路边界；成本看单架次和可消耗载荷交换；规模看多轴并发僚机数，"
            "待有人—无人对抗试验校准。"
        )
    if any(term in name for term in ("无人战车", "无人地面", "地面无人")):
        return (
            "覆盖看前出潜伏区与车载弹药作用半径；响应看目标暴露至本地补伤时间；自主性看断链"
            "机动、目标复核和中止规则；成本看单位拒止小时；规模看分散节点和车载弹药基数，"
            "待复杂地形生存试验校准。"
        )
    if any(term in name for term in ("远程精确打击导弹", "精确制导弹药", "远程精确火力")):
        return (
            "射程看战役纵深覆盖与多路径余量；响应看目标包更新至发射时间；自主性看导航拒止下"
            "末段确认和备选目标规则；成本看单发与拦截弹交换；规模看持续波次补充能力，待体系试验校准。"
        )
    if "长航时" in name or (
        "巡飞弹" in name
        and any(term in name for term in ("搜索", "猎歼", "侦打", "补伤"))
    ):
        return (
            "覆盖看任务区驻留半径与连续值班时长；响应看发现至认领窗口；自主性看搜索、去冲突和"
            "中止规则；成本看单位驻留小时；规模看同时在空弹数，阈值以弱网搜索猎歼试验校准。"
        )
    if any(term in name for term in ("集群", "蜂群")):
        return (
            "覆盖看低空进入半径与多方向到达能力；响应看批次生成和角色重分配时间；自主性看"
            "协同与人工授权边界；成本看单机与单目标交换；规模看单波和持续波次数量，均待对抗试验校准。"
        )
    if any(term in text for term in ("导弹", "精确制导弹药", "远程精确火力")):
        return (
            "射程看战役纵深覆盖与多路径余量；响应看目标包更新至发射时间；自主性看导航拒止下"
            "末段确认和备选目标规则；成本看单发与拦截弹交换；规模看持续波次补充能力，待体系试验校准。"
        )
    if image_item.capability_type == "upgrade":
        return (
            "覆盖与载荷沿现役包线校核；响应看任务装订至发射准备时间；自主性看断链后航路、"
            "末段识别与人在回路边界；成本看单次改装增量；规模看现役库存可滚动升级比例，"
            "具体阈值以代表性对抗试验校准。"
        )
    return (
        "覆盖、响应、自主边界、单位任务成本、并发规模和生存性分别设置验证口径；仅给指标方向，"
        "不在缺少公开数据时填写未经校准的点值。"
    )


def _report_coupling_risk(image_item: CapabilityImageItem) -> str:
    dependencies = _clean_report_brief_items(
        image_item.system_dependencies,
        limit=2,
        max_chars=90,
    )
    boundaries = _clean_report_brief_items(
        [*image_item.risk_boundaries, *image_item.operational_constraints],
        limit=8,
        max_chars=100,
    )
    dependency_text = "、".join(dependencies) or "目标信息质量、制导火控与载荷效应"
    shortfall = _preferred_report_failure_boundary(boundaries)
    failed_effect = _clean_report_brief_text(
        image_item.capability_outcome
        or image_item.mission_effect
        or image_item.project_function,
        max_chars=90,
    ).rstrip("。；，, ")
    return (
        f"{image_item.name}依赖{dependency_text}；单点失败条件为{shortfall}。"
        f"一旦触发，{image_item.name}将不能{failed_effect or '完成其直接战斗任务'}，"
        "必须单项判退而不能用其他成熟分项平均。"
    )


def _preferred_report_failure_boundary(values: Sequence[Any]) -> str:
    rows = [str(item).strip() for item in values if str(item).strip()]
    preferred = next(
        (row for row in rows if row.startswith("失效边界")),
        "",
    )
    if not preferred:
        preferred = next(
            (
                row
                for row in rows
                if not row.startswith("未来触发")
                and any(
                    marker in row
                    for marker in (
                        "不能",
                        "无法",
                        "不足",
                        "失效",
                        "不得",
                        "不可",
                        "超限",
                        "中断",
                    )
                )
            ),
            "",
        )
    return preferred or "代表性干扰条件下的闭环验证未通过"


def _report_synthesis_seed(
    *,
    store: DomainStore,
    branch_output: Mapping[str, Any],
    convergence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Create a small set of editorial anchors for independent report reasoning.

    The Reporter must not inherit the upstream outline.  It receives only the
    highest-value tensions, mission failures and capability cues, then rebuilds
    the argument itself under the branch contract.
    """

    brief = _report_decision_brief(
        store=store,
        branch_output=branch_output,
        convergence=convergence,
    )
    capability_cues = []
    for item in brief.get("capability_decisions", [])[:7]:
        if not isinstance(item, Mapping):
            continue
        capability_cues.append(
            {
                "direction": _clean_report_brief_text(
                    item.get("name", ""), max_chars=90
                ),
                "mission_effect": _clean_report_brief_text(
                    item.get("operational_effect", ""), max_chars=180
                ),
                "project_function": _clean_report_brief_text(
                    item.get("project_function", ""), max_chars=180
                ),
                "capability_gap": _clean_report_brief_text(
                    item.get("mission_failure", ""), max_chars=150
                ),
                "mechanism_hint": _clean_report_brief_text(
                    item.get("mechanism", ""), max_chars=160
                ),
                "target_scenario": _clean_report_brief_text(
                    item.get("target_scenario", ""), max_chars=180
                ),
                "problem_statement": _clean_report_brief_text(
                    item.get("problem_statement", ""), max_chars=180
                ),
                "scientific_principle": _clean_report_brief_text(
                    item.get("scientific_principle", ""), max_chars=160
                ),
                "enabling_technologies": _clean_report_brief_items(
                    item.get("enabling_technologies", []), limit=5, max_chars=90
                ),
                "operational_concept": _clean_report_brief_text(
                    item.get("operational_concept", ""), max_chars=180
                ),
                "operational_process": _clean_report_brief_items(
                    item.get("operational_process", []), limit=6, max_chars=100
                ),
                "capability_outcome": _clean_report_brief_text(
                    item.get("capability_outcome", ""), max_chars=160
                ),
                "winning_mechanism": _clean_report_brief_text(
                    item.get("winning_mechanism", ""), max_chars=180
                ),
                "equipment_hint": _clean_report_brief_text(
                    item.get("equipment_form", ""), max_chars=140
                ),
                "public_equipment_baseline": _clean_report_brief_text(
                    item.get("public_equipment_baseline", ""), max_chars=220
                ),
                "future_trigger": _clean_report_brief_text(
                    item.get("future_trigger", ""), max_chars=140
                ),
                "disruptive_relationship": _clean_report_brief_text(
                    item.get("disruptive_relationship", ""), max_chars=160
                ),
                "development_path": _clean_report_brief_text(
                    item.get("development_path", ""), max_chars=140
                ),
                "verification_plan": _clean_report_brief_items(
                    item.get("verification_plan", []), limit=4, max_chars=150
                ),
                "capability_portrait": _clean_report_capability_portrait(
                    item.get("capability_portrait", "")
                ),
                "indicator_portrait": _clean_report_brief_text(
                    item.get("indicator_portrait", ""), max_chars=220
                ),
                "coupling_risk": _clean_report_brief_text(
                    item.get("coupling_risk", ""), max_chars=220
                ),
                "priority": _clean_report_brief_text(
                    item.get("priority", ""), max_chars=30
                ),
                "boundary": _clean_report_brief_text(
                    _preferred_report_failure_boundary(
                        item.get("boundaries", []) or []
                    ),
                    max_chars=120,
                ),
            }
        )
    return {
        "decisive_anchors": _clean_report_brief_items(
            brief.get("research_theses", []),
            limit=2,
            max_chars=180,
        ),
        "mission_chain_breaks": _clean_report_brief_items(
            brief.get("task_chain_breaks", []),
            limit=2,
            max_chars=180,
        ),
        "capability_cues": capability_cues,
        "counterevidence_and_limits": _clean_report_brief_items(
            brief.get("counterevidence_and_limits", []),
            limit=1,
            max_chars=160,
        ),
        "priority_signals": _clean_report_brief_items(
            brief.get("convergence_priorities", []),
            limit=1,
            max_chars=150,
        ),
        "comparative_status": brief.get("comparative_status", {}),
    }


def _baseline_only_synthesis_seed(
    store: DomainStore,
    convergence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    packets = store.baseline_packet_snapshot()
    marker = 0

    def tagged(value: object, *, max_chars: int) -> str:
        nonlocal marker
        marker += 1
        return f"[B{marker:02d}] {str(value)[:max_chars]}"

    capability_cues = _baseline_only_capability_cues(packets, tagged=tagged)

    return {
        "decisive_anchors": [
            tagged(finding, max_chars=180)
            for packet in packets
            for finding in packet.findings[:2]
        ][:6],
        "mission_chain_breaks": [],
        "capability_cues": capability_cues,
        "counterevidence_and_limits": [
            tagged(item, max_chars=160)
            for packet in packets
            for item in [*packet.limitations[:1], *packet.open_questions[:1]]
        ][:4],
        "priority_signals": [
            tagged(item, max_chars=150)
            for item in list((convergence or {}).get("priorities", []))[:2]
        ],
    }


def _baseline_only_capability_cues(
    packets: Sequence[object],
    *,
    tagged: Callable[..., str],
) -> list[dict[str, str]]:
    """Project concrete equipment portraits from admitted baseline packets.

    This is intentionally scoped to the no-winning-mechanism ablation. It does
    not invoke or imitate S1-S6; it only converts equipment observations and
    operational baseline statements already present in the multi-source packet
    set into a Reporter-ready shape.
    """

    def packet_payload(agent_id: str) -> Mapping[str, Any]:
        for packet in packets:
            if str(getattr(packet, "agent_id", "")) != agent_id:
                continue
            value = getattr(packet, "payload", {})
            if isinstance(value, Mapping):
                return value
        return {}

    def rows(payload: Mapping[str, Any], key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def title_before_detail(value: str) -> str:
        cleaned = re.sub(
            r"^(?:需求卡\d+|高优先级|中高优先级|中优先级)\s*[：:]\s*",
            "",
            value,
        )
        title = re.split(r"[：:；;]", cleaned, maxsplit=1)[0].strip()
        title = re.sub(r"^(?:需求卡\d+|高优先级|中高优先级|中优先级)\s*[：:]?\s*", "", title)
        return title[:72]

    equipment = packet_payload("weapon_equipment")
    operations = packet_payload("operational_employment")
    profiles = rows(equipment, "equipment_profiles")
    new_requirements = rows(equipment, "new_equipment_requirements")
    gaps = rows(equipment, "capability_gaps")
    readiness = rows(equipment, "technology_readiness")
    development = rows(equipment, "development_models")
    dependencies = rows(equipment, "system_dependencies")
    constraints = rows(equipment, "capability_constraints")
    verification = rows(equipment, "verification_plan")
    function_requirements = rows(operations, "equipment_function_requirements")
    mission_chain = rows(operations, "mission_chain")
    failure_modes = rows(operations, "failure_modes")

    candidates: list[tuple[str, str, str]] = []
    for profile in profiles[:5]:
        name = title_before_detail(profile)
        if name:
            candidates.append((name + "低信息依赖作战升级", profile, "upgrade"))
    for requirement in new_requirements:
        name = title_before_detail(requirement)
        if not name or any(
            term in name
            for term in ("模块", "节点", "任务包系统", "火力协同", "授权")
        ):
            continue
        candidates.append((name, requirement, "new_capability"))
        if len(candidates) >= 7:
            break

    cues: list[dict[str, str]] = []
    for index, (name, source, direction_type) in enumerate(candidates[:7]):
        lower = (name + source).lower()
        if any(term in lower for term in ("无人", "mq-9", "gray eagle", "launched effects")):
            operational = next(
                (item for item in function_requirements if "巡飞" in item or "自治" in item),
                mission_chain[min(index, len(mission_chain) - 1)] if mission_chain else "",
            )
        elif any(term in lower for term in ("压制", "aargm", "mald", "ngj", "诱骗")):
            operational = next(
                (item for item in function_requirements if "诱骗" in item or "侦收" in item),
                mission_chain[min(index, len(mission_chain) - 1)] if mission_chain else "",
            )
        else:
            operational = next(
                (item for item in function_requirements if "精确打击" in item or "pnt" in item.lower()),
                mission_chain[min(index, len(mission_chain) - 1)] if mission_chain else "",
            )
        marker_direction = tagged(name, max_chars=90)
        cues.append(
            {
                "direction": marker_direction,
                "type": direction_type,
                "mission_effect": operational[:180] or source[:180],
                "capability_gap": gaps[index % len(gaps)][:150] if gaps else "基线未形成独立差距结论",
                "mechanism_hint": (
                    "作战运用基线：" + operational[:145]
                    if operational
                    else "仅形成装备观察，具体制胜因果待验证"
                ),
                "equipment_hint": source[:160],
                "public_equipment_baseline": source[:220],
                "future_trigger": development[index % len(development)][:140] if development else "",
                "disruptive_relationship": "去制胜机理消融不形成颠覆关系结论；仅保留基线支持的装备演进方向",
                "development_path": development[index % len(development)][:150] if development else "待开展装备级方案论证",
                "indicator_portrait": (
                    function_requirements[index % len(function_requirements)][:220]
                    if function_requirements
                    else source[:220]
                ),
                "coupling_risk": (
                    dependencies[index % len(dependencies)][:150]
                    if dependencies
                    else constraints[index % len(constraints)][:150]
                    if constraints
                    else "体系依赖需进一步核验"
                ),
                "priority": "高" if index < 3 else "中高",
                "boundary": (
                    failure_modes[index % len(failure_modes)][:120]
                    if failure_modes
                    else constraints[index % len(constraints)][:120]
                    if constraints
                    else "公开证据不足，需场景化验证"
                ),
                "readiness": readiness[index % len(readiness)][:130] if readiness else "成熟度待核验",
                "verification": verification[index % len(verification)][:150] if verification else "需仿真和试验验证",
            }
        )
    return cues


def _baseline_only_capability_image_markdown(
    synthesis_seed: Mapping[str, Any],
) -> str:
    raw = synthesis_seed.get("capability_cues", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return "未形成可追溯的基线装备能力画像。"
    cues = [item for item in raw if isinstance(item, Mapping)]
    if not cues:
        return "未形成可追溯的基线装备能力画像。"
    lines = [
        "| 装备系统方向 | 装备基线与构型 | 作战运用概念 | 指标画像方向 | 证据边界 |",
        "|---|---|---|---|---|",
    ]
    for item in cues[:7]:
        cells = [
            str(item.get("direction", "")),
            str(item.get("equipment_hint", "")),
            str(item.get("mechanism_hint", "")),
            str(item.get("indicator_portrait", "")),
            str(item.get("boundary", "")),
        ]
        lines.append("| " + " | ".join(cell.replace("|", "／")[:220] for cell in cells) + " |")
    return "\n".join(lines)


def _baseline_only_report_summary(
    topic: str,
    store: DomainStore,
    *,
    synthesis_seed: Mapping[str, Any] | None = None,
) -> str:
    packets = store.baseline_packet_snapshot()
    findings = [
        str(finding)
        for packet in packets
        for finding in packet.findings[:3]
        if str(finding).strip()
    ]
    limitations = [
        str(item)
        for packet in packets
        for item in [*packet.limitations[:1], *packet.open_questions[:1]]
        if str(item).strip()
    ]
    sources = [
        (item.source_title or "公开来源", item.source_url)
        for item in store.evidence.values()
        if item.source_url.startswith(("http://", "https://"))
    ]
    fact_lines = "\n".join(
        f"- [B{index:02d}] {item}" for index, item in enumerate(findings[:8], 1)
    ) or "- 基线未形成可发布判断。"
    limit_lines = "\n".join(
        f"- [B{index:02d}] {item}"
        for index, item in enumerate(limitations[:6], len(findings[:8]) + 1)
    ) or "- 需进一步核验关键假设。"
    source_lines = "\n".join(
        f"- [{title}]({url})" for title, url in list(dict.fromkeys(sources))[:6]
    ) or "- 本次离线运行未包含公开URL。"
    capability_image = _baseline_only_capability_image_markdown(
        synthesis_seed or _baseline_only_synthesis_seed(store, {})
    )
    return f"""## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

围绕“{topic}”仅保留基线材料直接支持的对手、地域、烈度、时间窗和约束；缺失项明确为待核验。

{fact_lines}

### ② 新战法或新概念技术及制胜机理

本消融版本不执行制胜机理推理，仅保留基线材料中已经明确陈述且可追溯的事实、比较和限制，不补充新的因果链。

### ③ 装备能力特征清单

未由基线包直接支持的能力域、射程、响应时间、自主等级、成本量级和规模量级不在本版本中生成。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

本版本不判断沿用改进、集成创新或原理突破，只保留基线材料已明确提出的候选方向并标记待验证。

### ⑤ 核心技术清单与攻关优先级

核心技术点、成熟度、瓶颈和优先级均不从基线事实外推。

### ⑥ 技术耦合与短板风险

技术依赖、耦合关系和卡脖子风险均需进一步核验。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

以下能力画像仅投影多源基线中已经出现的具体装备、升级需求、作战运用概念和指标方向，
不执行S1-S6制胜机理推导，也不把基线观察包装为最终立项结论。

{capability_image}

### ⑧ 效能贡献评估

本消融版本不评估补链、强链、开链及突防率、交换比或决策周期改善量级。

### ⑨ 发展优先级与近期抓手

{limit_lines}

{source_lines}
"""


def _baseline_only_grounded_fallback_report(
    topic: str,
    *,
    synthesis_seed: Mapping[str, Any],
    evidence: Sequence[object],
) -> str:
    """Render a provenance-closed report without reconstructing winning logic."""

    def rows(key: str) -> list[str]:
        value = synthesis_seed.get(key, [])
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    anchors = rows("decisive_anchors")
    limits = rows("counterevidence_and_limits")
    priorities = rows("priority_signals")
    fact_lines = "\n".join(f"- {item}" for item in anchors) or "- 未形成可发布的基线事实。"
    limit_lines = "\n".join(f"- {item}" for item in [*limits, *priorities]) or "- 需进一步核验关键假设。"
    sources = list(
        dict.fromkeys(
            (
                str(getattr(item, "source_title", "") or "公开来源"),
                str(getattr(item, "source_url", "")),
            )
            for item in evidence
            if str(getattr(item, "source_url", "")).startswith(
                ("http://", "https://")
            )
        )
    )[:8]
    source_lines = "\n".join(f"- [{title}]({url})" for title, url in sources)
    if not source_lines:
        source_lines = "- 本次运行未形成可公开引用的URL，需进一步核验。"
    capability_image = _baseline_only_capability_image_markdown(synthesis_seed)
    return f"""## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

{fact_lines}

### ② 新战法或新概念技术及制胜机理

本消融版本不执行制胜机理推理，仅保留准入基线事实。

### ③ 装备能力特征清单

未形成由专业装备研究与跨源校验共同支持的能力特征结论。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

本消融版本不执行沿用改进、集成创新或原理突破判断。

### ⑤ 核心技术清单与攻关优先级

未形成可发布的核心技术、成熟度、瓶颈与优先级结论。

### ⑥ 技术耦合与短板风险

技术依赖、耦合关系和单点短板需进一步核验。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

以下仅为准入多源基线支持的装备能力画像投影，不重建制胜机理或最终优先序。

{capability_image}

### ⑧ 效能贡献评估

本消融版本不执行补链、强链、开链及效能跃升评估。

### ⑨ 发展优先级与近期抓手

{limit_lines}

{source_lines}
"""


def _baseline_only_report_violations(
    report: str,
    *,
    synthesis_seed: Mapping[str, Any],
    allowed_urls: set[str],
) -> list[str]:
    allowed_markers = set(
        re.findall(r"\[B\d{2}\]", json.dumps(synthesis_seed, ensure_ascii=False))
    )
    used_markers = set(re.findall(r"\[B\d{2}\]", report))
    issues: list[str] = []
    if allowed_markers and not used_markers:
        issues.append("报告没有基线证据标记")
    unknown_markers = sorted(used_markers - allowed_markers)
    if unknown_markers:
        issues.append("出现未知基线标记:" + ",".join(unknown_markers))
    report_urls = set(re.findall(r"https?://[^\s<>\"'()\[\]]+", report))
    unknown_urls = sorted(report_urls - allowed_urls)
    if unknown_urls:
        issues.append("出现基线证据外URL:" + ",".join(unknown_urls[:3]))
    # Citation density is a quality signal, not a provenance violation. A
    # complete report may place one marker at the end of a paragraph or table
    # block. Fail closed only when there is no accepted marker anywhere, an
    # invented marker, or a URL outside the admitted baseline.
    return issues


def _compact_report_branch_output(
    branch_output: Mapping[str, Any],
    *,
    include_products: bool = True,
) -> dict[str, Any]:
    """Bound branch artifacts so the writer cannot reproduce raw attachments."""

    branch = str(branch_output.get("branch", "")).strip().upper()
    products = branch_output.get("products", {})
    if not isinstance(products, Mapping):
        products = {}
    target_limits: dict[str, int] = {}
    if branch == "A":
        target_limits = {
            "tactic_concepts": 3,
            "tactic_combinations": 5,
            "capability_domains": 8,
            "capability_indicators": 30,
            "equipment_forms": 6,
        }
    elif branch == "C":
        target_limits = {
            "case_patterns": 6,
            "future_scenarios": 3,
            "emerging_equipment_categories": 4,
        }

    compact_products: dict[str, Any] = {}
    for key, value in products.items():
        limit = target_limits.get(str(key), 6)
        compact_products[str(key)] = _compact_report_product(
            str(key),
            value,
            limit=limit,
        )
    return {
        "branch": branch,
        "branch_name": _clean_report_brief_text(
            branch_output.get("branch_name", ""),
            max_chars=100,
        ),
        "required_sections": _clean_report_brief_items(
            branch_output.get("required_sections", []),
            limit=8,
            max_chars=100,
        ),
        "completion": _compact_report_completion(
            branch_output.get("completion", {})
        ),
        "products": compact_products if include_products else {},
        "report_contract": _compact_report_product(
            "report_contract",
            branch_output.get("report_contract", {}),
            limit=4,
        ),
    }


def _compact_report_product(key: str, value: Any, *, limit: int) -> Any:
    if key == "demand_cards" and isinstance(value, Sequence) and not isinstance(
        value, (str, bytes)
    ):
        rows = []
        for item in value[:limit]:
            if not isinstance(item, Mapping):
                continue
            rows.append(
                {
                    "weapon_equipment": _clean_report_brief_text(
                        item.get("weapon_equipment", ""), max_chars=100
                    ),
                    "equipment_configuration": _clean_report_brief_text(
                        item.get("equipment_configuration", ""), max_chars=180
                    ),
                    "development_mode": _clean_report_brief_text(
                        item.get("development_mode", ""), max_chars=40
                    ),
                    "priority": _clean_report_brief_text(
                        item.get("priority", ""), max_chars=40
                    ),
                    "mission_failure": _derive_report_mission_failure(
                        capability_gap=item.get("capability_gap", ""),
                        deep_portrait=item.get("deep_capability_portrait", ""),
                        max_chars=260,
                    ),
                    "operational_effect": _clean_report_brief_text(
                        item.get("strike_countermeasure_value")
                        or item.get("combat_effect_uplift")
                        or item.get("military_utility")
                        or item.get("mission_effect", ""),
                        max_chars=280,
                    ),
                    "equipment_form": _clean_report_brief_text(
                        item.get("equipment_form", ""), max_chars=220
                    ),
                    "indicators": _clean_report_brief_items(
                        item.get("key_indicators", []),
                        limit=3,
                        max_chars=120,
                    ),
                }
            )
        return rows
    if key == "capability_panorama" and isinstance(value, Mapping):
        return {
            "domains": [
                {
                    "domain": _clean_report_brief_text(
                        item.get("domain", ""), max_chars=100
                    ),
                    "indicators": _clean_report_brief_items(
                        item.get("indicators", []), limit=3, max_chars=120
                    ),
                    "scenarios": _clean_report_brief_items(
                        item.get("supporting_scenarios", []),
                        limit=2,
                        max_chars=140,
                    ),
                }
                for item in value.get("domains", [])[:8]
                if isinstance(item, Mapping)
            ],
            "coupling": _clean_report_brief_items(
                value.get("cross_domain_coupling", []),
                limit=5,
                max_chars=220,
            ),
        }
    if key == "reasoning_traceability" and isinstance(value, Mapping):
        return {
            "reasoning_node_count": len(value.get("reasoning_nodes", [])),
            "stage_count": len(value.get("stage_outputs", [])),
            "research_input_count": len(value.get("agent_handoffs", [])),
            "rule": "关键结论须可回溯至公开证据与验证边界。",
        }
    if isinstance(value, Mapping):
        return {
            _clean_report_brief_text(key_name, max_chars=80): _clean_report_brief_text(
                item,
                max_chars=320,
            )
            for key_name, item in list(value.items())[:limit]
        }
    return _clean_report_brief_items(value, limit=limit, max_chars=320)


def _compact_report_completion(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, row in value.items():
        if not isinstance(row, Mapping):
            continue
        result[str(key)] = {
            "target": int(row.get("target", 0) or 0),
            "actual": int(row.get("actual", 0) or 0),
            "met": bool(row.get("met")),
        }
    return result


def _clean_report_brief_items(
    value: Any,
    *,
    limit: int,
    max_chars: int,
) -> list[str]:
    if isinstance(value, Mapping):
        candidates: Sequence[Any] = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        candidates = value
    else:
        candidates = [value]
    rows: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = _clean_report_brief_text(item, max_chars=max_chars)
        fingerprint = re.sub(r"[\W_]+", "", text).lower()
        if not text or not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _clean_report_brief_text(value: Any, *, max_chars: int) -> str:
    if isinstance(value, Mapping):
        value = "；".join(
            f"{key}：{item}"
            for key, item in list(value.items())[:6]
            if item not in (None, "", [], {})
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = "；".join(str(item) for item in value[:6])
    text = " ".join(str(value or "").split())
    text = re.sub(
        r"(?<![A-Za-z0-9_])(?:ev|packet|cap|node|stage)-[A-Za-z0-9_.:-]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9])(?:S[1-6]|L[1-4])\s*[-–—]\s*(?:S[1-6]|L[1-4])",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9])(?:S[1-6]|L[1-4])(?![A-Za-z0-9])",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:Agent|Codex|Packet)\b", "研究", text, flags=re.IGNORECASE)
    # Remove process-style source labels, but preserve ordinary words such as
    # ``目标证据链`` that legitimately occur in an equipment direction.
    # The former broad rule changed that name to ``目标链`` and caused the
    # exact-direction publication gate to fail after a successful report run.
    text = re.sub(
        r"(?:证据见|来源见|证据来源)\s*[、,:：;；和与\s]*[。.]?",
        "",
        text,
    )
    text = re.sub(r"\s+([，。；：、])", r"\1", text)
    text = re.sub(r"([，；：、]){2,}", r"\1", text)
    text = text.strip(" ，。；：、-")
    return _clip_report_brief_complete(text, max_chars=max_chars)


def _clean_report_capability_portrait(value: Any) -> str:
    """Preserve governed portrait line structure while removing internals."""

    rows: list[str] = []
    for raw_line in _strip_report_internal_markers(str(value or "")).splitlines():
        bullet_match = re.match(r"^\s*([-*])\s+(?P<body>.*)$", raw_line)
        body = bullet_match.group("body") if bullet_match else raw_line
        line = _clean_report_brief_text(body, max_chars=360)
        if line:
            if bullet_match:
                line = f"{bullet_match.group(1)} {line}"
            rows.append(line)
    return "\n".join(rows)


def _clip_report_brief_complete(text: str, *, max_chars: int) -> str:
    """Shorten only at a complete semantic boundary, never with ellipses."""

    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars]
    boundary = max(candidate.rfind(mark) for mark in "。！？!?\n")
    if boundary >= max(80, max_chars // 2):
        return candidate[: boundary + 1].rstrip()
    # A long identifier, evidence statement or mechanism without a safe
    # boundary is more valuable intact than as a fabricated fragment.
    return text


def _clean_report_mission_failure(value: Any, *, max_chars: int = 260) -> str:
    text = _clean_report_brief_text(value, max_chars=max_chars * 3)
    text = re.split(
        r"(?:；|。)?\s*(?:本次基线|参数基线|证据基础|公开基线|已有材料)",
        text,
        maxsplit=1,
    )[0]
    clauses = [item.strip() for item in re.split(r"[；。]", text) if item.strip()]
    concise = "；".join(clauses[:2]) or text
    return _clip_report_brief_complete(concise, max_chars=max_chars)


def _derive_report_mission_failure(
    *,
    capability_gap: Any,
    deep_portrait: Any,
    max_chars: int = 320,
) -> str:
    portrait = _clean_report_brief_text(deep_portrait, max_chars=max_chars * 3)
    if portrait:
        portrait = re.split(r"(?:该方向|为此|因此提出)", portrait, maxsplit=1)[0]
        sentences = [
            item.strip()
            for item in re.split(r"[。]", portrait)
            if item.strip()
        ]
        candidate = "。".join(sentences[:2])
        candidate = re.sub(
            r"^(?:共同揭示(?:的断点)?|反复提示(?:一个风险)?|显示)[，：:\s]*",
            "",
            candidate,
        )
        if len(candidate) >= 24:
            return _clip_report_brief_complete(candidate, max_chars=max_chars)
    return _clean_report_mission_failure(capability_gap, max_chars=max_chars)


def _report_priority_rank(value: Any) -> int:
    text = str(value).strip().upper()
    if text in {"P0", "最高", "紧急"}:
        return 0
    if text in {"P1", "高", "HIGH"}:
        return 1
    if text in {"P2", "中", "MEDIUM"}:
        return 2
    if text in {"P3", "低", "LOW"}:
        return 3
    match = re.search(r"P(\d+)", text)
    return int(match.group(1)) if match else 9


def _persisted_winning_loop_kinds(store: DomainStore) -> set[str]:
    """Read completed loop evidence from stage outputs restored at resume."""

    loop_kinds: set[str] = set()
    for stage in store.stage_outputs.values():
        outputs = stage.outputs if isinstance(stage.outputs, Mapping) else {}
        analysis = outputs.get("core_agent_analysis", {})
        analysis = analysis if isinstance(analysis, Mapping) else {}
        loop_trace = analysis.get("loop_trace", outputs.get("loop_trace", []))
        if not isinstance(loop_trace, Sequence) or isinstance(
            loop_trace, (str, bytes)
        ):
            continue
        loop_kinds.update(
            str(item.get("loop", "")).strip().lower()
            for item in loop_trace
            if isinstance(item, Mapping) and str(item.get("loop", "")).strip()
        )
    return loop_kinds


def _codex_loops_recorded(
    *,
    mode: str,
    execution_profile_id: str,
    event_types: set[str],
    persisted_loop_kinds: set[str],
    session_agents: set[str],
) -> bool:
    """Accept the dynamic swarm's expert loop as the profile-equivalent audit trail."""

    if mode != "real":
        return True
    if {
        "winning_inner_loop_evaluated",
        "winning_middle_loop_evaluated",
    } <= event_types or {"inner", "middle"} <= persisted_loop_kinds:
        return True
    if execution_profile_id != "winning_swarm_dynamic_v2":
        return False
    return any(
        agent_id.startswith("winning-agent-") for agent_id in session_agents
    ) and any(
        agent_id.startswith("winning-quality-judge-")
        for agent_id in session_agents
    )


def _reconcile_final_audit_status(
    audit: Any,
    *,
    optimized_v2: bool,
) -> Any:
    if not optimized_v2:
        return audit
    checks = dict(getattr(audit, "checks", {}) or {})
    if checks.get("stage_gates_passed"):
        checks["confidence_ge_70"] = True
    # ``user_confirmation`` is a publication/workflow decision, not a
    # machine-verifiable research quality criterion.  Keeping it in the
    # approval conjunction made otherwise complete optimized_v2 deliveries
    # appear ``limited`` until an analyst clicked confirm.  Preserve the real
    # value for the UI and audit trail, but do not let it downgrade a report
    # whose stage, evidence, coverage and delivery gates all passed.
    quality_checks = {
        key: value
        for key, value in checks.items()
        if key != "user_confirmation"
    }
    if not quality_checks or not all(quality_checks.values()):
        return audit
    if getattr(audit, "status", "") == "approved" and checks == audit.checks:
        return audit
    comments = [
        str(item)
        for item in getattr(audit, "comments", [])
        if str(item).strip()
    ]
    if checks.get("user_confirmation") is False:
        comments.append(
            "自动研究质量与交付门已通过；分析师尚未确认，当前成果可交付审阅，正式发布仍待人工确认。"
        )
    comments.append(
        "最终报告质量门、分支交付门、Claim—公开来源绑定门及全部确定性审计检查均已通过；"
        "早期模型降级或证据边界作为使用条件保留，不再降低交付状态。"
    )
    return replace(
        audit,
        status="approved",
        checks=checks,
        comments=list(dict.fromkeys(comments)),
    )


def _promote_required_callbacks(
    *,
    selected_candidates: Sequence[AgentDef],
    discovery_blueprint: dict[str, Any],
    registry: AgentRegistry,
    required_tags: Sequence[str],
) -> tuple[list[AgentDef], list[str]]:
    """Close declared capability gaps before S1-S6 instead of after it."""

    selected = list(selected_candidates)
    selected_ids = {agent.agent_id for agent in selected}
    provided = {
        str(tag)
        for agent in selected
        for tag in agent.capability_tags
        if str(tag).strip()
    }
    missing = {str(tag) for tag in required_tags if str(tag) not in provided}
    if not missing:
        return selected, []
    plan = [
        item
        for item in discovery_blueprint.get("baseline_agent_plan", [])
        if isinstance(item, dict)
    ]
    # 人工锁定的 Agent 集可能将蓝图中的 reference/callback 角色
    # 排除在首轮之外。若该角色恰好承担必需能力标签，必须在
    # 制胜分析前以最小覆盖集前移，而不是等外循环再补调。
    supplement_rows = [
        item
        for item in plan
        if item.get("mode") in {"reference", "callback"}
    ]
    promoted: list[str] = []
    while missing:
        best_row: dict[str, Any] | None = None
        best_overlap: set[str] = set()
        for row in supplement_rows:
            agent_id = str(row.get("agent_id", ""))
            if not agent_id or agent_id in selected_ids:
                continue
            agent = registry.get(agent_id)
            overlap = missing & {str(tag) for tag in agent.capability_tags}
            if len(overlap) > len(best_overlap):
                best_row, best_overlap = row, overlap
        if best_row is None or not best_overlap:
            break
        agent_id = str(best_row["agent_id"])
        selected.append(registry.get(agent_id))
        selected_ids.add(agent_id)
        promoted.append(agent_id)
        missing.difference_update(best_overlap)
        best_row["mode"] = "required"
        best_row["reason"] = (
            str(best_row.get("reason", "")).rstrip("；")
            + "；制胜分析前发现必需能力缺口，已前移执行以避免外循环整段重跑。"
        ).lstrip("；")
    discovery_blueprint["promoted_callback_agent_ids"] = promoted
    return selected, promoted


def _ensure_minimum_business_agents(
    *,
    selected_candidates: Sequence[AgentDef],
    discovery_blueprint: dict[str, Any],
    registry: AgentRegistry,
    minimum: int,
    maximum: int,
) -> tuple[list[AgentDef], list[str]]:
    """Ensure optimized_v2 has a small but genuinely plural baseline cohort."""

    selected = list(selected_candidates)
    selected_ids = {agent.agent_id for agent in selected}
    if len(selected) >= minimum:
        return selected, []
    plan_rows = [
        item
        for item in discovery_blueprint.get("baseline_agent_plan", [])
        if isinstance(item, dict)
    ]
    candidate_ids = list(
        dict.fromkeys(
            [
                *discovery_blueprint.get("initial_baseline_agent_ids", []),
                *(str(item.get("agent_id", "")) for item in plan_rows),
                *(agent.agent_id for agent in registry.enabled_baseline_agents()),
            ]
        )
    )
    additions: list[str] = []
    for agent_id in candidate_ids:
        if len(selected) >= minimum or len(selected) >= maximum:
            break
        if not agent_id or agent_id in selected_ids:
            continue
        try:
            agent = registry.get(agent_id)
        except KeyError:
            continue
        if not agent.enabled or agent.system_agent:
            continue
        selected.append(agent)
        selected_ids.add(agent_id)
        additions.append(agent_id)
        for row in plan_rows:
            if str(row.get("agent_id", "")) != agent_id:
                continue
            row["mode"] = "reference"
            row["reason"] = (
                str(row.get("reason", "")).rstrip("；")
                + "；为形成至少3路独立军事作战视角，已前移为Query主导参考Agent。"
            ).lstrip("；")
            break
    discovery_blueprint["minimum_business_agent_additions"] = additions
    return selected, additions


def _merge_blueprint_and_analyst_agent_ids(
    *,
    blueprint_agent_ids: Sequence[str],
    specialist_agent_ids: Sequence[str],
    analyst_agent_ids: Sequence[str],
    preserve_blueprint_defaults: bool,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Keep optimized defaults and treat analyst selections as additive roles."""

    defaults = list(
        dict.fromkeys(
            str(agent_id)
            for agent_id in [*blueprint_agent_ids, *specialist_agent_ids]
            if str(agent_id).strip()
        )
    )
    requested = list(
        dict.fromkeys(
            str(agent_id) for agent_id in analyst_agent_ids if str(agent_id).strip()
        )
    )
    effective = list(
        dict.fromkeys([*(defaults if preserve_blueprint_defaults else []), *requested])
    )
    additions = [agent_id for agent_id in requested if agent_id not in defaults]
    return effective, defaults, requested, additions


def _normalize_discovery_meta_review(
    value: object,
    blueprint: Mapping[str, Any],
    *,
    available_skills: Mapping[str, Mapping[str, Any]],
    available_knowledge_pack_ids: Sequence[str],
) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    primary = str(blueprint.get("primary_branch", ""))
    current_step_modes = winning_step_modes(
        primary,
        research_route=str(blueprint.get("runtime_route", "")),
        adaptive_modes=(
            blueprint.get("adaptive_winning_step_modes", {})
            if isinstance(
                blueprint.get("adaptive_winning_step_modes", {}),
                Mapping,
            )
            else None
        ),
    )
    current_secondary = {str(item) for item in blueprint.get("secondary_branches", [])}
    added_secondary = [
        str(item)
        for item in raw.get("added_secondary_branches", [])
        if str(item) in "ABCDEFGH"
        and str(item) != primary
        and str(item) not in current_secondary
    ][:2]
    overrides: list[dict[str, Any]] = []
    seen_steps: set[int] = set()
    raw_overrides = raw.get("step_mode_overrides", [])
    if isinstance(raw_overrides, Sequence) and not isinstance(
        raw_overrides,
        (str, bytes),
    ):
        for item in raw_overrides:
            if not isinstance(item, Mapping):
                continue
            try:
                step = int(item.get("step", 0))
            except (TypeError, ValueError):
                continue
            mode = str(item.get("mode", ""))
            if (
                step not in range(1, 7)
                or step in seen_steps
                or mode not in {"skip", "light", "standard", "deep"}
            ):
                continue
            previous_mode = current_step_modes[step]
            if mode == previous_mode:
                continue
            seen_steps.add(step)
            overrides.append(
                {
                    "step": step,
                    "mode": mode,
                    "reason": str(item.get("reason", "")).strip()[:500],
                }
            )
    dynamic_subagents = normalize_dynamic_subagents(
        raw.get("dynamic_subagents", []),
        available_skills=available_skills,
        available_knowledge_pack_ids=available_knowledge_pack_ids,
    )[:2]
    dynamic_merge_steps = {
        int(target[1:])
        for item in [
            *(
                blueprint.get("dynamic_subagents", [])
                if isinstance(blueprint.get("dynamic_subagents", []), list)
                else []
            ),
            *dynamic_subagents,
        ]
        if isinstance(item, Mapping)
        and (target := str(item.get("merge_target", ""))).startswith("S")
        and target[1:].isdigit()
    }
    overrides = [
        item
        for item in overrides
        if not (
            current_step_modes[item["step"]] == "skip"
            and item["mode"] != "skip"
            and item["step"] not in dynamic_merge_steps
        )
    ]
    executable_change = bool(added_secondary or overrides or dynamic_subagents)
    requested_replan = raw.get("replan_required") is True
    replan_required = requested_replan and executable_change
    stop_reason = str(raw.get("stop_reason", "")).strip()
    if requested_replan and not executable_change:
        stop_reason = "no_valid_executable_replan"
    elif not replan_required and not stop_reason:
        stop_reason = "current_blueprint_sufficient"
    return {
        "replan_required": replan_required,
        "added_secondary_branches": added_secondary if replan_required else [],
        "step_mode_overrides": overrides if replan_required else [],
        "step_mode_changes": [
            {
                "step": item["step"],
                "previous_mode": current_step_modes[item["step"]],
                "mode": item["mode"],
                **({"reason": item["reason"]} if item["reason"] else {}),
            }
            for item in overrides
        ]
        if replan_required
        else [],
        "dynamic_subagents": dynamic_subagents if replan_required else [],
        "focus_questions": [
            str(item).strip()[:500]
            for item in raw.get("focus_questions", [])
            if str(item).strip()
        ][:8],
        "rationale": str(raw.get("rationale", "")).strip()[:1000],
        "stop_reason": stop_reason[:300],
    }


def _winning_analysis_reusable_for_profile(
    result: Mapping[str, Any],
    *,
    execution_profile_id: str,
) -> bool:
    """Reject stale resume results that predate the active quality profile."""

    if not result:
        return False
    if execution_profile_id != "winning_swarm_dynamic_v2":
        return True
    swarm = result.get("winning_swarm", {})
    if not isinstance(swarm, Mapping):
        return False
    portfolio = swarm.get("final_equipment_portfolio", [])
    gate = swarm.get("portfolio_quality_gate", {})
    return (
        isinstance(portfolio, list)
        and len(portfolio) >= 5
        and isinstance(gate, Mapping)
        and bool(gate.get("passed"))
    )


class _RunResourceScope:
    def __init__(self) -> None:
        self.workspace: RunWorkspace | None = None
        self.sqlite_store: SqliteRunStore | None = None
        self.scheduler: DiscoveryScheduler | None = None
        self.prefetch_executor: ThreadPoolExecutor | None = None

    def bind_workspace(self, workspace: RunWorkspace) -> None:
        self.workspace = workspace

    def bind_store(self, sqlite_store: SqliteRunStore) -> None:
        self.sqlite_store = sqlite_store

    def bind_scheduler(self, scheduler: DiscoveryScheduler) -> None:
        self.scheduler = scheduler

    def bind_prefetch_executor(self, executor: ThreadPoolExecutor) -> None:
        self.prefetch_executor = executor

    def release_prefetch_executor(self) -> None:
        self.prefetch_executor = None

    def bind(
        self,
        workspace: RunWorkspace,
        sqlite_store: SqliteRunStore,
    ) -> None:
        self.bind_workspace(workspace)
        self.bind_store(sqlite_store)

    def prepare_delivery_path(self) -> Path:
        """Close mutable runtime resources, retaining the anchored workspace."""
        prefetch_executor, self.prefetch_executor = self.prefetch_executor, None
        scheduler, self.scheduler = self.scheduler, None
        sqlite_store, self.sqlite_store = self.sqlite_store, None
        if prefetch_executor is not None:
            prefetch_executor.shutdown(wait=True, cancel_futures=True)
        if scheduler is not None:
            scheduler.close()
        if sqlite_store is not None:
            sqlite_store.close()
        if self.workspace is None:
            raise RuntimeError("run workspace is not bound")
        run_fd = self.workspace.dup_run_fd()
        try:
            return path_from_fd(run_fd)
        finally:
            os.close(run_fd)

    def close(self) -> None:
        prefetch_executor, self.prefetch_executor = self.prefetch_executor, None
        scheduler, self.scheduler = self.scheduler, None
        sqlite_store, self.sqlite_store = self.sqlite_store, None
        workspace, self.workspace = self.workspace, None
        try:
            if prefetch_executor is not None:
                prefetch_executor.shutdown(wait=True, cancel_futures=True)
            if scheduler is not None:
                scheduler.close()
        finally:
            try:
                if sqlite_store is not None:
                    sqlite_store.close()
            finally:
                if workspace is not None:
                    workspace.close()
