"""分析五类实体与真实联系的召回覆盖，并为封闭关系候选提供稳定优先级。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from platform_core.knowledge.graphs.core_semantic_roles import (
    CORE_ROLE_ORDER,
    core_role_for_entity_type,
)

FIVE_ROLE_EXTRACTION_REVISION = "defense-five-role-extraction-priority-v1"

# 五类链按语义顺序定义，但图中事实关系仍服从本体声明的实际方向。
ADJACENT_SEMANTIC_TRANSITIONS = (
    ("concept", "principle"),
    ("principle", "technology"),
    ("technology", "capability"),
    ("capability", "application"),
)

# 这些跨级连接能表达实用语义联系，但不得取代相邻联系，也不能仅凭类型自动建边。
PRACTICAL_SEMANTIC_BRIDGES = frozenset(
    {
        frozenset(("concept", "technology")),
        frozenset(("concept", "capability")),
        frozenset(("principle", "capability")),
        frozenset(("technology", "application")),
    }
)


def semantic_transition(source_type: str, target_type: str) -> dict[str, Any]:
    """返回端点在五类链中的位置；只用于召回排序，不改变关系方向。"""
    source_role = core_role_for_entity_type(source_type)
    target_role = core_role_for_entity_type(target_type)
    if not source_role or not target_role or source_role == target_role:
        return {
            "source_role": source_role or "supporting",
            "target_role": target_role or "supporting",
            "transition": "",
            "priority": 0.0,
            "kind": "supporting",
        }

    role_pair = frozenset((source_role, target_role))
    for left, right in ADJACENT_SEMANTIC_TRANSITIONS:
        if role_pair == frozenset((left, right)):
            return {
                "source_role": source_role,
                "target_role": target_role,
                "transition": f"{left}_to_{right}",
                "priority": 1.0,
                "kind": "adjacent",
            }
    if role_pair in PRACTICAL_SEMANTIC_BRIDGES:
        ordered = sorted((source_role, target_role), key=CORE_ROLE_ORDER.index)
        return {
            "source_role": source_role,
            "target_role": target_role,
            "transition": f"{ordered[0]}_to_{ordered[1]}",
            "priority": 0.65,
            "kind": "practical_bridge",
        }
    return {
        "source_role": source_role,
        "target_role": target_role,
        "transition": "",
        "priority": 0.15,
        "kind": "other_core",
    }


def analyze_five_role_recall(
    entities: Iterable[Any],
    relations: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """按 canonical 端点统计已抽联系与复查目标，不猜测不存在的事实。"""
    entity_by_id: dict[str, str] = {}
    role_counts: Counter[str] = Counter()
    for entity in entities:
        entity_id = str(_field(entity, "entity_id") or _field(entity, "id") or "").strip()
        entity_type = str(_field(entity, "type") or _field(entity, "label") or "").strip()
        role = core_role_for_entity_type(entity_type)
        if not entity_id or not role:
            continue
        entity_by_id[entity_id] = role
        role_counts[role] += 1

    relations_provided = relations is not None
    observed_links: set[frozenset[str]] = set()
    for relation in relations or ():
        source_id = str(
            _field(relation, "source_entity_id") or _field(relation, "source_id") or _field(relation, "source") or ""
        ).strip()
        target_id = str(
            _field(relation, "target_entity_id") or _field(relation, "target_id") or _field(relation, "target") or ""
        ).strip()
        source_role = entity_by_id.get(source_id, "")
        target_role = entity_by_id.get(target_id, "")
        if source_role and target_role and source_role != target_role:
            observed_links.add(frozenset((source_role, target_role)))

    present_roles = [role for role in CORE_ROLE_ORDER if role_counts[role]]
    missing_roles = [role for role in CORE_ROLE_ORDER if not role_counts[role]]
    missing_transitions = []
    unavailable_transitions = []
    observed_transitions = []
    for left, right in ADJACENT_SEMANTIC_TRANSITIONS:
        name = f"{left}_to_{right}"
        if left not in role_counts or right not in role_counts:
            unavailable_transitions.append(name)
        elif frozenset((left, right)) in observed_links:
            observed_transitions.append(name)
        else:
            missing_transitions.append(name)

    return {
        "revision": FIVE_ROLE_EXTRACTION_REVISION,
        "relations_provided": relations_provided,
        "present_roles": present_roles,
        "missing_roles": missing_roles,
        "role_counts": {role: role_counts[role] for role in CORE_ROLE_ORDER},
        "observed_transitions": observed_transitions,
        "missing_transitions": missing_transitions,
        "unavailable_transitions": unavailable_transitions,
        "all_five_roles_observed": not missing_roles,
        "all_adjacent_transitions_observed": not missing_transitions and not unavailable_transitions,
    }


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
