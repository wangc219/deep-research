"""从跨文档证据构建 LightRAG 风格关系语义画像。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

RELATION_SEMANTIC_PROFILE_VERSION = "defense-lightrag-relation-profile-v2"
DEFAULT_MAX_EVIDENCE = 16
DEFAULT_MAX_CONDITIONS = 16
DEFAULT_MAX_CHARS = 12000


def build_relation_semantic_profile(
    *,
    relation_type: str,
    source_name: str,
    source_label: str,
    target_name: str,
    target_label: str,
    base_content: str = "",
    relation_mentions: Iterable[dict[str, Any]] = (),
    max_evidence: int = DEFAULT_MAX_EVIDENCE,
    max_conditions: int = DEFAULT_MAX_CONDITIONS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """聚合 accepted/pending 证据，生成统一关系向量的稳定文本。"""

    mentions = [item for item in relation_mentions if isinstance(item, dict)]
    source = _typed_name(source_name, source_label)
    target = _typed_name(target_name, target_label)
    relation = _clean(relation_type) or "RELATED_TO"
    canonical = _clean(base_content) or f"{source} → {relation} → {target}"
    file_ids = {_clean(item.get("file_id")) for item in mentions if _clean(item.get("file_id"))}
    claim_levels = _deduplicate(
        (item.get("claim_level") for item in mentions),
        limit=8,
    )
    review_statuses = _deduplicate(
        (item.get("review_status") for item in mentions),
        limit=8,
    )
    conditions = _deduplicate(
        (
            condition
            for item in mentions
            for condition in (item.get("applicable_conditions") or [])
            if isinstance(item.get("applicable_conditions") or [], list)
        ),
        limit=max_conditions,
    )
    evidence = _deduplicate(
        (item.get("evidence_quote") or item.get("text") for item in mentions),
        limit=max_evidence,
    )
    rationales = _deduplicate((item.get("reasoning_basis") for item in mentions), limit=max_evidence)

    lines = [
        canonical,
        f"关系类型：{relation}",
        f"源实体：{source}",
        f"目标实体：{target}",
    ]
    if file_ids:
        lines.append(f"独立来源数：{len(file_ids)}")
    if claim_levels:
        lines.append(f"知识层级：{'、'.join(claim_levels)}")
    if review_statuses:
        lines.append(f"证据状态：{'、'.join(review_statuses)}")
    if conditions:
        lines.append(f"适用条件：{'；'.join(conditions)}")
    if rationales:
        lines.append(f"关系依据：{'；'.join(rationales)}")
    if evidence:
        lines.append("跨文档证据：")
        lines.extend(f"- {item}" for item in evidence)
    content = "\n".join(lines)
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip()


def _typed_name(name: Any, label: Any) -> str:
    normalized_name = _clean(name) or "未知实体"
    normalized_label = _clean(label)
    return f"{normalized_name} [{normalized_label}]" if normalized_label else normalized_name


def _deduplicate(values: Iterable[Any], *, limit: int) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = _clean(value)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= max(limit, 0):
            break
    return result


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
