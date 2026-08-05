"""Risk-based final audit routing.

Quality defects belong in the producing stage.  The final audit decides release;
it must not become another full research or repeated expert-review loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AuditReviewDecision:
    model_review_required: bool
    expert_judge_present: bool
    expert_judge_passed: bool
    reason: str


def decide_final_audit_review(
    *,
    trace_events: Sequence[Any],
    deterministic_status: str,
    stage_outputs: Sequence[Any],
    capability_images: Sequence[Any],
    evidence_count: int,
) -> AuditReviewDecision:
    """Use one expert judgement at most, then rely on deterministic release gates."""

    swarm_summary = _latest_swarm_summary(trace_events)
    portfolio_gate = swarm_summary.get("portfolio_quality_gate", {})
    if not isinstance(portfolio_gate, Mapping):
        portfolio_gate = {}
    expert_status = str(portfolio_gate.get("expert_judge_status", "")).lower()
    expert_present = bool(expert_status) or bool(
        portfolio_gate.get("expert_assessed_count")
    )
    expert_passed = bool(portfolio_gate.get("expert_judge_passed")) and (
        expert_status in {"", "completed"}
    )
    if expert_present:
        return AuditReviewDecision(
            model_review_required=False,
            expert_judge_present=True,
            expert_judge_passed=expert_passed,
            reason=(
                "quality_expert_judge_completed"
                if expert_passed
                else "quality_expert_judge_blocked_release"
            ),
        )

    has_deterministic_gap = (
        deterministic_status != "approved"
        or not stage_outputs
        or any(not bool(getattr(item, "gate_passed", False)) for item in stage_outputs)
        or not capability_images
        or any(not getattr(item, "evidence_ids", []) for item in capability_images)
        or evidence_count <= 0
    )
    return AuditReviewDecision(
        model_review_required=True,
        expert_judge_present=False,
        expert_judge_passed=False,
        reason=(
            "single_final_auditor_for_detected_risk"
            if has_deterministic_gap
            else "single_final_auditor_without_upstream_expert"
        ),
    )


def _latest_swarm_summary(trace_events: Sequence[Any]) -> dict[str, Any]:
    for event in reversed(trace_events):
        if getattr(event, "event_type", "") != "swarm_gate_evaluated":
            continue
        payload = getattr(event, "payload", {})
        if not isinstance(payload, Mapping):
            continue
        summary = payload.get("swarm_summary", {})
        if isinstance(summary, Mapping) and summary:
            return dict(summary)
    return {}
