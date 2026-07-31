"""Tests for dynamic S1-S6 scheduler."""

import asyncio
import pytest

from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
    DynamicWinningScheduler,
    ExecutionPlan,
    StepNode,
    ExecutionMode,
)


# Use anyio instead of pytest-asyncio (anyio is already installed).
# The asyncio-only backend is pinned via the shared anyio_backend fixture in
# tests/conftest.py.
pytest_plugins = ('anyio',)


@pytest.mark.anyio
async def test_pipeline_parallelism():
    """Test broad S1/S2 parallelism while preserving the quality-critical S4→S5 chain."""
    execution_log = []
    start_time = asyncio.get_event_loop().time()

    async def mock_run_step(step, cycle, state, feedback):
        execution_log.append(("start", step, asyncio.get_event_loop().time() - start_time))
        # S5 is 5x slower than others
        await asyncio.sleep(0.05 if step != 5 else 0.25)
        execution_log.append(("end", step, asyncio.get_event_loop().time() - start_time))
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {
                "step": step,
                "agent_id": f"s{step}",
                "middle_cycle": cycle,
                "status": "completed",
            },
        }

    def mock_commit(outcome):
        pass

    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]

    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={1: "standard", 2: "standard", 3: "standard",
                    4: "standard", 5: "standard", 6: "standard"},
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )

    await scheduler.execute_pipeline(middle_cycle=1)

    # Extract timing
    timings = {step: {"start": None, "end": None} for step in range(1, 7)}
    for event, step, timestamp in execution_log:
        timings[step][event] = timestamp

    # Verify dependencies are respected
    # S3 depends on S1, S2
    assert timings[3]["start"] >= timings[1]["end"]
    assert timings[3]["start"] >= timings[2]["end"]

    # S4 depends on S3
    assert timings[4]["start"] >= timings[3]["end"]

    # S5 consumes S4 capability mapping before evaluating equipment gaps
    assert timings[5]["start"] >= timings[4]["end"]

    # S6 depends on S4, S5
    assert timings[6]["start"] >= timings[4]["end"]
    assert timings[6]["start"] >= timings[5]["end"]

    # Independent S1/S2 discovery still runs in parallel.
    s1_s2_overlap = (
        min(timings[1]["end"], timings[2]["end"])
        - max(timings[1]["start"], timings[2]["start"])
    )
    assert s1_s2_overlap > 0.03

    print("\nExecution timeline:")
    for event, step, timestamp in execution_log:
        print(f"  {event:5s} S{step}: {timestamp:.3f}s")


@pytest.mark.anyio
async def test_intelligent_backtrack():
    """Test that backtrack only reruns affected steps."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
        3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
        4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
        5: StepNode(5, "s5", ExecutionMode.STANDARD, (4,)),
        6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
    })

    # Mark all as completed
    for step in range(1, 7):
        plan.mark_completed(step)

    assert plan.completed_steps == {1, 2, 3, 4, 5, 6}

    # Backtrack S3 with specific field modification
    rerun_steps = plan.backtrack_to(
        target_step=3,
        reason="effect_chain needs revision",
        affected_fields=["effect_chain"],  # Only affects S4 and S6
        middle_cycle=2,
    )

    # Should only rerun S3, S4, S6 (not S5)
    assert set(rerun_steps) == {3, 4, 6}

    # Verify S5 still marked as completed
    assert plan.nodes[5].status == "completed"
    assert 5 in plan.completed_steps

    # Verify backtrack history
    assert len(plan.backtrack_history) == 1
    assert plan.backtrack_history[0]["target_step"] == 3
    assert plan.backtrack_history[0]["rerun_steps"] == [3, 4, 6]


@pytest.mark.anyio
async def test_coarse_grained_backtrack():
    """Test backtrack without affected_fields (rerun all downstream)."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
        3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
        4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
        5: StepNode(5, "s5", ExecutionMode.STANDARD, (4,)),
        6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
    })

    # Mark all as completed
    for step in range(1, 7):
        plan.mark_completed(step)

    # Backtrack S3 without specifying fields
    rerun_steps = plan.backtrack_to(
        target_step=3,
        reason="general consistency issue",
        affected_fields=None,  # No fine-grained info
        middle_cycle=2,
    )

    # Should rerun all downstream: S3, S4, S5, S6
    assert set(rerun_steps) == {3, 4, 5, 6}


@pytest.mark.anyio
async def test_skip_mode():
    """Test that skip mode steps are treated as satisfied dependencies."""
    execution_log = []

    async def mock_run_step(step, cycle, state, feedback):
        execution_log.append(step)
        await asyncio.sleep(0.01)
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {
                "step": step,
                "agent_id": f"s{step}",
                "middle_cycle": cycle,
                "status": "completed",
            },
        }

    def mock_commit(outcome):
        pass

    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]

    # C branch: S1, S2 skip
    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={
            1: "skip",
            2: "skip",
            3: "deep",
            4: "deep",
            5: "standard",
            6: "deep",
        },
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )

    await scheduler.execute_pipeline(middle_cycle=1)

    # Only S3-S6 should execute
    assert execution_log == [3, 4, 5, 6]

    # Verify skip steps are marked
    assert 1 in scheduler.plan.skipped_steps
    assert 2 in scheduler.plan.skipped_steps


