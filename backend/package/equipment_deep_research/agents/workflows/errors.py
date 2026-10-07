"""Workflow-level errors shared by execution modes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class S6QualityError(RuntimeError):
    """Raised when S6 cannot satisfy its quality gate without fallback."""

    def __init__(self, message: str, *, partial_result: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.partial_result = dict(partial_result) if isinstance(partial_result, Mapping) else {}


__all__ = ["S6QualityError"]
