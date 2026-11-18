"""图谱构建相关的纯函数工具集。

将数据变换逻辑从 MilvusGraphService 中抽离，
使 service 类专注于 I/O 和业务编排。
"""

from __future__ import annotations

import re
from typing import Any
from unicodedata import normalize

from platform_core.utils import hashstr

_CJK_INTERNAL_LAYOUT_GAP = re.compile(r"(?<=[\u3400-\u9fff])[\s\u00a0\u3000]+(?=[\u3400-\u9fff])")
_LATIN_LINE_WRAP_HYPHEN = re.compile(r"(?<=[A-Za-z])-[ \t\r]*\n[ \t]*(?=[A-Za-z])")
_PAPER_STYLE_NAME_PREFIX = re.compile(
    r"^(?:本文|本研究|该文|文中)(?:所)?(?:提出|研究|采用|设计|构建|开发|实现|介绍)(?:的)?"
)
_DAMAGED_NAME_TOKEN = re.compile(r"(?:@[A-Z]{2,}|\ufffd|[!\"#$%&'()*+,./:;<=>?\\^_`{|}~]{4,})")
_GENERIC_ENTITY_NAMES = {
    "系统",
    "平台",
    "方法",
    "模型",
    "技术",
    "能力",
    "应用",
    "结果",
    "验证",
    "数据集",
    "方案",
    "装置",
    "设备",
    "system",
    "platform",
    "method",
    "model",
    "technology",
    "capability",
    "application",
    "result",
    "validation",
    "dataset",
}
MAX_CANONICAL_ENTITY_NAME_LENGTH = 128
MAX_ENTITY_ALIASES = 16


def canonical_entity_display_name(text: str) -> str:
    """生成实体主数据展示名；修复可确定的中英文排版断词。"""

    normalized = normalize("NFKC", str(text or "").strip())
    normalized = _LATIN_LINE_WRAP_HYPHEN.sub("", normalized)
    return _CJK_INTERNAL_LAYOUT_GAP.sub("", normalized)


def resolve_entity_naming(
    mention_text: str,
    *,
    canonical_name: Any = None,
    aliases: Any = None,
    naming_rationale: Any = None,
) -> dict[str, Any]:
    """校验 LLM 规范名，同时保留可回切的原始 mention 与有界别名。"""

    raw_name = str(mention_text or "")
    fallback = canonical_entity_display_name(raw_name)
    candidate = canonical_entity_display_name(str(canonical_name or ""))
    candidate = _PAPER_STYLE_NAME_PREFIX.sub("", candidate).strip(" \t\r\n，,：:；;")
    if not _valid_canonical_entity_name(candidate):
        candidate = fallback

    normalized_canonical = normalize_entity_name(candidate)
    alias_values = aliases if isinstance(aliases, list) else []
    bounded_aliases: list[str] = []
    seen_aliases: set[str] = {normalized_canonical}
    for value in [*alias_values, raw_name]:
        alias = canonical_entity_display_name(str(value or ""))
        normalized_alias = normalize_entity_name(alias)
        if (
            not alias
            or len(alias) > 512
            or not any(character.isalnum() for character in alias)
            or not normalized_alias
            or normalized_alias in seen_aliases
        ):
            continue
        seen_aliases.add(normalized_alias)
        bounded_aliases.append(alias)
        if len(bounded_aliases) >= MAX_ENTITY_ALIASES:
            break

    rationale = " ".join(str(naming_rationale or "").split())[:1000]
    return {
        "canonical_name": candidate,
        "raw_name": raw_name,
        "aliases": bounded_aliases,
        "naming_rationale": rationale,
    }


def _valid_canonical_entity_name(value: str) -> bool:
    normalized = normalize_entity_name(value)
    if not 2 <= len(value) <= MAX_CANONICAL_ENTITY_NAME_LENGTH:
        return False
    if not any(character.isalnum() for character in value):
        return False
    if normalized in _GENERIC_ENTITY_NAMES:
        return False
    if value.startswith(("一种面向", "该方法", "该系统", "上述方法", "上述系统")):
        return False
    return _DAMAGED_NAME_TOKEN.search(value) is None


def normalize_entity_name(text: str) -> str:
    """统一实体身份键，同时消除汉字术语内部的分页空白。"""

    return " ".join(canonical_entity_display_name(text).casefold().split())


def compute_entity_id(kb_id: str, normalized_name: str, label: str) -> str:
    return hashstr(f"{kb_id}:{normalized_name}:{label}", length=32)


def compute_triple_id(
    kb_id: str,
    source_normalized_name: str,
    source_label: str,
    relation_type: str,
    target_normalized_name: str,
    target_label: str,
) -> str:
    return hashstr(
        f"{kb_id}:{source_normalized_name}:{source_label}:{relation_type}:{target_normalized_name}:{target_label}",
        length=32,
    )


def graph_entity_collection_name(kb_id: str) -> str:
    return f"{kb_id}_entity"


def graph_triple_collection_name(kb_id: str) -> str:
    return f"{kb_id}_triple"


