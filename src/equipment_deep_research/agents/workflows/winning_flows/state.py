"""Compatibility facade for the domain-owned swarm state model.

New code should import :class:`SwarmState` from
``equipment_deep_research.domain.swarm_strategy.state``. This module remains
available for checkpoints and integrations that used the historical Agent
workflow path.
"""

from equipment_deep_research.domain.swarm_strategy.state import SwarmState


__all__ = ["SwarmState"]
