"""把自然语言研发需求解析为可映射到知识图谱的结构化需求框架。"""

from __future__ import annotations

import re
from typing import Any

from platform_core.knowledge.graphs.graph_utils import normalize_entity_name

REQUIREMENT_ANALYSIS_VERSION = "defense-requirement-analysis-v2"

_CLAUSE_SPLITTER = re.compile(r"[\n。；;！？!?]+")
_QUANTITATIVE_CONSTRAINT = re.compile(
    r"(?:不超过|不少于|不低于|不高于|至少|至多|小于|大于|低于|高于|达到|≤|≥|<|>)?\s*"
    r"\d+(?:\.\d+)?\s*(?:%|毫秒|秒|分钟|小时|米|千米|公里|赫兹|千赫|兆赫|吉赫|"
    r"Hz|kHz|MHz|GHz|瓦|千瓦|公斤|千克|吨|℃|度|dB|Gbps|Mbps|次|个|架|套)"
)

_CAPABILITY_MARKERS = (
    "能力",
    "性能",
    "效能",
    "探测",
    "识别",
    "跟踪",
    "定位",
    "感知",
    "通信",
    "抗干扰",
    "生存性",
    "可靠性",
    "精度",
    "时延",
    "吞吐",
)
_CAPABILITY_VERBS = ("提升", "增强", "实现", "具备", "降低", "缩短", "提高", "支撑", "保障")
_SCENARIO_MARKERS = (
    "场景",
    "任务",
    "环境",
    "战场",
    "作战",
    "体系",
    "平台",
    "面向",
    "用于",
    "应用于",
    "条件下",
)
_CONSTRAINT_MARKERS = (
    "约束",
    "限制",
    "条件",
    "不超过",
    "不少于",
    "不低于",
    "不高于",
    "至少",
    "至多",
    "兼容",
    "接口",
    "成本",
    "功耗",
    "重量",
    "尺寸",
    "实时",
    "时延",
    "带宽",
    "温度",
)
_TECHNOLOGY_MARKERS = (
    "技术",
    "算法",
    "模型",
    "材料",
    "组件",
    "器件",
    "芯片",
    "传感器",
    "雷达",
    "通信",
    "网络",
    "控制",
    "软件",
    "架构",
    "波束",
    "频谱",
)
_CONCEPT_MARKERS = (
    "需求",
    "问题",
    "威胁",
    "复杂电磁环境",
    "极端环境",
    "体系对抗",
    "作战概念",
)
_PRINCIPLE_MARKERS = ("理论", "原理", "机制", "机理", "效应", "定律")

_ROLE_TO_FIELD = {
    "concept": "concept_targets",
    "principle": "principle_terms",
    "technology": "key_technical_elements",
    "capability": "target_capabilities",
    "application": "application_scenarios",
}


def analyze_requirement_query(
    query: str,
    path_result: dict[str, Any],
    *,
    discovery_mode: str,
) -> dict[str, Any]:
    """解析需求并把返回链路中的实体映射到需求字段。"""
    frame = parse_requirement_query(query)
    mappings = _map_path_entities(frame, path_result)
    mapped_fields = {mapping["requirement_field"] for mapping in mappings}
    expected_fields = {
        "concept_targets",
        "principle_terms",
        "target_capabilities",
        "application_scenarios",
        "key_technical_elements",
    }
    return {
        **frame,
        "mode": discovery_mode,
        "entity_mappings": mappings,
        "unmapped_fields": sorted(field for field in expected_fields if frame[field] and field not in mapped_fields),
        "needs_human_review": bool(frame["ambiguous_clauses"] or not mappings),
    }


