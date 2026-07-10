"""Project Stage 3.1 route concepts into concept-level candidate edges and routes.

Stage 3.2 is still a candidate-governance layer. It does not create facts, does
not read benchmark gold labels, and does not call external models.
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
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_4_stage2_validation"
    / "stage3_route_slot_abstractions_llm_v4.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_4_stage2_validation"
    / "stage3_concept_routes.sqlite"
)
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "experiment-artifacts" / "stage3_2_concept_edge_projection.md"

STAGE3_2_VERSION = "stage3-concept-edge-projection-v1"
ALLOWED_RELATIONS = {
    "enables",
    "drives",
    "implements",
    "has_capability",
    "applies_to",
    "constrains",
    "responsible_for",
}
TRANSITION_RELATIONS = {
    ("principle", "technology"): {"enables", "drives", "implements", "constrains"},
    ("principle", "capability"): {"enables", "drives", "constrains"},
    ("technology", "capability"): {"enables", "implements", "has_capability"},
    ("capability", "scenario"): {"applies_to", "enables"},
}


def main() -> int:
    args = _parse_args()
    summary = generate_concept_edge_projection(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        in_place=args.in_place,
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
    )
    print("stage3_concept_edge_projection_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def generate_concept_edge_projection(
    input_db: Path,
    output_db: Path,
    overwrite: bool = True,
    in_place: bool = False,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if not input_db.exists():
        raise FileNotFoundError(f"Input Stage 3.1 DB not found: {input_db}")
    if in_place:
        db_path = input_db
    else:
        if input_db.resolve() == output_db.resolve():
            raise ValueError("Use in_place=True when input_db and output_db are the same file.")
        if output_db.exists() and overwrite:
            output_db.unlink()
        if output_db.exists():
            raise FileExistsError(f"Output DB already exists; use --force to replace: {output_db}")
        output_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_db, output_db)
        db_path = output_db

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_stage3_2_schema(conn)
            _clear_stage3_2_tables(conn)
            _project_concept_edges(conn)
            _assemble_routes(conn)
            _insert_run(conn, input_db, db_path)
        summary = summarize_stage3_2(conn)
        summary.update(
            {
                "input_db": str(input_db),
                "output_db": str(db_path),
                "stage3_2_version": STAGE3_2_VERSION,
            }
        )
        if report_path is not None:
            _write_report(report_path, summary, conn)
        return summary
    finally:
        conn.close()


def ensure_stage3_2_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS concept_candidate_edges (
            concept_edge_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            source_concept_id TEXT NOT NULL,
            target_concept_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_layer TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_layer TEXT NOT NULL,
            source_method TEXT NOT NULL,
            supporting_candidate_edge_ids_json TEXT NOT NULL,
            supporting_source_slot_ids_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            confidence REAL,
            rationale TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS route_assemblies (
            route_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            route_pattern TEXT NOT NULL,
            ordered_concept_ids_json TEXT NOT NULL,
            ordered_concept_names_json TEXT NOT NULL,
            concept_edge_ids_json TEXT NOT NULL,
            relation_types_json TEXT NOT NULL,
            score REAL,
            source_method TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stage3_concept_projection_runs (
            run_id TEXT PRIMARY KEY,
            stage3_2_version TEXT NOT NULL,
            input_db TEXT NOT NULL,
            output_db TEXT NOT NULL,
            concept_candidate_edge_count INTEGER NOT NULL,
            route_assembly_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_concept_edges_case_relation
            ON concept_candidate_edges(case_id, relation_type);
        CREATE INDEX IF NOT EXISTS idx_concept_edges_source
            ON concept_candidate_edges(source_concept_id);
        CREATE INDEX IF NOT EXISTS idx_route_assemblies_case_pattern
            ON route_assemblies(case_id, route_pattern);
        """
    )


