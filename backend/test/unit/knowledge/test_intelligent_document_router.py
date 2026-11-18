"""智能解析路由的本地决策、委派和谱系测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError, PdfStreamError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from platform_core.knowledge.parser.base import DocumentParserException
from platform_core.knowledge.parser.factory import DocumentProcessorFactory
from platform_core.knowledge.parser.intelligent_router import (
    IntelligentDocumentRouter,
    PDFRoutingDecision,
    inspect_pdf_routing,
)
from platform_core.knowledge.parser.result import ParsedDocument


def _write_pdf(path: Path, *, text: str | None = None) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if text is not None:
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
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 10 Tf 30 750 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def _write_two_column_pdf(path: Path) -> None:
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
    stream = DecodedStreamObject()
    stream.set_data(
        "\n".join(
            [
                "BT /F1 10 Tf 40 700 Td (Left column technical content line one) Tj ET",
                "BT /F1 10 Tf 40 680 Td (Left column technical content line two) Tj ET",
                "BT /F1 10 Tf 330 700 Td (Right column technical content line one) Tj ET",
                "BT /F1 10 Tf 330 680 Td (Right column technical content line two) Tj ET",
            ]
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def test_real_two_column_pdf_is_routed_as_complex_layout(tmp_path: Path) -> None:
    source = tmp_path / "two-column.pdf"
    _write_two_column_pdf(source)

    decision = inspect_pdf_routing(source)

    assert decision.route == "complex_layout"
    assert decision.text_page_ratio == 1.0
    assert decision.column_page_ratio == 1.0


def test_digital_pdf_uses_native_text_without_loading_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "digital.pdf"
    document_text = "Searchable technical document text. " * 8
    _write_pdf(source, text=document_text)
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "get_processor",
        lambda *args, **kwargs: pytest.fail("数字 PDF 不应加载 OCR 处理器"),
    )

    result = IntelligentDocumentRouter().process_file_result(str(source))

    assert "Searchable technical document text" in result.markdown
    assert result.parser_name == "native_pdf"
    assert result.source_metadata["routing_decision"] == "native_text"
    assert result.source_metadata["routing_engine"] == "native_pdf"
    assert document_text.strip() not in str(result.source_metadata)
    assert set(result.source_metadata["routing_features"]) == {
        "route",
        "total_pages",
        "sampled_pages",
        "text_page_ratio",
        "average_text_chars",
        "image_page_ratio",
        "column_page_ratio",
        "failed_sample_pages",
        "cid_glyph_pages",
        "trailing_data_recovered",
    }


def test_broken_sample_page_degrades_to_ocr_instead_of_failing_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "broken-stream.pdf"
    source.write_bytes(b"placeholder")

    class BrokenPage:
        def extract_text(self, **_kwargs):
            raise ValueError("broken private stream detail")

        def get(self, _key):
            return None

    monkeypatch.setattr(
        "platform_core.knowledge.parser.intelligent_router.PdfReader",
        lambda _source: SimpleNamespace(pages=[BrokenPage()]),
    )

    decision = inspect_pdf_routing(source)

    assert decision.route == "scanned_or_mixed"
    assert decision.failed_sample_pages == 1
    assert decision.as_metadata()["failed_sample_pages"] == 1


def test_cid_glyph_encoded_text_layer_degrades_to_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "cid-glyphs.pdf"
    source.write_bytes(b"placeholder")

    class CIDGlyphPage:
        def extract_text(self, **_kwargs):
            return " ".join(f"/G{index:02X}" for index in range(64))

        def get(self, _key):
            return None

    monkeypatch.setattr(
        "platform_core.knowledge.parser.intelligent_router.PdfReader",
        lambda _source: SimpleNamespace(pages=[CIDGlyphPage()]),
    )
    monkeypatch.setattr("platform_core.knowledge.parser.intelligent_router._extract_layout_text", lambda _page: "")

    decision = inspect_pdf_routing(source)

    assert decision.route == "scanned_or_mixed"
    assert decision.text_page_ratio == 0.0
    assert decision.cid_glyph_pages == 1
    assert decision.as_metadata()["cid_glyph_pages"] == 1


def test_pdf_with_download_trace_after_eof_is_recovered_without_modifying_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "traced.pdf"
    _write_pdf(source, text="Searchable technical document text. " * 8)
    original = source.read_bytes()
    source.write_bytes(original + b"transferOut:download-trace")

    def reader(stream):
        if not isinstance(stream, BytesIO):
            raise PdfStreamError("trailing trace")
        return SimpleNamespace(pages=[])

    monkeypatch.setattr("platform_core.knowledge.parser.intelligent_router.PdfReader", reader)

    decision = inspect_pdf_routing(source)

    assert decision.trailing_data_recovered is True
    assert source.read_bytes() == original + b"transferOut:download-trace"


def test_invalid_page_tree_has_stable_error_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "invalid-pages.pdf"
    source.write_bytes(b"placeholder")

    class InvalidPages:
        def __len__(self):
            raise PdfReadError("private page tree detail")

    monkeypatch.setattr(
        "platform_core.knowledge.parser.intelligent_router.PdfReader",
        lambda _source: SimpleNamespace(pages=InvalidPages()),
    )

    with pytest.raises(DocumentParserException) as captured:
        inspect_pdf_routing(source)

    assert captured.value.status_code == "invalid_pdf_structure"


def test_scanned_pdf_delegates_to_local_rapid_ocr_with_resolved_params(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "scanned.pdf"
    _write_pdf(source)
    captured: dict[str, object] = {}

    def get_processor(engine_id: str, **kwargs):
        captured["engine_id"] = engine_id
        captured["kwargs"] = kwargs

        def process_file_result(file_path: str, params: dict[str, object]) -> ParsedDocument:
            captured["file_path"] = file_path
            captured["params"] = params
            return ParsedDocument(markdown="本地 OCR 结果", parser_name=engine_id)

        return SimpleNamespace(process_file_result=process_file_result)

    monkeypatch.setattr(DocumentProcessorFactory, "get_processor", get_processor)
    router = IntelligentDocumentRouter(engine_kwargs={"rapid_ocr": {"model_dir": "/local/model"}})

    result = router.process_file_result(str(source), {"ocr_engine": "auto", "trace_id": "run-1"})

    assert captured == {
        "engine_id": "rapid_ocr",
        "kwargs": {"model_dir": "/local/model"},
        "file_path": str(source),
        "params": {"ocr_engine": "rapid_ocr", "trace_id": "run-1"},
    }
    assert result.source_metadata["routing_decision"] == "scanned_or_mixed"
    assert result.source_metadata["routing_engine"] == "rapid_ocr"


def test_complex_pdf_delegates_to_configured_pp_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "complex.pdf"
    _write_pdf(source, text="layout")
    decision = PDFRoutingDecision(
        route="complex_layout",
        total_pages=1,
        sampled_pages=1,
        text_page_ratio=1.0,
        average_text_chars=500.0,
        image_page_ratio=0.5,
        column_page_ratio=0.0,
    )
    monkeypatch.setattr(
        "platform_core.knowledge.parser.intelligent_router.inspect_pdf_routing",
        lambda _path: decision,
    )
    captured: dict[str, object] = {}

    def get_processor(engine_id: str, **kwargs):
        captured.update(engine_id=engine_id, kwargs=kwargs)
        return SimpleNamespace(
            process_file_result=lambda _file_path, params: (
                captured.update(params=params) or ParsedDocument(markdown="结构化版面结果", parser_name=engine_id)
            )
        )

    monkeypatch.setattr(DocumentProcessorFactory, "get_processor", get_processor)
    router = IntelligentDocumentRouter(
        complex_engine="pp_structure_v3_ocr",
        engine_kwargs={"pp_structure_v3_ocr": {"server_url": "http://paddlex.local:8080"}},
    )

    result = router.process_file_result(str(source), {"ocr_engine": "auto"})

    assert captured == {
        "engine_id": "pp_structure_v3_ocr",
        "kwargs": {"server_url": "http://paddlex.local:8080"},
        "params": {"ocr_engine": "pp_structure_v3_ocr"},
    }
    assert result.parser_name == "pp_structure_v3_ocr"
    assert result.source_metadata["routing_decision"] == "complex_layout"
    assert result.source_metadata["routing_features"]["image_page_ratio"] == 0.5


def test_image_delegation_records_route_without_persisting_image_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"sensitive-image-bytes")
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "get_processor",
        lambda engine_id, **_kwargs: SimpleNamespace(
            process_file_result=lambda _file_path, _params: ParsedDocument(
                markdown="图片识别结果",
                parser_name=engine_id,
            )
        ),
    )

    result = IntelligentDocumentRouter().process_file_result(str(source))

    assert result.source_metadata == {
        "routing_mode": "auto",
        "routing_decision": "image_ocr",
        "routing_engine": "rapid_ocr",
    }
    assert "sensitive-image-bytes" not in str(result.source_metadata)


def test_health_is_degraded_when_configured_complex_engine_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def check_health(engine_id: str, **kwargs) -> dict[str, str]:
        calls.append((engine_id, kwargs))
        if engine_id == "rapid_ocr":
            return {"status": "healthy", "message": "ok"}
        return {
            "status": "unavailable",
            "message": "offline",
            "server_url": "http://must-not-leak.local",
        }

    monkeypatch.setattr(DocumentProcessorFactory, "check_health", check_health)
    router = IntelligentDocumentRouter(
        complex_engine="pp_structure_v3_ocr",
        engine_kwargs={"pp_structure_v3_ocr": {"server_url": "http://paddlex.local:8080"}},
    )

    result = router.check_health()

    assert calls == [
        ("rapid_ocr", {}),
        ("pp_structure_v3_ocr", {"server_url": "http://paddlex.local:8080"}),
    ]
    assert result == {
        "status": "degraded",
        "message": "智能路由仅剩非结构化回退路径",
        "details": {
            "native_engine": "native_pdf",
            "scan_engine": "rapid_ocr",
            "scan_status": "healthy",
            "complex_engines": ["pp_structure_v3_ocr", "rapid_ocr"],
            "complex_statuses": {
                "pp_structure_v3_ocr": "unavailable",
                "rapid_ocr": "healthy",
            },
        },
    }
    assert "must-not-leak" not in str(result)


def test_health_checks_docling_and_shared_local_engine_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def check_health(engine_id: str, **_kwargs) -> dict[str, str]:
        calls.append(engine_id)
        return {"status": "healthy", "message": "ok"}

    monkeypatch.setattr(DocumentProcessorFactory, "check_health", check_health)

    result = IntelligentDocumentRouter().check_health()

    assert calls == ["rapid_ocr", "docling_pdf"]
    assert result["status"] == "healthy"


def test_complex_route_falls_back_without_leaking_failure_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "complex-fallback.pdf"
    _write_pdf(source, text="layout")
    monkeypatch.setattr(
        "platform_core.knowledge.parser.intelligent_router.inspect_pdf_routing",
        lambda _path: PDFRoutingDecision(
            route="complex_layout",
            total_pages=1,
            sampled_pages=1,
            text_page_ratio=1.0,
            average_text_chars=500.0,
            image_page_ratio=0.5,
            column_page_ratio=0.0,
        ),
    )

    def get_processor(engine_id: str, **_kwargs):
        if engine_id == "pp_structure_v3_ocr":
            from platform_core.knowledge.parser.base import DocumentParserException

            return SimpleNamespace(
                process_file_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    DocumentParserException(
                        "private upstream address must not leak",
                        engine_id,
                        "unavailable",
                    )
                )
            )
        return SimpleNamespace(
            process_file_result=lambda *_args, **_kwargs: ParsedDocument(
                markdown="Docling local result",
                parser_name=engine_id,
            )
        )

    monkeypatch.setattr(DocumentProcessorFactory, "get_processor", get_processor)
    router = IntelligentDocumentRouter(complex_engines=("pp_structure_v3_ocr", "docling_pdf", "rapid_ocr"))

    result = router.process_file_result(str(source), {"ocr_engine": "auto"})

    assert result.parser_name == "docling_pdf"
    assert result.source_metadata["routing_engine"] == "docling_pdf"
    assert result.source_metadata["routing_attempts"] == [
        {
            "engine": "pp_structure_v3_ocr",
            "status": "failed",
            "error_code": "unavailable",
        },
        {"engine": "docling_pdf", "status": "succeeded"},
    ]
    assert "private upstream" not in str(result.source_metadata)
