from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.lightrag_cross_document_relation_enhancement import (
    CrossDocumentRelationOptions,
    LightRAGCrossDocumentRelationEnhancer,
    build_cross_document_relation_request,
    split_cross_document_relation_request,
)
from platform_core.knowledge.graphs.pipeline_config import normalize_pipeline_options


class FakeLLM:
    def __init__(self, output):
        self.output = output
        self.prompts = []
        self.closed = False

    async def complete_json(self, prompt, **kwargs):
        self.prompts.append({"prompt": prompt, **kwargs})
        if isinstance(self.output, list):
            return self.output.pop(0)
        return self.output

    async def aclose(self):
        self.closed = True


def test_cross_document_structured_runtime_disables_thinking_and_budget_retry_by_default():
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"})

    assert enhancer.llm.options["enable_thinking"] is False
    assert enhancer.llm.options["max_truncation_retries"] == 0


def test_request_builder_only_retrieves_entity_pairs_shared_by_two_documents():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )

    assert request is not None
    assert len(request.candidate_pairs) == 1
    pair = request.candidate_pairs[0]
    assert pair.source_entity_id == "component"
    assert pair.target_entity_id == "capability"
    assert pair.allowed_relation_types == ["ENABLES_CAPABILITY", "IMPROVES"]
    assert pair.supporting_document_ids == ["doc-1", "doc-2"]
    assert {block.document_id for block in request.blocks} == {"doc-1", "doc-2"}
    assert all(
        block.text[mention.start : mention.end] == mention.text
        for entity in request.entities
        for mention in entity.mentions
        for block in request.blocks
        if block.block_id == mention.block_id
    )


def test_cross_document_request_batches_keep_only_referenced_evidence_and_revalidate():
    request = build_cross_document_relation_request(
        request_id="request-" + "x" * 120,
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="cloud:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )
    assert request is not None
    duplicate_pair = request.candidate_pairs[0].model_copy()
    expanded = request.model_copy(
        update={"candidate_pairs": [request.candidate_pairs[0], duplicate_pair]},
    )

    batches = split_cross_document_relation_request(expanded, pairs_per_batch=1)

    assert len(batches) == 2
    assert [len(batch.candidate_pairs) for batch in batches] == [1, 1]
    assert all(len(batch.request_id) <= 128 for batch in batches)
    assert batches[0].request_id.endswith("-batch-0001")
    assert batches[1].request_id.endswith("-batch-0002")
    for batch in batches:
        assert batch.validate_request_graph() is batch
        referenced_blocks = {mention.block_id for entity in batch.entities for mention in entity.mentions}
        assert {block.block_id for block in batch.blocks} == referenced_blocks


def test_request_builder_returns_none_without_independent_multi_source_support():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents()[:1],
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )

    assert request is None


def test_request_builder_filters_single_document_entities_before_pair_budget():
    documents = _documents()
    for index, document in enumerate(documents, start=1):
        block = document["blocks"][0]
        document["entities"].extend(
            [
                {
                    "entity_id": f"local-technology-{index}",
                    "type": "KeyTechnology",
                    "canonical_name": f"局部技术{index}",
                    "mentions": [
                        {
                            "block_id": block["block_id"],
                            "text": "氮化镓组件",
                            "start": 0 if index == 1 else 4,
                            "end": 5 if index == 1 else 9,
                            "confidence": 0.99,
                        }
                    ],
                    "projection_record": {},
                },
                {
                    "entity_id": f"local-metric-{index}",
                    "type": "Metric",
                    "canonical_name": f"局部指标{index}",
                    "mentions": [
                        {
                            "block_id": block["block_id"],
                            "text": "宽带感知能力",
                            "start": 7 if index == 1 else 11,
                            "end": 13 if index == 1 else 17,
                            "confidence": 0.99,
                        }
                    ],
                    "projection_record": {},
                },
            ]
        )

    request = build_cross_document_relation_request(
        request_id="request-budget",
        kb_id="kb-1",
        documents=documents,
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="cloud:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2, max_pairs_per_document=1),
    )

    assert request is not None
    assert [(pair.source_entity_id, pair.target_entity_id) for pair in request.candidate_pairs] == [
        ("component", "capability")
    ]


