from __future__ import annotations

import asyncio
import base64
import re
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import platform_core.knowledge.parser.factory as factory_module
import platform_core.knowledge.parser.unified as parser_unified
from docx import Document
from PIL import Image

from platform_core.knowledge.parser.base import DocumentParserException
from platform_core.knowledge.parser.capabilities import PARSER_CAPABILITIES
from platform_core.knowledge.parser.factory import DocumentProcessorFactory
from platform_core.knowledge.parser.mineru import MinerUParser
from platform_core.knowledge.parser.mineru_official import MinerUOfficialParser
from platform_core.knowledge.parser.pp_structure_v3 import PPStructureV3Parser
from platform_core.knowledge.parser.rapid_ocr import RapidOCRParser
from platform_core.knowledge.parser.result import ParsedBlock, ParsedDocument
from platform_core.services.ocr_service import parse_document, parse_document_with_metadata

PARSER_FIXTURES = Path(__file__).parents[2] / "data"


def test_factory_cache_key_does_not_contain_credential():
    cache_key = DocumentProcessorFactory._build_cache_key("deepseek_ocr", {"api_key": "top-secret"})

    assert cache_key.startswith("deepseek_ocr|")
    assert "top-secret" not in cache_key


def test_clear_cache_can_target_single_engine(monkeypatch: pytest.MonkeyPatch):
    first = SimpleNamespace()
    second = SimpleNamespace()
    monkeypatch.setattr(
        factory_module,
        "_PROCESSOR_CACHE",
        {"rapid_ocr|one": first, "mineru_ocr|two": second},
    )

    DocumentProcessorFactory.clear_cache("rapid_ocr")

    assert factory_module._PROCESSOR_CACHE == {"mineru_ocr|two": second}


def test_parser_capabilities_match_concrete_parser_classes():
    capability = PARSER_CAPABILITIES["rapid_ocr"]

    assert capability.service_name == RapidOCRParser.service_name
    assert capability.display_name == RapidOCRParser.display_name
    assert list(capability.supported_extensions) == RapidOCRParser.supported_extensions
    assert all(item.service_name == engine_id for engine_id, item in PARSER_CAPABILITIES.items())
    assert all(item.display_name for item in PARSER_CAPABILITIES.values())


def test_mineru_parser_normalizes_trailing_slash():
    parser = MinerUParser(server_url="http://mineru-api:30001/")

    assert parser.server_url == "http://mineru-api:30001"
    assert parser.parse_endpoint == "http://mineru-api:30001/file_parse"


def test_mineru_official_health_check_does_not_create_task(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "platform_core.knowledge.parser.mineru_official.requests.post",
        lambda *args, **kwargs: pytest.fail("健康检查不应创建解析任务"),
    )

    health = MinerUOfficialParser(api_key="test-key").check_health()

    assert health["status"] == "configured"


def test_mineru_official_parsing_uses_shared_zip_processor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "mineru.pdf"
    file_path.write_bytes(b"pdf")
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    parser = MinerUOfficialParser(api_key="test-key")

    monkeypatch.setattr(parser, "_upload_file", lambda *args, **kwargs: "batch-id")
    monkeypatch.setattr(
        parser,
        "_poll_batch_result",
        lambda *args, **kwargs: {"state": "done", "full_zip_url": "https://example.test/result.zip"},
    )
    monkeypatch.setattr(parser, "_download_zip", lambda *args, **kwargs: str(zip_path))
    processed_paths: list[str] = []

    def _process_zip_file(zip_file_path: str, **kwargs) -> str:
        del kwargs
        processed_paths.append(zip_file_path)
        return "parsed markdown"

    monkeypatch.setattr(
        "platform_core.knowledge.parser.mineru_official.process_zip_file_sync",
        _process_zip_file,
    )

    assert parser.process_file(str(file_path)) == "parsed markdown"
    assert processed_paths == [str(zip_path)]
    assert not zip_path.exists()


