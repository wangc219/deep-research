from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import re
from statistics import mean
from typing import Any

from equipment_deep_research.domain.models import (
    AgentRecommendation,
    BaselineFindingPacket,
    CapabilityImageItem,
    RecallRequest,
    TraceEvent,
    WinningMechanismInput,
    WinningMechanismStageOutput,
    to_plain,
)
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.orchestration.capability_military_value import (
    military_capability_profile,
    rewrite_capability_for_military_value,
)
from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.domain.capability_portrait import (
    CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION,
    assemble_capability_portrait_modules,
    build_agent_led_capability_portrait,
    build_capability_title,
    capability_portrait_module_lengths,
    normalize_capability_portrait_modules,
    normalize_capability_portrait_text,
    normalize_capability_problem,
    normalize_operational_process,
    normalize_verification_plan,
)
from equipment_deep_research.orchestration.capability_confidence import (
    calibrate_capability_confidence,
)
from equipment_deep_research.orchestration.winning_reasoning import (
    SixStepReasoner,
    WinningResourceProjector,
)


_EXACT_PERFORMANCE_CLAIM = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|％|百分比|公里|千米|米|秒|分钟|小时)|"
    r"(?:提升|提高|缩短|降低|达到|超过|不少于|不低于)\s*\d+(?:\.\d+)?)"
)


def _has_unsupported_exact_performance_claim(direction: Mapping[str, Any]) -> bool:
    claim_text = " ".join(
        str(direction.get(field, ""))
        for field in (
            "function",
            "military_value",
            "operational_mechanism",
            "combat_effect_uplift",
            "strike_countermeasure_value",
            "capability_portrait",
        )
    )
    if not _EXACT_PERFORMANCE_CLAIM.search(claim_text):
        return False
    calibration_text = " ".join(
        str(direction.get(field, ""))
        for field in (
            "verification",
            "failure_boundary",
            "uncertainty_boundary",
            "combat_effect_uplift",
            "capability_portrait",
        )
    )
    return not any(
        marker in calibration_text
        for marker in (
            "公开证据",
            "未经校准",
            "需验证",
            "需要验证",
            "待验证",
            "不能给出",
            "不作承诺",
            "假设",
            "区间",
        )
    )


def _s6_validation_backlog_readiness(
    model_analysis: dict[str, Any] | None,
    evidence_ids: list[str],
) -> tuple[bool, list[str]]:
    """Collect S6 evidence/calibration backlog without blocking delivery."""

    analysis = model_analysis or {}
    issues: list[str] = []
    if analysis.get("s6_quality_gate_failed") or analysis.get(
        "s6_quality_gate_passed"
    ) is False:
        issues.append("历史S6质量标记尚未清理；仅保留为兼容性提示")
    allowed_evidence = set(evidence_ids)
    if not allowed_evidence:
        issues.append("没有可追溯公开证据")
    directions = analysis.get("concept_directions", [])
    if not isinstance(directions, list) or not directions:
        issues.append("S6没有结构化最终能力方向")
        return True, issues
    for position, raw_direction in enumerate(directions, start=1):
        if not isinstance(raw_direction, Mapping):
            issues.append(f"S6第{position}项不是结构化能力方向")
            continue
        direction = raw_direction
        direct_refs = {
            str(item)
            for item in direction.get("direct_evidence_refs", [])
            if str(item).strip()
        }
        if not direct_refs & allowed_evidence:
            issues.append(f"S6第{position}项缺少有效直接证据")
        if not str(direction.get("equipment_form", "")).strip():
            issues.append(f"S6第{position}项缺少装备对象")
        if not str(direction.get("operational_mechanism", "")).strip():
            issues.append(f"S6第{position}项缺少作战因果机理")
        if not str(direction.get("failure_boundary", "")).strip():
            issues.append(f"S6第{position}项缺少失效边界")
        verification_text = " ".join(
            str(direction.get(field, ""))
            for field in ("verification", "development_path", "capability_portrait")
        )
        if not any(
            marker in verification_text
            for marker in ("验证", "试验", "考核", "可证伪", "指标")
        ):
            issues.append(f"S6第{position}项缺少可证伪验证项")
        raw_confidence = direction.get("confidence")
        confidence_ready = str(raw_confidence).strip().lower() in {
            "high",
            "medium",
            "medium-high",
            "medium_high",
            "中",
            "中高",
            "高",
        }
        try:
            confidence_ready = confidence_ready or float(raw_confidence) >= 0.5
        except (TypeError, ValueError):
            pass
        if not confidence_ready:
            issues.append(f"S6第{position}项缺少合格置信度")
        if _has_unsupported_exact_performance_claim(direction):
            issues.append(f"S6第{position}项含未经校准的精确性能承诺")
    return True, list(dict.fromkeys(issues))


def _structured_analysis_volume(value: Any, *, depth: int = 0) -> int:
    """Measure substantive structured reasoning without capability-tag matching.

    L1-L3 receive the model's already-synthesized S-chain result.  A missing
    registry tag is therefore only a provenance limitation when the result
    itself contains enough structured, evidence-backed reasoning.  This small
    structural measure deliberately does not infer readiness from a catalogue
    of military keywords.
    """

    if depth > 5:
        return 0
    if isinstance(value, Mapping):
        return sum(
            _structured_analysis_volume(item, depth=depth + 1)
            for key, item in value.items()
            if not str(key).startswith("_")
            and key not in {"subagent_runs", "dynamic_subagent_runs", "loop_trace"}
        )
    if isinstance(value, (list, tuple, set)):
        return sum(
            _structured_analysis_volume(item, depth=depth + 1)
            for item in list(value)[:40]
        )
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 1 if value not in (None, False) else 0


def _model_semantic_readiness(
    model_analysis: dict[str, Any] | None,
    evidence_ids: list[str],
) -> dict[str, bool | int]:
    """Return semantic gate signals from the complete model result.

    Exact Agent capability labels remain useful for audit display, but they no
    longer decide whether a completed S-chain understands a situation,
    validates a concept, or identifies a capability gap.
    """

    analysis = model_analysis or {}
    volume = _structured_analysis_volume(analysis)
    swarm = analysis.get("winning_swarm", {})
    portfolio = (
        swarm.get("final_equipment_portfolio", [])
        if isinstance(swarm, Mapping)
        else []
    )
    direction_sets = (
        analysis.get("concept_directions", []),
        analysis.get("capability_synthesis", []),
        portfolio,
    )
    direction_count = sum(
        len(items) for items in direction_sets if isinstance(items, list)
    )
    s6_qualified = direction_count > 0
    evidence_grounded = bool(evidence_ids)
    substantive = volume >= 6 or direction_count > 0
    grounded = evidence_grounded and substantive
    synthesized = grounded and (s6_qualified or direction_count > 0 or volume >= 10)
    return {
        "volume": volume,
        "direction_count": direction_count,
        "s6_qualified": s6_qualified,
        "grounded": grounded,
        "validation_ready": synthesized,
        "gap_ready": synthesized,
    }


