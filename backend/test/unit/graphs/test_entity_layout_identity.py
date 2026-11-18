from __future__ import annotations

from platform_core.knowledge.graphs.graph_utils import (
    canonical_entity_display_name,
    normalize_entity_name,
)
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService


def test_entity_identity_removes_only_cjk_internal_layout_gaps():
    assert canonical_entity_display_name("定\r\n向能") == "定向能"
    assert normalize_entity_name("激 光器") == "激光器"
    assert normalize_entity_name("Light RAG") == "light rag"
    assert normalize_entity_name("MIMO 雷达") == "mimo 雷达"
    assert canonical_entity_display_name("recur-\nrent neural units") == "recurrent neural units"


def test_entity_master_uses_clean_name_while_mention_preserves_raw_span_text():
    service = object.__new__(MilvusGraphService)
    records = service._build_entity_records(
        "kb-test",
        [
            {
                "text": "定\r\n向能",
                "label": "KeyTechnology",
                "start": 4,
                "end": 9,
                "confidence": 0.9,
            }
        ],
        {"metadata": {"model_version": "test", "ontology_version": "defense-kg-1.0"}},
    )

    assert records[0]["normalized_name"] == "定向能"
    assert records[0]["name"] == "定向能"
    assert records[0]["mention_text"] == "定\r\n向能"
    assert records[0]["start_char"] == 4
    assert records[0]["end_char"] == 9


def test_entity_master_repairs_latin_line_wrap_without_rewriting_mention_span():
    service = object.__new__(MilvusGraphService)
    records = service._build_entity_records(
        "kb-test",
        [
            {
                "text": "recur-\nrent neural units",
                "label": "Component",
                "start": 10,
                "end": 34,
                "confidence": 0.9,
            }
        ],
        {"metadata": {"model_version": "test", "ontology_version": "defense-kg-1.0"}},
    )

    assert records[0]["normalized_name"] == "recurrent neural units"
    assert records[0]["name"] == "recurrent neural units"
    assert records[0]["mention_text"] == "recur-\nrent neural units"
