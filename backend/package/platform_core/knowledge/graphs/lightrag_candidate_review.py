"""LightRAG 对既有实体候选的受约束判型复核。"""

from __future__ import annotations

import math
import json
import re
from copy import deepcopy
from typing import Any
from unicodedata import normalize

from platform_core.knowledge.graphs.defense_ontology import (
    DEFENSE_ONTOLOGY_V1,
    canonical_entity_type,
    validate_relation_types,
)

ENTITY_REVIEW_MODES = frozenset({"off", "propose", "apply_experiment"})
DEFAULT_ENTITY_REVIEW_MIN_CONFIDENCE = 0.95
ENTITY_REVIEW_TRIGGERS = frozenset({"suspect_only", "all"})
DOCUMENT_TYPE_CONSISTENCY_MIN_RELATIONS = 2

ENTITY_REVIEW_PROMPT = """你是军事武器装备技术知识图谱的实体候选质检器。
输入候选是封闭集合。你只能引用给定 review_ref，不能新建实体、改变 text/Span 或引用其他 id。

逐项判断候选是否属于给定本体：
- 类型错误：action=relabel，并从本体闭集中选择 suggested_label；
- 根本不是本体实体（一般性动词/结果描述、机构名称、OCR 截断等）：action=reject，suggested_label=null；
- 候选正确或证据不足：不要返回。

技术、器件、材料、装备、能力、指标等稳定技术名词只要能映射到任一本体类型，就不得 reject，应在类型错误时 relabel。
只有确实无法归入任何本体类型的泛化表述、机构名称或损伤片段才能 reject。
suggested_label 与 current_label 相同时不要返回；reason 必须说明当前原文中的具体判据，不能只写“名词/动词”。
confidence 必须填写本次判断的真实概率；不得照抄占位值，低于 0.80 的决定应省略。
surface_type_hints 是平台根据术语后缀给出的高精度提示，same_surface_labels 表示当前 Block 内同一名称的其他类型。
两者只用于提醒你结合原句重点复核，不能替代原文语义；若同名多类型实际是同一概念，应把错误候选 relabel 到正确类型。
宁缺勿滥。不得依据外部常识扩展原文。
仅返回 JSON；entities 和 relations 必须是空数组，用于兼容平台统一 JSON 传输契约：
{{"entities":[],"relations":[],"decisions":[{{"review_ref":"c1","action":"relabel 或 reject",
"suggested_label":"relabel 时的本体类型，否则 null","confidence":0.96,"reason":"原文内具体依据"}}]}}

本体实体类型：
{ontology}

待复核候选：
{candidates}

当前原文：
{text}
"""

_GENERIC_NON_ENTITY = re.compile(
    r"^(?:成功|成功的应用|优秀效果|实际任务|局限性|价值|环境|取得(?:了)?成功|结果表明|本文|该系统|"
    r"上述方法|进展神速|赢得合同|坠毁失事|有限的作战|作战地|接收到)$"
)
_OCR_MARKER_FRAGMENT = re.compile(r"^@[A-Za-z]{2,8}$")
_OCR_CORRUPTED_NUMERIC_UNIT = re.compile(
    r"^[0-9０-９.,，。+\-—–~～#?？]+\s*(?:个?月|年|天|小时|分钟|秒|米|千米|公里|英尺|千瓦|兆瓦|赫兹)$"
)
_COMPONENT_SUFFIXES = ("器", "模块", "开关", "天线", "电源", "芯片", "组件")
_PRODUCT_SUFFIXES = ("武器", "系统", "装备", "平台", "导弹")
_ORGANIZATION_SUFFIXES = (
    "实验室",
    "研究所",
    "基地",
    "大学",
    "公司",
    "电视台",
    "电视网",
    "广播电台",
    "新闻社",
    "委员会",
    "司令部",
    "部队",
    "五角大楼",
    "院",
    "局",
)
_SHORT_ASCII_HEADER_FRAGMENT = re.compile(r"^[A-Z][a-z]{1,3}$")
_GLUED_ASCII_LAYOUT_FRAGMENT = re.compile(r"^[A-Za-z]{64,}$")
_ASCII_TRAILING_PUNCTUATION = re.compile(r"^(?=.*[A-Za-z])[^\n]{2,}[.;,:!?]$")
_ENGLISH_LAYOUT_STOP_FRAGMENT = re.compile(
    r"^(?:a|an|and|as|at|by|for|from|fro|in|into|of|on|or|pass|the|than|to|with)$",
    re.IGNORECASE,
)
_SINGLE_FORMULA_SYMBOL = re.compile(r"^[A-Za-z\u0370-\u03ff]$")
_PUBLICATION_HEADER = re.compile(
    r"^(?:(?:19|20)\d{2}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*第?\s*\d+\s*期)?|"
    r"第\s*\d+\s*卷(?:\s*第?\s*\d+\s*期)?(?:\s*\d+)?|第\s*\d+\s*期|"
    r"(?:vol(?:ume)?\.?|no\.?)\s*\d+(?:[,./-]\d+)*)$",
    re.IGNORECASE,
)
_ENGLISH_ORGANIZATION = re.compile(
    r"(?:\b(?:academy|agency|air\s*force\s*base|bureau|command|commission|company|"
    r"corporation|department|institute|university)\b|"
    r"\b(?:base|laborator(?:y|ies)|lab|office)\.?$)",
    re.IGNORECASE,
)
_LAYOUT_GAP_BETWEEN_TERM_CHARACTERS = re.compile(
    r"(?<=[A-Za-z\u3400-\u9fff])[\s\u00a0\u3000]+(?=[A-Za-z\u3400-\u9fff])"
)
_SINGLE_CJK_SURFACE = re.compile(r"^[\u3400-\u9fff]$")
_ALLOWED_SINGLE_CJK_MATERIALS = frozenset(
    "氢氘氚氦锂铍硼碳氮氧氟氖钠镁铝硅磷硫氯氩钾钙钪钛钒铬锰铁钴镍铜锌镓锗砷硒溴氪"
    "铷锶锆铌钼钌铑钯银镉铟锡锑碲碘氙铯钡铪钽钨铼锇铱铂金汞铊铅铋氡镭锕钍镤铀镎"
    "钚镅锔锫锎锿镄钔锘铹"
)
_NATIONAL_MILITARY_ORGANIZATION = re.compile(
    r"^(?:中国|美国|俄罗斯|英国|法国|德国|日本|印度|以色列|韩国|朝鲜|乌克兰|苏联)"
    r"(?:人民解放军)?(?:陆军|海军|空军|火箭军|太空军|海军陆战队)$"
)
_ACTION_PHRASE_PREFIXES = (
    "采用",
    "导致",
    "产生",
    "提供",
    "使用",
    "使",
    "增强",
    "实现",
    "干扰",
    "形成",
    "支持",
    "支撑",
    "提升",
    "提高",
    "搅乱",
    "摧毁",
    "降低",
    "减少",
    "利用",
    "用于",
    "破坏",
    "终止",
    "完成",
    "毁坏",
)

