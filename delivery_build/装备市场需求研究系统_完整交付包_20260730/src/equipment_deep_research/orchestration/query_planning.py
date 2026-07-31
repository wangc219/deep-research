"""Gap-driven, deduplicated multi-round search query planning."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ResearchQuery:
    query: str
    purpose: str
    round_index: int


class QueryHistory:
    def __init__(self, prior_queries: list[str] | None = None) -> None:
        self._seen = {_normalize(item) for item in prior_queries or []}

    def should_run(self, query: str) -> bool:
        key = _normalize(query)
        if not key or key in self._seen:
            return False
        self._seen.add(key)
        return True


class QueryPlanner:
    def plan_round(self, *, route: str, round_index: int, open_questions: list[str], conflicts: list[str], prior_queries: list[str]) -> list[ResearchQuery]:
        history = QueryHistory(prior_queries)
        candidates = [*open_questions, *(f"争议/反证：{item}" for item in conflicts)]
        if not candidates:
            candidates = [f"{route} 最新公开资料 装备能力"]
        result: list[ResearchQuery] = []
        for question in candidates:
            variants = [question, f"{question} 参数 试验", f"{question} limitations controversy"]
            for query in variants:
                if history.should_run(query):
                    result.append(ResearchQuery(query, "evidence_gap" if question in open_questions else "counter_evidence", round_index))
        return result


def _normalize(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())
