from __future__ import annotations

import pytest

from platform_core.knowledge.training.graph_retrieval_quality import (
    GraphRetrievalQualityCase,
    evaluate_graph_retrieval_quality,
    graph_retrieval_quality_gate,
)


def _case(method: str, *, entity_ids: list[str], triple_ids: list[str], valid=True, relevant=True):
    return {
        "query_id": "q-1",
        "query": "复杂电磁环境探测能力",
        "method": method,
        "gold_entity_ids": ["e1", "e2"],
        "gold_triple_ids": ["r1", "r2"],
        "retrieved_entity_ids": entity_ids,
        "retrieved_triple_ids": triple_ids,
        "retrieved_paths": [
            {
                "path_id": f"path-{method}",
                "relation_ids": ["r1", "r2"],
                "chunk_ids": ["c1", "c2"],
                "file_ids": ["f1", "f2"],
                "valid": valid,
                "relevant": relevant,
            }
        ],
        "judgment": {
            "source": "human",
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-11-03T10:00:00+08:00",
            "guideline_version": "defense-kg-retrieval-review-v1",
        },
    }


def test_retrieval_quality_reports_rank_metrics_cross_document_paths_and_synergy():
    records = [
        _case("keyword", entity_ids=["noise", "e1"], triple_ids=["noise", "r1"]),
        _case("entity_vector", entity_ids=["e1", "noise"], triple_ids=["r1"]),
        _case("triple_vector", entity_ids=["e2"], triple_ids=["r2", "noise"]),
        _case("lightrag_hybrid", entity_ids=["e1", "e2"], triple_ids=["r1", "r2"]),
        _case("lightrag_mix", entity_ids=["e1", "e2"], triple_ids=["r1", "r2"]),
    ]

    report = evaluate_graph_retrieval_quality(records, k=2)

    assert report["complete"] is True
    assert report["methods"]["lightrag_hybrid"]["entity"]["recall_at_k"] == 1.0
    assert report["methods"]["lightrag_hybrid"]["entity"]["mrr"] == 1.0
    assert report["methods"]["lightrag_hybrid"]["entity"]["ndcg_at_k"] == 1.0
    assert report["methods"]["lightrag_hybrid"]["cross_document_path_validity"] == 1.0
    assert report["synergy"]["lightrag_hybrid_vs_best_single"]["composite_gain"] > 0
    assert all(item["passed"] for item in graph_retrieval_quality_gate(report))


def test_retrieval_quality_refuses_incomplete_or_inconsistent_paired_contracts():
    one = _case("lightrag_hybrid", entity_ids=["e1"], triple_ids=["r1"])
    report = evaluate_graph_retrieval_quality([one], k=2)
    assert report["complete"] is False
    assert graph_retrieval_quality_gate(report)[0]["passed"] is False

    inconsistent = _case("entity_vector", entity_ids=["e1"], triple_ids=["r1"])
    inconsistent["gold_entity_ids"] = ["different"]
    with pytest.raises(ValueError, match="共享相同"):
        evaluate_graph_retrieval_quality([one, inconsistent], k=2)


def test_retrieval_quality_rejects_duplicate_ranked_ids():
    payload = _case("keyword", entity_ids=["e1", "e1"], triple_ids=["r1"])

    with pytest.raises(ValueError, match="不得包含重复"):
        GraphRetrievalQualityCase.model_validate(payload)


def test_retrieval_quality_gate_rejects_missing_human_judgment_provenance():
    records = [
        _case(method, entity_ids=["e1", "e2"], triple_ids=["r1", "r2"])
        for method in ("keyword", "entity_vector", "triple_vector", "lightrag_hybrid", "lightrag_mix")
    ]
    for record in records:
        record.pop("judgment")

    report = evaluate_graph_retrieval_quality(records, k=2)
    gates = {item["id"]: item for item in graph_retrieval_quality_gate(report)}

    assert report["human_judgment_complete"] is False
    assert gates["retrieval_human_judgments_complete"]["passed"] is False
