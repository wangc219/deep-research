"""Phase 3 migration: expand Phase 1 extraction rows into structured SQLite.

This script intentionally stays in the local experiment layer:
- no Neo4j
- no canonical Entity table
- no FactEdge or HypothesisLink
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHASE1_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase1_all_chunks"
    / "phase1_extractions.sqlite"
)
DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr"
    / "chunks.jsonl"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase3_structured"
    / "phase3_extractions.sqlite"
)

CONTENT_TYPE_CLASSIFIER_VERSION = "content-type-rules-v2"
VALID_STRENGTHS = {"strong", "speculative", "weak", "negated"}
STRENGTH_MAPPINGS = {
    "asserted": "strong",
    "expected": "speculative",
}
ISSUE_SEVERITIES = {"info", "warning", "error", "critical"}


def main() -> int:
    args = _parse_args()
    output_db = Path(args.output_db).expanduser().resolve()
    if output_db.exists() and not args.force:
        raise SystemExit(f"Output DB already exists; use --force to replace: {output_db}")
    attempts_root = (
        Path(args.attempts_root).expanduser().resolve()
        if args.attempts_root
        else output_db.parent / "attempts"
    )
    summary = migrate_phase1_to_phase3(
        phase1_db=Path(args.phase1_db).expanduser().resolve(),
        chunks_path=Path(args.chunks).expanduser().resolve(),
        output_db=output_db,
        attempts_root=attempts_root,
        overwrite=args.force,
    )
    print("phase3_migration_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def migrate_phase1_to_phase3(
    phase1_db: Path,
    chunks_path: Path,
    output_db: Path,
    attempts_root: Path,
    overwrite: bool = True,
) -> dict[str, Any]:
    if not phase1_db.exists():
        raise FileNotFoundError(f"Phase 1 DB not found: {phase1_db}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"chunks.jsonl not found: {chunks_path}")
    if output_db.exists() and overwrite:
        output_db.unlink()
    output_db.parent.mkdir(parents=True, exist_ok=True)
    attempts_root.mkdir(parents=True, exist_ok=True)

    chunks = _load_chunks(chunks_path)
    phase1_rows = _load_phase1_rows(phase1_db)

    conn = sqlite3.connect(output_db)
    try:
        ensure_phase3_schema(conn)
        with conn:
            for row in phase1_rows:
                chunk_id = str(row["chunk_id"])
                chunk = chunks.get(chunk_id)
                if chunk is None:
                    raise ValueError(f"Missing chunk for phase1 row: {chunk_id}")
                payload = json.loads(row["payload_json"])
                _migrate_row(
                    conn=conn,
                    row=row,
                    chunk=chunk,
                    payload=payload,
                    attempts_root=attempts_root,
                )
        summary = summarize_phase3(conn)
    finally:
        conn.close()
    summary.update(
        {
            "phase1_db": str(phase1_db),
            "chunks_path": str(chunks_path),
            "output_db": str(output_db),
            "attempts_root": str(attempts_root),
        }
    )
    return summary


def ensure_phase3_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_type TEXT NOT NULL,
            parser TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            text TEXT NOT NULL,
            source_path TEXT NOT NULL,
            page INTEGER,
            section_title TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content_type_classifier_version TEXT NOT NULL,
            content_type_status TEXT NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(document_id)
        );

        CREATE TABLE IF NOT EXISTS extractions (
            extraction_id TEXT PRIMARY KEY,
            chunk_id TEXT NOT NULL,
            phase1_row_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            adapter_name TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS extraction_attempts (
            attempt_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            attempt_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            raw_request_hash TEXT NOT NULL,
            raw_request_path TEXT NOT NULL,
            raw_response_hash TEXT NOT NULL,
            raw_response_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS evidence_spans (
            evidence_span_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            raw_evidence_id TEXT NOT NULL,
            quote TEXT NOT NULL,
            start_char INTEGER,
            end_char INTEGER,
            page INTEGER,
            match_status TEXT NOT NULL,
            match_error TEXT NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS entity_mentions (
            mention_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            raw_entity_id TEXT NOT NULL,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS entity_evidence_links (
            mention_id TEXT NOT NULL,
            evidence_span_id TEXT NOT NULL,
            PRIMARY KEY (mention_id, evidence_span_id),
            FOREIGN KEY(mention_id) REFERENCES entity_mentions(mention_id),
            FOREIGN KEY(evidence_span_id) REFERENCES evidence_spans(evidence_span_id)
        );

        CREATE TABLE IF NOT EXISTS source_claims (
            claim_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            raw_claim_id TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            text TEXT NOT NULL,
            modality TEXT NOT NULL,
            subject_mention_id TEXT NOT NULL,
            object_mention_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            confidence REAL NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS evidence_claim_links (
            evidence_span_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            PRIMARY KEY (evidence_span_id, claim_id),
            FOREIGN KEY(evidence_span_id) REFERENCES evidence_spans(evidence_span_id),
            FOREIGN KEY(claim_id) REFERENCES source_claims(claim_id)
        );

        CREATE TABLE IF NOT EXISTS relation_assertions (
            assertion_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            raw_relation_id TEXT NOT NULL,
            source_mention_id TEXT NOT NULL,
            target_mention_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            assertion_strength TEXT NOT NULL,
            raw_assertion_strength TEXT NOT NULL,
            strength_normalization_status TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE TABLE IF NOT EXISTS relation_claim_links (
            assertion_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            PRIMARY KEY (assertion_id, claim_id),
            FOREIGN KEY(assertion_id) REFERENCES relation_assertions(assertion_id),
            FOREIGN KEY(claim_id) REFERENCES source_claims(claim_id)
        );

        CREATE TABLE IF NOT EXISTS issues (
            issue_id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            field TEXT NOT NULL,
            code TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            recoverable INTEGER NOT NULL,
            FOREIGN KEY(extraction_id) REFERENCES extractions(extraction_id),
            FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_extractions_chunk_id ON extractions(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_entity_mentions_chunk_id ON entity_mentions(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_relation_assertions_chunk_id ON relation_assertions(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_source_claims_chunk_id ON source_claims(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_spans_chunk_id ON evidence_spans(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_issues_chunk_id ON issues(chunk_id);
        """
    )
    conn.commit()


