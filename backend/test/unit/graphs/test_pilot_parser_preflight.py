from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from platform_core.knowledge.parser.intelligent_router import PDFRoutingDecision
from platform_core.knowledge.training.pilot_parser_preflight import (
    PARSER_PREFLIGHT_VERSION,
    build_parser_batch_plan,
    load_source_manifest,
    run_parser_preflight,
    write_parser_preflight_outputs,
)


def test_preflight_verifies_sha_classifies_and_builds_workload(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(source)
    manifest = [_manifest_row(source)]

    rows, report, batches = run_parser_preflight(
        manifest,
        inspector=lambda _path, **_kwargs: PDFRoutingDecision(
            route="scanned_or_mixed",
            total_pages=7,
            sampled_pages=7,
            text_page_ratio=0.2,
            average_text_chars=12.0,
            image_page_ratio=1.0,
            column_page_ratio=0.0,
        ),
    )

    assert rows[0]["sha256_verified"] is True
    assert rows[0]["route"] == "scanned_or_mixed"
    assert report["ready"] is True
    assert report["quality_signals"] == {
        "trailing_data_recovered_documents": 0,
        "documents_with_failed_sample_pages": 0,
        "failed_sample_pages": 0,
        "documents_with_cid_glyph_pages": 0,
        "cid_glyph_pages": 0,
    }
    assert report["workload_estimate"] == {
        "native_text_pages": 0,
        "structure_layout_pages": 0,
        "ocr_pages": 7,
        "cpu_weighted_page_units": 56,
    }
    assert batches[0]["document_ids"] == [manifest[0]["document_id"]]


def test_preflight_fails_closed_before_inspection_on_hash_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"not-the-manifest-content")
    manifest = [_manifest_row(source, digest="0" * 64)]

    rows, report, batches = run_parser_preflight(
        manifest,
        inspector=lambda *_args, **_kwargs: pytest.fail("指纹不一致时不得读取 PDF 页面"),
    )

    assert rows[0]["status"] == "failed"
    assert rows[0]["error_code"] == "content_sha256_mismatch"
    assert report["ready"] is False
    assert report["failure_counts"] == {"content_sha256_mismatch": 1}
    assert batches == []


def test_preflight_resume_reuses_only_same_version_parameters_and_verified_input(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    manifest = [_manifest_row(source)]
    resumed = {
        **manifest[0],
        "preflight_version": PARSER_PREFLIGHT_VERSION,
        "status": "succeeded",
        "route": "native_text",
        "sample_limit": 12,
        "sha256_verified": True,
        "total_pages": 3,
        "sampled_pages": 3,
        "failed_sample_pages": 0,
        "trailing_data_recovered": False,
        "elapsed_ms": 4,
    }

    rows, report, _batches = run_parser_preflight(
        manifest,
        resume_rows=[resumed],
        inspector=lambda *_args, **_kwargs: pytest.fail("断点结果应直接复用"),
    )

    assert rows == [resumed]
    assert report["reused_from_resume"] == 1


def test_preflight_checkpoints_each_new_result_but_not_reused_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    manifest = [_manifest_row(source)]
    checkpoints = []

    rows, _report, _batches = run_parser_preflight(
        manifest,
        inspector=lambda _path, **_kwargs: PDFRoutingDecision(
            route="native_text",
            total_pages=1,
            sampled_pages=1,
            text_page_ratio=1.0,
            average_text_chars=200.0,
            image_page_ratio=0.0,
            column_page_ratio=0.0,
        ),
        on_result=checkpoints.append,
    )

    assert checkpoints == rows


def test_manifest_and_outputs_are_sorted_and_round_trip(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(
        json.dumps(_manifest_row(second), ensure_ascii=False)
        + "\n"
        + json.dumps(_manifest_row(first), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    manifest = load_source_manifest(manifest_path)
    rows = [
        {
            **row,
            "preflight_version": PARSER_PREFLIGHT_VERSION,
            "status": "succeeded",
            "route": "native_text",
            "sample_limit": 12,
            "sha256_verified": True,
            "total_pages": 1,
            "sampled_pages": 1,
            "elapsed_ms": 0,
        }
        for row in reversed(manifest)
    ]
    batches = build_parser_batch_plan(rows, batch_size=1)
    paths = write_parser_preflight_outputs(tmp_path / "output", rows=rows, report={"ready": True}, batches=batches)

    loaded = load_source_manifest(paths["rows"])
    assert [row["document_id"] for row in loaded] == sorted(row["document_id"] for row in rows)
    assert paths["report"].read_text(encoding="utf-8") == '{\n  "ready": true\n}\n'


def _manifest_row(path: Path, *, digest: str | None = None) -> dict:
    resolved_digest = digest or hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "document_id": f"src_{resolved_digest}",
        "path": str(path),
        "content_sha256": resolved_digest,
        "file_size": path.stat().st_size,
        "source_mtime_ns": path.stat().st_mtime_ns,
    }