# 这些后缀只提供判型复核提示，不直接改写实体。刻意不使用“器”“系统”“平台”等高歧义后缀，
# 避免把“武器”误判为 Component，或把“控制系统”一律判为完整 ProductSystem。
_SURFACE_TYPE_SUFFIX_HINTS = (
    (("武器", "装备", "导弹", "战斗机", "无人机", "舰艇"), "ProductSystem", "完整装备或武器产品称谓"),
    (
        (
            "模块",
            "芯片",
            "天线",
            "传感器",
            "探测器",
            "放大器",
            "振荡器",
            "速调管",
            "磁控管",
            "电子管",
            "器件",
            "激光器",
            "产生器",
            "发生器",
            "计算机",
            "电脑",
            "电源",
            "尾翼",
            "弹头",
        ),
        "Component",
        "器件或组件称谓",
    ),
    (("算法", "模型"), "AlgorithmModel", "算法或模型称谓"),
    (("材料", "合金", "陶瓷", "涂层", "复合材料"), "Material", "材料称谓"),
    (("原理", "机理", "效应", "定律"), "ScientificPrinciple", "作用机理或科学原理称谓"),
    (("能力",), "Capability", "能力称谓"),
    (
        (
            "指标",
            "参数",
            "质量",
            "功率",
            "能量",
            "频率",
            "频移",
            "速率",
            "变化率",
            "精度",
            "分辨率",
            "距离",
            "时延",
            "时差",
            "相位差",
            "信噪比",
            "灵敏度",
        ),
        "Metric",
        "可测量指标称谓",
    ),
    (("约束", "限制条件"), "Constraint", "约束条件称谓"),
    (("技术", "工艺", "方案", "设计"), "KeyTechnology", "技术、方案或工艺称谓"),
)

_EXACT_SURFACE_TYPE_HINTS = {
    "CDMA": ("AlgorithmModel", "通信多址或信号处理方法缩写"),
    "CFAR": ("AlgorithmModel", "检测或信号处理算法缩写"),
    "ESPRIT": ("AlgorithmModel", "参数估计算法缩写"),
    "FDMA": ("AlgorithmModel", "通信多址或信号处理方法缩写"),
    "FDOA": ("AlgorithmModel", "定位或参数估计方法缩写"),
    "MUSIC": ("AlgorithmModel", "参数估计算法缩写"),
    "OFDM": ("AlgorithmModel", "调制或信号处理方法缩写"),
    "TDMA": ("AlgorithmModel", "通信多址或信号处理方法缩写"),
    "TDOA": ("AlgorithmModel", "定位或参数估计方法缩写"),
}

_ENGLISH_SURFACE_TYPE_SUFFIX_HINTS = (
    (("technique", "technology"), "KeyTechnology", "英文技术称谓"),
    (("algorithm", "model"), "AlgorithmModel", "英文算法或模型称谓"),
    (
        (
            "antenna",
            "chip",
            "component",
            "detector",
            "module",
            "power supply",
            "receiver",
            "sensor",
            "transmitter",
        ),
        "Component",
        "英文器件或组件称谓",
    ),
    (("alloy", "ceramic", "coating", "composite", "material"), "Material", "英文材料称谓"),
    (("effect", "law", "mechanism", "principle"), "ScientificPrinciple", "英文原理或机理称谓"),
    (("capability",), "Capability", "英文能力称谓"),
    (
        ("accuracy", "bandwidth", "distance", "frequency", "power", "rate", "range", "resolution"),
        "Metric",
        "英文可测量指标称谓",
    ),
    (("constraint", "limitation"), "Constraint", "英文约束称谓"),
)


def clear_non_ontology_entity_reason(text: Any) -> str | None:
    """识别无需模型判断即可确定不属于当前军事技术本体的表面模式。"""
    normalized = normalize("NFKC", str(text or "").strip())
    layout_surface = _layout_quality_surface(normalized)
    if normalized and not any(character.isalnum() for character in normalized):
        return "punctuation_or_ocr_fragment"
    if _GENERIC_NON_ENTITY.fullmatch(layout_surface):
        return "generic_non_entity"
    if _OCR_MARKER_FRAGMENT.fullmatch(layout_surface):
        return "ocr_marker_fragment"
    if _OCR_CORRUPTED_NUMERIC_UNIT.fullmatch(layout_surface) and any(
        marker in layout_surface for marker in ("#", "?", "？")
    ):
        return "ocr_corrupted_numeric_fragment"
    if _PUBLICATION_HEADER.fullmatch(normalized):
        return "publication_header"
    if (
        layout_surface.endswith(_ORGANIZATION_SUFFIXES)
        or _NATIONAL_MILITARY_ORGANIZATION.fullmatch(layout_surface)
        or _ENGLISH_ORGANIZATION.search(normalized)
    ):
        return "organization_name"
    if _SINGLE_CJK_SURFACE.fullmatch(layout_surface) and layout_surface not in _ALLOWED_SINGLE_CJK_MATERIALS:
        return "single_cjk_fragment"
    if _SHORT_ASCII_HEADER_FRAGMENT.fullmatch(normalized):
        return "short_ascii_header_fragment"
    if _ENGLISH_LAYOUT_STOP_FRAGMENT.fullmatch(normalized):
        return "english_layout_stop_fragment"
    if _ASCII_TRAILING_PUNCTUATION.fullmatch(normalized):
        return "ascii_trailing_punctuation"
    if _SINGLE_FORMULA_SYMBOL.fullmatch(normalized):
        return "single_formula_symbol"
    if _GLUED_ASCII_LAYOUT_FRAGMENT.fullmatch(normalized):
        return "glued_ascii_layout_fragment"
    return None


