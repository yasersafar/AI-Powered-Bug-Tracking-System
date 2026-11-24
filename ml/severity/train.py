"""Tune (10-fold CV on the training period only) and fit the severity ensemble.

    python -m ml.severity.train --ecosystem eclipse

Writes ml/artifacts/severity/<ecosystem>.joblib and docs/results/severity_<ecosystem>_cv.json.
The test period is never touched here.
"""

import argparse
import time
from dataclasses import asdict, replace

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold

from ml.common.paths import ARTIFACTS
from ml.common.results import write_json
from ml.common.split import describe_split
from ml.severity import data
from ml.severity.model import (
    Hyperparameters,
    SeverityClassifier,
    build_pipeline,
    naive_bayes,
    svc,
    vectorizer,
)

SVC_GRID = [(c, w) for c in (0.1, 0.3, 1.0) for w in (None, "balanced")]
NB_GRID = (0.1, 0.3, 1.0)


def tune(
    texts: np.ndarray, labels: np.ndarray, folds: int, seed: int
) -> tuple[Hyperparameters, dict[str, dict[str, float]]]:
    """Grid-search LinearSVC (C, class weight) and ComplementNB (alpha) with stratified k-fold.

    Selection criterion fixed in advance: highest mean macro-F1 (every severity level matters,
    Critical most of all). RandomForest is not tuned (cost); it uses fixed, documented values.
    """
    base = Hyperparameters()
    scores: dict[str, dict[str, list[float]]] = {}
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for fold, (train_idx, valid_idx) in enumerate(splitter.split(texts, labels), start=1):
        started = time.perf_counter()
        vec = vectorizer(base)
        x_train = vec.fit_transform(texts[train_idx])
        x_valid = vec.transform(texts[valid_idx])
        y_train, y_valid = labels[train_idx], labels[valid_idx]
        candidates = {
            f"svm C={c} weight={w}": svc(replace(base, svc_c=c, svc_class_weight=w), seed)
            for c, w in SVC_GRID
        } | {f"nb alpha={a}": naive_bayes(replace(base, nb_alpha=a)) for a in NB_GRID}
        for name, model in candidates.items():
            predicted = model.fit(x_train, y_train).predict(x_valid)
            entry = scores.setdefault(name, {"accuracy": [], "macro_f1": []})
            entry["accuracy"].append(float(accuracy_score(y_valid, predicted)))
            entry["macro_f1"].append(float(f1_score(y_valid, predicted, average="macro")))
        print(f"  fold {fold}/{folds} done in {time.perf_counter() - started:.0f}s", flush=True)

    summary = {
        name: {metric: round(float(np.mean(v)), 4) for metric, v in values.items()}
        | {f"{metric}_std": round(float(np.std(v)), 4) for metric, v in values.items()}
        for name, values in scores.items()
    }
    best_svc = max(SVC_GRID, key=lambda cw: summary[f"svm C={cw[0]} weight={cw[1]}"]["macro_f1"])
    best_nb = max(NB_GRID, key=lambda a: summary[f"nb alpha={a}"]["macro_f1"])
    chosen = replace(base, svc_c=best_svc[0], svc_class_weight=best_svc[1], nb_alpha=best_nb)
    return chosen, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", default="eclipse", choices=["eclipse", "mozilla"])
    parser.add_argument("--folds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    train, test = data.load(args.ecosystem)
    texts, labels = train["text"].to_numpy(), train["severity"].to_numpy()
    print(f"[severity/{args.ecosystem}] train={len(train):,} (test held out: {len(test):,})")

    started = time.perf_counter()
    hp, cv_summary = tune(texts, labels, args.folds, args.seed)
    tuning_seconds = time.perf_counter() - started
    print(f"  chosen: {hp}")

    started = time.perf_counter()
    model = SeverityClassifier(build_pipeline(hp, args.seed).fit(texts, labels))
    fit_seconds = time.perf_counter() - started
    model.save(ARTIFACTS / "severity" / f"{args.ecosystem}.joblib")

    write_json(
        f"severity_{args.ecosystem}_cv.json",
        {
            "task": "severity classification - hyper-parameter tuning",
            "dataset": args.ecosystem,
            "split": describe_split(train, test),
            "class_distribution_train": train["severity"].value_counts().to_dict(),
            "cv": {
                "folds": args.folds,
                "stratified": True,
                "selection": "mean macro-F1",
                "scores": cv_summary,
            },
            "chosen_hyperparameters": asdict(hp),
            "tuning_seconds": round(tuning_seconds, 1),
            "final_fit_seconds": round(fit_seconds, 1),
        },
    )
    print(f"  fitted in {fit_seconds:.0f}s -> ml/artifacts/severity/{args.ecosystem}.joblib")


if __name__ == "__main__":
    main()
