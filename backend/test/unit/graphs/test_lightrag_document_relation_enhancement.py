from __future__ import annotations

import pytest
from pydantic import ValidationError

from defense_document_re_contract import (
    DocumentREBlock,
    DocumentREEntity,
    DocumentREMention,
    DocumentREOptions,
    DocumentRERelationType,
    DocumentRERequest,
)
from platform_core.knowledge.graphs.lightrag_document_relation_enhancement import (
    LightRAGDocumentRelationEnhancer,
    _candidate_pairs,
)


class FakeLLM:
    def __init__(self, output):
        self.output = output
        self.prompts = []
        self.closed = False

    async def complete_json(self, prompt, **kwargs):
        self.prompts.append({"prompt": prompt, **kwargs})
        return self.output

    async def aclose(self):
        self.closed = True


def _request(*, max_relations: int = 12) -> DocumentRERequest:
    return DocumentRERequest(
        request_id="request-1",
        pipeline_revision="hybrid-v2-r1",
        model_version="local:military-chat",
        ontology_version="defense-kg-1.0",
        document_id="doc-1",
        document_version=1,
        blocks=[
            DocumentREBlock(block_id="b1", text="氮化镓组件用于雷达前端", block_index=0),
            DocumentREBlock(block_id="b2", text="该组件提升宽带感知能力", block_index=1),
        ],
        entities=[
            DocumentREEntity(
                entity_id="e1",
                type="Component",
                canonical_name="氮化镓组件",
                mentions=[DocumentREMention(block_id="b1", text="氮化镓组件", start=0, end=5)],
            ),
            DocumentREEntity(
                entity_id="e2",
                type="Capability",
                canonical_name="宽带感知能力",
                mentions=[DocumentREMention(block_id="b2", text="宽带感知能力", start=5, end=11)],
            ),
        ],
        relation_types=[
            DocumentRERelationType(
                code="ENABLES_CAPABILITY",
                name_zh="形成能力",
                description="原理或技术形成可验证能力",
                head_types=["Component"],
                tail_types=["Capability"],
            )
        ],
        options=DocumentREOptions(max_chars=1000, max_relations=max_relations),
    )


def test_document_relation_options_use_bounded_relation_budget():
    assert DocumentREOptions().max_relations == 12
    assert DocumentREOptions().max_candidate_pairs == 256
    with pytest.raises(ValidationError):
        DocumentREOptions(max_relations=65)
    with pytest.raises(ValidationError):
        DocumentREOptions(max_candidate_pairs=2049)


def test_document_candidate_budget_prioritizes_five_role_adjacent_transition():
    request = _request().model_copy(
        update={
            "entities": [
                *_request().entities,
                DocumentREEntity(
                    entity_id="e3",
                    type="Metric",
                    canonical_name="带宽指标",
                    mentions=[DocumentREMention(block_id="b1", text="雷达", start=7, end=9)],
                ),
            ],
            "relation_types": [
                *_request().relation_types,
                DocumentRERelationType(
                    code="MEASURED_BY",
                    name_zh="由指标度量",
                    description="能力由指标度量",
                    head_types=["Capability"],
                    tail_types=["Metric"],
                ),
            ],
            "options": DocumentREOptions(max_candidate_pairs=1),
        }
    )

    pairs = _candidate_pairs(request)

    assert [(item["source_entity_id"], item["target_entity_id"]) for item in pairs] == [("e1", "e2")]
    assert pairs[0]["semantic_transition"] == "technology_to_capability"
    assert pairs[0]["semantic_chain_priority"] == 1.0


def test_document_relation_structured_runtime_disables_thinking_and_budget_retry_by_default():
    enhancer = LightRAGDocumentRelationEnhancer({"model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"})

    assert enhancer.llm.options["enable_thinking"] is False
    assert enhancer.llm.options["max_truncation_retries"] == 0
    assert enhancer.min_confidence == 0.8


@pytest.mark.asyncio
async def test_document_llm_accepts_only_grounded_cross_block_relation():
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "confidence": 0.84,
                    "evidence_spans": [
                        {"block_id": "b1", "start": 0, "end": 5},
                        {"block_id": "b2", "start": 0, "end": 11},
                    ],
                }
            ]
        }
    )
    enhancer = LightRAGDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(_request())
    await enhancer.aclose()

    assert len(response.relations) == 1
    assert response.relations[0].source_entity_id == "e1"
    assert response.relations[0].target_entity_id == "e2"
    assert response.runtime.backend == "llm"
    assert response.runtime.candidate_count == 1
    assert response.runtime.accepted_count == 1
    assert response.runtime.truncated_count == 0
    assert "不可信来源文本" in llm.prompts[0]["prompt"]
    assert "最多返回 12 条关系" in llm.prompts[0]["prompt"]
    assert "confidence 不得低于 0.80" in llm.prompts[0]["prompt"]
    assert '"name_zh":"形成能力"' in llm.prompts[0]["prompt"]
    assert '"description":"原理或技术形成可验证能力"' in llm.prompts[0]["prompt"]
    assert '"pair_ref":"doc-p1"' in llm.prompts[0]["prompt"]
    assert "候选对共现不等于存在关系" in llm.prompts[0]["prompt"]
    assert '"semantic_role":"technology"' in llm.prompts[0]["prompt"]
    assert '"semantic_role":"capability"' in llm.prompts[0]["prompt"]
    assert "先围绕内容主线检查关系" in llm.prompts[0]["prompt"]
    assert "五类允许缺项，共现不能补造成关系" in llm.prompts[0]["prompt"]
    assert llm.prompts[0]["required_keys"] == ("relations",)
    assert llm.closed is True


