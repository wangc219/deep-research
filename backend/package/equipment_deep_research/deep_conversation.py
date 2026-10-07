"""Backward-compatible import facade for conversation domain primitives.

New code should import from ``equipment_deep_research.domain.conversation``.
This module remains temporarily so existing API clients and persisted workers
can upgrade without changing their import paths in the same deployment.
"""

from equipment_deep_research.domain.conversation import *  # noqa: F401,F403
