"""Programmatic candidate and worker-brief deduplication.

Deduplication is an operator aid, not a novelty gate. A near match should
prompt the agent to read or merge existing material before creating another
candidate; it must not define whether a demand is genuinely new.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from difflib import SequenceMatcher
import string
import unicodedata

from knowledgegraph.demand_discovery.domain.store import DomainStore


NEAR_DUP_THRESHOLD = 0.85
SIMILAR_THRESHOLD = 0.60


@dataclass(frozen=True)
class DedupResult:
    near_duplicates: list[tuple[str, float]]
    similar: list[tuple[str, float]]

    def to_dict(self) -> dict[str, list[dict[str, float | str]]]:
        return {
            "near_duplicates": [
                {"candidate_id": candidate_id, "score": round(score, 4)}
                for candidate_id, score in self.near_duplicates
            ],
            "similar": [
                {"candidate_id": candidate_id, "score": round(score, 4)}
                for candidate_id, score in self.similar
            ],
        }


def normalize_title(text: str) -> str:
    """Normalize titles for conservative string-level comparison."""

    normalized = unicodedata.normalize("NFKC", text).lower()
    drop = set(string.punctuation)
    return "".join(
        char
        for char in normalized
        if not char.isspace()
        and char not in drop
        and not unicodedata.category(char).startswith("P")
    )


def similarity(a: str, b: str) -> float:
    """Return a title similarity score with bigram Jaccard support.

    Character bigram Jaccard is the explicit Phase 4 baseline. Sequence ratio
    is used as a second string-only signal so short Chinese titles with one
    inserted connective are not under-scored.
    """

    left = normalize_title(a)
    right = normalize_title(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    jaccard = _bigram_jaccard(left, right)
    if _ascii_only(left) and _ascii_only(right) and min(len(left), len(right)) < 16:
        return jaccard
    return max(jaccard, SequenceMatcher(None, left, right).ratio())


def check_candidate(
    store: DomainStore,
    title: str,
    statement: str,
) -> DedupResult:
    scored: list[tuple[str, float]] = []
    for candidate in store.candidates.values():
        title_score = similarity(title, candidate.title)
        statement_score = similarity(statement, candidate.demand_statement)
        score = max(title_score, (title_score * 0.75) + (statement_score * 0.25))
        if score >= SIMILAR_THRESHOLD:
            scored.append((candidate.candidate_id, score))

    scored.sort(key=lambda item: (-item[1], item[0]))
    near = [item for item in scored if item[1] >= NEAR_DUP_THRESHOLD]
    similar_items = [
        item
        for item in scored
        if SIMILAR_THRESHOLD <= item[1] < NEAR_DUP_THRESHOLD
    ]
    return DedupResult(near_duplicates=near, similar=similar_items)


def _bigram_jaccard(left: str, right: str) -> float:
    left_grams = _char_bigrams(left)
    right_grams = _char_bigrams(right)
    if not left_grams or not right_grams:
        return 1.0 if left == right else 0.0
    intersection = sum((left_grams & right_grams).values())
    union = sum((left_grams | right_grams).values())
    return intersection / union if union else 0.0


def _char_bigrams(text: str) -> Counter[str]:
    if len(text) < 2:
        return Counter([text]) if text else Counter()
    return Counter(text[index : index + 2] for index in range(len(text) - 1))


def _ascii_only(text: str) -> bool:
    return all(ord(char) < 128 for char in text)
