from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import pytest

from platform_core.knowledge.graphs.lightrag_document_value_routing import (
    DOCUMENT_VALUE_ROUTING_VERSION,
    LightRAGDocumentValueRouter,
)


def _document() -> dict:
    text = "本文提出新型高光谱激光雷达架构，可提升复杂电磁环境下高超声速目标探测能力。"
    return {
        "document_id": "doc-1",
        "document_version": 1,
        "title": "高光谱激光雷达研究",
        "blocks": [{"block_id": "b1", "page": 1, "heading_path": ["摘要"], "text": text}],
    }


@pytest.mark.asyncio
async def test_document_value_router_requires_grounded_high_novel_military_evidence():
    document = _document()
    text = document["blocks"][0]["text"]
    evidence_text = "提升复杂电磁环境下高超声速目标探测能力"
    start = text.index(evidence_text)
    llm = Mock()
    llm.complete_json = AsyncMock(
        return_value={
            "military_relevance": "direct",
            "novelty": "emerging",
            "priority": "high",
            "confidence": 0.92,
            "dimensions": ["探测感知", "复杂环境适应"],
            "reason": "原文同时给出新架构与复杂环境目标探测能力收益",
            "evidence": [{"block_id": "b1", "start": start, "end": start + len(evidence_text)}],
        }
    )
    llm.aclose = AsyncMock()
    router = LightRAGDocumentValueRouter({"model_spec": "project:model"}, llm=llm)

    result = await router.assess(document, {"signals": {}, "military_value_code": "military"})

    assert result["version"] == DOCUMENT_VALUE_ROUTING_VERSION
    assert result["focused_reextraction_recommended"] is True
    assert result["evidence"][0]["text"] == evidence_text
    assert result["expert_review_required"] is True


@pytest.mark.asyncio
async def test_document_value_router_downgrades_unlocatable_model_evidence():
    llm = Mock()
    llm.complete_json = AsyncMock(
        return_value={
            "military_relevance": "direct",
            "novelty": "breakthrough",
            "priority": "high",
            "confidence": 0.99,
            "dimensions": ["关键技术跃迁"],
            "reason": "模型声称价值很高",
            "evidence": [{"block_id": "invented", "start": 0, "end": 10}],
        }
    )
    llm.aclose = AsyncMock()
    router = LightRAGDocumentValueRouter({"model_spec": "project:model"}, llm=llm)

    result = await router.assess(_document(), {"signals": {}, "military_value_code": "military"})

    assert result["focused_reextraction_recommended"] is False
    assert result["evidence"] == []
    assert result["rejected_evidence_count"] == 1


def test_document_value_router_rejects_out_of_range_threshold():
    with pytest.raises(ValueError, match="min_confidence"):
        LightRAGDocumentValueRouter({"model_spec": "project:model", "min_confidence": 1.1})


@pytest.mark.asyncio
async def test_document_value_router_samples_conclusion_and_excludes_references():
    document = _document()
    document["blocks"] = [
        {"block_id": "b1", "page": 1, "heading_path": ["引言"], "text": "背景介绍。" * 2000},
        {
            "block_id": "b2",
            "page": 8,
            "heading_path": ["结论与展望"],
            "text": "实验证明新架构提升了复杂环境下的目标探测能力。",
        },
        {
            "block_id": "b3",
            "page": 9,
            "heading_path": ["参考文献"],
            "text": "[1] ZHANG A, LI B. Radar study[J]. Journal, 2024:1-9.\n"
            "[2] WANG C, ZHAO D. Sensor study[J]. Proceedings, 2023:2-8.",
        },
    ]
    llm = Mock()
    llm.complete_json = AsyncMock(
        return_value={
            "military_relevance": "general",
            "novelty": "incremental",
            "priority": "normal",
            "confidence": 0.7,
            "dimensions": [],
            "reason": "不足以进入重点复抽",
            "evidence": [],
        }
    )
    llm.aclose = AsyncMock()
    router = LightRAGDocumentValueRouter({"model_spec": "project:model"}, llm=llm)

    await router.assess(document, {"signals": {}, "military_value_code": "general"})

    prompt = llm.complete_json.await_args.args[0]
    block_payload = json.loads(prompt.split("原文 Block：", 1)[1])
    assert {item["block_id"] for item in block_payload} == {"b1", "b2"}
    assert next(item for item in block_payload if item["block_id"] == "b2")["text"].startswith("实验证明")
