from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unicodedata import normalize

from platform_core.knowledge.graphs.graph_utils import normalize_entity_name, resolve_entity_naming

from .defense_quality_contract import (
    DEFAULT_MAX_HYPOTHESES_PER_CHUNK,
    MAX_HYPOTHESES_PER_CHUNK,
    normalize_relation_metadata,
)


@dataclass(frozen=True, slots=True)
class GraphExtractionInput:
    """一个保持原文与 Block 元数据绑定的抽取输入。"""

    text: str
    chunk_metadata: dict[str, Any] | None = None
    candidate_entities: list[dict[str, Any]] | None = None


class GraphExtractor(ABC):
    extractor_type: str

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}

    @abstractmethod
    async def extract(self, text: str, *, chunk_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        pass

    async def extract_batch(self, inputs: list[GraphExtractionInput]) -> list[dict[str, Any]]:
        """批量抽取；默认保持单条语义，支持批推理的适配器应覆盖。"""
        return [await self.extract(item.text, chunk_metadata=item.chunk_metadata) for item in inputs]

    def validate_options(self) -> None:
        return None

    async def aclose(self) -> None:
        """构建结束后释放抽取器资源。"""


# 与 knowledge_graph_entities / knowledge_graph_triples 的列长度对齐（见 storage/postgres/models_knowledge.py，
# test/unit/graphs 里有一条用例断言它们一致，避免将来漂移）。
#
# 这几个值都由模型生成、本身没有长度上限。实测出现过把整段正文当成实体名（1672 字符），
# 而 upsert_chunk_graph 是把一个分块的所有实体放进**一条多行 INSERT**：一个值超长，整批
# 被 PostgreSQL 拒绝，该分块的图谱全部丢失，且 graph_indexed 不置位——分块永远停在 pending，
# 每次重试都要再烧一次模型调用，还照样失败。
#
# 所以在落库前丢弃越界的单位（而不是抛异常：抛异常会让整个分块的抽取都失败，比丢弃更糟），
# 让损失止于它自己。
MAX_ENTITY_NAME_LENGTH = 512
MAX_ENTITY_LABEL_LENGTH = 128
MAX_RELATION_TYPE_LENGTH = 256


def _is_persistable_entity(entity: dict[str, Any]) -> bool:
    """实体须含语义字符，且名称、归一化名和标签均可安全落库。"""

    text = entity["text"]
    return (
        any(character.isalnum() for character in normalize("NFKC", text))
        and len(text) <= MAX_ENTITY_NAME_LENGTH
        and len(normalize_entity_name(text)) <= MAX_ENTITY_NAME_LENGTH
        and len(entity["label"]) <= MAX_ENTITY_LABEL_LENGTH
    )


def normalize_extraction_result(
    result: dict[str, Any],
    extractor_type: str,
    extractor_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("extraction_result 必须是对象")

    entities = result.get("entities") or []
    relations = result.get("relations") or []
    if not isinstance(entities, list) or not isinstance(relations, list):
        raise ValueError("extraction_result.entities 和 relations 必须是数组")

    normalized_entities_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    entity_refs: dict[str, dict[str, Any]] = {}
    dropped_refs: set[str] = set()
    # 按实体去重计数：同一个越界实体可能在多条关系里被反复引用，按出现次数计会虚高
    dropped_entity_keys: set[tuple[str, str]] = set()

    def add_entity(entity: Any, path: str) -> dict[str, Any] | None:
        normalized_entity = _normalize_entity(entity, path)
        if not _is_persistable_entity(normalized_entity):
            # 记下它的引用标识，引用它的关系要一并丢弃，否则会变成悬空关系
            dropped_refs.update(_entity_refs(entity, normalized_entity))
            dropped_entity_keys.add(_entity_key(normalized_entity))
            return None

        key = _entity_key(normalized_entity)
        existing = normalized_entities_by_key.get(key)
        if existing is None:
            normalized_entities_by_key[key] = normalized_entity
            existing = normalized_entity
        else:
            _merge_attributes(existing, normalized_entity)
            _merge_entity_naming(existing, normalized_entity)

        for ref in _entity_refs(entity, existing):
            entity_refs[ref] = existing
        return existing

    for index, entity in enumerate(entities):
        add_entity(entity, f"entities[{index}]")

    normalized_relations = []
    dropped_relations = 0
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            raise ValueError("relations 元素必须是对象")
        source = _normalize_relation_endpoint(
            relation.get("source"),
            entity_refs,
            add_entity,
            dropped_refs,
            result,
            f"relations[{index}].source",
        )
        target = _normalize_relation_endpoint(
            relation.get("target"),
            entity_refs,
            add_entity,
            dropped_refs,
            result,
            f"relations[{index}].target",
        )
        text = str(relation.get("text") or "").strip()
        if not text:
            raise ValueError("relations[].text 不能为空")
        label = str(relation.get("label") or "RELATED_TO").strip() or "RELATED_TO"
        if source is None or target is None or len(label) > MAX_RELATION_TYPE_LENGTH:
            dropped_relations += 1
            continue
        relation_metadata = normalize_relation_metadata(relation)
        if (
            relation_metadata["claim_level"] == "Fact"
            and not relation_metadata["evidence_quote"]
            and not relation_metadata["evidence_spans"]
        ):
            relation_metadata["claim_level"] = "Inference"
            relation_metadata["uncertainty"] = relation_metadata["uncertainty"] or "缺少可核验的原文证据短句"
        if relation_metadata["claim_level"] == "Hypothesis" and label not in {
            "COMBINES_WITH",
            "PREDICTED_LINK",
            "TRANSFERABLE_TO",
            "POTENTIAL_FOR",
        }:
            label = "PREDICTED_LINK"
        normalized_relation = {
            "source": source,
            "target": target,
            "text": text,
            "label": label,
            **relation_metadata,
        }
        model_sources = _normalize_model_sources(relation.get("model_sources"))
        if model_sources:
            normalized_relation["model_sources"] = model_sources
        normalized_relations.append(normalized_relation)

    evidence_backed_entities = {
        _entity_key(endpoint)
        for relation in normalized_relations
        if relation["claim_level"] != "Hypothesis"
        for endpoint in (relation["source"], relation["target"])
    }
    governed_relations = []
    hypothesis_count = 0
    options = extractor_options or {}
    hypotheses_enabled = options.get("enable_hypothesis_extraction", True)
    configured_hypothesis_limit = options.get("max_hypotheses_per_chunk", DEFAULT_MAX_HYPOTHESES_PER_CHUNK)
    try:
        configured_hypothesis_limit = int(configured_hypothesis_limit)
    except (TypeError, ValueError, OverflowError):
        configured_hypothesis_limit = DEFAULT_MAX_HYPOTHESES_PER_CHUNK
    hypothesis_limit = (
        max(0, min(configured_hypothesis_limit, MAX_HYPOTHESES_PER_CHUNK)) if hypotheses_enabled is True else 0
    )
    for relation in normalized_relations:
        if relation["claim_level"] != "Hypothesis":
            governed_relations.append(relation)
            continue
        endpoints_are_supported = all(
            _entity_key(endpoint) in evidence_backed_entities for endpoint in (relation["source"], relation["target"])
        )
        if not endpoints_are_supported or hypothesis_count >= hypothesis_limit:
            dropped_relations += 1
            continue
        hypothesis_count += 1
        governed_relations.append(relation)

    metadata = dict(result.get("metadata") or {})
    metadata.setdefault("extractor_type", extractor_type)
    metadata.setdefault("schema_version", 1)
    if dropped_entity_keys or dropped_relations:
        # 丢弃必须可观察：否则只表现为图谱里少了几条，无法判断是模型没抽到还是被丢掉
        metadata["dropped_entities"] = len(dropped_entity_keys)
        metadata["dropped_relations"] = dropped_relations
    return {
        "entities": list(normalized_entities_by_key.values()),
        "relations": governed_relations,
        "metadata": metadata,
    }


def verify_extraction_evidence(result: dict[str, Any], source_text: str) -> dict[str, Any]:
    """由 Span 生成事实与推断证据；无法核验的候选固定进入待复核。"""
    source = "".join(normalize("NFKC", source_text).split())
    verified = 0
    reclassified = 0
    grounded_inferences = 0
    ungrounded_inferences = 0
    for relation in result["relations"]:
        if relation["claim_level"] == "Hypothesis":
            continue
        span_quote = _quote_from_evidence_spans(relation.get("evidence_spans"), source_text)
        if span_quote:
            relation["evidence_quote"] = span_quote
        quote = "".join(normalize("NFKC", relation["evidence_quote"]).split())
        quote_is_grounded = bool(quote and quote in source)
        if relation["claim_level"] == "Inference":
            if quote_is_grounded:
                grounded_inferences += 1
                continue
            relation["confidence"] = min(relation["confidence"], 0.5)
            relation["expert_review_required"] = True
            relation["review_status"] = "pending"
            uncertainty = relation["uncertainty"]
            relation["uncertainty"] = f"{uncertainty}；推断证据未匹配当前分块，需复核".lstrip("；")
            ungrounded_inferences += 1
            continue
        if quote_is_grounded:
            verified += 1
            continue
        relation["claim_level"] = "Inference"
        relation["confidence"] = min(relation["confidence"], 0.5)
        relation["expert_review_required"] = True
        relation["review_status"] = "pending"
        uncertainty = relation["uncertainty"]
        relation["uncertainty"] = f"{uncertainty}；原文引用未匹配当前分块，需复核".lstrip("；")
        reclassified += 1
    result["metadata"]["evidence_verification"] = {
        "verified_facts": verified,
        "reclassified_facts": reclassified,
        "grounded_inferences": grounded_inferences,
        "ungrounded_inferences": ungrounded_inferences,
    }
    return result


def _quote_from_evidence_spans(spans: Any, source_text: str) -> str:
    """将模型返回的半开字符区间收敛为一段可逐字核验的原文。"""
    if not isinstance(spans, list) or not spans:
        return ""
    starts = []
    ends = []
    for span in spans:
        if not isinstance(span, dict):
            return ""
        start = span.get("start")
        end = span.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(source_text)
        ):
            return ""
        starts.append(start)
        ends.append(end)
    return source_text[min(starts) : max(ends)]


def _normalize_relation_endpoint(
    endpoint: Any,
    entity_refs: dict[str, dict[str, Any]],
    add_entity: Callable[[Any, str], dict[str, Any] | None],
    dropped_refs: set[str],
    result: dict[str, Any],
    path: str,
) -> dict[str, Any] | None:
    if isinstance(endpoint, dict):
        return add_entity(endpoint, path)

    endpoint_ref = str(endpoint or "").strip()
    if len(endpoint_ref) > MAX_ENTITY_NAME_LENGTH:
        # 引用名本身就超过实体名的列长度：不可能对应任何可落库的实体，丢弃这条关系
        return None
    if endpoint_ref in dropped_refs:
        # 引用的是一个因越界被丢弃的实体：连这条关系一起丢弃，而不是报错
        return None
    entity = entity_refs.get(endpoint_ref)
    if entity is None:
        raise ValueError(
            f"relations[].source/target 必须是实体对象，或引用 entities[].text/id，"
            f"未找到: {path}={endpoint_ref}, Result: {result}"
        )
    return entity


def _normalize_entity(entity: Any, path: str) -> dict[str, Any]:
    if not isinstance(entity, dict):
        raise ValueError(f"{path} 必须是对象")

    text = str(entity.get("text") or "").strip()
    if not text:
        raise ValueError(f"{path}.text 不能为空")

    attributes = entity.get("attributes") or []
    if not isinstance(attributes, list):
        raise ValueError(f"{path}.attributes 必须是数组")

    normalized_attributes = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            raise ValueError(f"{path}.attributes 元素必须是对象")
        attr_text = str(attribute.get("text") or "").strip()
        if not attr_text:
            continue
        normalized_attribute = {
            "text": attr_text,
            "label": str(attribute.get("label") or "Attribute").strip() or "Attribute",
        }
        confidence = attribute.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            normalized_attribute["confidence"] = max(0.0, min(float(confidence), 1.0))
        normalized_attributes.append(normalized_attribute)

    normalized = {
        "text": text,
        "label": str(entity.get("label") or "Entity").strip() or "Entity",
        "attributes": normalized_attributes,
    }
    start = entity.get("start")
    end = entity.get("end")
    if isinstance(start, int) and not isinstance(start, bool) and isinstance(end, int) and not isinstance(end, bool):
        if start >= 0 and end > start:
            normalized["start"] = start
            normalized["end"] = end
    confidence = entity.get("confidence")
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        normalized["confidence"] = max(0.0, min(float(confidence), 1.0))
    model_sources = _normalize_model_sources(entity.get("model_sources"))
    if model_sources:
        normalized["model_sources"] = model_sources
    if any(entity.get(field) for field in ("canonical_name", "raw_name", "aliases", "naming_rationale")):
        normalized.update(
            resolve_entity_naming(
                text,
                canonical_name=entity.get("canonical_name"),
                aliases=entity.get("aliases"),
                naming_rationale=entity.get("naming_rationale"),
            )
        )
    return normalized


def _entity_key(entity: dict[str, Any]) -> tuple[str, str]:
    return (normalize_entity_name(entity["text"]), entity["label"])


def _entity_refs(raw_entity: Any, entity: dict[str, Any]) -> list[str]:
    refs = [entity["text"]]
    if isinstance(raw_entity, dict):
        entity_id = str(raw_entity.get("id") or "").strip()
        if entity_id:
            refs.append(entity_id)
    return refs


def _merge_attributes(target: dict[str, Any], source: dict[str, Any]) -> None:
    known_attributes = {(attr["text"], attr["label"]) for attr in target.get("attributes") or []}
    for attribute in source.get("attributes") or []:
        attribute_key = (attribute["text"], attribute["label"])
        if attribute_key not in known_attributes:
            target.setdefault("attributes", []).append(attribute)
            known_attributes.add(attribute_key)


def _merge_entity_naming(target: dict[str, Any], source: dict[str, Any]) -> None:
    if not any(source.get(field) for field in ("canonical_name", "aliases", "naming_rationale")):
        return
    target.update(
        resolve_entity_naming(
            target["text"],
            canonical_name=source.get("canonical_name") or target.get("canonical_name"),
            aliases=[*(target.get("aliases") or []), *(source.get("aliases") or [])],
            naming_rationale=source.get("naming_rationale") or target.get("naming_rationale"),
        )
    )


def _normalize_model_sources(value: Any) -> list[str]:
    """收敛多模型来源标记，供候选审核和运行误差分析。"""
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip()[:128] for item in value if str(item or "").strip()))[:16]
