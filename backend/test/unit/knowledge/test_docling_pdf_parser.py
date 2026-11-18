"""Docling Slim 本地 PDF 版面解析真实文件测试。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from platform_core.knowledge.parser.base import DocumentParserException
import platform_core.knowledge.parser.docling_pdf as docling_pdf_module
from platform_core.knowledge.parser.docling_pdf import DoclingPdfParser
from platform_core.knowledge.parser.intelligent_router import IntelligentDocumentRouter


def _write_complex_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = "\n".join(
        [
            "BT /F1 15 Tf 40 760 Td (Complex Layout Report) Tj ET",
            "BT /F1 10 Tf 40 700 Td (Left column line one) Tj ET",
            "BT /F1 10 Tf 40 680 Td (Left column line two) Tj ET",
            "BT /F1 10 Tf 330 700 Td (Right column line one) Tj ET",
            "BT /F1 10 Tf 330 680 Td (Right column line two) Tj ET",
            "40 560 m 560 560 l 560 480 l 40 480 l h S",
            "40 520 m 560 520 l S",
            "300 560 m 300 480 l S",
            "BT /F1 10 Tf 60 540 Td (Metric) Tj ET",
            "BT /F1 10 Tf 330 540 Td (Value) Tj ET",
            "BT /F1 10 Tf 60 500 Td (Range) Tj ET",
            "BT /F1 10 Tf 330 500 Td (120 km) Tj ET",
            "BT /F1 11 Tf 40 420 Td (F = m * a) Tj ET",
            "BT /F1 9 Tf 40 80 Td (Document footer) Tj ET",
        ]
    ).encode()
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def test_real_complex_pdf_preserves_columns_table_formula_and_source_map(tmp_path: Path) -> None:
    source = tmp_path / "complex-layout.pdf"
    _write_complex_pdf(source)

    result = DoclingPdfParser().process_file_result(str(source))

    assert result.parser_name == "docling_pdf"
    assert result.source_metadata["page_count"] == 1
    assert result.source_metadata["table_count"] == 1
    assert result.source_metadata["formula_count"] == 1
    assert result.markdown.index("Left column line two") < result.markdown.index("Right column line one")
    assert result.markdown.index("Right column line two") < result.markdown.index("Document footer")
    assert "| Metric | Value |" in result.markdown
    assert "| Range | 120 km |" in result.markdown

    layout_blocks = [
        block for block in result.blocks if block.source_metadata["position_kind"] == "docling_pdf_layout_block"
    ]
    assert {block.block_type for block in layout_blocks} >= {"paragraph", "table", "formula"}
    assert all(block.bbox is not None for block in layout_blocks)
    assert all(result.markdown[block.start_char : block.end_char] for block in layout_blocks)
    assert result.markdown[result.blocks[0].start_char : result.blocks[0].end_char] == result.markdown


def test_real_complex_pdf_routes_to_local_docling_without_service(tmp_path: Path) -> None:
    source = tmp_path / "complex-auto.pdf"
    _write_complex_pdf(source)

    result = IntelligentDocumentRouter().process_file_result(str(source))

    assert result.parser_name == "docling_pdf"
    assert result.source_metadata["routing_decision"] == "complex_layout"
    assert result.source_metadata["routing_engine"] == "docling_pdf"
    assert result.source_metadata["routing_attempts"] == [{"engine": "docling_pdf", "status": "succeeded"}]


def test_blank_pdf_fails_closed_for_ocr_fallback(tmp_path: Path) -> None:
    source = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(source)

    with pytest.raises(DocumentParserException) as exc_info:
        DoclingPdfParser().process_file_result(str(source))

    assert exc_info.value.status_code == "no_text_layer"


def test_health_checks_runtime_without_loading_document() -> None:
    health = DoclingPdfParser().check_health()

    assert health["status"] == "healthy"
    assert health["details"]["docling_slim_version"]
    assert health["details"]["pypdfium2_version"]


def test_pdfium_document_lifecycle_is_serialized_across_parser_instances(tmp_path, monkeypatch) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-test-first")
    second.write_bytes(b"%PDF-test-second")
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_extract(_self, _path):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with state_lock:
            active -= 1
        return (
            SimpleNamespace(
                fragments=(object(),),
                text_cell_count=0,
                table_count=0,
                formula_count=0,
            ),
        )

    monkeypatch.setattr(DoclingPdfParser, "_extract_pages", fake_extract)
    monkeypatch.setattr(docling_pdf_module, "_build_document", lambda _pages: ("parsed", ()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda path: DoclingPdfParser().process_file_result(str(path)).markdown,
                (first, second),
            )
        )

    assert results == ["parsed", "parsed"]
    assert maximum_active == 1
