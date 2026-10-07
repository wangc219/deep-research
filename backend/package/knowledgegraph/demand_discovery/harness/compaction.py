"""Research-memory compaction helpers for harness message projection."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from knowledgegraph.demand_discovery.llm.model_config import GPT55_CONTEXT_WINDOW_TOKENS


SPLIT_TURN_LOOKBACK = 8


@dataclass
class CompactionSettings:
    context_window: int = GPT55_CONTEXT_WINDOW_TOKENS
    reserve_tokens: int = 32_000
    keep_recent_tokens: int = 40_000


@dataclass
class CutPoint:
    index: int
    split_turn: bool


@dataclass
class CompactionRecord:
    summary: str
    cut_index: int
    split_turn: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "cut_index": self.cut_index,
            "split_turn": self.split_turn,
        }


def should_compact(context_tokens: int, settings: CompactionSettings) -> bool:
    return context_tokens > settings.context_window - settings.reserve_tokens


def find_cut_point(
    messages: list[Any],
    keep_recent_tokens: int,
) -> CutPoint:
    if not messages:
        return CutPoint(index=0, split_turn=False)

    total = 0
    candidate = 0
    for index in range(len(messages) - 1, -1, -1):
        total += estimate_message_tokens(messages[index])
        candidate = index
        if total >= keep_recent_tokens:
            break

    lower_bound = max(0, candidate - SPLIT_TURN_LOOKBACK)
    for index in range(candidate, lower_bound - 1, -1):
        if getattr(messages[index], "role", "") == "user":
            if index == 0 and candidate > 0:
                break
            return CutPoint(index=index, split_turn=False)

    while candidate < len(messages) and getattr(messages[candidate], "role", "") == "tool_result":
        candidate += 1
    if candidate >= len(messages):
        candidate = max(len(messages) - 1, 0)
    return CutPoint(index=candidate, split_turn=True)


def estimate_context_tokens(messages: list[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def estimate_message_tokens(message: Any) -> int:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text = "".join(
            str(getattr(block, "text", "")) + str(getattr(block, "arguments", ""))
            for block in content
        )
    else:
        text = str(content)
    return max(ceil((len(getattr(message, "role", "")) + len(text)) / 4), 1)


def append_domain_index(summary: str, run_state: dict[str, Any]) -> str:
    evidence_ids = [
        str(item.get("evidence_id", ""))
        for item in run_state.get("evidence", [])
        if item.get("evidence_id")
    ]
    candidate_rows = [
        (
            str(item.get("candidate_id", "")),
            str(item.get("status", "")),
        )
        for item in run_state.get("candidates", [])
        if item.get("candidate_id")
    ]
    lines = [summary.strip(), "", "## Programmatic Domain Index"]
    lines.append("Evidence IDs: " + (", ".join(evidence_ids) if evidence_ids else "none"))
    if candidate_rows:
        lines.append(
            "Candidate IDs: "
            + ", ".join(f"{candidate_id}({status})" for candidate_id, status in candidate_rows)
        )
    else:
        lines.append("Candidate IDs: none")
    return "\n".join(lines).strip()
