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
    execution_profile_id: str = "",
) -> AuditReviewDecision:
    """Route one short model audit.

    The deterministic audit is retained by the caller only as a compatibility
    diagnostic. It is never an alternative decision source, including for
    dynamic-swarm runs or runs that already contain an upstream expert judge.
    """

    summary = _latest_swarm_summary(trace_events)

    # The swarm gate has had two serialized shapes in the wild.  Older
    # traces put the expert judgement under ``portfolio_quality_gate`` while
    # newer traces expose the S5 fields directly on ``swarm_summary``.  Read
    # both forms so a completed judgement is never mistaken for an absent one
    # (which would otherwise schedule a duplicate model audit).
    portfolio_gate = summary.get("portfolio_quality_gate", {})
    if not isinstance(portfolio_gate, Mapping):
        portfolio_gate = {}
    expert_status = str(
        portfolio_gate.get("expert_judge_status", summary.get("expert_judge_status", ""))
        or ""
    ).strip().lower()
    expert_count = portfolio_gate.get(
        "expert_assessed_count", summary.get("expert_assessed_count", 0)
    )
    expert_present = bool(
        summary.get("expert_judge_present")
        or portfolio_gate.get("expert_judge_present")
        or expert_status
        or expert_count
        or summary.get("dynamic_s5_passed")
    )
    raw_passed = portfolio_gate.get(
        "expert_judge_passed", summary.get("expert_judge_passed", False)
    )
    expert_passed = bool(raw_passed or summary.get("dynamic_s5_passed"))
    # A failed/unfinished status must not be upgraded merely because a stale
    # boolean was persisted alongside it.
    if expert_status and expert_status not in {"completed", "passed", "approved"}:
        expert_passed = False

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

    # Dynamic swarm runs can already contain an internal innovation audit.  A
    # sparse/limited run has no useful second-opinion payload, so preserve the
    # historical no-duplicate-auditor route.  Once concrete stage/card/evidence
    # material is present, the independent model review remains the authority
    # (the model-only audit contract).
    if (
        execution_profile_id == "winning_swarm_dynamic_v2"
        and deterministic_status != "approved"
        and not stage_outputs
        and not capability_images
        and evidence_count <= 0
    ):
        return AuditReviewDecision(
            model_review_required=False,
            expert_judge_present=False,
            expert_judge_passed=False,
            reason="dynamic_swarm_internal_innovation_audit",
        )

    # A completed optimized harness already contains an explicit S5 business
    # judgement. Re-running a second auditor adds latency and creates a
    # competing verdict; route directly to the existing judgement.
    if execution_profile_id == "optimized_v2":
        return AuditReviewDecision(False, True, True, "upstream_s5_business_judgement")
    has_deterministic_gap = deterministic_status != "approved"
    return AuditReviewDecision(True, expert_present, expert_passed,
        "short_model_audit_after_diagnostics" if has_deterministic_gap else "short_model_audit")


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
