"""从 Markdown 字符位置恢复可追溯的结构化 Block 元数据。"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ORDERED_LIST_PATTERN = re.compile(r"^\d+[.)、]\s+")
_UNORDERED_LIST_PATTERN = re.compile(r"^[-*+]\s+")


@dataclass(frozen=True, slots=True)
class _HeadingSnapshot:
    offset: int
    path: tuple[str, ...]


class MarkdownBlockMetadataIndex:
    """一次扫描 Markdown，并按 Chunk 起始偏移返回标题路径与 Block 类型。"""

    def __init__(self, markdown: str) -> None:
        self._snapshots = self._build_heading_snapshots(markdown or "")
        self._offsets = [snapshot.offset for snapshot in self._snapshots]

    def metadata_for(
        self,
        *,
        chunk_text: str,
        start_char: int | None,
        filename: str,
        processing_params: dict[str, Any],
    ) -> dict[str, Any]:
        """生成不虚构页码或 bbox 的最小 Block 谱系。"""
        heading_path = self._heading_path(start_char)
        parser_blocks = _matching_parser_blocks(
            processing_params.get("parser_blocks"),
            start_char=start_char,
            end_char=(start_char + len(chunk_text)) if start_char is not None else None,
        )
        containing_bbox_blocks = [
            block
            for block in parser_blocks
            if _valid_bbox(block[1].get("bbox"))
            and int(block[1]["start_char"]) <= int(start_char or 0)
            and int(block[1]["end_char"]) >= int((start_char or 0) + len(chunk_text))
        ]
        primary_match = min(
            containing_bbox_blocks or parser_blocks,
            key=lambda block: int(block[1]["end_char"]) - int(block[1]["start_char"]),
            default=None,
        )
        primary_block = primary_match[1] if primary_match else {}
        parser_name = str(processing_params.get("parser_name") or _legacy_parser_name(filename))
        parser_version = str(processing_params.get("parser_version") or "legacy-unversioned")
        document_version = max(int(processing_params.get("document_version") or 1), 1)
        parser_source_metadata = processing_params.get("parser_source_metadata")
        source_metadata = dict(parser_source_metadata) if isinstance(parser_source_metadata, dict) else {}
        source_metadata.update(
            {
                "source_file": filename,
                "position_kind": "markdown_char" if start_char is not None else "derived_chunk",
            }
        )
        if processing_params.get("document_content_hash"):
            source_metadata["document_content_hash"] = str(processing_params["document_content_hash"])
        if parser_blocks:
            source_metadata["source_block_indices"] = [block[0] for block in parser_blocks]
            source_metadata["source_page_numbers"] = list(
                dict.fromkeys(
                    int(block[1]["page_number"]) for block in parser_blocks if block[1].get("page_number") is not None
                )
            )
            block_source_metadata = primary_block.get("source_metadata")
            if isinstance(block_source_metadata, dict):
                source_metadata["parser_block"] = dict(block_source_metadata)
        structured_heading_path = primary_block.get("heading_path")
        if not heading_path and isinstance(structured_heading_path, list):
            heading_path = [str(item) for item in structured_heading_path if str(item).strip()]
        bbox = primary_block.get("bbox") if len(containing_bbox_blocks) == 1 else None
        return {
            "document_version": document_version,
            "page_number": primary_block.get("page_number"),
            "block_type": primary_block.get("block_type") or _detect_block_type(chunk_text),
            "heading_path": heading_path,
            "bbox": list(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "source_metadata": source_metadata,
        }

    def _heading_path(self, start_char: int | None) -> list[str]:
        if start_char is None or not self._snapshots:
            return []
        index = bisect.bisect_right(self._offsets, int(start_char)) - 1
        return list(self._snapshots[index].path) if index >= 0 else []

    @staticmethod
    def _build_heading_snapshots(markdown: str) -> list[_HeadingSnapshot]:
        snapshots: list[_HeadingSnapshot] = []
        path: list[str] = []
        offset = 0
        for line in markdown.splitlines(keepends=True):
            match = _HEADING_PATTERN.match(line.strip())
            if match:
                level = len(match.group(1))
                title = match.group(2).strip().strip("#").strip()
                path = path[: level - 1]
                path.append(title)
                snapshots.append(_HeadingSnapshot(offset=offset, path=tuple(path)))
            offset += len(line)
        return snapshots


def _matching_parser_blocks(
    value: object,
    *,
    start_char: int | None,
    end_char: int | None,
) -> list[tuple[int, dict[str, Any]]]:
    """返回与 Chunk 字符区间重叠的合法解析器 Block。"""
    if start_char is None or end_char is None or not isinstance(value, list):
        return []

    matches: list[tuple[int, dict[str, Any]]] = []
    for index, raw_block in enumerate(value):
        if not isinstance(raw_block, dict):
            continue
        try:
            block_start = int(raw_block["start_char"])
            block_end = int(raw_block["end_char"])
        except (KeyError, TypeError, ValueError):
            continue
        if block_start < end_char and start_char < block_end:
            matches.append((index, raw_block))
    return matches


def _valid_bbox(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(coordinate, (int, float)) for coordinate in value)
    )


def _detect_block_type(text: str) -> str:
    first_line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    if not first_line:
        return "empty"
    if _HEADING_PATTERN.match(first_line):
        return "heading"
    if first_line.startswith("```"):
        return "code"
    if first_line.startswith("|") and first_line.endswith("|"):
        return "table"
    if first_line.startswith("!["):
        return "image"
    if first_line.startswith(">"):
        return "quote"
    if _ORDERED_LIST_PATTERN.match(first_line) or _UNORDERED_LIST_PATTERN.match(first_line):
        return "list"
    return "paragraph"


def _legacy_parser_name(filename: str) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    return {
        ".txt": "native_text",
        ".md": "native_markdown",
        ".html": "markdownify",
        ".htm": "markdownify",
        ".csv": "pandas_csv",
        ".json": "stdlib_json",
    }.get(suffix, "legacy_unrecorded")
