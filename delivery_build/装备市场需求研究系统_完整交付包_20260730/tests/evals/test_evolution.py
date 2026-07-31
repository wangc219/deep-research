from __future__ import annotations

from pathlib import Path

import pytest

from evals.evolution import EvolutionRegistry, build_query_residuals
from evals.models import PAIRWISE_V1_DIMENSIONS, read_jsonl, write_jsonl


def test_evolution_registry_requires_human_approval(tmp_path: Path) -> None:
    registry = EvolutionRegistry(tmp_path)

    with pytest.raises(ValueError, match="human approval"):
        registry.activate("optimized_v2", actor="admin")

    registry.approve("optimized_v2", actor="admin")
    activated = registry.activate("optimized_v2", actor="admin")
    rolled_back = registry.rollback(actor="admin")

    assert activated["champion_profile_id"] == "optimized_v2"
    assert rolled_back["champion_profile_id"] == "legacy_v1"


def test_query_residual_marks_test_and_custom_prompt_as_exploratory(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval"
    pair_root = eval_root / "pairs" / "generic_agent"
    pair_root.mkdir(parents=True)
    queries_path = tmp_path / "queries.jsonl"
    write_jsonl(
        queries_path,
        [{"query_id": "Q-0001", "query": "q", "region": "r", "domain": "d", "difficulty": "easy", "split": "test"}],
    )
    write_jsonl(
        pair_root / "pairs.admin.jsonl",
        [{"pair_id": "P-1", "query_id": "Q-0001", "system_a": "full_method", "system_b": "generic_agent", "reversed": False}],
    )
    write_jsonl(
        eval_root / "judgments.generic_agent.jsonl",
        [{
            "pair_id": "P-1",
            "judge_id": "judge",
            "winner": "B",
            "confidence": 0.9,
            "dimensions": {dimension: "B" for dimension in PAIRWISE_V1_DIMENSIONS},
            "reason": "baseline better",
            "citation_issues": [],
            "hard_failures": [],
        }],
    )

    residuals = build_query_residuals(
        eval_id="eval",
        eval_root=eval_root,
        queries_path=queries_path,
        baselines=["generic_agent"],
        execution_profile_id="optimized_v2",
        exploratory_only=False,
    )

    assert residuals[0].exploratory_only is True
    assert all(value == 1.0 for value in residuals[0].nine_dimension_gaps.values())
    assert read_jsonl(eval_root / "query_residuals.jsonl")[0]["query_id"] == "Q-0001"