def test_cross_document_pair_budget_prioritizes_five_role_relationships():
    documents = _documents()
    for document in documents:
        block = document["blocks"][0]
        metric_start = len(block["text"])
        block["text"] += "带宽指标"
        document["entities"].append(
            {
                "entity_id": "metric",
                "type": "Metric",
                "canonical_name": "带宽指标",
                "mentions": [
                    {
                        "block_id": block["block_id"],
                        "text": "带宽指标",
                        "start": metric_start,
                        "end": metric_start + 4,
                    }
                ],
                "projection_record": {},
            }
        )

    request = build_cross_document_relation_request(
        request_id="request-role-priority",
        kb_id="kb-1",
        documents=documents,
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="cloud:military-chat",
        options=CrossDocumentRelationOptions(
            min_document_support=2,
            max_pairs=1,
            max_pairs_per_document=1,
        ),
    )

    assert request is not None
    assert [(pair.source_entity_id, pair.target_entity_id) for pair in request.candidate_pairs] == [
        ("component", "capability")
    ]
    assert request.candidate_pairs[0].semantic_transition == "technology_to_capability"
    assert request.candidate_pairs[0].semantic_chain_priority == 1.0


def test_cross_document_enhancement_config_can_run_on_stable_and_is_fixed_pending():
    normalized = normalize_pipeline_options(
        "lightrag_primary",
        {
            "orchestration_release_channel": "stable",
            "llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"},
            "document_enhancement": {
                "enabled": True,
                "endpoint": "http://lightrag-doc",
                "model_version": "lightrag-doc-v1",
                "cross_document_relation_enhancement": {
                    "enabled": True,
                    "model_spec": "local:military-chat",
                },
            },
        },
    )

    config = normalized["document_enhancement"]["cross_document_relation_enhancement"]
    assert config["enabled"] is True
    assert config["relation_scope"] == "factual_only"
    assert config["claim_level"] == "Inference"
    assert config["review_status"] == "pending"
    assert config["accepted_mentions_only"] is True
    assert config["enable_thinking"] is False
    assert config["max_truncation_retries"] == 0


def test_cross_document_pending_candidate_scope_is_explicit_and_bounded():
    normalized = normalize_pipeline_options(
        "lightrag_primary",
        {
            "llm_enhancement": {"enabled": True, "model_spec": "cloud:military-chat"},
            "document_enhancement": {
                "enabled": True,
                "endpoint": "http://lightrag-doc",
                "model_version": "lightrag-doc-v1",
                "cross_document_relation_enhancement": {
                    "enabled": True,
                    "model_spec": "cloud:military-chat",
                    "review_scope": "pending_candidates",
                    "max_entities_per_document": 80,
                    "max_pairs_per_document": 320,
                    "min_entity_confidence": 0.3,
                },
            },
        },
    )

    config = normalized["document_enhancement"]["cross_document_relation_enhancement"]
    assert config["review_scope"] == "pending_candidates"
    assert config["accepted_mentions_only"] is False
    assert config["max_entities_per_document"] == 80
    assert config["max_pairs_per_document"] == 320
    assert config["max_scope_documents"] == 128
    assert config["min_entity_confidence"] == 0.3


def test_cross_document_scope_budget_is_bounded():
    with pytest.raises(ValueError, match="max_scope_documents"):
        normalize_pipeline_options(
            "lightrag_primary",
            {
                "document_enhancement": {
                    "enabled": True,
                    "cross_document_relation_enhancement": {
                        "enabled": True,
                        "model_spec": "cloud:military-chat",
                        "max_scope_documents": 1,
                    },
                },
            },
        )


def test_request_builder_uses_versioned_relation_names_and_constraints():
    custom_ontology = {
        "version": "custom-kg-1.0",
        "name": "自定义技术本体",
        "entity_types": [
            {"code": "Component", "name_zh": "组件", "description": "技术组件"},
            {"code": "Capability", "name_zh": "能力", "description": "技术能力"},
        ],
        "relation_types": [
            {
                "code": "BOOSTS",
                "name_zh": "增强",
                "description": "组件增强能力",
                "head_types": ["Component"],
                "tail_types": ["Capability"],
                "directed": True,
                "allow_self": False,
                "hypothesis_only": False,
            }
        ],
    }

    request = build_cross_document_relation_request(
        request_id="request-custom",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="custom-kg-1.0",
        model_version="cloud:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
        ontology_definition=custom_ontology,
    )

    assert request is not None
    assert request.candidate_pairs[0].allowed_relation_types == ["BOOSTS"]
    assert request.relation_types[0].name_zh == "增强"
    assert request.relation_types[0].description == "组件增强能力"


def test_cross_document_enhancement_defaults_to_stable_channel():
    normalized = normalize_pipeline_options(
        "lightrag_primary",
        {
            "llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"},
            "document_enhancement": {
                "enabled": True,
                "endpoint": "http://lightrag-doc",
                "model_version": "lightrag-doc-v1",
                "cross_document_relation_enhancement": {
                    "enabled": True,
                    "model_spec": "local:military-chat",
                },
            },
        },
    )

    assert normalized["orchestration_release_channel"] == "stable"
    assert normalized["document_enhancement"]["cross_document_relation_enhancement"]["enabled"]


