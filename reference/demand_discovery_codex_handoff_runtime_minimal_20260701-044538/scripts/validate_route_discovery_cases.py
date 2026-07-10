"""Validate route discovery benchmark cases.

This script checks structural consistency that JSON Schema alone cannot cover
without external dependencies: local source paths, manifest splits, edge refs,
slot names, and seven-relation compatibility.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SEVEN_RELATIONS = {
    "enables",
    "drives",
    "implements",
    "has_capability",
    "applies_to",
    "constrains",
    "responsible_for",
}

SLOTS = {"principle", "technology", "capability", "application"}

SLOT_KEY = {
    "principle": "principles",
    "technology": "technologies",
    "capability": "capabilities",
    "application": "applications",
}

ROUTE_SEMANTIC_ROLES = {
    "principle_to_technology_support",
    "technology_to_capability_enablement",
    "capability_to_application_fit",
    "technology_to_application_fit",
    "principle_to_application_constraint",
    "cross_layer_relation",
}

REQUIRED_ROUTE_SLOTS = ["principle", "technology", "capability", "application"]

CASE_EVALUATION_LAYERS = {"extraction", "normalization", "candidate_edge", "route"}

SLOT_VISIBILITY = {
    "visible_chunk",
    "visible_source",
    "inferred_from_visible",
    "holdout_bridge",
    "route_target",
}

SLOT_EVALUATION_STAGES = {
    "visible_extraction",
    "normalization_candidate",
    "candidate_expansion",
    "route_assembly",
}

EDGE_EVALUATION_STAGES = {
    "chunk_local_extraction",
    "normalization_candidate",
    "cross_chunk_candidate",
    "cross_doc_candidate",
    "route_assembly",
    "hidden_bridge_validation",
}

EDGE_EVIDENCE_EXPECTATIONS = {
    "visible_same_chunk",
    "visible_cross_chunk",
    "visible_cross_doc",
    "visible_source_context",
    "inferred_from_visible",
    "holdout_bridge",
    "route_level",
}

VISIBLE_ENDPOINT_POLICIES = {
    "both_endpoints_visible",
    "source_visible",
    "target_visible",
    "one_endpoint_visible",
    "endpoints_not_required",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def is_local_path(value: str) -> bool:
    return bool(value) and not value.startswith(("http://", "https://"))


def collect_slot_names(case: dict[str, Any], slot: str) -> set[str]:
    names: set[str] = set()
    for item in case.get("gold_slots", {}).get(SLOT_KEY[slot], []):
        name = str(item.get("name", ""))
        if name:
            names.add(name)
        for alias in item.get("aliases", []):
            if alias:
                names.add(str(alias))
    return names


def source_ids_for_case(case: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for source in case.get("visible_sources", []):
        if source.get("source_id"):
            ids.add(str(source["source_id"]))
    for source in case.get("hidden_bridge_sources", []):
        if source.get("source_id"):
            ids.add(str(source["source_id"]))
    return ids


def validate_source_record(record: dict[str, Any], errors: list[str]) -> None:
    sid = record.get("source_id", "<missing-source-id>")
    if record.get("split") not in {"visible", "holdout"}:
        errors.append(f"{sid}: invalid split {record.get('split')!r}")
    for key in ("local_path", "raw_path", "html_snapshot_path", "processed_path", "original_raw_path"):
        value = record.get(key)
        if value and is_local_path(value) and not Path(value).exists():
            errors.append(f"{sid}: missing {key} {value}")
    for key in ("local_path", "raw_path", "html_snapshot_path"):
        value = record.get(key, "")
        if "data/benchmarks/route_discovery/sources" in value:
            errors.append(f"{sid}: process snapshot path used as formal {key}: {value}")


def validate_case_sources(
    case: dict[str, Any],
    manifest_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    case_id = case.get("case_id", "<missing-case-id>")
    seen_visible: set[str] = set()
    seen_holdout: set[str] = set()

    for source in case.get("visible_sources", []):
        sid = source.get("source_id")
        seen_visible.add(str(sid))
        manifest = manifest_by_id.get(str(sid))
        if not manifest:
            errors.append(f"{case_id}: visible source {sid} missing from source_manifest")
            continue
        if manifest.get("split") != "visible":
            errors.append(f"{case_id}: visible source {sid} has manifest split {manifest.get('split')}")
        for key in ("path_or_url", "raw_path", "html_snapshot_path"):
            value = source.get(key)
            if value and is_local_path(value) and not Path(value).exists():
                errors.append(f"{case_id}: visible source {sid} missing {key} {value}")

    for source in case.get("hidden_bridge_sources", []):
        sid = source.get("source_id")
        seen_holdout.add(str(sid))
        manifest = manifest_by_id.get(str(sid))
        if not manifest:
            errors.append(f"{case_id}: hidden source {sid} missing from source_manifest")
            continue
        if manifest.get("split") != "holdout":
            errors.append(f"{case_id}: hidden source {sid} has manifest split {manifest.get('split')}")
        for key in ("path_or_url", "raw_path"):
            value = source.get(key)
            if value and is_local_path(value) and not Path(value).exists():
                errors.append(f"{case_id}: hidden source {sid} missing {key} {value}")

    leaked = seen_visible & seen_holdout
    if leaked:
        errors.append(f"{case_id}: source ids appear in both visible and holdout: {sorted(leaked)}")


def validate_edges(case: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    case_id = case.get("case_id", "<missing-case-id>")
    edges: dict[str, dict[str, Any]] = {}
    slot_names = {slot: collect_slot_names(case, slot) for slot in SLOTS}

    for edge in case.get("gold_edges", []):
        edge_id = str(edge.get("edge_id", ""))
        if not edge_id:
            errors.append(f"{case_id}: gold edge missing edge_id")
            continue
        if edge_id in edges:
            errors.append(f"{case_id}: duplicate edge_id {edge_id}")
        edges[edge_id] = edge

        relation = edge.get("relation")
        if relation not in SEVEN_RELATIONS:
            errors.append(f"{case_id}/{edge_id}: relation {relation!r} is not in seven-relation schema")

        for relation_item in edge.get("acceptable_relations", []):
            if relation_item not in SEVEN_RELATIONS:
                errors.append(
                    f"{case_id}/{edge_id}: acceptable relation {relation_item!r} is not in seven-relation schema"
                )

        for key in ("source_slot", "target_slot"):
            if edge.get(key) not in SLOTS:
                errors.append(f"{case_id}/{edge_id}: invalid {key} {edge.get(key)!r}")

        source_slot = edge.get("source_slot")
        target_slot = edge.get("target_slot")
        if source_slot in SLOTS and edge.get("source_name") not in slot_names[source_slot]:
            errors.append(
                f"{case_id}/{edge_id}: source_name {edge.get('source_name')!r} not found in {source_slot} slots"
            )
        if target_slot in SLOTS and edge.get("target_name") not in slot_names[target_slot]:
            errors.append(
                f"{case_id}/{edge_id}: target_name {edge.get('target_name')!r} not found in {target_slot} slots"
            )

        role = edge.get("route_semantic_role")
        if role not in ROUTE_SEMANTIC_ROLES:
            errors.append(f"{case_id}/{edge_id}: invalid route_semantic_role {role!r}")

    return edges


def validate_evaluation_layers(case: dict[str, Any], errors: list[str]) -> None:
    case_id = case.get("case_id", "<missing-case-id>")
    layers = case.get("evaluation_layers")
    if not isinstance(layers, dict):
        errors.append(f"{case_id}: missing evaluation_layers")
        return
    missing_layers = sorted(CASE_EVALUATION_LAYERS - set(layers))
    if missing_layers:
        errors.append(f"{case_id}: evaluation_layers missing {missing_layers}")
    for layer_name, layer in layers.items():
        if layer_name not in CASE_EVALUATION_LAYERS:
            errors.append(f"{case_id}: invalid evaluation layer {layer_name!r}")
            continue
        if not isinstance(layer, dict):
            errors.append(f"{case_id}: evaluation layer {layer_name!r} must be an object")
            continue
        if not str(layer.get("description", "")).strip():
            errors.append(f"{case_id}: evaluation layer {layer_name!r} missing description")
        for stage in layer.get("slot_stages", []):
            if stage not in SLOT_EVALUATION_STAGES:
                errors.append(
                    f"{case_id}: evaluation layer {layer_name!r} invalid slot_stage {stage!r}"
                )
        for stage in layer.get("edge_stages", []):
            if stage not in EDGE_EVALUATION_STAGES:
                errors.append(
                    f"{case_id}: evaluation layer {layer_name!r} invalid edge_stage {stage!r}"
                )


def validate_slot_layers(case: dict[str, Any], errors: list[str]) -> None:
    case_id = case.get("case_id", "<missing-case-id>")
    valid_source_ids = source_ids_for_case(case)
    for slot_key in SLOT_KEY.values():
        for item in case.get("gold_slots", {}).get(slot_key, []):
            name = str(item.get("name", "<missing-slot-name>"))
            visibility = item.get("visibility")
            if visibility not in SLOT_VISIBILITY:
                errors.append(f"{case_id}: slot {name} invalid visibility {visibility!r}")
            stage = item.get("evaluation_stage")
            if stage is None:
                errors.append(f"{case_id}: slot {name} missing evaluation_stage")
            elif stage not in SLOT_EVALUATION_STAGES:
                errors.append(f"{case_id}: slot {name} invalid evaluation_stage {stage!r}")
            for source_id in item.get("evidence_source_ids", []):
                if source_id not in valid_source_ids:
                    errors.append(f"{case_id}: slot {name} unknown evidence_source_id {source_id!r}")


def validate_edge_layers(case: dict[str, Any], errors: list[str]) -> None:
    case_id = case.get("case_id", "<missing-case-id>")
    valid_source_ids = source_ids_for_case(case)
    for edge in case.get("gold_edges", []):
        edge_id = str(edge.get("edge_id", "<missing-edge-id>"))
        stage = edge.get("evaluation_stage")
        if stage is None:
            errors.append(f"{case_id}/{edge_id}: missing evaluation_stage")
        elif stage not in EDGE_EVALUATION_STAGES:
            errors.append(f"{case_id}/{edge_id}: invalid evaluation_stage {stage!r}")

        expectation = edge.get("evidence_expectation")
        if expectation not in EDGE_EVIDENCE_EXPECTATIONS:
            errors.append(f"{case_id}/{edge_id}: invalid evidence_expectation {expectation!r}")

        endpoint_policy = edge.get("visible_endpoint_policy")
        if endpoint_policy not in VISIBLE_ENDPOINT_POLICIES:
            errors.append(f"{case_id}/{edge_id}: invalid visible_endpoint_policy {endpoint_policy!r}")

        for source_id in edge.get("evidence_source_ids", []):
            if source_id not in valid_source_ids:
                errors.append(f"{case_id}/{edge_id}: unknown evidence_source_id {source_id!r}")


def validate_chains_and_routes(
    case: dict[str, Any],
    edges: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    case_id = case.get("case_id", "<missing-case-id>")

    for chain in case.get("gold_chains", []):
        chain_id = chain.get("chain_id", "<missing-chain-id>")
        for edge_id in chain.get("edge_ids", []):
            if edge_id not in edges:
                errors.append(f"{case_id}/{chain_id}: missing edge reference {edge_id}")
        for slot in chain.get("ordered_slots", []):
            if slot not in SLOTS:
                errors.append(f"{case_id}/{chain_id}: invalid ordered slot {slot!r}")

    for route in case.get("gold_routes", []):
        route_id = route.get("route_id", "<missing-route-id>")
        for edge_id in route.get("edge_ids", []):
            if edge_id not in edges:
                errors.append(f"{case_id}/{route_id}: missing edge reference {edge_id}")
        if route.get("ordered_slots") != REQUIRED_ROUTE_SLOTS:
            errors.append(f"{case_id}/{route_id}: ordered_slots must be {REQUIRED_ROUTE_SLOTS}")
        if len(route.get("ordered_nodes", [])) != len(route.get("ordered_slots", [])):
            errors.append(f"{case_id}/{route_id}: ordered_nodes length does not match ordered_slots")
        if len(route.get("display_ordered_nodes", [])) != len(route.get("ordered_slots", [])):
            errors.append(f"{case_id}/{route_id}: display_ordered_nodes length does not match ordered_slots")


def validate_cases(cases: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    manifest_by_id = {str(record.get("source_id")): record for record in sources}

    for record in sources:
        validate_source_record(record, errors)

    for case in cases:
        validate_case_sources(case, manifest_by_id, errors)
        validate_evaluation_layers(case, errors)
        validate_slot_layers(case, errors)
        edges = validate_edges(case, errors)
        validate_edge_layers(case, errors)
        validate_chains_and_routes(case, edges, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold-routes",
        type=Path,
        default=Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl"),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path("data/benchmarks/route_discovery/source_manifest_v0.jsonl"),
    )
    args = parser.parse_args()

    cases = read_jsonl(args.gold_routes)
    sources = read_jsonl(args.source_manifest)
    errors = validate_cases(cases, sources)

    print(
        json.dumps(
            {
                "case_count": len(cases),
                "source_count": len(sources),
                "error_count": len(errors),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