class WinningMechanismEngine:
    def __init__(
        self,
        *,
        min_confidence: float = 0.62,
        min_l2_feasibility: int = 2,
        risk_based_gates: bool = False,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_l2_feasibility = min_l2_feasibility
        self.risk_based_gates = risk_based_gates

    def run(
        self,
        *,
        topic: str,
        route: str,
        store: DomainStore,
        trace: TraceStore,
        coverage: dict[str, Any],
        attempt: int = 1,
        max_rounds: int = 5,
        resume_from: str = "L1",
        prior_stages: list[WinningMechanismStageOutput] | None = None,
        model_analysis: dict[str, Any] | None = None,
        loops_enabled: bool = True,
    ) -> tuple[
        list[WinningMechanismStageOutput],
        list[CapabilityImageItem],
        list[AgentRecommendation],
    ]:
        if resume_from not in {"L1", "L2", "L3"}:
            raise ValueError("resume_from must be L1, L2, or L3")
        packets = store.baseline_packet_snapshot()
        evidence_ids = sorted(
            {evidence_id for packet in packets for evidence_id in packet.evidence_ids}
        )
        input_pack = self._input_pack(
            topic=topic,
            route=route,
            packets=packets,
            store=store,
            coverage=coverage,
            attempt=attempt,
            max_rounds=max_rounds,
        )
        store.add_winning_input(input_pack)
        resources = WinningResourceProjector().build(
            input_pack=input_pack,
            packets=packets,
            evidence=store.evidence_snapshot(),
        )
        store.add_knowledge_projection(resources)
        trace.append(
            TraceEvent(
                event_id=f"trace-{input_pack.input_id}",
                event_type="winning_input_prepared",
                actor="orchestrator",
                summary="制胜机理输入包已完成上下文投影与一致性初检",
                input_refs=input_pack.packet_ids,
                output_refs=[input_pack.input_id],
                payload={
                    "route": route,
                    "coverage": coverage,
                    "open_questions": input_pack.open_questions,
                },
            )
        )
        trace.append(
            TraceEvent(
                event_id=f"trace-{resources.projection_id}",
                event_type="winning_resources_projected",
                actor="winning_mechanism",
                summary="理论工具、战例、前沿情报与问题链已按本次任务动态投影",
                input_refs=[input_pack.input_id, *resources.evidence_ids],
                output_refs=[resources.projection_id],
                payload={
                    "theory_tool_count": len(resources.theory_tools),
                    "case_resource_count": len(resources.case_resources),
                    "frontier_resource_count": len(resources.frontier_resources),
                    "question_count": len(resources.question_chain),
                },
            )
        )
        reasoning = SixStepReasoner().run(
            topic=topic,
            route=route,
            packets=packets,
            evidence=store.evidence_snapshot(),
            input_pack=input_pack,
            resources=resources,
            model_analysis=model_analysis,
        )
        for node in reasoning.critical_nodes():
            store.add_reasoning_node(node)
            trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-{node.object_id}"
                        if attempt == 1
                        else f"trace-{node.object_id}-r{attempt}"
                    ),
                    event_type="winning_reasoning_step_completed",
                    actor="winning_mechanism",
                    summary=node.summary,
                    input_refs=node.input_refs,
                    output_refs=[node.object_id],
                    payload={
                        "title": node.title,
                        "evidence_ids": node.evidence_ids,
                        "confidence": node.confidence,
                        "assumptions": node.assumptions,
                        "claim_ids": node.claim_ids,
                        "step": node.step,
                        "next_action": node.next_action,
                    },
                )
            )
        recommendations = self._recommend_missing_agents(coverage)
        suffix = "" if attempt == 1 else f"-r{attempt}"
        if not loops_enabled:
            # A true single-pass ablation keeps S1-S6 reasoning and capability
            # synthesis, while removing the L1-L3 gate/recall loop objects.
            l1 = replace(
                self._l1(
                    topic=topic,
                    route=route,
                    packets=packets,
                    evidence_ids=evidence_ids,
                    coverage=coverage,
                    stage_id=f"stage-L1{suffix}",
                    model_analysis=model_analysis,
                ),
                recall_requests=[],
            )
            l2 = replace(
                self._l2(
                    topic=topic,
                    route=route,
                    l1=l1,
                    evidence_ids=evidence_ids,
                    coverage=coverage,
                    stage_id=f"stage-L2{suffix}",
                    frontier_count=len(resources.frontier_resources),
                    model_analysis=model_analysis,
                ),
                recall_requests=[],
            )
            l3 = replace(
                self._l3(
                    topic=topic,
                    route=route,
                    l1=l1,
                    l2=l2,
                    evidence_ids=evidence_ids,
                    coverage=coverage,
                    stage_id=f"stage-L3{suffix}",
                    model_analysis=model_analysis,
                ),
                recall_requests=[],
            )
            images = self._capability_images(
                topic=topic,
                route=route,
                l3=l3,
                evidence_ids=evidence_ids,
                coverage=coverage,
                packets=packets,
                attempt=attempt,
                model_analysis=model_analysis,
            )
            for image in images:
                store.add_capability_image(image)
                trace.append(
                    TraceEvent(
                        event_id=f"trace-capability-{image.capability_id}",
                        event_type="capability_image_created",
                        actor="winning_mechanism",
                        summary=image.name,
                        input_refs=list(image.evidence_ids),
                        output_refs=[image.capability_id],
                        payload={"stage_policy": "single_pass_no_loops"},
                    )
                )
            return [], images, recommendations
        prior = {stage.layer: stage for stage in prior_stages or []}
        if resume_from == "L1":
            l1 = self._l1(
                topic=topic,
                route=route,
                packets=packets,
                evidence_ids=evidence_ids,
                coverage=coverage,
                stage_id=f"stage-L1{suffix}",
                model_analysis=model_analysis,
            )
            if model_analysis:
                validation_backlog_ready, validation_backlog_issues = (
                    _s6_validation_backlog_readiness(
                        model_analysis,
                        evidence_ids,
                    )
                )
                l1.outputs["core_agent_analysis"] = {
                    "defense_decomposition": model_analysis.get(
                        "defense_decomposition", []
                    ),
                    "winning_paths": model_analysis.get("winning_paths", []),
                    "effect_chain": model_analysis.get("effect_chain", []),
                    "assumptions": model_analysis.get("assumptions", []),
                    "subagent_runs": model_analysis.get("subagent_runs", []),
                    "dynamic_subagent_runs": model_analysis.get(
                        "dynamic_subagent_runs", []
                    ),
                    "dynamic_subagent_outputs": model_analysis.get(
                        "dynamic_subagent_outputs", []
                    ),
                    "loop_trace": model_analysis.get("loop_trace", []),
                    "middle_loop_limited": model_analysis.get(
                        "middle_loop_limited",
                        False,
                    ),
                    "s6_quality_gate_passed": model_analysis.get(
                        "s6_quality_gate_passed",
                        True,
                    ),
                    "s6_quality_gate_issues": model_analysis.get(
                        "s6_quality_gate_issues",
                        [],
                    ),
                    "targeted_evidence_preflight": {
                        "eligible_for_validation_backlog": (
                            validation_backlog_ready
                        ),
                        "blocking_issues": validation_backlog_issues,
                    },
                }
                # S6 local quality flags are advisory compatibility fields;
                # they cannot overturn an otherwise completed reasoning chain.
                s6_quality_failed = False
                if (
                    not s6_quality_failed
                    and model_analysis.get("middle_loop_limited")
                    and (
                        not self.risk_based_gates
                        or (
                            model_analysis.get("evidence_supplement_pending")
                            and not validation_backlog_ready
                        )
                    )
                ):
                    l1 = replace(
                        l1,
                        gate_passed=False,
                        gate_reasons=[
                            *l1.gate_reasons,
                            "制胜机理中循环达到上限后仍存在阻断性问题："
                            + "；".join(validation_backlog_issues[:4]),
                        ],
                    )
                elif (
                    not s6_quality_failed
                    and model_analysis.get("middle_loop_limited")
                ):
                    l1.outputs["risk_based_residual"] = (
                        "中循环仍有非致命一致性或证据校准残差；已保留限制，"
                        "不触发整链重跑。"
                    )
            l1.outputs["evidence_grounded_findings"] = _packet_digest(packets)
            l1.outputs["reasoning_refs"] = [
                reasoning.defense_decomposition.object_id,
                reasoning.winning_paths.object_id,
                reasoning.effect_chain.object_id,
            ]
        else:
            l1 = self._required_prior_stage(prior, "L1", resume_from)
        store.add_stage_output(l1)
        trace.append(
            TraceEvent(
                event_id=f"trace-winning-l1{suffix}",
                event_type=(
                    "winning_stage_completed"
                    if resume_from == "L1"
                    else "winning_stage_reused"
                ),
                actor="winning_mechanism",
                summary=f"L1 {'completed' if resume_from == 'L1' else 'reused'}: gate={l1.gate_passed}",
                output_refs=[l1.stage_id],
            )
        )
        if resume_from == "L1":
            self._trace_recalls(trace, l1)
        if resume_from in {"L1", "L2"}:
            l2 = self._l2(
                topic=topic,
                route=route,
                l1=l1,
                evidence_ids=evidence_ids,
                coverage=coverage,
                stage_id=f"stage-L2{suffix}",
                frontier_count=len(resources.frontier_resources),
                model_analysis=model_analysis,
            )
            l2.outputs["reasoning_refs"] = [reasoning.capability_mapping.object_id]
            l2.outputs["frontier_evidence_ids"] = [
                item.get("evidence_id", "") for item in resources.frontier_resources
            ]
            if model_analysis:
                l2.outputs["core_agent_concept_directions"] = model_analysis.get(
                    "concept_directions", []
                )
        else:
            l2 = self._required_prior_stage(prior, "L2", resume_from)
        store.add_stage_output(l2)
        trace.append(
            TraceEvent(
                event_id=f"trace-winning-l2{suffix}",
                event_type=(
                    "winning_stage_reused"
                    if resume_from == "L3"
                    else "winning_stage_completed"
                ),
                actor="winning_mechanism",
                summary=f"L2 {'reused' if resume_from == 'L3' else 'completed'}: gate={l2.gate_passed}",
                output_refs=[l2.stage_id],
            )
        )
        if resume_from in {"L1", "L2"}:
            self._trace_recalls(trace, l2)
        l3 = self._l3(
            topic=topic,
            route=route,
            l1=l1,
            l2=l2,
            evidence_ids=evidence_ids,
            coverage=coverage,
            stage_id=f"stage-L3{suffix}",
            model_analysis=model_analysis,
        )
        l3.outputs["reasoning_refs"] = [
            reasoning.gap_matrix.object_id,
            *[item.object_id for item in reasoning.image_drafts],
        ]
        l3.outputs["gap_basis"] = _gap_basis(packets)
        if model_analysis:
            l3.outputs["core_agent_gap_assessment"] = model_analysis.get(
                "gap_assessment", []
            )
            l3.outputs["branch_products"] = model_analysis.get(
                "branch_products", {}
            )
        store.add_stage_output(l3)
        trace.append(
            TraceEvent(
                event_id=f"trace-winning-l3{suffix}",
                event_type="winning_stage_completed",
                actor="winning_mechanism",
                summary=f"L3 completed: gate={l3.gate_passed}",
                output_refs=[l3.stage_id],
            )
        )
        self._trace_recalls(trace, l3)
        images = self._capability_images(
            topic=topic,
            route=route,
            l3=l3,
            evidence_ids=evidence_ids,
            coverage=coverage,
            packets=packets,
            attempt=attempt,
            model_analysis=model_analysis,
        )
        for image in images:
            store.add_capability_image(image)
            trace.append(
                TraceEvent(
                    event_id=f"trace-capability-{image.capability_id}",
                    event_type="capability_image_created",
                    actor="winning_mechanism",
                    summary=image.name,
                    input_refs=[l3.stage_id, *image.evidence_ids],
                    output_refs=[image.capability_id],
                )
            )
        return [l1, l2, l3], images, recommendations

    def run_deep_divergence(
        self,
        *,
        topic: str,
        route: str,
        store: DomainStore,
        trace: TraceStore,
        coverage: dict[str, Any],
        model_analysis: dict[str, Any] | None = None,
        attempt: int = 1,
    ) -> tuple[list[WinningMechanismStageOutput], list[CapabilityImageItem], list[AgentRecommendation]]:
        """Project a constrained deep-research result without the L1-L3 engine.

        ``deep_divergence_v1`` is a continuation of an existing run.  It must
        not manufacture a synthetic S1/S2/S5 chain (or invoke the ordinary
        convergence/winning harness).  The provider has already performed the
        bounded S3/S4/S6 reasoning; this method only wraps those structured
        outputs into the legacy delivery objects consumed by reporting and the
        capability ledger.  The runner relabels the three objects to S3/S4/S6
        immediately after this call.
        """
        analysis = dict(model_analysis or {})
        packets = store.baseline_packet_snapshot()
        evidence_ids = sorted(
            {
                str(evidence_id)
                for packet in packets
                for evidence_id in packet.evidence_ids
                if str(evidence_id).strip()
            }
        )
        # Deep jobs receive canonical parent context and may have no baseline
        # packets at all.  Evidence references embedded by the provider are
        # still retained when they resolve to the run's evidence index.
        valid_evidence = {
            str(item.get("evidence_id", ""))
            for item in store.evidence_index()
            if isinstance(item, Mapping) and str(item.get("evidence_id", "")).strip()
        }
        for direction in analysis.get("concept_directions", []):
            if not isinstance(direction, Mapping):
                continue
            for ref in direction.get("direct_evidence_refs", []):
                # Parent-bound deep jobs carry canonical evidence references
                # even when the isolated child does not duplicate EvidenceCard
                # rows locally.  Preserve those IDs for version provenance;
                # the parent ledger remains the authority for their details.
                if str(ref).strip() and (str(ref) in valid_evidence or not valid_evidence):
                    evidence_ids.append(str(ref))
        evidence_ids = list(dict.fromkeys(evidence_ids))

        def confidence(value: Any, fallback: float = 0.0) -> float:
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return fallback

        overall_confidence = confidence(analysis.get("confidence"), 0.62)
        s3_rows = analysis.get("breakthrough_directions", [])
        if not isinstance(s3_rows, list):
            s3_rows = []
        s4_rows = analysis.get("capability_mapping", [])
        if not isinstance(s4_rows, list):
            s4_rows = []
        directions = [
            dict(item)
            for item in analysis.get("concept_directions", [])
            if isinstance(item, Mapping)
            and str(item.get("name", "")).strip()
            and str(item.get("type", "")) in {"new_capability", "upgrade"}
        ][:6]
        # A deep job is allowed to retain analysis only when the evidence gate
        # is met.  In particular, do not generate generic fallback cards when
        # S6 did not produce a stable equipment identity.
        s6_gate = bool(directions) and bool(evidence_ids)
        stage_specs = (
            ("L1", "S3", "竞争性机制发散", {"breakthrough_directions": s3_rows}),
            ("L2", "S4", "装备能力映射", {"capability_mapping": s4_rows}),
            ("L3", "S6", "待核验能力画像", {"concept_directions": directions}),
        )
        stages: list[WinningMechanismStageOutput] = []
        for legacy_layer, deep_stage, title, outputs in stage_specs:
            has_output = bool(next(iter(outputs.values()), []))
            gate = has_output and bool(evidence_ids)
            reasons: list[str] = []
            if not has_output:
                reasons.append(f"{deep_stage}未形成结构化结果")
            if not evidence_ids:
                reasons.append(f"{deep_stage}缺少可追溯公开证据")
            stages.append(
                WinningMechanismStageOutput(
                    stage_id=f"stage-{deep_stage}",
                    layer=legacy_layer,  # relabelled by DeepResearchRunner
                    title=title,
                    outputs={
                        **outputs,
                        "deep_stage": deep_stage,
                        "execution_profile_id": "deep_divergence_v1",
                    },
                    confidence=overall_confidence,
                    evidence_ids=list(evidence_ids),
                    gate_passed=gate,
                    gate_reasons=reasons,
                    recall_requests=[],
                )
            )
        images: list[CapabilityImageItem] = []
        if s6_gate:
            # Reuse only the card materializer; unlike ``run`` this path does
            # not construct reasoning resources, L1/L2/L3 gates, recalls or
            # fallback weapon directions.
            images = self._model_capability_images(
                topic=topic,
                route=route,
                l3=stages[2],
                evidence_ids=evidence_ids,
                packets=packets,
                directions=directions,
                model_analysis=analysis,
                attempt=attempt,
                limit_suffix="",
                preserve_direction_identity=True,
            )
            for image in images:
                store.add_capability_image(image)
                trace.append(
                    TraceEvent(
                        event_id=f"trace-deep-capability-{image.capability_id}",
                        event_type="capability_image_created",
                        actor="deep_divergence",
                        summary=image.name,
                        input_refs=list(image.evidence_ids),
                        output_refs=[image.capability_id],
                        payload={"execution_profile_id": "deep_divergence_v1", "stage": "S6"},
                    )
                )
        recommendations: list[AgentRecommendation] = []
        trace.append(
            TraceEvent(
                event_id=f"trace-deep-divergence-projected-r{attempt}",
                event_type="deep_divergence_projected",
                actor="deep_divergence",
                summary="已按S3/S4/S6专用契约投影深研结果",
                output_refs=[stage.stage_id for stage in stages],
                payload={
                    "execution_profile_id": "deep_divergence_v1",
                    "stage_scope": ["S3", "S4", "S6"],
                    "candidate_count": len(directions),
                    "evidence_count": len(evidence_ids),
                    "s6_gate_passed": s6_gate,
                },
            )
        )
        return stages, images, recommendations

    @staticmethod
    def _required_prior_stage(
        prior: dict[str, WinningMechanismStageOutput],
        layer: str,
        resume_from: str,
    ) -> WinningMechanismStageOutput:
        if layer not in prior:
            raise ValueError(f"resume_from={resume_from} requires prior {layer} stage")
        return prior[layer]

    @staticmethod
    def _trace_recalls(
        trace: TraceStore,
        stage: WinningMechanismStageOutput,
    ) -> None:
        for recall in stage.recall_requests:
            trace.append(
                TraceEvent(
                    event_id=f"trace-{recall.recall_id}",
                    event_type="recall_requested",
                    actor="winning_mechanism",
                    summary=recall.reason,
                    input_refs=[stage.stage_id],
                    output_refs=[recall.recall_id],
                    payload=to_plain(recall),
                )
            )

    def _input_pack(
        self,
        *,
        topic: str,
        route: str,
        packets: list[BaselineFindingPacket],
        store: DomainStore,
        coverage: dict[str, Any],
        attempt: int,
        max_rounds: int,
    ) -> WinningMechanismInput:
        open_questions = list(
            dict.fromkeys(
                question for packet in packets for question in packet.open_questions
            )
        )
        conflicts = list(
            dict.fromkeys(
                conflict
                for packet in packets
                for conflict in packet.limitations
                if "冲突" in conflict or "矛盾" in conflict
            )
        )
        route_frame = {
            "new_winning_mechanism": "以国际形势、潜在威胁和对抗场景为起点，从新制胜机制、新作战打法和新体系组合推导新质装备功能。",
            "traditional_gap": "以传统场景、传统制胜和传统战法为基线，对比当前装备能力并识别不足、空白与升级功能。",
            "war_case_learning": "以国际局部战争为样本，多轮检索装备新能力、打法新模式、效果与不足，并迁移为未来布局方向。",
        }.get(route, "按研究问题动态选择制胜机理分析路线。")
        return WinningMechanismInput(
            input_id=f"winning-input-r{attempt}",
            research_route=route,
            problem_frame={
                "topic": topic,
                "objective": "回答需要发展具备什么功能的产品",
                "route_frame": route_frame,
            },
            packet_ids=[packet.packet_id for packet in packets],
            evidence_index=store.evidence_index(),
            coverage_map=coverage,
            conflict_set=conflicts,
            open_questions=open_questions,
            round_budget={
                "current_round": attempt,
                "maximum_rounds": max_rounds,
                "same_target_recall_limit": 3,
            },
            attempt=attempt,
        )

    def _l1(
        self,
        *,
        topic: str,
        route: str,
        packets: list[BaselineFindingPacket],
        evidence_ids: list[str],
        coverage: dict[str, Any],
        stage_id: str,
        model_analysis: dict[str, Any] | None = None,
        confidence_override: float | None = None,
        post_recall: bool = False,
    ) -> WinningMechanismStageOutput:
        confidence = (
            _avg_confidence(packets)
            if confidence_override is None
            else round(confidence_override, 3)
        )
        recall_suffix = _stage_attempt_suffix(stage_id)
        semantic = _model_semantic_readiness(model_analysis, evidence_ids)
        model_grounded = bool(semantic["grounded"])
        missing_tags = list(coverage.get("missing_required_tags", []))
        recalls: list[RecallRequest] = []
        # Missing baseline capability tags remain visible as coverage limits,
        # but never trigger mechanical retrieval expansion.  S1-S6 must reason
        # from the selected evidence and request only a concrete evidence gap.
        if self.risk_based_gates and not evidence_ids:
            target_agent_id = (
                min(packets, key=lambda packet: packet.confidence).agent_id
                if packets
                else None
            )
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L1-no-evidence{recall_suffix}",
                    source_layer="L1",
                    target_agent_id=target_agent_id,
                    target_capability_tag=None,
                    reason="L1没有可追溯公开证据，无法形成有边界的制胜判断。",
                    required_data=[
                        f"补充{topic}相关至少一项可追溯公开材料、直接摘录和适用边界"
                    ],
                    return_node="L1",
                    urgency="high",
                )
            )
        confidence_floor = (
            max(0.58, self.min_confidence - 0.04)
            if self.risk_based_gates and model_grounded
            else self.min_confidence
        )
        if (
            self.risk_based_gates
            and model_grounded
            and (recall_suffix or post_recall)
            and not missing_tags
        ):
            # A targeted recall is meant to close a bounded evidence residual,
            # not force the same conservative first-pass threshold again.  The
            # post-recall floor remains evidence/model/coverage gated and never
            # falls below 0.55.
            confidence_floor = max(0.55, self.min_confidence - 0.07)
        if not self.risk_based_gates and confidence < confidence_floor and packets:
            target = min(packets, key=lambda packet: packet.confidence)
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L1-confidence-{target.agent_id}{recall_suffix}",
                    source_layer="L1",
                    target_agent_id=target.agent_id,
                    target_capability_tag=None,
                    reason="L1 综合置信度未达到门控，需要定向补充高置信证据。",
                    required_data=[f"补充{topic}相关可材料化公开证据和结构化判断"],
                    return_node="L1",
                    urgency="high",
                )
            )
        gate_passed = (
            bool(evidence_ids) and not recalls
            if self.risk_based_gates
            else confidence >= confidence_floor and not recalls
        )
        gate_reasons: list[str] = []
        if not gate_passed:
            if not evidence_ids:
                gate_reasons.append("L1缺少可追溯公开证据")
            if not self.risk_based_gates and not model_grounded:
                gate_reasons.append("L1尚未形成实质性制胜机理分析")
            if not self.risk_based_gates and confidence < confidence_floor:
                gate_reasons.append(
                    f"L1综合置信度{confidence:.1%}低于有限门槛{confidence_floor:.1%}"
                )
        return WinningMechanismStageOutput(
            stage_id=stage_id,
            layer="L1",
            title="制胜逻辑分析",
            outputs={
                "weakness_map": [
                    "围绕敌体系感知、决策、拦截、冗余进行分层解构。",
                    f"{topic}的关键弱点需由场景、装备和运用证据共同支撑。",
                ],
                "winning_paths": [
                    _route_winning_path(route),
                    "以战例和公开证据校验制胜路径假设。",
                ],
                "effect_chain": "行动 -> 直接效果 -> 间接效果 -> 最终能力收益。",
                "key_capabilities": [
                    "感知发现",
                    "快速决策",
                    "精确打击/拦截",
                    "体系协同",
                ],
                "assumptions": ["公开资料足以支撑初步画像，不替代专家论证。"],
                "coverage_limits": missing_tags if self.risk_based_gates else [],
                "semantic_gate": {
                    "substantive_volume": semantic["volume"],
                    "direction_count": semantic["direction_count"],
                    "exact_tag_gaps_are_non_blocking": bool(
                        self.risk_based_gates and model_grounded and missing_tags
                    ),
                    "low_confidence_is_warning": bool(
                        self.risk_based_gates and confidence < confidence_floor
                    ),
                },
            },
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=gate_reasons,
            recall_requests=recalls,
        )

    def reevaluate_gates_after_recall(
        self,
        *,
        topic: str,
        route: str,
        stages: list[WinningMechanismStageOutput],
        store: DomainStore,
        coverage: dict[str, Any],
        model_analysis: dict[str, Any] | None,
        recall_supplements: list[dict[str, Any]],
    ) -> list[WinningMechanismStageOutput]:
        """Re-evaluate only the gate chain affected by a completed recall.

        Recall packets supersede weaker packets from the same agent for gate
        scoring.  Existing S1-S6 outputs, stage identities and capability
        images are deliberately retained; this method only refreshes L1-L3
        gate state and evidence references.
        """
        if not stages or not recall_supplements:
            return stages
        by_layer = {stage.layer: stage for stage in stages}
        affected_layers = {
            str(item.get("return_node", "")) for item in recall_supplements
        }
        ordered_layers = ["L1", "L2", "L3"]
        affected_indexes = [
            ordered_layers.index(layer)
            for layer in affected_layers
            if layer in ordered_layers
        ]
        if not affected_indexes:
            return stages
        start_index = min(affected_indexes)
        packets = _effective_packets_after_recall(store.baseline_packet_snapshot())
        evidence_ids = sorted(
            {evidence_id for packet in packets for evidence_id in packet.evidence_ids}
        )
        post_recall_confidence = _evidence_weighted_confidence(packets)
        supplements_by_layer = {
            layer: [
                item
                for item in recall_supplements
                if item.get("return_node") == layer
            ]
            for layer in ordered_layers
        }

        def merge_gate(
            original: WinningMechanismStageOutput,
            evaluated: WinningMechanismStageOutput,
        ) -> WinningMechanismStageOutput:
            supplements = supplements_by_layer.get(original.layer, [])
            outputs = dict(original.outputs)
            existing = outputs.get("recall_supplements", [])
            if supplements:
                outputs["recall_supplements"] = [
                    *(list(existing) if isinstance(existing, list) else []),
                    *supplements,
                ]
            return replace(
                original,
                outputs=outputs,
                confidence=evaluated.confidence,
                evidence_ids=list(
                    dict.fromkeys([*original.evidence_ids, *evaluated.evidence_ids])
                ),
                gate_passed=evaluated.gate_passed,
                gate_reasons=evaluated.gate_reasons,
                # A completed recall gets one deterministic re-evaluation.  A
                # residual is surfaced as a concrete limitation rather than
                # scheduling the same recall repeatedly.
                recall_requests=[],
            )

        l1 = by_layer["L1"]
        if start_index == 0:
            evaluated_l1 = self._l1(
                topic=topic,
                route=route,
                packets=packets,
                evidence_ids=evidence_ids,
                coverage=coverage,
                stage_id=l1.stage_id,
                model_analysis=model_analysis,
                confidence_override=post_recall_confidence,
                post_recall=True,
            )
            l1_supplements = supplements_by_layer["L1"]
            new_l1_evidence = {
                evidence_id
                for item in l1_supplements
                for evidence_id in item.get("new_evidence_ids", [])
            }
            if l1_supplements and not new_l1_evidence:
                evaluated_l1 = replace(
                    evaluated_l1,
                    gate_passed=False,
                    gate_reasons=[
                        "L1定向再调未形成新增可接纳证据，无法提高制胜逻辑结论置信度"
                    ],
                    recall_requests=[],
                )
            elif not evaluated_l1.gate_passed:
                evaluated_l1 = replace(
                    evaluated_l1,
                    gate_reasons=[
                        f"L1再调后有效证据加权置信度{post_recall_confidence:.1%}仍低于门槛，或必需能力覆盖仍不完整"
                    ],
                    recall_requests=[],
                )
            l1 = merge_gate(l1, evaluated_l1)

        l2 = by_layer["L2"]
        if start_index <= 1:
            evaluated_l2 = self._l2(
                topic=topic,
                route=route,
                l1=l1,
                evidence_ids=evidence_ids,
                coverage=coverage,
                stage_id=l2.stage_id,
                model_analysis=model_analysis,
            )
            l2 = merge_gate(l2, evaluated_l2)

        l3 = by_layer["L3"]
        evaluated_l3 = self._l3(
            topic=topic,
            route=route,
            l1=l1,
            l2=l2,
            evidence_ids=evidence_ids,
            coverage=coverage,
            stage_id=l3.stage_id,
            model_analysis=model_analysis,
        )
        l3 = merge_gate(l3, evaluated_l3)
        return [l1, l2, l3]

    def _l2(
        self,
        *,
        topic: str,
        route: str,
        l1: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
        stage_id: str,
        frontier_count: int = 0,
        model_analysis: dict[str, Any] | None = None,
    ) -> WinningMechanismStageOutput:
        recall_suffix = _stage_attempt_suffix(stage_id)
        validation_tag = {
            "new_winning_mechanism": "technology_readiness",
            "traditional_gap": "capability_gap",
            "war_case_learning": "lessons",
        }.get(route, "equipment")
        provided = set(coverage.get("provided_tags", []))
        semantic = _model_semantic_readiness(model_analysis, evidence_ids)
        model_validation_ready = bool(semantic["validation_ready"])
        validation_ready = validation_tag in provided or (
            self.risk_based_gates and model_validation_ready
        )
        recalls: list[RecallRequest] = []
        if l1.gate_passed and not validation_ready and not self.risk_based_gates:
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L2-{validation_tag}{recall_suffix}",
                    source_layer="L2",
                    target_agent_id=None,
                    target_capability_tag=validation_tag,
                    reason=f"L2 缺少 {validation_tag} 能力支撑，无法完成概念可行性验证。",
                    required_data=[
                        f"补充{topic}相关成熟度、试验状态、工程约束或路线适用性证据"
                    ],
                    return_node="L2",
                    urgency="medium",
                )
            )
        if l1.gate_passed and not evidence_ids:
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L2-frontier-evidence{recall_suffix}",
                    source_layer="L2",
                    target_agent_id=None,
                    target_capability_tag="technology_readiness",
                    reason="L2 没有可接纳证据支撑前沿方向与工程可行性判断。",
                    required_data=[
                        "补充可材料化的试验、验证、部署或技术成熟度公开证据"
                    ],
                    return_node="L2",
                    urgency="high",
                )
            )
        feasibility = (
            (3 if self.risk_based_gates and model_validation_ready else 4)
            if l1.gate_passed and validation_ready and evidence_ids
            else 2
        )
        confidence = min(
            0.86, max(0.55, l1.confidence - (0 if l1.gate_passed else 0.08))
        )
        gate_passed = (
            feasibility >= self.min_l2_feasibility and l1.gate_passed and not recalls
        )
        gate_reasons: list[str] = []
        if not l1.gate_passed:
            gate_reasons.append("L2前置门L1未通过；根因仅在L1展示，本层不重复展开")
        if l1.gate_passed and not validation_ready:
            gate_reasons.append(f"L2缺少{validation_tag}验证能力")
        if l1.gate_passed and not evidence_ids:
            gate_reasons.append("L2缺少可材料化的前沿或工程验证证据")
        if l1.gate_passed and feasibility < self.min_l2_feasibility:
            gate_reasons.append(
                f"L2可行性评分{feasibility}低于门槛{self.min_l2_feasibility}"
            )
        return WinningMechanismStageOutput(
            stage_id=stage_id,
            layer="L2",
            title="概念创新评估",
            outputs={
                "concept_scan": [
                    "扫描高超、模块化、低成本、AI自主、诱饵、巡飞弹等前沿样式。",
                    f"结合{topic}判断可迁移的新能力空间。",
                ],
                "analogy_innovation": "七维分解并进行跨域移植评估。",
                "screened_directions": [
                    "新能力方向：体系化感知-决策-火力闭环。",
                    "改进方向：现有装备在复杂场景下的探测、协同和抗干扰能力提升。",
                ],
                "feasibility_score": feasibility,
                "validation_capability": validation_tag,
                "validation_source": (
                    "S步骤结构化验证"
                    if self.risk_based_gates
                    and model_validation_ready
                    and validation_tag not in provided
                    else "业务Agent覆盖"
                ),
                "frontier_evidence_count": frontier_count,
                "route": route,
            },
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=[] if gate_passed else gate_reasons,
            recall_requests=recalls,
        )

    def _l3(
        self,
        *,
        topic: str,
        route: str,
        l1: WinningMechanismStageOutput,
        l2: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
        stage_id: str,
        model_analysis: dict[str, Any] | None = None,
    ) -> WinningMechanismStageOutput:
        confidence = min(l1.confidence, l2.confidence)
        recall_suffix = _stage_attempt_suffix(stage_id)
        provided = set(coverage.get("provided_tags", []))
        recalls: list[RecallRequest] = []
        validation_backlog: list[dict[str, Any]] = []
        semantic = _model_semantic_readiness(model_analysis, evidence_ids)
        model_gap_ready = bool(semantic["gap_ready"])
        gap_ready = "capability_gap" in provided or (
            self.risk_based_gates and model_gap_ready
        )
        if l2.gate_passed and not gap_ready and not self.risk_based_gates:
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L3-capability-gap{recall_suffix}",
                    source_layer="L3",
                    target_agent_id=None,
                    target_capability_tag="capability_gap",
                    reason="L3 缺少现有能力基线与差距量化专业覆盖。",
                    required_data=[
                        f"补充{topic}的现有装备基线、场景需求阈值、参数区间和五档差距依据"
                    ],
                    return_node="L3",
                    urgency="high",
                )
            )
        if l2.gate_passed and not evidence_ids:
            recalls.append(
                RecallRequest(
                    recall_id=f"recall-L3-evidence-traceability{recall_suffix}",
                    source_layer="L3",
                    target_agent_id=None,
                    target_capability_tag="equipment",
                    reason="L3 能力画像没有可追溯证据，不能正式生成差距与优先级。",
                    required_data=["补充能力基线、差距数据和参数位置引用"],
                    return_node="L3",
                    urgency="high",
                )
            )
        validation_backlog_ready, validation_backlog_issues = (
            _s6_validation_backlog_readiness(model_analysis, evidence_ids)
        )
        if (model_analysis or {}).get("evidence_supplement_pending"):
            for index, item in enumerate(
                (model_analysis or {}).get("targeted_evidence_requests", [])[:2],
                start=1,
            ):
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question", "")).strip()
                target_agent_id = str(item.get("target_agent_id", "")).strip()
                if not question or not target_agent_id:
                    continue
                source_preferences = [
                    str(value)
                    for value in item.get("source_preferences", [])
                    if str(value).strip()
                ][:3]
                affected_steps = [
                    str(value)
                    for value in item.get("affected_steps", [])
                    if str(value).strip()
                ][:4]
                explicit_blocker = item.get("blocking") is True or str(
                    item.get("gate_impact", "")
                ).strip().lower() in {"blocking", "hard", "hard_block"}
                if (
                    self.risk_based_gates
                    and validation_backlog_ready
                    and not explicit_blocker
                ):
                    validation_backlog.append(
                        {
                            "request_id": f"validation-L3-{index}{recall_suffix}",
                            "question": question,
                            "target_agent_id": target_agent_id,
                            "source_preferences": source_preferences,
                            "affected_steps": affected_steps,
                            "reason": str(item.get("reason", "")).strip(),
                            "classification": "calibration_backlog",
                            "gate_impact": "non_blocking",
                            "rationale": (
                                "S6已形成可交付画像；该请求用于进一步校准直接证据、"
                                "作战机理、失效边界、验证项和置信度，不影响当前交付；"
                                "后续可继续校准型号、成本交换或试验参数。"
                            ),
                        }
                    )
                    continue
                recalls.append(
                    RecallRequest(
                        recall_id=(
                            f"recall-L3-targeted-evidence-{index}{recall_suffix}"
                        ),
                        source_layer="L3",
                        target_agent_id=target_agent_id,
                        target_capability_tag=None,
                        reason=str(item.get("reason", "")).strip()
                        or "制胜链批判发现一项会影响能力差距结论的直接证据缺口。",
                        required_data=[
                            question,
                            *(
                                [f"优先来源：{'、'.join(source_preferences)}"]
                                if source_preferences
                                else []
                            ),
                            *(
                                [f"仅回灌受影响步骤：S{'/S'.join(affected_steps)}"]
                                if affected_steps
                                else []
                            ),
                        ],
                        return_node="L3",
                        urgency="high",
                    )
                )
        s6_quality_failed = False
        gate_passed = l2.gate_passed and not recalls and not s6_quality_failed
        gate_reasons: list[str] = []
        if not l2.gate_passed:
            gate_reasons.append("L3前置门L2未通过；根因仅在上游失败层展示，本层不重复展开")
        if s6_quality_failed:
            gate_reasons.append(
                "S6能力画像质量门未通过："
                + "；".join(
                    str(item)
                    for item in (model_analysis or {}).get(
                        "s6_quality_gate_issues", []
                    )[:4]
                )
            )
        if l2.gate_passed and not gap_ready:
            gate_reasons.append("L3缺少现有能力基线与差距量化覆盖")
        if l2.gate_passed and not evidence_ids:
            gate_reasons.append("L3能力画像缺少可追溯公开证据")
        if recalls and (model_analysis or {}).get("evidence_supplement_pending"):
            detail = "；".join(validation_backlog_issues[:4])
            gate_reasons.append(
                "L3定向补证属于硬阻断"
                + (f"：{detail}" if detail else "")
            )
        outputs: dict[str, Any] = {
            "dedup_grouping": "合并L1关键能力与L2创新方向，形成能力条目组。",
            "category_mapping": "按平台、任务、射程、速度、载荷和保障约束映射。",
            "gap_quantification": "按空白、关键差距、部分差距、满足、超出五档评估。",
            "priority_method": "关键性 x 紧迫性 x 可行性。",
            "coverage_limits": coverage.get("missing_required_tags", []),
        }
        if validation_backlog:
            outputs["validation_backlog"] = validation_backlog
            outputs["risk_based_residual"] = (
                "存在不阻断发布的证据校准任务；报告必须保留限制说明和后续验证计划。"
            )
        return WinningMechanismStageOutput(
            stage_id=stage_id,
            layer="L3",
            title="能力图像生成",
            outputs=outputs,
            confidence=confidence,
            evidence_ids=evidence_ids,
            gate_passed=gate_passed,
            gate_reasons=[] if gate_passed else gate_reasons,
            recall_requests=recalls,
        )

    def _capability_images(
        self,
        *,
        topic: str,
        route: str,
        l3: WinningMechanismStageOutput,
        evidence_ids: list[str],
        coverage: dict[str, Any],
        packets: list[BaselineFindingPacket],
        attempt: int = 1,
        model_analysis: dict[str, Any] | None = None,
    ) -> list[CapabilityImageItem]:
        limit_suffix = ""
        if coverage.get("missing_required_tags"):
            limit_suffix = (
                f"（受限：缺少{','.join(coverage['missing_required_tags'])}覆盖）"
            )
        profile = _route_capability_profile(route, topic)
        military_profile = military_capability_profile(topic, route)
        directions = [
            item
            for item in (model_analysis or {}).get("concept_directions", [])
            if isinstance(item, dict)
            and item.get("type") in {"new_capability", "upgrade"}
            and str(item.get("name", "")).strip()
        ][:7]
        if directions:
            return self._model_capability_images(
                topic=topic,
                route=route,
                l3=l3,
                evidence_ids=evidence_ids,
                packets=packets,
                directions=directions,
                model_analysis=model_analysis or {},
                attempt=attempt,
                limit_suffix=limit_suffix,
                preserve_direction_identity=(
                    bool((model_analysis or {}).get("s6_quality_gate_passed"))
                    and not bool((model_analysis or {}).get("s6_quality_gate_failed"))
                ),
            )
        fallback_directions = _fallback_specific_weapon_directions(
            topic=topic,
            route=route,
            profile=profile,
            military_profile=military_profile,
            evidence_ids=evidence_ids,
            confidence=l3.confidence,
            gap_basis=_gap_basis(packets),
        )
        return self._model_capability_images(
            topic=topic,
            route=route,
            l3=l3,
            evidence_ids=evidence_ids,
            packets=packets,
            directions=fallback_directions,
            model_analysis={
                "winning_paths": [profile["new_logic"], profile["upgrade_logic"]],
                "capability_mapping": [
                    "无人化低空突击",
                    "远程精确打击",
                    "巡飞弹规模毁伤",
                    "低空反无人拦截",
                    "现役火控与再打击升级",
                ],
            },
            attempt=attempt,
            limit_suffix=limit_suffix,
            preserve_direction_identity=False,
        )

    def _model_capability_images(
        self,
        *,
        topic: str,
        route: str,
        l3: WinningMechanismStageOutput,
        evidence_ids: list[str],
        packets: list[BaselineFindingPacket],
        directions: list[dict[str, Any]],
        model_analysis: dict[str, Any],
        attempt: int,
        limit_suffix: str,
        preserve_direction_identity: bool,
    ) -> list[CapabilityImageItem]:
        profile = _route_capability_profile(route, topic)
        gap_basis = _gap_basis(packets)
        allowed_evidence = set(evidence_ids)
        counters = {"new_capability": 0, "upgrade": 0}
        images: list[CapabilityImageItem] = []
        seen_names: set[str] = set()
        for direction in directions:
            name = _normalize_direction_name(direction.get("name", ""))
            name_identity = " ".join(
                str(direction.get(field, ""))
                for field in ("name", "equipment_form", "function", "military_value")
            )
            if any(marker in name_identity for marker in ("无人艇", "无人水面")) and any(
                marker in name_identity
                for marker in (
                    "巡航弹舱",
                    "巡航弹发射",
                    "远程弹药发射",
                    "远火发射",
                    "海上分布弹舱",
                    "海上远程火力",
                )
            ):
                name = build_capability_title(
                    name=name,
                    equipment_form=direction.get("equipment_form", ""),
                    effect=(
                        direction.get("function", "")
                        or direction.get("military_value", "")
                    ),
                )
            capability_type = str(direction.get("type", ""))
            if not name or name in seen_names or capability_type not in counters:
                continue
            seen_names.add(name)
            counters[capability_type] += 1
            type_index = counters[capability_type]
            prefix = "new" if capability_type == "new_capability" else "upgrade"
            capability_id = f"cap-{prefix}-{type_index:03d}"
            if attempt != 1:
                capability_id += f"-r{attempt}"
            detail = _capability_detail_profile(route, capability_type)
            function = str(direction.get("function", "")).strip()
            if not function:
                function = (
                    profile["new_image"]
                    if capability_type == "new_capability"
                    else profile["upgrade_image"]
                )
            direct_evidence = [
                str(item)
                for item in direction.get("direct_evidence_refs", [])
                if str(item) in allowed_evidence
            ]
            has_explicit_direct_evidence = "direct_evidence_refs" in direction
            capability_evidence_ids = (
                direct_evidence if has_explicit_direct_evidence else evidence_ids
            )
            if not capability_evidence_ids:
                capability_evidence_ids = [
                    str(item)
                    for item in direction.get("evidence_ids", [])
                    if str(item).strip() in allowed_evidence
                ]
            military_value = str(direction.get("military_value", "")).strip()
            depth_mechanism = str(direction.get("depth_mechanism", "")).strip()
            foresight = str(direction.get("foresight", "")).strip()
            novelty = str(direction.get("novelty", "")).strip()
            capability_portrait = str(
                direction.get("capability_portrait", "")
            ).strip()
            # S6 owns five independently authored modules.  Prefer the
            # structured module payload when it is complete, because a few
            # providers return a flattened whole-card string with dropped
            # newlines (which makes the technology/process labels look like
            # short or malformed columns in downstream quality gates).  The
            # assembly is lossless: it only restores the governed labels and
            # preserves each authored module verbatim.
            raw_portrait_modules = direction.get("capability_portrait_modules")
            if isinstance(raw_portrait_modules, Mapping):
                assembled_modules_portrait = assemble_capability_portrait_modules(
                    raw_portrait_modules
                )
                if assembled_modules_portrait:
                    capability_portrait = assembled_modules_portrait
            equipment_form = str(direction.get("equipment_form", "")).strip()
            operational_mechanism = str(
                direction.get("operational_mechanism", "")
            ).strip()
            target_scenario = str(
                direction.get("target_scenario", "") or topic
            ).strip()
            raw_problem_statement = str(
                direction.get("problem_statement", "")
                or direction.get("capability_gap", "")
            ).strip()
            scientific_principle = str(
                direction.get("scientific_principle", "")
                or direction.get("depth_mechanism", "")
                or direction.get("novelty", "")
            ).strip()
            enabling_technologies = _dedupe_text(
                [
                    str(item)
                    for item in direction.get("enabling_technologies", [])
                    if str(item).strip()
                ]
            )
            operational_concept = str(
                direction.get("operational_concept", "")
                or direction.get("operational_mechanism", "")
            ).strip()
            equipment_identity = "；".join(
                item
                for item in (
                    str(direction.get("primary_equipment_identity", "")).strip(),
                    name,
                    equipment_form,
                    function,
                    military_value,
                )
                if item
            )
            problem_statement = normalize_capability_problem(
                raw_problem_statement,
                fallback=(
                    f"{name}对应的关键任务链仍存在目标、授权、交战或毁伤评估断点"
                ),
            )
            operational_process = normalize_operational_process(
                direction.get("operational_process", []),
                equipment_identity=equipment_identity,
            )
            capability_outcome = str(
                direction.get("capability_outcome", "")
                or direction.get("function", "")
                or direction.get("military_value", "")
            ).strip()
            winning_mechanism = str(
                direction.get("winning_mechanism", "")
                or direction.get("depth_mechanism", "")
                or direction.get("novelty", "")
            ).strip()
            development_path = str(direction.get("development_path", "")).strip()
            raw_verification_plan = direction.get("validation_plan", [])
            baseline_operational_constraints = _capability_evidence_basis(packets)
            verification_inputs = (
                list(raw_verification_plan)
                if isinstance(raw_verification_plan, (list, tuple))
                else [raw_verification_plan]
                if raw_verification_plan not in (None, "")
                else []
            )
            strike_countermeasure_value = str(
                direction.get("strike_countermeasure_value", "")
            ).strip()
            baseline_system = str(direction.get("baseline_system", "")).strip()
            direction_gap = str(direction.get("capability_gap", "")).strip()
            query_relevance = str(direction.get("query_relevance", "")).strip()
            upgrade_package = _dedupe_text(
                [
                    str(item)
                    for item in direction.get("upgrade_package", [])
                    if str(item).strip()
                ]
            )
            combat_effect_uplift = str(
                direction.get("combat_effect_uplift", "")
            ).strip()
            strike_chain_contribution = str(
                direction.get("strike_chain_contribution", "")
            ).strip()
            upgrade_boundary = str(direction.get("upgrade_boundary", "")).strip()
            future_trigger = str(direction.get("future_trigger", "")).strip()
            adversary_adaptation = str(
                direction.get("adversary_adaptation", "")
            ).strip()
            failure_boundary = str(direction.get("failure_boundary", "")).strip()
            unique_operational_role = str(
                direction.get("unique_operational_role", "")
            ).strip()
            target_and_direct_effect = str(
                direction.get("target_and_direct_effect", "")
            ).strip()
            mechanism_chain = _dedupe_text(
                [
                    str(item)
                    for item in direction.get("mechanism_chain", [])
                    if str(item).strip()
                ]
            )
            non_substitutable_difference = str(
                direction.get("non_substitutable_difference", "")
            ).strip()
            uncertainty_boundary = str(
                direction.get("uncertainty_boundary", "")
            ).strip()
            feasibility_basis = str(direction.get("feasibility_basis", "")).strip()
            verification_plan = normalize_verification_plan(
                [baseline_operational_constraints, *verification_inputs],
                equipment_identity=equipment_identity,
                failure_boundary=failure_boundary or uncertainty_boundary,
            )
            derived_from = _dedupe_text(
                [str(item) for item in direction.get("derived_from", []) if str(item).strip()]
            )
            feasibility = direction.get("feasibility")
            horizon = str(direction.get("horizon", "")).strip()
            priority_code = str(direction.get("priority", "")).strip()
            priority_parts = [part for part in (priority_code, horizon) if part]
            if feasibility not in (None, ""):
                priority_parts.append(f"可行性{feasibility}/5")
            priority = " · ".join(priority_parts) or "待组合评审"
            try:
                direction_confidence = float(direction.get("confidence", l3.confidence))
            except (TypeError, ValueError):
                direction_confidence = l3.confidence
            direction_confidence = max(0.0, min(1.0, direction_confidence))
            generic_gap = (
                profile["new_gap"]
                if capability_type == "new_capability"
                else profile["upgrade_gap"]
            )
            capability_gap = direction_gap or generic_gap
            baseline_gap = baseline_system or gap_basis
            reasoning_refs = _dedupe_text(
                [
                    *derived_from,
                    *[str(item) for item in l3.outputs.get("reasoning_refs", [])],
                ]
            )
            agent_contributions = _agent_contributions(
                packets, capability_evidence_ids
            )
            structured_evidence_basis = _structured_evidence_basis(
                packets, capability_evidence_ids
            )
            portrait_verification_plan = _dedupe_text(
                [
                    *verification_plan,
                    *([feasibility_basis] if feasibility_basis else []),
                ]
            )
            calibrated_confidence, confidence_components = (
                calibrate_capability_confidence(
                    {
                        **direction,
                        "name": name,
                        "equipment_form": equipment_form,
                        "target_scenario": target_scenario,
                        "problem_statement": problem_statement,
                        "capability_gap": direction_gap or capability_gap,
                        "function": function,
                        "operational_mechanism": operational_mechanism or depth_mechanism,
                        "military_utility": military_value,
                        "strike_countermeasure_value": strike_countermeasure_value,
                        "evidence_ids": capability_evidence_ids,
                        "evidence_basis": structured_evidence_basis,
                        "verification_plan": portrait_verification_plan,
                        "development_path": development_path,
                        "failure_boundary": failure_boundary,
                        "adversary_adaptation": adversary_adaptation,
                    },
                    prior=direction_confidence,
                )
            )
            source_logic = _model_source_winning_logic(
                direction=direction,
                model_analysis=model_analysis,
                fallback=(
                    profile["new_logic"]
                    if capability_type == "new_capability"
                    else profile["upgrade_logic"]
                ),
            )
            countermeasure_value = (
                strike_countermeasure_value
                or depth_mechanism
                or detail["strike_countermeasure_value"]
            )
            deep_portrait = _compose_deep_capability_portrait(
                topic=topic,
                name=name,
                function=function,
                equipment_form=equipment_form,
                military_value=military_value,
                operational_mechanism=operational_mechanism or depth_mechanism,
                countermeasure_value=countermeasure_value,
                novelty=novelty,
                foresight=foresight,
                development_path=development_path,
                target_scenario=target_scenario,
                problem_statement=problem_statement,
                scientific_principle=scientific_principle,
                enabling_technologies=enabling_technologies,
                operational_concept=operational_concept,
                operational_process=operational_process,
                capability_outcome=capability_outcome,
                winning_mechanism=winning_mechanism,
                supplied_portrait=capability_portrait,
                baseline=baseline_system or gap_basis,
                failure_boundary=[
                    *([failure_boundary] if failure_boundary else []),
                    *([uncertainty_boundary] if uncertainty_boundary else []),
                    *(
                        [baseline_operational_constraints]
                        if not failure_boundary and not uncertainty_boundary
                        else []
                    ),
                    *detail["risk_boundaries"],
                ],
                verification_plan=portrait_verification_plan,
                expand_deterministic=False,
                # When S6 has completed its explicit whole-card Codex semantic
                # review, keep the accepted portrait and process together.
                # Local rendering remains a structural fallback for historical
                # cards that predate that contract; it must not choose a weapon
                # flow from title/baseline keywords.
                preserve_supplied=(
                    isinstance(
                        direction.get("semantic_consistency_check"), Mapping
                    )
                    and direction["semantic_consistency_check"].get("consistent")
                    is True
                ),
            )
            images.append(
                CapabilityImageItem(
                    capability_id=capability_id,
                    name=name,
                    equipment_category=equipment_form or (
                        profile["new_category"]
                        if capability_type == "new_capability"
                        else profile["upgrade_category"]
                    ),
                    capability_type=capability_type,
                    source_winning_logic=source_logic,
                    related_scenario=topic,
                    priority=priority,
                    capability_gap=(
                        f"{capability_gap}；该方向装备基线：{baseline_gap}"
                    ),
                    capability_image=deep_portrait,
                    evidence_ids=capability_evidence_ids,
                    confidence=calibrated_confidence,
                    confidence_components=confidence_components,
                    project_function=function,
                    mission_effect=military_value or detail["mission_effect"],
                    system_dependencies=detail["system_dependencies"],
                    risk_boundaries=[
                        *([f"未来触发：{future_trigger}"] if future_trigger else []),
                        *(
                            [f"对手反适应：{adversary_adaptation}"]
                            if adversary_adaptation
                            else []
                        ),
                        *([f"失效边界：{failure_boundary}"] if failure_boundary else []),
                        *([uncertainty_boundary] if uncertainty_boundary else []),
                        *([feasibility_basis] if feasibility_basis else []),
                        *detail["risk_boundaries"],
                    ],
                    military_utility=(
                        military_value
                        or query_relevance
                        or detail["mission_effect"]
                    ),
                    strike_countermeasure_value=countermeasure_value,
                    novelty=novelty or detail["novelty"],
                    foresight=foresight or detail["foresight"],
                    operational_constraints=[
                        *(
                            [f"对手反适应：{adversary_adaptation}"]
                            if adversary_adaptation
                            else []
                        ),
                        *([f"失效边界：{failure_boundary}"] if failure_boundary else []),
                        *([uncertainty_boundary] if uncertainty_boundary else []),
                        *detail["risk_boundaries"],
                    ],
                    evidence_basis=structured_evidence_basis,
                    agent_contributions=agent_contributions,
                    reasoning_refs=reasoning_refs,
                    deep_capability_portrait=deep_portrait,
                    equipment_form=equipment_form,
                    operational_mechanism=(
                        operational_mechanism or depth_mechanism or countermeasure_value
                    ),
                    development_path=(
                        development_path
                    ),
                    baseline_system=baseline_system,
                    upgrade_package=upgrade_package,
                    combat_effect_uplift=combat_effect_uplift,
                    strike_chain_contribution=strike_chain_contribution,
                    upgrade_boundary=upgrade_boundary,
                    target_scenario=target_scenario,
                    problem_statement=problem_statement,
                    scientific_principle=scientific_principle,
                    enabling_technologies=enabling_technologies,
                    operational_concept=operational_concept,
                    operational_process=operational_process,
                    capability_outcome=capability_outcome,
                    winning_mechanism=winning_mechanism,
                    unique_operational_role=unique_operational_role,
                    target_and_direct_effect=target_and_direct_effect,
                    mechanism_chain=mechanism_chain,
                    non_substitutable_difference=non_substitutable_difference,
                    adversary_adaptation=adversary_adaptation,
                    failure_boundary=failure_boundary,
                    verification_plan=verification_plan,
                    system_contribution_thesis=str(
                        direction.get("system_contribution_thesis", "")
                    ).strip(),
                    indicator_portrait=str(
                        direction.get("indicator_portrait", "")
                    ).strip(),
                    capability_portrait_modules=(
                        normalize_capability_portrait_modules(
                            direction.get("capability_portrait_modules", {}),
                            allow_structured_salvage=True,
                        )
                        if isinstance(
                            direction.get("capability_portrait_modules"), Mapping
                        )
                        else {}
                    ),
                    portrait_module_character_counts=(
                        capability_portrait_module_lengths(
                            normalize_capability_portrait_modules(
                                direction.get("capability_portrait_modules", {}),
                                allow_structured_salvage=True,
                            )
                        )
                        if isinstance(
                            direction.get("capability_portrait_modules"), Mapping
                        )
                        else {}
                    ),
                    portrait_quality_warnings=[
                        str(item).strip()
                        for item in direction.get(
                            "s6_authoring_quality_warnings", []
                        )
                        if str(item).strip()
                    ],
                    portrait_quality_contract_version=(
                        str(
                            direction.get("portrait_quality_contract_version")
                            or CAPABILITY_PORTRAIT_QUALITY_CONTRACT_VERSION
                        )
                        if isinstance(
                            direction.get("capability_portrait_modules"), Mapping
                        )
                        else ""
                    ),
                    capability_classification=(
                        dict(direction.get("capability_classification", {}))
                        if isinstance(direction.get("capability_classification", {}), Mapping)
                        else {}
                    ),
                    hypothesis_id=str(direction.get("hypothesis_id", "")).strip(),
                    card_binding_id=str(
                        direction.get("card_binding_id", "")
                    ).strip(),
                    source_hypothesis_title=str(
                        direction.get("source_hypothesis_title", "")
                    ).strip(),
                    primary_equipment_identity=str(
                        direction.get("primary_equipment_identity", "")
                    ).strip(),
                    semantic_consistency_check=(
                        dict(direction.get("semantic_consistency_check", {}))
                        if isinstance(direction.get("semantic_consistency_check"), Mapping)
                        else {}
                    ),
                    verification_status=str(
                        direction.get("verification_status", "assessed")
                    ).strip()
                    or "assessed",
                    confidence_limited=bool(
                        direction.get("confidence_limited", False)
                    ),
                    portrait_authoring_status=(
                        "s6_authored_semantically_consistent"
                        if (
                            isinstance(
                                direction.get("semantic_consistency_check"), Mapping
                            )
                            and direction["semantic_consistency_check"].get("consistent")
                            is True
                            and preserve_direction_identity
                            and str(direction.get("s6_authoring_status", ""))
                            in {
                                "authored_semantically_consistent",
                                # Quality-limited means a non-blocking S6
                                # advisory (for example near-duplicate
                                # clauses), not that the model card lost its
                                # identity. If all five structured modules
                                # survived, retain the authored card for the
                                # Reporter instead of replacing it with a
                                # generic deterministic portrait.
                                "authored_quality_limited",
                            }
                            and isinstance(
                                direction.get("capability_portrait_modules"), Mapping
                            )
                            and all(
                                str(
                                    direction["capability_portrait_modules"].get(key, "")
                                ).strip()
                                for key in (
                                    "overview",
                                    "technology_implementation",
                                    "operational_process",
                                    "capability_effects",
                                    "winning_logic",
                                )
                            )
                        )
                        else str(
                            direction.get("s6_authoring_status")
                            or "legacy_v1"
                        )
                    ),
                )
            )
        if preserve_direction_identity:
            # ``concept_directions`` is the S6 gate-approved final combination.
            # Its names and ordering are a delivery invariant. Generic fallback
            # enrichment must not replace a concrete S6 weapon title after the
            # gate has passed, otherwise the title and retained weapon fields
            # describe different equipment and poison audit/report generation.
            return images
        return [
            CapabilityImageItem(
                **rewrite_capability_for_military_value(
                    to_plain(item),
                    topic=topic,
                    route=route,
                )
            )
            for item in images
        ]

    def _recommend_missing_agents(
        self, coverage: dict[str, Any]
    ) -> list[AgentRecommendation]:
        return [
            AgentRecommendation(
                recommendation_id=f"agent-rec-{tag}",
                missing_capability_tag=tag,
                reason=f"当前启用agent未覆盖{tag}，会限制制胜机理研判。",
                suggested_agent_description=f"建议启用或新增具备{tag}能力标签的agent。",
            )
            for tag in coverage.get("missing_required_tags", [])
        ]


