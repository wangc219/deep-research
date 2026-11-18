import pytest

from scripts.benchmark_relation_profile_retrieval import (
    _cases,
    _ranking_metrics,
    _records,
)


def test_runtime_probe_compares_same_relations_with_only_profile_content_changed():
    cases = _cases()
    baseline = {item["id"]: item for item in _records(cases, profile=False)}
    profile = {item["id"]: item for item in _records(cases, profile=True)}

    assert baseline.keys() == profile.keys()
    assert baseline["relation-antijamming"]["source_id"] == profile["relation-antijamming"]["source_id"]
    assert baseline["relation-antijamming"]["target_id"] == profile["relation-antijamming"]["target_id"]
    assert "频率捷变使接收链" not in baseline["relation-antijamming"]["content"]
    assert "频率捷变使接收链" in profile["relation-antijamming"]["content"]
    assert "独立来源数：2" in profile["relation-antijamming"]["content"]


def test_runtime_probe_ranking_metrics_use_missing_and_ranked_gold_consistently():
    metrics = _ranking_metrics(
        [
            {"rank": 1},
            {"rank": 2},
            {"rank": None},
            {"rank": 6},
        ],
        k=5,
    )

    assert metrics == pytest.approx(
        {
            "recall_at_5": 0.5,
            "mrr": (1 + 0.5 + 0 + 1 / 6) / 4,
            "ndcg_at_5": (1 + 1 / 1.584962500721156 + 0 + 0) / 4,
        }
    )
