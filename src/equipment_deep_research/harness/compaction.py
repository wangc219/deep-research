"""Deterministic, loss-aware context compaction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class CompactionRecord:
    original_tokens: int
    compacted_tokens: int
    removed_item_count: int


def estimate_tokens(value: Any) -> int:
    text = json.dumps(value.sections if hasattr(value, "sections") else value, ensure_ascii=False, sort_keys=True)
    return max(1, (len(text) + 3) // 4)


class ContextCompactor:
    def compact(self, pack: Any, *, token_budget: int) -> tuple[Any, CompactionRecord]:
        sections = json.loads(json.dumps(pack.sections, ensure_ascii=False))
        original = estimate_tokens(sections)
        removed = 0
        # Preserve task, coverage, recalls and checkpoint; trim only repeated lists.
        for name, value in list(sections.items()):
            if name in {"task", "coverage", "recall_request", "own_checkpoint"} or not isinstance(value, list):
                continue
            seen: set[str] = set()
            compacted = []
            for item in value:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker in seen:
                    removed += 1
                    continue
                seen.add(marker)
                compacted.append(item)
            sections[name] = compacted
        # Deterministically drop tail items only after their identifiers were retained.
        while estimate_tokens(sections) > token_budget:
            candidates = [(name, value) for name, value in sections.items() if isinstance(value, list) and len(value) > 1]
            if not candidates:
                break
            name, value = max(candidates, key=lambda pair: (len(pair[1]), pair[0]))
            value.pop()
            removed += 1
        compacted_pack = type(pack)(agent_id=pack.agent_id, sections=sections)
        return compacted_pack, CompactionRecord(original, estimate_tokens(compacted_pack), removed)
