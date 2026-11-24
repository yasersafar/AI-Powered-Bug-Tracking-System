import numpy as np
from numpy.typing import NDArray

from ml.duplicate.detector import DuplicateDetector

VOCAB = ["crash", "save", "editor", "theme", "login", "network"]


def fake_encoder(texts: list[str]) -> NDArray[np.float32]:
    """Synthetic bag-of-words 'embedding' so the test needs no model download."""
    vectors = np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalised: NDArray[np.float32] = (vectors / np.maximum(norms, 1e-9)).astype(np.float32)
    return normalised


def detector() -> DuplicateDetector:
    d = DuplicateDetector(fake_encoder, dimension=len(VOCAB), semantic_weight=0.8)
    d.add_many(
        [10, 11, 12],
        ["Editor crash on save", "Login fails on network change", "Theme colours wrong in editor"],
    )
    # Unrelated filler reports: with only three documents most BM25 IDF values would be zero.
    d.add_many(
        range(100, 106),
        [
            "Printing margins",
            "Font rendering blurry",
            "Help page typo",
            "Keyboard shortcut missing",
            "Menu icon misaligned",
            "Tooltip delay too long",
        ],
    )
    return d


def test_finds_the_duplicate_first() -> None:
    results = detector().search("crash in editor when I save", top_k=3)
    assert results[0].bug_id == 10
    assert 0 < results[0].score <= 1
    assert results == sorted(results, key=lambda r: -r.score)


def test_incremental_add_is_searchable() -> None:
    d = detector()
    d.add(13, "Network login timeout", "Login hangs when the network changes")
    assert d.search("login network hang", top_k=1)[0].bug_id in {11, 13}
    assert len(d) == 10


def test_exclude_min_score_and_no_match() -> None:
    d = detector()
    assert all(r.bug_id != 10 for r in d.search("editor crash save", exclude={10}))
    assert d.search("completely unrelated words") == []
    assert d.search("editor crash save", min_score=1.1) == []