def entity_type_surface_hints(text: Any) -> list[dict[str, str]]:
    """返回保守的术语表面判型提示，仅供 LLM 结合原句复核。"""

    normalized = _layout_quality_surface(text)
    if normalized.startswith(_ACTION_PHRASE_PREFIXES):
        return []
    hints = []
    exact_hint = _EXACT_SURFACE_TYPE_HINTS.get(normalized.upper())
    if exact_hint is not None:
        label, reason = exact_hint
        hints.append({"suggested_label": label, "reason": reason})
    for suffixes, label, reason in _SURFACE_TYPE_SUFFIX_HINTS:
        if normalized.endswith(suffixes):
            hints.append({"suggested_label": label, "reason": reason})
    lowered = " ".join(normalize("NFKC", str(text or "").strip()).split()).casefold()
    for suffixes, label, reason in _ENGLISH_SURFACE_TYPE_SUFFIX_HINTS:
        if any(re.search(rf"(?:^|[\s/_-]){re.escape(suffix)}$", lowered) for suffix in suffixes):
            hints.append({"suggested_label": label, "reason": reason})
    return hints


def filter_clear_non_ontology_candidates(result: dict[str, Any]) -> dict[str, Any]:
    """过滤各模型来源的确定性非本体候选，并同步移除悬空关系。"""

    filtered = deepcopy(result)
    entities = [deepcopy(entity) for entity in filtered.get("entities") or [] if isinstance(entity, dict)]
    relations = [deepcopy(relation) for relation in filtered.get("relations") or []]
    original_index = _entity_index(entities)
    protected_objects: set[int] = set()
    for relation in relations:
        if not isinstance(relation, dict) or not _human_reviewed(relation):
            continue
        for endpoint in (relation.get("source"), relation.get("target")):
            resolved = _resolve_relation_endpoint(endpoint, original_index, {})
            if resolved is not None:
                protected_objects.add(id(resolved))

    kept_entities = []
    rejected = []
    rejection_counts: dict[str, int] = {}
    for entity in entities:
        reason = clear_non_ontology_entity_reason(entity.get("text"))
        if reason is None:
            reason = _nested_ascii_word_fragment_reason(entity, entities)
        if reason is None or _human_reviewed(entity) or id(entity) in protected_objects:
            kept_entities.append(entity)
            continue
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        rejected.append(
            {
                "id": str(entity.get("id") or ""),
                "text": str(entity.get("text") or "")[:256],
                "label": canonical_entity_type(str(entity.get("label") or "")),
                "start": entity.get("start"),
                "end": entity.get("end"),
                "reason": reason,
                "model_sources": list(entity.get("model_sources") or [])[:8],
            }
        )

    kept_index = _entity_index(kept_entities)
    kept_relations = []
    dropped_relations = 0
    for raw_relation in relations:
        if not isinstance(raw_relation, dict):
            dropped_relations += 1
            continue
        source = _resolve_relation_endpoint(raw_relation.get("source"), kept_index, {})
        target = _resolve_relation_endpoint(raw_relation.get("target"), kept_index, {})
        if source is None or target is None:
            dropped_relations += 1
            continue
        relation = deepcopy(raw_relation)
        relation.update({"source": source, "target": target})
        kept_relations.append(relation)

    metadata = dict(filtered.get("metadata") or {})
    previous = metadata.get("deterministic_entity_quality_filter")
    previous = previous if isinstance(previous, dict) else {}
    previous_counts = previous.get("total_rejection_counts")
    total_counts = dict(previous_counts) if isinstance(previous_counts, dict) else {}
    for reason, count in rejection_counts.items():
        total_counts[reason] = int(total_counts.get(reason) or 0) + count
    current_pass = {
        "revision": "layout-aware-clear-non-ontology-v1",
        "dropped_entity_count": len(rejected),
        "dropped_relation_count": dropped_relations,
        "protected_human_entity_count": len(protected_objects),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "sampled_rejections": rejected[:64],
        "truncated": len(rejected) > 64,
    }
    previous_passes = previous.get("passes")
    passes = [deepcopy(item) for item in previous_passes or [] if isinstance(item, dict)]
    passes.append(deepcopy(current_pass))
    current_pass.update(
        {
            "pass_count": int(previous.get("pass_count") or len(passes) - 1) + 1,
            "total_dropped_entity_count": int(previous.get("total_dropped_entity_count") or 0) + len(rejected),
            "total_dropped_relation_count": int(previous.get("total_dropped_relation_count") or 0) + dropped_relations,
            "total_rejection_counts": dict(sorted(total_counts.items())),
            "passes": passes[-8:],
        }
    )
    metadata["deterministic_entity_quality_filter"] = current_pass
    metadata["dropped_entities"] = int(metadata.get("dropped_entities") or 0) + len(rejected)
    metadata["dropped_relations"] = int(metadata.get("dropped_relations") or 0) + dropped_relations
    filtered.update({"entities": kept_entities, "relations": kept_relations, "metadata": metadata})
    return filtered


