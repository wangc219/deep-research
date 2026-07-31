from __future__ import annotations

from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from data_crawling_handoff.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
