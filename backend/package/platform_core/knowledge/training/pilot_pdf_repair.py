"""为页树根缺失但页面对象完整的 Pilot PDF 生成可审计候选副本。"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from pypdf import PdfReader

PDF_REPAIR_VERSION = "defense-kg-pdf-repair-v1"


def repair_missing_pages_root(
    source_path: str | Path,
    output_path: str | Path,
    *,
    expected_source_sha256: str,
    pages_root_object_id: int,
    page_object_ids: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    """只追加缺失页树根，验证页面对象后生成不覆盖原件的候选 PDF。"""
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"源 PDF 不存在: {source}")
    if output.exists():
        raise ValueError(f"候选输出已存在，拒绝覆盖: {output}")
    if source == output:
        raise ValueError("候选输出不能覆盖源 PDF")
    if pages_root_object_id < 1:
        raise ValueError("pages_root_object_id 必须大于 0")
    resolved_page_ids = tuple(int(value) for value in page_object_ids)
    if not resolved_page_ids or len(set(resolved_page_ids)) != len(resolved_page_ids):
        raise ValueError("page_object_ids 必须是非空且不重复的对象编号")
    if any(value < 1 or value == pages_root_object_id for value in resolved_page_ids):
        raise ValueError("page_object_ids 包含非法对象编号")

    source_bytes = source.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    if source_sha256 != expected_source_sha256.lower():
        raise ValueError("源 PDF SHA-256 与批准输入不一致")
    root_object_id, size, previous_xref = _inspect_repair_contract(
        source_bytes,
        pages_root_object_id=pages_root_object_id,
        page_object_ids=resolved_page_ids,
    )
    candidate_bytes = _append_pages_root_revision(
        source_bytes,
        root_object_id=root_object_id,
        size=size,
        previous_xref=previous_xref,
        pages_root_object_id=pages_root_object_id,
        page_object_ids=resolved_page_ids,
    )
    validation = _validate_candidate(candidate_bytes, expected_pages=len(resolved_page_ids))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(candidate_bytes)
    return {
        "repair_version": PDF_REPAIR_VERSION,
        "status": "candidate_generated",
        "source_path": str(source),
        "output_path": str(output),
        "source_sha256": source_sha256,
        "output_sha256": _sha256_bytes(candidate_bytes),
        "source_bytes": len(source_bytes),
        "output_bytes": len(candidate_bytes),
        "bytes_appended": len(candidate_bytes) - len(source_bytes),
        "pages_root_object_id": pages_root_object_id,
        "page_object_ids": list(resolved_page_ids),
        "validation": validation,
        "adoption_status": "human_review_required",
    }


def _inspect_repair_contract(
    data: bytes,
    *,
    pages_root_object_id: int,
    page_object_ids: tuple[int, ...],
) -> tuple[int, int, int]:
    trailers = list(re.finditer(rb"trailer\s*<<(.*?)>>\s*startxref\s*(\d+)\s*%%EOF", data, re.DOTALL))
    if not trailers:
        raise ValueError("PDF 不含可识别的最终 trailer/startxref")
    trailer = trailers[-1]
    trailer_body = trailer.group(1)
    size_match = re.search(rb"/Size\s+(\d+)", trailer_body)
    root_match = re.search(rb"/Root\s+(\d+)\s+0\s+R", trailer_body)
    if size_match is None or root_match is None:
        raise ValueError("最终 trailer 缺少 /Size 或 /Root")
    size = int(size_match.group(1))
    root_object_id = int(root_match.group(1))
    previous_xref = int(trailer.group(2))
    if pages_root_object_id >= size or any(page_id >= size for page_id in page_object_ids):
        raise ValueError("页树或页面对象编号超出 trailer /Size")

    root_body = _latest_object_body(data, root_object_id)
    expected_pages_reference = re.compile(rb"/Pages\s+" + str(pages_root_object_id).encode() + rb"\s+0\s+R")
    if expected_pages_reference.search(root_body) is None:
        raise ValueError("Catalog 未引用指定的缺失页树根")
    if _object_bodies(data, pages_root_object_id):
        raise ValueError("指定页树根对象实际存在，拒绝猜测性修复")

    for page_id in page_object_ids:
        page_body = _latest_object_body(data, page_id)
        if re.search(rb"/Type\s*/Page(?!s)", page_body) is None:
            raise ValueError(f"对象 {page_id} 不是 Page")
        parent_pattern = re.compile(rb"/Parent\s+" + str(pages_root_object_id).encode() + rb"\s+0\s+R")
        if parent_pattern.search(page_body) is None:
            raise ValueError(f"页面对象 {page_id} 未引用指定页树根")
    return root_object_id, size, previous_xref


def _append_pages_root_revision(
    data: bytes,
    *,
    root_object_id: int,
    size: int,
    previous_xref: int,
    pages_root_object_id: int,
    page_object_ids: tuple[int, ...],
) -> bytes:
    page_references = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    pages_object_offset = len(data)
    pages_object = (
        f"\n{pages_root_object_id} 0 obj\n"
        f"<< /Type /Pages /Kids [{page_references}] /Count {len(page_object_ids)} >>\n"
        "endobj\n"
    ).encode("ascii")
    xref_offset = len(data) + len(pages_object)
    revision = (
        f"xref\n{pages_root_object_id} 1\n{pages_object_offset:010d} 00000 n \n"
        f"trailer\n<< /Size {size} /Root {root_object_id} 0 R /Prev {previous_xref} >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return data + pages_object + revision


def _validate_candidate(data: bytes, *, expected_pages: int) -> dict[str, Any]:
    reader = PdfReader(BytesIO(data))
    pypdf_pages = len(reader.pages)
    if pypdf_pages != expected_pages:
        raise ValueError(f"pypdf 页数不一致: {pypdf_pages} != {expected_pages}")

    page_sizes = []
    text_char_counts = []
    document = pdfium.PdfDocument(data)
    try:
        if len(document) != expected_pages:
            raise ValueError(f"PDFium 页数不一致: {len(document)} != {expected_pages}")
        for page_index in range(len(document)):
            page = document[page_index]
            try:
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError(f"第 {page_index + 1} 页尺寸无效")
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded()
                finally:
                    text_page.close()
                page_sizes.append([round(width, 2), round(height, 2)])
                text_char_counts.append(len(text.strip()))
            finally:
                page.close()
    finally:
        document.close()
    return {
        "pypdf_page_count": pypdf_pages,
        "pdfium_page_count": expected_pages,
        "pdfium_page_sizes": page_sizes,
        "pdfium_text_char_counts": text_char_counts,
        "all_pages_loadable": True,
    }


def _latest_object_body(data: bytes, object_id: int) -> bytes:
    bodies = _object_bodies(data, object_id)
    if not bodies:
        raise ValueError(f"缺少对象 {object_id}")
    return bodies[-1]


def _object_bodies(data: bytes, object_id: int) -> list[bytes]:
    pattern = re.compile(
        rb"(?:^|[\r\n])" + str(object_id).encode() + rb"\s+0\s+obj\s*(.*?)\s*endobj",
        re.DOTALL,
    )
    return [match.group(1) for match in pattern.finditer(data)]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