def test_mineru_official_does_not_fallback_when_shared_zip_processing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "mineru.pdf"
    file_path.write_bytes(b"pdf")
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    parser = MinerUOfficialParser(api_key="test-key")

    monkeypatch.setattr(parser, "_upload_file", lambda *args, **kwargs: "batch-id")
    monkeypatch.setattr(
        parser,
        "_poll_batch_result",
        lambda *args, **kwargs: {"state": "done", "full_zip_url": "https://example.test/result.zip"},
    )
    monkeypatch.setattr(parser, "_download_zip", lambda *args, **kwargs: str(zip_path))

    def _raise_zip_processing_error(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("malformed result archive")

    monkeypatch.setattr(
        "platform_core.knowledge.parser.mineru_official.process_zip_file_sync",
        _raise_zip_processing_error,
    )

    with pytest.raises(DocumentParserException, match="malformed result archive"):
        parser.process_file(str(file_path))

    assert not zip_path.exists()


def test_rapid_ocr_health_check_does_not_load_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "platform_core.knowledge.parser.rapid_ocr.RapidOCR",
        lambda *args, **kwargs: pytest.fail("健康检查不应加载 OCR 模型"),
    )

    health = RapidOCRParser().check_health()

    assert health["status"] == "healthy"


def test_pp_structure_result_preserves_layout_page_spans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "layout.pdf"
    file_path.write_bytes(b"pdf")
    parser = PPStructureV3Parser(server_url="http://paddlex.test")
    monkeypatch.setattr(parser, "check_health", lambda: {"status": "healthy", "message": "ok"})
    monkeypatch.setattr(
        parser,
        "_call_layout_api",
        lambda **kwargs: {
            "errorCode": 0,
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {"text": "第一页版面"},
                        "prunedResult": {
                            "parsing_res_list": [
                                {
                                    "block_label": "text",
                                    "block_content": "第一页版面",
                                    "block_bbox": [10, 20, 300, 80],
                                }
                            ]
                        },
                    },
                    {
                        "markdown": {"text": "第二页版面"},
                        "prunedResult": {
                            "parsing_res_list": [
                                {
                                    "block_label": "section_title",
                                    "block_content": "第二页版面",
                                    "block_bbox": [12, 24, 310, 88],
                                }
                            ]
                        },
                    },
                ]
            },
        },
    )

    result = parser.process_file_result(str(file_path))

    assert result.markdown == "第一页版面\n\n第二页版面"
    assert result.parser_name == "pp_structure_v3_ocr"
    assert result.source_metadata["page_count"] == 2
    page_blocks = [block for block in result.blocks if block.source_metadata["position_kind"] == "layout_page"]
    assert [(block.page_number, block.start_char, block.end_char) for block in page_blocks] == [
        (1, 0, 5),
        (2, 7, 12),
    ]
    assert [result.markdown[block.start_char : block.end_char] for block in page_blocks] == [
        "第一页版面",
        "第二页版面",
    ]
    layout_blocks = [block for block in result.blocks if block.source_metadata["position_kind"] == "layout_block"]
    assert [(block.block_type, block.bbox) for block in layout_blocks] == [
        ("paragraph", (10.0, 20.0, 300.0, 80.0)),
        ("heading", (12.0, 24.0, 310.0, 88.0)),
    ]


def _build_pdf(file_path: Path, text: str | list[str]) -> None:
    """用标准库构造带文本的最小 PDF，避免测试引入额外 PDF 依赖。"""
    pages = [text] if isinstance(text, str) else text
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for index, page_text in enumerate(pages):
        escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + index * 2} 0 R >>"
                ).encode(),
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            ]
        )
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, object_body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_number} 0 obj\n".encode())
        pdf.extend(object_body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode())
    pdf.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode())
    file_path.write_bytes(pdf)


