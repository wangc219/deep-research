from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.agents.provider import (
    _report_delivery_blocking_issues,
    _report_capability_portrait_markdown,
    _stabilize_report_delivery_contract,
    _sanitize_reporter_output,
    _strip_report_internal_markers,
)
from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_title,
)
from equipment_deep_research.delivery.exporter import DeliveryExporter
from equipment_deep_research.delivery.quality_gate import ReportQualityGate
from equipment_deep_research.domain.models import TraceEvent, to_plain
from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal
from equipment_deep_research.domain.store import SqliteRunStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.recovery import _restore_domain_store
from equipment_deep_research.orchestration.deliverables import build_delivery_artifacts
from equipment_deep_research.orchestration.reporting import render_report
from equipment_deep_research.orchestration.runner import (
    DeepResearchRunner,
    _reconcile_final_audit_status,
    _report_evidence_catalog,
    _report_priority_rank,
    _report_synthesis_seed,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate a completed run using the compact branch-aware report format."
    )
    parser.add_argument("run_id")
    parser.add_argument("--output-root", default="outputs/runs")
    parser.add_argument(
        "--real-synthesis",
        action="store_true",
        help=(
            "Call the configured real reporter model again using the existing "
            "query, compact reasoning seeds, public source URLs and branch contract."
        ),
    )
    parser.add_argument(
        "--synthesis-file",
        type=Path,
        help=(
            "Use a locally reviewed cross-material synthesis Markdown file. "
            "This avoids sending run artifacts to an external provider."
        ),
    )
    parser.add_argument(
        "--provider",
        help="Override the reporter provider recorded by the run.",
    )
    parser.add_argument(
        "--model",
        help="Override the reporter model recorded by the run.",
    )
    parser.add_argument(
        "--base-url",
        help="Custom HTTPS API base URL; otherwise use the provider environment.",
    )
    parser.add_argument(
        "--api-key-env",
        help="Name of the environment variable containing the API key.",
    )
    parser.add_argument(
        "--postfix",
        action="store_true",
        help=(
            "Write report-postfix.md and report-quality-gate-postfix.json without "
            "modifying the original report, run database, trace/domain exports, "
            "delivery manifest, claim binding, or reporter session."
        ),
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    output_root = Path(args.output_root).resolve()
    workspace = RunWorkspace.open_existing(output_root, args.run_id)
    sqlite_store = SqliteRunStore.for_workspace(workspace, run_id=args.run_id)
    try:
        store = _restore_domain_store(sqlite_store.domain_objects())
        problem = next(iter(store.problems.values()))
        audit = next(iter(store.audits.values()))
        run_dir = workspace.run_dir
        blueprint = _read_json(run_dir / "discovery_blueprint.json")
        round_summary = _read_json(run_dir / "round_summary.json")
        report_template_mode = _recorded_report_template_mode(
            run_dir,
            round_summary,
        )
        branch_payload = _read_json(run_dir / "branch_deliverables.json")
        branch = str(
            branch_payload.get("branch")
            or round_summary.get("discovery_branch")
            or blueprint.get("primary_branch")
            or "A"
        )
        route = str(
            round_summary.get("resolved_route")
            or blueprint.get("runtime_route")
            or problem.research_route
        )
        coverage = round_summary.get("coverage", {})
        artifacts = build_delivery_artifacts(
            topic=problem.topic,
            branch=branch,
            blueprint=blueprint,
            store=store,
        )
        reporter_summary = _last_reporter_summary(run_dir)
        synthesis_metadata: dict[str, Any] = {
            "mode": "stored_reporter_summary",
        }
        if args.real_synthesis and args.synthesis_file:
            parser.error("--real-synthesis and --synthesis-file are mutually exclusive")
        if args.synthesis_file:
            reporter_summary = _sanitize_reporter_output(
                args.synthesis_file.resolve().read_text(encoding="utf-8")
            ).strip()
            if len(reporter_summary) < 800:
                raise RuntimeError(
                    "local synthesis is too short; expected at least 800 characters"
                )
            synthesis_metadata = {
                "mode": "local_codex_cross_material_synthesis",
                "source_file": args.synthesis_file.name,
                "source_counts": {
                    "agent_packets": len(store.baseline_packets),
                    "evidence": len(store.evidence),
                    "reasoning_nodes": len(store.reasoning_nodes),
                    "stage_outputs": len(store.stage_outputs),
                    "capability_images": len(store.capability_images),
                },
            }
            if not args.postfix:
                _append_reporter_session(
                    run_dir,
                    {
                        "agent_id": "reporter",
                        "event_type": "model_result",
                        "regenerated": True,
                        "synthesis_mode": "local_codex_cross_material_synthesis",
                        "text": reporter_summary,
                    },
                )
        elif args.real_synthesis:
            try:
                previous_reporter_summary = reporter_summary
                reporter_summary, synthesis_metadata = _generate_real_synthesis(
                    project_root=project_root,
                    problem=problem,
                    audit=audit,
                    store=store,
                    coverage=coverage,
                    route=route,
                    blueprint=blueprint,
                    artifacts=artifacts,
                    round_summary=round_summary,
                    report_template_mode=report_template_mode,
                    provider_override=args.provider,
                    model_override=args.model,
                    base_url_override=args.base_url,
                    api_key_env_override=args.api_key_env,
                )
                if len(reporter_summary) < 800 and len(previous_reporter_summary) >= 800:
                    reporter_summary = previous_reporter_summary
                    synthesis_metadata["synthesis_length_note"] = (
                        "undersized_new_synthesis_replaced_with_previous_reviewable_summary"
                    )
            except Exception as exc:
                failure = {
                    "run_id": args.run_id,
                    "status": "failed_no_fallback",
                    "reason": type(exc).__name__,
                    "detail": str(exc)[:1000],
                    "report_overwritten": False,
                    "postfix_mode": bool(args.postfix),
                }
                rejected_synthesis = str(
                    getattr(exc, "rejected_synthesis", "") or ""
                ).strip()
                if args.postfix and rejected_synthesis:
                    workspace.write_run_text(
                        "reporter-synthesis-rejected-postfix.md",
                        rejected_synthesis,
                    )
                    failure["rejected_synthesis_preserved"] = True
                    failure["rejected_synthesis_chars"] = len(
                        rejected_synthesis
                    )
                workspace.write_run_text(
                    (
                        "report-regeneration-failure-postfix.json"
                        if args.postfix
                        else "report_regeneration_failure.json"
                    ),
                    json.dumps(
                        failure,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
                if not args.postfix:
                    _append_reporter_session(
                        run_dir,
                        {
                            "agent_id": "reporter",
                            "event_type": "model_error",
                            "regenerated": True,
                            **failure,
                        },
                    )
                raise
            if not args.postfix:
                _append_reporter_session(
                    run_dir,
                    {
                        "agent_id": "reporter",
                        "event_type": "model_result",
                        "regenerated": True,
                        "synthesis_mode": "cross_material_strategic_synthesis",
                        "synthesis_metadata": synthesis_metadata,
                        "text": reporter_summary,
                    },
                )
        deep_synthesis = bool(
            args.real_synthesis
            or args.synthesis_file
            or (
                reporter_summary
                and synthesis_metadata.get("mode") == "stored_reporter_summary"
            )
        )
        if str(round_summary.get("mode", "")).strip().lower() == "real" and not deep_synthesis:
            raise RuntimeError(
                "real run has no independent Reporter正文；拒绝使用确定性模板覆盖report.md。"
                "请使用--real-synthesis或--synthesis-file。"
            )
        if deep_synthesis:
            audit = replace(
                audit,
                comments=[
                    str(item)
                    for item in audit.comments
                    if "报告模型超时或异常" not in str(item)
                    and "确定性深度综合模板" not in str(item)
                ],
            )
        report = render_report(
            topic=problem.topic,
            route=route,
            store=store,
            coverage=coverage,
            audit=audit,
            executive_summary=reporter_summary,
            discovery_branch=branch,
            discovery_blueprint=blueprint,
            delivery_artifacts=artifacts,
            prefer_model_report=deep_synthesis,
        )
        report = replace(
            report,
            body=_sanitize_reporter_output(report.body),
        )
        current_seed = _report_synthesis_seed(
            store=store,
            branch_output=artifacts["branch_deliverables"],
            convergence=round_summary.get("discovery_convergence", {}),
        )
        report = replace(
            report,
            body=_ensure_winning_track_summary(
                _refresh_governed_capability_portraits(
                    report.body,
                    current_seed.get("capability_cues", []),
                ),
                current_seed.get("capability_cues", []),
            ),
        )
        report = replace(
            report,
            body=_stabilize_report_delivery_contract(
                report.body,
                {
                    "report_template_mode": report_template_mode,
                    "execution_profile_id": blueprint.get(
                        "execution_profile_id", "legacy_v1"
                    ),
                    "synthesis_seed": current_seed,
                    "branch_writer_brief": artifacts.get(
                        "branch_writer_brief", {}
                    ),
                },
            ),
        )
        existing_report = store.reports.get(report.report_id)
        if existing_report is not None and existing_report.body == report.body:
            report = replace(report, created_at=existing_report.created_at)
        ordered_capabilities = sorted(
            store.capability_images.values(),
            key=lambda item: (
                _report_priority_rank(item.priority),
                -float(item.confidence),
                item.name,
            ),
        )[:7]
        quality_report = ReportQualityGate().validate(
            report.body,
            {
                "evidence_count": len(store.evidence),
                "topic": problem.topic,
                "branch": branch,
                "execution_profile_id": blueprint.get(
                    "execution_profile_id", "legacy_v1"
                ),
                "require_detailed_capability_portraits": (
                    blueprint.get("execution_profile_id")
                    in {"swarm_quality_v1", "winning_swarm_dynamic_v2"}
                ),
                "report_template_mode": report_template_mode,
                "delivery_owned_h1": True,
                "report_hard_max_chars": artifacts["branch_writer_brief"].get(
                    "hard_max_chars"
                ),
                "branch_delivery_status": artifacts["branch_deliverables"].get(
                    "delivery_status"
                ),
                "require_disruptive_lens_diversity": (
                    len(store.capability_images) >= 5
                ),
                "expected_capability_directions": [
                    build_capability_title(
                        name=_strip_report_internal_markers(item.name).strip(),
                        equipment_form=item.equipment_form or item.equipment_category,
                        effect=item.strike_countermeasure_value
                        or item.military_utility
                        or item.mission_effect,
                    )
                    for item in ordered_capabilities
                ],
                "expected_capability_records": [
                    {
                        "name": build_capability_title(
                            name=_strip_report_internal_markers(item.name).strip(),
                            equipment_form=item.equipment_form
                            or item.equipment_category,
                            effect=item.strike_countermeasure_value
                            or item.military_utility
                            or item.mission_effect,
                        ),
                        "equipment_form": item.equipment_form,
                        "equipment_category": item.equipment_category,
                        "capability_type": item.capability_type,
                        "mission_effect": item.mission_effect,
                        "military_utility": item.military_utility,
                        "operational_mechanism": item.operational_mechanism,
                        "strike_countermeasure_value": item.strike_countermeasure_value,
                        "evidence_count": len(item.evidence_ids),
                    }
                    for item in ordered_capabilities
                ],
            },
        )
        branch_gate_passed = (
            artifacts["branch_deliverables"].get("delivery_status") == "complete"
        )
        binding_path = run_dir / "claim_source_binding.json"
        binding_payload = _read_json(binding_path) if binding_path.exists() else {}
        try:
            binding_rate = float(binding_payload.get("binding_rate", 0.0) or 0.0)
        except (TypeError, ValueError):
            binding_rate = 0.0
        internal_reference_found = bool(
            re.search(
                r"\b(?:packet|claim|ev|stage|capability)-[A-Za-z0-9_.:-]+"
                r"|〔改写断点：保留事实但不得照录〕"
                r"|(?m:(?:^|\|\s*|\*\*)[A-Ha-h]\s*[.．、:：]\s*(?=[^\s|*]))",
                report.body,
            )
        )
        source_binding_passed = binding_rate >= 0.9 and not internal_reference_found
        stale_report_gate_comments = (
            "optimized_v2正式报告门控未全部通过",
            "重生成后的正式报告门控未全部通过",
        )
        audit = replace(
            audit,
            comments=[
                str(item)
                for item in audit.comments
                if not any(
                    marker in str(item) for marker in stale_report_gate_comments
                )
            ],
        )
        if quality_report.passed and branch_gate_passed and source_binding_passed:
            audit = _reconcile_final_audit_status(audit, optimized_v2=True)
        else:
            audit = replace(
                audit,
                status="limited",
                comments=list(
                    dict.fromkeys(
                        [
                            *audit.comments,
                            "重生成后的正式报告门控未全部通过；保留本次正文和具体质量缺口，"
                            "不触发整篇自动重写。",
                        ]
                    )
                ),
            )
        if args.postfix:
            postfix_summary = {
                "run_id": args.run_id,
                "branch": branch,
                "report_template_mode": report_template_mode,
                "postfix_mode": True,
                "original_report_preserved": True,
                "run_database_preserved": True,
                "reporter_session_preserved": True,
                "report_chars": len(report.body),
                "quality_passed": quality_report.passed,
                "quality_score": quality_report.overall_score,
                "audit_status_if_applied": audit.status,
                "branch_gate_passed": branch_gate_passed,
                "source_binding_passed": source_binding_passed,
                "binding_rate": binding_rate,
                "internal_reference_found": internal_reference_found,
                "synthesis_chars": len(reporter_summary),
                "synthesis": synthesis_metadata,
            }
            workspace.write_run_text("report-postfix.md", report.body)
            workspace.write_run_text(
                "report-quality-gate-postfix.json",
                json.dumps(
                    to_plain(quality_report),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
            workspace.write_run_text(
                "report-regeneration-postfix.json",
                json.dumps(
                    postfix_summary,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
            print(json.dumps(postfix_summary, ensure_ascii=False))
            return 0
        content_hash = sha256(report.body.encode("utf-8")).hexdigest()[:16]
        event_kind = (
            "report_strategic_synthesis_regenerated"
            if deep_synthesis
            else "report_compacted"
        )
        operation_hash = sha256(
            json.dumps(
                {
                    "operation_schema": "report_regeneration_v2",
                    "report_hash": content_hash,
                    "audit": to_plain(audit),
                    "quality_passed": quality_report.passed,
                    "quality_score": quality_report.overall_score,
                    "source_binding_passed": source_binding_passed,
                    "binding_rate": binding_rate,
                    "internal_reference_found": internal_reference_found,
                    "synthesis": synthesis_metadata,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        proposal_key = f"{event_kind}:{args.run_id}:{operation_hash}"
        trace = TraceEvent(
            event_id=f"trace-{proposal_key}",
            event_type=event_kind,
            actor="reporter",
            summary=(
                "能力画像研究报告已由独立报告Agent围绕Query和精炼研判种子完成深度重生成"
                if deep_synthesis
                else f"能力画像研究报告已按{branch}分支规范精简重生成"
            ),
            output_refs=[report.report_id],
            payload={
                "branch": branch,
                "report_chars": len(report.body),
                "format": (
                    "cross_material_strategic_synthesis_v1"
                    if deep_synthesis
                    else "compact_branch_report_v2"
                ),
                "synthesis": synthesis_metadata,
                "quality_passed": quality_report.passed,
                "branch_gate_passed": branch_gate_passed,
                "source_binding_passed": source_binding_passed,
            },
            created_at=report.created_at,
        )
        domain_proposals = [
            DomainWriteProposal(
                proposal_id=proposal_key,
                object_type="ResearchReport",
                operation="upsert",
                payload=to_plain(report),
                idempotency_key=proposal_key,
            )
        ]
        audit_key = f"{proposal_key}:audit"
        domain_proposals.append(
            DomainWriteProposal(
                proposal_id=audit_key,
                object_type="AuditResult",
                operation="upsert",
                payload=to_plain(audit),
                idempotency_key=audit_key,
            )
        )
        sqlite_store.commit(
            domain_proposals,
            [
                TraceProposal(
                    proposal_id=trace.event_id,
                    event_type=trace.event_type,
                    actor=trace.actor,
                    payload=to_plain(trace),
                ),
            ],
        )
        workspace.write_run_text("report.md", report.body)
        workspace.write_run_text(
            "report_quality_gate.json",
            json.dumps(
                to_plain(quality_report),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )
        if binding_payload:
            workspace.write_run_text(
                "claim_source_binding.json",
                json.dumps(
                    {
                        **binding_payload,
                        "binding_rate": binding_rate,
                        "internal_reference_found": internal_reference_found,
                        "passed": source_binding_passed,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
            )
        sqlite_store.export_domain_jsonl(run_dir / "domain.jsonl")
        sqlite_store.export_trace_jsonl(run_dir / "trace.jsonl")
        manifest = DeliveryExporter().build_manifest(run_dir)
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "branch": branch,
                    "report_chars": len(report.body),
                    "quality_passed": quality_report.passed,
                    "quality_score": quality_report.overall_score,
                    "audit_status": audit.status,
                    "source_binding_passed": source_binding_passed,
                    "synthesis_chars": len(reporter_summary),
                    "synthesis": synthesis_metadata,
                    "manifest_files": manifest["file_count"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        sqlite_store.close()
        workspace.close()

def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _recorded_report_template_mode(
    run_dir: Path,
    round_summary: dict[str, Any],
) -> str:
    recorded = str(round_summary.get("report_template_mode", "")).strip()
    if recorded in {"three_layer_nine_item", "project_argument_v1"}:
        return recorded
    trace_path = run_dir / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = row.get("payload", row)
            if not isinstance(event, dict) or event.get("event_type") != "run_started":
                continue
            event_payload = event.get("payload", {})
            if not isinstance(event_payload, dict):
                continue
            recorded = str(event_payload.get("report_template_mode", "")).strip()
            if recorded in {"three_layer_nine_item", "project_argument_v1"}:
                return recorded
    original_report = (run_dir / "report.md").read_text(encoding="utf-8")
    if re.search(r"^##\s*一、需求分析\s*$", original_report, flags=re.MULTILINE):
        return "project_argument_v1"
    return "three_layer_nine_item"


def _last_reporter_summary(run_dir: Path) -> str:
    session_path = run_dir / "agent_sessions" / "reporter.jsonl"
    if not session_path.exists():
        return ""
    summary = ""
    reviewable_summary = ""
    for line in session_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event_type") == "model_result" and str(row.get("text", "")).strip():
            summary = str(row["text"]).strip()
            if len(summary) >= 800:
                reviewable_summary = summary
    return reviewable_summary or summary


def _refresh_governed_capability_portraits(
    report_body: str,
    capability_cues: list[dict[str, Any]],
) -> str:
    """Refresh only governed portrait blocks from the current delivery contract.

    Stored Reporter prose remains the source for the report argument.  The
    capability blocks are deterministic projections, so a postfix regeneration
    should bring them forward when the structured contract becomes stricter.
    """

    body = str(report_body)
    for cue_index, cue in enumerate(capability_cues):
        if not isinstance(cue, dict):
            continue
        source_name = _strip_report_internal_markers(
            str(cue.get("direction", ""))
        ).strip()
        name = build_capability_title(
            name=source_name,
            equipment_form=cue.get("equipment_hint")
            or cue.get("equipment_form")
            or cue.get("public_equipment_baseline"),
            effect=cue.get("mission_effect"),
        )
        portrait = _strip_report_internal_markers(
            _report_capability_portrait_markdown(cue)
        ).strip()
        if not source_name or not name or not portrait:
            continue
        exact_pattern = re.compile(
            rf"^\*\*{re.escape(name)}｜装备能力画像\*\*\s*\n"
            r"(?P<body>.*?)"
            r"(?=^\*\*.+?｜装备能力画像\*\*\s*$|^###\s+)",
            flags=re.MULTILINE | re.DOTALL,
        )
        replacement = f"**{name}｜装备能力画像**\n\n{portrait}\n\n"
        body, count = exact_pattern.subn(replacement, body, count=1)
        if count:
            if name != source_name:
                body = body.replace(source_name, name)
            continue

        # A completed run may contain a pre-fix working title while retaining
        # the same equipment form. Match that governed block by its concrete
        # equipment subject, then refresh both the block heading and any table
        # row using the stale alias.
        hint = _strip_report_internal_markers(
            str(cue.get("equipment_hint") or cue.get("equipment_form") or "")
        ).strip()
        hint_anchor = re.split(r"[，,；;。]", hint, maxsplit=1)[0].strip()
        any_block_pattern = re.compile(
            r"^\*\*(?P<alias>.+?)｜装备能力画像\*\*\s*\n"
            r"(?P<body>.*?)"
            r"(?=^\*\*.+?｜装备能力画像\*\*\s*$|^###\s+)",
            flags=re.MULTILINE | re.DOTALL,
        )
        matched = next(
            (
                match
                for match in any_block_pattern.finditer(body)
                if hint_anchor and hint_anchor in match.group("body")
            ),
            None,
        )
        if matched is None:
            ordered_matches = list(any_block_pattern.finditer(body))
            if len(ordered_matches) == len(capability_cues):
                # Completed-run upgrades keep the governed card order stable.
                # When an old Reporter block has neither the new title nor a
                # sufficiently specific equipment hint, use that stable order
                # instead of leaving the stale alias and stale portrait behind.
                matched = ordered_matches[cue_index]
        if matched is None:
            continue
        alias = matched.group("alias").strip()
        body = body[: matched.start()] + replacement + body[matched.end() :]
        if alias and alias != name:
            body = body.replace(alias, name)
    return _sanitize_reporter_output(body)


def _ensure_winning_track_summary(
    report_body: str,
    capability_cues: list[dict[str, Any]],
) -> str:
    """State the three decision tracks when a multi-weapon portfolio is present."""

    body = str(report_body)
    if len(capability_cues) < 5 or all(
        marker in body for marker in ("效能跃升", "跨代优势", "新概念赛道")
    ):
        return body
    names = [
        build_capability_title(
            name=_strip_report_internal_markers(str(cue.get("direction", ""))).strip(),
            equipment_form=cue.get("equipment_hint")
            or cue.get("equipment_form")
            or cue.get("public_equipment_baseline"),
            effect=cue.get("mission_effect"),
        )
        for cue in capability_cues
        if isinstance(cue, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return body
    lead = "、".join(names[:2])
    middle = "、".join(names[2:4]) or names[-1]
    frontier = names[-1]
    paragraph = (
        "组合建设按三条制胜轨道验收：一是以"
        f"{lead}形成现役效能跃升，重点考核机场失能后的火力接替与受扰任务保持；"
        "二是以"
        f"{middle}在传统远火与巡飞弹赛道形成跨代优势，重点考核多轴持续波次、"
        "单位有效毁伤成本和对手拦截资源消耗；三是以"
        f"{frontier}开辟新概念赛道，只有在可重复形成、可确认且可被后续火力利用的"
        "功能压制窗口时才进入型号化。三轨均以直接战果、对手反适应、失效边界和"
        "可证伪试验决定建设取舍。"
    )
    anchor = "### （三）体系贡献率分析\n"
    if anchor in body:
        body = body.replace(anchor, f"{anchor}\n{paragraph}\n", 1)
    else:
        body = f"{body.rstrip()}\n\n{paragraph}\n"
    return _sanitize_reporter_output(body)


def _generate_real_synthesis(
    *,
    project_root: Path,
    problem: Any,
    audit: Any,
    store: Any,
    coverage: dict[str, Any],
    route: str,
    blueprint: dict[str, Any],
    artifacts: dict[str, Any],
    round_summary: dict[str, Any],
    report_template_mode: str,
    provider_override: str | None,
    model_override: str | None,
    base_url_override: str | None,
    api_key_env_override: str | None,
) -> tuple[str, dict[str, Any]]:
    recorded = round_summary.get("agent_models", {}).get("reporter", {})
    if not isinstance(recorded, dict):
        recorded = {}
    provider_name = str(provider_override or recorded.get("provider") or "codex")
    model = str(model_override or recorded.get("model") or "gpt-5.5")
    api_key_env = str(
        api_key_env_override
        or recorded.get("api_key_env")
        or (
            os.environ.get("EQUIPMENT_DR_CODEX_API_KEY_ENV", "")
            if provider_name == "codex"
            else "EQUIPMENT_DR_API_KEY"
        )
    ).strip()
    base_url = str(
        base_url_override
        or recorded.get("base_url")
        or (
            os.environ.get("EQUIPMENT_DR_CODEX_BASE_URL", "")
            if provider_name == "codex"
            else os.environ.get("EQUIPMENT_DR_BASE_URL", "")
        )
    ).strip()
    if provider_name in {"codex", "responses"} and not base_url:
        raise RuntimeError(
            "real synthesis requires a custom API base URL; pass --base-url or "
            "configure the matching EQUIPMENT_DR_*_BASE_URL environment variable"
        )
    if not api_key_env:
        raise RuntimeError(
            "real synthesis requires --api-key-env or a recorded/configured key environment"
        )

    config_root = project_root / "configs" / "equipment_deep_research"
    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=project_root / "outputs" / "runs",
        agent_config_path=config_root / "agents.yaml",
        preset_config_path=config_root / "presets.yaml",
        provider_config_path=config_root / "providers.yaml",
    )
    registry = AgentRegistry.load(config_root / "agents.yaml")
    provider = runner._select_agent_provider(
        "real",
        provider_name,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        agent_model_profiles={
            "reporter": {
                "provider": provider_name,
                "model": model,
                "base_url": base_url,
                "api_key_env": api_key_env,
            }
        },
        agent_registry=registry,
    )
    draft_report = getattr(provider, "draft_report", None)
    if not callable(draft_report):
        raise RuntimeError(f"provider {provider_name!r} does not support draft_report")
    payload = {
        "topic": problem.topic,
        "research_route": route,
        "report_template_mode": report_template_mode,
        "execution_profile_id": str(
            blueprint.get("execution_profile_id") or "optimized_v2"
        ),
        "report_context": {
            "primary_branch": blueprint.get(
                "primary_branch",
                artifacts["branch_deliverables"].get("branch", ""),
            ),
            "branch_name": artifacts["branch_deliverables"].get(
                "branch_name", ""
            ),
            "secondary_branches": list(blueprint.get("secondary_branches", []))[:2],
            "audit_status": audit.status,
            "audit_limits": [str(item)[:220] for item in audit.comments[:3]],
            "coverage_passed": bool(coverage.get("coverage_passed")),
        },
        "synthesis_seed": _report_synthesis_seed(
            store=store,
            branch_output=artifacts["branch_deliverables"],
            convergence=round_summary.get("discovery_convergence", {}),
        ),
        "evidence_catalog": _report_evidence_catalog(
            store,
            limit=8,
            claim_chars=150,
        ),
        "branch_report_contract": artifacts["branch_report_contract"],
        "branch_writer_brief": artifacts["branch_writer_brief"],
    }
    synthesis = str(draft_report(payload)).strip()
    metric_reader = getattr(provider, "_call_metrics_since", None)
    call_metrics = metric_reader(0) if callable(metric_reader) else []
    reporter_call_metrics = [
        dict(item)
        for item in call_metrics
        if isinstance(item, dict) and str(item.get("agent_id", "")) == "reporter"
    ]
    quality_issue_consumer = getattr(provider, "consume_report_quality_issues", None)
    retained_quality_issues = (
        quality_issue_consumer()
        if callable(quality_issue_consumer)
        else []
    )
    blocking_quality_issues = _report_delivery_blocking_issues(
        retained_quality_issues
    )
    # Reporter chapter-local retries already handle missing/invalid chapters.
    # Residual assembly findings are persisted as diagnostics and must not
    # hard-fail the report-only regeneration; the downstream quality artifact
    # remains authoritative for review and follow-up repair.
    if len(synthesis) < 800:
        # Preserve a short but non-empty Reporter result as a reviewable
        # limited synthesis; do not turn length variance into a hard failure.
        synthesis_metadata_note = "undersized_synthesis_retained_for_review"
    else:
        synthesis_metadata_note = ""
    return synthesis, {
        "mode": "real_cross_material_synthesis",
        "report_template_mode": report_template_mode,
        "provider": provider_name,
        "model": model,
        "base_url_host": str(recorded.get("base_url_host") or "custom"),
        "model_call_count": len(reporter_call_metrics),
        "model_elapsed_seconds": round(
            sum(
                float(item.get("elapsed_seconds", 0.0) or 0.0)
                for item in reporter_call_metrics
            ),
            3,
        ),
        "call_metrics": reporter_call_metrics,
        "advisory_quality_issues": [
            str(item) for item in retained_quality_issues[:16]
        ],
        "retained_blocking_quality_issues": [
            str(item) for item in blocking_quality_issues[:16]
        ],
        "synthesis_length_note": synthesis_metadata_note,
        "source_counts": {
            "agent_packets": len(store.baseline_packets),
            "evidence": len(store.evidence),
            "reasoning_nodes": len(store.reasoning_nodes),
            "stage_outputs": len(store.stage_outputs),
            "capability_images": len(store.capability_images),
        },
    }


def _append_reporter_session(run_dir: Path, row: dict[str, Any]) -> None:
    path = run_dir / "agent_sessions" / "reporter.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