def resolve_deterministic_entity_type_conflicts(
    result: dict[str, Any],
    *,
    relabel_single_candidates: bool = False,
) -> dict[str, Any]:
    """以唯一高精度表面提示修正单候选并消解同 Span 多类型候选。"""

    resolved = deepcopy(result)
    entities = [deepcopy(entity) for entity in resolved.get("entities") or [] if isinstance(entity, dict)]
    grouped: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for entity in entities:
        start = entity.get("start")
        end = entity.get("end")
        text = str(entity.get("text") or "")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
        ):
            grouped.setdefault((text, start, end), []).append(entity)

    dropped_objects: set[int] = set()
    replacement_by_id: dict[str, dict[str, Any]] = {}
    replacement_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]] = {}
    resolved_groups = []
    unresolved_group_count = 0
    relabeled_entity_count = 0
    for (text, start, end), candidates in grouped.items():
        labels = {canonical_entity_type(str(candidate.get("label") or "")) for candidate in candidates}
        if any(_human_reviewed(candidate) for candidate in candidates):
            unresolved_group_count += int(len(labels) > 1)
            continue
        hinted_labels = {hint["suggested_label"] for hint in entity_type_surface_hints(text)}
        if len(hinted_labels) != 1:
            unresolved_group_count += int(len(labels) > 1)
            continue
        selected_label = next(iter(hinted_labels))
        if labels == {selected_label}:
            continue
        if len(labels) <= 1 and not relabel_single_candidates:
            continue
        matching = [
            candidate
            for candidate in candidates
            if canonical_entity_type(str(candidate.get("label") or "")) == selected_label
        ]
        if not matching:
            if not relabel_single_candidates:
                unresolved_group_count += int(len(labels) > 1)
                continue
            selected = max(candidates, key=lambda candidate: _probability(candidate.get("confidence")))
            original_identity = _entity_identity(selected)
            original_label = canonical_entity_type(str(selected.get("label") or ""))
            selected["label"] = selected_label
            selected["original_label"] = original_label
            selected["review_status"] = selected.get("review_status") or "pending"
            selected["expert_review_required"] = True
            selected["model_sources"] = list(
                dict.fromkeys([*(selected.get("model_sources") or []), "deterministic_surface_type_resolution"])
            )
            replacement_by_identity[original_identity] = selected
            identifier = str(selected.get("id") or "")
            if identifier:
                replacement_by_id[identifier] = selected
            relabeled_entity_count += 1
        else:
            selected = max(matching, key=lambda candidate: _probability(candidate.get("confidence")))
        selected["type_resolution"] = {
            "rule": "exact_span_unique_surface_hint_v2",
            "selected_label": selected_label,
            "discarded_labels": sorted(labels - {selected_label}),
            "expert_review_required": bool(not matching),
        }
        for candidate in candidates:
            if candidate is selected:
                continue
            dropped_objects.add(id(candidate))
            replacement_by_identity[_entity_identity(candidate)] = selected
            identifier = str(candidate.get("id") or "")
            if identifier:
                replacement_by_id[identifier] = selected
        resolved_groups.append(
            {
                "text": text,
                "start": start,
                "end": end,
                "selected_label": selected_label,
                "discarded_labels": sorted(labels - {selected_label}),
                "relabeled": not bool(matching),
            }
        )

    kept_entities = [entity for entity in entities if id(entity) not in dropped_objects]
    relations, rebound_relations, dropped_relations = _rewrite_relations_after_type_resolution(
        resolved.get("relations") or [],
        kept_entities,
        replacement_by_id=replacement_by_id,
        replacement_by_identity=replacement_by_identity,
    )
    (
        kept_entities,
        relations,
        document_consistency_report,
    ) = _resolve_document_relation_consistent_types(kept_entities, relations)
    metadata = dict(resolved.get("metadata") or {})
    previous_report = metadata.get("deterministic_entity_type_resolution")
    previous_report = previous_report if isinstance(previous_report, dict) else {}
    current_pass = {
        "revision": "exact-span-surface-hint-v2",
        "resolved_group_count": len(resolved_groups),
        "unresolved_group_count": unresolved_group_count,
        "relabeled_entity_count": relabeled_entity_count,
        "dropped_entity_count": len(dropped_objects),
        "rebound_relation_count": rebound_relations,
        "dropped_relation_count": dropped_relations,
        "groups": resolved_groups[:64],
        "truncated": len(resolved_groups) > 64,
    }
    previous_passes = previous_report.get("passes")
    if isinstance(previous_passes, list):
        passes = [deepcopy(item) for item in previous_passes if isinstance(item, dict)]
    elif previous_report:
        passes = [
            {
                key: deepcopy(value)
                for key, value in previous_report.items()
                if key not in {"passes", "pass_count", "total_resolved_group_count"}
            }
        ]
    else:
        passes = []
    passes.append(deepcopy(current_pass))
    current_pass.update(
        {
            "pass_count": int(previous_report.get("pass_count") or len(passes) - 1) + 1,
            "total_resolved_group_count": int(
                previous_report.get("total_resolved_group_count") or previous_report.get("resolved_group_count") or 0
            )
            + len(resolved_groups),
            "passes": passes[-8:],
        }
    )
    metadata["deterministic_entity_type_resolution"] = current_pass
    metadata["document_entity_type_consistency"] = _accumulate_consistency_report(
        metadata.get("document_entity_type_consistency"),
        document_consistency_report,
    )
    metadata["entity_type_conflicts"] = _same_surface_type_conflicts(kept_entities)
    resolved.update({"entities": kept_entities, "relations": relations, "metadata": metadata})
    return resolved


def build_entity_review_prompt(
    source_text: str,
    entities: list[dict[str, Any]],
    *,
    ontology_definition: dict[str, Any],
    trigger: str = "suspect_only",
    max_candidates: int = 48,
) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """构建闭集 review_ref Prompt；没有待复核项时不触发模型调用。"""

    if trigger not in ENTITY_REVIEW_TRIGGERS:
        allowed = ", ".join(sorted(ENTITY_REVIEW_TRIGGERS))
        raise ValueError(f"entity_review_trigger 必须是: {allowed}")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 512:
        raise ValueError("entity_review_max_candidates 必须是 1 到 512 之间的整数")
    rows = []
    labels_by_surface: dict[str, set[str]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        surface = _normalized_surface(entity.get("text"))
        label = canonical_entity_type(str(entity.get("label") or ""))
        if surface and label:
            labels_by_surface.setdefault(surface, set()).add(label)
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict) or _human_reviewed(entity):
            continue
        score = _suspicion_score(entity)
        if trigger == "suspect_only" and score <= 0:
            continue
        rows.append((index, score, entity))
    rows.sort(
        key=lambda row: (
            -row[1],
            float(row[2].get("confidence") or 0.0),
            int(row[2].get("start") or 0),
            str(row[2].get("text") or ""),
            row[0],
        )
    )
    bindings: dict[str, dict[str, Any]] = {}
    payload = []
    for sequence, (_, suspicion_score, entity) in enumerate(rows[:max_candidates], start=1):
        review_ref = f"c{sequence}"
        bindings[review_ref] = entity
        surface = _normalized_surface(entity.get("text"))
        same_surface_labels = sorted(labels_by_surface.get(surface, set()))
        payload.append(
            {
                "review_ref": review_ref,
                "text": str(entity.get("text") or "")[:256],
                "current_label": canonical_entity_type(str(entity.get("label") or "")),
                "start": entity.get("start"),
                "end": entity.get("end"),
                "model_confidence": _probability(entity.get("confidence")),
                "suspicion_score": suspicion_score,
                "surface_type_hints": entity_type_surface_hints(entity.get("text")),
                "same_surface_labels": same_surface_labels if len(same_surface_labels) > 1 else [],
            }
        )
    if not bindings:
        return None, {}
    ontology = [
        {
            "code": str(item.get("code") or ""),
            "description": str(item.get("description") or "")[:300],
        }
        for item in ontology_definition.get("entity_types") or []
        if isinstance(item, dict) and item.get("code")
    ]
    return (
        ENTITY_REVIEW_PROMPT.format(
            ontology=json.dumps(ontology, ensure_ascii=False, separators=(",", ":")),
            candidates=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            text=source_text,
        ),
        bindings,
    )


