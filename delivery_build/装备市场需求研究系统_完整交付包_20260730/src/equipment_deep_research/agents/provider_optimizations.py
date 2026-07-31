"""Performance optimizations for S1-S6 winning mechanism execution.

This module provides prefetching and pipelining strategies to reduce
the total execution time of the S1-S6 winning mechanism analysis.

Key optimization: Discovery Prefetching
--------------------------------------
Instead of waiting for each step to complete before starting the next step's
discovery, we predict which steps will run next based on the dependency graph
and start their discovery proactively.

Dependency graph:
    S1 ─┐
        ├─→ S3 ─→ S4 ─→ S5 ─→ S6
    S2 ─┘

Prefetch strategy:
- When S1 or S2 starts: prefetch S3
- When S3 starts: prefetch S4
- When S4 starts: prefetch S5
- When S5 starts: prefetch S6

Expected benefit: 40-50% reduction in total execution time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from equipment_deep_research.agents.registry import AgentDef


# Dependency map for S1-S6
STEP_DEPENDENCIES: dict[int, tuple[int, ...]] = {
    1: (),
    2: (),
    3: (1, 2),
    4: (3,),
    5: (4,),
    6: (4, 5),
}

# Prefetch strategy: which steps to prefetch when a step starts
PREFETCH_MAP: dict[int, tuple[int, ...]] = {
    1: (3,),  # When S1 starts, prefetch S3 (will need S1+S2)
    2: (3,),  # When S2 starts, prefetch S3 (will need S1+S2)
    3: (4,),  # S4 consumes S3 breakthrough/effect-chain output
    4: (5,),  # S5 must consume S4 capability mapping and constraints
    5: (6,),  # S6 synthesizes S4 capability mapping and S5 gap assessment
}


class DiscoveryPrefetcher:
    """Manages discovery prefetching for S1-S6 steps.

    This class coordinates the prefetching of discovery requests based on
    the dependency graph, ensuring that when a step completes, the discovery
    for its dependent steps is already available or in progress.
    """

    def __init__(
        self,
        *,
        discovery_fn: Callable[[AgentDef, dict[str, Any]], Awaitable[tuple[str, dict[str, Any]]]],
        agent_map: Mapping[int, AgentDef],
        shared_context: Mapping[str, Any],
        enabled: bool = True,
    ) -> None:
        """Initialize the prefetcher.

        Args:
            discovery_fn: Async function to run discovery for a step
            agent_map: Map from step number to AgentDef
            shared_context: Shared context for all discovery requests
            enabled: Whether prefetching is enabled (can be disabled for debugging)
        """
        self.discovery_fn = discovery_fn
        self.agent_map = agent_map
        self.shared_context = shared_context
        self.enabled = enabled

        # Track in-flight prefetch tasks
        self._prefetch_tasks: dict[int, asyncio.Task[tuple[str, dict[str, Any]]]] = {}
        self._prefetch_results: dict[int, tuple[str, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def trigger_prefetch(self, completed_step: int) -> None:
        """Trigger prefetching when a step starts or completes.

        Args:
            completed_step: The step that just started (for prefetch triggering)
        """
        if not self.enabled:
            return

        # Determine which steps to prefetch
        to_prefetch = PREFETCH_MAP.get(completed_step, ())

        for step in to_prefetch:
            # Skip if already prefetched or in progress
            if step in self._prefetch_results or step in self._prefetch_tasks:
                continue

            # Skip if agent not found
            agent = self.agent_map.get(step)
            if agent is None:
                continue

            # Start prefetch task
            self._prefetch_tasks[step] = asyncio.create_task(
                self._run_prefetch(step, agent)
            )

    async def _run_prefetch(
        self,
        step: int,
        agent: AgentDef,
    ) -> tuple[str, dict[str, Any]]:
        """Run a prefetch discovery request.

        Args:
            step: Step number to prefetch
            agent: AgentDef for the step

        Returns:
            Discovery text and metadata
        """
        try:
            # Build discovery context for this step
            context = dict(self.shared_context)

            # Run discovery
            result = await self.discovery_fn(agent, context)

            # Store result
            async with self._lock:
                self._prefetch_results[step] = result

            return result

        except Exception as e:
            # Prefetch failures should not crash the pipeline
            # The step will re-run discovery when it actually executes
            print(f"[DiscoveryPrefetcher] Prefetch failed for step {step}: {e}")
            raise
        finally:
            # Remove from in-flight tasks
            async with self._lock:
                self._prefetch_tasks.pop(step, None)

    async def get_or_run_discovery(
        self,
        step: int,
        agent: AgentDef,
        context: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Get prefetched discovery result or run it now.

        Args:
            step: Step number
            agent: AgentDef for the step
            context: Discovery context

        Returns:
            Discovery text and metadata
        """
        # Check if we have a prefetched result
        async with self._lock:
            result = self._prefetch_results.pop(step, None)

        if result is not None:
            print(f"[DiscoveryPrefetcher] Using prefetched discovery for step {step}")
            return result

        # Check if prefetch is in progress
        task = self._prefetch_tasks.get(step)
        if task is not None:
            print(f"[DiscoveryPrefetcher] Waiting for in-progress prefetch for step {step}")
            try:
                return await task
            except Exception:
                # Prefetch failed, fall through to run discovery now
                pass

        # No prefetch available, run discovery now
        print(f"[DiscoveryPrefetcher] Running discovery now for step {step}")
        return await self.discovery_fn(agent, dict(context))

    async def cancel_all(self) -> None:
        """Cancel all in-flight prefetch tasks."""
        async with self._lock:
            tasks = list(self._prefetch_tasks.values())
            self._prefetch_tasks.clear()

        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_step_agent_map(
    step_definitions: tuple[tuple[str, str, dict], ...],
    agent_registry: Mapping[str, AgentDef],
) -> dict[int, AgentDef]:
    """Create a map from step number to AgentDef.

    Args:
        step_definitions: Tuple of (agent_id, system_prompt, schema) for each step
        agent_registry: Registry of all AgentDef instances

    Returns:
        Map from step number (1-6) to AgentDef
    """
    agent_map: dict[int, AgentDef] = {}

    for step_num, (agent_id, _, _) in enumerate(step_definitions, start=1):
        agent = agent_registry.get(agent_id)
        if agent is not None:
            agent_map[step_num] = agent

    return agent_map


