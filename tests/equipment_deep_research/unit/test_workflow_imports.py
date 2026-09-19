from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_s6_and_coordinator_imports_are_safe_in_either_cold_order() -> None:
    """The two workflow modules expose the same S6 helpers without a cycle."""

    root = Path(__file__).resolve().parents[3]
    script = """
import importlib

first = importlib.import_module("{first}")
second = importlib.import_module("{second}")
coordinator = importlib.import_module("equipment_deep_research.agents.workflows.coordinator")
s6_quality = importlib.import_module("equipment_deep_research.agents.workflows.s6_quality")
assert hasattr(first, "_equipment_semantic_assessment")
assert hasattr(second, "_equipment_semantic_assessment")
assert coordinator._equipment_semantic_assessment is s6_quality._equipment_semantic_assessment
"""
    for first, second in (
        (
            "equipment_deep_research.agents.workflows.s6_quality",
            "equipment_deep_research.agents.workflows.coordinator",
        ),
        (
            "equipment_deep_research.agents.workflows.coordinator",
            "equipment_deep_research.agents.workflows.s6_quality",
        ),
    ):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script.format(first=first, second=second),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(root / "src")},
        )
        assert completed.returncode == 0, completed.stderr
