"""Compatibility wrapper for extraction schema constants.

Reusable extraction code now lives under ``src/knowledgegraph/extraction``.
This module keeps historical ``from schema import ...`` imports working for
legacy scripts and tests.
"""

from __future__ import annotations

from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.schema import *  # noqa: F401,F403,E402