def classify_content_type(text: str, section_title: str = "") -> str:
    stripped = text.strip()
    lower = stripped.lower()
    section = section_title or ""
    digit_ratio = sum(char.isdigit() for char in stripped) / max(1, len(stripped))
    line_count = stripped.count("\n") + 1
    chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in stripped)
    ascii_alpha_count = sum(char.isascii() and char.isalpha() for char in stripped)

    if "参考文献" in section or section.lower().startswith("references") or "参考文献" in stripped[:80]:
        return "references"
    if (
        "摘 要" in stripped[:100]
        or "关键词" in stripped[:500]
        or "abstract:" in lower[:200]
    ):
        return "abstract_or_metadata"
    if (
        "<table" in lower
        or re.search(r"(^|\n)\s*表\s*\d|(^|\n)\s*table\s*\d", stripped, re.I)
        or digit_ratio >= 0.18
        or line_count >= 18
    ):
        return "table_or_parameter_dense"
    if re.search(r"(^|\n)\s*图\s*\d|fig\.?\s*\d", stripped, re.I):
        return "figure_caption_or_figure_context"
    if "结论" in section or section.lower().startswith("conclusion"):
        return "conclusion"
    if (
        chinese_count
        and ascii_alpha_count
        and min(chinese_count, ascii_alpha_count) / max(chinese_count, ascii_alpha_count) > 0.20
    ):
        return "mixed_language_body"
    if ascii_alpha_count > chinese_count:
        return "english_body"
    return "chinese_body"


def summarize_phase3(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        "documents",
        "chunks",
        "extractions",
        "extraction_attempts",
        "entity_mentions",
        "relation_assertions",
        "source_claims",
        "evidence_spans",
        "relation_claim_links",
        "evidence_claim_links",
        "entity_evidence_links",
        "issues",
    ]
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
    }
    content_type_counts = dict(
        conn.execute(
            "SELECT content_type, COUNT(*) FROM chunks GROUP BY content_type ORDER BY content_type"
        ).fetchall()
    )
    issue_counts = dict(
        conn.execute(
            "SELECT code, COUNT(*) FROM issues GROUP BY code ORDER BY code"
        ).fetchall()
    )
    return {
        "documents": counts["documents"],
        "chunks": counts["chunks"],
        "extractions": counts["extractions"],
        "counts": counts,
        "content_type_counts": content_type_counts,
        "issue_counts": issue_counts,
    }


