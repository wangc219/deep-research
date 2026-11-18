"""平台与文档级实体漏抽增强器共用的稳定契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DocumentEntityBlock(BaseModel):
    """保留原始字符偏移的结构化文档 Block。"""

    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    block_index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    base_char_offset: int = Field(default=0, ge=0)
    heading_path: list[str] = Field(default_factory=list)


class DocumentEntityMention(BaseModel):
    """当前文档中已经写入权威库的实体 mention。"""

    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span_order(self):
        if self.end <= self.start:
            raise ValueError("mention end 必须大于 start")
        return self


class DocumentKnownEntity(BaseModel):
    """文档级补抽时只读的 canonical entity 摘要。"""

    entity_id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=128)
    canonical_name: str = Field(min_length=1, max_length=512)
    mentions: list[DocumentEntityMention] = Field(default_factory=list)


class DocumentEntityType(BaseModel):
    """允许文档增强器返回的版本化实体类型。"""

    code: str = Field(min_length=1, max_length=128)
    name_zh: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)


class DocumentEntityOptions(BaseModel):
    """文档级实体补抽的硬预算。"""

    max_blocks: int = Field(default=48, ge=1, le=256)
    max_chars: int = Field(default=12_000, ge=512, le=200_000)
    max_candidates: int = Field(default=100, ge=1, le=1000)


class DocumentEntityRequest(BaseModel):
    """单个不可变文档窗口的实体漏抽请求。"""

    request_id: str = Field(min_length=1, max_length=128)
    stage_revision: str = Field(min_length=1, max_length=128)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pipeline_revision: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=256)
    ontology_version: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: int = Field(ge=1)
    blocks: list[DocumentEntityBlock] = Field(min_length=1)
    known_entities: list[DocumentKnownEntity] = Field(default_factory=list)
    entity_types: list[DocumentEntityType] = Field(min_length=1)
    options: DocumentEntityOptions = Field(default_factory=DocumentEntityOptions)

    @model_validator(mode="after")
    def validate_document_window(self):
        if len(self.blocks) > self.options.max_blocks:
            raise ValueError("文档实体补抽 Block 数超过请求上限")
        if sum(len(block.text) for block in self.blocks) > self.options.max_chars:
            raise ValueError("文档实体补抽字符数超过请求上限")
        block_by_id = {block.block_id: block for block in self.blocks}
        if len(block_by_id) != len(self.blocks):
            raise ValueError("文档实体补抽 block_id 不能重复")
        if len({item.code for item in self.entity_types}) != len(self.entity_types):
            raise ValueError("文档实体补抽实体类型不能重复")
        for entity in self.known_entities:
            for mention in entity.mentions:
                block = block_by_id.get(mention.block_id)
                if block is None:
                    raise ValueError("已知实体引用了请求外 Block")
                if mention.end > len(block.text) or block.text[mention.start : mention.end] != mention.text:
                    raise ValueError("已知实体 mention Span 无法回切原文")
        return self


class DocumentEntityCandidate(BaseModel):
    """表达可回切 mention 与待对齐规范名，不授予模型创建稳定实体 ID 的权限。"""

    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    type: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    attributes: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    canonical_name: str | None = Field(default=None, min_length=2, max_length=512)
    raw_name: str | None = Field(default=None, min_length=1, max_length=512)
    aliases: list[str] = Field(default_factory=list, max_length=16)
    naming_rationale: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_span_order(self):
        if self.end <= self.start:
            raise ValueError("候选实体 end 必须大于 start")
        if self.raw_name is not None and self.raw_name != self.text:
            raise ValueError("候选实体 raw_name 必须等于原文 text")
        return self


class DocumentEntityRuntime(BaseModel):
    """文档实体增强的运行谱系。"""

    backend: Literal["llm", "test"]
    adapter: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=256)
    ontology_version: str = Field(min_length=1, max_length=128)
    latency_ms: int = Field(ge=0)
    device: str = Field(default="unknown", max_length=64)


class DocumentOCRRepairProposal(BaseModel):
    """只读的 OCR 修复建议；永不替换权威原文或作为实体证据。"""

    block_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    original_text: str = Field(min_length=1, max_length=512)
    suggested_text: str = Field(min_length=1, max_length=512)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_span_order(self):
        if self.end <= self.start:
            raise ValueError("OCR 修复建议 end 必须大于 start")
        return self


class DocumentEntityResponse(BaseModel):
    """经契约校验后仍须进入 canonical 对齐和人工审核的候选。"""

    request_id: str
    document_id: str
    document_version: int = Field(ge=1)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entities: list[DocumentEntityCandidate] = Field(default_factory=list)
    repair_proposals: list[DocumentOCRRepairProposal] = Field(default_factory=list, max_length=200)
    normalization: dict[str, Any] = Field(default_factory=dict)
    runtime: DocumentEntityRuntime

    def validate_against(self, request: DocumentEntityRequest) -> DocumentEntityResponse:
        """阻止模型返回请求外 Block、本体类型或不可回切 Span。"""
        if self.request_id != request.request_id:
            raise ValueError("文档实体增强返回了不匹配的 request_id")
        if self.document_id != request.document_id or self.document_version != request.document_version:
            raise ValueError("文档实体增强返回了不匹配的文档版本")
        if self.input_hash != request.input_hash:
            raise ValueError("文档实体增强返回了不匹配的 input_hash")
        if self.runtime.model_version != request.model_version:
            raise ValueError("文档实体增强返回了不匹配的模型版本")
        if self.runtime.ontology_version != request.ontology_version:
            raise ValueError("文档实体增强返回了不匹配的本体版本")

        block_by_id = {block.block_id: block for block in request.blocks}
        allowed_types = {item.code for item in request.entity_types}
        if len(self.entities) > request.options.max_candidates:
            raise ValueError("文档实体增强候选数超过请求上限")
        for entity in self.entities:
            block = block_by_id.get(entity.block_id)
            if block is None:
                raise ValueError("文档实体增强引用了请求外 Block")
            if entity.type not in allowed_types:
                raise ValueError("文档实体增强返回了本体外实体类型")
            if entity.end > len(block.text) or block.text[entity.start : entity.end] != entity.text:
                raise ValueError("文档实体增强 Span 无法回切原文")
        for proposal in self.repair_proposals:
            block = block_by_id.get(proposal.block_id)
            if block is None:
                raise ValueError("OCR 修复建议引用了请求外 Block")
            if proposal.end > len(block.text) or block.text[proposal.start : proposal.end] != proposal.original_text:
                raise ValueError("OCR 修复建议 Span 无法回切原文")
        return self
