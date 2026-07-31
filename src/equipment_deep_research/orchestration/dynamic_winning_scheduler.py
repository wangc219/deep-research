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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepAction(str, Enum):
    """Actions that a reasoning node can trigger."""
    CONTINUE = "continue"
    PARALLEL = "parallel"  # Suggest parallel exploration (not yet implemented)
    BACKTRACK = "backtrack"
    RECALL = "recall"  # Request evidence supplement
    STOP = "stop"


class ExecutionMode(str, Enum):
    """Execution intensity per branch blueprint."""
    SKIP = "skip"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


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

        async def run_step_wrapper(step: int) -> None:
            """Wrapper to execute step and handle completion."""
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
                elif action == StepAction.STOP:
                    # Stop signal: mark all pending as skipped
                    for pending_step in pending_steps:
                        if self.plan.nodes[pending_step].status == "pending":
                            self.plan.mark_skipped(pending_step)

            except Exception as e:
                # Mark as failed but don't crash entire pipeline
                node = self.plan.nodes[step]
                node.status = "failed"
                self.emit_progress_fn({
                    "step": step,
                    "agent_id": node.agent_id,
                    "middle_cycle": middle_cycle,
                    "status": "failed",
                    "error": str(e),
                })
            finally:
                # Remove from running tasks
                running_tasks.pop(step, None)
                # Wake up scheduler
                completion_event.set()

        # Main scheduling loop
        while pending_steps:
            # Get ready steps
            ready_steps = self.plan.get_ready_steps()

            # Launch all ready steps immediately (pipeline parallelism)
            for step in ready_steps:
                if step not in running_tasks:
                    pending_steps.discard(step)
                    running_tasks[step] = asyncio.create_task(run_step_wrapper(step))

            # If nothing is running and nothing is ready, we're stuck or done
            if not running_tasks:
                break

            # Wait for at least one task to complete
            completion_event.clear()
            await asyncio.wait(
                [*running_tasks.values(), asyncio.create_task(completion_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

        # Wait for all remaining tasks to complete
        if running_tasks:
            await asyncio.gather(*running_tasks.values())

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