def summarize_stage3_2(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "concept_candidate_edge_count": _count(conn, "concept_candidate_edges"),
        "route_assembly_count": _count(conn, "route_assemblies"),
        "full_four_layer_route_count": _count_where(
            conn,
            "route_assemblies",
            "json_array_length(ordered_concept_ids_json) = 4",
        ),
        "concept_edge_relation_counts": _group_counts(conn, "concept_candidate_edges", "relation_type"),
        "route_pattern_counts": _group_counts(conn, "route_assemblies", "route_pattern"),
    }


def _project_concept_edges(conn: sqlite3.Connection) -> None:
    concepts = _load_concepts(conn)
    concepts_by_id = {concept["concept_id"]: concept for concept in concepts}
    concept_ids_by_source_slot = _concept_ids_by_source_slot(conn, concepts)
    aggregates: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    rows = conn.execute(
        """
        SELECT candidate_edge_id, case_id, source_candidate_id, target_candidate_id,
               source_name, source_layer, relation_type, target_name, target_layer,
               source_method, supporting_assertion_ids_json, source_evidence_json,
               confidence, rationale
        FROM candidate_edges
        WHERE status = 'unverified_candidate'
          AND relation_type IN ('enables', 'drives', 'implements', 'has_capability',
                                'applies_to', 'constrains', 'responsible_for')
          AND COALESCE(source_candidate_id, '') != ''
          AND COALESCE(target_candidate_id, '') != ''
        ORDER BY case_id, relation_type, source_name, target_name
        """
    ).fetchall()
    for row in rows:
        source_concept_ids = concept_ids_by_source_slot.get(str(row["source_candidate_id"]), [])
        target_concept_ids = concept_ids_by_source_slot.get(str(row["target_candidate_id"]), [])
        for source_concept_id in source_concept_ids:
            for target_concept_id in target_concept_ids:
                if source_concept_id == target_concept_id:
                    continue
                source = concepts_by_id[source_concept_id]
                target = concepts_by_id[target_concept_id]
                if source["case_id"] != row["case_id"] or target["case_id"] != row["case_id"]:
                    continue
                key = (str(row["case_id"]), source_concept_id, str(row["relation_type"]), target_concept_id)
                item = aggregates.setdefault(
                    key,
                    {
                        "source": source,
                        "target": target,
                        "relation_type": str(row["relation_type"]),
                        "supporting_candidate_edge_ids": [],
                        "supporting_source_slot_ids": [],
                        "supporting_assertion_ids": [],
                        "source_evidence": [],
                        "confidence_values": [],
                    },
                )
                item["supporting_candidate_edge_ids"].append(str(row["candidate_edge_id"]))
                item["supporting_source_slot_ids"].extend(
                    [str(row["source_candidate_id"]), str(row["target_candidate_id"])]
                )
                item["supporting_assertion_ids"].extend(_json_list(row["supporting_assertion_ids_json"]))
                item["source_evidence"].append(_json_object(row["source_evidence_json"]))
                if row["confidence"] is not None:
                    item["confidence_values"].append(float(row["confidence"]))

    created_at = _now()
    for (case_id, source_concept_id, relation_type, target_concept_id), item in sorted(aggregates.items()):
        source = item["source"]
        target = item["target"]
        support_edge_ids = _dedupe_nonempty(item["supporting_candidate_edge_ids"])
        support_slot_ids = _dedupe_nonempty(item["supporting_source_slot_ids"])
        concept_edge_id = _concept_edge_id(case_id, source_concept_id, relation_type, target_concept_id)
        confidence = max(item["confidence_values"]) if item["confidence_values"] else None
        evidence_json = {
            "supporting_candidate_edges": support_edge_ids,
            "supporting_assertions": _dedupe_nonempty(item["supporting_assertion_ids"]),
            "source_evidence": item["source_evidence"],
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO concept_candidate_edges (
                concept_edge_id, case_id, source_concept_id, target_concept_id,
                source_name, source_layer, relation_type, target_name, target_layer,
                source_method, supporting_candidate_edge_ids_json,
                supporting_source_slot_ids_json, evidence_json, confidence,
                rationale, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                concept_edge_id,
                case_id,
                source_concept_id,
                target_concept_id,
                source["canonical_name"],
                source["layer"],
                relation_type,
                target["canonical_name"],
                target["layer"],
                "concept_edge_projection",
                json.dumps(support_edge_ids, ensure_ascii=False),
                json.dumps(support_slot_ids, ensure_ascii=False),
                json.dumps(evidence_json, ensure_ascii=False),
                confidence,
                "Projected from candidate_edges through route_concept_source_links.",
                "unverified_candidate",
                created_at,
            ),
        )


