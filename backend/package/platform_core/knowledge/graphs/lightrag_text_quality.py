"""LightRAG 增强各阶段共用的原文损伤检测信号。"""

from __future__ import annotations

import re
from dataclasses import dataclass

OCR_DAMAGE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])[@#^~|]{1,2}[A-Za-z]{1,4}(?![A-Za-z0-9])"),
    re.compile(r"(?<![\w])[=<>+*/\\-]{1,3}\?(?![\w])"),
    re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffd]"),
)
_DENSE_SYMBOL_CLUSTER = re.compile(r"[!\"#$%&'()*+,./:;<=>?@\[\\\]^_`{|}~’“”]{3,}")
_MALFORMED_NUMERIC_TOKEN = re.compile(r"(?<!\S)[,.;:]\d{1,3}(?!\S)")
_LATIN_LEXICAL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+._/-]{1,}")
_REFERENCE_INDEX = re.compile(r"(?:^|\n)\s*\[\s*\d{1,3}\s*\]\s+")
_REFERENCE_DESIGNATOR = re.compile(r"\[(?:J|C|M|D|R|S|EB/OL)\]", re.IGNORECASE)
_REFERENCE_PROCEEDINGS = re.compile(
    r"\b(?:proceedings|conference|symposium|workshop|transactions|journal)\b",
    re.IGNORECASE,
)
_REFERENCE_YEAR_PAGES = re.compile(r"\b(?:19|20)\d{2}\s*[,;:]\s*\d+(?:\s*[-–]\s*\d+)?")
_REFERENCE_AUTHOR_SEQUENCE = re.compile(r"\b[A-Z][A-Z-]{1,20}(?:\s+[A-Z])?\s*,\s*[A-Z][A-Z-]{1,20}")


@dataclass(frozen=True, slots=True)
class OCRDamageSpan:
    """一个可定位但不改写原文的 OCR/排版损伤。"""

    start: int
    end: int
    text: str
    reason: str


def substantive_text_metrics(text: str) -> dict[str, int | bool]:
    """以语言无关的词汇量信号识别值得补抽的实质文本。"""
    cjk_char_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_token_count = len(_LATIN_LEXICAL_TOKEN.findall(text))
    lexical_unit_count = cjk_char_count // 2 + latin_token_count
    return {
        "cjk_char_count": cjk_char_count,
        "latin_token_count": latin_token_count,
        "lexical_unit_count": lexical_unit_count,
        "is_substantive": lexical_unit_count >= 4,
    }


def reference_section_metrics(text: str) -> dict[str, int | bool]:
    """识别参考文献密集 Block，避免把论文标题、作者和出版物当作技术实体。"""

    reference_index_count = len(_REFERENCE_INDEX.findall(text))
    designator_count = len(_REFERENCE_DESIGNATOR.findall(text))
    proceedings_count = len(_REFERENCE_PROCEEDINGS.findall(text))
    year_pages_count = len(_REFERENCE_YEAR_PAGES.findall(text))
    author_sequence_count = len(_REFERENCE_AUTHOR_SEQUENCE.findall(text))
    score = (
        reference_index_count * 3 + designator_count * 2 + proceedings_count + year_pages_count + author_sequence_count
    )
    is_reference_section = (
        reference_index_count >= 2
        or designator_count >= 2
        or score >= 6
        or (proceedings_count >= 2 and year_pages_count >= 1)
    )
    return {
        "reference_index_count": reference_index_count,
        "reference_designator_count": designator_count,
        "reference_proceedings_count": proceedings_count,
        "reference_year_pages_count": year_pages_count,
        "reference_author_sequence_count": author_sequence_count,
        "reference_likelihood_score": score,
        "is_reference_section": is_reference_section,
    }


def detect_ocr_damage(text: str) -> list[OCRDamageSpan]:
    """保守识别明显乱码和脱离上下文的排版占位符。"""
    found: dict[tuple[int, int], OCRDamageSpan] = {}
    for pattern in OCR_DAMAGE_PATTERNS:
        for match in pattern.finditer(text):
            span = OCRDamageSpan(
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                reason="疑似 OCR/排版损伤，禁止自动规范化为标准实体",
            )
            found[(span.start, span.end)] = span
    for match in _DENSE_SYMBOL_CLUSTER.finditer(text):
        if len(set(match.group(0))) < 2:
            continue
        start = match.start() - 1 if match.start() and text[match.start() - 1].isdigit() else match.start()
        span = OCRDamageSpan(
            start=start,
            end=match.end(),
            text=text[start : match.end()],
            reason="疑似连续 OCR 替换符，禁止作为实体或技术编号",
        )
        found[(span.start, span.end)] = span
    for match in _MALFORMED_NUMERIC_TOKEN.finditer(text):
        span = OCRDamageSpan(
            start=match.start(),
            end=match.end(),
            text=match.group(0),
            reason="疑似缺失前导数字的 OCR 数值片段，禁止自动补写原文",
        )
        found[(span.start, span.end)] = span
    return [found[key] for key in sorted(found)]