def validate_entity_review_decisions(
    raw: Any,
    *,
    source_text: str,
    bindings: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """把模型闭集 decision 映射回平台候选，不采用模型自报 text 或 Span。"""

    decisions = raw.get("decisions") if isinstance(raw, dict) else None
    raw_count = len(decisions) if isinstance(decisions, list) else 0
    projected = []
    unknown_ref_count = 0
    for decision in decisions or []:
        if not isinstance(decision, dict):
            unknown_ref_count += 1
            continue
        review_ref = str(decision.get("review_ref") or "")
        entity = bindings.get(review_ref)
        if entity is None:
            unknown_ref_count += 1
            continue
        projected.append(
            {
                "entity_id": str(entity.get("id") or ""),
                "text": str(entity.get("text") or ""),
                "start": entity.get("start"),
                "end": entity.get("end"),
                "current_label": canonical_entity_type(str(entity.get("label") or "")),
                "action": decision.get("action"),
                "suggested_label": decision.get("suggested_label"),
                "confidence": decision.get("confidence"),
                "reason": decision.get("reason"),
            }
        )
    valid = validate_entity_review_proposals(
        projected,
        source_text=source_text,
        known_entities=list(bindings.values()),
    )
    return valid, {
        "raw_decision_count": raw_count,
        "unknown_review_ref_count": unknown_ref_count,
        "valid_decision_count": len(valid),
    }


def _suspicion_score(entity: dict[str, Any]) -> int:
    text = str(entity.get("text") or "").strip()
    label = canonical_entity_type(str(entity.get("label") or ""))
    score = 0
    clear_rejection = clear_non_ontology_entity_reason(text)
    if clear_rejection:
        score += 5
    if label == "Material" and text.endswith(_COMPONENT_SUFFIXES):
        score += 4
    if label == "Capability" and text.endswith(_COMPONENT_SUFFIXES + _PRODUCT_SUFFIXES):
        score += 3
    if label == "ScientificPrinciple" and text.endswith(_PRODUCT_SUFFIXES):
        score += 4
    if label == "ProductSystem" and text.endswith(_ORGANIZATION_SUFFIXES):
        score += 5
    hinted_labels = {hint["suggested_label"] for hint in entity_type_surface_hints(text)}
    if hinted_labels and label not in hinted_labels:
        score += 4
    if _explicit_low_confidence(entity.get("confidence"), threshold=0.7):
        score += 1
    return score


def _reject_allowed(entity: dict[str, Any]) -> bool:
    """自动拒绝只覆盖高精度表面模式，技术名词必须走 relabel 或人工复核。"""

    return clear_non_ontology_entity_reason(entity.get("text")) is not None


def _explicit_low_confidence(value: Any, *, threshold: float) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and 0.0 <= number < threshold


def validate_entity_review_proposals(
    raw_value: Any,
    *,
    source_text: str,
    known_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """只保留能够唯一绑定到既有原文 Span 的闭集类型纠错建议。"""

    if not isinstance(raw_value, list):
        return []
    indexed = _entity_index(known_entities)
    proposals: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for raw in raw_value:
        if not isinstance(raw, dict):
            continue
        entity = _resolve_proposal_entity(raw, indexed)
        if entity is None:
            continue
        start = entity.get("start")
        end = entity.get("end")
        text = str(entity.get("text") or "")
        current_label = canonical_entity_type(str(entity.get("label") or ""))
        action = str(raw.get("action") or ("relabel" if raw.get("suggested_label") else "")).strip().lower()
        suggested_label = canonical_entity_type(str(raw.get("suggested_label") or ""))
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not 0 <= start < end <= len(source_text)
            or source_text[start:end] != text
            or current_label not in DEFENSE_ONTOLOGY_V1.entity_type_by_code
            or action not in {"relabel", "reject"}
            or (action == "reject" and not _reject_allowed(entity))
            or (
                action == "relabel"
                and (suggested_label not in DEFENSE_ONTOLOGY_V1.entity_type_by_code or suggested_label == current_label)
            )
        ):
            continue
        confidence = _probability(raw.get("confidence"))
        key = (str(entity.get("id") or ""), start, end, current_label)
        proposal = {
            "entity_id": str(entity.get("id") or ""),
            "text": text,
            "start": start,
            "end": end,
            "current_label": current_label,
            "action": action,
            "suggested_label": suggested_label if action == "relabel" else None,
            "confidence": confidence,
            "reason": str(raw.get("reason") or "")[:1000],
            "status": "proposed",
            "applied": False,
        }
        existing = proposals.get(key)
        if existing is None or _proposal_priority(proposal) < _proposal_priority(existing):
            proposals[key] = proposal
    return sorted(proposals.values(), key=_proposal_sort_key)


def review_entities(
    result: dict[str, Any],
    proposals: list[dict[str, Any]],
    *,
    mode: str,
    min_confidence: float = DEFAULT_ENTITY_REVIEW_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """记录判型建议，并仅在实验模式下修改未审核候选及重验关系。"""

    if mode not in ENTITY_REVIEW_MODES:
        allowed = ", ".join(sorted(ENTITY_REVIEW_MODES))
        raise ValueError(f"entity_review_mode 必须是: {allowed}")
    threshold = _validated_probability(min_confidence)
    reviewed = deepcopy(result)
    metadata = dict(reviewed.get("metadata") or {})
    if mode == "off":
        metadata["entity_review"] = _review_report(mode, threshold, [], 0, 0, 0)
        reviewed["metadata"] = metadata
        return reviewed

    entities = [deepcopy(entity) for entity in reviewed.get("entities") or []]
    indexed = _entity_index(entities)
    applied_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]] = {}
    rejected_identities: set[tuple[str, int | None, int | None, str]] = set()
    audited = []
    blocked_count = 0
    low_confidence_count = 0
    for proposal in proposals:
        item = deepcopy(proposal)
        entity = _resolve_proposal_entity(item, indexed)
        if entity is None:
            item.update({"status": "stale", "applied": False})
            blocked_count += 1
            audited.append(item)
            continue
        if _human_reviewed(entity):
            item.update({"status": "blocked_human_review", "applied": False})
            blocked_count += 1
            audited.append(item)
            continue
        if mode != "apply_experiment":
            audited.append(item)
            continue
        if float(item.get("confidence") or 0.0) < threshold:
            item.update({"status": "below_threshold", "applied": False})
            low_confidence_count += 1
            audited.append(item)
            continue

        old_identity = _entity_identity(entity)
        if item.get("action") == "reject":
            rejected_identities.add(old_identity)
            item.update({"status": "applied_experiment", "applied": True})
            audited.append(item)
            continue
        original_label = canonical_entity_type(str(entity.get("label") or ""))
        entity["label"] = str(item["suggested_label"])
        entity["original_label"] = original_label
        entity["expert_review_required"] = True
        entity["review_status"] = "pending"
        entity["model_sources"] = list(
            dict.fromkeys([*(entity.get("model_sources") or []), "lightrag_llm_entity_review"])
        )
        entity["entity_review"] = {
            "original_label": original_label,
            "suggested_label": str(item["suggested_label"]),
            "confidence": float(item["confidence"]),
            "reason": str(item.get("reason") or ""),
            "mode": mode,
        }
        applied_by_identity[old_identity] = entity
        item.update({"status": "applied_experiment", "applied": True})
        audited.append(item)

    entities = [entity for entity in entities if _entity_identity(entity) not in rejected_identities]
    relations, dropped_relations = _rewrite_and_validate_relations(
        reviewed.get("relations") or [],
        entities,
        applied_by_identity,
        force_validate=bool(rejected_identities),
    )
    metadata["entity_review"] = _review_report(
        mode,
        threshold,
        audited,
        len(applied_by_identity) + len(rejected_identities),
        blocked_count,
        low_confidence_count,
        dropped_relations=dropped_relations,
        relabel_applied_count=len(applied_by_identity),
        reject_applied_count=len(rejected_identities),
    )
    metadata["entity_type_conflicts"] = _same_surface_type_conflicts(entities)
    reviewed.update({"entities": entities, "relations": relations, "metadata": metadata})
    return reviewed


