"""Repository quality gate for local development and CI."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    environment = {**os.environ, "PYTHONPATH": "src"}
    commands = [
        [sys.executable, "-m", "equipment_deep_research.architecture"],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/equipment_deep_research/unit/test_architecture_boundaries.py",
            "tests/equipment_deep_research/unit/test_settings.py",
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, env=environment)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
