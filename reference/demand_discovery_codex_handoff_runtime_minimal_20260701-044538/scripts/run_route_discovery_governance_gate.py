"""Run route discovery governance gates and produce a diagnosis report.

The gate combines benchmark structure validation, gold evidence audit, strict
Stage 3 evaluation, and semantic near-match review. Gold labels are used only
for evaluation and diagnosis; this script must not be used as generation input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import audit_route_discovery_gold_evidence
import audit_route_discovery_gold_adequacy
import evaluate_stage3_route_candidates
import route_discovery_gold_alignment
import review_stage3_candidate_edges
import validate_route_discovery_cases


DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_SOURCE_MANIFEST = Path("data/benchmarks/route_discovery/source_manifest_v0.jsonl")
DEFAULT_GOLD_AUDIT = Path("data/benchmarks/route_discovery/gold_slot_evidence_audit_v0.jsonl")
DEFAULT_GOLD_ALIGNMENT = Path("data/benchmarks/route_discovery/gold_alignment_v0.jsonl")
DEFAULT_STAGE3_DB = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/"
    "stage3_route_candidates_llm_governed.sqlite"
)
DEFAULT_OUTPUT_JSON = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/"
    "route_discovery_governance_gate_summary.json"
)
DEFAULT_REPORT = Path("docs/experiment-artifacts/route_discovery_governance_gate_v1.md")


def main() -> int:
    args = _parse_args()
    summary = run_governance_gate(
        gold_routes=Path(args.gold_routes),
        source_manifest=Path(args.source_manifest),
        gold_audit=Path(args.gold_audit),
        stage3_db=Path(args.stage3_db) if args.stage3_db else None,
        gold_alignment=Path(args.gold_alignment) if args.gold_alignment else None,
        project_root=Path(args.project_root).resolve(),
        require_source_files=not args.allow_missing_source_files,
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.stage3_db) if args.stage3_db else None), encoding="utf-8")

    print("route_discovery_governance_gate=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0 if summary["diagnosis"]["gate_status"] != "blocked" else 1


def run_governance_gate(
    gold_routes: Path,
    source_manifest: Path,
    gold_audit: Path,
    stage3_db: Path | None,
    gold_alignment: Path | None,
    project_root: Path,
    require_source_files: bool = True,
) -> dict[str, Any]:
    cases = validate_route_discovery_cases.read_jsonl(gold_routes)
    sources = validate_route_discovery_cases.read_jsonl(source_manifest)
    case_errors = validate_route_discovery_cases.validate_cases(cases, sources)
    case_validation = {
        "case_count": len(cases),
        "source_count": len(sources),
        "error_count": len(case_errors),
        "errors": case_errors,
    }

    audit_rows = audit_route_discovery_gold_evidence.read_jsonl(gold_audit)
    gold_audit_summary = audit_route_discovery_gold_evidence.audit_gold_evidence(
        cases,
        audit_rows,
        project_root=project_root,
        require_source_files=require_source_files,
    )

    strict_summary: dict[str, Any] = {}
    semantic_summary: dict[str, Any] = {}
    gold_adequacy_summary: dict[str, Any] = {}
    if stage3_db is not None and stage3_db.exists():
        candidates = audit_route_discovery_gold_adequacy.load_candidate_surface(stage3_db)
        alignment = (
            route_discovery_gold_alignment.load_gold_alignment_if_exists(gold_alignment)
            if gold_alignment is not None
            else None
        )
        strict_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(
            cases,
            candidates,
            alignment=alignment,
        )
        semantic_summary = review_stage3_candidate_edges.review_stage3_candidate_edges(cases, candidates)
        gold_adequacy_summary = audit_route_discovery_gold_adequacy.audit_gold_adequacy(
            cases=cases,
            db_path=stage3_db,
            gold_routes=gold_routes,
        )

    diagnosis = diagnose_governance_state(
        gold_audit_summary=gold_audit_summary,
        case_validation=case_validation,
        strict_summary=strict_summary,
        semantic_summary=semantic_summary,
        gold_adequacy_summary=gold_adequacy_summary,
    )
    return {
        "gold_routes": str(gold_routes),
        "source_manifest": str(source_manifest),
        "gold_audit": str(gold_audit),
        "stage3_db": str(stage3_db) if stage3_db is not None else "",
        "case_validation": case_validation,
        "gold_audit_summary": gold_audit_summary,
        "strict_stage3_summary": _stage3_overall(strict_summary),
        "calibrated_stage3_summary": _calibrated_overall(strict_summary),
        "semantic_stage3_summary": _semantic_overall(semantic_summary),
        "gold_adequacy_summary": _gold_adequacy_overall(gold_adequacy_summary),
        "diagnosis": diagnosis,
    }


def diagnose_governance_state(
    gold_audit_summary: dict[str, Any],
    case_validation: dict[str, Any],
    strict_summary: dict[str, Any],
    semantic_summary: dict[str, Any],
    gold_adequacy_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommended_actions: list[str] = []
    signals: list[str] = []
    expectation_counts = semantic_summary.get("expectation_counts", {}) if semantic_summary else {}
    local_extraction_gate_edges = int(expectation_counts.get("local_extraction_gate", 0) or 0)

    if int(case_validation.get("error_count", 0) or 0) > 0:
        return {
            "gate_status": "blocked",
            "gold_case_status": "blocked",
            "primary_bottleneck": "benchmark_structure",
            "signals": ["benchmark_case_validation_failed"],
            "local_extraction_gate_edges": local_extraction_gate_edges,
            "recommended_actions": ["fix benchmark structural validation errors before interpreting pipeline metrics"],
        }

    if not gold_audit_summary.get("ready", False):
        return {
            "gate_status": "blocked",
            "gold_case_status": "blocked",
            "primary_bottleneck": "gold_case_audit",
            "signals": ["gold_evidence_audit_failed"],
            "local_extraction_gate_edges": local_extraction_gate_edges,
            "recommended_actions": ["fix gold evidence audit before interpreting extraction metrics"],
        }

    if not strict_summary:
        return {
            "gate_status": "gold_ready",
            "gold_case_status": "ready",
            "primary_bottleneck": "stage3_not_evaluated",
            "signals": ["stage3_candidate_db_not_available"],
            "local_extraction_gate_edges": local_extraction_gate_edges,
            "recommended_actions": ["run Stage 2/2.5/2.6/3 and then rerun this governance gate"],
        }

    strict_edge_hits = int(strict_summary.get("edge_hit_count", 0) or 0)
    strict_route_hits = int(strict_summary.get("route_hit_count", 0) or 0)
    edge_total = int(strict_summary.get("edge_total", 0) or 0)
    endpoint_ready = int(strict_summary.get("endpoint_ready_count", 0) or 0)
    semantic_matches = int(semantic_summary.get("semantic_edge_match_count", 0) or 0)
    relation_near_miss = int(semantic_summary.get("relation_near_miss_count", 0) or 0)
    endpoint_near_miss = int(semantic_summary.get("endpoint_near_miss_count", 0) or 0)
    missing_candidates = int(semantic_summary.get("missing_candidate_count", 0) or 0)
    wrong_direction = int(semantic_summary.get("wrong_direction_count", 0) or 0)
    relation_issue_count = relation_near_miss + wrong_direction
    endpoint_issue_count = endpoint_near_miss + missing_candidates
    calibrated = strict_summary.get("calibrated", {}) if strict_summary else {}
    calibrated_edge_hits = int(calibrated.get("edge_hit_count", strict_edge_hits) or 0)
    calibrated_route_variant_hits = int(calibrated.get("route_variant_hit_count", 0) or 0)

    if local_extraction_gate_edges == 0:
        signals.append("no_chunk_local_gold_edge_gate")
    if calibrated_edge_hits > strict_edge_hits:
        signals.append("manual_alignment_calibrated_hits_present")
    if calibrated_route_variant_hits > 0:
        signals.append("partial_route_variant_present")
    if strict_edge_hits == 0 and semantic_matches > 0:
        signals.append("strict_match_low_but_semantic_match_present")
    if relation_near_miss > 0:
        signals.append("relation_type_near_miss_present")
    if wrong_direction > 0:
        signals.append("direction_error_present")
    if endpoint_ready < edge_total:
        signals.append("endpoint_readiness_incomplete")
    if endpoint_near_miss > 0 or missing_candidates > 0:
        signals.append("candidate_expansion_incomplete")
    if strict_edge_hits > 0 and strict_route_hits == 0:
        signals.append("route_assembly_not_yet_validated")
    if gold_adequacy_summary and gold_adequacy_summary.get("strict_scores_may_understate_progress", False):
        signals.append("gold_adequacy_review_needed")
        recommended_actions.append("review gold adequacy issues before treating strict misses as model failure")

    primary_bottleneck = "ready_for_larger_validation"
    if relation_issue_count and relation_issue_count >= max(semantic_matches, endpoint_issue_count):
        primary_bottleneck = "relation_review_or_prompt"
        recommended_actions.append("review relation type and direction failures before route-level prediction")
    elif relation_issue_count:
        recommended_actions.append("review relation type near misses as a secondary gate")
    if primary_bottleneck != "relation_review_or_prompt" and strict_edge_hits == 0 and semantic_matches > 0:
        primary_bottleneck = "normalization_or_candidate_alignment"
        recommended_actions.append("improve canonical alias alignment and semantic endpoint matching before judging prompt failure")
    elif primary_bottleneck != "relation_review_or_prompt" and (endpoint_ready < edge_total or missing_candidates):
        primary_bottleneck = "candidate_expansion"
        recommended_actions.append("expand candidate slots and endpoint candidates using visible context, embeddings, and LLM review")
    elif primary_bottleneck != "relation_review_or_prompt" and strict_edge_hits > 0 and strict_route_hits == 0:
        primary_bottleneck = "route_assembly"
        recommended_actions.append("add route assembly and rerank over unverified candidate edges")

    if not recommended_actions:
        recommended_actions.append("run a larger non-benchmark validation sample before any production extraction")

    return {
        "gate_status": "evaluated",
        "gold_case_status": "ready",
        "primary_bottleneck": primary_bottleneck,
        "signals": signals,
        "local_extraction_gate_edges": local_extraction_gate_edges,
        "recommended_actions": recommended_actions,
    }


def render_report(summary: dict[str, Any], stage3_db: Path | None) -> str:
    diagnosis = summary["diagnosis"]
    strict = summary["strict_stage3_summary"]
    calibrated = summary.get("calibrated_stage3_summary", {})
    semantic = summary["semantic_stage3_summary"]
    audit = summary["gold_audit_summary"]
    adequacy = summary.get("gold_adequacy_summary", {})
    lines = [
        "# Route Discovery Governance Gate v1",
        "",
        "本报告把 benchmark 正确性、候选严格命中、语义近似命中和瓶颈归因分开。gold labels 只用于评价，不参与候选生成。",
        "",
        "## Inputs",
        "",
        f"- gold routes: `{summary['gold_routes']}`",
        f"- source manifest: `{summary['source_manifest']}`",
        f"- gold audit: `{summary['gold_audit']}`",
        f"- stage3 DB: `{stage3_db}`" if stage3_db else "- stage3 DB: not provided",
        "",
        "## Gate Summary",
        "",
        f"- gate status: `{diagnosis['gate_status']}`",
        f"- gold case status: `{diagnosis['gold_case_status']}`",
        f"- primary bottleneck: `{diagnosis['primary_bottleneck']}`",
        f"- signals: `{diagnosis['signals']}`",
        f"- recommended actions: `{diagnosis['recommended_actions']}`",
        "",
        "## Gold Evidence Audit",
        "",
        f"- ready: `{audit['ready']}`",
        f"- gold slots / audit records: {audit['gold_slot_count']} / {audit['audit_record_count']}",
        f"- verdict counts: `{audit['verdict_counts']}`",
        f"- errors: {len(audit['errors'])}",
        f"- warnings: {len(audit['warnings'])}",
        "",
        "## Gold Adequacy Gate",
        "",
        f"- status: `{adequacy.get('gold_adequacy_status', 'not_run')}`",
        f"- strict scores may understate progress: `{adequacy.get('strict_scores_may_understate_progress', False)}`",
        f"- review issues: {adequacy.get('review_issue_count', 0)}",
        f"- issue counts: `{adequacy.get('issue_counts', {})}`",
        "",
        "## Stage 3 Strict Evaluation",
        "",
        f"- slot hit: {strict.get('slot_hit_count', 0)}/{strict.get('slot_total', 0)}",
        f"- endpoint readiness: {strict.get('endpoint_ready_count', 0)}/{strict.get('edge_total', 0)}",
        f"- edge hit: {strict.get('edge_hit_count', 0)}/{strict.get('edge_total', 0)}",
        f"- chain hit: {strict.get('chain_hit_count', 0)}/{strict.get('chain_total', 0)}",
        f"- route hit: {strict.get('route_hit_count', 0)}/{strict.get('route_total', 0)}",
        "",
        "## Stage 3 Calibrated Evaluation",
        "",
        f"- gold alignment applied: `{calibrated.get('gold_alignment_applied', False)}`",
        f"- calibrated edge hit: {calibrated.get('edge_hit_count', 0)}/{calibrated.get('edge_total', 0)} "
        f"(delta vs strict: {calibrated.get('edge_hit_delta_vs_strict', 0)})",
        f"- calibrated route hit: {calibrated.get('route_hit_count', 0)}/{calibrated.get('route_total', 0)} "
        f"(delta vs strict: {calibrated.get('route_hit_delta_vs_strict', 0)})",
        f"- calibrated route variant hit: {calibrated.get('route_variant_hit_count', 0)}/"
        f"{calibrated.get('route_variant_total', 0)}",
        "",
        "## Stage 3 Semantic Review",
        "",
        f"- semantic edge match: {semantic.get('semantic_edge_match_count', 0)}/{semantic.get('edge_total', 0)}",
        f"- label counts: `{semantic.get('label_counts', {})}`",
        f"- expectation buckets: `{semantic.get('expectation_counts', {})}`",
        "",
        "## Interpretation",
        "",
        "- `no_chunk_local_gold_edge_gate` 表示当前 gold edge 主要不该由单 chunk 抽取直接命中，不能用 direct edge=0 推断 prompt 失败。",
        "- `manual_alignment_calibrated_hits_present` 表示人工审核的 endpoint/route 对齐后新增了命中，strict 字符串口径确有低估。",
        "- `partial_route_variant_present` 表示存在人工声明的子路线命中，但它不等于完整四层 strict route 命中。",
        "- `strict_match_low_but_semantic_match_present` 表示严格字符串口径低估了候选质量，应优先处理 alias/canonical 对齐。",
        "- `gold_adequacy_review_needed` 表示 gold alias、endpoint、acceptable_relations、route pattern 或 stage policy 可能过窄；只能生成审核项，不能自动把候选写回 gold。",
        "- `relation_type_near_miss_present` 或 `direction_error_present` 才指向关系 schema/prompt 或关系审核需要继续加强。",
        "- 所有 Stage 3 输出仍是 `unverified_candidate`，不是事实图谱边。",
        "",
    ]
    return "\n".join(lines)


def _stage3_overall(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        "slot_hit_count": summary["slot_hit_count"],
        "slot_total": summary["slot_total"],
        "endpoint_ready_count": summary["endpoint_ready_count"],
        "edge_hit_count": summary["edge_hit_count"],
        "edge_total": summary["edge_total"],
        "chain_hit_count": summary["chain_hit_count"],
        "chain_total": summary["chain_total"],
        "route_hit_count": summary["route_hit_count"],
        "route_total": summary["route_total"],
        "candidate_source_counts": summary.get("candidate_source_counts", {}),
    }


def _calibrated_overall(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    calibrated = summary.get("calibrated")
    if not calibrated:
        return {
            "gold_alignment_applied": bool(summary.get("gold_alignment_applied", False)),
            "gold_alignment_record_count": int(summary.get("gold_alignment_record_count", 0) or 0),
            "strict_edge_hit_count": int(summary.get("edge_hit_count", 0) or 0),
            "strict_route_hit_count": int(summary.get("route_hit_count", 0) or 0),
            "edge_hit_delta_vs_strict": 0,
            "route_hit_delta_vs_strict": 0,
            "route_variant_hit_count": 0,
            "route_variant_total": 0,
        }
    edge_hit_count = int(calibrated.get("edge_hit_count", 0) or 0)
    route_hit_count = int(calibrated.get("route_hit_count", 0) or 0)
    strict_edge_hit_count = int(summary.get("edge_hit_count", 0) or 0)
    strict_route_hit_count = int(summary.get("route_hit_count", 0) or 0)
    return {
        "gold_alignment_applied": bool(summary.get("gold_alignment_applied", True)),
        "gold_alignment_record_count": int(summary.get("gold_alignment_record_count", 0) or 0),
        "slot_hit_count": int(calibrated.get("slot_hit_count", 0) or 0),
        "slot_total": int(calibrated.get("slot_total", 0) or 0),
        "endpoint_ready_count": int(calibrated.get("endpoint_ready_count", 0) or 0),
        "edge_hit_count": edge_hit_count,
        "edge_total": int(calibrated.get("edge_total", 0) or 0),
        "chain_hit_count": int(calibrated.get("chain_hit_count", 0) or 0),
        "chain_total": int(calibrated.get("chain_total", 0) or 0),
        "route_hit_count": route_hit_count,
        "route_total": int(calibrated.get("route_total", 0) or 0),
        "route_variant_hit_count": int(calibrated.get("route_variant_hit_count", 0) or 0),
        "route_variant_total": int(calibrated.get("route_variant_total", 0) or 0),
        "strict_edge_hit_count": strict_edge_hit_count,
        "strict_route_hit_count": strict_route_hit_count,
        "edge_hit_delta_vs_strict": edge_hit_count - strict_edge_hit_count,
        "route_hit_delta_vs_strict": route_hit_count - strict_route_hit_count,
    }


def _semantic_overall(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        "edge_total": summary["edge_total"],
        "semantic_edge_match_count": summary["semantic_edge_match_count"],
        "strict_match_count": summary["strict_match_count"],
        "relation_near_miss_count": summary["relation_near_miss_count"],
        "endpoint_near_miss_count": summary["endpoint_near_miss_count"],
        "wrong_direction_count": summary["wrong_direction_count"],
        "missing_candidate_count": summary["missing_candidate_count"],
        "label_counts": summary["label_counts"],
        "expectation_counts": summary["expectation_counts"],
    }


def _gold_adequacy_overall(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        "gold_adequacy_status": summary["gold_adequacy_status"],
        "strict_scores_may_understate_progress": summary["strict_scores_may_understate_progress"],
        "review_issue_count": summary["review_issue_count"],
        "issue_counts": summary["issue_counts"],
    }


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    diagnosis = summary["diagnosis"]
    return {
        "gate_status": diagnosis["gate_status"],
        "gold_case_status": diagnosis["gold_case_status"],
        "primary_bottleneck": diagnosis["primary_bottleneck"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_MANIFEST))
    parser.add_argument("--gold-audit", default=str(DEFAULT_GOLD_AUDIT))
    parser.add_argument("--gold-alignment", default=str(DEFAULT_GOLD_ALIGNMENT))
    parser.add_argument("--stage3-db", default=str(DEFAULT_STAGE3_DB))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--allow-missing-source-files", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
