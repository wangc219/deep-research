from __future__ import annotations
from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "dynamic_winning"

@lru_cache(maxsize=None)
def load_dynamic_winning_prompt(stage: str) -> str:
    key = str(stage).strip().upper()
    if key not in {f"S{i}" for i in range(1, 7)}:
        raise ValueError(f"unknown dynamic winning stage: {stage!r}")
    return (_PROMPT_DIR / f"{key}.md").read_text(encoding="utf-8").strip()
