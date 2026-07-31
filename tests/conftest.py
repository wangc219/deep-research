"""Shared pytest fixtures for the equipment_deep_research test suite."""

import pytest


@pytest.fixture
def anyio_backend():
    """Pin anyio-based async tests to the asyncio backend.

    The environment does not install `trio`, so without this the anyio plugin
    would parametrize every async test with a `[trio]` variant that fails at
    import time. Restricting to asyncio keeps the suite green and matches the
    project's asyncio-only runtime.
    """
    return "asyncio"
