"""Evaluate Stage 3 route candidates against route discovery benchmark gold labels.

Gold labels are used only for evaluation. Candidate generation must not read
this script or its gold inputs as discovery context.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any

from route_discovery_gold_alignment import GoldAlignment, load_gold_alignment_if_exists
from stage3_endpoint_matching import build_slot_index, endpoint_layer, endpoint_terms


DEFAULT_STAGE3_DB = Path(
    "data/processed/extraction_experiments/stage2_entity_normalization_v1/stage3_route_candidates.sqlite"
)
DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_GOLD_ALIGNMENT = Path("data/benchmarks/route_discovery/gold_alignment_v0.jsonl")
DEFAULT_OUTPUT_JSON = Path(
    "data/processed/extraction_experiments/stage2_entity_normalization_v1/stage3_route_candidate_eval_summary.json"
)
DEFAULT_REPORT = Path("docs/experiment-artifacts/stage3_route_candidate_generation_v1_validation.md")

SLOT_KEYS = ("principles", "technologies", "capabilities", "applications")
SLOT_LAYERS = {
    "principles": {"principle"},
    "technologies": {"technology"},
    "capabilities": {"capability"},
    "applications": {"scenario"},
}
EDGE_SLOT_LAYERS = {
    "principle": SLOT_LAYERS["principles"],
    "technology": SLOT_LAYERS["technologies"],
    "capability": SLOT_LAYERS["capabilities"],
    "application": SLOT_LAYERS["applications"],
}


def main() -> int:
    args = _parse_args()
    cases = _read_jsonl(Path(args.gold_routes))
    candidates = _load_candidates(Path(args.db))
    alignment = load_gold_alignment_if_exists(Path(args.gold_alignment))
    summary = evaluate_stage3_candidates(cases, candidates, alignment=alignment)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.db), Path(args.gold_routes)), encoding="utf-8")

    print("stage3_route_candidate_eval_summary=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0


def evaluate_stage3_candidates(
    cases: list[dict[str, Any]],
    candidates: dict[str, dict[str, list[dict[str, Any]]]],
    alignment: GoldAlignment | None = None,
) -> dict[str, Any]:
    case_results = [
        evaluate_case(
            case,
            candidates.get(str(case["case_id"]), {"slots": [], "edges": []}),
            alignment=alignment,
        )
        for case in cases
    ]
    total_slots = sum(case["slot_total"] for case in case_results)
    total_edges = sum(case["edge_total"] for case in case_results)
    total_chains = sum(case["chain_total"] for case in case_results)
    total_routes = sum(case["route_total"] for case in case_results)
    summary = {
        "case_count": len(case_results),
        "slot_hit_count": sum(case["slot_hit_count"] for case in case_results),
        "slot_total": total_slots,
        "endpoint_ready_count": sum(case["endpoint_ready_count"] for case in case_results),
        "edge_hit_count": sum(case["edge_hit_count"] for case in case_results),
        "edge_total": total_edges,
        "chain_hit_count": sum(case["chain_hit_count"] for case in case_results),
        "chain_total": total_chains,
        "route_hit_count": sum(case["route_hit_count"] for case in case_results),
        "route_total": total_routes,
        "slot_hit_rate": _rate(sum(case["slot_hit_count"] for case in case_results), total_slots),
        "endpoint_ready_rate": _rate(sum(case["endpoint_ready_count"] for case in case_results), total_edges),
        "edge_hit_rate": _rate(sum(case["edge_hit_count"] for case in case_results), total_edges),
        "chain_hit_rate": _rate(sum(case["chain_hit_count"] for case in case_results), total_chains),
        "route_hit_rate": _rate(sum(case["route_hit_count"] for case in case_results), total_routes),
        "candidate_source_counts": _candidate_source_counts(candidates),
        "stage_aware": _stage_aware_summary(case_results),
        "gold_alignment_applied": alignment is not None,
        "gold_alignment_record_count": len(alignment.records) if alignment is not None else 0,
        "cases": case_results,
    }
    if alignment is not None:
        summary["calibrated"] = _calibrated_summary(case_results)
    return summary


def evaluate_case(
    case: dict[str, Any],
    candidate_rows: dict[str, list[dict[str, Any]]],
    alignment: GoldAlignment | None = None,
) -> dict[str, Any]:
    strict = _evaluate_case_core(case, candidate_rows, alignment=None)
    if alignment is None:
        return strict
    calibrated = _evaluate_case_core(case, candidate_rows, alignment=alignment)
    strict["calibrated"] = _calibrated_case_view(case, calibrated, alignment)
    return strict


def _evaluate_case_core(
    case: dict[str, Any],
    candidate_rows: dict[str, list[dict[str, Any]]],
    alignment: GoldAlignment | None = None,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    slots = candidate_rows["slots"]
    edges = candidate_rows["edges"]
    slot_by_id = build_slot_index(slots)
    slot_results: list[dict[str, Any]] = []
    for slot_key in SLOT_KEYS:
        for item in case.get("gold_slots", {}).get(slot_key, []):
            gold_names = _names_for_slot(item, case_id=case_id, alignment=alignment)
            matches = [
                slot
                for slot in slots
                if _candidate_slot_matches(gold_names, slot)
                and _candidate_layer_matches_slot(slot_key, str(slot.get("layer", "")))
            ]
            slot_results.append(
                {
                    "slot_key": slot_key,
                    "gold_name": item.get("name", ""),
                    "evaluation_stage": item.get("evaluation_stage", "unspecified"),
                    "visibility": item.get("visibility", "unspecified"),
                    "hit": bool(matches),
                    "matches": _short_slots(matches),
                }
            )

    slot_item_by_name = {
        item.get("name", ""): item
        for slot_key in SLOT_KEYS
        for item in case.get("gold_slots", {}).get(slot_key, [])
    }
    edge_results: list[dict[str, Any]] = []
    for edge in case.get("gold_edges", []):
        source_names = _names_for_slot(
            slot_item_by_name.get(edge.get("source_name", ""), {"name": edge.get("source_name", "")}),
            case_id=case_id,
            alignment=alignment,
        )
        target_names = _names_for_slot(
            slot_item_by_name.get(edge.get("target_name", ""), {"name": edge.get("target_name", "")}),
            case_id=case_id,
            alignment=alignment,
        )
        source_slot_matches = [
            slot
            for slot in slots
            if _candidate_slot_matches(source_names, slot)
            and _candidate_layer_matches_edge_slot(edge.get("source_slot", ""), str(slot.get("layer", "")))
        ]
        target_slot_matches = [
            slot
            for slot in slots
            if _candidate_slot_matches(target_names, slot)
            and _candidate_layer_matches_edge_slot(edge.get("target_slot", ""), str(slot.get("layer", "")))
        ]
        endpoint_ready = bool(source_slot_matches and target_slot_matches)
        edge_matches = [
            candidate_edge
            for candidate_edge in edges
            if _candidate_edge_endpoint_matches(
                source_names,
                target_names,
                candidate_edge,
                slot_by_id,
                edge.get("source_slot", ""),
                edge.get("target_slot", ""),
            )
            and candidate_edge.get("relation_type") in set(edge.get("acceptable_relations", []))
        ]
        reversed_matches = [
            candidate_edge
            for candidate_edge in edges
            if _candidate_edge_endpoint_matches(
                target_names,
                source_names,
                candidate_edge,
                slot_by_id,
                edge.get("target_slot", ""),
                edge.get("source_slot", ""),
            )
            and candidate_edge.get("relation_type") in set(edge.get("acceptable_relations", []))
        ]
        edge_results.append(
            {
                "edge_id": edge.get("edge_id", ""),
                "evaluation_stage": edge.get("evaluation_stage", "unspecified"),
                "gold_source": edge.get("source_name", ""),
                "gold_relation": edge.get("relation", ""),
                "gold_target": edge.get("target_name", ""),
                "endpoint_ready": endpoint_ready,
                "source_slot_hit": bool(source_slot_matches),
                "target_slot_hit": bool(target_slot_matches),
                "edge_hit": bool(edge_matches),
                "reversed_edge_hit": bool(reversed_matches),
                "matched_edges": _short_edges(edge_matches or reversed_matches),
            }
        )

    edge_hit_by_id = {edge["edge_id"]: edge["edge_hit"] for edge in edge_results}
    endpoint_ready_by_id = {edge["edge_id"]: edge["endpoint_ready"] for edge in edge_results}
    chain_results = []
    for chain in case.get("gold_chains", []):
        edge_ids = list(chain.get("edge_ids", []))
        chain_results.append(
            {
                "chain_id": chain.get("chain_id", ""),
                "endpoint_ready": all(endpoint_ready_by_id.get(edge_id, False) for edge_id in edge_ids),
                "hit": all(edge_hit_by_id.get(edge_id, False) for edge_id in edge_ids),
            }
        )
    route_results = []
    for route in case.get("gold_routes", []):
        edge_ids = list(route.get("edge_ids", []))
        route_results.append(
            {
                "route_id": route.get("route_id", ""),
                "endpoint_ready": all(endpoint_ready_by_id.get(edge_id, False) for edge_id in edge_ids),
                "hit": all(edge_hit_by_id.get(edge_id, False) for edge_id in edge_ids),
            }
        )

    return {
        "case_id": case_id,
        "title": case.get("title", ""),
        "candidate_slot_count": len(slots),
        "candidate_edge_count": len(edges),
        "candidate_source_counts": {
            "slots": dict(Counter(slot.get("source_method", "") for slot in slots)),
            "edges": dict(Counter(edge.get("source_method", "") for edge in edges)),
        },
        "slot_hit_count": sum(1 for result in slot_results if result["hit"]),
        "slot_total": len(slot_results),
        "endpoint_ready_count": sum(1 for result in edge_results if result["endpoint_ready"]),
        "edge_hit_count": sum(1 for result in edge_results if result["edge_hit"]),
        "edge_total": len(edge_results),
        "chain_hit_count": sum(1 for result in chain_results if result["hit"]),
        "chain_total": len(chain_results),
        "route_hit_count": sum(1 for result in route_results if result["hit"]),
        "route_total": len(route_results),
        "slot_results": slot_results,
        "edge_results": edge_results,
        "chain_results": chain_results,
        "route_results": route_results,
    }


def render_report(summary: dict[str, Any], db_path: Path, gold_path: Path) -> str:
    lines = [
        "# Stage 3 Route Candidate Generation v1 Validation",
        "",
        "本报告只评价 Stage 3 产出的 `unverified_candidate` 是否覆盖 benchmark gold labels；gold labels 只用于评价，不作为候选生成输入。",
        "",
        "## Inputs",
        "",
        f"- candidate DB: `{db_path}`",
        f"- gold routes: `{gold_path}`",
        "",
        "## Overall",
        "",
        f"- slot hit: {summary['slot_hit_count']}/{summary['slot_total']} ({summary['slot_hit_rate']:.2%})",
        f"- endpoint readiness: {summary['endpoint_ready_count']}/{summary['edge_total']} ({summary['endpoint_ready_rate']:.2%})",
        f"- edge hit: {summary['edge_hit_count']}/{summary['edge_total']} ({summary['edge_hit_rate']:.2%})",
        f"- chain hit: {summary['chain_hit_count']}/{summary['chain_total']} ({summary['chain_hit_rate']:.2%})",
        f"- route hit: {summary['route_hit_count']}/{summary['route_total']} ({summary['route_hit_rate']:.2%})",
        f"- gold alignment applied: `{summary.get('gold_alignment_applied', False)}` "
        f"({summary.get('gold_alignment_record_count', 0)} records)",
        "",
        "## Candidate Sources",
        "",
        f"- slots: `{summary['candidate_source_counts']['slots']}`",
        f"- edges: `{summary['candidate_source_counts']['edges']}`",
        "",
        "## Interpretation",
        "",
        "- `slot hit` 使用严格字符串口径：gold name/alias 必须出现在 candidate slot name/alias 中。",
        "- `endpoint readiness` 只表示一条 gold edge 的两个端点都已作为 candidate slot 出现，不表示关系成立。",
        "- `edge hit` 要求 source、target 方向和 relation type 同时命中；端点匹配会同时使用 candidate edge 文本和 linked candidate slot 的 name/aliases。",
        "- Stage 3 输出仍为候选，不是事实图谱边，也不是最终路线发现。",
        "",
    ]
    if "calibrated" in summary:
        calibrated = summary["calibrated"]
        lines.extend(
            [
                "## Calibrated Metrics",
                "",
                "这些指标只使用人工审核的 gold alignment 包进行评价侧校准；strict 指标和原始 gold 不变。",
                "",
                f"- calibrated slot hit: {calibrated['slot_hit_count']}/{calibrated['slot_total']} "
                f"({calibrated['slot_hit_rate']:.2%})",
                f"- calibrated endpoint readiness: {calibrated['endpoint_ready_count']}/{calibrated['edge_total']} "
                f"({calibrated['endpoint_ready_rate']:.2%})",
                f"- calibrated edge hit: {calibrated['edge_hit_count']}/{calibrated['edge_total']} "
                f"({calibrated['edge_hit_rate']:.2%})",
                f"- calibrated route hit: {calibrated['route_hit_count']}/{calibrated['route_total']} "
                f"({calibrated['route_hit_rate']:.2%})",
                f"- calibrated route variant hit: {calibrated['route_variant_hit_count']}/"
                f"{calibrated['route_variant_total']}",
                "",
            ]
        )
    for case in summary["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"- title: {case['title']}",
                f"- candidates: slots={case['candidate_slot_count']}, edges={case['candidate_edge_count']}",
                f"- slot hit: {case['slot_hit_count']}/{case['slot_total']}",
                f"- endpoint readiness: {case['endpoint_ready_count']}/{case['edge_total']}",
                f"- edge hit: {case['edge_hit_count']}/{case['edge_total']}",
                "",
                "| slot | stage | hit | matches |",
                "| --- | --- | --- | --- |",
            ]
        )
        for slot in case["slot_results"]:
            lines.append(
                f"| {slot['gold_name']} | {slot['evaluation_stage']} | {slot['hit']} | "
                f"{'; '.join(item['name'] for item in slot['matches']) or '-'} |"
            )
        lines.extend(["", "| edge | stage | endpoints | edge hit | matches |", "| --- | --- | --- | --- | --- |"])
        for edge in case["edge_results"]:
            gold = f"{edge['gold_source']} -{edge['gold_relation']}-> {edge['gold_target']}"
            matches = "; ".join(
                f"{item['source_name']} -{item['relation_type']}-> {item['target_name']}"
                for item in edge["matched_edges"]
            )
            lines.append(
                f"| {gold} | {edge['evaluation_stage']} | {edge['endpoint_ready']} | "
                f"{edge['edge_hit']} | {matches or '-'} |"
            )
        lines.append("")
    return "\n".join(lines)


def _load_candidates(db_path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Stage 3 DB not found: {db_path}")
    candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            """
            SELECT candidate_id, case_id, layer, name, aliases_json, source_method,
                   confidence, status
            FROM candidate_slots
            ORDER BY case_id, source_method, layer, name
            """
        ):
            item = dict(row)
            item["aliases"] = _loads_json_list(item.pop("aliases_json"))
            candidates.setdefault(str(row["case_id"]), {"slots": [], "edges": []})["slots"].append(item)
        for row in conn.execute(
            """
            SELECT candidate_edge_id, case_id, source_candidate_id, target_candidate_id,
                   source_name, source_layer, relation_type, target_name, target_layer,
                   source_method, confidence, rationale, status
            FROM candidate_edges
            ORDER BY case_id, source_method, relation_type, source_name, target_name
            """
        ):
            candidates.setdefault(str(row["case_id"]), {"slots": [], "edges": []})["edges"].append(dict(row))
    finally:
        conn.close()
    return candidates


def _candidate_source_counts(candidates: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, dict[str, int]]:
    slot_counter: Counter[str] = Counter()
    edge_counter: Counter[str] = Counter()
    for rows in candidates.values():
        slot_counter.update(str(slot.get("source_method", "")) for slot in rows["slots"])
        edge_counter.update(str(edge.get("source_method", "")) for edge in rows["edges"])
    return {"slots": dict(slot_counter), "edges": dict(edge_counter)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(value: str) -> str:
    return "".join(str(value).lower().split())


def _names_for_slot(
    slot_item: dict[str, Any],
    case_id: str = "",
    alignment: GoldAlignment | None = None,
) -> list[str]:
    names = [str(slot_item.get("name", ""))]
    names.extend(str(alias) for alias in slot_item.get("aliases", []))
    if alignment is not None:
        names.extend(alignment.aliases_for_slot(case_id, str(slot_item.get("name", ""))))
    return _dedupe_nonempty([name for name in names if len(_norm(name)) >= 2])


def _candidate_slot_matches(gold_names: list[str], candidate: dict[str, Any]) -> bool:
    terms = [str(candidate.get("name", ""))]
    terms.extend(str(alias) for alias in candidate.get("aliases", []))
    return any(_gold_in_candidate(gold_names, term) for term in terms)


def _candidate_edge_endpoint_matches(
    source_gold_names: list[str],
    target_gold_names: list[str],
    candidate_edge: dict[str, Any],
    slot_by_id: dict[str, dict[str, Any]],
    source_slot: str = "",
    target_slot: str = "",
) -> bool:
    return (
        _candidate_layer_matches_edge_slot(source_slot, endpoint_layer(candidate_edge, "source", slot_by_id))
        and _candidate_layer_matches_edge_slot(target_slot, endpoint_layer(candidate_edge, "target", slot_by_id))
        and _gold_in_any_candidate_term(source_gold_names, endpoint_terms(candidate_edge, "source", slot_by_id))
        and _gold_in_any_candidate_term(target_gold_names, endpoint_terms(candidate_edge, "target", slot_by_id))
    )


def _candidate_layer_matches_slot(slot_key: str, layer: str) -> bool:
    expected = SLOT_LAYERS.get(slot_key)
    if not expected:
        return True
    return layer in expected


def _candidate_layer_matches_edge_slot(slot_name: str, layer: str) -> bool:
    expected = EDGE_SLOT_LAYERS.get(str(slot_name))
    if not expected:
        return True
    return layer in expected


def _gold_in_candidate(gold_names: list[str], candidate_text: str) -> bool:
    candidate = _norm(candidate_text)
    if not candidate:
        return False
    return any(_norm(gold_name) in candidate for gold_name in gold_names if _norm(gold_name))


def _gold_in_any_candidate_term(gold_names: list[str], candidate_terms: list[str]) -> bool:
    return any(_gold_in_candidate(gold_names, term) for term in candidate_terms)


def _loads_json_list(value: str) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item)]


def _short_slots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": row["name"],
            "layer": row["layer"],
            "source_method": row["source_method"],
        }
        for row in rows[:5]
    ]


def _short_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_name": row["source_name"],
            "relation_type": row["relation_type"],
            "target_name": row["target_name"],
            "source_method": row["source_method"],
        }
        for row in rows[:5]
    ]


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _calibrated_case_view(
    case: dict[str, Any],
    calibrated: dict[str, Any],
    alignment: GoldAlignment,
) -> dict[str, Any]:
    case_id = str(case.get("case_id", ""))
    edge_hit_by_id = {
        str(edge.get("edge_id", "")): bool(edge.get("edge_hit"))
        for edge in calibrated.get("edge_results", [])
    }
    route_variant_results: list[dict[str, Any]] = []
    for route in case.get("gold_routes", []):
        route_id = str(route.get("route_id", ""))
        for variant in alignment.variants_for_route(case_id, route_id):
            required_edges = [str(edge_id) for edge_id in variant.get("required_gold_edge_refs", [])]
            route_variant_results.append(
                {
                    "route_id": route_id,
                    "alignment_id": variant.get("alignment_id", ""),
                    "accepted_ordered_slots": list(variant.get("accepted_ordered_slots", [])),
                    "required_gold_edge_refs": required_edges,
                    "hit": bool(required_edges) and all(edge_hit_by_id.get(edge_id, False) for edge_id in required_edges),
                    "rationale": variant.get("rationale", ""),
                }
            )
    result = {
        "slot_hit_count": calibrated["slot_hit_count"],
        "slot_total": calibrated["slot_total"],
        "endpoint_ready_count": calibrated["endpoint_ready_count"],
        "edge_hit_count": calibrated["edge_hit_count"],
        "edge_total": calibrated["edge_total"],
        "chain_hit_count": calibrated["chain_hit_count"],
        "chain_total": calibrated["chain_total"],
        "route_hit_count": calibrated["route_hit_count"],
        "route_total": calibrated["route_total"],
        "route_variant_hit_count": sum(1 for item in route_variant_results if item["hit"]),
        "route_variant_total": len(route_variant_results),
        "route_variant_results": route_variant_results,
    }
    return result


def _calibrated_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    calibrated_cases = [case["calibrated"] for case in case_results if "calibrated" in case]
    slot_hit_count = sum(case["slot_hit_count"] for case in calibrated_cases)
    slot_total = sum(case["slot_total"] for case in calibrated_cases)
    endpoint_ready_count = sum(case["endpoint_ready_count"] for case in calibrated_cases)
    edge_hit_count = sum(case["edge_hit_count"] for case in calibrated_cases)
    edge_total = sum(case["edge_total"] for case in calibrated_cases)
    chain_hit_count = sum(case["chain_hit_count"] for case in calibrated_cases)
    chain_total = sum(case["chain_total"] for case in calibrated_cases)
    route_hit_count = sum(case["route_hit_count"] for case in calibrated_cases)
    route_total = sum(case["route_total"] for case in calibrated_cases)
    route_variant_hit_count = sum(case["route_variant_hit_count"] for case in calibrated_cases)
    route_variant_total = sum(case["route_variant_total"] for case in calibrated_cases)
    return {
        "slot_hit_count": slot_hit_count,
        "slot_total": slot_total,
        "endpoint_ready_count": endpoint_ready_count,
        "edge_hit_count": edge_hit_count,
        "edge_total": edge_total,
        "chain_hit_count": chain_hit_count,
        "chain_total": chain_total,
        "route_hit_count": route_hit_count,
        "route_total": route_total,
        "route_variant_hit_count": route_variant_hit_count,
        "route_variant_total": route_variant_total,
        "slot_hit_rate": _rate(slot_hit_count, slot_total),
        "endpoint_ready_rate": _rate(endpoint_ready_count, edge_total),
        "edge_hit_rate": _rate(edge_hit_count, edge_total),
        "chain_hit_rate": _rate(chain_hit_count, chain_total),
        "route_hit_rate": _rate(route_hit_count, route_total),
        "route_variant_hit_rate": _rate(route_variant_hit_count, route_variant_total),
        "cases": calibrated_cases,
    }


def _stage_aware_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, int]] = {}
    for case in case_results:
        for edge in case.get("edge_results", []):
            stage = str(edge.get("evaluation_stage", "unspecified") or "unspecified")
            bucket = by_stage.setdefault(stage, {"edge_total": 0, "edge_hit_count": 0, "endpoint_ready_count": 0})
            bucket["edge_total"] += 1
            bucket["edge_hit_count"] += int(bool(edge.get("edge_hit")))
            bucket["endpoint_ready_count"] += int(bool(edge.get("endpoint_ready")))
    local = by_stage.get("chunk_local_extraction", {"edge_total": 0, "edge_hit_count": 0, "endpoint_ready_count": 0})
    return {
        "by_edge_stage": by_stage,
        "local_extraction_edge_total": local["edge_total"],
        "local_extraction_edge_hit_count": local["edge_hit_count"],
        "local_extraction_endpoint_ready_count": local["endpoint_ready_count"],
    }


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


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot_hit": f"{summary['slot_hit_count']}/{summary['slot_total']}",
        "endpoint_ready": f"{summary['endpoint_ready_count']}/{summary['edge_total']}",
        "edge_hit": f"{summary['edge_hit_count']}/{summary['edge_total']}",
        "chain_hit": f"{summary['chain_hit_count']}/{summary['chain_total']}",
        "route_hit": f"{summary['route_hit_count']}/{summary['route_total']}",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_STAGE3_DB))
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--gold-alignment", default=str(DEFAULT_GOLD_ALIGNMENT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
