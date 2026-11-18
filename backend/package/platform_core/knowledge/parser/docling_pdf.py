"""基于 Docling Slim PDF backend 的本地数字版面解析器。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from platform_core.knowledge.parser.base import BaseDocumentProcessor, DocumentParserException
from platform_core.knowledge.parser.capabilities import get_parser_capability
from platform_core.knowledge.parser.result import ParsedBlock, ParsedDocument
from platform_core.knowledge.utils.pdf_utils import PDFIUM_DOCUMENT_LOCK

_CAPABILITY = get_parser_capability("docling_pdf")
_FORMULA_PATTERN = re.compile(r"(?:[=+−×÷√∑∫≈≠≤≥^]|\b(?:sin|cos|tan|log|exp)\b)", re.I)


@dataclass(frozen=True, slots=True)
class _LayoutFragment:
    text: str
    bbox: tuple[float, float, float, float]
    block_type: str

    @property
    def center_x(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]


@dataclass(frozen=True, slots=True)
class _LayoutPage:
    page_number: int
    width: float
    height: float
    fragments: tuple[_LayoutFragment, ...]
    text_cell_count: int
    table_count: int
    formula_count: int


class DoclingPdfParser(BaseDocumentProcessor):
    """用 Docling Slim 的 PDFium backend 提取数字 PDF 的位置与阅读顺序。"""

    service_name = _CAPABILITY.service_name
    display_name = _CAPABILITY.display_name
    supported_extensions = list(_CAPABILITY.supported_extensions)

    def process_file(self, file_path: str, params: dict[str, Any] | None = None) -> str:
        return self.process_file_result(file_path, params).markdown

    def process_file_result(self, file_path: str, params: dict[str, Any] | None = None) -> ParsedDocument:
        del params
        path = Path(file_path)
        if not path.exists():
            raise DocumentParserException(f"文件不存在: {path}", self.service_name, "file_not_found")
        if path.suffix.lower() != ".pdf":
            raise DocumentParserException(
                f"不支持的文件类型: {path.suffix.lower()}",
                self.service_name,
                "unsupported_file_type",
            )

        with PDFIUM_DOCUMENT_LOCK:
            pages = self._extract_pages(path)
        if not any(page.fragments for page in pages):
            raise DocumentParserException(
                "PDF 不含可用数字文本层",
                self.service_name,
                "no_text_layer",
            )

        markdown, blocks = _build_document(pages)
        return ParsedDocument(
            markdown=markdown,
            parser_name=self.service_name,
            parser_version=f"docling-slim-{version('docling-slim')}/pypdfium2-{version('pypdfium2')}",
            source_metadata={
                "file_extension": ".pdf",
                "page_count": len(pages),
                "text_cell_count": sum(page.text_cell_count for page in pages),
                "table_count": sum(page.table_count for page in pages),
                "formula_count": sum(page.formula_count for page in pages),
                "layout_method": "docling_pypdfium2_text_layer",
                "bbox_coordinate_system": "pdf_points_top_left",
            },
            blocks=blocks,
        )

    def check_health(self) -> dict[str, Any]:
        """只校验本地依赖，不加载模型或读取文档。"""
        try:
            import rtree  # noqa: F401
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend  # noqa: F401

            return {
                "status": "healthy",
                "message": "Docling PDF 本地 backend 可用",
                "details": {
                    "docling_slim_version": version("docling-slim"),
                    "pypdfium2_version": version("pypdfium2"),
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unavailable",
                "message": "Docling PDF 本地 backend 不可用",
                "details": {"error_type": type(exc).__name__},
            }

    def _extract_pages(self, path: Path) -> tuple[_LayoutPage, ...]:
        try:
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.document import InputDocument

            input_document = InputDocument(path, InputFormat.PDF, PyPdfiumDocumentBackend)
            backend = getattr(input_document, "_backend", None)
            if not input_document.valid or backend is None or not backend.is_valid():
                raise DocumentParserException(
                    "Docling 无法读取 PDF",
                    self.service_name,
                    "invalid_document",
                )

            pages: list[_LayoutPage] = []
            try:
                for page_index in range(backend.page_count()):
                    page = backend.load_page(page_index)
                    try:
                        size = page.get_size()
                        cells = tuple(_fragment_from_text_cell(cell) for cell in page.get_text_cells())
                        cells = tuple(cell for cell in cells if cell is not None)
                        shape_regions = tuple(page.get_connected_shape_bounding_boxes(tolerance=1.5) or ())
                        pages.append(
                            _assemble_page(
                                page_number=page_index + 1,
                                page_width=float(size.width),
                                page_height=float(size.height),
                                cells=cells,
                                shape_regions=shape_regions,
                            )
                        )
                    finally:
                        page.unload()
            finally:
                backend.unload()
            return tuple(pages)
        except DocumentParserException:
            raise
        except Exception as exc:
            raise DocumentParserException(
                f"Docling PDF 解析失败: {type(exc).__name__}",
                self.service_name,
                "processing_failed",
            ) from exc


def _fragment_from_text_cell(cell: Any) -> _LayoutFragment | None:
    text = str(cell.text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    bbox = cell.rect.to_bounding_box()
    coordinates = (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
        return None
    return _LayoutFragment(
        text=text,
        bbox=coordinates,
        block_type="formula" if _looks_like_formula(text) else "paragraph",
    )


def _assemble_page(
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    cells: tuple[_LayoutFragment, ...],
    shape_regions: tuple[Any, ...],
) -> _LayoutPage:
    table_groups = _detect_table_groups(cells, shape_regions, page_width, page_height)
    table_cell_ids = {id(cell) for group in table_groups for cell in group[1]}
    fragments = [cell for cell in cells if id(cell) not in table_cell_ids]
    fragments.extend(_table_fragment(region, group_cells) for region, group_cells in table_groups)
    ordered = _reading_order(tuple(fragments), page_width)
    return _LayoutPage(
        page_number=page_number,
        width=page_width,
        height=page_height,
        fragments=ordered,
        text_cell_count=len(cells),
        table_count=len(table_groups),
        formula_count=sum(fragment.block_type == "formula" for fragment in ordered),
    )


def _detect_table_groups(
    cells: tuple[_LayoutFragment, ...],
    shape_regions: tuple[Any, ...],
    page_width: float,
    page_height: float,
) -> tuple[tuple[tuple[float, float, float, float], tuple[_LayoutFragment, ...]], ...]:
    groups = []
    claimed: set[int] = set()
    for raw_region in shape_regions:
        region = (float(raw_region.l), float(raw_region.t), float(raw_region.r), float(raw_region.b))
        if region[2] - region[0] < page_width * 0.2 or region[3] - region[1] < page_height * 0.04:
            continue
        region_cells = tuple(
            cell for cell in cells if id(cell) not in claimed and _bbox_center_inside(cell.bbox, region)
        )
        if len(region_cells) < 4 or not _has_table_grid(region_cells):
            continue
        groups.append((region, region_cells))
        claimed.update(id(cell) for cell in region_cells)
    return tuple(groups)


def _has_table_grid(cells: tuple[_LayoutFragment, ...]) -> bool:
    row_tops = _cluster_values((cell.bbox[1] for cell in cells), tolerance=6.0)
    column_lefts = _cluster_values((cell.bbox[0] for cell in cells), tolerance=8.0)
    rows = tuple(row for row in _group_rows(cells) if len(row) >= 2)
    if len(row_tops) < 2 or len(column_lefts) < 2 or len(rows) < 2:
        return False
    aligned_columns = 0
    for column_left in column_lefts:
        matching_rows = sum(any(abs(cell.bbox[0] - column_left) <= 8.0 for cell in row) for row in rows)
        if matching_rows >= 2:
            aligned_columns += 1
    return aligned_columns >= 2


def _table_fragment(
    region: tuple[float, float, float, float],
    cells: tuple[_LayoutFragment, ...],
) -> _LayoutFragment:
    rows = _group_rows(cells)
    rendered_rows = ["| " + " | ".join(cell.text for cell in row) + " |" for row in rows]
    if rendered_rows:
        column_count = max(len(row) for row in rows)
        rendered_rows.insert(1, "| " + " | ".join("---" for _ in range(column_count)) + " |")
    return _LayoutFragment(text="\n".join(rendered_rows), bbox=region, block_type="table")


def _group_rows(cells: Iterable[_LayoutFragment]) -> tuple[tuple[_LayoutFragment, ...], ...]:
    ordered = sorted(cells, key=lambda cell: (cell.center_y, cell.bbox[0]))
    rows: list[list[_LayoutFragment]] = []
    for cell in ordered:
        if not rows:
            rows.append([cell])
            continue
        row_center = sum(item.center_y for item in rows[-1]) / len(rows[-1])
        tolerance = max(5.0, (cell.bbox[3] - cell.bbox[1]) * 0.6)
        if abs(cell.center_y - row_center) <= tolerance:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    return tuple(tuple(sorted(row, key=lambda cell: cell.bbox[0])) for row in rows)


def _reading_order(fragments: tuple[_LayoutFragment, ...], page_width: float) -> tuple[_LayoutFragment, ...]:
    spanning = tuple(fragment for fragment in fragments if fragment.width >= page_width * 0.62)
    spanning_ids = {id(fragment) for fragment in spanning}
    body = tuple(fragment for fragment in fragments if id(fragment) not in spanning_ids)
    if not spanning:
        return _order_column_segment(body, page_width)

    ordered: list[_LayoutFragment] = []
    remaining = list(body)
    lower_bound = float("-inf")
    for span in sorted(spanning, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])):
        segment = tuple(fragment for fragment in remaining if lower_bound <= fragment.center_y < span.bbox[1])
        ordered.extend(_order_column_segment(segment, page_width))
        selected = {id(fragment) for fragment in segment}
        remaining = [fragment for fragment in remaining if id(fragment) not in selected]
        ordered.append(span)
        lower_bound = span.bbox[3]
    ordered.extend(_order_column_segment(tuple(remaining), page_width))
    return tuple(ordered)


def _order_column_segment(
    fragments: tuple[_LayoutFragment, ...],
    page_width: float,
) -> tuple[_LayoutFragment, ...]:
    if len(fragments) < 4:
        return tuple(sorted(fragments, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])))

    left, right = _split_two_columns(fragments, page_width)
    if not left or not right:
        return tuple(sorted(fragments, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])))

    overlap_top = max(min(fragment.center_y for fragment in left), min(fragment.center_y for fragment in right))
    overlap_bottom = min(max(fragment.center_y for fragment in left), max(fragment.center_y for fragment in right))
    if overlap_bottom <= overlap_top:
        return tuple(sorted(fragments, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])))

    before = tuple(fragment for fragment in fragments if fragment.center_y < overlap_top)
    after = tuple(fragment for fragment in fragments if fragment.center_y > overlap_bottom)
    outside_ids = {id(fragment) for fragment in (*before, *after)}
    left_body = tuple(fragment for fragment in left if id(fragment) not in outside_ids)
    right_body = tuple(fragment for fragment in right if id(fragment) not in outside_ids)
    return (
        *sorted(before, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])),
        *sorted(left_body, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])),
        *sorted(right_body, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])),
        *sorted(after, key=lambda fragment: (fragment.bbox[1], fragment.bbox[0])),
    )


def _split_two_columns(
    fragments: tuple[_LayoutFragment, ...],
    page_width: float,
) -> tuple[tuple[_LayoutFragment, ...], tuple[_LayoutFragment, ...]]:
    centers = [fragment.center_x for fragment in fragments]
    centroid_left, centroid_right = min(centers), max(centers)
    if centroid_right - centroid_left < page_width * 0.22:
        return (), ()

    left: tuple[_LayoutFragment, ...] = ()
    right: tuple[_LayoutFragment, ...] = ()
    for _ in range(12):
        left = tuple(
            fragment
            for fragment in fragments
            if abs(fragment.center_x - centroid_left) <= abs(fragment.center_x - centroid_right)
        )
        left_ids = {id(fragment) for fragment in left}
        right = tuple(fragment for fragment in fragments if id(fragment) not in left_ids)
        if len(left) < 2 or len(right) < 2:
            return (), ()
        new_left = sum(fragment.center_x for fragment in left) / len(left)
        new_right = sum(fragment.center_x for fragment in right) / len(right)
        if abs(new_left - centroid_left) < 0.1 and abs(new_right - centroid_right) < 0.1:
            break
        centroid_left, centroid_right = new_left, new_right

    if centroid_left > centroid_right:
        left, right = right, left
    gutter = min(fragment.bbox[0] for fragment in right) - max(fragment.bbox[2] for fragment in left)
    if gutter < page_width * 0.025:
        return (), ()
    return left, right


def _looks_like_formula(text: str) -> bool:
    compact = text.strip()
    if len(compact) > 180 or not _FORMULA_PATTERN.search(compact):
        return False
    words = re.findall(r"[A-Za-z]{4,}", compact)
    return len(words) <= 3


def _bbox_center_inside(
    bbox: tuple[float, float, float, float],
    region: tuple[float, float, float, float],
) -> bool:
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return region[0] <= center_x <= region[2] and region[1] <= center_y <= region[3]


def _cluster_values(values: Iterable[float], *, tolerance: float) -> tuple[float, ...]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if clusters and abs(value - sum(clusters[-1]) / len(clusters[-1])) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return tuple(sum(cluster) / len(cluster) for cluster in clusters)


def _build_document(pages: tuple[_LayoutPage, ...]) -> tuple[str, tuple[ParsedBlock, ...]]:
    page_texts = ["\n\n".join(fragment.text for fragment in page.fragments) for page in pages]
    markdown = "\n\n".join(page_texts)
    blocks: list[ParsedBlock] = []
    document_offset = 0
    for page_index, (page, page_text) in enumerate(zip(pages, page_texts, strict=True)):
        if page_index:
            document_offset += 2
        page_start = document_offset
        document_offset += len(page_text)
        blocks.append(
            ParsedBlock(
                start_char=page_start,
                end_char=document_offset,
                page_number=page.page_number,
                block_type="paragraph" if page_text else "empty",
                source_metadata={
                    "position_kind": "docling_pdf_layout_page",
                    "page_width": page.width,
                    "page_height": page.height,
                },
            )
        )

        local_offset = 0
        for fragment_index, fragment in enumerate(page.fragments):
            if fragment_index:
                local_offset += 2
            start_char = page_start + local_offset
            local_offset += len(fragment.text)
            blocks.append(
                ParsedBlock(
                    start_char=start_char,
                    end_char=page_start + local_offset,
                    page_number=page.page_number,
                    block_type=fragment.block_type,
                    bbox=fragment.bbox,
                    source_metadata={"position_kind": "docling_pdf_layout_block"},
                )
            )
    return markdown, tuple(blocks)
