"""为 LightRAG 构造只删除高确定性排版空白、可回切原文的临时视图。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_CJK_SECTION_LABELS = frozenset({"摘要", "关键词", "引言", "结论", "参考文献"})
_LAYOUT_WHITESPACE = re.compile(r"[ \u00a0\u2000-\u200a\u202f\u205f\u3000\r\n]+")
_ASCII_TOKEN_LEFT = re.compile(r"[A-Za-z0-9][A-Za-z0-9+./-]{0,15}$")
_ASCII_TOKEN_RIGHT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+./-]{0,15}")


@dataclass(frozen=True, slots=True)
class LayoutWhitespaceDeletion:
    """一处从临时视图删除、但仍保留在权威原文中的排版空白。"""

    original_start: int
    original_end: int
    deleted_text: str
    reason: str
    normalized_position: int


@dataclass(frozen=True, slots=True)
class LayoutMappedSpan:
    """临时视图与原文间的字符 Span 映射。"""

    start: int
    end: int
    normalization_dependent: bool


@dataclass(frozen=True, slots=True)
class LayoutNormalizedTextView:
    """不改写字符、只移除排版空白的非持久化文本视图。"""

    original_text: str
    normalized_text: str
    deletions: tuple[LayoutWhitespaceDeletion, ...]
    normalized_to_original: tuple[int, ...]
    original_prefix_kept: tuple[int, ...]

    def normalized_span_to_original(self, start: int, end: int) -> LayoutMappedSpan | None:
        """把规范化 Span 回切为包含原始排版空白的原文 Span。"""
        if not _valid_span(start, end, len(self.normalized_text)):
            return None
        original_start = self.normalized_to_original[start]
        original_end = self.normalized_to_original[end - 1] + 1
        dependent = any(
            original_start < deletion.original_end and original_end > deletion.original_start
            for deletion in self.deletions
        )
        return LayoutMappedSpan(original_start, original_end, dependent)

    def original_span_to_normalized(self, start: int, end: int) -> LayoutMappedSpan | None:
        """把原文 Span 映射到规范化视图；纯空白 Span 不产生候选。"""
        if not _valid_span(start, end, len(self.original_text)):
            return None
        normalized_start = self.original_prefix_kept[start]
        normalized_end = self.original_prefix_kept[end]
        if normalized_end <= normalized_start:
            return None
        mapped_original = self.normalized_to_original[normalized_start:normalized_end]
        if not mapped_original or mapped_original[0] < start or mapped_original[-1] >= end:
            return None
        dependent = any(start < deletion.original_end and end > deletion.original_start for deletion in self.deletions)
        return LayoutMappedSpan(normalized_start, normalized_end, dependent)

    def deletion_manifest(self) -> list[dict[str, Any]]:
        """返回不含正文字符、可用于谱系和人工审核的删除清单。"""
        return [
            {
                "original_start": item.original_start,
                "original_end": item.original_end,
                "deleted_whitespace": item.deleted_text,
                "reason": item.reason,
                "normalized_position": item.normalized_position,
                "temporary_view_only": True,
            }
            for item in self.deletions
        ]


def build_layout_normalized_text_view(
    source_text: str,
    *,
    max_deletions: int = 256,
    max_whitespace_chars: int = 8,
) -> LayoutNormalizedTextView:
    """仅删除 CJK 字间和短技术缩写周围的高确定性排版空白。"""
    if isinstance(max_deletions, bool) or not isinstance(max_deletions, int) or not 1 <= max_deletions <= 4096:
        raise ValueError("max_deletions 必须是 1 到 4096 之间的整数")
    if (
        isinstance(max_whitespace_chars, bool)
        or not isinstance(max_whitespace_chars, int)
        or not 1 <= max_whitespace_chars <= 32
    ):
        raise ValueError("max_whitespace_chars 必须是 1 到 32 之间的整数")

    deletion_specs: list[tuple[int, int, str]] = []
    for match in _LAYOUT_WHITESPACE.finditer(source_text):
        if len(deletion_specs) >= max_deletions:
            break
        whitespace = match.group(0)
        if len(whitespace) > max_whitespace_chars:
            continue
        reason = _deletion_reason(source_text, match.start(), match.end(), whitespace)
        if reason:
            deletion_specs.append((match.start(), match.end(), reason))

    deleted_positions = {position for start, end, _reason in deletion_specs for position in range(start, end)}
    normalized_chars: list[str] = []
    normalized_to_original: list[int] = []
    original_prefix_kept = [0]
    kept_count = 0
    for position, char in enumerate(source_text):
        if position not in deleted_positions:
            normalized_chars.append(char)
            normalized_to_original.append(position)
            kept_count += 1
        original_prefix_kept.append(kept_count)

    deletions = tuple(
        LayoutWhitespaceDeletion(
            original_start=start,
            original_end=end,
            deleted_text=source_text[start:end],
            reason=reason,
            normalized_position=original_prefix_kept[start],
        )
        for start, end, reason in deletion_specs
    )
    return LayoutNormalizedTextView(
        original_text=source_text,
        normalized_text="".join(normalized_chars),
        deletions=deletions,
        normalized_to_original=tuple(normalized_to_original),
        original_prefix_kept=tuple(original_prefix_kept),
    )


def candidates_for_layout_view(
    result: dict[str, Any],
    view: LayoutNormalizedTextView,
) -> dict[str, Any]:
    """把既有原文候选映射进规范化视图，供 LightRAG 去重和补漏。"""
    entities: list[dict[str, Any]] = []
    entity_by_ref: dict[str, dict[str, Any]] = {}
    for raw in result.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        mapped = view.original_span_to_normalized(raw.get("start"), raw.get("end"))
        if mapped is None:
            continue
        normalized_text = view.normalized_text[mapped.start : mapped.end]
        original_text = view.original_text[int(raw["start"]) : int(raw["end"])]
        if str(raw.get("text") or "") != original_text:
            continue
        entity = {
            **raw,
            "text": normalized_text,
            "start": mapped.start,
            "end": mapped.end,
            "original_text": original_text,
        }
        entities.append(entity)
        for ref in _entity_refs(entity):
            entity_by_ref[ref] = entity
        original_id = str(raw.get("id") or "")
        original_mention = str(raw.get("text") or "")
        if original_id:
            entity_by_ref[original_id] = entity
        if original_mention:
            entity_by_ref[original_mention] = entity

    relations: list[dict[str, Any]] = []
    for raw in result.get("relations") or []:
        if not isinstance(raw, dict):
            continue
        source = _resolve_endpoint(raw.get("source"), entity_by_ref)
        target = _resolve_endpoint(raw.get("target"), entity_by_ref)
        if source is None or target is None:
            continue
        evidence_spans: list[dict[str, int]] = []
        invalid_evidence = False
        for span in raw.get("evidence_spans") or []:
            if not isinstance(span, dict):
                invalid_evidence = True
                break
            mapped = view.original_span_to_normalized(span.get("start"), span.get("end"))
            if mapped is None:
                invalid_evidence = True
                break
            evidence_spans.append({"start": mapped.start, "end": mapped.end})
        if invalid_evidence:
            continue
        relation = {**raw, "source": source, "target": target}
        if raw.get("evidence_spans"):
            relation["evidence_spans"] = evidence_spans
        relations.append(relation)
    return {"entities": entities, "relations": relations, "metadata": {}}


def remap_layout_view_candidates(
    prepared: dict[str, Any],
    view: LayoutNormalizedTextView,
    *,
    original_known_entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """把 LightRAG 候选回切原文，保留规范化术语并强制进入待审核流程。"""
    original_by_id = {
        str(entity.get("id") or ""): entity
        for entity in original_known_entities
        if isinstance(entity, dict) and str(entity.get("id") or "")
    }
    entities: list[dict[str, Any]] = []
    entity_by_id = dict(original_by_id)
    dropped_entities = 0
    for raw in prepared.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        mapped = view.normalized_span_to_original(raw.get("start"), raw.get("end"))
        if mapped is None:
            dropped_entities += 1
            continue
        entity_id = str(raw.get("id") or "")
        normalized_text = str(raw.get("text") or "")
        original_text = view.original_text[mapped.start : mapped.end]
        entity = {
            **raw,
            "text": original_text,
            "normalized_text": normalized_text,
            "start": mapped.start,
            "end": mapped.end,
            "review_status": "pending",
            "expert_review_required": True,
            "model_sources": ["lightrag_llm_layout_normalized_initial"],
            "layout_normalized_by_platform": mapped.normalization_dependent,
            "layout_normalization_context_used": True,
        }
        entities.append(entity)
        if entity_id:
            entity_by_id[entity_id] = entity

    relations: list[dict[str, Any]] = []
    dropped_relations = 0
    for raw in prepared.get("relations") or []:
        if not isinstance(raw, dict):
            continue
        source_id = _endpoint_id(raw.get("source"))
        target_id = _endpoint_id(raw.get("target"))
        source = entity_by_id.get(source_id)
        target = entity_by_id.get(target_id)
        mapped_spans: list[dict[str, int]] = []
        for span in raw.get("evidence_spans") or []:
            if not isinstance(span, dict):
                mapped_spans = []
                break
            mapped = view.normalized_span_to_original(span.get("start"), span.get("end"))
            if mapped is None:
                mapped_spans = []
                break
            mapped_spans.append({"start": mapped.start, "end": mapped.end})
        if source is None or target is None or not mapped_spans:
            dropped_relations += 1
            continue
        relations.append(
            {
                **raw,
                "source": source,
                "target": target,
                "evidence_quote": "",
                "evidence_spans": mapped_spans,
                "review_status": "pending",
                "expert_review_required": True,
                "model_sources": ["lightrag_llm_layout_normalized_initial"],
                "layout_normalized_by_platform": True,
                "layout_normalization_context_used": True,
            }
        )

    metadata = dict(prepared.get("metadata") or {})
    metadata.update(
        {
            "stage": "layout_normalized_initial_enhancement",
            "original_text_preserved": True,
            "temporary_layout_normalized_view": True,
            "layout_normalization_deletions": view.deletion_manifest(),
            "layout_deletion_count": len(view.deletions),
            "layout_deleted_char_count": sum(len(item.deleted_text) for item in view.deletions),
            "remap_dropped_entities": dropped_entities,
            "remap_dropped_relations": dropped_relations,
            "authority_write_enabled": False,
        }
    )
    return {"entities": entities, "relations": relations, "metadata": metadata}


def _deletion_reason(source: str, start: int, end: int, whitespace: str) -> str | None:
    if start == 0 or end >= len(source):
        return None
    left = source[start - 1]
    right = source[end]
    has_line_break = "\n" in whitespace or "\r" in whitespace

    if _is_cjk(left) and _is_cjk(right):
        if not has_line_break:
            return "cjk_intercharacter_layout_space"
        if left + right in _CJK_SECTION_LABELS and _line_break_count(whitespace) <= 2:
            return "split_cjk_section_label"
        return None

    if has_line_break:
        return None
    if _is_cjk(left):
        token_match = _ASCII_TOKEN_RIGHT.match(source[end:])
        if token_match and _is_short_technical_token(token_match.group(0)):
            return "cjk_technical_token_boundary"
    if _is_cjk(right):
        token_match = _ASCII_TOKEN_LEFT.search(source[:start])
        if token_match and _is_short_technical_token(token_match.group(0)):
            return "technical_token_cjk_boundary"
    return None


def _is_cjk(char: str) -> bool:
    return "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def _is_short_technical_token(token: str) -> bool:
    letters = [char for char in token if char.isascii() and char.isalpha()]
    return (
        bool(token)
        and len(token) <= 16
        and (
            any(char.isdigit() for char in token)
            or (letters and all(char.isupper() for char in letters) and len(letters) <= 12)
        )
    )


def _line_break_count(value: str) -> int:
    return len(re.findall(r"\r\n|\r|\n", value))


def _valid_span(start: Any, end: Any, text_length: int) -> bool:
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= text_length
    )


def _entity_refs(entity: dict[str, Any]) -> set[str]:
    return {value for value in (str(entity.get("id") or ""), str(entity.get("text") or "")) if value}


def _endpoint_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")


def _resolve_endpoint(value: Any, refs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for ref in _entity_refs(value):
            if ref in refs:
                return refs[ref]
        return None
    return refs.get(str(value or ""))
