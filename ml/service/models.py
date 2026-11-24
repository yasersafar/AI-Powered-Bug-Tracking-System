"""Loading the trained models for the running system (CPU only, no network: DC-03).

Each model is loaded on its own: a missing or broken artifact only disables the step that
needs it (that step is then reported as `degraded`), never the whole pipeline.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from ml.common.paths import ARTIFACTS
from ml.severity.model import SeverityPrediction

logger = logging.getLogger("ml.service")

EMBEDDING_DIR = "all-MiniLM-L6-v2"
SEVERITY_FILE = "severity/eclipse.joblib"
# CNN-LSTM trained on this system's own resolution history (backend/scripts/train_assignment.py),
# one per database: its classes are user ids of that database, so it can score the developers
# of the running system. The models trained on Eclipse/Mozilla in Stage 4 rank pseudonymised
# Bugzilla developers and are used for the offline evaluation only.
LIVE_ASSIGNMENT_DIR = "assignment/live"


def live_model_dir(artifacts: Path, database: str) -> Path:
    return artifacts / LIVE_ASSIGNMENT_DIR / database


class TextEncoder(Protocol):
    dimension: int

    def encode(self, texts: list[str]) -> NDArray[np.float32]: ...


class SeverityModel(Protocol):
    def predict(self, texts: list[str]) -> list[SeverityPrediction]: ...


class HistoryModel(Protocol):
    developers: list[str]

    def probabilities(self, texts: list[str]) -> NDArray[np.float32]: ...


@dataclass
class TriageModels:
    encoder: TextEncoder | None = None
    severity: SeverityModel | None = None
    history: HistoryModel | None = None
    errors: dict[str, str] = field(default_factory=dict)
    load_seconds: float = 0.0
    # Main weight file of each model (for the `model_state` record: which version is served).
    files: dict[str, Path] = field(default_factory=dict)

    def describe(self) -> dict[str, str]:
        def state(model: object, key: str) -> str:
            return "loaded" if model is not None else self.errors.get(key, "not loaded")

        return {
            "embedding": state(self.encoder, "embedding"),
            "severity": state(self.severity, "severity"),
            "assignment_history": state(self.history, "assignment_history"),
        }


def limit_threads(threads: int) -> None:
    """Keep inference from using every core (heat, and fairness between requests)."""
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, str(threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import torch

    torch.set_num_threads(threads)


def load_models(
    artifacts: Path = ARTIFACTS, threads: int = 2, database: str = "default"
) -> TriageModels:
    started = time.perf_counter()
    models = TriageModels()
    try:
        limit_threads(threads)
    except Exception as exc:  # torch missing: the encoder and history model cannot load either
        logger.warning("could not configure torch threads: %s", exc)

    try:
        from ml.duplicate.embedder import Embedder

        models.encoder = Embedder(artifacts / EMBEDDING_DIR)
        models.files["embedding"] = artifacts / EMBEDDING_DIR / "model.safetensors"
    except Exception as exc:
        models.errors["embedding"] = f"unavailable: {exc}"

    try:
        from ml.severity.model import SeverityClassifier

        path = artifacts / SEVERITY_FILE
        if not path.exists():
            raise FileNotFoundError(f"{path.name} missing; run `make train`")
        models.severity = SeverityClassifier.load(path).single_threaded()
        models.files["severity"] = path
    except Exception as exc:
        models.errors["severity"] = f"unavailable: {exc}"

    live = live_model_dir(artifacts, database)
    if (live / "meta.json").exists():
        try:
            from ml.assignment.cnn_lstm import DeveloperRanker

            models.history = DeveloperRanker.load(live)
            models.files["assignment_history"] = live / "model.pt"
        except Exception as exc:
            models.errors["assignment_history"] = f"unavailable: {exc}"
    else:
        models.errors["assignment_history"] = (
            "no live CNN-LSTM yet (needs resolution history); using history similarity"
        )

    models.load_seconds = round(time.perf_counter() - started, 2)
    for key, value in models.describe().items():
        logger.info("model %s: %s", key, value)
    return models
