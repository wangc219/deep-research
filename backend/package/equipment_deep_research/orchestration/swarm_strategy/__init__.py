"""Compatibility facade for pure winning-swarm strategy rules.

Canonical implementations live under ``domain.swarm_strategy`` so Agent
workflows can consume deterministic planning without importing orchestration
controllers.
"""

from equipment_deep_research.domain.swarm_strategy import *  # noqa: F401,F403
