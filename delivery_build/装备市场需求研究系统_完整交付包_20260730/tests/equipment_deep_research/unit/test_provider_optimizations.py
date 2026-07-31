"""Unit tests for provider optimizations."""

import asyncio
import pytest
from dataclasses import dataclass

from equipment_deep_research.agents.provider_optimizations import (
    DiscoveryPrefetcher,
    PREFETCH_MAP,
    STEP_DEPENDENCIES,
    create_step_agent_map,
    should_enable_prefetching,
    get_optimized_search_context_size,
    get_optimized_discovery_max_output_tokens,
)

# Use anyio for async tests (matches project's test configuration)
pytestmark = pytest.mark.anyio


def test_step_dependencies():
    """Verify step dependencies are correctly defined."""
    # S1 and S2 have no dependencies
    assert STEP_DEPENDENCIES[1] == ()
    assert STEP_DEPENDENCIES[2] == ()

    # S3 depends on S1 and S2
    assert STEP_DEPENDENCIES[3] == (1, 2)

    # S4 depends on S3
    assert STEP_DEPENDENCIES[4] == (3,)

    # S5 consumes the S4 capability mapping before evaluating equipment gaps
    assert STEP_DEPENDENCIES[5] == (4,)

    # S6 depends on S4 and S5
    assert STEP_DEPENDENCIES[6] == (4, 5)


def test_prefetch_map_coverage():
    """Verify prefetch map covers critical paths."""
    # S1 and S2 should prefetch S3 (their common dependent)
    assert 3 in PREFETCH_MAP[1]
    assert 3 in PREFETCH_MAP[2]

    # S3 prefetches S4; S4 then prefetches the dependent S5 analysis
    assert 4 in PREFETCH_MAP[3]
    assert 5 not in PREFETCH_MAP[3]
    assert 5 in PREFETCH_MAP[4]

    # S5 prefetches the final S6 synthesis
    assert 6 not in PREFETCH_MAP[4]
    assert 6 in PREFETCH_MAP[5]


def test_search_context_size_optimization():
    """Verify search context size is optimized per step."""
    # S1, S2 should use high (broad search)
    assert get_optimized_search_context_size(1, "winning_s1_opponent") == "high"
    assert get_optimized_search_context_size(2, "winning_s2_operations") == "high"

    # S3, S4, S5 should use medium (focused on upstream)
    assert get_optimized_search_context_size(3, "winning_s3_breakthrough") == "medium"
    assert get_optimized_search_context_size(4, "winning_s4_capability") == "medium"
    assert get_optimized_search_context_size(5, "winning_s5_gap") == "medium"

    # S6 should use low (mainly synthesis)
    assert get_optimized_search_context_size(6, "winning_s6_image") == "low"


def test_discovery_max_output_tokens_by_mode():
    """Verify max output tokens scale with execution mode."""
    # Light mode should have lowest tokens
    light = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "light")
    standard = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "standard")
    deep = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "deep")

    assert light < standard < deep

    # S1/S2 should get more tokens
    s1_tokens = get_optimized_discovery_max_output_tokens(1, "winning_s1_opponent", "standard")
    s3_tokens = get_optimized_discovery_max_output_tokens(3, "winning_s3_breakthrough", "standard")
    assert s1_tokens > s3_tokens

    # S6 should get fewer tokens
    s6_tokens = get_optimized_discovery_max_output_tokens(6, "winning_s6_image", "standard")
    assert s6_tokens < s3_tokens


def test_should_enable_prefetching_default():
    """Verify prefetching is enabled by default."""
    import os

    # Remove env var to test default
    os.environ.pop("EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH", None)

    assert should_enable_prefetching() is True


def test_should_enable_prefetching_disabled():
    """Verify prefetching can be disabled via env var."""
    import os

    # Test various disable values
    for disable_value in ("0", "false", "no", "False", "NO"):
        os.environ["EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH"] = disable_value
        assert should_enable_prefetching() is False

    # Clean up
    os.environ.pop("EQUIPMENT_DR_ENABLE_DISCOVERY_PREFETCH", None)


def test_create_step_agent_map():
    """Test creation of step-to-agent mapping."""
    @dataclass
    class MockAgent:
        agent_id: str

    step_definitions = (
        ("winning_s1_opponent", "system1", {}),
        ("winning_s2_operations", "system2", {}),
        ("winning_s3_breakthrough", "system3", {}),
    )

    agent_registry = {
        "winning_s1_opponent": MockAgent("winning_s1_opponent"),
        "winning_s2_operations": MockAgent("winning_s2_operations"),
        "winning_s3_breakthrough": MockAgent("winning_s3_breakthrough"),
    }

    agent_map = create_step_agent_map(step_definitions, agent_registry)

    assert len(agent_map) == 3
    assert agent_map[1].agent_id == "winning_s1_opponent"
    assert agent_map[2].agent_id == "winning_s2_operations"
    assert agent_map[3].agent_id == "winning_s3_breakthrough"