def fetch_chunk_bundle(conn: sqlite3.Connection, chunk_id: str) -> dict[str, Any]:
    return {
        "chunk": _one(conn, "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)),
        "entity_mentions": _many(
            conn,
            "SELECT * FROM entity_mentions WHERE chunk_id = ? ORDER BY mention_id",
            (chunk_id,),
        ),
        "relation_assertions": _many(
            conn,
            "SELECT * FROM relation_assertions WHERE chunk_id = ? ORDER BY assertion_id",
            (chunk_id,),
        ),
        "source_claims": _many(
            conn,
            "SELECT * FROM source_claims WHERE chunk_id = ? ORDER BY claim_id",
            (chunk_id,),
        ),
        "evidence_spans": _many(
            conn,
            "SELECT * FROM evidence_spans WHERE chunk_id = ? ORDER BY evidence_span_id",
            (chunk_id,),
        ),
        "issues": _many(
            conn,
            "SELECT * FROM issues WHERE chunk_id = ? ORDER BY issue_id",
            (chunk_id,),
        ),
    }


def _migrate_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    chunk: dict[str, Any],
    payload: dict[str, Any],
    attempts_root: Path,
) -> None:
    chunk_id = str(row["chunk_id"])
    document_id = str(chunk.get("document_id") or payload.get("document_id") or "")
    metadata = dict(chunk.get("metadata") or {})
    extraction_id = _global_id(chunk_id, "extraction", "phase1")

    _insert_document(conn, document_id, chunk, metadata)
    _insert_chunk(conn, chunk_id, document_id, chunk, metadata)
    _insert_extraction(conn, extraction_id, row, payload)
    _insert_attempt(conn, extraction_id, row, payload, attempts_root)

    issue_counter = _IssueCounter()
    warning_evidence_ids = _warning_evidence_ids(payload.get("warnings") or [])
    evidence_ids = _insert_evidence_spans(
        conn=conn,
        extraction_id=extraction_id,
        chunk_id=chunk_id,
        chunk=chunk,
        payload=payload,
        warning_evidence_ids=warning_evidence_ids,
    )
    entity_ids = _insert_entity_mentions(conn, extraction_id, chunk_id, payload, evidence_ids, issue_counter)
    claim_ids, claims_by_signature = _insert_claims(
        conn,
        extraction_id,
        chunk_id,
        payload,
        evidence_ids,
        entity_ids,
        issue_counter,
    )
    _insert_relations(
        conn,
        extraction_id,
        chunk_id,
        payload,
        entity_ids,
        claim_ids,
        claims_by_signature,
        issue_counter,
    )
    _insert_warning_issues(conn, extraction_id, chunk_id, payload, evidence_ids, issue_counter)


def _insert_document(
    conn: sqlite3.Connection,
    document_id: str,
    chunk: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO documents (
            document_id, title, source_path, source_type, parser, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            str(metadata.get("title") or chunk.get("section_title") or document_id),
            str(chunk.get("source_path") or ""),
            str(metadata.get("source_type") or ""),
            str(metadata.get("parser") or ""),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ),
    )


