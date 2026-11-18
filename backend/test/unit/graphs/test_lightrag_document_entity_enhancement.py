from __future__ import annotations

import pytest

from defense_document_entity_contract import (
    DocumentEntityBlock,
    DocumentEntityOptions,
    DocumentEntityRequest,
    DocumentEntityType,
    DocumentKnownEntity,
    DocumentEntityMention,
)
from platform_core.knowledge.graphs.lightrag_document_entity_enhancement import (
    LightRAGDocumentEntityEnhancer,
)


class FakeLLM:
    def __init__(self, output):
        self.outputs = output if isinstance(output, list) else [output]
        self.prompts = []
        self.closed = False

    async def complete_json(self, prompt, **kwargs):
        self.prompts.append({"prompt": prompt, **kwargs})
        return self.outputs[len(self.prompts) - 1]

    async def aclose(self):
        self.closed = True


def _request() -> DocumentEntityRequest:
    return DocumentEntityRequest(
        request_id="request-entity-1",
        stage_revision="document-entity-enhancement-v8",
        input_hash="a" * 64,
        pipeline_revision="hybrid-v2-r1",
        model_version="local:military-chat",
        ontology_version="defense-kg-1.0",
        document_id="doc-1",
        document_version=1,
        blocks=[
            DocumentEntityBlock(block_id="b1", text="氮化镓组件用于雷达前端", block_index=0),
            DocumentEntityBlock(block_id="b2", text="@AB宽带感知能力得到提升", block_index=1),
        ],
        known_entities=[
            DocumentKnownEntity(
                entity_id="e1",
                type="Component",
                canonical_name="氮化镓组件",
                mentions=[DocumentEntityMention(block_id="b1", text="氮化镓组件", start=0, end=5)],
            )
        ],
        entity_types=[
            DocumentEntityType(code="Component", name_zh="技术组件"),
            DocumentEntityType(code="Capability", name_zh="产品能力"),
        ],
        options=DocumentEntityOptions(max_chars=1000, max_candidates=10),
    )


def test_document_entity_structured_runtime_disables_thinking_and_budget_retry_by_default():
    enhancer = LightRAGDocumentEntityEnhancer({"model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"})

    assert enhancer.llm.options["enable_thinking"] is False
    assert enhancer.llm.options["max_truncation_retries"] == 0
    assert enhancer.max_entities_per_call == 24


def test_document_entity_output_budget_caps_entities_before_call():
    enhancer = LightRAGDocumentEntityEnhancer(
        {
            "model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
            "max_output_tokens": 2048,
            "max_entities_per_call": 24,
            "max_repair_proposals_per_call": 4,
        }
    )

    assert enhancer.max_entities_per_call == 12


@pytest.mark.asyncio
async def test_document_entity_enhancer_keeps_only_new_grounded_ontology_mentions():
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "b1",
                    "text": "氮化镓组件",
                    "type": "Component",
                    "start": 0,
                    "end": 5,
                    "confidence": 0.99,
                },
                {
                    "block_id": "b2",
                    "text": "宽带感知能力",
                    "type": "能力",
                    "start": 3,
                    "end": 9,
                    "confidence": 0.87,
                    "canonical_name": "复杂环境宽带感知能力",
                    "raw_name": "宽带感知能力",
                    "aliases": ["宽带感知"],
                    "naming_rationale": "保留能力对象并补充跨 Block 可确认的环境限定。",
                    "attributes": [{"label": "ResearchThread", "text": "main"}],
                },
                {
                    "block_id": "b2",
                    "text": "不存在",
                    "type": "Capability",
                    "start": 3,
                    "end": 6,
                    "confidence": 0.9,
                },
                {
                    "block_id": "b2",
                    "text": "@AB宽带感知能力",
                    "type": "Capability",
                    "start": 0,
                    "end": 9,
                    "confidence": 0.9,
                },
            ],
            "ocr_repair_proposals": [
                {
                    "block_id": "b2",
                    "start": 0,
                    "end": 3,
                    "original_text": "@AB",
                    "suggested_text": "AB",
                    "confidence": 0.8,
                    "reason": "疑似排版残留",
                }
            ],
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(_request())
    await enhancer.aclose()

    assert [(item.text, item.type, item.start, item.end) for item in response.entities] == [
        ("宽带感知能力", "Capability", 3, 9)
    ]
    assert response.entities[0].raw_name == "宽带感知能力"
    assert response.entities[0].canonical_name == "复杂环境宽带感知能力"
    assert response.entities[0].aliases == ["宽带感知", "宽带感知能力"]
    assert response.entities[0].naming_rationale.startswith("保留能力对象")
    assert response.entities[0].attributes == [{"label": "ResearchThread", "text": "main"}]
    assert response.repair_proposals[0].original_text == "@AB"
    assert '"max_entities":10' in llm.prompts[0]["prompt"]
    assert '"max_repair_proposals":4' in llm.prompts[0]["prompt"]
    assert response.normalization["output_budget"]["initial_entity_limit"] == 10
    assert response.input_hash == "a" * 64
    assert llm.prompts[0]["required_keys"] == ("entities",)
    assert "不得创建 canonical entity ID" in llm.prompts[0]["prompt"]
    assert "最完整、稳定、可复用的术语边界" in llm.prompts[0]["prompt"]
    assert "概念/需求 → 科学原理 → 关键技术/算法/材料/组件 → 能力 → 应用场景" in llm.prompts[0]["prompt"]
    assert "研究什么问题，面向什么对象、需求、环境或威胁" in llm.prompts[0]["prompt"]
    assert "领域限定词 + 核心对象 + 类型后缀" in llm.prompts[0]["prompt"]
    assert "canonical_name、aliases、naming_rationale" in llm.prompts[0]["prompt"]
    assert "不得把 Concept 错标为 Domain、Constraint" in llm.prompts[0]["prompt"]
    assert "在内部先按内容主线完成五问" in llm.prompts[0]["prompt"]
    assert "五类允许缺项，不得为凑齐主线造实体" in llm.prompts[0]["prompt"]
    assert "ResearchThread" in llm.prompts[0]["prompt"]
    assert "仿真、模拟、数字孪生" in llm.prompts[0]["prompt"]
    assert "样机、外场实测、系统应用" in llm.prompts[0]["prompt"]
    assert response.normalization["content_mainline"] == {
        "analysis_method": "concept-principle-technology-application-capability-five-questions",
        "available_roles": ["technology", "capability"],
        "present_roles": ["technology", "capability"],
        "missing_available_roles": [],
        "entity_counts": {
            "concept": 0,
            "principle": 0,
            "technology": 1,
            "capability": 1,
            "application": 0,
        },
        "missing_roles_are_allowed": True,
        "auto_fill_disabled": True,
    }
    assert llm.closed is True


