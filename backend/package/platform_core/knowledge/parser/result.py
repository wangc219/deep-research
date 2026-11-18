"""文档解析结果与安全运行谱系契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

UNIFIED_PARSER_VERSION = "platform-unified-parser-v2"
PARSED_TEXT_NORMALIZATION_VERSION = "postgres-text-v1"
PARSED_TEXT_REPLACEMENT_CHARACTER = "\ufffd"


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """解析器产生的原文 Block 位置，不包含模型推断字段。"""

    start_char: int
    end_char: int
    page_number: int | None = None
    block_type: str | None = None
    heading_path: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """转换为可写入 PostgreSQL JSONB 的稳定结构。"""
        return {
            "start_char": self.start_char,
            "end_char": self.end_char,
            "page_number": self.page_number,
            "block_type": self.block_type,
            "heading_path": list(self.heading_path),
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "source_metadata": dict(self.source_metadata),
        }


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """解析后的 Markdown 及可持久化、无凭据的解析器谱系。"""

    markdown: str
    parser_name: str
    parser_version: str = UNIFIED_PARSER_VERSION
    source_metadata: dict[str, Any] = field(default_factory=dict)
    blocks: tuple[ParsedBlock, ...] = ()


def normalize_parsed_document_text(document: ParsedDocument) -> ParsedDocument:
    """等长替换 PostgreSQL 不接受的 NUL，并记录可审计规范化谱系。"""
    nul_count = document.markdown.count("\x00")
    if nul_count == 0:
        return document

    source_metadata = dict(document.source_metadata)
    previous = source_metadata.get("text_normalization")
    if previous is not None and not isinstance(previous, dict):
        previous = {"parser_value": str(previous)}
    source_metadata["text_normalization"] = {
        **dict(previous or {}),
        "version": PARSED_TEXT_NORMALIZATION_VERSION,
        "nul_replacements": nul_count,
        "replacement": f"U+{ord(PARSED_TEXT_REPLACEMENT_CHARACTER):04X}",
        "offset_preserving": True,
    }
    return ParsedDocument(
        markdown=document.markdown.replace("\x00", PARSED_TEXT_REPLACEMENT_CHARACTER),
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        source_metadata=source_metadata,
        blocks=document.blocks,
    )
