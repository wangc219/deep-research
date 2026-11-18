"""解析文本进入向量与图谱抽取前的确定性质量门禁。"""

from __future__ import annotations

import re
from typing import Any

CID_GLYPH_PATTERN = re.compile(r"/G[0-9A-Fa-f]{2,6}(?=$|[\s/])")


def analyze_parsed_text(text: str) -> dict[str, Any]:
    """返回不含原文的解析质量指标和修复建议。"""
    character_count = len(text)
    non_whitespace_count = sum(not character.isspace() for character in text)
    readable_count = sum(character.isalnum() for character in text)
    replacement_count = text.count("\ufffd")
    nul_count = text.count("\x00")
    cid_tokens = CID_GLYPH_PATTERN.findall(text)
    cid_token_chars = sum(len(token) for token in cid_tokens)
    cid_ratio = cid_token_chars / max(character_count, 1)
    replacement_ratio = replacement_count / max(character_count, 1)

    issues: list[str] = []
    if non_whitespace_count == 0:
        issues.append("empty_text")
    elif readable_count < 80:
        issues.append("insufficient_readable_text")
    if len(cid_tokens) >= 8 and cid_ratio >= 0.08:
        issues.append("cid_glyph_encoding")
    if replacement_count >= 8 and replacement_ratio >= 0.02:
        issues.append("replacement_character_corruption")
    if nul_count:
        issues.append("nul_character")

    requires_ocr = bool(
        {"empty_text", "insufficient_readable_text", "cid_glyph_encoding", "replacement_character_corruption"}
        & set(issues)
    )
    return {
        "contract_version": "parsed-text-quality-v1",
        "character_count": character_count,
        "non_whitespace_count": non_whitespace_count,
        "readable_count": readable_count,
        "replacement_count": replacement_count,
        "replacement_ratio": round(replacement_ratio, 6),
        "nul_count": nul_count,
        "cid_glyph_tokens": len(cid_tokens),
        "cid_glyph_ratio": round(cid_ratio, 6),
        "issues": issues,
        "ready_for_extraction": not issues,
        "recommended_route": "ocr" if requires_ocr else "keep_current_parser",
    }
