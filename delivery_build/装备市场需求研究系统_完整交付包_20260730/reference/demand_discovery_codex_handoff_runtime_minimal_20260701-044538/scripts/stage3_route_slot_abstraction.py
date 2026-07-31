"""Generate route-level concept candidates from Stage 3 literal slots.

Stage 3.1 is a candidate-governance layer. It does not change extracted
entities, does not add fact edges, and does not read benchmark gold labels.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_4_stage2_validation"
    / "stage3_route_candidates_llm_governed.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_4_stage2_validation"
    / "stage3_route_slot_abstractions.sqlite"
)
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "experiment-artifacts" / "stage3_route_slot_abstraction_v1.md"
DEFAULT_CASE_CONTEXT = PROJECT_ROOT / "data" / "benchmarks" / "route_discovery" / "gold_routes_v0.jsonl"

STAGE3_1_VERSION = "stage3-route-slot-abstraction-v4"
ALLOWED_LAYERS = {"principle", "technology", "capability", "scenario"}
ALLOWED_ABSTRACTION_TYPES = {
    "model_generated_canonical",
    "existing_route_candidate",
    "literal_alias_group",
    "broader_route_concept",
}
ALLOWED_SUPPORT_LEVELS = {"literal_alias", "semantically_supported", "weakly_supported"}
DEFAULT_CASE_PAYLOAD_LIMIT = 220
DEFAULT_MODEL_CALL_MAX_RETRIES = 3
DEFAULT_MODEL_CALL_RETRY_SLEEP_SECONDS = 10.0


def main() -> int:
    args = _parse_args()
    concept_generator = _build_concept_generator(args)
    safe_case_context = (
        _load_safe_case_context(Path(args.case_context).expanduser().resolve())
        if args.case_context
        else {}
    )
    summary = generate_route_slot_abstractions(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        concept_generator=concept_generator,
        max_cases=args.max_cases,
        case_ids=args.case_id,
        case_payload_limit=args.case_payload_limit,
        safe_case_context_by_case=safe_case_context,
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
    )
    print("stage3_route_slot_abstraction_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def generate_route_slot_abstractions(
    input_db: Path,
    output_db: Path,
    overwrite: bool = True,
    concept_generator: Any | None = None,
    max_cases: int | None = None,
    case_ids: list[str] | None = None,
    case_payload_limit: int = DEFAULT_CASE_PAYLOAD_LIMIT,
    safe_case_context_by_case: dict[str, dict[str, Any]] | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if not input_db.exists():
        raise FileNotFoundError(f"Input Stage 3 DB not found: {input_db}")
    if output_db.exists() and overwrite:
        output_db.unlink()
    if output_db.exists():
        raise FileExistsError(f"Output DB already exists; use --force to replace: {output_db}")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_db, output_db)

    generator = concept_generator or ExistingRouteSlotConceptGenerator()
    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_stage3_1_schema(conn)
            _clear_stage3_1_tables(conn)
            selected_case_ids = _select_case_ids(conn, case_ids, max_cases)
            for case_id in selected_case_ids:
                payload = _case_payload(
                    conn,
                    case_id,
                    safe_case_context=(safe_case_context_by_case or {}).get(case_id, {}),
                    case_payload_limit=case_payload_limit,
                )
                generated = _call_with_retries(
                    lambda: generator.generate_route_concepts(payload),
                    label=f"stage3_route_slot_abstraction:{case_id}",
                )
                _insert_route_concepts(conn, case_id, generated, getattr(generator, "source_method", "llm_route_slot_abstractor"))
            _insert_run(conn, input_db, output_db, generator)
        summary = summarize_stage3_1(conn)
        summary.update(
            {
                "input_db": str(input_db),
                "output_db": str(output_db),
                "stage3_1_version": STAGE3_1_VERSION,
                "concept_generator": getattr(generator, "model", generator.__class__.__name__),
            }
        )
        if report_path is not None:
            _write_report(report_path, summary, conn)
        return summary
    finally:
        conn.close()


def ensure_stage3_1_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS route_concept_candidates (
            concept_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            abstraction_type TEXT NOT NULL,
            support_level TEXT NOT NULL,
            source_method TEXT NOT NULL,
            source_candidate_slot_ids_json TEXT NOT NULL,
            source_resolved_entity_ids_json TEXT NOT NULL,
            source_mentions_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            confidence REAL,
            rationale TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS route_concept_source_links (
            concept_id TEXT NOT NULL,
            source_candidate_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_layer TEXT NOT NULL,
            link_role TEXT NOT NULL,
            support_score REAL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (concept_id, source_candidate_id)
        );

        CREATE TABLE IF NOT EXISTS stage3_slot_abstraction_runs (
            run_id TEXT PRIMARY KEY,
            stage3_1_version TEXT NOT NULL,
            input_db TEXT NOT NULL,
            output_db TEXT NOT NULL,
            concept_generator TEXT NOT NULL,
            route_concept_count INTEGER NOT NULL,
            linked_source_slot_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_route_concepts_case_layer
            ON route_concept_candidates(case_id, layer);
        CREATE INDEX IF NOT EXISTS idx_route_concept_links_source
            ON route_concept_source_links(source_candidate_id);
        """
    )


