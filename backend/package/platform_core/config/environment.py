"""Deep Research environment contract with temporary legacy-name fallbacks."""

from __future__ import annotations

import os
from collections.abc import Iterable


PREFIX = "DEEP_RESEARCH_"
LEGACY_PREFIX = "YUXI_"


def env_value(
    name: str,
    default: str | None = None,
    *,
    legacy_names: Iterable[str] = (),
) -> str | None:
    """Return the canonical value, falling back to explicitly listed legacy names.

    Presence wins over truthiness so an intentional empty canonical value is not
    overwritten by a stale legacy value.
    """

    if name in os.environ:
        return os.environ[name]
    for legacy_name in legacy_names:
        if legacy_name in os.environ:
            return os.environ[legacy_name]
    return default


def deep_research_env(suffix: str, default: str | None = None) -> str | None:
    """Read ``DEEP_RESEARCH_<suffix>`` with one release-cycle YUXI fallback."""

    return env_value(
        f"{PREFIX}{suffix}",
        default,
        legacy_names=(f"{LEGACY_PREFIX}{suffix}",),
    )


__all__ = ["LEGACY_PREFIX", "PREFIX", "deep_research_env", "env_value"]
