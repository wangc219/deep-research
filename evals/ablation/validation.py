from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re


LOOP_EVENTS = {
    "discovery_meta_loop_evaluated",
    "winning_inner_loop_evaluated",
    "winning_middle_loop_evaluated",
    "winning_outer_loop_evaluated",
    "recall_requested",
    "recall_task_completed",
}
DOMAIN_BASELINE_ACTORS = {
    "international_situation",
    "combat_scenario",
    "weapon_equipment",
    "operational_employment",
    "scenario_divergence",
    "case_research",
    "technology_radar",
    "opponent_monitoring",
    "system_confrontation",
    "cross_domain_fusion",
    "nontraditional_security",
}
WINNING_EVENTS = {
    "winning_input_prepared",
    "winning_resources_projected",
    "winning_reasoning_step_completed",
    "winning_stage_completed",
    "capability_image_created",
}


def validate_variant_trace(variant: str, artifact_refs: list[str], base_dir: Path) -> dict[str, Any]:
    trace_path = _trace_path(artifact_refs, base_dir)
    if trace_path is None:
        return {"valid": False, "reason": "缺少trace.jsonl", "events": []}
    event_types: list[str] = []
    actors: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
        event_types.append(str(row.get("event_type") or payload.get("event_type") or ""))
        actors.append(str(row.get("actor") or payload.get("actor") or ""))
    forbidden: set[str] = set()
    if variant == "no_winning_mechanism":
        forbidden.update(LOOP_EVENTS)
        forbidden.update(WINNING_EVENTS)
    violations = sorted(set(event_types) & forbidden)
    reasons: list[str] = []
    if violations:
        reasons.append("出现禁止事件：" + "、".join(violations))
    if variant == "no_multisource_baseline":
        leaked_domain_actors = sorted(set(actors) & DOMAIN_BASELINE_ACTORS)
        if leaked_domain_actors:
            reasons.append("出现被消融的专业基线Agent：" + "、".join(leaked_domain_actors))
        if "generic_researcher" not in actors:
            reasons.append("未发现受限通用检索Agent执行记录")
        domain_path = trace_path.parent / "domain.jsonl"
        evidence_urls: set[str] = set()
        if domain_path.is_file():
            for line in domain_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") != "EvidenceCard":
                    continue
                payload = row.get("payload", {})
                url = str(payload.get("source_url", "")).strip()
                if url.startswith(("http://", "https://")):
                    evidence_urls.add(url)
        if len(evidence_urls) > 2:
            reasons.append(f"受限通用检索准入来源超过2个：{len(evidence_urls)}")
        report_path = trace_path.parent / "report.md"
        report_urls = set()
        if report_path.is_file():
            report_urls = set(
                re.findall(r"https?://[^\s<>)\]}]+", report_path.read_text(encoding="utf-8"))
            )
        if len(report_urls) > 2:
            reasons.append(f"去多源报告公开引用超过2个：{len(report_urls)}")
    return {
        "valid": not reasons,
        "reason": "；".join(reasons),
        "events": sorted(set(event_types)),
        "actors": sorted(set(actors)),
        "trace_path": str(trace_path),
        "evidence_url_count": len(evidence_urls) if variant == "no_multisource_baseline" else None,
        "report_url_count": len(report_urls) if variant == "no_multisource_baseline" else None,
    }


def _trace_path(artifact_refs: list[str], base_dir: Path) -> Path | None:
    for ref in artifact_refs:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        if candidate.name == "trace.jsonl" and candidate.is_file():
            return candidate.resolve()
    for candidate in base_dir.rglob("trace.jsonl"):
        if candidate.is_file():
            return candidate.resolve()
    return None
