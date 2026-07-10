"""Stage 2.5 model-assisted governance for entity aliases and relation reviews.

This script starts from a Stage 2 entity-normalization SQLite database. It adds
embedding-generated alias candidates and LLM review tables, but it does not
auto-merge entities and does not create new relation assertions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
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
    / "stage2_entity_normalization_v1"
    / "stage2_entity_normalization.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage2_entity_model_governance.sqlite"
)

MODEL_GOVERNANCE_VERSION = "stage2-model-governance-v1"
ALIAS_REVIEW_PROMPT_VERSION = "alias-candidate-review-v1"
RELATION_REVIEW_PROMPT_VERSION = "relation-assertion-review-v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_EMBEDDING_BATCH_SIZE = 10
DEFAULT_SIMILARITY_THRESHOLD = 0.86
DEFAULT_TOP_K = 5
DEFAULT_REVIEW_BATCH_SIZE = 20
DEFAULT_LLM_CANDIDATE_BATCH_SIZE = 60
DEFAULT_MODEL_CALL_MAX_RETRIES = 3
DEFAULT_MODEL_CALL_RETRY_SLEEP_SECONDS = 5.0


def main() -> int:
    args = _parse_args()
    embedding_provider = _build_embedding_provider(args)
    alias_reviewer = _build_alias_reviewer(args)
    relation_reviewer = _build_relation_reviewer(args)
    llm_candidate_generator = _build_llm_candidate_generator(args)
    summary = run_model_governance(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        embedding_provider=embedding_provider,
        llm_candidate_generator=llm_candidate_generator,
        alias_reviewer=alias_reviewer,
        relation_reviewer=relation_reviewer,
        similarity_threshold=float(args.similarity_threshold),
        top_k=int(args.top_k),
        review_batch_size=int(args.review_batch_size),
        llm_candidate_batch_size=int(args.llm_candidate_batch_size),
        max_embedding_entities=args.max_embedding_entities,
        min_embedding_mentions=args.min_embedding_mentions,
        max_llm_candidate_batches=args.max_llm_candidate_batches,
        max_alias_candidates=args.max_alias_candidates,
        max_relation_reviews=args.max_relation_reviews,
    )
    print("stage2_model_governance_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def run_model_governance(
    input_db: Path,
    output_db: Path,
    overwrite: bool = True,
    embedding_provider: Any | None = None,
    llm_candidate_generator: Any | None = None,
    alias_reviewer: Any | None = None,
    relation_reviewer: Any | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
    review_batch_size: int = DEFAULT_REVIEW_BATCH_SIZE,
    llm_candidate_batch_size: int = DEFAULT_LLM_CANDIDATE_BATCH_SIZE,
    max_embedding_entities: int | None = None,
    min_embedding_mentions: int = 1,
    max_llm_candidate_batches: int | None = None,
    max_alias_candidates: int | None = None,
    max_relation_reviews: int | None = None,
) -> dict[str, Any]:
    if not input_db.exists():
        raise FileNotFoundError(f"Input Stage 2 DB not found: {input_db}")
    if output_db.exists() and overwrite:
        output_db.unlink()
    if output_db.exists():
        raise FileExistsError(f"Output DB already exists; use --force to replace: {output_db}")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_db, output_db)

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_model_governance_schema(conn)
            entity_rows = _fetch_embedding_entities(
                conn,
                max_embedding_entities=max_embedding_entities,
                min_embedding_mentions=min_embedding_mentions,
            )
            if embedding_provider is not None:
                _write_entity_embeddings(conn, entity_rows, embedding_provider)
                candidates = _generate_embedding_candidates(
                    conn=conn,
                    similarity_threshold=similarity_threshold,
                    top_k=top_k,
                    max_alias_candidates=max_alias_candidates,
                )
            else:
                candidates = []
            if llm_candidate_generator is not None:
                candidates.extend(
                    _generate_llm_alias_candidates(
                        conn=conn,
                        entities=entity_rows,
                        llm_candidate_generator=llm_candidate_generator,
                        batch_size=llm_candidate_batch_size,
                        max_batches=max_llm_candidate_batches,
                    )
                )
            if alias_reviewer is not None and candidates:
                _review_alias_candidates(conn, candidates, alias_reviewer, review_batch_size)
            relations = _fetch_relation_review_inputs(conn, max_relation_reviews)
            if relation_reviewer is not None and relations:
                _review_relations(conn, relations, relation_reviewer, review_batch_size)
            _insert_run_record(
                conn=conn,
                input_db=input_db,
                output_db=output_db,
                embedding_provider=embedding_provider,
                llm_candidate_generator=llm_candidate_generator,
                alias_reviewer=alias_reviewer,
                relation_reviewer=relation_reviewer,
                similarity_threshold=similarity_threshold,
                top_k=top_k,
                review_batch_size=review_batch_size,
            )
        summary = summarize_model_governance(conn)
        summary.update(
            {
                "input_db": str(input_db),
                "output_db": str(output_db),
                "model_governance_version": MODEL_GOVERNANCE_VERSION,
                "embedding_model": getattr(embedding_provider, "model", "none")
                if embedding_provider is not None
                else "none",
                "llm_candidate_model": getattr(llm_candidate_generator, "model", "none")
                if llm_candidate_generator is not None
                else "none",
                "alias_review_model": getattr(alias_reviewer, "model", "none")
                if alias_reviewer is not None
                else "none",
                "relation_review_model": getattr(relation_reviewer, "model", "none")
                if relation_reviewer is not None
                else "none",
                "similarity_threshold": similarity_threshold,
                "top_k": top_k,
                "review_batch_size": review_batch_size,
                "llm_candidate_batch_size": llm_candidate_batch_size,
                "max_embedding_entities": max_embedding_entities,
                "min_embedding_mentions": min_embedding_mentions,
            }
        )
        return summary
    finally:
        conn.close()


def ensure_model_governance_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_embeddings (
            resolved_entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            canonical_type TEXT NOT NULL,
            embedding_text TEXT NOT NULL,
            embedding_text_hash TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            embedding_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entity_alias_candidates (
            candidate_id TEXT PRIMARY KEY,
            left_resolved_entity_id TEXT NOT NULL,
            right_resolved_entity_id TEXT NOT NULL,
            left_name TEXT NOT NULL,
            right_name TEXT NOT NULL,
            left_type TEXT NOT NULL,
            right_type TEXT NOT NULL,
            similarity REAL NOT NULL,
            candidate_method TEXT NOT NULL,
            candidate_source TEXT NOT NULL,
            evidence_basis TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entity_alias_candidate_reviews (
            review_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            confidence REAL,
            review_source TEXT NOT NULL,
            review_model TEXT NOT NULL,
            review_prompt_version TEXT NOT NULL,
            review_note TEXT NOT NULL,
            raw_response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES entity_alias_candidates(candidate_id)
        );

        CREATE TABLE IF NOT EXISTS relation_assertion_reviews (
            review_id TEXT PRIMARY KEY,
            assertion_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            suggested_relation_type TEXT,
            suggested_direction TEXT NOT NULL,
            path_safety TEXT NOT NULL,
            confidence REAL,
            review_source TEXT NOT NULL,
            review_model TEXT NOT NULL,
            review_prompt_version TEXT NOT NULL,
            review_note TEXT NOT NULL,
            raw_response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(assertion_id) REFERENCES relation_assertions(assertion_id)
        );

        CREATE TABLE IF NOT EXISTS stage2_model_governance_runs (
            run_id TEXT PRIMARY KEY,
            model_governance_version TEXT NOT NULL,
            input_db TEXT NOT NULL,
            output_db TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dimension INTEGER,
            similarity_threshold REAL NOT NULL,
            top_k INTEGER NOT NULL,
            review_batch_size INTEGER NOT NULL DEFAULT 20,
            llm_candidate_model TEXT NOT NULL DEFAULT 'none',
            alias_review_model TEXT NOT NULL,
            relation_review_model TEXT NOT NULL,
            embedding_candidate_count INTEGER NOT NULL,
            alias_review_count INTEGER NOT NULL,
            relation_review_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_alias_candidates_left
            ON entity_alias_candidates(left_resolved_entity_id);
        CREATE INDEX IF NOT EXISTS idx_alias_candidates_right
            ON entity_alias_candidates(right_resolved_entity_id);
        CREATE INDEX IF NOT EXISTS idx_alias_reviews_candidate
            ON entity_alias_candidate_reviews(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_relation_reviews_assertion
            ON relation_assertion_reviews(assertion_id);
        """
    )


