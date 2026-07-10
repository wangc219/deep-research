"""Evaluate extraction output against route discovery gold cases.

This separates extraction-stage coverage from downstream candidate readiness:
visible input presence, extracted slot/entity coverage, direct local relation
hits, and candidate endpoint coverage for later route assembly.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_EXPERIMENT_DIR = Path(
    "data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided"
)

SLOT_ENTITY_TYPES = {
    "principles": {"Principle"},
    "technologies": {"Technology", "EngineeringObject"},
    "capabilities": {"Capability"},
    "applications": {"Scenario", "EngineeringObject"},
}

EDGE_SLOT_ENTITY_TYPES = {
    "principle": SLOT_ENTITY_TYPES["principles"],
    "technology": SLOT_ENTITY_TYPES["technologies"],
    "capability": SLOT_ENTITY_TYPES["capabilities"],
    "application": SLOT_ENTITY_TYPES["applications"],
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(text: str) -> str:
    return "".join(str(text).lower().split())


def names_for_slot(slot_item: dict[str, Any]) -> list[str]:
    names = [str(slot_item.get("name", ""))]
    names.extend(str(alias) for alias in slot_item.get("aliases", []))
    return [name for name in names if len(norm(name)) >= 2]


def any_name_matches(gold_names: list[str], extracted_name: str) -> bool:
    extracted = norm(extracted_name)
    if not extracted:
        return False
    for gold_name in gold_names:
        gold = norm(gold_name)
        if not gold:
            continue
        if gold in extracted:
            return True
    return False


def any_term_in_text(gold_names: list[str], text: str) -> bool:
    normalized_text = norm(text)
    if not normalized_text:
        return False
    return any(norm(gold_name) in normalized_text for gold_name in gold_names if norm(gold_name))


def source_ids_for_case(chunks: list[dict[str, Any]], case_id: str) -> set[str]:
    return {
        str(chunk.get("metadata", {}).get("source_id", ""))
        for chunk in chunks
        if chunk.get("metadata", {}).get("case_id") == case_id
    }


def load_extractions(db_path: Path, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Extraction DB not found: {db_path}")
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        has_extractions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "extractions"),
        ).fetchone()
        if not has_extractions:
            raise RuntimeError(f"Extraction DB has no extractions table: {db_path}")
        for chunk_id, status, payload_json in conn.execute(
            "SELECT chunk_id, status, payload_json FROM extractions ORDER BY id"
        ):
            if chunk_id not in chunk_by_id:
                continue
            if status in {"failed", "invalid_json"}:
                continue
            payload = json.loads(payload_json)
            payload["_status"] = status
            payload["_chunk"] = chunk_by_id[chunk_id]
            rows.append(payload)
    return rows


def entity_rows(extractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in extractions:
        chunk = result["_chunk"]
        for entity in result.get("entities", []):
            rows.append(
                {
                    "case_id": chunk.get("metadata", {}).get("case_id", ""),
                    "source_id": chunk.get("metadata", {}).get("source_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "entity_id": entity.get("entity_id", ""),
                    "name": entity.get("name", ""),
                    "entity_type": entity.get("entity_type", ""),
                }
            )
    return rows


def relation_rows(extractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in extractions:
        chunk = result["_chunk"]
        entities = {entity.get("entity_id", ""): entity for entity in result.get("entities", [])}
        for relation in result.get("relations", []):
            source = entities.get(relation.get("source_entity_id", ""), {})
            target = entities.get(relation.get("target_entity_id", ""), {})
            rows.append(
                {
                    "case_id": chunk.get("metadata", {}).get("case_id", ""),
                    "source_id": chunk.get("metadata", {}).get("source_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "relation_id": relation.get("relation_id", ""),
                    "source_name": source.get("name", ""),
                    "source_type": source.get("entity_type", ""),
                    "relation_type": relation.get("relation_type", ""),
                    "target_name": target.get("name", ""),
                    "target_type": target.get("entity_type", ""),
                    "assertion_strength": relation.get("assertion_strength", ""),
                    "inference_eligible": relation.get("inference_eligible", ""),
                    "trigger_text": relation.get("trigger_text", ""),
                }
            )
    return rows


def evaluate_case(
    case: dict[str, Any],
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    case_entities = [entity for entity in entities if entity["case_id"] == case_id]
    case_relations = [relation for relation in relations if relation["case_id"] == case_id]
    case_chunks = [
        chunk
        for chunk in (chunks or [])
        if chunk.get("metadata", {}).get("case_id") == case_id
    ]
    case_text = "\n".join(str(chunk.get("text", "")) for chunk in case_chunks)

    slot_results: dict[str, list[dict[str, Any]]] = {}
    for slot_key in ("principles", "technologies", "capabilities", "applications"):
        results: list[dict[str, Any]] = []
        for item in case.get("gold_slots", {}).get(slot_key, []):
            gold_names = names_for_slot(item)
            input_matches = [
                {
                    "source_id": chunk.get("metadata", {}).get("source_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                }
                for chunk in case_chunks
                if any_term_in_text(gold_names, str(chunk.get("text", "")))
            ]
            matches = [
                {
                    "name": entity["name"],
                    "entity_type": entity["entity_type"],
                    "source_id": entity["source_id"],
                    "chunk_id": entity["chunk_id"],
                }
                for entity in case_entities
                if any_name_matches(gold_names, entity["name"])
                and entity_type_matches_slot(slot_key, entity.get("entity_type", ""))
            ]
            input_hit = any_term_in_text(gold_names, case_text)
            hit = bool(matches)
            results.append(
                {
                    "gold_name": item.get("name", ""),
                    "visibility": item.get("visibility", "unspecified"),
                    "evaluation_stage": item.get("evaluation_stage", "unspecified"),
                    "input_hit": input_hit,
                    "input_chunks": input_matches[:5],
                    "hit": hit,
                    "diagnosis": diagnose_slot(item, input_hit=input_hit, extracted_hit=hit),
                    "matched_entities": matches[:5],
                }
            )
        slot_results[slot_key] = results

    edge_results: list[dict[str, Any]] = []
    slot_items = {
        item["name"]: item
        for items in case.get("gold_slots", {}).values()
        for item in items
    }
    for edge in case.get("gold_edges", []):
        source_names = names_for_slot(slot_items.get(edge.get("source_name", ""), {"name": edge.get("source_name", "")}))
        target_names = names_for_slot(slot_items.get(edge.get("target_name", ""), {"name": edge.get("target_name", "")}))
        input_cooccur_chunks = [
            {
                "source_id": chunk.get("metadata", {}).get("source_id", ""),
                "chunk_id": chunk.get("chunk_id", ""),
            }
            for chunk in case_chunks
            if any_term_in_text(source_names, str(chunk.get("text", "")))
            and any_term_in_text(target_names, str(chunk.get("text", "")))
        ]
        source_entity_matches = [
            entity
            for entity in case_entities
            if any_name_matches(source_names, entity["name"])
            and entity_type_matches_edge_slot(edge.get("source_slot", ""), entity.get("entity_type", ""))
        ]
        target_entity_matches = [
            entity
            for entity in case_entities
            if any_name_matches(target_names, entity["name"])
            and entity_type_matches_edge_slot(edge.get("target_slot", ""), entity.get("entity_type", ""))
        ]
        endpoint_matches = [
            relation
            for relation in case_relations
            if any_name_matches(source_names, relation["source_name"])
            and any_name_matches(target_names, relation["target_name"])
            and entity_type_matches_edge_slot(edge.get("source_slot", ""), relation.get("source_type", ""))
            and entity_type_matches_edge_slot(edge.get("target_slot", ""), relation.get("target_type", ""))
        ]
        reversed_matches = [
            relation
            for relation in case_relations
            if any_name_matches(source_names, relation["target_name"])
            and any_name_matches(target_names, relation["source_name"])
            and entity_type_matches_edge_slot(edge.get("source_slot", ""), relation.get("target_type", ""))
            and entity_type_matches_edge_slot(edge.get("target_slot", ""), relation.get("source_type", ""))
        ]
        relation_matches = [
            relation
            for relation in endpoint_matches
            if relation["relation_type"] in set(edge.get("acceptable_relations", []))
        ]
        input_endpoint_hit = bool(input_cooccur_chunks)
        candidate_endpoint_hit = bool(source_entity_matches and target_entity_matches)
        endpoint_direction_hit = bool(endpoint_matches)
        reversed_endpoint_hit = bool(reversed_matches)
        relation_hit = bool(relation_matches)
        edge_results.append(
            {
                "edge_id": edge.get("edge_id", ""),
                "evaluation_stage": edge.get("evaluation_stage", "unspecified"),
                "gold": {
                    "source": edge.get("source_name", ""),
                    "relation": edge.get("relation", ""),
                    "target": edge.get("target_name", ""),
                    "acceptable_relations": edge.get("acceptable_relations", []),
                },
                "input_endpoint_cooccur_same_chunk": input_endpoint_hit,
                "input_cooccur_chunks": input_cooccur_chunks[:5],
                "candidate_endpoint_hit": candidate_endpoint_hit,
                "source_entity_hit": bool(source_entity_matches),
                "target_entity_hit": bool(target_entity_matches),
                "source_entity_matches": source_entity_matches[:5],
                "target_entity_matches": target_entity_matches[:5],
                "endpoint_direction_hit": endpoint_direction_hit,
                "reversed_endpoint_hit": reversed_endpoint_hit,
                "relation_hit": relation_hit,
                "diagnosis": diagnose_edge(
                    edge,
                    input_endpoint_hit=input_endpoint_hit,
                    candidate_endpoint_hit=candidate_endpoint_hit,
                    endpoint_direction_hit=endpoint_direction_hit,
                    reversed_endpoint_hit=reversed_endpoint_hit,
                    relation_hit=relation_hit,
                ),
                "matched_relations": relation_matches[:5] or endpoint_matches[:5] or reversed_matches[:3],
            }
        )

    chain_results = []
    relation_hit_by_edge = {item["edge_id"]: item["relation_hit"] for item in edge_results}
    candidate_hit_by_edge = {item["edge_id"]: item["candidate_endpoint_hit"] for item in edge_results}
    for chain in case.get("gold_chains", []):
        edge_ids = list(chain.get("edge_ids", []))
        chain_results.append(
            {
                "chain_id": chain.get("chain_id", ""),
                "edge_ids": edge_ids,
                "candidate_hit": all(candidate_hit_by_edge.get(edge_id, False) for edge_id in edge_ids),
                "hit": all(relation_hit_by_edge.get(edge_id, False) for edge_id in edge_ids),
            }
        )

    route_results = []
    for route in case.get("gold_routes", []):
        edge_ids = list(route.get("edge_ids", []))
        route_results.append(
            {
                "route_id": route.get("route_id", ""),
                "edge_ids": edge_ids,
                "candidate_hit": all(candidate_hit_by_edge.get(edge_id, False) for edge_id in edge_ids),
                "hit": all(relation_hit_by_edge.get(edge_id, False) for edge_id in edge_ids),
            }
        )

    input_slot_hits = sum(1 for items in slot_results.values() for item in items if item["input_hit"])
    slot_hits = sum(1 for items in slot_results.values() for item in items if item["hit"])
    slot_total = sum(len(items) for items in slot_results.values())
    slot_stage_counts = Counter(
        item["evaluation_stage"] for items in slot_results.values() for item in items
    )
    slot_input_hit_by_stage = Counter(
        item["evaluation_stage"] for items in slot_results.values() for item in items if item["input_hit"]
    )
    slot_extracted_hit_by_stage = Counter(
        item["evaluation_stage"] for items in slot_results.values() for item in items if item["hit"]
    )
    slot_visibility_counts = Counter(
        item["visibility"] for items in slot_results.values() for item in items
    )
    slot_diagnosis_counts = Counter(
        item["diagnosis"] for items in slot_results.values() for item in items
    )
    edge_hits = sum(1 for item in edge_results if item["relation_hit"])
    endpoint_hits = sum(1 for item in edge_results if item["endpoint_direction_hit"])
    candidate_edge_hits = sum(1 for item in edge_results if item["candidate_endpoint_hit"])
    input_endpoint_hits = sum(1 for item in edge_results if item["input_endpoint_cooccur_same_chunk"])
    edge_stage_counts = Counter(item["evaluation_stage"] for item in edge_results)
    edge_relation_hit_by_stage = Counter(
        item["evaluation_stage"] for item in edge_results if item["relation_hit"]
    )
    edge_diagnosis_counts = Counter(item["diagnosis"] for item in edge_results)
    return {
        "case_id": case_id,
        "title": case.get("title", ""),
        "entity_count": len(case_entities),
        "relation_count": len(case_relations),
        "input_slot_hit_count": input_slot_hits,
        "slot_hit_count": slot_hits,
        "slot_total": slot_total,
        "input_slot_hit_rate": input_slot_hits / slot_total if slot_total else 0,
        "slot_hit_rate": slot_hits / slot_total if slot_total else 0,
        "slot_visibility_counts": dict(slot_visibility_counts),
        "slot_diagnosis_counts": dict(slot_diagnosis_counts),
        "slot_stage_counts": dict(slot_stage_counts),
        "slot_input_hit_by_stage": {
            stage: slot_input_hit_by_stage.get(stage, 0)
            for stage in slot_stage_counts
        },
        "slot_extracted_hit_by_stage": {
            stage: slot_extracted_hit_by_stage.get(stage, 0)
            for stage in slot_stage_counts
        },
        "edge_input_endpoint_hit_count": input_endpoint_hits,
        "edge_candidate_endpoint_hit_count": candidate_edge_hits,
        "edge_endpoint_hit_count": endpoint_hits,
        "edge_relation_hit_count": edge_hits,
        "edge_total": len(edge_results),
        "edge_input_endpoint_hit_rate": input_endpoint_hits / len(edge_results) if edge_results else 0,
        "edge_candidate_endpoint_hit_rate": candidate_edge_hits / len(edge_results) if edge_results else 0,
        "edge_relation_hit_rate": edge_hits / len(edge_results) if edge_results else 0,
        "edge_stage_counts": dict(edge_stage_counts),
        "edge_diagnosis_counts": dict(edge_diagnosis_counts),
        "edge_relation_hit_by_stage": {
            stage: edge_relation_hit_by_stage.get(stage, 0)
            for stage in edge_stage_counts
        },
        "slot_results": slot_results,
        "edge_results": edge_results,
        "chain_results": chain_results,
        "route_results": route_results,
        "relation_type_counts": dict(Counter(item["relation_type"] for item in case_relations)),
        "top_entities": Counter(item["name"] for item in case_entities).most_common(20),
    }


def diagnose_slot(slot_item: dict[str, Any], input_hit: bool, extracted_hit: bool) -> str:
    if extracted_hit:
        return "extracted_hit"
    if str(slot_item.get("evaluation_stage", "")) != "visible_extraction":
        return "not_extraction_stage"
    if input_hit:
        return "visible_input_present_extraction_miss"
    return "visible_input_absent"


def diagnose_edge(
    edge_item: dict[str, Any],
    input_endpoint_hit: bool,
    candidate_endpoint_hit: bool,
    endpoint_direction_hit: bool,
    reversed_endpoint_hit: bool,
    relation_hit: bool,
) -> str:
    if str(edge_item.get("evaluation_stage", "")) != "chunk_local_extraction":
        return "not_extraction_stage"
    if relation_hit:
        return "local_direct_hit"
    if not input_endpoint_hit:
        return "local_input_endpoint_absent"
    if not candidate_endpoint_hit:
        return "local_endpoint_extraction_miss"
    if reversed_endpoint_hit:
        return "local_direction_miss"
    if endpoint_direction_hit:
        return "local_relation_type_miss"
    return "local_relation_missing"


def entity_type_matches_slot(slot_key: str, entity_type: str) -> bool:
    expected = SLOT_ENTITY_TYPES.get(slot_key)
    if not expected:
        return True
    return str(entity_type) in expected


def entity_type_matches_edge_slot(slot_name: str, entity_type: str) -> bool:
    expected = EDGE_SLOT_ENTITY_TYPES.get(str(slot_name))
    if not expected:
        return True
    return str(entity_type) in expected


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Route Discovery Visible Extraction Coverage")
    lines.append("")
    lines.append("本报告拆分抽取阶段与后续路线发现阶段的指标：输入为 visible sources 的 gold-alias-guided chunks；hidden bridge sources 未进入输入。")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- chunks: {summary['chunk_count']}")
    lines.append(f"- extraction_rows: {summary['extraction_row_count']}")
    lines.append(f"- status_counts: `{summary['status_counts']}`")
    lines.append(f"- relation_type_counts: `{summary['relation_type_counts']}`")
    lines.append("")
    total_input_slot_hits = sum(case["input_slot_hit_count"] for case in summary["cases"])
    total_slot_hits = sum(case["slot_hit_count"] for case in summary["cases"])
    total_slots = sum(case["slot_total"] for case in summary["cases"])
    total_input_edge_hits = sum(case["edge_input_endpoint_hit_count"] for case in summary["cases"])
    total_candidate_edge_hits = sum(case["edge_candidate_endpoint_hit_count"] for case in summary["cases"])
    total_edge_hits = sum(case["edge_relation_hit_count"] for case in summary["cases"])
    total_edges = sum(case["edge_total"] for case in summary["cases"])
    total_slot_visibility_counts: Counter[str] = Counter()
    total_slot_stage_counts: Counter[str] = Counter()
    total_slot_input_by_stage: Counter[str] = Counter()
    total_slot_extracted_by_stage: Counter[str] = Counter()
    total_slot_diagnosis_counts: Counter[str] = Counter()
    total_stage_counts: Counter[str] = Counter()
    total_stage_hits: Counter[str] = Counter()
    total_edge_diagnosis_counts: Counter[str] = Counter()
    for case in summary["cases"]:
        total_slot_visibility_counts.update(case.get("slot_visibility_counts", {}))
        total_slot_stage_counts.update(case.get("slot_stage_counts", {}))
        total_slot_input_by_stage.update(case.get("slot_input_hit_by_stage", {}))
        total_slot_extracted_by_stage.update(case.get("slot_extracted_hit_by_stage", {}))
        total_slot_diagnosis_counts.update(case.get("slot_diagnosis_counts", {}))
        total_stage_counts.update(case.get("edge_stage_counts", {}))
        total_stage_hits.update(case.get("edge_relation_hit_by_stage", {}))
        total_edge_diagnosis_counts.update(case.get("edge_diagnosis_counts", {}))
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        f"- overall input slot presence: {total_input_slot_hits}/{total_slots} ({(total_input_slot_hits / total_slots if total_slots else 0):.2%})"
    )
    lines.append(
        f"- overall extracted slot hit: {total_slot_hits}/{total_slots} ({(total_slot_hits / total_slots if total_slots else 0):.2%})"
    )
    lines.append(f"- slot visibility counts: `{dict(total_slot_visibility_counts)}`")
    lines.append(f"- slot stage counts: `{dict(total_slot_stage_counts)}`")
    lines.append(f"- slot input hits by stage: `{dict(total_slot_input_by_stage)}`")
    lines.append(f"- slot extracted hits by stage: `{dict(total_slot_extracted_by_stage)}`")
    lines.append(f"- slot diagnosis counts: `{dict(total_slot_diagnosis_counts)}`")
    lines.append(
        f"- overall same-chunk input endpoint co-occurrence: {total_input_edge_hits}/{total_edges} ({(total_input_edge_hits / total_edges if total_edges else 0):.2%})"
    )
    lines.append(
        f"- overall candidate endpoint readiness: {total_candidate_edge_hits}/{total_edges} ({(total_candidate_edge_hits / total_edges if total_edges else 0):.2%})"
    )
    lines.append(
        f"- overall direct edge relation hit: {total_edge_hits}/{total_edges} ({(total_edge_hits / total_edges if total_edges else 0):.2%})"
    )
    lines.append(f"- edge stage counts: `{dict(total_stage_counts)}`")
    lines.append(f"- edge relation hits by stage: `{dict(total_stage_hits)}`")
    lines.append(f"- edge diagnosis counts: `{dict(total_edge_diagnosis_counts)}`")
    lines.append("- direct edge hits are intentionally strict: source endpoint, target endpoint, direction, and relation type must all match gold_edges.")
    lines.append("- candidate endpoint readiness means both gold endpoints have extracted entity matches somewhere in the visible case corpus; it is a signal for entity normalization and candidate edge generation, not a verified relation.")
    lines.append("- low same-chunk endpoint co-occurrence means direct chunk extraction should not be expected to recover those gold edges without downstream route assembly.")
    lines.append("")
    lines.append("## Case Results")
    lines.append("")
    for case in summary["cases"]:
        lines.append(f"### {case['case_id']} {case['title']}")
        lines.append("")
        lines.append(
            f"- input slot presence: {case['input_slot_hit_count']}/{case['slot_total']} ({case['input_slot_hit_rate']:.2%})"
        )
        lines.append(
            f"- extracted slot hit: {case['slot_hit_count']}/{case['slot_total']} ({case['slot_hit_rate']:.2%})"
        )
        lines.append(f"- slot visibility: `{case.get('slot_visibility_counts', {})}`")
        lines.append(f"- slot stages: `{case.get('slot_stage_counts', {})}`")
        lines.append(f"- slot input hits by stage: `{case.get('slot_input_hit_by_stage', {})}`")
        lines.append(f"- slot extracted hits by stage: `{case.get('slot_extracted_hit_by_stage', {})}`")
        lines.append(f"- slot diagnosis: `{case.get('slot_diagnosis_counts', {})}`")
        lines.append(
            f"- same-chunk input endpoint co-occurrence: {case['edge_input_endpoint_hit_count']}/{case['edge_total']} ({case['edge_input_endpoint_hit_rate']:.2%})"
        )
        lines.append(
            f"- candidate endpoint readiness: {case['edge_candidate_endpoint_hit_count']}/{case['edge_total']} ({case['edge_candidate_endpoint_hit_rate']:.2%})"
        )
        lines.append(
            f"- edge endpoint hit: {case['edge_endpoint_hit_count']}/{case['edge_total']}"
        )
        lines.append(
            f"- edge relation hit: {case['edge_relation_hit_count']}/{case['edge_total']} ({case['edge_relation_hit_rate']:.2%})"
        )
        lines.append(f"- edge stages: `{case.get('edge_stage_counts', {})}`")
        lines.append(f"- edge relation hits by stage: `{case.get('edge_relation_hit_by_stage', {})}`")
        lines.append(f"- edge diagnosis: `{case.get('edge_diagnosis_counts', {})}`")
        lines.append(f"- relation types: `{case['relation_type_counts']}`")
        lines.append("")
        lines.append("| slot | stage | visibility | gold | input hit | extracted hit | diagnosis | matched entities |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for slot, items in case["slot_results"].items():
            for item in items:
                matches = "; ".join(
                    f"{match['name']}({match['entity_type']}, {match['source_id']})"
                    for match in item["matched_entities"]
                )
                lines.append(
                    f"| {slot} | {item.get('evaluation_stage', 'unspecified')} | "
                    f"{item.get('visibility', 'unspecified')} | {item['gold_name']} | "
                    f"{item['input_hit']} | {item['hit']} | {item.get('diagnosis', '')} | {matches} |"
                )
        lines.append("")
        lines.append("| edge | stage | gold relation | input cooccur | candidate endpoints | direct relation | diagnosis | matched relation |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for edge in case["edge_results"]:
            matched = ""
            if edge["matched_relations"]:
                rel = edge["matched_relations"][0]
                matched = (
                    f"{rel['source_name']} -{rel['relation_type']}-> {rel['target_name']} "
                    f"({rel['source_id']})"
                )
            gold = edge["gold"]
            lines.append(
                f"| {edge['edge_id']} | {edge.get('evaluation_stage', 'unspecified')} | "
                f"{gold['source']} -{gold['relation']}-> {gold['target']} | "
                f"{edge['input_endpoint_cooccur_same_chunk']} | {edge['candidate_endpoint_hit']} | "
                f"{edge['relation_hit']} | {edge.get('diagnosis', '')} | {matched} |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-routes", default="data/benchmarks/route_discovery/gold_routes_v0.jsonl")
    parser.add_argument("--chunks", default=str(DEFAULT_EXPERIMENT_DIR / "chunks_visible_gold_guided.jsonl"))
    parser.add_argument("--db", default=str(DEFAULT_EXPERIMENT_DIR / "codex_gpt_5_5_visible_extractions.sqlite"))
    parser.add_argument("--output-json", default=str(DEFAULT_EXPERIMENT_DIR / "codex_gpt_5_5_gold_coverage_summary.json"))
    parser.add_argument("--report", default="docs/experiment-artifacts/route_discovery_codex_gpt_5_5_v4_3_staged_coverage.md")
    args = parser.parse_args()

    cases = read_jsonl(Path(args.gold_routes))
    chunks = read_jsonl(Path(args.chunks))
    extractions = load_extractions(Path(args.db), chunks)
    entities = entity_rows(extractions)
    relations = relation_rows(extractions)
    status_counts = Counter(result["_status"] for result in extractions)
    relation_type_counts = Counter(relation["relation_type"] for relation in relations)
    case_summaries = [evaluate_case(case, entities, relations, chunks) for case in cases]
    summary = {
        "chunk_count": len(chunks),
        "extraction_row_count": len(extractions),
        "status_counts": dict(status_counts),
        "relation_type_counts": dict(relation_type_counts),
        "cases": case_summaries,
    }

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(Path(args.report), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
