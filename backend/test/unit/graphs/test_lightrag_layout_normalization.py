from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from platform_core.knowledge.graphs.extractors.lightrag_enhancement import LightRAGQualityEnhancer
from platform_core.knowledge.graphs.lightrag_layout_normalization import (
    build_layout_normalized_text_view,
    candidates_for_layout_view,
    remap_layout_view_candidates,
)


def test_normalizes_known_cjk_layout_fragments_without_rewriting_characters():
    source = "信 息 对 抗 技 术\n摘\n\n要\n集中式 MIMO 雷达"

    view = build_layout_normalized_text_view(source)

    assert view.original_text == source
    assert view.normalized_text == "信息对抗技术\n摘要\n集中式MIMO雷达"
    assert {item.reason for item in view.deletions} == {
        "cjk_intercharacter_layout_space",
        "split_cjk_section_label",
        "cjk_technical_token_boundary",
        "technical_token_cjk_boundary",
    }


def test_preserves_english_word_spaces_punctuation_tables_and_paragraph_boundaries():
    source = "Light RAG 方法；雷达, MIMO\n正文结束\n\n下一段\n雷达\t阵列"

    view = build_layout_normalized_text_view(source)

    assert "Light RAG" in view.normalized_text
    assert "方法；雷达, MIMO" in view.normalized_text
    assert "正文结束\n\n下一段" in view.normalized_text
    assert "雷达\t阵列" in view.normalized_text


def test_normalized_span_maps_back_to_raw_evidence_with_layout_whitespace():
    source = "集中式 MIMO 雷达采用匹配滤波"
    view = build_layout_normalized_text_view(source)
    normalized = "集中式MIMO雷达"
    start = view.normalized_text.index(normalized)

    mapped = view.normalized_span_to_original(start, start + len(normalized))

    assert mapped is not None
    assert mapped.normalization_dependent is True
    assert source[mapped.start : mapped.end] == "集中式 MIMO 雷达"


def test_existing_candidates_are_mapped_for_deduplication_and_restore_original_span():
    source = "集中式 MIMO 雷达采用匹配滤波算法"
    original_start = source.index("匹配滤波算法")
    view = build_layout_normalized_text_view(source)
    mapped = candidates_for_layout_view(
        {
            "entities": [
                {
                    "id": "algorithm",
                    "text": "匹配滤波算法",
                    "label": "AlgorithmModel",
                    "start": original_start,
                    "end": original_start + 6,
                }
            ],
            "relations": [],
        },
        view,
    )

    assert mapped["entities"][0]["text"] == "匹配滤波算法"
    assert view.normalized_text[mapped["entities"][0]["start"] : mapped["entities"][0]["end"]] == "匹配滤波算法"


def test_remapped_candidates_keep_raw_mentions_and_pending_authority_status():
    source = "集中式 MIMO 雷达采用匹配滤波算法提升探测能力"
    view = build_layout_normalized_text_view(source)
    radar_text = "集中式MIMO雷达"
    algorithm_text = "匹配滤波算法"
    radar_start = view.normalized_text.index(radar_text)
    algorithm_start = view.normalized_text.index(algorithm_text)
    evidence_end = view.normalized_text.index("探测能力") + 4
    prepared = {
        "entities": [
            {
                "id": "radar",
                "text": radar_text,
                "label": "ProductSystem",
                "start": radar_start,
                "end": radar_start + len(radar_text),
                "confidence": 0.94,
            },
            {
                "id": "algorithm",
                "text": algorithm_text,
                "label": "AlgorithmModel",
                "start": algorithm_start,
                "end": algorithm_start + len(algorithm_text),
                "confidence": 0.95,
            },
        ],
        "relations": [
            {
                "source": {"id": "radar"},
                "target": {"id": "algorithm"},
                "label": "USES_TECHNOLOGY",
                "evidence_spans": [{"start": radar_start, "end": evidence_end}],
            }
        ],
        "metadata": {},
    }

    remapped = remap_layout_view_candidates(prepared, view, original_known_entities=[])

    radar = next(item for item in remapped["entities"] if item["id"] == "radar")
    assert radar["text"] == "集中式 MIMO 雷达"
    assert radar["normalized_text"] == radar_text
    assert radar["review_status"] == "pending"
    assert radar["expert_review_required"] is True
    assert radar["layout_normalized_by_platform"] is True
    relation = remapped["relations"][0]
    span = relation["evidence_spans"][0]
    assert source[span["start"] : span["end"]] == "集中式 MIMO 雷达采用匹配滤波算法提升探测能力"
    assert relation["evidence_quote"] == ""
    assert remapped["metadata"]["original_text_preserved"] is True
    assert remapped["metadata"]["authority_write_enabled"] is False


@pytest.mark.asyncio
async def test_layout_hint_strengthens_initial_extraction_without_extra_llm_call():
    source = "集中式 MIMO 雷达采用匹配滤波算法"
    radar = "集中式 MIMO 雷达"
    radar_start = source.index(radar)
    llm = Mock()
    llm.validate_options = Mock()
    llm.aclose = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={
            "entities": [
                {
                    "id": "layout-radar",
                    "text": radar,
                    "label": "ProductSystem",
                    "start": radar_start,
                    "end": radar_start + len(radar),
                    "confidence": 0.96,
                }
            ],
            "relations": [],
            "ocr_repair_proposals": [],
        }
    )
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "entity_review_mode": "off",
            "layout_normalization": {"enabled": True},
            "max_gleanings": 0,
        },
        llm=llm,
    )

    result = await enhancer.enhance_initial(
        source,
        {"entities": [], "relations": [], "metadata": {}},
    )

    assert llm.complete_json.await_count == 1
    assert result["entities"][0]["text"] == "集中式 MIMO 雷达"
    prompt = llm.complete_json.await_args.args[0]
    assert prompt.count('"continuous_excerpt":"集中式MIMO雷达采用匹配滤波算法"') == 2
    report = result["metadata"]["llm_enhancement"]["layout_normalization"]
    assert report["status"] == "merged_into_initial_prompt"
    assert report["llm_calls"] == 0
    assert report["hint_count"] == 2
    assert report["authority_write_enabled"] is False


@pytest.mark.asyncio
async def test_layout_view_skips_redundant_llm_call_when_spaces_only_border_ocr_damage():
    source = "该方案可产生 0$.+ 左右功率，长度约为 ,0 英尺"
    llm = Mock()
    llm.validate_options = Mock()
    llm.aclose = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={"entities": [], "relations": [], "ocr_repair_proposals": []}
    )
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "entity_review_mode": "off",
            "layout_normalization": {"enabled": True},
            "max_gleanings": 0,
        },
        llm=llm,
    )

    result = await enhancer.enhance_initial(
        source,
        {"entities": [], "relations": [], "metadata": {}},
    )

    assert llm.complete_json.await_count == 1
    report = result["metadata"]["llm_enhancement"]["layout_normalization"]
    assert report["status"] == "skipped_ocr_damage_only"
    assert report["llm_calls"] == 0
    assert report["ocr_adjacent_deletion_count"] == report["deletion_count"]
