"""平台统一金标 JSONL 契约。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GoldBlock(BaseModel):
    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class GoldEvidenceSpan(BaseModel):
    block_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("证据 end 必须大于 start")
        return self


class GoldAnnotationProvenance(BaseModel):
    review_mode: Literal["double_human", "dual_model_expert"] = "double_human"
    annotator_ids: list[str] = Field(default_factory=list, max_length=10)
    model_prelabel_ids: list[str] = Field(default_factory=list, max_length=10)
    arbitrator_id: str | None = Field(default=None, max_length=128)
    adjudicated: bool = False
    expert_review_scope: Literal["differences_only", "all_candidates"] = "differences_only"
    guideline_version: str = Field(default="", max_length=128)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_annotators(self):
        normalized = [item.strip() for item in self.annotator_ids if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("annotator_ids 不能重复")
        self.annotator_ids = normalized
        model_ids = [item.strip() for item in self.model_prelabel_ids if item.strip()]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("model_prelabel_ids 不能重复")
        self.model_prelabel_ids = model_ids
        return self


class GoldEntity(BaseModel):
    entity_id: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    canonical_entity_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("实体 end 必须大于 start")
        return self


class GoldRelation(BaseModel):
    relation_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=256)
    source_entity_id: str = Field(min_length=1, max_length=128)
    target_entity_id: str = Field(min_length=1, max_length=128)
    evidence_block_ids: list[str] = Field(default_factory=list)
    evidence_spans: list[GoldEvidenceSpan] = Field(default_factory=list)
    applicable_conditions: list[str] = Field(default_factory=list)
    claim_level: Literal["Fact", "Inference", "Hypothesis"] = "Fact"


class GoldAttribute(BaseModel):
    """实体与原文属性值之间的可定位属性监督。"""

    attribute_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=256)
    block_id: str = Field(min_length=1, max_length=128)
    value_text: str = Field(min_length=1, max_length=512)
    value_start: int = Field(ge=0)
    value_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self):
        if self.value_end <= self.value_start:
            raise ValueError("属性值 end 必须大于 start")
        return self


class GoldEventArgument(BaseModel):
    """事件论元及其原文 Span。"""

    role: str = Field(min_length=1, max_length=128)
    entity_id: str | None = Field(default=None, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("事件论元 end 必须大于 start")
        return self


class GoldEvent(BaseModel):
    """带触发词和论元 Span 的军事技术事件。"""

    event_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=256)
    trigger_block_id: str = Field(min_length=1, max_length=128)
    trigger_text: str = Field(min_length=1, max_length=128)
    trigger_start: int = Field(ge=0)
    trigger_end: int = Field(gt=0)
    arguments: list[GoldEventArgument] = Field(default_factory=list)
    evidence_spans: list[GoldEvidenceSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_span(self):
        if self.trigger_end <= self.trigger_start:
            raise ValueError("事件触发词 end 必须大于 start")
        return self


class GoldDocument(BaseModel):
    document_id: str = Field(min_length=1, max_length=128)
    title: str = ""
    split: Literal["train", "dev", "test"]
    language: Literal["zh", "en", "mixed", "unknown"] = "unknown"
    source_type: Literal["paper", "patent", "other", "unknown"] = "unknown"
    domain: str = Field(default="", max_length=256)
    source_version: str = Field(default="", max_length=128)
    annotation: GoldAnnotationProvenance | None = None
    blocks: list[GoldBlock] = Field(min_length=1)
    entities: list[GoldEntity] = Field(default_factory=list)
    relations: list[GoldRelation] = Field(default_factory=list)
    attributes: list[GoldAttribute] = Field(default_factory=list)
    events: list[GoldEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references_and_original_text(self):
        block_by_id = {block.block_id: block for block in self.blocks}
        if len(block_by_id) != len(self.blocks):
            raise ValueError("同一文档 block_id 必须唯一")
        entity_by_id = {entity.entity_id: entity for entity in self.entities}
        if len(entity_by_id) != len(self.entities):
            raise ValueError("同一文档 entity_id 必须唯一")

        for entity in self.entities:
            block = block_by_id.get(entity.block_id)
            if block is None:
                raise ValueError(f"实体 {entity.entity_id} 引用了不存在的 Block")
            if entity.end > len(block.text) or block.text[entity.start : entity.end] != entity.text:
                raise ValueError(f"实体 {entity.entity_id} 的 Span 无法逐字回切原文")
        for relation in self.relations:
            if relation.source_entity_id not in entity_by_id or relation.target_entity_id not in entity_by_id:
                raise ValueError(f"关系 {relation.relation_id} 引用了不存在的实体")
            if any(block_id not in block_by_id for block_id in relation.evidence_block_ids):
                raise ValueError(f"关系 {relation.relation_id} 引用了不存在的证据 Block")
            for evidence in relation.evidence_spans:
                block = block_by_id.get(evidence.block_id)
                if block is None:
                    raise ValueError(f"关系 {relation.relation_id} 引用了不存在的证据 Span Block")
                if evidence.end > len(block.text) or block.text[evidence.start : evidence.end] != evidence.text:
                    raise ValueError(f"关系 {relation.relation_id} 的证据 Span 无法逐字回切原文")
        attribute_ids: set[str] = set()
        for attribute in self.attributes:
            if attribute.attribute_id in attribute_ids:
                raise ValueError(f"属性 ID 重复: {attribute.attribute_id}")
            attribute_ids.add(attribute.attribute_id)
            if attribute.entity_id not in entity_by_id:
                raise ValueError(f"属性 {attribute.attribute_id} 引用了不存在的实体")
            block = block_by_id.get(attribute.block_id)
            if block is None:
                raise ValueError(f"属性 {attribute.attribute_id} 引用了不存在的 Block")
            if (
                attribute.value_end > len(block.text)
                or block.text[attribute.value_start : attribute.value_end] != attribute.value_text
            ):
                raise ValueError(f"属性 {attribute.attribute_id} 的值 Span 无法逐字回切原文")
        event_ids: set[str] = set()
        for event in self.events:
            if event.event_id in event_ids:
                raise ValueError(f"事件 ID 重复: {event.event_id}")
            event_ids.add(event.event_id)
            block = block_by_id.get(event.trigger_block_id)
            if block is None:
                raise ValueError(f"事件 {event.event_id} 引用了不存在的触发词 Block")
            if (
                event.trigger_end > len(block.text)
                or block.text[event.trigger_start : event.trigger_end] != event.trigger_text
            ):
                raise ValueError(f"事件 {event.event_id} 的触发词 Span 无法逐字回切原文")
            for argument in event.arguments:
                if argument.entity_id is not None and argument.entity_id not in entity_by_id:
                    raise ValueError(f"事件 {event.event_id} 的论元引用了不存在的实体")
                argument_block = block_by_id.get(argument.block_id)
                if argument_block is None:
                    raise ValueError(f"事件 {event.event_id} 的论元引用了不存在的 Block")
                if argument.end > len(argument_block.text) or (
                    argument_block.text[argument.start : argument.end] != argument.text
                ):
                    raise ValueError(f"事件 {event.event_id} 的论元 Span 无法逐字回切原文")
            for evidence in event.evidence_spans:
                evidence_block = block_by_id.get(evidence.block_id)
                if evidence_block is None:
                    raise ValueError(f"事件 {event.event_id} 引用了不存在的证据 Block")
                if evidence.end > len(evidence_block.text) or (
                    evidence_block.text[evidence.start : evidence.end] != evidence.text
                ):
                    raise ValueError(f"事件 {event.event_id} 的证据 Span 无法逐字回切原文")
        return self


def load_gold_jsonl(path: str | Path) -> list[GoldDocument]:
    """加载并校验统一金标 JSONL，禁止同一文档重复进入不同集合。"""
    documents = []
    document_splits: dict[str, str] = {}
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                document = GoldDocument.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"金标 JSONL 第 {line_number} 行无效: {exc}") from exc
            existing = document_splits.get(document.document_id)
            if existing is not None:
                raise ValueError(
                    f"文档 {document.document_id} 重复出现，已有 split={existing}，当前 split={document.split}"
                )
            document_splits[document.document_id] = document.split
            documents.append(document)
    if not documents:
        raise ValueError("金标 JSONL 不能为空")
    return documents
