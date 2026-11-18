"""PDF 解析前置检查。

本模块在文档进入 MinerU、pypdf 等解析器之前，
先用平台已有的 pypdfium2 依赖检查 PDF 页面树是否能逐页加载。
它只负责识别明显的 PDF 结构异常，例如页树中存在 null 页槽、非 Page 对象或循环引用；
不负责修复 PDF，也不能被当作内容 OCR 或页数统计的业务事实源。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pypdfium2 as pdfium

from platform_core.knowledge.parser.base import DocumentParserException


# PDFium 进程级全局状态不支持同一进程内多线程并发打开文档。前置校验和
# Docling PDF backend 必须共用这把锁，否则两段各自限流仍会互相重叠。
PDFIUM_DOCUMENT_LOCK = threading.RLock()


@dataclass(slots=True)
class PDFPageLoadIssue:
    """PDF 页面加载异常位置。"""

    page_number: int
    message: str


def recover_pdf_bytes_after_eof(source: BinaryIO, *, force: bool = False) -> bytes | None:
    """仅在内存中移除最终 EOF 后的附加数据，不修改来源文件。"""

    source.seek(0, 2)
    file_size = source.tell()
    tail_size = min(file_size, 64 * 1024)
    source.seek(file_size - tail_size)
    tail = source.read(tail_size)
    eof_index = tail.rfind(b"%%EOF")
    if eof_index < 0:
        return None

    clean_end = file_size - tail_size + eof_index + len(b"%%EOF")
    trailing_data = tail[eof_index + len(b"%%EOF") :]
    if clean_end >= file_size or (not force and not trailing_data.strip()):
        return None

    source.seek(0)
    prefix = source.read(clean_end - len(b"%%EOF"))
    separator = b"" if prefix.endswith((b"\r", b"\n")) else b"\n"
    return prefix + separator + b"%%EOF\n"


def _format_page_numbers(page_numbers: list[int], *, limit: int = 8) -> str:
    """格式化页码列表，避免异常信息过长。"""

    visible = page_numbers[:limit]
    result = "、".join(str(page_number) for page_number in visible)
    if len(page_numbers) > limit:
        result = f"{result} 等 {len(page_numbers)} 个"
    return result


def validate_pdf_page_tree_loadable(file_path: str | Path) -> None:
    """校验 PDF 页树中的每一个页槽都能作为页面加载。"""

    with PDFIUM_DOCUMENT_LOCK:
        _validate_pdf_page_tree_loadable(file_path)


def _validate_pdf_page_tree_loadable(file_path: str | Path) -> None:
    """在持有 PDFium 进程锁时执行页面树校验。"""

    path = Path(file_path)

    try:
        with path.open("rb") as source:
            recovered_bytes = recover_pdf_bytes_after_eof(source)
        doc = pdfium.PdfDocument(recovered_bytes if recovered_bytes is not None else str(path))
    except Exception as exc:  # noqa: BLE001
        # pypdfium2 打开加密 PDF 时抛 PdfiumError（消息含 password），无独立加密属性。
        if isinstance(exc, pdfium.PdfiumError) and "password" in str(exc).lower():
            raise DocumentParserException(
                "PDF 文件已加密或需要密码，无法进入文档解析流程",
                "pdf_preflight",
                "encrypted_pdf",
            ) from exc
        raise DocumentParserException(
            f"PDF 文件结构异常，无法打开页面目录: {exc}",
            "pdf_preflight",
            "invalid_pdf_structure",
        ) from exc

    try:
        page_count = len(doc)
        if page_count <= 0:
            raise DocumentParserException(
                "PDF 文件没有可解析页面",
                "pdf_preflight",
                "empty_pdf",
            )

        issues: list[PDFPageLoadIssue] = []
        for page_index in range(page_count):
            try:
                page = doc[page_index]
                # 访问页面尺寸会触发页面对象基础解析，能提前暴露 null/非 Page 页槽。
                _ = page.get_size()
            except Exception as exc:  # noqa: BLE001
                issues.append(PDFPageLoadIssue(page_number=page_index + 1, message=str(exc)))

        if issues:
            bad_pages = _format_page_numbers([issue.page_number for issue in issues])
            first_error = issues[0].message or "页面对象无法加载"
            raise DocumentParserException(
                "PDF 页面结构异常："
                f"声明页数为 {page_count}，但第 {bad_pages} 个页槽不是可加载页面对象。"
                f"底层错误：{first_error}。请先用 Acrobat、打印为 PDF、qpdf 或 mutool 等工具重写 PDF 后再上传。",
                "pdf_preflight",
                "invalid_pdf_page_tree",
            )
    finally:
        doc.close()