def _build_docx(file_path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(str(file_path))


def test_pdfreader_preserves_page_order_blank_pages_and_trimming(tmp_path: Path):
    """文本提取保留空页分隔并去除逐页首尾空白。"""
    from platform_core.knowledge.parser.unified import pdfreader

    file_path = tmp_path / "pages.pdf"
    _build_pdf(file_path, ["  First page  ", "", "Last page"])
    assert pdfreader(file_path) == "First page\n\n\n\nLast page"


def test_pdfreader_result_preserves_page_spans(tmp_path: Path):
    """原生文本层结果保留页码和可回切的逐页字符区间。"""
    from platform_core.knowledge.parser.unified import pdfreader_result

    file_path = tmp_path / "page-spans.pdf"
    _build_pdf(file_path, ["First page", "Second page"])

    result = pdfreader_result(file_path)

    assert result.markdown == "First page\n\nSecond page"
    assert result.source_metadata == {"file_extension": ".pdf", "page_count": 2}
    assert [(block.page_number, block.start_char, block.end_char) for block in result.blocks] == [
        (1, 0, 10),
        (2, 12, 23),
    ]
    assert [result.markdown[block.start_char : block.end_char] for block in result.blocks] == [
        "First page",
        "Second page",
    ]


def test_pdfreader_result_reuses_trailing_download_trace_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """正式原生解析与预检使用同一尾部追踪数据恢复逻辑。"""
    from pypdf.errors import PdfStreamError
    from platform_core.knowledge.parser.unified import pdfreader_result

    file_path = tmp_path / "traced.pdf"
    _build_pdf(file_path, ["Original page"])
    original = file_path.read_bytes()
    file_path.write_bytes(original + b"transferOut:download-trace")

    class RecoveredPage:
        def extract_text(self, **_kwargs):
            return "Recovered page"

    def reader(source):
        if not isinstance(source, BytesIO):
            raise PdfStreamError("trailing trace")
        return SimpleNamespace(pages=[RecoveredPage()])

    monkeypatch.setattr("platform_core.knowledge.parser.intelligent_router.PdfReader", reader)

    result = pdfreader_result(file_path)

    assert result.markdown == "Recovered page"
    assert result.source_metadata["trailing_data_recovered"] is True
    assert file_path.read_bytes() == original + b"transferOut:download-trace"


def test_pdfreader_rejects_corrupt_pdf(tmp_path: Path):
    """损坏 PDF 显式失败，不返回伪成功空文本。"""
    from pypdf.errors import PdfReadError
    from platform_core.knowledge.parser.unified import pdfreader

    file_path = tmp_path / "broken.pdf"
    file_path.write_bytes(b"%PDF-1.4\ninvalid")
    with pytest.raises(PdfReadError):
        pdfreader(file_path)


def _build_png(file_path: Path) -> None:
    image = Image.new("RGB", (120, 80), "white")
    image.save(str(file_path))


@pytest.mark.asyncio
async def test_parse_document_pdf_returns_markdown_text(tmp_path: Path):
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")

    markdown = await parse_document(str(file_path), params={"ocr_engine": "disable"})

    assert "Parser" in markdown
    assert "content" in markdown


@pytest.mark.asyncio
async def test_parse_document_metadata_records_native_pdf_lineage(tmp_path: Path):
    file_path = tmp_path / "parser_lineage.pdf"
    _build_pdf(file_path, "Parser PDF lineage")

    result = await parse_document_with_metadata(str(file_path), params={"ocr_engine": "disable"})

    assert "Parser" in result.markdown
    assert result.parser_name == "native_pdf"
    assert result.parser_version == "platform-unified-parser-v2"
    assert result.source_metadata == {"file_extension": ".pdf", "page_count": 1}
    assert len(result.blocks) == 1
    assert result.blocks[0].page_number == 1


@pytest.mark.asyncio
async def test_resolved_pdf_preflight_reuses_trailing_data_recovery(tmp_path: Path):
    """统一入口的 PDFium 前检不得先于原生解析拒绝可恢复的下载追踪尾部。"""
    file_path = tmp_path / "traced.pdf"
    _build_pdf(file_path, "Parser PDF lineage")
    original = file_path.read_bytes()
    traced = original + b"Fulltextuser:Group.szdxccache:False\x92\x00\x00\x00wftrace"
    file_path.write_bytes(traced)

    result = await parser_unified.parse_resolved_document_result(
        str(file_path),
        params={"ocr_engine": "disable"},
    )

    assert "Parser" in result.markdown
    assert result.source_metadata["trailing_data_recovered"] is True
    assert file_path.read_bytes() == traced


@pytest.mark.asyncio
async def test_resolved_pdf_replaces_invalid_unicode_surrogates_without_shifting_spans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """解析边界一对一替换非法代理字符，确保 UTF-8 可写且 Span 不偏移。"""
    file_path = tmp_path / "invalid-unicode.pdf"
    _build_pdf(file_path, "valid pdf")
    parsed = ParsedDocument(
        markdown="A\udbc2B",
        parser_name="native_pdf",
        source_metadata={"file_extension": ".pdf", "page_count": 1},
        blocks=(ParsedBlock(start_char=0, end_char=3, page_number=1),),
    )

    async def parse_result(*_args, **_kwargs):
        return parsed

    monkeypatch.setattr(parser_unified, "parse_pdf_result_async", parse_result)

    result = await parser_unified.parse_resolved_document_result(
        str(file_path),
        params={"ocr_engine": "disable"},
    )

    assert result.markdown == "A\ufffdB"
    assert result.markdown.encode("utf-8")
    assert result.blocks == parsed.blocks
    assert result.source_metadata["invalid_unicode_surrogates_replaced"] == 1


@pytest.mark.asyncio
async def test_resolved_pdf_preserves_structured_ocr_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "structured.pdf"
    _build_pdf(file_path, "valid pdf")
    expected = ParsedDocument(
        markdown="版面解析结果",
        parser_name="pp_structure_v3_ocr",
        source_metadata={"file_extension": ".pdf", "page_count": 1},
        blocks=(
            ParsedBlock(
                start_char=0,
                end_char=6,
                page_number=1,
                block_type="paragraph",
            ),
        ),
    )
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "process_file_result",
        lambda *args, **kwargs: expected,
    )

    result = await parser_unified.parse_resolved_document_result(
        str(file_path),
        params={"ocr_engine": "pp_structure_v3_ocr", "_ocr_processor_kwargs": {}},
    )

    assert result.markdown == expected.markdown
    assert result.parser_name == "pp_structure_v3_ocr"
    assert result.blocks == expected.blocks
    assert result.source_metadata["page_count"] == 1


