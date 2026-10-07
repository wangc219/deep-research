"""Gap-driven, deduplicated multi-round search query planning."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


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

    def seen(self, query: str) -> bool:
        """Return whether a query has already been accepted by this history."""

        return _normalize(query) in self._seen


class QueryPlanner:
    def __init__(
        self,
        *,
        max_queries_per_round: int = 6,
        near_duplicate_threshold: float = 0.86,
    ) -> None:
        # A query round is a bounded research batch.  Keeping this limit in
        # the planner prevents a noisy model handoff from turning one round
        # into an unbounded fan-out of nearly identical searches.
        self.max_queries_per_round = max(1, min(32, int(max_queries_per_round)))
        self.near_duplicate_threshold = max(
            0.5, min(1.0, float(near_duplicate_threshold))
        )

    def plan_round(
        self,
        *,
        route: str,
        round_index: int,
        open_questions: list[str],
        conflicts: list[str],
        prior_queries: list[str],
        max_queries: int | None = None,
    ) -> list[ResearchQuery]:
        history = QueryHistory(prior_queries)
        limit = self.max_queries_per_round if max_queries is None else max(
            1, min(32, int(max_queries))
        )
        candidates = [
            # Conflicts are more information-dense than ordinary gaps: one
            # targeted counter-search can invalidate several downstream
            # assumptions, so schedule them first.
            *((f"争议/反证：{item}", "counter_evidence") for item in conflicts),
            *((item, "evidence_gap") for item in open_questions),
        ]
        if not candidates:
            candidates = [(f"{route} 最新公开资料 装备能力", "evidence_gap")]
        result: list[ResearchQuery] = []
        for query, purpose in candidates:
            # Open questions are authored by the current Codex research pass.
            # Do not mechanically manufacture parameter/test/controversy
            # suffix permutations; later rounds should be driven by the actual
            # evidence residual returned by the Agent.
            if not history.should_run(query):
                continue
            # A later round may restate the same gap with slightly different
            # wording.  Exact history matching does not catch that case and
            # would spend another provider call for equivalent evidence.
            # Keep the check conservative (the same token overlap rule used
            # within the current batch) so genuinely new angles remain
            # eligible.
            if any(
                _near_duplicate(query, prior, self.near_duplicate_threshold)
                for prior in prior_queries
            ):
                continue
            if any(
                item.purpose == purpose
                and _near_duplicate(query, item.query, self.near_duplicate_threshold)
                for item in result
            ):
                continue
            result.append(ResearchQuery(query, purpose, round_index))
            if len(result) >= limit:
                break
        return result


def _normalize(query: str) -> str:
    # NFKC folds full-width punctuation/letters and makes model-generated
    # variants such as ``ＡＢＣ`` and ``ABC`` share one cache/history key.
    text = unicodedata.normalize("NFKC", str(query or "")).casefold()
    text = re.sub(r"[\u2010-\u2015\u2212]+", "-", text)
    # Preserve search operators and quoted phrases; they change the evidence
    # being requested even when all words are otherwise identical.
    return re.sub(r"\s+", " ", text).strip()


def _tokens(query: str) -> set[str]:
    normalized = re.sub(r"[，。；、？！,.!?;]+", " ", _normalize(query))
    tokens: set[str] = set()
    for chunk in normalized.split():
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            # Chinese queries normally have no spaces.  Character bigrams
            # catch small connective edits (``的``/``在``) without requiring
            # an embedding call, while the full chunk preserves precision for
            # exact matches.
            tokens.add(chunk)
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
        else:
            tokens.add(chunk)
    return tokens


def _near_duplicate(left: str, right: str, threshold: float) -> bool:
    """Detect query paraphrases without an embedding/model call.

    Token overlap is intentionally conservative.  Empty or one-token queries
    are left to exact history matching because overlap would over-collapse
    useful short Chinese questions.
    """

    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    intersection = len(left_tokens & right_tokens)
    return intersection / max(1, len(left_tokens | right_tokens)) >= threshold