@pytest.mark.asyncio
async def test_document_entity_enhancer_drops_unknown_block_and_type():
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "outside",
                    "text": "氮化镓组件",
                    "type": "Component",
                    "start": 0,
                    "end": 5,
                    "confidence": 0.9,
                },
                {
                    "block_id": "b1",
                    "text": "雷达前端",
                    "type": "Weapon",
                    "start": 7,
                    "end": 11,
                    "confidence": 0.9,
                },
            ]
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(_request())

    assert response.entities == []


@pytest.mark.asyncio
async def test_document_entity_enhancer_uses_reversible_layout_view_without_extra_llm_call():
    source_text = "集 中 式 MIMO 雷达用于多模式一体化波形设计"
    normalized_text = "集中式MIMO雷达"
    request_payload = _request().model_dump(mode="python")
    request_payload.update(
        {
            "blocks": [DocumentEntityBlock(block_id="layout", text=source_text, block_index=0)],
            "known_entities": [],
            "entity_types": [
                *_request().entity_types,
                DocumentEntityType(code="ProductSystem", name_zh="产品系统"),
            ],
        }
    )
    request = DocumentEntityRequest.model_validate(request_payload)
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "layout",
                    "text": normalized_text,
                    "type": "ProductSystem",
                    "start": 0,
                    "end": len(normalized_text),
                    "confidence": 0.94,
                }
            ]
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert len(llm.prompts) == 1
    assert normalized_text in llm.prompts[0]["prompt"]
    assert source_text not in llm.prompts[0]["prompt"]
    assert [(item.text, item.start, item.end) for item in response.entities] == [
        ("集 中 式 MIMO 雷达", 0, len("集 中 式 MIMO 雷达"))
    ]
    assert response.normalization["status"] == "applied"
    assert response.normalization["normalized_block_count"] == 1
    assert response.normalization["deletion_count"] == 4
    assert response.model_dump(mode="json")["entities"][0]["text"] == source_text[: len("集 中 式 MIMO 雷达")]


@pytest.mark.asyncio
async def test_document_entity_enhancer_rejects_clear_organization_candidate():
    organization = "中国电子科技集团公司第五十四研究所"
    request_payload = _request().model_dump(mode="python")
    request_payload.update(
        {
            "blocks": [DocumentEntityBlock(block_id="org", text=organization, block_index=0)],
            "known_entities": [],
            "entity_types": [
                *_request().entity_types,
                DocumentEntityType(code="ProductSystem", name_zh="产品系统"),
            ],
        }
    )
    request = DocumentEntityRequest.model_validate(request_payload)
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "org",
                    "text": organization,
                    "type": "ProductSystem",
                    "start": 0,
                    "end": len(organization),
                    "confidence": 0.99,
                }
            ]
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer({"model_spec": "local:military-chat"}, llm=llm)

    response = await enhancer.enhance(request)

    assert response.entities == []


