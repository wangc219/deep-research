"""Neutral in-process gateway for the platform public-web search runtime.

Domain packages depend on this small port instead of importing the platform
Agent/tooling layer.  The built-in web-search module registers the concrete
executor during tool discovery.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


_SearchExecutor = Callable[..., dict[str, Any]]
_executor: _SearchExecutor | None = None


def register_public_web_search(executor: _SearchExecutor) -> None:
    """Register the process-local executor owned by the platform runtime."""
    global _executor
    _executor = executor


def execute_public_web_search(
    query: str,
    *,
    count: int = 10,
    time_range: str | None = None,
    sites: list[str] | None = None,
    block_hosts: list[str] | None = None,
    required_terms: list[str] | None = None,
    required_term_groups: list[list[str]] | None = None,
    fusion_strategy: str = "adaptive",
) -> dict[str, Any]:
    """Execute through the registered unified search runtime."""
    if _executor is None:
        return {
            "query": query,
            "results": [],
            "status": "unavailable",
            "error": "统一公开检索运行时尚未注册",
        }
    return _executor(
        query,
        count=count,
        time_range=time_range,
        sites=sites,
        block_hosts=block_hosts,
        required_terms=required_terms,
        required_term_groups=required_term_groups,
        fusion_strategy=fusion_strategy,
    )