def summarize_model_governance(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "embedding_count": _count(conn, "entity_embeddings"),
        "alias_candidate_count": _count(conn, "entity_alias_candidates"),
        "embedding_candidate_count": _count_where(
            conn,
            "entity_alias_candidates",
            "candidate_method = 'embedding_cosine'",
        ),
        "llm_candidate_count": _count_where(
            conn,
            "entity_alias_candidates",
            "candidate_method = 'llm_candidate_generation'",
        ),
        "alias_review_count": _count(conn, "entity_alias_candidate_reviews"),
        "relation_review_count": _count(conn, "relation_assertion_reviews"),
        "relation_assertion_count": _count(conn, "relation_assertions"),
        "alias_review_decisions": _group_count(conn, "entity_alias_candidate_reviews", "decision"),
        "relation_review_decisions": _group_count(conn, "relation_assertion_reviews", "decision"),
    }


@dataclass
class DashScopeTextEmbeddingProvider:
    api_key: str
    model: str = DEFAULT_EMBEDDING_MODEL
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    text_type: str = "document"
    output_type: str = "dense"

    @classmethod
    def from_env(cls) -> "DashScopeTextEmbeddingProvider":
        dotenv = _load_powershell_dotenv()
        api_key = _env_value("STAGE2_EMBEDDING_API_KEY", dotenv) or _env_value("DASHSCOPE_API_KEY", dotenv)
        if not api_key:
            raise RuntimeError("Missing embedding API key. Set STAGE2_EMBEDDING_API_KEY or DASHSCOPE_API_KEY.")
        return cls(
            api_key=api_key,
            model=_env_value("STAGE2_EMBEDDING_MODEL", dotenv, DEFAULT_EMBEDDING_MODEL) or DEFAULT_EMBEDDING_MODEL,
            dimension=int(_env_value("STAGE2_EMBEDDING_DIMENSION", dotenv, str(DEFAULT_EMBEDDING_DIMENSION)) or DEFAULT_EMBEDDING_DIMENSION),
            batch_size=int(_env_value("STAGE2_EMBEDDING_BATCH_SIZE", dotenv, str(DEFAULT_EMBEDDING_BATCH_SIZE)) or DEFAULT_EMBEDDING_BATCH_SIZE),
            text_type=_env_value("STAGE2_EMBEDDING_TEXT_TYPE", dotenv, "document") or "document",
            output_type=_env_value("STAGE2_EMBEDDING_OUTPUT_TYPE", dotenv, "dense") or "dense",
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            import dashscope
        except ImportError as exc:
            raise RuntimeError("dashscope package is required for --embedding-provider dashscope.") from exc
        dashscope.api_key = self.api_key
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = dashscope.TextEmbedding.call(
                model=self.model,
                input=batch,
                dimension=self.dimension,
                text_type=self.text_type,
                output_type=self.output_type,
            )
            status_code = getattr(response, "status_code", None)
            if status_code is not None and status_code >= 400:
                raise RuntimeError(f"DashScope embedding failed: {response}")
            output = getattr(response, "output", None) or response.get("output")
            embeddings = output["embeddings"]
            vectors.extend([list(item["embedding"]) for item in embeddings])
        if len(vectors) != len(texts):
            raise RuntimeError(f"Embedding count mismatch: expected {len(texts)}, got {len(vectors)}")
        return vectors


class OpenAICompatibleAliasReviewer:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleAliasReviewer":
        client = _build_openai_compatible_client_from_stage2_env()
        return cls(client=client, model=client.config.model)

    def review_alias_candidates(self, candidates: list[dict[str, object]]) -> list[dict[str, object]]:
        payload = {
            "task": "Review whether each pair names the same canonical entity.",
            "allowed_decisions": ["same_entity", "related_but_distinct", "different", "uncertain"],
            "rules": [
                "Accept same_entity only when the two names are aliases/translations/abbreviations of the same entity.",
                "Use related_but_distinct for parent-child, organization-subunit, method-application, capability-technology, or broader/narrower concepts.",
                "Do not merge actor granularity differences such as country, military branch, department, and project office.",
                "Return JSON only.",
            ],
            "candidates": candidates,
        }
        result = self.client.complete_json(
            [
                {
                    "role": "system",
                    "content": "You are a strict entity-resolution reviewer. You do not create new entities.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        return _extract_review_list(result, ["reviews", "results", "alias_candidate_reviews", "entity_alias_candidate_reviews"])


class OpenAICompatibleRelationReviewer:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleRelationReviewer":
        client = _build_openai_compatible_client_from_stage2_env()
        return cls(client=client, model=client.config.model)

    def review_relations(self, relations: list[dict[str, object]]) -> list[dict[str, object]]:
        payload = {
            "task": "Review extracted relation assertions. Do not add new relations.",
            "allowed_decisions": [
                "correct",
                "wrong_type",
                "reversed",
                "unsupported",
                "plausible_but_overbroad",
                "uncertain",
            ],
            "allowed_suggested_direction": ["keep", "reverse", "drop", "needs_review"],
            "allowed_path_safety": ["path_safe", "context_only", "needs_review", "unsafe"],
            "rules": [
                "Judge only from the relation fields, trigger_text, and endpoint names/types.",
                "Mark reversed if source and target direction should be swapped.",
                "Mark plausible_but_overbroad when the relation is broadly plausible but too coarse for route prediction.",
                "Use path_safe only when the relation can safely participate in route prediction.",
                "Return JSON only.",
            ],
            "relations": relations,
        }
        result = self.client.complete_json(
            [
                {
                    "role": "system",
                    "content": "You are a strict knowledge-graph relation quality reviewer.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        return _extract_review_list(result, ["reviews", "results", "relation_reviews", "relation_assertion_reviews"])


class OpenAICompatibleAliasCandidateGenerator:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAICompatibleAliasCandidateGenerator":
        client = _build_openai_compatible_client_from_stage2_env()
        return cls(client=client, model=client.config.model)

    def generate_alias_candidates(self, entities: list[dict[str, object]]) -> list[dict[str, object]]:
        payload = {
            "task": "Propose additional same-entity alias candidates from this canonical entity list.",
            "output_schema": {
                "candidates": [
                    {
                        "left_resolved_entity_id": "optional",
                        "right_resolved_entity_id": "optional",
                        "left_name": "required if id omitted",
                        "right_name": "required if id omitted",
                        "decision_hint": "same_entity_candidate | related_but_distinct_candidate | uncertain",
                        "confidence": 0.0,
                        "evidence_basis": "short reason",
                    }
                ]
            },
            "rules": [
                "Only propose pairs likely to be aliases, translations, spelling variants, abbreviations, or acronym expansions of the same entity.",
                "Do not propose parent-child, method-application, capability-technology, source-subunit, or broader/narrower concept pairs.",
                "Do not propose Source actor granularity merges such as country vs military branch vs department.",
                "Prefer high precision; returning an empty list is acceptable.",
                "Return JSON only.",
            ],
            "entities": entities,
        }
        result = self.client.complete_json(
            [
                {
                    "role": "system",
                    "content": "You are a conservative alias candidate generator. You do not merge entities.",
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        return _extract_review_list(result, ["candidates", "alias_candidates", "entity_alias_candidates"])


def _fetch_embedding_entities(
    conn: sqlite3.Connection,
    max_embedding_entities: int | None = None,
    min_embedding_mentions: int = 1,
) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute(
        """
        SELECT resolved_entity_id, canonical_name, canonical_type, canonical_layer,
               entity_status, alias_json, mention_count, chunk_count, document_count
        FROM resolved_entities
        WHERE entity_status != 'noise'
          AND mention_count >= ?
        ORDER BY document_count DESC, mention_count DESC, canonical_name, resolved_entity_id
        """
        ,
        (max(1, int(min_embedding_mentions)),),
    ):
        item = dict(row)
        aliases = json.loads(item.get("alias_json") or "[]")
        item["embedding_text"] = _embedding_text(item, aliases)
        rows.append(item)
        if max_embedding_entities is not None and len(rows) >= max_embedding_entities:
            break
    return rows


def _write_entity_embeddings(
    conn: sqlite3.Connection,
    entity_rows: list[dict[str, Any]],
    embedding_provider: Any,
) -> None:
    texts = [str(item["embedding_text"]) for item in entity_rows]
    vectors = embedding_provider.embed_texts(texts) if texts else []
    created_at = _now()
    for item, vector in zip(entity_rows, vectors):
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_embeddings (
                resolved_entity_id, canonical_name, canonical_type, embedding_text,
                embedding_text_hash, embedding_model, embedding_dimension,
                embedding_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["resolved_entity_id"],
                item["canonical_name"],
                item["canonical_type"],
                item["embedding_text"],
                _sha1(str(item["embedding_text"])),
                getattr(embedding_provider, "model", "unknown"),
                int(getattr(embedding_provider, "dimension", len(vector))),
                json.dumps(vector, ensure_ascii=False),
                created_at,
            ),
        )


def _generate_embedding_candidates(
    conn: sqlite3.Connection,
    similarity_threshold: float,
    top_k: int,
    max_alias_candidates: int | None,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in conn.execute("SELECT * FROM entity_embeddings ORDER BY resolved_entity_id")]
    scored_by_left: dict[str, list[dict[str, Any]]] = {}
    for left_index, left in enumerate(rows):
        left_vector = json.loads(left["embedding_json"])
        for right in rows[left_index + 1 :]:
            if not _compatible_alias_candidate(left, right):
                continue
            right_vector = json.loads(right["embedding_json"])
            similarity = _cosine_similarity(left_vector, right_vector)
            if similarity < similarity_threshold:
                continue
            candidate = _candidate_row(left, right, similarity)
            scored_by_left.setdefault(str(left["resolved_entity_id"]), []).append(candidate)

    candidates: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for left_id in sorted(scored_by_left):
        ranked = sorted(scored_by_left[left_id], key=lambda item: (-float(item["similarity"]), item["right_name"]))
        for candidate in ranked[:top_k]:
            pair = tuple(sorted([candidate["left_resolved_entity_id"], candidate["right_resolved_entity_id"]]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidates.append(candidate)
            if max_alias_candidates is not None and len(candidates) >= max_alias_candidates:
                break
        if max_alias_candidates is not None and len(candidates) >= max_alias_candidates:
            break

    created_at = _now()
    for candidate in candidates:
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_alias_candidates (
                candidate_id, left_resolved_entity_id, right_resolved_entity_id,
                left_name, right_name, left_type, right_type, similarity,
                candidate_method, candidate_source, evidence_basis, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate["candidate_id"],
                candidate["left_resolved_entity_id"],
                candidate["right_resolved_entity_id"],
                candidate["left_name"],
                candidate["right_name"],
                candidate["left_type"],
                candidate["right_type"],
                candidate["similarity"],
                "embedding_cosine",
                getattr(candidate, "candidate_source", "embedding"),
                candidate["evidence_basis"],
                "pending_review",
                created_at,
            ),
        )
    return candidates


def _review_alias_candidates(
    conn: sqlite3.Connection,
    candidates: list[dict[str, Any]],
    alias_reviewer: Any,
    review_batch_size: int,
) -> None:
    reviews = []
    for batch in _batches(candidates, review_batch_size):
        reviews.extend(
            _extract_review_list(
                _call_with_retries(
                    lambda: alias_reviewer.review_alias_candidates(batch),
                    label="alias_candidate_review",
                ),
                ["reviews", "results", "alias_candidate_reviews", "entity_alias_candidate_reviews"],
            )
        )
    by_id = {
        str(review.get("candidate_id")): review
        for review in reviews
        if review.get("candidate_id")
    }
    created_at = _now()
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        review = by_id.get(candidate_id) or _find_review_by_names(candidate, reviews) or {
            "candidate_id": candidate_id,
            "decision": "uncertain",
            "confidence": None,
            "review_note": "Reviewer did not return a row for this candidate.",
            "raw_response": {},
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_alias_candidate_reviews (
                review_id, candidate_id, decision, confidence, review_source,
                review_model, review_prompt_version, review_note,
                raw_response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _review_id(candidate_id, ALIAS_REVIEW_PROMPT_VERSION),
                candidate_id,
                _safe_choice(str(review.get("decision") or "uncertain"), {"same_entity", "related_but_distinct", "different", "uncertain"}, "uncertain"),
                _float_or_none(review.get("confidence")),
                "llm_reviewed",
                getattr(alias_reviewer, "model", "unknown"),
                ALIAS_REVIEW_PROMPT_VERSION,
                str(review.get("review_note") or review.get("rationale") or ""),
                json.dumps(review.get("raw_response", review), ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )


def _fetch_relation_review_inputs(
    conn: sqlite3.Connection,
    max_relation_reviews: int | None,
) -> list[dict[str, Any]]:
    query = """
        SELECT ra.assertion_id, ra.document_id, ra.chunk_id, ra.relation_type,
               ra.confidence, ra.trigger_text, ra.inference_eligible,
               source.resolved_entity_id AS source_resolved_entity_id,
               source.name AS source_mention_name,
               source.entity_type AS source_mention_type,
               source_entity.canonical_name AS source_name,
               source_entity.canonical_type AS source_type,
               target.resolved_entity_id AS target_resolved_entity_id,
               target.name AS target_mention_name,
               target.entity_type AS target_mention_type,
               target_entity.canonical_name AS target_name,
               target_entity.canonical_type AS target_type
        FROM relation_assertions ra
        LEFT JOIN entity_mentions source ON ra.source_mention_id = source.mention_id
        LEFT JOIN resolved_entities source_entity ON source.resolved_entity_id = source_entity.resolved_entity_id
        LEFT JOIN entity_mentions target ON ra.target_mention_id = target.mention_id
        LEFT JOIN resolved_entities target_entity ON target.resolved_entity_id = target_entity.resolved_entity_id
        ORDER BY ra.assertion_id
    """
    rows = [dict(row) for row in conn.execute(query)]
    if max_relation_reviews is not None:
        return rows[:max_relation_reviews]
    return rows


def _review_relations(
    conn: sqlite3.Connection,
    relations: list[dict[str, Any]],
    relation_reviewer: Any,
    review_batch_size: int,
) -> None:
    reviews = []
    for batch in _batches(relations, review_batch_size):
        reviews.extend(
            _extract_review_list(
                _call_with_retries(
                    lambda: relation_reviewer.review_relations(batch),
                    label="relation_assertion_review",
                ),
                ["reviews", "results", "relation_reviews", "relation_assertion_reviews"],
            )
        )
    by_id = {str(review.get("assertion_id")): review for review in reviews}
    created_at = _now()
    for relation in relations:
        assertion_id = str(relation["assertion_id"])
        review = by_id.get(assertion_id) or {
            "assertion_id": assertion_id,
            "decision": "uncertain",
            "suggested_relation_type": relation.get("relation_type"),
            "suggested_direction": "needs_review",
            "path_safety": "needs_review",
            "confidence": None,
            "review_note": "Reviewer did not return a row for this relation.",
            "raw_response": {},
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO relation_assertion_reviews (
                review_id, assertion_id, decision, suggested_relation_type,
                suggested_direction, path_safety, confidence, review_source,
                review_model, review_prompt_version, review_note,
                raw_response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _review_id(assertion_id, RELATION_REVIEW_PROMPT_VERSION),
                assertion_id,
                _safe_choice(
                    str(review.get("decision") or "uncertain"),
                    {"correct", "wrong_type", "reversed", "unsupported", "plausible_but_overbroad", "uncertain"},
                    "uncertain",
                ),
                str(review.get("suggested_relation_type") or relation.get("relation_type") or ""),
                _safe_choice(
                    str(review.get("suggested_direction") or "needs_review"),
                    {"keep", "reverse", "drop", "needs_review"},
                    "needs_review",
                ),
                _safe_choice(
                    str(review.get("path_safety") or "needs_review"),
                    {"path_safe", "context_only", "needs_review", "unsafe"},
                    "needs_review",
                ),
                _float_or_none(review.get("confidence")),
                "llm_reviewed",
                getattr(relation_reviewer, "model", "unknown"),
                RELATION_REVIEW_PROMPT_VERSION,
                str(review.get("review_note") or review.get("rationale") or ""),
                json.dumps(review.get("raw_response", review), ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )


def _insert_run_record(
    conn: sqlite3.Connection,
    input_db: Path,
    output_db: Path,
    embedding_provider: Any | None,
    llm_candidate_generator: Any | None,
    alias_reviewer: Any | None,
    relation_reviewer: Any | None,
    similarity_threshold: float,
    top_k: int,
    review_batch_size: int,
) -> None:
    summary = summarize_model_governance(conn)
    created_at = _now()
    run_id = "stage2-model-run-" + _sha1(f"{input_db}\0{output_db}\0{created_at}")[:16]
    conn.execute(
        """
        INSERT INTO stage2_model_governance_runs (
            run_id, model_governance_version, input_db, output_db,
            embedding_model, embedding_dimension, similarity_threshold, top_k,
            review_batch_size, llm_candidate_model, alias_review_model, relation_review_model, embedding_candidate_count,
            alias_review_count, relation_review_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            MODEL_GOVERNANCE_VERSION,
            str(input_db),
            str(output_db),
            getattr(embedding_provider, "model", "none") if embedding_provider is not None else "none",
            getattr(embedding_provider, "dimension", None) if embedding_provider is not None else None,
            similarity_threshold,
            top_k,
            review_batch_size,
            getattr(llm_candidate_generator, "model", "none") if llm_candidate_generator is not None else "none",
            getattr(alias_reviewer, "model", "none") if alias_reviewer is not None else "none",
            getattr(relation_reviewer, "model", "none") if relation_reviewer is not None else "none",
            summary["embedding_candidate_count"],
            summary["alias_review_count"],
            summary["relation_review_count"],
            created_at,
        ),
    )


def _build_embedding_provider(args: argparse.Namespace) -> Any | None:
    provider = str(args.embedding_provider or "").lower()
    if provider == "none":
        return None
    if provider == "dashscope":
        return DashScopeTextEmbeddingProvider.from_env()
    raise ValueError(f"Unsupported embedding provider: {provider}")


def _build_alias_reviewer(args: argparse.Namespace) -> Any | None:
    provider = str(args.alias_review_provider or "").lower()
    if provider == "none":
        return None
    if provider == "llm":
        return OpenAICompatibleAliasReviewer.from_env()
    raise ValueError(f"Unsupported alias review provider: {provider}")


def _build_llm_candidate_generator(args: argparse.Namespace) -> Any | None:
    provider = str(args.llm_candidate_provider or "").lower()
    if provider == "none":
        return None
    if provider == "llm":
        return OpenAICompatibleAliasCandidateGenerator.from_env()
    raise ValueError(f"Unsupported LLM candidate provider: {provider}")


def _build_relation_reviewer(args: argparse.Namespace) -> Any | None:
    provider = str(args.relation_review_provider or "").lower()
    if provider == "none":
        return None
    if provider == "llm":
        return OpenAICompatibleRelationReviewer.from_env()
    raise ValueError(f"Unsupported relation review provider: {provider}")


def _build_openai_compatible_client_from_stage2_env() -> Any:
    script_root = PROJECT_ROOT / "scripts" / "extraction_experiment"
    if str(script_root) not in sys.path:
        sys.path.insert(0, str(script_root))
    from llm_client import LLMConfig, OpenAICompatibleClient

    dotenv = _load_powershell_dotenv()

    def value(stage2_name: str, extraction_name: str, default: str | None = None) -> str | None:
        return _env_value(stage2_name, dotenv) or _env_value(extraction_name, dotenv) or default

    api_key = (
        value("STAGE2_REVIEW_LLM_API_KEY", "EXTRACTION_LLM_API_KEY")
        or _env_value("DASHSCOPE_API_KEY", dotenv)
        or _env_value("OPENAI_API_KEY", dotenv)
    )
    if not api_key:
        raise RuntimeError("Missing review LLM API key. Set STAGE2_REVIEW_LLM_API_KEY or EXTRACTION_LLM_API_KEY.")
    config = LLMConfig(
        base_url=(value("STAGE2_REVIEW_LLM_BASE_URL", "EXTRACTION_LLM_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1").rstrip("/"),
        api_key=api_key,
        model=value("STAGE2_REVIEW_LLM_MODEL", "EXTRACTION_LLM_MODEL", "gpt-5.5") or "gpt-5.5",
        timeout_seconds=int(value("STAGE2_REVIEW_LLM_TIMEOUT_SECONDS", "EXTRACTION_LLM_TIMEOUT_SECONDS", "120") or "120"),
        temperature=float(value("STAGE2_REVIEW_LLM_TEMPERATURE", "EXTRACTION_LLM_TEMPERATURE", "0") or "0"),
        reasoning_effort=value("STAGE2_REVIEW_LLM_REASONING_EFFORT", "EXTRACTION_LLM_REASONING_EFFORT", "high"),
        thinking_enabled=_env_bool("STAGE2_REVIEW_LLM_THINKING_ENABLED", False, dotenv),
        response_format_json=_env_bool("STAGE2_REVIEW_LLM_JSON_MODE", True, dotenv),
    )
    return OpenAICompatibleClient(config)


def _candidate_row(left: dict[str, Any], right: dict[str, Any], similarity: float) -> dict[str, Any]:
    left_id = str(left["resolved_entity_id"])
    right_id = str(right["resolved_entity_id"])
    return {
        "candidate_id": _candidate_id(left_id, right_id, "embedding_cosine"),
        "left_resolved_entity_id": left_id,
        "right_resolved_entity_id": right_id,
        "left_name": str(left["canonical_name"]),
        "right_name": str(right["canonical_name"]),
        "left_type": str(left["canonical_type"]),
        "right_type": str(right["canonical_type"]),
        "similarity": round(similarity, 6),
        "candidate_method": "embedding_cosine",
        "candidate_source": "embedding",
        "evidence_basis": (
            f"cosine_similarity={similarity:.6f}; "
            f"left_embedding_model={left['embedding_model']}; right_embedding_model={right['embedding_model']}"
        ),
    }


def _generate_llm_alias_candidates(
    conn: sqlite3.Connection,
    entities: list[dict[str, Any]],
    llm_candidate_generator: Any,
    batch_size: int,
    max_batches: int | None,
) -> list[dict[str, Any]]:
    entity_lookup = _entity_lookup(entities)
    candidates: list[dict[str, Any]] = []
    batches = _entity_batches_for_llm_generation(entities, batch_size)
    if max_batches is not None:
        batches = batches[:max_batches]
    for batch in batches:
        generated = _extract_review_list(
            _call_with_retries(
                lambda: llm_candidate_generator.generate_alias_candidates(batch),
                label="llm_alias_candidate_generation",
            ),
            ["candidates", "alias_candidates", "entity_alias_candidates"],
        )
        for raw_candidate in generated:
            candidate = _coerce_llm_candidate(raw_candidate, entity_lookup)
            if candidate is not None:
                candidates.append(candidate)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate["candidate_id"] in seen:
            continue
        seen.add(candidate["candidate_id"])
        deduped.append(candidate)

    created_at = _now()
    for candidate in deduped:
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_alias_candidates (
                candidate_id, left_resolved_entity_id, right_resolved_entity_id,
                left_name, right_name, left_type, right_type, similarity,
                candidate_method, candidate_source, evidence_basis, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate["candidate_id"],
                candidate["left_resolved_entity_id"],
                candidate["right_resolved_entity_id"],
                candidate["left_name"],
                candidate["right_name"],
                candidate["left_type"],
                candidate["right_type"],
                candidate["similarity"],
                "llm_candidate_generation",
                "llm",
                candidate["evidence_basis"],
                "pending_review",
                created_at,
            ),
        )
    return deduped


def _coerce_llm_candidate(
    raw_candidate: dict[str, Any],
    entity_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    left = _lookup_entity(raw_candidate, "left", entity_lookup)
    right = _lookup_entity(raw_candidate, "right", entity_lookup)
    if left is None or right is None:
        return None
    if not _compatible_alias_candidate(left, right):
        return None
    similarity = _float_or_none(raw_candidate.get("confidence"))
    if similarity is None:
        similarity = 0.0
    return {
        "candidate_id": _candidate_id(
            str(left["resolved_entity_id"]),
            str(right["resolved_entity_id"]),
            "llm_candidate_generation",
        ),
        "left_resolved_entity_id": str(left["resolved_entity_id"]),
        "right_resolved_entity_id": str(right["resolved_entity_id"]),
        "left_name": str(left["canonical_name"]),
        "right_name": str(right["canonical_name"]),
        "left_type": str(left["canonical_type"]),
        "right_type": str(right["canonical_type"]),
        "similarity": round(float(similarity), 6),
        "candidate_method": "llm_candidate_generation",
        "candidate_source": "llm",
        "evidence_basis": str(raw_candidate.get("evidence_basis") or raw_candidate.get("review_note") or ""),
    }


def _lookup_entity(
    raw_candidate: dict[str, Any],
    side: str,
    entity_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    resolved_entity_id = raw_candidate.get(f"{side}_resolved_entity_id")
    if resolved_entity_id and str(resolved_entity_id) in entity_lookup:
        return entity_lookup[str(resolved_entity_id)]
    name = raw_candidate.get(f"{side}_name")
    if name:
        return entity_lookup.get(_name_key(str(name)))
    return None


def _entity_lookup(entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for entity in entities:
        lookup[str(entity["resolved_entity_id"])] = entity
        lookup.setdefault(_name_key(str(entity["canonical_name"])), entity)
    return lookup


def _entity_batches_for_llm_generation(
    entities: list[dict[str, Any]],
    batch_size: int,
) -> list[list[dict[str, Any]]]:
    eligible = [
        {
            "resolved_entity_id": item["resolved_entity_id"],
            "canonical_name": item["canonical_name"],
            "canonical_type": item["canonical_type"],
            "canonical_layer": item["canonical_layer"],
            "alias_json": item["alias_json"],
            "mention_count": item["mention_count"],
            "document_count": item["document_count"],
        }
        for item in entities
        if item.get("entity_status") != "noise" and item.get("canonical_type") != "Source"
    ]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in eligible:
        by_type.setdefault(str(item["canonical_type"]), []).append(item)
    batches: list[list[dict[str, Any]]] = []
    for entity_type in sorted(by_type):
        sorted_items = sorted(by_type[entity_type], key=lambda item: str(item["canonical_name"]))
        batches.extend(_batches(sorted_items, batch_size))
    return batches


def _compatible_alias_candidate(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["resolved_entity_id"] == right["resolved_entity_id"]:
        return False
    if left["canonical_type"] != right["canonical_type"]:
        return False
    if left["canonical_type"] in {"Noise", "Source"}:
        return False
    if str(left["canonical_name"]).strip().lower() == str(right["canonical_name"]).strip().lower():
        return False
    return True


def _embedding_text(item: dict[str, Any], aliases: list[str]) -> str:
    alias_text = "; ".join(sorted({str(alias) for alias in aliases if str(alias).strip()}))
    return "\n".join(
        [
            f"name: {item['canonical_name']}",
            f"type: {item['canonical_type']}",
            f"layer: {item['canonical_layer']}",
            f"aliases: {alias_text}",
        ]
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _candidate_id(left_id: str, right_id: str, method: str) -> str:
    low, high = sorted([left_id, right_id])
    return "entity-alias-candidate-" + _sha1(f"{method}\0{low}\0{high}")[:16]


def _batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    safe_size = max(1, int(batch_size))
    return [items[start : start + safe_size] for start in range(0, len(items), safe_size)]


def _extract_review_list(value: Any, keys: list[str]) -> list[dict[str, Any]]:
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
        int(os.getenv("STAGE2_MODEL_CALL_MAX_RETRIES", str(DEFAULT_MODEL_CALL_MAX_RETRIES))),
    )
    sleep_seconds = float(
        os.getenv(
            "STAGE2_MODEL_CALL_RETRY_SLEEP_SECONDS",
            str(DEFAULT_MODEL_CALL_RETRY_SLEEP_SECONDS),
        )
    )
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return callback()
        except Exception as exc:  # noqa: BLE001 - external transports raise mixed exception types.
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


def _find_review_by_names(
    candidate: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_names = {
        _name_key(str(candidate.get("left_name") or "")),
        _name_key(str(candidate.get("right_name") or "")),
    }
    for review in reviews:
        review_names = {
            _name_key(str(review.get("left_name") or "")),
            _name_key(str(review.get("right_name") or "")),
        }
        if candidate_names == review_names:
            return review
    return None


def _name_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _review_id(subject_id: str, prompt_version: str) -> str:
    return "model-review-" + _sha1(f"{prompt_version}\0{subject_id}")[:16]


def _safe_choice(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _count_where(conn: sqlite3.Connection, table: str, where_clause: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}").fetchone()[0])


def _group_count(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column} ORDER BY {column}"
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_value(name: str, dotenv: dict[str, str], default: str | None = None) -> str | None:
    return os.getenv(name) or dotenv.get(name) or default


def _env_bool(name: str, default: bool, dotenv: dict[str, str]) -> bool:
    value = os.getenv(name) or dotenv.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _load_powershell_dotenv(path: Path | None = None) -> dict[str, str]:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    pattern = __import__("re").compile(r"^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])(.*?)\2\s*$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            values[match.group(1)] = match.group(3)
    return values


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add embedding alias candidates and LLM review tables to a Stage 2 SQLite DB.",
    )
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--embedding-provider",
        choices=["none", "dashscope"],
        default=os.getenv("STAGE2_EMBEDDING_PROVIDER", "none"),
    )
    parser.add_argument(
        "--alias-review-provider",
        choices=["none", "llm"],
        default=os.getenv("STAGE2_ALIAS_REVIEW_PROVIDER", "none"),
    )
    parser.add_argument(
        "--llm-candidate-provider",
        choices=["none", "llm"],
        default=os.getenv("STAGE2_LLM_CANDIDATE_PROVIDER", "none"),
    )
    parser.add_argument(
        "--relation-review-provider",
        choices=["none", "llm"],
        default=os.getenv("STAGE2_RELATION_REVIEW_PROVIDER", "none"),
    )
    parser.add_argument(
        "--similarity-threshold",
        default=os.getenv("STAGE2_EMBEDDING_MIN_SIMILARITY", str(DEFAULT_SIMILARITY_THRESHOLD)),
    )
    parser.add_argument("--top-k", default=os.getenv("STAGE2_EMBEDDING_TOP_K", str(DEFAULT_TOP_K)))
    parser.add_argument("--review-batch-size", default=os.getenv("STAGE2_REVIEW_BATCH_SIZE", str(DEFAULT_REVIEW_BATCH_SIZE)))
    parser.add_argument("--llm-candidate-batch-size", default=os.getenv("STAGE2_LLM_CANDIDATE_BATCH_SIZE", str(DEFAULT_LLM_CANDIDATE_BATCH_SIZE)))
    parser.add_argument("--max-embedding-entities", type=int, default=None)
    parser.add_argument("--min-embedding-mentions", type=int, default=1)
    parser.add_argument("--max-llm-candidate-batches", type=int, default=None)
    parser.add_argument("--max-alias-candidates", type=int, default=None)
    parser.add_argument("--max-relation-reviews", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
