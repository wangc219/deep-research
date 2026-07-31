"""Phase 1 runner: extract all chunks into a minimal SQLite table.

This CLI keeps Phase 1 storage small while delegating reusable extraction
contracts, prompts, adapters, and LLM client code to ``src/knowledgegraph``:
- no governance store
- no graph database
- one SQLite table named extractions with seven fields
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.adapters import (  # noqa: E402
    LLMSevenRelationSchemaGuidedAdapter,
    LLMSchemaGuidedAdapter,
    SchemaGuidedOfflineAdapter,
)
from knowledgegraph.extraction.llm_client import LLMConfig, OpenAICompatibleClient  # noqa: E402
from knowledgegraph.extraction.models import DocumentChunk, ExtractionResult, load_chunks  # noqa: E402
from knowledgegraph.extraction.schema import SCHEMA_VERSION  # noqa: E402
from knowledgegraph.material_governance.extraction.phase1_sqlite import (  # noqa: E402
    ensure_phase1_schema,
    existing_status_for_chunk,
    should_replace_status,
    summarize_phase1,
    write_phase1_chunk_row,
)


DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr"
    / "chunks.jsonl"
)
DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase1_all_chunks"
    / "phase1_extractions.sqlite"
)


def main() -> int:
    args = _parse_args()
    chunks_path = Path(args.chunks).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = load_chunks(chunks_path)
    if not chunks:
        raise SystemExit(f"No chunks found in {chunks_path}")
    selected_chunks = chunks[: args.limit] if args.limit else chunks

    if args.summary_only:
        with sqlite3.connect(db_path) as conn:
            ensure_schema(conn)
            summary = summarize(conn)
        summary.update(
            {
                "chunks_path": str(chunks_path),
                "db_path": str(db_path),
                "input_chunk_count": len(chunks),
                "selected_chunk_count": len(selected_chunks),
                "processed_this_run": 0,
                "mode": args.mode,
                "prompt_version": args.prompt_version,
            }
        )
        print("phase1_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    client: OpenAICompatibleClient | None = None
    llm_config: LLMConfig | None = None
    if args.mode == "llm":
        llm_config = LLMConfig.from_env()
        if args.workers <= 1:
            client = OpenAICompatibleClient(llm_config)
            adapter = build_llm_adapter(client, prompt_version=args.prompt_version)
        else:
            adapter = SchemaGuidedOfflineAdapter()
    else:
        adapter = SchemaGuidedOfflineAdapter()

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        processed = run_chunks(
            conn=conn,
            chunks=selected_chunks,
            adapter=adapter,
            client=client,
            force=args.force,
            retry_failed=args.retry_failed,
            max_new=args.max_new,
            workers=args.workers,
            batch_size=args.batch_size,
            mode=args.mode,
            llm_config=llm_config,
            prompt_version=args.prompt_version,
        )
        summary = summarize(conn)

    summary.update(
        {
            "chunks_path": str(chunks_path),
            "db_path": str(db_path),
            "input_chunk_count": len(chunks),
            "selected_chunk_count": len(selected_chunks),
            "processed_this_run": processed,
            "mode": args.mode,
            "workers": args.workers,
            "batch_size": args.batch_size,
            "prompt_version": args.prompt_version,
        }
    )
    print("phase1_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def ensure_schema(conn: sqlite3.Connection) -> None:
    ensure_phase1_schema(conn)


def run_chunks(
    conn: sqlite3.Connection,
    chunks: list[DocumentChunk],
    adapter: Any,
    client: OpenAICompatibleClient | None,
    force: bool,
    retry_failed: bool,
    max_new: int,
    workers: int = 1,
    batch_size: int = 0,
    mode: str = "offline",
    llm_config: LLMConfig | None = None,
    prompt_version: str = "v3",
) -> int:
    pending: list[tuple[int, DocumentChunk, str | None]] = []
    for index, chunk in enumerate(chunks, start=1):
        if max_new and len(pending) >= max_new:
            break
        existing_status = _existing_status(conn, chunk.chunk_id)
        if existing_status and not _should_replace(existing_status, force, retry_failed):
            print(
                f"[{index}/{len(chunks)}] skip {chunk.chunk_id} existing={existing_status}",
                flush=True,
            )
            continue
        pending.append((index, chunk, existing_status))

    if workers <= 1:
        return _run_chunks_sequential(
            conn=conn,
            chunks=pending,
            total_count=len(chunks),
            adapter=adapter,
            client=client,
        )

    return _run_chunks_concurrent(
        conn=conn,
        chunks=pending,
        total_count=len(chunks),
        workers=workers,
        batch_size=batch_size,
        mode=mode,
        llm_config=llm_config,
        prompt_version=prompt_version,
    )


def _run_chunks_sequential(
    conn: sqlite3.Connection,
    chunks: list[tuple[int, DocumentChunk, str | None]],
    total_count: int,
    adapter: Any,
    client: OpenAICompatibleClient | None,
) -> int:
    processed = 0
    for index, chunk, existing_status in chunks:
        row = _extract_chunk_row(chunk=chunk, adapter=adapter, client=client)
        _write_chunk_row(
            conn=conn,
            chunk=chunk,
            existing_status=existing_status,
            row=row,
        )
        processed += 1
        print(
            f"[{index}/{total_count}] wrote {chunk.chunk_id} status={row['status']}",
            flush=True,
        )
    return processed


def _run_chunks_concurrent(
    conn: sqlite3.Connection,
    chunks: list[tuple[int, DocumentChunk, str | None]],
    total_count: int,
    workers: int,
    batch_size: int,
    mode: str,
    llm_config: LLMConfig | None,
    prompt_version: str,
) -> int:
    if not chunks:
        return 0

    processed = 0
    effective_batch_size = batch_size if batch_size > 0 else len(chunks)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for batch_start in range(0, len(chunks), effective_batch_size):
            batch = chunks[batch_start : batch_start + effective_batch_size]
            futures = {
                executor.submit(
                    _extract_chunk_with_worker_adapter,
                    chunk,
                    mode,
                    llm_config,
                    prompt_version,
                ): (index, chunk, existing_status)
                for index, chunk, existing_status in batch
            }
            for future in as_completed(futures):
                index, chunk, existing_status = futures[future]
                row = future.result()
                _write_chunk_row(
                    conn=conn,
                    chunk=chunk,
                    existing_status=existing_status,
                    row=row,
                )
                processed += 1
                print(
                    f"[{index}/{total_count}] wrote {chunk.chunk_id} status={row['status']}",
                    flush=True,
                )
    return processed


def _extract_chunk_with_worker_adapter(
    chunk: DocumentChunk,
    mode: str,
    llm_config: LLMConfig | None,
    prompt_version: str = "v3",
) -> dict[str, Any]:
    client: OpenAICompatibleClient | None = None
    try:
        if mode == "llm":
            client = OpenAICompatibleClient(llm_config or LLMConfig.from_env())
            adapter = build_llm_adapter(client, prompt_version=prompt_version)
        else:
            adapter = SchemaGuidedOfflineAdapter()
        return _extract_chunk_row(chunk=chunk, adapter=adapter, client=client)
    except Exception as exc:  # noqa: BLE001 - Phase 1 records worker setup failures.
        payload = _error_payload(exc)
        return {
            "chunk_id": chunk.chunk_id,
            "raw_llm": _raw_llm(client, payload),
            "payload": payload,
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
        }


def _extract_chunk_row(
    chunk: DocumentChunk,
    adapter: Any,
    client: OpenAICompatibleClient | None,
) -> dict[str, Any]:
    schema_version = SCHEMA_VERSION
    try:
        result = adapter.extract(chunk)
        if result is None:
            payload = {"error_type": "NoResult", "error_message": "adapter returned None"}
            status = "failed"
        else:
            payload = result.to_dict()
            schema_version = _schema_version(result)
            status = _status_for_result(result, chunk)
        raw_llm = _raw_llm(client, payload)
    except json.JSONDecodeError as exc:
        payload = _error_payload(exc)
        raw_llm = _raw_llm(client, payload)
        status = "invalid_json"
    except Exception as exc:  # noqa: BLE001 - Phase 1 records failures, it does not stop the batch.
        payload = _error_payload(exc)
        raw_llm = _raw_llm(client, payload)
        status = "failed"
    return {
        "chunk_id": chunk.chunk_id,
        "raw_llm": raw_llm,
        "payload": payload,
        "schema_version": schema_version,
        "status": status,
    }


def build_llm_adapter(
    client: OpenAICompatibleClient,
    prompt_version: str = "v3",
) -> LLMSchemaGuidedAdapter:
    if prompt_version == "v4":
        return LLMSevenRelationSchemaGuidedAdapter(client)
    return LLMSchemaGuidedAdapter(client)


def _write_chunk_row(
    conn: sqlite3.Connection,
    chunk: DocumentChunk,
    existing_status: str | None,
    row: dict[str, Any],
) -> None:
    write_phase1_chunk_row(
        conn=conn,
        chunk_id=chunk.chunk_id,
        existing_status=existing_status,
        row=row,
    )


def summarize(conn: sqlite3.Connection) -> dict[str, Any]:
    return summarize_phase1(conn)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 1 all-chunk extraction into one SQLite table.",
    )
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--mode", choices=["llm", "offline"], default="llm")
    parser.add_argument(
        "--prompt-version",
        choices=["v3", "v4"],
        default="v3",
        help=(
            "LLM prompt variant. v3 keeps the historical 15-relation prompt; "
            "v4 asks the model to emit only the seven prediction-oriented relations."
        ),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-new", type=int, default=0)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent extraction workers. SQLite writes remain serialized.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Submit at most this many chunks per batch; 0 submits all pending chunks.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Replace existing failed/invalid_json rows; successful rows are skipped.",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.batch_size < 0:
        parser.error("--batch-size must be >= 0")
    return args


def _existing_status(conn: sqlite3.Connection, chunk_id: str) -> str | None:
    return existing_status_for_chunk(conn, chunk_id)


def _should_replace(existing_status: str, force: bool, retry_failed: bool) -> bool:
    return should_replace_status(existing_status, force, retry_failed)


def _insert_row(
    conn: sqlite3.Connection,
    chunk_id: str,
    raw_llm: str,
    payload: dict[str, Any],
    schema_version: str,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO extractions (
            chunk_id,
            raw_llm,
            payload_json,
            schema_version,
            status,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            raw_llm,
            json.dumps(payload, ensure_ascii=False),
            schema_version,
            status,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _status_for_result(result: ExtractionResult, chunk: DocumentChunk) -> str:
    structural_warnings = result.validate(chunk.text)
    if structural_warnings or result.warnings:
        return "validation_warning"
    return "success"


def _schema_version(result: ExtractionResult) -> str:
    if result.trace and result.trace.schema_version:
        return result.trace.schema_version
    return SCHEMA_VERSION


def _raw_llm(
    client: OpenAICompatibleClient | None,
    payload: dict[str, Any],
) -> str:
    if client and client.last_content:
        return client.last_content
    if client and client.last_raw_response:
        return client.last_raw_response
    return json.dumps(payload, ensure_ascii=False)


def _error_payload(exc: Exception) -> dict[str, str]:
    return {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


if __name__ == "__main__":
    raise SystemExit(main())
