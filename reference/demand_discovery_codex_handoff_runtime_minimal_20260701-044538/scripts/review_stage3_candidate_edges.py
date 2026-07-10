"""Review Stage 3 candidate edges for semantic near matches to benchmark gold.

This is an evaluator, not a discovery step. Gold labels are allowed here because
the output is diagnostic review evidence; they must not be used by candidate
generation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3
from typing import Any

from stage3_endpoint_matching import build_slot_index, endpoint_layer, endpoint_terms


DEFAULT_STAGE3_DB = Path(
    "data/processed/extraction_experiments/stage2_entity_normalization_v1/stage3_route_candidates.sqlite"
)
DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_OUTPUT_JSON = Path(
    "data/processed/extraction_experiments/stage2_entity_normalization_v1/stage3_candidate_edge_semantic_review.json"
)
DEFAULT_REPORT = Path("docs/experiment-artifacts/stage3_candidate_edge_semantic_review.md")

SLOT_KEYS = ("principles", "technologies", "capabilities", "applications")
EDGE_SLOT_LAYERS = {
    "principle": {"principle"},
    "technology": {"technology"},
    "capability": {"capability"},
    "application": {"scenario"},
}
SEMANTIC_ENDPOINT_THRESHOLD = 0.62
SEMANTIC_AVERAGE_THRESHOLD = 0.70
PARTIAL_ENDPOINT_THRESHOLD = 0.55


def main() -> int:
    args = _parse_args()
    cases = _read_jsonl(Path(args.gold_routes))
    candidates = _load_candidates(Path(args.db))
    summary = review_stage3_candidate_edges(cases, candidates)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.db), Path(args.gold_routes)), encoding="utf-8")

    print("stage3_candidate_edge_semantic_review=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0


def review_stage3_candidate_edges(
    cases: list[dict[str, Any]],
    candidates: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    case_results = [review_case(case, candidates.get(str(case["case_id"]), {"slots": [], "edges": []})) for case in cases]
    label_counts = Counter(
        edge["review_label"] for case in case_results for edge in case["edge_reviews"]
    )
    expectation_counts = Counter(
        edge["expectation_bucket"] for case in case_results for edge in case["edge_reviews"]
    )
    return {
        "case_count": len(case_results),
        "edge_total": sum(len(case["edge_reviews"]) for case in case_results),
        "semantic_edge_match_count": label_counts.get("semantic_match", 0) + label_counts.get("strict_match", 0),
        "strict_match_count": label_counts.get("strict_match", 0),
        "relation_near_miss_count": label_counts.get("near_miss_relation", 0),
        "endpoint_near_miss_count": label_counts.get("near_miss_endpoint", 0),
        "wrong_direction_count": label_counts.get("wrong_direction_semantic", 0),
        "missing_candidate_count": label_counts.get("missing_candidate", 0),
        "label_counts": dict(label_counts),
        "expectation_counts": dict(expectation_counts),
        "cases": case_results,
    }


def review_case(case: dict[str, Any], candidate_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    slot_item_by_name = {
        item.get("name", ""): item
        for slot_key in SLOT_KEYS
        for item in case.get("gold_slots", {}).get(slot_key, [])
    }
    edges = candidate_rows.get("edges", [])
    slot_by_id = build_slot_index(candidate_rows.get("slots", []))
    edge_reviews: list[dict[str, Any]] = []
    for gold_edge in case.get("gold_edges", []):
        source_names = _names_for_slot(
            slot_item_by_name.get(gold_edge.get("source_name", ""), {"name": gold_edge.get("source_name", "")})
        )
        target_names = _names_for_slot(
            slot_item_by_name.get(gold_edge.get("target_name", ""), {"name": gold_edge.get("target_name", "")})
        )
        scored = [
            _score_candidate_edge(source_names, target_names, gold_edge, candidate, slot_by_id)
            for candidate in edges
        ]
        best = max(scored, key=lambda item: item["score"], default=None)
        label = _review_label(best, gold_edge)
        edge_reviews.append(
            {
                "edge_id": gold_edge.get("edge_id", ""),
                "evaluation_stage": gold_edge.get("evaluation_stage", "unspecified"),
                "evidence_expectation": gold_edge.get("evidence_expectation", "unspecified"),
                "expectation_bucket": _expectation_bucket(gold_edge),
                "gold_source": gold_edge.get("source_name", ""),
                "gold_relation": gold_edge.get("relation", ""),
                "gold_target": gold_edge.get("target_name", ""),
                "acceptable_relations": list(gold_edge.get("acceptable_relations", [])),
                "review_label": label,
                "best_candidate": _short_candidate(best) if best else None,
                "top_candidates": [_short_candidate(item) for item in sorted(scored, key=lambda item: item["score"], reverse=True)[:3]],
            }
        )
    return {
        "case_id": case.get("case_id", ""),
        "title": case.get("title", ""),
        "candidate_edge_count": len(edges),
        "label_counts": dict(Counter(edge["review_label"] for edge in edge_reviews)),
        "expectation_counts": dict(Counter(edge["expectation_bucket"] for edge in edge_reviews)),
        "edge_reviews": edge_reviews,
    }


def render_report(summary: dict[str, Any], db_path: Path, gold_path: Path) -> str:
    lines = [
        "# Stage 3 Candidate Edge Semantic Review",
        "",
        "本报告只做评价和诊断：gold labels 没有参与候选生成。`semantic_match` 不等于事实成立，只表示候选边与 gold edge 在端点和关系上达到语义近似，需要后续证据审核。",
        "",
        "## Inputs",
        "",
        f"- candidate DB: `{db_path}`",
        f"- gold routes: `{gold_path}`",
        "",
        "## Summary",
        "",
        f"- edge total: {summary['edge_total']}",
        f"- label counts: `{summary['label_counts']}`",
        f"- expectation buckets: `{summary['expectation_counts']}`",
        "",
        "## Interpretation",
        "",
        "- `strict_match`: 严格字符串端点和关系类型均命中。",
        "- `semantic_match`: 严格字符串没命中，但端点语义近似且关系类型在 acceptable_relations 中；端点评分会同时使用 candidate edge 文本和 linked candidate slot 的 name/aliases。",
        "- `near_miss_relation`: 端点近似，但关系类型不在 acceptable_relations 中。",
        "- `near_miss_endpoint`: 至少一端接近，但另一端或方向不够稳定。",
        "- `missing_candidate`: Stage 3 候选里没有足够接近的边。",
        "- `not_discoverable_without_holdout` 的 gold edge 不应被当作 visible-only 抽取失败。",
        "",
    ]
    for case in summary["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"- title: {case['title']}",
                f"- candidate edges: {case['candidate_edge_count']}",
                f"- label counts: `{case['label_counts']}`",
                f"- expectation counts: `{case['expectation_counts']}`",
                "",
                "| edge | bucket | label | best candidate | scores |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for edge in case["edge_reviews"]:
            best = edge.get("best_candidate") or {}
            candidate_text = (
                f"{best.get('source_name', '-')} -{best.get('relation_type', '-')}-> "
                f"{best.get('target_name', '-')}"
                if best
                else "-"
            )
            score_text = (
                f"source={best.get('source_score', 0):.2f}, "
                f"target={best.get('target_score', 0):.2f}, "
                f"score={best.get('score', 0):.2f}"
                if best
                else "-"
            )
            gold = f"{edge['gold_source']} -{edge['gold_relation']}-> {edge['gold_target']}"
            lines.append(
                f"| {edge['edge_id']}: {gold} | {edge['expectation_bucket']} | "
                f"{edge['review_label']} | {candidate_text} | {score_text} |"
            )
        lines.append("")
    return "\n".join(lines)


def _score_candidate_edge(
    source_gold_names: list[str],
    target_gold_names: list[str],
    gold_edge: dict[str, Any],
    candidate: dict[str, Any],
    slot_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_terms = endpoint_terms(candidate, "source", slot_by_id)
    target_terms = endpoint_terms(candidate, "target", slot_by_id)
    forward_source = _name_score_many(source_gold_names, source_terms)
    forward_target = _name_score_many(target_gold_names, target_terms)
    reversed_source = _name_score_many(source_gold_names, target_terms)
    reversed_target = _name_score_many(target_gold_names, source_terms)

    forward_score = _edge_score(forward_source, forward_target)
    reversed_score = _edge_score(reversed_source, reversed_target)
    direction = "forward" if forward_score >= reversed_score else "reversed"
    forward_layer_ok = _candidate_layers_match(
        str(gold_edge.get("source_slot", "")),
        endpoint_layer(candidate, "source", slot_by_id),
        str(gold_edge.get("target_slot", "")),
        endpoint_layer(candidate, "target", slot_by_id),
    )
    reversed_layer_ok = _candidate_layers_match(
        str(gold_edge.get("source_slot", "")),
        endpoint_layer(candidate, "target", slot_by_id),
        str(gold_edge.get("target_slot", "")),
        endpoint_layer(candidate, "source", slot_by_id),
    )
    layer_ok = forward_layer_ok if direction == "forward" else reversed_layer_ok
    source_score = forward_source if direction == "forward" else reversed_source
    target_score = forward_target if direction == "forward" else reversed_target
    relation_ok = candidate.get("relation_type") in set(gold_edge.get("acceptable_relations", []))
    relation_bonus = 0.08 if relation_ok else 0.0
    score = max(forward_score, reversed_score) + relation_bonus
    return {
        "candidate": candidate,
        "direction": direction,
        "source_score": source_score,
        "target_score": target_score,
        "endpoint_average": (source_score + target_score) / 2,
        "endpoint_min": min(source_score, target_score),
        "layer_ok": layer_ok,
        "relation_ok": relation_ok,
        "strict_endpoint_match": _strict_endpoint_match(
            direction,
            source_gold_names,
            target_gold_names,
            source_terms,
            target_terms,
        ),
        "score": score,
    }


def _review_label(best: dict[str, Any] | None, gold_edge: dict[str, Any]) -> str:
    if best is None:
        return "missing_candidate"
    if best["strict_endpoint_match"] and best["relation_ok"] and best["direction"] == "forward" and best["layer_ok"]:
        return "strict_match"
    if (
        best["direction"] == "reversed"
        and best["endpoint_min"] >= SEMANTIC_ENDPOINT_THRESHOLD
        and best["relation_ok"]
        and best["layer_ok"]
    ):
        return "wrong_direction_semantic"
    if (
        best["endpoint_min"] >= SEMANTIC_ENDPOINT_THRESHOLD
        and best["endpoint_average"] >= SEMANTIC_AVERAGE_THRESHOLD
        and best["relation_ok"]
        and best["layer_ok"]
    ):
        return "semantic_match"
    if (
        best["endpoint_min"] >= SEMANTIC_ENDPOINT_THRESHOLD
        and best["endpoint_average"] >= SEMANTIC_AVERAGE_THRESHOLD
        and not best["relation_ok"]
        and best["layer_ok"]
    ):
        return "near_miss_relation"
    if max(best["source_score"], best["target_score"]) >= PARTIAL_ENDPOINT_THRESHOLD:
        return "near_miss_endpoint"
    return "missing_candidate"


def _expectation_bucket(edge: dict[str, Any]) -> str:
    stage = str(edge.get("evaluation_stage", ""))
    expectation = str(edge.get("evidence_expectation", ""))
    if expectation == "holdout_bridge" or stage == "hidden_bridge_validation":
        return "not_discoverable_without_holdout"
    if stage == "chunk_local_extraction":
        return "local_extraction_gate"
    if stage in {"cross_chunk_candidate", "cross_doc_candidate"}:
        return "candidate_generation_gate"
    if stage == "route_assembly":
        return "route_assembly_gate"
    return "unspecified"


def _edge_score(source_score: float, target_score: float) -> float:
    return min(source_score, target_score) * 0.6 + ((source_score + target_score) / 2) * 0.4


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


def _name_score_many(gold_names: list[str], candidate_terms: list[str]) -> float:
    return max((_name_score(gold_names, term) for term in candidate_terms), default=0.0)


def _strict_endpoint_match(
    direction: str,
    source_gold_names: list[str],
    target_gold_names: list[str],
    source_terms: list[str],
    target_terms: list[str],
) -> bool:
    if direction == "reversed":
        return _gold_in_any_candidate_term(source_gold_names, target_terms) and _gold_in_any_candidate_term(
            target_gold_names,
            source_terms,
        )
    return _gold_in_any_candidate_term(source_gold_names, source_terms) and _gold_in_any_candidate_term(
        target_gold_names,
        target_terms,
    )


def _char_jaccard(left: str, right: str) -> float:
    left_chars = set(left)
    right_chars = set(right)
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


def _names_for_slot(slot_item: dict[str, Any]) -> list[str]:
    names = [str(slot_item.get("name", ""))]
    names.extend(str(alias) for alias in slot_item.get("aliases", []))
    return [name for name in names if len(_norm(name)) >= 2]


def _gold_in_candidate(gold_names: list[str], candidate_text: str) -> bool:
    candidate = _norm(candidate_text)
    return bool(candidate) and any(_norm(gold_name) in candidate for gold_name in gold_names if _norm(gold_name))


def _gold_in_any_candidate_term(gold_names: list[str], candidate_terms: list[str]) -> bool:
    return any(_gold_in_candidate(gold_names, term) for term in candidate_terms)


def _short_candidate(scored: dict[str, Any]) -> dict[str, Any]:
    candidate = scored["candidate"]
    return {
        "source_name": candidate.get("source_name", ""),
        "relation_type": candidate.get("relation_type", ""),
        "target_name": candidate.get("target_name", ""),
        "source_method": candidate.get("source_method", ""),
        "direction": scored["direction"],
        "source_score": round(float(scored["source_score"]), 4),
        "target_score": round(float(scored["target_score"]), 4),
        "endpoint_average": round(float(scored["endpoint_average"]), 4),
        "layer_ok": bool(scored["layer_ok"]),
        "relation_ok": bool(scored["relation_ok"]),
        "score": round(float(scored["score"]), 4),
    }


def _candidate_layers_match(
    source_slot: str,
    source_layer: str,
    target_slot: str,
    target_layer: str,
) -> bool:
    return _layer_matches_slot(source_slot, source_layer) and _layer_matches_slot(target_slot, target_layer)


def _layer_matches_slot(slot_name: str, layer: str) -> bool:
    expected = EDGE_SLOT_LAYERS.get(slot_name)
    if not expected:
        return True
    return layer in expected


def _load_candidates(db_path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Stage 3 DB not found: {db_path}")
    candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with sqlite3.connect(db_path) as conn:
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
    return candidates


def _loads_json_list(value: str) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm(value: str) -> str:
    ignored = set(" \t\r\n-_/\\|()（）[]【】{}<>《》:：;；,，.。'\"“”‘’")
    return "".join(ch for ch in str(value).lower() if ch not in ignored)


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_total": summary["edge_total"],
        "label_counts": summary["label_counts"],
        "semantic_edge_match_count": summary["semantic_edge_match_count"],
        "expectation_counts": summary["expectation_counts"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_STAGE3_DB))
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
