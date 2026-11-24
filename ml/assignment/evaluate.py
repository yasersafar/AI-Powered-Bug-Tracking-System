"""Evaluate the CNN-LSTM recommender on the held-out (newest 20%) period.

    python -m ml.assignment.evaluate --ecosystem eclipse

Reassignment (bug tossing) simulation, as specified:
  The bug is assigned to the first developer of a ranked list; while that developer is not the
  real fixer it is reassigned to the next one. Reassignments = (rank of the real fixer) - 1.
  * model: list ranked by CNN-LSTM probability
  * random baseline: a random order of the same candidate pool, averaged over 5 seeds
  * reference (not a target): most frequent fixer of the bug's component in training
  * reference (not a target): the real number of assignee changes recorded in Bugzilla
Reduction = 1 - model / random (target >= 20%).
"""

import argparse
import time
from collections import Counter

import numpy as np

from ml.assignment import data as assignment_data
from ml.assignment.cnn_lstm import DeveloperRanker
from ml.common.paths import ARTIFACTS, RESULTS
from ml.common.plots import bar_png
from ml.common.results import write_json

SEEDS = (0, 1, 2, 3, 4)


def ranks_from_scores(scores: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """1-based rank of the true label in each row (ties broken pessimistically)."""
    true_scores = scores[np.arange(len(labels)), labels]
    ranks: np.ndarray = (scores > true_scores[:, None]).sum(axis=1) + 1
    return ranks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", default="eclipse", choices=["eclipse", "mozilla"])
    parser.add_argument("--sample", type=int, default=None)
    args = parser.parse_args()

    dataset = assignment_data.load(args.ecosystem, sample=args.sample)
    ranker = DeveloperRanker.load(ARTIFACTS / "assignment" / args.ecosystem)
    if ranker.developers != dataset.developers:
        raise RuntimeError("Developer list differs from training; retrain the model")
    index = {d: i for i, d in enumerate(dataset.developers)}
    labels = np.array([index[d] for d in dataset.test["fixer"]])
    texts = assignment_data.model_text(dataset.test)
    probabilities = ranker.probabilities(texts)
    model_ranks = ranks_from_scores(probabilities, labels)
    pool = len(dataset.developers)

    accuracy = {f"top{k}": round(float((model_ranks <= k).mean()), 4) for k in (1, 3, 5, 10)}

    random_means = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        scores = rng.random((len(labels), pool))
        random_means.append(float((ranks_from_scores(scores, labels) - 1).mean()))
    random_reassignments = float(np.mean(random_means))

    train = dataset.train
    by_component = {c: Counter(g["fixer"]) for c, g in train.groupby("component")}
    overall = Counter(train["fixer"])
    heuristic = np.zeros((len(labels), pool))
    for row, component in enumerate(dataset.test["component"]):
        local = by_component.get(component, Counter())
        for developer, column in index.items():
            heuristic[row, column] = local.get(developer, 0) * 1e6 + overall.get(developer, 0)
    heuristic_ranks = ranks_from_scores(heuristic, labels)

    model_reassignments = float((model_ranks - 1).mean())
    reduction = 1 - model_reassignments / random_reassignments
    observed = float(dataset.test["assignee_changes"].mean())

    timings = []
    for text in texts[:300]:
        started = time.perf_counter()
        ranker.probabilities([text])
        timings.append((time.perf_counter() - started) * 1000)

    bar_png(
        {
            "CNN-LSTM": model_reassignments,
            "component\nheuristic": float((heuristic_ranks - 1).mean()),
            "random\n(5 seeds)": random_reassignments,
            "observed in\nBugzilla": observed,
        },
        f"Mean reassignments until the real fixer - {args.ecosystem}",
        "reassignments per bug",
        RESULTS / f"assignment_{args.ecosystem}_reassignments.png",
    )
    path = write_json(
        f"assignment_{args.ecosystem}.json",
        {
            "task": "developer assignment, CNN-LSTM (FR-12)",
            "dataset": args.ecosystem,
            "candidate_developers": pool,
            "min_fixes_per_developer_in_training": assignment_data.MIN_FIXES,
            "sample_most_recent_fixed_bugs": args.sample,
            "train_size": len(dataset.train),
            "validation_size": len(dataset.validation),
            "test_size_covered": len(dataset.test),
            "test_size_total": dataset.test_total,
            "test_coverage": round(len(dataset.test) / dataset.test_total, 4),
            "test_period": [
                str(dataset.test["created"].min().date()),
                str(dataset.test["created"].max().date()),
            ],
            "accuracy": accuracy,
            "component_heuristic_accuracy": {
                f"top{k}": round(float((heuristic_ranks <= k).mean()), 4) for k in (1, 3, 5)
            },
            "reassignments": {
                "model_mean": round(model_reassignments, 3),
                "model_median": float(np.median(model_ranks - 1)),
                "random_mean_over_5_seeds": round(random_reassignments, 3),
                "random_per_seed": [round(v, 3) for v in random_means],
                "reduction_vs_random": round(reduction, 4),
                "component_heuristic_mean": round(float((heuristic_ranks - 1).mean()), 3),
                "reduction_vs_component_heuristic": round(
                    1 - model_reassignments / float((heuristic_ranks - 1).mean()), 4
                ),
                "observed_bugzilla_assignee_changes_mean": round(observed, 3),
                "method": "reassignments = rank of real fixer - 1 when following the ranked list",
            },
            "latency_ms_single_report": {
                "p50": round(float(np.percentile(timings, 50)), 2),
                "p95": round(float(np.percentile(timings, 95)), 2),
            },
        },
    )
    print(
        f"[assignment/{args.ecosystem}] top1={accuracy['top1']} top3={accuracy['top3']} "
        f"reassignments model={model_reassignments:.2f} random={random_reassignments:.2f} "
        f"reduction={reduction:.1%} -> {path.name}"
    )


if __name__ == "__main__":
    main()
