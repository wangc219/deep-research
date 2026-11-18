from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from platform_core.knowledge.graphs.extractors.lightrag_enhancement import LightRAGQualityEnhancer
from platform_core.knowledge.graphs.lightrag_adaptive_routing import (
    decide_lightrag_adaptive_routing,
    normalize_adaptive_routing_options,
)


def _clean_result(*, relations: bool = True) -> dict:
    entities = [
        {
            "id": "component",
            "text": "氮化镓功率放大器",
            "label": "Component",
            "start": 0,
            "end": 8,
            "confidence": 0.96,
        },
        {
            "id": "capability",
            "text": "雷达探测能力",
            "label": "Capability",
            "start": 10,
            "end": 16,
            "confidence": 0.94,
        },
    ]
    relation_rows = []
    if relations:
        relation_rows.append(
            {
                "source": "component",
                "target": "capability",
                "label": "ENABLES_CAPABILITY",
                "confidence": 0.93,
                "evidence_spans": [{"start": 0, "end": 16}],
            }
        )
    return {"entities": entities, "relations": relation_rows, "metadata": {"feasible": True, "warnings": []}}


def test_adaptive_routing_preserves_full_enhancement_when_disabled():
    decision = decide_lightrag_adaptive_routing(
        "氮化镓功率放大器提升雷达探测能力",
        _clean_result(),
        {"enabled": False},
    )

    assert decision["should_enhance"] is True
    assert decision["decision"] == "enhance"
    assert decision["trigger_reasons"] == []


def test_adaptive_routing_skips_clean_dense_block_and_records_metrics():
    decision = decide_lightrag_adaptive_routing(
        "氮化镓功率放大器提升雷达探测能力",
        _clean_result(),
        {"enabled": True},
    )

    assert decision["should_enhance"] is False
    assert decision["decision"] == "skip"
    assert decision["metrics"]["entity_count"] == 2
    assert decision["metrics"]["relation_count"] == 1
    assert decision["metrics"]["ocr_damage_count"] == 0


@pytest.mark.parametrize(
    ("text", "result", "reason"),
    [
        ("脉冲@AB电源用于雷达探测", _clean_result(), "ocr_damage"),
        ("集 中 式 MIMO 雷达用于目标探测", _clean_result(), "layout_damage"),
        (
            "雷达波形设计用于复杂电磁环境目标探测与识别" * 4,
            {"entities": [], "relations": [], "metadata": {}},
            "technical_text_without_entities",
        ),
        (
            "氮化镓功率放大器提升雷达探测能力",
            _clean_result(relations=False),
            "multiple_entities_without_relation",
        ),
        (
            "氮化镓功率放大器提升雷达探测能力",
            {
                **_clean_result(),
                "entities": [{**_clean_result()["entities"][0], "confidence": 0.6}],
            },
            "low_confidence_candidates",
        ),
        (
            "氮化镓功率放大器提升雷达探测能力",
            {**_clean_result(), "metadata": {"feasible": False, "warnings": ["partial"]}},
            "backend_warning",
        ),
    ],
)
def test_adaptive_routing_triggers_on_quality_gap(text, result, reason):
    decision = decide_lightrag_adaptive_routing(text, result, {"enabled": True})

    assert decision["should_enhance"] is True
    assert reason in decision["trigger_reasons"]


def test_adaptive_routing_detects_generic_substantive_text_without_domain_dictionary_hit():
    decision = decide_lightrag_adaptive_routing(
        "Protein folding dynamics reveal stable molecular interactions under changing temperature conditions.",
        {"entities": [], "relations": [], "metadata": {}},
        {"enabled": True, "min_source_chars": 20},
    )

    assert decision["should_enhance"] is True
    assert "substantive_text_without_entities" in decision["trigger_reasons"]
    assert decision["metrics"]["technical_signal_count"] == 0
    assert decision["metrics"]["lexical_unit_count"] >= 4


def test_adaptive_routing_rejects_invalid_config():
    with pytest.raises(ValueError, match="adaptive_routing.enabled"):
        normalize_adaptive_routing_options({"enabled": "yes"})
    with pytest.raises(ValueError, match="low_confidence_threshold"):
        normalize_adaptive_routing_options({"low_confidence_threshold": 2})


@pytest.mark.asyncio
async def test_quality_enhancer_skips_both_llm_stages_for_clean_block():
    llm = Mock()
    llm.validate_options = Mock()
    llm.complete_json = AsyncMock()
    llm.aclose = AsyncMock()
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "max_gleanings": 1,
            "entity_review_mode": "off",
            "adaptive_routing": {"enabled": True},
        },
        llm=llm,
    )
    text = "氮化镓功率放大器提升雷达探测能力"

    initial = await enhancer.enhance_initial(text, _clean_result())
    final = await enhancer.glean(text, initial)

    assert llm.complete_json.await_count == 0
    report = final["metadata"]["llm_enhancement"]
    assert report["status"] == "skipped_adaptive"
    assert report["initial_status"] == "skipped_adaptive"
    assert report["gleaning_status"] == "skipped_adaptive"
    assert report["adaptive_routing"]["decision"] == "skip"


@pytest.mark.asyncio
async def test_quality_enhancer_runs_initial_llm_for_relation_gap():
    llm = Mock()
    llm.validate_options = Mock()
    llm.complete_json = AsyncMock(return_value={"entities": [], "relations": []})
    llm.aclose = AsyncMock()
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "max_gleanings": 0,
            "entity_review_mode": "off",
            "adaptive_routing": {"enabled": True},
        },
        llm=llm,
    )

    result = await enhancer.enhance_initial(
        "氮化镓功率放大器提升雷达探测能力",
        _clean_result(relations=False),
    )

    assert llm.complete_json.await_count == 1
    routing = result["metadata"]["llm_enhancement"]["adaptive_routing"]
    assert routing["decision"] == "enhance"
    assert "multiple_entities_without_relation" in routing["trigger_reasons"]


@pytest.mark.asyncio
async def test_quality_enhancer_suppresses_reference_section_even_when_adaptive_routing_is_disabled():
    llm = Mock()
    llm.validate_options = Mock()
    llm.complete_json = AsyncMock()
    llm.aclose = AsyncMock()
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "max_gleanings": 1,
            "entity_review_mode": "off",
            "adaptive_routing": {"enabled": False},
        },
        llm=llm,
    )
    text = (
        "[45] SMITH J, LEE K. Robust learning methods[J]. Journal of Systems, 2021:10-20.\n"
        "[46] WANG A, CHEN B. Adversarial training[C]//Proceedings of International Conference, 2022:1-9."
    )

    initial = await enhancer.enhance_initial(text, {"entities": [], "relations": [], "metadata": {}})
    final = await enhancer.glean(text, initial)

    assert llm.complete_json.await_count == 0
    report = final["metadata"]["llm_enhancement"]
    assert report["initial_status"] == "skipped_reference_section"
    assert report["gleaning_status"] == "skipped_reference_section"
    assert report["reference_section"]["is_reference_section"] is True
