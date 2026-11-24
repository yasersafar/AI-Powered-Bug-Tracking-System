import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from ml.duplicate.bm25 import BM25Index

CORPUS = [  # synthetic
    ["editor", "crashes", "when", "saving", "large", "file"],
    ["save", "button", "disabled", "after", "editing"],
    ["crash", "on", "startup", "with", "null", "pointer"],
    ["large", "file", "upload", "times", "out"],
    ["editor", "crashes", "crashes", "on", "save"],
    ["dark", "theme", "colours", "wrong"],
]


@pytest.mark.parametrize(
    "query",
    [
        ["editor", "crashes"],
        ["large", "file", "save"],
        ["crash"],
        ["unknown"],
        ["crashes", "crashes"],
    ],
)
def test_scores_match_rank_bm25_exactly(query: list[str]) -> None:
    index = BM25Index()
    index.add_many(CORPUS)
    expected = BM25Okapi(CORPUS).get_scores(query)
    np.testing.assert_allclose(index.scores(query), expected, rtol=1e-12)


def test_incremental_add_equals_rebuild() -> None:
    incremental = BM25Index()
    incremental.add_many(CORPUS[:3])
    incremental.scores(["editor"])  # force a cached state before adding more
    incremental.add_many(CORPUS[3:])
    np.testing.assert_allclose(
        incremental.scores(["editor", "crashes"]),
        BM25Okapi(CORPUS).get_scores(["editor", "crashes"]),
    )


def test_top_k_respects_limit_and_start() -> None:
    index = BM25Index()
    index.add_many(CORPUS)
    positions, scores = index.top_k(["editor", "crashes"], k=2)
    assert positions.tolist() == [4, 0]
    assert scores[0] >= scores[1]
    limited, _ = index.top_k(["editor", "crashes"], k=2, limit=4)
    assert 4 not in limited.tolist()
    started, started_scores = index.top_k(["editor", "crashes"], k=6, start=3)
    assert set(started[started_scores > 0].tolist()) <= {3, 4, 5}


def test_empty_index() -> None:
    positions, scores = BM25Index().top_k(["anything"], k=3)
    assert len(positions) == len(scores) == 0
