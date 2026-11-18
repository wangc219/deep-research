"""基于结构化 Block 与权威图谱记录生成文档审计结果。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from typing import Any

from platform_core.knowledge.graphs.knowledge_card_profile import build_knowledge_card_profile

DOCUMENT_AUDIT_RULE_VERSION = "defense-document-audit-v1"

_RESEARCH_MARKERS = ("摘要", "关键词", "引言", "方法", "试验", "实验", "结果", "结论", "参考文献", "doi")
_NON_RESEARCH_MARKERS = ("征稿启事", "会议通知", "目录", "编者按", "作者索引", "广告", "版权声明", "勘误")
_NEGATED_MILITARY_PATTERNS = (
    r"(?:未|不|无)(?:直接)?涉及(?:任何)?(?:军事|武器装备|装备|作战)(?:应用|场景|任务|需求)?",
    r"(?:不|未)(?:面向|用于|服务于)(?:军事|武器装备|装备|作战)(?:应用|场景|任务|需求)?",
    r"缺少(?:明确)?(?:军事|武器装备|装备|作战)(?:关联|应用|场景|落点)",
)
_MILITARY_TERMS = (
    "军事",
    "武器",
    "装备",
    "作战",
    "雷达",
    "电子对抗",
    "抗干扰",
    "导弹",
    "防空",
    "反导",
    "无人机",
    "制导",
    "火控",
    "侦察",
    "毁伤",
    "战场",
    "空天",
)
_EQUIPMENT_TERMS = ("装备", "平台", "系统", "组件", "器件", "载荷", "任务", "能力")
_POTENTIAL_MILITARY_TERMS = (
    "前沿技术",
    "新材料",
    "复合材料",
    "算法",
    "智能",
    "控制",
    "感知",
    "传感",
    "能源",
    "动力",
    "制造",
    "高温",
    "高速",
    "高过载",
    "低信噪比",
    "可靠性",
    "自主",
    "增材制造",
    "数字孪生",
)
_TRANSFER_MARKERS = (
    "可迁移",
    "迁移至",
    "可用于",
    "适用于",
    "应用于",
    "可支撑",
    "有望用于",
    "潜在应用",
    "跨领域",
)
_MILITARY_VALUE_LABELS = {
    "military": "Military",
    "potential": "Potential",
    "uncertain": "Uncertain",
    "general": "General",
    "no_military_value": "No Military Value",
}
_MATURITY_MARKERS = {
    "concept": ("设想", "概念", "假设", "可能"),
    "laboratory": ("仿真", "实验", "试验", "样机"),
    "engineering": ("工程验证", "原型", "实测", "部署", "应用"),
    "operational": ("列装", "实战", "批产", "规模化应用"),
}

_TECHNOLOGY_TYPES = {"KeyTechnology", "AlgorithmModel", "Material", "Component", "ScientificPrinciple"}
_CAPABILITY_TYPES = {"Capability", "Metric"}
_APPLICATION_TYPES = {"ApplicationScenario", "ProductSystem", "Domain"}
_INNOVATION_RELATIONS = {"EVOLVES_FROM", "REPLACES", "IMPROVES", "COMBINES_WITH", "TRANSFERABLE_TO"}
_ENTITY_EVIDENCE_USES = {
    "ScientificPrinciple": "科学原理识别",
    "KeyTechnology": "关键技术识别",
    "AlgorithmModel": "算法模型识别",
    "Material": "材料识别",
    "Component": "技术组件识别",
    "ProductSystem": "产品系统识别",
    "Capability": "能力收益识别",
    "ApplicationScenario": "应用场景识别",
    "Domain": "技术领域识别",
    "Achievement": "技术成果识别",
    "Metric": "技术指标识别",
    "Constraint": "约束条件识别",
}


def triage_document(document: dict[str, Any]) -> dict[str, Any]:
    """保守识别非研究资料；不确定材料继续进入抽取，避免误杀。"""
    blocks = list(document.get("blocks") or [])
    title = str(document.get("title") or "").strip()
    text = "\n".join(str(block.get("text") or "") for block in blocks)
    normalized = (title + "\n" + text).lower()
    triage_text = _strip_negated_military_context(normalized)
    research_hits = _term_hits(normalized, _RESEARCH_MARKERS)
    non_research_hits = _term_hits((title + "\n" + text[:3000]).lower(), _NON_RESEARCH_MARKERS)
    military_hits = _term_hits(triage_text, _MILITARY_TERMS)
    equipment_hits = _term_hits(triage_text, _EQUIPMENT_TERMS)
    potential_hits = _term_hits(normalized, _POTENTIAL_MILITARY_TERMS)
    transfer_hits = _term_hits(normalized, _TRANSFER_MARKERS)
    negated_military_phrases = _pattern_hits(normalized, _NEGATED_MILITARY_PATTERNS)
    content_chars = len(text.strip())

    explicit_non_research = len(non_research_hits) >= 2 and len(research_hits) < 2
    too_short = content_chars < 800
    eligible = not explicit_non_research and not too_short
    if explicit_non_research:
        document_kind = "non_research"
        reason = "命中多个非研究资料标记，且缺少论文结构信号。"
    elif too_short:
        document_kind = "insufficient_content"
        reason = "可解析正文少于 800 字，暂不进入实体关系抽取。"
    elif len(research_hits) >= 4:
        document_kind = "research_article"
        reason = "具备摘要、方法、试验、结论或参考文献等研究论文结构信号。"
    elif "综述" in normalized or "review" in normalized:
        document_kind = "review"
        reason = "识别为综述资料，保留进入知识抽取。"
    else:
        document_kind = "uncertain_research"
        reason = "未形成强非研究证据，按保守策略保留进入知识抽取。"

    if len(military_hits) >= 2 and equipment_hits:
        triage_level = "military"
    elif military_hits:
        triage_level = "military_context"
    else:
        triage_level = "general_technology"

    military_value = _classify_military_value(
        eligible=eligible,
        document_kind=document_kind,
        triage_level=triage_level,
        military_hits=military_hits,
        potential_hits=potential_hits,
        transfer_hits=transfer_hits,
        negated_military_phrases=negated_military_phrases,
    )

    input_payload = [
        {
            "block_id": str(block.get("block_id") or ""),
            "text_sha256": hashlib.sha256(str(block.get("text") or "").encode("utf-8")).hexdigest(),
        }
        for block in blocks
    ]
    evidence = _find_evidence(
        blocks,
        [
            *research_hits,
            *non_research_hits,
            *military_hits,
            *potential_hits,
            *transfer_hits,
            *negated_military_phrases,
        ],
        limit=12,
    )
    return {
        "document_id": str(document["document_id"]),
        "document_version": int(document.get("document_version") or 1),
        "document_kind": document_kind,
        "triage_level": triage_level,
        **military_value,
        "eligible_for_extraction": eligible,
        "reason": reason,
        "signals": {
            "content_chars": content_chars,
            "block_count": len(blocks),
            "research_markers": research_hits,
            "non_research_markers": non_research_hits,
            "military_markers": military_hits,
            "equipment_markers": equipment_hits,
            "potential_military_markers": potential_hits,
            "transfer_markers": transfer_hits,
            "negated_military_phrases": negated_military_phrases,
        },
        "evidence": evidence,
        "rule_version": DOCUMENT_AUDIT_RULE_VERSION,
        "input_hash": _canonical_sha256(input_payload),
    }


def build_document_knowledge(
    document: dict[str, Any],
    *,
    triage: dict[str, Any],
    pipeline_revision: str,
    ontology_version: str,
) -> dict[str, Any]:
    """仅用权威实体、关系和原文 Span 构造研究链及知识卡。"""
    entities = [item for item in document.get("entities") or [] if item.get("lifecycle_status", "active") == "active"]
    relations = [
        item
        for item in document.get("relations") or []
        if item.get("lifecycle_status", "active") == "active"
        and item.get("review_status") not in {"rejected", "superseded"}
    ]
    entity_by_id = {str(item["entity_id"]): item for item in entities}
    evidence_refs = _collect_evidence_refs(entities, relations, blocks=document.get("blocks") or [])
    main_thread = _build_thread(
        document=document,
        thread_key="main",
        thread_type="main",
        title=f"{document.get('title') or document['document_id']}：研究主线",
        entities=entities,
        relations=relations,
        evidence_refs=evidence_refs,
        triage=triage,
        pipeline_revision=pipeline_revision,
    )

    grouped_entity_ids: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        for mention in entity.get("mentions") or []:
            heading = " / ".join(str(item) for item in mention.get("heading_path") or [] if item)
            if heading:
                grouped_entity_ids[heading].add(str(entity["entity_id"]))
    sub_threads = []
    for heading, entity_ids in sorted(grouped_entity_ids.items()):
        if len(entity_ids) < 2:
            continue
        section_entities = [entity_by_id[entity_id] for entity_id in sorted(entity_ids)]
        section_relations = [
            relation
            for relation in relations
            if str(relation.get("source_entity_id")) in entity_ids
            and str(relation.get("target_entity_id")) in entity_ids
        ]
        sub_threads.append(
            _build_thread(
                document=document,
                thread_key=f"section:{heading}",
                thread_type="sub",
                title=heading,
                entities=section_entities,
                relations=section_relations,
                evidence_refs=_collect_evidence_refs(
                    section_entities,
                    section_relations,
                    blocks=document.get("blocks") or [],
                ),
                triage=triage,
                pipeline_revision=pipeline_revision,
            )
        )
        if len(sub_threads) >= 8:
            break

    all_threads = [main_thread, *sub_threads]
    card_id = _stable_id(
        "card",
        str(document["document_id"]),
        str(document.get("document_version") or 1),
        pipeline_revision,
    )
    maturity = _maturity(document, relations)
    heat_signals = _heat_signals(document, entities, relations)
    innovation = _innovation_potential(entities, relations)
    profile = build_knowledge_card_profile(
        entities=entities,
        relations=relations,
        triage=triage,
        threads=all_threads,
        evidence_refs=evidence_refs,
    )
    card = {
        "card_id": card_id,
        "kb_id": str(document["kb_id"]),
        "document_id": str(document["document_id"]),
        "document_version": int(document.get("document_version") or 1),
        "title": str(document.get("title") or document["document_id"]),
        "source_summary": dict(document.get("source_summary") or {}),
        "triage": triage,
        "content_overview": _content_overview(document, entities, relations),
        "main_thread_id": main_thread["thread_id"],
        "sub_thread_ids": [item["thread_id"] for item in sub_threads],
        "core_entity_ids": [str(item["entity_id"]) for item in entities[:50]],
        "core_relation_ids": [str(item["triple_id"]) for item in relations[:100]],
        "technology_families": _entity_names(entities, _TECHNOLOGY_TYPES, 12),
        "capability_gains": _entity_names(entities, _CAPABILITY_TYPES, 12),
        "application_directions": _entity_names(entities, _APPLICATION_TYPES, 12),
        "evidence_refs": evidence_refs[:100],
        "maturity": maturity,
        "heat_signals": heat_signals,
        "innovation_potential": innovation,
        **profile,
        "uncertainty": (
            "知识卡是对已抽取知识的审计摘要；pending/Inference/Hypothesis 不等同于已接受事实，"
            "应结合 review_status、claim_level 和原文 Span 复核。"
        ),
        "pipeline_revision": pipeline_revision,
        "ontology_version": ontology_version,
        "governance_status": "pending",
    }
    return {"threads": all_threads, "card": card}


def _build_thread(
    *,
    document: dict[str, Any],
    thread_key: str,
    thread_type: str,
    title: str,
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
    triage: dict[str, Any],
    pipeline_revision: str,
) -> dict[str, Any]:
    relation_types = Counter(str(item.get("relation_type") or "") for item in relations)
    innovation_signals = [
        {"relation_type": relation_type, "count": count}
        for relation_type, count in sorted(relation_types.items())
        if relation_type in _INNOVATION_RELATIONS
    ]
    accepted = sum(1 for item in relations if item.get("review_status") == "accepted")
    evidence_coverage = sum(1 for item in relations if item.get("evidence_spans")) / max(len(relations), 1)
    confidence = min(0.95, 0.35 + accepted * 0.03 + evidence_coverage * 0.35 + min(len(entities), 10) * 0.02)
    return {
        "thread_id": _stable_id(
            "thread",
            str(document["document_id"]),
            str(document.get("document_version") or 1),
            thread_key,
            pipeline_revision,
        ),
        "kb_id": str(document["kb_id"]),
        "document_id": str(document["document_id"]),
        "document_version": int(document.get("document_version") or 1),
        "thread_key": thread_key,
        "thread_type": thread_type,
        "title": title,
        "technical_line": _entity_names(entities, _TECHNOLOGY_TYPES, 12),
        "capability_direction": _entity_names(entities, _CAPABILITY_TYPES, 12),
        "application_direction": _entity_names(entities, _APPLICATION_TYPES, 12),
        "military_value": {
            "level": triage.get("military_value_level") or triage.get("triage_level", "general_technology"),
            "code": triage.get("military_value_code"),
            "reason": triage.get("military_value_reason"),
            "deep_extraction_recommended": triage.get("deep_extraction_recommended"),
            "expert_review_required": triage.get("military_value_review_required"),
            "evidence": triage.get("evidence", [])[:6],
        },
        "innovation_signals": innovation_signals,
        "entity_ids": [str(item["entity_id"]) for item in entities],
        "relation_ids": [str(item["triple_id"]) for item in relations],
        "evidence_refs": evidence_refs,
        "uncertainty": "研究链由当前图谱 revision 自动归纳，关系审核状态变化后需重建。",
        "confidence": round(confidence, 4),
        "pipeline_revision": pipeline_revision,
        "governance_status": "pending",
    }


def _content_overview(document: dict[str, Any], entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> str:
    technologies = _entity_names(entities, _TECHNOLOGY_TYPES, 3)
    capabilities = _entity_names(entities, _CAPABILITY_TYPES, 3)
    applications = _entity_names(entities, _APPLICATION_TYPES, 3)
    parts = [f"已识别 {len(entities)} 个标准实体和 {len(relations)} 条候选/有效关系。"]
    if technologies:
        parts.append(f"技术主项：{'、'.join(technologies)}。")
    if capabilities:
        parts.append(f"能力指向：{'、'.join(capabilities)}。")
    if applications:
        parts.append(f"应用方向：{'、'.join(applications)}。")
    return "".join(parts)


def _maturity(document: dict[str, Any], relations: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(str(block.get("text") or "") for block in document.get("blocks") or [])
    scores = {stage: sum(text.count(term) for term in terms) for stage, terms in _MATURITY_MARKERS.items()}
    validated = sum(1 for item in relations if item.get("relation_type") == "VALIDATED_BY")
    scores["engineering"] += validated
    stage = (
        max(scores, key=lambda item: (scores[item], list(scores).index(item))) if any(scores.values()) else "unknown"
    )
    return {
        "stage": stage,
        "signals": scores,
        "algorithm_version": DOCUMENT_AUDIT_RULE_VERSION,
        "claim_level": "Inference",
    }


def _heat_signals(
    document: dict[str, Any], entities: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> dict[str, Any]:
    years = re.findall(r"(?:19|20)\d{2}", str(document.get("title") or ""))
    return {
        "publication_year": int(years[-1]) if years else None,
        "entity_mentions": sum(len(item.get("mentions") or []) for item in entities),
        "relation_mentions": len(relations),
        "accepted_relations": sum(1 for item in relations if item.get("review_status") == "accepted"),
        "note": "单篇知识卡仅记录可观测信号；跨文献热度由演化分析模块计算。",
    }


def _innovation_potential(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    innovation_relations = [
        str(item.get("triple_id"))
        for item in relations
        if item.get("relation_type") in _INNOVATION_RELATIONS or item.get("claim_level") == "Hypothesis"
    ]
    type_diversity = len({str(item.get("label") or "") for item in entities})
    score = min(1.0, len(innovation_relations) * 0.08 + type_diversity * 0.04)
    return {
        "score": round(score, 4),
        "supporting_relation_ids": innovation_relations[:30],
        "entity_type_diversity": type_diversity,
        "claim_level": "Inference",
        "algorithm_version": DOCUMENT_AUDIT_RULE_VERSION,
    }


def _collect_evidence_refs(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    *,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """合并同一 Span 的实体与关系引用，并从原始 Block 严格回切证据。"""
    refs: dict[tuple[Any, ...], dict[str, Any]] = {}
    for entity in entities:
        for mention in entity.get("mentions") or []:
            key = (mention.get("block_id"), mention.get("start"), mention.get("end"))
            ref = refs.setdefault(key, _evidence_ref(mention))
            entity_id = entity.get("entity_id")
            if entity_id is not None and entity_id not in ref["entity_ids"]:
                ref["entity_ids"].append(entity_id)
            _append_support(
                ref,
                {
                    "kind": "entity",
                    "id": entity_id,
                    "evidence_use": "entity_identification",
                    "evidence_use_label": _ENTITY_EVIDENCE_USES.get(
                        str(entity.get("label") or entity.get("type") or ""),
                        "实体识别",
                    ),
                    "entity_type": entity.get("label") or entity.get("type"),
                    "claim_level": None,
                    "review_status": mention.get("review_status") or "pending",
                    "confidence": mention.get("confidence"),
                    "extraction_method": mention.get("extraction_method") or "entity_mention",
                    "model_version": mention.get("model_version"),
                    "ontology_version": mention.get("ontology_version"),
                    "pipeline_revision": mention.get("pipeline_revision"),
                },
            )
    for relation in relations:
        for span in relation.get("evidence_spans") or []:
            key = (span.get("block_id"), span.get("start"), span.get("end"))
            ref = refs.setdefault(key, _evidence_ref(span))
            triple_id = relation.get("triple_id")
            if triple_id is not None and triple_id not in ref["triple_ids"]:
                ref["triple_ids"].append(triple_id)
            _append_support(
                ref,
                {
                    "kind": "relation",
                    "id": triple_id,
                    "evidence_use": "relation_support",
                    "evidence_use_label": f"{relation.get('relation_type') or '关系'} 支撑",
                    "relation_type": relation.get("relation_type"),
                    "claim_level": span.get("claim_level") or relation.get("claim_level") or "Inference",
                    "review_status": span.get("review_status") or relation.get("review_status") or "pending",
                    "confidence": span.get("confidence", relation.get("confidence")),
                    "extraction_method": span.get("extraction_method")
                    or relation.get("extraction_method")
                    or "relation_mention",
                    "model_version": span.get("model_version") or relation.get("model_version"),
                    "ontology_version": span.get("ontology_version") or relation.get("ontology_version"),
                    "pipeline_revision": span.get("pipeline_revision") or relation.get("pipeline_revision"),
                },
            )

    block_by_id = {str(block.get("block_id") or ""): block for block in blocks}
    result = []
    for key in sorted(refs, key=lambda item: tuple(str(value) for value in item)):
        ref = refs[key]
        block = block_by_id.get(str(ref["block_id"] or ""))
        ref.update(_rebuild_evidence_text(ref, block))
        result.append(ref)
    return result


def _evidence_ref(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": span.get("block_id"),
        "page": span.get("page"),
        "start": span.get("start"),
        "end": span.get("end"),
        "entity_ids": [],
        "triple_ids": [],
        "supports": [],
    }


def _append_support(ref: dict[str, Any], support: dict[str, Any]) -> None:
    """按知识对象去重保存该 Span 的用途、可信级别和抽取谱系。"""
    identity = (support.get("kind"), support.get("id"))
    if any((item.get("kind"), item.get("id")) == identity for item in ref["supports"]):
        return
    ref["supports"].append(support)


def _rebuild_evidence_text(ref: dict[str, Any], block: dict[str, Any] | None) -> dict[str, Any]:
    if block is None:
        return {"text": "", "rebuildable": False, "heading_path": [], "bbox": None}
    text = str(block.get("text") or "")
    start = ref.get("start")
    end = ref.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(text):
        return {
            "text": "",
            "rebuildable": False,
            "heading_path": block.get("heading_path") or [],
            "bbox": block.get("bbox"),
        }
    return {
        "text": text[start:end],
        "rebuildable": True,
        "heading_path": block.get("heading_path") or [],
        "bbox": block.get("bbox"),
    }


def _entity_names(entities: list[dict[str, Any]], allowed_types: set[str], limit: int) -> list[str]:
    result = []
    for entity in entities:
        if str(entity.get("label") or entity.get("type") or "") not in allowed_types:
            continue
        name = str(entity.get("name") or entity.get("canonical_name") or "").strip()
        if name and name not in result:
            result.append(name)
        if len(result) >= limit:
            break
    return result


def _find_evidence(blocks: list[dict[str, Any]], terms: list[str], *, limit: int) -> list[dict[str, Any]]:
    evidence = []
    for block in blocks:
        text = str(block.get("text") or "")
        for term in terms:
            start = text.lower().find(term.lower())
            if start < 0:
                continue
            end = start + len(term)
            evidence.append(
                {
                    "block_id": str(block.get("block_id") or ""),
                    "page": block.get("page"),
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                }
            )
            if len(evidence) >= limit:
                return evidence
    return evidence


def _term_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    hits = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(0).strip()
            if value and value not in hits:
                hits.append(value)
    return hits


def _classify_military_value(
    *,
    eligible: bool,
    document_kind: str,
    triage_level: str,
    military_hits: list[str],
    potential_hits: list[str],
    transfer_hits: list[str],
    negated_military_phrases: list[str],
) -> dict[str, Any]:
    """按审计参考规范给出五级军事价值，不改变既有解析准入结论。"""
    if not eligible:
        code = "uncertain"
        reason = (
            "当前资料不是可确认的研究正文，信息不足以判断军事价值。"
            if document_kind == "insufficient_content"
            else "当前资料属于非研究材料，不据此形成军事价值结论。"
        )
    elif triage_level == "military":
        code = "military"
        reason = "正文同时具有军事/对抗信号和装备、系统、任务或能力落点。"
    elif military_hits:
        code = "uncertain"
        reason = "正文存在军事语境，但缺少足够装备、任务或能力落点，需专家复核。"
    elif negated_military_phrases:
        code = "no_military_value"
        reason = "正文明确否定军事、武器装备或作战用途，且未发现其他非否定军事证据。"
    elif len(potential_hits) >= 2 and transfer_hits:
        code = "potential"
        reason = "正文包含多个可迁移前沿技术信号，并给出了应用、迁移或跨领域线索。"
    elif potential_hits:
        code = "uncertain"
        reason = "正文包含潜在军事迁移技术信号，但尚无明确装备、任务或应用路径。"
    else:
        code = "general"
        reason = "正文具备研究价值，但当前未发现直接军事价值或明确技术迁移线索。"
    deep_extraction_recommended = eligible and code in {"military", "potential", "uncertain"}
    return {
        "military_value_code": code,
        "military_value_level": _MILITARY_VALUE_LABELS[code],
        "military_value_reason": reason,
        "deep_extraction_recommended": deep_extraction_recommended,
        "military_value_review_required": eligible and code in {"potential", "uncertain"},
    }


def _strip_negated_military_context(text: str) -> str:
    """只在资料分流评分中屏蔽明确否定的军事/装备短语。"""
    for pattern in _NEGATED_MILITARY_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text


def _stable_id(namespace: str, *parts: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, "|".join((namespace, *parts))).hex


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
