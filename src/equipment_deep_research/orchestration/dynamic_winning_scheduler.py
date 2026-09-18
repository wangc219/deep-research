"""Dynamic S1-S6 winning mechanism scheduler with backtrack/skip/parallel support.

Implements the architecture's requirement that S1-S6 should NOT be a fixed pipeline,
but a dynamic Tree-of-Warfare execution graph supporting:
- Branch-specific execution modes: skip/light/standard/deep
- Dynamic actions from reasoning nodes: continue/parallel/backtrack/recall/stop
- Pipeline parallelism: steps start immediately when dependencies are satisfied
- Intelligent middle-loop rerun: only affected steps, not all downstream
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


StepOutcome = Mapping[str, Any]
RunStepFn = Callable[
    [int, int, Mapping[str, Any], list[str] | None],
    Awaitable[StepOutcome],
]
RunCohortFn = Callable[
    [tuple[int, ...], int, Mapping[str, Any], list[str] | None],
    Awaitable[Sequence[StepOutcome]],
]
CommitStepFn = Callable[[StepOutcome], None]
StateSnapshotFn = Callable[[], Mapping[str, Any]]
BeforeReadyUnitsFn = Callable[[Sequence[tuple[int, ...]]], Awaitable[None]]


async def _gather_fail_fast(
    awaitables: Sequence[Awaitable[Any]],
) -> list[Any]:
    """Gather sibling units without leaving work behind after one fails.

    ``asyncio.gather`` propagates the first exception but deliberately leaves
    the other awaitables running.  Production step/cohort callbacks can still
    mutate shared state after the scheduler has reported a failure unless the
    siblings are explicitly cancelled and awaited.  Keep that policy in one
    small helper so both production execution paths share identical cleanup
    semantics, including when the caller itself is cancelled.
    """

    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    if not tasks:
        return []
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class StepAction(str, Enum):
    """Actions that a reasoning node can trigger."""
    CONTINUE = "continue"
    PARALLEL = "parallel"
    BACKTRACK = "backtrack"
    RECALL = "recall"  # Request evidence supplement
    STOP = "stop"


class ExecutionMode(str, Enum):
    """Execution intensity per branch blueprint."""
    SKIP = "skip"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


def plan_dependency_waves(
    selected_steps: Sequence[int],
    *,
    dependency_map: Mapping[int, Sequence[int]],
) -> list[tuple[int, ...]]:
    """Plan deterministic dependency waves for compatibility execution.

    Steps outside ``selected_steps`` are treated as already satisfied.  This
    matches branch pruning and targeted resume behavior in the production
    winning workflow.
    """

    selected = {int(step) for step in selected_steps}
    known_steps = {int(step) for step in dependency_map}
    satisfied = known_steps - selected
    pending = sorted(selected)
    waves: list[tuple[int, ...]] = []
    while pending:
        wave = tuple(
            step
            for step in pending
            if all(int(dependency) in satisfied for dependency in dependency_map[step])
        )
        if not wave:
            # Preserve the historical recovery behavior for malformed or
            # partially migrated DAGs instead of deadlocking the run.
            wave = (pending[0],)
        waves.append(wave)
        satisfied.update(wave)
        pending = [step for step in pending if step not in wave]
    return waves


def reserve_parallel_capacity(
    *,
    in_flight: int,
    max_parallel: int,
    remaining_call_budget: int,
    requested_slots: int,
    reserved_calls_per_slot: int = 1,
) -> int:
    """Grant extra parallel exploration slots without exceeding budget."""

    room = max(0, int(max_parallel) - max(0, int(in_flight)))
    per_slot = max(1, int(reserved_calls_per_slot))
    budget_slots = max(0, int(remaining_call_budget)) // per_slot
    return max(0, min(int(requested_slots), room, budget_slots))


async def execute_production_step_waves(
    *,
    selected_steps: Sequence[int],
    execution_profile_id: str,
    dependency_map: Mapping[int, Sequence[int]],
    middle_cycle: int,
    middle_feedback: list[str] | None,
    snapshot_state_fn: StateSnapshotFn,
    run_step_fn: RunStepFn,
    commit_step_fn: CommitStepFn,
    physical_cohorts: Sequence[Sequence[int]] = (),
    run_cohort_fn: RunCohortFn | None = None,
    before_ready_units_fn: BeforeReadyUnitsFn | None = None,
    dynamic_pipeline_enabled: bool | None = None,
) -> None:
    """Run the production S1-S6 scheduler extracted from ``winning.py``.

    The scheduler owns dependency readiness, optimized-v2 cohort execution,
    compatibility waves, task cancellation and failure propagation.  Business
    behavior remains injected by callbacks so this module does not depend on
    provider, prompt, deadline or Mission Graph implementation details.
    """

    selected = {int(step) for step in selected_steps}
    if not selected:
        return

    normalized_dependencies = {
        int(step): tuple(int(dependency) for dependency in dependencies)
        for step, dependencies in dependency_map.items()
    }
    missing = selected - set(normalized_dependencies)
    if missing:
        raise ValueError(f"missing dependency definitions for steps: {sorted(missing)}")

    if execution_profile_id == "optimized_v2" and middle_cycle == 1:
        await _execute_production_cohorts(
            selected=selected,
            dependency_map=normalized_dependencies,
            physical_cohorts=physical_cohorts,
            middle_cycle=middle_cycle,
            middle_feedback=middle_feedback,
            snapshot_state_fn=snapshot_state_fn,
            run_step_fn=run_step_fn,
            commit_step_fn=commit_step_fn,
            run_cohort_fn=run_cohort_fn,
            before_ready_units_fn=before_ready_units_fn,
        )
        return

    if dynamic_pipeline_enabled is None:
        dynamic_pipeline_enabled = (
            os.environ.get("EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", "1").strip()
            != "0"
        )

    if not dynamic_pipeline_enabled:
        await _execute_compatibility_waves(
            selected=selected,
            dependency_map=normalized_dependencies,
            middle_cycle=middle_cycle,
            middle_feedback=middle_feedback,
            snapshot_state_fn=snapshot_state_fn,
            run_step_fn=run_step_fn,
            commit_step_fn=commit_step_fn,
        )
        return

    await _execute_dependency_ready_pipeline(
        selected=selected,
        dependency_map=normalized_dependencies,
        middle_cycle=middle_cycle,
        middle_feedback=middle_feedback,
        snapshot_state_fn=snapshot_state_fn,
        run_step_fn=run_step_fn,
        commit_step_fn=commit_step_fn,
    )


async def _execute_production_cohorts(
    *,
    selected: set[int],
    dependency_map: Mapping[int, Sequence[int]],
    physical_cohorts: Sequence[Sequence[int]],
    middle_cycle: int,
    middle_feedback: list[str] | None,
    snapshot_state_fn: StateSnapshotFn,
    run_step_fn: RunStepFn,
    commit_step_fn: CommitStepFn,
    run_cohort_fn: RunCohortFn | None,
    before_ready_units_fn: BeforeReadyUnitsFn | None,
) -> None:
    cohorts = [
        tuple(int(step) for step in cohort)
        for cohort in physical_cohorts
        if cohort and {int(step) for step in cohort} <= selected
    ]
    cohort_members = {step for cohort in cohorts for step in cohort}
    pending_units = [
        *cohorts,
        *((step,) for step in sorted(selected - cohort_members)),
    ]
    satisfied = set(dependency_map) - selected

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
        if before_ready_units_fn is not None:
            await before_ready_units_fn(tuple(ready_units))

        prior = dict(snapshot_state_fn())

        async def execute_unit(unit: tuple[int, ...]) -> Sequence[StepOutcome]:
            if len(unit) > 1:
                if run_cohort_fn is None:
                    raise ValueError("run_cohort_fn is required for physical cohorts")
                return await run_cohort_fn(
                    unit,
                    middle_cycle,
                    prior,
                    middle_feedback,
                )
            return [
                await run_step_fn(
                    unit[0],
                    middle_cycle,
                    prior,
                    middle_feedback,
                )
            ]

        batches = await _gather_fail_fast(
            [execute_unit(unit) for unit in ready_units]
        )
        outcomes = [outcome for batch in batches for outcome in batch]
        for outcome in sorted(outcomes, key=_outcome_step):
            commit_step_fn(outcome)
        for unit in ready_units:
            satisfied.update(unit)
            pending_units.remove(unit)


async def _execute_compatibility_waves(
    *,
    selected: set[int],
    dependency_map: Mapping[int, Sequence[int]],
    middle_cycle: int,
    middle_feedback: list[str] | None,
    snapshot_state_fn: StateSnapshotFn,
    run_step_fn: RunStepFn,
    commit_step_fn: CommitStepFn,
) -> None:
    for wave in plan_dependency_waves(selected, dependency_map=dependency_map):
        prior = dict(snapshot_state_fn())
        outcomes = await _gather_fail_fast(
            [
                run_step_fn(step, middle_cycle, prior, middle_feedback)
                for step in wave
            ]
        )
        for outcome in sorted(outcomes, key=_outcome_step):
            commit_step_fn(outcome)


async def _execute_dependency_ready_pipeline(
    *,
    selected: set[int],
    dependency_map: Mapping[int, Sequence[int]],
    middle_cycle: int,
    middle_feedback: list[str] | None,
    snapshot_state_fn: StateSnapshotFn,
    run_step_fn: RunStepFn,
    commit_step_fn: CommitStepFn,
) -> None:
    satisfied = set(dependency_map) - selected
    pending = set(selected)
    running: dict[int, asyncio.Task[None]] = {}
    failures: list[BaseException] = []
    wake = asyncio.Event()

    async def run_and_commit(
        step: int,
        *,
        prior_state: Mapping[str, Any],
    ) -> None:
        try:
            outcome = await run_step_fn(
                step,
                middle_cycle,
                prior_state,
                middle_feedback,
            )
            commit_step_fn(outcome)
            satisfied.add(step)
        except BaseException as exc:
            failures.append(exc)
            # Fail fast at the task boundary.  Waiting for the coordinator's
            # next wake-up leaves a small race where a slower sibling can
            # commit after one ready unit has already failed.
            for other_step, other_task in list(running.items()):
                if other_step != step and not other_task.done():
                    other_task.cancel()
        finally:
            running.pop(step, None)
            wake.set()

    try:
        while pending or running:
            if failures:
                await _cancel_tasks(running.values())
                raise failures[0]
            ready = sorted(
                step
                for step in pending
                if all(dependency in satisfied for dependency in dependency_map[step])
            )
            # All work admitted in one dispatch tick must see the same
            # immutable state.  Apart from avoiding repeated serialization of
            # the accumulated query context, this prevents a fast S1 task from
            # observing a partial S2 commit merely because its coroutine got
            # scheduled first.
            prior = dict(snapshot_state_fn()) if ready else None
            for step in ready:
                pending.discard(step)
                running[step] = asyncio.create_task(
                    run_and_commit(step, prior_state=dict(prior or {}))
                )
            if not running:
                if not pending:
                    break
                # Preserve recovery behavior for malformed or migrated DAGs.
                fallback = min(pending)
                pending.discard(fallback)
                running[fallback] = asyncio.create_task(
                    run_and_commit(
                        fallback,
                        prior_state=dict(snapshot_state_fn()),
                    )
                )
            wake.clear()
            await wake.wait()
        if failures:
            raise failures[0]
    finally:
        # A caller cancellation can interrupt ``wake.wait`` while ready units
        # are still in flight.  They must be cancelled and awaited before the
        # cancellation escapes, otherwise a late provider response can commit
        # into a run that has already been aborted.
        await _cancel_tasks(running.values())


async def _cancel_tasks(tasks: Sequence[asyncio.Task[None]] | Any) -> None:
    pending_tasks = list(tasks)
    for task in pending_tasks:
        task.cancel()
    if pending_tasks:
        await asyncio.gather(*pending_tasks, return_exceptions=True)


def _outcome_step(outcome: StepOutcome) -> int:
    run = outcome.get("run", {})
    if not isinstance(run, Mapping):
        raise ValueError("step outcome must contain a mapping at 'run'")
    return int(run["step"])


@dataclass
class StepNode:
    """Represents one S1-S6 step in the execution graph."""
    step: int
    agent_id: str
    mode: ExecutionMode
    dependencies: tuple[int, ...]
    status: str = "pending"  # pending/ready/running/completed/skipped/backtracked
    result: dict[str, Any] | None = None
    next_action: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    middle_cycle: int = 1


@dataclass
class ExecutionPlan:
    """Dynamic execution plan for S1-S6, mutable during runtime."""
    nodes: dict[int, StepNode]
    completed_steps: set[int] = field(default_factory=set)
    skipped_steps: set[int] = field(default_factory=set)
    backtrack_history: list[dict[str, Any]] = field(default_factory=list)

    def mark_completed(self, step: int) -> None:
        """Mark step as completed and check for next actions."""
        self.completed_steps.add(step)
        node = self.nodes.get(step)
        if node:
            node.status = "completed"

    def mark_skipped(self, step: int) -> None:
        """Mark step as skipped (treated as satisfied for dependency checking)."""
        self.skipped_steps.add(step)
        node = self.nodes.get(step)
        if node:
            node.status = "skipped"

    def is_satisfied(self, step: int) -> bool:
        """Check if all dependencies for a step are satisfied."""
        node = self.nodes.get(step)
        if not node:
            return False
        satisfied = self.completed_steps | self.skipped_steps
        return all(dep in satisfied for dep in node.dependencies)

    def get_ready_steps(self) -> list[int]:
        """Get all steps whose dependencies are satisfied and not yet started."""
        ready = []
        for step, node in self.nodes.items():
            if (
                node.status == "pending"
                and node.mode != ExecutionMode.SKIP
                and self.is_satisfied(step)
            ):
                ready.append(step)
        return sorted(ready)

    def backtrack_to(
        self,
        target_step: int,
        *,
        reason: str,
        affected_fields: list[str] | None = None,
        middle_cycle: int = 2,
    ) -> list[int]:
        """Backtrack to target step and compute affected downstream steps.

        Returns list of steps to rerun (including target).
        Implements intelligent rerun: only steps actually affected by the change.
        """
        # Field-level dependency map (step, field) -> affected_steps
        field_impact_map = {
            ("defense_decomposition", 1): {2, 3},
            ("operational_review", 2): {3, 6},
            ("winning_paths", 2): {3, 6},
            ("breakthrough_directions", 3): {4},
            ("effect_chain", 3): {4, 6},
            ("capability_mapping", 4): {5, 6},
            ("dotmlpf_matrix", 4): {6},
            ("gap_assessment", 5): {6},
        }

        # Compute actually affected steps
        affected_steps = {target_step}

        if affected_fields:
            # Fine-grained: only steps affected by modified fields
            for field in affected_fields:
                affected_steps.update(
                    field_impact_map.get((field, target_step), set())
                )
        else:
            # Coarse-grained: all downstream steps
            # S3←{S1,S2}, S4←{S3}, S5←{S4}, S6←{S4,S5}
            downstream_map = {
                1: {2, 3, 4, 5, 6},
                2: {3, 4, 5, 6},
                3: {4, 5, 6},
                4: {5, 6},
                5: {6},
            }
            affected_steps.update(downstream_map.get(target_step, set()))

        # Only rerun steps that were actually completed
        rerun_steps = sorted(affected_steps & self.completed_steps)

        # Mark as pending and update middle_cycle
        for step in rerun_steps:
            node = self.nodes.get(step)
            if node:
                node.status = "pending"
                node.middle_cycle = middle_cycle
                node.retry_count += 1

        # Remove from completed set
        self.completed_steps -= set(rerun_steps)

        # Record backtrack event
        self.backtrack_history.append({
            "target_step": target_step,
            "reason": reason,
            "affected_fields": affected_fields or [],
            "rerun_steps": rerun_steps,
            "middle_cycle": middle_cycle,
        })

        return rerun_steps


class DynamicWinningScheduler:
    """Dynamic scheduler for S1-S6 with pipeline parallelism and intelligent backtracking."""

    # Default dependency map (can be overridden per branch)
    DEFAULT_DEPENDENCIES: dict[int, tuple[int, ...]] = {
        1: (),
        2: (),
        3: (1, 2),
        4: (3,),
        5: (4,),
        6: (4, 5),
    }

    def __init__(
        self,
        *,
        step_definitions: Sequence[tuple[str, str, dict]],
        step_modes: Mapping[int, str],
        run_step_fn: Callable[[int, int, Mapping[str, Any], list[str] | None], Awaitable[dict[str, Any]]],
        commit_step_fn: Callable[[dict[str, Any]], None],
        emit_progress_fn: Callable[[dict[str, Any]], None] | None = None,
        max_parallel: int | None = None,
        parallel_call_budget: int | None = None,
    ) -> None:
        """Initialize scheduler.

        Args:
            step_definitions: Tuple of (agent_id, system_prompt, schema) for each step
            step_modes: Map of step -> execution mode (skip/light/standard/deep)
            run_step_fn: Async function to execute one step
            commit_step_fn: Function to commit step result to accumulated state
            emit_progress_fn: Optional function to emit progress events
        """
        self.step_definitions = step_definitions
        self.step_modes = step_modes
        self.run_step_fn = run_step_fn
        self.commit_step_fn = commit_step_fn
        self.emit_progress_fn = emit_progress_fn or (lambda x: None)
        if max_parallel is None:
            try:
                configured_parallel = int(
                    os.environ.get("EQUIPMENT_DR_DYNAMIC_MAX_PARALLEL", "8")
                )
            except (TypeError, ValueError):
                configured_parallel = 8
        else:
            configured_parallel = max_parallel
        self.max_parallel = max(1, min(64, configured_parallel))
        if parallel_call_budget is None:
            try:
                configured_budget = int(
                    os.environ.get(
                        "EQUIPMENT_DR_DYNAMIC_PARALLEL_CALL_BUDGET",
                        str(self.max_parallel * 3),
                    )
                )
            except (TypeError, ValueError):
                configured_budget = self.max_parallel * 3
        else:
            configured_budget = parallel_call_budget
        self.parallel_call_budget = max(0, min(4096, int(configured_budget)))

        # Build execution plan
        self.plan = self._build_initial_plan()

    def _build_initial_plan(self) -> ExecutionPlan:
        """Build initial execution plan from step modes and dependencies."""
        nodes = {}
        skipped = set()

        for step in range(1, len(self.step_definitions) + 1):
            agent_id = self.step_definitions[step - 1][0]
            mode_str = self.step_modes.get(step, "standard")
            mode = ExecutionMode(mode_str)

            nodes[step] = StepNode(
                step=step,
                agent_id=agent_id,
                mode=mode,
                dependencies=self.DEFAULT_DEPENDENCIES[step],
                status="pending" if mode != ExecutionMode.SKIP else "skipped",
            )

            if mode == ExecutionMode.SKIP:
                skipped.add(step)

        return ExecutionPlan(nodes=nodes, skipped_steps=skipped)

    async def execute_pipeline(
        self,
        *,
        middle_cycle: int = 1,
        middle_feedback: list[str] | None = None,
    ) -> None:
        """Execute S1-S6 with dynamic pipeline parallelism.

        Steps are launched immediately when dependencies are satisfied,
        without waiting for other steps in the same "wave".
        """
        # Emit skipped steps immediately
        for step in self.plan.skipped_steps:
            node = self.plan.nodes[step]
            self.emit_progress_fn({
                "step": step,
                "agent_id": node.agent_id,
                "middle_cycle": middle_cycle,
                "execution_mode": "skip",
                "status": "skipped_by_branch_blueprint",
            })

        # Track running tasks
        running_tasks: dict[int, asyncio.Task] = {}
        pending_steps = {
            step for step, node in self.plan.nodes.items()
            if node.status == "pending"
        }

        # Completion event to wake up scheduler
        completion_event = asyncio.Event()
        parallel_budget_remaining = self.parallel_call_budget
        failures: list[BaseException] = []

        async def run_step_wrapper(step: int) -> None:
            """Wrapper to execute step and handle completion."""
            nonlocal parallel_budget_remaining
            try:
                node = self.plan.nodes[step]
                node.status = "running"

                # Execute step
                outcome = await self.run_step_fn(
                    step,
                    middle_cycle,
                    {},  # Prior outputs retrieved inside run_step_fn
                    middle_feedback,
                )

                # Store result and next_action
                node.result = outcome
                node.next_action = outcome.get("run", {}).get("next_action", {})

                # Commit to accumulated state
                self.commit_step_fn(outcome)

                # Mark completed
                self.plan.mark_completed(step)

                # Check for action requests
                action = node.next_action.get("action", "continue")
                if action == StepAction.BACKTRACK:
                    # Backtrack will be handled by middle-loop critic
                    pass
                elif action == StepAction.PARALLEL:
                    requested = node.next_action.get("parallel_steps") or []
                    extra_steps: list[int] = []
                    if isinstance(requested, list):
                        for raw in requested:
                            try:
                                extra = int(raw)
                            except (TypeError, ValueError):
                                continue
                            extra_node = self.plan.nodes.get(extra)
                            if extra_node is None:
                                continue
                            if extra_node.status == "skipped" and extra not in extra_steps:
                                extra_steps.append(extra)
                    granted = reserve_parallel_capacity(
                        in_flight=max(0, len(running_tasks) - 1),
                        max_parallel=self.max_parallel,
                        remaining_call_budget=parallel_budget_remaining,
                        requested_slots=len(extra_steps),
                    )
                    parallel_budget_remaining = max(
                        0, parallel_budget_remaining - granted
                    )
                    awakened = extra_steps[:granted]
                    for extra in awakened:
                        extra_node = self.plan.nodes[extra]
                        extra_node.status = "pending"
                        if extra_node.mode == ExecutionMode.SKIP:
                            extra_node.mode = ExecutionMode.STANDARD
                        self.plan.skipped_steps.discard(extra)
                        pending_steps.add(extra)
                    self.emit_progress_fn({
                        "step": step,
                        "agent_id": node.agent_id,
                        "middle_cycle": middle_cycle,
                        "status": "parallel_exploration_reserved",
                        "granted_slots": granted,
                        "parallel_steps": awakened,
                        "reason": str(node.next_action.get("reason", ""))[:240],
                    })
                elif action == StepAction.STOP:
                    # Stop signal: mark all pending as skipped
                    for pending_step in pending_steps:
                        if self.plan.nodes[pending_step].status == "pending":
                            self.plan.mark_skipped(pending_step)

            except Exception as e:
                # Keep the first provider/validation failure authoritative and
                # cancel siblings promptly.  Swallowing the exception leaves
                # downstream nodes waiting on an unsatisfied dependency and
                # makes the scheduler appear to have completed successfully.
                node = self.plan.nodes[step]
                node.status = "failed"
                failures.append(e)
                self.emit_progress_fn({
                    "step": step,
                    "agent_id": node.agent_id,
                    "middle_cycle": middle_cycle,
                    "status": "failed",
                    "error": str(e),
                })
                for other_step, other_task in list(running_tasks.items()):
                    if other_step != step and not other_task.done():
                        other_task.cancel()
            finally:
                # Remove from running tasks
                running_tasks.pop(step, None)
                # Wake up scheduler
                completion_event.set()

        # Main scheduling loop
        try:
            while pending_steps or running_tasks:
                if failures:
                    await _cancel_tasks(running_tasks.values())
                    raise failures[0]

                # A STOP action converts pending nodes to skipped.  Keep the
                # bookkeeping set in sync so a stopped run does not look
                # like a malformed graph on the next scheduler tick.
                pending_steps = {
                    step
                    for step in pending_steps
                    if self.plan.nodes[step].status == "pending"
                }
                # Get ready steps
                ready_steps = self.plan.get_ready_steps()

                # Launch a bounded ready slice to protect providers under dynamic load.
                capacity = max(0, self.max_parallel - len(running_tasks))
                for step in ready_steps[:capacity]:
                    if step not in running_tasks:
                        pending_steps.discard(step)
                        running_tasks[step] = asyncio.create_task(run_step_wrapper(step))

                # If nothing is running and nothing is ready, we're stuck or done
                if not running_tasks:
                    if pending_steps:
                        unresolved = sorted(pending_steps)
                        raise RuntimeError(
                            "dynamic winning scheduler deadlocked; unresolved steps: "
                            f"{unresolved}"
                        )
                    break

                # Wait for at least one task to complete
                completion_event.clear()
                completion_waiter = asyncio.create_task(completion_event.wait())
                try:
                    await asyncio.wait(
                        [*running_tasks.values(), completion_waiter],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    if not completion_waiter.done():
                        completion_waiter.cancel()
                        await asyncio.gather(completion_waiter, return_exceptions=True)
        finally:
            # External cancellation must not leave provider calls running.
            await _cancel_tasks(running_tasks.values())

        if failures:
            raise failures[0]

    async def execute_with_middle_loop(
        self,
        *,
        critic_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        accumulated_state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute S1-S6 with middle-loop critic and intelligent backtracking.

        Args:
            critic_fn: Async function to run middle-loop critic
            accumulated_state: Current accumulated state

        Returns:
            Final accumulated state with loop trace
        """
        # First execution
        await self.execute_pipeline(middle_cycle=1)

        # Run middle-loop critic
        critic_result = await critic_fn(dict(accumulated_state))

        passed = critic_result.get("passed") is True
        loop_trace = [{
            "loop": "middle",
            "cycle": 1,
            "passed": passed,
            "issues": [str(item) for item in critic_result.get("issues", [])][:6],
        }]

        # If passed or no backtrack requested, done
        if passed:
            return {
                "loop_trace": loop_trace,
                "backtrack_history": self.plan.backtrack_history,
            }

        # Compute backtrack steps
        rerun_from = critic_result.get("rerun_from_step", 0)
        affected_fields = critic_result.get("affected_fields", [])

        if not rerun_from or rerun_from not in self.plan.nodes:
            # No valid backtrack target
            return {
                "loop_trace": loop_trace,
                "backtrack_history": self.plan.backtrack_history,
                "middle_loop_limited": True,
            }

        # Intelligent backtrack
        rerun_steps = self.plan.backtrack_to(
            target_step=rerun_from,
            reason="; ".join(critic_result.get("issues", []))[:200],
            affected_fields=affected_fields if affected_fields else None,
            middle_cycle=2,
        )

        if not rerun_steps:
            # Nothing to rerun
            return {
                "loop_trace": loop_trace,
                "backtrack_history": self.plan.backtrack_history,
            }

        # Re-execute affected steps
        feedback = [str(item) for item in critic_result.get("rerun_guidance", [])][:8]
        await self.execute_pipeline(middle_cycle=2, middle_feedback=feedback)

        # Second critic pass
        second_critic = await critic_fn(dict(accumulated_state))
        second_passed = second_critic.get("passed") is True

        loop_trace.append({
            "loop": "middle",
            "cycle": 2,
            "passed": second_passed,
            "rerun_steps": rerun_steps,
            "issues": [str(item) for item in second_critic.get("issues", [])][:6],
        })

        return {
            "loop_trace": loop_trace,
            "backtrack_history": self.plan.backtrack_history,
            "middle_loop_limited": not second_passed,
        }


