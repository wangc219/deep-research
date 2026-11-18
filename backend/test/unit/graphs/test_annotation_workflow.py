import pytest
from pydantic import ValidationError

from platform_core.knowledge.training.annotation_workflow import (
    AnnotationAssignmentSpec,
    AnnotationCampaignSpec,
    compare_independent_annotations,
)
from platform_core.knowledge.training.gold_contract import GoldDocument


def _document(*, entity_id: str = "e1", relation_type: str = "ENABLES_CAPABILITY") -> GoldDocument:
    return GoldDocument.model_validate(
        {
            "document_id": "doc-1",
            "split": "train",
            "blocks": [{"block_id": "block-1", "text": "相控阵雷达提升探测能力。"}],
            "entities": [
                {
                    "entity_id": entity_id,
                    "block_id": "block-1",
                    "type": "KeyTechnology",
                    "text": "相控阵雷达",
                    "start": 0,
                    "end": 5,
                    "canonical_entity_id": "canonical-1",
                },
                {
                    "entity_id": "e2",
                    "block_id": "block-1",
                    "type": "Capability",
                    "text": "探测能力",
                    "start": 7,
                    "end": 11,
                    "canonical_entity_id": "canonical-2",
                },
            ],
            "relations": [
                {
                    "relation_id": "r1",
                    "type": relation_type,
                    "source_entity_id": entity_id,
                    "target_entity_id": "e2",
                    "evidence_block_ids": ["block-1"],
                    "evidence_spans": [
                        {"block_id": "block-1", "start": 0, "end": 11, "text": "相控阵雷达提升探测能力"}
                    ],
                    "applicable_conditions": ["完成阵列校准"],
                    "claim_level": "Fact",
                }
            ],
        }
    )


def test_assignment_requires_two_independent_annotators_and_third_arbitrator():
    with pytest.raises(ValidationError, match="两名不同"):
        AnnotationAssignmentSpec(
            document_id="doc-1",
            split="train",
            annotator_ids=["reviewer", "reviewer"],
            arbitrator_id="expert",
        )

    with pytest.raises(ValidationError, match="仲裁专家"):
        AnnotationAssignmentSpec(
            document_id="doc-1",
            split="train",
            annotator_ids=["reviewer-a", "reviewer-b"],
            arbitrator_id="reviewer-a",
        )


def test_pilot_campaign_rejects_non_210_30_60_distribution():
    with pytest.raises(ValidationError, match="210/30/60"):
        AnnotationCampaignSpec(
            name="pilot",
            ontology_version="defense-kg-1.0",
            assignments=[
                {
                    "document_id": "doc-1",
                    "split": "train",
                    "annotator_ids": ["a", "b"],
                    "arbitrator_id": "c",
                }
            ],
        )


def test_annotation_diff_ignores_local_ids_but_preserves_direction_evidence_and_conditions():
    left = _document(entity_id="left-local")
    right = _document(entity_id="right-local")

    result = compare_independent_annotations(left, right)

    assert result["agreement"] is True
    assert result["entities"]["common_count"] == 2
    assert result["relations"]["common_count"] == 1


def test_annotation_diff_reports_relation_type_disagreement():
    result = compare_independent_annotations(
        _document(relation_type="ENABLES_CAPABILITY"),
        _document(relation_type="APPLIED_TO"),
    )

    assert result["agreement"] is False
    assert result["disagreement_count"] == 2
    assert result["relations"]["only_left"][0]["type"] == "ENABLES_CAPABILITY"
    assert result["relations"]["only_right"][0]["type"] == "APPLIED_TO"
