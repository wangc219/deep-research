"""为 LightRAG 二次补抽构造可审计的封闭关系候选集。"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import (
    DEFENSE_ONTOLOGY_V1,
    canonical_entity_type,
    validate_relation_types,
)
from platform_core.knowledge.graphs.lightrag_candidate_review import clear_non_ontology_entity_reason

RELATION_COMPLETION_REVISION = "defense-lightrag-relation-completion-v4"
RELATION_ENDPOINT_POLICIES = frozenset(
    {
        "multi_model_consensus",
        "entity_first_single_model",
        "lightrag_primary",
    }
)
# PDF 解析后的单个换行通常只是视觉折行，不是语义句界；句末标点或空行才截断关系候选。
_LINE_BREAK = r"(?:\r\n|\r(?!\n)|(?<!\r)\n)"
_SENTENCE_BOUNDARY = re.compile(rf"[。！？!?]|{_LINE_BREAK}[ \t]*{_LINE_BREAK}")
_RELATION_CUES = {
    "BASED_ON": re.compile(r"基于|依据|源于|机理|原理"),
    "USES_TECHNOLOGY": re.compile(r"采用|使用|利用|借助|通过"),
    "IMPLEMENTS": re.compile(r"实现|实现了|用于实现"),
    "COMPOSED_OF": re.compile(r"由.+组成|组成|构成|包含|集成"),
    "ENABLES_CAPABILITY": re.compile(r"形成|实现|具备|获得|提供.+能力"),
    "SUPPORTS_APPLICATION": re.compile(r"支撑|支持|保障"),
    "APPLIED_TO": re.compile(r"应用于|用于|面向|部署于"),
    "PRODUCES_ACHIEVEMENT": re.compile(r"研制|形成.+成果|获得.+成果|产出"),
    "BELONGS_TO_DOMAIN": re.compile(r"属于|归属|领域"),
    "MEASURED_BY": re.compile(r"指标|测量|度量|达到|性能为|精度为"),
    "CONSTRAINED_BY": re.compile(r"受限|限制|约束|瓶颈|依赖于"),
    "IMPROVES": re.compile(r"提升|提高|增强|改善|优化"),
    "VALIDATED_BY": re.compile(r"验证|试验|测试|样机"),
    "EVOLVES_FROM": re.compile(r"演化|发展自|改进自|在.+基础上"),
    "REPLACES": re.compile(r"替代|取代|代替"),
}
_ENDPOINT_TYPE_SUFFIX_HINTS = (
    (("武器", "装备", "导弹", "战斗机", "无人机", "舰艇"), "ProductSystem"),
    (("激光器", "产生器", "电源", "模块", "芯片", "天线", "传感器"), "Component"),
    (("算法", "模型"), "AlgorithmModel"),
    (("材料", "合金", "陶瓷", "涂层", "复合材料"), "Material"),
    (("原理", "机理", "效应", "定律"), "ScientificPrinciple"),
    (("能力",), "Capability"),
    (("约束", "限制条件"), "Constraint"),
    (("技术", "工艺", "方案"), "KeyTechnology"),
    (("效率", "精度", "波束质量", "脉冲能量"), "Metric"),
)


def normalize_relation_completion_options(
    options: dict[str, Any] | None,
    *,
    orchestration_mode: str | None = None,
    primary_extract_relations: bool | None = None,
) -> dict[str, Any]:
    """按主抽职责规范化关系补抽，避免实体优先模式被错误的多模型门槛拒绝。"""
    if options is not None and not isinstance(options, dict):
        raise ValueError("llm_enhancement.relation_completion 必须是对象")
    raw = dict(options or {})
    normalized_mode = str(orchestration_mode or "").strip()
    lightrag_primary = normalized_mode == "lightrag_primary"
    entity_first = not lightrag_primary and primary_extract_relations is False
    default_policy = (
        "lightrag_primary"
        if lightrag_primary
        else "entity_first_single_model"
        if entity_first
        else "multi_model_consensus"
    )
    endpoint_policy = str(raw.get("endpoint_policy") or default_policy).strip()
    if endpoint_policy not in RELATION_ENDPOINT_POLICIES:
        allowed = ", ".join(sorted(RELATION_ENDPOINT_POLICIES))
        raise ValueError(f"llm_enhancement.relation_completion.endpoint_policy 必须是: {allowed}")
    relaxed_endpoint_support = endpoint_policy in {"entity_first_single_model", "lightrag_primary"}
    return {
        "enabled": _boolean(raw.get("enabled", False), "enabled"),
        "endpoint_policy": endpoint_policy,
        "max_entities": _integer(raw.get("max_entities", 48), "max_entities", 2, 256),
        "max_candidate_pairs": _integer(
            raw.get("max_candidate_pairs", 32),
            "max_candidate_pairs",
            1,
            256,
        ),
        "max_distance_chars": _integer(
            raw.get("max_distance_chars", 480 if lightrag_primary else 240),
            "max_distance_chars",
            1,
            2000,
        ),
        "min_entity_confidence": _probability(
            raw.get("min_entity_confidence", 0.5 if relaxed_endpoint_support else 0.75),
            "min_entity_confidence",
        ),
        "min_relation_confidence": _probability(
            raw.get("min_relation_confidence", 0.82),
            "min_relation_confidence",
        ),
        "min_entity_model_sources": _integer(
            raw.get("min_entity_model_sources", 1 if relaxed_endpoint_support else 2),
            "min_entity_model_sources",
            1,
            4,
        ),
        "require_same_sentence": _boolean(
            raw.get("require_same_sentence", not lightrag_primary),
            "require_same_sentence",
        ),
        "require_relation_cue": _boolean(
            raw.get("require_relation_cue", True),
            "require_relation_cue",
        ),
    }


def build_relation_completion_inventory(
    text: str,
    result: dict[str, Any],
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    """生成句内实体对、允许关系和稳定临时引用，不让 LLM 自由发明端点。"""
    config = normalize_relation_completion_options(options)
    raw_entities = list(result.get("entities") or [])
    rejection_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()
    eligible = []
    for item in raw_entities:
        rejection_reason = _entity_rejection_reason(item, text, config)
        if rejection_reason:
            rejection_counts[rejection_reason] += 1
            continue
        eligible.append(_normalized_entity(item))

    entities_by_span: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for entity in eligible:
        span_key = (int(entity["start"]), int(entity["end"]), str(entity["text"]))
        entities_by_span.setdefault(span_key, []).append(entity)
    eligible = _resolve_ambiguous_entity_types(
        entities_by_span,
        endpoint_policy=config["endpoint_policy"],
        rejection_counts=rejection_counts,
        resolution_counts=resolution_counts,
    )
    eligible.sort(
        key=lambda item: (
            -_confidence(item.get("confidence")),
            int(item["start"]),
            int(item["end"]),
            str(item["label"]),
            str(item["text"]),
        )
    )
    eligible = eligible[: config["max_entities"]]
    eligible.sort(key=lambda item: (int(item["start"]), int(item["end"]), str(item["text"])))

    aliases: dict[str, dict[str, Any]] = {}
    alias_by_key: dict[tuple[str, int, int, str], str] = {}
    entity_by_ref: dict[str, dict[str, Any]] = {}
    for index, entity in enumerate(eligible, start=1):
        alias = f"rc-e{index}"
        key = _entity_key(entity)
        aliases[alias] = entity
        alias_by_key[key] = alias
        for ref in (str(entity.get("id") or "").strip(), str(entity.get("text") or "").strip()):
            if ref:
                entity_by_ref.setdefault(ref, entity)

    existing_relations = _existing_relation_keys(result.get("relations") or [], entity_by_ref)
    rows = []
    for source in eligible:
        for target in eligible:
            source_key = _entity_key(source)
            target_key = _entity_key(target)
            if source_key == target_key:
                continue
            if int(source["start"]) < int(target["end"]) and int(target["start"]) < int(source["end"]):
                continue
            endpoint_start = min(int(source["start"]), int(target["start"]))
            endpoint_end = max(int(source["end"]), int(target["end"]))
            distance = endpoint_end - endpoint_start
            if distance > config["max_distance_chars"]:
                continue
            between_start = min(int(source["end"]), int(target["end"]))
            between_end = max(int(source["start"]), int(target["start"]))
            if (
                config["require_same_sentence"]
                and between_end > between_start
                and _SENTENCE_BOUNDARY.search(text[between_start:between_end])
            ):
                continue
            evidence_start, evidence_end = _sentence_evidence_span(text, endpoint_start, endpoint_end)
            allowed_labels = [
                relation.code
                for relation in DEFENSE_ONTOLOGY_V1.relation_types
                if not relation.hypothesis_only
                and validate_relation_types(source["label"], relation.code, target["label"])
                and (source_key, relation.code, target_key) not in existing_relations
            ]
            evidence_text = text[evidence_start:evidence_end]
            matched_cues = {
                label: cues for label in allowed_labels if (cues := match_relation_cues(label, evidence_text))
            }
            between_endpoint_cues = {
                label: cues
                for label in allowed_labels
                if (cues := match_relation_cues(label, text[between_start:between_end]))
            }
            if config["require_relation_cue"]:
                allowed_labels = [label for label in allowed_labels if label in matched_cues]
            if not allowed_labels:
                continue
            rows.append(
                {
                    "source_ref": alias_by_key[source_key],
                    "target_ref": alias_by_key[target_key],
                    "source": _compact_entity(source),
                    "target": _compact_entity(target),
                    "allowed_labels": allowed_labels,
                    "matched_cues": {label: matched_cues.get(label, []) for label in allowed_labels},
                    "between_endpoint_cues": {label: between_endpoint_cues.get(label, []) for label in allowed_labels},
                    "evidence_span": {"start": evidence_start, "end": evidence_end},
                    "distance_chars": distance,
                    "pair_confidence_floor": round(
                        min(_confidence(source.get("confidence")), _confidence(target.get("confidence"))),
                        6,
                    ),
                }
            )

    rows, cue_position_pruned_pairs = _prefer_between_endpoint_cues(rows)
    rows.sort(
        key=lambda item: (
            int(item["distance_chars"]),
            -float(item["pair_confidence_floor"]),
            int(item["evidence_span"]["start"]),
            str(item["source_ref"]),
            str(item["target_ref"]),
        )
    )
    rows = rows[: config["max_candidate_pairs"]]
    for index, row in enumerate(rows, start=1):
        row["pair_ref"] = f"rc-p{index}"

    selected_aliases = {str(row["source_ref"]) for row in rows} | {str(row["target_ref"]) for row in rows}
    return {
        "revision": RELATION_COMPLETION_REVISION,
        "config": config,
        "candidates": rows,
        "endpoint_aliases": {alias: entity for alias, entity in aliases.items() if alias in selected_aliases},
        "allowed_relation_claims": {
            (str(row["source_ref"]), label, str(row["target_ref"])) for row in rows for label in row["allowed_labels"]
        },
        "metrics": {
            "input_entity_count": len(raw_entities),
            "eligible_entity_count": len(eligible),
            "entity_rejection_counts": dict(sorted(rejection_counts.items())),
            "entity_resolution_counts": dict(sorted(resolution_counts.items())),
            "existing_relation_count": len(result.get("relations") or []),
            "candidate_pair_count": len(rows),
            "cue_position_pruned_pairs": cue_position_pruned_pairs,
        },
    }


def relation_completion_prompt_payload(inventory: dict[str, Any]) -> dict[str, Any]:
    """将重复实体从候选对中提取为一次性引用表，降低 Prompt 成本。"""
    aliases = inventory.get("endpoint_aliases") or {}
    candidates = inventory.get("candidates") or []
    return {
        "entities": {
            str(alias): _compact_entity(entity) for alias, entity in aliases.items() if isinstance(entity, dict)
        },
        "pairs": [
            {
                "pair_ref": row.get("pair_ref"),
                "source_ref": row.get("source_ref"),
                "target_ref": row.get("target_ref"),
                "allowed_labels": row.get("allowed_labels") or [],
                "matched_cues": row.get("matched_cues") or {},
                "between_endpoint_cues": row.get("between_endpoint_cues") or {},
                "evidence_span": row.get("evidence_span") or {},
            }
            for row in candidates
            if isinstance(row, dict)
        ],
    }


def _prefer_between_endpoint_cues(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """同句同关系存在端点间谓词时，删除仅由远处谓词触发的伪候选。"""
    groups_with_between_cue = {
        (
            int((row.get("evidence_span") or {}).get("start") or 0),
            int((row.get("evidence_span") or {}).get("end") or 0),
            label,
        )
        for row in rows
        for label in row.get("allowed_labels") or []
        if (row.get("between_endpoint_cues") or {}).get(label)
    }
    if not groups_with_between_cue:
        return rows, 0

    filtered = []
    pruned_pairs = 0
    for row in rows:
        evidence = row.get("evidence_span") or {}
        retained_labels = []
        for label in row.get("allowed_labels") or []:
            group = (int(evidence.get("start") or 0), int(evidence.get("end") or 0), label)
            if group in groups_with_between_cue and not (row.get("between_endpoint_cues") or {}).get(label):
                continue
            retained_labels.append(label)
        if not retained_labels:
            pruned_pairs += 1
            continue
        retained = dict(row)
        retained["allowed_labels"] = retained_labels
        retained["matched_cues"] = {label: (row.get("matched_cues") or {}).get(label, []) for label in retained_labels}
        retained["between_endpoint_cues"] = {
            label: (row.get("between_endpoint_cues") or {}).get(label, []) for label in retained_labels
        }
        filtered.append(retained)
    return filtered, pruned_pairs


def match_relation_cues(label: str, text: str) -> list[str]:
    """返回关系证据中命中的有限触发词，供候选压缩和人工审核共用。"""
    pattern = _RELATION_CUES.get(str(label or "").strip().upper())
    if pattern is None:
        return []
    return list(dict.fromkeys(match.group(0)[:64] for match in pattern.finditer(text)))[:4]


def _sentence_evidence_span(text: str, endpoint_start: int, endpoint_end: int) -> tuple[int, int]:
    """返回覆盖两个端点的完整句子，便于识别位于首实体之前的关系谓词。"""
    left = 0
    for match in _SENTENCE_BOUNDARY.finditer(text, 0, endpoint_start):
        left = match.end()
    right_match = _SENTENCE_BOUNDARY.search(text, endpoint_end)
    right = right_match.end() if right_match is not None else len(text)
    return left, right


def _entity_rejection_reason(value: Any, text: str, config: dict[str, Any]) -> str | None:
    if not isinstance(value, dict):
        return "invalid_record"
    start, end = value.get("start"), value.get("end")
    entity_text = str(value.get("text") or "")
    label = canonical_entity_type(str(value.get("label") or ""))
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or not 0 <= start < end <= len(text)
        or text[start:end] != entity_text
    ):
        return "invalid_span"
    if label not in DEFENSE_ONTOLOGY_V1.entity_type_by_code:
        return "invalid_ontology_type"
    if _confidence(value.get("confidence")) < config["min_entity_confidence"]:
        return "below_entity_confidence"
    if clear_non_ontology_entity_reason(entity_text):
        return "clear_non_ontology_entity"
    model_sources = {str(source).strip() for source in value.get("model_sources") or [] if str(source).strip()}
    if len(model_sources) < config["min_entity_model_sources"]:
        return "insufficient_model_support"
    return None


def _resolve_ambiguous_entity_types(
    entities_by_span: dict[tuple[int, int, str], list[dict[str, Any]]],
    *,
    endpoint_policy: str,
    rejection_counts: Counter[str],
    resolution_counts: Counter[str],
) -> list[dict[str, Any]]:
    """实体优先模式仅用高精度表面提示消解类型；其余冲突继续拒绝进入关系端点。"""
    resolved = []
    for candidates in entities_by_span.values():
        labels = {str(candidate["label"]) for candidate in candidates}
        if len(labels) <= 1:
            resolved.extend(candidates)
            continue
        if endpoint_policy == "entity_first_single_model":
            hinted_labels = _relation_endpoint_type_hints(candidates[0].get("text"))
            hinted = [candidate for candidate in candidates if candidate["label"] in hinted_labels]
            if len(hinted) == 1:
                resolved.append(hinted[0])
                resolution_counts["ambiguous_resolved_by_surface_hint"] += 1
                rejection_counts["ambiguous_nonselected_types"] += len(candidates) - 1
                continue
        rejection_counts["ambiguous_same_span_types"] += len(candidates)
    return resolved


def _relation_endpoint_type_hints(text: Any) -> set[str]:
    """返回只用于封闭关系端点消歧的保守术语后缀类型。"""
    normalized = str(text or "").strip()
    return {label for suffixes, label in _ENDPOINT_TYPE_SUFFIX_HINTS if normalized.endswith(suffixes)}


def _normalized_entity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "label": canonical_entity_type(str(value.get("label") or "")),
        "start": int(value["start"]),
        "end": int(value["end"]),
        "text": str(value.get("text") or ""),
    }


def _existing_relation_keys(
    values: list[Any],
    entity_by_ref: dict[str, dict[str, Any]],
) -> set[tuple[tuple[str, int, int, str], str, tuple[str, int, int, str]]]:
    keys = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        source = _endpoint_entity(value.get("source"), entity_by_ref)
        target = _endpoint_entity(value.get("target"), entity_by_ref)
        label = str(value.get("label") or "").strip().upper()
        if source is not None and target is not None and label:
            keys.add((_entity_key(source), label, _entity_key(target)))
    return keys


def _endpoint_entity(value: Any, entity_by_ref: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if all(field in value for field in ("text", "label", "start", "end")):
            return value
        for ref in (str(value.get("id") or "").strip(), str(value.get("text") or "").strip()):
            if ref in entity_by_ref:
                return entity_by_ref[ref]
        return None
    return entity_by_ref.get(str(value or "").strip())


def _entity_key(entity: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        canonical_entity_type(str(entity.get("label") or "")),
        int(entity.get("start") or 0),
        int(entity.get("end") or 0),
        str(entity.get("text") or ""),
    )


def _compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(entity.get("text") or "")[:256],
        "label": str(entity.get("label") or "")[:64],
        "start": int(entity["start"]),
        "end": int(entity["end"]),
        "confidence": round(_confidence(entity.get("confidence")), 6),
    }


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return normalized if math.isfinite(normalized) else 0.0


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"llm_enhancement.relation_completion.{field} 必须是布尔值")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"llm_enhancement.relation_completion.{field} 必须是 {minimum} 到 {maximum} 之间的整数")
    return value


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"llm_enhancement.relation_completion.{field} 必须是 0 到 1 之间的数字")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"llm_enhancement.relation_completion.{field} 必须是 0 到 1 之间的数字") from exc
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"llm_enhancement.relation_completion.{field} 必须是 0 到 1 之间的数字")
    return normalized
