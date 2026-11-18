"""Pilot 向量入库的文件、Chunk 与原文 Span 一致性校验。"""

from __future__ import annotations

from collections import Counter
from typing import Any


def validate_indexed_document(
    *,
    file_id: str,
    status: str,
    declared_chunk_count: int,
    source_text: str,
    chunks: list[Any],
) -> dict[str, Any]:
    """校验单篇文档的索引状态、Chunk 数和原文回切。"""
    issues: list[dict[str, Any]] = []
    if status != "indexed":
        issues.append({"code": "file_not_indexed", "actual": status})
    if declared_chunk_count != len(chunks):
        issues.append(
            {
                "code": "declared_chunk_count_mismatch",
                "declared": declared_chunk_count,
                "actual": len(chunks),
            }
        )
    if "\x00" in source_text:
        issues.append({"code": "source_contains_nul", "count": source_text.count("\x00")})

    indexes = [int(chunk.chunk_index) for chunk in chunks]
    if indexes != list(range(len(chunks))):
        issues.append({"code": "chunk_indexes_not_contiguous", "indexes": indexes})

    rebuildable_chunks = 0
    for chunk in chunks:
        start = chunk.start_char_pos
        end = chunk.end_char_pos
        if start is None or end is None:
            issues.append({"code": "missing_chunk_span", "chunk_id": chunk.chunk_id})
            continue
        if start < 0 or end <= start or end > len(source_text):
            issues.append(
                {
                    "code": "invalid_chunk_span",
                    "chunk_id": chunk.chunk_id,
                    "start": start,
                    "end": end,
                    "source_chars": len(source_text),
                }
            )
            continue
        if source_text[start:end] != chunk.content:
            issues.append(
                {
                    "code": "chunk_source_mismatch",
                    "chunk_id": chunk.chunk_id,
                    "start": start,
                    "end": end,
                }
            )
            continue
        rebuildable_chunks += 1

    return {
        "file_id": file_id,
        "status": status,
        "source_characters": len(source_text),
        "chunk_count": len(chunks),
        "rebuildable_chunks": rebuildable_chunks,
        "ready": not issues,
        "issues": issues,
    }


def summarize_index_validation(
    documents: list[dict[str, Any]],
    *,
    expected_file_count: int | None = None,
    vector_count: int | None = None,
) -> dict[str, Any]:
    """汇总文档校验结果并给出 fail-closed 准入结论。"""
    issue_counts = Counter(str(issue["code"]) for document in documents for issue in document.get("issues", []))
    file_count_matches = expected_file_count is None or len(documents) == expected_file_count
    total_chunks = sum(int(document.get("chunk_count") or 0) for document in documents)
    rebuildable_chunks = sum(int(document.get("rebuildable_chunks") or 0) for document in documents)
    vector_count_matches = vector_count is None or vector_count == total_chunks
    ready = file_count_matches and vector_count_matches and all(bool(document.get("ready")) for document in documents)
    return {
        "ready": ready,
        "expected_file_count": expected_file_count,
        "file_count": len(documents),
        "file_count_matches": file_count_matches,
        "indexed_file_count": sum(document.get("status") == "indexed" for document in documents),
        "chunk_count": total_chunks,
        "vector_count": vector_count,
        "vector_count_matches": vector_count_matches,
        "rebuildable_chunk_count": rebuildable_chunks,
        "span_rebuild_rate": rebuildable_chunks / total_chunks if total_chunks else 0.0,
        "issue_counts": dict(sorted(issue_counts.items())),
        "failed_files": [document["file_id"] for document in documents if not document.get("ready")],
    }
