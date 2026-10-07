"""Deployment configuration shared by composition roots.

The package deliberately contains no provider, database, web framework or
workflow imports.  It is safe to use from CLIs, workers and tests alike.
"""

from equipment_deep_research.config.settings import (
    ProjectPaths,
    Settings,
    load_settings,
)

__all__ = ["ProjectPaths", "Settings", "load_settings"]
