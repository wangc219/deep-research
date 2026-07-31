"""Generate unverified route candidate slots and edges from merged Stage 2 data."""

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
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.governance.entity_path_policy import (  # noqa: E402
    POLICY_VERSION as ENTITY_PATH_POLICY_VERSION,
    classify_entity_path_policy,
)

DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage2_entity_merged.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage3_route_candidates.sqlite"
)
DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_3_gold_guided"
    / "chunks_visible_gold_guided.jsonl"
)
DEFAULT_CASE_CONTEXT = PROJECT_ROOT / "data" / "benchmarks" / "route_discovery" / "gold_routes_v0.jsonl"

STAGE3_VERSION = "stage3-route-candidate-generation-v1"
DEFAULT_STAGE3_MODEL_CALL_MAX_RETRIES = 3
DEFAULT_STAGE3_MODEL_CALL_RETRY_SLEEP_SECONDS = 10.0
DEFAULT_CHUNK_CONTEXT_CHARS = 1800
DEFAULT_CASE_PAYLOAD_LIMIT = 30

TYPE_TO_LAYER = {
    "Principle": "principle",
    "Mechanism": "principle",
    "Technology": "technology",
    "EngineeringObject": "technology",
    "Capability": "capability",
    "Scenario": "scenario",
    "Application": "scenario",
    "RequirementGap": "requirement",
    "Constraint": "constraint",
    "Metric": "metric",
    "Source": "source",
}


def main() -> int:
    args = _parse_args()
    llm_generator = _build_llm_generator(args)
    summary = generate_route_candidates(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        llm_generator=llm_generator,
        max_llm_cases=args.max_llm_cases,
        llm_case_ids=args.llm_case_id,
        chunks_path=Path(args.chunks).expanduser().resolve() if args.chunks else None,
        chunk_context_chars=args.chunk_context_chars,
        case_payload_limit=args.case_payload_limit,
        case_context_path=Path(args.case_context).expanduser().resolve() if args.case_context else None,
        append=args.append,
    )
    print("stage3_route_candidate_generation_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def generate_route_candidates(
    input_db: Path,
    output_db: Path,
    overwrite: bool = True,
    llm_generator: Any | None = None,
    max_llm_cases: int | None = None,
    llm_case_ids: list[str] | None = None,
    chunks_path: Path | None = None,
    chunk_context_chars: int = DEFAULT_CHUNK_CONTEXT_CHARS,
    case_payload_limit: int = DEFAULT_CASE_PAYLOAD_LIMIT,
    case_context_path: Path | None = None,
    append: bool = False,
) -> dict[str, Any]:
    if not input_db.exists():
        raise FileNotFoundError(f"Input merged Stage 2 DB not found: {input_db}")
    if append:
        if not output_db.exists():
            raise FileNotFoundError(f"Output DB not found for append mode: {output_db}")
    elif output_db.exists() and overwrite:
        output_db.unlink()
    if output_db.exists() and not append:
        raise FileExistsError(f"Output DB already exists; use --force to replace: {output_db}")
    if not append:
        output_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_db, output_db)

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_stage3_schema(conn)
            _project_canonical_slots(conn)
            _project_path_safe_edges(conn)
        chunk_context_by_case = (
            _load_visible_chunk_context(chunks_path, chunk_context_chars)
            if chunks_path is not None
            else {}
        )
        safe_case_context_by_case = (
            _load_safe_case_context(case_context_path)
            if case_context_path is not None
            else {}
        )
        if llm_generator is not None:
            _generate_llm_candidates(
                conn,
                llm_generator,
                max_llm_cases,
                chunk_context_by_case,
                safe_case_context_by_case,
                llm_case_ids=llm_case_ids,
                case_payload_limit=case_payload_limit,
            )
        with conn:
            _insert_run(conn, input_db, output_db, llm_generator)
        summary = summarize_stage3(conn)
        summary.update(
            {
                "input_db": str(input_db),
                "output_db": str(output_db),
                "stage3_version": STAGE3_VERSION,
                "llm_model": getattr(llm_generator, "model", "none") if llm_generator is not None else "none",
                "chunk_context_case_count": len(chunk_context_by_case),
                "chunks_path": str(chunks_path) if chunks_path is not None else "",
                "safe_case_context_count": len(safe_case_context_by_case),
                "case_context_path": str(case_context_path) if case_context_path is not None else "",
            }
        )
        return summary
    finally:
        conn.close()


