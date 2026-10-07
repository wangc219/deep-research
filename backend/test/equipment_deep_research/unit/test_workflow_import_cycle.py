from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _run_cold_import(order: tuple[str, str]) -> subprocess.CompletedProcess[str]:
    """Import the workflow pair in a fresh interpreter and verify the bridge."""

    script = """
import importlib

order = {order!r}
for name in order:
    importlib.import_module(name)

s6 = importlib.import_module("equipment_deep_research.agents.workflows.s6_quality")
coordinator = importlib.import_module("equipment_deep_research.agents.workflows.coordinator")
names = coordinator._S6_QUALITY_HELPER_NAMES
assert all(hasattr(s6, name) for name in names)
assert all(getattr(coordinator, name) is getattr(s6, name) for name in names)
""".format(order=order)
    root = Path(__file__).resolve().parents[3]
    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )


def test_s6_workflow_modules_import_without_cycle_in_either_order() -> None:
    s6 = "equipment_deep_research.agents.workflows.s6_quality"
    coordinator = "equipment_deep_research.agents.workflows.coordinator"

    for order in ((s6, coordinator), (coordinator, s6)):
        completed = _run_cold_import(order)
        assert completed.returncode == 0, completed.stderr
