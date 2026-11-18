from types import SimpleNamespace

from platform_core.knowledge.training.pilot_index_validation import (
    summarize_index_validation,
    validate_indexed_document,
)


def test_index_validation_accepts_exact_exclusive_end_spans() -> None:
    source = "雷达\n宽带接收组件"
    chunks = [
        SimpleNamespace(
            chunk_id="chunk-0",
            chunk_index=0,
            start_char_pos=0,
            end_char_pos=2,
            content="雷达",
        ),
        SimpleNamespace(
            chunk_id="chunk-1",
            chunk_index=1,
            start_char_pos=3,
            end_char_pos=len(source),
            content="宽带接收组件",
        ),
    ]

    document = validate_indexed_document(
        file_id="file-1",
        status="indexed",
        declared_chunk_count=2,
        source_text=source,
        chunks=chunks,
    )
    summary = summarize_index_validation([document], expected_file_count=1, vector_count=2)

    assert document["ready"] is True
    assert document["rebuildable_chunks"] == 2
    assert summary["ready"] is True
    assert summary["span_rebuild_rate"] == 1.0
    assert summary["vector_count_matches"] is True


def test_index_validation_fails_closed_on_missing_span_mismatch_and_nul() -> None:
    source = "雷达\x00组件"
    chunks = [
        SimpleNamespace(
            chunk_id="chunk-0",
            chunk_index=1,
            start_char_pos=None,
            end_char_pos=None,
            content="雷达",
        ),
        SimpleNamespace(
            chunk_id="chunk-1",
            chunk_index=3,
            start_char_pos=0,
            end_char_pos=2,
            content="错误",
        ),
    ]

    document = validate_indexed_document(
        file_id="file-1",
        status="parsed",
        declared_chunk_count=3,
        source_text=source,
        chunks=chunks,
    )
    summary = summarize_index_validation([document], expected_file_count=2, vector_count=1)

    assert document["ready"] is False
    assert summary["ready"] is False
    assert summary["file_count_matches"] is False
    assert summary["vector_count_matches"] is False
    assert summary["issue_counts"] == {
        "chunk_indexes_not_contiguous": 1,
        "chunk_source_mismatch": 1,
        "declared_chunk_count_mismatch": 1,
        "file_not_indexed": 1,
        "missing_chunk_span": 1,
        "source_contains_nul": 1,
    }
