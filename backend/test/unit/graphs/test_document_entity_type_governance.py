from platform_core.knowledge.graphs.document_entity_type_governance import (
    propose_document_entity_type_redirects,
)


def _entity(entity_id: str, label: str, *, name: str = "定向能", accepted: bool = False) -> dict:
    return {
        "entity_id": entity_id,
        "type": label,
        "canonical_name": name,
        "mentions": [{"confidence": 0.8}],
        "mention_review_statuses": ["accepted" if accepted else "pending"],
        "projection_record": {
            "entity_id": entity_id,
            "normalized_name": name,
            "label": label,
        },
    }


def test_document_type_governance_redirects_only_relation_supported_type():
    document = {
        "entities": [
            _entity("energy-capability", "Capability"),
            _entity("energy-achievement", "Achievement"),
            _entity("energy-tech", "KeyTechnology"),
            _entity("missile", "ProductSystem", name="巡航导弹"),
            _entity("suppression", "Capability", name="电子压制能力"),
        ]
    }
    relations = [
        {
            "source_entity_id": "missile",
            "target_entity_id": "energy-tech",
            "type": "USES_TECHNOLOGY",
        },
        {
            "source_entity_id": "energy-tech",
            "target_entity_id": "suppression",
            "type": "ENABLES_CAPABILITY",
        },
    ]

    result = propose_document_entity_type_redirects(document=document, relations=relations)

    assert result["resolved_group_count"] == 1
    assert result["redirect_count"] == 2
    assert result["resolved_groups"][0]["selected_entity_id"] == "energy-tech"
    assert result["resolved_groups"][0]["relation_compatibility_scores"] == {
        "Achievement": 0,
        "Capability": 0,
        "KeyTechnology": 2,
    }
    assert {(decision.source_entity_id, decision.target_entity_id) for decision in result["decisions"]} == {
        ("energy-capability", "energy-tech"),
        ("energy-achievement", "energy-tech"),
    }


def test_document_type_governance_keeps_ambiguous_or_human_reviewed_groups():
    ambiguous = propose_document_entity_type_redirects(
        document={
            "entities": [
                _entity("pod-component", "Component", name="吊舱"),
                _entity("pod-product", "ProductSystem", name="吊舱"),
            ]
        },
        relations=[],
    )
    assert ambiguous["resolved_group_count"] == 0
    assert ambiguous["skipped_groups"][0]["reason"] == "insufficient_unique_relation_evidence"

    protected = propose_document_entity_type_redirects(
        document={
            "entities": [
                _entity("energy-capability", "Capability", accepted=True),
                _entity("energy-tech", "KeyTechnology"),
                _entity("missile", "ProductSystem", name="巡航导弹"),
                _entity("suppression", "Capability", name="电子压制能力"),
            ]
        },
        relations=[
            {
                "source_entity_id": "missile",
                "target_entity_id": "energy-tech",
                "type": "USES_TECHNOLOGY",
            },
            {
                "source_entity_id": "energy-tech",
                "target_entity_id": "suppression",
                "type": "ENABLES_CAPABILITY",
            },
        ],
    )
    assert protected["resolved_group_count"] == 0
    assert protected["skipped_groups"][0]["reason"] == "human_reviewed_mention_present"
