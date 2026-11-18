import asyncio

import pytest

from platform_core.knowledge.graphs.lightrag_evidence_summary import LightRAGEvidenceSummarySelector
from platform_core.knowledge.graphs.pipeline_config import normalize_pipeline_options


@pytest.mark.asyncio
async def test_evidence_summary_is_disabled_by_default():
    called = False

    async def complete(_prompt):
        nonlocal called
        called = True
        return {}

    selector = LightRAGEvidenceSummarySelector(completion=complete)
    result = await selector.enhance_records([{"id": "e1", "content": "雷达", "evidence_rows": []}])

    assert result[0]["content"] == "雷达"
    assert called is False


@pytest.mark.asyncio
async def test_evidence_summary_renders_only_exact_accepted_rows():
    async def complete(prompt):
        assert "不得生成、概括或改写" in prompt
        return {
            "selected_evidence_ids": [
                "relation-mention:9",
                "forged:1",
                "relation-mention:9",
                "entity-mention:2",
            ]
        }

    selector = LightRAGEvidenceSummarySelector(
        {
            "enabled": True,
            "model_spec": "local:military-chat",
            "source_text_policy": "local_only",
            "max_selected": 2,
        },
        completion=complete,
    )
    result = await selector.enhance_records(
        [
            {
                "id": "e1",
                "content": "宽带射频收发器\n实体类型：Component",
                "evidence_rows": [
                    {
                        "evidence_id": "entity-mention:2",
                        "kind": "entity_mention",
                        "text": "宽带射频模块",
                    },
                    {
                        "evidence_id": "relation-mention:9",
                        "kind": "relation_evidence",
                        "text": "采用频率捷变提高复杂电磁环境下的抗干扰能力。",
                    },
                ],
            }
        ]
    )

    content = result[0]["content"]
    assert "[relation-mention:9] 采用频率捷变提高复杂电磁环境下的抗干扰能力。" in content
    assert "[entity-mention:2] 宽带射频模块" in content
    assert "forged" not in content
    assert result[0]["evidence_summary"]["selected_count"] == 2
    assert result[0]["evidence_summary"]["authoritative_write"] is False


@pytest.mark.asyncio
async def test_evidence_summary_degrades_or_raises_by_policy():
    async def fail(_prompt):
        raise RuntimeError("model unavailable")

    record = {
        "id": "e1",
        "content": "材料",
        "evidence_rows": [{"evidence_id": "m:1", "text": "高温烧蚀率降低。"}],
    }
    selector = LightRAGEvidenceSummarySelector(
        {
            "enabled": True,
            "model_spec": "local:model",
            "source_text_policy": "local_only",
            "strict": False,
        },
        completion=fail,
    )
    result = await selector.enhance_records([record])
    assert result[0]["content"] == "材料"
    assert result[0]["evidence_summary"]["status"] == "degraded"

    strict = LightRAGEvidenceSummarySelector(
        {
            "enabled": True,
            "model_spec": "local:model",
            "source_text_policy": "local_only",
            "strict": True,
        },
        completion=fail,
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        await strict.enhance_records([record])


@pytest.mark.asyncio
async def test_evidence_summary_refuses_unapproved_source_text_destination():
    selector = LightRAGEvidenceSummarySelector(
        {
            "enabled": True,
            "model_spec": "external:model",
            "source_text_policy": "local_only",
        },
        completion=lambda _prompt: None,
    )

    with pytest.raises(ValueError, match="拒绝未登记"):
        await selector.enhance_records(
            [
                {
                    "id": "e1",
                    "content": "材料",
                    "evidence_rows": [{"evidence_id": "m:1", "text": "耐高温"}],
                }
            ]
        )


@pytest.mark.asyncio
async def test_evidence_summary_bounds_parallel_model_calls():
    active = 0
    peak = 0

    async def complete(_prompt):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"selected_evidence_ids": ["m:1"]}

    selector = LightRAGEvidenceSummarySelector(
        {
            "enabled": True,
            "model_spec": "local:model",
            "source_text_policy": "local_only",
            "concurrency": 2,
        },
        completion=complete,
    )
    records = [
        {
            "id": f"e{index}",
            "content": "材料",
            "evidence_rows": [{"evidence_id": "m:1", "text": "耐高温"}],
        }
        for index in range(6)
    ]

    result = await selector.enhance_records(records)

    assert len(result) == 6
    assert peak == 2


def test_pipeline_normalizes_evidence_summary_as_optional_retrieval_only_feature():
    base = {"llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"}}
    disabled = normalize_pipeline_options("lightrag_primary", base)
    assert disabled["retrieval_evidence_summary"] == {"enabled": False}

    enabled = normalize_pipeline_options(
        "lightrag_primary",
        {
            **base,
            "retrieval_evidence_summary": {
                "enabled": True,
                "model_spec": "local:military-chat",
                "source_text_policy": "local_only",
                "max_selected": 8,
            }
        },
    )
    summary = enabled["retrieval_evidence_summary"]
    assert summary["enabled"] is True
    assert summary["extractive_only"] is True
    assert summary["authoritative_write"] is False
    assert summary["max_selected"] == 8
    assert summary["concurrency"] == 4

    with pytest.raises(ValueError, match="source_text_policy"):
        normalize_pipeline_options(
            "lightrag_primary",
            {
                **base,
                "retrieval_evidence_summary": {
                    "enabled": True,
                    "model_spec": "external:model",
                }
            },
        )

    with pytest.raises(ValueError, match="本地模型提供方"):
        normalize_pipeline_options(
            "lightrag_primary",
            {
                **base,
                "retrieval_evidence_summary": {
                    "enabled": True,
                    "model_spec": "external:model",
                    "source_text_policy": "local_only",
                }
            },
        )
