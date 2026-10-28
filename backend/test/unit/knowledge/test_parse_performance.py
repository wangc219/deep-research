"""解析并发、取消和 PDF 文字层优先回归。"""

import asyncio
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from platform_core.knowledge.parser.rapid_ocr import RapidOCRParser
from platform_core.knowledge.parser.local_ocr_pool import process_local_document
from platform_core.services.knowledge_task_service import resolve_document_concurrency, run_document_batch


def make_text_pdf(path, *, blank_page=False):
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
    text = "This is searchable text in the first page. " * 6
    stream.set_data(f"BT /F1 10 Tf 30 750 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if blank_page:
        writer.add_blank_page(width=600, height=800)
    writer.write(path)


def test_mixed_pdf_uses_text_and_ocr_in_page_order(tmp_path, monkeypatch):
    source = tmp_path / "mixed.pdf"
    make_text_pdf(source, blank_page=True)
    parser = RapidOCRParser()
    ocr = Mock(return_value="OCR_SECOND_PAGE")
    monkeypatch.setattr(parser, "process_image", ocr)
    result = parser.process_pdf(str(source))
    assert result.index("searchable text") < result.index("OCR_SECOND_PAGE")
    assert ocr.call_count == 1
    ocr.reset_mock()
    parser.process_pdf(str(source), {"prefer_text_layer": False})
    assert ocr.call_count == 2


def test_large_scanned_image_does_not_skip_ocr_due_to_partial_text(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pypdfium2 as pdfium

    source = tmp_path / "partial-layer.pdf"
    make_text_pdf(source)
    monkeypatch.setattr(
        pdfium.PdfPage, "get_objects", lambda *args, **kwargs: [SimpleNamespace(get_bounds=lambda: (0, 0, 600, 800))]
    )
    parser = RapidOCRParser()
    ocr = Mock(return_value="完整扫描页文字")
    monkeypatch.setattr(parser, "process_image", ocr)
    assert parser.process_pdf(str(source)) == "完整扫描页文字"
    ocr.assert_called_once()


@pytest.mark.asyncio
async def test_spawned_ocr_processes_read_real_text_pdf(tmp_path):
    source = tmp_path / "searchable.pdf"
    make_text_pdf(source)
    results = await asyncio.wait_for(
        asyncio.gather(
            process_local_document(str(source), {"prefer_text_layer": True}),
            process_local_document(str(source), {"prefer_text_layer": True}),
        ),
        30,
    )
    assert all("searchable text" in result for result in results)


@pytest.mark.asyncio
async def test_document_batch_bound_and_order():
    active = 0
    peak = 0
    release = asyncio.Event()

    async def process(index, value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            release.set()
        await release.wait()
        await asyncio.sleep(0)
        active -= 1
        return value * 2

    result = await asyncio.wait_for(run_document_batch([3, 2, 1, 0], process, concurrency=2), 2)
    assert result == [6, 4, 2, 0]
    assert peak == 2


@pytest.mark.asyncio
async def test_cancelling_batch_drains_all_workers():
    started = asyncio.Event()
    active = 0

    async def process(index, value):
        nonlocal active
        active += 1
        if active == 2:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    task = asyncio.create_task(run_document_batch([1, 2, 3], process, concurrency=2))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0


@pytest.mark.parametrize("value", [0, 5, True, "2"])
def test_document_concurrency_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        resolve_document_concurrency({"parse_concurrency": value})
