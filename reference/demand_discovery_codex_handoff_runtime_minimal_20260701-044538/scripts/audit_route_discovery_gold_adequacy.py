"""Audit whether route-discovery gold labels are adequate for current scoring.

This is an evaluator/gate script. It may read gold labels and generated
candidate databases, but it must not participate in candidate generation and it
must not update gold files automatically.
"""

from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3
from typing import Any

import evaluate_stage3_route_candidates
import review_stage3_candidate_edges


DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_STAGE3_DB = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_concept_routes.sqlite"
)
DEFAULT_OUTPUT_JSON = Path("data/benchmarks/route_discovery/gold_adequacy_gate_summary.json")
DEFAULT_REPORT = Path("docs/manual-review/route_discovery_gold_adequacy_gate.md")

ROUTE_SIMILARITY_THRESHOLD = 0.55
EDGE_REVIEW_LABELS_FOR_GOLD_REVIEW = {
    "semantic_match": "alias_or_endpoint_gap",
    "near_miss_relation": "gold_relation_scope_gap",
    "near_miss_endpoint": "semantic_endpoint_gap",
}
NON_LOCAL_EDGE_STAGES = {
    "hidden_bridge_validation",
    "route_assembly",
    "cross_chunk_candidate",
    "cross_doc_candidate",
}
NON_LOCAL_EVIDENCE_EXPECTATIONS = {
    "holdout_bridge",
    "route_level",
    "inferred_from_visible",
    "visible_cross_chunk",
    "visible_cross_doc",
    "visible_source_context",
}