@pytest.mark.asyncio
async def test_document_entity_enhancer_rejects_candidate_below_confidence_gate():
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "b1",
                    "text": "雷达前端",
                    "type": "Component",
                    "start": 7,
                    "end": 11,
                    "confidence": 0.84,
                }
            ]
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer(
        {"model_spec": "local:military-chat", "min_confidence": 0.85},
        llm=llm,
    )

    response = await enhancer.enhance(_request())

    assert response.entities == []


@pytest.mark.asyncio
async def test_document_entity_enhancer_adaptively_gleans_sparse_long_window():
    request_payload = _request().model_dump(mode="python")
    request_payload["blocks"][1]["text"] += "，雷达信号处理链路保持稳定" * 12
    request = DocumentEntityRequest.model_validate(request_payload)
    llm = FakeLLM(
        [
            {
                "entities": [
                    {
                        "block_id": "b1",
                        "text": "雷达前端",
                        "type": "Component",
                        "start": 7,
                        "end": 11,
                        "confidence": 0.92,
                    }
                ],
                "continuation_needed": False,
            },
            {
                "entities": [
                    {
                        "block_id": "b2",
                        "text": "宽带感知能力",
                        "type": "Capability",
                        "start": 3,
                        "end": 9,
                        "confidence": 0.91,
                    }
                ],
                "continuation_needed": False,
            },
        ]
    )
    enhancer = LightRAGDocumentEntityEnhancer(
        {
            "model_spec": "local:military-chat",
            "max_gleanings": 1,
            "gleaning_min_source_chars": 128,
            "gleaning_min_candidates": 2,
        },
        llm=llm,
    )

    response = await enhancer.enhance(request)

    assert [item.text for item in response.entities] == ["雷达前端", "宽带感知能力"]
    assert len(llm.prompts) == 2
    assert "第二轮查漏（gleaning）" in llm.prompts[1]["prompt"]
    assert "雷达前端" in llm.prompts[1]["prompt"]
    assert response.normalization["gleaning"] == {
        "enabled": True,
        "status": "completed",
        "max_gleanings": 1,
        "gleaning_calls": 1,
        "llm_calls": 2,
        "source_chars": sum(len(block.text) for block in request.blocks),
        "initial_candidate_count": 1,
        "gleaning_candidate_count": 1,
        "final_candidate_count": 2,
        "trigger_reasons": ["sparse_initial_candidates"],
        "initial_missing_available_roles": ["capability"],
    }


@pytest.mark.asyncio
async def test_document_entity_gleaning_targets_missing_available_five_role_recall():
    request = _request().model_copy(
        update={
            "blocks": [
                _request().blocks[0],
                _request().blocks[1].model_copy(
                    update={"text": _request().blocks[1].text + "，雷达信号处理链路保持稳定" * 12}
                ),
            ]
        }
    )
    llm = FakeLLM(
        [
            {
                "entities": [
                    {
                        "block_id": "b1",
                        "text": "雷达前端",
                        "type": "Component",
                        "start": 7,
                        "end": 11,
                        "confidence": 0.92,
                    }
                ],
                "continuation_needed": False,
            },
            {
                "entities": [
                    {
                        "block_id": "b2",
                        "text": "宽带感知能力",
                        "type": "Capability",
                        "start": 3,
                        "end": 9,
                        "confidence": 0.91,
                    }
                ],
                "continuation_needed": False,
            },
        ]
    )
    enhancer = LightRAGDocumentEntityEnhancer(
        {
            "model_spec": "local:military-chat",
            "max_gleanings": 1,
            "gleaning_min_source_chars": 128,
            "gleaning_min_candidates": 1,
            "gleaning_on_layout_damage": False,
            "gleaning_on_role_gap": True,
        },
        llm=llm,
    )

    response = await enhancer.enhance(request)

    assert len(llm.prompts) == 2
    assert response.normalization["gleaning"]["trigger_reasons"] == [
        "five_role_recall_gap:capability"
    ]
    assert "角色缺失只是复查信号，不是实体或关系证据" in llm.prompts[1]["prompt"]
    assert [item.text for item in response.entities] == ["雷达前端", "宽带感知能力"]


@pytest.mark.asyncio
async def test_document_entity_enhancer_does_not_glean_when_first_pass_is_sufficient():
    llm = FakeLLM(
        {
            "entities": [
                {
                    "block_id": "b1",
                    "text": "雷达前端",
                    "type": "Component",
                    "start": 7,
                    "end": 11,
                    "confidence": 0.92,
                }
            ],
            "continuation_needed": False,
        }
    )
    enhancer = LightRAGDocumentEntityEnhancer(
        {
            "model_spec": "local:military-chat",
            "max_gleanings": 1,
            "gleaning_min_source_chars": 128,
            "gleaning_min_candidates": 1,
            "gleaning_on_layout_damage": False,
        },
        llm=llm,
    )

    response = await enhancer.enhance(_request())

    assert len(llm.prompts) == 1
    assert response.normalization["gleaning"]["status"] == "skipped_not_needed"
    assert response.normalization["gleaning"]["llm_calls"] == 1
