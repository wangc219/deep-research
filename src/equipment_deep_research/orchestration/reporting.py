from __future__ import annotations

from equipment_deep_research.domain.models import AuditResult, CapabilityImageItem, ResearchReport
from equipment_deep_research.domain.store import DomainStore


def audit_run(
    *,
    store: DomainStore,
    coverage: dict,
    max_rounds: int,
    current_rounds: int = 1,
    source_materials: list[dict] | None = None,
) -> AuditResult:
    stage_outputs = list(store.stage_outputs.values())
    min_confidence = min((stage.confidence for stage in stage_outputs), default=0.0)
    source_materials = list(source_materials or [])
    materialization_ok = True
    if source_materials:
        materialization_ok = any(row.get("status") in {"fetched", "fixture_materialized"} for row in source_materials)
    checks = {
        "consistency": bool(stage_outputs),
        "confidence_ge_70": min_confidence >= 0.7,
        "coverage": bool(coverage.get("coverage_passed")),
        "user_confirmation": True,
        "round_limit": current_rounds <= max_rounds,
        "source_materialization": materialization_ok,
    }
    comments = []
    if not checks["coverage"]:
        comments.append("本次启用agent未覆盖全部关键capability，报告需标注限制。")
    if not checks["confidence_ge_70"]:
        comments.append("阶段最低置信度低于70%，仅可作为受限初稿。")
    if not checks["source_materialization"]:
        comments.append("联网材料化未成功获取正文，仅保留失败诊断artifact；真实结论需在网络可用环境重跑。")
    status = "approved" if all(checks.values()) else "limited"
    return AuditResult(audit_id="audit-001", status=status, checks=checks, comments=comments)


def render_report(*, topic: str, route: str, store: DomainStore, coverage: dict, audit: AuditResult) -> ResearchReport:
    images = list(store.capability_images.values())
    lines = [
        f"# {topic} 装备能力图像需求报告",
        "",
        "## 研究路线",
        route,
        "",
        "## Agent覆盖情况",
        f"- 已覆盖能力标签：{', '.join(coverage.get('provided_tags', [])) or '无'}",
        f"- 缺失关键能力标签：{', '.join(coverage.get('missing_required_tags', [])) or '无'}",
        f"- 审计状态：{audit.status}",
        "",
        "## 制胜机理阶段结论",
    ]
    for stage in store.stage_outputs.values():
        lines.extend(
            [
                f"### {stage.layer} {stage.title}",
                f"- 置信度：{stage.confidence:.2f}",
                f"- 门控：{'通过' if stage.gate_passed else '未通过/受限'}",
                f"- 原因：{'; '.join(stage.gate_reasons) if stage.gate_reasons else '满足当前阶段条件'}",
                "",
            ]
        )
    lines.extend(["## 作战能力图像需求", ""])
    for image in images:
        lines.extend(_image_lines(image))
    lines.extend(["## 证据索引", ""])
    for evidence in store.evidence.values():
        artifact_note = f"，artifact={','.join(evidence.artifact_refs)}" if evidence.artifact_refs else ""
        lines.append(f"- {evidence.evidence_id}：{evidence.claim}（{evidence.source_title}，{evidence.source_tier}级{artifact_note}）")
    if audit.comments:
        lines.extend(["", "## 限制与后续补证", ""])
        lines.extend(f"- {comment}" for comment in audit.comments)
    body = "\n".join(lines).strip() + "\n"
    return ResearchReport(
        report_id="report-001",
        title=f"{topic} 装备能力图像需求报告",
        body=body,
        capability_ids=[image.capability_id for image in images],
        evidence_ids=list(store.evidence),
        audit_id=audit.audit_id,
    )


def _image_lines(image: CapabilityImageItem) -> list[str]:
    label = "新作战能力方向" if image.capability_type == "new_capability" else "现有装备升级需求"
    return [
        f"### {image.capability_id} {image.name}",
        f"- 类型：{label}",
        f"- 装备类别：{image.equipment_category}",
        f"- 来源制胜逻辑：{image.source_winning_logic}",
        f"- 关联场景：{image.related_scenario}",
        f"- 优先级：{image.priority}",
        f"- 能力差距：{image.capability_gap}",
        f"- 能力画像：{image.capability_image}",
        "",
    ]
