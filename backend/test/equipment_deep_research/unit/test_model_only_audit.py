from __future__ import annotations

from types import SimpleNamespace

from equipment_deep_research.orchestration.audit_policy import decide_final_audit_review
from equipment_deep_research.orchestration.reporting import audit_run
from equipment_deep_research.orchestration.runner import (
    _apply_frontier_innovation_policy,
    _apply_model_audit_result,
)
from equipment_deep_research.domain.store import DomainStore


def test_audit_work_item_has_no_deterministic_release_status() -> None:
    audit = audit_run(store=DomainStore(), coverage={}, max_rounds=1)
    assert audit.status == "pending"
    assert audit.audit_source == "model"
    assert audit.hard_blockers == []
    assert audit.substantive_checks == {}
    assert audit.mechanical_diagnostics


def test_model_response_is_the_only_status_source() -> None:
    audit = audit_run(store=DomainStore(), coverage={"coverage_passed": False}, max_rounds=1)
    reviewed = _apply_model_audit_result(
        audit,
        {
            "audit_status": "approved",
            "substantive_checks": {
                "military_relevance": True,
                "causal_coherence": False,
            },
            "hard_blockers": [],
            "advisories": ["建议补充反证"],
            "risk_summary": "业务方向成立，性能仍需验证。",
        },
    )
    assert reviewed.status == "approved"
    assert reviewed.audit_source == "model"
    assert reviewed.substantive_checks["causal_coherence"] is False
    assert reviewed.hard_blockers == []


def test_model_review_is_always_routed_even_after_upstream_judgement() -> None:
    decision = decide_final_audit_review(
        trace_events=[],
        deterministic_status="approved",
        stage_outputs=[SimpleNamespace(gate_passed=True)],
        capability_images=[SimpleNamespace(evidence_ids=["ev-1"])],
        evidence_count=1,
        execution_profile_id="winning_swarm_dynamic_v2",
    )
    assert decision.model_review_required is True
    assert decision.expert_judge_present is False


def test_frontier_policy_defers_missing_proof_without_hard_blocking() -> None:
    audit = audit_run(store=DomainStore(), coverage={}, max_rounds=1)
    reviewed = _apply_model_audit_result(
        audit,
        {
            "audit_status": "limited",
            "substantive_checks": {
                "innovation_new_quality": True,
                "foresight": True,
                "scientific_plausibility": True,
                "implementability": True,
            },
            "hard_blockers": [
                "缺少装备级实证、误伤评估和法律适用材料。"
            ],
        },
    )
    frontier = _apply_frontier_innovation_policy(
        reviewed, execution_profile_id="winning_swarm_dynamic_v2"
    )
    assert frontier.status == "approved"
    assert frontier.hard_blockers == []
    assert frontier.model_review["research_posture"] == "frontier_innovation"
    assert frontier.model_review["validation_status"] == "not_audited_this_round"
    assert frontier.model_review["non_core_audit_status"] == "not_judged"


def test_frontier_policy_keeps_explicit_operational_safety_blocking() -> None:
    audit = audit_run(store=DomainStore(), coverage={}, max_rounds=1)
    reviewed = _apply_model_audit_result(
        audit,
        {
            "audit_status": "limited",
            "substantive_checks": {
                "innovation_new_quality": True,
                "foresight": True,
                "scientific_plausibility": True,
                "implementability": True,
            },
            "hard_blockers": ["包含可直接执行的攻击步骤。"],
        },
    )
    frontier = _apply_frontier_innovation_policy(
        reviewed, execution_profile_id="winning_swarm_dynamic_v2"
    )
    assert frontier.status == "limited"
    assert frontier.hard_blockers == ["包含可直接执行的攻击步骤。"]
