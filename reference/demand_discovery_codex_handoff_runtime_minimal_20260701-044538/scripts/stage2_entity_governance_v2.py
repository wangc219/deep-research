"""Thin CLI for Stage 2 Entity Governance v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.entity_governance import candidates as entity_candidates  # noqa: E402
from knowledgegraph.material_governance.entity_governance import embeddings as entity_embeddings  # noqa: E402
from knowledgegraph.material_governance.entity_governance import review as entity_review  # noqa: E402
from knowledgegraph.material_governance.entity_governance import runner as entity_runner  # noqa: E402
from knowledgegraph.material_governance.entity_governance.common import (  # noqa: E402
    DEFAULT_CODEX_HOME,
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    DEFAULT_CODEX_TIMEOUT_SECONDS,
    DEFAULT_MIN_CONCEPT_CONFIDENCE,
    DEFAULT_MIN_MERGE_CONFIDENCE,
    DEFAULT_REVIEW_BATCH_SIZE,
    DEFAULT_REVIEW_WORKERS,
    DEFAULT_EMBEDDING_WORKERS,
    DEFAULT_RUN_MODE,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K,
    RUN_MODES,
)

DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_entity_normalization_research.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_entity_governance_v2_research.sqlite"
)
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "experiment-artifacts" / "literature_100_doc_stage2_entity_governance_v2.md"


def main() -> int:
    args = _parse_args()
    embedding_provider = None
    llm_candidate_generator = None
    entity_reviewer = None
    if not args.rule_only:
        embedding_provider = _build_embedding_provider(args)
        llm_candidate_generator = _build_llm_candidate_generator(args)
        entity_reviewer = _build_entity_reviewer(args)
    summary = entity_runner.run_entity_governance_v2(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        rule_only=args.rule_only,
        ranking_db=Path(args.ranking_db).expanduser().resolve() if args.ranking_db else None,
        run_mode=args.run_mode,
        embedding_provider=embedding_provider,
        llm_candidate_generator=llm_candidate_generator,
        entity_reviewer=entity_reviewer,
        max_embedding_entities=int(args.max_embedding_entities),
        max_alias_candidates=int(args.max_alias_candidates),
        max_llm_candidate_batches=int(args.max_llm_candidate_batches),
        max_review_candidates=int(args.max_review_candidates),
        review_batch_size=int(args.review_batch_size),
        review_workers=int(args.review_workers),
        embedding_workers=int(args.embedding_workers),
        similarity_threshold=float(args.similarity_threshold),
        top_k=int(args.top_k),
        min_merge_confidence=float(args.min_merge_confidence),
        min_concept_confidence=float(args.min_concept_confidence),
        include_source_candidates=bool(args.include_source_candidates),
        embedding_provider_name=str(args.embedding_provider),
        llm_candidate_provider_name=str(args.llm_candidate_provider),
        entity_review_provider_name=str(args.entity_review_provider),
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
    )
    print("stage2_entity_governance_v2_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _build_embedding_provider(args: argparse.Namespace) -> Any | None:
    provider = str(args.embedding_provider or "none").lower()
    if provider == "none":
        return None
    if provider == "dashscope":
        return entity_embeddings.DashScopeTextEmbeddingProvider.from_env()
    raise ValueError(f"Unsupported embedding provider: {provider}")


def _build_llm_candidate_generator(args: argparse.Namespace) -> Any | None:
    provider = str(args.llm_candidate_provider or "none").lower()
    if provider == "none":
        return None
    if provider == "llm":
        return entity_candidates.OpenAICompatibleEntityCandidateGenerator.from_env()
    raise ValueError(f"Unsupported LLM candidate provider: {provider}")


def _build_entity_reviewer(args: argparse.Namespace) -> Any | None:
    provider = str(args.entity_review_provider or "none").lower()
    if provider == "none":
        return None
    if provider == "llm":
        return entity_review.OpenAICompatibleEntityGovernanceReviewer.from_env()
    if provider == "codex":
        return entity_review.CodexExecEntityGovernanceReviewer.from_env(args)
    raise ValueError(f"Unsupported entity review provider: {provider}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stage 2 Entity Governance v2 on a copied SQLite DB.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--run-mode", choices=sorted(RUN_MODES), default=DEFAULT_RUN_MODE)
    parser.add_argument("--ranking-db", default="")
    parser.add_argument("--embedding-provider", choices=["none", "dashscope"], default="none")
    parser.add_argument("--llm-candidate-provider", choices=["none", "llm"], default="none")
    parser.add_argument("--entity-review-provider", choices=["none", "llm", "codex"], default="codex")
    parser.add_argument("--max-embedding-entities", type=int, default=5000)
    parser.add_argument("--max-alias-candidates", type=int, default=3000)
    parser.add_argument("--max-llm-candidate-batches", type=int, default=0)
    parser.add_argument("--max-review-candidates", type=int, default=3000)
    parser.add_argument("--review-batch-size", type=int, default=DEFAULT_REVIEW_BATCH_SIZE)
    parser.add_argument("--review-workers", type=int, default=DEFAULT_REVIEW_WORKERS)
    parser.add_argument("--embedding-workers", type=int, default=DEFAULT_EMBEDDING_WORKERS)
    parser.add_argument("--similarity-threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--min-merge-confidence", type=float, default=DEFAULT_MIN_MERGE_CONFIDENCE)
    parser.add_argument("--min-concept-confidence", type=float, default=DEFAULT_MIN_CONCEPT_CONFIDENCE)
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--codex-model", default=DEFAULT_CODEX_MODEL)
    parser.add_argument("--codex-reasoning-effort", default=DEFAULT_CODEX_REASONING_EFFORT)
    parser.add_argument("--codex-timeout-seconds", type=int, default=DEFAULT_CODEX_TIMEOUT_SECONDS)
    parser.add_argument("--include-source-candidates", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rule-only", action="store_true")
    args = parser.parse_args()
    if not args.rule_only and args.llm_candidate_provider == "llm" and int(args.max_llm_candidate_batches) <= 0:
        parser.error("--llm-candidate-provider llm requires --max-llm-candidate-batches > 0")
    if int(args.review_batch_size) <= 0:
        parser.error("--review-batch-size must be > 0")
    if int(args.review_workers) <= 0:
        parser.error("--review-workers must be > 0")
    if int(args.embedding_workers) <= 0:
        parser.error("--embedding-workers must be > 0")
    if int(args.codex_timeout_seconds) <= 0:
        parser.error("--codex-timeout-seconds must be > 0")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
