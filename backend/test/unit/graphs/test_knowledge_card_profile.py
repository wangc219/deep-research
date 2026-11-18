from platform_core.knowledge.graphs.knowledge_card_profile import build_knowledge_card_profile


def test_profile_exposes_metrics_transfer_hints_and_grounded_narrative():
    entities = [
        {
            "entity_id": "tech",
            "label": "KeyTechnology",
            "name": "自适应波束形成",
            "mentions": [{"review_status": "accepted"}],
        },
        {
            "entity_id": "cap",
            "label": "Capability",
            "name": "抗干扰能力",
            "mentions": [{"review_status": "accepted"}],
        },
        {
            "entity_id": "app",
            "label": "ApplicationScenario",
            "name": "复杂电磁环境",
            "mentions": [{"review_status": "pending"}],
        },
        {
            "entity_id": "metric",
            "label": "Metric",
            "name": "识别准确率",
            "mentions": [{"review_status": "accepted"}],
        },
    ]
    relations = [
        {
            "triple_id": "trusted",
            "source_entity_id": "tech",
            "target_entity_id": "cap",
            "relation_type": "ENABLES_CAPABILITY",
            "claim_level": "Fact",
            "review_status": "accepted",
            "evidence_spans": [{"block_id": "b1", "start": 0, "end": 10}],
        },
        {
            "triple_id": "transfer",
            "source_entity_id": "tech",
            "target_entity_id": "app",
            "relation_type": "TRANSFERABLE_TO",
            "claim_level": "Hypothesis",
            "review_status": "pending",
            "evidence_spans": [{"block_id": "b2", "start": 5, "end": 15}],
        },
    ]
    evidence_refs = [
        {"block_id": "b1", "start": 0, "end": 10, "rebuildable": True},
        {"block_id": "b2", "start": 5, "end": 15, "rebuildable": False},
    ]

    result = build_knowledge_card_profile(
        entities=entities,
        relations=relations,
        triage={"military_value_reason": "存在明确装备能力落点。"},
        threads=[
            {
                "technical_line": ["自适应波束形成"],
                "capability_direction": ["抗干扰能力"],
                "application_direction": ["复杂电磁环境"],
            }
        ],
        evidence_refs=evidence_refs,
    )

    assert result["key_metrics"] == [
        {
            "entity_id": "metric",
            "name": "识别准确率",
            "evidence_count": 1,
            "review_status": "accepted",
        }
    ]
    assert result["transfer_potential"]["claim_level"] == "Inference"
    assert result["transfer_potential"]["supporting_relation_ids"] == ["transfer"]
    assert result["graph_rag_hints"]["trusted_path_count"] == 1
    assert result["graph_rag_hints"]["edge_prediction_candidate_ids"] == ["transfer"]
    assert result["graph_rag_hints"]["recommended_paths"][1]["eligible_for_trusted_query"] is False
    assert result["narrative_report"]["military_value"] == "存在明确装备能力落点。"
    assert "1/2 条证据 Span 可由原文重建" in result["narrative_report"]["evidence_and_uncertainty"]
    assert "自适应波束形成 → 抗干扰能力" == result["narrative_report"]["technical_chain"]