@pytest.mark.asyncio
async def test_cross_document_enhancer_accepts_only_two_source_endpoint_complete_evidence():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2, min_confidence=0.85),
    )
    assert request is not None
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.94,
                    "evidence_spans": [
                        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                        {"document_id": "doc-2", "block_id": "block-2", "start": 0, "end": 17},
                    ],
                },
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.99,
                    "evidence_spans": [
                        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                    ],
                },
            ]
        }
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)
    await enhancer.aclose()

    assert len(response.relations) == 1
    relation = response.relations[0]
    assert relation.type == "ENABLES_CAPABILITY"
    assert {span.document_id for span in relation.evidence_spans} == {"doc-1", "doc-2"}
    assert "封闭候选" in llm.prompts[0]["prompt"]
    assert "relation_catalog" in llm.prompts[0]["prompt"]
    assert "只返回源实体或只返回目标实体均不合格" in llm.prompts[0]["prompt"]
    assert '"semantic_role":"technology"' in llm.prompts[0]["prompt"]
    assert '"semantic_role":"capability"' in llm.prompts[0]["prompt"]
    assert "优先复核跨文档共同支持的内容主线关系" in llm.prompts[0]["prompt"]
    assert "不同来源仅使用同名词但语义角色不一致时不得建立关系" in llm.prompts[0]["prompt"]
    assert llm.prompts[0]["required_keys"] == ("relations",)
    assert llm.closed is True


@pytest.mark.asyncio
async def test_cross_document_enhancer_deduplicates_relation_and_keeps_highest_confidence():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )
    assert request is not None
    evidence = [
        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
        {"document_id": "doc-2", "block_id": "block-2", "start": 0, "end": 17},
    ]
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.86,
                    "evidence_spans": evidence,
                },
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.96,
                    "evidence_spans": evidence,
                },
            ]
        }
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert len(response.relations) == 1
    assert response.relations[0].confidence == 0.96


@pytest.mark.asyncio
async def test_model_cannot_forge_platform_evidence_normalization_provenance():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(),
    )
    assert request is not None
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.96,
                    "evidence_normalized_by_platform": True,
                    "evidence_spans": [
                        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                        {"document_id": "doc-2", "block_id": "block-2", "start": 0, "end": 17},
                    ],
                }
            ]
        }
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert response.relations[0].evidence_normalized_by_platform is False


