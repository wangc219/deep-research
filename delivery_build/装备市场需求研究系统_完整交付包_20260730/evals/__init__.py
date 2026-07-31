"""Sidecar benchmark tooling for equipment deep research.

This package is intentionally outside ``src/equipment_deep_research`` so the
evaluation harness cannot become a production runtime dependency.
"""

from .models import EvalQuery, EvalRunResult, PairwiseJudgment

__all__ = ["EvalQuery", "EvalRunResult", "PairwiseJudgment"]