def _assemble_routes(conn: sqlite3.Connection) -> None:
    edges = [dict(row) for row in conn.execute("SELECT * FROM concept_candidate_edges ORDER BY case_id, source_name")]
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if _transition_allowed(edge):
            outgoing[str(edge["source_concept_id"])].append(edge)
    created_at = _now()
    inserted: set[str] = set()
    for edge_1 in edges:
        if not _transition_allowed(edge_1) or edge_1["source_layer"] not in {"principle", "technology"}:
            continue
        for edge_2 in outgoing.get(str(edge_1["target_concept_id"]), []):
            route_edges = [edge_1, edge_2]
            _insert_route(conn, route_edges, created_at, inserted)
            for edge_3 in outgoing.get(str(edge_2["target_concept_id"]), []):
                if [edge_1["source_layer"], edge_1["target_layer"], edge_2["target_layer"], edge_3["target_layer"]] != [
                    "principle",
                    "technology",
                    "capability",
                    "scenario",
                ]:
                    continue
                _insert_route(conn, [edge_1, edge_2, edge_3], created_at, inserted)
    _assemble_shared_capability_routes(conn, edges, created_at, inserted)


def _insert_route(
    conn: sqlite3.Connection,
    route_edges: list[dict[str, Any]],
    created_at: str,
    inserted: set[str],
) -> None:
    ordered_ids = [str(route_edges[0]["source_concept_id"])] + [
        str(edge["target_concept_id"]) for edge in route_edges
    ]
    ordered_names = [str(route_edges[0]["source_name"])] + [str(edge["target_name"]) for edge in route_edges]
    layers = [str(route_edges[0]["source_layer"])] + [str(edge["target_layer"]) for edge in route_edges]
    pattern = "->".join(layers)
    edge_ids = [str(edge["concept_edge_id"]) for edge in route_edges]
    route_id = _route_id(str(route_edges[0]["case_id"]), edge_ids)
    if route_id in inserted:
        return
    inserted.add(route_id)
    confidence_values = [float(edge["confidence"]) for edge in route_edges if edge.get("confidence") is not None]
    score = sum(confidence_values) / len(confidence_values) if confidence_values else None
    conn.execute(
        """
        INSERT OR REPLACE INTO route_assemblies (
            route_id, case_id, route_pattern, ordered_concept_ids_json,
            ordered_concept_names_json, concept_edge_ids_json, relation_types_json,
            score, source_method, evidence_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            route_id,
            route_edges[0]["case_id"],
            pattern,
            json.dumps(ordered_ids, ensure_ascii=False),
            json.dumps(ordered_names, ensure_ascii=False),
            json.dumps(edge_ids, ensure_ascii=False),
            json.dumps([edge["relation_type"] for edge in route_edges], ensure_ascii=False),
            score,
            "concept_route_assembly",
            json.dumps({"concept_edge_ids": edge_ids}, ensure_ascii=False),
            "unverified_candidate",
            created_at,
        ),
    )


def _assemble_shared_capability_routes(
    conn: sqlite3.Connection,
    edges: list[dict[str, Any]],
    created_at: str,
    inserted: set[str],
) -> None:
    principle_to_capability = [
        edge
        for edge in edges
        if edge["source_layer"] == "principle"
        and edge["target_layer"] == "capability"
        and edge["relation_type"] in TRANSITION_RELATIONS[("principle", "capability")]
    ]
    technology_to_capability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capability_to_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if (
            edge["source_layer"] == "technology"
            and edge["target_layer"] == "capability"
            and edge["relation_type"] in TRANSITION_RELATIONS[("technology", "capability")]
        ):
            technology_to_capability[str(edge["target_concept_id"])].append(edge)
        if (
            edge["source_layer"] == "capability"
            and edge["target_layer"] == "scenario"
            and edge["relation_type"] in TRANSITION_RELATIONS[("capability", "scenario")]
        ):
            capability_to_scenario[str(edge["source_concept_id"])].append(edge)
    for principle_edge in principle_to_capability:
        capability_id = str(principle_edge["target_concept_id"])
        for technology_edge in technology_to_capability.get(capability_id, []):
            for scenario_edge in capability_to_scenario.get(capability_id, []):
                _insert_custom_route(
                    conn=conn,
                    case_id=str(principle_edge["case_id"]),
                    route_pattern="principle+technology->capability->scenario",
                    ordered_ids=[
                        str(principle_edge["source_concept_id"]),
                        str(technology_edge["source_concept_id"]),
                        capability_id,
                        str(scenario_edge["target_concept_id"]),
                    ],
                    ordered_names=[
                        str(principle_edge["source_name"]),
                        str(technology_edge["source_name"]),
                        str(principle_edge["target_name"]),
                        str(scenario_edge["target_name"]),
                    ],
                    route_edges=[principle_edge, technology_edge, scenario_edge],
                    created_at=created_at,
                    inserted=inserted,
                )


def _insert_custom_route(
    conn: sqlite3.Connection,
    case_id: str,
    route_pattern: str,
    ordered_ids: list[str],
    ordered_names: list[str],
    route_edges: list[dict[str, Any]],
    created_at: str,
    inserted: set[str],
) -> None:
    edge_ids = [str(edge["concept_edge_id"]) for edge in route_edges]
    route_id = _route_id(case_id, edge_ids)
    if route_id in inserted:
        return
    inserted.add(route_id)
    confidence_values = [float(edge["confidence"]) for edge in route_edges if edge.get("confidence") is not None]
    score = sum(confidence_values) / len(confidence_values) if confidence_values else None
    conn.execute(
        """
        INSERT OR REPLACE INTO route_assemblies (
            route_id, case_id, route_pattern, ordered_concept_ids_json,
            ordered_concept_names_json, concept_edge_ids_json, relation_types_json,
            score, source_method, evidence_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            route_id,
            case_id,
            route_pattern,
            json.dumps(ordered_ids, ensure_ascii=False),
            json.dumps(ordered_names, ensure_ascii=False),
            json.dumps(edge_ids, ensure_ascii=False),
            json.dumps([edge["relation_type"] for edge in route_edges], ensure_ascii=False),
            score,
            "concept_route_assembly",
            json.dumps({"concept_edge_ids": edge_ids}, ensure_ascii=False),
            "unverified_candidate",
            created_at,
        ),
    )