def _insert_chunk(
    conn: sqlite3.Connection,
    chunk_id: str,
    document_id: str,
    chunk: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    text = str(chunk.get("text") or "")
    section_title = str(chunk.get("section_title") or "")
    conn.execute(
        """
        INSERT INTO chunks (
            chunk_id, document_id, text, source_path, page, section_title,
            metadata_json, content_type, content_type_classifier_version,
            content_type_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            document_id,
            text,
            str(chunk.get("source_path") or ""),
            chunk.get("page"),
            section_title,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            classify_content_type(text, section_title),
            CONTENT_TYPE_CLASSIFIER_VERSION,
            "classified",
        ),
    )


def _insert_extraction(
    conn: sqlite3.Connection,
    extraction_id: str,
    row: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    trace = dict(payload.get("trace") or {})
    conn.execute(
        """
        INSERT INTO extractions (
            extraction_id, chunk_id, phase1_row_id, task_id, adapter_name,
            schema_version, prompt_version, model, status, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            extraction_id,
            str(row["chunk_id"]),
            int(row["id"]),
            str(payload.get("task_id") or ""),
            str(payload.get("adapter_name") or ""),
            str(row.get("schema_version") or trace.get("schema_version") or ""),
            str(trace.get("prompt_version") or ""),
            str(trace.get("model") or ""),
            str(row["status"]),
            str(row["payload_json"]),
            str(row["created_at"]),
        ),
    )


def _insert_attempt(
    conn: sqlite3.Connection,
    extraction_id: str,
    row: dict[str, Any],
    payload: dict[str, Any],
    attempts_root: Path,
) -> None:
    chunk_id = str(row["chunk_id"])
    attempt_id = _global_id(chunk_id, "attempt", "001")
    attempt_dir = attempts_root / _safe_path_name(attempt_id)
    request_body = {
        "source": "phase1_backfill",
        "phase1_row_id": int(row["id"]),
        "chunk_id": chunk_id,
    }
    response_body = {
        "raw_llm": str(row["raw_llm"]),
    }
    request_path, request_hash = _write_json_artifact(attempt_dir / "request.json", request_body)
    response_path, response_hash = _write_json_artifact(attempt_dir / "response.json", response_body)
    error_type = str(payload.get("error_type") or "")
    error_message = str(payload.get("error_message") or "")
    created_at = str(row["created_at"] or datetime.now(timezone.utc).isoformat())
    conn.execute(
        """
        INSERT INTO extraction_attempts (
            attempt_id, extraction_id, chunk_id, attempt_index, status,
            error_type, error_message, raw_request_hash, raw_request_path,
            raw_response_hash, raw_response_path, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            extraction_id,
            chunk_id,
            1,
            str(row["status"]),
            error_type,
            error_message,
            request_hash,
            str(request_path),
            response_hash,
            str(response_path),
            created_at,
            created_at,
        ),
    )


def _insert_evidence_spans(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    chunk: dict[str, Any],
    payload: dict[str, Any],
    warning_evidence_ids: set[str],
) -> dict[str, str]:
    chunk_text = str(chunk.get("text") or "")
    evidence_ids: dict[str, str] = {}
    for item in payload.get("evidence_spans") or []:
        raw_evidence_id = str(item.get("evidence_id") or f"ev-{len(evidence_ids) + 1}")
        evidence_span_id = _global_id(chunk_id, "evidence", raw_evidence_id)
        quote = str(item.get("quote") or "")
        start_char = item.get("start_char")
        end_char = item.get("end_char")
        match_status, match_error, start_char, end_char = _evidence_match_status(
            quote=quote,
            chunk_text=chunk_text,
            start_char=start_char,
            end_char=end_char,
            was_warned=raw_evidence_id in warning_evidence_ids,
        )
        conn.execute(
            """
            INSERT INTO evidence_spans (
                evidence_span_id, extraction_id, chunk_id, raw_evidence_id, quote,
                start_char, end_char, page, match_status, match_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_span_id,
                extraction_id,
                chunk_id,
                raw_evidence_id,
                quote,
                start_char,
                end_char,
                item.get("page", chunk.get("page")),
                match_status,
                match_error,
            ),
        )
        evidence_ids[raw_evidence_id] = evidence_span_id
    return evidence_ids


def _insert_entity_mentions(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    payload: dict[str, Any],
    evidence_ids: dict[str, str],
    issue_counter: "_IssueCounter",
) -> dict[str, str]:
    entity_ids: dict[str, str] = {}
    for item in payload.get("entities") or []:
        raw_entity_id = str(item.get("entity_id") or f"entity-{len(entity_ids) + 1}")
        mention_id = _global_id(chunk_id, "entity", raw_entity_id)
        conn.execute(
            """
            INSERT INTO entity_mentions (
                mention_id, extraction_id, chunk_id, raw_entity_id,
                name, entity_type, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mention_id,
                extraction_id,
                chunk_id,
                raw_entity_id,
                str(item.get("name") or ""),
                str(item.get("entity_type") or ""),
                float(item.get("confidence") or 0.0),
            ),
        )
        entity_ids[raw_entity_id] = mention_id
        for raw_evidence_id in item.get("evidence_span_ids") or []:
            evidence_span_id = evidence_ids.get(str(raw_evidence_id))
            if evidence_span_id:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_evidence_links (
                        mention_id, evidence_span_id
                    ) VALUES (?, ?)
                    """,
                    (mention_id, evidence_span_id),
                )
            else:
                _insert_issue(
                    conn,
                    extraction_id,
                    chunk_id,
                    issue_counter.next(chunk_id),
                    "entity_mention",
                    mention_id,
                    "evidence_span_ids",
                    "entity_missing_evidence",
                    "error",
                    f"entity evidence id not found: {raw_evidence_id}",
                    True,
                )
    return entity_ids


def _insert_claims(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    payload: dict[str, Any],
    evidence_ids: dict[str, str],
    entity_ids: dict[str, str],
    issue_counter: "_IssueCounter",
) -> tuple[dict[str, str], dict[tuple[str, str, str], list[str]]]:
    claim_ids: dict[str, str] = {}
    claims_by_signature: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for item in payload.get("claims") or []:
        raw_claim_id = str(item.get("claim_id") or f"claim-{len(claim_ids) + 1}")
        claim_id = _global_id(chunk_id, "claim", raw_claim_id)
        subject_raw_id = str(item.get("subject_entity_id") or "")
        object_raw_id = str(item.get("object_entity_id") or "")
        predicate = str(item.get("predicate") or "")
        subject_mention_id = entity_ids.get(subject_raw_id, "")
        object_mention_id = entity_ids.get(object_raw_id, "")
        conn.execute(
            """
            INSERT INTO source_claims (
                claim_id, extraction_id, chunk_id, raw_claim_id, claim_type,
                text, modality, subject_mention_id, object_mention_id,
                predicate, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                extraction_id,
                chunk_id,
                raw_claim_id,
                str(item.get("claim_type") or ""),
                str(item.get("text") or ""),
                str(item.get("modality") or ""),
                subject_mention_id,
                object_mention_id,
                predicate,
                float(item.get("confidence") or 0.0),
            ),
        )
        claim_ids[raw_claim_id] = claim_id
        claims_by_signature[(subject_raw_id, object_raw_id, predicate)].append(claim_id)
        if not subject_mention_id:
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "source_claim",
                claim_id,
                "subject_mention_id",
                "claim_missing_subject_mention",
                "critical",
                f"claim subject entity id not found: {subject_raw_id}",
                True,
            )
        if not object_mention_id:
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "source_claim",
                claim_id,
                "object_mention_id",
                "claim_missing_object_mention",
                "critical",
                f"claim object entity id not found: {object_raw_id}",
                True,
            )
        for raw_evidence_id in item.get("evidence_span_ids") or []:
            evidence_span_id = evidence_ids.get(str(raw_evidence_id))
            if evidence_span_id:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO evidence_claim_links (
                        evidence_span_id, claim_id
                    ) VALUES (?, ?)
                    """,
                    (evidence_span_id, claim_id),
                )
            else:
                _insert_issue(
                    conn,
                    extraction_id,
                    chunk_id,
                    issue_counter.next(chunk_id),
                    "source_claim",
                    claim_id,
                    "evidence_span_ids",
                    "claim_missing_evidence",
                    "error",
                    f"claim evidence id not found: {raw_evidence_id}",
                    True,
                )
    return claim_ids, claims_by_signature


def _insert_relations(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    payload: dict[str, Any],
    entity_ids: dict[str, str],
    claim_ids: dict[str, str],
    claims_by_signature: dict[tuple[str, str, str], list[str]],
    issue_counter: "_IssueCounter",
) -> None:
    del claim_ids
    for item in payload.get("relations") or []:
        raw_relation_id = str(item.get("relation_id") or f"relation-{issue_counter.peek()}")
        assertion_id = _global_id(chunk_id, "relation", raw_relation_id)
        source_raw_id = str(item.get("source_entity_id") or "")
        target_raw_id = str(item.get("target_entity_id") or "")
        relation_type = str(item.get("relation_type") or "")
        raw_strength = str(item.get("assertion_strength") or "")
        strength, normalization_status = _normalize_strength(raw_strength)
        conn.execute(
            """
            INSERT INTO relation_assertions (
                assertion_id, extraction_id, chunk_id, raw_relation_id,
                source_mention_id, target_mention_id, relation_type,
                assertion_strength, raw_assertion_strength,
                strength_normalization_status, confidence, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assertion_id,
                extraction_id,
                chunk_id,
                raw_relation_id,
                entity_ids.get(source_raw_id, ""),
                entity_ids.get(target_raw_id, ""),
                relation_type,
                strength,
                raw_strength,
                normalization_status,
                float(item.get("confidence") or 0.0),
                "extracted",
            ),
        )
        if normalization_status != "valid":
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "relation_assertion",
                assertion_id,
                "assertion_strength",
                "invalid_assertion_strength",
                "warning",
                f"mapped raw assertion_strength {raw_strength!r} to {strength!r}",
                True,
            )
        linked_claim_ids = claims_by_signature.get((source_raw_id, target_raw_id, relation_type), [])
        if not linked_claim_ids:
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "relation_assertion",
                assertion_id,
                "claim_id",
                "relation_missing_claim",
                "critical",
                "relation assertion has no matching source claim",
                True,
            )
        for claim_id in linked_claim_ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO relation_claim_links (
                    assertion_id, claim_id
                ) VALUES (?, ?)
                """,
                (assertion_id, claim_id),
            )


def _insert_warning_issues(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    payload: dict[str, Any],
    evidence_ids: dict[str, str],
    issue_counter: "_IssueCounter",
) -> None:
    for warning in payload.get("warnings") or []:
        warning_text = str(warning)
        if warning_text.startswith("evidence_quote_not_found:"):
            raw_evidence_id = warning_text.split(":", 1)[1]
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "evidence_span",
                evidence_ids.get(raw_evidence_id, _global_id(chunk_id, "evidence", raw_evidence_id)),
                "quote",
                "evidence_quote_not_found",
                "error",
                warning_text,
                True,
            )
        elif warning_text.startswith("invalid_assertion_strength:"):
            continue
        else:
            _insert_issue(
                conn,
                extraction_id,
                chunk_id,
                issue_counter.next(chunk_id),
                "extraction",
                extraction_id,
                "",
                "model_self_warning",
                "info",
                warning_text,
                True,
            )


