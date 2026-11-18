"""双人独立标注、差异比较与专家仲裁领域契约。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .gold_contract import GoldDocument, GoldEntity, GoldRelation
from .pilot_coverage import normalize_acceptance_languages

PILOT_SPLIT_COUNTS = {"train": 210, "dev": 30, "test": 60}
DEFAULT_GUIDELINE_VERSION = "defense-kg-annotation-v1"


class AnnotationAssignmentSpec(BaseModel):
    """一篇文档的两名独立标注员和第三名仲裁专家。"""

    document_id: str = Field(min_length=1, max_length=64)
    document_version: int = Field(default=1, ge=1)
    split: Literal["train", "dev", "test"]
    annotator_ids: list[str] = Field(min_length=2, max_length=2)
    arbitrator_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_roles(self):
        annotators = [str(item).strip() for item in self.annotator_ids]
        if any(not item for item in annotators) or len(set(annotators)) != 2:
            raise ValueError("每篇文档必须分配两名不同的标注员")
        arbitrator_id = self.arbitrator_id.strip()
        if arbitrator_id in annotators:
            raise ValueError("仲裁专家必须与两名标注员不同")
        self.annotator_ids = annotators
        self.arbitrator_id = arbitrator_id
        return self


class AnnotationCampaignSpec(BaseModel):
    """版本固定、按文档切分的标注活动定义。"""

    name: str = Field(min_length=1, max_length=255)
    guideline_version: str = Field(default=DEFAULT_GUIDELINE_VERSION, min_length=1, max_length=128)
    ontology_version: str = Field(min_length=1, max_length=128)
    pilot_mode: bool = True
    acceptance_languages: list[str] = Field(default_factory=lambda: ["en", "zh"], min_length=1, max_length=16)
    assignments: list[AnnotationAssignmentSpec] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_documents_and_splits(self):
        self.acceptance_languages = sorted(normalize_acceptance_languages(self.acceptance_languages))
        document_ids = [item.document_id for item in self.assignments]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("同一标注活动不能重复分配同一文档")
        if self.pilot_mode:
            split_counts = Counter(item.split for item in self.assignments)
            actual = {split: split_counts.get(split, 0) for split in PILOT_SPLIT_COUNTS}
            if actual != PILOT_SPLIT_COUNTS:
                raise ValueError(f"Pilot 标注活动必须按 210/30/60 切分，实际为 {actual}")
        return self


def compare_independent_annotations(left: GoldDocument, right: GoldDocument) -> dict[str, Any]:
    """忽略临时 ID，按严格实体、关系方向、证据和条件生成确定性差异。"""
    if left.document_id != right.document_id:
        raise ValueError("只能比较同一文档的两份独立标注")
    if left.split != right.split:
        raise ValueError("同一文档的两份标注 split 不一致")

    left_entities = {_entity_key(entity): _entity_payload(entity) for entity in left.entities}
    right_entities = {_entity_key(entity): _entity_payload(entity) for entity in right.entities}
    left_relations = _relation_payloads(left)
    right_relations = _relation_payloads(right)

    entity_diff = _compare_payload_maps(left_entities, right_entities)
    relation_diff = _compare_payload_maps(left_relations, right_relations)
    disagreement_count = len(entity_diff["only_left"]) + len(entity_diff["only_right"])
    disagreement_count += len(relation_diff["only_left"]) + len(relation_diff["only_right"])
    return {
        "contract_version": "defense-kg-annotation-diff-v1",
        "document_id": left.document_id,
        "entities": entity_diff,
        "relations": relation_diff,
        "disagreement_count": disagreement_count,
        "agreement": disagreement_count == 0,
    }


def _entity_key(entity: GoldEntity) -> tuple[Any, ...]:
    return (
        entity.block_id,
        entity.start,
        entity.end,
        entity.type,
        entity.canonical_entity_id or "",
    )


def _entity_payload(entity: GoldEntity) -> dict[str, Any]:
    return {
        "block_id": entity.block_id,
        "start": entity.start,
        "end": entity.end,
        "type": entity.type,
        "text": entity.text,
        "canonical_entity_id": entity.canonical_entity_id,
    }


def _relation_payloads(document: GoldDocument) -> dict[tuple[Any, ...], dict[str, Any]]:
    entity_by_id = {entity.entity_id: entity for entity in document.entities}
    payloads = {}
    for relation in document.relations:
        key = _relation_key(relation, entity_by_id)
        payloads[key] = {
            "type": relation.type,
            "source": _entity_payload(entity_by_id[relation.source_entity_id]),
            "target": _entity_payload(entity_by_id[relation.target_entity_id]),
            "claim_level": relation.claim_level,
            "evidence_block_ids": sorted(set(relation.evidence_block_ids)),
            "evidence_spans": sorted(
                (
                    {
                        "block_id": span.block_id,
                        "start": span.start,
                        "end": span.end,
                        "text": span.text,
                    }
                    for span in relation.evidence_spans
                ),
                key=lambda item: (item["block_id"], item["start"], item["end"]),
            ),
            "applicable_conditions": sorted(set(relation.applicable_conditions)),
        }
    return payloads


def _relation_key(relation: GoldRelation, entity_by_id: dict[str, GoldEntity]) -> tuple[Any, ...]:
    evidence = tuple(sorted((span.block_id, span.start, span.end, span.text) for span in relation.evidence_spans))
    return (
        relation.type,
        _entity_key(entity_by_id[relation.source_entity_id]),
        _entity_key(entity_by_id[relation.target_entity_id]),
        relation.claim_level,
        tuple(sorted(set(relation.evidence_block_ids))),
        evidence,
        tuple(sorted(set(relation.applicable_conditions))),
    )


def _compare_payload_maps(
    left: dict[tuple[Any, ...], dict[str, Any]],
    right: dict[tuple[Any, ...], dict[str, Any]],
) -> dict[str, Any]:
    left_keys = set(left)
    right_keys = set(right)
    return {
        "common_count": len(left_keys & right_keys),
        "only_left": [left[key] for key in sorted(left_keys - right_keys, key=repr)],
        "only_right": [right[key] for key in sorted(right_keys - left_keys, key=repr)],
    }