@pytest.mark.anyio
async def test_partial_execution():
    """Test execution with some steps already completed (resume scenario)."""
    execution_log = []

    async def mock_run_step(step, cycle, state, feedback):
        execution_log.append(step)
        await asyncio.sleep(0.01)
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {
                "step": step,
                "agent_id": f"s{step}",
                "middle_cycle": cycle,
                "status": "completed",
            },
        }

    def mock_commit(outcome):
        pass

    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]

    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={i: "standard" for i in range(1, 7)},
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )

    # Simulate S1-S3 already completed
    scheduler.plan.mark_completed(1)
    scheduler.plan.mark_completed(2)
    scheduler.plan.mark_completed(3)

    await scheduler.execute_pipeline(middle_cycle=1)

    # Only S4-S6 should execute
    assert execution_log == [4, 5, 6]


@pytest.mark.anyio
async def test_ready_steps_ordering():
    """Test that ready steps are correctly identified and ordered."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
        3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
        4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
        5: StepNode(5, "s5", ExecutionMode.STANDARD, (4,)),
        6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
    })

    # Initially, S1 and S2 are ready
    ready = plan.get_ready_steps()
    assert set(ready) == {1, 2}

    # After S1 completes
    plan.mark_completed(1)
    ready = plan.get_ready_steps()
    assert set(ready) == {2}  # S2 still ready, S3 not yet

    # After S2 completes
    plan.mark_completed(2)
    ready = plan.get_ready_steps()
    assert set(ready) == {3}  # S3 now ready

    # After S3 completes
    plan.mark_completed(3)
    ready = plan.get_ready_steps()
    assert set(ready) == {4}  # S5 waits for S4 capability mapping

    # After S4 completes (S5 still running)
    plan.mark_completed(4)
    ready = plan.get_ready_steps()
    assert set(ready) == {5}  # S5 becomes ready, S6 not yet

    # After S5 completes
    plan.mark_completed(5)
    ready = plan.get_ready_steps()
    assert set(ready) == {6}  # S6 now ready


@pytest.mark.anyio
async def test_backtrack_after_partial_completion():
    """Test backtracking when only some steps are completed."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
        3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
        4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
        5: StepNode(5, "s5", ExecutionMode.STANDARD, (4,)),
        6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
    })

    # Only S1-S4 completed
    plan.mark_completed(1)
    plan.mark_completed(2)
    plan.mark_completed(3)
    plan.mark_completed(4)

    # Backtrack S3
    rerun_steps = plan.backtrack_to(
        target_step=3,
        reason="test",
        affected_fields=None,
        middle_cycle=2,
    )

    # Should only rerun S3 and S4 (S5, S6 were never completed)
    assert set(rerun_steps) == {3, 4}


@pytest.mark.anyio
async def test_step_modes():
    """Test different execution modes (skip/light/standard/deep)."""
    execution_modes_seen = []

    async def mock_run_step(step, cycle, state, feedback):
        node = state if isinstance(state, dict) else {}
        execution_modes_seen.append((step, node.get("mode", "unknown")))
        await asyncio.sleep(0.01)
        return {
            "result": {},
            "assumptions": [],
            "open_questions": [],
            "reasoning_node": {"next_action": {"action": "continue"}},
            "run": {
                "step": step,
                "agent_id": f"s{step}",
                "middle_cycle": cycle,
                "status": "completed",
            },
        }

    def mock_commit(outcome):
        pass

    steps = [
        ("s1", "prompt1", {}),
        ("s2", "prompt2", {}),
        ("s3", "prompt3", {}),
        ("s4", "prompt4", {}),
        ("s5", "prompt5", {}),
        ("s6", "prompt6", {}),
    ]

    # Mixed modes (E branch pattern)
    scheduler = DynamicWinningScheduler(
        step_definitions=steps,
        step_modes={
            1: "deep",
            2: "skip",
            3: "deep",
            4: "deep",
            5: "standard",
            6: "standard",
        },
        run_step_fn=mock_run_step,
        commit_step_fn=mock_commit,
    )

    await scheduler.execute_pipeline(middle_cycle=1)

    # S2 should be skipped
    executed_steps = [step for step, mode in execution_modes_seen]
    assert 2 not in executed_steps
    assert set(executed_steps) == {1, 3, 4, 5, 6}


def test_execution_plan_basics():
    """Test basic ExecutionPlan operations."""
    plan = ExecutionPlan(nodes={
        1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
        2: StepNode(2, "s2", ExecutionMode.SKIP, (), status="skipped"),
    })

    # Initially, S2 is skipped
    assert plan.is_satisfied(1)  # No dependencies

    # Mark S2 as skipped in the plan
    plan.mark_skipped(2)
    assert 2 in plan.skipped_steps

    # Mark S1 completed
    plan.mark_completed(1)
    assert 1 in plan.completed_steps
    assert plan.nodes[1].status == "completed"

    # Verify S2 skipped
    assert 2 in plan.skipped_steps
    assert plan.nodes[2].status == "skipped"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