def _load_concepts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT concept_id, case_id, layer, canonical_name, aliases_json,
                   source_candidate_slot_ids_json, confidence, status
            FROM route_concept_candidates
            WHERE status = 'unverified_candidate'
            ORDER BY case_id, layer, canonical_name
            """
        )
    ]


def _concept_ids_by_source_slot(
    conn: sqlite3.Connection,
    concepts: list[dict[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for concept in concepts:
        for source_id in _json_list(concept.get("source_candidate_slot_ids_json")):
            result[source_id].append(str(concept["concept_id"]))
    if _table_exists(conn, "route_concept_source_links"):
        rows = conn.execute(
            "SELECT concept_id, source_candidate_id FROM route_concept_source_links ORDER BY concept_id"
        ).fetchall()
        for row in rows:
            result[str(row["source_candidate_id"])].append(str(row["concept_id"]))
    return {source_id: _dedupe_nonempty(concept_ids) for source_id, concept_ids in result.items()}


def _transition_allowed(edge: dict[str, Any]) -> bool:
    return str(edge.get("relation_type") or "") in TRANSITION_RELATIONS.get(
        (str(edge.get("source_layer") or ""), str(edge.get("target_layer") or "")),
        set(),
    )


def _insert_run(conn: sqlite3.Connection, input_db: Path, output_db: Path) -> None:
    summary = summarize_stage3_2(conn)
    created_at = _now()
    run_id = "stage3-2-run-" + _sha1(f"{input_db}\0{output_db}\0{created_at}")[:16]
    conn.execute(
        """
        INSERT INTO stage3_concept_projection_runs (
            run_id, stage3_2_version, input_db, output_db,
            concept_candidate_edge_count, route_assembly_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            STAGE3_2_VERSION,
            str(input_db),
            str(output_db),
            summary["concept_candidate_edge_count"],
            summary["route_assembly_count"],
            created_at,
        ),
    )


