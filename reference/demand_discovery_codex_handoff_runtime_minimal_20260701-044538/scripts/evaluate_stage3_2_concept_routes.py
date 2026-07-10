"""Evaluate Stage 3.2 concept-level edges and route assemblies.

Gold labels are used only for evaluation. This script does not participate in
candidate generation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any

import evaluate_stage3_route_candidates
from route_discovery_gold_alignment import GoldAlignment, load_gold_alignment_if_exists


DEFAULT_STAGE3_2_DB = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_concept_routes.sqlite"
)
DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_GOLD_ALIGNMENT = Path("data/benchmarks/route_discovery/gold_alignment_v0.jsonl")
DEFAULT_OUTPUT_JSON = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_2_concept_route_eval_summary.json"
)
DEFAULT_REPORT = Path("docs/experiment-artifacts/stage3_2_concept_route_evaluation.md")


def main() -> int:
    args = _parse_args()
    cases = _read_jsonl(Path(args.gold_routes))
    alignment = load_gold_alignment_if_exists(Path(args.gold_alignment))
    summary = evaluate_stage3_2_concept_routes(cases=cases, db_path=Path(args.db), alignment=alignment)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.db), Path(args.gold_routes)), encoding="utf-8")

    print("stage3_2_concept_route_eval_summary=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0


def evaluate_stage3_2_concept_routes(
    cases: list[dict[str, Any]],
    db_path: Path,
    alignment: GoldAlignment | None = None,
) -> dict[str, Any]:
    base = evaluate_stage3_route_candidates._load_candidates(db_path)
    concept_slots = _load_candidates(db_path, include_concept_slots=True, include_concept_edges=False)
    concept_graph = _load_candidates(db_path, include_concept_slots=True, include_concept_edges=True)

    base_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(cases, base, alignment=alignment)
    concept_slot_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(
        cases,
        concept_slots,
        alignment=alignment,
    )
    concept_graph_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(
        cases,
        concept_graph,
        alignment=alignment,
    )
    concept_edge_count, route_assembly_count, route_pattern_counts = _stage3_2_counts(db_path)
    return {
        "db_path": str(db_path),
        "concept_candidate_edge_count": concept_edge_count,
        "route_assembly_count": route_assembly_count,
        "route_pattern_counts": route_pattern_counts,
        "base": _metric_view(base_summary),
        "concept_slots_only": _metric_view(concept_slot_summary),
        "concept_graph": _metric_view(concept_graph_summary),
        "base_calibrated": _calibrated_metric_view(base_summary),
        "concept_slots_only_calibrated": _calibrated_metric_view(concept_slot_summary),
        "concept_graph_calibrated": _calibrated_metric_view(concept_graph_summary),
        "delta_vs_base": _delta_view(base_summary, concept_graph_summary),
        "delta_vs_concept_slots_only": _delta_view(concept_slot_summary, concept_graph_summary),
        "cases": _case_delta_view(concept_slot_summary, concept_graph_summary),
    }


def render_report(summary: dict[str, Any], db_path: Path, gold_path: Path) -> str:
    lines = [
        "# Stage 3.2 Concept Route Evaluation",
        "",
        "本报告评价 concept-level candidate edges 和 route assemblies 是否改善 gold edge / chain / route 覆盖。gold labels 只用于评价，不参与生成。",
        "",
        "## Inputs",
        "",
        f"- Stage 3.2 DB: `{db_path}`",
        f"- gold routes: `{gold_path}`",
        "",
        "## Overall",
        "",
        f"- concept candidate edges: {summary['concept_candidate_edge_count']}",
        f"- route assemblies: {summary['route_assembly_count']}",
        f"- route pattern counts: `{summary['route_pattern_counts']}`",
        f"- base edge hit: {summary['base']['edge_hit_count']}/{summary['base']['edge_total']} ({summary['base']['edge_hit_rate']:.2%})",
        f"- concept slots edge hit: {summary['concept_slots_only']['edge_hit_count']}/{summary['concept_slots_only']['edge_total']} ({summary['concept_slots_only']['edge_hit_rate']:.2%})",
        f"- concept graph edge hit: {summary['concept_graph']['edge_hit_count']}/{summary['concept_graph']['edge_total']} ({summary['concept_graph']['edge_hit_rate']:.2%})",
        f"- edge hit delta vs concept slots: {summary['delta_vs_concept_slots_only']['edge_hit_count']}",
        f"- chain hit delta vs concept slots: {summary['delta_vs_concept_slots_only']['chain_hit_count']}",
        f"- route hit delta vs concept slots: {summary['delta_vs_concept_slots_only']['route_hit_count']}",
        f"- calibrated concept graph edge hit: {summary['concept_graph_calibrated'].get('edge_hit_count', 0)}/"
        f"{summary['concept_graph_calibrated'].get('edge_total', 0)} "
        f"(delta vs strict: {summary['concept_graph_calibrated'].get('edge_hit_delta_vs_strict', 0)})",
        f"- calibrated route variant hit: {summary['concept_graph_calibrated'].get('route_variant_hit_count', 0)}/"
        f"{summary['concept_graph_calibrated'].get('route_variant_total', 0)}",
        "",
        "## Interpretation",
        "",
        "- `base` 只使用原 `candidate_slots` 和 `candidate_edges`。",
        "- `concept_slots_only` 加入 `route_concept_candidates`，但不加入 concept edges。",
        "- `concept_graph` 同时加入 `route_concept_candidates` 和 `concept_candidate_edges`。",
        "- `route_assemblies` 是候选路线排序/审核对象；严格 gold route hit 仍由 edge hit 组合计算。",
        "- `calibrated` 指标只使用人工审核的 gold alignment 对评价口径做补充；route variant hit 不等于 full strict route hit。",
        "",
        "## Case Deltas",
        "",
        "| case | concept-slot edge hit | concept-graph edge hit | delta | concept-slot route hit | concept-graph route hit | delta |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['concept_slots_edge_hit_count']}/{case['edge_total']} | "
            f"{case['concept_graph_edge_hit_count']}/{case['edge_total']} | {case['edge_hit_delta']} | "
            f"{case['concept_slots_route_hit_count']}/{case['route_total']} | "
            f"{case['concept_graph_route_hit_count']}/{case['route_total']} | {case['route_hit_delta']} |"
        )
    return "\n".join(lines) + "\n"


def _load_candidates(
    db_path: Path,
    include_concept_slots: bool,
    include_concept_edges: bool,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    candidates = evaluate_stage3_route_candidates._load_candidates(db_path)
    if not include_concept_slots and not include_concept_edges:
        return candidates
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if include_concept_slots:
            for row in conn.execute(
                """
                SELECT concept_id, case_id, layer, canonical_name, aliases_json,
                       source_method, source_mentions_json, confidence, status
                FROM route_concept_candidates
                WHERE status = 'unverified_candidate'
                ORDER BY case_id, layer, canonical_name
                """
            ):
                aliases = _loads_json_list(str(row["aliases_json"] or "[]"))
                source_mentions = _loads_json_list(str(row["source_mentions_json"] or "[]"))
                item = {
                    "candidate_id": str(row["concept_id"]),
                    "case_id": str(row["case_id"]),
                    "layer": str(row["layer"]),
                    "name": str(row["canonical_name"]),
                    "aliases": _dedupe_nonempty(aliases + source_mentions),
                    "source_method": "route_concept:" + str(row["source_method"]),
                    "confidence": row["confidence"],
                    "status": row["status"],
                }
                candidates.setdefault(str(row["case_id"]), {"slots": [], "edges": []})["slots"].append(item)
        if include_concept_edges and _table_exists(conn, "concept_candidate_edges"):
            for row in conn.execute(
                """
                SELECT concept_edge_id, case_id, source_concept_id, target_concept_id,
                       source_name, source_layer, relation_type, target_name,
                       target_layer, source_method, confidence, rationale, status
                FROM concept_candidate_edges
                WHERE status = 'unverified_candidate'
                ORDER BY case_id, relation_type, source_name, target_name
                """
            ):
                item = {
                    "candidate_edge_id": str(row["concept_edge_id"]),
                    "case_id": str(row["case_id"]),
                    "source_candidate_id": str(row["source_concept_id"]),
                    "target_candidate_id": str(row["target_concept_id"]),
                    "source_name": str(row["source_name"]),
                    "source_layer": str(row["source_layer"]),
                    "relation_type": str(row["relation_type"]),
                    "target_name": str(row["target_name"]),
                    "target_layer": str(row["target_layer"]),
                    "source_method": str(row["source_method"]),
                    "confidence": row["confidence"],
                    "rationale": str(row["rationale"] or ""),
                    "status": str(row["status"]),
                }
                candidates.setdefault(str(row["case_id"]), {"slots": [], "edges": []})["edges"].append(item)
    finally:
        conn.close()
    return candidates


def _stage3_2_counts(db_path: Path) -> tuple[int, int, dict[str, int]]:
    conn = sqlite3.connect(db_path)
    try:
        concept_edge_count = _count_table(conn, "concept_candidate_edges")
        route_assembly_count = _count_table(conn, "route_assemblies")
        route_pattern_counts = (
            {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT route_pattern, COUNT(1) FROM route_assemblies GROUP BY route_pattern ORDER BY route_pattern"
                )
            }
            if _table_exists(conn, "route_assemblies")
            else {}
        )
    finally:
        conn.close()
    return concept_edge_count, route_assembly_count, route_pattern_counts


def _metric_view(summary: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "slot_hit_count",
        "slot_total",
        "endpoint_ready_count",
        "edge_hit_count",
        "edge_total",
        "chain_hit_count",
        "chain_total",
        "route_hit_count",
        "route_total",
        "slot_hit_rate",
        "endpoint_ready_rate",
        "edge_hit_rate",
        "chain_hit_rate",
        "route_hit_rate",
    ]
    return {key: summary[key] for key in keys}


def _calibrated_metric_view(summary: dict[str, Any]) -> dict[str, Any]:
    calibrated = summary.get("calibrated")
    if not calibrated:
        return {
            "gold_alignment_applied": bool(summary.get("gold_alignment_applied", False)),
            "gold_alignment_record_count": int(summary.get("gold_alignment_record_count", 0) or 0),
            "edge_hit_count": int(summary.get("edge_hit_count", 0) or 0),
            "edge_total": int(summary.get("edge_total", 0) or 0),
            "route_hit_count": int(summary.get("route_hit_count", 0) or 0),
            "route_total": int(summary.get("route_total", 0) or 0),
            "route_variant_hit_count": 0,
            "route_variant_total": 0,
            "strict_edge_hit_count": int(summary.get("edge_hit_count", 0) or 0),
            "strict_route_hit_count": int(summary.get("route_hit_count", 0) or 0),
            "edge_hit_delta_vs_strict": 0,
            "route_hit_delta_vs_strict": 0,
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


def _delta_view(left: dict[str, Any], right: dict[str, Any]) -> dict[str, int]:
    return {
        "slot_hit_count": int(right["slot_hit_count"]) - int(left["slot_hit_count"]),
        "endpoint_ready_count": int(right["endpoint_ready_count"]) - int(left["endpoint_ready_count"]),
        "edge_hit_count": int(right["edge_hit_count"]) - int(left["edge_hit_count"]),
        "chain_hit_count": int(right["chain_hit_count"]) - int(left["chain_hit_count"]),
        "route_hit_count": int(right["route_hit_count"]) - int(left["route_hit_count"]),
    }


def _case_delta_view(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    right_by_case = {case["case_id"]: case for case in right["cases"]}
    rows = []
    for left_case in left["cases"]:
        right_case = right_by_case[str(left_case["case_id"])]
        rows.append(
            {
                "case_id": left_case["case_id"],
                "edge_total": left_case["edge_total"],
                "route_total": left_case["route_total"],
                "concept_slots_edge_hit_count": left_case["edge_hit_count"],
                "concept_graph_edge_hit_count": right_case["edge_hit_count"],
                "edge_hit_delta": right_case["edge_hit_count"] - left_case["edge_hit_count"],
                "concept_slots_route_hit_count": left_case["route_hit_count"],
                "concept_graph_route_hit_count": right_case["route_hit_count"],
                "route_hit_delta": right_case["route_hit_count"] - left_case["route_hit_count"],
            }
        )
    return rows


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "concept_candidate_edge_count": summary["concept_candidate_edge_count"],
        "route_assembly_count": summary["route_assembly_count"],
        "base_edge_hit": f"{summary['base']['edge_hit_count']}/{summary['base']['edge_total']}",
        "concept_graph_edge_hit": f"{summary['concept_graph']['edge_hit_count']}/{summary['concept_graph']['edge_total']}",
        "edge_hit_delta_vs_concept_slots": summary["delta_vs_concept_slots_only"]["edge_hit_count"],
        "route_hit_delta_vs_concept_slots": summary["delta_vs_concept_slots_only"]["route_hit_count"],
    }


def _count_table(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0])


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _loads_json_list(value: str) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item)]


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Stage 3.2 concept-level route candidates.")
    parser.add_argument("--db", default=str(DEFAULT_STAGE3_2_DB))
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--gold-alignment", default=str(DEFAULT_GOLD_ALIGNMENT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