async def test_discovery_prefetcher_basic():
    """Test basic prefetcher functionality."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        agent_id = agent.agent_id
        call_log.append(("discovery", agent_id))
        await asyncio.sleep(0.05)  # Simulate async work
        return f"discovery for {agent_id}", {"sources": [f"{agent_id}_source"]}

    agent_map = {
        1: MockAgent("s1"),
        2: MockAgent("s2"),
        3: MockAgent("s3"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={"topic": "test"},
        enabled=True,
    )

    # Trigger prefetch for S3 when S1 starts
    prefetcher.trigger_prefetch(1)

    # Wait for prefetch to complete
    await asyncio.sleep(0.1)

    # Get prefetched result for S3
    text, metadata = await prefetcher.get_or_run_discovery(
        3,
        agent_map[3],
        {"topic": "test"},
    )

    assert "s3" in text
    assert metadata["sources"] == ["s3_source"]

    # Verify discovery was called only once (prefetch, not on-demand)
    discovery_calls = [call for call in call_log if call[0] == "discovery" and call[1] == "s3"]
    assert len(discovery_calls) == 1


async def test_discovery_prefetcher_on_demand():
    """Test prefetcher falls back to on-demand discovery when no prefetch."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        agent_id = agent.agent_id
        call_log.append(("discovery", agent_id))
        await asyncio.sleep(0.05)
        return f"discovery for {agent_id}", {"sources": []}

    agent_map = {
        1: MockAgent("s1"),
        2: MockAgent("s2"),
        3: MockAgent("s3"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=True,
    )

    # Get discovery for S2 without prefetching
    text, metadata = await prefetcher.get_or_run_discovery(
        2,
        agent_map[2],
        {},
    )

    assert "s2" in text

    # Verify discovery was called on-demand
    discovery_calls = [call for call in call_log if call[0] == "discovery" and call[1] == "s2"]
    assert len(discovery_calls) == 1


async def test_discovery_prefetcher_waits_for_inflight():
    """Test prefetcher waits for in-flight prefetch tasks."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        agent_id = agent.agent_id
        call_log.append(("start", agent_id))
        await asyncio.sleep(0.2)  # Long-running discovery
        call_log.append(("end", agent_id))
        return f"discovery for {agent_id}", {"sources": []}

    agent_map = {
        3: MockAgent("s3"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=True,
    )

    # Trigger prefetch
    prefetcher.trigger_prefetch(1)

    # Wait a bit but not enough for prefetch to complete
    await asyncio.sleep(0.05)

    # Try to get discovery (should wait for in-flight prefetch)
    text, metadata = await prefetcher.get_or_run_discovery(
        3,
        agent_map[3],
        {},
    )

    assert "s3" in text

    # Verify discovery was called only once
    start_calls = [call for call in call_log if call[0] == "start" and call[1] == "s3"]
    assert len(start_calls) == 1


async def test_discovery_prefetcher_disabled():
    """Test prefetcher does nothing when disabled."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        call_log.append(agent.agent_id)
        return f"discovery for {agent.agent_id}", {"sources": []}

    agent_map = {
        1: MockAgent("s1"),
        3: MockAgent("s3"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=False,
    )

    # Trigger prefetch (should do nothing)
    prefetcher.trigger_prefetch(1)

    await asyncio.sleep(0.05)

    # No prefetch should have happened
    assert len(call_log) == 0

    # Get discovery on-demand
    text, metadata = await prefetcher.get_or_run_discovery(
        3,
        agent_map[3],
        {},
    )

    assert "s3" in text
    assert "s3" in call_log


async def test_discovery_prefetcher_multiple_triggers():
    """Test prefetcher handles multiple trigger calls gracefully."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        call_log.append(agent.agent_id)
        await asyncio.sleep(0.05)
        return f"discovery for {agent.agent_id}", {"sources": []}

    agent_map = {
        3: MockAgent("s3"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=True,
    )

    # Trigger prefetch multiple times (should start only once)
    prefetcher.trigger_prefetch(1)  # Triggers S3
    prefetcher.trigger_prefetch(2)  # Also triggers S3

    await asyncio.sleep(0.1)

    # Verify discovery was called only once
    s3_calls = [call for call in call_log if call == "s3"]
    assert len(s3_calls) == 1


async def test_discovery_prefetcher_cancel_all():
    """Test cancelling all in-flight prefetch tasks."""
    call_log = []

    @dataclass
    class MockAgent:
        agent_id: str

    async def mock_discovery(agent, context):
        agent_id = agent.agent_id
        call_log.append(("start", agent_id))
        try:
            await asyncio.sleep(1.0)  # Long task
            call_log.append(("end", agent_id))
        except asyncio.CancelledError:
            call_log.append(("cancelled", agent_id))
            raise
        return f"discovery for {agent_id}", {"sources": []}

    agent_map = {
        3: MockAgent("s3"),
        4: MockAgent("s4"),
    }

    prefetcher = DiscoveryPrefetcher(
        discovery_fn=mock_discovery,
        agent_map=agent_map,
        shared_context={},
        enabled=True,
    )

    # Trigger prefetch
    prefetcher.trigger_prefetch(1)
    prefetcher.trigger_prefetch(3)

    # Wait a bit for tasks to start
    await asyncio.sleep(0.05)

    # Cancel all
    await prefetcher.cancel_all()

    # Verify tasks were cancelled
    cancelled_calls = [call for call in call_log if call[0] == "cancelled"]
    assert len(cancelled_calls) > 0

    # Verify no tasks completed
    end_calls = [call for call in call_log if call[0] == "end"]
    assert len(end_calls) == 0
