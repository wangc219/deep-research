"""Evaluate Stage 3.1 route concept candidates against gold slots.

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


DEFAULT_STAGE3_1_DB = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions.sqlite"
)
DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_OUTPUT_JSON = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_1_route_slot_abstraction_eval_summary.json"
)
DEFAULT_REPORT = Path("docs/experiment-artifacts/stage3_1_route_slot_abstraction_eval.md")


def main() -> int:
    args = _parse_args()
    cases = _read_jsonl(Path(args.gold_routes))
    summary = evaluate_stage3_1_route_slot_abstraction(cases=cases, db_path=Path(args.db))

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.db), Path(args.gold_routes)), encoding="utf-8")

    print("stage3_1_route_slot_abstraction_eval_summary=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0


def evaluate_stage3_1_route_slot_abstraction(
    cases: list[dict[str, Any]],
    db_path: Path,
) -> dict[str, Any]:
    baseline = _load_candidates(db_path, include_route_concepts=False)
    augmented = _load_candidates(db_path, include_route_concepts=True)
    baseline_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(cases, baseline)
    augmented_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(cases, augmented)
    route_concept_count, route_concept_source_counts = _route_concept_counts(db_path)
    return {
        "db_path": str(db_path),
        "route_concept_count": route_concept_count,
        "route_concept_source_counts": route_concept_source_counts,
        "baseline": _metric_view(baseline_summary),
        "concept_augmented": _metric_view(augmented_summary),
        "delta": _delta_view(baseline_summary, augmented_summary),
        "cases": _case_delta_view(baseline_summary, augmented_summary),
    }


def render_report(summary: dict[str, Any], db_path: Path, gold_path: Path) -> str:
    lines = [
        "# Stage 3.1 Route Slot Abstraction Evaluation",
        "",
        "本报告只评价 route concept 是否改善 gold slot / endpoint readiness 覆盖。gold labels 只用于评价，不参与概念生成。",
        "",
        "## Inputs",
        "",
        f"- Stage 3.1 DB: `{db_path}`",
        f"- gold routes: `{gold_path}`",
        "",
        "## Overall",
        "",
        f"- route concepts: {summary['route_concept_count']}",
        f"- route concept source methods: `{summary['route_concept_source_counts']}`",
        f"- baseline slot hit: {summary['baseline']['slot_hit_count']}/{summary['baseline']['slot_total']} ({summary['baseline']['slot_hit_rate']:.2%})",
        f"- concept-augmented slot hit: {summary['concept_augmented']['slot_hit_count']}/{summary['concept_augmented']['slot_total']} ({summary['concept_augmented']['slot_hit_rate']:.2%})",
        f"- slot hit delta: {summary['delta']['slot_hit_count']}",
        f"- baseline endpoint readiness: {summary['baseline']['endpoint_ready_count']}/{summary['baseline']['edge_total']} ({summary['baseline']['endpoint_ready_rate']:.2%})",
        f"- concept-augmented endpoint readiness: {summary['concept_augmented']['endpoint_ready_count']}/{summary['concept_augmented']['edge_total']} ({summary['concept_augmented']['endpoint_ready_rate']:.2%})",
        f"- endpoint readiness delta: {summary['delta']['endpoint_ready_count']}",
        f"- edge hit delta: {summary['delta']['edge_hit_count']}",
        "",
        "## Interpretation",
        "",
        "- `baseline` 只使用原 `candidate_slots`。",
        "- `concept_augmented` 把 `route_concept_candidates` 转成只用于评价的 candidate slot，再与原 `candidate_slots` 合并。",
        "- 本脚本没有把 route concept 写回 `candidate_slots`，也没有把 route concept 自动接入 `candidate_edges`。",
        "- 因此本轮主要观察 slot hit 和 endpoint readiness；edge hit 不显著提升是预期风险。",
        "",
        "## Case Deltas",
        "",
        "| case | baseline slot | augmented slot | delta | baseline endpoint | augmented endpoint | delta |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['baseline_slot_hit_count']}/{case['slot_total']} | "
            f"{case['augmented_slot_hit_count']}/{case['slot_total']} | {case['slot_hit_delta']} | "
            f"{case['baseline_endpoint_ready_count']}/{case['edge_total']} | "
            f"{case['augmented_endpoint_ready_count']}/{case['edge_total']} | {case['endpoint_ready_delta']} |"
        )
    return "\n".join(lines) + "\n"


def _load_candidates(db_path: Path, include_route_concepts: bool) -> dict[str, dict[str, list[dict[str, Any]]]]:
    candidates = evaluate_stage3_route_candidates._load_candidates(db_path)
    if not include_route_concepts:
        return candidates
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
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
    finally:
        conn.close()
    return candidates


def _route_concept_counts(db_path: Path) -> tuple[int, dict[str, int]]:
    conn = sqlite3.connect(db_path)
    try:
        count = int(conn.execute("SELECT COUNT(1) FROM route_concept_candidates").fetchone()[0])
        source_counts = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT source_method, COUNT(1) FROM route_concept_candidates GROUP BY source_method ORDER BY source_method"
            )
        }
    finally:
        conn.close()
    return count, source_counts


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
    ]
    return {key: summary[key] for key in keys}


def _delta_view(baseline: dict[str, Any], augmented: dict[str, Any]) -> dict[str, int]:
    return {
        "slot_hit_count": int(augmented["slot_hit_count"]) - int(baseline["slot_hit_count"]),
        "endpoint_ready_count": int(augmented["endpoint_ready_count"]) - int(baseline["endpoint_ready_count"]),
        "edge_hit_count": int(augmented["edge_hit_count"]) - int(baseline["edge_hit_count"]),
        "chain_hit_count": int(augmented["chain_hit_count"]) - int(baseline["chain_hit_count"]),
        "route_hit_count": int(augmented["route_hit_count"]) - int(baseline["route_hit_count"]),
    }


def _case_delta_view(baseline: dict[str, Any], augmented: dict[str, Any]) -> list[dict[str, Any]]:
    augmented_by_case = {case["case_id"]: case for case in augmented["cases"]}
    rows = []
    for base_case in baseline["cases"]:
        aug_case = augmented_by_case[str(base_case["case_id"])]
        rows.append(
            {
                "case_id": base_case["case_id"],
                "slot_total": base_case["slot_total"],
                "edge_total": base_case["edge_total"],
                "baseline_slot_hit_count": base_case["slot_hit_count"],
                "augmented_slot_hit_count": aug_case["slot_hit_count"],
                "slot_hit_delta": aug_case["slot_hit_count"] - base_case["slot_hit_count"],
                "baseline_endpoint_ready_count": base_case["endpoint_ready_count"],
                "augmented_endpoint_ready_count": aug_case["endpoint_ready_count"],
                "endpoint_ready_delta": aug_case["endpoint_ready_count"] - base_case["endpoint_ready_count"],
                "baseline_edge_hit_count": base_case["edge_hit_count"],
                "augmented_edge_hit_count": aug_case["edge_hit_count"],
                "edge_hit_delta": aug_case["edge_hit_count"] - base_case["edge_hit_count"],
            }
        )
    return rows


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_concept_count": summary["route_concept_count"],
        "baseline_slot_hit": f"{summary['baseline']['slot_hit_count']}/{summary['baseline']['slot_total']}",
        "concept_augmented_slot_hit": f"{summary['concept_augmented']['slot_hit_count']}/{summary['concept_augmented']['slot_total']}",
        "slot_hit_delta": summary["delta"]["slot_hit_count"],
        "baseline_endpoint_ready": f"{summary['baseline']['endpoint_ready_count']}/{summary['baseline']['edge_total']}",
        "concept_augmented_endpoint_ready": f"{summary['concept_augmented']['endpoint_ready_count']}/{summary['concept_augmented']['edge_total']}",
        "endpoint_ready_delta": summary["delta"]["endpoint_ready_count"],
        "edge_hit_delta": summary["delta"]["edge_hit_count"],
    }


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
    parser = argparse.ArgumentParser(description="Evaluate Stage 3.1 route concept slot lift.")
    parser.add_argument("--db", default=str(DEFAULT_STAGE3_1_DB))
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