def _avg_confidence(packets: list[BaselineFindingPacket]) -> float:
    if not packets:
        return 0.0
    return round(mean(packet.confidence for packet in packets), 3)


def _effective_packets_after_recall(
    packets: list[BaselineFindingPacket],
) -> list[BaselineFindingPacket]:
    """Keep one evidence-bearing effective packet per business agent."""
    selected: dict[str, BaselineFindingPacket] = {}
    for packet in packets:
        current = selected.get(packet.agent_id)
        if current is None:
            selected[packet.agent_id] = packet
            continue
        packet_rank = (
            packet.admission_status != "rejected",
            bool(packet.evidence_ids),
            len(packet.evidence_ids),
            packet.created_at,
        )
        current_rank = (
            current.admission_status != "rejected",
            bool(current.evidence_ids),
            len(current.evidence_ids),
            current.created_at,
        )
        if packet_rank >= current_rank:
            selected[packet.agent_id] = packet
    return list(selected.values())


def _evidence_weighted_confidence(
    packets: list[BaselineFindingPacket],
) -> float:
    if not packets:
        return 0.0
    weights = [max(1, len(packet.evidence_ids)) for packet in packets]
    return round(
        sum(packet.confidence * weight for packet, weight in zip(packets, weights))
        / sum(weights),
        3,
    )