def summarize_stage3_1(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "route_concept_count": _count(conn, "route_concept_candidates"),
        "linked_source_slot_count": _count(conn, "route_concept_source_links"),
        "isolated_route_concept_count": _count_where(
            conn,
            "route_concept_candidates",
            "json_array_length(source_candidate_slot_ids_json) = 0",
        ),
        "case_counts": _group_counts(conn, "route_concept_candidates", "case_id"),
        "layer_counts": _group_counts(conn, "route_concept_candidates", "layer"),
        "source_method_counts": _group_counts(conn, "route_concept_candidates", "source_method"),
    }


class ExistingRouteSlotConceptGenerator:
    """Promote existing LLM route slots and link them back to literal slots."""

    model = "existing-route-slot-concept-generator-v1"
    source_method = "existing_llm_route_slot"

    def __init__(self, min_link_score: float = 0.42, max_sources_per_concept: int = 8) -> None:
        self.min_link_score = min_link_score
        self.max_sources_per_concept = max_sources_per_concept

    def generate_route_concepts(self, case_payload: dict[str, object]) -> dict[str, object]:
        literal_slots = _list_dicts(case_payload.get("literal_candidate_slots"))
        existing_slots = _list_dicts(case_payload.get("existing_route_slots"))
        concepts: list[dict[str, object]] = []
        for route_slot in existing_slots:
            layer = str(route_slot.get("layer") or "").strip()
            name = str(route_slot.get("name") or "").strip()
            if layer not in ALLOWED_LAYERS or not name:
                continue
            scored_sources = [
                (self._slot_link_score(route_slot, literal_slot), literal_slot)
                for literal_slot in literal_slots
                if str(literal_slot.get("layer") or "").strip() == layer
            ]
            selected = [
                literal_slot
                for score, literal_slot in sorted(scored_sources, key=lambda item: item[0], reverse=True)
                if score >= self.min_link_score
            ][: self.max_sources_per_concept]
            if not selected:
                continue
            source_candidate_ids = [str(slot["candidate_id"]) for slot in selected]
            source_mentions = _dedupe_nonempty(
                [str(slot.get("name") or "") for slot in selected]
                + [
                    str(mention)
                    for slot in selected
                    for mention in _list_strings(slot.get("mention_names"))
                ]
            )
            concepts.append(
                {
                    "layer": layer,
                    "canonical_name": name,
                    "aliases": _list_strings(route_slot.get("aliases")),
                    "source_candidate_ids": source_candidate_ids,
                    "source_mentions": source_mentions,
                    "abstraction_type": "existing_route_candidate",
                    "support_level": "semantically_supported",
                    "confidence": route_slot.get("confidence"),
                    "rationale": "Existing LLM route candidate linked to literal canonical slots by name/alias overlap.",
                    "source_route_slot_id": route_slot.get("candidate_id"),
                }
            )
        return {"route_concepts": concepts}

    def _slot_link_score(self, route_slot: dict[str, Any], literal_slot: dict[str, Any]) -> float:
        route_terms = _slot_terms(route_slot)
        literal_terms = _slot_terms(literal_slot)
        if not route_terms or not literal_terms:
            return 0.0
        return max(_term_similarity(left, right) for left in route_terms for right in literal_terms)


