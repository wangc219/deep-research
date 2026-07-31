"""Prepare standardized chunks from PDFs via the existing MinerU pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from models import DocumentChunk, write_jsonl


DEFAULT_SOURCE_ROOT = "data/raw/zsdd/2026-02/papers"
DEFAULT_WORK_ROOT = "data/processed/extraction_experiments"
DEFAULT_DATASET_NAME = "zsdd_2026_02"


def main() -> int:
    args = _parse_args()
    source_root = Path(args.source_root).expanduser().resolve()
    dataset_root = Path(args.work_root).expanduser().resolve() / args.dataset_name
    raw_markdown_root = (
        Path(args.raw_markdown_root).expanduser().resolve()
        if args.raw_markdown_root
        else dataset_root / "mineru_raw"
    )
    artifact_root = (
        Path(args.artifact_root).expanduser().resolve()
        if args.artifact_root
        else dataset_root / "mineru_artifacts"
    )
    chunks_output = (
        Path(args.chunks_output).expanduser().resolve()
        if args.chunks_output
        else dataset_root / "chunks.jsonl"
    )

    mineru_summary: dict[str, Any] | None = None
    if not args.skip_mineru:
        mineru_summary = _run_mineru(
            source_root=source_root,
            raw_markdown_root=raw_markdown_root,
            artifact_root=artifact_root,
            args=args,
        )

    chunks = build_chunks_from_markdown_root(
        markdown_root=raw_markdown_root,
        source_root=source_root,
        max_chars=args.max_chars,
    )
    if args.chunk_limit and args.chunk_limit > 0:
        chunks = chunks[: args.chunk_limit]

    write_jsonl(chunks_output, [chunk.to_dict() for chunk in chunks])
    report = {
        "source_root": str(source_root),
        "raw_markdown_root": str(raw_markdown_root),
        "artifact_root": str(artifact_root),
        "chunks_output": str(chunks_output),
        "chunk_count": len(chunks),
        "mineru_options": {
            "enable_ocr": args.enable_ocr,
            "model_version": args.model_version,
            "language": args.language,
            "enable_table": not args.disable_tables,
            "enable_formula": not args.disable_formulas,
        },
        "mineru_summary": mineru_summary,
    }
    report_path = dataset_root / "prepare_chunks_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("prepare_chunks_summary=" + json.dumps(report, ensure_ascii=False))
    if not chunks:
        print("prepare_chunks_error=no chunks generated")
        return 2
    return 0


def build_chunks_from_markdown_root(
    markdown_root: Path,
    source_root: Path,
    max_chars: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    markdown_paths = sorted(markdown_root.rglob("*.md"))
    for markdown_path in markdown_paths:
        text = markdown_path.read_text(encoding="utf-8")
        document_id = _document_id(markdown_root, markdown_path)
        title = markdown_path.stem
        source_pdf = _infer_source_pdf(source_root, markdown_root, markdown_path)
        chunks.extend(
            _chunk_markdown(
                document_id=document_id,
                title=title,
                source_path=str(source_pdf) if source_pdf else "",
                markdown_text=text,
                max_chars=max_chars,
            )
        )
    return chunks


def _run_mineru(
    source_root: Path,
    raw_markdown_root: Path,
    artifact_root: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    import requests as requests_lib
    import mineru_api_batch

    if args.disable_env_proxy:
        _clear_proxy_environment()
        mineru_api_batch.requests.Session = _no_proxy_session_factory(requests_lib)

    return mineru_api_batch.run_batch(
        source_root=str(source_root),
        output_root=str(raw_markdown_root),
        base_url=args.base_url,
        token_env_var=args.token_env_var,
        model_version=args.model_version,
        language=args.language,
        enable_table=not args.disable_tables,
        enable_formula=not args.disable_formulas,
        is_ocr=args.enable_ocr,
        batch_size=args.batch_size,
        limit=args.limit,
        force=args.force_mineru,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        artifact_root=str(artifact_root),
    )


def _chunk_markdown(
    document_id: str,
    title: str,
    source_path: str,
    markdown_text: str,
    max_chars: int,
) -> list[DocumentChunk]:
    blocks = _markdown_blocks(markdown_text)
    chunks: list[DocumentChunk] = []
    section_title = ""
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        chunk_text = "\n\n".join(buffer).strip()
        if not chunk_text:
            buffer.clear()
            return
        index = len(chunks) + 1
        chunks.append(
            DocumentChunk(
                document_id=document_id,
                chunk_id=f"{document_id}-chunk-{index:04d}",
                text=chunk_text,
                source_path=source_path,
                page=None,
                section_title=section_title,
                metadata={
                    "title": title,
                    "source_type": "paper",
                    "parser": "mineru",
                },
            )
        )
        buffer.clear()

    for block in blocks:
        if block.startswith("#"):
            flush()
            section_title = block.lstrip("#").strip()
            continue
        if sum(len(item) for item in buffer) + len(block) > max_chars:
            flush()
        if len(block) <= max_chars:
            buffer.append(block)
        else:
            flush()
            for part in _split_long_text(block, max_chars):
                buffer.append(part)
                flush()
    flush()
    return chunks


def _markdown_blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_blocks = re.split(r"\n\s*\n+", normalized)
    return [block.strip() for block in raw_blocks if block.strip()]


def _split_long_text(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        parts.append(text[start : start + max_chars].strip())
        start += max_chars
    return [part for part in parts if part]


def _document_id(markdown_root: Path, markdown_path: Path) -> str:
    relative = markdown_path.relative_to(markdown_root).with_suffix("")
    digest = hashlib.sha1(relative.as_posix().encode("utf-8")).hexdigest()[:10]
    safe_stem = re.sub(r"[^0-9A-Za-z_\-]+", "_", relative.stem).strip("_")
    return f"doc-{safe_stem[:40]}-{digest}"


def _infer_source_pdf(
    source_root: Path,
    markdown_root: Path,
    markdown_path: Path,
) -> Path | None:
    relative = markdown_path.relative_to(markdown_root).with_suffix(".pdf")
    candidate = source_root / relative
    if candidate.exists():
        return candidate
    stem_matches = sorted(source_root.rglob(f"{markdown_path.stem}.pdf"))
    return stem_matches[0] if stem_matches else None


def _clear_proxy_environment() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)


def _no_proxy_session_factory(requests_lib):
    def create_session():
        session = requests_lib.sessions.Session()
        session.trust_env = False
        return session

    return create_session


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert PDFs with MinerU and prepare standardized chunks JSONL.",
    )
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--work-root", default=DEFAULT_WORK_ROOT)
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--raw-markdown-root")
    parser.add_argument("--artifact-root")
    parser.add_argument("--chunks-output")
    parser.add_argument("--skip-mineru", action="store_true")
    parser.add_argument("--force-mineru", action="store_true")
    parser.add_argument("--base-url", default="https://mineru.net")
    parser.add_argument("--token-env-var", default="MINERU_TOKEN")
    parser.add_argument("--model-version", default="vlm")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--disable-tables", action="store_true")
    parser.add_argument("--disable-formulas", action="store_true")
    parser.add_argument(
        "--enable-ocr",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable MinerU OCR. Default is enabled; use --no-enable-ocr only for controlled comparison.",
    )
    parser.add_argument(
        "--disable-env-proxy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Disable proxy environment variables before calling MinerU API.",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval-seconds", type=int, default=10)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--chunk-limit", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
