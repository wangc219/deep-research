"""Small Okapi BM25 implementation with character bigram tokenization."""

from __future__ import annotations

from collections import Counter
import math


class BM25Index:
    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = list(documents)
        self.k1 = k1
        self.b = b
        self._tokens = [_tokenize(doc) for doc in self.documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._avgdl = sum(self._lengths) / len(self._lengths) if self._lengths else 0
        self._df: Counter[str] = Counter()
        for tokens in self._tokens:
            self._df.update(set(tokens))

    def rank(self, query: str, *, top_k: int = 10) -> list[tuple[int, float]]:
        query_tokens = _tokenize(query)
        scores = [
            (index, self._score(query_tokens, tokens, self._lengths[index]))
            for index, tokens in enumerate(self._tokens)
        ]
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

    def _score(self, query_tokens: list[str], doc_tokens: list[str], doc_len: int) -> float:
        if not query_tokens or not doc_tokens or not self.documents:
            return 0.0
        tf = Counter(doc_tokens)
        score = 0.0
        for token in query_tokens:
            df = self._df.get(token, 0)
            if df == 0:
                continue
            idf = math.log(1 + (len(self.documents) - df + 0.5) / (df + 0.5))
            freq = tf[token]
            denom = freq + self.k1 * (1 - self.b + self.b * doc_len / max(self._avgdl, 1))
            score += idf * freq * (self.k1 + 1) / denom
        return score


def _tokenize(text: str) -> list[str]:
    compact = "".join(str(text or "").lower().split())
    if len(compact) <= 1:
        return [compact] if compact else []
    return [compact[index : index + 2] for index in range(len(compact) - 1)]
