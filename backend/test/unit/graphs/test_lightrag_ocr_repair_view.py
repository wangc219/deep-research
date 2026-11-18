from __future__ import annotations

from platform_core.knowledge.graphs.lightrag_ocr_repair_view import (
    build_ocr_repaired_text_view,
    candidates_for_repaired_view,
    partition_repaired_view_candidates,
)


def test_repaired_view_preserves_source_and_maps_only_unambiguous_boundaries():
    source = "脉冲@AB电源采用匹配滤波算法"
    start = source.index("@AB")
    view = build_ocr_repaired_text_view(
        source,
        [
            {
                "original_start": start,
                "original_end": start + 3,
                "original_text": "@AB",
                "suggested_text": "功率",
                "confidence": 0.97,
                "reason": "上下文可恢复",
            }
        ],
        min_confidence=0.85,
        max_proposals=4,
    )

    assert view.original_text == source
    assert view.repaired_text == "脉冲功率电源采用匹配滤波算法"
    assert view.repaired_span_to_original(start + 1, start + 2) is None
    clean_start = view.repaired_text.index("匹配滤波算法")
    mapped = view.repaired_span_to_original(clean_start, clean_start + 6)
    assert mapped is not None
    assert mapped.repair_dependent is False
    assert source[mapped.start : mapped.end] == "匹配滤波算法"


def test_equal_length_repair_has_boundary_map_but_remains_repair_dependent():
    source = "脉冲@AB电源"
    start = source.index("@AB")
    view = build_ocr_repaired_text_view(
        source,
        [
            {
                "original_start": start,
                "original_end": start + 3,
                "original_text": "@AB",
                "suggested_text": "功率源",
                "confidence": 0.99,
                "reason": "等长修复",
            }
        ],
        min_confidence=0.85,
        max_proposals=4,
    )

    mapped = view.repaired_span_to_original(start, start + 3)
    assert mapped is not None
    assert mapped.start == start
    assert mapped.end == start + 3
    assert mapped.repair_dependent is True


def test_overlapping_low_confidence_and_invalid_proposals_never_rewrite_source():
    source = "A@AB=>?B"
    view = build_ocr_repaired_text_view(
        source,
        [
            {
                "original_start": 1,
                "original_end": 4,
                "original_text": "@AB",
                "suggested_text": "技术",
                "confidence": 0.95,
                "reason": "候选一",
            },
            {
                "original_start": 2,
                "original_end": 7,
                "original_text": "AB=>?",
                "suggested_text": "组件",
                "confidence": 0.99,
                "reason": "重叠候选",
            },
            {
                "original_start": 4,
                "original_end": 7,
                "original_text": "=>?",
                "suggested_text": "连接",
                "confidence": 0.2,
                "reason": "低置信度",
            },
        ],
        min_confidence=0.85,
        max_proposals=4,
    )

    assert view.original_text == source
    assert len(view.patches) == 1
    assert {item["rejection_reason"] for item in view.rejected_proposals} == {
        "overlapping_proposal",
        "below_min_confidence",
    }


def test_partition_keeps_clean_candidates_and_isolates_repair_dependent_candidates():
    source = "脉冲@AB电源采用匹配滤波算法提升距离分辨能力"
    damage_start = source.index("@AB")
    view = build_ocr_repaired_text_view(
        source,
        [
            {
                "original_start": damage_start,
                "original_end": damage_start + 3,
                "original_text": "@AB",
                "suggested_text": "功率",
                "confidence": 0.98,
                "reason": "术语上下文",
            }
        ],
        min_confidence=0.85,
        max_proposals=4,
    )
    algorithm_start = view.repaired_text.index("匹配滤波算法")
    capability_start = view.repaired_text.index("距离分辨能力")
    damaged_entity_end = view.repaired_text.index("电源") + 2
    prepared = {
        "entities": [
            {
                "id": "damaged",
                "text": view.repaired_text[:damaged_entity_end],
                "label": "KeyTechnology",
                "start": 0,
                "end": damaged_entity_end,
                "confidence": 0.9,
            },
            {
                "id": "algorithm",
                "text": "匹配滤波算法",
                "label": "AlgorithmModel",
                "start": algorithm_start,
                "end": algorithm_start + 6,
                "confidence": 0.95,
            },
            {
                "id": "capability",
                "text": "距离分辨能力",
                "label": "Capability",
                "start": capability_start,
                "end": capability_start + 6,
                "confidence": 0.94,
            },
        ],
        "relations": [
            {
                "source": {"id": "algorithm"},
                "target": {"id": "capability"},
                "label": "ENABLES_CAPABILITY",
                "evidence_spans": [
                    {"start": algorithm_start, "end": capability_start + 6},
                ],
            },
            {
                "source": {"id": "damaged"},
                "target": {"id": "capability"},
                "label": "ENABLES_CAPABILITY",
                "evidence_spans": [{"start": 0, "end": capability_start + 6}],
            },
        ],
        "metadata": {},
    }

    partitioned = partition_repaired_view_candidates(prepared, view, original_known_entities=[])

    assert {item["id"] for item in partitioned["entities"]} == {"algorithm", "capability"}
    assert len(partitioned["relations"]) == 1
    assert (
        source[
            partitioned["relations"][0]["evidence_spans"][0]["start"] : partitioned["relations"][0]["evidence_spans"][
                0
            ]["end"]
        ]
        == "匹配滤波算法提升距离分辨能力"
    )
    isolated = partitioned["metadata"]["repair_dependent_candidates"]
    assert isolated["authority_eligible"] is False
    assert [item["id"] for item in isolated["entities"]] == ["damaged"]
    assert len(isolated["relations"]) == 1


def test_existing_candidates_are_mapped_without_copying_repair_dependent_evidence():
    source = "脉冲@AB电源采用匹配滤波算法"
    damage_start = source.index("@AB")
    algorithm_start = source.index("匹配滤波算法")
    view = build_ocr_repaired_text_view(
        source,
        [
            {
                "original_start": damage_start,
                "original_end": damage_start + 3,
                "original_text": "@AB",
                "suggested_text": "功率",
                "confidence": 0.99,
                "reason": "术语上下文",
            }
        ],
        min_confidence=0.85,
        max_proposals=4,
    )
    mapped = candidates_for_repaired_view(
        {
            "entities": [
                {
                    "id": "algorithm",
                    "text": "匹配滤波算法",
                    "label": "AlgorithmModel",
                    "start": algorithm_start,
                    "end": algorithm_start + 6,
                },
                {
                    "id": "damaged",
                    "text": "@AB",
                    "label": "Component",
                    "start": damage_start,
                    "end": damage_start + 3,
                },
            ],
            "relations": [],
        },
        view,
    )

    assert [item["id"] for item in mapped["entities"]] == ["algorithm"]
    assert view.repaired_text[mapped["entities"][0]["start"] : mapped["entities"][0]["end"]] == "匹配滤波算法"