def _clear_stage3_2_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM concept_candidate_edges")
    conn.execute("DELETE FROM route_assemblies")
    conn.execute("DELETE FROM stage3_concept_projection_runs")


def _write_report(report_path: Path, summary: dict[str, Any], conn: sqlite3.Connection) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    examples = conn.execute(
        """
        SELECT case_id, route_pattern, ordered_concept_names_json,
               relation_types_json, score
        FROM route_assemblies
        ORDER BY case_id, route_pattern DESC, score DESC
        LIMIT 20
        """
    ).fetchall()
    lines = [
        "# Stage 3.2 Concept Edge Projection",
        "",
        "本报告记录 route concept 级候选边投影与路线组装结果。输出仍为 `unverified_candidate`，不是事实图谱事实。",
        "",
        "## Summary",
        "",
        f"- concept candidate edges: {summary['concept_candidate_edge_count']}",
        f"- route assemblies: {summary['route_assembly_count']}",
        f"- full four-layer routes: {summary['full_four_layer_route_count']}",
        f"- relation counts: `{summary['concept_edge_relation_counts']}`",
        f"- route pattern counts: `{summary['route_pattern_counts']}`",
        "",
        "## Inputs",
        "",
        f"- input DB: `{summary['input_db']}`",
        f"- output DB: `{summary['output_db']}`",
        f"- version: `{summary['stage3_2_version']}`",
        "",
        "## Route Examples",
        "",
        "| case | pattern | route | relations | score |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in examples:
        route = " -> ".join(_json_list(row["ordered_concept_names_json"]))
        relations = " -> ".join(_json_list(row["relation_types_json"]))
        score = "" if row["score"] is None else f"{float(row['score']):.3f}"
        lines.append(f"| {row['case_id']} | {row['route_pattern']} | {route} | {relations} | {score} |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 未读取 benchmark gold slots、gold edges 或 hidden bridge sources。",
            "- 未调用外部模型。",
            "- 未修改 `candidate_edges` 或任何事实表。",
            "- concept edge 和 route assembly 只用于后续评价、排序和人工审核。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in loaded if str(item)] if isinstance(loaded, list) else []


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


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, where_clause: str) -> int:
    return int(conn.execute(f"SELECT COUNT(1) FROM {table} WHERE {where_clause}").fetchone()[0])


def _group_counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in conn.execute(f"SELECT {column}, COUNT(1) FROM {table} GROUP BY {column} ORDER BY {column}")
    }


def _concept_edge_id(case_id: str, source_concept_id: str, relation_type: str, target_concept_id: str) -> str:
    return "concept-edge-" + _sha1(f"{case_id}\0{source_concept_id}\0{relation_type}\0{target_concept_id}")[:18]


def _route_id(case_id: str, edge_ids: list[str]) -> str:
    return "route-assembly-" + _sha1(f"{case_id}\0{'|'.join(edge_ids)}")[:18]


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project Stage 3.1 route concepts to concept-level edges and routes.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
