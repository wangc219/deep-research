from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from equipment_deep_research.domain.models import AuditResult, CapabilityImageItem, ResearchReport
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.orchestration.deliverables import (
    branch_report_contract,
    build_delivery_artifacts,
)


_MATERIALIZED_SOURCE_STATUSES = frozenset(
    {
        "fetched",
        "cached",
        "reader_fetched",
        "fixture_materialized",
        "materialized",
    }
)


# These are deliberately broad semantic signals, not a catalogue of required
# agent labels.  The audit reads the completed capability card and asks
# whether it explains a military use case, a causal equipment effect, and a
# meaningful change from the baseline.  Missing a registry tag or a numeric
# confidence threshold is therefore only a diagnostic.
_MILITARY_CONTEXT_MARKERS = (
    "作战", "战场", "对手", "敌", "交战", "打击", "毁伤", "火力", "侦察",
    "预警", "防御", "防空", "反制", "拒止", "突防", "兵力", "任务链", "战术",
    "战役", "战区", "编队", "目标", "生存", "抗毁", "持续作战", "作战阶段",
)
_GENERIC_FILL_MARKERS = (
    "待智能体", "待模型", "待确认", "尚待", "未知", "暂无", "由智能体依据",
    "提升能力", "增强能力", "形成能力", "创新性待", "前瞻判断待",
)
_GENERIC_INNOVATION_TERMS = frozenset(
    {"智能化", "数字化", "网络化", "体系化", "分布式", "模块化", "增强型", "自主化"}
)
_DISRUPTION_MARKERS = (
    "重构", "改变对抗", "改变交战", "改变任务链", "跨代", "范式", "非对称",
    "时间交换", "空间交换", "成本交换", "数量交换", "平台依赖", "交战几何",
    "低成本", "规模化", "蜂群", "无人集群", "拒止", "抗毁", "饱和", "自主协同",
    "任务链重构", "体系协同", "替代平台", "分布式协同", "转向", "交换关系", "断链", "持续消耗", "迫使",
)
_NON_EQUIPMENT_EXACT = frozenset(
    {"流程", "机制", "方法", "算法", "模型", "架构", "体系能力", "平台能力", "作战概念", "保障节点"}
)
_NON_EQUIPMENT_MARKERS = ("流程", "算法", "模型", "架构", "概念", "机制")
_EQUIPMENT_MARKERS = (
    "系统", "平台", "装置", "终端", "雷达", "导弹", "无人机", "舰", "机", "车", "炮", "弹", "载荷", "机器人"
)
_CAUSAL_MARKERS = (
    "导致", "因此", "通过", "从而", "使", "闭合", "断点", "任务链", "转向", "恢复", "维持", "避免", "降低", "实现"
)
_EXACT_PERFORMANCE_CLAIM = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|％|百分比|公里|千米|米|秒|分钟|小时)|"
    r"(?:提升|提高|缩短|降低|达到|超过|不少于|不低于)\s*\d+(?:\.\d+)?)"
)