def _stage_attempt_suffix(stage_id: str) -> str:
    marker = "-r"
    return stage_id[stage_id.rfind(marker) :] if marker in stage_id else ""


def _packet_digest(packets: list[BaselineFindingPacket]) -> list[dict[str, Any]]:
    return [
        {
            "agent_id": packet.agent_id,
            "capability_tags": packet.capability_tags,
            "findings": packet.findings[:3],
            "confidence": packet.confidence,
            "evidence_ids": packet.evidence_ids,
        }
        for packet in packets
    ]


def _gap_basis(packets: list[BaselineFindingPacket]) -> str:
    values: list[str] = []
    for packet in packets:
        for key in (
            "current_parameters",
            "capability_constraints",
            "technology_readiness",
        ):
            value = packet.analysis_sections.get(key)
            if value not in (None, "", [], {}):
                values.extend(_summarize_analysis_value(value))
    if not values:
        values = [finding for packet in packets for finding in packet.findings]
    return "；".join(_dedupe_text(values)[:4]) or "尚无可采纳的现有能力基线"


def _capability_evidence_basis(packets: list[BaselineFindingPacket]) -> str:
    values: list[str] = []
    for packet in packets:
        for key in (
            "environment_constraints",
            "force_coordination",
            "operational_constraints",
            "capability_constraints",
        ):
            value = packet.analysis_sections.get(key)
            if value not in (None, "", [], {}):
                values.extend(_summarize_analysis_value(value))
    if not values:
        values = [
            packet.handoff_summary for packet in packets if packet.handoff_summary
        ]
    return "；".join(_dedupe_text(values)[:4]) or "需在下一轮补充场景与装备约束"


