from types import SimpleNamespace

from platform_core.knowledge.graphs.document_knowledge_audit import (
    build_document_knowledge,
    triage_document,
)
from platform_core.repositories.knowledge_graph_document_audit_repository import _serialize_card


def test_triage_keeps_uncertain_research_and_returns_rebuildable_evidence():
    document = {
        "document_id": "doc-1",
        "document_version": 1,
        "title": "复杂电磁环境下雷达抗干扰方法研究",
        "blocks": [
            {
                "block_id": "block-1",
                "page": 1,
                "text": "摘要 本文面向雷达装备抗干扰任务，提出一种算法。" + "试验结果表明方法有效。" * 80,
            },
            {"block_id": "block-2", "page": 8, "text": "结论 该方法可提升雷达系统能力。参考文献"},
        ],
    }

    result = triage_document(document)

    assert result["eligible_for_extraction"] is True
    assert result["triage_level"] == "military"
    assert result["military_value_level"] == "Military"
    assert result["deep_extraction_recommended"] is True
    assert result["military_value_review_required"] is False
    assert result["evidence"]
    for evidence in result["evidence"]:
        block = next(item for item in document["blocks"] if item["block_id"] == evidence["block_id"])
        assert block["text"][evidence["start"] : evidence["end"]] == evidence["text"]


def test_triage_excludes_explicit_non_research_material():
    document = {
        "document_id": "doc-notice",
        "document_version": 1,
        "title": "征稿启事与会议通知",
        "blocks": [
            {
                "block_id": "notice",
                "page": 1,
                "text": "征稿启事 会议通知 编者按 " + "欢迎投稿。" * 200,
            }
        ],
    }

    result = triage_document(document)

    assert result["document_kind"] == "non_research"
    assert result["eligible_for_extraction"] is False
    assert result["military_value_level"] == "Uncertain"
    assert result["deep_extraction_recommended"] is False


def test_triage_does_not_treat_negated_equipment_disclaimer_as_military_evidence():
    document = {
        "document_id": "doc-general",
        "document_version": 1,
        "title": "复合材料实验方法研究",
        "blocks": [
            {
                "block_id": "general",
                "page": 1,
                "text": (
                    "摘要 本文研究复合材料实验方法，不涉及武器装备，也不用于作战任务。"
                    + "实验结果表明材料性能得到改善。" * 80
                    + "结论 本研究未面向军事应用。参考文献"
                ),
            }
        ],
    }

    result = triage_document(document)

    assert result["eligible_for_extraction"] is True
    assert result["triage_level"] == "general_technology"
    assert result["military_value_level"] == "No Military Value"
    assert result["deep_extraction_recommended"] is False
    assert result["signals"]["military_markers"] == []
    assert result["signals"]["equipment_markers"] == []
    assert result["signals"]["negated_military_phrases"]


def test_triage_distinguishes_potential_uncertain_and_general_military_value():
    def classify(title: str, sentence: str) -> dict:
        return triage_document(
            {
                "document_id": title,
                "document_version": 1,
                "title": title,
                "blocks": [
                    {
                        "block_id": "b1",
                        "page": 1,
                        "text": "摘要 " + sentence + "。" + "实验结果稳定。" * 120 + "结论 研究完成。参考文献",
                    }
                ],
            }
        )

    potential = classify(
        "高温复合材料跨领域应用研究",
        "本文研究新材料与高温制造工艺，可迁移至极端环境热防护应用",
    )
    uncertain = classify(
        "量子传感算法研究",
        "本文提出新型传感算法并分析低信噪比条件下的可靠性",
    )
    general = classify(
        "抽象代数性质研究",
        "本文证明一组代数恒等式并给出严格数学推导",
    )

    assert potential["military_value_level"] == "Potential"
    assert potential["deep_extraction_recommended"] is True
    assert potential["military_value_review_required"] is True
    assert uncertain["military_value_level"] == "Uncertain"
    assert uncertain["deep_extraction_recommended"] is True
    assert uncertain["military_value_review_required"] is True
    assert general["military_value_level"] == "General"
    assert general["deep_extraction_recommended"] is False
    assert general["military_value_review_required"] is False


def test_document_knowledge_uses_authoritative_entities_relations_and_spans():
    document = {
        "kb_id": "kb-1",
        "document_id": "doc-1",
        "document_version": 1,
        "title": "雷达抗干扰技术研究 2025",
        "source_summary": {"source_type": "paper", "language": "zh"},
        "blocks": [
            {
                "block_id": "b1",
                "page": 1,
                "heading_path": ["方法"],
                "text": "自适应波束形成技术提升抗干扰能力。",
            }
        ],
        "entities": [
            {
                "entity_id": "e-tech",
                "label": "KeyTechnology",
                "name": "自适应波束形成技术",
                "lifecycle_status": "active",
                "mentions": [{"block_id": "b1", "page": 1, "start": 0, "end": 9, "heading_path": ["方法"]}],
            },
            {
                "entity_id": "e-cap",
                "label": "Capability",
                "name": "抗干扰能力",
                "lifecycle_status": "active",
                "mentions": [{"block_id": "b1", "page": 1, "start": 11, "end": 16, "heading_path": ["方法"]}],
            },
        ],
        "relations": [
            {
                "triple_id": "r1",
                "source_entity_id": "e-tech",
                "target_entity_id": "e-cap",
                "relation_type": "ENABLES_CAPABILITY",
                "claim_level": "Fact",
                "review_status": "accepted",
                "lifecycle_status": "active",
                "evidence_spans": [{"block_id": "b1", "page": 1, "start": 0, "end": 17}],
            }
        ],
    }
    triage = triage_document(document)

    result = build_document_knowledge(
        document,
        triage=triage,
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
    )

    assert result["card"]["technology_families"] == ["自适应波束形成技术"]
    assert result["card"]["capability_gains"] == ["抗干扰能力"]
    assert result["card"]["core_relation_ids"] == ["r1"]
    assert result["card"]["graph_rag_hints"]["trusted_path_count"] == 1
    assert result["card"]["narrative_report"]["technical_chain"] == "自适应波束形成技术 → 抗干扰能力"
    assert result["card"]["transfer_potential"]["claim_level"] == "Inference"
    assert result["threads"][0]["technical_line"] == ["自适应波束形成技术"]
    assert result["threads"][0]["confidence"] > 0.7
    assert result["threads"][0]["military_value"]["level"] == triage["military_value_level"]
    assert (
        result["threads"][0]["military_value"]["deep_extraction_recommended"] is triage["deep_extraction_recommended"]
    )
    evidence = result["card"]["evidence_refs"]
    assert any(item["text"] == "自适应波束形成技术" and item["rebuildable"] for item in evidence)
    assert any(
        item["triple_ids"] == ["r1"] and item["text"] == "自适应波束形成技术提升抗干扰能力。" for item in evidence
    )


