from __future__ import annotations

from types import SimpleNamespace

from equipment_deep_research.orchestration.audit_policy import (
    decide_final_audit_review,
)


def _event(gate: dict) -> SimpleNamespace:
    return SimpleNamespace(
        event_type="swarm_gate_evaluated",
        payload={"swarm_summary": {"portfolio_quality_gate": gate}},
    )


def test_completed_expert_judge_prevents_duplicate_model_audit() -> None:
    decision = decide_final_audit_review(
        trace_events=[
            _event(
                {
                    "expert_judge_status": "completed",
                    "expert_judge_passed": True,
                    "expert_assessed_count": 6,
                }
            )
        ],
        deterministic_status="approved",
        stage_outputs=[SimpleNamespace(gate_passed=True)],
        capability_images=[SimpleNamespace(evidence_ids=["ev-1"])],
        evidence_count=4,
    )

    assert decision.expert_judge_present is True
    assert decision.expert_judge_passed is True
    assert decision.model_review_required is False


def test_failed_expert_judge_blocks_release_without_second_opinion_loop() -> None:
    decision = decide_final_audit_review(
        trace_events=[
            _event(
                {
                    "expert_judge_status": "completed",
                    "expert_judge_passed": False,
                    "expert_assessed_count": 4,
                }
            )
        ],
        deterministic_status="approved",
        stage_outputs=[SimpleNamespace(gate_passed=True)],
        capability_images=[SimpleNamespace(evidence_ids=["ev-1"])],
        evidence_count=4,
    )

    assert decision.expert_judge_present is True
    assert decision.expert_judge_passed is False
    assert decision.model_review_required is False


def test_single_final_auditor_is_kept_when_no_upstream_expert_exists() -> None:
    decision = decide_final_audit_review(
        trace_events=[],
        deterministic_status="limited",
        stage_outputs=[SimpleNamespace(gate_passed=False)],
        capability_images=[],
        evidence_count=0,
    )

    assert decision.expert_judge_present is False
    assert decision.model_review_required is True


def test_dynamic_swarm_uses_internal_innovation_audit_without_second_model() -> None:
    decision = decide_final_audit_review(
        trace_events=[],
        deterministic_status="limited",
        stage_outputs=[],
        capability_images=[],
        evidence_count=0,
        execution_profile_id="winning_swarm_dynamic_v2",
    )

    assert decision.model_review_required is False
    assert decision.reason == "dynamic_swarm_internal_innovation_audit"