def _insert_issue(
    conn: sqlite3.Connection,
    extraction_id: str,
    chunk_id: str,
    issue_id: str,
    object_type: str,
    object_id: str,
    field: str,
    code: str,
    severity: str,
    message: str,
    recoverable: bool,
) -> None:
    if severity not in ISSUE_SEVERITIES:
        raise ValueError(f"invalid issue severity: {severity}")
    conn.execute(
        """
        INSERT INTO issues (
            issue_id, extraction_id, chunk_id, object_type, object_id, field,
            code, severity, message, recoverable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            issue_id,
            extraction_id,
            chunk_id,
            object_type,
            object_id,
            field,
            code,
            severity,
            message,
            1 if recoverable else 0,
        ),
    )


def _load_chunks(path: Path) -> dict[str, dict[str, Any]]:
    chunks: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            chunks[str(item.get("chunk_id"))] = item
    return chunks


def _load_phase1_rows(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, chunk_id, raw_llm, payload_json, schema_version,
                       status, created_at
                FROM extractions
                ORDER BY id
                """
            ).fetchall()
        ]
    finally:
        conn.close()


def _evidence_match_status(
    quote: str,
    chunk_text: str,
    start_char: Any,
    end_char: Any,
    was_warned: bool,
) -> tuple[str, str, int | None, int | None]:
    if not quote:
        return "missing_quote", "empty evidence quote", _int_or_none(start_char), _int_or_none(end_char)
    located_at = chunk_text.find(quote)
    if located_at >= 0 and not was_warned:
        return "exact", "", located_at, located_at + len(quote)
    if not was_warned and start_char is not None and end_char is not None:
        start = _int_or_none(start_char)
        end = _int_or_none(end_char)
        if start is not None and end is not None and chunk_text[start:end] == quote:
            return "exact", "", start, end
    return (
        "not_found",
        "quote not found in chunk text",
        _int_or_none(start_char),
        _int_or_none(end_char),
    )