def should_enable_prefetching() -> bool:
    """Check if discovery prefetching should be enabled.

    Returns:
        True if prefetching should be enabled
    """
    import os

    # Check environment variable
    env_value = os.environ.get("EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH", "1").strip()

    # Disabled if explicitly set to "0" or "false"
    if env_value.lower() in ("0", "false", "no"):
        return False

    return True


# Additional optimization: Adjust search_context_size based on step
def get_optimized_search_context_size(step: int, agent_id: str) -> str:
    """Get optimized search_context_size for a step.

    S1, S2: "high" - Need broad search
    S3, S4, S5: "medium" - More focused based on upstream
    S6: "low" - Mainly synthesis, minimal new search

    Args:
        step: Step number (1-6)
        agent_id: Agent ID

    Returns:
        Search context size: "low", "medium", or "high"
    """
    if step in (1, 2):
        return "high"
    elif step in (3, 4, 5):
        return "medium"
    elif step == 6:
        return "low"
    else:
        return "medium"  # Default for unknown steps


def get_optimized_discovery_max_output_tokens(
    step: int,
    agent_id: str,
    execution_mode: str,
) -> int:
    """Get optimized max_output_tokens for discovery phase.

    Args:
        step: Step number (1-6)
        agent_id: Agent ID
        execution_mode: "light", "standard", or "deep"

    Returns:
        Max output tokens for discovery
    """
    # Base values by execution mode
    base = {
        "light": 1200,
        "standard": 1600,
        "deep": 2200,
    }.get(execution_mode, 1600)

    # S1/S2 need more discovery capacity
    if step in (1, 2):
        return int(base * 1.2)

    # S6 needs less discovery
    if step == 6:
        return int(base * 0.7)

    return base


__all__ = [
    "DiscoveryPrefetcher",
    "STEP_DEPENDENCIES",
    "PREFETCH_MAP",
    "create_step_agent_map",
    "should_enable_prefetching",
    "get_optimized_search_context_size",
    "get_optimized_discovery_max_output_tokens",
]