def _structured_evidence_basis(
    packets: list[BaselineFindingPacket], evidence_ids: list[str]
) -> list[str]:
    allowed = set(evidence_ids)
    rows: list[str] = []
    for packet in packets:
        matched = [item for item in packet.evidence_ids if item in allowed]
        if not matched:
            continue
        findings = _dedupe_text([*packet.findings, packet.handoff_summary])[:2]
        if findings:
            rows.append(
                f"{packet.agent_id}（{','.join(matched[:4])}）：{'；'.join(findings)}"
            )
    return rows[:6]


def _agent_contributions(
    packets: list[BaselineFindingPacket], evidence_ids: list[str]
) -> list[str]:
    allowed = set(evidence_ids)
    rows = []
    for packet in packets:
        if allowed and not allowed.intersection(packet.evidence_ids):
            continue
        contribution = packet.handoff_summary or next(iter(packet.findings), "")
        if contribution:
            rows.append(f"{packet.agent_id}：{_short_text(contribution, 140)}")
    return _dedupe_text(rows)[:6]


def _fallback_specific_weapon_directions(
    *,
    topic: str,
    route: str,
    profile: dict[str, str],
    military_profile: dict[str, Any],
    evidence_ids: list[str],
    confidence: float,
    gap_basis: str,
) -> list[dict[str, Any]]:
    """Keep a concrete multi-weapon portfolio when the S6 call misses its deadline."""
    del profile, military_profile
    directions = build_deadline_weapon_directions(
        topic=topic,
        evidence_ids=evidence_ids,
        confidence=confidence,
        gap_basis=gap_basis,
    )
    route_method = {
        "traditional_gap": "采用模块化任务载荷和现役火控接口补齐关键能力断点",
        "war_case_learning": "吸收战例中的低成本规模运用与战损后重构机制",
    }.get(route, "采用分布式决策与多域效应动态组合压缩打击闭环")
    if directions:
        first = directions[0]
        first["operational_mechanism"] = (
            f"{route_method}；{first.get('operational_mechanism', '')}"
        ).strip("；")
        first["operational_concept"] = first["operational_mechanism"]
        first["winning_mechanism"] = (
            f"{route_method}；{first.get('winning_mechanism', '')}"
        ).strip("；")
        first["capability_portrait"] = build_agent_led_capability_portrait(
            scenario=first.get("target_scenario", topic),
            problem=first.get("problem_statement", first.get("capability_gap", "")),
            principle=first.get("scientific_principle", route_method),
            technologies=first.get("enabling_technologies", []),
            operational_concept=first.get("operational_concept", route_method),
            operational_steps=first.get("operational_process", []),
            capability=first.get("capability_outcome", first.get("function", "")),
            effect=first.get("military_value", first.get("combat_effect_uplift", "")),
            winning_mechanism=first.get("winning_mechanism", route_method),
            equipment_form=first.get("equipment_form")
            or first.get("equipment_category", ""),
            baseline=first.get("baseline_system", ""),
            development_path=first.get("development_path", ""),
            failure_boundary=first.get("failure_boundary", ""),
            verification_plan=first.get("verification", ""),
        )
    return directions


