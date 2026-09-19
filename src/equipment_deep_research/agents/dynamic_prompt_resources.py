"""Markdown resources that are authoritative for the dynamic swarm prompts."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "dynamic_winning"

_SECTION = re.compile(
    r"^<!-- prompt: ([\w.]+) -->\n(.*?)\n<!-- /prompt -->$", re.MULTILINE | re.DOTALL
)


def _prompt_paths(key: str) -> tuple[Path, ...]:
    """Return the base resource and any explicitly split companion prompts.

    S6 is kept as the stage-level contract, while its five portrait-column
    briefs live in ``S6_1.md`` through ``S6_5.md``.  The loader presents the
    same section API to callers so splitting the files does not change the
    runtime contract.
    """

    base = _PROMPT_DIR / f"{key}.md"
    companions = (
        tuple(sorted(_PROMPT_DIR.glob(f"{key}_[0-9].md")))
        if key == "S6"
        else ()
    )
    return (base, *companions)


def _normalise_stage(stage: str) -> str:
    """Return the validated Markdown resource key for a stage name."""

    key = str(stage).strip().upper()
    if key == "COMMON":
        key = "common"
    if key not in {"common", *(f"S{i}" for i in range(1, 7))}:
        raise ValueError(f"unknown dynamic winning stage: {stage!r}")
    return key


@lru_cache(maxsize=None)
def _load_sections(key: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for path in _prompt_paths(key):
        text = path.read_text(encoding="utf-8")
        matches = _SECTION.findall(text)
        if not matches:
            raise ValueError(f"prompt file has no reviewable sections: {path.name}")
        for name, body in matches:
            if name in sections:
                raise ValueError(f"duplicate dynamic prompt section: {key}/{name}")
            sections[name] = body
    return sections


def load_dynamic_winning_prompt(stage: str, *, section: str = "system") -> str:
    """Read exact prose, excluding Markdown labels; restart workers after edits."""
    key = _normalise_stage(stage)

    try:
        return _load_sections(key)[section]
    except KeyError as exc:
        raise ValueError(f"missing dynamic prompt section: {key}/{section}") from exc


@lru_cache(maxsize=None)
def _load_json_section(key: str, section: str) -> Any:
    """Parse one reviewed JSON section once per worker generation."""

    raw = load_dynamic_winning_prompt(key, section=section)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON dynamic prompt section: {key}/{section}"
        ) from exc


def load_dynamic_winning_json(stage: str, *, section: str) -> Any:
    """Load a JSON-valued prompt/resource section from the reviewed Markdown.

    Structured resources such as dimension packs and naming-style catalogs are
    kept beside the prose prompts so the execution modules contain no hidden
    model-facing copy.  The section is parsed on every cache population and is
    returned as a defensive JSON value; callers should copy mutable mappings if
    they intend to mutate them.
    """

    key = _normalise_stage(stage)
    # Callers frequently receive mutable mappings/lists and some enrich them
    # while assembling a task payload.  Return a defensive copy without
    # reparsing the same Markdown JSON for every S3/S4 seat.
    return deepcopy(_load_json_section(key, section))


def invalidate_dynamic_winning_prompt_cache() -> None:
    """Make approved prompt changes visible immediately in this worker."""

    _load_sections.cache_clear()
    _load_json_section.cache_clear()


__all__ = [
    "invalidate_dynamic_winning_prompt_cache",
    "load_dynamic_winning_json",
    "load_dynamic_winning_prompt",
]