@pytest.mark.asyncio
async def test_document_llm_drops_relation_without_both_endpoint_mentions():
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "confidence": 0.9,
                    "evidence_spans": [{"block_id": "b1", "start": 0, "end": 5}],
                }
            ]
        }
    )
    enhancer = LightRAGDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(_request())

    assert response.relations == []


@pytest.mark.asyncio
async def test_document_llm_requires_one_contiguous_span_for_same_block_relation():
    request = _request().model_copy(
        update={
            "blocks": [DocumentREBlock(block_id="b1", text="氮化镓组件提升宽带感知能力", block_index=0)],
            "entities": [
                DocumentREEntity(
                    entity_id="e1",
                    type="Component",
                    canonical_name="氮化镓组件",
                    mentions=[DocumentREMention(block_id="b1", text="氮化镓组件", start=0, end=5)],
                ),
                DocumentREEntity(
                    entity_id="e2",
                    type="Capability",
                    canonical_name="宽带感知能力",
                    mentions=[DocumentREMention(block_id="b1", text="宽带感知能力", start=7, end=13)],
                ),
            ],
        }
    )
    llm = FakeLLM(
        {
            "relations": [
                {
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "confidence": 0.95,
                    "evidence_spans": [
                        {"block_id": "b1", "start": 0, "end": 5},
                        {"block_id": "b1", "start": 7, "end": 13},
                    ],
                }
            ]
        }
    )

    response = await LightRAGDocumentRelationEnhancer(
        {"model_spec": "local:military-chat"},
        llm=llm,
    ).enhance(request)

    assert response.relations == []


@pytest.mark.asyncio
async def test_document_llm_enforces_relation_budget_and_audits_truncation():
    valid_relation = {
        "type": "ENABLES_CAPABILITY",
        "source_entity_id": "e1",
        "target_entity_id": "e2",
        "confidence": 0.84,
        "evidence_spans": [
            {"block_id": "b1", "start": 0, "end": 5},
            {"block_id": "b2", "start": 0, "end": 11},
        ],
    }
    llm = FakeLLM({"relations": [valid_relation, {**valid_relation, "confidence": 0.8}]})
    enhancer = LightRAGDocumentRelationEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(_request(max_relations=1))

    assert len(response.relations) == 1
    assert response.runtime.candidate_count == 2
    assert response.runtime.accepted_count == 1
    assert response.runtime.truncated_count == 1
    assert "最多返回 1 条关系" in llm.prompts[0]["prompt"]


@pytest.mark.asyncio
async def test_document_llm_rejects_relation_outside_closed_candidate_pair():
    llm = FakeLLM(
        {
            "relations": [
                {
                    "pair_ref": "outside-pair",
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "confidence": 0.95,
                    "evidence_spans": [
                        {"block_id": "b1", "start": 0, "end": 5},
                        {"block_id": "b2", "start": 0, "end": 11},
                    ],
                }
            ]
        }
    )

    response = await LightRAGDocumentRelationEnhancer(
        {"model_spec": "local:military-chat"},
        llm=llm,
    ).enhance(_request())

    assert response.relations == []


@pytest.mark.asyncio
async def test_document_llm_skips_model_when_ontology_has_no_compatible_pair():
    request = _request().model_copy(
        update={
            "relation_types": [
                DocumentRERelationType(
                    code="COMPOSED_OF",
                    name_zh="组成",
                    description="系统由组件构成",
                    head_types=["ProductSystem"],
                    tail_types=["Component"],
                )
            ]
        }
    )
    llm = FakeLLM({"relations": []})

    response = await LightRAGDocumentRelationEnhancer(
        {"model_spec": "local:military-chat"},
        llm=llm,
    ).enhance(request)

    assert response.relations == []
    assert response.runtime.candidate_count == 0
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_document_llm_bounds_closed_candidate_pairs_before_model_call():
    request = _request().model_copy(
        update={
            "entities": [
                *_request().entities,
                DocumentREEntity(
                    entity_id="e3",
                    type="Component",
                    canonical_name="雷达前端",
                    mentions=[DocumentREMention(block_id="b1", text="雷达前端", start=7, end=11)],
                ),
            ],
            "options": DocumentREOptions(
                max_chars=1000,
                max_relations=12,
                max_candidate_pairs=1,
            ),
        }
    )
    llm = FakeLLM({"relations": []})

    await LightRAGDocumentRelationEnhancer(
        {"model_spec": "local:military-chat"},
        llm=llm,
    ).enhance(request)

    assert '"pair_ref":"doc-p1"' in llm.prompts[0]["prompt"]
    assert '"pair_ref":"doc-p2"' not in llm.prompts[0]["prompt"]
