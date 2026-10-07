from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunStagePolicy:
    """Immutable stage controls used by evaluation-only ablation runs.

    Production callers resolve to ``full_method`` and therefore preserve the
    existing baseline, winning and L1-L4 behavior.
    """

    policy_id: str
    winning_enabled: bool = True
    feedback_loops_enabled: bool = True
    meta_loop_enabled: bool = True
    baseline_report_only: bool = False
    evidence_closed: bool = False

    @property
    def is_ablation(self) -> bool:
        return self.policy_id != "full_method"


POLICIES: dict[str, RunStagePolicy] = {
    "full_method": RunStagePolicy(policy_id="full_method"),
    "no_multisource_baseline": RunStagePolicy(
        policy_id="no_multisource_baseline",
        # This ablation removes only the specialist multi-source baseline.
        # S1-S6 and L1-L4 must remain identical to the full method, otherwise
        # the measured effect is confounded with removal of feedback loops.
        feedback_loops_enabled=True,
        meta_loop_enabled=True,
        # Keep S1-S6/L1-L4 structurally identical while preventing the model
        # from recreating the removed specialist baseline from latent
        # knowledge. Query text defines scope, not an additional fact source.
        evidence_closed=True,
    ),
    "no_winning_mechanism": RunStagePolicy(
        policy_id="no_winning_mechanism",
        winning_enabled=False,
        feedback_loops_enabled=False,
        meta_loop_enabled=False,
        baseline_report_only=True,
    ),
}


def resolve_run_stage_policy(policy_id: str | None) -> RunStagePolicy:
    key = str(policy_id or "full_method").strip() or "full_method"
    try:
        return POLICIES[key]
    except KeyError as exc:
        raise ValueError(f"unknown run stage policy: {key}") from exc


__all__ = ["POLICIES", "RunStagePolicy", "resolve_run_stage_policy"]
