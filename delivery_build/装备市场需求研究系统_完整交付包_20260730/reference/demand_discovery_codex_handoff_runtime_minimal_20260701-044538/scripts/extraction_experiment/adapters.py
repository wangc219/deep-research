"""Compatibility wrapper for extraction adapters.

Legacy tests and scripts import this module as a bare ``adapters`` module after
putting ``scripts/extraction_experiment`` on ``sys.path``. Keep that import
surface stable while the reusable implementation lives in ``src``.
"""

from __future__ import annotations

from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.adapters import *  # noqa: F401,F403,E402
from knowledgegraph.extraction.adapters import (  # noqa: F401,E402
    _build_extraction_prompt,
    _build_seven_relation_extraction_prompt,
    _coerce_evidence_span,
    _coerce_llm_payload,
    _locate_quote,
    _normalize_match_text,
)
