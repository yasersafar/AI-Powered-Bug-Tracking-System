"""Two-phase duplicate detection (FR-10): BM25 retrieval (top-50) -> semantic re-ranking.

final_score = w * cosine(MiniLM embeddings) + (1 - w) * BM25 / max(BM25 among candidates)

w is chosen on a validation period (see evaluate.py). Embeddings of indexed reports are cached;
`add` indexes a new report incrementally (BM25 postings + one embedding).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ml.common.text import report_text, tokenize
from ml.duplicate.bm25 import BM25Index

Encoder = Callable[[list[str]], NDArray[np.float32]]


@dataclass(frozen=True)
class DuplicateCandidate:
    bug_id: int
    score: float
    cosine: float
    bm25: float


class DuplicateDetector:
    def __init__(
        self,
        encoder: Encoder,
        dimension: int = 384,
        semantic_weight: float = 0.8,
        candidates: int = 50,
    ) -> None:
        self.encode = encoder
        self.semantic_weight = semantic_weight
        self.candidates = candidates
        self.bm25 = BM25Index()
        self.ids: list[int] = []
        # Row buffer with spare capacity (grown by 1/8, at least 1,024 rows, when full), so adding
        # one report does not copy the whole embedding matrix.
        self._buffer: NDArray[np.float32] = np.zeros((0, dimension), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def embeddings(self) -> NDArray[np.float32]:
        return self._buffer[: len(self.ids)]

    def _append(self, vectors: NDArray[np.float32]) -> None:
        start, needed = len(self.ids), len(self.ids) + len(vectors)
        if needed > len(self._buffer):
            capacity = max(needed, len(self._buffer) + max(1024, len(self._buffer) // 8))
            grown = np.zeros((capacity, vectors.shape[1]), np.float32)
            grown[:start] = self._buffer[:start]
            self._buffer = grown
        self._buffer[start:needed] = vectors

    def add_many(
        self,
        bug_ids: Sequence[int],
        texts: Sequence[str],
        embeddings: NDArray[np.float32] | None = None,
    ) -> None:
        cleaned = list(texts)
        vectors = embeddings if embeddings is not None else self.encode(cleaned)
        self.bm25.add_many([tokenize(t) for t in cleaned])
        self._append(np.asarray(vectors, dtype=np.float32).reshape(len(cleaned), -1))
        self.ids.extend(int(i) for i in bug_ids)

    def add(self, bug_id: int, title: str, description: str) -> None:
        self.add_many([bug_id], [report_text(title, description)])

    def search(
        self,
        text: str,
        top_k: int = 3,
        limit: int | None = None,
        exclude: set[int] | None = None,
        min_score: float = 0.0,
        query_vector: NDArray[np.float32] | None = None,
    ) -> list[DuplicateCandidate]:
        positions, bm25_scores = self.bm25.top_k(tokenize(text), self.candidates, limit)
        keep = bm25_scores > 0
        positions, bm25_scores = positions[keep], bm25_scores[keep]
        if exclude:
            mask = np.array([self.ids[p] not in exclude for p in positions], dtype=bool)
            positions, bm25_scores = positions[mask], bm25_scores[mask]
        if len(positions) == 0:
            return []
        vector = query_vector if query_vector is not None else self.encode([text])[0]
        cosine = self.embeddings[positions] @ vector
        lexical = bm25_scores / bm25_scores.max()
        final = self.semantic_weight * cosine + (1 - self.semantic_weight) * lexical
        order = np.argsort(-final, kind="stable")[:top_k]
        return [
            DuplicateCandidate(
                bug_id=self.ids[positions[i]],
                score=round(float(final[i]), 4),
                cosine=round(float(cosine[i]), 4),
                bm25=round(float(bm25_scores[i]), 4),
            )
            for i in order
            if final[i] >= min_score
        ]