def _normalize_strength(raw_strength: str) -> tuple[str, str]:
    if raw_strength in VALID_STRENGTHS:
        return raw_strength, "valid"
    if raw_strength in STRENGTH_MAPPINGS:
        return STRENGTH_MAPPINGS[raw_strength], "mapped"
    return "weak", "invalid_kept_raw"


def _warning_evidence_ids(warnings: list[Any]) -> set[str]:
    evidence_ids: set[str] = set()
    for warning in warnings:
        warning_text = str(warning)
        if warning_text.startswith("evidence_quote_not_found:"):
            evidence_ids.add(warning_text.split(":", 1)[1])
    return evidence_ids


def _write_json_artifact(path: Path, payload: dict[str, Any]) -> tuple[Path, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    return path.resolve(), hashlib.sha256(data).hexdigest()


def _global_id(chunk_id: str, kind: str, raw_id: str) -> str:
    return f"{chunk_id}::{kind}::{raw_id}"


def _safe_path_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _one(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> dict[str, Any]:
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.row_factory = original_row_factory


def _many(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.row_factory = original_row_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Phase 1 extraction SQLite into Phase 3 structured SQLite.",
    )
    parser.add_argument("--phase1-db", default=str(DEFAULT_PHASE1_DB))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument(
        "--attempts-root",
        default="",
        help="Directory for request/response artifacts; default is output DB parent/attempts.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


class _IssueCounter:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def next(self, chunk_id: str) -> str:
        self._counts[chunk_id] += 1
        return _global_id(chunk_id, "issue", f"{self._counts[chunk_id]:04d}")

    def peek(self) -> int:
        return sum(self._counts.values()) + 1


if __name__ == "__main__":
    raise SystemExit(main())