class OpenAICompatibleRouteSlotAbstractor:
    model: str
    source_method = "llm_route_slot_abstractor"

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleRouteSlotAbstractor":
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from stage2_model_governance import _build_openai_compatible_client_from_stage2_env

        client = _build_openai_compatible_client_from_stage2_env()
        return cls(client=client, model=client.config.model)

    def generate_route_concepts(self, case_payload: dict[str, object]) -> dict[str, object]:
        payload = {
            "task": "Generate route-level canonical concept candidates from literal extracted slots.",
            "rules": [
                "Do not read or infer benchmark gold labels.",
                "Do not complete a four-layer route.",
                "Do not create facts or new relation assertions.",
                "Every route concept must cite at least one source_candidate_id from literal_candidate_slots or existing_route_slots.",
                "Use existing_route_slots only as unverified alias seeds or abstraction hints; do not treat them as facts, and prefer at least one literal_candidate_slots source when available.",
                "Prefer compact upper-level names useful for route reasoning.",
                "Use each literal slot's edge_neighborhood to infer route role: concepts with outgoing enables/implements/has_capability edges are often technologies or capabilities; concepts with incoming applies_to edges are often scenarios; concepts linked by drives/constrains may be principles, requirements, or constraints that explain a route.",
                "For capability concepts, prefer effects or functions that can sit between a technology and a scenario, such as prediction, correction, compensation, scheduling, cooling, robustness, sensing, quality control, or performance maintenance.",
                "For scenario concepts, identify the application target or operational problem environment, not only a dataset, test setup, measurement method, or paper topic.",
                "For scenario concepts, preserve the route-relevant object, environment, and objective when literal slots mention transmission, propagation, control, correction, compensation, measurement, evaluation, quality, robustness, or performance in a real system.",
                "Do not collapse an application target into dataset/test/reporting-only context unless all supporting slots are only dataset, test, report, bibliographic, parameter, or evaluation-method phrases.",
                "When a concept name uses slash-compressed wording, abbreviations, English variants, or paraphrased source mentions, include plain-language aliases that spell out route-relevant variants. For example, 短/长距离通信 should include 短距离通信 and 长距离通信 when both are supported.",
                "For principle concepts, prefer mechanisms, dependencies, statistical relationships, control/feedback ideas, physical effects, model assumptions, constraints, or transformation rules that explain why a technology works.",
                "For technology concepts, prefer methods, architectures, systems, algorithms, materials, devices, or implementation approaches that can enable a capability.",
                "Preserve raw literal names in source_mentions.",
                "Reject concepts that are merely broad domains such as 技术, 能力, 系统, 应用.",
                "Return JSON only.",
            ],
            "allowed_layers": sorted(ALLOWED_LAYERS),
            "allowed_abstraction_types": sorted(ALLOWED_ABSTRACTION_TYPES),
            "allowed_support_levels": sorted(ALLOWED_SUPPORT_LEVELS),
            "output_schema": {
                "route_concepts": [
                    {
                        "layer": "principle|technology|capability|scenario",
                        "canonical_name": "string",
                        "aliases": ["string"],
                        "source_candidate_ids": ["candidate slot id from literal_candidate_slots or existing_route_slots"],
                        "source_mentions": ["raw literal names"],
                        "abstraction_type": "model_generated_canonical|literal_alias_group|broader_route_concept",
                        "support_level": "literal_alias|semantically_supported|weakly_supported",
                        "confidence": 0.0,
                        "rationale": "short reason",
                    }
                ]
            },
            "case": case_payload,
        }
        result = self.client.complete_json(
            [
                {
                    "role": "system",
                    "content": "You are a conservative route slot abstraction reviewer.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        return {"route_concepts": _extract_list(result, ["route_concepts", "concepts", "route_slots"])}


def _case_payload(
    conn: sqlite3.Connection,
    case_id: str,
    safe_case_context: dict[str, Any] | None = None,
    case_payload_limit: int = DEFAULT_CASE_PAYLOAD_LIMIT,
) -> dict[str, Any]:
    literal_slots = _literal_candidate_slots(conn, case_id, case_payload_limit)
    existing_route_slots = _existing_route_slots(conn, case_id, case_payload_limit)
    candidate_edges = _candidate_edges(conn, case_id, case_payload_limit)
    _attach_edge_neighborhood(literal_slots, candidate_edges)
    _attach_edge_neighborhood(existing_route_slots, candidate_edges)
    return {
        "case_id": case_id,
        "case_task": _sanitize_case_context(safe_case_context or {}),
        "literal_candidate_slots": literal_slots,
        "existing_route_slots": existing_route_slots,
        "candidate_edges": candidate_edges,
    }


def _attach_edge_neighborhood(slots: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    slots_by_id = {str(slot.get("candidate_id") or ""): slot for slot in slots}
    for slot in slots:
        slot["edge_neighborhood"] = {"incoming": [], "outgoing": []}
    for edge in edges:
        source_id = str(edge.get("source_candidate_id") or "")
        target_id = str(edge.get("target_candidate_id") or "")
        if source_id in slots_by_id:
            outgoing = slots_by_id[source_id]["edge_neighborhood"]["outgoing"]
            outgoing.append(
                {
                    "candidate_edge_id": edge.get("candidate_edge_id"),
                    "relation_type": edge.get("relation_type"),
                    "neighbor_candidate_id": target_id,
                    "neighbor_name": edge.get("target_name"),
                    "neighbor_layer": edge.get("target_layer"),
                    "confidence": edge.get("confidence"),
                    "source_method": edge.get("source_method"),
                }
            )
        if target_id in slots_by_id:
            incoming = slots_by_id[target_id]["edge_neighborhood"]["incoming"]
            incoming.append(
                {
                    "candidate_edge_id": edge.get("candidate_edge_id"),
                    "relation_type": edge.get("relation_type"),
                    "neighbor_candidate_id": source_id,
                    "neighbor_name": edge.get("source_name"),
                    "neighbor_layer": edge.get("source_layer"),
                    "confidence": edge.get("confidence"),
                    "source_method": edge.get("source_method"),
                }
            )
    for slot in slots:
        for direction in ["incoming", "outgoing"]:
            slot["edge_neighborhood"][direction] = sorted(
                slot["edge_neighborhood"][direction],
                key=lambda item: (
                    str(item.get("relation_type") or ""),
                    str(item.get("neighbor_layer") or ""),
                    str(item.get("neighbor_name") or ""),
                ),
            )[:8]


def _literal_candidate_slots(conn: sqlite3.Connection, case_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT candidate_id, case_id, layer, name, aliases_json, source_method,
               source_resolved_entity_id, source_evidence_json, confidence, status
        FROM candidate_slots
        WHERE case_id = ?
          AND source_method = 'canonical_projection'
          AND layer IN ('principle', 'technology', 'capability', 'scenario')
        ORDER BY layer, name
        LIMIT ?
        """,
        (case_id, max(1, int(limit))),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = _slot_row_to_payload(conn, row)
        result.append(item)
    return result


def _existing_route_slots(conn: sqlite3.Connection, case_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT candidate_id, case_id, layer, name, aliases_json, source_method,
               source_resolved_entity_id, source_evidence_json, confidence, status
        FROM candidate_slots
        WHERE case_id = ?
          AND source_method = 'llm_route_candidate'
          AND layer IN ('principle', 'technology', 'capability', 'scenario')
        ORDER BY layer, name
        LIMIT ?
        """,
        (case_id, max(1, int(limit))),
    ).fetchall()
    return [_slot_row_to_payload(conn, row) for row in rows]


def _candidate_edges(conn: sqlite3.Connection, case_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT candidate_edge_id, source_candidate_id, target_candidate_id,
               source_name, source_layer, relation_type, target_name, target_layer,
               source_method, supporting_assertion_ids_json, source_evidence_json,
               confidence, rationale, status
        FROM candidate_edges
        WHERE case_id = ?
        ORDER BY source_method, relation_type, source_name, target_name
        LIMIT ?
        """,
        (case_id, max(1, int(limit))),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["supporting_assertion_ids"] = _json_list(item.pop("supporting_assertion_ids_json"))
        item["source_evidence"] = _json_object(item.pop("source_evidence_json"))
        result.append(item)
    return result


def _slot_row_to_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["aliases"] = _json_list(str(item.pop("aliases_json") or "[]"))
    item["source_evidence"] = _json_object(str(item.pop("source_evidence_json") or "{}"))
    resolved_entity_id = str(item.get("source_resolved_entity_id") or "").strip()
    item["mention_names"] = _mention_names_for_resolved_entity(conn, resolved_entity_id) if resolved_entity_id else []
    return item


def _mention_names_for_resolved_entity(conn: sqlite3.Connection, resolved_entity_id: str) -> list[str]:
    if not resolved_entity_id:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT name
        FROM entity_mentions
        WHERE resolved_entity_id = ?
        ORDER BY name
        LIMIT 20
        """,
        (resolved_entity_id,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _insert_route_concepts(
    conn: sqlite3.Connection,
    case_id: str,
    generated: dict[str, Any],
    source_method: str,
) -> None:
    source_slots = _source_slot_index(conn, case_id)
    created_at = _now()
    for raw_item in _extract_list(generated, ["route_concepts", "concepts", "route_slots"]):
        item = dict(raw_item)
        layer = str(item.get("layer") or "").strip()
        name = str(item.get("canonical_name") or item.get("name") or "").strip()
        if layer not in ALLOWED_LAYERS or not name:
            continue
        source_ids = _dedupe_nonempty(_list_strings(item.get("source_candidate_ids")))
        source_ids = [source_id for source_id in source_ids if source_id in source_slots]
        if not source_ids:
            continue
        abstraction_type = str(item.get("abstraction_type") or "model_generated_canonical").strip()
        if abstraction_type not in ALLOWED_ABSTRACTION_TYPES:
            abstraction_type = "model_generated_canonical"
        support_level = str(item.get("support_level") or "semantically_supported").strip()
        if support_level not in ALLOWED_SUPPORT_LEVELS:
            support_level = "semantically_supported"
        source_mentions = _dedupe_nonempty(
            _list_strings(item.get("source_mentions"))
            + [source_slots[source_id]["name"] for source_id in source_ids]
            + [
                mention
                for source_id in source_ids
                for mention in _list_strings(source_slots[source_id].get("mention_names"))
            ]
        )
        aliases = _dedupe_nonempty(
            _list_strings(item.get("aliases"))
            + [
                alias
                for source_id in source_ids
                for alias in _list_strings(source_slots[source_id].get("aliases"))
            ]
        )
        resolved_entity_ids = _dedupe_nonempty(
            [
                str(source_slots[source_id].get("source_resolved_entity_id") or "")
                for source_id in source_ids
            ]
        )
        concept_id = _concept_id(case_id, source_method, layer, name, source_ids)
        evidence_json = {
            "source_candidate_slots": [
                {
                    "candidate_id": source_id,
                    "name": source_slots[source_id]["name"],
                    "source_evidence": source_slots[source_id].get("source_evidence", {}),
                }
                for source_id in source_ids
            ],
        }
        if item.get("source_route_slot_id"):
            evidence_json["source_route_slot_id"] = str(item.get("source_route_slot_id"))
        conn.execute(
            """
            INSERT OR REPLACE INTO route_concept_candidates (
                concept_id, case_id, layer, canonical_name, aliases_json,
                abstraction_type, support_level, source_method,
                source_candidate_slot_ids_json, source_resolved_entity_ids_json,
                source_mentions_json, evidence_json, confidence, rationale,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                concept_id,
                case_id,
                layer,
                name,
                json.dumps(aliases, ensure_ascii=False),
                abstraction_type,
                support_level,
                source_method,
                json.dumps(source_ids, ensure_ascii=False),
                json.dumps(resolved_entity_ids, ensure_ascii=False),
                json.dumps(source_mentions, ensure_ascii=False),
                json.dumps(evidence_json, ensure_ascii=False),
                _float_or_none(item.get("confidence")),
                str(item.get("rationale") or ""),
                "unverified_candidate",
                created_at,
            ),
        )
        for source_id in source_ids:
            source_slot = source_slots[source_id]
            conn.execute(
                """
                INSERT OR REPLACE INTO route_concept_source_links (
                    concept_id, source_candidate_id, source_name, source_layer,
                    link_role, support_score, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    concept_id,
                    source_id,
                    source_slot["name"],
                    source_slot["layer"],
                    "supporting_literal_slot",
                    None,
                    json.dumps(source_slot.get("source_evidence", {}), ensure_ascii=False),
                    created_at,
                ),
            )


def _source_slot_index(conn: sqlite3.Connection, case_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT candidate_id, layer, name, aliases_json, source_resolved_entity_id,
               source_evidence_json
        FROM candidate_slots
        WHERE case_id = ?
        """,
        (case_id,),
    ).fetchall()
    result = {}
    for row in rows:
        item = _slot_row_to_payload(conn, row)
        result[str(item["candidate_id"])] = item
    return result


def _select_case_ids(conn: sqlite3.Connection, case_ids: list[str] | None, max_cases: int | None) -> list[str]:
    selected = [
        str(row["case_id"])
        for row in conn.execute("SELECT DISTINCT case_id FROM candidate_slots ORDER BY case_id").fetchall()
    ]
    if case_ids:
        requested = set(case_ids)
        selected = [case_id for case_id in selected if case_id in requested]
    if max_cases is not None:
        selected = selected[: max(0, int(max_cases))]
    return selected


def _clear_stage3_1_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM route_concept_source_links")
    conn.execute("DELETE FROM route_concept_candidates")
    conn.execute("DELETE FROM stage3_slot_abstraction_runs")


def _insert_run(conn: sqlite3.Connection, input_db: Path, output_db: Path, generator: Any) -> None:
    summary = summarize_stage3_1(conn)
    created_at = _now()
    run_id = "stage3-1-run-" + _sha1(f"{input_db}\0{output_db}\0{created_at}")[:16]
    conn.execute(
        """
        INSERT INTO stage3_slot_abstraction_runs (
            run_id, stage3_1_version, input_db, output_db, concept_generator,
            route_concept_count, linked_source_slot_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            STAGE3_1_VERSION,
            str(input_db),
            str(output_db),
            getattr(generator, "model", generator.__class__.__name__),
            summary["route_concept_count"],
            summary["linked_source_slot_count"],
            created_at,
        ),
    )


def _write_report(report_path: Path, summary: dict[str, Any], conn: sqlite3.Connection) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    examples = conn.execute(
        """
        SELECT case_id, layer, canonical_name, source_method,
               source_candidate_slot_ids_json, source_mentions_json, confidence
        FROM route_concept_candidates
        ORDER BY case_id, layer, confidence DESC, canonical_name
        LIMIT 30
        """
    ).fetchall()
    lines = [
        f"# Stage 3.1 Route Slot Abstraction ({STAGE3_1_VERSION})",
        "",
        "本报告记录从 Stage 3 字面候选槽位生成路线级上位候选概念的结果。输出仍为 `unverified_candidate`，不是事实图谱事实。",
        "",
        "## Summary",
        "",
        f"- route concepts: {summary['route_concept_count']}",
        f"- linked source slots: {summary['linked_source_slot_count']}",
        f"- isolated route concepts: {summary['isolated_route_concept_count']}",
        f"- case counts: `{summary['case_counts']}`",
        f"- layer counts: `{summary['layer_counts']}`",
        f"- source method counts: `{summary['source_method_counts']}`",
        "",
        "## Inputs",
        "",
        f"- input DB: `{summary['input_db']}`",
        f"- output DB: `{summary['output_db']}`",
        f"- generator: `{summary['concept_generator']}`",
        "",
        "## Examples",
        "",
        "| case | layer | concept | source slots | source mentions |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in examples:
        source_ids = ", ".join(_json_list(row["source_candidate_slot_ids_json"]))
        mentions = "; ".join(_json_list(row["source_mentions_json"])[:5])
        lines.append(
            f"| {row['case_id']} | {row['layer']} | {row['canonical_name']} | {source_ids} | {mentions} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 未读取 benchmark gold slots、gold edges 或 hidden sources。",
            "- 未修改 `candidate_slots`、`candidate_edges`、`resolved_entities`。",
            "- route concept 只用于后续 endpoint matching、route assembly 和人工审核排序。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_concept_generator(args: argparse.Namespace) -> Any:
    if args.concept_generator == "existing-slots":
        return ExistingRouteSlotConceptGenerator(min_link_score=args.min_link_score)
    if args.concept_generator == "llm":
        return OpenAICompatibleRouteSlotAbstractor.from_env()
    raise ValueError(f"Unsupported concept generator: {args.concept_generator}")


def _load_safe_case_context(case_context_path: Path) -> dict[str, dict[str, Any]]:
    if not case_context_path.exists():
        raise FileNotFoundError(f"Case context file not found: {case_context_path}")
    result: dict[str, dict[str, Any]] = {}
    with case_context_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                case = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{case_context_path}:{line_no}: invalid JSON: {exc}") from exc
            case_id = str(case.get("case_id") or "")
            if case_id:
                result[case_id] = _sanitize_case_context(case)
    return result


def _sanitize_case_context(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: case.get(key)
        for key in ["case_id", "title", "mode"]
        if str(case.get(key) or "").strip()
    }


def _slot_terms(slot: dict[str, Any]) -> list[str]:
    return _dedupe_nonempty(
        [str(slot.get("name") or "")]
        + _list_strings(slot.get("aliases"))
        + _list_strings(slot.get("mention_names"))
    )


def _term_similarity(left: str, right: str) -> float:
    left_norm = _norm(left)
    right_norm = _norm(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) >= 4 and (left_norm in right_norm or right_norm in left_norm):
        return 0.86
    left_shingles = _char_shingles(left_norm)
    right_shingles = _char_shingles(right_norm)
    if not left_shingles or not right_shingles:
        return 0.0
    overlap = len(left_shingles & right_shingles)
    union = len(left_shingles | right_shingles)
    return overlap / union if union else 0.0


def _char_shingles(value: str, size: int = 2) -> set[str]:
    if len(value) <= size:
        return {value}
    return {value[index : index + size] for index in range(0, len(value) - size + 1)}


def _extract_list(value: Any, keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in loaded] if isinstance(loaded, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


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


def _call_with_retries(callback: Any, label: str) -> Any:
    max_retries = max(1, int(__import__("os").getenv("STAGE3_1_MODEL_CALL_MAX_RETRIES", str(DEFAULT_MODEL_CALL_MAX_RETRIES))))
    sleep_seconds = float(
        __import__("os").getenv(
            "STAGE3_1_MODEL_CALL_RETRY_SLEEP_SECONDS",
            str(DEFAULT_MODEL_CALL_RETRY_SLEEP_SECONDS),
        )
    )
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return callback()
        except Exception as exc:  # noqa: BLE001 - external model transports raise mixed exception types.
            last_error = exc
            if attempt >= max_retries:
                break
            print(
                f"{label} failed on attempt {attempt}/{max_retries}: "
                f"{type(exc).__name__}: {exc}; retrying...",
                file=sys.stderr,
            )
            time.sleep(sleep_seconds)
    assert last_error is not None
    raise last_error


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, where_clause: str) -> int:
    return int(conn.execute(f"SELECT COUNT(1) FROM {table} WHERE {where_clause}").fetchone()[0])


def _group_counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in conn.execute(f"SELECT {column}, COUNT(1) FROM {table} GROUP BY {column} ORDER BY {column}")
    }


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _concept_id(case_id: str, source_method: str, layer: str, name: str, source_ids: list[str]) -> str:
    return "route-concept-" + _sha1(f"{case_id}\0{source_method}\0{layer}\0{name}\0{'|'.join(source_ids)}")[:18]


def _norm(value: str) -> str:
    return "".join(str(value).lower().split())


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 3.1 route-level concept candidates.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--concept-generator", choices=["existing-slots", "llm"], default="existing-slots")
    parser.add_argument("--case-id", action="append", default=[], help="Restrict to one case id. Can be repeated.")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--case-payload-limit", type=int, default=DEFAULT_CASE_PAYLOAD_LIMIT)
    parser.add_argument("--min-link-score", type=float, default=0.42)
    parser.add_argument("--case-context", default=str(DEFAULT_CASE_CONTEXT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