def _model_source_winning_logic(
    *, direction: dict[str, Any], model_analysis: dict[str, Any], fallback: str
) -> str:
    upstream: list[str] = []
    for key in ("winning_paths", "effect_chain", "capability_mapping"):
        value = model_analysis.get(key)
        if value not in (None, "", [], {}):
            upstream.extend(_summarize_analysis_value(value))
    function = str(direction.get("function", "")).strip()
    chain = _dedupe_text(upstream)[:2]
    if chain and function:
        return f"{' → '.join(chain)} → 装备能力：{_short_text(function)}"
    if chain:
        return " → ".join(chain)
    return fallback


def _normalize_direction_name(value: object) -> str:
    """Remove internal candidate labels without changing the approved identity."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^(?:候选\s*)?[A-Ha-h]\s*[：:、.．)）-]\s*", "", text)
    return text.strip(" ，,；;。:：")


def _compose_deep_capability_portrait(
    *,
    topic: str,
    name: str,
    function: str,
    equipment_form: str,
    military_value: str,
    operational_mechanism: str,
    countermeasure_value: str,
    novelty: str,
    foresight: str,
    development_path: str,
    target_scenario: str = "",
    problem_statement: str = "",
    scientific_principle: str = "",
    enabling_technologies: list[str] | None = None,
    operational_concept: str = "",
    operational_process: list[str] | None = None,
    capability_outcome: str = "",
    winning_mechanism: str = "",
    supplied_portrait: str = "",
    baseline: str = "",
    failure_boundary: list[str] | str = "",
    verification_plan: str = "",
    expand_deterministic: bool = True,
    preserve_supplied: bool = False,
) -> str:
    supplied = normalize_capability_portrait_text(supplied_portrait)
    if preserve_supplied and supplied:
        return supplied
    del expand_deterministic
    return build_agent_led_capability_portrait(
        name=name,
        scenario=target_scenario or topic,
        problem=problem_statement,
        principle=(
            scientific_principle
            or operational_mechanism
            or winning_mechanism
            or novelty
        ),
        technologies=enabling_technologies or [],
        operational_concept=(
            operational_concept or operational_mechanism or countermeasure_value
        ),
        operational_steps=operational_process or [],
        capability=capability_outcome or function,
        effect=military_value or function,
        winning_mechanism=(
            winning_mechanism
            or countermeasure_value
            or operational_mechanism
            or novelty
            or foresight
        ),
        equipment_form=equipment_form or name,
        baseline=baseline,
        development_path=development_path,
        failure_boundary=failure_boundary,
        verification_plan=verification_plan,
    )


def _summarize_analysis_value(value: object) -> list[str]:
    if isinstance(value, list):
        rows: list[str] = []
        for item in value[:4]:
            rows.extend(_summarize_analysis_value(item))
        return rows
    if isinstance(value, dict):
        preferred_pairs = [
            ("parameter", "value"),
            ("constraint", "effect"),
            ("conclusion", ""),
            ("task", "constraints"),
            ("name", "assessment"),
            ("model", "maturity"),
        ]
        for primary, secondary in preferred_pairs:
            if value.get(primary):
                text = str(value[primary]).strip()
                if secondary and value.get(secondary):
                    detail = value[secondary]
                    if isinstance(detail, list):
                        detail = "、".join(str(item) for item in detail[:3])
                    text = f"{text}：{detail}"
                return [_short_text(text)]
        return [_short_text(f"{key}：{item}") for key, item in list(value.items())[:2]]
    text = str(value).strip()
    return [_short_text(text)] if text else []


def _short_text(value: str, limit: int = 180) -> str:
    normalized = " ".join(value.replace("\n", " ").split())
    return (
        normalized
        if len(normalized) <= limit
        else normalized[: limit - 1].rstrip() + "…"
    )


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _capability_detail_profile(route: str, capability_type: str) -> dict[str, object]:
    common = {
        "system_dependencies": [
            "与现有指挥信息、情报侦察、保障和训练体系形成标准化接口",
            "在通信受限、数据不完备和局部节点失效条件下支持降级运行",
        ],
        "risk_boundaries": [
            "公开证据不足的参数不得转化为确定性指标，保留区间与置信度",
            "不以单一平台性能替代体系任务效果，不假设持续高带宽连接",
        ],
        "foresight": "跟踪对手体系、频谱环境、智能化任务链和低成本规模化手段变化，按触发条件滚动调整能力基线。",
    }
    if capability_type == "upgrade":
        return {
            **common,
            "mission_effect": "以较短工程周期提升现役装备在复杂环境中的体系贡献度、任务适配性和持续保障能力。",
            "upgrade_package": [
                "开放数据与任务接口",
                "软件定义任务重构",
                "抗扰协同与故障降级",
                "状态监测和保障决策",
            ],
            "strike_countermeasure_value": "优先增强现役装备对复杂目标、电子压制、链路受扰和体系节点失效的发现、抗扰、反制与恢复能力。",
            "novelty": "以开放架构、软件定义和任务模块替代单项参数堆叠，使现役平台能够持续吸收新算法、新载荷和新协同方式。",
        }
    mission = (
        "形成可组合、可扩展、可降级的新型任务能力，缩短从发现问题到产生任务效果的闭环。"
    )
    if route == "war_case_learning":
        mission = "将公开战例中可迁移的有效机制转化为低成本、可规模化、可快速重构的新型任务能力。"
    elif route == "traditional_gap":
        mission = (
            "补齐传统任务链关键空白节点，在极端边界条件下提供可快速接入的专用能力。"
        )
    return {
        **common,
        "mission_effect": mission,
        # Do not manufacture a common combat-effect or novelty conclusion for
        # every new direction.  These fields are meaningful only when an S3/S4
        # or S6 agent has tied them to the weapon's actual target, effect
        # medium, employment window and baseline.
        "strike_countermeasure_value": "",
        "novelty": "",
    }


def _route_winning_path(route: str) -> str:
    if route == "traditional_gap":
        return "传统打法能力缺口 -> 当前装备对比 -> 残余差距 -> 升级需求。"
    if route == "war_case_learning":
        return "局部战争案例 -> 新打法/新能力/不足 -> 未来布局方向。"
    return "新制胜机制/新体系组合/新作战样式 -> 新装备能力增长点。"


def _route_capability_profile(route: str, topic: str = "") -> dict[str, str]:
    profile = military_capability_profile(topic, route)
    route_method = {
        "traditional_gap": "采用模块化任务载荷和现役火控接口补齐关键能力断点",
        "war_case_learning": "吸收战例中的低成本规模运用与战损后重构机制",
    }.get(route, "采用分布式决策与多域效应动态组合压缩打击闭环")
    return {
        "new_name": str(profile["new_name"]),
        "new_category": str(profile["new_form"]),
        "new_logic": "作战对象与失败窗口 -> 目标猎获/火力分配断点 -> 打击、拦截或反制效果 -> 新装备能力",
        "new_gap": str(profile["gap"]),
        "new_image": (
            f"形成{profile['new_name']}，以{profile['new_form']}为主要装备形态；"
            f"{route_method}；{profile['mechanism']}，直接作战效果为：{profile['effect']}"
        ),
        "upgrade_name": str(profile["upgrade_name"]),
        "upgrade_category": str(profile["upgrade_form"]),
        "upgrade_logic": "现役装备任务基线 -> 对抗条件下的目标/火力断点 -> 可承载升级项 -> 直接作战效果提升",
        "upgrade_gap": str(profile["gap"]),
        "upgrade_image": (
            f"围绕{profile['upgrade_name']}改进{profile['baseline']}；"
            f"{profile['mechanism']}，直接作战效果为：{profile['effect']}"
        ),
    }
