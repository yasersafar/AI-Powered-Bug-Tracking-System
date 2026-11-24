"""Severity classifier: TF-IDF (word 1-2 grams) -> soft-voting ensemble of
calibrated LinearSVC, RandomForest and ComplementNB (FR-11)."""

import os
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

LABELS = ["Low", "Medium", "High", "Critical"]


def _cpu_jobs() -> int:
    """Respect the OMP_NUM_THREADS cap (Makefile ML_THREADS); all cores when unset."""
    value = os.environ.get("OMP_NUM_THREADS", "")
    return int(value) if value.isdigit() and int(value) > 0 else -1


@dataclass(frozen=True)
class Hyperparameters:
    svc_c: float = 0.3
    svc_class_weight: str | None = "balanced"
    nb_alpha: float = 0.3
    rf_trees: int = 200
    min_df: int = 3
    max_features: int = 200_000


def vectorizer(hp: Hyperparameters) -> TfidfVectorizer:
    return TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=hp.min_df,
        max_features=hp.max_features,
        sublinear_tf=True,
        strip_accents="unicode",
        lowercase=True,
    )


def svc(hp: Hyperparameters, seed: int = 42) -> CalibratedClassifierCV:
    # Calibration gives LinearSVC probabilities so it can take part in soft voting.
    return CalibratedClassifierCV(
        LinearSVC(C=hp.svc_c, class_weight=hp.svc_class_weight, random_state=seed),
        method="sigmoid",
        cv=3,
    )


def forest(hp: Hyperparameters, seed: int = 42) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=hp.rf_trees,
        max_features="sqrt",
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        n_jobs=_cpu_jobs(),
        random_state=seed,
    )


def naive_bayes(hp: Hyperparameters) -> ComplementNB:
    return ComplementNB(alpha=hp.nb_alpha)


def build_pipeline(hp: Hyperparameters, seed: int = 42) -> Pipeline:
    ensemble = VotingClassifier(
        estimators=[("svm", svc(hp, seed)), ("rf", forest(hp, seed)), ("nb", naive_bayes(hp))],
        voting="soft",
        n_jobs=1,
    )
    return Pipeline([("tfidf", vectorizer(hp)), ("ensemble", ensemble)])


@dataclass(frozen=True)
class SeverityPrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]


class SeverityClassifier:
    """Inference wrapper around the fitted pipeline."""

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.classes: list[str] = [str(c) for c in pipeline.classes_]

    def single_threaded(self) -> "SeverityClassifier":
        """For serving: one report per call, many calls in parallel. Without this the
        RandomForest starts a joblib worker pool for every single prediction."""
        for _, step in self.pipeline.steps:
            for member in getattr(step, "estimators_", []) or []:
                if hasattr(member, "n_jobs"):
                    member.n_jobs = 1
            if hasattr(step, "n_jobs"):
                step.n_jobs = 1
        return self

    @classmethod
    def load(cls, path: Path) -> "SeverityClassifier":
        return cls(joblib.load(path))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path, compress=3)

    def predict(self, texts: list[str]) -> list[SeverityPrediction]:
        probabilities = np.asarray(self.pipeline.predict_proba(texts))
        results = []
        for row in probabilities:
            best = int(row.argmax())
            results.append(
                SeverityPrediction(
                    label=self.classes[best],
                    confidence=float(row[best]),
                    probabilities={
                        c: round(float(p), 4) for c, p in zip(self.classes, row, strict=True)
                    },
                )
            )
        return results
