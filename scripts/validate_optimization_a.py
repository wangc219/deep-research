#!/usr/bin/env python3
# ruff: noqa: F401
"""Quick validation script for dynamic S1-S6 scheduler optimization.

This script helps verify the optimization works correctly before full deployment.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print('=' * 80)


def print_success(msg: str) -> None:
    """Print success message."""
    print(f"✅ {msg}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"❌ {msg}")


def print_info(msg: str) -> None:
    """Print info message."""
    print(f"ℹ️  {msg}")


async def test_imports() -> bool:
    """Test that all required modules can be imported."""
    print_header("Testing Imports")

    try:
        from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
            DynamicWinningScheduler,
            ExecutionPlan,
            StepNode,
            ExecutionMode,
            execute_s1_s6_dynamic,
        )
        print_success("Dynamic scheduler module imported successfully")
        return True
    except ImportError as e:
        print_error(f"Failed to import dynamic scheduler: {e}")
        return False


async def test_basic_functionality() -> bool:
    """Test basic scheduler functionality."""
    print_header("Testing Basic Functionality")

    try:
        from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
            DynamicWinningScheduler,
            ExecutionMode,
        )

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

        await scheduler.execute_pipeline(middle_cycle=1)

        if execution_log == [1, 2, 3, 4, 5, 6]:
            print_success("All 6 steps executed in correct dependency order")
            return True
        else:
            print_error(f"Unexpected execution order: {execution_log}")
            return False

    except Exception as e:
        print_error(f"Basic functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_skip_mode() -> bool:
    """Test skip mode handling."""
    print_header("Testing Skip Mode")

    try:
        from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
            DynamicWinningScheduler,
        )

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

        if execution_log == [3, 4, 5, 6]:
            print_success("Skip mode works correctly (S1, S2 skipped)")
            return True
        else:
            print_error(f"Unexpected execution with skip mode: {execution_log}")
            return False

    except Exception as e:
        print_error(f"Skip mode test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_intelligent_backtrack() -> bool:
    """Test intelligent backtracking."""
    print_header("Testing Intelligent Backtrack")

    try:
        from equipment_deep_research.orchestration.dynamic_winning_scheduler import (
            ExecutionPlan,
            StepNode,
            ExecutionMode,
        )

        plan = ExecutionPlan(nodes={
            1: StepNode(1, "s1", ExecutionMode.STANDARD, ()),
            2: StepNode(2, "s2", ExecutionMode.STANDARD, ()),
            3: StepNode(3, "s3", ExecutionMode.STANDARD, (1, 2)),
            4: StepNode(4, "s4", ExecutionMode.STANDARD, (3,)),
            5: StepNode(5, "s5", ExecutionMode.STANDARD, (3,)),
            6: StepNode(6, "s6", ExecutionMode.STANDARD, (4, 5)),
        })

        # Mark all as completed
        for step in range(1, 7):
            plan.mark_completed(step)

        # Backtrack S3 with specific field modification
        rerun_steps = plan.backtrack_to(
            target_step=3,
            reason="effect_chain needs revision",
            affected_fields=["effect_chain"],  # Only affects S4 and S6
            middle_cycle=2,
        )

        if set(rerun_steps) == {3, 4, 6}:
            print_success("Intelligent backtrack works (only S3, S4, S6 rerun, S5 preserved)")
            print_info(f"  Backtrack history: {plan.backtrack_history}")
            return True
        else:
            print_error(f"Unexpected rerun steps: {rerun_steps}, expected {{3, 4, 6}}")
            return False

    except Exception as e:
        print_error(f"Intelligent backtrack test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_unit_tests() -> bool:
    """Run pytest unit tests."""
    print_header("Running Unit Tests")

    try:
        import pytest
        test_file = Path(__file__).parent.parent / "tests" / "test_dynamic_winning_scheduler.py"

        if not test_file.exists():
            print_error(f"Test file not found: {test_file}")
            return False

        print_info(f"Running pytest on {test_file}")
        result = pytest.main([str(test_file), "-v", "--tb=short"])

        if result == 0:
            print_success("All unit tests passed")
            return True
        else:
            print_error(f"Unit tests failed with exit code {result}")
            return False

    except ImportError:
        print_error("pytest not installed, skipping unit tests")
        print_info("Install with: pip install pytest pytest-asyncio")
        return False
    except Exception as e:
        print_error(f"Unit tests failed: {e}")
        return False


def check_environment() -> dict[str, Any]:
    """Check environment configuration."""
    print_header("Checking Environment")

    env_vars = {
        "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER": os.environ.get(
            "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", "not set"
        ),
        "EQUIPMENT_DR_MODE": os.environ.get("EQUIPMENT_DR_MODE", "not set"),
        "EQUIPMENT_DR_PROVIDER": os.environ.get("EQUIPMENT_DR_PROVIDER", "not set"),
        "EQUIPMENT_DR_CODEX_BASE_URL": os.environ.get("EQUIPMENT_DR_CODEX_BASE_URL", "not set"),
    }

    for key, value in env_vars.items():
        if value == "not set":
            print_info(f"{key}: {value} (using default)")
        else:
            # Mask API keys
            if "KEY" in key or "URL" in key:
                print_info(f"{key}: {'*' * 8}")
            else:
                print_info(f"{key}: {value}")

    return env_vars


def print_summary(results: dict[str, bool]) -> None:
    """Print test summary."""
    print_header("Summary")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    print(f"\nTotal tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed == 0:
        print_success("\n🎉 All validation checks passed!")
        print_info("\nNext steps:")
        print("  1. Review docs/OPTIMIZATION_PLAN_A_IMPLEMENTATION.md")
        print("  2. Integrate the scheduler into provider.py")
        print("  3. Run smoke test: python3 scripts/run_deep_research.py --mode fake ...")
        print("  4. Run performance test: python3 scripts/run_deep_research.py --mode real ...")
    else:
        print_error("\n⚠️  Some validation checks failed!")
        print_info("\nFailed tests:")
        for test_name, passed in results.items():
            if not passed:
                print(f"  - {test_name}")


async def main():
    """Run all validation checks."""
    print("=" * 80)
    print("  Dynamic S1-S6 Scheduler Validation")
    print("  Optimization Plan A - Quick Verification")
    print("=" * 80)

    # Check environment
    check_environment()

    # Run tests
    results = {}

    results["imports"] = await test_imports()
    if not results["imports"]:
        print_error("\nCannot proceed without successful imports")
        print_summary(results)
        return

    results["basic_functionality"] = await test_basic_functionality()
    results["skip_mode"] = await test_skip_mode()
    results["intelligent_backtrack"] = await test_intelligent_backtrack()
    results["unit_tests"] = await run_unit_tests()

    # Print summary
    print_summary(results)

    # Exit code
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
