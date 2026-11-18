"""本体版本定义校验与不可变快照差异计算。"""

from __future__ import annotations

import re
from typing import Any

VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENTITY_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
RELATION_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,255}$")


def normalize_ontology_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化一个可独立复现的本体快照。"""
    if not isinstance(definition, dict):
        raise ValueError("本体定义必须是对象")

    version = _required_text(definition.get("version"), "本体版本")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("本体版本只能包含字母、数字、点、下划线和连字符")
    name = _required_text(definition.get("name"), "本体名称")

    raw_entities = definition.get("entity_types")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise ValueError("本体至少需要一个实体类型")
    entities = [_normalize_entity_type(item) for item in raw_entities]
    entity_codes = _require_unique_codes(entities, "实体类型")

    raw_relations = definition.get("relation_types")
    if not isinstance(raw_relations, list):
        raise ValueError("关系类型必须是数组")
    relations = [_normalize_relation_type(item, entity_codes) for item in raw_relations]
    _require_unique_codes(relations, "关系类型")

    return {
        "version": version,
        "name": name,
        "entity_types": entities,
        "relation_types": relations,
    }


def build_ontology_change_set(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """从两个不可变快照生成新增、修改和废弃的确定性映射。"""
    normalized_current = normalize_ontology_definition(current)
    normalized_previous = normalize_ontology_definition(previous) if previous is not None else None
    return {
        "entity_types": _compare_types(
            normalized_previous["entity_types"] if normalized_previous else [],
            normalized_current["entity_types"],
        ),
        "relation_types": _compare_types(
            normalized_previous["relation_types"] if normalized_previous else [],
            normalized_current["relation_types"],
        ),
    }


def _normalize_entity_type(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("实体类型定义必须是对象")
    code = _required_text(item.get("code"), "实体类型编码")
    if not ENTITY_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"实体类型编码不合法: {code}")
    return {
        "code": code,
        "name_zh": _required_text(item.get("name_zh"), f"实体类型 {code} 中文名称"),
        "description": str(item.get("description") or "").strip(),
    }


def _normalize_relation_type(item: Any, entity_codes: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("关系类型定义必须是对象")
    code = _required_text(item.get("code"), "关系类型编码")
    if not RELATION_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"关系类型编码不合法: {code}")
    head_types = _normalize_endpoint_types(item.get("head_types"), code, "起点", entity_codes)
    tail_types = _normalize_endpoint_types(item.get("tail_types"), code, "终点", entity_codes)
    return {
        "code": code,
        "name_zh": _required_text(item.get("name_zh"), f"关系类型 {code} 中文名称"),
        "description": str(item.get("description") or "").strip(),
        "head_types": head_types,
        "tail_types": tail_types,
        "directed": _strict_bool(item.get("directed", True), code, "directed"),
        "allow_self": _strict_bool(item.get("allow_self", False), code, "allow_self"),
        "hypothesis_only": _strict_bool(item.get("hypothesis_only", False), code, "hypothesis_only"),
    }


def _normalize_endpoint_types(value: Any, relation_code: str, side: str, entity_codes: set[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"关系 {relation_code} 的{side}类型不能为空")
    types = [_required_text(item, f"关系 {relation_code} 的{side}类型") for item in value]
    if len(types) != len(set(types)):
        raise ValueError(f"关系 {relation_code} 的{side}类型存在重复")
    unknown = sorted(set(types) - entity_codes)
    if unknown:
        raise ValueError(f"关系 {relation_code} 引用了未知{side}实体类型: {', '.join(unknown)}")
    return types


def _strict_bool(value: Any, relation_code: str, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"关系 {relation_code} 的 {field} 必须是布尔值")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    return value.strip()


def _require_unique_codes(items: list[dict[str, Any]], label: str) -> set[str]:
    codes = [item["code"] for item in items]
    if len(codes) != len(set(codes)):
        raise ValueError(f"{label}编码不能重复")
    return set(codes)


def _compare_types(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    previous_by_code = {item["code"]: item for item in previous}
    current_by_code = {item["code"]: item for item in current}
    added = [
        {"code": code, "definition": current_by_code[code]}
        for code in sorted(current_by_code.keys() - previous_by_code.keys())
    ]
    deprecated = [
        {"code": code, "definition": previous_by_code[code]}
        for code in sorted(previous_by_code.keys() - current_by_code.keys())
    ]
    modified = [
        {
            "code": code,
            "previous_definition": previous_by_code[code],
            "current_definition": current_by_code[code],
        }
        for code in sorted(previous_by_code.keys() & current_by_code.keys())
        if previous_by_code[code] != current_by_code[code]
    ]
    return {"added": added, "modified": modified, "deprecated": deprecated}