async def execute_s1_s6_dynamic(
    *,
    step_definitions: Sequence[tuple[str, str, dict]],
    step_modes: Mapping[int, str],
    run_step_fn: Callable[[int, int, Mapping[str, Any], list[str] | None], Awaitable[dict[str, Any]]],
    commit_step_fn: Callable[[dict[str, Any]], None],
    critic_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    accumulated_state: Mapping[str, Any],
    emit_progress_fn: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute S1-S6 with dynamic scheduling, pipeline parallelism, and intelligent backtracking.

    This is the main entry point replacing the old run_step_waves function.

    Args:
        step_definitions: Tuple of (agent_id, system_prompt, schema) for S1-S6
        step_modes: Map of step -> execution mode from branch blueprint
        run_step_fn: Async function to execute one step
        commit_step_fn: Function to commit step result
        critic_fn: Async function to run middle-loop critic
        accumulated_state: Current accumulated state
        emit_progress_fn: Optional progress callback

    Returns:
        Loop trace and backtrack history
    """
    scheduler = DynamicWinningScheduler(
        step_definitions=step_definitions,
        step_modes=step_modes,
        run_step_fn=run_step_fn,
        commit_step_fn=commit_step_fn,
        emit_progress_fn=emit_progress_fn,
    )

    return await scheduler.execute_with_middle_loop(
        critic_fn=critic_fn,
        accumulated_state=accumulated_state,
    )
