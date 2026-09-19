from __future__ import annotations

import json

import pytest

from evals.deep_dialogue import evaluate_jsonl, score_deep_dialogue_case


def _direction(name: str, mechanism: str) -> dict:
    return {
        "name": name,
        "primary_equipment_identity": "参考拦截无人机",
        "changed_assumption": f"假设-{name}",
        "equipment_form": f"构型-{name}",
        "operational_mechanism": mechanism,
        "decisive_target": "目标任务链",
        "mission_kill_criterion": "关键任务周期中断",
        "disruptive_difference": f"差异-{name}",
        "failure_boundary": f"边界-{name}",
        "stable": False,
    }


def test_structural_benchmark_rewards_diverse_closed_and_adversarial_result() -> None:
    score = score_deep_dialogue_case(
        {
            "case_id": "quality",
            "canonical_identity": {
                "primary_equipment_identity": "参考拦截无人机"
            },
            "s6_confirmed": False,
            "result": {
                "concept_directions": [
                    _direction("甲", "自主复核"),
                    _direction("乙", "诱骗识别"),
                    _direction("丙", "协同封控"),
                ],
                "adjudication": {"retained": ["甲", "乙"]},
                "research_gaps": ["诱骗环境需验证"],
                "open_questions": ["任务窗口多长"],
                "runtime": {"tools": ["diverge", "challenge"]},
            },
        }
    )

    assert score.identity_lock == 1
    assert score.direction_diversity == 1
    assert score.causal_closure == 1
    assert score.adversarial_depth == 1
    assert score.uncertainty_retention == 1
    assert score.loop_efficiency == 1
    assert score.s6_confirmation == 1
    assert score.total == 1
    assert score.failures == ()


def test_structural_benchmark_detects_identity_switch_repetition_and_s6_bypass() -> None:
    repeated = _direction("甲", "同一机理")
    repeated["primary_equipment_identity"] = "另一个装备"
    repeated.pop("failure_boundary")
    repeated["stable"] = True
    score = score_deep_dialogue_case(
        {
            "case_id": "regression",
            "canonical_identity": {
                "primary_equipment_identity": "参考拦截无人机"
            },
            "s6_confirmed": False,
            "result": {
                "concept_directions": [repeated, dict(repeated)],
                "capability_card_draft": {"overview": "未确认成卡"},
                "runtime": {"tools": ["deepen", "deepen", "author_s6"]},
            },
        }
    )

    assert score.total < 0.65
    assert {
        "canonical_identity_changed",
        "directions_repeat_same_mechanism",
        "adversarial_boundary_too_thin",
        "uncertainty_erased",
        "repeated_domain_action",
        "s6_without_user_confirmation",
    } <= set(score.failures)


def test_jsonl_benchmark_aggregates_real_provider_captures(tmp_path) -> None:
    path = tmp_path / "deep-results.jsonl"
    rows = [
        {
            "case_id": name,
            "canonical_identity": {
                "primary_equipment_identity": "参考拦截无人机"
            },
            "result": {
                "concept_directions": [_direction(name, f"机理-{name}")],
                "research_gaps": ["待验证"],
                "runtime": {"tools": ["deepen"]},
            },
        }
        for name in ("a", "b")
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    report = evaluate_jsonl(path)

    assert report["schema_version"] == "deep-dialogue-benchmark-v1"
    assert report["case_count"] == 2
    assert report["means"]["identity_lock"] == 1
    assert len(report["cases"]) == 2


def test_jsonl_benchmark_rejects_empty_input(tmp_path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        evaluate_jsonl(path)
