from __future__ import annotations

from copy import deepcopy

import pytest

from platform_core.knowledge.training.graph_retrieval_quality import evaluate_graph_retrieval_quality
from platform_core.knowledge.training.graph_retrieval_review import (
    finalize_blinded_graph_retrieval_review,
    prepare_blinded_graph_retrieval_review,
)


def _snapshots() -> list[dict]:
    records = []
    for method in ("keyword", "entity_vector", "triple_vector", "lightrag_hybrid", "lightrag_mix"):
        records.append(
            {
                "query_id": "q-1",
                "query": "哪些技术跨文档支撑探测能力？",
                "method": method,
                "retrieved_entity_ids": ["e1", "e2"],
                "retrieved_triple_ids": ["r1", "r2"],
                "retrieved_paths": [
                    {
                        "path_id": f"{method}-path",
                        "relation_ids": ["r1", "r2"],
                        "chunk_ids": ["c1", "c2"],
                        "file_ids": ["f1", "f2"],
                    }
                ],
            }
        )
    return records


def _complete_review(review: dict) -> dict:
    completed = deepcopy(review)
    completed["judgment"] = {
        "source": "human",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-11-03T11:00:00+08:00",
        "guideline_version": "defense-kg-retrieval-review-v1",
    }
    for run in completed["runs"]:
        run["gold_entity_ids"] = ["e1", "e2"]
        run["gold_triple_ids"] = ["r1", "r2"]
        for path in run["retrieved_paths"]:
            path["valid"] = True
            path["relevant"] = True
    return completed


def test_blind_review_hides_methods_and_finalizes_a_complete_human_matrix():
    review, key = prepare_blinded_graph_retrieval_review(_snapshots(), blind_key="fixed-test-key")

    assert all("method" not in run for run in review["runs"])
    assert {item["method"] for item in key["mapping"]} == {
        "keyword",
        "entity_vector",
        "triple_vector",
        "lightrag_hybrid",
        "lightrag_mix",
    }

    cases = finalize_blinded_graph_retrieval_review(_complete_review(review), key)
    report = evaluate_graph_retrieval_quality(cases)

    assert len(cases) == 5
    assert report["complete"] is True
    assert report["human_judgment_complete"] is True
    assert report["reviewer_ids"] == ["reviewer-1"]


def test_blind_review_refuses_incomplete_methods_and_unfinished_judgments():
    with pytest.raises(ValueError, match="方法矩阵不完整"):
        prepare_blinded_graph_retrieval_review(_snapshots()[:-1], blind_key="fixed-test-key")

    review, key = prepare_blinded_graph_retrieval_review(_snapshots(), blind_key="fixed-test-key")
    incomplete = _complete_review(review)
    incomplete["runs"][0]["retrieved_paths"][0]["relevant"] = None

    with pytest.raises(ValueError, match="未判断 relevant"):
        finalize_blinded_graph_retrieval_review(incomplete, key)


def test_blind_review_refuses_mismatched_key():
    review, key = prepare_blinded_graph_retrieval_review(_snapshots(), blind_key="fixed-test-key")
    key["input_fingerprint_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="输入指纹不一致"):
        finalize_blinded_graph_retrieval_review(_complete_review(review), key)
