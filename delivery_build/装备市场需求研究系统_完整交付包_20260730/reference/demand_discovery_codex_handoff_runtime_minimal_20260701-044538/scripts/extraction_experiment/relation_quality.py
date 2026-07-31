"""Compatibility wrapper for relation quality governance helpers."""

from __future__ import annotations

from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.relation_quality import *  # noqa: F401,F403,E402