def main() -> int:
    args = _parse_args()
    summary = audit_gold_adequacy_from_paths(
        gold_routes=Path(args.gold_routes),
        db_path=Path(args.db),
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.gold_routes), Path(args.db)), encoding="utf-8")

    print("route_discovery_gold_adequacy_gate=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0


def audit_gold_adequacy_from_paths(gold_routes: Path, db_path: Path) -> dict[str, Any]:
    cases = _read_jsonl(gold_routes)
    return audit_gold_adequacy(cases=cases, db_path=db_path, gold_routes=gold_routes)


def audit_gold_adequacy(
    cases: list[dict[str, Any]],
    db_path: Path,
    gold_routes: Path | None = None,
) -> dict[str, Any]:
    candidates = _load_candidate_surface(db_path)
    strict_summary = evaluate_stage3_route_candidates.evaluate_stage3_candidates(cases, candidates)
    semantic_summary = review_stage3_candidate_edges.review_stage3_candidate_edges(cases, candidates)
    route_assemblies = _load_route_assemblies(db_path)

    review_queue: list[dict[str, Any]] = []
    review_queue.extend(_edge_adequacy_issues(cases, strict_summary, semantic_summary))
    review_queue.extend(_stage_policy_issues(cases))
    review_queue.extend(_route_pattern_issues(cases, strict_summary, route_assemblies))
    review_queue = _sort_review_queue(review_queue)

    issue_counts = Counter(issue["category"] for issue in review_queue)
    issue_counts.setdefault("alias_or_endpoint_gap", 0)
    issue_counts.setdefault("gold_relation_scope_gap", 0)
    issue_counts.setdefault("semantic_endpoint_gap", 0)
    issue_counts.setdefault("route_pattern_gap", 0)
    issue_counts.setdefault("stage_policy_gap", 0)

    blind_spot_categories = {
        "alias_or_endpoint_gap",
        "gold_relation_scope_gap",
        "route_pattern_gap",
        "stage_policy_gap",
    }
    strict_scores_may_understate_progress = any(issue_counts[category] for category in blind_spot_categories)

    return {
        "gold_routes": str(gold_routes or ""),
        "db_path": str(db_path),
        "gold_adequacy_status": "needs_human_review" if review_queue else "adequate_for_current_gate",
        "strict_scores_may_understate_progress": strict_scores_may_understate_progress,
        "auto_updated_gold": False,
        "case_count": len(cases),
        "strict_summary": _strict_overall(strict_summary),
        "semantic_summary": _semantic_overall(semantic_summary),
        "route_assembly_count": sum(len(rows) for rows in route_assemblies.values()),
        "review_issue_count": len(review_queue),
        "issue_counts": dict(issue_counts),
        "review_queue": review_queue,
    }


def load_candidate_surface(db_path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load base and concept candidate slots/edges for evaluation gates."""
    return _load_candidate_surface(db_path)


def render_report(summary: dict[str, Any], gold_path: Path, db_path: Path) -> str:
    lines = [
        "# Route Discovery Gold Adequacy Gate",
        "",
        "本报告检查当前 gold label 是否足以解释 strict scoring。它只产生人工审核项，不自动修改 `gold_routes_v0.jsonl`，也不参与候选生成。",
        "",
        "## Inputs",
        "",
        f"- gold routes: `{gold_path}`",
        f"- candidate DB: `{db_path}`",
        "",
        "## Summary",
        "",
        f"- status: `{summary['gold_adequacy_status']}`",
        f"- strict scores may understate progress: `{summary['strict_scores_may_understate_progress']}`",
        f"- auto updated gold: `{summary['auto_updated_gold']}`",
        f"- review issues: {summary['review_issue_count']}",
        f"- issue counts: `{summary['issue_counts']}`",
        f"- strict edge/route hit: {summary['strict_summary'].get('edge_hit_count', 0)}/"
        f"{summary['strict_summary'].get('edge_total', 0)}; "
        f"{summary['strict_summary'].get('route_hit_count', 0)}/"
        f"{summary['strict_summary'].get('route_total', 0)}",
        f"- semantic edge matches: {summary['semantic_summary'].get('semantic_edge_match_count', 0)}/"
        f"{summary['semantic_summary'].get('edge_total', 0)}",
        f"- route assemblies: {summary['route_assembly_count']}",
        "",
        "## Interpretation",
        "",
        "- `alias_or_endpoint_gap`：strict 字符串没有命中，但候选与 gold edge 有语义近邻，可能需要补 gold aliases 或补 alternate endpoint。也可能是候选过宽，必须人工判定。",
        "- `gold_relation_scope_gap`：端点接近但关系类型不在 gold acceptable_relations 内，可能是 gold 关系口径过窄，也可能是候选关系错。",
        "- `route_pattern_gap`：候选路线与 gold route 节点接近，但 strict route 口径没有给分，通常需要审核 alternate route shape 或上位概念 alias。",
        "- `stage_policy_gap`：该 gold edge 本来就不是 chunk-local direct extraction gate，不能用 direct edge miss 直接推断 prompt 或模型失败。",
        "- 所有 candidate 仍是 `unverified_candidate`；本 gate 只说明 gold/evaluator 可能有盲区，不证明候选为真。",
        "",
    ]
    if summary["review_queue"]:
        lines.extend(
            [
                "## Review Queue",
                "",
                "| category | case | gold ref | severity | candidate | action |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for issue in summary["review_queue"][:80]:
            candidate = issue.get("candidate") or {}
            if "source_name" in candidate:
                candidate_text = (
                    f"{candidate.get('source_name', '-')} -{candidate.get('relation_type', '-')}-> "
                    f"{candidate.get('target_name', '-')}"
                )
            elif "ordered_concept_names" in candidate:
                candidate_text = " -> ".join(candidate.get("ordered_concept_names", []))
            else:
                candidate_text = "-"
            lines.append(
                f"| {issue['category']} | {issue['case_id']} | {issue['gold_ref']} | "
                f"{issue['severity']} | {candidate_text} | {issue['recommended_action']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _edge_adequacy_issues(
    cases: list[dict[str, Any]],
    strict_summary: dict[str, Any],
    semantic_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    strict_edges = {
        (str(case["case_id"]), str(edge["edge_id"])): edge
        for case in strict_summary.get("cases", [])
        for edge in case.get("edge_results", [])
    }
    issues: list[dict[str, Any]] = []
    for case in semantic_summary.get("cases", []):
        case_id = str(case.get("case_id", ""))
        for review in case.get("edge_reviews", []):
            label = str(review.get("review_label", ""))
            category = EDGE_REVIEW_LABELS_FOR_GOLD_REVIEW.get(label)
            if not category:
                continue
            strict_edge = strict_edges.get((case_id, str(review.get("edge_id", ""))), {})
            if strict_edge.get("edge_hit"):
                continue
            candidate = review.get("best_candidate") or {}
            issues.append(
                {
                    "category": category,
                    "case_id": case_id,
                    "gold_ref": str(review.get("edge_id", "")),
                    "severity": "needs_human_review",
                    "rationale": _edge_issue_rationale(category, review),
                    "gold": {
                        "source": review.get("gold_source", ""),
                        "relation": review.get("gold_relation", ""),
                        "target": review.get("gold_target", ""),
                        "acceptable_relations": review.get("acceptable_relations", []),
                        "evaluation_stage": review.get("evaluation_stage", ""),
                        "evidence_expectation": review.get("evidence_expectation", ""),
                    },
                    "candidate": candidate,
                    "recommended_action": _edge_recommended_action(category),
                    "auto_update_gold": False,
                }
            )
    return issues


def _stage_policy_issues(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id", ""))
        for edge in case.get("gold_edges", []):
            stage = str(edge.get("evaluation_stage", ""))
            expectation = str(edge.get("evidence_expectation", ""))
            if stage not in NON_LOCAL_EDGE_STAGES and expectation not in NON_LOCAL_EVIDENCE_EXPECTATIONS:
                continue
            issues.append(
                {
                    "category": "stage_policy_gap",
                    "case_id": case_id,
                    "gold_ref": str(edge.get("edge_id", "")),
                    "severity": "info",
                    "rationale": (
                        f"该 gold edge 的 evaluation_stage={stage!r}, evidence_expectation={expectation!r}，"
                        "不能用 direct edge miss 直接判定 chunk 抽取失败。"
                    ),
                    "gold": {
                        "source": edge.get("source_name", ""),
                        "relation": edge.get("relation", ""),
                        "target": edge.get("target_name", ""),
                        "evaluation_stage": stage,
                        "evidence_expectation": expectation,
                    },
                    "candidate": {},
                    "recommended_action": "把该 edge 只用于对应阶段门禁；如需 direct extraction gate，另设 chunk-local gold edge。",
                    "auto_update_gold": False,
                }
            )
    return issues


def _route_pattern_issues(
    cases: list[dict[str, Any]],
    strict_summary: dict[str, Any],
    route_assemblies: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    strict_cases = {str(case["case_id"]): case for case in strict_summary.get("cases", [])}
    issues: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id", ""))
        routes = route_assemblies.get(case_id, [])
        if not routes:
            continue
        strict_case = strict_cases.get(case_id, {})
        route_hit_by_id = {
            str(route.get("route_id", "")): bool(route.get("hit"))
            for route in strict_case.get("route_results", [])
        }
        for gold_route in case.get("gold_routes", []):
            if route_hit_by_id.get(str(gold_route.get("route_id", ""))):
                continue
            best = _best_route_match(case, gold_route, routes)
            if best is None or best["score"] < ROUTE_SIMILARITY_THRESHOLD:
                continue
            issues.append(
                {
                    "category": "route_pattern_gap",
                    "case_id": case_id,
                    "gold_ref": str(gold_route.get("route_id", "")),
                    "severity": "needs_human_review",
                    "rationale": (
                        "候选路线与 gold route 节点语义接近，但 strict route hit 未给分；"
                        "可能需要补充 gold alias、alternate route shape 或修正 route evaluator。"
                    ),
                    "gold": {
                        "ordered_nodes": list(gold_route.get("ordered_nodes", [])),
                        "edge_ids": list(gold_route.get("edge_ids", [])),
                    },
                    "candidate": best["route"],
                    "route_similarity": round(float(best["score"]), 4),
                    "recommended_action": "人工审核该候选路线是否应作为 gold alternate 或 evaluator 近似命中口径。",
                    "auto_update_gold": False,
                }
            )
    return issues


def _best_route_match(
    case: dict[str, Any],
    gold_route: dict[str, Any],
    routes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    scored = [
        {
            "score": _route_similarity(case, list(gold_route.get("ordered_nodes", [])), route),
            "route": route,
        }
        for route in routes
    ]
    return max(scored, key=lambda item: item["score"], default=None)


def _route_similarity(case: dict[str, Any], gold_nodes: list[str], route: dict[str, Any]) -> float:
    candidate_nodes = list(route.get("ordered_concept_names", []))
    if not gold_nodes or not candidate_nodes:
        return 0.0
    slot_terms = _gold_slot_terms_by_name(case)
    if len(candidate_nodes) == len(gold_nodes):
        scores = [
            _name_score(slot_terms.get(str(gold), [str(gold)]), str(candidate))
            for gold, candidate in zip(gold_nodes, candidate_nodes)
        ]
        return sum(scores) / len(scores)

    best_scores: list[float] = []
    for gold in gold_nodes:
        gold_terms = slot_terms.get(str(gold), [str(gold)])
        best_scores.append(max((_name_score(gold_terms, str(candidate)) for candidate in candidate_nodes), default=0.0))
    return sum(best_scores) / len(best_scores)


def _gold_slot_terms_by_name(case: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for slot_group in ("principles", "technologies", "capabilities", "applications"):
        for slot in case.get("gold_slots", {}).get(slot_group, []):
            name = str(slot.get("name", ""))
            terms = [name]
            terms.extend(str(alias) for alias in slot.get("aliases", []))
            result[name] = [term for term in terms if _norm(term)]
    return result


def _load_candidate_surface(db_path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"candidate DB not found: {db_path}")
    candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if _table_exists(conn, "candidate_slots"):
            for row in conn.execute(
                """
                SELECT candidate_id, case_id, layer, name, aliases_json, source_method,
                       confidence, status
                FROM candidate_slots
                ORDER BY case_id, source_method, layer, name
                """
            ):
                item = dict(row)
                item["aliases"] = _loads_json_list(str(item.pop("aliases_json") or "[]"))
                candidates.setdefault(str(row["case_id"]), {"slots": [], "edges": []})["slots"].append(item)
        if _table_exists(conn, "route_concept_candidates"):
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
        if _table_exists(conn, "candidate_edges"):
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
        if _table_exists(conn, "concept_candidate_edges"):
            for row in conn.execute(
                """
                SELECT concept_edge_id, case_id, source_concept_id, target_concept_id,
                       source_name, source_layer, relation_type, target_name, target_layer,
                       source_method, confidence, rationale, status
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


def _load_route_assemblies(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    rows_by_case: dict[str, list[dict[str, Any]]] = {}
    if not db_path.exists():
        return rows_by_case
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "route_assemblies"):
            return rows_by_case
        for row in conn.execute(
            """
            SELECT route_id, case_id, route_pattern, ordered_concept_names_json,
                   concept_edge_ids_json, relation_types_json, score, source_method, status
            FROM route_assemblies
            WHERE status = 'unverified_candidate'
            ORDER BY case_id, score DESC, route_pattern, route_id
            """
        ):
            item = {
                "route_id": str(row["route_id"]),
                "case_id": str(row["case_id"]),
                "route_pattern": str(row["route_pattern"]),
                "ordered_concept_names": _loads_json_list(str(row["ordered_concept_names_json"] or "[]")),
                "concept_edge_ids": _loads_json_list(str(row["concept_edge_ids_json"] or "[]")),
                "relation_types": _loads_json_list(str(row["relation_types_json"] or "[]")),
                "score": float(row["score"] or 0.0),
                "source_method": str(row["source_method"]),
                "status": str(row["status"]),
            }
            rows_by_case.setdefault(str(row["case_id"]), []).append(item)
    finally:
        conn.close()
    return rows_by_case


def _edge_issue_rationale(category: str, review: dict[str, Any]) -> str:
    if category == "alias_or_endpoint_gap":
        return "strict 字符串没有命中，但 semantic reviewer 找到了端点和关系均接近的候选边。"
    if category == "gold_relation_scope_gap":
        return "候选端点接近，但关系类型不在 gold acceptable_relations 内，需要审核 gold 关系口径或候选关系类型。"
    return "候选至少一端接近 gold endpoint，但另一端或上位概念对齐不足，需要审核 endpoint alias/canonical。"


def _edge_recommended_action(category: str) -> str:
    if category == "alias_or_endpoint_gap":
        return "人工审核是否应补充 gold alias、alternate endpoint，或提升 evaluator 的语义端点匹配。"
    if category == "gold_relation_scope_gap":
        return "人工审核 acceptable_relations 是否过窄；不要自动接受候选关系。"
    return "人工审核候选端点是否是有效上位概念；若有效，补充 gold alias 或 endpoint policy。"


def _sort_review_queue(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "alias_or_endpoint_gap": 0,
        "route_pattern_gap": 1,
        "gold_relation_scope_gap": 2,
        "semantic_endpoint_gap": 3,
        "stage_policy_gap": 4,
    }
    return sorted(
        issues,
        key=lambda item: (
            priority.get(str(item.get("category", "")), 99),
            str(item.get("case_id", "")),
            str(item.get("gold_ref", "")),
        ),
    )


def _strict_overall(summary: dict[str, Any]) -> dict[str, Any]:
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
    }


def _semantic_overall(summary: dict[str, Any]) -> dict[str, Any]:
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


def _name_score(gold_names: list[str], candidate_text: str) -> float:
    candidate = _norm(candidate_text)
    if not candidate:
        return 0.0
    best = 0.0
    for gold_name in gold_names:
        gold = _norm(gold_name)
        if not gold:
            continue
        if gold == candidate:
            return 1.0
        if gold in candidate or candidate in gold:
            best = max(best, 0.92)
        best = max(best, SequenceMatcher(None, gold, candidate).ratio())
        best = max(best, _char_jaccard(gold, candidate))
    return best


def _char_jaccard(left: str, right: str) -> float:
    left_chars = set(left)
    right_chars = set(right)
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(value: str) -> str:
    ignored = set(" \t\r\n-_/\\|()（）[]【】{}<>《》:：;；,，.。'\"“”‘’")
    return "".join(ch for ch in str(value).lower() if ch not in ignored)


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": summary["gold_adequacy_status"],
        "strict_scores_may_understate_progress": summary["strict_scores_may_understate_progress"],
        "review_issue_count": summary["review_issue_count"],
        "issue_counts": summary["issue_counts"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--db", default=str(DEFAULT_STAGE3_DB))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