def _review_report(
    mode: str,
    threshold: float,
    proposals: list[dict[str, Any]],
    applied_count: int,
    blocked_count: int,
    low_confidence_count: int,
    *,
    dropped_relations: int = 0,
    relabel_applied_count: int = 0,
    reject_applied_count: int = 0,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "min_confidence": threshold,
        "proposal_count": len(proposals),
        "applied_count": applied_count,
        "relabel_applied_count": relabel_applied_count,
        "reject_applied_count": reject_applied_count,
        "blocked_count": blocked_count,
        "below_threshold_count": low_confidence_count,
        "relations_dropped_after_review": dropped_relations,
        "proposals": proposals,
    }


def _entity_index(entities: list[dict[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_span: dict[tuple[str, int | None, int | None, str], list[dict[str, Any]]] = {}
    by_text_label: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entity in entities:
        identifier = str(entity.get("id") or "")
        if identifier:
            by_id.setdefault(identifier, []).append(entity)
        by_span.setdefault(_entity_identity(entity), []).append(entity)
        by_text_label.setdefault(
            (
                str(entity.get("text") or ""),
                canonical_entity_type(str(entity.get("label") or "")),
            ),
            [],
        ).append(entity)
    return {"by_id": by_id, "by_span": by_span, "by_text_label": by_text_label}


def _resolve_proposal_entity(raw: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    identifier = str(raw.get("entity_id") or raw.get("id") or "")
    if identifier:
        matches = index["by_id"].get(identifier) or []
        if len(matches) == 1 and _proposal_matches_entity(raw, matches[0]):
            return matches[0]
    identity = (
        str(raw.get("text") or ""),
        raw.get("start") if isinstance(raw.get("start"), int) and not isinstance(raw.get("start"), bool) else None,
        raw.get("end") if isinstance(raw.get("end"), int) and not isinstance(raw.get("end"), bool) else None,
        canonical_entity_type(str(raw.get("current_label") or "")),
    )
    matches = index["by_span"].get(identity) or []
    if len(matches) == 1:
        return matches[0]
    # 既有候选可能没有稳定 id，且模型可能算错中文字符位置。
    # 只在文本+当前类型于本 Block 唯一时回绑定平台已有 Span；同名多处继续拒绝。
    matches = index["by_text_label"].get((identity[0], identity[3])) or []
    return matches[0] if len(matches) == 1 else None


def _proposal_matches_entity(raw: dict[str, Any], entity: dict[str, Any]) -> bool:
    expected = {
        "text": str(entity.get("text") or ""),
        "start": entity.get("start"),
        "end": entity.get("end"),
        "current_label": canonical_entity_type(str(entity.get("label") or "")),
    }
    return all(raw.get(key) == value for key, value in expected.items())


def _rewrite_and_validate_relations(
    relations: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    applied_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]],
    *,
    force_validate: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    if not applied_by_identity and not force_validate:
        return [deepcopy(relation) for relation in relations], 0
    index = _entity_index(entities)
    kept = []
    dropped = 0
    for raw_relation in relations:
        relation = deepcopy(raw_relation)
        source = _resolve_relation_endpoint(relation.get("source"), index, applied_by_identity)
        target = _resolve_relation_endpoint(relation.get("target"), index, applied_by_identity)
        if (
            source is None
            or target is None
            or not validate_relation_types(
                str(source.get("label") or ""),
                str(relation.get("label") or ""),
                str(target.get("label") or ""),
            )
        ):
            dropped += 1
            continue
        relation.update({"source": source, "target": target})
        kept.append(relation)
    return kept, dropped


def _resolve_document_relation_consistent_types(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """仅以同文档关系方向的唯一优势收敛跨 Span 同名类型冲突。"""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        surface = _normalized_surface(entity.get("text"))
        if surface:
            grouped.setdefault(surface, []).append(entity)

    dropped_objects: set[int] = set()
    replacement_by_id: dict[str, dict[str, Any]] = {}
    replacement_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]] = {}
    resolved_groups = []
    skipped_groups = []
    relabeled_count = 0
    for surface, candidates in grouped.items():
        labels = sorted(
            {
                canonical_entity_type(str(candidate.get("label") or ""))
                for candidate in candidates
                if candidate.get("label")
            }
        )
        if len(labels) <= 1:
            continue
        if any(_human_reviewed(candidate) for candidate in candidates):
            skipped_groups.append(
                {
                    "normalized_surface": surface,
                    "labels": labels,
                    "reason": "human_reviewed_candidate_present",
                }
            )
            continue

        scores = _relation_type_consistency_scores(
            normalized_surface=surface,
            candidate_labels=labels,
            entities=entities,
            relations=relations,
        )
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        selected_label, selected_score = ranked[0]
        runner_up_score = ranked[1][1]
        if selected_score < DOCUMENT_TYPE_CONSISTENCY_MIN_RELATIONS or selected_score <= runner_up_score:
            skipped_groups.append(
                {
                    "normalized_surface": surface,
                    "labels": labels,
                    "relation_compatibility_scores": scores,
                    "reason": "insufficient_unique_relation_evidence",
                }
            )
            continue

        by_span: dict[tuple[str, int | None, int | None], list[dict[str, Any]]] = {}
        for candidate in candidates:
            by_span.setdefault(
                (
                    str(candidate.get("text") or ""),
                    candidate.get("start") if isinstance(candidate.get("start"), int) else None,
                    candidate.get("end") if isinstance(candidate.get("end"), int) else None,
                ),
                [],
            ).append(candidate)
        for span_candidates in by_span.values():
            selected = max(
                span_candidates,
                key=lambda candidate: (
                    canonical_entity_type(str(candidate.get("label") or "")) == selected_label,
                    _probability(candidate.get("confidence")),
                    str(candidate.get("id") or ""),
                ),
            )
            old_identities = {id(candidate): _entity_identity(candidate) for candidate in span_candidates}
            original_label = canonical_entity_type(str(selected.get("label") or ""))
            if original_label != selected_label:
                selected["label"] = selected_label
                selected["original_label"] = original_label
                selected["review_status"] = selected.get("review_status") or "pending"
                selected["expert_review_required"] = True
                selected["model_sources"] = list(
                    dict.fromkeys(
                        [
                            *(selected.get("model_sources") or []),
                            "document_relation_type_consistency",
                        ]
                    )
                )
                relabeled_count += 1
            selected["type_resolution"] = {
                "rule": "document_relation_consistency_v1",
                "selected_label": selected_label,
                "relation_compatibility_scores": scores,
                "supporting_relation_count": selected_score,
                "score_margin": selected_score - runner_up_score,
                "expert_review_required": True,
            }
            for candidate in span_candidates:
                identifier = str(candidate.get("id") or "")
                if identifier:
                    replacement_by_id[identifier] = selected
                replacement_by_identity[old_identities[id(candidate)]] = selected
                if candidate is not selected:
                    dropped_objects.add(id(candidate))

        resolved_groups.append(
            {
                "normalized_surface": surface,
                "text": str(candidates[0].get("text") or "")[:256],
                "selected_label": selected_label,
                "discarded_labels": sorted(set(labels) - {selected_label}),
                "relation_compatibility_scores": scores,
                "supporting_relation_count": selected_score,
                "score_margin": selected_score - runner_up_score,
            }
        )

    kept_entities = [entity for entity in entities if id(entity) not in dropped_objects]
    if replacement_by_id or replacement_by_identity:
        rewritten, rebound_count, dropped_relation_count = _rewrite_relations_after_type_resolution(
            relations,
            kept_entities,
            replacement_by_id=replacement_by_id,
            replacement_by_identity=replacement_by_identity,
        )
    else:
        rewritten = [deepcopy(relation) for relation in relations]
        rebound_count = 0
        dropped_relation_count = 0
    return (
        kept_entities,
        rewritten,
        {
            "revision": "document-relation-consistency-v1",
            "minimum_supporting_relations": DOCUMENT_TYPE_CONSISTENCY_MIN_RELATIONS,
            "resolved_group_count": len(resolved_groups),
            "relabeled_entity_count": relabeled_count,
            "dropped_duplicate_entity_count": len(dropped_objects),
            "rebound_relation_count": rebound_count,
            "dropped_relation_count": dropped_relation_count,
            "skipped_group_count": len(skipped_groups),
            "resolved_groups": resolved_groups[:64],
            "skipped_groups": skipped_groups[:64],
            "truncated": len(resolved_groups) > 64 or len(skipped_groups) > 64,
        },
    )


def _relation_type_consistency_scores(
    *,
    normalized_surface: str,
    candidate_labels: list[str],
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, int]:
    """统计每个候选类型能保留的不同关系证据数。"""

    index = _entity_index(entities)
    compatible_relations: dict[str, set[tuple[Any, ...]]] = {label: set() for label in candidate_labels}
    for relation_index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        source = _resolve_relation_endpoint(relation.get("source"), index, {})
        target = _resolve_relation_endpoint(relation.get("target"), index, {})
        if source is None or target is None:
            continue
        source_matches = _normalized_surface(source.get("text")) == normalized_surface
        target_matches = _normalized_surface(target.get("text")) == normalized_surface
        if not source_matches and not target_matches:
            continue
        relation_label = str(relation.get("label") or "")
        evidence_key = (
            str(relation.get("id") or ""),
            relation_index,
            relation_label,
            _entity_identity(source),
            _entity_identity(target),
        )
        for candidate_label in candidate_labels:
            source_label = candidate_label if source_matches else str(source.get("label") or "")
            target_label = candidate_label if target_matches else str(target.get("label") or "")
            if validate_relation_types(source_label, relation_label, target_label):
                compatible_relations[candidate_label].add(evidence_key)
    return {label: len(values) for label, values in sorted(compatible_relations.items())}


def _accumulate_consistency_report(previous: Any, current: dict[str, Any]) -> dict[str, Any]:
    """保留有限多次判型审计，避免后续补抽覆盖早期决策。"""

    previous = previous if isinstance(previous, dict) else {}
    passes = [deepcopy(item) for item in previous.get("passes") or [] if isinstance(item, dict)]
    passes.append(deepcopy(current))
    return {
        **current,
        "pass_count": int(previous.get("pass_count") or len(passes) - 1) + 1,
        "total_resolved_group_count": int(previous.get("total_resolved_group_count") or 0)
        + int(current.get("resolved_group_count") or 0),
        "total_relabeled_entity_count": int(previous.get("total_relabeled_entity_count") or 0)
        + int(current.get("relabeled_entity_count") or 0),
        "passes": passes[-8:],
    }


def _rewrite_relations_after_type_resolution(
    relations: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    *,
    replacement_by_id: dict[str, dict[str, Any]],
    replacement_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """把关系端点重绑定到确定性消歧结果，并重新执行本体方向校验。"""

    index = _entity_index(entities)
    kept = []
    rebound = 0
    dropped = 0
    for raw_relation in relations:
        if not isinstance(raw_relation, dict):
            dropped += 1
            continue
        relation = deepcopy(raw_relation)
        source, source_rebound = _resolved_type_endpoint(
            relation.get("source"),
            index,
            replacement_by_id,
            replacement_by_identity,
        )
        target, target_rebound = _resolved_type_endpoint(
            relation.get("target"),
            index,
            replacement_by_id,
            replacement_by_identity,
        )
        if (
            source is None
            or target is None
            or not validate_relation_types(
                str(source.get("label") or ""),
                str(relation.get("label") or ""),
                str(target.get("label") or ""),
            )
        ):
            dropped += 1
            continue
        relation.update({"source": source, "target": target})
        kept.append(relation)
        rebound += int(source_rebound or target_rebound)
    return kept, rebound, dropped


def _resolved_type_endpoint(
    endpoint: Any,
    index: dict[str, Any],
    replacement_by_id: dict[str, dict[str, Any]],
    replacement_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    if isinstance(endpoint, dict):
        identifier = str(endpoint.get("id") or "")
        replacement = replacement_by_id.get(identifier) or replacement_by_identity.get(_entity_identity(endpoint))
        if replacement is not None:
            return replacement, True
        matches = index["by_id"].get(identifier) or []
        if len(matches) == 1:
            return matches[0], False
        matches = index["by_span"].get(_entity_identity(endpoint)) or []
        return (matches[0], False) if len(matches) == 1 else (None, False)

    reference = str(endpoint or "")
    replacement = replacement_by_id.get(reference)
    if replacement is not None:
        return replacement, True
    matches = index["by_id"].get(reference) or []
    if len(matches) == 1:
        return matches[0], False
    text_matches = [entity for entity in _entities_from_index(index) if str(entity.get("text") or "") == reference]
    return (text_matches[0], False) if len(text_matches) == 1 else (None, False)


def _entities_from_index(index: dict[str, Any]) -> list[dict[str, Any]]:
    """按对象身份返回实体索引中的唯一候选。"""

    values = []
    seen: set[int] = set()
    for candidates in index["by_span"].values():
        for entity in candidates:
            if id(entity) in seen:
                continue
            seen.add(id(entity))
            values.append(entity)
    return values


def _resolve_relation_endpoint(
    endpoint: Any,
    index: dict[str, Any],
    applied_by_identity: dict[tuple[str, int | None, int | None, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if isinstance(endpoint, dict):
        replacement = applied_by_identity.get(_entity_identity(endpoint))
        if replacement is not None:
            return replacement
        identifier = str(endpoint.get("id") or "")
        matches = index["by_id"].get(identifier) or []
        if len(matches) == 1:
            return matches[0]
        matches = index["by_span"].get(_entity_identity(endpoint)) or []
        return matches[0] if len(matches) == 1 else None
    reference = str(endpoint or "")
    id_matches = index["by_id"].get(reference) or []
    if len(id_matches) == 1:
        return id_matches[0]
    text_matches = [
        entity for values in index["by_span"].values() for entity in values if entity.get("text") == reference
    ]
    return text_matches[0] if len(text_matches) == 1 else None


def _entity_identity(entity: dict[str, Any]) -> tuple[str, int | None, int | None, str]:
    return (
        str(entity.get("text") or ""),
        entity.get("start") if isinstance(entity.get("start"), int) else None,
        entity.get("end") if isinstance(entity.get("end"), int) else None,
        canonical_entity_type(str(entity.get("label") or "")),
    )


def _same_surface_type_conflicts(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """记录同一表面名称的多类型冲突，供后续跨 Chunk 治理与人工审核。"""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        surface = _normalized_surface(entity.get("text"))
        if surface:
            grouped.setdefault(surface, []).append(entity)
    conflicts = []
    for surface, candidates in grouped.items():
        labels = sorted(
            {
                canonical_entity_type(str(candidate.get("label") or ""))
                for candidate in candidates
                if candidate.get("label")
            }
        )
        if len(labels) <= 1:
            continue
        conflicts.append(
            {
                "normalized_surface": surface,
                "text": str(candidates[0].get("text") or "")[:256],
                "labels": labels,
                "candidate_refs": [
                    {
                        "id": str(candidate.get("id") or ""),
                        "start": candidate.get("start"),
                        "end": candidate.get("end"),
                        "label": canonical_entity_type(str(candidate.get("label") or "")),
                    }
                    for candidate in candidates[:16]
                ],
                "status": "pending",
                "expert_review_required": True,
            }
        )
    conflicts.sort(key=lambda item: (item["normalized_surface"], item["labels"]))
    return {
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:64],
        "truncated": len(conflicts) > 64,
    }


def _normalized_surface(text: Any) -> str:
    return " ".join(_layout_quality_surface(text).casefold().split())


def _nested_ascii_word_fragment_reason(
    candidate: dict[str, Any],
    entities: list[dict[str, Any]],
) -> str | None:
    """拒绝从较长英文实体的单词内部起止的嵌套残片。"""

    text = str(candidate.get("text") or "")
    start = candidate.get("start")
    end = candidate.get("end")
    if (
        not re.search(r"[A-Za-z]", text)
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
    ):
        return None
    for container in entities:
        if container is candidate:
            continue
        outer_text = str(container.get("text") or "")
        outer_start = container.get("start")
        outer_end = container.get("end")
        if (
            not isinstance(outer_start, int)
            or isinstance(outer_start, bool)
            or not isinstance(outer_end, int)
            or isinstance(outer_end, bool)
            or outer_start > start
            or outer_end < end
            or (outer_start == start and outer_end == end)
        ):
            continue
        relative_start = start - outer_start
        relative_end = end - outer_start
        starts_inside_word = (
            relative_start > 0
            and relative_start < len(outer_text)
            and outer_text[relative_start - 1].isalnum()
            and outer_text[relative_start].isalnum()
        )
        ends_inside_word = (
            0 < relative_end < len(outer_text)
            and outer_text[relative_end - 1].isalnum()
            and outer_text[relative_end].isalnum()
        )
        if starts_inside_word or ends_inside_word:
            return "nested_ascii_word_fragment"
    return None


def _layout_quality_surface(text: Any) -> str:
    """仅为判质删除术语内部排版空白，不改写实体文本或证据 Span。"""

    normalized = normalize("NFKC", str(text or "").strip())
    return _LAYOUT_GAP_BETWEEN_TERM_CHARACTERS.sub("", normalized)


def _human_reviewed(entity: dict[str, Any]) -> bool:
    if str(entity.get("review_status") or "").casefold() in {"accepted", "rejected"}:
        return True
    return any("human" in str(source).casefold() for source in entity.get("model_sources") or [])


def _proposal_priority(proposal: dict[str, Any]) -> tuple[float, str]:
    return (-float(proposal["confidence"]), str(proposal["action"]), str(proposal["suggested_label"]))


def _proposal_sort_key(proposal: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(proposal["start"]),
        int(proposal["end"]),
        str(proposal["text"]),
        str(proposal["current_label"]),
        str(proposal["action"]),
        str(proposal["suggested_label"]),
    )


def _probability(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(number, 1.0)) if math.isfinite(number) else 0.0


def _validated_probability(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("entity_review_min_confidence 必须是 0 到 1 之间的数字")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("entity_review_min_confidence 必须是 0 到 1 之间的数字") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("entity_review_min_confidence 必须是 0 到 1 之间的数字")
    return number
