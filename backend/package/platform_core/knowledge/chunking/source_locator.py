"""把派生 Chunk 安全定位回原始 Markdown 字符区间。"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class LocatedSourceText:
    """保留原文内容及 exclusive-end 字符位置。"""

    content: str
    start_char: int
    end_char: int
    match_kind: Literal["exact", "whitespace_normalized"]


class SourceTextLocator:
    """按文档顺序定位 Chunk，且不把非连续派生文本伪装成原文 Span。"""

    def __init__(self, source_text: str) -> None:
        self._source_text = source_text or ""
        compact_chars: list[str] = []
        source_positions: list[int] = []
        for position, character in enumerate(self._source_text):
            if character.isspace():
                continue
            compact_chars.append(character)
            source_positions.append(position)
        self._compact_source = "".join(compact_chars)
        self._source_positions = source_positions

    def locate(self, chunk_text: str, *, search_from: int = 0) -> LocatedSourceText | None:
        """返回可证明连续对应的原文；仅空白差异时恢复原始空白。"""
        text = (chunk_text or "").strip()
        if not text or not self._source_text:
            return None

        safe_search_from = max(int(search_from or 0), 0)
        exact_start = self._source_text.find(text, safe_search_from)
        if exact_start >= 0:
            exact_end = exact_start + len(text)
            return LocatedSourceText(
                content=self._source_text[exact_start:exact_end],
                start_char=exact_start,
                end_char=exact_end,
                match_kind="exact",
            )

        compact_chunk = _compact_whitespace(text)
        if not compact_chunk or not self._source_positions:
            return None

        compact_search_from = bisect.bisect_left(self._source_positions, safe_search_from)
        compact_start = self._compact_source.find(compact_chunk, compact_search_from)
        if compact_start < 0:
            return None

        compact_end = compact_start + len(compact_chunk)
        source_start = self._source_positions[compact_start]
        source_end = self._source_positions[compact_end - 1] + 1
        source_slice = self._source_text[source_start:source_end]
        if _compact_whitespace(source_slice) != compact_chunk:
            return None

        return LocatedSourceText(
            content=source_slice,
            start_char=source_start,
            end_char=source_end,
            match_kind="whitespace_normalized",
        )


def _compact_whitespace(text: str) -> str:
    return "".join(character for character in text if not character.isspace())
