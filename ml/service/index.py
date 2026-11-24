"""In-memory duplicate index for the running system: one DuplicateDetector per project.

Duplicates are only searched inside the same project. Embeddings are computed once per bug
and cached by the caller (the backend stores them in PostgreSQL), so a restart only has to
rebuild the BM25 postings. New bugs are added incrementally (FR-10).

The index also answers "which embedding does bug X have?", which the recommender uses to
compare a new report with the bugs a developer has resolved (history similarity).
"""

import threading
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from ml.duplicate.detector import DuplicateCandidate, DuplicateDetector, Encoder

DEFAULT_SEMANTIC_WEIGHT = 0.7  # chosen on the validation period in Stage 4 (both datasets)


class BugIndex:
    def __init__(
        self,
        encoder: Encoder,
        dimension: int = 384,
        semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    ) -> None:
        self.encode = encoder
        self.dimension = dimension
        self.semantic_weight = semantic_weight
        self._projects: dict[int, DuplicateDetector] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._where: dict[int, tuple[int, int]] = {}  # bug_id -> (project_id, row)
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ bookkeeping
    def _lock(self, project_id: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def _detector(self, project_id: int) -> DuplicateDetector:
        with self._guard:
            detector = self._projects.get(project_id)
            if detector is None:
                detector = DuplicateDetector(
                    self.encode, dimension=self.dimension, semantic_weight=self.semantic_weight
                )
                self._projects[project_id] = detector
            return detector

    def has_project(self, project_id: int) -> bool:
        return project_id in self._projects

    def size(self, project_id: int | None = None) -> int:
        if project_id is not None:
            detector = self._projects.get(project_id)
            return len(detector) if detector else 0
        return len(self._where)

    def max_bug_id(self, project_id: int) -> int:
        detector = self._projects.get(project_id)
        return max(detector.ids) if detector and detector.ids else 0

    def contains(self, bug_id: int) -> bool:
        return bug_id in self._where

    def drop_project(self, project_id: int) -> None:
        """Forget a project's index (e.g. after a report was edited); it is rebuilt lazily."""
        with self._lock(project_id), self._guard:
            detector = self._projects.pop(project_id, None)
            if detector:
                for bug_id in detector.ids:
                    self._where.pop(bug_id, None)

    # ------------------------------------------------------------------ writes
    def add_many(
        self,
        project_id: int,
        bug_ids: Sequence[int],
        texts: Sequence[str],
        vectors: NDArray[np.float32] | None = None,
    ) -> None:
        if not bug_ids:
            return
        with self._lock(project_id):
            detector = self._detector(project_id)
            fresh = [i for i, b in enumerate(bug_ids) if b not in self._where]
            if not fresh:
                return
            ids = [int(bug_ids[i]) for i in fresh]
            chosen = [texts[i] for i in fresh]
            matrix = vectors[fresh] if vectors is not None else self.encode(list(chosen))
            start = len(detector)
            detector.add_many(ids, chosen, np.asarray(matrix, dtype=np.float32))
            with self._guard:
                for offset, bug_id in enumerate(ids):
                    self._where[bug_id] = (project_id, start + offset)

    def add(
        self, project_id: int, bug_id: int, text: str, vector: NDArray[np.float32] | None = None
    ) -> None:
        self.add_many(project_id, [bug_id], [text], None if vector is None else vector[None, :])

    # ------------------------------------------------------------------ reads
    def search(
        self,
        project_id: int,
        text: str,
        query_vector: NDArray[np.float32],
        top_k: int,
        min_score: float,
        exclude: set[int] | None = None,
    ) -> list[DuplicateCandidate]:
        detector = self._projects.get(project_id)
        if detector is None or len(detector) == 0:
            return []
        with self._lock(project_id):
            return detector.search(
                text, top_k=top_k, exclude=exclude, min_score=min_score, query_vector=query_vector
            )

    def vectors(self, bug_ids: Sequence[int]) -> NDArray[np.float32]:
        """Embeddings of the given (indexed) bugs; unknown ids are skipped."""
        by_project: dict[int, list[int]] = {}
        for bug_id in bug_ids:
            where = self._where.get(bug_id)
            if where is not None:
                by_project.setdefault(where[0], []).append(where[1])
        rows: list[NDArray[np.float32]] = []
        for project_id, positions in by_project.items():
            with self._lock(project_id):
                detector = self._projects.get(project_id)
                if detector is None:
                    continue
                matrix = detector.embeddings
                rows += [matrix[p] for p in positions if p < len(matrix)]
        if not rows:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.vstack(rows).astype(np.float32)
