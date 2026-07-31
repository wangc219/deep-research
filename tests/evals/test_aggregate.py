from pathlib import Path

from evals.aggregate import aggregate_pairwise, bootstrap_interval
from evals.models import write_jsonl


DIMENSIONS = {
    "task_fulfillment": "A",
    "facts_and_citations": "A",
    "analysis_depth": "A",
    "equipment_demand_value": "A",
    "uncertainty": "A",
}


def test_aggregate_maps_reversed_pairs_back_to_systems(tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "mapping.jsonl",
        [
            {"pair_id": "P-1", "query_id": "Q-1", "system_a": "full_method", "system_b": "generic_deep_research", "reversed": False},
            {"pair_id": "P-2", "query_id": "Q-1", "system_a": "generic_deep_research", "system_b": "full_method", "reversed": True},
        ],
    )
    write_jsonl(
        tmp_path / "judgments.jsonl",
        [
            {"pair_id": "P-1", "judge_id": "J1", "winner": "A", "confidence": 0.8, "dimensions": DIMENSIONS, "reason": "", "citation_issues": [], "hard_failures": []},
            {"pair_id": "P-2", "judge_id": "J1", "winner": "B", "confidence": 0.8, "dimensions": {key: "B" for key in DIMENSIONS}, "reason": "", "citation_issues": [], "hard_failures": []},
        ],
    )
    summary = aggregate_pairwise(tmp_path / "judgments.jsonl", tmp_path / "mapping.jsonl", bootstrap_samples=200)
    assert summary["systems"]["full_method"]["wins"] == 1
    assert summary["systems"]["full_method"]["score_rate"] == 1.0


def test_bootstrap_interval_is_bounded() -> None:
    lower, upper = bootstrap_interval([1.0, 0.5, 0.0], samples=200, seed=7)
    assert 0 <= lower <= upper <= 1


def test_aggregate_ignores_legacy_communication_efficiency_votes(tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "mapping.jsonl",
        [{"pair_id": "P-legacy", "query_id": "Q-1", "system_a": "full_method", "system_b": "generic_agent", "reversed": False}],
    )
    legacy_dimensions = {**DIMENSIONS, "communication_efficiency": "B"}
    write_jsonl(
        tmp_path / "judgments.jsonl",
        [{"pair_id": "P-legacy", "judge_id": "J1", "winner": "tie", "confidence": 0.8, "dimensions": legacy_dimensions, "reason": "", "citation_issues": [], "hard_failures": []}],
    )
    summary = aggregate_pairwise(
        tmp_path / "judgments.jsonl",
        tmp_path / "mapping.jsonl",
        bootstrap_samples=100,
    )
    assert "communication_efficiency" not in summary["dimension_votes"]