@pytest.mark.asyncio
async def test_unified_zip_parser_returns_markdown_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "parser_test.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("full.md", "# ZIP content")

    async def _process_zip_file(*args, **kwargs) -> str:
        del args, kwargs
        return "# ZIP content"

    monkeypatch.setattr(parser_unified, "_process_zip_file", _process_zip_file)

    markdown = await parser_unified.parse_resolved_document(
        str(archive),
        params={"image_bucket": "images", "image_prefix": "kb/test"},
    )

    assert markdown == "# ZIP content"
    assert isinstance(markdown, str)


@pytest.mark.asyncio
async def test_parse_document_docx_returns_markdown_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "parser_test.docx"
    _build_docx(file_path, "Parser DOCX content")

    # 避免测试依赖 docling 行为，直接验证统一 parser 可回退到 python-docx。
    def _raise_docling_error(*args, **kwargs):
        raise RuntimeError("force fallback to python-docx")

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _raise_docling_error)

    markdown = await parse_document(str(file_path))

    assert "Parser DOCX content" in markdown


@pytest.mark.asyncio
async def test_parse_document_metadata_records_docx_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "parser_lineage.docx"
    _build_docx(file_path, "Parser DOCX lineage")

    def _raise_docling_error(*args, **kwargs):
        raise RuntimeError("force fallback to python-docx")

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _raise_docling_error)

    result = await parse_document_with_metadata(str(file_path))

    assert "Parser DOCX lineage" in result.markdown
    assert result.parser_name == "python_docx"


