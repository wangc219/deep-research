"""Physical cohort execution used by optimized_v2 on the first cycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from equipment_deep_research.contracts.runtime import BudgetRuntime


async def run_optimized_steps(
    selected_steps: Sequence[int],
    *,
    middle_cycle: int,
    middle_feedback: list[str] | None,
    accumulated: dict[str, Any],
    commit_step: Callable[..., Any],
    run_step: Callable[..., Any],
    step_dependency_map: Mapping[int, Sequence[int]],
    host: BudgetRuntime,
    loop_trace: list[dict[str, Any]],
    physical_cohorts: Sequence[tuple[int, ...]],
    primary_branch: str,
    run_physical_cohort: Callable[..., Any],
    run_tactic_validation_wave: Callable[..., Any],
) -> None:
    """Schedule dependency-ready cohorts; preserve per-stage commits and validation."""
    selected = set(selected_steps)
    selected_cohorts = [
        cohort for cohort in physical_cohorts if set(cohort) <= selected
    ]
    cohort_members = {step for cohort in selected_cohorts for step in cohort}
    units: list[tuple[int, ...]] = [
        *selected_cohorts,
        *((step,) for step in sorted(selected - cohort_members)),
    ]
    pending_units = list(units)
    satisfied = {step for step in range(1, 7) if step not in selected}
    dependency_map = step_dependency_map
    while pending_units:
        ready_units = [
            unit
            for unit in pending_units
            if all(
                dependency in satisfied or dependency in unit
                for step in unit
                for dependency in dependency_map[step]
            )
        ]
        if not ready_units:
            ready_units = [pending_units[0]]
        if (
            primary_branch == "A"
            and any(3 in unit for unit in ready_units)
            and "tactic_validation_results" not in accumulated
        ):
            if host._optional_work_allowed(
                priority="critical",
                minimum_remaining_seconds=180.0,
            ):
                await run_tactic_validation_wave()
            else:
                accumulated["tactic_validation_budget_skipped"] = True
                loop_trace.append(
                    {
                        "loop": "validation",
                        "event": "deadline_skip",
                        "passed": True,
                        "issues": ["运行进入截止收敛区间，跳过可选战法验证波次。"],
                    }
                )
        prior = dict(accumulated)

        async def execute_unit(unit: tuple[int, ...]) -> list[dict[str, Any]]:
            if len(unit) > 1:
                return await run_physical_cohort(
                    unit,
                    middle_cycle=middle_cycle,
                    prior_step_outputs=prior,
                    middle_feedback=middle_feedback,
                )
            return [
                await run_step(
                    unit[0],
                    middle_cycle=middle_cycle,
                    prior_step_outputs=prior,
                    middle_feedback=middle_feedback,
                )
            ]

        batches = await asyncio.gather(*(execute_unit(unit) for unit in ready_units))
        for outcomes in batches:
            for outcome in sorted(outcomes, key=lambda item: int(item["run"]["step"])):
                commit_step(outcome)
        for unit in ready_units:
            satisfied.update(unit)
            pending_units.remove(unit)
    return
