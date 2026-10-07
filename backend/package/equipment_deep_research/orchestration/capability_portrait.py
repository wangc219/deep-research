"""Compatibility facade for capability portrait domain rules.

The implementation now lives in ``domain.capability_portrait``.  Keep this
facade for consumers that used the historical orchestration import path.
"""

from equipment_deep_research.domain.capability_portrait import *  # noqa: F401,F403