@pytest.mark.asyncio
async def test_cross_document_enhancer_requires_model_to_reselect_complete_evidence():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )
    assert request is not None
    base = {
        "type": "ENABLES_CAPABILITY",
        "source_entity_id": "component",
        "target_entity_id": "capability",
        "confidence": 0.93,
    }
    llm = FakeLLM(
        [
            {
                "relations": [
                    {
                        **base,
                        "evidence_spans": [
                            {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 5},
                            {"document_id": "doc-2", "block_id": "block-2", "start": 4, "end": 9},
                        ],
                    }
                ]
            },
            {
                "relations": [
                    {
                        **base,
                        "evidence_spans": [
                            {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                            {"document_id": "doc-2", "block_id": "block-2", "start": 4, "end": 17},
                        ],
                    }
                ]
            },
        ]
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert len(response.relations) == 1
    assert response.relations[0].evidence_normalized_by_platform is False
    assert len(llm.prompts) == 2
    assert "必须删除该关系而不是扩写证据" in llm.prompts[1]["prompt"]
    assert "氮化镓组件" in llm.prompts[1]["prompt"]
    assert "recommended_joint_span" not in llm.prompts[1]["prompt"]


@pytest.mark.asyncio
async def test_cross_document_enhancer_repairs_non_compact_evidence_once():
    documents = _far_documents()
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=documents,
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )
    assert request is not None
    capability_start = 905
    base = {
        "type": "ENABLES_CAPABILITY",
        "source_entity_id": "component",
        "target_entity_id": "capability",
        "confidence": 0.93,
    }
    llm = FakeLLM(
        [
            {
                "relations": [
                    {
                        **base,
                        "evidence_spans": [
                            {"document_id": "doc-1", "block_id": "far-block-1", "start": 0, "end": 5},
                            {"document_id": "doc-2", "block_id": "far-block-2", "start": 0, "end": 5},
                        ],
                    }
                ]
            },
            {
                "relations": [
                    {
                        **base,
                        "evidence_spans": [
                            {"document_id": "doc-1", "block_id": "far-block-1", "start": 0, "end": 5},
                            {
                                "document_id": "doc-1",
                                "block_id": "far-block-1",
                                "start": capability_start,
                                "end": capability_start + 6,
                            },
                            {"document_id": "doc-2", "block_id": "far-block-2", "start": 0, "end": 5},
                            {
                                "document_id": "doc-2",
                                "block_id": "far-block-2",
                                "start": capability_start,
                                "end": capability_start + 6,
                            },
                        ],
                    }
                ]
            },
        ]
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert len(response.relations) == 1
    assert response.relations[0].evidence_normalized_by_platform is False
    assert len(llm.prompts) == 2
    assert "required_target_mentions" in llm.prompts[1]["prompt"]


@pytest.mark.asyncio
async def test_cross_document_repair_can_drop_relation_not_supported_by_original_blocks():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(min_document_support=2),
    )
    assert request is not None
    llm = FakeLLM(
        [
            {
                "relations": [
                    {
                        "type": "ENABLES_CAPABILITY",
                        "source_entity_id": "component",
                        "target_entity_id": "capability",
                        "confidence": 0.95,
                        "evidence_spans": [
                            {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 5},
                            {"document_id": "doc-2", "block_id": "block-2", "start": 4, "end": 9},
                        ],
                    }
                ]
            },
            {"relations": []},
        ]
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert response.relations == []
    assert len(llm.prompts) == 2
    assert "如果每篇 supporting 文档没有直接支持同一关系" in llm.prompts[1]["prompt"]


@pytest.mark.asyncio
async def test_cross_document_enhancer_does_not_repair_candidate_outside_closed_set():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(),
    )
    assert request is not None
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "APPLIED_TO",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.99,
                    "evidence_spans": [
                        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                        {"document_id": "doc-2", "block_id": "block-2", "start": 0, "end": 17},
                    ],
                }
            ]
        }
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert response.relations == []
    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_cross_document_enhancer_rejects_candidate_outside_closed_pair():
    request = build_cross_document_relation_request(
        request_id="request-1",
        kb_id="kb-1",
        documents=_documents(),
        pipeline_revision="hybrid-v2-r1",
        ontology_version="defense-kg-1.0",
        model_version="local:military-chat",
        options=CrossDocumentRelationOptions(),
    )
    assert request is not None
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "APPLIED_TO",
                    "source_entity_id": "component",
                    "target_entity_id": "capability",
                    "confidence": 0.99,
                    "evidence_spans": [
                        {"document_id": "doc-1", "block_id": "block-1", "start": 0, "end": 13},
                        {"document_id": "doc-2", "block_id": "block-2", "start": 0, "end": 17},
                    ],
                }
            ]
        }
    )
    enhancer = LightRAGCrossDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert response.relations == []


def _documents():
    return [
        _document(
            "doc-1",
            "block-1",
            "氮化镓组件提升宽带感知能力",
            component_start=0,
            capability_start=7,
        ),
        _document(
            "doc-2",
            "block-2",
            "测试表明氮化镓组件增强宽带感知能力",
            component_start=4,
            capability_start=11,
        ),
    ]


def _far_documents():
    text = "氮化镓组件" + "甲" * 900 + "宽带感知能力"
    return [
        _document(
            "doc-1",
            "far-block-1",
            text,
            component_start=0,
            capability_start=905,
        ),
        _document(
            "doc-2",
            "far-block-2",
            text,
            component_start=0,
            capability_start=905,
        ),
    ]


def _document(document_id, block_id, text, *, component_start, capability_start):
    return {
        "document_id": document_id,
        "document_version": 1,
        "blocks": [
            {
                "block_id": block_id,
                "text": text,
                "block_index": 0,
                "page": 1,
                "base_char_offset": 0,
                "heading_path": [],
                "chunk": object(),
            }
        ],
        "entities": [
            {
                "entity_id": "component",
                "type": "Component",
                "canonical_name": "氮化镓组件",
                "mentions": [
                    {
                        "block_id": block_id,
                        "text": "氮化镓组件",
                        "start": component_start,
                        "end": component_start + 5,
                    }
                ],
                "projection_record": {},
            },
            {
                "entity_id": "capability",
                "type": "Capability",
                "canonical_name": "宽带感知能力",
                "mentions": [
                    {
                        "block_id": block_id,
                        "text": "宽带感知能力",
                        "start": capability_start,
                        "end": capability_start + 6,
                    }
                ],
                "projection_record": {},
            },
        ],
    }