@pytest.mark.parametrize(
    ("filename", "expected_fragments"),
    [
        ("测试文档.docx", ("20XX个人述职报告", "测试表格")),
        ("测试演示.pptx", ("BUSINESS REPORT TEMPLATE", "工作内容回顾")),
        ("测试表格.xlsx", ("个人所得税计算",)),
    ],
)
def test_slim_office_backends_convert_real_fixtures(
    filename: str,
    expected_fragments: tuple[str, ...],
) -> None:
    if filename.endswith(".xls") and shutil.which("libreoffice") is None:
        pytest.skip("旧版 Excel fixture 需要 LibreOffice 转换器")

    document = parser_unified._convert_office_document(PARSER_FIXTURES / filename)

    markdown = document.export_to_markdown()

    assert markdown.strip()
    assert all(fragment in markdown for fragment in expected_fragments)


def test_xls_parsed_with_pandas_without_libreoffice() -> None:
    """旧版 .xls 不走 Docling，直接用 pandas + xlrd 解析为 Markdown。"""
    markdown = parser_unified._convert_xls_to_markdown(PARSER_FIXTURES / "测试旧表格.xls")

    assert markdown.strip()
    assert "Docling Slim" in markdown
    assert "53" in markdown


async def test_parse_resolved_document_routes_xls_to_pandas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_resolved_document 对 .xls 使用 pandas 路径而非 Docling。"""
    docling_calls: list[Path] = []

    def _fake_docling(file_path: Path, params: dict | None = None) -> str:
        docling_calls.append(file_path)
        return "docling"

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _fake_docling)

    markdown = await parser_unified.parse_resolved_document(str(PARSER_FIXTURES / "测试旧表格.xls"))

    assert "Docling Slim" in markdown
    assert not docling_calls


async def test_xls_preserves_single_row_text_and_blank_cells() -> None:
    """真实多 sheet 文件保留单行内容、文本编号与空白，跳过空表。"""
    markdown = await parser_unified.parse_resolved_document(str(PARSER_FIXTURES / "xls-cell-preservation.xls"))

    assert "## 单行" in markdown
    assert "## 文本与空白" in markdown
    assert "## 空表" not in markdown
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")] for line in markdown.splitlines() if line.startswith("|")
    ]
    assert ["唯一内容", "53"] in rows
    assert ["编号", "标记", "备注"] in rows
    assert ["00123", "NA", ""] in rows
    assert ["00456", "NULL", "保留文本"] in rows


def test_slim_office_backend_unloads_after_conversion_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unloaded = False

    class FailingBackend:
        def convert(self):
            raise RuntimeError("conversion failed")

        def unload(self):
            nonlocal unloaded
            unloaded = True

    input_document = SimpleNamespace(valid=True, _backend=FailingBackend())
    monkeypatch.setattr(parser_unified, "InputDocument", lambda *_args: input_document)

    with pytest.raises(RuntimeError, match="conversion failed"):
        parser_unified._convert_office_document(tmp_path / "failure.docx")

    assert unloaded


def test_slim_docx_preserves_embedded_image_bytes_and_markdown_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded_images: list[bytes] = []

    def _capture_upload(image_data, filename, bucket_name, object_prefix):
        del filename, bucket_name, object_prefix
        uploaded_images.append(image_data)
        return "https://example.test/docx-image.png"

    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _capture_upload)

    markdown = parser_unified._convert_with_docling(PARSER_FIXTURES / "测试文档.docx")

    assert len(uploaded_images) == 1
    assert uploaded_images[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert re.search(
        r"20XX个人述职报告[\s\S]+!\[image_\d+\.png\]\(https://example\.test/docx-image\.png\)"
        r"[\s\S]+测试图片",
        markdown,
    )


@pytest.mark.asyncio
async def test_pdf_never_enters_office_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Existing PDF path")
    monkeypatch.setattr(
        parser_unified,
        "_convert_office_document",
        lambda *_args, **_kwargs: pytest.fail("PDF 不得进入 Office backend"),
    )

    markdown = await parse_document(str(file_path), params={"ocr_engine": "disable"})

    assert "Existing PDF path" in markdown


def test_lock_excludes_full_docling_and_torch_runtime() -> None:
    lock_text = (Path(__file__).parents[3] / "uv.lock").read_text(encoding="utf-8")
    package_names = set(re.findall(r'^name = "([^"]+)"$', lock_text, flags=re.MULTILINE))

    assert {
        "docling",
        "docling-ibm-models",
        "docling-parse",
        "torch",
        "torchvision",
    }.isdisjoint(package_names)


def test_convert_csv_to_markdown_preserves_column_dtypes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.csv"
    file_path.write_text("id,score\n9007199254740993,2.5\n", encoding="utf-8")
    captured_dtypes: list[dict[str, object]] = []
    original_to_markdown = pd.DataFrame.to_markdown

    def _capture_dtypes(dataframe: pd.DataFrame, *args, **kwargs) -> str:
        captured_dtypes.append(dataframe.dtypes.to_dict())
        return original_to_markdown(dataframe, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_markdown", _capture_dtypes)

    markdown = parser_unified._convert_csv_to_markdown(file_path)

    assert markdown
    assert str(captured_dtypes[0]["id"]) == "int64"


def test_convert_with_docling_reinserts_image_links_in_document_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.docx"
    file_path.write_bytes(b"fake docx")
    first_image = base64.b64encode(b"first image").decode()
    second_image = base64.b64encode(b"second image").decode()
    fake_doc = SimpleNamespace(
        pictures=[
            SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{first_image}")),
            SimpleNamespace(image=SimpleNamespace(uri="https://example.test/remote.png")),
            SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{second_image}")),
        ],
        export_to_markdown=lambda: "before\n<!-- image -->\nremote\n<!-- image -->\nbetween\n<!-- image -->\nafter",
    )
    uploaded_images: list[bytes] = []

    def _fake_upload_image_to_minio(image_data, filename, bucket_name, object_prefix):
        uploaded_images.append(image_data)
        return f"https://example.test/{len(uploaded_images)}.png"

    monkeypatch.setattr(parser_unified, "_convert_office_document", lambda _path: fake_doc)
    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _fake_upload_image_to_minio)
    image_timestamps = iter([1.0, 2.0])
    monkeypatch.setattr(parser_unified.time, "time", lambda: next(image_timestamps))

    markdown = parser_unified._convert_with_docling(file_path)

    assert uploaded_images == [b"first image", b"second image"]
    assert markdown == (
        "before\n"
        "![image_1000000.png](https://example.test/1.png)\n"
        "remote\n"
        "\n"
        "between\n"
        "![image_2000000.png](https://example.test/2.png)\n"
        "after"
    )


def test_convert_with_docling_keeps_image_placeholder_when_upload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.docx"
    file_path.write_bytes(b"fake docx")
    image = base64.b64encode(b"image data").decode()
    fake_doc = SimpleNamespace(
        pictures=[SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{image}"))],
        export_to_markdown=lambda: "before\n<!-- image -->\nafter",
    )

    def _raise_upload_error(*args, **kwargs):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(parser_unified, "_convert_office_document", lambda _path: fake_doc)
    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _raise_upload_error)
    monkeypatch.setattr(parser_unified.time, "time", lambda: 1.0)

    markdown = parser_unified._convert_with_docling(file_path)

    assert markdown == "before\n[图片: image_1000000.png]\nafter"


@pytest.mark.asyncio
async def test_parse_document_png_returns_markdown_text_with_mocked_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)

    async def _fake_parse_image_async(file, params=None):
        return ParsedDocument(markdown="Parser PNG content", parser_name="rapid_ocr")

    async def _resolve_params(params=None, db=None):
        del db
        return params or {}

    monkeypatch.setattr(parser_unified, "parse_image_result_async", _fake_parse_image_async)
    monkeypatch.setattr("platform_core.services.ocr_service.resolve_ocr_task_params", _resolve_params)

    markdown = await parse_document(str(file_path), params={"ocr_engine": "rapid_ocr"})

    assert "Parser PNG content" in markdown


def test_parse_image_ignores_ocr_engine_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)
    captured = {}

    def _fake_process_file(processor_type, file, params=None, processor_kwargs=None):
        captured["processor_type"] = processor_type
        captured["file"] = file
        captured["params"] = params
        return ParsedDocument(markdown="OCR content", parser_name=processor_type)

    monkeypatch.setattr(DocumentProcessorFactory, "process_file_result", _fake_process_file)

    result = parser_unified.parse_image(
        str(file_path),
        params={
            "ocr_engine": "mineru_ocr",
            "backend": "old-backend",
            "ocr_engine_config": {"backend": "pipeline", "formula_enable": False},
        },
    )

    assert result == "OCR content"
    assert captured["processor_type"] == "mineru_ocr"
    assert captured["file"] == str(file_path)
    assert captured["params"]["backend"] == "old-backend"
    assert "formula_enable" not in captured["params"]


def test_parse_image_ignores_enable_ocr(tmp_path: Path) -> None:
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)

    with pytest.raises(ValueError, match="必须启用OCR"):
        parser_unified.parse_image(str(file_path), params={"ocr_engine": "disable", "enable_ocr": "rapid_ocr"})


def test_low_level_pdf_parser_requires_resolved_ocr_engine(tmp_path: Path) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")

    with pytest.raises(ValueError, match="请通过 parse_document"):
        parser_unified.parse_pdf(str(file_path), params={})


@pytest.mark.asyncio
async def test_parse_document_docx_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test_async.docx"
    file_path.write_bytes(b"fake docx")
    completion_order: list[str] = []

    def _slow_docling_conversion(*args, **kwargs) -> str:
        time.sleep(0.1)
        return "Async DOCX content"

    async def _parse_document() -> None:
        await parse_document(str(file_path))
        completion_order.append("parse")

    async def _record_event_loop_progress() -> None:
        await asyncio.sleep(0.01)
        completion_order.append("event_loop")

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _slow_docling_conversion)

    await asyncio.gather(_parse_document(), _record_event_loop_progress())

    assert completion_order == ["event_loop", "parse"]


@pytest.mark.asyncio
async def test_parse_document_uses_config_default_ocr_when_engine_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")
    captured = {}

    def _fake_process_file(processor_type, file, params=None, processor_kwargs=None):
        captured["processor_type"] = processor_type
        captured["file"] = file
        captured["params"] = params
        return ParsedDocument(markdown="default OCR content", parser_name=processor_type)

    async def _build_processor_kwargs(db, engine_id):
        del db, engine_id
        return {}

    async def _system_options_get(_option, _db=None):
        return {"default_ocr_engine": "mineru_ocr"}

    monkeypatch.setattr("platform_core.config.options.Option.get", _system_options_get)
    monkeypatch.setattr(DocumentProcessorFactory, "process_file_result", _fake_process_file)
    monkeypatch.setattr("platform_core.services.ocr_service._build_processor_kwargs", _build_processor_kwargs)

    result = await parse_document(str(file_path), params={}, db=object())

    assert result == "default OCR content"
    assert captured["processor_type"] == "mineru_ocr"
    assert captured["file"] == str(file_path)


def test_parse_pdf_keeps_explicit_disable_when_default_ocr_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")
    result = parser_unified.parse_pdf(str(file_path), params={"ocr_engine": "disable"})

    assert "Parser PDF content" in result


def test_rapid_ocr_resolves_model_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "custom_models"
    monkeypatch.setenv("RAPIDOCR_MODEL_DIR", str(target_dir))
    parser = RapidOCRParser()
    params = parser._get_model_params()

    assert params["Global.model_root_dir"] == str(target_dir)
    assert target_dir.exists()
