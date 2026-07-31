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
            reporter_summary = args.synthesis_file.resolve().read_text(
                encoding="utf-8"
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
                    provider_override=args.provider,
                    model_override=args.model,
                    base_url_override=args.base_url,
                    api_key_env_override=args.api_key_env,
                )
            except Exception as exc:
                failure = {
                    "run_id": args.run_id,
                    "status": "failed_no_fallback",
                    "reason": type(exc).__name__,
                    "detail": str(exc)[:1000],
                    "report_overwritten": False,
                }
                workspace.write_run_text(
                    "report_regeneration_failure.json",
                    json.dumps(
                        failure,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                )
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
        existing_report = store.reports.get(report.report_id)
        if existing_report is not None and existing_report.body == report.body:
            report = replace(report, created_at=existing_report.created_at)
        quality_report = ReportQualityGate().validate(
            report.body,
            {
                "evidence_count": len(store.evidence),
                "branch": branch,
                "report_hard_max_chars": artifacts["branch_writer_brief"].get(
                    "hard_max_chars"
                ),
                "branch_delivery_status": artifacts["branch_deliverables"].get(
                    "delivery_status"
                ),
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
                r"\b(?:packet|claim|ev|stage|capability)-[A-Za-z0-9_.:-]+",
                report.body,
            )
        )
        source_binding_passed = binding_rate >= 0.9 and not internal_reference_found
        stale_report_gate_comment = "optimized_v2正式报告门控未全部通过"
        audit = replace(
            audit,
            comments=[
                str(item)
                for item in audit.comments
                if stale_report_gate_comment not in str(item)
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


def _last_reporter_summary(run_dir: Path) -> str:
    session_path = run_dir / "agent_sessions" / "reporter.jsonl"
    if not session_path.exists():
        return ""
    summary = ""
    for line in session_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event_type") == "model_result" and str(row.get("text", "")).strip():
            summary = str(row["text"]).strip()
    return summary


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
    if retained_quality_issues:
        raise RuntimeError(
            "reporter retained quality issues: "
            + "；".join(str(item) for item in retained_quality_issues[:8])
        )
    if len(synthesis) < 800:
        raise RuntimeError(
            f"reporter returned an undersized synthesis ({len(synthesis)} chars)"
        )
    return synthesis, {
        "mode": "real_cross_material_synthesis",
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
