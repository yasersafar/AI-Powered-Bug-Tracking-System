"""Evaluate the fitted severity ensemble on the held-out (newest 20%) test period.

    python -m ml.severity.evaluate --ecosystem eclipse

Writes docs/results/severity_<ecosystem>.json, severity_<ecosystem>_models.csv and
severity_<ecosystem>_confusion.png. Also reports each single model, so the choice of the
ensemble is backed by data, and a majority-class baseline.
"""

import argparse
import csv
import time

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)

from ml.common.paths import ARTIFACTS, RESULTS
from ml.common.plots import confusion_matrix_png
from ml.common.results import write_json
from ml.common.split import describe_split
from ml.severity import data
from ml.severity.model import LABELS, SeverityClassifier


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    result: dict[str, float] = {"accuracy": round(float(accuracy_score(y_true, y_pred)), 4)}
    for average in ("macro", "weighted"):
        p, r, f, _ = precision_recall_fscore_support(
            y_true, y_pred, average=average, labels=LABELS, zero_division=0
        )
        result |= {
            f"{average}_precision": round(float(p), 4),
            f"{average}_recall": round(float(r), 4),
            f"{average}_f1": round(float(f), 4),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", default="eclipse", choices=["eclipse", "mozilla"])
    args = parser.parse_args()

    train, test = data.load(args.ecosystem)
    model = SeverityClassifier.load(ARTIFACTS / "severity" / f"{args.ecosystem}.joblib")
    texts, y_true = test["text"].tolist(), test["severity"].to_numpy()

    pipeline = model.pipeline
    features = pipeline.named_steps["tfidf"].transform(texts)
    ensemble = pipeline.named_steps["ensemble"]
    rows: dict[str, dict[str, float]] = {}
    for name, estimator in ensemble.named_estimators_.items():
        # VotingClassifier fits its members on label-encoded targets: decode back to names.
        rows[name] = metrics(y_true, ensemble.classes_[estimator.predict(features)])
    ensemble_pred = ensemble.predict(features)
    rows["soft_voting_ensemble"] = metrics(y_true, ensemble_pred)
    majority = train["severity"].mode()[0]
    rows[f"baseline_majority ({majority})"] = metrics(y_true, np.full(len(y_true), majority))

    # Latency of a single report, as the API would call it (NFR-02).
    sample = texts[:200]
    timings = []
    for text in sample:
        started = time.perf_counter()
        model.predict([text])
        timings.append((time.perf_counter() - started) * 1000)

    # Informational: the same predictions collapsed to severe (High/Critical) vs non-severe,
    # the binary setting most of the severity-prediction literature reports.
    severe = {"High", "Critical"}
    binary_true = np.array([label in severe for label in y_true])
    binary_pred = np.array([label in severe for label in ensemble_pred])
    p, r, f, _ = precision_recall_fscore_support(
        binary_true, binary_pred, average="binary", zero_division=0
    )
    binary = {
        "accuracy": round(float((binary_true == binary_pred).mean()), 4),
        "severe_precision": round(float(p), 4),
        "severe_recall": round(float(r), 4),
        "severe_f1": round(float(f), 4),
        "majority_baseline_accuracy": round(float(1 - binary_true.mean()), 4),
    }

    matrix = confusion_matrix(y_true, ensemble_pred, labels=LABELS)
    png = RESULTS / f"severity_{args.ecosystem}_confusion.png"
    confusion_matrix_png(matrix, LABELS, f"Severity ensemble - {args.ecosystem} test period", png)
    with (RESULTS / f"severity_{args.ecosystem}_models.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        columns = list(next(iter(rows.values())))
        writer.writerow(["model", *columns])
        for name, values in rows.items():
            writer.writerow([name, *(values[c] for c in columns)])

    path = write_json(
        f"severity_{args.ecosystem}.json",
        {
            "task": "severity classification (Low/Medium/High/Critical)",
            "dataset": args.ecosystem,
            "split": describe_split(train, test),
            "class_distribution_test": test["severity"].value_counts().to_dict(),
            "models": rows,
            "per_class": classification_report(
                y_true, ensemble_pred, labels=LABELS, output_dict=True, zero_division=0
            ),
            "confusion_matrix": {"labels": LABELS, "rows_true_cols_pred": matrix.tolist()},
            "binary_severe_vs_non_severe_info": binary,
            "latency_ms_single_report": {
                "p50": round(float(np.percentile(timings, 50)), 2),
                "p95": round(float(np.percentile(timings, 95)), 2),
                "samples": len(timings),
            },
        },
    )
    best = rows["soft_voting_ensemble"]
    print(
        f"[severity/{args.ecosystem}] ensemble accuracy={best['accuracy']} "
        f"macro-F1={best['macro_f1']} -> {path.name}"
    )


if __name__ == "__main__":
    main()
