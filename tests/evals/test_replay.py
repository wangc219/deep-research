from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.replay import (
    ReplayObservation,
    ReplayPolicy,
    aggregate_replay,
    build_replay_manifest,
    load_replay_fixture,
    validate_replay_fixture,
)


def _fixture(path: Path, count: int = 3) -> Path:
    rows = [
        {
            "query_id": f"Q-EV-{index:04d}",
            "query": f"测试问题 {index}",
            "region": "台海",
            "domain": "无人系统",
            "difficulty": "medium",
            "split": "pilot",
            "target_stages": ["S1", "S4", "S6"],
            "residual_tags": ["evidence_boundary"],
            "target_metrics": ["evidence_and_factuality"],
            "seed": "fixture-v1",
        }
        for index in range(1, count + 1)
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _observations(*, include_neither: bool = False, hard_failure: bool = False) -> list[ReplayObservation]:
    rows: list[ReplayObservation] = []
    arms = ("prompt_only", "memory_only", "both") + (("neither",) if include_neither else ())
    quality = {"prompt_only": 0.60, "memory_only": 0.62, "both": 0.72, "neither": 0.50}
    for query_index in range(1, 4):
        for arm in arms:
            rows.append(
                ReplayObservation(
                    eval_id="replay-test",
                    query_id=f"Q-EV-{query_index:04d}",
                    arm=arm,
                    quality_score=quality[arm],
                    hard_failures=("schema",) if hard_failure and arm == "both" else (),
                    token_count=100 if arm != "both" else 110,
                    estimated_cost=1.0 if arm != "both" else 1.1,
                    duration_seconds=10 if arm != "both" else 11,
                    metric_scores={"evidence_and_factuality": quality[arm]},
                )
            )
    return rows


def test_fixed_fixture_is_valid_and_manifest_is_portable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl")
    metadata = validate_replay_fixture(fixture, expected_seed="fixture-v1", expected_count=3)
    assert metadata["valid"] is True
    assert metadata["query_count"] == 3
    assert not metadata["fixture_path"].startswith("/")
    assert [row["query_id"] for row in load_replay_fixture(fixture, expected_seed="fixture-v1")] == [
        "Q-EV-0001",
        "Q-EV-0002",
        "Q-EV-0003",
    ]

    manifest = build_replay_manifest(
        fixture_path=fixture,
        eval_id="replay-test",
        bundle_id="bundle-1",
        seed="fixture-v1",
        project_root=tmp_path,
    )
    assert manifest["fixture_path"] == "fixture.jsonl"
    assert manifest["dataset_snapshot"] == manifest["fixture_sha256"]


def test_manifest_uses_explicit_project_root_for_nested_fixture(tmp_path: Path) -> None:
    project_root = tmp_path / "checkout"
    fixture = project_root / "evals" / "fixtures" / "pilot.jsonl"
    fixture.parent.mkdir(parents=True)
    _fixture(fixture)
    manifest = build_replay_manifest(
        fixture_path=fixture,
        eval_id="replay-nested",
        bundle_id="bundle-1",
        seed="fixture-v1",
        project_root=project_root,
    )
    assert manifest["fixture_path"] == "evals/fixtures/pilot.jsonl"


def test_three_arm_replay_reports_paired_effect_and_passes_gate(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl")
    summary = aggregate_replay(
        _observations(),
        fixture=fixture,
        eval_id="replay-test",
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        policy=ReplayPolicy(
            min_quality_delta=0.03,
            max_cost_increase=0.20,
            max_latency_increase=0.20,
        ),
        bootstrap_samples=100,
        seed=7,
    )

    assert summary["complete_case_count"] == 3
    assert summary["effects"]["both_vs_prompt_only"]["delta"] == pytest.approx(0.12)
    assert summary["effects"]["both_vs_prompt_only"]["ci"][0] >= 0.03
    assert summary["gate"]["verdict"] == "pass"
    assert summary["arms"]["both"]["p95_duration_seconds"] == pytest.approx(11.0)


def test_four_arm_replay_exposes_prompt_memory_and_interaction_effects(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl")
    summary = aggregate_replay(
        _observations(include_neither=True),
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both", "neither"),
        reference_arm="neither",
        candidate_arm="both",
        policy={"min_quality_delta": 0.03, "max_cost_increase": 0.20, "max_latency_increase": 0.20},
        bootstrap_samples=100,
        seed=7,
    )
    assert summary["gate"]["passed"] is True
    assert summary["effects"]["prompt_main_effect"]["delta"] == pytest.approx(0.10)
    assert summary["effects"]["memory_main_effect"]["delta"] == pytest.approx(0.12)
    assert "interaction" in summary["effects"]


def test_hard_failure_fails_closed_even_when_quality_improves(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl")
    summary = aggregate_replay(
        _observations(hard_failure=True),
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
    )
    assert summary["gate"]["verdict"] == "fail"
    assert "hard_failure_present" in summary["gate"]["reasons"]


def test_direct_observation_normalizes_numeric_strings_before_aggregation(tmp_path: Path) -> None:
    """Direct constructors must preserve the same numeric invariant as JSON rows."""

    fixture = _fixture(tmp_path / "fixture.jsonl", count=1)
    rows = [
        ReplayObservation(
            eval_id="replay-test",
            query_id="Q-EV-0001",
            arm=arm,
            quality_score=str(0.72 if arm == "both" else 0.60),
            token_count="110" if arm == "both" else "100",
            estimated_cost="1.1" if arm == "both" else "1.0",
            duration_seconds="11" if arm == "both" else "10",
            non_target_regression="0",
            metric_scores={"evidence_and_factuality": str(0.72 if arm == "both" else 0.60)},
        )
        for arm in ("prompt_only", "memory_only", "both")
    ]

    summary = aggregate_replay(
        rows,
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
        seed=7,
    )

    assert summary["gate"]["verdict"] == "pass"
    assert rows[0].quality_score == pytest.approx(0.60)
    assert rows[0].token_count == pytest.approx(100.0)
    assert rows[0].metric_scores["evidence_and_factuality"] == pytest.approx(0.60)


def test_missing_arm_is_inconclusive_and_fixture_mismatch_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl")
    rows = [row for row in _observations() if not (row.query_id == "Q-EV-0003" and row.arm == "memory_only")]
    summary = aggregate_replay(
        rows,
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
    )
    assert summary["gate"]["verdict"] == "inconclusive"
    assert "incomplete_query_arm_pairs" in summary["gate"]["reasons"]
    with pytest.raises(ValueError, match="seed mismatch"):
        validate_replay_fixture(fixture, expected_seed="wrong-seed")


@pytest.mark.parametrize("arms", [(), ("both",), ("prompt_only", "both")])
def test_replay_requires_all_three_attribution_arms(
    tmp_path: Path, arms: tuple[str, ...]
) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl", count=1)
    with pytest.raises(ValueError, match="prompt_only, memory_only and both"):
        aggregate_replay(
            _observations(),
            fixture=fixture,
            expected_arms=arms,
            reference_arm="prompt_only",
            candidate_arm="both",
            bootstrap_samples=100,
        )


def test_replay_missing_required_observed_arm_cannot_pass(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl", count=1)
    rows = [
        row
        for row in _observations()
        if row.arm != "memory_only"
    ]
    summary = aggregate_replay(
        rows,
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
    )
    assert summary["gate"]["passed"] is False
    assert "required_arm_not_observed" in summary["gate"]["reasons"]
    assert "incomplete_query_arm_pairs" in summary["gate"]["reasons"]
    assert summary["gate"]["verdict"] == "fail"


def test_replay_manifest_requires_all_three_attribution_arms(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "fixture.jsonl", count=1)
    with pytest.raises(ValueError, match="prompt_only, memory_only and both"):
        build_replay_manifest(
            fixture_path=fixture,
            eval_id="replay-test",
            bundle_id="bundle-1",
            arms=("prompt_only", "both"),
            seed="fixture-v1",
            project_root=tmp_path,
        )


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_non_completed_observations_fail_closed_even_when_pairs_are_present(
    tmp_path: Path, status: str
) -> None:
    """A complete arm matrix must not turn failed executions into a pass."""

    fixture = _fixture(tmp_path / "fixture.jsonl", count=1)
    rows = [
        ReplayObservation(
            eval_id="replay-test",
            query_id="Q-EV-0001",
            arm=arm,
            quality_score=0.72 if arm == "both" else 0.60,
            status=status,
        )
        for arm in ("prompt_only", "memory_only", "both")
    ]
    summary = aggregate_replay(
        rows,
        fixture=fixture,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
        seed=7,
    )

    assert summary["gate"]["verdict"] == "fail"
    assert "incomplete_arm_execution" in summary["gate"]["reasons"]
    assert "hard_failure_present" in summary["gate"]["reasons"]
    assert summary["arms"]["both"]["completed_count"] == 0
