"""Evaluate duplicate detection on logpai/bugrepo (the data used by Meng et al., 2024).

    python -m ml.duplicate.evaluate --dataset eclipse_platform

Protocol (online, time-respecting):
  * Reports are ordered by creation time. A query is a report marked DUPLICATE; the relevant
    answers are the earlier reports in the same duplicate cluster (union of duplicate links).
  * Realistic setting: a query may only retrieve reports created *before* it - the whole
    history (tens of thousands of reports), exactly what the IDE plug-in faces.
  * Benchmark-comparable setting: the pool is limited to the test period (Meng et al. evaluate
    inside their test split, which is far smaller).
  * Test queries: newest 20% of reports. Validation queries (used only to choose the
    semantic weight w): the 10% just before the test period.
Metrics: Recall@1/5/10, MRR, BM25 candidate recall@50, p50/p95 latency of a live search.
"""

import argparse
import hashlib
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ml.common.paths import ARTIFACTS, RAW, RESULTS
from ml.common.plots import bar_png
from ml.common.results import write_json
from ml.common.text import clean_text, report_text, tokenize
from ml.duplicate.detector import DuplicateDetector
from ml.duplicate.embedder import Embedder

DATASETS = {
    "eclipse_platform": "unzipped/eclipse_platform.csv",
    "eclipse_jdt": "eclipse_jdt.csv",
}
WEIGHTS = (0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
CANDIDATES = 50
KS = (1, 5, 10)
EMBED_CHARS = 1000


def load(dataset: str) -> pd.DataFrame:
    frame = pd.read_csv(
        RAW / "bugrepo" / DATASETS[dataset],
        usecols=["Issue_id", "Duplicated_issue", "Title", "Description", "Created_time"],
    )
    frame["created"] = pd.to_datetime(frame["Created_time"], utc=True, format="mixed")
    frame["text"] = [
        report_text(t, d) for t, d in zip(frame["Title"], frame["Description"], strict=True)
    ]
    frame = frame.rename(columns={"Issue_id": "bug_id", "Duplicated_issue": "duplicate_of"})
    frame = frame.sort_values(["created", "bug_id"]).reset_index(drop=True)
    return frame[["bug_id", "created", "text", "duplicate_of", "Title"]]


def cluster_ids(frame: pd.DataFrame) -> NDArray[np.int64]:
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for bug, master in zip(frame["bug_id"], frame["duplicate_of"], strict=True):
        if pd.notna(master):
            parent[find(int(bug))] = find(int(master))
    return np.array([find(int(b)) for b in frame["bug_id"]], dtype=np.int64)


def embeddings_for(frame: pd.DataFrame, dataset: str) -> NDArray[np.float32]:
    texts = [clean_text(t, EMBED_CHARS) for t in frame["text"]]
    digest = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]
    cache = ARTIFACTS / "duplicate" / f"{dataset}_{digest}.npy"
    if cache.exists():
        cached: NDArray[np.float32] = np.load(cache)
        return cached
    started = time.perf_counter()
    vectors = Embedder().encode(texts, show_progress=True)
    print(f"  embedded {len(texts):,} reports in {time.perf_counter() - started:.0f}s")
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, vectors)
    return vectors


@dataclass
class Query:
    position: int
    relevant: set[int]


def queries(
    frame: pd.DataFrame, clusters: NDArray[np.int64], start: int, end: int, pool_start: int = 0
) -> list[Query]:
    by_cluster: dict[int, list[int]] = {}
    for position, cluster in enumerate(clusters):
        by_cluster.setdefault(int(cluster), []).append(position)
    result = []
    for position in range(start, end):
        if pd.isna(frame.at[position, "duplicate_of"]):
            continue
        earlier = {p for p in by_cluster[int(clusters[position])] if pool_start <= p < position}
        if earlier:
            result.append(Query(position, earlier))
    return result


def evaluate(
    detector: DuplicateDetector,
    vectors: NDArray[np.float32],
    frame: pd.DataFrame,
    items: list[Query],
    weights: tuple[float, ...],
    pool_start: int = 0,
) -> dict[str, dict[str, float]]:
    """Ranks for every weight from one BM25 pass per query, plus BM25-only and dense-only."""
    ranks: dict[str, list[int | None]] = {f"w={w}": [] for w in weights}
    ranks["bm25_only"], ranks["dense_only_full_scan"] = [], []
    ceiling = 0
    for query in items:
        tokens = tokenize(frame.at[query.position, "text"])
        positions, bm25 = detector.bm25.top_k(
            tokens, CANDIDATES, limit=query.position, start=pool_start
        )
        keep = bm25 > 0
        positions, bm25 = positions[keep], bm25[keep]
        hit = np.array([p in query.relevant for p in positions], dtype=bool)
        ceiling += bool(hit.any())
        cosine = vectors[positions] @ vectors[query.position] if len(positions) else np.zeros(0)
        lexical = bm25 / bm25.max() if len(bm25) else bm25
        for w in weights:
            order = np.argsort(-(w * cosine + (1 - w) * lexical), kind="stable")
            found = np.flatnonzero(hit[order])
            ranks[f"w={w}"].append(int(found[0]) + 1 if len(found) else None)
        found = np.flatnonzero(hit)  # BM25 order as returned
        ranks["bm25_only"].append(int(found[0]) + 1 if len(found) else None)
        dense = vectors[pool_start : query.position] @ vectors[query.position]
        best_relevant = max(dense[p - pool_start] for p in query.relevant)
        ranks["dense_only_full_scan"].append(int((dense > best_relevant).sum()) + 1)

    def summarise(values: list[int | None]) -> dict[str, float]:
        array = np.array([v if v is not None else 10**9 for v in values], dtype=np.float64)
        out = {f"recall@{k}": round(float((array <= k).mean()), 4) for k in KS}
        out["mrr"] = round(float(np.mean([1 / v if v is not None else 0.0 for v in values])), 4)
        return out

    result = {name: summarise(values) for name, values in ranks.items()}
    result["bm25_candidate_recall@50"] = {"recall": round(ceiling / max(len(items), 1), 4)}
    return result