def build_graph_payload(normalized_result: dict[str, Any]) -> dict[str, Any]:
    """将抽取器产出的标准化结果转换为 Neo4j 写入所需的图结构。

    返回的 entities 已完成去重合并：同名同 label 的实体只保留一份，
    属性（attributes）取并集。
    """
    # 延迟导入避免 extractors.base -> graph_utils 初始化时形成循环依赖。
    from platform_core.knowledge.graphs.extractors.defense_quality_contract import RELATION_METADATA_FIELDS

    entities: list[dict[str, Any]] = []
    entity_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    def add_entity(entity: dict[str, Any]) -> str:
        key = (normalize_entity_name(entity["text"]), entity.get("label") or "Entity")
        existing = entity_by_key.get(key)
        if existing is not None:
            known_attributes = {(attr["text"], attr["label"]) for attr in existing.get("attributes") or []}
            for attribute in entity.get("attributes") or []:
                attribute_key = (attribute["text"], attribute["label"])
                if attribute_key not in known_attributes:
                    existing.setdefault("attributes", []).append(attribute)
                    known_attributes.add(attribute_key)
            return existing["id"]

        graph_entity = {
            "id": f"e{len(entities) + 1}",
            "text": entity["text"],
            "label": entity.get("label") or "Entity",
            "attributes": list(entity.get("attributes") or []),
        }
        for field in (
            "start",
            "end",
            "confidence",
            "model_sources",
            "review_status",
            "acceptance_reason",
            "canonical_name",
            "raw_name",
            "aliases",
            "naming_rationale",
        ):
            if field in entity:
                graph_entity[field] = entity[field]
        entities.append(graph_entity)
        entity_by_key[key] = graph_entity
        return graph_entity["id"]

    for entity in normalized_result["entities"]:
        add_entity(entity)

    relations = []
    for relation in normalized_result["relations"]:
        graph_relation = {
            "source": add_entity(relation["source"]),
            "target": add_entity(relation["target"]),
            "text": relation["text"],
            "label": relation.get("label") or "RELATED_TO",
        }
        graph_relation.update({field: relation.get(field) for field in RELATION_METADATA_FIELDS})
        if relation.get("secondary_review"):
            graph_relation["secondary_review"] = dict(relation["secondary_review"])
        if relation.get("model_sources"):
            graph_relation["model_sources"] = list(relation["model_sources"])
        relations.append(graph_relation)

    return {"entities": entities, "relations": relations, "metadata": normalized_result["metadata"]}


# ─── Cypher 模板 ────────────────────────────────────────────────
# 将大段 Cypher 字符串集中管理，提升 write_chunk_graph 的可读性。


def cypher_merge_chunk(db_label: str) -> str:
    """MERGE Chunk 节点并写入元数据。"""
    return f"""
    MERGE (c:Chunk:MilvusKB:`{db_label}` {{chunk_id: $chunk_id}})
    SET c.file_id = $file_id,
        c.kb_id = $kb_id,
        c.chunk_index = $chunk_index,
        c.content_preview = $content_preview,
        c.start_char_pos = $start_char_pos,
        c.end_char_pos = $end_char_pos,
        c.document_version = $document_version,
        c.page_number = $page_number,
        c.block_type = $block_type,
        c.heading_path = $heading_path,
        c.bbox = $bbox,
        c.parser_name = $parser_name,
        c.parser_version = $parser_version
    """


def cypher_merge_entity_mention(db_label: str) -> str:
    """MERGE Entity 节点；仅对真实 mention 创建 Chunk → Entity 边。"""
    return f"""
    MATCH (c:Chunk:MilvusKB:`{db_label}` {{chunk_id: $chunk_id}})
    MERGE (e:Entity:MilvusKB:`{db_label}` {{
        entity_id: $entity_id
    }})
    SET e.kb_id = $kb_id,
        e.normalized_name = $normalized_name,
        e.label = $entity_label,
        e.name = $name,
        e.attributes = $attributes,
        e.lifecycle_status = $lifecycle_status,
        e.superseded_by_entity_id = $superseded_by_entity_id,
        e.entity_version = $entity_version
    FOREACH (_ IN CASE WHEN $has_mention THEN [1] ELSE [] END |
        MERGE (c)-[m:MENTIONS {{chunk_id: $chunk_id, file_id: $file_id, kb_id: $kb_id}}]->(e)
        SET m.review_status = $review_status,
            m.confidence = $confidence,
            m.start_char = $start_char,
            m.end_char = $end_char,
            m.model_version = $model_version,
            m.ontology_version = $ontology_version
    )
    """


def cypher_merge_relation(db_label: str) -> str:
    """MERGE 两个 Entity 之间的 RELATION 边。"""
    return f"""
    MATCH (source:Entity:MilvusKB:`{db_label}` {{entity_id: $source_entity_id}})
    MATCH (target:Entity:MilvusKB:`{db_label}` {{entity_id: $target_entity_id}})
    MERGE (source)-[r:RELATION {{
        triple_id: $triple_id,
        chunk_id: $chunk_id
    }}]->(target)
    SET r.kb_id = $kb_id,
        r.source_name = $source_name,
        r.target_name = $target_name,
        r.type = $relation_type,
        r.text = $text,
        r.file_id = $file_id,
        r.extractor_type = $extractor_type,
        r.claim_level = $claim_level,
        r.confidence = $confidence,
        r.evidence_quote = $evidence_quote,
        r.reasoning_basis = $reasoning_basis,
        r.applicable_conditions = $applicable_conditions,
        r.secondary_review_verdict = $secondary_review_verdict,
        r.secondary_review_basis = $secondary_review_basis,
        r.secondary_review_revision = $secondary_review_revision,
        r.military_value_dimensions = $military_value_dimensions,
        r.expected_capability_gain = $expected_capability_gain,
        r.application_direction = $application_direction,
        r.uncertainty = $uncertainty,
        r.expert_review_required = $expert_review_required,
        r.review_status = $review_status,
        r.model_version = $model_version,
        r.ontology_version = $ontology_version,
        r.pipeline_revision = $pipeline_revision,
        r.lifecycle_status = $lifecycle_status,
        r.superseded_by_triple_id = $superseded_by_triple_id,
        r.relation_version = $relation_version
    """