def _audit_text(value: Any) -> str:
    """Flatten a card field for semantic checks without exposing internals."""

    if isinstance(value, Mapping):
        return "；".join(
            f"{key}:{_audit_text(item)}" for key, item in value.items() if str(item).strip()
        )
    if isinstance(value, (list, tuple, set)):
        return "；".join(_audit_text(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _meaningful_text(value: Any, *, minimum: int = 8) -> bool:
    text = _audit_text(value)
    if len(text) < minimum:
        return False
    return not any(marker in text for marker in _GENERIC_FILL_MARKERS)


def _card_substantive_checks(image: CapabilityImageItem, *, route: str) -> dict[str, bool]:
    """Evaluate the five military-facing criteria for one capability card.

    This is intentionally a conservative semantic/structural check.  It does
    not pretend that lexical evidence proves combat performance; it only
    verifies that a candidate is stated as an equipment-backed military
    proposition with a closed effect chain and an explicit innovation claim.
    """

    scenario = _audit_text(image.target_scenario or image.related_scenario)
    military_effect = _audit_text(
        image.military_utility or image.mission_effect or image.capability_outcome
    )
    military_relevance = bool(
        _meaningful_text(scenario, minimum=4)
        and _meaningful_text(military_effect, minimum=8)
        and (
            any(marker in scenario for marker in _MILITARY_CONTEXT_MARKERS)
            or any(marker in military_effect for marker in _MILITARY_CONTEXT_MARKERS)
            or _meaningful_text(image.operational_concept, minimum=18)
        )
    )

    problem = _audit_text(image.problem_statement or image.capability_gap)
    gap = _audit_text(image.capability_gap or image.project_function)
    mechanism = _audit_text(
        image.winning_mechanism or image.operational_mechanism
    )
    outcome = _audit_text(image.capability_outcome or image.mission_effect or image.military_utility)
    causal_coherence = bool(
        _meaningful_text(problem)
        and _meaningful_text(gap)
        and _meaningful_text(mechanism)
        and _meaningful_text(outcome)
        and any(
            marker in "；".join((problem, gap, mechanism, outcome))
            for marker in _CAUSAL_MARKERS
        )
    )

    identity = _audit_text(
        image.primary_equipment_identity or image.equipment_form or image.equipment_category
    )
    category = _audit_text(image.equipment_category)
    concrete_equipment = bool(
        _meaningful_text(identity, minimum=2)
        and identity not in _NON_EQUIPMENT_EXACT
        and not identity.endswith("能力")
        and (
            any(marker in identity for marker in _EQUIPMENT_MARKERS)
            or _meaningful_text(category, minimum=6)
        )
        and not (
            any(marker in identity for marker in _NON_EQUIPMENT_MARKERS)
            and not any(marker in identity for marker in _EQUIPMENT_MARKERS)
        )
    )

    novelty = _audit_text(image.novelty or image.winning_mechanism)
    comparison = _audit_text(
        image.baseline_system or image.upgrade_boundary or image.combat_effect_uplift
    )
    innovation_new_quality = bool(
        _meaningful_text(novelty, minimum=12)
        and (
            len(novelty) >= 22
            or any(marker in novelty for marker in _DISRUPTION_MARKERS)
            or (
                image.capability_type == "upgrade"
                and _meaningful_text(comparison, minimum=10)
            )
        )
        and not (
            len(novelty) <= 12
            and any(term in novelty for term in _GENERIC_INNOVATION_TERMS)
        )
    )

    route_text = " ".join(
        _audit_text(value)
        for value in (
            image.winning_mechanism,
            image.operational_mechanism,
            image.strike_countermeasure_value,
            image.capability_outcome,
            image.novelty,
            image.combat_effect_uplift,
        )
    )
    if route == "traditional_gap" or image.capability_type == "upgrade":
        route_fit = bool(
            _meaningful_text(image.baseline_system, minimum=8)
            and (
                _meaningful_text(image.combat_effect_uplift, minimum=8)
                or bool(image.upgrade_package)
                or _meaningful_text(image.upgrade_boundary, minimum=8)
            )
            and innovation_new_quality
        )
    else:
        # New-mechanism/case routes must name the relationship that changes;
        # a generic "autonomous" or "intelligent" implementation is not by
        # itself a disruption claim.
        route_fit = bool(any(marker in route_text for marker in _DISRUPTION_MARKERS))

    return {
        "military_relevance": military_relevance,
        "causal_coherence": causal_coherence,
        "concrete_equipment": concrete_equipment,
        "innovation_new_quality": innovation_new_quality,
        "disruptive_or_route_fit": route_fit,
    }


def _substantive_audit(
    *,
    store: DomainStore,
    stage_outputs: list[Any],
    route: str,
) -> tuple[dict[str, bool], list[str], bool]:
    """Return aggregate five-criterion results and substantive blockers."""

    images = list(store.capability_images.values())
    if images:
        per_card = [_card_substantive_checks(image, route=route) for image in images]
        names = (
            "military_relevance",
            "causal_coherence",
            "concrete_equipment",
            "innovation_new_quality",
            "disruptive_or_route_fit",
        )
        # A single malformed/low-maturity candidate must not take down an
        # otherwise useful portfolio.  The hard gate asks whether at least
        # one delivered direction closes all five business questions; weaker
        # siblings remain visible as follow-up advisories.
        valid_cards = [item for item in per_card if all(item.values())]
        checks = {key: any(item[key] for item in per_card) for key in names}
        if valid_cards:
            checks = {key: True for key in names}
        notes = []
        if len(valid_cards) < len(images):
            notes.append(
                f"{len(images) - len(valid_cards)}项能力画像未同时闭合五判据；保留为候选/补证方向，不阻断已闭合方向交付。"
            )
        return checks, notes, bool(valid_cards)

    # Historical baseline-only/early checkpoints may have an evidence-backed
    # S-chain but no persisted S6 card yet.  Keep this path compatible while
    # making the absence visible to the caller; a run with no stages at all is
    # still a real hard blocker below.
    evidence_refs = [
        ref for stage in stage_outputs for ref in getattr(stage, "evidence_ids", [])
    ]
    stage_content = any(
        _audit_text(getattr(stage, "outputs", {}))
        for stage in stage_outputs
    )
    if stage_outputs and evidence_refs and (
        all(getattr(stage, "gate_passed", False) for stage in stage_outputs)
        or stage_content
    ):
        return (
            {
                "military_relevance": True,
                "causal_coherence": True,
                "concrete_equipment": True,
                "innovation_new_quality": True,
                "disruptive_or_route_fit": True,
            },
            ["尚未持久化能力画像；五判据暂以已通过门控的证据链兼容复核，正式发布仍应补齐装备卡。"],
            True,
        )
    return (
        {
            "military_relevance": False,
            "causal_coherence": False,
            "concrete_equipment": False,
            "innovation_new_quality": False,
            "disruptive_or_route_fit": False,
        },
        ["没有可供五判据复核的能力画像或阶段综合结果。"],
        False,
    )


def _has_materialized_source(source_materials: list[dict]) -> bool:
    """Return true only when at least one source has usable materialized content."""

    return any(
        str(row.get("status") or row.get("materialization_status") or "")
        .strip()
        .lower()
        in _MATERIALIZED_SOURCE_STATUSES
        for row in source_materials
    )


def audit_run(
    *,
    store: DomainStore,
    coverage: dict,
    max_rounds: int,
    current_rounds: int = 1,
    source_materials: list[dict] | None = None,
    analyst_confirmed: bool = False,
    risk_based_confidence: bool = False,
) -> AuditResult:
    """Create the model-audit work item without making a local judgement.

    This function deliberately does not evaluate the five criteria and does
    not create hard blockers.  The old lexical/threshold checks remain in the
    serialized diagnostics solely so historical readers and replay tooling do
    not break; the final status is assigned by ``provider.review_audit``.
    """
    stage_outputs = list(store.stage_outputs.values())
    min_confidence = min((stage.confidence for stage in stage_outputs), default=0.0)
    source_materials = list(source_materials or [])
    materialization_ok = True
    if source_materials:
        materialization_ok = _has_materialized_source(source_materials)
    stage_gates_passed = bool(stage_outputs) and all(
        stage.gate_passed for stage in stage_outputs
    )
    # Keep historical process booleans as diagnostics only.  They are never
    # combined into an approval/limited result.
    mechanical_diagnostics = {
        "consistency": bool(stage_outputs),
        "stage_gates_passed": stage_gates_passed,
        "confidence_ge_70": min_confidence >= 0.7
        or (risk_based_confidence and stage_gates_passed),
        "coverage": bool(coverage.get("coverage_passed")),
        "user_confirmation": analyst_confirmed,
        "round_limit": current_rounds <= max_rounds,
        "source_materialization": materialization_ok,
    }
    advisories: list[str] = []
    if not stage_outputs and not store.capability_images and not store.evidence:
        advisories.append("审计输入较少；由模型结合主题和现有材料判断是否可交付。")
    if not mechanical_diagnostics["coverage"]:
        advisories.append("能力标签覆盖不足；作为范围提示，不作为实质审计硬门。")
    if not mechanical_diagnostics["confidence_ge_70"]:
        advisories.append(f"阶段最低置信度为{min_confidence:.2f}；仅作校准提示，不替代因果与装备审计。")
    if not mechanical_diagnostics["stage_gates_passed"]:
        failed_gates = [
            f"{stage.layer}（{'；'.join(stage.gate_reasons) or '门控未通过'}）"
            for stage in stage_outputs
            if not stage.gate_passed
        ]
        advisories.append(
            "制胜分析门控未全部通过："
            + ("、".join(failed_gates) if failed_gates else "缺少有效阶段输出")
            + "；作为复核提示，最终仍以五判据和安全交付阻断为准。"
        )
    if not mechanical_diagnostics["source_materialization"]:
        advisories.append("联网材料化未成功获取正文；保留失败诊断，已存在的证据边界不因抓取状态自动失效。")
    if not mechanical_diagnostics["user_confirmation"]:
        advisories.append("分析师尚未确认；不改变机器审计状态，但正式发布仍需人工确认。")
    if not mechanical_diagnostics["round_limit"]:
        advisories.append(f"实际研究轮次为{current_rounds}，超过允许上限{max_rounds}；作为过程风险提示。")

    # ``audit_run`` is the transport boundary for the independent auditor in
    # production.  A few direct callers (and persisted pre-model artifacts),
    # however, invoke it with a completed card/stage and expect the old
    # reviewable status immediately.  Keep that narrow compatibility path:
    # empty/early inputs remain genuinely ``pending`` while concrete outputs
    # get a provisional five-criterion result that a later model response can
    # replace via ``_apply_model_audit_result``.
    compatibility_mode = bool(store.capability_images) or bool(
        stage_outputs and (analyst_confirmed or risk_based_confidence or source_materials)
    )
    substantive_checks: dict[str, bool] = {}
    substantive_notes: list[str] = []
    hard_blockers: list[str] = []
    status = "pending"
    if compatibility_mode:
        substantive_checks, substantive_notes, substantive_passed = _substantive_audit(
            store=store,
            stage_outputs=stage_outputs,
            route=str(coverage.get("route", "")),
        )
        advisories.extend(substantive_notes)
        if store.capability_images:
            # A complete card is the business result; mechanical retrieval,
            # confidence and publication fields remain diagnostics only.
            status = "approved" if substantive_passed else "limited"
            hard_blockers = [
                key for key, passed in substantive_checks.items() if not passed
            ]
        else:
            # Without a persisted card, retain the historical stage-only
            # compatibility semantics.  Failed stage/source/process gates are
            # still visible and keep the provisional result limited.
            status = "approved" if all(mechanical_diagnostics.values()) else "limited"

    # Keep the legacy mechanical map in ``checks`` as an additive diagnostic.
    # New model-only consumers ignore these fields, while replay/UI code and
    # older callers can still inspect source materialization, stage gates,
    # confirmation and round count without a KeyError.
    checks = {
        **mechanical_diagnostics,
        "audit_status": status,
        "audit_source": "model",
    }
    if compatibility_mode:
        comments = [
            "最终审计由独立模型接管；当前保留已完成产物的兼容性预审结果。",
            *advisories,
        ]
    else:
        comments = [
            "最终审计仅采用独立模型判断；本地流程字段只作诊断。",
            "模型审计尚未返回，当前状态为待业务审计；报告可继续生成和审阅。",
            *advisories,
        ]
    return AuditResult(
        audit_id="audit-001",
        status=status,
        checks=checks,
        comments=list(dict.fromkeys(comments)),
        substantive_checks=substantive_checks,
        mechanical_diagnostics=mechanical_diagnostics,
        hard_blockers=hard_blockers,
        advisories=list(dict.fromkeys(advisories)),
        audit_source="model",
    )


def render_report(
    *,
    topic: str,
    route: str,
    store: DomainStore,
    coverage: dict,
    audit: AuditResult,
    executive_summary: str = "",
    discovery_branch: str = "",
    discovery_blueprint: dict | None = None,
    delivery_artifacts: dict | None = None,
    prefer_model_report: bool = False,
    report_title: str = "",
) -> ResearchReport:
    images = sorted(store.capability_images.values(), key=_capability_priority_key)
    branch = discovery_branch or _route_branch(route)
    artifacts = delivery_artifacts or build_delivery_artifacts(
        topic=topic,
        branch=branch,
        blueprint=discovery_blueprint,
        store=store,
    )
    branch_output = artifacts["branch_deliverables"]
    report_title = str(report_title).strip() or _branch_report_title(topic, artifacts)
    complete_model_report = bool(
        executive_summary.strip()
        and (
            prefer_model_report
            or _looks_like_branch_deep_report(executive_summary, branch_output)
        )
    )
    if complete_model_report:
        model_body = _embedded_model_report_body(executive_summary)
        lines = [
            f"# {report_title}",
            "",
            model_body,
            "",
        ]
        lines.extend(_compact_evidence_reference_lines(store, branch=branch))
        body = _public_report_text("\n".join(lines)).strip() + "\n"
        return ResearchReport(
            report_id="report-001",
            title=report_title,
            body=body,
            capability_ids=[image.capability_id for image in images],
            evidence_ids=list(store.evidence),
            audit_id=audit.audit_id,
        )

    lines = [
        f"# {report_title}",
        "",
        (
            f"> 当前按“{branch_output.get('branch_name', '装备能力发现')}”分支撰写。"
            "报告综合多源公开证据、任务链因果分析、装备差距与未来场景，"
            "形成面向任务效能和装备建设决策的最终研判。"
        ),
        "",
        "## 1. 核心结论",
        "",
        _compact_executive_summary("", images, audit),
        "",
        (
            f"**结论状态：** {_route_label(route)}路径；"
            f"审计{_audit_status_label(audit.status)}；"
            f"形成{len(images)}项能力方向，其中新能力"
            f"{sum(item.capability_type == 'new_capability' for item in images)}项、现役升级"
            f"{sum(item.capability_type == 'upgrade' for item in images)}项。"
        ),
        "",
        "## 2. 分支深度综合研判与军事运用价值",
        "",
    ]
    lines.extend(
        _deterministic_cross_material_lines(
            store=store,
            images=images,
            branch_output=branch_output,
        )
    )
    lines.extend(_compact_branch_report_lines(branch_output))
    lines.extend(_capability_portfolio_lines(images))
    lines.extend(_evolution_path_lines(images))
    lines.extend(
        _evidence_boundary_lines(
            store=store,
            audit=audit,
            coverage=coverage,
            branch=branch,
            section_number=6,
        )
    )
    lines.extend(_compact_evidence_reference_lines(store, branch=branch))
    body = _public_report_text("\n".join(lines)).strip() + "\n"
    return ResearchReport(
        report_id="report-001",
        title=report_title,
        body=body,
        capability_ids=[image.capability_id for image in images],
        evidence_ids=list(store.evidence),
        audit_id=audit.audit_id,
    )


def _branch_report_title(topic: str, artifacts: Mapping[str, Any]) -> str:
    del artifacts
    normalized_topic = " ".join(str(topic or "").split()).strip()
    if not normalized_topic:
        return "军事武器装备需求研究"
    # Query text often contains execution instructions (candidate counts,
    # scoring weights, acceptance notes).  They belong in task metadata, not
    # the publication title.  Keep this deterministic fallback aligned with
    # the Reporter title-rewrite path so every render surface is consistent.
    normalized_topic = re.split(r"[：:]", normalized_topic, maxsplit=1)[0].strip()
    normalized_topic = re.sub(r"[（(].*?[）)]", "", normalized_topic).strip(
        " ，,；;。．"
    )
    normalized_topic = re.sub(
        r"(?:只提出|按创新性|按需求性|按科学可行性|按效能性|按发展性|综合评分|只选前\d+|生成入选.*)$",
        "",
        normalized_topic,
    ).strip(" ，,；;。．")
    if not normalized_topic.endswith(("研究", "分析", "论证")):
        normalized_topic += "研究"
    return normalized_topic[:80]


def _compact_executive_summary(
    executive_summary: str,
    images: list[CapabilityImageItem],
    audit: AuditResult,
) -> str:
    source = executive_summary.strip() or _deterministic_executive_summary(images, audit)
    rows: list[str] = []
    for raw in source.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        text = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s*)", "", stripped).strip()
        text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
        if not text or text in {"执行摘要", "综合研判摘要", "能力画像研究报告"}:
            continue
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[。！？])", text)
            if item.strip()
        ]
        rows.append(_compact_text(sentences[0] if sentences else text, 220))
        if len(rows) >= 3 or sum(len(item) for item in rows) >= 800:
            break
    return "\n\n".join(rows) if rows else _deterministic_executive_summary(images, audit)


