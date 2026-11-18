"""从已审核别名和关系邻域构建 LightRAG 风格实体语义画像。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

ENTITY_SEMANTIC_PROFILE_VERSION = "defense-lightrag-entity-profile-v1"
DEFAULT_MAX_ALIASES = 32
DEFAULT_MAX_RELATIONS = 64
DEFAULT_MAX_CHARS = 12000


def build_entity_semantic_profile(
    *,
    entity_id: str,
    name: str,
    normalized_name: str,
    label: str,
    accepted_mentions: Iterable[str] = (),
    trusted_aliases: Iterable[str] = (),
    accepted_relations: Iterable[dict[str, Any]] = (),
    max_aliases: int = DEFAULT_MAX_ALIASES,
    max_relations: int = DEFAULT_MAX_RELATIONS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """生成稳定、去重且有字符上限的实体向量文本。"""

    canonical = _clean(name) or _clean(normalized_name)
    normalized = _clean(normalized_name) or canonical
    entity_type = _clean(label) or "Entity"
    aliases = _deduplicate(
        [*accepted_mentions, *trusted_aliases],
        excluded={_key(canonical), _key(normalized)},
        limit=max_aliases,
    )
    relation_lines = _relation_lines(
        entity_id=entity_id,
        relations=accepted_relations,
        limit=max_relations,
    )

    lines = [canonical, f"实体类型：{entity_type}"]
    if normalized and normalized != canonical:
        lines.append(f"标准名：{normalized}")
    if aliases:
        lines.append(f"已审核别名：{'、'.join(aliases)}")
    if relation_lines:
        lines.append("已审核关系邻域：")
        lines.extend(f"- {line}" for line in relation_lines)
    content = "\n".join(lines)
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip()


def _relation_lines(
    *,
    entity_id: str,
    relations: Iterable[dict[str, Any]],
    limit: int,
) -> list[str]:
    lines = []
    for relation in relations:
        source_id = str(relation.get("source_entity_id") or "")
        target_id = str(relation.get("target_entity_id") or "")
        relation_type = _clean(relation.get("relation_type"))
        if not relation_type:
            continue
        if source_id == entity_id:
            neighbor = _typed_name(relation.get("target_name"), relation.get("target_label"))
            line = f"{relation_type} → {neighbor}"
        elif target_id == entity_id:
            neighbor = _typed_name(relation.get("source_name"), relation.get("source_label"))
            line = f"{neighbor} → {relation_type}"
        else:
            continue
        if line not in lines:
            lines.append(line)
    return sorted(lines, key=lambda item: (item.casefold(), item))[: max(limit, 0)]


def _typed_name(name: Any, label: Any) -> str:
    normalized_name = _clean(name) or "未知实体"
    normalized_label = _clean(label)
    return f"{normalized_name} [{normalized_label}]" if normalized_label else normalized_name


def _deduplicate(values: Iterable[Any], *, excluded: set[str], limit: int) -> list[str]:
    result = []
    seen = set(excluded)
    for value in values:
        normalized = _clean(value)
        key = _key(normalized)
        if not normalized or not key or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result[: max(limit, 0)]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _key(value: str) -> str:
    return _clean(value).casefold()
