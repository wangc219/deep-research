"""PaddleX 布局页、精确字符定位与 bbox 安全转换。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from platform_core.knowledge.parser.result import ParsedBlock


@dataclass(frozen=True, slots=True)
class PaddleXLayoutBlock:
    """PaddleX 返回且尚未映射到 Markdown 的布局块。"""

    text: str
    block_type: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PaddleXLayoutPage:
    """一页 Markdown 及其原始布局候选。"""

    page_number: int
    text: str
    layout_blocks: tuple[PaddleXLayoutBlock, ...] = ()


def extract_paddlex_layout_blocks(pruned_result: dict[str, Any]) -> tuple[PaddleXLayoutBlock, ...]:
    """只接纳同时具有原文和四点数值 bbox 的 PaddleX 布局块。"""
    raw_blocks = pruned_result.get("parsing_res_list") or pruned_result.get("parsingResList") or []
    candidates: list[PaddleXLayoutBlock] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            continue
        text = raw_block.get("block_content") or raw_block.get("blockContent") or raw_block.get("text")
        bbox = raw_block.get("block_bbox") or raw_block.get("blockBbox") or raw_block.get("bbox")
        if not isinstance(text, str) or not text or not _valid_bbox(bbox):
            continue
        label = str(raw_block.get("block_label") or raw_block.get("blockLabel") or "paragraph").strip()
        candidates.append(
            PaddleXLayoutBlock(
                text=text,
                block_type=_normalize_layout_block_type(label),
                bbox=tuple(float(coordinate) for coordinate in bbox),
            )
        )
    return tuple(candidates)


def build_paddlex_page_blocks(
    pages: list[PaddleXLayoutPage],
    *,
    separator: str = "\n\n",
) -> tuple[str, tuple[ParsedBlock, ...]]:
    """拼接页文本，并仅为可逐字顺序回切的布局块生成位置。"""
    markdown = separator.join(page.text for page in pages)
    blocks: list[ParsedBlock] = []
    offset = 0
    for page_index, page in enumerate(pages):
        if page_index:
            offset += len(separator)
        page_start = offset
        offset += len(page.text)
        blocks.append(
            ParsedBlock(
                start_char=page_start,
                end_char=offset,
                page_number=page.page_number,
                block_type="paragraph" if page.text else "empty",
                source_metadata={"position_kind": "layout_page"},
            )
        )

        search_from = 0
        for candidate in page.layout_blocks:
            local_start = page.text.find(candidate.text, search_from)
            if local_start < 0:
                continue
            local_end = local_start + len(candidate.text)
            search_from = local_end
            blocks.append(
                ParsedBlock(
                    start_char=page_start + local_start,
                    end_char=page_start + local_end,
                    page_number=page.page_number,
                    block_type=candidate.block_type,
                    bbox=candidate.bbox,
                    source_metadata={"position_kind": "layout_block"},
                )
            )

    return markdown, tuple(blocks)


def _valid_bbox(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(
            isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool) and math.isfinite(coordinate)
            for coordinate in value
        )
    )


def _normalize_layout_block_type(label: str) -> str:
    normalized = label.lower().replace("-", "_").replace(" ", "_")
    return {
        "title": "heading",
        "doc_title": "heading",
        "section_title": "heading",
        "text": "paragraph",
        "content": "paragraph",
        "table": "table",
        "image": "image",
        "figure": "image",
        "formula": "formula",
    }.get(normalized, normalized or "paragraph")