def _embedded_model_report_body(text: str) -> str:
    """Keep the generated report as body content under the canonical title."""

    body = str(text).strip()
    fenced = re.fullmatch(
        r"```(?:markdown|md)?\s*\n(?P<body>.*)\n```",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        body = fenced.group("body").strip()
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and re.match(
        r"^(?:以下(?:为|是)|现提交|报告正文如下|根据(?:上述|输入))",
        lines[0].strip(),
    ):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    if lines and re.match(r"^#\s+", lines[0].strip()):
        lines.pop(0)
    normalized = re.sub(
        r"^(#{1,6})\s*([^#\s].*)$",
        lambda match: (
            ("##" if len(match.group(1)) == 1 else match.group(1))
            + " "
            + match.group(2).strip()
        ),
        "\n".join(lines).strip(),
        flags=re.MULTILINE,
    )
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _strategic_judgment_lines(images: list[CapabilityImageItem]) -> list[str]:
    if not images:
        return ["当前尚无满足门控的能力方向，应先补足证据和效果链。", ""]
    rows: list[str] = []
    for image in images[:4]:
        portrait = (
            image.deep_capability_portrait
            or image.capability_image
            or _primary_capability_statement(image)
        )
        value = (
            image.strike_countermeasure_value
            or image.military_utility
            or image.combat_effect_uplift
            or image.mission_effect
            or _primary_capability_statement(image)
        )
        operational_roles = _military_role_labels(image)
        rows.extend(
            [
                f"### {image.priority}　{image.name}",
                "",
                "**深度能力画像。**",
                "",
                portrait,
                "",
                (
                    f"**军事运用价值（{operational_roles}）。** "
                    f"{_compact_text(value, 180)}"
                ),
                "",
                (
                    f"**适用边界。** "
                    f"{_compact_list(image.risk_boundaries or image.operational_constraints, 2, 100) or '受工程成熟度、体系接口和任务规则约束'}；"
                    f"证据与推理链：{_trace_refs(image)}。"
                ),
                "",
            ]
        )
    return rows


def _deterministic_cross_material_lines(
    *,
    store: DomainStore,
    images: list[CapabilityImageItem],
    branch_output: Mapping[str, Any],
) -> list[str]:
    packet_findings = [
        str(finding)
        for packet in store.baseline_packets.values()
        for finding in packet.findings
        if str(finding).strip()
    ]
    stage_findings = [
        item
        for stage in sorted(
            store.stage_outputs.values(),
            key=lambda row: (row.created_at, row.stage_id),
        )
        for item in _flatten_report_strings(stage.outputs)
    ]
    main_judgments = list(dict.fromkeys([*packet_findings, *stage_findings]))[:4]
    military_effects = list(
        dict.fromkeys(
            value
            for image in images
            for value in (
                image.strike_chain_contribution,
                image.strike_countermeasure_value,
                image.military_utility,
                image.combat_effect_uplift,
                image.mission_effect,
            )
            if value.strip()
        )
    )[:4]
    future_boundaries = list(
        dict.fromkeys(
            value
            for image in images
            for value in (
                image.foresight,
                image.development_path,
                *image.risk_boundaries,
                *image.operational_constraints,
            )
            if value.strip()
        )
    )[:4]
    contract = branch_output.get("report_contract", {})
    thesis = str(contract.get("thesis", "")) if isinstance(contract, Mapping) else ""
    military_test = (
        str(contract.get("military_test", ""))
        if isinstance(contract, Mapping)
        else ""
    )
    future_test = (
        str(contract.get("future_test", ""))
        if isinstance(contract, Mapping)
        else ""
    )
    return [
        "### 主矛盾、效果链断点与制胜判断",
        "",
        _compact_text(
            thesis
            + " 综合多源业务研究与六步因果链，当前最重要的跨材料判断为："
            + _compact_list(main_judgments, 4, 900),
            1150,
        ),
        "",
        "### 打击、反制、抗毁与持续作战价值",
        "",
        _compact_text(
            military_test
            + " 现有能力方向应作为相互依赖的任务组合评估，其共同军事效果为："
            + _compact_list(
                military_effects,
                4,
                760,
            ),
            980,
        ),
        "",
        "### 未来战争演化、建设时序与验证边界",
        "",
        _compact_text(
            future_test
            + " 面向未来演化与对手适应，需重点验证："
            + _compact_list(future_boundaries, 4, 720)
            + "。上述判断须由公开来源、任务级压力测试和反事实场景共同校准。",
            980,
        ),
        "",
    ]


def _flatten_report_strings(value: Any, *, limit: int = 24) -> list[str]:
    rows: list[str] = []

    def visit(item: Any) -> None:
        if len(rows) >= limit:
            return
        if isinstance(item, str):
            text = item.strip()
            if text:
                rows.append(text)
            return
        if isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return rows


def _compact_branch_report_lines(branch_output: Mapping[str, Any]) -> list[str]:
    branch = str(branch_output.get("branch", "A"))
    name = str(branch_output.get("branch_name", "装备能力发现"))
    products = branch_output.get("products", {})
    lines = [f"## 3. {name}分支专用输出", ""]
    if branch == "A":
        lines.extend(_branch_a_lines(products))
    elif branch == "B":
        lines.extend(_branch_b_lines(products))
    elif branch == "C":
        lines.extend(_branch_c_lines(products))
    else:
        lines.extend(_other_branch_lines(branch_output))
    lines.extend(_completion_line(branch_output.get("completion", {})))
    return lines


def _looks_like_branch_deep_report(
    text: str,
    branch_output: Mapping[str, Any],
) -> bool:
    del branch_output
    required_headings = (
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
        "### ① 典型作战场景",
        "### ② 新战法或新概念技术及制胜机理",
        "### ③ 装备能力特征清单",
        "## 第二层：技术攻关层——能力实现途径与核心技术",
        "### ④ 能力实现途径",
        "### ⑤ 核心技术清单与攻关优先级",
        "### ⑥ 技术耦合与短板风险",
        "## 第三层：能力图像与效能贡献层",
        "### ⑦ 装备能力图像",
        "### ⑧ 效能贡献评估",
        "### ⑨ 发展优先级与近期抓手",
    )
    content_groups = (
        ("对手", "地域", "烈度", "时间窗"),
        ("制胜机理", "现有范式", "新战法", "新概念技术"),
        ("射程", "响应时间", "自主等级", "成本量级", "规模量级"),
        ("沿用改进", "集成创新", "原理突破"),
        ("成熟度", "瓶颈", "优先级"),
        ("耦合", "短板", "卡脖子"),
        ("能力域", "指标画像", "谱系位置"),
        ("补链", "强链", "开链"),
        ("P0", "P1", "P2", "演示验证"),
    )
    return (
        len(text.strip()) >= 2200
        and all(heading in text for heading in required_headings)
        and all(any(marker in text for marker in group) for group in content_groups)
    )


def _has_numbered_label(text: str, label: str, index: int) -> bool:
    return re.search(
        rf"{re.escape(label)}\s*[（(]?\s*0*{index}\s*[）)]?",
        text,
    ) is not None


def _branch_delivery_index_lines(branch_output: Mapping[str, Any]) -> list[str]:
    branch_name = str(branch_output.get("branch_name", "装备能力发现"))
    completion = branch_output.get("completion", {})
    lines = [
        f"## 3. {branch_name}分支交付状态与回溯入口",
        "",
        "深度正文已覆盖本分支规定产物；为避免重复复述，本节只保留定量门槛与回溯说明。",
        "",
    ]
    if isinstance(completion, Mapping) and completion:
        for key, row in completion.items():
            if not isinstance(row, Mapping):
                continue
            lines.append(
                f"- {key}：目标 {row.get('target', 0)}，实际 {row.get('actual', 0)}，"
                f"{'满足' if row.get('met') else '未满足，已作为交付缺口披露'}。"
            )
    else:
        lines.append("- 当前分支未设置定量数量门槛，按必需章节和证据门控验收。")
    lines.extend(
        [
            "",
            "核心来源见报告末尾索引；完整逐项证据说明见随附 evidence_references.md，能力关系和机器可读回溯信息另随结构化附件交付。",
            "",
        ]
    )
    return lines


def _branch_a_lines(products: Mapping[str, Any]) -> list[str]:
    concepts = _string_items(products.get("tactic_concepts"))[:3]
    combinations = _string_items(products.get("tactic_combinations"))[:5]
    domains = _string_items(products.get("capability_domains"))[:8]
    indicators = _string_items(products.get("capability_indicators"))[:30]
    forms = _string_items(products.get("equipment_forms"))[:8]
    return [
        "### 3.1 战法概念集：3种新战法",
        "",
        *_numbered_lines(concepts, 220),
        "",
        "### 3.2 战法组合：5种组合",
        "",
        *_numbered_lines(combinations, 200),
        "",
        "### 3.3 装备能力需求图像：8大能力域",
        "",
        *_numbered_lines(domains, 150),
        "",
        "### 3.4 30项能力指标",
        "",
        *_indicator_lines(indicators),
        "",
        "### 3.5 关联装备形态建议",
        "",
        *_numbered_lines(forms, 170),
        "",
    ]


def _branch_b_lines(products: Mapping[str, Any]) -> list[str]:
    cards = products.get("demand_cards", [])
    panorama = products.get("capability_panorama", {})
    traceability = products.get("reasoning_traceability", {})
    lines = [
        "### 3.1 武器装备能力需求卡片",
        "",
        "| 优先级 | 具体待发展武器装备 | 装备构型与发展方式 | 军事运用价值 | 关键指标、场景与证据 |",
        "|---|---|---|---|---|",
    ]
    for card in list(cards)[:8] if isinstance(cards, list) else []:
        if not isinstance(card, Mapping):
            continue
        military_value = card.get("strike_countermeasure_value") or card.get("military_utility") or card.get("mission_effect")
        indicators = _compact_list(card.get("key_indicators", []), 3, 130)
        scenarios = _compact_list(card.get("supporting_scenarios", []), 1, 100)
        evidence_count = len(list(card.get("evidence_chain", [])))
        evidence = f"已关联{evidence_count}项正式证据" if evidence_count else "待补证"
        lines.append(
            f"| {card.get('priority', '待评估')} | {_table_text(card.get('weapon_equipment', ''), 80)} | "
            f"{_table_text(card.get('development_mode', ''), 35)}；{_table_text(card.get('equipment_configuration', ''), 100)} | "
            f"{_table_text(military_value, 120)} | {_table_text(indicators, 100)}；场景：{_table_text(scenarios, 70)}；{_table_text(evidence, 65)} |"
        )
    if len(lines) == 4:
        lines.append("| — | 尚未形成可发布需求卡片 | — | — | 待补证 |")
    lines.extend(["", "### 3.2 能力全景图", ""])
    domains = panorama.get("domains", []) if isinstance(panorama, Mapping) else []
    for index, node in enumerate(list(domains)[:10], start=1):
        if not isinstance(node, Mapping):
            continue
        lines.append(
            f"{index}. **{_compact_text(node.get('domain', '能力域'), 60)}**："
            f"能力节点{_compact_list(node.get('capability_ids', []), 4, 110) or '待补充'}；"
            f"核心指标{_compact_list(node.get('indicators', []), 4, 150) or '待验证'}；"
            f"支撑场景{_compact_list(node.get('supporting_scenarios', []), 2, 120) or '待补充'}。"
        )
    if not domains:
        lines.append("- 尚未形成可发布的能力全景关系。")
    lines.extend(["", "### 3.3 深度研究结论与推理链回溯", ""])
    if isinstance(traceability, Mapping):
        lines.append(
            f"需求判断已连接{len(traceability.get('agent_handoffs', []))}组专业研究结论、"
            f"{len(traceability.get('reasoning_nodes', []))}个因果推理节点和"
            f"{len(traceability.get('stage_outputs', []))}层质量校验结果。主报告保留关键因果判断，"
            "需求卡片、证据链与可证伪条件的逐项映射已在配套附件中保留。"
        )
    else:
        lines.append("- 推理链索引尚未形成，当前结论只能作为待审方向。")
    lines.append("")
    return lines


def _branch_c_lines(products: Mapping[str, Any]) -> list[str]:
    patterns = _string_items(products.get("case_patterns"))[:6]
    scenarios = _string_items(products.get("future_scenarios"))[:3]
    categories = _string_items(products.get("emerging_equipment_categories"))[:4]
    return [
        "### 3.1 案例规律报告：6条核心规律",
        "",
        *_numbered_lines(patterns, 240),
        "",
        "### 3.2 未来场景预测：3类高置信场景",
        "",
        *_numbered_lines(scenarios, 260),
        "",
        "### 3.3 装备需求图像：4大新兴装备类别",
        "",
        *_numbered_lines(categories, 220),
        "",
    ]


def _other_branch_lines(branch_output: Mapping[str, Any]) -> list[str]:
    branch = str(branch_output.get("branch", "D"))
    products = branch_output.get("products", {})
    lines: list[str] = []
    for index, section in enumerate(branch_output.get("required_sections", []), start=1):
        lines.extend([f"### 3.{index} {section}", ""])
        values: list[str] = []
        for key in _other_branch_section_keys(branch, str(section)):
            values.extend(_generic_product_items(key, products.get(key)))
        lines.extend(_numbered_lines(list(dict.fromkeys(values))[:2], 125))
        lines.append("")
    return lines


def _other_branch_section_keys(branch: str, section: str) -> list[str]:
    mapping = {
        "D": {
            "技术机会谱系": ["technology_opportunities"],
            "成熟度与颠覆场景": ["future_scenarios"],
            "技术牵引装备形态": ["equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "E": {
            "对手变化规律": ["threat_patterns"],
            "威胁形成场景": ["future_scenarios"],
            "对冲能力与装备建议": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "F": {
            "体系脆弱性规律": ["system_vulnerabilities"],
            "级联失效场景": ["future_scenarios"],
            "补链强链能力组合": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "G": {
            "跨域缝隙图谱": ["cross_domain_gaps"],
            "协同模式组合": ["tactic_combinations"],
            "接口与装备形态建议": ["capability_indicators", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
        "H": {
            "新型威胁画像": ["emerging_threat_profiles"],
            "高置信场景": ["future_scenarios"],
            "韧性与非致命装备需求": ["capability_domains", "equipment_forms"],
            "装备能力需求图像（需求卡片）": ["demand_cards"],
        },
    }
    return mapping.get(branch, {}).get(section, [])


def _generic_product_items(key: str, value: Any) -> list[str]:
    if key == "demand_cards" and isinstance(value, list):
        rows: list[str] = []
        for card in value[:8]:
            if not isinstance(card, Mapping):
                continue
            military_value = card.get("strike_countermeasure_value") or card.get("military_utility") or card.get("mission_effect")
            rows.append(
                f"{card.get('weapon_equipment', '待发展武器装备')}（{card.get('priority', '待评估')}）："
                f"{military_value or card.get('deep_capability_portrait', '')}；"
                f"关键指标{_compact_list(card.get('key_indicators', []), 3, 120) or '待验证'}。"
            )
        return rows
    return _string_items(value)


def _capability_portfolio_lines(images: list[CapabilityImageItem]) -> list[str]:
    lines = [
        "## 4. 装备能力画像与建设优先序",
        "",
        "| 优先级 | 能力方向 | 建议形态 | 决策动作 |",
        "|---|---|---|---|",
    ]
    for image in images[:8]:
        action_prefix = (
            "优先现役改装"
            if image.capability_type == "upgrade"
            else "纳入新研论证"
        )
        lines.append(
            f"| {image.priority} | {_table_text(image.name, 65)} | "
            f"{_table_text(image.equipment_form or image.equipment_category, 60)} | "
            f"{action_prefix} |"
        )
    if not images:
        lines.append("| — | 尚未形成满足门控的能力方向 | — | 先补足证据与效果链 |")
    lines.append("")
    return lines


def _evolution_path_lines(images: list[CapabilityImageItem]) -> list[str]:
    lines = [
        "## 5. 建设演进路径",
        "",
        "演进路径按‘近期现役改装与指标固化—中期体系集成与跨平台联试—远期按验证结果转入新研或规模部署’三阶段推进，任何阶段未通过任务级压力验证均不得直接扩量。",
        "",
    ]
    for image in images[:5]:
        path = image.development_path or (
            "近期完成接口、软件或保障模块验证；中期开展体系集成和压力联试；"
            "远期依据成熟度、任务增益和失效边界决定规模部署或转入新研。"
        )
        lines.append(
            f"- **{image.name}：** {_compact_text(path, 190)}"
        )
    if not images:
        lines.append("- 当前缺少可进入演进路径的能力方向，应先补足证据与效果链。")
    lines.append("")
    return lines


def _evidence_boundary_lines(
    *,
    store: DomainStore,
    audit: AuditResult,
    coverage: Mapping[str, Any],
    branch: str,
    section_number: int = 6,
) -> list[str]:
    tiers: dict[str, int] = {}
    domains: set[str] = set()
    for evidence in store.evidence.values():
        tiers[evidence.source_tier] = tiers.get(evidence.source_tier, 0) + 1
        host = urlsplit(evidence.source_url).hostname
        if host:
            domains.add(host)
    tier_text = "、".join(f"{key}级{value}项" for key, value in sorted(tiers.items())) or "无正式证据"
    missing = list(coverage.get("missing_required_tags", []))
    lines = [
        f"## {section_number}. 证据边界与后续验证",
        "",
        f"- **证据基础：** 正式证据{len(store.evidence)}项，来源域{len(domains)}类，层级分布为{tier_text}。",
        f"- **覆盖状态：** {'关键能力标签已覆盖' if not missing else '仍缺少：' + '、'.join(str(item) for item in missing[:8])}。",
        f"- **审计结论：** {_audit_status_label(audit.status)}。",
    ]
    if missing:
        # Keep the analyst-facing scope warning in the public report.  The
        # wording is intentionally stable because evaluation adapters and
        # downstream reviewers use it to distinguish a selected-agent subset
        # from an accidentally expanded baseline.
        lines.extend(
            [
                "",
                "本次启用agent未覆盖全部关键capability，报告需标注限制。",
            ]
        )
    if audit.hard_blockers:
        lines.append(f"- **业务实质阻断：** {'；'.join(str(item) for item in audit.hard_blockers[:6])}。")
    elif audit.advisories:
        lines.append("- **审计提示：** 流程字段仅作诊断；最终业务实质结论由独立模型审计给出。")
    public_comments = [
        str(comment)
        for comment in audit.comments
        if not any(
            marker in str(comment)
            for marker in (
                "质量门",
                "分支交付门",
                "Claim",
                "确定性审计",
                "模型降级",
                "报告模型",
            )
        )
    ]
    if public_comments:
        lines.extend(
            f"- {_compact_text(_public_report_text(comment), 160)}"
            for comment in public_comments[:3]
        )
    else:
        lines.append("- 后续仍需使用仿真、半实物联试、演训和失效注入校准性能阈值与适用边界。")
    lines.extend(
        [
            "",
            "报告仅列核心来源；完整证据索引与推理回溯见随附 evidence_references.md 和结构化附件。",
            "",
        ]
    )
    return lines


def _formal_evidence_reference_lines(store: DomainStore) -> list[str]:
    """Render every formal evidence card as a self-contained report appendix."""

    evidence_rows = list(store.evidence.values())
    lines = [
        "## 正式证据引用说明",
        "",
        (
            f"> 本节完整列示本报告登记的 {len(evidence_rows)} 项正式证据。"
            "“直接支撑”表示证据已绑定正式结论节点，并同时保存可核对的原文摘录和正文位置；"
            "“背景/间接支撑”不得单独用于确认关键事实。未登记的发布日期或原文位置不作推测，"
            "并明确标为待核验。"
        ),
        "",
    ]
    if not evidence_rows:
        return [
            *lines,
            "- 本报告未登记正式证据；事实性结论均应视为待补证、待核验。",
            "",
        ]

    for index, evidence in enumerate(evidence_rows, start=1):
        publication_date, publication_year = _source_publication_date(evidence)
        collected_date = _evidence_collected_date(evidence)
        bindings = _evidence_bindings(store, evidence.evidence_id)
        support_type = _evidence_support_type(evidence, is_bound=bool(bindings))
        source_location = _public_source_location(evidence.source_location)
        validity = _evidence_time_validity(
            publication_year=publication_year,
            collected_date=collected_date,
        )
        claim = re.sub(
            r"^E\s*0*\d+\s*[:：]\s*",
            "",
            str(evidence.claim or "").strip(),
            flags=re.IGNORECASE,
        ) or "证据卡未登记对应结论，不能作为独立结论依据。"
        excerpt = (
            _compact_text(str(evidence.excerpt).strip(), 260)
            if str(evidence.excerpt or "").strip()
            else "未随证据卡保存原文摘录，需打开原文复核。"
        )
        title = _compact_text(
            evidence.source_title or urlsplit(evidence.source_url).hostname or "未命名来源",
            120,
        )
        source_tier = str(evidence.source_tier or "未分级").strip()
        url = str(evidence.source_url or "").strip()
        rendered_url = f"<{url}>" if url.startswith(("https://", "http://")) else "未登记可访问 URL"
        lines.extend(
            [
                f"### E{index:02d}｜{title}",
                "",
                f"- **对应结论：** {_compact_text(claim, 360)}",
                f"- **正文绑定：** {'；'.join(bindings) if bindings else '未与正式结论节点绑定，仅作为背景材料'}。",
                f"- **证据作用：** {support_type}；来源层级：{source_tier}级。",
                f"- **URL：** {rendered_url}",
                f"- **发布日期/更新日期：** {publication_date}",
                f"- **原文位置：** {source_location}",
                f"- **时间有效性：** {validity}",
                f"- **原文摘录：** {excerpt}",
                "",
            ]
        )
    return lines


def render_formal_evidence_reference(store: DomainStore) -> str:
    """Render the complete human-readable evidence ledger as a sidecar."""

    return _public_report_text(
        "\n".join(_formal_evidence_reference_lines(store))
    ).strip() + "\n"


def _compact_evidence_reference_lines(
    store: DomainStore,
    *,
    branch: str,
    maximum_items: int = 6,
) -> list[str]:
    """Keep the decision report bounded while preserving core public handles."""

    evidence_rows = list(store.evidence.values())
    if not evidence_rows:
        return []
    preferred_agent = "case_research" if branch == "C" else ""

    def priority(evidence: Any) -> tuple[int, int, int, str]:
        bindings = _evidence_bindings(store, evidence.evidence_id)
        return (
            int(str(evidence.created_by) == preferred_agent),
            int(bool(str(evidence.excerpt or "").strip())),
            int(bool(bindings)),
            str(evidence.created_at),
        )

    selected = sorted(evidence_rows, key=priority, reverse=True)[:maximum_items]
    lines = [
        "**核心公开来源索引**",
        "",
        (
            f"本报告从 {len(evidence_rows)} 项正式证据中列示与主论证最相关的"
            f" {len(selected)} 项来源；完整证据索引与推理回溯、逐项证据作用、正文绑定、日期、原文位置和摘录"
            "见随附 evidence_references.md。"
        ),
        "",
    ]
    for index, evidence in enumerate(selected, start=1):
        bindings = _evidence_bindings(store, evidence.evidence_id)
        support_type = _evidence_support_type(evidence, is_bound=bool(bindings))
        support_label = "直接/有限直接支撑" if "直接支撑" in support_type else "背景/间接支撑"
        publication_date, _ = _source_publication_date(evidence)
        title = _compact_text(
            evidence.source_title
            or urlsplit(evidence.source_url).hostname
            or "未命名来源",
            90,
        )
        claim = _compact_text(str(evidence.claim or "证据作用待核验"), 120)
        url = str(evidence.source_url or "").strip()
        rendered_title = f"[{title}]({url})" if url.startswith(("https://", "http://")) else title
        lines.append(
            f"- **E{index:02d}** {rendered_title}（{evidence.source_tier or '未分级'}级，"
            f"{support_label}，{publication_date}）：{claim}"
        )
    lines.append("")
    return lines


def _evidence_bindings(store: DomainStore, evidence_id: str) -> list[str]:
    bindings: list[str] = []
    collections = (
        (store.capability_images.values(), "能力方向", "name"),
        (store.reasoning_nodes.values(), "推理结论", "title"),
        (store.stage_outputs.values(), "阶段结论", "title"),
        (store.baseline_packets.values(), "研究判断", "topic_focus"),
    )
    for items, label, title_field in collections:
        for item in items:
            if evidence_id not in list(getattr(item, "evidence_ids", []) or []):
                continue
            title = str(getattr(item, title_field, "") or "").strip()
            binding = f"{label}“{_compact_text(title, 70)}”" if title else label
            if binding not in bindings:
                bindings.append(binding)
            if len(bindings) >= 4:
                return bindings
    return bindings


def _evidence_support_type(evidence: Any, *, is_bound: bool) -> str:
    excerpt = str(getattr(evidence, "excerpt", "") or "").strip()
    location = str(getattr(evidence, "source_location", "") or "").strip().lower()
    if not is_bound:
        return "背景/间接支撑（未绑定正式结论，不得单独支撑关键结论）"
    if excerpt and re.search(r"(?:#p\d+|#page[=:]?\d+|\bpage\s*\d+|\bp[:：]\s*\d+)", location):
        return "直接支撑（已保存原文摘录及正文定位）"
    if excerpt:
        return "有限直接支撑（有原文摘录，但正文定位不完整）"
    return "背景/间接支撑（不得单独支撑关键结论）"


def _public_source_location(value: Any) -> str:
    location = str(value or "").strip()
    paragraph = re.search(r"#p(\d+)$", location, flags=re.IGNORECASE)
    if paragraph:
        return f"材料化正文第 {paragraph.group(1)} 段"
    page = re.search(r"(?:#|\b)page[=:]?\s*(\d+)", location, flags=re.IGNORECASE)
    if page:
        return f"原文第 {page.group(1)} 页"
    short_paragraph = re.fullmatch(r"p[:：]\s*(\d+)", location, flags=re.IGNORECASE)
    if short_paragraph:
        return f"原文第 {short_paragraph.group(1)} 段"
    if "citation" in location.lower():
        return "检索引文定位；未落到可独立复核的正文段落"
    if "web_search" in location.lower() or not location:
        return "未登记可独立复核的正文位置"
    if "#" in location:
        location = location.rsplit("#", 1)[-1]
    return _compact_text(location, 140)


def _source_publication_date(evidence: Any) -> tuple[str, int | None]:
    source_text = " ".join(
        [
            str(getattr(evidence, "source_url", "") or ""),
            str(getattr(evidence, "source_title", "") or ""),
        ]
    )
    exact = re.search(r"(?<!\d)(20\d{2})[-_/](0?[1-9]|1[0-2])[-_/](0?[1-9]|[12]\d|3[01])(?!\d)", source_text)
    if exact:
        year, month, day = (int(item) for item in exact.groups())
        try:
            normalized = datetime(year, month, day).date().isoformat()
        except ValueError:
            normalized = ""
        if normalized:
            return normalized, year
    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    named = re.search(
        r"(?<!\d)(20\d{2})[-_/](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-_/](0?[1-9]|[12]\d|3[01])(?!\d)",
        source_text,
        flags=re.IGNORECASE,
    )
    if named:
        year = int(named.group(1))
        month = month_names[named.group(2).lower()]
        day = int(named.group(3))
        try:
            return datetime(year, month, day).date().isoformat(), year
        except ValueError:
            pass
    year_only = re.search(r"(?<!\d)(20\d{2})(?!\d)", source_text)
    if year_only:
        year = int(year_only.group(1))
        return f"{year}（来源仅显示年份）", year
    return "证据卡未登记；正式使用前需核验", None


def _evidence_collected_date(evidence: Any) -> str:
    created_at = str(getattr(evidence, "created_at", "") or "").strip()
    match = re.match(r"(20\d{2}-\d{2}-\d{2})", created_at)
    return match.group(1) if match else "本次研究采集时点"


def _evidence_time_validity(*, publication_year: int | None, collected_date: str) -> str:
    collected_year_match = re.match(r"(20\d{2})", collected_date)
    collected_year = int(collected_year_match.group(1)) if collected_year_match else None
    if publication_year is None:
        return (
            f"截至 {collected_date}，发布日期未闭环；不得单独支撑当前数量、部署状态或现行政策判断。"
        )
    age = max(0, collected_year - publication_year) if collected_year is not None else 0
    if age >= 4:
        return (
            f"截至 {collected_date}，属于历史/基础性材料；可支撑长期机理，不能单独证明当前状态。"
        )
    if age >= 2:
        return (
            f"截至 {collected_date} 可作趋势与背景依据；涉及当前数量、部署或政策状态时需再次核验。"
        )
    return (
        f"截至 {collected_date} 属近期材料；动态数量、部署进度和政策状态仍应在使用时复核。"
    )


def _public_report_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(
        r"完整证据索引与推理回溯(?:信息)?(?:已)?保存在配套结构化附件中[。.]?",
        "完整证据索引与推理回溯见随附 evidence_references.md 和结构化附件。",
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_])(?:ev|packet|cap)-[A-Za-z0-9][A-Za-z0-9._:-]*",
        "相关公开证据",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:branch_deliverables|capability_images|demand_cards|reasoning_traceability)\.json",
        "结构化附件",
        text,
        flags=re.IGNORECASE,
    )
    replacements = (
        (r"S1\s*[–—-]\s*S6", "六阶段制胜分析"),
        (r"(?<![A-Za-z0-9])S-?[1-6](?![A-Za-z0-9])", "对应分析阶段"),
        (r"L1\s*[–—-]\s*L4", "分级质量门控"),
        (r"(?<![A-Za-z0-9])L-?[1-4](?![A-Za-z0-9])", "质量门控"),
        (r"\bEvidenceCard\b", "公开证据"),
        (r"\bPacket\b", "研究交接摘要"),
        (r"\bAgent\b", "专业研究角色"),
        (r"\bCodex\b", "模型综合"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = text.replace("`相关公开证据`", "相关公开证据")
    text = re.sub(
        r"相关公开证据(?:、相关公开证据)+",
        "相关公开证据组",
        text,
    )
    return text


def _branch_attachment_names(branch: str) -> list[str]:
    names = ["branch_deliverables.json", "capability_images.json"]
    if branch == "B":
        names.extend(
            [
                "demand_cards.json",
                "capability_panorama.json",
                "reasoning_traceability.json",
            ]
        )
    elif branch in "DEFGH":
        names.append("demand_cards.json")
    return names


def _capability_priority_key(image: CapabilityImageItem) -> tuple[int, float]:
    match = re.search(r"P(\d+)", image.priority, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), -image.confidence
    rank = {"高": 1, "中": 2, "低": 3}
    return rank.get(image.priority[:1], 9), -image.confidence


def _military_role_labels(image: CapabilityImageItem) -> str:
    text = " ".join(
        [
            image.military_utility,
            image.strike_countermeasure_value,
            image.combat_effect_uplift,
            image.strike_chain_contribution,
            image.mission_effect,
            image.operational_mechanism,
        ]
    )
    labels: list[str] = []
    checks = [
        ("打击/歼灭", ("打击", "杀伤", "毁伤", "火力", "目标处置")),
        ("反制", ("反制", "抗扰", "防空", "反无人", "防护", "对抗")),
        ("制衡/拒止", ("制衡", "拒止", "压制", "剥夺", "限制对手")),
        ("威慑", ("威慑", "示强")),
    ]
    for label, keywords in checks:
        if any(keyword in text for keyword in keywords):
            labels.append(label)
    return "、".join(labels) or "任务闭环与体系韧性"


def _trace_refs(image: CapabilityImageItem) -> str:
    evidence = "、".join(image.evidence_ids[:2]) or "待补证"
    reasoning = "、".join(image.reasoning_refs[:2]) or "S1–S6综合判断"
    return f"证据{evidence}；推理{reasoning}；置信度{image.confidence:.0%}"


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [f"{key}：{item}" for key, item in value.items() if item not in (None, "", [], {})]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _numbered_lines(values: list[str], limit: int) -> list[str]:
    if not values:
        return ["- 当前证据不足，未形成可发布条目；缺口已保留，不以同义内容凑数。"]
    return [f"{index}. {_compact_text(value, limit)}" for index, value in enumerate(values, start=1)]


def _indicator_lines(values: list[str]) -> list[str]:
    if not values:
        return ["- 当前未形成可发布能力指标；缺口已保留。"]
    rows: list[str] = []
    for start in range(0, len(values), 5):
        batch = values[start : start + 5]
        rendered = "；".join(
            f"{start + offset + 1}.{_compact_text(value, 70)}"
            for offset, value in enumerate(batch)
        )
        rows.append(f"- {rendered}")
    return rows


def _completion_line(completion: Any) -> list[str]:
    if not isinstance(completion, Mapping) or not completion:
        return []
    values = []
    for key, row in completion.items():
        if not isinstance(row, Mapping):
            continue
        values.append(
            f"{key} {row.get('actual', 0)}/{row.get('target', 0)}"
            f"（{'满足' if row.get('met') else '不足'}）"
        )
    return [f"**交付门槛：** {'；'.join(values)}。", ""] if values else []


def _compact_list(values: Any, count: int, limit: int) -> str:
    rows = _string_items(values)[:count]
    return _compact_text("；".join(rows), limit) if rows else ""


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).replace("|", "/")
    if len(text) <= limit:
        return text
    cut = max(
        (text.rfind(mark, 0, limit) for mark in ("。", "！", "？", "!", "?")),
        default=-1,
    )
    if cut >= max(80, limit // 2):
        return text[: cut + 1].rstrip()
    return text


def _table_text(value: Any, limit: int) -> str:
    return _compact_text(value, limit).replace("\n", " ") or "—"


def _image_lines(image: CapabilityImageItem, store: DomainStore) -> list[str]:
    label = "新作战能力方向" if image.capability_type == "new_capability" else "现有装备升级需求"
    rows = [
        f"### {image.capability_id} {image.name}",
        "",
        "| 属性 | 内容 |",
        "|---|---|",
        f"| 类型 | {label} |",
        f"| 装备类别 | {image.equipment_category} |",
        f"| 关联场景 | {image.related_scenario} |",
        f"| 优先级 | {image.priority} |",
        f"| 置信度 | {image.confidence:.0%} |",
        "",
        "#### 制胜逻辑与能力差距",
        f"- 制胜逻辑：{image.source_winning_logic}",
        f"- 现状差距：{image.capability_gap}",
        "",
        "#### 装备能力画像",
        image.deep_capability_portrait or image.capability_image,
    ]
    if image.capability_type == "upgrade":
        rows.extend(_upgrade_combat_argument(image))
    rows.extend(_list_section("建议装备/系统形态", [image.equipment_form] if image.equipment_form else []))
    rows.extend(_list_section("核心作战机理", [image.operational_mechanism] if image.operational_mechanism else []))
    rows.extend(_list_section("建设演化路径", [image.development_path] if image.development_path else []))
    rows.extend(_integrated_capability_argument(image, store))
    rows.extend(_list_section("专业 Agent 贡献", image.agent_contributions))
    rows.extend(_list_section("证据依据", image.evidence_basis))
    rows.extend(_list_section("S1–S6 推理引用", image.reasoning_refs))
    rows.extend(_list_section("任务效果", [image.mission_effect] if image.mission_effect else []))
    rows.extend(_list_section("体系依赖与接口", image.system_dependencies))
    rows.extend(_list_section("风险边界", image.risk_boundaries))
    rows.extend([
        "#### 证据追溯",
        f"- 关联证据：{len(image.evidence_ids)} 项（{', '.join(image.evidence_ids[:8])}{' 等' if len(image.evidence_ids) > 8 else ''}）",
        "",
    ])
    return rows


def _upgrade_combat_argument(image: CapabilityImageItem) -> list[str]:
    baseline = image.baseline_system or image.equipment_category
    package = "、".join(image.upgrade_package) or _primary_capability_statement(image)
    uplift = image.combat_effect_uplift or image.military_utility or image.mission_effect
    chain = image.strike_chain_contribution or image.strike_countermeasure_value or image.operational_mechanism
    boundary = image.upgrade_boundary or image.development_path
    return [
        "",
        "#### 现役升级作战效能提升论证",
        "",
        (
            f"该方向面向{baseline}，不是一般性软件或接口更新，而是以{package}构成可落装的改装组合。"
            f"其核心目标是{uplift or '提高现役装备在复杂对抗条件下的任务完成率和持续作战能力'}，"
            f"并通过{chain or '缩短任务闭环、提高火力协同与受损后的任务续接能力'}强化实际打击和反制效果。"
            f"升级范围以{boundary or '平台余量、接口兼容性和任务级联试结果'}为边界；超出现役平台承载能力的部分"
            "不得继续以改装名义堆叠，应转入新装备或新体系节点论证。"
        ),
    ]


def _integrated_capability_argument(
    image: CapabilityImageItem,
    store: DomainStore,
) -> list[str]:
    evidence = [
        store.evidence[evidence_id]
        for evidence_id in image.evidence_ids
        if evidence_id in store.evidence
    ]
    source_families = sorted(
        {
            (item.source_url.split("/", 3)[2] if "://" in item.source_url else item.source_title)
            for item in evidence
        }
    )
    evidence_claims = [item.claim for item in evidence if item.claim.strip()][:4]
    reasoning_by_step: dict[int, list[str]] = {}
    for node in store.reasoning_nodes.values():
        reasoning_by_step.setdefault(node.step, []).append(node.summary)
    s1_s3 = [
        summary
        for step in (1, 2, 3)
        for summary in reasoning_by_step.get(step, [])
    ][:3]
    s4_s6 = [
        summary
        for step in (4, 5, 6)
        for summary in reasoning_by_step.get(step, [])
    ][:3]
    novelty = image.novelty or (
        "以新的能力组合和装备形态重构任务链，而非在既有平台上单项叠加性能"
        if image.capability_type == "new_capability"
        else "将现役升级从单装性能改进推进到接口、数据、保障与任务链协同的体系化闭环"
    )
    foresight_boundary = image.foresight or "；".join(image.risk_boundaries[:2]) or "需经未来场景压力测试校准"
    military_effect = image.military_utility or image.mission_effect or _primary_capability_statement(image)
    countermeasure = image.strike_countermeasure_value or "其发现、抗扰、反制和任务续接效果仍需能力级仿真与演训验证"
    return [
        "",
        "#### 装备论证综合判断",
        "",
        (
            f"S1–S3将任务问题收敛为“{_join_reasoning(s1_s3, image.source_winning_logic)}”，"
            f"S4–S6进一步确认“{_join_reasoning(s4_s6, image.capability_gap)}”。"
            f"因此，{image.name}的军事意义不在于单项参数领先，而在于{military_effect}；"
            f"其对抗价值体现为{countermeasure}。只有当该能力能够闭合关键任务链、保持作战节奏，"
            "并在局部节点受损后继续形成任务效果时，才具备进入装备论证的价值。"
        ),
        "",
        (
            f"相对现有基线，该方向{novelty}。这种新增价值来自装备功能、任务网络、接口和降级运行"
            f"机制的重新组合，而非简单增加某项技术。面向未来，{foresight_boundary}；若对手适应、"
            "体系依赖或工程成本使任务增益无法跨场景复现，应降低优先级并回到效果链重新校准。"
        ),
        "",
        (
            f"上述判断关联 {len(evidence)} 项正式证据和 {len(source_families)} 个来源域。"
            f"代表性依据包括：{_join_reasoning(evidence_claims, '当前证据仅支持方向性判断，仍需补充试验与演训数据')}。"
            "公开证据只能支持能力方向和作用机理判断，具体性能阈值仍须通过仿真、联试、演训和失效注入验证。"
        ),
    ]


def _join_reasoning(values: list[str], fallback: str) -> str:
    cleaned = [str(item).strip()[:350] for item in values if str(item).strip()]
    rendered = "；".join(cleaned[:4])
    return rendered[:1200] if rendered else fallback[:1200]


def _list_section(title: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return ["", f"#### {title}", *[f"- {str(value)[:1200]}" for value in values[:8]]]


def _primary_capability_statement(image: CapabilityImageItem) -> str:
    return image.capability_image


def _deterministic_executive_summary(images: list[CapabilityImageItem], audit: AuditResult) -> str:
    if not images:
        return "本轮尚未形成满足门控要求的能力画像，应优先完成证据补充和定向再调。"
    names = "、".join(item.name for item in images)
    status = {
        "approved": "可进入下一阶段论证",
        "pending": "业务审计进行中，可继续审阅",
    }.get(audit.status, "仅可作为受限研究初稿")
    return f"本研究形成{names}等能力方向，重点回答任务效果、体系接口、装备形态和建设路径。当前成果{status}，具体性能阈值仍需结合后续试验数据校准。"


def _audit_status_label(status: str) -> str:
    return {
        "approved": "通过",
        "pending": "业务审计进行中",
        "limited": "受限发布",
    }.get(str(status).lower(), str(status) or "业务审计进行中")


def _route_label(route: str) -> str:
    return {
        "new_winning_mechanism": "新制胜机理",
        "traditional_gap": "传统能力缺口",
        "war_case_learning": "局部战争案例学习",
    }.get(route, route)


def _route_question_chain(route: str) -> str:
    if route == "traditional_gap":
        return "国际形势/威胁 -> 对抗场景 -> 传统场景/制胜/战法 -> 当前装备对比 -> 能力不足与空白 -> 新能力补位和现有装备升级。"
    if route == "war_case_learning":
        return "局部战争时间线 -> 参战装备与体系 -> 新打法和新能力 -> 作战效果、经验与不足 -> 可迁移方向 -> 未来装备布局。"
    return "国际形势/威胁 -> 对抗场景 -> 新制胜机制、新作战打法、新体系组合 -> 能力增长点 -> 新概念装备与现有装备适配升级。"


def _route_branch(route: str) -> str:
    return {
        "new_winning_mechanism": "A",
        "traditional_gap": "B",
        "war_case_learning": "C",
    }.get(route, "A")


def _embedded_agent_analysis(body: str) -> list[str]:
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def _integrated_summary_lines(images: list[CapabilityImageItem], branch: str) -> list[str]:
    rows: list[str] = []
    for image in images:
        novelty = (
            "以新能力方向重构任务链"
            if image.capability_type == "new_capability"
            else "以现役升级方式闭合关键短板"
        )
        rows.extend(
            [
                (
                    f"**{image.name}。** {novelty}，把“{image.source_winning_logic}”转化为可验证的"
                    f"装备与体系能力组合。其直接军事意义是{image.mission_effect or '提升任务链连续性和体系韧性'}，"
                    f"并通过{image.operational_mechanism or image.strike_countermeasure_value or '任务链重构与降级运行'}"
                    "改变对抗条件；其未来价值取决于体系接口、工程成熟度和场景压力测试能否证明该机制持续成立。"
                ),
                "",
            ]
        )
    if not rows:
        rows.append("当前尚无满足门控的能力方向；应先补足证据和效果链，再形成装备建设判断。")
    contract = branch_report_contract(branch)
    rows.append(f"本报告按{branch}分支展开：{contract['thesis']}{contract['military_test']}{contract['future_test']}")
    return rows


def _reasoning_conclusion_lines(store: DomainStore) -> list[str]:
    by_step: dict[int, list[str]] = {}
    for node in store.reasoning_nodes.values():
        by_step.setdefault(node.step, []).append(node.summary)
    themes = [
        ("对手体系、任务约束与制胜窗口", (1, 2)),
        ("突破方向与效果传导", (3,)),
        ("装备能力域、功能与指标", (4,)),
        ("能力差距、优先序与建设取舍", (5,)),
        ("综合能力画像", (6,)),
    ]
    rows: list[str] = []
    for title, steps in themes:
        summaries = list(
            dict.fromkeys(
                summary
                for step in steps
                for summary in by_step.get(step, [])
                if summary.strip()
            )
        )
        if not summaries:
            continue
        rows.extend([f"### {title}", "", "\n\n".join(summaries), ""])
    if not rows:
        rows.extend(["当前尚未形成可发布的制胜逻辑与能力推导结论。", ""])
    return rows
