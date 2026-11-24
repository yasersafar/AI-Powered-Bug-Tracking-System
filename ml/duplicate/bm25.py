"""Incremental Okapi BM25 index over posting lists (vectorised with NumPy).

The scoring formula is exactly rank_bm25's BM25Okapi (k1=1.5, b=0.75, epsilon=0.25 floor for
negative IDF); a unit test checks that the scores are identical. rank_bm25 rescans every
document for every query term, which is too slow for real-time use on ~100k reports (NFR-02),
and it cannot add documents; this index only touches documents that contain a query term
and supports `add` for new bugs.

Adding a document must stay cheap while the index is live (FR-10), so nothing is recomputed
over the whole vocabulary on `add`: the IDF of a query term is computed exactly from the
current document count when it is needed. Only the epsilon floor for negative IDFs needs the
average IDF of all terms; it is recomputed exactly whenever the index has grown by more than
AVERAGE_REFRESH (1%) since the last computation, which keeps it within a fraction of a percent
of rank_bm25's value and affects only terms that occur in more than half of all reports.
"""

import math
from collections import Counter

import numpy as np
from numpy.typing import NDArray

AVERAGE_REFRESH = 0.01


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75, epsilon: float = 0.25) -> None:
        self.k1, self.b, self.epsilon = k1, b, epsilon
        self._postings: dict[str, tuple[list[int], list[int]]] = {}
        self._arrays: dict[str, tuple[NDArray[np.int64], NDArray[np.float64]]] = {}
        self._doc_len: list[int] = []
        self._doc_len_array: NDArray[np.float64] = np.zeros(0)
        self._total_len = 0
        self._average_idf = 0.0
        self._average_n = 0  # document count when the average IDF was computed

    def __len__(self) -> int:
        return len(self._doc_len)

    def add(self, tokens: list[str]) -> int:
        """Append one document; returns its position."""
        position = len(self._doc_len)
        for term, tf in Counter(tokens).items():
            docs, tfs = self._postings.setdefault(term, ([], []))
            docs.append(position)
            tfs.append(tf)
            self._arrays.pop(term, None)
        self._doc_len.append(len(tokens))
        self._total_len += len(tokens)
        return position

    def add_many(self, documents: list[list[str]]) -> None:
        for tokens in documents:
            self.add(tokens)

    def _raw_idf(self, term: str, n: int) -> float:
        df = len(self._postings[term][0])
        return math.log(n - df + 0.5) - math.log(df + 0.5)

    def _idf(self, term: str) -> float:
        n = len(self._doc_len)
        value = self._raw_idf(term, n)
        if value >= 0:
            return value
        if self._average_n == 0 or n > self._average_n * (1 + AVERAGE_REFRESH):
            total = sum(self._raw_idf(t, n) for t in self._postings)
            self._average_idf = total / len(self._postings)
            self._average_n = n
        return self.epsilon * self._average_idf

    def _lengths(self) -> NDArray[np.float64]:
        """Document lengths as an array, extended (not rebuilt) after adds."""
        have = len(self._doc_len_array)
        if have < len(self._doc_len):
            extra = np.asarray(self._doc_len[have:], dtype=np.float64)
            self._doc_len_array = np.concatenate([self._doc_len_array, extra])
        return self._doc_len_array

    def _postings_array(self, term: str) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        cached = self._arrays.get(term)
        if cached is None:
            docs, tfs = self._postings[term]
            cached = (np.asarray(docs, dtype=np.int64), np.asarray(tfs, dtype=np.float64))
            self._arrays[term] = cached
        return cached

    def scores(self, query: list[str], limit: int | None = None) -> NDArray[np.float64]:
        """BM25 score of every document (only the first `limit` documents if given)."""
        n = len(self._doc_len) if limit is None else limit
        result = np.zeros(n, dtype=np.float64)
        if n == 0:
            return result
        avgdl = self._total_len / len(self._doc_len)
        norm = self.k1 * (1 - self.b + self.b * self._lengths() / avgdl)
        for term in query:  # duplicates counted, as in rank_bm25
            if term not in self._postings:
                continue
            docs, tfs = self._postings_array(term)
            if limit is not None:
                keep = docs < limit
                docs, tfs = docs[keep], tfs[keep]
            result[docs] += self._idf(term) * tfs * (self.k1 + 1) / (tfs + norm[docs])
        return result

    def top_k(
        self, query: list[str], k: int, limit: int | None = None, start: int = 0
    ) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        """Best k documents among positions [start, limit)."""
        scores = self.scores(query, limit)
        if start:
            scores[:start] = 0.0
        k = min(k, len(scores))
        if k == 0:
            return np.zeros(0, dtype=np.int64), np.zeros(0)
        top = np.argpartition(-scores, k - 1)[:k]
        order = top[np.argsort(-scores[top], kind="stable")]
        return order.astype(np.int64), scores[order]
