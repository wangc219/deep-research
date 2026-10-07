"""Config-driven keyword gate used as a soft ranking signal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class KeywordGate:
    def __init__(self, categories: dict[str, list[str]]) -> None:
        self.categories = {
            str(category): [str(word) for word in words]
            for category, words in categories.items()
        }

    def score(self, text: str) -> dict[str, Any]:
        hits: dict[str, list[str]] = {}
        for category, words in self.categories.items():
            matched = [word for word in words if word and word in text]
            if matched:
                hits[category] = matched
        return {
            "score": sum(len(words) for words in hits.values()),
            "hits": hits,
        }


def load_default_keyword_gate() -> KeywordGate:
    return load_keyword_gate(default_keyword_gate_path())


def load_keyword_gate(path: str | Path) -> KeywordGate:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return KeywordGate(dict(data.get("categories", {})))


def default_keyword_gate_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "demand_discovery"
        / "keyword_gate.yaml"
    )