def test_document_knowledge_merges_entity_and_relation_references_on_same_span():
    document = {
        "kb_id": "kb-1",
        "document_id": "doc-1",
        "document_version": 1,
        "title": "证据合并测试",
        "blocks": [{"block_id": "b1", "page": 2, "heading_path": ["结论"], "text": "技术有效"}],
        "entities": [
            {
                "entity_id": "e1",
                "label": "KeyTechnology",
                "name": "技术",
                "mentions": [
                    {
                        "block_id": "b1",
                        "page": 2,
                        "start": 0,
                        "end": 4,
                        "confidence": 0.91,
                        "extraction_method": "entity_mention",
                        "model_version": "lightrag.5-multi-v1",
                        "ontology_version": "defense-kg-1.0",
                        "review_status": "accepted",
                    }
                ],
            }
        ],
        "relations": [
            {
                "triple_id": "r1",
                "source_entity_id": "e1",
                "target_entity_id": "e1",
                "relation_type": "IMPROVES",
                "claim_level": "Fact",
                "review_status": "accepted",
                "evidence_spans": [
                    {
                        "block_id": "b1",
                        "page": 2,
                        "start": 0,
                        "end": 4,
                        "claim_level": "Fact",
                        "confidence": 0.86,
                        "extraction_method": "lightrag_joint_ie",
                        "model_version": "lightrag.5-multi-v1",
                        "ontology_version": "defense-kg-1.0",
                        "pipeline_revision": "hybrid-v2-r1",
                        "review_status": "accepted",
                    }
                ],
            }
        ],
    }

    result = build_document_knowledge(
        document,
        triage=triage_document(document),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
    )

    assert result["card"]["evidence_refs"] == [
        {
            "block_id": "b1",
            "page": 2,
            "start": 0,
            "end": 4,
            "entity_ids": ["e1"],
            "triple_ids": ["r1"],
            "supports": [
                {
                    "kind": "entity",
                    "id": "e1",
                    "evidence_use": "entity_identification",
                    "evidence_use_label": "关键技术识别",
                    "entity_type": "KeyTechnology",
                    "claim_level": None,
                    "review_status": "accepted",
                    "confidence": 0.91,
                    "extraction_method": "entity_mention",
                    "model_version": "lightrag.5-multi-v1",
                    "ontology_version": "defense-kg-1.0",
                    "pipeline_revision": None,
                },
                {
                    "kind": "relation",
                    "id": "r1",
                    "evidence_use": "relation_support",
                    "evidence_use_label": "IMPROVES 支撑",
                    "relation_type": "IMPROVES",
                    "claim_level": "Fact",
                    "review_status": "accepted",
                    "confidence": 0.86,
                    "extraction_method": "lightrag_joint_ie",
                    "model_version": "lightrag.5-multi-v1",
                    "ontology_version": "defense-kg-1.0",
                    "pipeline_revision": "hybrid-v2-r1",
                },
            ],
            "text": "技术有效",
            "rebuildable": True,
            "heading_path": ["结论"],
            "bbox": None,
        }
    ]


def test_card_list_omits_heavy_profile_but_detail_returns_it():
    card = SimpleNamespace(
        card_id="card",
        document_id="doc",
        document_version=1,
        title="标题",
        source_summary={},
        triage={},
        content_overview="概要",
        main_thread_id="thread",
        sub_thread_ids=[],
        core_entity_ids=[],
        core_relation_ids=[],
        technology_families=[],
        capability_gains=[],
        application_directions=[],
        evidence_refs=[{"block_id": "b1"}],
        maturity={},
        heat_signals={},
        innovation_potential={},
        key_metrics=[{"entity_id": "metric"}],
        transfer_potential={"score": 0.2},
        graph_rag_hints={"recommended_paths": [{"relation_id": "r1"}]},
        narrative_report={"technical_chain": "技术 → 能力"},
        uncertainty="待审核",
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        governance_status="pending",
        updated_at=None,
    )

    summary = _serialize_card(card, include_evidence=False)
    detail = _serialize_card(card, include_evidence=True)

    assert "graph_rag_hints" not in summary
    assert "narrative_report" not in summary
    assert "key_metrics" not in summary
    assert detail["graph_rag_hints"]["recommended_paths"][0]["relation_id"] == "r1"
    assert detail["evidence_refs"] == [{"block_id": "b1"}]