def parse_requirement_query(query: str) -> dict[str, Any]:
    """用确定性规则提取能力、场景、约束和技术要素，不伪造缺失字段。"""
    normalized_query = " ".join(str(query or "").split()).strip()
    clauses = _clauses(normalized_query)
    target_capabilities: list[str] = []
    concept_targets: list[str] = []
    principle_terms: list[str] = []
    application_scenarios: list[str] = []
    constraints: list[str] = []
    key_technical_elements: list[str] = []
    ambiguous_clauses: list[str] = []

    for clause in clauses:
        categories = 0
        if _has_any(clause, _CONCEPT_MARKERS):
            concept_targets.append(clause)
            categories += 1
        if _has_any(clause, _PRINCIPLE_MARKERS):
            principle_terms.append(clause)
            categories += 1
        if _has_any(clause, _CAPABILITY_MARKERS) and _has_any(clause, _CAPABILITY_VERBS):
            target_capabilities.append(clause)
            categories += 1
        if _has_any(clause, _SCENARIO_MARKERS):
            application_scenarios.append(clause)
            categories += 1
        if _has_any(clause, _CONSTRAINT_MARKERS) or _QUANTITATIVE_CONSTRAINT.search(clause):
            constraints.append(clause)
            categories += 1
        if _has_any(clause, _TECHNOLOGY_MARKERS):
            key_technical_elements.append(clause)
            categories += 1
        if categories == 0:
            ambiguous_clauses.append(clause)

    return {
        "analysis_version": REQUIREMENT_ANALYSIS_VERSION,
        "original_query": normalized_query,
        "concept_targets": _deduplicate(concept_targets),
        "principle_terms": _deduplicate(principle_terms),
        "target_capabilities": _deduplicate(target_capabilities),
        "application_scenarios": _deduplicate(application_scenarios),
        "constraints": _deduplicate(constraints),
        "key_technical_elements": _deduplicate(key_technical_elements),
        "quantitative_constraints": _deduplicate(
            match.group(0).strip()
            for clause in clauses
            for match in _QUANTITATIVE_CONSTRAINT.finditer(clause)
            if match.group(0).strip()
        ),
        "ambiguous_clauses": _deduplicate(ambiguous_clauses),
    }


def _map_path_entities(frame: dict[str, Any], path_result: dict[str, Any]) -> list[dict[str, Any]]:
    mappings: dict[tuple[str, str], dict[str, Any]] = {}
    frame_terms = {field: [normalize_entity_name(value) for value in frame[field]] for field in _ROLE_TO_FIELD.values()}
    for path in path_result.get("paths") or []:
        path_score = max(0.0, min(float(path.get("score") or 0.0) / 6.0, 1.0))
        path_id = str(path.get("path_id") or "")
        for node in path.get("nodes") or []:
            role = str(node.get("semantic_role") or "other")
            field = _ROLE_TO_FIELD.get(role)
            entity_id = _entity_id(node)
            if not field or not entity_id:
                continue
            name = str(node.get("name") or "").strip()
            normalized_name = normalize_entity_name(name)
            lexical_score = (
                max(
                    (
                        1.0
                        if normalized_name == term
                        else 0.82
                        if normalized_name and (normalized_name in term or term in normalized_name)
                        else 0.0
                    )
                    for term in frame_terms[field]
                )
                if frame_terms[field]
                else 0.0
            )
            relevance = _bounded_score((node.get("properties") or {}).get("query_relevance"))
            mapping_score = round(max(lexical_score, relevance, path_score * 0.75), 4)
            key = (field, entity_id)
            current = mappings.get(key)
            if current is None:
                mappings[key] = {
                    "requirement_field": field,
                    "entity_id": entity_id,
                    "name": name,
                    "type": str(node.get("type") or ""),
                    "semantic_role": role,
                    "mapping_score": mapping_score,
                    "path_ids": [path_id] if path_id else [],
                }
            else:
                current["mapping_score"] = max(current["mapping_score"], mapping_score)
                if path_id and path_id not in current["path_ids"]:
                    current["path_ids"].append(path_id)

    return sorted(
        mappings.values(),
        key=lambda item: (item["mapping_score"], item["requirement_field"], item["entity_id"]),
        reverse=True,
    )[:50]


def _clauses(query: str) -> list[str]:
    clauses = []
    for segment in _CLAUSE_SPLITTER.split(query):
        segment = segment.strip(" ，,、：:")
        if not segment:
            continue
        comma_segments = [part.strip() for part in re.split(r"[，,]", segment) if part.strip()]
        clauses.extend(comma_segments or [segment])
    return _deduplicate(clauses)


def _entity_id(node: dict[str, Any]) -> str:
    return str((node.get("properties") or {}).get("entity_id") or node.get("entity_id") or "").strip()


def _bounded_score(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _deduplicate(values) -> list[str]:
    return list(dict.fromkeys(str(value).strip()[:240] for value in values if str(value).strip()))
