"""平台与 LightRAG 文档级关系增强服务共用的稳定契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DocumentREBlock(BaseModel):
    """保留原始字符偏移的结构化文档 Block。"""

    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    block_index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    base_char_offset: int = Field(default=0, ge=0)
    heading_path: list[str] = Field(default_factory=list)


class DocumentREMention(BaseModel):
    """已对齐到 canonical entity 的原文 mention。"""

    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_span_order(self):
        if self.end <= self.start:
            raise ValueError("mention end 必须大于 start")
        return self


class DocumentREEntity(BaseModel):
    """实体对齐完成后的标准实体簇。"""

    entity_id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=128)
    canonical_name: str = Field(min_length=1, max_length=512)
    mentions: list[DocumentREMention] = Field(min_length=1)


class DocumentRERelationType(BaseModel):
    """文档级模型可输出的受约束关系类型。"""

    code: str = Field(min_length=1, max_length=256)
    name_zh: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=1000)
    head_types: list[str] = Field(min_length=1)
    tail_types: list[str] = Field(min_length=1)
    directed: bool = True
    allow_self: bool = False
    hypothesis_only: bool = False


class DocumentREOptions(BaseModel):
    """文档级推理限制；模型硬上限由 sidecar 再次校验。"""

    relation_threshold: float | None = Field(default=None, ge=0, le=1)
    max_entities: int = Field(default=42, ge=2, le=512)
    max_blocks: int = Field(default=128, ge=1, le=1024)
    max_chars: int = Field(default=16_000, ge=512, le=1_000_000)
    max_relations: int = Field(default=12, ge=1, le=64)
    max_candidate_pairs: int = Field(default=256, ge=1, le=2048)


class DocumentRERequest(BaseModel):
    """单个不可变文档版本的文档级关系增强请求。"""

    request_id: str = Field(min_length=1, max_length=128)
    pipeline_revision: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=256)
    ontology_version: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: int = Field(ge=1)
    blocks: list[DocumentREBlock] = Field(min_length=1)
    entities: list[DocumentREEntity] = Field(min_length=2)
    relation_types: list[DocumentRERelationType] = Field(min_length=1)
    options: DocumentREOptions = Field(default_factory=DocumentREOptions)

    @model_validator(mode="after")
    def validate_document_graph(self):
        if len(self.blocks) > self.options.max_blocks:
            raise ValueError("文档 Block 数超过请求上限")
        if len(self.entities) > self.options.max_entities:
            raise ValueError("文档 canonical entity 数超过请求上限")
        if sum(len(block.text) for block in self.blocks) > self.options.max_chars:
            raise ValueError("文档字符数超过请求上限")

        block_by_id = {block.block_id: block for block in self.blocks}
        if len(block_by_id) != len(self.blocks):
            raise ValueError("文档 block_id 不能重复")
        entity_ids = {entity.entity_id for entity in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("文档 entity_id 不能重复")
        for entity in self.entities:
            for mention in entity.mentions:
                block = block_by_id.get(mention.block_id)
                if block is None:
                    raise ValueError(f"实体 {entity.entity_id} 引用了不存在的 Block")
                if mention.end > len(block.text) or block.text[mention.start : mention.end] != mention.text:
                    raise ValueError(f"实体 {entity.entity_id} 的 mention Span 无法回切原文")
        return self


class DocumentREEvidenceSpan(BaseModel):
    """可回切到原始 Block 的文档级关系证据。"""

    block_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span_order(self):
        if self.end <= self.start:
            raise ValueError("证据 end 必须大于 start")
        return self


class DocumentRERelation(BaseModel):
    """以 canonical entity ID 表达的跨 Block 关系候选。"""

    type: str = Field(min_length=1, max_length=256)
    source_entity_id: str = Field(min_length=1, max_length=64)
    target_entity_id: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)
    confidence_kind: Literal["probability", "hard_label"] = "probability"
    evidence_spans: list[DocumentREEvidenceSpan] = Field(min_length=1)
    applicable_conditions: list[str] = Field(default_factory=list, max_length=20)


class DocumentRERuntime(BaseModel):
    """文档级模型运行谱系。"""

    backend: Literal["llm", "test"]
    adapter: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=256)
    ontology_version: str = Field(min_length=1, max_length=128)
    latency_ms: int = Field(ge=0)
    device: str = Field(default="unknown", max_length=64)
    candidate_count: int | None = Field(default=None, ge=0)
    accepted_count: int | None = Field(default=None, ge=0)
    truncated_count: int = Field(default=0, ge=0)


class DocumentREResponse(BaseModel):
    """文档级关系增强响应。"""

    request_id: str
    document_id: str
    document_version: int = Field(ge=1)
    relations: list[DocumentRERelation] = Field(default_factory=list)
    runtime: DocumentRERuntime

    def validate_against(self, request: DocumentRERequest) -> DocumentREResponse:
        """校验服务返回只引用请求中的端点、关系和可回切证据。"""
        if self.request_id != request.request_id:
            raise ValueError("文档级关系服务返回了不匹配的 request_id")
        if self.document_id != request.document_id or self.document_version != request.document_version:
            raise ValueError("文档级关系服务返回了不匹配的文档版本")
        if self.runtime.model_version != request.model_version:
            raise ValueError("文档级关系服务返回了不匹配的模型版本")
        if self.runtime.ontology_version != request.ontology_version:
            raise ValueError("文档级关系服务返回了不匹配的本体版本")
        if len(self.relations) > request.options.max_relations:
            raise ValueError("文档级关系数量超过请求上限")

        block_by_id = {block.block_id: block for block in request.blocks}
        entity_by_id = {entity.entity_id: entity for entity in request.entities}
        relation_type_by_code = {item.code: item for item in request.relation_types}
        for relation in self.relations:
            source = entity_by_id.get(relation.source_entity_id)
            target = entity_by_id.get(relation.target_entity_id)
            relation_type = relation_type_by_code.get(relation.type)
            if source is None or target is None:
                raise ValueError("文档级关系引用了请求外的 canonical entity")
            if relation_type is None:
                raise ValueError("文档级关系返回了本体外关系类型")
            if relation.source_entity_id == relation.target_entity_id and not relation_type.allow_self:
                raise ValueError("文档级关系违反本体自关系约束")
            if source.type not in relation_type.head_types or target.type not in relation_type.tail_types:
                raise ValueError("文档级关系违反本体端点类型约束")
            for span in relation.evidence_spans:
                block = block_by_id.get(span.block_id)
                if block is None or span.end > len(block.text):
                    raise ValueError("文档级关系证据 Span 无法回切原文")
        return self