def ensure_stage3_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS candidate_slots (
            candidate_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            source_method TEXT NOT NULL,
            source_resolved_entity_id TEXT,
            source_evidence_json TEXT NOT NULL,
            confidence REAL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_edges (
            candidate_edge_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            source_candidate_id TEXT,
            target_candidate_id TEXT,
            source_name TEXT NOT NULL,
            source_layer TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_layer TEXT NOT NULL,
            source_method TEXT NOT NULL,
            supporting_assertion_ids_json TEXT NOT NULL,
            source_evidence_json TEXT NOT NULL,
            confidence REAL,
            source_weight_multiplier REAL NOT NULL DEFAULT 1.0,
            target_weight_multiplier REAL NOT NULL DEFAULT 1.0,
            edge_weight REAL,
            path_eligibility TEXT NOT NULL DEFAULT 'path_safe',
            governance_flags_json TEXT NOT NULL DEFAULT '[]',
            rationale TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entity_governance_annotations (
            resolved_entity_id TEXT PRIMARY KEY,
            path_eligibility TEXT NOT NULL,
            weight_multiplier REAL NOT NULL,
            granularity_label TEXT NOT NULL,
            governance_reason TEXT NOT NULL,
            governance_source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stage3_route_candidate_runs (
            run_id TEXT PRIMARY KEY,
            stage3_version TEXT NOT NULL,
            input_db TEXT NOT NULL,
            output_db TEXT NOT NULL,
            llm_model TEXT NOT NULL,
            candidate_slot_count INTEGER NOT NULL,
            candidate_edge_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_slots_case_layer
            ON candidate_slots(case_id, layer);
        CREATE INDEX IF NOT EXISTS idx_candidate_edges_case_relation
            ON candidate_edges(case_id, relation_type);
        """
    )
    _ensure_column(conn, "candidate_edges", "source_weight_multiplier", "REAL NOT NULL DEFAULT 1.0")
    _ensure_column(conn, "candidate_edges", "target_weight_multiplier", "REAL NOT NULL DEFAULT 1.0")
    _ensure_column(conn, "candidate_edges", "edge_weight", "REAL")
    _ensure_column(conn, "candidate_edges", "path_eligibility", "TEXT NOT NULL DEFAULT 'path_safe'")
    _ensure_column(conn, "candidate_edges", "governance_flags_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_entity_governance_annotations(conn)


def summarize_stage3(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "candidate_slot_count": _count(conn, "candidate_slots"),
        "candidate_edge_count": _count(conn, "candidate_edges"),
        "projected_candidate_slot_count": _count_where(conn, "candidate_slots", "source_method = 'canonical_projection'"),
        "llm_candidate_slot_count": _count_where(conn, "candidate_slots", "source_method = 'llm_route_candidate'"),
        "projected_candidate_edge_count": _count_where(conn, "candidate_edges", "source_method = 'path_safe_relation_projection'"),
        "llm_candidate_edge_count": _count_where(conn, "candidate_edges", "source_method = 'llm_route_candidate'"),
    }


def _project_canonical_slots(conn: sqlite3.Connection) -> None:
    created_at = _now()
    rows = conn.execute(
        """
        SELECT re.resolved_entity_id, re.canonical_name, re.canonical_type,
               re.canonical_layer, re.alias_json, re.entity_status,
               em.chunk_id
        FROM resolved_entities re
        JOIN entity_mentions em ON re.resolved_entity_id = em.resolved_entity_id
        WHERE re.entity_status = 'active'
        GROUP BY re.resolved_entity_id, em.chunk_id
        """
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        case_id = _case_id_from_chunk(str(row["chunk_id"]))
        if not case_id:
            continue
        layer = str(row["canonical_layer"] or TYPE_TO_LAYER.get(str(row["canonical_type"]), "unknown"))
        if layer in {"source", "metric", "constraint", "requirement", "unknown"}:
            # Constraints and requirements are useful context, but not route slots
            # until a later candidate role classifier promotes them.
            continue
        candidate_id = _slot_id(case_id, str(row["resolved_entity_id"]), "canonical_projection")
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        conn.execute(
            """
            INSERT OR REPLACE INTO candidate_slots (
                candidate_id, case_id, layer, name, aliases_json, source_method,
                source_resolved_entity_id, source_evidence_json, confidence,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                case_id,
                layer,
                row["canonical_name"],
                row["alias_json"] or "[]",
                "canonical_projection",
                row["resolved_entity_id"],
                json.dumps({"chunk_id": row["chunk_id"]}, ensure_ascii=False),
                None,
                "unverified_candidate",
                created_at,
            ),
        )


def _project_path_safe_edges(conn: sqlite3.Connection) -> None:
    created_at = _now()
    rows = conn.execute(
        """
        SELECT ra.assertion_id, ra.chunk_id, ra.relation_type, ra.confidence,
               source.resolved_entity_id AS source_resolved_entity_id,
               source_entity.canonical_name AS source_name,
               source_entity.canonical_layer AS source_layer,
               target.resolved_entity_id AS target_resolved_entity_id,
               target_entity.canonical_name AS target_name,
               target_entity.canonical_layer AS target_layer
        FROM relation_assertions ra
        JOIN relation_assertion_reviews rr ON ra.assertion_id = rr.assertion_id
        JOIN entity_mentions source ON ra.source_mention_id = source.mention_id
        JOIN resolved_entities source_entity ON source.resolved_entity_id = source_entity.resolved_entity_id
        JOIN entity_mentions target ON ra.target_mention_id = target.mention_id
        JOIN resolved_entities target_entity ON target.resolved_entity_id = target_entity.resolved_entity_id
        WHERE rr.decision = 'correct'
          AND rr.path_safety = 'path_safe'
          AND source_entity.entity_status = 'active'
          AND target_entity.entity_status = 'active'
        """
    ).fetchall()
    for row in rows:
        case_id = _case_id_from_chunk(str(row["chunk_id"]))
        if not case_id:
            continue
        source_policy = _entity_policy(conn, str(row["source_resolved_entity_id"]))
        target_policy = _entity_policy(conn, str(row["target_resolved_entity_id"]))
        if source_policy["path_eligibility"] == "excluded" or target_policy["path_eligibility"] == "excluded":
            continue
        edge_path_eligibility = (
            "path_safe"
            if source_policy["path_eligibility"] == "path_safe" and target_policy["path_eligibility"] == "path_safe"
            else "limited"
        )
        governance_flags = _edge_governance_flags(source_policy, target_policy)
        confidence = _float_or_none(row["confidence"])
        source_weight = float(source_policy["weight_multiplier"])
        target_weight = float(target_policy["weight_multiplier"])
        edge_weight = None if confidence is None else confidence * source_weight * target_weight
        source_slot_id = _slot_id(case_id, str(row["source_resolved_entity_id"]), "canonical_projection")
        target_slot_id = _slot_id(case_id, str(row["target_resolved_entity_id"]), "canonical_projection")
        edge_id = _edge_id(case_id, str(row["assertion_id"]), "path_safe_relation_projection")
        conn.execute(
            """
            INSERT OR REPLACE INTO candidate_edges (
                candidate_edge_id, case_id, source_candidate_id, target_candidate_id,
                source_name, source_layer, relation_type, target_name, target_layer,
                source_method, supporting_assertion_ids_json, source_evidence_json,
                confidence, source_weight_multiplier, target_weight_multiplier,
                edge_weight, path_eligibility, governance_flags_json, rationale,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                case_id,
                source_slot_id,
                target_slot_id,
                row["source_name"],
                row["source_layer"],
                row["relation_type"],
                row["target_name"],
                row["target_layer"],
                "path_safe_relation_projection",
                json.dumps([row["assertion_id"]], ensure_ascii=False),
                json.dumps(
                    {
                        "chunk_id": row["chunk_id"],
                        "assertion_id": row["assertion_id"],
                    },
                    ensure_ascii=False,
                ),
                confidence,
                source_weight,
                target_weight,
                edge_weight,
                edge_path_eligibility,
                json.dumps(governance_flags, ensure_ascii=False),
                "",
                "unverified_candidate",
                created_at,
            ),
        )


class OpenAICompatibleRouteCandidateGenerator:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleRouteCandidateGenerator":
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from stage2_model_governance import _build_openai_compatible_client_from_stage2_env

        client = _build_openai_compatible_client_from_stage2_env()
        return cls(client=client, model=client.config.model)

    def generate_case_candidates(self, case_payload: dict[str, object]) -> dict[str, object]:
        payload = {
            "task": "Generate unverified route candidate slots and edges from visible extracted knowledge only.",
            "rules": [
                "Do not claim facts. All outputs are unverified candidates.",
                "Do not use hidden bridge sources or benchmark gold labels.",
                "Use case_task.title/mode as the user-facing discovery target when deciding route-level application/capability candidates.",
                "Prefer high-level route slots: principle, technology, capability, scenario.",
                "Generate missing capability/application slots only when supported or strongly implied by visible entities and path-safe relations.",
                "Use context_entities and context_relations as weak visible signals for route-level abstraction; do not copy every context entity into route slots.",
                "Promote principle candidates when visible text expresses mechanisms, correlations, constraints, or model assumptions, even if the exact gold-style phrase is absent.",
                "Use visible_source_context to abstract route-level candidates; do not copy navigation noise, bibliographic references, or unrelated examples.",
                "Do not force a complete four-layer route. Generate only candidates supported by the visible context.",
                "Keep output small: at most 12 candidate_slots and at most 18 candidate_edges.",
                "Use relation types only from enables, drives, implements, has_capability, applies_to, constrains, responsible_for.",
                "Return JSON only.",
            ],
            "output_schema": {
                "candidate_slots": [
                    {
                        "layer": "principle|technology|capability|scenario",
                        "name": "string",
                        "aliases": ["string"],
                        "confidence": 0.0,
                        "supporting_chunk_ids": ["string"],
                        "rationale": "short reason",
                    }
                ],
                "candidate_edges": [
                    {
                        "source_name": "string",
                        "relation_type": "string",
                        "target_name": "string",
                        "confidence": 0.0,
                        "supporting_chunk_ids": ["string"],
                        "rationale": "short reason",
                    }
                ],
            },
            "case": case_payload,
        }
        result = _call_with_retries(
            lambda: self.client.complete_json(
                [
                    {
                        "role": "system",
                        "content": "You are a conservative scientific route candidate generator.",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]
            ),
            label="stage3_route_candidate_generation",
        )
        return {
            "candidate_slots": _list_from_any(result, ["candidate_slots", "slots"]),
            "candidate_edges": _list_from_any(result, ["candidate_edges", "edges"]),
        }


def _generate_llm_candidates(
    conn: sqlite3.Connection,
    llm_generator: Any,
    max_llm_cases: int | None,
    chunk_context_by_case: dict[str, list[dict[str, Any]]],
    safe_case_context_by_case: dict[str, dict[str, Any]],
    llm_case_ids: list[str] | None = None,
    case_payload_limit: int = DEFAULT_CASE_PAYLOAD_LIMIT,
) -> None:
    case_ids = sorted({row["case_id"] for row in conn.execute("SELECT DISTINCT case_id FROM candidate_slots")})
    if llm_case_ids:
        requested = set(llm_case_ids)
        case_ids = [case_id for case_id in case_ids if case_id in requested]
    if max_llm_cases is not None:
        case_ids = case_ids[:max_llm_cases]
    created_at = _now()
    for case_id in case_ids:
        payload = _case_payload(
            conn,
            case_id,
            chunk_context_by_case.get(case_id, []),
            safe_case_context_by_case.get(case_id, {}),
            case_payload_limit=case_payload_limit,
        )
        generated = llm_generator.generate_case_candidates(payload)
        slot_name_to_id = _candidate_slot_name_index(conn, case_id)
        for item in generated.get("candidate_slots", []):
            name = str(item.get("name") or "").strip()
            layer = str(item.get("layer") or "unknown").strip()
            if not name or layer not in {"principle", "technology", "capability", "scenario"}:
                continue
            candidate_id = _slot_id(case_id, name, "llm_route_candidate")
            slot_name_to_id[_norm(name)] = candidate_id
            aliases = [str(alias) for alias in item.get("aliases", []) if str(alias).strip()]
            supporting_chunk_ids = _string_list(item.get("supporting_chunk_ids"))
            conn.execute(
                """
                INSERT OR REPLACE INTO candidate_slots (
                    candidate_id, case_id, layer, name, aliases_json, source_method,
                    source_resolved_entity_id, source_evidence_json, confidence,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    case_id,
                    layer,
                    name,
                    json.dumps(aliases, ensure_ascii=False),
                    "llm_route_candidate",
                    None,
                    json.dumps(
                        {
                            "rationale": item.get("rationale", ""),
                            "supporting_chunk_ids": supporting_chunk_ids,
                        },
                        ensure_ascii=False,
                    ),
                    _float_or_none(item.get("confidence")),
                    "unverified_candidate",
                    created_at,
                ),
            )
        for item in generated.get("candidate_edges", []):
            source_name = str(item.get("source_name") or "").strip()
            target_name = str(item.get("target_name") or "").strip()
            relation_type = str(item.get("relation_type") or "").strip()
            if not source_name or not target_name or relation_type not in {
                "enables",
                "drives",
                "implements",
                "has_capability",
                "applies_to",
                "constrains",
                "responsible_for",
            }:
                continue
            edge_id = _edge_id(case_id, f"{source_name}\0{relation_type}\0{target_name}", "llm_route_candidate")
            source_candidate_id = slot_name_to_id.get(_norm(source_name))
            target_candidate_id = slot_name_to_id.get(_norm(target_name))
            supporting_chunk_ids = _string_list(item.get("supporting_chunk_ids"))
            conn.execute(
                """
                INSERT OR REPLACE INTO candidate_edges (
                    candidate_edge_id, case_id, source_candidate_id, target_candidate_id,
                    source_name, source_layer, relation_type, target_name, target_layer,
                    source_method, supporting_assertion_ids_json, source_evidence_json,
                    confidence, source_weight_multiplier, target_weight_multiplier,
                    edge_weight, path_eligibility, governance_flags_json, rationale,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    case_id,
                    source_candidate_id,
                    target_candidate_id,
                    source_name,
                    _layer_for_candidate(conn, source_candidate_id),
                    relation_type,
                    target_name,
                    _layer_for_candidate(conn, target_candidate_id),
                    "llm_route_candidate",
                    "[]",
                    json.dumps(
                        {
                            "supporting_chunk_ids": supporting_chunk_ids,
                            "rationale": item.get("rationale", ""),
                        },
                        ensure_ascii=False,
                    ),
                    _float_or_none(item.get("confidence")),
                    1.0,
                    1.0,
                    _float_or_none(item.get("confidence")),
                    "unverified",
                    json.dumps(["llm_candidate_unverified"], ensure_ascii=False),
                    str(item.get("rationale") or ""),
                    "unverified_candidate",
                    created_at,
                ),
            )
        conn.commit()


def _case_payload(
    conn: sqlite3.Connection,
    case_id: str,
    visible_source_context: list[dict[str, Any]] | None = None,
    safe_case_context: dict[str, Any] | None = None,
    case_payload_limit: int = DEFAULT_CASE_PAYLOAD_LIMIT,
) -> dict[str, Any]:
    slots = [dict(row) for row in conn.execute(
        """
        SELECT layer, name, aliases_json, source_method
        FROM candidate_slots
        WHERE case_id = ?
        ORDER BY layer, name
        LIMIT ?
        """,
        (case_id, case_payload_limit),
    )]
    edges = [dict(row) for row in conn.execute(
        """
        SELECT source_name, relation_type, target_name, source_method
        FROM candidate_edges
        WHERE case_id = ?
        ORDER BY relation_type, source_name, target_name
        LIMIT ?
        """,
        (case_id, case_payload_limit),
    )]
    return {
        "case_id": case_id,
        "case_task": safe_case_context or {},
        "candidate_slots": slots,
        "candidate_edges": edges,
        "context_entities": _case_context_entities(conn, case_id, case_payload_limit),
        "context_relations": _case_context_relations(conn, case_id, case_payload_limit),
        "visible_source_context": visible_source_context or [],
    }


def _case_context_entities(
    conn: sqlite3.Connection,
    case_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT re.resolved_entity_id, re.canonical_name AS name,
               re.canonical_type AS entity_type, re.canonical_layer AS layer,
               re.alias_json AS aliases_json, re.mention_count,
               re.chunk_count, re.document_count, MIN(em.chunk_id) AS sample_chunk_id
        FROM resolved_entities re
        JOIN entity_mentions em ON re.resolved_entity_id = em.resolved_entity_id
        WHERE re.entity_status = 'active'
          AND em.chunk_id LIKE ?
        GROUP BY re.resolved_entity_id
        ORDER BY
            CASE re.canonical_layer
                WHEN 'requirement' THEN 0
                WHEN 'constraint' THEN 1
                WHEN 'principle' THEN 2
                WHEN 'capability' THEN 3
                WHEN 'technology' THEN 4
                WHEN 'scenario' THEN 5
                ELSE 9
            END,
            re.document_count DESC,
            re.mention_count DESC,
            re.canonical_name
        LIMIT ?
        """,
        (f"{case_id}-%", max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def _case_context_relations(
    conn: sqlite3.Connection,
    case_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ra.assertion_id, ra.relation_type, ra.confidence, ra.trigger_text,
               rr.path_safety,
               source_entity.canonical_name AS source_name,
               source_entity.canonical_layer AS source_layer,
               source_entity.canonical_type AS source_type,
               target_entity.canonical_name AS target_name,
               target_entity.canonical_layer AS target_layer,
               target_entity.canonical_type AS target_type
        FROM relation_assertions ra
        JOIN relation_assertion_reviews rr ON ra.assertion_id = rr.assertion_id
        JOIN entity_mentions source ON ra.source_mention_id = source.mention_id
        JOIN resolved_entities source_entity ON source.resolved_entity_id = source_entity.resolved_entity_id
        JOIN entity_mentions target ON ra.target_mention_id = target.mention_id
        JOIN resolved_entities target_entity ON target.resolved_entity_id = target_entity.resolved_entity_id
        WHERE ra.chunk_id LIKE ?
          AND rr.decision = 'correct'
          AND rr.path_safety != 'unsafe'
          AND source_entity.entity_status = 'active'
          AND target_entity.entity_status = 'active'
        ORDER BY
            CASE rr.path_safety
                WHEN 'path_safe' THEN 0
                WHEN 'context_only' THEN 1
                ELSE 2
            END,
            ra.confidence DESC,
            ra.relation_type,
            source_entity.canonical_name,
            target_entity.canonical_name
        LIMIT ?
        """,
        (f"{case_id}-%", max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_visible_chunk_context(chunks_path: Path, excerpt_chars: int) -> dict[str, list[dict[str, Any]]]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")
    context_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with chunks_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                chunk = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{chunks_path}:{line_no}: invalid JSON: {exc}") from exc
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            case_id = str(metadata.get("case_id") or "")
            if not case_id:
                continue
            context_by_case[case_id].append(
                {
                    "source_id": str(metadata.get("source_id") or chunk.get("document_id") or ""),
                    "source_title": str(metadata.get("source_title") or chunk.get("section_title") or ""),
                    "source_role": str(metadata.get("source_role") or ""),
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                    "excerpt": _compact_excerpt(str(chunk.get("text") or ""), excerpt_chars),
                }
            )
    return dict(context_by_case)


def _load_safe_case_context(case_context_path: Path) -> dict[str, dict[str, Any]]:
    if not case_context_path.exists():
        raise FileNotFoundError(f"Case context file not found: {case_context_path}")
    contexts: dict[str, dict[str, Any]] = {}
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
            if not case_id:
                continue
            contexts[case_id] = {
                "case_id": case_id,
                "title": str(case.get("title") or ""),
                "mode": str(case.get("mode") or ""),
                "visible_sources": [
                    {
                        "source_id": str(source.get("source_id") or ""),
                        "title": str(source.get("title") or ""),
                        "source_role": str(source.get("source_role") or ""),
                        "evidence_scope": str(source.get("evidence_scope") or ""),
                    }
                    for source in case.get("visible_sources", [])
                    if isinstance(source, dict)
                ],
            }
    return contexts


def _candidate_slot_name_index(conn: sqlite3.Connection, case_id: str) -> dict[str, str]:
    return {
        _norm(row["name"]): row["candidate_id"]
        for row in conn.execute(
            "SELECT candidate_id, name FROM candidate_slots WHERE case_id = ?",
            (case_id,),
        )
    }


def _layer_for_candidate(conn: sqlite3.Connection, candidate_id: str | None) -> str:
    if not candidate_id:
        return "unknown"
    row = conn.execute("SELECT layer FROM candidate_slots WHERE candidate_id = ?", (candidate_id,)).fetchone()
    return str(row["layer"]) if row else "unknown"


def _insert_run(conn: sqlite3.Connection, input_db: Path, output_db: Path, llm_generator: Any | None) -> None:
    summary = summarize_stage3(conn)
    created_at = _now()
    run_id = "stage3-run-" + _sha1(f"{input_db}\0{output_db}\0{created_at}")[:16]
    conn.execute(
        """
        INSERT INTO stage3_route_candidate_runs (
            run_id, stage3_version, input_db, output_db, llm_model,
            candidate_slot_count, candidate_edge_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            STAGE3_VERSION,
            str(input_db),
            str(output_db),
            getattr(llm_generator, "model", "none") if llm_generator is not None else "none",
            summary["candidate_slot_count"],
            summary["candidate_edge_count"],
            created_at,
        ),
    )


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _ensure_entity_governance_annotations(conn: sqlite3.Connection) -> None:
    created_at = _now()
    rows = conn.execute(
        """
        SELECT re.resolved_entity_id, re.canonical_name, re.canonical_type,
               re.canonical_layer, re.entity_status, re.alias_json,
               re.mention_count, re.chunk_count, re.document_count
        FROM resolved_entities re
        LEFT JOIN entity_governance_annotations a
          ON re.resolved_entity_id = a.resolved_entity_id
        WHERE re.entity_status = 'active'
          AND a.resolved_entity_id IS NULL
        """
    ).fetchall()
    for row in rows:
        policy = classify_entity_path_policy(dict(row))
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_governance_annotations (
                resolved_entity_id, path_eligibility, weight_multiplier,
                granularity_label, governance_reason, governance_source,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["resolved_entity_id"],
                policy.path_eligibility,
                policy.weight_multiplier,
                policy.granularity_label,
                policy.governance_reason,
                ENTITY_PATH_POLICY_VERSION,
                created_at,
            ),
        )


def _entity_policy(conn: sqlite3.Connection, resolved_entity_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT path_eligibility, weight_multiplier, granularity_label, governance_reason
        FROM entity_governance_annotations
        WHERE resolved_entity_id = ?
        """,
        (resolved_entity_id,),
    ).fetchone()
    if row is None:
        return {
            "path_eligibility": "path_safe",
            "weight_multiplier": 1.0,
            "granularity_label": "specific_route_entity",
            "governance_reason": "missing annotation default",
        }
    return dict(row)


def _edge_governance_flags(source_policy: dict[str, Any], target_policy: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    for prefix, policy in (("source", source_policy), ("target", target_policy)):
        label = str(policy.get("granularity_label") or "")
        eligibility = str(policy.get("path_eligibility") or "")
        if eligibility == "limited":
            flags.append(f"{prefix}_{label}")
        elif eligibility == "review_required":
            flags.append(f"{prefix}_review_required")
        if label == "generic_class":
            flags.append("generic_entity_penalty")
        elif label == "broad_technology_family":
            flags.append("broad_technology_family_penalty")
    return sorted(set(flags))


def _build_llm_generator(args: argparse.Namespace) -> Any | None:
    if args.llm_provider == "none":
        return None
    if args.llm_provider == "llm":
        return OpenAICompatibleRouteCandidateGenerator.from_env()
    raise ValueError(f"Unsupported LLM provider: {args.llm_provider}")


def _case_id_from_chunk(chunk_id: str) -> str:
    parts = str(chunk_id).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else ""


def _slot_id(case_id: str, value: str, source_method: str) -> str:
    return "candidate-slot-" + _sha1(f"{case_id}\0{source_method}\0{value}")[:16]


def _edge_id(case_id: str, value: str, source_method: str) -> str:
    return "candidate-edge-" + _sha1(f"{case_id}\0{source_method}\0{value}")[:16]


def _list_from_any(value: Any, keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _call_with_retries(callback: Any, label: str) -> Any:
    max_retries = max(
        1,
        int(__import__("os").getenv("STAGE3_MODEL_CALL_MAX_RETRIES", str(DEFAULT_STAGE3_MODEL_CALL_MAX_RETRIES))),
    )
    sleep_seconds = float(
        __import__("os").getenv(
            "STAGE3_MODEL_CALL_RETRY_SLEEP_SECONDS",
            str(DEFAULT_STAGE3_MODEL_CALL_RETRY_SLEEP_SECONDS),
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
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, where_clause: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}").fetchone()[0])


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _compact_excerpt(text: str, max_chars: int) -> str:
    compacted = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if max_chars <= 0 or len(compacted) <= max_chars:
        return compacted
    head_chars = max_chars * 2 // 3
    tail_chars = max_chars - head_chars
    return compacted[:head_chars].rstrip() + "\n...[truncated]...\n" + compacted[-tail_chars:].lstrip()


def _norm(value: str) -> str:
    return "".join(str(value).lower().split())


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate unverified route candidate slots and edges.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--append", action="store_true", help="Append LLM candidates to an existing output DB.")
    parser.add_argument("--llm-provider", choices=["none", "llm"], default="none")
    parser.add_argument("--max-llm-cases", type=int, default=None)
    parser.add_argument(
        "--llm-case-id",
        action="append",
        default=[],
        help="Restrict LLM candidate generation to one case id. Can be repeated.",
    )
    parser.add_argument(
        "--chunks",
        default=str(DEFAULT_CHUNKS),
        help="Visible chunks JSONL used only as LLM candidate-generation context. Use an empty value to disable.",
    )
    parser.add_argument("--chunk-context-chars", type=int, default=DEFAULT_CHUNK_CONTEXT_CHARS)
    parser.add_argument("--case-payload-limit", type=int, default=DEFAULT_CASE_PAYLOAD_LIMIT)
    parser.add_argument(
        "--case-context",
        default=str(DEFAULT_CASE_CONTEXT),
        help="Benchmark case task context JSONL. Only case title/mode/visible source metadata are read.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