def latency(
    detector: DuplicateDetector,
    frame: pd.DataFrame,
    items: list[Query],
    embedder: Embedder,
    samples: int = 300,
) -> dict[str, float]:
    """Wall-clock time of a live search: embed the query text + BM25 + re-rank (full index)."""
    timings = []
    for query in items[:samples]:
        text = frame.at[query.position, "text"]
        started = time.perf_counter()
        vector = embedder.encode([clean_text(text, EMBED_CHARS)])[0]
        detector.search(text, top_k=3, query_vector=vector)
        timings.append((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    detector.add(-1, "Latency probe", "Incremental indexing of one new report for the benchmark.")
    add_ms = (time.perf_counter() - started) * 1000
    return {
        "p50_ms": round(float(np.percentile(timings, 50)), 1),
        "p95_ms": round(float(np.percentile(timings, 95)), 1),
        "max_ms": round(float(np.max(timings)), 1),
        "samples": len(timings),
        "index_size": len(detector) - 1,
        "incremental_add_ms": round(add_ms, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eclipse_platform", choices=list(DATASETS))
    args = parser.parse_args()

    frame = load(args.dataset)
    clusters = cluster_ids(frame)
    vectors = embeddings_for(frame, args.dataset)
    n = len(frame)
    test_start, valid_start = int(n * 0.8), int(n * 0.7)

    embedder = Embedder()
    detector = DuplicateDetector(embedder.encode, dimension=vectors.shape[1])
    detector.add_many(frame["bug_id"].tolist(), frame["text"].tolist(), embeddings=vectors)

    validation = queries(frame, clusters, valid_start, test_start)
    tuning = evaluate(detector, vectors, frame, validation, WEIGHTS)
    best_w = max(WEIGHTS, key=lambda w: (tuning[f"w={w}"]["recall@5"], tuning[f"w={w}"]["mrr"]))
    print(f"  validation queries={len(validation)} -> chosen semantic weight w={best_w}")

    test = queries(frame, clusters, test_start, n)
    realistic = evaluate(detector, vectors, frame, test, (best_w,))
    benchmark_items = queries(frame, clusters, test_start, n, pool_start=test_start)
    comparable = evaluate(
        detector, vectors, frame, benchmark_items, (best_w,), pool_start=test_start
    )
    detector.semantic_weight = best_w
    timing = latency(detector, frame, test, embedder)

    chosen = realistic[f"w={best_w}"]
    bar_png(
        {
            "BM25": realistic["bm25_only"]["recall@5"],
            "BM25+MiniLM": chosen["recall@5"],
            "MiniLM full scan": realistic["dense_only_full_scan"]["recall@5"],
        },
        f"Duplicate detection Recall@5 - {args.dataset} (whole history as pool)",
        "Recall@5",
        RESULTS / f"duplicates_{args.dataset}_recall5.png",
    )
    path = write_json(
        f"duplicates_{args.dataset}.json",
        {
            "task": "duplicate bug report retrieval (FR-10)",
            "dataset": f"logpai/bugrepo {args.dataset}",
            "reports": n,
            "period": [str(frame["created"].min().date()), str(frame["created"].max().date())],
            "test_period_start": str(frame.at[test_start, "created"].date()),
            "pipeline": {
                "retrieval": "BM25 Okapi top-50",
                "rerank": "all-MiniLM-L6-v2 cosine",
                "fusion": "w*cosine + (1-w)*bm25/max",
                "chosen_w": best_w,
            },
            "validation": {"queries": len(validation), "by_weight": tuning},
            "test_realistic_pool_all_earlier_reports": {"queries": len(test), **realistic},
            "test_benchmark_comparable_pool_test_period_only": {
                "queries": len(benchmark_items),
                **comparable,
            },
            "latency_live_search": timing,
        },
    )
    print(
        f"[duplicates/{args.dataset}] test queries={len(test)} recall@5={chosen['recall@5']} "
        f"mrr={chosen['mrr']} p95={timing['p95_ms']}ms -> {path.name}"
    )


if __name__ == "__main__":
    main()
